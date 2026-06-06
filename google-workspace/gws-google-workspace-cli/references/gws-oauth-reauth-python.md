# gws Python OAuth Re-auth（绕过 keyring 卡死问题）

当 gws CLI 卡在 "Using keyring backend" 时，`gws auth login` 也无法正常工作。此时可以用纯 Python 做 OAuth 重认证，完全绕过 gws 及其 keyring 依赖。

## 适用场景

- gws CLI `auth status` / `auth login` 卡在 "Using keyring backend"
- 需要添加新的 OAuth scope（如 contacts）但无法通过 gws 完成
- 已有 client_id / client_secret（可在 `~/.config/gws/client_secret.json` 或 `credentials.enc` 中找到）

## 完整脚本

```python
#!/usr/bin/env python3
"""
Google OAuth flow to add new scopes when gws CLI is stuck on keyring.
Bypasses gws entirely — uses Python's http.server for the OAuth callback.
"""

import json, urllib.request, urllib.parse, base64, socket, http.server, threading, os, sys
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# 从 gws 配置获取（或硬编码）
CLIENT_ID = "your_client_id"
CLIENT_SECRET = "your_client_secret"
REDIRECT_PORT = 56273  # 可自选，不能与已有服务冲突
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}"

# 全部已有 scope + 新 scope（⚠️ 必须包含旧的，否则会丢失原有权限）
SCOPES = " ".join([
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/tasks",
    "https://www.googleapis.com/auth/presentations",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/contacts",      # ← 新 scope
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
])

# 生成 OAuth URL
auth_url = (
    "https://accounts.google.com/o/oauth2/auth?"
    + urllib.parse.urlencode({
        "scope": SCOPES,
        "access_type": "offline",
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "client_id": CLIENT_ID,
        "prompt": "consent",  # 强制重新授权，获取新 refresh_token
    })
)
print(f"AUTH_URL:{auth_url}")
sys.stdout.flush()

# 启动本地 HTTP server 接收回调
auth_code = None
got_code = threading.Event()

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)
        if "code" in params:
            auth_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<html><body><h1>\u5df2\u63a8\u5e7f</h1><p>Authorization succeeded! You can close this window.</p></body></html>")
            got_code.set()
        else:
            error = params.get("error", ["unknown"])[0]
            self.send_response(400)
            self.end_headers()
            self.wfile.write(f"Error: {error}".encode())
            got_code.set()
    def log_message(self, format, *args):
        pass  # 不输出日志

server = http.server.HTTPServer(("127.0.0.1", REDIRECT_PORT), Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()

print(f"WAITING...")
sys.stdout.flush()

if not got_code.wait(timeout=300):
    print("ERROR:Timeout")
    server.shutdown()
    sys.exit(1)
server.shutdown()

# 换 token
token_data = urllib.parse.urlencode({
    "code": auth_code,
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "redirect_uri": REDIRECT_URI,
    "grant_type": "authorization_code",
}).encode()

req = urllib.request.Request(
    "https://oauth2.googleapis.com/token",
    data=token_data,
    headers={"Content-Type": "application/x-www-form-urlencoded"},
)
resp = urllib.request.urlopen(req)
tokens = json.loads(resp.read())
new_refresh = tokens.get("refresh_token", "")

if not new_refresh:
    print("ERROR:No refresh_token in response")
    sys.exit(1)

# 保存新凭据到 credentials.enc
new_creds = {
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "refresh_token": new_refresh,
    "type": "authorized_user",
}

# AES-GCM 加密（密钥从 .encryption_key 读取）
with open(os.path.expanduser("~/.config/gws/.encryption_key")) as f:
    enc_key_b64 = f.read().strip()
key = base64.b64decode(enc_key_b64)
aesgcm = AESGCM(key)
nonce = os.urandom(12)
ct = aesgcm.encrypt(nonce, json.dumps(new_creds).encode(), None)

# 备份旧文件
if os.path.exists(os.path.expanduser("~/.config/gws/credentials.enc")):
    os.rename(
        os.path.expanduser("~/.config/gws/credentials.enc"),
        os.path.expanduser("~/.config/gws/credentials.enc.bak"),
    )

with open(os.path.expanduser("~/.config/gws/credentials.enc"), "wb") as f:
    f.write(nonce + ct)

print("SUCCESS:credentials.enc updated with new scopes")
```

## 注意事项

- **`--prompt=consent`** 是关键 —— 不加的话 Google 可能直接复用已有的 token 而不发新的 refresh_token
- **scope 必须包含所有需要**的 scope（旧的 + 新的），否则新 token 会丢失旧权限
- **`redirect_uri` 是 localhost**，所以用户必须在执行脚本的同一台机器上打开浏览器授权
- 如果端口 56273 被占用，换一个端口（确保与 URL 中的 redirect_uri 一致）
- 脚本会自动备份旧 `credentials.enc` 到 `credentials.enc.bak`
- 依赖：`pip install cryptography`