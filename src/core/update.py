"""
在线更新模块
拉取版本清单、下载并校验安装包，供关于页的手动检查更新使用。
Copyright (c) 2026 Lisselde_E <Lisselde.E@outlook.com>.
Licensed under the GNU General Public License v3.0.

清单格式（GitHub Pages 纯文本；第一行必须是版本号）：
R1.0.0.0
# win_sha256: <64 位十六进制>
# win_url_zh_CN: https://.../GiTool_Setup.exe
# win_url_en_US: https://.../GiTool_Setup.exe
# log
- 条目一

解析阶段只做尽力提取；sha256 缺失或非法时由 download_package 拒绝下载。
"""
import hashlib
import os
import re
import shutil
import ssl
import urllib.request
from pathlib import Path
from typing import Callable, List, Optional

from . import store
from .config import Config
from .i18n import language as ui_language
from .i18n import tr

CHUNK_SIZE = 1024 * 1024  # 下载分块 1MB


class UpdateError(Exception):
    """更新清单非法、下载失败或校验不通过。"""


class UpdateInfo:
    """一次更新检查结果。"""

    __slots__ = ("version", "sha256", "url_zh_cn", "url_en_us", "changelog", "size")

    def __init__(self, version: str, sha256: str, url_zh_cn: str = "",
                 url_en_us: str = "", changelog: Optional[List[str]] = None,
                 size: Optional[int] = None):
        self.version = version
        self.sha256 = sha256
        self.url_zh_cn = url_zh_cn
        self.url_en_us = url_en_us
        self.changelog = list(changelog or [])
        self.size = size

    def url_for(self, language: str) -> str:
        """按界面语言选下载地址（中文优先中文地址，其余走英文地址）。"""
        if str(language or "").lower().startswith("zh"):
            return self.url_zh_cn or self.url_en_us
        return self.url_en_us or self.url_zh_cn

    def __repr__(self):
        return f"UpdateInfo({self.version!r})"


_VERSION_RE = re.compile(r"R?\d+\.\d+\.\d+\.\d+")
_SHA256_RE = re.compile(r"[0-9a-fA-F]{64}")


def version_tuple(version: str):
    """提取四段版本号元组（兼容带 R 前缀）；无法解析返回 None。"""
    match = re.search(r"R?(\d+)\.(\d+)\.(\d+)\.(\d+)", version or "")
    return tuple(map(int, match.groups())) if match else None


def is_newer(latest: str, current: str) -> bool:
    """latest 是否比 current 新（四段逐段比较）。"""
    a, b = version_tuple(latest), version_tuple(current)
    return bool(a and b and a > b)


def _clean(value: str) -> str:
    """去掉首尾空白与反引号（清单里的 URL 可能被反引号包裹）。"""
    return value.strip().strip("`").strip()


def parse_manifest(text: str) -> UpdateInfo:
    """解析更新清单。非法内容抛 UpdateError。"""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if not lines:
        raise UpdateError(tr("更新清单为空"))

    # 第一行是版本号；容忍带 "# " 前缀的旧写法
    first = _clean(lines[0].lstrip("#"))
    if not _VERSION_RE.fullmatch(first):
        raise UpdateError(tr("无法解析更新清单中的版本号"))
    version = first

    meta = {}
    changelog = []
    in_log = False
    for line in lines[1:]:
        if line.startswith("#"):
            body = line[1:].strip()
            if body.lower() == "log":
                in_log = True
                continue
            if in_log:
                continue
            key, sep, value = body.partition(":")
            if sep:
                meta[key.strip().lower()] = _clean(value)
            continue
        if in_log and line.startswith("-"):
            item = line[1:].strip()
            if item:
                changelog.append(item)

    # win_sha256 是唯一必填字段；非法值按缺失处理
    sha256 = meta.get("win_sha256") or ""
    if not _SHA256_RE.fullmatch(sha256):
        sha256 = ""

    size = meta.get("size", "")
    try:
        size_value = int(size) if size else None
    except ValueError:
        size_value = None

    return UpdateInfo(version, sha256, meta.get("win_url_zh_cn", ""),
                      meta.get("win_url_en_us", ""), changelog, size_value)


