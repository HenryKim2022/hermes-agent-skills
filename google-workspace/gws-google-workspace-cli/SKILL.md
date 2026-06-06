---
name: gws-google-workspace-cli
description: Google Workspace CLI - 管理 Gmail、日历、Drive、Sheets 等 Google 服务
---

# Google Workspace CLI (gws) 使用指南

## 概述
`gws` 是 Google Workspace CLI，用于管理 Gmail、日历、Drive、Sheets、Docs 等 Google 服务。

## ⚡ 先判断：要不要用替代方案？

**gws CLI 已知问题：** keyring 频繁卡死（`Using keyring backend` 后挂起），`auth login` 也受影响。

**判断原则：** 如果 gws 超时/卡住超过一次——**不要反复重试，直接切换到成熟替代方案**。不要自己写脚本调 API（用户明确说过：**"我要成熟的 CLI 方案，别自己开发"**）。

### 替代方案速查表

| 服务 | 替代工具 | 安装 | 认证方式 |
|------|---------|------|---------|
| 📅 日历 | `gcalcli` | `pip install gcalcli` | 复用 gws refresh_token 注入 pickle |
| 👥 通讯录 | `goobook` | `pip install goobook` | 复用 gws refresh_token 注入 JSON |
| 📧 邮件 | `himalaya` | `brew install himalaya` | Gmail App Password |
| 📁 Drive | 仍用 gws | — | gws 能用时继续用 |

**认证注入原理（见 references/credential-injection.md）：** 解密 gws 的 credentials.enc → 拿到 refresh_token → 用 `google.oauth2.credentials.Credentials` 构造凭据 → 保存到目标工具的认证文件。完全绕过 OAuth 浏览器授权流程。

## 认证 (auth)

```bash
gws auth login                   # 认证（打开浏览器）
gws auth login --readonly        # 只读 scope
gws auth login --full            # 所有 scope（含 pubsub + cloud-platform）
gws auth status                  # 查看当前认证状态
gws auth export                  # 输出解密后的凭据
gws auth logout                  # 清除凭据
```

### 添加 People/Contacts API scope

默认 gws scope 不包括 `contacts`，操作 Google 联系人时需单独授权：

```bash
gws auth login --scopes "https://www.googleapis.com/auth/contacts" --services people
```

会生成浏览器链接让用户授权。**注意：** `--scopes` 会覆盖默认 scope 而非追加。如果同时需要 calendar + contacts，要全写上：

```bash
gws auth login --scopes "https://www.googleapis.com/auth/calendar,https://www.googleapis.com/auth/contacts" --services calendar,people
```

### gcalcli / goobook credentials 复用（绕过 gws 的不稳定问题）

当 gws CLI 不稳定时（keyring 超时），其他成熟 CLI 工具（gcalcli, goobook）可以用更稳定的方式直接复用 gws 的凭据：

**原理：** gws 的 `credentials.enc` 用 AES-GCM 加密了 refresh_token，解密后可直接构造 Google API 的 `Credentials` 对象，注入到其他 CLI 工具。

**快捷注入（gcalcli 专用）：**
```bash
python3 ~/.hermes/skills/google-workspace/gws-google-workspace-cli/scripts/inject-gws-to-gcalcli.py
```

**通用的手动方法（适用于 gcalcli、goobook 等任何支持 Credentials 的工具）：**

