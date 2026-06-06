# Credential Injection: gws → gcalcli / goobook

当 gws CLI 因 keyring 问题卡死时，可以解密 gws 的 credentials.enc，将 refresh_token 注入其他工具的认证文件。

## 通用步骤

```python
import base64, json, os, pickle
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

# 1. 解密 gws credentials.enc
key = base64.b64decode(open(os.path.expanduser('~/.config/gws/.encryption_key')).read().strip())
with open(os.path.expanduser('~/.config/gws/credentials.enc'), 'rb') as f:
    data = f.read()
creds_data = json.loads(AESGCM(key).decrypt(data[:12], data[12:], None))
refresh_token = creds_data['refresh_token']

# 2. 读 client_secret.json
with open(os.path.expanduser('~/.config/gws/client_secret.json')) as f:
    cs = json.load(f)
inst = cs.get('installed', cs.get('web', {}))
client_id = inst['client_id']
client_secret = inst['client_secret']

# 3. 构建 Credentials 对象（scope 必须包含在原始 refresh_token 授权范围内）
creds = Credentials(
    token=None,
    refresh_token=refresh_token,
    token_uri='https://oauth2.googleapis.com/token',
    client_id=client_id,
    client_secret=client_secret,
    scopes=['https://www.googleapis.com/auth/calendar']  # 或 contacts 等
)
creds.refresh(Request())
```

## 注入 gcalcli

```python
import pickle
data_dir = os.path.expanduser('~/Library/Application Support/gcalcli')
os.makedirs(data_dir, exist_ok=True)
oauth_path = os.path.join(data_dir, 'oauth')
with open(oauth_path, 'wb') as f:
    pickle.dump(creds, f)
```

gcalcli 存储路径：`~/Library/Application Support/gcalcli/oauth`（pickle 序列化）

## 注入 goobook

```python
auth_dir = os.path.expanduser('~/.local/share/goobook')
os.makedirs(auth_dir, exist_ok=True)
auth_path = os.path.join(auth_dir, 'goobook_auth.json')
with open(auth_path, 'w') as f:
    f.write(creds.to_json())
```

goobook 存储路径：`~/.local/share/goobook/goobook_auth.json`（JSON 格式）

## ⚠️ Scope 限制

refresh_token 只能用于它**最初被授权时包含的 scope**。gws 默认 scope 不包括 contacts：

```
calendar, drive, gmail.modify, presentations, userinfo.email, openid, documents, spreadsheets, tasks
```

如果需要 contacts scope，必须重新走 OAuth 授权流程（因为无法事后追加 scope）。