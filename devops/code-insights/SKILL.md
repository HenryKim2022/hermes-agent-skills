---
name: code-insights
description: GitLab 代码提交采集与分析（API-only 模式）—— 通过 GitLab REST API 采集 commit + diff，不走 SSH clone
---

# code-insights

GitLab 代码提交采集工具。**通过 GitLab REST API 采集 commit + diff**（不走 SSH clone），patch 直接从 API 响应拼装，按天存储。

## 两种运行模式

| 模式 | 数据来源 | 速度 | 网络依赖 |
|------|----------|------|----------|
| **API-only（默认）** | GitLab REST API | 快（无 clone） | 仅需 20080 |
| SSH clone（旧） | `git clone` 本地提取 | 慢（首次 clone 耗时长） | 需要 20022 SSH |

**推荐 API-only 模式**。collector.py 已默认使用 API 获取 patch，不再依赖 SSH clone。

### 目录结构

| 项目类型 | 分支 | 说明 |
|----------|------|------|
| `atomy/*` | `qa` | atomy 模块固定用 qa 分支 |
| `hypermotion/*` | `saas_qa` | 大部分项目的默认分支 |
| `hypermotion/CI-CD` | `master` | CI-CD 固定用 master |

## 目录结构

```
~/.hermes/code-insights/
├── commits/{date}/{group}/{project}/    ← 原始 patch（采集阶段）
│   ├── commits.json
│   └── {commit_id}.patch
└── reports/                              ← 报告输出（报告阶段）
    └── daily/{date}/{group}/{project}/
        ├── {commit_id}.summary.md        ← 产品视角：改动 + 风险
        └── {commit_id}.detailed.md      ← 代码质量视角：质量 + 效率
```

## 采集流程（API-only 模式）

1. OAuth token 获取（密码模式，`get_token()`）
2. 遍历 `projects.yaml` 中的项目列表
3. 根据 `resolve_branch()` 确定分支：atomy → qa, CI-CD → master, 其他 → saas_qa
4. 调用 GitLab Projects API 搜索项目获取 `project_id`（只搜索项目名，不 URL-encode 斜杠）
5. 调用 GitLab Commits API：`?ref_name={branch}&since=&until=`（只拉指定分支，不过 all=true）
6. 过滤无效 commit（author 为 gitlab/bot/system/空的自动化提交）
7. **通过 Diff API** 获取每个 commit 的 patch 内容，直接写文件（不走 git clone）
8. 保存 commit 元数据到 `commits.json`

## 报告阶段

每个 commit 单独生成两个报告：

| 报告 | 视角 | 内容 |
|------|------|------|
| `*.summary.md` | 产品视角 | 改动描述 + 风险/爆炸半径评估 |
| `*.detailed.md` | 代码质量视角 | 质量评分 + 效率评估（AI 加持背景） |

### Summary 报告内容

```
### 1. 产品改动
- 一句话描述（面向产品/管理层）
- 改了什么模块/功能

### 2. 风险评估（爆炸半径）
- 影响范围：小 / 中 / 大
- 理由（改了哪些模块、是否涉及核心业务、是否有回滚难度）
- 建议（如果有）
```

### Detailed 报告内容（百分制，2026-05-08 更新）

**核心原则**：不说废话，不写"阶段/评估/说明"等报告腔。理由要有逻辑，直接说问题，不美化缺陷。

```
### 1. 代码质量评分

| 维度 | 评分 | 说明 |
|------|------|------|
| 代码规范 | /100 | |
| Commit 规范 | /100 | ⚠️ 标题与实际内容不符 → 低分 |
| 可维护性 | /100 | |
| 安全性 | /100 | |
| 测试覆盖 | /100 | |
| **综合** | **/100** | |

### 2. 理由总结

**功能意图：**（一句话说清楚这个提交想解决什么问题）

**做得好的：**（列出2-3点真正值得肯定的，最多3条）

**主要隐患（5点）：**（分条列出，精确到代码位置引用）
1.
2.
3.
4.
5.

### 3. 效率评估
- 代码行数：+X/-Y
- 提交粒度：（合理/过粗/过细）及理由
- 理论开发周期：（短/中/长）+ 理由
```

**扣分原则**：
- Commit 标题与实际内容不符（标题说A实际是B）：40分以下
- 无测试覆盖：60分以下
- 静默失败风险（错误仅warning不阻止）：70分以下
- 前置条件不透明（删注释/配置无说明）：70分以下

## 使用方式

### 采集阶段

```bash
# 采集指定日期
python3 ~/.hermes/skills/devops/code-insights/scripts/collector.py 2026-04-30

# 采集今日
python3 ~/.hermes/skills/devops/code-insights/scripts/collector.py today
```

