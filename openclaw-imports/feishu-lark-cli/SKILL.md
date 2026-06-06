---
name: feishu-lark-cli
description: 飞书/Feishu Lark CLI (lark-cli) 安装、认证、基本操作
category: openclaw-imports
---

# Feishu / Lark CLI (lark-cli) 使用指南

## 概述

`lark-cli` 是飞书/Lark 的官方 CLI 工具，用于管理日历、通讯录、消息、文档等。

## 安装

```bash
npx @larksuite/cli@latest install
```

全局安装后命令为 `lark-cli`，位于 `/usr/local/bin/lark-cli`。

## ⚠️ 大坑：`env -i` + pipe 组合会炸

`env -i` 清空了几乎所有环境变量（包括 `PATH` 中 conda/python 路径），导致 **pipe 到 python3 等解释器时加载不到正确的 Python**，出现 `JSONDecodeError: Expecting value: line 1 column 1`。

**症状：** lark-cli 输出正常（JSON），但 pipe 后的 python3 脚本报错。

**解法：** 不要 pipe。要么：
- 用 `--jq` 过滤（lark-cli 内置支持）
- 把输出写到临时文件再读：`... > /tmp/out.json && python3 -c "..." < /tmp/out.json`
- 或者两段式：先跑 lark-cli，再在独立代码块里处理

示例：
```bash
# ❌ 会炸
env -i HOME="$HOME" PATH="/usr/local/bin:/usr/bin:/bin" lark-cli ... | python3 -c "..."

# ✅ 安全写法
env -i HOME="$HOME" PATH="/usr/local/bin:/usr/bin:/bin" lark-cli ... > /tmp/out.json
python3 -c "import json; d=json.load(open('/tmp/out.json')); ..."
```

## 关键坑：Hermes 上下文检测（⚠️ 高频踩坑点）

`lark-cli` 会检测环境变量中的 `_HERMES_GATEWAY=1` 等 Hermes 信号。如果检测到 Hermes 上下文但未执行过 `config bind`，**所有命令都会拒绝执行**，返回：

```
hermes context detected but lark-cli is not bound to it
```

### 场景 A：用户已自行配置 App（推荐给懂的用户）

用户可能已通过 `lark-cli config init` 或手动配置好了 App 凭据（在 `~/.lark-cli/config.json` 中），此时不需要走 `config bind` 流程。直接用 **`env -i` 剥离 Hermes 环境变量** 来绕过检测：

```bash
env -i HOME="$HOME" PATH="/usr/local/bin:/usr/bin:/bin" lark-cli auth status
```

⚠️ 注意：`env -i` 会清空所有环境变量，因此：
- **`PWD` 缺失**可能导致路径相关命令出错。`qrcode --output` 只接受相对路径（拒绝绝对路径），需要额外传入 `PWD`：
  ```bash
  env -i HOME="$HOME" PATH="/usr/local/bin:/usr/bin:/bin" PWD="/tmp" \
    lark-cli auth qrcode --output ./lark-login.png "<verification_url>"
  ```
- `HOME` 必须保留（找配置文件），`PATH` 必须包含 `lark-cli` 所在目录

### 场景 B：标准绑定流程（需用户确认）

需要用户先配置好 Feishu App 凭据（App ID + App Secret），然后：

⚠️ **必须让用户确认后才能执行。**

```bash
# 1. 写入 .env
echo "FEISHU_APP_ID=your_app_id" >> ~/.hermes/.env
echo "FEISHU_APP_SECRET=your_app_secret" >> ~/.hermes/.env

# 2. 绑定，询问用户选择身份：
# --identity bot-only      仅机器人身份（安全默认，不能访问个人资源）
# --identity user-default  用户身份（可访问个人日历/邮件/云盘等）
lark-cli config bind --source hermes --identity user-default   # 或 bot-only
```

### 设备流授权（无论场景 A/B 都执行）

