#!/usr/bin/env python3
"""
从 gws credentials 注入认证到 gcalcli
用法: python3 inject-gws-to-gcalcli.py
"""
import base64, json, os, pathlib, pickle
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

GWS_DIR = pathlib.Path.home() / '.config/gws'
GCALCLI_DIR = pathlib.Path.home() / 'Library/Application Support/gcalcli'

# 1. 解密 credentials.enc
key = base64.b64decode((GWS_DIR / '.encryption_key').read_text().strip())
with open(GWS_DIR / 'credentials.enc', 'rb') as f:
    data = f.read()
creds_data = json.loads(AESGCM(key).decrypt(data[:12], data[12:], None))

# 2. 读 client_secret
cs = json.loads((GWS_DIR / 'client_secret.json').read_text())
inst = cs.get('installed', cs.get('web', {}))
client_id = inst['client_id']
client_secret = inst['client_secret']

# 3. 创建 Credentials
creds = Credentials(
    token=None,
    refresh_token=creds_data['refresh_token'],
    token_uri='https://oauth2.googleapis.com/token',
    client_id=client_id,
    client_secret=client_secret,
    scopes=['https://www.googleapis.com/auth/calendar']
)

# 4. 刷新
creds.refresh(Request())
print(f'✅ Token refreshed, expires: {creds.expiry}')

# 5. 保存
GCALCLI_DIR.mkdir(parents=True, exist_ok=True)
with open(GCALCLI_DIR / 'oauth', 'wb') as f:
    pickle.dump(creds, f)
print(f'✅ Saved to {GCALCLI_DIR / "oauth"}')
print('🎉 现在可以运行: gcalcli agenda')