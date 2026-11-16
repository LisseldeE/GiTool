"""配置持久化：读写用户目录下的 ~/.gitool/config.json。

只存少量偏好（界面风格、深浅色、上次扫描目录），因此用一个扁平的 JSON 对象，
读取失败（文件缺失/JSON 损坏）时按空配置处理，写入失败静默忽略。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

_PATH = Path.home() / ".gitool" / "config.json"
_cache: dict | None = None


def config_path() -> Path:
    return _PATH


def load() -> dict:
    """读取完整配置；文件不存在或内容无效时返回空字典。"""
    try:
        data = json.loads(_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _data() -> dict:
    global _cache
    if _cache is None:
        _cache = load()
    return _cache


def get(key: str, default=None):
    return _data().get(key, default)


def save(data: dict) -> None:
    """原子写入：先写临时文件再替换，避免中途失败留下半截 JSON。"""
    global _cache
    _cache = dict(data)
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, _PATH)
    except OSError:
        pass


def set_value(key: str, value) -> None:
    """更新单个键并写回；值未变化时不重复写盘。"""
    data = _data()
    if data.get(key) == value:
        return
    data[key] = value
    save(data)


def repo_sources() -> list[dict]:
    """已登记的仓库来源：每项 {"path": 绝对路径, "kind": "repo" | "folder"}。"""
    raw = get("repo_sources")
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        path, kind = item.get("path"), item.get("kind")
        if isinstance(path, str) and path and kind in ("repo", "folder"):
            out.append({"path": path, "kind": kind})
    return out


def save_repo_sources(items: list[dict]) -> None:
    set_value("repo_sources", [{"path": i["path"], "kind": i["kind"]} for i in items])


def sensitive_verify_required() -> bool:
    """敏感操作（推送、关闭保护本身）是否需要二次校验；默认关闭。"""
    return bool(get("sensitive_verify", False))


def _repo_key(path: str) -> str:
    """仓库配置的键：真实路径小写，避免盘符/分隔符差异导致读不到。"""
    try:
        return str(Path(path).resolve()).lower()
    except OSError:
        return str(path).lower()


def repo_options(path: str) -> dict:
    """单个仓库的附加配置（目前只有批量推送目标）。"""
    raw = get("repo_options")
    if not isinstance(raw, dict):
        return {}
    item = raw.get(_repo_key(path))
    return item if isinstance(item, dict) else {}


def save_push_remotes(path: str, names: list[str]) -> None:
    """保存该仓库的批量推送目标（远程名列表）。"""
    raw = get("repo_options")
    data = dict(raw) if isinstance(raw, dict) else {}
    key = _repo_key(path)
    item = dict(data.get(key)) if isinstance(data.get(key), dict) else {}
    item["push_remotes"] = list(names)
    data[key] = item
    set_value("repo_options", data)


def push_remotes(path: str) -> list[str] | None:
    """读取批量推送目标；从未配置时返回 None（由界面取默认值）。"""
    raw = repo_options(path).get("push_remotes")
    if not isinstance(raw, list):
        return None
    return [str(n) for n in raw if isinstance(n, str)]
