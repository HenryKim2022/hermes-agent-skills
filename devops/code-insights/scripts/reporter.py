#!/usr/bin/env python3
"""
Code Insights 报告生成器 - 使用 Claude Code 分析
每个 commit 生成 summary + detailed 两个报告文件
"""

import json
import sys
import re
import subprocess
import shutil
from pathlib import Path
from datetime import datetime
from functools import lru_cache
import tempfile
import os

# ── 配置 ──────────────────────────────────────────────
import yaml

BASE_DIR    = Path.home() / ".hermes" / "code-insights"
COMMITS_DIR = BASE_DIR / "commits"
REPORT_DIR  = BASE_DIR / "reports" / "daily"
REPOS_DIR   = BASE_DIR / "repos"
PROJECTS_FILE = Path(__file__).parent.parent / "projects.yaml"

# SSH 配置（已验证可用）
GL_SSH_HOST = "office.oneprocloud.com.cn"
GL_SSH_PORT = "20022"
GL_SSH_USER = "git"

# 分支规则（与 collector.py 一致）
BRANCH_RULES = {
    "atomy": "qa",
    "CI-CD": "master",
}
DEFAULT_BRANCH = "saas_qa"


def load_projects():
    with open(PROJECTS_FILE) as f:
        config = yaml.safe_load(f)
    projects = {}
    for group, paths in config.get("groups", {}).items():
        for path_with_namespace in paths:
            project_name = path_with_namespace.rsplit("/", 1)[-1]
            projects[f"{group}/{project_name}"] = {
                "path_with_namespace": path_with_namespace,
                "branch": _resolve_branch(path_with_namespace),
            }
    return projects


def _resolve_branch(path_with_namespace: str) -> str:
    for prefix, branch in BRANCH_RULES.items():
        if prefix in path_with_namespace:
            return branch
    return DEFAULT_BRANCH


PROJECTS = load_projects()

SUMMARY_PROMPT_TPL = """你是一个产品经理，从代码变更推断产品层面的影响。

## 输入
项目: {project}
分支: {branch}
提交: {sha}
作者: {author}
时间: {committed_date}
提交信息: {message}
涉及文件: {chunk_file}

## Patch（代码变更）
```diff
{patch}
```

## 输出要求（Summary 报告）

### 1. 产品改动
- 用一句话描述这个 commit 做了什么（面向产品/管理层）
- 说明改了什么模块/功能

### 2. 风险评估（爆炸半径）
- 影响范围：小 / 中 / 大
- 理由：
  - 改了哪些依赖模块：
  - 是否涉及核心业务流程：
  - 是否有回滚难度：
- 建议：（如果有）

## 约束
- 不超过 150 字
- 不重编，只基于 patch 内容推断
- 风险评估要具体，不要模糊
"""

DETAILED_PROMPT_TPL = """你是一个资深代码审查专家，严格审查代码变更质量。

## 输入
项目: {project}
分支: {branch}
提交: {sha}
作者: {author}
时间: {committed_date}
提交信息: {message}
涉及文件: {chunk_file}

## Patch（代码变更）
```diff
{patch}
```

## 输出要求（Detailed 报告，严格、简洁、直接）

### 1. 代码质量评分

| 维度 | 评分 | 说明 |
|------|------|------|
| 代码规范 | /100 | |
| Commit 规范 | /100 | ⚠️ 标题与实际内容不符 → 低分（标题说"支持"实际是"取消注释启用"） |
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

## 扣分原则
- Commit 标题与实际内容不符（标题说A实际是B）：低分（40分以下）
- 无测试覆盖：低于60分
- 静默失败风险（错误仅warning不阻止）：低于70分
- 前置条件不透明（删注释/配置无说明）：低于70分

## 约束
- 不说废话，不写"阶段/评估/说明"等报告腔
- 理由要有逻辑，直接说问题
- 不美化缺陷
"""

# ── 工具函数 ──────────────────────────────────────────

MAX_TOKENS_INPUT = 100000  # Claude context window