```python
import base64, json, os, pickle
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

# 1. 解密 gws 凭据
key = base64.b64decode(open(os.path.expanduser('~/.config/gws/.encryption_key')).read().strip())
with open(os.path.expanduser('~/.config/gws/credentials.enc'), 'rb') as f:
    creds_data = json.loads(AESGCM(key).decrypt(f.read()[:12], f.read()[12:], None))

with open(os.path.expanduser('~/.config/gws/client_secret.json')) as f:
    inst = json.load(f).get('installed', json.load(f).get('web', {}))
    
# 2. 构造 Credentials 对象并刷新
creds = Credentials(
    token=None,
    refresh_token=creds_data['refresh_token'],
    token_uri='https://oauth2.googleapis.com/token',
    client_id=inst['client_id'],
    client_secret=inst['client_secret'],
    scopes=['https://www.googleapis.com/auth/calendar']  # 按工具所需 scope 填写
)
creds.refresh(Request())

# 3. 写入对应工具的缓存
# gcalcli: ~/Library/Application Support/gcalcli/oauth (pickle)
data_dir = os.path.expanduser('~/Library/Application Support/gcalcli')
os.makedirs(data_dir, exist_ok=True)
with open(os.path.join(data_dir, 'oauth'), 'wb') as f:
    pickle.dump(creds, f)

# goobook: ~/.local/share/goobook/goobook_auth.json (JSON)
auth_dir = os.path.expanduser('~/.local/share/goobook')
os.makedirs(auth_dir, exist_ok=True)
with open(os.path.join(auth_dir, 'goobook_auth.json'), 'w') as f:
    f.write(creds.to_json())
```

**注意：** 如果 refresh_token 不含目标 scope（如 contacts），会返回 `invalid_scope`。需要用新的 OAuth 流程获取含 contacts 的新 refresh_token。

**一句话：** 别自己写 Google REST API 封装。用成熟 CLI（gcalcli/goobook/himalaya） + credentials 注入绕过 gws 不稳定问题。

### ⚠️ 大坑：gws 卡 keyring 时 `auth login` 也无法使用

当 gws CLI 在 `auth status` / `auth login` 时卡在 "Using keyring backend"（已知问题），`gws auth login` 也无法正常工作 —— 它同样依赖 keyring 初始化。

**症状：** `gws auth login` 输出 auth URL 后进程挂起，或者根本没有输出就超时。

**解法：用纯 Python 做 OAuth 重认证，完全绕过 gws 及其 keyring 依赖。** 见 `references/gws-oauth-reauth-python.md`。

核心思路：
1. 用已知的 client_id / client_secret 构造手动 OAuth URL（包含全部现有 scope + 新 scope）
2. 本地启动一个 HTTP server 接收回调
3. 拿到 auth code 后换取 refresh_token
4. 用 AES-GCM 加密后写回 `credentials.enc`（在 .encryption_key 密钥不变的前提下）

注意：`--prompt=consent` 会强制用户重新授权并获得新的 refresh_token。新 token 必须包含全部需要的 scope，因为 OAuth 不支持事后追加 scope。

### 解密凭据直接调 REST API（绕过 gws CLI 超时问题）

gws CLI 经常超时/卡住时，可以直接解密 `credentials.enc`（AES-GCM 加密），用 refresh_token 获取 access_token 后调 Google REST API：

1. 读取 `~/.config/gws/.encryption_key`（base64 解码后 32 字节）
2. AES-GCM 解密 `~/.config/gws/credentials.enc`（前 12 字节 = nonce）
3. 用解密出的 refresh_token 换 access_token（标准 OAuth2 refresh）
4. 直接调 REST API

完整代码见 `gmail-analysis` 技能的 `references/gws-direct-api.md`。

## 命令位置
- 二进制：`/usr/local/bin/gws`
- 配置目录：`~/.config/gws/`
- 认证信息：`~/.config/gws/credentials.db`（keyring 管理）
- 加密凭据文件：`credentials.enc` + `.encryption_key`（AES-GCM 加密，可解密直接用于 REST API）

## 常用命令

### Gmail
```bash
gws gmail users messages list --params '{"userId": "me", "maxResults": 3}'
gws gmail users messages get --params '{"userId": "me", "id": "..."}'
```

### Calendar
```bash
gws calendar calendarList list --params '{\"maxResults\": 5}'
gws calendar events list --params '{\"calendarId\": \"primary\", \"maxResults\": 10}'
gws calendar +agenda  # 显示近期所有事件
```

#### 创建日历事件（events insert）