### 报告阶段

```bash
# 生成指定日期的报告
python3 ~/.hermes/skills/devops/code-insights/scripts/reporter.py 2026-04-30

# 生成今日报告
python3 ~/.hermes/skills/devops/code-insights/scripts/reporter.py today
```

## 输出

- `commits/{date}/{group}/{project}/commits.json` — commit 元数据
- `commits/{date}/{group}/{project}/{commit_id}.patch` — 每个 commit 的完整 diff
- `reports/daily/{date}/{group}/{project}/{sha}.summary.md` — 产品视角报告
- `reports/daily/{date}/{group}/{project}/{sha}.detailed.md` — 代码质量报告

## 核心设计

### GitLab 认证

使用 `oauth/token`（密码模式）：
```
POST http://192.168.10.254:20080/oauth/token
{"grant_type": "password", "username": "devops", "password": "devops@HyperMotion"}
```

### 项目列表

**`projects.yaml`** 是项目列表的权威来源（不是 collector.py 硬编码）。格式：
```yaml
groups:
  hypermotion:        # ← 这个 key 决定 commits 目录的 group 子目录名
    - hypermotion/nezha
    - hypermotion/mass
  atomy:              # ← atomy/ 项目放这里，确保分支规则正确匹配
    - atomy/hamalv3
  income:
    - hypermotion/income
```

> ⚠️ **路径约定**：YAML 的分组 key（如 `atomy`）会直接作为 `commits/{date}/{group}/{project}/` 的路径前缀。应使用 GitLab namespace 作为分组 key，保持一致。

> ⚠️ **分组 key 决定存储路径**：YAML 分组 key（不是 GitLab namespace）决定 commits 目录结构！
> - `hypermotion:` 组里写 `- atomy/hamalv3` → 数据存到 `commits/hypermotion/hamalv3/`（group=hypermotion, project=hamalv3）
> - `atomy:` 组里写 `- atomy/hamalv3` → 数据存到 `commits/atomy/hamalv3/`
> - **每个项目必须在自己对应的 namespace 分组下**（`atomy/hamalv3` 放在 `atomy:` 组），否则 reporter 找不到数据

> ⚠️ **重复检查**：同一项目不要出现在多个分组里。

> ⚠️ **hamalv3 vs hamal**：GitLab 上 `atomy/hamalv3` 是目前正在使用的，`hypermotion/hamal` 已废弃。两者不要混淆。

按需增删项目，范围由 Ray 确认后扩展。

### Commits API

```
GET /projects/{id}/repository/commits?ref_name={branch}&since={after}&until={date}%2023:59:59
```
- `ref_name`：指定分支，不过 all=true（避免引入其他分支噪音）
- `since/until`：日期范围筛选

### Clone URL 重写

> **collector 用 API-only，已废弃 clone**：collector.py 不再使用 SSH clone，patch 直接从 Diff API 获取。此节仅供 reporter 调试参考。

reporter 用的 persistent clone 使用 SSH 协议。项目原始 URL 为 `ssh://git@office.oneprocloud.com.cn:20022/{path}.git`（DNS 解析不了），重写为 `ssh://devops:devops%40HyperMotion@192.168.10.254:20022/{path}.git`。

**注意**：reporter SSH clone 用端口 **20022**（不是 20080）。clone URL 格式：`ssh://git@office.oneprocloud.com.cn:20022/{path_with_namespace}.git`。

Bare clone 存储位置：`~/.hermes/code-insights/repos/{group}/{project}/`（每个项目只 clone 一次，复用）。

### Shallow Clone

- `--depth=100` 限制历史
- `--branch {branch}` 指定分支
- `--single-branch` 只拉单个分支
- clone 到 `/tmp/code-insights-{date}-{project}/`

### Git 命令

```bash
# 获取单个 commit 的 patch（完整 diff）
git show {commit_id} --format= --patch > {commit_id}.patch
```

### 过滤规则

跳过：
- author 为 `gitlab/bot/system/空` 的自动化提交
- message 以 `Merge branch` 开头的 merge commit

## 已知坑（调试记录）

### `commits.json` 是 dict 结构，不是 list
```python
# ❌ 错误：直接遍历 dict
for commit in commits_data:
    sha = commit["sha"]

# ✅ 正确：取 commits 字段
commits_list = commits_data.get("commits", [])
for commit in commits_list:
    sha = commit["sha"]
```
完整结构：
```json
{
  "date": "2026-04-30",
  "group": "hypermotion",
  "project": "nezha",
  "branch": "saas_qa",
  "commits": [...]
}
```