def count_patch_stats(patch: str) -> tuple[int, int]:
    """统计 patch 增加/删除行数"""
    added = removed = 0
    for line in patch.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return added, removed


@lru_cache(maxsize=256)
def split_patch(patch: str) -> list[dict]:
    """
    将 patch 按文件拆分，文件过大时按逻辑块二次拆分。
    返回: [{"file": "path/file.py", "content": "...", "is_partial": bool}, ...]
    """
    files = []
    current_file = None
    current_lines = []

    for line in patch.splitlines(True):  # keepends
        if line.startswith("diff --git"):
            if current_file is not None:
                current_file["content"] = "".join(current_lines)
                files.append(current_file)
            fname = line.split(" b/", 1)[-1].strip() if " b/" in line else "unknown"
            current_file = {"file": fname, "content": "", "lines": 0}
            current_lines = []
        elif current_file is not None:
            current_lines.append(line)
            current_file["lines"] += 1

    if current_file is not None:
        current_file["content"] = "".join(current_lines)
        files.append(current_file)

    # 过滤掉辅助行（---、+++、index），保留实际 diff 内容
    for f in files:
        f["content"] = "".join(
            l for l in f["content"].splitlines(True)
            if not l.startswith(("--- ", "+++ ", "index "))
        )

    # 按文件大小降序排列，优先放满每个 chunk
    files.sort(key=lambda x: len(x["content"]), reverse=True)

    # 分块：保持文件完整，超大文件按 @@ 块拆分
    chunks = []
    current_chunk_files = []
    current_chunk_size = 0

    # 预留 prompt + 输出空间，约 2000 token
    max_patch_per_call = (MAX_TOKENS_INPUT - 2000) * 4  # 粗估：1 token ≈ 4 字符

    for f in files:
        fsize = len(f["content"])
        # 单文件超限时按 @@ 段落拆分
        if fsize > max_patch_per_call:
            sub_chunks = _split_by_hunks(f, max_patch_per_call)
            for sc in sub_chunks:
                chunks.append({"file": f["file"], "content": sc, "is_partial": True})
        elif current_chunk_size + fsize > max_patch_per_call:
            # 当前 chunk 满了，先保存
            if current_chunk_files:
                chunks.append(_merge_chunk_files(current_chunk_files))
            current_chunk_files = [f]
            current_chunk_size = fsize
        else:
            current_chunk_files.append(f)
            current_chunk_size += fsize

    if current_chunk_files:
        chunks.append(_merge_chunk_files(current_chunk_files))

    return chunks


def _split_by_hunks(file_info: dict, max_size: int) -> list[str]:
    """
    按 git diff 的 @@ 段落拆分，超大段落内部截断。
    """
    content = file_info["content"]
    fname = file_info["file"]
    hunks = []
    current_hunk = []

    for line in content.splitlines(True):
        if line.startswith("@@ "):
            if current_hunk:
                hunks.append("".join(current_hunk))
            current_hunk = [line]
        else:
            current_hunk.append(line)

    if current_hunk:
        hunks.append("".join(current_hunk))

    # 合并 hunk 到 chunk，不超限
    result = []
    current = f"=== {fname} (partial) ===\n"
    for hunk in hunks:
        if len(current) + len(hunk) > max_size:
            if current.strip():
                result.append(current)
            current = f"=== {fname} (partial) ===\n"
            # 单个 hunk 仍超限 → 截断（保留头尾各 1/3）
            if len(hunk) > max_size:
                cut = int(max_size * 0.6)
                result.append(hunk[:cut] + f"\n... [内容过长，已截断] ...\n")
                continue
        current += hunk

    if current.strip():
        result.append(current)
    return result


def _merge_chunk_files(files: list[dict]) -> dict:
    """将多个文件合并为一个 chunk"""
    combined = ""
    for f in files:
        combined += f"=== {f['file']} ===\n{f['content']}\n"
    return {
        "file": "\n".join(f["file"] for f in files),
        "content": combined,
        "is_partial": False
    }