**语法（容易搞错）：**
```bash
gws calendar events insert \
  --params '{"calendarId": "xiaoquqi@gmail.com"}' \
  --json '{
    "summary": "会议标题",
    "location": "地点",
    "description": "描述",
    "start": {"dateTime": "2026-04-29T15:00:00+08:00", "timeZone": "Asia/Shanghai"},
    "end": {"dateTime": "2026-04-29T16:00:00+08:00", "timeZone": "Asia/Shanghai"},
    "reminders": {"useDefault": false, "overrides": [{"method": "popup", "minutes": 15}]}
  }'
```

**要点：**
- `calendarId` 必须放 `--params`，不是 `--calendar_id` flag
- 事件完整 body 放 `--json`，两者缺一不可
- 日期格式：`2026-04-29T15:00:00+08:00`（含时区），不用 Z 表示 UTC
- **先用 `--dry-run** 验证**，避免实际触发安全扫描（URL 含非 ASCII 字符如中文/emoji 会触发 `Non-ASCII URL path` 安全扫描，需用户审批）

**查日历 ID：**
```bash
gws calendar calendarList list | python3 -c "import json,sys; d=json.load(sys.stdin); [print(i['id'], i.get('summary','')) for i in d.get('items',[])]"
```

### Drive
```bash
gws drive files list --params '{"pageSize": 10}'
```

### Sheets
```bash
gws sheets spreadsheets get --params '{"spreadsheetId": "..."}'
```

## 凭据复用：gws → 其他 Google CLI 工具

gws 的 credentials.enc 里存有 refresh_token，可以解密后直接用于其他 Google CLI 工具（gcalcli、goobook 等），完全绕过 OAuth 重新授权流程。

**原理：** AES-GCM 解密 → refresh_token → 用目标 tool 的 scope 构造 Credentials → 写入目标 tool 的认证文件。

**完整代码见 `references/credential-injection.md`。**

**⚠️ scope 限制：** refresh_token 只能用于它**最初被授权时包含的 scope**。gws 默认 scope 无 contacts，如需 contacts 授权必须重新 OAuth。

## 故障排查

**找不到命令？**
用户可能以为命令名是 `gms`，但实际是 `gws`。搜索 `~/.config/` 目录：
```bash
ls ~/.config/ | grep -i google
```
如果看到 `gws` 目录，说明就是 `gws` 命令。

**⚠️ gws CLI 经常超时/卡住（已知问题）**  
gws 有时会无限挂起（即使 `gws auth status` 也只停留在 "Using keyring backend"）。  
遇到超时直接使用直接 API 方式（见 `references/gws-direct-api.md`），不要反复重试 gws。

**认证失败？**
检查 `~/.config/gws/credentials.db` 是否存在，用 `gws auth login` 重新认证。

**gws CLI 一直超时/卡住？**
gws CLI 有时会因 keyring 问题或网络原因卡住（即使 `gws auth status` 也只输出 "Using keyring backend" 后挂起）。此时可以绕过 gws，直接解密其凭据调用 Google REST API：

1. gws 的凭据文件是 AES-GCM 加密的，加密密钥在 `~/.config/gws/.encryption_key`（base64 编码的 32 字节 key）
2. `credentials.enc` 存有 refresh_token（OAuth2 authorized_user 格式）
3. `token_cache.json` 存有各 scope 的 access_token（已过期但可刷新）

**解密 + 刷新 token + 调 API 的完整代码见 `gmail-analysis` 技能的 `references/gws-direct-api.md`**

## 环境变量
- `GOOGLE_WORKSPACE_CLI_CONFIG_DIR` — 覆盖配置目录
- `GOOGLE_WORKSPACE_CLI_LOG` — 日志级别（如 `gws=debug`）

---

## gcalcli — Google Calendar CLI

当 gws 不稳定时，gcalcli 是日历操作的稳健替代方案。

### 安装

```bash
pip install gcalcli
# 或 brew install gcalcli（但 pip 版更新）
```

### 认证（从 gws 注入，推荐）

gcalcli 的 `init` 命令使用 `run_local_server()`，在非交互式终端中会挂起无输出。**推荐用 gws 凭据注入：**

```bash
python3 ~/.hermes/skills/google-workspace/gws-google-workspace-cli/scripts/inject-gws-to-gcalcli.py
```

注意：gws 的 refresh_token 必须包含 `calendar` scope。如果 gws 授权时没指定 calendar，需要重新授权含 calendar scope。

### 常用命令

```bash
gcalcli agenda                              # 查看今日日程
gcalcli agenda "2026-05-27"                 # 查看指定日期
gcalcli calw 2026-05-25 2026-05-31          # 查看某段时间范围
gcalcli calm                                # 查看当月日历
gcalcli quick "明天下午3点 和Ray开会"         # 自然语言快速创建事件
gcalcli list                                # 列出未来事件
gcalcli --help                              # 帮助
gcalcli <command> --help                    # 子命令帮助
```

### 查询范围

- `agenda` 默认显示今日起的日程
- `calw` 显示指定日期所在周
- `calm` 显示当月日历
- `list` 列出未来所有事件

### 数据目录

| 平台 | 路径 |
|------|------|
| macOS | `~/Library/Application Support/gcalcli/` |
| Linux/XDG | `~/.local/share/gcalcli/` |

- OAuth 认证文件: `oauth`（pickle 格式）
- 缓存文件: `cache`

### 配置

gcalcli 使用 toml 配置文件，位于 `~/Library/Application Support/gcalcli/config.toml`，或通过 `GCALCLI_CONFIG` 环境变量指定。

### 已知坑

- `init` 命令的 OAuth 流程在非交互环境会挂起（`run_local_server(open_browser=False)` 导致）
- `--client-id` / `--client-secret` 必须同时提供，缺一不可
- `--noauth_local_server` 主要用于 SSH 远程场景

## goobook — Google Contacts CLI

当 gws 不稳定或需要联系人管理时，goobook 是替代方案。

### 安装

```bash
pip install goobook
```

### 认证

#### 方法一：从 gws 注入（需 contacts scope）

只有当 gws 的 refresh_token 已包含 `contacts` scope 时才能直接注入：

```python
import base64, json, os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