### commits.json 的字段名（与 GitLab API 不同）
```python
# ✅ collector 保存的字段
commit["sha"]       # 不是 "id"
commit["author"]    # 不是 "author_name"
commit["date"]      # 不是 "committed_date"
commit["message"]   # 就是这个
```

### `resolve_branch()` 入参是 `path_with_namespace`，不是 `project`
```python
# ❌ 错误：用 project 字段匹配，atomy/hamalv3 会匹配失败（因为 "hamalv3" 不含 "atomy"）
branch = resolve_branch(project)

# ✅ 正确：用完整 path_with_namespace 匹配
branch = resolve_branch("atomy/hamalv3")  # → "qa"
branch = resolve_branch("hypermotion/nezha")  # → "saas_qa"
```
```bash
# ❌ 错误：git 把 "patch" 当文件路径，只输出那个文件的 diff（不存在就为空）
git show {sha} --format= -- patch

# ✅ 正确：用 --patch 标志，不过滤文件
git show {sha} --format= --patch
```

### 项目搜索 API 不接受 URL-encoded 斜杠
```python
# ❌ 错误：urllib.parse.quote('hypermotion/nezha') → 'hypermotion%2Fnezha'，搜不到
api(f'/projects?search={urllib.parse.quote(project_path)}')

# ✅ 正确：只搜索项目名（路径最后一段），然后用完整 path_with_namespace 匹配
proj_name = project_path.rsplit('/', 1)[-1]  # → "nezha"
result = api(f'/projects?search={proj_name}&per_page=50')
for p in result:
    if p['path_with_namespace'] == project_path:
        return p
```

### ref_name 不要加 `origin/` 前缀
```python
# ❌ 错误：ref_name=origin/saas_qa 返回 0 结果
# ✅ 正确：ref_name=saas_qa
GET /projects/{id}/repository/commits?ref_name=saas_qa&since=&until=
```

### `all=true` 会拉所有分支，引入噪音
```python
# ❌ 错误：all=true 会拉所有分支的 commits，包括不在 default branch 上的 feature 分支
GET /projects/{id}/repository/commits?all=true&since=&until=

# ✅ 正确：配合 ref_name 只拉指定分支
GET /projects/{id}/repository/commits?ref_name=saas_qa&since=&until=
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `GITLAB_URL` | `http://192.168.10.254:20080` | GitLab 地址（API 用 HTTP） |
| `GITLAB_USER` | `devops` | 用户名 |
| `GITLAB_PASS` | `devops@HyperMotion` | 密码 |

### 运行 reporter 时需要传入 token

```bash
# reporter.py 需要 GitLab token，但 ~/.hermes/.gitlab_token 文件可能为空
# 正确方式：运行时从 OAuth API 动态获取
GL_TOKEN=$(curl -s -X POST http://192.168.10.254:20080/oauth/token \
  -H "Content-Type: application/json" \
  -d '{"grant_type":"password","username":"devops","password":"devops@HyperMotion"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

GIT_TOKEN="$GL_TOKEN" python3 reporter.py 2026-04-30
```

## 依赖

- `git`：系统命令

## 报告阶段（Claude Code CLI）

reporter.py 使用 Claude Code CLI 进行代码审查（而非 LLM API 调用）：

```python
subprocess.run([
    "claude", "-p", "--output-format", "text",
    "--no-session-persistence", "--dangerously-skip-permissions", prompt
], ...)
```

Claude Code 直接读取本地代码仓库（通过 `clone_and_prepare_repo` 切到指定 SHA 的 detached HEAD），可以引用本地文件进行更精准的分析。



### 验证方式

**先跑单个 commit 验证 prompt 效果，再跑全量：**

```bash
# 全量跑
python reporter.py 2026-04-30

# 先测单个 commit：用 execute_code 或直接写 test 脚本调 process_commit()
```
- 注意：reporter.py 依赖 SSH clone 仓库，如果 VPN 路由有问题会导致 clone 超时
- 可以用 API-only 模式获取 patch 验证新 prompt 格式（不需要 clone）

## 报告阶段已知坑

### patch 过长时自动分块
`split_patch()` 会按文件拆分 patch，超大文件按 `@@` hunk 段落二次拆分，每个 chunk 单独调用 Claude Code，结果用 `---` 分隔拼接。

### patch 截断保留上下文
`_split_by_hunes()` 对超大段落截断时保留头尾各 1/3，确保关键逻辑不丢失。

### clone 复用
`clone_and_prepare_repo()` 只在项目级别执行一次（不是每个 commit 重新 clone），后续 commit 只需 `git checkout` 到对应 SHA。

