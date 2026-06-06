#!/usr/bin/env python3
# ==========================================================
# GitLab 代码提交采集器（API 模式）
# 功能：通过 GitLab REST API 采集指定日期的 commits + diff
# 依赖：标准库（urllib, json, pathlib, subprocess）
# ==========================================================

import subprocess
import json
import sys
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime


# =========== 配置 ===========
import yaml

BASE = Path.home() / ".hermes" / "code-insights"
REPOS = BASE / "repos"
COMMITS = BASE / "commits"
PROJECTS_FILE = Path(__file__).parent.parent / "projects.yaml"

GL_URL = "http://192.168.10.254:20080"
GL_USER = "devops"
GL_PASS = "devops@HyperMotion"
GL_GROUP_ID = "36"
# SSH clone 用 GitLab 官方地址（office.oneprocloud.com.cn:20022），不走 VPN 分配的 192.168.10.254
GL_SSH_HOST = "office.oneprocloud.com.cn"
GL_SSH_PORT = "20022"
GL_SSH_USER = "git"

TOKEN = None

# 分支规则（与 clone_projects.sh 一致）
BRANCH_RULES = {
    "atomy": "qa",
    "CI-CD": "master",
}
DEFAULT_BRANCH = "saas_qa"


def load_projects():
    """从 projects.yaml 加载项目列表"""
    with open(PROJECTS_FILE) as f:
        config = yaml.safe_load(f)
    projects = []
    for group, paths in config.get("groups", {}).items():
        for path_with_namespace in paths:
            project_name = path_with_namespace.rsplit("/", 1)[-1]
            projects.append({
                "group": group,
                "project": project_name,
                "path_with_namespace": path_with_namespace,
            })
    return projects


PROJECTS = load_projects()


def resolve_branch(path_with_namespace):
    """根据项目路径返回对应分支（与 clone_projects.sh 逻辑一致）"""
    for prefix, branch in BRANCH_RULES.items():
        if prefix in path_with_namespace:
            return branch
    return DEFAULT_BRANCH


# =========== Token 管理 ===========
def get_token():
    """获取 GitLab OAuth token（带缓存）"""
    global TOKEN
    if TOKEN:
        return TOKEN
    data = json.dumps({"grant_type": "password", "username": GL_USER, "password": GL_PASS}).encode()
    req = urllib.request.Request(
        f"{GL_URL}/oauth/token",
        data=data,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        TOKEN = json.loads(r.read())["access_token"]
    return TOKEN


def ensure_token():
    """确保 token 有效，必要时刷新"""
    token = get_token()
    try:
        req = urllib.request.Request(
            f"{GL_URL}/api/v4/version",
            headers={"Authorization": f"Bearer {token}"}
        )
        urllib.request.urlopen(req, timeout=10)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            global TOKEN
            TOKEN = None
            return get_token()
        raise
    return token


# =========== GitLab API ===========
def get_project_id(path_with_namespace, token):
    """搜索项目并返回 project_id"""
    project_name = path_with_namespace.rsplit("/", 1)[-1]
    url = f"{GL_URL}/api/v4/projects?search={urllib.parse.quote(project_name)}&per_page=50"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        projects = json.loads(r.read())
    for p in projects:
        if p["path_with_namespace"] == path_with_namespace:
            return p["id"]
    return None


def get_commits(project_id, branch, date_str, token):
    """获取指定分支指定日期的 commits"""
    after = date_str
    until = f"{date_str}T23:59:59Z"
    url = f"{GL_URL}/api/v4/projects/{project_id}/repository/commits"
    params = urllib.parse.urlencode({
        "ref_name": branch,
        "since": after,
        "until": until,
        "per_page": 100,
    })
    req = urllib.request.Request(f"{url}?{params}", headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def get_diff_from_api(project_id, sha, token):
    """通过 GitLab API 获取单个 commit 的 diff，格式化为 patch 文件内容"""
    url = f"{GL_URL}/api/v4/projects/{project_id}/repository/commits/{sha}/diff"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        diffs = json.loads(r.read())

    patch_lines = []
    for d in diffs:
        old_path = d.get("old_path", d.get("old_file_path", ""))
        new_path = d.get("new_path", d.get("new_file_path", ""))
        diff_text = d.get("diff", "")
        patch_lines.append(f"diff --git a/{old_path} b/{new_path}")
        patch_lines.append(diff_text)

    return "\n".join(patch_lines)


# =========== 主流程 ===========
def collect(date_str):
    print(f"\n{'='*60}")
    print(f"  Collector v3 (API-only)  {date_str}")
    print(f"{'='*60}")

    token = ensure_token()
    print("[OK] token")

    for proj in PROJECTS:
        group, project = proj["group"], proj["project"]
        branch = resolve_branch(proj["path_with_namespace"])
        print(f"\n[{group}/{project}] branch={branch}")

        # 1. 获取 project_id
        project_id = get_project_id(proj["path_with_namespace"], token)
        if not project_id:
            print(f"  [SKIP] 未找到 project_id")
            continue

        # 2. 获取当日 commits（API）
        remote_commits = get_commits(project_id, branch, date_str, token)
        print(f"  API: {len(remote_commits)} commits")

        # 3. 过滤：去掉 gitlab/bot/system
        SKIP_AUTHORS = {"bot", "system", ""}
        filtered = [
            c for c in remote_commits
            if c.get("author_name", "").lower() not in SKIP_AUTHORS
        ]

        # 4. 标准化字段
        commits_standardized = []
        for c in filtered:
            commits_standardized.append({
                "sha": c["id"],
                "author": c.get("author_name", ""),
                "email": c.get("author_email", ""),
                "date": c.get("created_at", ""),
                "message": c.get("message", ""),
                "additions": c.get("stats", {}).get("additions", 0),
                "deletions": c.get("stats", {}).get("deletions", 0),
            })

        # 5. 保存 commits.json
        out_dir = COMMITS / date_str / group / project
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "commits.json"

        with open(out_file, "w") as f:
            json.dump({
                "date": date_str,
                "group": group,
                "project": project,
                "branch": branch,
                "commits": commits_standardized,
            }, f, ensure_ascii=False, indent=2)

        print(f"  [OK] {out_file}")

        # 6. 获取每个 commit 的 patch 文件
        for c in commits_standardized:
            sha = c["sha"]
            patch_content = get_diff_from_api(project_id, sha, token)
            patch_file = out_dir / f"{sha}.patch"
            with open(patch_file, "w") as f:
                f.write(patch_content)
            print(f"  {sha[:8]}  {c['author']}  +{c['additions']}/-{c['deletions']}  {c['message'][:50]}")

        print(f"\n  共 {len(commits_standardized)} 条有效 commit")


if __name__ == "__main__":
    date_str = sys.argv[1] if len(sys.argv) > 1 else "today"
    if date_str == "today":
        date_str = datetime.now().strftime("%Y-%m-%d")
    collect(date_str)
