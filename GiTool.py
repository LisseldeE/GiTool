import os
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from src.core import store, theme
from src.core.config import Config
from src.ui.window import AppWindow, apply_style


def _load_app_icon(app):
    """从项目根目录加载 icon.ico 作为应用/窗口图标；文件缺失时静默跳过。"""
    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
    if os.path.isfile(icon_path):
        app.setWindowIcon(QIcon(icon_path))


def _restore_prefs():
    """启动时恢复上次保存的外观偏好，须在建窗前调用。"""
    data = store.load()
    if isinstance(data.get("style"), str):
        theme.set_style(data["style"])
    if isinstance(data.get("theme"), str):
        theme.set_theme(data["theme"])


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(Config.APP_NAME)
    _restore_prefs()
    app.setStyleSheet(apply_style())
    _load_app_icon(app)

    win = AppWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()