## 报告阶段已知坑

### patch 过长时自动分块
`split_patch()` 会按文件拆分 patch，超大文件按 `@@` hunk 段落二次拆分，每个 chunk 单独调用 Claude Code，结果用 `---` 分隔拼接。

### patch 截断保留上下文
`_split_by_hunes()` 对超大段落截断时保留头尾各 1/3，确保关键逻辑不丢失。

### `git fetch` 超时（reporter）
reporter 在已有 persistent clone 上执行 `git fetch`（等待 60s 超时），当网络不可达时会等满 60s。一个项目会重试 6 次（retry 次数）。虽然最终会跳过，但会拖慢整体速度（约 7 分钟/项目）。这是已知的非致命问题，不影响报告质量。

### reporter 调试：stdout 缓冲
reporter 作为后台进程运行时，Python stdout 会被缓冲，实时进度看不到。调试时加 `-u` 参数：
```bash
# ❌ 普通后台运行看不到输出
python3 reporter.py 2026-04-30

# ✅ 加 -u 实时看进度
PYTHONUNBUFFERED=1 python3 -u reporter.py 2026-04-30
```

### projects.yaml 分组 key 与存储路径的对应关系
collector.py 中 commit 数据写入路径：
```python
group = projects_yaml_group  # YAML 中的分组 key（不是 GitLab namespace）
project = project_name       # YAML 中写的路径最后一段
# → commits/{date}/{group}/{project}/
```
- YAML 写 `- atomy/hamalv3` 且分组 key=atomy → `commits/{date}/atomy/hamalv3/`
- YAML 写 `- atomy/hamalv3` 且分组 key=hypermotion → `commits/{date}/hypermotion/hamalv3/`

reporter 的 `clone_and_prepare_repo()` 用 `path_with_namespace` 查 PROJECTS 找分支，路径解析是独立的。所以 collector 和 reporter 都依赖 YAML 中 project_path（完整 path_with_namespace）匹配 PROJECTS 的 key。

### 确认 `pathy_with_namespace` 正确
collector 输出的 `commits.json` 中每个 commit 记录 `project_path`（来自 `path_with_namespace`），reporter 据此找 PROJECTS 条目。确保 YAML 中的 project_path 与 GitLab 实际 path_with_namespace 完全一致（包括大小写）。

## 调试记录（2026-05-07）

### collector 从 SSH clone 改为 API-only
collector.py 重写，不再通过 SSH clone 项目。patch 改为直接调用 GitLab Diff API 获取：
```
GET /projects/{id}/repository/commits/{sha}/diff
```
Diff API 返回的文件结构与 patch 格式一致，直接拼接即可生成 .patch 文件。

### projects.yaml 路径约定发现
reporter 读取 `commits/{date}/{group}/{project}/` 路径，其中 `{group}` 来自 YAML 的分组 key，**不是** GitLab namespace。这意味着如果 YAML 分组用 `HyperBDR`，但 collector 实际输出到 `hypermotion/`（因为 `path_with_namespace` 是 `hypermotion/nezha`），就会路径不匹配。

**结论**：YAML 分组 key 必须与 GitLab namespace 一致。正确的 `projects.yaml` 分组 key 是 `hypermotion`（GitLab namespace），而不是 `HyperBDR`。

### atomy/hamalv3 分组修复（2026-05-07）
症状：reporter 运行时 hypermotion/hamalv3 分支是 `saas_qa`（来自 BRANCH_RULES 的默认规则），但 GitLab 上 `atomy/hamalv3` 的正确分支是 `qa`。

根因：`projects.yaml` 中 `atomy/hamalv3` 被错误地放在了 `hypermotion:` 分组下，导致：
1. collector 把它当成 `hypermotion/hamalv3` 存储（group key=hypermotion）
2. reporter 查找 `hypermotion/hamalv3` → 在 BRANCH_RULES 中匹配 `hypermotion/*` → 分支=saas_qa
3. 但 GitLab 上 `atomy/hamalv3` 应该走 `atomy/*` → 分支=qa

修复：在 `projects.yaml` 中建独立的 `atomy:` 分组，把 `atomy/hamalv3` 移过去：
```yaml
atomy:
  - atomy/hamalv3    # 分支 qa
```

**验证**：`from reporter import PROJECTS; print(PROJECTS.get('atomy/hamalv3'))` 应显示 `{'path_with_namespace': 'atomy/hamalv3', 'branch': 'qa'}`

### Diff API 的路径字段
GitLab API 返回的字段在不同版本可能不同（`old_path`/`new_path` vs `old_file_path`/`new_file_path`），collector.py 已用 `.get()` 兼容两种格式。
