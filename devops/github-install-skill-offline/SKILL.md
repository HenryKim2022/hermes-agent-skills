---
name: github-install-skill-offline
description: 当终端无法直接 clone GitHub 仓库时，通过 GitHub API tarball 接口绕过网络限制安装/升级技能和 pip 包
---

# GitHub 仓库离线安装/升级（终端网络不通时）

## 问题
- `git clone git@github.com:xxx` 或 `git clone https://github.com/xxx` 超时
- `git fetch` 从 GitHub 拉取新版本时 TLS handshake 卡住（可 SSH 克隆但无法 fetch）
- 系统配置了代理（如 Clash Verge），但 `curl --proxy http://127.0.0.1:7890` TLS handshake 同样卡住
- 浏览器能访问 GitHub，但下载文件触发浏览器行为，无法保存到目标路径

## 场景一：安装 Skill

```bash
# 1. 用 curl 下载 tarball（GitHub API 不走代理但 curl 可达）
curl -s --max-time 30 -L \
  -H "Accept: application/vnd.github.v3+json" \
  -H "User-Agent: Mozilla/5.0" \
  "https://api.github.com/repos/{owner}/{repo}/tarball/{branch}" \
  -o /tmp/repo.tar.gz

# 2. 解压
tar -xzf /tmp/repo.tar.gz -C /tmp/

# 3. 移动到 skills 目录
ls /tmp/ | grep {repo}  # 找解压出的目录名
mv /tmp/{owner}-{repo}-{commit}/ ~/.hermes/skills/{category}/{repo-name}/

# 4. 推送 git
cd ~/.hermes/skills
git add {category}/{repo-name}/
git commit -m "Add {repo-name}"
git push
```

## 场景二：升级 pip 安装的包（含本地修改）

适用于 hermes-agent 等通过 `pip install -e .` 安装的有 GitHub 仓库的项目。

### 步骤 1：查最新版本
```python
import urllib.request, json
url = "https://api.github.com/repos/{owner}/{repo}/releases/latest"
req = urllib.request.Request(url, headers={"User-Agent": "hermes-agent"})
with urllib.request.urlopen(req, timeout=15) as resp:
    data = json.loads(resp.read())
print(f"Latest: {data['tag_name']}")
print(data['body'][:500])  # 看 release notes
```

### 步骤 2：下载 tarball
```python
import urllib.request, tarfile, os, shutil

url = "https://api.github.com/repos/{owner}/{repo}/tarball/{tag}"
req = urllib.request.Request(url, headers={
    "User-Agent": "hermes-agent",
    "Accept": "application/vnd.github+json"
})
with urllib.request.urlopen(req, timeout=30) as resp:
    data = resp.read()

tmp_tar = os.path.expanduser("~/.hermes/upgrade.tar.gz")
with open(tmp_tar, 'wb') as f:
    f.write(data)
print(f"Downloaded {len(data):,} bytes")
```

### 步骤 3：提取并合并
```python
import tarfile, shutil, os

extract_base = os.path.expanduser("~/.hermes/upgrade_extract")
if os.path.exists(extract_base):
    shutil.rmtree(extract_base)
os.makedirs(extract_base)

with tarfile.open(tmp_tar, 'r:gz') as tar:
    top_dir = tar.getmembers()[0].name  # 格式：{owner}-{repo}-{commit}
    tar.extractall(extract_base)

extract_path = os.path.join(extract_base, top_dir)
hermes_home = os.path.expanduser("~/.hermes/hermes-agent")

# 保留本地自定义目录
custom_to_preserve = ['skills', 'landingpage', 'venv', 'node_modules']
for item in custom_to_preserve:
    src = os.path.join(hermes_home, item)
    if os.path.exists(src):
        dst = os.path.join(extract_path, item)
        if os.path.isdir(src):
            if os.path.exists(dst):
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
        print(f"Restored: {item}")
```

### 步骤 4：替换并重新安装
```python
final_backup = os.path.expanduser("~/.hermes/hermes-agent.v{旧版本}.final")
if os.path.exists(final_backup):
    shutil.rmtree(final_backup)
shutil.move(hermes_home, final_backup)  # 备份旧版本
shutil.move(extract_path, hermes_home)  # 放置新版本
```

```bash
cd ~/.hermes/hermes-agent
pip install -e . --quiet
```

### 步骤 5：重新追加本地代码修改
如果旧版本有本地代码修改，需要在新版本中重新 patch：
```python
# 1. 先查旧版本的修改
# git diff HEAD  # 在旧版本 backup 目录执行

# 2. 重新 patch 到新版本文件
# 用 patch 工具追加 handler 方法
# 用 patch 工具追加 dispatch 分支
# 用 patch 工具追加到 COMMAND_REGISTRY
```

## 关键点
- GitHub API (`api.github.com`) 可能比 `raw.githubusercontent.com` 更容易连通
- `urllib` 下载时 header 要加 `User-Agent`，否则可能被限速
- 解压目录名格式：`{owner}-{repo}-{commit}`，需先确认
- 下载 timeout 建议 30s，数据量通常 20-30MB
- **升级 pip 包时必须备份旧版本**，因为 git fetch 不可用，无法通过 git merge 合并
- 本地代码修改需要在替换安装后重新 patch（文件内容已完全替换）
- 自定义 skills 目录和依赖（venv/ node_modules/）需要显式保留

### hermes-agent 升级特殊处理
- 当前目录 `skills/` 是 repo 自带的（bundled skills），新版也会包含
- 新版 vs 当前版 skill 差异：按需处理（新版多了 `yuanbao`，当前多了 `feeds`/`leisure`）
- 升级前先 `git diff HEAD` 查本地修改，patch 到新版本
- hermes-agent 需要 patch 3 个文件：
  - `cli.py`（handler 方法 + dispatch 分支）
  - `gateway/run.py`（async handler 方法 + dispatch）
  - `hermes_cli/commands.py`（COMMAND_REGISTRY）
- 安装完成后必须 `pip install -e . --quiet` 重新安装，再用 `hermes --version` 验证

### GitHub API 查最新 release
无需 git fetch，直接 `https://api.github.com/repos/{owner}/{repo}/releases/latest` 获取版本信息和 release notes。

## 验证代理实际端口（Clash Verge）
```bash
# Clash Verge 可能监听在随机高端口，不是默认的 7890
lsof -nP -iTCP -sTCP:LISTEN | grep -i clash
```

## 验证安装
```bash
hermes --version  # 确认版本号
```

## 紧急回滚
```bash
cd ~/.hermes
rm -rf hermes-agent
mv hermes-agent.v{旧版本}.final hermes-agent
pip install -e .
hermes --version  # 确认回滚成功
```