def fetch_manifest(url: str = None, timeout: float = 8.0) -> UpdateInfo:
    """下载并解析更新清单（网络/解析异常统一抛 UpdateError）。"""
    target = url or Config.UPDATE_URL
    # 优先用 certifi 根证书（打包环境或系统证书库缺失时会校验失败）
    try:
        import certifi
        ssl_context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ssl_context = ssl.create_default_context()

    request = urllib.request.Request(target)
    request.add_header("User-Agent", Config.APP_NAME)
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=ssl_context) as response:
            body = response.read().decode("utf-8", errors="replace")
    except Exception as e:
        raise UpdateError(tr("无法获取更新清单: {err}", err=e)) from e
    return parse_manifest(body)


def updates_dir() -> Path:
    """安装包缓存目录（配置目录下的 updates/，不存在时创建）。"""
    path = store.config_path().parent / "updates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def package_path(info: UpdateInfo) -> Path:
    """安装包在本机的缓存路径，按版本命名。"""
    safe = re.sub(r"[^0-9A-Za-z._-]", "_", info.version) or "latest"
    return updates_dir() / f"GiTool_Setup_{safe}.exe"


def download_package(info: UpdateInfo,
                     progress: Optional[Callable[[int, int], None]] = None,
                     cancel=None,
                     on_verify: Optional[Callable[[], None]] = None) -> Path:
    """下载安装包到缓存目录并校验 sha256，返回落地路径。

    progress(done, total)：total 为 0 表示长度未知；cancel 为 threading.Event，
    置位后抛 UpdateError（已下载部分保留为 .part，供下次续传）。
    on_verify()：字节下载完成、开始 sha256 校验前回调，供界面切换提示。
    """
    url = info.url_for(ui_language())
    if not url:
        raise UpdateError(tr("更新清单未提供下载地址"))
    if not _SHA256_RE.fullmatch(info.sha256):
        raise UpdateError(tr("更新清单缺少合法的 win_sha256（需 64 位十六进制）"))

    target = package_path(info)
    part = target.with_name(target.name + ".part")
    target.unlink(missing_ok=True)

    existing = part.stat().st_size if part.exists() else 0
    headers = {"User-Agent": Config.APP_NAME}
    if existing:
        headers["Range"] = f"bytes={existing}-"

    request = urllib.request.Request(url, headers=headers)
    try:
        response = urllib.request.urlopen(request, timeout=20)
    except Exception as e:
        raise UpdateError(tr("无法下载安装包: {err}", err=e)) from e

    with response:
        status = getattr(response, "status", 200)
        if existing and status != 206:
            existing = 0  # 服务端不支持断点续传，从头写入
        content_length = int(response.headers.get("Content-Length") or 0)
        total = (existing + content_length) if existing else (content_length or (info.size or 0))
        done = existing
        if progress:
            progress(done, total)

        mode = "ab" if existing else "wb"
        with open(part, mode) as fh:
            while True:
                if cancel is not None and cancel.is_set():
                    raise UpdateError(tr("已取消下载"))
                chunk = response.read(CHUNK_SIZE)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)

    if info.size and done != info.size:
        part.unlink(missing_ok=True)
        raise UpdateError(tr("安装包大小不符: 期望 {expected}，实际 {actual}",
                             expected=info.size, actual=done))

    if on_verify:
        on_verify()

    digest = hashlib.sha256()
    with open(part, "rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    if digest.hexdigest().lower() != info.sha256.lower():
        part.unlink(missing_ok=True)
        raise UpdateError(tr("安装包校验失败（sha256 不匹配）"))

    os.replace(part, target)
    return target


def clear_cache():
    """清空更新缓存目录（程序启动时调用）；失败静默忽略。"""
    directory = updates_dir()
    for entry in directory.iterdir():
        try:
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                entry.unlink(missing_ok=True)
        except OSError:
            pass