用非阻塞方式（分两轮），适用于 AI agent 场景：

**第一轮：获取设备码 + 生成二维码**

```bash
# 获取设备码（必须指定 --domain/--recommend/--scope，否则报错）
env -i HOME="$HOME" PATH="/usr/local/bin:/usr/bin:/bin" \
  lark-cli auth login --no-wait --json --domain calendar

# 生成 PNG 二维码（--output 只接受相对路径，不能是绝对路径！）
env -i HOME="$HOME" PATH="/usr/local/bin:/usr/bin:/bin" PWD="/tmp" \
  lark-cli auth qrcode --output ./lark-login.png "<verification_url>"
```

### 通讯录

```bash
lark-cli contact +search-user --query "John"           # 搜索用户
lark-cli contact users get --params '{"user_id":"...","user_id_type":"open_id"}'
```

#### 枚举所有有企业邮箱的联系人（无需全量通讯录权限）

如果 App 没有 `contact:contact.base:readonly` 权限（无法调用 `+list`），可以用 `--has-enterprise-email` 过滤器枚举所有有企业邮箱的用户，无需关键字：

```bash
env -i HOME="$HOME" PATH="/usr/local/bin:/usr/bin:/bin" \
  lark-cli contact +search-user --as user --has-enterprise-email --page-size 30 --format pretty
```

**效果：** 一次性列出所有有企业邮箱的在职员工（包括部门、邮箱、open_id），比逐字搜索高效得多。适用场景：通讯录同步、全员消息群发等。

也可以组合多个过滤条件：
```bash
# 仅曾聊过的企业联系人
lark-cli contact +search-user --as user --has-enterprise-email --has-chatted
# 排除外部用户
lark-cli contact +search-user --as user --has-enterprise-email --exclude-external-users
```

**注意：** `+search-user` 返回字段中用户姓名字段是 `localized_name` 而非 `name`。

如果需要增加新权限（如已有 `calendar` 想加 `contact`），**重复设备流授权即可**，但必须指定新的 domain 组合：

```bash
# 假设已有 calendar 权限，现在追加 contact
env -i HOME="$HOME" PATH="/usr/local/bin:/usr/bin:/bin" \
  lark-cli auth login --no-wait --json --domain "calendar,contact"

# → 生成新二维码 → 用户扫码 → 完成
# 新 token 会合并新旧 scope，不会丢失原有权限
```

⚠️ **注意：** 用户扫码后原 token 会立即失效，新 token 包含所有 scope。确保你的 device code 没过期（10分钟内）。

### `--domain` 可选值

`auth login --no-wait` 必须指定 scope，推荐用 `--domain` 或 `--recommend`：

- `--domain calendar` — 仅日历（最常用）
- `--domain all` — 全部权限
- `--recommend` — 仅推荐范围（自动审批，无需管理员审核）
- `--domain im,calendar,drive` — 多域用逗号分隔

## 配置位置

| 内容 | 路径 |
|------|------|
| 主配置文件 | `~/.lark-cli/config.json` |
| 加密 App Secret | `~/Library/Application Support/lark-cli/appsecret_*.enc`（macOS） |
| 加密密钥 | `~/Library/Application Support/lark-cli/master.key.file`（macOS） |
| 日志/缓存 | `~/.lark-cli/cache/` |

## 常用命令

### 日历

#### ⚠️ 日历平台判断：默认走飞书，不是 Google！

Ray 同时用飞书和 Google 日历。**当用户说"我的会议"、"日程"、"日历"时，默认查飞书日历，不要先查 Google Calendar。** 判断依据：
- 中文会议标题 + 中文团队参会 → 飞书日历
- 用户说"我的会议" ≠ Google Calendar
- 只有明确提到 Google/Gmail 或使用英文会议标题时才查 Google

#### 查看日程

