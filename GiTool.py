import ctypes
import os
import struct
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from src.core import i18n, store, theme
from src.core.config import Config
from src.ui.window import AppWindow, apply_style

# Windows 任务栏按 AppUserModelID 归组并取图标；不设置时会把进程归到 python.exe，
# 任务栏显示的仍是 Python 的图标。打包后同样生效。
_APP_ID = "GiTool.PushGate"

_IMAGE_ICON = 1
_LR_LOADFROMFILE = 0x0010
_WM_SETICON = 0x0080
_ICON_SMALL, _ICON_BIG = 0, 1
_SM_CXICON, _SM_CXSMICON = 11, 49


def _set_app_id() -> None:
    """给进程一个独立 AppUserModelID（须在建窗前调用）。"""
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(_APP_ID)
    except Exception:
        pass


def _icon_path() -> str | None:
    """icon.ico 的绝对路径：源码运行取脚本目录，打包后取可执行文件目录。"""
    bases = (os.path.dirname(os.path.abspath(sys.argv[0] or __file__)),
             os.path.dirname(os.path.abspath(__file__)))
    for base in bases:
        path = os.path.join(base, "icon.ico")
        if os.path.isfile(path):
            return path
    return None


def _ico_sizes(path: str) -> list[int]:
    """ico 目录里各帧的边长（目录项为 0 表示 256）。"""
    try:
        with open(path, "rb") as fh:
            head = fh.read(6)
            if len(head) < 6:
                return []
            count = struct.unpack_from("<H", head, 4)[0]
            entries = fh.read(count * 16)
    except OSError:
        return []
    sizes = []
    for i in range(count):
        offset = i * 16
        if offset + 1 > len(entries):
            break
        sizes.append(entries[offset] or 256)
    return sizes


def _frame_for(sizes: list[int], want: int) -> int:
    """选不小于目标的最小帧；都不够就用最大帧——只缩小不放大，避免发糊。"""
    if not sizes:
        return want
    bigger = [s for s in sizes if s >= want]
    return min(bigger) if bigger else max(sizes)


def _apply_taskbar_icon(window, path: str) -> None:
    """按系统实际请求的像素尺寸从 ico 取帧，绕开 Qt 的 DPI 换算后再缩放。

    Qt 生成窗口 HICON 时会按设备像素比放大逻辑尺寸，Windows 再缩回任务栏槽位，
    小图标因此发糊；这里直接给 Windows 一张尺寸准确的帧。
    """
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.LoadImageW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint,
                                      ctypes.c_int, ctypes.c_int, ctypes.c_uint]
        user32.LoadImageW.restype = ctypes.c_void_p
        user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                        ctypes.c_void_p, ctypes.c_void_p]
        hwnd = int(window.winId())
        sizes = _ico_sizes(path)
        for kind, metric in ((_ICON_SMALL, _SM_CXSMICON), (_ICON_BIG, _SM_CXICON)):
            want = int(user32.GetSystemMetrics(metric) or 16)
            frame = _frame_for(sizes, want)
            hicon = user32.LoadImageW(None, path, _IMAGE_ICON, frame, frame,
                                      _LR_LOADFROMFILE)
            if hicon:
                user32.SendMessageW(hwnd, _WM_SETICON, kind, hicon)
    except Exception:
        pass


def _restore_prefs():
    """启动时恢复上次保存的外观偏好，须在建窗前调用。"""
    data = store.load()
    if isinstance(data.get("style"), str):
        theme.set_style(data["style"])
    if isinstance(data.get("theme"), str):
        theme.set_theme(data["theme"])


def _clean_update_cache():
    """启动时清空上次下载的更新包，失败不影响启动。"""
    try:
        from src.core.update import clear_cache
        clear_cache()
    except Exception:
        pass


def main():
    _set_app_id()
    app = QApplication(sys.argv)
    app.setApplicationName(Config.APP_NAME)
    _restore_prefs()
    i18n.initialize()
    _clean_update_cache()
    app.setStyleSheet(apply_style())

    path = _icon_path()
    if path:
        app.setWindowIcon(QIcon(path))

    win = AppWindow()
    win.show()
    if path:
        _apply_taskbar_icon(win, path)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
