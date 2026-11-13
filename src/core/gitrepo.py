"""Git 仓库的本地扫描与状态读取。

只读取本地 git 信息（含 refs/remotes 中缓存的远端状态），不发起 fetch 等网络请求。
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# 扫描时直接剪掉的目录：不可能作为仓库根，且通常体积很大
_SKIP_DIRS = {
    "node_modules", ".venv", "venv", "env", "dist", "build", "out", "target",
    "__pycache__", ".tox", ".mypy_cache", ".pytest_cache", "site-packages",
    ".idea", ".vs", ".next", ".nuxt", "vendor", "bower_components",
}

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_FIELD_SEP = "\x1f"


@dataclass
class RemoteBranch:
    """某个远程仓库上对应当前分支的状态。"""

    remote: str
    branch: str
    exists: bool          # 远端是否已存在该分支
    commit: str           # 远端分支最新提交短哈希
    subject: str          # 远端分支最新提交说明
    ahead: int            # 本地领先的提交数
    behind: int           # 本地落后的提交数

    @property
    def pushable(self) -> bool:
        """远端分支不存在（首次推送）或本地确有领先提交时可推送。"""
        return not self.exists or self.ahead > 0


@dataclass
class RepoInfo:
    path: Path
    name: str
    branch: str
    head_short: str
    head_subject: str
    dirty: bool
    remotes: list[RemoteBranch]
    branches: list[str] = field(default_factory=list)   # 本地分支（含当前分支）

    @property
    def pushable_remotes(self) -> list[RemoteBranch]:
        return [r for r in self.remotes if r.pushable]

    @property
    def detached(self) -> bool:
        return self.branch.startswith("detached")


def _git(repo: Path, *args: str, timeout: float = 10) -> tuple[bool, str]:
    """执行 git 子命令；成功返回 (True, stdout)，失败返回 (False, "")。"""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=_CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return False, ""
    if proc.returncode != 0:
        return False, ""
    return True, proc.stdout.strip()


def find_repos(root: Path) -> list[Path]:
    """递归查找 root 下所有 Git 仓库（含 .git 的目录）。

    找到仓库根后不再深入其内部，避免把子模块/依赖目录当成独立仓库。
    """
    root = Path(root)
    if not root.is_dir():
        return []

    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda _: None):
        current = Path(dirpath)
        # 普通仓库的 .git 是目录；worktree / 子模块的 .git 是文件
        if ".git" in dirnames or ".git" in filenames:
            found.append(current)
            dirnames[:] = []
            continue
        dirnames[:] = sorted(
            d for d in dirnames if d not in _SKIP_DIRS and d != ".git"
        )
    return found


def _parse_remote_refs(raw: str) -> tuple[dict[tuple[str, str], tuple[str, str]], dict[str, str]]:
    """解析 for-each-ref 输出，返回 ((remote, branch) -> (短哈希, 说明), remote -> HEAD 短哈希)。"""
    refs: dict[tuple[str, str], tuple[str, str]] = {}
    heads: dict[str, str] = {}
    for line in raw.splitlines():
        parts = line.split("\t", 2)
        if len(parts) < 3 or not parts[0].startswith("refs/remotes/"):
            continue
        rest = parts[0][len("refs/remotes/"):]
        if "/" not in rest:
            continue
        remote, branch = rest.split("/", 1)
        short, subject = parts[1], parts[2]
        if branch == "HEAD":
            heads[remote] = short
        else:
            refs[(remote, branch)] = (short, subject)
    return refs, heads


def _divergence(repo: Path, ref: str, local: str = "HEAD") -> tuple[int, int] | None:
    """返回 (本地领先, 本地落后) 提交数。"""
    ok, out = _git(repo, "rev-list", "--left-right", "--count", f"{local}...{ref}")
    if not ok:
        return None
    parts = out.split()
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def local_branches(path: Path) -> list[str]:
    """列出本地分支名（按 git 默认排序，当前分支不一定在最前）。"""
    ok, out = _git(Path(path), "for-each-ref", "--format=%(refname:short)", "refs/heads")
    if not ok:
        return []
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def read_repo(path: Path, branch: str | None = None) -> RepoInfo | None:
    """读取单个仓库的状态；空仓库或无提交时返回 None。

    branch 为 None 时读取当前分支；指定时按该本地分支读取提交与领先/落后数，
    用于推送页里切换要查看/推送的分支。
    """
    path = Path(path)

    ok, current = _git(path, "symbolic-ref", "--short", "-q", "HEAD")
    current = current if ok and current else ""
    target = branch or current or "HEAD"

    ok, head_short = _git(path, "rev-parse", "--short=7", target)
    if not ok:
        return None

    if branch is None:
        branch = current or f"detached@{head_short}"

    ok, log_line = _git(path, "log", "-1", "--format=%h%x1f%s", target)
    head_subject = ""
    if ok and _FIELD_SEP in log_line:
        head_short, head_subject = log_line.split(_FIELD_SEP, 1)

    # 不统计未跟踪文件：大型仓库下 status 会明显变慢，已跟踪改动足够标示“有修改”
    # 未检出的分支没有工作区，不显示改动标记
    dirty = False
    if branch == current:
        ok, status = _git(path, "status", "--porcelain", "--untracked-files=no")
        dirty = ok and bool(status)

    ok, remote_raw = _git(path, "remote")
    remotes = [r for r in remote_raw.splitlines() if r] if ok else []

    refs: dict[tuple[str, str], tuple[str, str]] = {}
    heads: dict[str, str] = {}
    if remotes:
        ok, ref_raw = _git(
            path, "for-each-ref",
            "--format=%(refname)%09%(objectname:short)%09%(subject)",
            "refs/remotes",
        )
        if ok:
            refs, heads = _parse_remote_refs(ref_raw)

    remote_branches: list[RemoteBranch] = []
    for remote in remotes:
        ref = f"refs/remotes/{remote}/{branch}"
        cached = refs.get((remote, branch))
        if cached is not None:
            short, subject = cached
            delta = _divergence(path, ref, target)
            ahead, behind = delta if delta else (0, 0)
            remote_branches.append(RemoteBranch(
                remote, branch, True, short, subject, ahead, behind,
            ))
            continue

        # 远端还没有该分支：相对远端默认分支估算将推送的提交数
        ahead = 0
        head_ref = heads.get(remote)
        if head_ref:
            ok, count = _git(path, "rev-list", "--count", f"{remote}/HEAD..{target}")
            ahead = int(count) if ok and count.isdigit() else 0
        if not ahead:
            ok, count = _git(path, "rev-list", "--count", target)
            ahead = int(count) if ok and count.isdigit() else 0
        remote_branches.append(RemoteBranch(
            remote, branch, False, "", "", ahead, 0,
        ))

    return RepoInfo(
        path=path,
        name=path.name,
        branch=branch,
        head_short=head_short,
        head_subject=head_subject,
        dirty=dirty,
        remotes=remote_branches,
        branches=local_branches(path),
    )


def scan(root: Path) -> list[RepoInfo]:
    """扫描目录下所有仓库并按名称排序，读取失败的仓库跳过。"""
    repos = []
    for path in find_repos(Path(root)):
        info = read_repo(path)
        if info is not None:
            repos.append(info)
    repos.sort(key=lambda r: r.name.lower())
    return repos


def scan_sources(sources: list[dict]) -> list[RepoInfo]:
    """按来源列表汇总仓库：folder 递归查找，repo 直接读取。

    同一仓库被多处覆盖时只保留一份（按解析后的真实路径去重）。
    """
    repos, seen = [], set()
    for src in sources:
        path = Path(str(src.get("path", "")))
        if not path.is_dir():
            continue
        candidates = [path] if src.get("kind") == "repo" else find_repos(path)
        for cand in candidates:
            try:
                key = str(cand.resolve()).lower()
            except OSError:
                key = str(cand).lower()
            if key in seen:
                continue
            info = read_repo(cand)
            if info is None:
                continue
            seen.add(key)
            repos.append(info)
    repos.sort(key=lambda r: r.name.lower())
    return repos


def push_args(remote: str, branch: str, set_upstream: bool) -> list[str]:
    """构造推送参数（配合 QProcess 在仓库目录中执行 git）。"""
    args = ["push", "--porcelain"]
    if set_upstream:
        args.append("-u")
    args.extend([remote, branch])
    return args
