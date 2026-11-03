"""仓库页：目录选择、仓库列表，以及在原条目位置展开的推送详情。

视觉完全沿用模板的主题取色，交互按 PRD：
列表条目右侧箭头 → 条目原位展开详情 → 绿色上箭确认（系统 PIN 校验后推送）/ 红色叉取消。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve, QLineF, QPointF, QProcess, QRect, QRectF, QSize, Qt, QThread,
    QTimer, QVariantAnimation, Signal,
)
from PySide6.QtGui import (
    QColor, QFont, QFontMetrics, QIcon, QKeySequence, QPainter,
    QPainterPath, QPalette, QShortcut,
)
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QScrollArea,
    QVBoxLayout, QWidget,
)

from ..core import gitrepo, store, theme, verify
from ..core.gitrepo import RemoteBranch, RepoInfo

# 仓库无 icon.ico 时，用名称首字母生成头像底色
_AVATAR_COLORS = (
    "#5b8def", "#7a6ff0", "#d96c75", "#d69a3a",
    "#39a875", "#3a9bb8", "#b564a8", "#7f8693",
)
_GREEN = QColor("#2fb95a")
_RED = QColor("#e5534b")
_ORANGE = QColor("#d99036")

_TITLE_PT, _SUB_PT, _BODY_PT = 18, 10, 9

_PANEL_TOP = 102
_BAR_H = 46


def _row_height(repo: RepoInfo) -> int:
    """条目（以及原位展开的详情卡）的固定高度：随远程数量增长。"""
    return 84 + 19 * max(1, len(repo.remotes))


def _is_dark(widget: QWidget) -> bool:
    """与模板一致：优先使用设置里的深浅色，跟随系统时看顶层窗口调色板。"""
    ov = theme.dark_override()
    if ov is not None:
        return ov
    top = widget.window() or widget
    return top.palette().color(QPalette.ColorRole.Window).lightness() < 128


def _elide(painter: QPainter, text: str, width: float) -> str:
    return painter.fontMetrics().elidedText(text, Qt.ElideRight, int(width))


def _gap_text(rb: RemoteBranch) -> tuple[str, QColor]:
    """远程差距文案与颜色。"""
    if not rb.exists:
        return "未推送", _ORANGE
    if rb.ahead and rb.behind:
        return f"↑{rb.ahead} ↓{rb.behind}", _GREEN
    if rb.ahead:
        return f"↑{rb.ahead}", _GREEN
    if rb.behind:
        return f"↓{rb.behind}", _ORANGE
    return "已同步", QColor()


class ScanThread(QThread):
    """后台扫描目录，避免大目录阻塞界面。"""

    done = Signal(object)   # list[RepoInfo]

    def __init__(self, root: Path, parent=None):
        super().__init__(parent)
        self.root = root

    def run(self):
        try:
            repos = gitrepo.scan(self.root)
        except Exception:
            repos = []
        self.done.emit(repos)


class PillButton(QWidget):
    """面板内的胶囊文字按钮。"""

    clicked = Signal()

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.text = text
        self._hover = False
        self._accept = True
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(108, 32)

    def set_accept(self, accept: bool):
        self._accept = accept
        self.setCursor(Qt.PointingHandCursor if accept else Qt.ArrowCursor)
        self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._accept and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self._accept:
            p.setOpacity(0.4)
        dark = _is_dark(self)
        base = theme.st("accent", dark)
        fill = base.lighter(112) if self._hover else base
        r = self.height() / 2

        p.setPen(Qt.NoPen)
        p.setBrush(fill)
        p.drawRoundedRect(QRectF(self.rect()), r, r)

        f = QFont(self.font())
        f.setPointSize(9)
        p.setFont(f)
        p.setPen(QColor("#ffffff"))
        p.drawText(QRectF(self.rect()), Qt.AlignCenter, self.text)
        p.end()


class ArrowButton(QWidget):
    """条目右侧的按钮区域：无边框，平时只留箭头，悬停整片淡淡高亮，与条目融为一体。"""

    clicked = Signal()

    WIDTH = 56

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hover = False
        self.setCursor(Qt.PointingHandCursor)

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        if self.rect().contains(e.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = _is_dark(self)
        accent = theme.st("accent", dark)

        if self._hover:
            # 普通高亮：整片纯色填充，无描边、无渐变、无圆角
            fill = QColor(accent)
            fill.setAlpha(24 if dark else 18)
            p.setPen(Qt.NoPen)
            p.fillRect(self.rect(), fill)

        p.setPen(accent)
        cx, cy = self.width() / 2, self.height() / 2
        p.drawLine(QLineF(cx - 9, cy, cx + 9, cy))
        p.drawLine(QLineF(cx + 4, cy - 6, cx + 9, cy))
        p.drawLine(QLineF(cx + 4, cy + 6, cx + 9, cy))
        p.end()


class RepoRow(QWidget):
    """单个仓库条目：图标、名称、分支、本地提交、各远程状态。"""

    open_requested = Signal(object, object)   # (RepoInfo, RepoRow)

    def __init__(self, repo: RepoInfo, parent=None):
        super().__init__(parent)
        self.repo = repo
        self._hover = False
        self.setFixedHeight(_row_height(repo))

        self._icon: QIcon | None = None
        icon_path = repo.path / "icon.ico"
        if icon_path.is_file():
            self._icon = QIcon(str(icon_path))

        self.arrow = ArrowButton(self)
        self.arrow.setVisible(bool(repo.pushable_remotes) and not repo.detached)
        self.arrow.clicked.connect(lambda: self.open_requested.emit(self.repo, self))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # 铺满条目右侧整条区域，右边缘与条目右边缘完全贴合
        self.arrow.setGeometry(self.width() - ArrowButton.WIDTH, 0,
                               ArrowButton.WIDTH, self.height())

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = _is_dark(self)
        w, h = self.width(), self.height()

        if self._hover:
            p.setPen(Qt.NoPen)
            p.setBrush(theme.st("nav_hover", dark))
            # 直角高亮，与右侧按钮区域一致
            p.drawRect(0, 0, w, h)

        self._paint_icon(p, QRect(16, 14, 40, 40), dark)

        name_w = w - 70 - 74
        f = QFont(self.font())
        f.setPointSize(11)
        f.setBold(True)
        p.setFont(f)
        p.setPen(theme.st("title_text", dark))
        p.drawText(QRectF(70, 10, name_w, 20), Qt.AlignVCenter | Qt.AlignLeft,
                   _elide(p, self.repo.name, name_w))

        # 有未提交改动：名称后的小圆点
        if self.repo.dirty:
            name_wd = p.fontMetrics().horizontalAdvance(self.repo.name)
            dot_x = min(70 + name_wd + 9, 70 + name_w - 4)
            p.setPen(Qt.NoPen)
            p.setBrush(_ORANGE)
            p.drawEllipse(QRectF(dot_x, 18, 6, 6))

        f_sub = QFont(self.font())
        f_sub.setPointSize(8)
        p.setFont(f_sub)
        p.setPen(theme.st("sub_text", dark))
        p.drawText(QRectF(70, 31, name_w, 15), Qt.AlignVCenter | Qt.AlignLeft,
                   _elide(p, str(self.repo.path), name_w))

        # 分支胶囊 + 本地最新提交
        chip_font = QFont(self.font())
        chip_font.setPointSize(8)
        chip_font.setBold(True)
        chip_w = _text_width(chip_font, self.repo.branch) + 16
        chip = QRectF(70, 51, chip_w, 18)
        accent = theme.st("accent", dark)
        chip_bg = QColor(accent)
        chip_bg.setAlpha(28)
        p.setPen(Qt.NoPen)
        p.setBrush(chip_bg)
        p.drawRoundedRect(chip, 9, 9)
        p.setFont(chip_font)
        p.setPen(accent)
        p.drawText(chip, Qt.AlignCenter, self.repo.branch)

        p.setFont(f_sub)
        p.setPen(theme.st("sub_text", dark))
        local_x = chip.right() + 9
        local_w = w - local_x - 74
        local_text = f"{self.repo.head_short}  {self.repo.head_subject}"
        p.drawText(QRectF(local_x, 51, local_w, 18), Qt.AlignVCenter | Qt.AlignLeft,
                   _elide(p, local_text, local_w))

        # 远程状态行
        y = 74.0
        if not self.repo.remotes:
            p.setFont(f_sub)
            p.setPen(theme.st("placeholder", dark))
            p.drawText(QRectF(16, y, w - 32, 19), Qt.AlignVCenter | Qt.AlignLeft,
                       "未配置远程仓库")
        for rb in self.repo.remotes:
            self._paint_remote_line(p, rb, y, w, dark)
            y += 19

        p.setPen(theme.st("panel_border", dark))
        p.drawLine(16, h - 1, w - 16, h - 1)
        p.end()

    def _paint_icon(self, p: QPainter, rect: QRect, dark: bool):
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), 9, 9)
        p.save()
        p.setClipPath(path)
        if self._icon is not None:
            p.drawPixmap(rect, self._icon.pixmap(QSize(40, 40)))
        else:
            color = QColor(_AVATAR_COLORS[hash(self.repo.name) % len(_AVATAR_COLORS)])
            p.fillRect(rect, color)
            f = QFont(self.font())
            f.setPointSize(15)
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor("#ffffff"))
            p.drawText(QRectF(rect), Qt.AlignCenter, self.repo.name[:1].upper())
        p.restore()

    def _paint_remote_line(self, p: QPainter, rb: RemoteBranch, y: float, w: int, dark: bool):
        f = QFont(self.font())
        f.setPointSize(8)
        f.setBold(True)
        p.setFont(f)
        p.setPen(theme.st("nav_text", dark))
        label = f"{rb.remote}/{rb.branch}" if rb.exists else f"{rb.remote} · 新分支"
        p.drawText(QRectF(16, y, 132, 19), Qt.AlignVCenter | Qt.AlignLeft,
                   _elide(p, label, 132))

        p.setFont(_pt_font(self.font(), 8))
        p.setPen(theme.st("sub_text", dark))
        if rb.exists:
            p.drawText(QRectF(150, y, 62, 19), Qt.AlignVCenter | Qt.AlignLeft, rb.commit)

        text, color = _gap_text(rb)
        p.setPen(color if color.isValid() else theme.st("placeholder", dark))
        p.drawText(QRectF(214, y, 56, 19), Qt.AlignVCenter | Qt.AlignLeft, text)

        p.setPen(theme.st("placeholder", dark))
        subject_w = max(0, w - 276 - 60)
        p.drawText(QRectF(276, y, subject_w, 19), Qt.AlignVCenter | Qt.AlignLeft,
                   _elide(p, rb.subject or "—", subject_w))


def _pt_font(base: QFont, pt: int, bold: bool = False) -> QFont:
    f = QFont(base)
    f.setPointSize(pt)
    f.setBold(bold)
    return f


def _text_width(font: QFont, text: str) -> int:
    """用与绘制一致的字体量文字宽度（分支胶囊自适应宽度用）。"""
    return QFontMetrics(font).horizontalAdvance(text)


class EmptyState(QWidget):
    """列表为空/扫描中的居中提示。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.title = "还没有仓库"
        self.subtitle = "选择一个目录，扫描其中所有 Git 仓库"
        self.scanning = False
        self.btn = PillButton("选择目录", self)

    def set_text(self, title: str, subtitle: str):
        self.title, self.subtitle = title, subtitle
        self.update()

    def set_scanning(self, scanning: bool):
        self.scanning = scanning
        self.btn.set_accept(not scanning)
        self.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.btn.move((self.width() - self.btn.width()) // 2,
                      self.height() // 2 + 52)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = _is_dark(self)
        w, h = self.width(), self.height()

        f = QFont(self.font())
        f.setPointSize(13)
        f.setBold(True)
        p.setFont(f)
        p.setPen(theme.st("title_text", dark))
        p.drawText(QRectF(0, h / 2 - 34, w, 26), Qt.AlignCenter, self.title)

        f.setPointSize(9)
        f.setBold(False)
        p.setFont(f)
        p.setPen(theme.st("sub_text", dark))
        p.drawText(QRectF(0, h / 2 - 4, w, 20), Qt.AlignCenter, self.subtitle)

        if self.scanning:
            # 扫描中的呼吸圆点
            phase = getattr(self, "_phase", 0)
            alpha = int(90 + 120 * abs(1 - (phase % 2)))
            col = QColor(theme.st("accent", dark))
            col.setAlpha(alpha)
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            p.drawEllipse(QRectF(w / 2 - 4, h / 2 + 24, 8, 8))
        p.end()


class RemoteOption(QWidget):
    """详情左侧的远程选择卡。"""

    picked = Signal(object)

    def __init__(self, remote: RemoteBranch, parent=None):
        super().__init__(parent)
        self.remote = remote
        self.selected = False
        self._hover = False
        self.setCursor(Qt.PointingHandCursor)

    def set_selected(self, selected: bool):
        self.selected = selected
        self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        if self.rect().contains(e.position().toPoint()):
            self.picked.emit(self.remote)
        super().mouseReleaseEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = _is_dark(self)
        accent = theme.st("accent", dark)
        border = accent if self.selected else theme.st("panel_border", dark)
        bg = QColor(accent)
        bg.setAlpha(24 if self.selected else 0)
        if self._hover and not self.selected:
            bg = theme.st("nav_hover", dark)
            bg.setAlpha(max(18, bg.alpha()))

        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(border)
        p.setBrush(bg)
        p.drawRoundedRect(r, 8, 8)

        # 单行：远程名 + 差距（分支信息放在中间摘要里，给矮卡片省空间）
        f = QFont(self.font())
        f.setPointSize(9)
        f.setBold(True)
        p.setFont(f)
        p.setPen(theme.st("title_text", dark))
        gap_w = 44
        p.drawText(QRectF(10, 0, self.width() - 10 - gap_w - 8, self.height()),
                   Qt.AlignVCenter | Qt.AlignLeft,
                   _elide(p, self.remote.remote, self.width() - 10 - gap_w - 8))

        text, color = _gap_text(self.remote)
        p.setFont(_pt_font(self.font(), 8))
        p.setPen(color if color.isValid() else theme.st("sub_text", dark))
        p.drawText(QRectF(self.width() - gap_w - 8, 0, gap_w, self.height()),
                   Qt.AlignVCenter | Qt.AlignRight, text)
        p.end()


class StatusBar(QWidget):
    """详情里的状态行：文字 + 活动指针。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.text = "选择操作以继续"
        self.kind = "idle"
        self.setFixedHeight(38)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    def set_state(self, text: str, kind: str):
        self.text, self.kind = text, kind
        if kind == "busy":
            if not self._timer.isActive():
                self._phase = 0.0   # 从左侧起步
                self._timer.start()
        else:
            self._timer.stop()
            self._phase = 0.0
        self.update()

    def _tick(self):
        self._phase = (self._phase + 0.022) % 2.0
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = _is_dark(self)
        w = self.width()
        colors = {
            "idle": theme.st("placeholder", dark),
            "busy": theme.st("title_text", dark),
            "success": _GREEN,
            "error": _RED,
        }
        f = QFont(self.font())
        f.setPointSize(9)
        p.setFont(f)
        p.setPen(colors.get(self.kind, colors["idle"]))
        p.drawText(QRectF(0, 0, w, 22), Qt.AlignTop | Qt.AlignLeft,
                   _elide(p, self.text, w))

        track = QRectF(0, self.height() - 6, min(190, w), 3)
        p.setPen(Qt.NoPen)
        p.setBrush(theme.st("panel_border", dark))
        p.drawRoundedRect(track, 1.5, 1.5)

        if self.kind == "busy":
            seg_w = 54
            t = self._phase if self._phase <= 1 else 2 - self._phase
            x = track.x() + (track.width() - seg_w) * t
            p.setBrush(theme.st("accent", dark))
            p.drawRoundedRect(QRectF(x, track.y(), seg_w, track.height()), 1.5, 1.5)
        elif self.kind in ("success", "error"):
            p.setBrush(colors[self.kind])
            p.drawRoundedRect(track, 1.5, 1.5)
        p.end()


class ActionPad(QWidget):
    """详情右侧的操作方块：一个正方形对半切成两格，上绿↑确认、下红✕取消。"""

    confirm_clicked = Signal()
    cancel_clicked = Signal()

    WIDTH = 112

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hover = -1          # -1 无，0 上半格，1 下半格
        self.confirm_enabled = True
        self.cancel_enabled = True
        self.setFixedWidth(self.WIDTH)
        self.setMinimumHeight(56)
        self.setMouseTracking(True)   # 不按键也能收到 mouseMove，用于悬浮高亮
        self.setCursor(Qt.PointingHandCursor)

    def set_enabled(self, confirm: bool, cancel: bool):
        self.confirm_enabled, self.cancel_enabled = confirm, cancel
        self._hover = -1
        self.update()

    def _cell_at(self, pos) -> int:
        return 0 if pos.y() < self.height() / 2 else 1

    def mouseMoveEvent(self, e):
        idx = self._cell_at(e.position())
        if idx != self._hover:
            self._hover = idx
            self.update()
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):
        self._hover = -1
        self.update()
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        if self.rect().contains(e.position().toPoint()):
            idx = self._cell_at(e.position())
            if idx == 0 and self.confirm_enabled:
                self.confirm_clicked.emit()
            elif idx == 1 and self.cancel_enabled:
                self.cancel_clicked.emit()
        super().mouseReleaseEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = _is_dark(self)
        w, h = self.width(), self.height()
        mid = h / 2
        cells = (QRectF(0, 0, w, mid), QRectF(0, mid, w, h - mid))
        colors = (_GREEN, _RED)
        enabled = (self.confirm_enabled, self.cancel_enabled)

        outer = QPainterPath()
        outer.addRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5))

        for i in (0, 1):
            cell = cells[i]
            p.save()
            if not enabled[i]:
                p.setOpacity(0.35)
            clip = QPainterPath()
            clip.addRect(cell)
            p.setClipPath(outer.intersected(clip))

            base = colors[i]
            if self._hover == i:
                # 仅悬停时出现的淡透明底色
                fill = QColor(base)
                fill.setAlpha(40 if dark else 30)
                p.setPen(Qt.NoPen)
                p.fillRect(cell, fill)

            # 图标保持本色，透明底上也能看清
            p.setPen(base)
            cx, cy = w / 2, cell.center().y()
            if i == 0:
                p.drawLine(QLineF(cx, cy + 10, cx, cy - 9))
                p.drawLine(QLineF(cx - 7, cy - 2, cx, cy - 9))
                p.drawLine(QLineF(cx + 7, cy - 2, cx, cy - 9))
            else:
                k = 8
                p.drawLine(QLineF(cx - k, cy - k, cx + k, cy + k))
                p.drawLine(QLineF(cx + k, cy - k, cx - k, cy + k))
            p.restore()

        # 两格之间的分隔线
        p.setPen(QColor(255, 255, 255, 44) if dark else QColor(0, 0, 0, 48))
        p.drawLine(QLineF(0, mid, w, mid))
        # 按钮区左侧边线，与内容区分开
        p.setPen(QColor(255, 255, 255, 36) if dark else QColor(0, 0, 0, 40))
        p.drawLine(QLineF(0.5, 0, 0.5, h))
        p.end()


class DetailPanel(QWidget):
    """条目原位展开后的推送详情。"""

    confirm_requested = Signal(object)   # RemoteBranch
    cancel_requested = Signal()

    def __init__(self, repo: RepoInfo, parent=None):
        super().__init__(parent)
        self.repo = repo
        self.busy = False
        # 只列出需要推送的远程；已同步的无需展示
        self.remotes = list(repo.pushable_remotes)
        self.remote: RemoteBranch | None = self.remotes[0] if self.remotes else None
        self._options: list[RemoteOption] = []
        self._labels = []     # (QLabel, pt, theme key, bold)
        # 与所替换的条目等高：不挤压上下相邻条目
        self.setFixedHeight(_row_height(repo))
        self._build()

    # ---------- 构建 ----------
    def _label(self, text: str, pt: int, key: str, bold: bool = False) -> QLabel:
        lab = QLabel(text, self)
        self._labels.append((lab, pt, key, bold))
        return lab

    def _build(self):
        root = QHBoxLayout(self)
        # 右侧按钮区与条目按钮一致：撑满高度并贴住卡片右边缘
        root.setContentsMargins(18, 0, 0, 0)
        root.setSpacing(16)

        # 左：远程选择；卡片高度受条目约束，选项按可用高度收缩
        left = QWidget(self)
        left.setFixedWidth(150)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 8, 0, 8)
        lv.setSpacing(4)
        lv.addWidget(self._label("推送到", 8, "sub_text"))
        n = len(self.remotes)
        if n:
            content = self.height() - 16
            opt_h = max(24, min(32, (content - 17 - 4 * n) // n))
            for rb in self.remotes:
                opt = RemoteOption(rb, left)
                opt.setFixedHeight(opt_h)
                opt.set_selected(rb is self.remote)
                opt.picked.connect(self._select_remote)
                self._options.append(opt)
                lv.addWidget(opt)
        else:
            lv.addWidget(self._label("没有需要推送的远程", 8, "placeholder"))
        lv.addStretch(1)
        root.addWidget(left)

        # 中：推送摘要与状态
        center = QVBoxLayout()
        center.setContentsMargins(0, 8, 0, 8)
        center.setSpacing(2)
        center.addStretch(1)
        self.headline = self._label("", 14, "title_text", True)
        self.branch_lab = self._label("", 8, "sub_text")
        center.addWidget(self.headline)
        center.addWidget(self.branch_lab)
        center.addSpacing(4)
        self.status = StatusBar(self)
        center.addWidget(self.status)
        center.addStretch(1)
        root.addLayout(center, 1)

        # 右：与条目按钮同款的整条按钮区域，上下对半为确认 / 取消
        self.pad = ActionPad(self)
        self.pad.confirm_clicked.connect(self._confirm)
        self.pad.cancel_clicked.connect(self.cancel_requested)
        root.addWidget(self.pad)

        self._refresh_summary()
        self.apply_style()

    def _refresh_summary(self):
        rb = self.remote
        count = rb.ahead if rb else 0
        self.headline.setText(f"即将推送 {count} 个提交")
        self.branch_lab.setText(f"当前分支：{self.repo.branch}")
        has = rb is not None and not self.repo.detached
        self.pad.set_enabled(has and not self.busy, not self.busy)

    # ---------- 交互 ----------
    def _select_remote(self, rb: RemoteBranch):
        self.remote = rb
        for opt in self._options:
            opt.set_selected(opt.remote is rb)
        self._refresh_summary()

    def _confirm(self):
        if self.busy or self.remote is None:
            return
        self.confirm_requested.emit(self.remote)

    def set_busy(self, busy: bool):
        self.busy = busy
        self._refresh_summary()

    def set_status(self, text: str, kind: str):
        self.status.set_state(text, kind)

    def apply_style(self):
        dark = _is_dark(self)
        for lab, pt, key, bold in self._labels:
            f = QFont(self.font())
            f.setPointSize(pt)
            f.setBold(bold)
            lab.setFont(f)
            lab.setStyleSheet(
                f"color: {theme.st(key, dark).name()}; background: transparent;"
            )
        for opt in self._options:
            opt.update()
        self.status.update()
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = _is_dark(self)
        p.setPen(theme.st("panel_border", dark))
        p.setBrush(theme.st("panel_bg", dark))
        # 二级界面使用直角卡片
        p.drawRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5))
        p.end()


class RepoPage(QWidget):
    """仓库主页面。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)

        self._root: Path | None = None
        self._repos: list[RepoInfo] = []
        self._scan_thread: ScanThread | None = None
        self._verify_session = None
        self._verify_remote: RemoteBranch | None = None
        self._verify_timer: QTimer | None = None
        self._prompt_known: set[int] = set()
        self._focus_timer: QTimer | None = None
        self._focus_tries = 0
        self._guard_on = False
        self._proc: QProcess | None = None
        self._detail: DetailPanel | None = None
        self._detail_anim: QVariantAnimation | None = None
        self._detail_row: RepoRow | None = None
        self._detail_index = -1
        self._holder: QWidget | None = None
        self._layout: QVBoxLayout | None = None

        # 恢复上次扫描目录：目录仍存在则等页面首次显示时自动扫描
        saved_root = store.get("last_scan_root")
        if isinstance(saved_root, str) and Path(saved_root).is_dir():
            self._root = Path(saved_root)
        self._restore_pending = self._root is not None

        self.choose_btn = PillButton("选择目录", self)
        self.choose_btn.clicked.connect(self._choose_dir)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # 隐藏纵向滚动条占位，让条目/按钮右边缘直达面板边缘（滚轮仍可滚动）
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.viewport().setAutoFillBackground(False)

        self.empty = EmptyState(self)
        self.empty.btn.clicked.connect(self._choose_dir)

        self._esc = QShortcut(QKeySequence("Escape"), self)
        self._esc.setContext(Qt.WindowShortcut)
        self._esc.activated.connect(self._on_escape)

        self._phase_timer = QTimer(self)
        self._phase_timer.setInterval(80)
        self._phase_timer.timeout.connect(self._empty_tick)

        self.apply_style()

    # ---------- 几何与绘制 ----------
    def _panel_rect(self) -> QRect:
        return QRect(30, _PANEL_TOP, max(0, self.width() - 60),
                     max(0, self.height() - _PANEL_TOP - 28))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        panel = self._panel_rect()
        self.choose_btn.move(panel.right() - self.choose_btn.width() - 14,
                             panel.top() + 7)
        body = QRect(panel.left() + 1, panel.top() + _BAR_H,
                     panel.width() - 2, panel.height() - _BAR_H - 1)
        self.scroll.setGeometry(body)
        self.empty.setGeometry(body)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = _is_dark(self)
        p.setPen(Qt.NoPen)
        p.setBrush(theme.st("content_bg", dark))
        p.drawRect(self.rect())

        left, top, w = 30, 28, self.width() - 60
        f = QFont(self.font())
        f.setPointSize(_TITLE_PT)
        f.setBold(True)
        p.setFont(f)
        p.setPen(theme.st("title_text", dark))
        p.drawText(QRectF(left, top, w, 30), Qt.AlignVCenter | Qt.AlignLeft, "仓库")

        f.setPointSize(_SUB_PT)
        f.setBold(False)
        p.setFont(f)
        p.setPen(theme.st("sub_text", dark))
        p.drawText(QRectF(left, top + 34, w, 22), Qt.AlignVCenter | Qt.AlignLeft,
                   "选择目录后扫描其中的 Git 仓库，推送前需要系统身份验证")

        panel = self._panel_rect()
        r = theme.st("panel_radius", dark)
        p.setPen(theme.st("panel_border", dark))
        p.setBrush(theme.st("panel_bg", dark))
        p.drawRoundedRect(QRectF(panel).adjusted(0.5, 0.5, -0.5, -0.5), r, r)

        # 面板顶栏：当前目录 / 扫描状态
        if self._is_scanning():
            root_text = "正在扫描目录…"
        elif self._root is not None:
            root_text = str(self._root)
        else:
            root_text = "尚未选择目录"
        f = QFont(self.font())
        f.setPointSize(8)
        p.setFont(f)
        p.setPen(theme.st("sub_text", dark))
        p.drawText(QRectF(panel.left() + 18, panel.top() + 5,
                          panel.width() - 150, _BAR_H - 10),
                   Qt.AlignVCenter | Qt.AlignLeft,
                   _elide(p, root_text, panel.width() - 150))

        p.setPen(theme.st("panel_border", dark))
        p.drawLine(panel.left() + 1, panel.top() + _BAR_H,
                   panel.right() - 1, panel.top() + _BAR_H)
        p.end()

    # ---------- 主题 ----------
    def apply_style(self):
        dark = _is_dark(self)
        handle = theme.st("sub_text", dark).name()
        self.scroll.setStyleSheet(f"""
            QScrollArea {{ background: transparent; border: none; }}
            QScrollBar:vertical {{ width: 8px; background: transparent; margin: 2px 0; }}
            QScrollBar::handle:vertical {{ background: {handle}; border-radius: 4px;
                                          min-height: 28px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: transparent; }}
        """)
        self.choose_btn.update()
        self.empty.update()
        if self._holder is not None:
            for row in self._holder.findChildren(RepoRow):
                row.update()
                row.arrow.update()
        if self._detail is not None:
            self._detail.apply_style()
        self.update()

    # ---------- 目录与扫描 ----------
    def _choose_dir(self):
        start = str(self._root) if self._root else str(Path.home())
        picked = QFileDialog.getExistingDirectory(self, "选择要扫描的目录", start)
        if not picked:
            return
        self._root = Path(picked)
        self._start_scan()

    def _is_scanning(self) -> bool:
        return self._scan_thread is not None and self._scan_thread.isRunning()

    def _start_scan(self):
        self._close_detail(instant=True)
        self._repos = []
        if self._root is not None:
            store.set_value("last_scan_root", str(self._root))
        self._rebuild_rows()
        self.empty.set_text("正在扫描目录…", "正在查找其中的 Git 仓库")
        self.empty.set_scanning(True)
        self.empty.show()
        self.scroll.hide()
        self.choose_btn.set_accept(False)
        self._phase_timer.start()

        thread = ScanThread(self._root, self)
        thread.done.connect(self._on_scan_done)
        thread.finished.connect(thread.deleteLater)
        self._scan_thread = thread
        thread.start()
        self.update()

    def _on_scan_done(self, repos: list):
        self._scan_thread = None
        self._phase_timer.stop()
        self.choose_btn.set_accept(True)
        self._repos = repos
        self._rebuild_rows()

        if repos:
            self.empty.hide()
            self.scroll.show()
        else:
            self.empty.set_scanning(False)
            self.empty.set_text("没有找到 Git 仓库", "换一个目录试试，其中不含含 .git 的文件夹")
            self.empty.show()
        self.update()

    def _empty_tick(self):
        self.empty._phase = getattr(self.empty, "_phase", 0) + 0.08
        self.empty.update()

    # ---------- 列表 ----------
    def _rebuild_rows(self):
        self._detail = None
        self._detail_row = None
        self._detail_index = -1
        self._detail_anim = None

        if self._holder is not None:
            self._holder.deleteLater()
            self._holder = None

        holder = QWidget()
        holder.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(holder)
        lay.setContentsMargins(0, 4, 0, 4)
        lay.setSpacing(0)
        for repo in self._repos:
            row = RepoRow(repo, holder)
            row.open_requested.connect(self._open_detail)
            lay.addWidget(row)
        lay.addStretch(1)
        self.scroll.setWidget(holder)
        self._holder = holder
        self._layout = lay

    def _update_repo(self, path: Path):
        info = gitrepo.read_repo(path)
        if info is None:
            self._repos = [r for r in self._repos if r.path != path]
        else:
            self._repos = [info if r.path == path else r for r in self._repos]
        self._rebuild_rows()

    # ---------- 详情 ----------
    def _open_detail(self, repo: RepoInfo, row: RepoRow):
        if self._detail_anim is not None or self._layout is None:
            return
        if self._layout.indexOf(row) < 0:
            return
        # 已有条目展开：先收起，再展开当前点击的条目（验证/推送中不打断）
        if self._detail is not None:
            if self._detail.busy:
                return
            self._close_detail(instant=True)
            self._layout.activate()
        idx = self._layout.indexOf(row)
        if idx < 0:
            return

        # 详情直接长在列表里：该行从布局中取出、原位左滑淡出，
        # 同一位置插入详情卡片，其余条目自然被推开，不覆盖整个面板
        geo = row.geometry()
        self._layout.removeWidget(row)
        row.setGeometry(geo)
        row.raise_()
        self._detail_row = row
        self._detail_index = idx

        card = DetailPanel(repo, self._holder)
        card.confirm_requested.connect(self._on_confirm)
        card.cancel_requested.connect(self._request_close)
        self._layout.insertWidget(idx, card)
        self._detail = card

        row_eff = QGraphicsOpacityEffect(row)
        row.setGraphicsEffect(row_eff)
        card_eff = QGraphicsOpacityEffect(card)
        card.setGraphicsEffect(card_eff)
        card_eff.setOpacity(0.0)

        anim = QVariantAnimation(self)
        anim.setDuration(220)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)

        def frame(t: float):
            row_eff.setOpacity(1.0 - t)
            row.move(geo.x() - int(30 * t), geo.y())
            card_eff.setOpacity(t)

        def done():
            row.hide()
            row.setGraphicsEffect(None)
            row.move(geo.x(), geo.y())
            card.setGraphicsEffect(None)
            if self._detail_anim is anim:
                self._detail_anim = None

        anim.valueChanged.connect(frame)
        anim.finished.connect(done)
        anim.start()
        self._detail_anim = anim
        card.setFocus()

    def _request_close(self):
        if self._detail is None or self._detail_anim is not None:
            return
        if self._detail.busy:
            return
        self._close_detail()

    def _close_detail(self, instant: bool = False):
        card = self._detail
        if card is None:
            if self._detail_anim is not None:
                self._detail_anim.stop()
                self._detail_anim = None
            return
        row = self._detail_row
        idx = self._detail_index
        if self._detail_anim is not None:
            self._detail_anim.stop()
            self._detail_anim = None

        if instant:
            self._layout.removeWidget(card)
            card.deleteLater()
            self._detail = None
            self._detail_row = None
            self._detail_index = -1
            if row is not None:
                row.setGraphicsEffect(None)
                self._layout.insertWidget(idx, row)
                row.show()
            self.setFocus()
            return

        eff = QGraphicsOpacityEffect(card)
        card.setGraphicsEffect(eff)
        anim = QVariantAnimation(self)
        anim.setDuration(150)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)

        def frame(t: float):
            eff.setOpacity(1.0 - t)

        def done():
            self._layout.removeWidget(card)
            card.deleteLater()
            self._detail = None
            self._detail_row = None
            self._detail_index = -1
            if row is not None:
                # 行回到原条目位置并淡入
                self._layout.insertWidget(idx, row)
                row.show()
                row_eff = QGraphicsOpacityEffect(row)
                row.setGraphicsEffect(row_eff)
                row_eff.setOpacity(0.0)
                back = QVariantAnimation(self)
                back.setDuration(160)
                back.setStartValue(0.0)
                back.setEndValue(1.0)
                back.setEasingCurve(QEasingCurve.OutCubic)
                back.valueChanged.connect(lambda v: row_eff.setOpacity(float(v)))

                def row_done():
                    row.setGraphicsEffect(None)
                    if self._detail_anim is back:
                        self._detail_anim = None

                back.finished.connect(row_done)
                self._detail_anim = back
                back.start()
            self.setFocus()

        anim.valueChanged.connect(frame)
        anim.finished.connect(done)
        anim.start()
        self._detail_anim = anim

    # ---------- 推送流程 ----------
    def _on_confirm(self, remote: RemoteBranch):
        detail = self._detail
        if detail is None:
            return
        detail.set_busy(True)
        detail.set_status("正在等待系统身份验证…", "busy")

        window = self.window()
        self._prompt_known = verify.prompt_windows()
        self._verify_remote = remote
        result, session = verify.start_verification(
            "GiTool：请验证身份以继续推送", int(window.winId()))
        if result is not None:
            self._after_verify(remote, result)
            return
        self._verify_session = session

        timer = QTimer(self)
        timer.setInterval(50)
        timer.timeout.connect(self._poll_verify)
        timer.start()
        self._verify_timer = timer

        self._focus_tries = 0
        timer = QTimer(self)
        timer.setInterval(200)
        timer.timeout.connect(self._focus_prompt)
        timer.start()
        self._focus_timer = timer

    def _focus_prompt(self):
        """验证对话框出现后把它切到前台，并把主窗口一起置顶。"""
        self._focus_tries += 1
        fresh = verify.prompt_windows() - self._prompt_known
        for hwnd in fresh:
            if verify.activate_prompt(hwnd, int(self.window().winId())):
                self._guard_on = True
                self._stop_focus_timer()
                return
        if self._focus_tries >= 6:
            self._stop_focus_timer()

    def _poll_verify(self):
        session = self._verify_session
        if session is None:
            self._stop_verify_timer()
            return
        try:
            if session.status() == 0:
                return
            result = session.finish()
        except Exception as exc:
            result = verify.VerifyResult(False, "error", f"验证调用失败：{exc}")
        self._verify_session = None
        self._stop_verify_timer()
        self._restore_focus()
        QTimer.singleShot(200, lambda: self._restore_focus(True))
        QTimer.singleShot(600, lambda: self._restore_focus(True))
        QTimer.singleShot(1500, lambda: self._restore_focus(True, True))
        remote = self._verify_remote
        self._verify_remote = None
        if remote is not None:
            self._after_verify(remote, result)

    def _restore_focus(self, release: bool = False, force: bool = False):
        """验证结束把键盘焦点交回主窗口，稍后再撤销验证期间的置顶。

        置顶要等对话框真正消失、主窗口回到前台之后才撤销：提前撤销会让系统刚
        激活的其它窗口露到主窗口前面，那就是用户看到的"闪一下"。force 只作兜底，
        避免极端情况下主窗口一直置顶。
        """
        hwnd = int(self.window().winId())
        if verify.foreground_window() != hwnd:
            verify.activate_window(hwnd)
        if not self._guard_on:
            return
        if force or (release and verify.foreground_window() == hwnd):
            self._guard_on = False
            verify.set_topmost(hwnd, False)

    def _stop_verify_timer(self):
        if self._verify_timer is not None:
            self._verify_timer.stop()
            self._verify_timer.deleteLater()
            self._verify_timer = None

    def _stop_focus_timer(self):
        if self._focus_timer is not None:
            self._focus_timer.stop()
            self._focus_timer.deleteLater()
            self._focus_timer = None

    def _after_verify(self, remote: RemoteBranch, result):
        self._stop_focus_timer()
        detail = self._detail
        if detail is None:
            return
        if not result.ok:
            detail.set_busy(False)
            detail.set_status(f"{result.message}，可重新验证或取消", "error")
            return
        detail.set_status(f"验证通过，正在推送到 {remote.remote}…", "busy")
        self._start_push(remote)

    def _start_push(self, remote: RemoteBranch):
        detail = self._detail
        if detail is None:
            return
        set_upstream = not remote.exists
        proc = QProcess(self)
        proc.setWorkingDirectory(str(detail.repo.path))
        proc.finished.connect(lambda code, _status: self._on_push_finished(remote, int(code)))
        proc.errorOccurred.connect(self._on_push_error)
        self._proc = proc
        proc.start("git", gitrepo.push_args(remote.remote, detail.repo.branch, set_upstream))

    def _on_push_error(self, _err):
        if self._detail is not None and self._detail.busy:
            self._detail.set_busy(False)
            self._detail.set_status("无法启动 git，请确认已安装并加入 PATH", "error")

    def _on_push_finished(self, remote: RemoteBranch, code: int):
        detail = self._detail
        if detail is None:
            return
        out = bytes(self._proc.readAllStandardOutput()).decode("utf-8", "replace")
        err = bytes(self._proc.readAllStandardError()).decode("utf-8", "replace")
        self._proc = None

        if code == 0:
            detail.set_status(f"推送成功，{remote.remote}/{detail.repo.branch} 已更新", "success")
            QTimer.singleShot(1400, lambda: self._finish_push(detail))
            return

        detail.set_busy(False)
        reason = _brief_error(out + "\n" + err)
        detail.set_status(f"推送失败：{reason}", "error")

    def _finish_push(self, detail: DetailPanel):
        if self._detail is not detail:
            return
        path = detail.repo.path
        self._close_detail(instant=True)
        self._update_repo(path)

    # ---------- Esc ----------
    def _on_escape(self):
        if self._detail is not None:
            if self._detail.busy:
                return
            self._request_close()
            return
        win = self.window()
        if win is not None:
            win.close()

    def showEvent(self, e):
        super().showEvent(e)
        self.setFocus()
        if self._restore_pending:
            self._restore_pending = False
            if self._root is not None:
                self._start_scan()

    def shutdown(self):
        """窗口关闭前等待后台线程结束，避免 QThread 销毁告警。"""
        if self._guard_on:
            self._guard_on = False
            verify.set_topmost(int(self.window().winId()), False)
        if self._verify_session is not None:
            self._verify_session.release()
            self._verify_session = None
        thread = self._scan_thread
        if thread is not None and thread.isRunning():
            thread.wait(3000)


def _brief_error(text: str) -> str:
    """从 git 输出中提取一行可读的失败原因。"""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for ln in lines:
        low = ln.lower()
        if low.startswith(("fatal:", "error:", "remote:", "!")):
            return ln[:90]
    return (lines[-1] if lines else "未知错误")[:90]