```bash
lark-cli calendar +agenda                              # 查看近期日程（今日起）
lark-cli calendar +agenda --date "2026-05-26"          # 指定日期（注意：输出为 JSON 而非纯文本，勿 pipe）
# 或用原始 API（支持时间戳参数）：
lark-cli calendar events instance_view --params '{"calendar_id":"primary","start_time":"1700000000","end_time":"1700086400"}'
```

**注意：** `+agenda` 的输出格式取决于 `--format` flag，默认 json。如需纯文本友好展示可加 `--format pretty`。

#### 创建事件（+create）

```bash
env -i HOME="$HOME" PATH="/usr/local/bin:/usr/bin:/bin" \
  lark-cli calendar +create \
    --summary "会议标题" \
    --description "描述说明" \
    --start "2026-06-02T10:00:00+03:00" \
    --end "2026-06-02T12:00:00+03:00" \
    --attendee-ids "ou_xxx,ou_yyy,ou_zzz" \
    --as user
```

参数说明：
- `--summary` — 事件标题
- `--description` — 描述（可选）
- `--start` / `--end` — ISO 8601 格式，含时区偏移（如 `+03:00`、`+08:00`）
- `--attendee-ids` — 参与人 open_id，逗号分隔（支持 user ou_、群 oc_、会议室 omm_）
- `--calendar-id` — 日历 ID，默认 primary
- `--as user` — 以用户身份创建（否则可能以 bot 身份）
- `--dry-run` — 先验证不实际执行
- 创建成功后时间会自动转为日历所有者的时区显示

### 📌 邀请参会者前的搜人策略（⚠️ 高频踩坑）

创建跨团队/全公司会议时，**千万不要只用 `--has-enterprise-email` 搜人**。这会漏掉两类人：
- **关联组织（跨租户/cross_tenant）成员** — 他们没有企业邮箱
- **本企业无企业邮箱的成员** — 部门信息可能为空

**正确的多轮搜索策略（必须组合使用）：**

```bash
# 1️⃣ 第一轮：搜本企业有邮箱人员（企业邮箱+部门信息）
env -i HOME="$HOME" PATH="/usr/local/bin:/usr/bin:/bin" \
  lark-cli contact +search-user --as user --has-enterprise-email --page-size 30

# 2️⃣ 第二轮：按关联组织名称搜跨租户成员
#    例如 "万云博华"、"万博智云"、"武汉" 等
env -i HOME="$HOME" PATH="/usr/local/bin:/usr/bin:/bin" \
  lark-cli contact +search-user --query "万云博华" --as user --page-size 30

# 3️⃣ 第三轮：按部门/团队关键词搜（会找到无企业邮箱但也有关联的成员）
#    使用 "研发"、"技术服务"、"北京"、"武汉" 等关键词
env -i HOME="$HOME" PATH="/usr/local/bin:/usr/bin:/bin" \
  lark-cli contact +search-user --query "研发" --as user --page-size 30

# 4️⃣ 第四轮（可选）：搜所有聊过的联系人（补漏）
env -i HOME="$HOME" PATH="/usr/local/bin:/usr/bin:/bin" \
  lark-cli contact +search-user --as user --has-chatted --page-size 30
```

**关键原则：**
- 不同搜索词的返回结果**互相补充**，一个词只返回部分结果
- 对所有结果**手动去重**后汇总 open_id 列表
- `has_more: true` 说明还有未返回的用户，加 `--page-size 30` 再翻页（`+search-user` 不支持翻页参数，可以换个关键词缩小范围）
- 跨租户用户的 `is_cross_tenant: true`，可以据此识别
- 关联组织（跨租户）成员**能被正常邀请**参加飞书会议，和本企业用户一样用 open_id

**典型应用场景对照表：**
| 场景 | 搜索策略 |
|------|---------|
| 全员通知 | `--has-enterprise-email` + 逐组织名搜索 |
| 全体研发 | `--query "研发"` |
| 北京+武汉全员 | `--query "北京"` + `--query "武汉"` + 各组织名 |
| 技术服务部 | `--query "技术服务"` |
| 关联组织 | `--query "万云博华"`、`--query "万博智云"` 等组织全称/简称 |

