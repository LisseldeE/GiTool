"""
更新对话框
展示新版本与更新日志，下载安装包并在完成后启动安装程序。
Copyright (c) 2026 Lisselde_E <Lisselde.E@outlook.com>.
Licensed under the GNU General Public License v3.0.
"""
import subprocess
import threading
from html import escape
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QTextBrowser, QVBoxLayout,
)

from ..core import theme
from ..core.config import Config
from ..core.i18n import tr
from ..core.update import UpdateInfo, download_package


def _is_dark(widget) -> bool:
    """是否为深色主题：优先用设置中的深浅色模式，跟随系统时回退到调色板。"""
    ov = theme.dark_override()
    if ov is not None:
        return ov
    return widget.palette().color(QPalette.ColorRole.Window).lightness() < 128


class UpdateDialog(QDialog):
    """新版本详情：版本号 + 更新日志 + 下载进度；完成后退出并启动安装包。"""

    progress_changed = Signal(int, int)  # (已下载字节, 总字节；0 表未知)
    verify_changed = Signal()            # 字节下载完成，进入 sha256 校验
    download_done = Signal(object)       # Path（成功）或 Exception（失败）

    def __init__(self, info: UpdateInfo, parent=None):
        super().__init__(parent)
        self._info = info
        self._cancel = threading.Event()
        self._thread = None
        self._closed = False
        self.setWindowTitle(tr("{name} 更新", name=Config.APP_NAME))
        self.setWindowFlags(Qt.Dialog | Qt.WindowCloseButtonHint)
        self.setFixedSize(520, 470)
        self._init_ui()
        self.progress_changed.connect(self._on_progress)
        self.verify_changed.connect(self._on_verify)
        self.download_done.connect(self._on_download_done)

    def _init_ui(self):
        dark = _is_dark(self)
        accent = theme.st("accent", dark)
        accent_hover = accent.lighter(112)
        title_col = theme.st("title_text", dark).name()
        sub_col = theme.st("sub_text", dark).name()
        border = theme.st("panel_border", dark).name()
        self.setStyleSheet(f"""
            QDialog {{ background: {theme.st("content_bg", dark).name()}; }}
            QLabel {{ background: transparent; }}
            QLabel#UpdateTitle {{ color: {accent.name()}; font-size: 16pt; font-weight: bold; }}
            QLabel#UpdateSub, QLabel#UpdateStatus {{
                color: {sub_col}; font-size: 9pt;
            }}
            QLabel#UpdateLogTitle {{ color: {title_col}; font-size: 10pt; font-weight: bold; }}
            QTextBrowser {{
                background: transparent; border: none; color: {title_col}; font-size: 10pt;
            }}
            QProgressBar {{ background: {border}; border: none; border-radius: 4px; }}
            QProgressBar::chunk {{ background: {accent.name()}; border-radius: 4px; }}
            QPushButton {{
                min-width: 108px; min-height: 34px;
                border-radius: 8px; font-size: 10pt;
            }}
            QPushButton#Secondary {{
                background: transparent; border: 1px solid {border}; color: {title_col};
            }}
            QPushButton#Secondary:hover {{ border-color: {accent.name()}; color: {accent.name()}; }}
            QPushButton#Primary {{
                background: {accent.name()}; border: none; color: #ffffff;
            }}
            QPushButton#Primary:hover {{ background: {accent_hover.name()}; }}
            QPushButton:disabled {{ color: {sub_col}; background: transparent;
                                    border: 1px solid {border}; }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        title = QLabel(tr("发现新版本 {version}", version=self._info.version))
        title.setObjectName("UpdateTitle")
        layout.addWidget(title)

        current = QLabel(tr("当前版本 {version}", version=Config.APP_VERSION))
        current.setObjectName("UpdateSub")
        layout.addWidget(current)

        log_title = QLabel(tr("更新内容"))
        log_title.setObjectName("UpdateLogTitle")
        layout.addSpacing(4)
        layout.addWidget(log_title)

        self._log_view = QTextBrowser()
        self._log_view.setOpenLinks(False)
        if self._info.changelog:
            self._log_view.setHtml("".join(
                f'<p style="margin:4px 0;">· {escape(item)}</p>'
                for item in self._info.changelog))
        else:
            self._log_view.setPlainText(tr("暂无更新说明"))
        layout.addWidget(self._log_view, 1)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(8)
        layout.addWidget(self._progress)

        self._status = QLabel(tr("下载后会自动校验安装包并启动安装程序，安装期间程序将退出。"))
        self._status.setObjectName("UpdateStatus")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._cancel_btn = QPushButton(tr("取消"))
        self._cancel_btn.setObjectName("Secondary")
        self._cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self._cancel_btn)

        btn_layout.addSpacing(8)

        self._download_btn = QPushButton(tr("立即更新"))
        self._download_btn.setObjectName("Primary")
        self._download_btn.clicked.connect(self._start_download)
        btn_layout.addWidget(self._download_btn)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

    # ---- 下载 ----

    def _start_download(self):
        if self._thread and self._thread.is_alive():
            return
        self._download_btn.setEnabled(False)
        self._progress.setVisible(True)
        self._progress.setRange(0, 0)
        self._status.setText(tr("正在连接下载地址…"))
        self._cancel.clear()
        self._thread = threading.Thread(target=self._worker, daemon=True,
                                        name="gitool-update-download")
        self._thread.start()

    def _worker(self):
        try:
            path = download_package(
                self._info,
                progress=lambda done, total: self.progress_changed.emit(done, total),
                cancel=self._cancel,
                on_verify=lambda: self.verify_changed.emit())
        except Exception as e:
            self.download_done.emit(e)
            return
        self.download_done.emit(path)

    def _on_progress(self, done: int, total: int):
        if total > 0:
            percent = min(int(done * 100 / total), 100)
            self._progress.setRange(0, 100)
            self._progress.setValue(percent)
            self._status.setText(tr("正在下载… {percent}%", percent=percent))
        else:
            self._progress.setRange(0, 0)
            self._status.setText(tr("正在下载…"))

    def _on_verify(self):
        """字节下载完成，进入 sha256 校验（安装包较大时需要一点时间）"""
        self._progress.setRange(0, 100)
        self._progress.setValue(100)
        self._status.setText(tr("正在校验安装包…"))

    def _on_download_done(self, result):
        if self._closed:
            return
        if isinstance(result, Path):
            self._progress.setRange(0, 100)
            self._progress.setValue(100)
            self._status.setText(tr("正在启动安装程序…"))
            QTimer.singleShot(400, lambda: self._launch_installer(result))
            return

        # 失败：按钮改为重试，小字说明原因
        self._download_btn.setEnabled(True)
        self._download_btn.setText(tr("重试"))
        self._progress.setVisible(False)
        self._status.setText(tr("更新失败：{err}", err=result))

    def _launch_installer(self, path: Path):
        """延迟拉起安装包再退出主程序：安装器启动时旧 exe 已释放，避免文件占用。

        静默参数：不显示向导；安装器内部会静默卸载旧版并全量安装，结束后由
        [Run] 自行启动新版主程序（这里无需再计算安装路径）。
        """
        if self._closed:
            return
        command = (f'cmd /c ping -n 3 127.0.0.1 >nul & start "" "{path}" '
                   f'/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-')
        try:
            subprocess.Popen(
                command, shell=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as e:
            self._status.setText(tr("更新失败：{err}", err=e))
            self._download_btn.setEnabled(True)
            return
        # 模态对话框的 exec 循环不会被 QApplication.quit() 打断：先结束对话框，
        # 回到主事件循环后再退出，确保进程在安装器启动前释放 exe/文件句柄。
        self.accept()
        QTimer.singleShot(0, QApplication.quit)

    def reject(self):
        self._closed = True
        self._cancel.set()
        super().reject()
