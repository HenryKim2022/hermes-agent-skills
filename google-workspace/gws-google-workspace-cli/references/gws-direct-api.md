# gws Direct API Fallback

当 gws CLI 超时/卡住时，解密其凭据直接调用 Google REST API。

## 凭据文件结构

| 文件 | 格式 | 内容 |
|------|------|------|
| `~/.config/gws/.encryption_key` | base64 文本 (44 chars) | AES-256-GCM 密钥 (32 bytes) |
| `~/.config/gws/credentials.enc` | AES-GCM 加密 JSON | OAuth2 authorized_user (含 refresh_token) |
| `~/.config/gws/token_cache.json` | AES-GCM 加密 JSON | 各 scope 的 access_token (可能已过期) |

## 完整工作代码

```python
import json, base64, requests, os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# 1. 解密 credentials.enc 获取 refresh_token
key_file = os.path.expanduser('~/.config/gws/.encryption_key')
cred_file = os.path.expanduser('~/.config/gws/credentials.enc')

with open(key_file) as f:
    key = base64.b64decode(f.read().strip())
with open(cred_file, 'rb') as f:
    data = f.read()

aesgcm = AESGCM(key)
plaintext = aesgcm.decrypt(data[:12], data[12:], None)
creds = json.loads(plaintext)
# creds = {"client_id": "...", "client_secret": "...", "refresh_token": "...", "type": "authorized_user"}

# 2. 刷新 access_token
resp = requests.post('https://oauth2.googleapis.com/token', data={
    'client_id': creds['client_id'],
    'client_secret': creds['client_secret'],
    'refresh_token': creds['refresh_token'],
    'grant_type': 'refresh_token',
}, timeout=15)
token = resp.json()['access_token']
headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json'}

# 3. 调用 Gmail API
r = requests.get(
    'https://gmail.googleapis.com/gmail/v1/users/me/messages',
    params={'q': 'before:2013/01/01', 'maxResults': 1},
    headers=headers,
    timeout=20
)
data = r.json()
print(f'Total estimate: {data.get("resultSizeEstimate", 0)}')
```

## 可选：解密 token_cache.json（查看所有 scope 的 token）

```python
with open(os.path.expanduser('~/.config/gws/token_cache.json'), 'rb') as f:
    data = f.read()
aesgcm = AESGCM(key)
tokens = json.loads(aesgcm.decrypt(data[:12], data[12:], None))
for scope, info in tokens.items():
    if info:
        print(f'{scope}: at={str(info.get("access_token",""))[:30]}...')
```

## 注意事项

- `cryptography` 库需要安装：`pip install cryptography`
- `requests` 库需要安装：`pip install requests`
- refresh_token 不会过期，但 access_token 约 1 小时后过期，需要重新刷新
- Gmail API `resultSizeEstimate` 上限为 201，实际邮件数可能更多，需分页获取
- 分页：在 list 请求中加 `pageToken` 参数，从上一页响应的 `nextPageToken` 获取