def call_claude_code(prompt: str, timeout: int = 120) -> str:
    """调用 Claude Code 进行分析"""
    try:
        result = subprocess.run(
            ["claude", "--print", "--output-format", "text", "--no-session-persistence",
             "--dangerously-skip-permissions", prompt],
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "CLAUDE_CODE_SIMPLE": "1"}
        )
        if result.returncode != 0:
            return f"[Claude Code 错误: {result.stderr.strip()}]"
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return "[Claude Code 超时]"
    except FileNotFoundError:
        return "[Claude Code 未找到，请确保已安装]"
    except Exception as e:
        return f"[Claude Code 调用失败: {e}]"


def get_git_url(project_path: str) -> str:
    """
    构建 SSH clone URL（使用已验证的 office.oneprocloud.com.cn:20022）
    project_path 格式：group/project_name  →  path_with_namespace：group/project_name
    """
    info = PROJECTS.get(project_path, {})
    path_with_namespace = info.get("path_with_namespace", project_path)
    return f"ssh://{GL_SSH_USER}@{GL_SSH_HOST}:{GL_SSH_PORT}/{path_with_namespace}.git"


def clone_and_prepare_repo(project_path: str, sha: str, patch_content: str, repos_base: Path = None) -> tuple[bool, str]:
    """
    克隆或更新项目仓库到 repos_base，支持直接 checkout 到目标 SHA。
    SSH clone 已验证可用，1-2 秒完成。
    Returns (success, work_dir_or_error_msg)
    """
    if repos_base is None:
        repos_base = REPOS_DIR

    info = PROJECTS.get(project_path, {})
    path_with_namespace = info.get("path_with_namespace", project_path)
    branch = info.get("branch", "saas_qa")
    work_dir = repos_base / project_path

    git_url = get_git_url(project_path)

    try:
        if not work_dir.exists():
            # 全新 clone（--single-branch 只拉目标分支，1-2 秒）
            r = subprocess.run(
                ["git", "clone", "--bare", "--single-branch", "-b", branch,
                 git_url, str(work_dir)],
                capture_output=True, text=True, timeout=60
            )
            if r.returncode != 0:
                return False, f"Clone 失败: {r.stderr[:200]}"
        else:
            # 已有 clone，检查当前分支是否匹配
            r = subprocess.run(
                ["git", "--git-dir", str(work_dir), "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True, timeout=10
            )
            current_branch = r.stdout.strip()

            if current_branch != branch:
                # 分支不同，重新 clone
                shutil.rmtree(work_dir, ignore_errors=True)
                r = subprocess.run(
                    ["git", "clone", "--bare", "--single-branch", "-b", branch,
                     git_url, str(work_dir)],
                    capture_output=True, text=True, timeout=60
                )
                if r.returncode != 0:
                    return False, f"重新 Clone 失败: {r.stderr[:200]}"

        return True, str(work_dir)

    except subprocess.TimeoutExpired:
        return False, "Git clone 超时"
    except Exception as e:
        return False, f"Git 操作失败: {e}"


def _build_prompt(template: str, **kwargs) -> str:
    """填充 prompt 模板"""
    return template.format(**kwargs)


def process_commit(commit, patch_content, project_path, report_root, is_summary: bool, work_dir: str = None):
    """处理单个 commit，生成 summary 或 detailed 报告（支持大 patch 分块）"""
    sha     = commit["sha"]
    author  = commit["author"]
    date    = commit["date"]
    message = commit["message"]
    branch  = PROJECTS.get(project_path, {}).get("branch", "saas_qa")
    added, removed = count_patch_stats(patch_content)

    chunks = split_patch(patch_content)
    results = []

    for i, chunk in enumerate(chunks):
        chunk_note = f"（第 {i+1}/{len(chunks)} 部分）" if len(chunks) > 1 else ""

        if is_summary:
            prompt = _build_prompt(SUMMARY_PROMPT_TPL,
                project=project_path, branch=branch, sha=sha,
                author=author, committed_date=date, message=message,
                patch=chunk["content"], chunk_note=chunk_note,
                chunk_file=chunk["file"])
        else:
            prompt = _build_prompt(DETAILED_PROMPT_TPL,
                project=project_path, branch=branch, sha=sha,
                author=author, committed_date=date, message=message,
                patch=chunk["content"],
                chunk_note=chunk_note, chunk_file=chunk["file"])

        # 如果有 work_dir，添加上下文信息
        if work_dir:
            prompt = f"[工作目录: {work_dir}]\n\n{prompt}"

        result = call_claude_code(prompt)
        results.append(result)
        print(f"    {'['+str(i+1)+'/'+str(len(chunks))+']' if len(chunks)>1 else '  '} ✅")

    final = "\n\n---\n\n".join(results)

    out_dir = report_root / project_path
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = "summary" if is_summary else "detailed"
    (out_dir / f"{sha}.{suffix}.md").write_text(
        f"# {suffix.title()} — {sha[:8]}{' (分块)' if len(chunks)>1 else ''}\n\n"
        f"**项目:** {project_path}\n"
        f"**作者:** {author}\n"
        f"**时间:** {date}\n"
        f"**分支:** {branch}\n"
        f"**提交:** {message}\n\n"
        f"---\n\n{final}"
    )

    return sha[:8], author, message, added, removed


# ── 主流程 ─────────────────────────────────────────────

def main(date_str: str):
    commits_base = COMMITS_DIR / date_str
    if not commits_base.exists():
        print(f"❌ 目录不存在: {commits_base}")
        return

    report_root = REPORT_DIR / date_str
    report_root.mkdir(parents=True, exist_ok=True)

    # 遍历所有 commits.json
    json_files = list(commits_base.rglob("commits.json"))
    if not json_files:
        print(f"❌ 找不到 commits.json: {commits_base}")
        return

    total = 0
    for json_file in json_files:
        project_path = str(json_file.parent.relative_to(commits_base))
        commits_data = json.loads(json_file.read_text())

        commits_list = commits_data.get("commits", [])
        print(f"\n📦 {project_path}: {len(commits_list)} commits")

        # 为每个项目尝试 clone 一次（如果需要）
        work_dir = None
        clone_success = False

        for commit in commits_list:
            sha = commit["sha"]
            patch_file = json_file.parent / f"{sha}.patch"
            if not patch_file.exists():
                print(f"  ⚠️  patch 不存在: {sha[:8]}")
                continue

            patch_content = patch_file.read_text()
            chunks = split_patch(patch_content)  # 缓存，避免重复解析
            print(f"  🔍 {sha[:8]} | {commit['author']} | {len(patch_content.splitlines())} 行 patch")

            # 尝试 clone 并应用 patch（只尝试一次 per 项目）
            if not clone_success:
                success, result = clone_and_prepare_repo(
                    project_path, sha, patch_content
                )
                if success:
                    work_dir = result
                    clone_success = True
                    print(f"    📁 已克隆到: {work_dir}")
                else:
                    print(f"    ⚠️  Clone 失败，将使用 patch 直接分析: {result}")

            short_sha, author, msg, added, removed = process_commit(
                commit, patch_content, project_path, report_root, is_summary=True,
                work_dir=work_dir if clone_success else None
            )
            print(f"    Summary {'[分块]' if len(chunks)>1 else ''}")
            short_sha, author, msg, added, removed = process_commit(
                commit, patch_content, project_path, report_root, is_summary=False,
                work_dir=work_dir if clone_success else None
            )
            print(f"    Detailed {'[分块]' if len(chunks)>1 else ''} | +{added}/-{removed} | {msg[:50]}")
            total += 1

    print(f"\n✅ 完成！共处理 {total} 个 commit")
    print(f"📂 报告目录: {report_root}")


if __name__ == "__main__":
    date_arg = sys.argv[1] if len(sys.argv) > 1 else "today"
    if date_arg == "today":
        date_arg = datetime.now().strftime("%Y-%m-%d")
    main(date_arg)