key = base64.b64decode(open(os.path.expanduser('~/.config/gws/.encryption_key')).read().strip())
with open(os.path.expanduser('~/.config/gws/credentials.enc'), 'rb') as f:
    data = f.read()
creds_data = json.loads(AESGCM(key).decrypt(data[:12], data[12:], None))

with open(os.path.expanduser('~/.config/gws/client_secret.json')) as f:
    cs = json.load(f)
inst = cs.get('installed', cs.get('web', {}))
client_id = inst['client_id']
client_secret = inst['client_secret']

creds = Credentials(
    token=None,
    refresh_token=creds_data['refresh_token'],
    token_uri='https://oauth2.googleapis.com/token',
    client_id=client_id,
    client_secret=client_secret,
    scopes=['https://www.googleapis.com/auth/contacts']
)
creds.refresh(Request())

auth_path = os.path.expanduser('~/.local/share/goobook/goobook_auth.json')
os.makedirs(os.path.dirname(auth_path), exist_ok=True)
with open(auth_path, 'w') as f:
    f.write(creds.to_json())
```

#### 方法二：OOB 授权（contacts scope 缺失时）

如果 gws refresh_token 不含 contacts scope，需手动 OAuth 授权（见 `references/oauth-code-to-token.md`）。

### 常用命令

```bash
goobook dump_contacts              # 列出所有联系人
goobook query "张三"               # 搜索联系人
goobook dquery "zhang"             # 详细搜索（支持正则）
goobook add --name "李四" --email "lisi@example.com" --phone "13800138000"
goobook reload                     # 重新加载缓存
```

### 配置文件

默认 `~/.goobookrc`：

```ini
[DEFAULT]
cache_filename: ~/.goobook_cache
cache_expiry_hours: 24
filter_groupless_contacts: yes
```

### 数据目录

- Auth 文件: `~/.local/share/goobook/goobook_auth.json`（JSON 格式，非 pickle）
- 缓存: `~/.cache/goobook/`

### 已知坑

- contacts scope 需要单独授权，gws 默认 scope **不包含** contacts
- `authenticate` 命令使用 `run_local_server()`，非交互终端会挂起
- 新增联系人必须指定 `--name`（否则报错）
