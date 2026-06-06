# 绕过 gws CLI 直接调 Gmail REST API

## 何时使用

gws CLI 在某些 macOS 系统上可能因 keyring/认证问题无限挂起（`gws auth status` 输出 "Using keyring backend: keyring" 后无响应）。此时可直接解密 gws 凭据调用 Google REST API。

## 凭据解密

gws 在 `~/.config/gws/` 下存储加密凭据：

| 文件 | 说明 |
|------|------|
| `credentials.enc` | AES-GCM 加密的 OAuth 凭据（含 refresh_token） |
| `token_cache.json` | AES-GCM 加密的 access_token 缓存 |
| `.encryption_key` | base64 编码的 32 字节 AES-256 密钥 |
| `client_secret.json` | OAuth 客户端 ID/Secret（明文） |

解密方式（Python + cryptography）：

```python
import json, base64, os, requests
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# 读取密钥
with open(os.path.expanduser('~/.config/gws/.encryption_key')) as f:
    key = base64.b64decode(f.read().strip())

# 解密 credentials.enc（含 refresh_token）
with open(os.path.expanduser('~/.config/gws/credentials.enc'), 'rb') as f:
    data = f.read()
aesgcm = AESGCM(key)
creds = json.loads(aesgcm.decrypt(data[:12], data[12:], None))
# creds = {'client_id': '...', 'client_secret': '...', 'refresh_token': '...', 'type': 'authorized_user'}

# 解密 token_cache.json（含 access_token 缓存，非必需）
with open(os.path.expanduser('~/.config/gws/token_cache.json'), 'rb') as f:
    data = f.read()
aesgcm = AESGCM(key)
tokens = json.loads(aesgcm.decrypt(data[:12], data[12:], None))
# tokens = {'https://mail.google.com/': {'access_token': '...'}, ...}
```

## 刷新 Access Token

credentials.enc 的 refresh_token 可以跨 scope 使用：

```python
resp = requests.post('https://oauth2.googleapis.com/token', data={
    'client_id': creds['client_id'],
    'client_secret': creds['client_secret'],
    'refresh_token': creds['refresh_token'],
    'grant_type': 'refresh_token',
}, timeout=15)
token = resp.json()['access_token']
```

## 并发获取邮件元数据

### 方法 A：ThreadPoolExecutor（20 workers，稳定）

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json'}

def fetch_one(mid):
    r = requests.get(
        f'https://gmail.googleapis.com/gmail/v1/users/me/messages/{mid}',
        params={'format': 'metadata'}, headers=headers, timeout=30
    )
    if r.status_code != 200:
        return {'id': mid, 'error': r.status_code}
    msg = r.json()
    hdrs = {h['name']: h['value'] for h in msg.get('payload', {}).get('headers', [])}
    return {
        'id': mid,
        'from': hdrs.get('From', ''),
        'subject': hdrs.get('Subject', ''),
        'date': hdrs.get('Date', ''),
        'snippet': msg.get('snippet', '')[:120],
    }

with ThreadPoolExecutor(max_workers=20) as ex:
    futs = {ex.submit(fetch_one, mid): mid for mid in all_ids}
    for f in as_completed(futs):
        results.append(f.result())
```

### 方法 B：asyncio + httpx（100 并发，更快但依赖 aiohttp/httpx）

```python
import asyncio, httpx

async def fetch_one(mid, sem):
    async with sem:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.get(
                f'https://gmail.googleapis.com/gmail/v1/users/me/messages/{mid}',
                params={'format': 'metadata'},
                headers={'Authorization': f'Bearer {token}'}
            )
            # ... 解析同上

sem = asyncio.Semaphore(100)
tasks = [fetch_one(mid, sem) for mid in all_ids]
results = await asyncio.gather(*tasks)
```

性能参考：875 封邮件，20 并发 ThreadPoolExecutor 约 4 分钟；100 并发 asyncio 约 2 分钟。

## Gmail API 分页

```python
all_ids = []
page_token = None
while True:
    params = {'q': 'after:2014/1/1 before:2015/1/1', 'maxResults': 500}
    if page_token:
        params['pageToken'] = page_token
    r = requests.get('https://gmail.googleapis.com/gmail/v1/users/me/messages',
        params=params, headers=headers, timeout=60)
    data = r.json()
    msgs = data.get('messages', [])
    all_ids.extend([m['id'] for m in msgs])
    page_token = data.get('nextPageToken')
    if not page_token:
        break
```

⚠️ `resultSizeEstimate` 不可靠，会 cap 在固定值（如 201）。实际数量和分页结果为准。

## 批量打标签（通过 REST API）

```python
def apply_label(msg_ids, label_id):
    batch_size = 50  # ⚠️ 50 封一批，超过可能导致静默失败
    for i in range(0, len(msg_ids), batch_size):
        batch = msg_ids[i:i+batch_size]
        r = requests.post(
            'https://gmail.googleapis.com/gmail/v1/users/me/messages/batchModify',
            headers=headers,
            json={'ids': batch, 'addLabelIds': [label_id]},
            timeout=60
        )
        # HTTP 204 = 成功（No Content，batch 操作的正常响应）
        # HTTP 200 = 普通单操作成功
        if r.status_code in (200, 204):
            success += len(batch)
        time.sleep(0.3)  # 节流
```

## LLM 辅助邮件分类

对于大量旧邮件（如某一年全部邮件），按发件人域名分类效率最高：

```python
DELETE_DOMAINS = {
    'linkedin.com', 'agoda.com', 'meetup.com', 'thsrc.com.tw',
    'booking.com', 'stackinsider.com',  # 社交/旅游/订阅
}
KEEP_DOMAINS = {
    'gohighedu.com', '163.com', 'oneprocloud.com',  # 工作/教育
}

def classify(email):
    domain = extract_domain(email['from'])
    if 'xiaoquqi@gmail.com' in email['from']:
        return 'keep'  # 用户自己发的邮件保留
    if domain in DELETE_DOMAINS:
        return 'delete'
    if domain in KEEP_DOMAINS:
        return 'keep'
    return 'review'  # 未知域名需人工审查
```

先用 domain 批量分类，再对 `review` 类逐封审查。这样 875 封邮件可以几分钟内完成分类。