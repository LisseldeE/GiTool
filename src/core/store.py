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
