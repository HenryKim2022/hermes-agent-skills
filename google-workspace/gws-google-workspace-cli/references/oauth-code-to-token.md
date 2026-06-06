# OAuth 授权码 → refresh_token 兑换

当使用 Out-of-Band 方式获得授权码后，用以下方式兑换 refresh_token：

## 命令行

```bash
curl -s -X POST https://oauth2.googleapis.com/token \
  -d "code=AUTH_CODE" \
  -d "client_id=CLIENT_ID" \
  -d "client_secret=CLIENT_SECRET" \
  -d "redirect_uri=urn:ietf:wg:oauth:2.0:oob" \
  -d "grant_type=authorization_code"
```

返回的 JSON 中包含 `refresh_token` 和 `access_token`。

## Python

```python
import urllib.request, urllib.parse, json

data = urllib.parse.urlencode({
    "code": "AUTH_CODE",
    "client_id": "CLIENT_ID",
    "client_secret": "CLIENT_SECRET",
    "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
    "grant_type": "authorization_code"
}).encode()

req = urllib.request.Request(
    "https://oauth2.googleapis.com/token",
    data=data,
    headers={"Content-Type": "application/x-www-form-urlencoded"}
)
result = json.loads(urllib.request.urlopen(req).read())
refresh_token = result.get("refresh_token")

# 保存到 goobook 的 auth 文件
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

creds = Credentials(
    token=result["access_token"],
    refresh_token=result.get("refresh_token"),
    token_uri="https://oauth2.googleapis.com/token",
    client_id="CLIENT_ID",
    client_secret="CLIENT_SECRET",
    scopes=["https://www.googleapis.com/auth/contacts"]
)

auth_path = os.path.expanduser("~/.local/share/goobook/goobook_auth.json")
os.makedirs(os.path.dirname(auth_path), exist_ok=True)
with open(auth_path, "w") as f:
    f.write(creds.to_json())
```

## 注意

- 授权码一次性有效，使用后即失效
- 返回的 refresh_token 在后续使用中如果过期，需要重新授权
- `prompt=consent` 确保每次都返回新的 refresh_token（否则可能不返回）