**已知坑：** `+search-user` 无法通过 `is_cross_tenant` 参数筛选。要找到所有关联组织成员，只能用组织名称逐个搜索。

**⚠️ 武汉关联组织只有2人：** 万博智云软件科技（武汉）有限公司的 cross-tenant 成员仅 王炜、李细鹏 2人。用户可能预期更多，不要反复搜索浪费时间。本企业的武汉研发部成员（Bruce Lee、黄迎兵、Wang Wei、Wang Qi）在 `--has-enterprise-email` 中已包含。

#### 更新事件（+update）

```bash
env -i HOME="$HOME" PATH="/usr/local/bin:/usr/bin:/bin" \
  lark-cli calendar +update \
    --event-id "<event_id>" \
    --summary "新标题" \
    --add-attendee-ids "ou_xxx"
```

### 通讯录

```bash
lark-cli contact +search-user --query "John"           # 搜索用户
lark-cli contact users get --params '{"user_id":"...","user_id_type":"open_id"}'
```

#### 枚举所有有企业邮箱的联系人（无需全量通讯录权限）

如果 App 没有 `contact:contact.base:readonly` 权限（无法调用 `+list`），可以用 `--has-enterprise-email` 过滤器枚举所有有企业邮箱的用户，无需关键字：

```bash
env -i HOME="$HOME" PATH="/usr/local/bin:/usr/bin:/bin" \
  lark-cli contact +search-user --as user --has-enterprise-email --page-size 30 --format pretty
```

**效果：** 一次性列出所有有企业邮箱的在职员工（包括部门、邮箱、open_id），比逐字搜索高效得多。适用场景：通讯录同步、全员消息群发等。

也可以组合多个过滤条件：
```bash
# 仅曾聊过的企业联系人
lark-cli contact +search-user --as user --has-enterprise-email --has-chatted
# 排除外部用户
lark-cli contact +search-user --as user --has-enterprise-email --exclude-external-users
```

**注意：** `+search-user` 返回字段中用户姓名字段是 `localized_name` 而非 `name`。
```json
{"localized_name": "Bruce Lee", "open_id": "ou_xxx", "email": "...", "department": "武汉研发部"}
```
- `open_id` — 用户唯一标识（用于邀请参会等）
- `email` — 邮箱
- `department` — 部门
- `p2p_chat_id` — 单聊会话 ID

### 消息
```bash
lark-cli im messages create --data '{"receive_id":"...","msg_type":"text","content":"..."}'
```

### 通用 API 调用
```bash
lark-cli api GET /open-apis/calendar/v4/calendars
lark-cli api POST /open-apis/im/v1/messages --data '{"receive_id":"...","msg_type":"text","content":"{\"text\":\"hello\"}"}'
```

### 输出格式
```bash
lark-cli ... --format json      # 默认
lark-cli ... --format table     # 表格
lark-cli ... --format pretty    # 友好格式
lark-cli ... --jq '.data.items[0]'  # jq 过滤
```

## 验证状态
```bash
lark-cli doctor          # 整体健康检查
lark-cli auth status     # 查看当前认证状态
lark-cli auth check --scope <scope>  # 检查 scope
```

## 注意事项
- 更新 CLI：`lark-cli update`
- 切换配置 profile：`lark-cli --profile <name>`
- 退出登录：`lark-cli auth logout`
- skills 安装步骤可能超时（不影响核心 CLI 使用）

## 参考
- 官方仓库：https://github.com/larksuite/cli
- API 文档：https://open.feishu.cn/document/
- 完整认证+建事件流程示例：参考 `references/auth-flow-example.md`
- 跨组织参会者搜索实战（研发+关联组织）：参考 `references/attendee-search-across-orgs.md`