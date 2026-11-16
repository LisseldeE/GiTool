"""
仓库详情页
配置远程仓库、选择批量推送目标，并执行推送 / 抓取 / 拉取。
Copyright (c) 2026 Lisselde_E <Lisselde.E@outlook.com>.
Licensed under the GNU General Public License v3.0.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from PySide6.QtCore import (
    QEvent, QPointF, QProcess, QRect, QRectF, Qt, QTimer, Signal,
)
from PySide6.QtGui import (
    QColor, QFont, QFontMetrics, QKeySequence, QPainter, QPen, QShortcut,
)
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QScrollArea, QSizePolicy, QVBoxLayout,
    QWidget,
)

from ..core import gitrepo, store, theme
from ..core.gitrepo import RepoInfo
from ..core.i18n import tr
from .repo_page import (
    OverlayScrollBar, PillButton, _BAR_H, _PANEL_TOP, _SUB_PT, _TITLE_PT,
    _brief_error, _elide, _is_dark, scan_service,
)

_GREEN = QColor("#2fb95a")
_RED = QColor("#e5534b")
_ORANGE = QColor("#d99036")

_NAME_RE = re.compile(r"[A-Za-z0-9._-]+")


def _push_reason(text: str) -> str:
    """把 push --porcelain 的输出变成一句人话。"""
    low = text.lower()
    if "non-fast-forward" in low or "[rejected]" in low:
        return tr("远端有新的提交，请先拉取")
    if "permission denied" in low or "authentication failed" in low:
        return tr("没有推送权限，请检查凭据")
    return _brief_error(text.lstrip("! "))


class BackButton(QWidget):
    """面板顶栏里的返回按钮：箭头 + 文字。"""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hover = False
        self.setFixedSize(72, 28)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tr("返回仓库列表（Esc）"))

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = _is_dark(self)
        accent = theme.st("accent", dark)
        if self._hover:
            bg = QColor(accent)
            bg.setAlpha(24 if dark else 18)
            p.setPen(Qt.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(QRectF(self.rect()), 6, 6)

        p.setPen(QPen(accent, 1.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        cy = self.height() / 2
        p.drawLine(QPointF(16, cy - 6), QPointF(10, cy))
        p.drawLine(QPointF(10, cy), QPointF(16, cy + 6))

        f = QFont(self.font())
        f.setPointSize(9)
        p.setFont(f)
        p.setPen(accent)
        p.drawText(QRectF(24, 0, self.width() - 24, self.height()),
                   Qt.AlignVCenter | Qt.AlignLeft, tr("返回"))
        p.end()


class MiniButton(QWidget):
    """行内与顶栏的轻量按钮：细边框，悬停时染主题色。"""

    clicked = Signal()

    H = 26

    def __init__(self, text: str, danger: bool = False, primary: bool = False,
                 parent=None):
        super().__init__(parent)
        self.text = text
        self.danger = danger
        self.primary = primary
        self._hover = False
        self._enabled = True
        self._armed = False
        self.set_text(text)
        self.setCursor(Qt.PointingHandCursor)

    def set_text(self, text: str):
        """热切换语言时更新文字，并按文字宽度调整按钮尺寸。"""
        self.text = text
        f = QFont(self.font())
        f.setPointSize(8)
        w = QFontMetrics(f).horizontalAdvance(text) + 22
        self.setFixedSize(max(44, w), self.H)
        self.update()

    def set_enabled(self, enabled: bool):
        if self._enabled == enabled:
            return
        self._enabled = enabled
        self._hover = False
        self.setCursor(Qt.PointingHandCursor if enabled else Qt.ArrowCursor)
        self.update()

    def set_armed(self, armed: bool):
        """危险操作进入「再次点击确认」状态时的红色描边。"""
        if self._armed == armed:
            return
        self._armed = armed
        self.update()

    def enterEvent(self, e):
        self._hover = self._enabled
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        if (self._enabled and e.button() == Qt.LeftButton
                and self.rect().contains(e.position().toPoint())):
            self.clicked.emit()
        super().mouseReleaseEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self._enabled:
            p.setOpacity(0.35)
        dark = _is_dark(self)
        accent = theme.st("accent", dark)
        if self.primary:
            fill = accent.lighter(112) if self._hover else accent
            p.setPen(Qt.NoPen)
            p.setBrush(fill)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
            color = QColor("#ffffff")
        else:
            border = _RED if self._armed else (
                accent if self._hover else theme.st("panel_border", dark))
            p.setPen(QPen(border, 1))
            if self._hover:
                bg = QColor(accent)
                bg.setAlpha(20 if dark else 14)
                p.setBrush(bg)
            else:
                p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
            color = _RED if (self.danger or self._armed) else (
                accent if self._hover else theme.st("title_text", dark))

        f = QFont(self.font())
        f.setPointSize(8)
        p.setFont(f)
        p.setPen(color)
        p.drawText(QRectF(self.rect()), Qt.AlignCenter, self.text)
        p.end()


class RemoteRow(QWidget):
    """一行远程仓库：目标圆点 + 名称/地址 + 状态 + 抓取/推送/拉取/编辑/删除。"""

    H = 62

    target_toggled = Signal(str)
    fetch_requested = Signal(str)
    push_requested = Signal(str)
    pull_requested = Signal(str)
    edit_requested = Signal(str)
    remove_requested = Signal(str)

    _BUTTON_ORDER = ("fetch", "push", "pull", "edit", "remove")

    def __init__(self, name: str, url: str, status: str, status_color: QColor,
                 target: bool, parent=None):
        super().__init__(parent)
        self.name, self.url = name, url
        self.status, self.status_color = status, status_color
        self.target = target
        self._hover = False
        self._busy = False
        self._buttons: dict[str, MiniButton] = {
            "fetch": MiniButton(tr("抓取"), parent=self),
            "push": MiniButton(tr("推送"), parent=self),
            "pull": MiniButton(tr("拉取"), parent=self),
            "edit": MiniButton(tr("编辑"), parent=self),
            "remove": MiniButton(tr("删除"), danger=True, parent=self),
        }
        self.retranslate_tips()
        self._buttons["fetch"].clicked.connect(lambda: self.fetch_requested.emit(self.name))
        self._buttons["push"].clicked.connect(lambda: self.push_requested.emit(self.name))
        self._buttons["pull"].clicked.connect(lambda: self.pull_requested.emit(self.name))
        self._buttons["edit"].clicked.connect(lambda: self.edit_requested.emit(self.name))
        self._buttons["remove"].clicked.connect(lambda: self.remove_requested.emit(self.name))
        self.setFixedHeight(self.H)
        self.setMouseTracking(True)
        self.setToolTip(f"{name}：{url}")

    H_LABELS = {
        "fetch": "抓取", "push": "推送", "pull": "拉取",
        "edit": "编辑", "remove": "删除",
    }

    def retranslate_tips(self):
        """更新按钮提示；按钮文字在 retranslate 里更新。"""
        self._buttons["fetch"].setToolTip("git fetch --prune")
        self._buttons["push"].setToolTip(tr("推送当前分支到该远程"))
        self._buttons["pull"].setToolTip(tr("git pull --ff-only（只允许快进）"))
        self._buttons["edit"].setToolTip(tr("修改远程地址"))
        self._buttons["remove"].setToolTip(tr("移除该远程（需再次点击确认）"))

    def retranslate(self):
        """热切换语言后更新按钮文字与提示，并重新排布。"""
        for key, label in self.H_LABELS.items():
            self._buttons[key].set_text(tr(label))
        self.retranslate_tips()
        self.setToolTip(f"{self.name}：{self.url}")
        self._place_buttons()

    # ---------- 状态 ----------
    def set_target(self, target: bool):
        self.target = target
        self.update()

    def set_busy(self, busy: bool):
        self._busy = busy
        self._hover = False
        for btn in self._buttons.values():
            btn.set_enabled(not busy)
        self.setCursor(Qt.ArrowCursor)
        self.update()

    def set_remove_armed(self, armed: bool):
        self._buttons["remove"].set_armed(armed)

    # ---------- 交互 ----------
    def _target_rect(self) -> QRectF:
        return QRectF(10, (self.height() - 30) / 2, 32, 30)

    def mouseMoveEvent(self, e):
        hot = not self._busy and self._target_rect().contains(e.position())
        self.setCursor(Qt.PointingHandCursor if hot else Qt.ArrowCursor)
        if hot != self._hover:
            self._hover = hot
            self.update()
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        if (not self._busy and e.button() == Qt.LeftButton
                and self._target_rect().contains(e.position())):
            self.target_toggled.emit(self.name)
        super().mouseReleaseEvent(e)

    # ---------- 绘制 ----------
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self._busy:
            p.setOpacity(0.55)
        dark = _is_dark(self)
        w, h = self.width(), self.height()

        if self._hover:
            p.setPen(Qt.NoPen)
            p.setBrush(theme.st("nav_hover", dark))
            p.drawRoundedRect(QRectF(6, 2, w - 12, h - 4), 8, 8)

        # 批量推送目标圆点
        accent = theme.st("accent", dark)
        circle = QRectF(18, h / 2 - 8, 16, 16)
        if self.target:
            p.setPen(Qt.NoPen)
            p.setBrush(accent)
            p.drawEllipse(circle)
            p.setPen(QPen(QColor("#ffffff"), 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawLine(QPointF(22, h / 2), QPointF(25, h / 2 + 3))
            p.drawLine(QPointF(25, h / 2 + 3), QPointF(30, h / 2 - 4))
        else:
            border = QColor(theme.st("sub_text", dark))
            border.setAlpha(150)
            p.setPen(QPen(border, 1.2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(circle)

        # 名称与地址
        left = 46
        right = self._buttons["fetch"].x() - 10
        if right <= left:
            # 首次布局前还没有按钮几何，先按右对齐估算，避免文字画到按钮上
            right = w - 260
        p.setFont(self._name_font())
        p.setPen(theme.st("title_text", dark))
        p.drawText(QRectF(left, 10, max(0, right - left - 96), 20),
                   Qt.AlignVCenter | Qt.AlignLeft,
                   _elide(p, self.name, max(0, right - left - 96)))

        f = QFont(self.font())
        f.setPointSize(8)
        p.setFont(f)
        p.setPen(theme.st("sub_text", dark))
        p.drawText(QRectF(left, 32, max(0, right - left), 16),
                   Qt.AlignVCenter | Qt.AlignLeft,
                   _elide(p, self.url, max(0, right - left)))

        # 状态（贴在按钮左侧）
        p.setPen(self.status_color)
        p.drawText(QRectF(right - 86, 10, 86, 20),
                   Qt.AlignVCenter | Qt.AlignRight, self.status)

        # 底部细分隔线
        p.setPen(theme.st("panel_border", dark))
        p.drawLine(46, h - 1, w - 14, h - 1)
        p.end()

    def _name_font(self) -> QFont:
        f = QFont(self.font())
        f.setPointSize(10)
        f.setBold(True)
        return f

    def _place_buttons(self):
        x = self.width() - 14
        for key in reversed(self._BUTTON_ORDER):
            btn = self._buttons[key]
            x -= btn.width()
            btn.move(x, (self.height() - btn.height()) // 2)
            x -= 4

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_buttons()


class RemoteEditor(QWidget):
    """内联的远程编辑条：名称 + 地址 + 保存/取消，避免弹窗打断操作。"""

    saved = Signal(str, str)
    cancelled = Signal()

    H = 46

    def __init__(self, parent=None):
        super().__init__(parent)
        self.name_locked = False
        self.name_edit = QLineEdit(self)
        self.name_edit.setPlaceholderText(tr("名称，例如 origin"))
        self.name_edit.setFixedWidth(120)
        self.url_edit = QLineEdit(self)
        self.url_edit.setPlaceholderText(
            tr("地址，例如 https://github.com/user/repo.git"))

        lay = QHBoxLayout(self)
        lay.setContentsMargins(46, 0, 14, 0)
        lay.setSpacing(8)
        lay.addWidget(self.name_edit)
        lay.addWidget(self.url_edit, 1)
        self.cancel_btn = MiniButton(tr("取消"), parent=self)
        self.save_btn = MiniButton(tr("保存"), primary=True, parent=self)
        self.cancel_btn.clicked.connect(self.cancelled)
        self.save_btn.clicked.connect(self._emit_save)
        lay.addWidget(self.cancel_btn)
        lay.addWidget(self.save_btn)
        self.url_edit.returnPressed.connect(self._emit_save)
        self.setFixedHeight(self.H)
        self.hide()

    def open(self, name: str, url: str, name_locked: bool):
        self.name_locked = name_locked
        self.name_edit.setText(name)
        self.url_edit.setText(url)
        self.name_edit.setReadOnly(name_locked)
        self.name_edit.setEnabled(not name_locked)
        self.show()
        if name_locked:
            self.url_edit.setFocus()
        else:
            self.name_edit.setFocus()
        self.url_edit.setCursorPosition(len(url))

    def _emit_save(self):
        self.saved.emit(self.name_edit.text(), self.url_edit.text())

    def retranslate(self):
        """热切换语言后更新占位提示与按钮文字。"""
        self.name_edit.setPlaceholderText(tr("名称，例如 origin"))
        self.url_edit.setPlaceholderText(
            tr("地址，例如 https://github.com/user/repo.git"))
        self.cancel_btn.set_text(tr("取消"))
        self.save_btn.set_text(tr("保存"))


class StatGrid(QWidget):
    """详情页顶部的四格概览。"""

    H = 84

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[tuple[str, str, QColor | None]] = []
        self.setFixedHeight(self.H)

    def set_items(self, items: list[tuple[str, str, QColor | None]]):
        self._items = list(items)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = _is_dark(self)
        w = self.width()
        n = max(1, len(self._items))
        cw = w / n
        for i, (label, value, color) in enumerate(self._items):
            x = i * cw
            if i:
                p.setPen(theme.st("panel_border", dark))
                p.drawLine(QRectF(x, 18, 0, 0).topLeft(), QRectF(x, self.H - 18, 0, 0).topLeft())

            f = QFont(self.font())
            f.setPointSize(8)
            p.setFont(f)
            p.setPen(theme.st("sub_text", dark))
            p.drawText(QRectF(x + 18, 16, cw - 26, 16),
                       Qt.AlignVCenter | Qt.AlignLeft, label)

            f.setPointSize(11)
            f.setBold(True)
            p.setFont(f)
            p.setPen(color if color is not None else theme.st("title_text", dark))
            p.drawText(QRectF(x + 18, 38, cw - 26, 24),
                       Qt.AlignVCenter | Qt.AlignLeft,
                       _elide(p, value, cw - 26))
        p.end()


class RepoDetailPage(QWidget):
    """仓库详情：远程配置 + 批量推送目标 + 推送/抓取/拉取。"""

    back_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self._path: Path | None = None
        self._repo: RepoInfo | None = None
        self._remotes: list[tuple[str, str]] = []
        self._rows: dict[str, RemoteRow] = {}
        self._targets: set[str] = set()
        self._busy = False
        self._proc: QProcess | None = None
        self._after_proc = None
        self._queue: list[str] = []
        self._failures: list[str] = []
        self._armed: str | None = None
        self._status_text = ""
        self._status_kind = "idle"
        self._hint: QLabel | None = None
        self._bar_text_right = 0

        self.back_btn = BackButton(self)
        self.back_btn.clicked.connect(self._on_back)
        self.open_btn = MiniButton(tr("打开目录"), parent=self)
        self.open_btn.setToolTip(tr("在资源管理器中打开仓库目录"))
        self.open_btn.clicked.connect(self._open_folder)
        self.fetch_btn = MiniButton(tr("抓取全部"), parent=self)
        self.fetch_btn.setToolTip(tr("git fetch --prune（刷新所有远程的领先/落后统计）"))
        self.fetch_btn.clicked.connect(self._fetch_all)
        self.refresh_btn = MiniButton(tr("刷新"), parent=self)
        self.refresh_btn.setToolTip(tr("重新读取本地状态（不发网络请求）"))
        self.refresh_btn.clicked.connect(self._reload)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.viewport().setAutoFillBackground(False)
        self._vbar = OverlayScrollBar(self.scroll)
        self.scroll.installEventFilter(self)

        self.content = QWidget()
        self.content.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(self.content)
        lay.setContentsMargins(0, 10, 0, 16)
        lay.setSpacing(0)
        self.overview = StatGrid(self.content)
        lay.addWidget(self.overview)
        lay.addSpacing(12)

        head = QWidget(self.content)
        hl = QHBoxLayout(head)
        hl.setContentsMargins(18, 0, 14, 0)
        hl.setSpacing(8)
        self.sec_title = QLabel(tr("远程仓库"), head)
        self.sec_hint = QLabel(tr("点左侧圆点加入批量推送目标"), head)
        # 英文提示更长：不让 QLabel 的文本宽度撑宽整页，空间不足时直接裁切
        self.sec_hint.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        hl.addWidget(self.sec_title, 0, Qt.AlignVCenter)
        hl.addSpacing(6)
        hl.addWidget(self.sec_hint, 1, Qt.AlignVCenter)
        self.add_btn = MiniButton(tr("添加远程"), parent=head)
        self.push_all_btn = PillButton(tr("推送全部目标"), head)
        self.push_all_btn.clicked.connect(self._push_all)
        hl.addWidget(self.add_btn, 0, Qt.AlignVCenter)
        hl.addWidget(self.push_all_btn, 0, Qt.AlignVCenter)
        self.add_btn.clicked.connect(self._add_remote)
        head.setFixedHeight(44)
        lay.addWidget(head)

        self.remotes_host = QWidget(self.content)
        self.remotes_lay = QVBoxLayout(self.remotes_host)
        self.remotes_lay.setContentsMargins(0, 0, 0, 0)
        self.remotes_lay.setSpacing(0)
        lay.addWidget(self.remotes_host)

        self.editor = RemoteEditor(self.content)
        self.editor.saved.connect(self._save_remote)
        self.editor.cancelled.connect(self.editor.hide)
        lay.addWidget(self.editor)
        lay.addStretch(1)

        self.scroll.setWidget(self.content)

        self._arm_timer = QTimer(self)
        self._arm_timer.setSingleShot(True)
        self._arm_timer.setInterval(2600)
        self._arm_timer.timeout.connect(self._disarm)

        self._esc = QShortcut(QKeySequence("Escape"), self)
        self._esc.setContext(Qt.WindowShortcut)
        self._esc.activated.connect(self._on_back)

        f = QFont(self.font())
        f.setPointSize(10)
        f.setBold(True)
        self.sec_title.setFont(f)

        self.apply_style()
        self._refresh_overview()
        self._refresh_buttons()

    # ---------- 打开 / 刷新 ----------
    def open_repo(self, target):
        """target 可以是 RepoInfo 或仓库路径。"""
        path = target.path if isinstance(target, RepoInfo) else Path(str(target))
        self._path = Path(path)
        self._disarm()
        self.editor.hide()
        self._status_text = ""
        self._status_kind = "idle"
        self._reload()
        self.setFocus()

    def showEvent(self, e):
        super().showEvent(e)
        self._vbar.resize_to_area()
        if not self._busy:
            self._reload()

    def eventFilter(self, obj, ev):
        if obj is self.scroll and ev.type() == QEvent.Resize:
            self._vbar.resize_to_area()
        return super().eventFilter(obj, ev)

    def _reload(self, info: RepoInfo | None = None):
        if self._path is None:
            return
        # 重建行会丢掉「再次点击删除」的待确认状态，先统一复位
        self._disarm()
        self._repo = info if info is not None else gitrepo.read_repo(self._path)
        self._remotes = gitrepo.remote_entries(self._path) if self._repo else []
        if self._repo is None:
            self._set_status(tr("无法读取该仓库：目录不存在或不是 git 仓库"), "error")
        self._load_targets()
        self._rebuild_rows()
        self._refresh_overview()
        self._refresh_buttons()
        self._vbar.resize_to_area()
        self.update()

    def _load_targets(self):
        names = [n for n, _ in self._remotes]
        saved = store.push_remotes(str(self._path))
        if saved is None:
            default = "origin" if "origin" in names else (names[0] if names else None)
            self._targets = {default} if default else set()
        else:
            self._targets = {n for n in saved if n in names}

    def _save_targets(self):
        if self._path is None:
            return
        order = [n for n, _ in self._remotes if n in self._targets]
        store.save_push_remotes(str(self._path), order)

    def _remote_branch(self, name: str):
        if self._repo is None:
            return None
        return next((r for r in self._repo.remotes if r.remote == name), None)

    def _status_of(self, name: str) -> tuple[str, QColor]:
        dark = _is_dark(self)
        rb = self._remote_branch(name)
        if rb is None:
            return "", theme.st("sub_text", dark)
        if not rb.exists:
            return tr("未推送"), _ORANGE
        if rb.ahead and rb.behind:
            return f"↑{rb.ahead} ↓{rb.behind}", _GREEN
        if rb.ahead:
            return f"↑{rb.ahead}", _GREEN
        if rb.behind:
            return f"↓{rb.behind}", _ORANGE
        return tr("已同步"), _GREEN

    # ---------- 列表重建 ----------
    def _rebuild_rows(self):
        while self.remotes_lay.count():
            item = self.remotes_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._rows.clear()
        self._hint = None

        if not self._remotes:
            hint = QLabel(
                tr("还没有远程仓库。点击右上角「添加远程」填写名称与地址，"
                   "之后就能在这里推送、拉取。"), self.remotes_host)
            hint.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            hint.setWordWrap(True)
            hint.setContentsMargins(46, 12, 24, 14)
            self.remotes_lay.addWidget(hint)
            self._hint = hint
            self._style_hint()
            return

        for name, url in self._remotes:
            text, color = self._status_of(name)
            row = RemoteRow(name, url, text, color, name in self._targets,
                            self.remotes_host)
            row.target_toggled.connect(self._toggle_target)
            row.fetch_requested.connect(self._fetch_one)
            row.push_requested.connect(self._push_one)
            row.pull_requested.connect(self._pull)
            row.edit_requested.connect(self._edit_remote)
            row.remove_requested.connect(self._remove_remote)
            row.set_busy(self._busy)
            self.remotes_lay.addWidget(row)
            self._rows[name] = row

    def _refresh_overview(self):
        if self._repo is None:
            self.overview.set_items([
                (tr("状态"), tr("无法读取该仓库"), _RED),
                (tr("当前分支"), "—", None),
                ("HEAD", "—", None),
                (tr("批量推送目标"), "—", None),
            ])
            return
        dirty = self._repo.dirty
        self.overview.set_items([
            (tr("当前分支"), self._repo.branch or "—", None),
            ("HEAD", self._repo.head_short or "—", None),
            (tr("工作区"), tr("有未提交改动") if dirty else tr("干净"),
             _ORANGE if dirty else None),
            (tr("批量推送目标"), f"{len(self._targets)} / {len(self._remotes)}", None),
        ])

    def _refresh_buttons(self):
        detached = self._repo is not None and self._repo.detached
        self.add_btn.set_enabled(not self._busy)
        self.fetch_btn.set_enabled(not self._busy and bool(self._remotes))
        self.refresh_btn.set_enabled(not self._busy)
        self.open_btn.set_enabled(not self._busy and self._path is not None)
        self.push_all_btn.set_accept(
            not self._busy and bool(self._targets) and not detached
            and self._repo is not None)

    def _set_busy(self, busy: bool):
        self._busy = busy
        for row in self._rows.values():
            row.set_busy(busy)
        self.editor.setEnabled(not busy)
        self._refresh_buttons()
        self.update()

    def _set_status(self, text: str, kind: str):
        self._status_text, self._status_kind = text, kind
        self.update()

    # ---------- 几何 ----------
    def _panel_rect(self) -> QRect:
        return QRect(30, _PANEL_TOP, max(0, self.width() - 60),
                     max(0, self.height() - _PANEL_TOP - 28))

    def _place_top_buttons(self):
        panel = self._panel_rect()
        self.back_btn.move(panel.left() + 10, panel.top() + (_BAR_H - 28) // 2)
        x = panel.right() - 12
        for btn in (self.refresh_btn, self.fetch_btn, self.open_btn):
            btn.move(x - btn.width(), panel.top() + (_BAR_H - btn.height()) // 2)
            x = btn.x() - 6
        self._bar_text_right = x - 12

    def retranslate(self):
        """热切换语言后刷新标题、按钮、概览、远程行与状态提示。"""
        self.back_btn.setToolTip(tr("返回仓库列表（Esc）"))
        self.open_btn.set_text(tr("打开目录"))
        self.open_btn.setToolTip(tr("在资源管理器中打开仓库目录"))
        self.fetch_btn.set_text(tr("抓取全部"))
        self.fetch_btn.setToolTip(tr("git fetch --prune（刷新所有远程的领先/落后统计）"))
        self.refresh_btn.set_text(tr("刷新"))
        self.refresh_btn.setToolTip(tr("重新读取本地状态（不发网络请求）"))
        self.sec_title.setText(tr("远程仓库"))
        self.sec_hint.setText(tr("点左侧圆点加入批量推送目标"))
        self.add_btn.set_text(tr("添加远程"))
        self.push_all_btn.set_text(tr("推送全部目标"))
        self.editor.retranslate()
        if self._hint is not None:
            self._hint.setText(tr("还没有远程仓库。点击右上角「添加远程」填写名称与地址，"
                                  "之后就能在这里推送、拉取。"))
        for row in self._rows.values():
            row.retranslate()
        self._place_top_buttons()
        self._refresh_overview()
        # 状态行文案含动态数据，无法重译，切回默认提示
        self._status_text = ""
        self._status_kind = "idle"
        self.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_top_buttons()
        panel = self._panel_rect()
        body = QRect(panel.left() + 1, panel.top() + _BAR_H,
                     panel.width() - 2, panel.height() - _BAR_H - 1)
        self.scroll.setGeometry(body)
        self._vbar.resize_to_area()

    # ---------- 绘制 ----------
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = _is_dark(self)
        p.setPen(Qt.NoPen)
        p.setBrush(theme.st("content_bg", dark))
        p.drawRect(self.rect())

        left, top, w = 30, 28, self.width() - 60
        title = self._repo.name if self._repo is not None else tr("仓库详情")
        f = QFont(self.font())
        f.setPointSize(_TITLE_PT)
        f.setBold(True)
        p.setFont(f)
        p.setPen(theme.st("title_text", dark))
        p.drawText(QRectF(left, top, w, 30), Qt.AlignVCenter | Qt.AlignLeft,
                   _elide(p, title, w))

        f.setPointSize(_SUB_PT)
        f.setBold(False)
        p.setFont(f)
        p.setPen(theme.st("sub_text", dark))
        sub = str(self._path) if self._path is not None else tr("从「仓库」页点开一个仓库")
        p.drawText(QRectF(left, top + 34, w, 22), Qt.AlignVCenter | Qt.AlignLeft,
                   _elide(p, sub, w))

        panel = self._panel_rect()
        r = theme.st("panel_radius", dark)
        p.setPen(theme.st("panel_border", dark))
        p.setBrush(theme.st("panel_bg", dark))
        p.drawRoundedRect(QRectF(panel).adjusted(0.5, 0.5, -0.5, -0.5), r, r)

        # 顶栏状态：分支与远程/目标数量
        if self._repo is None:
            bar_text = tr("未加载仓库")
        elif self._repo.detached:
            bar_text = tr("游离 HEAD · {n} 个远程", n=len(self._remotes))
        else:
            bar_text = tr("分支 {branch} · {n} 个远程 · 推送目标 {targets}",
                          branch=self._repo.branch, n=len(self._remotes),
                          targets=len(self._targets))
        f.setPointSize(8)
        p.setFont(f)
        p.setPen(theme.st("sub_text", dark))
        text_x = self.back_btn.geometry().right() + 12
        text_w = max(0, self._bar_text_right - text_x)
        p.drawText(QRectF(text_x, panel.top() + 5, text_w, _BAR_H - 10),
                   Qt.AlignVCenter | Qt.AlignLeft,
                   _elide(p, bar_text, text_w))

        p.setPen(theme.st("panel_border", dark))
        p.drawLine(panel.left() + 1, panel.top() + _BAR_H,
                   panel.right() - 1, panel.top() + _BAR_H)

        # 底部状态行
        text = self._status_text or tr("选中远程即可推送、拉取；圆点用于批量推送目标")
        f.setPointSize(8)
        p.setFont(f)
        p.setPen(self._status_color(dark))
        p.drawText(QRectF(31, panel.bottom() + 4, self.width() - 62, 22),
                   Qt.AlignVCenter | Qt.AlignLeft,
                   _elide(p, text, self.width() - 62))
        p.end()

    def _status_color(self, dark: bool) -> QColor:
        if self._status_kind == "busy":
            return theme.st("accent", dark)
        if self._status_kind == "success":
            return _GREEN
        if self._status_kind == "error":
            return _RED
        return theme.st("sub_text", dark)

    # ---------- 主题 ----------
    def apply_style(self):
        dark = _is_dark(self)
        sub = theme.st("sub_text", dark)
        handle = f"rgba({sub.red()}, {sub.green()}, {sub.blue()}, 100)"
        handle_hot = f"rgba({sub.red()}, {sub.green()}, {sub.blue()}, 170)"
        self.scroll.setStyleSheet(f"""
            QScrollArea {{ background: transparent; border: none; }}
            QScrollBar:vertical {{ width: 8px; background: transparent; margin: 2px 0; }}
            QScrollBar::handle:vertical {{ background: {handle}; border-radius: 4px;
                                          min-height: 32px; }}
            QScrollBar::handle:vertical:hover {{ background: {handle_hot}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: transparent; }}
        """)

        title = theme.st("title_text", dark)
        border = QColor(sub)
        border.setAlpha(90)
        accent = theme.st("accent", dark)
        self.editor.setStyleSheet(f"""
            QLineEdit {{
                background: transparent; color: {title.name()};
                border: 1px solid rgba({border.red()}, {border.green()}, {border.blue()}, 90);
                border-radius: 6px; padding: 3px 8px; font-size: 9pt;
            }}
            QLineEdit:focus {{ border-color: {accent.name()}; }}
            QLineEdit:disabled {{ color: {sub.name()};
                border-color: rgba({border.red()}, {border.green()}, {border.blue()}, 50); }}
        """)

        f = QFont(self.font())
        f.setPointSize(10)
        f.setBold(True)
        self.sec_title.setFont(f)
        self.sec_title.setStyleSheet(
            f"color: {title.name()}; background: transparent;")
        f2 = QFont(self.font())
        f2.setPointSize(8)
        self.sec_hint.setFont(f2)
        self.sec_hint.setStyleSheet(
            f"color: {sub.name()}; background: transparent;")

        self._style_hint()
        for row in self._rows.values():
            row.update()
        self.overview.update()
        self.editor.update()
        self.update()

    def _style_hint(self):
        if self._hint is None:
            return
        dark = _is_dark(self)
        f = QFont(self.font())
        f.setPointSize(8)
        self._hint.setFont(f)
        self._hint.setStyleSheet(
            f"color: {theme.st('sub_text', dark).name()}; background: transparent;")

    # ---------- 目标与远程配置 ----------
    def _toggle_target(self, name: str):
        if self._busy:
            return
        if name in self._targets:
            self._targets.discard(name)
        else:
            self._targets.add(name)
        self._save_targets()
        row = self._rows.get(name)
        if row is not None:
            row.set_target(name in self._targets)
        self._refresh_overview()
        self._refresh_buttons()

    def _add_remote(self):
        if self._busy:
            return
        self.editor.open("", "", False)

    def _edit_remote(self, name: str):
        if self._busy:
            return
        url = dict(self._remotes).get(name, "")
        self.editor.open(name, url, True)

    def _save_remote(self, name: str, url: str):
        if self._busy or self._path is None:
            return
        name, url = name.strip(), url.strip()
        if not _NAME_RE.fullmatch(name):
            self._set_status(tr("远程名称只能包含字母、数字、点、下划线与连字符"), "error")
            return
        if not url:
            self._set_status(tr("请填写远程地址"), "error")
            return

        if self.editor.name_locked:
            ok, out = gitrepo.remote_set_url(self._path, name, url)
            if not ok:
                self._set_status(tr("更新失败：{err}", err=_brief_error(out)), "error")
                return
            self.editor.hide()
            self._set_status(tr("已更新 {name} 的地址", name=name), "success")
            self._after_change()
            return

        if name in dict(self._remotes):
            self._set_status(tr("已存在名为 {name} 的远程", name=name), "error")
            return
        ok, out = gitrepo.remote_add(self._path, name, url)
        if not ok:
            self._set_status(tr("添加失败：{err}", err=_brief_error(out)), "error")
            return
        # 新加的远程直接加入批量推送目标，省一次点击
        order = [n for n, _ in self._remotes if n in self._targets]
        order.append(name)
        store.save_push_remotes(str(self._path), order)
        self._targets.add(name)
        self.editor.hide()
        self._set_status(tr("已添加远程 {name}", name=name), "success")
        self._after_change()

    def _remove_remote(self, name: str):
        if self._busy or self._path is None:
            return
        if self._armed != name:
            self._disarm()
            self._armed = name
            row = self._rows.get(name)
            if row is not None:
                row.set_remove_armed(True)
            self._set_status(tr("再次点击「删除」以移除远程 {name}", name=name), "idle")
            self._arm_timer.start()
            return

        self._disarm()
        ok, out = gitrepo.remote_remove(self._path, name)
        if not ok:
            self._set_status(tr("删除失败：{err}", err=_brief_error(out)), "error")
            return
        self._targets.discard(name)
        self._save_targets()
        self._set_status(tr("已移除远程 {name}", name=name), "success")
        self._after_change()

    def _disarm(self):
        self._armed = None
        self._arm_timer.stop()
        for row in self._rows.values():
            row.set_remove_armed(False)

    def _open_folder(self):
        if self._path is None:
            return
        try:
            os.startfile(str(self._path))
        except OSError:
            self._set_status(tr("无法打开目录"), "error")

    # ---------- 推送 ----------
    def _push_all(self):
        if self._busy or self._repo is None:
            return
        if self._repo.detached:
            self._set_status(tr("当前处于游离 HEAD，无法推送"), "error")
            return
        names = [n for n, _ in self._remotes if n in self._targets]
        if not names:
            self._set_status(tr("还没有选择批量推送目标"), "idle")
            return
        self._verified(lambda: self._begin_push(names))

    def _push_one(self, name: str):
        if self._busy or self._repo is None:
            return
        if self._repo.detached:
            self._set_status(tr("当前处于游离 HEAD，无法推送"), "error")
            return
        self._verified(lambda: self._begin_push([name]))

    def _verified(self, action):
        """与推送页一致：开启二次校验时先过 Windows Hello。"""
        if not store.sensitive_verify_required():
            action()
            return
        page = getattr(self.window(), "repo_page", None)
        if page is None:
            action()
            return
        self._set_busy(True)
        self._set_status(tr("正在等待系统身份验证…"), "busy")
        page.confirm(tr("GiTool：请验证身份以继续推送"),
                     lambda result: self._on_verified(result, action))

    def _on_verified(self, result, action):
        if not result.ok:
            self._set_busy(False)
            self._set_status(tr("{msg}，可重新推送", msg=result.message), "error")
            return
        action()

    def _begin_push(self, names: list[str]):
        self._queue = list(names)
        self._set_busy(True)
        self._push_next()

    def _push_next(self):
        if not self._queue:
            self._set_busy(False)
            self._set_status(tr("推送完成，推送目标已全部更新"), "success")
            self._after_change()
            return
        name = self._queue[0]
        rb = self._remote_branch(name)
        set_upstream = rb is None or not rb.exists
        self._run_git(gitrepo.push_args(name, self._repo.branch, set_upstream),
                      tr("正在推送到 {name}…", name=name),
                      lambda code, text: self._push_done(name, code, text))

    def _push_done(self, name: str, code: int, text: str):
        if self._queue and self._queue[0] == name:
            self._queue.pop(0)
        if code != 0:
            self._queue.clear()
            self._set_busy(False)
            self._set_status(tr("推送到 {name} 失败：{reason}", name=name,
                                reason=_push_reason(text)), "error")
            self._after_change()
            return
        self._push_next()

    # ---------- 抓取 ----------
    def _fetch_all(self):
        if self._busy or not self._remotes:
            return
        self._queue = [n for n, _ in self._remotes]
        self._failures = []
        self._set_busy(True)
        self._fetch_next()

    def _fetch_one(self, name: str):
        if self._busy:
            return
        self._queue = [name]
        self._failures = []
        self._set_busy(True)
        self._fetch_next()

    def _fetch_next(self):
        if not self._queue:
            self._set_busy(False)
            if self._failures:
                self._set_status(tr("抓取失败：{err}", err=self._failures[0]), "error")
            else:
                self._set_status(tr("抓取完成，远端状态已更新"), "success")
            self._after_change()
            return
        name = self._queue[0]
        self._run_git(gitrepo.fetch_args(name), tr("正在抓取 {name}…", name=name),
                      lambda code, text: self._fetch_done(name, code, text))

    def _fetch_done(self, name: str, code: int, text: str):
        if self._queue and self._queue[0] == name:
            self._queue.pop(0)
        if code != 0:
            self._failures.append(f"{name}：{_brief_error(text)}")
        self._fetch_next()

    # ---------- 拉取 ----------
    def _pull(self, name: str):
        if self._busy or self._repo is None:
            return
        if self._repo.detached:
            self._set_status(tr("当前处于游离 HEAD，无法拉取"), "error")
            return
        branch = self._repo.branch
        self._set_busy(True)
        self._run_git(gitrepo.pull_args(name, branch),
                      tr("正在从 {name} 拉取 {branch}…", name=name, branch=branch),
                      lambda code, text: self._pull_done(name, branch, code, text))

    def _pull_done(self, name: str, branch: str, code: int, text: str):
        self._set_busy(False)
        if code == 0:
            self._set_status(tr("已从 {name} 拉取 {branch}", name=name,
                                branch=branch), "success")
        else:
            self._set_status(tr("拉取失败：{err}", err=_brief_error(text)), "error")
        self._after_change()

    # ---------- git 进程 ----------
    def _run_git(self, args: list[str], label: str, done):
        if self._proc is not None or self._path is None:
            return
        self._set_status(label, "busy")
        proc = QProcess(self)
        proc.setWorkingDirectory(str(self._path))
        self._after_proc = done
        proc.finished.connect(self._on_proc_finished)
        proc.errorOccurred.connect(self._on_proc_error)
        self._proc = proc
        proc.start("git", args)

    def _on_proc_finished(self, code: int, _status):
        proc = self._proc
        done = self._after_proc
        self._proc = None
        self._after_proc = None
        text = ""
        if proc is not None:
            out = bytes(proc.readAllStandardOutput()).decode("utf-8", "replace")
            err = bytes(proc.readAllStandardError()).decode("utf-8", "replace")
            text = (out + "\n" + err).strip()
            proc.deleteLater()
        if done is not None:
            done(int(code), text)

    def _on_proc_error(self, _err):
        proc = self._proc
        if proc is None:
            return
        if proc.error() == QProcess.ProcessError.FailedToStart:
            self._proc = None
            self._after_proc = None
            self._set_busy(False)
            self._set_status(tr("无法启动 git，请确认已安装并加入 PATH"), "error")

    # ---------- 收尾 ----------
    def _after_change(self):
        """操作后重新读取状态，并回写全局扫描缓存（首页/推送页同步刷新）。"""
        if self._path is None:
            return
        info = gitrepo.read_repo(self._path)
        if info is not None:
            scan_service().update_repo(info.path, info)
        self._reload(info)

    def _on_back(self):
        if self._busy:
            self._set_status(tr("正在执行 git 操作，请稍候"), "idle")
            return
        self.editor.hide()
        self.back_requested.emit()

    def shutdown(self):
        self._disarm()
        if self._proc is not None:
            self._proc.kill()
            self._proc.waitForFinished(500)
            self._proc = None
            self._after_proc = None
