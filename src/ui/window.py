import sys

from PySide6.QtCore import (
    Qt, QRectF, QRect, Signal, QPointF, QEasingCurve, QVariantAnimation,
    QAbstractAnimation, QTimer, QEvent,
)
from PySide6.QtGui import (
    QPainter, QColor, QPainterPath, QFont, QPen, QPalette, QGuiApplication, QLinearGradient,
    QCursor, QFontMetrics,
)
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QStackedWidget,
    QGraphicsOpacityEffect, QMessageBox, QSpacerItem,
)

from ..core import store, theme
from ..core.config import Config
from .repo_page import HomePage, RepoPage, SourcesPage, scan_service

ZOOM_MS = 240        # 最大化/还原展开收起动画时长
TITLE_BAR_H = 40       # macOS 顶栏高度（交通灯行）
_TITLE_BAR_WIN = 34    # Win11 顶栏高度（更窄，贴合系统标题栏）
_DEF_MIN_W, _DEF_MIN_H = 860, 580   # 应用默认最小客户区尺寸（macOS 全客户区）


def bar_h() -> int:
    """依当前风格返回顶栏高度（Win11 用更窄的标题栏）"""
    return _TITLE_BAR_WIN if theme.is_win() else TITLE_BAR_H

# 「导航」分栏上下留白：Win11 需留出整体顶栏分隔线下的呼吸空间
_SIDE_TOP_MAC, _SIDE_TOP_WIN = 4, 16
_SIDE_BOT_MAC, _SIDE_BOT_WIN = 6, 8


def is_dark(widget=None) -> bool:
    """是否为深色主题：优先采用设置中的深浅色模式，跟随系统时回退到窗口调色板判断"""
    ov = theme.dark_override()
    if ov is not None:
        return ov
    return widget.palette().color(QPalette.ColorRole.Window).lightness() < 128


_WIN32 = sys.platform == "win32"
_DWMWA_WINDOW_CORNER_PREFERENCE = 33
_DWMWCP_DONOTROUND = 1
_DWMWCP_ROUND = 2


def set_native_round(window, round_on: bool):
    if not _WIN32:
        return
    import ctypes
    try:
        val = ctypes.c_int(_DWMWCP_ROUND if round_on else _DWMWCP_DONOTROUND)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            int(window.winId()), _DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(val), ctypes.sizeof(val))
    except Exception:
        pass  # 系统不支持时静默忽略


def _force_frame_recalc(window):
    """切换风格后强制 Windows 重算非客户区（重发 WM_NCCALCSIZE / WM_NCHITTEST）。

    用于 macOS（裁剪原生标题栏）与 Win11（展示原生标题栏）之间即时切换。
    非 Windows 下直接忽略。
    """
    if not _WIN32:
        return
    import ctypes
    try:
        SWP_NOSIZE = 0x0001
        SWP_NOMOVE = 0x0002
        SWP_NOZORDER = 0x0004
        SWP_NOACTIVATE = 0x0010
        SWP_FRAMECHANGED = 0x0020
        ctypes.windll.user32.SetWindowPos(
            int(window.winId()), 0, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED | SWP_NOACTIVATE)
    except Exception:
        pass


# ---- macOS 自绘顶栏模式：WM_NCCALCSIZE 裁掉原生标题栏 + WM_NCHITTEST 边缘缩放 ----
_WM_NCCALCSIZE = 0x0083
_WM_NCHITTEST = 0x0084
# 命中区域常量（仅边缘缩放码；标题栏/控制键已由系统原生接管）
HT_LEFT, HT_RIGHT, HT_TOP, HT_TOPLEFT, HT_TOPRIGHT, HT_BOTTOM = 10, 11, 12, 13, 14, 15
HT_BOTTOMLEFT, HT_BOTTOMRIGHT = 16, 17
_RESIZE_EDGE = 6


def _edge_hit_test(window, lparam):
    """返回窗口边缘对应的边缘缩放命中码，内部区域返回 0。

    WM_NCHITTEST 的 lParam 是物理像素，而 Qt geometry() 是逻辑像素，
    高 DPI 缩放下二者不一致，需先按 devicePixelRatio 对齐。
    仅 macOS 自绘顶栏模式使用；Win11 走系统原生边框。
    """
    dpr = max(1.0, window.devicePixelRatioF())
    x = _low_word(lparam) / dpr
    y = _high_word(lparam) / dpr
    r = window.geometry()
    left, top, right, bottom = r.left(), r.top(), r.right(), r.bottom()
    el, et = x >= left and x < left + _RESIZE_EDGE, y >= top and y < top + _RESIZE_EDGE
    er = x > right - _RESIZE_EDGE and x <= right
    eb = y > bottom - _RESIZE_EDGE and y <= bottom
    if et and el: return HT_TOPLEFT
    if et and er: return HT_TOPRIGHT
    if eb and el: return HT_BOTTOMLEFT
    if eb and er: return HT_BOTTOMRIGHT
    if el: return HT_LEFT
    if er: return HT_RIGHT
    if et: return HT_TOP
    if eb: return HT_BOTTOM
    return 0


def _low_word(v): return ctypes_int16(v & 0xFFFF)
def _high_word(v): return ctypes_int16((v >> 16) & 0xFFFF)


def ctypes_int16(u):
    return (u - 65536) if u >= 32768 else u


class TrafficLightButton(QWidget):
    """macOS 红黄绿灯窗口按钮：表浅渐变 + 描边环 + 悬浮符号"""

    clicked_signal = Signal(int)  # 0 close, 1 minimize, 2 maximize/restore

    _COLORS = {
        'red':    (0xFF5F57, 0xE1443C),
        'yellow': (0xFEBE2E, 0xDB9D0E),
        'green':  (0x28C840, 0x15A92E),
    }

    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self.kind = kind  # 'red' / 'yellow' / 'green'
        self.host = None   # 指向所属 TrafficHeader，用于集群失焦/悬停
        self._hover = False
        self.setFixedSize(14, 14)
        self.setCursor(Qt.PointingHandCursor)

    def is_lit(self) -> bool:
        """点亮条件：窗口在焦点，或鼠标悬停在红绿灯集群上（macOS 失焦置灰）"""
        if self.host is None:
            return True
        return self.host.window_active or self.host.cluster_hover

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
            idx = {'red': 0, 'yellow': 1, 'green': 2}[self.kind]
            self.clicked_signal.emit(idx)
        super().mouseReleaseEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = is_dark(self)

        if self.is_lit():
            top, bottom = self._COLORS[self.kind]
            if self._hover:
                top = QColor(top).lighter(112)
                bottom = QColor(bottom).lighter(112)
            outline = QColor(0, 0, 0, 55)
        else:
            # 失焦置灰（macOS：窗口非焦点时三灯变灰，悬停时再亮起）
            top, bottom = (QColor(192, 195, 201), QColor(168, 172, 179)) if not dark \
                else (QColor(104, 108, 116), QColor(84, 88, 96))
            outline = QColor(0, 0, 0, 30)

        r = QRectF(self.rect()).adjusted(1.2, 1.2, -1.2, -1.2)

        g = QLinearGradient(r.topLeft(), r.bottomRight())
        g.setColorAt(0.0, QColor(top))
        g.setColorAt(1.0, QColor(bottom))
        p.setPen(QPen(outline, 0.7))
        p.setBrush(g)
        p.drawEllipse(r)

        hp = QPainterPath()
        hp.moveTo(r.center().x(), r.top() + r.height() * 0.18)
        hp.arcTo(QRectF(r.left() + 1, r.top() + 1, r.width() - 2, r.height() - 2), 180, 200)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 70 if self.is_lit() else 26))
        p.drawPath(hp)

        # 符号仅悬停时显示（hover 当前灯，或整个集群被悬停则三灯一起显示）
        show_symbol = self._hover or (self.host is not None and self.host.cluster_hover)
        if show_symbol:
            self._draw_symbol(p, r.center())
        p.end()

    def _draw_symbol(self, p: QPainter, c: QPointF):
        p.setPen(QPen(QColor(60, 20, 15, 210), 1.1, Qt.SolidLine, Qt.RoundCap))
        d = 2.6
        if self.kind == 'red':                                      # ×
            p.drawLine(QPointF(c.x() - d, c.y() - d), QPointF(c.x() + d, c.y() + d))
            p.drawLine(QPointF(c.x() - d, c.y() + d), QPointF(c.x() + d, c.y() - d))
        elif self.kind == 'yellow':                                 # −
            p.drawLine(QPointF(c.x() - d, c.y()), QPointF(c.x() + d, c.y()))
        elif self.kind == 'green':                                  # 展开 ↑ 角箭头
            a, b, k = c.x(), c.y(), 1.3
            p.setPen(QPen(QColor(20, 60, 20, 210), 1.1, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(self._expand_arrow_path(a, b, k))

    @staticmethod
    def _expand_arrow_path(x: float, y: float, k: float) -> QPainterPath:
        pa = QPainterPath()
        pa.moveTo(x - k, y + k * 1.4)          # 右上箭头
        pa.lineTo(x + k * 1.4, y - k)
        pa.lineTo(x + k, y - k * 1.5)
        pa.lineTo(x + k * 1.5, y - k)
        pa.moveTo(x + k, y - k * 1.4)          # 左下箭头
        pa.lineTo(x - k * 1.4, y + k)
        pa.lineTo(x - k * 1.5, y + k)
        pa.moveTo(x - k, y + k * 1.5)
        return pa


class TrafficHeader(QWidget):
    """侧边栏顶部的红黄绿灯行：可拖拽移动、双击切换最大化"""

    traffic_signal = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(TITLE_BAR_H)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self.window_active = True     # 窗口是否在焦点（macOS 失焦置灰）
        self.cluster_hover = False    # 鼠标是否悬停在红绿灯集群上
        self._hover_timer = QTimer(self)
        self._hover_timer.setInterval(40)
        self._hover_timer.timeout.connect(self._poll_light_hover)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 0, 0)
        lay.setSpacing(8)

        # macOS 左上角交通灯
        self.lights = []
        for kind in ('red', 'yellow', 'green'):
            b = TrafficLightButton(kind)
            b.host = self
            b.clicked_signal.connect(self.traffic_signal)
            self.lights.append(b)
            lay.addWidget(b)

        self.app_title = QLabel(Config.APP_NAME)
        self.app_title.setObjectName("TitleLabel")
        lay.addSpacing(4)
        lay.addWidget(self.app_title)
        lay.addStretch(1)

        self.apply_style()

    def apply_style(self):
        """按当前风格调整顶栏布局：macOS 显示交通灯（Win11 用系统原生标题栏）"""
        win = theme.is_win()
        for b in self.lights:
            b.setVisible(not win)
        # 轮询悬停：仅 macOS 红绿灯可见时运行
        if win:
            self.stop_polling()
        else:
            self.start_polling()

    def start_polling(self):
        """启动红绿灯悬停轮询（macOS 失焦唤起所需）"""
        self._hover_timer.start()

    def stop_polling(self):
        """暂停红绿灯悬停轮询并清掉悬停残留"""
        self._hover_timer.stop()
        self.cluster_hover = False
        for b in self.lights:
            b._hover = False
            b.update()

    def _poll_light_hover(self):
        """轮询光标位置更新集群/逐灯悬停状态（enter/leave 事件在快速移动时不可靠）。

        统一在全局坐标下比较：QCursor.pos() 与 mapToGlobal 派生的矩形都使用同一
        权威坐标系，避开自绘无边框窗口在 DPI 缩放下 widget 局部坐标转换的偏差，
        确保鼠标移开后悬停状态能被正确清除。
        """
        gpos = QCursor.pos()
        cluster = QRect()
        for b in self.lights:
            if b.isVisible():
                gr = QRect(b.mapToGlobal(b.rect().topLeft()), b.size())
                cluster = cluster.united(gr.adjusted(-3, -3, 3, 3))
        hover = cluster.contains(gpos)
        if hover != self.cluster_hover:
            self.cluster_hover = hover
            for b in self.lights:
                b.update()
        for b in self.lights:
            if not b.isVisible():
                continue
            gr = QRect(b.mapToGlobal(b.rect().topLeft()), b.size())
            h = gr.adjusted(-1, -1, 1, 1).contains(gpos)
            if h != b._hover:
                b._hover = h
                b.update()

    def set_window_active(self, active: bool):
        """窗口焦点变化时置灰/亮起红绿灯（macOS 行为）"""
        if active != self.window_active:
            self.window_active = active
            for b in self.lights:
                b.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = (e.globalPosition().toPoint()
                          - self.window().frameGeometry().topLeft())

    def mouseMoveEvent(self, e):
        # 最大化(全屏)状态禁止移动：否则 Qt 误以为无边框(setGeometry 会被 Windows 边框
        # 钳制)产生大量 "Unable to set geometry" 日志。macOS 全屏也不允许拖动窗口。
        if e.buttons() == Qt.LeftButton and hasattr(self, '_drag') \
                and not self.window().isMaximized():
            self.window().move(e.globalPosition().toPoint() - self._drag)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.traffic_signal.emit(2)


class TopDragBar(QWidget):
    """覆盖内容区顶部的透明拖拽条（macOS）：可移动窗口、双击最大化。

    Win11 不使用本控件，其标题栏由系统原生标题栏承载。
    """

    traffic_signal = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(bar_h())
        self.setAttribute(Qt.WA_TranslucentBackground)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = (e.globalPosition().toPoint()
                          - self.window().frameGeometry().topLeft())

    def mouseMoveEvent(self, e):
        # 最大化(全屏)状态禁止移动：否则 Qt 误以为无边框(setGeometry 会被 Windows 边框
        # 钳制)产生大量 "Unable to set geometry" 日志。macOS 全屏也不允许拖动窗口。
        if e.buttons() == Qt.LeftButton and hasattr(self, '_drag') \
                and not self.window().isMaximized():
            self.window().move(e.globalPosition().toPoint() - self._drag)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.traffic_signal.emit(2)


class NavButton(QWidget):
    """自绘侧边导航项：选中态高亮胶囊 + 简约线条图标"""

    clicked_signal = Signal(str)

    def __init__(self, key: str, label: str, icon_path=None, parent=None):
        super().__init__(parent)
        self.key = key
        self.label = label
        self.active = False
        self._hover = False
        self.icon_path = icon_path
        self.setFixedHeight(40)
        self.setCursor(Qt.PointingHandCursor)

    def set_active(self, active: bool):
        if self.active != active:
            self.active = active
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
            self.clicked_signal.emit(self.key)
        super().mouseReleaseEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = is_dark(self)

        ICON_LEFT, TEXT_LEFT = 19.0, 46.0
        r = theme.st("pill_radius", dark)
        pill = QRectF(self.rect()).adjusted(8, 3, -8, -3)
        if self.active:
            p.setBrush(theme.st("nav_pill", dark))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(pill, r, r)
        elif self._hover:
            p.setBrush(theme.st("nav_hover", dark))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(pill, r, r)

        self._draw_icon(p, dark)

        # 文字行对齐图标、垂直居中、行高统一
        f = QFont(self.font())
        f.setPointSize(10)
        col = theme.st("nav_text_act", dark) if self.active else theme.st("nav_text", dark)
        if self.active:
            f.setBold(True)
        p.setFont(f)
        p.setPen(col)
        p.drawText(QRectF(TEXT_LEFT, 0, self.width() - TEXT_LEFT - 12, self.height()),
                   Qt.AlignVCenter | Qt.AlignLeft, self.label)
        p.end()

    def _draw_icon(self, p: QPainter, dark: bool):
        col = theme.st("icon", dark)
        p.setPen(QPen(col, 1.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        cw, x0, y0 = 9.0, 19.0, (self.height() - 9) / 2
        paths = {
            'pulse': lambda: (
                p.drawPolyline([
                    QPointF(x0, y0 + cw * 0.62),
                    QPointF(x0 + cw * 0.28, y0 + cw * 0.62),
                    QPointF(x0 + cw * 0.42, y0 + cw * 0.28),
                    QPointF(x0 + cw * 0.62, y0 + cw * 0.72),
                    QPointF(x0 + cw * 0.82, y0 + cw * 0.42),
                    QPointF(x0 + cw, y0 + cw * 0.42)]),
                p.drawLine(QPointF(x0, y0 + cw * 0.78), QPointF(x0 + cw, y0 + cw * 0.78)),
            ),
            'doc': lambda: p.drawPath(self._doc_path(cw, x0, y0)),
            'gear': lambda: (
                p.drawEllipse(QPointF(x0 + cw / 2, y0 + cw / 2), 3.0, 3.0),
                p.drawEllipse(QPointF(x0 + cw / 2, y0 + cw / 2), 5.7, 5.7),
            ),
            'info': lambda: (
                p.drawEllipse(QPointF(x0 + cw / 2, y0 + cw / 2), cw / 2 - 0.4, cw / 2 - 0.4),
                p.drawLine(QPointF(x0 + cw / 2, y0 + cw * 0.34),
                           QPointF(x0 + cw / 2, y0 + cw * 0.34)),
            ),
            'home': lambda: (
                p.drawPolyline([QPointF(x0, y0 + cw * 0.46),
                                QPointF(x0 + cw / 2, y0 + 0.6),
                                QPointF(x0 + cw, y0 + cw * 0.46)]),
                p.drawPolyline([QPointF(x0 + 1.4, y0 + cw * 0.46),
                                QPointF(x0 + 1.4, y0 + cw),
                                QPointF(x0 + cw - 1.4, y0 + cw),
                                QPointF(x0 + cw - 1.4, y0 + cw * 0.46)]),
            ),
            'folder': lambda: (
                p.drawPolyline([QPointF(x0, y0 + cw),
                                QPointF(x0, y0 + cw * 0.2),
                                QPointF(x0 + cw * 0.38, y0 + cw * 0.2),
                                QPointF(x0 + cw * 0.5, y0 + cw * 0.38),
                                QPointF(x0 + cw, y0 + cw * 0.38),
                                QPointF(x0 + cw, y0 + cw),
                                QPointF(x0, y0 + cw)]),
            ),
            'upload': lambda: (
                p.drawLine(QPointF(x0 + cw / 2, y0 + cw * 0.78),
                           QPointF(x0 + cw / 2, y0 + cw * 0.06)),
                p.drawPolyline([QPointF(x0 + cw * 0.2, y0 + cw * 0.32),
                                QPointF(x0 + cw / 2, y0 + cw * 0.06),
                                QPointF(x0 + cw * 0.8, y0 + cw * 0.32)]),
                p.drawLine(QPointF(x0, y0 + cw), QPointF(x0 + cw, y0 + cw)),
            ),
        }
        paths.get(self.icon_path or 'doc', paths['doc'])()

    @staticmethod
    def _doc_path(cw, x0, y0):
        path = QPainterPath()
        path.moveTo(x0, y0 + cw)
        path.lineTo(x0, y0 + 3)
        path.lineTo(x0 + cw * 0.5, y0 + 3)
        path.lineTo(x0 + cw * 0.7, y0 + cw * 0.35)
        path.lineTo(x0 + cw, y0 + cw * 0.35)
        path.lineTo(x0 + cw, y0 + cw)
        path.closeSubpath()
        return path


class Sidebar(QWidget):
    """左侧导航栏：顶部红黄绿灯 + 导航项"""

    traffic_signal = Signal(int)
    navigate_signal = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(210)
        self.setAttribute(Qt.WA_TranslucentBackground)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 14)
        lay.setSpacing(2)

        self.header = TrafficHeader()
        self.header.traffic_signal.connect(self.traffic_signal)
        lay.addWidget(self.header)

        # 「导航」分栏的上下留白（Win11 需让分隔线）
        self._sec_top = QSpacerItem(1, _SIDE_TOP_MAC)
        lay.addItem(self._sec_top)

        section = QLabel("导航")
        section.setObjectName("SectionLabel")
        section.setContentsMargins(19, 0, 0, 0)   # 对齐下方导航项图标列
        lay.addWidget(section)

        self._sec_bot = QSpacerItem(1, _SIDE_BOT_MAC)
        lay.addItem(self._sec_bot)

        self.nav_items = []
        for key, label, ip in [("home", "首页", "home"),
                               ("sources", "仓库", "folder"),
                               ("repos", "推送", "upload"),
                               ("settings", "设置", "gear")]:
            nb = NavButton(key, label, ip)
            nb.clicked_signal.connect(self.navigate_signal)
            self.nav_items.append(nb)
            lay.addWidget(nb)
        lay.addStretch(1)
        # 主栏下方单独一个「关于」入口：与其他导航项隔开、沉底独立
        self.about_btn = NavButton("about", "关于", "info")
        self.about_btn.clicked_signal.connect(self.navigate_signal)
        self.nav_items.append(self.about_btn)
        lay.addWidget(self.about_btn)

        self.nav_items[0].set_active(True)

    def apply_style(self):
        """按当前风格调整侧栏：Win11 用系统原生标题栏（已自带应用名），
        隐藏侧栏顶部的虚拟标题行，但仍保留「导航」上方的顶部边距，避免导航标题贴顶；
        macOS 显示交通灯组并用自身留白。两种风格切换时窗口/侧栏尺寸不变。"""
        win = theme.is_win()
        self.header.setVisible(not win)
        self._sec_top.changeSize(1, _SIDE_TOP_WIN if win else _SIDE_TOP_MAC)
        self._sec_bot.changeSize(1, _SIDE_BOT_WIN if win else _SIDE_BOT_MAC)
        self.layout().activate()
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = is_dark(self)

        # Win11 顶栏由系统原生标题栏承载，这里侧栏统一为侧栏底色
        p.setPen(Qt.NoPen)
        p.setBrush(theme.st("sidebar_bg", dark))
        p.drawRect(self.rect())
        p.end()


class ContentArea(QWidget):
    """内容区页：macOS 风格留白与分区标题"""

    def __init__(self, title: str, subtitle: str, parent=None):
        super().__init__(parent)
        self.title, self.subtitle = title, subtitle

    def header_geometry(self):
        """统一内容页页标题/副标题的布局起点与宽度。

        Win11 已采用系统原生标题栏，窗口不再占用客户区顶部的自绘顶栏，
        因此内容布局与 macOS 完全一致。
        """
        return False, 30, 28, self.width() - 60

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = is_dark(self)
        pr = theme.st("panel_radius", dark)

        p.setPen(Qt.NoPen)
        p.setBrush(theme.st("content_bg", dark))
        p.drawRect(self.rect())

        _, left, top, w = self.header_geometry()

        title_font = QFont(self.font())
        title_font.setPointSize(18)
        title_font.setBold(True)
        sub_font = QFont(self.font())
        sub_font.setPointSize(10)

        # macOS / Win11(原生窗口)：标题带 + 独立圆角占位面板
        p.setFont(title_font)
        p.setPen(theme.st("title_text", dark))
        p.drawText(QRectF(left, top, w, 30), Qt.AlignVCenter | Qt.AlignLeft, self.title)
        p.setFont(sub_font)
        p.setPen(theme.st("sub_text", dark))
        p.drawText(QRectF(left, top + 34, w, 22), Qt.AlignVCenter | Qt.AlignLeft, self.subtitle)

        panel_r = QRectF(left, top + 72, w, self.height() - (top + 102))
        p.setPen(QPen(theme.st("panel_border", dark), 1))
        p.setBrush(theme.st("panel_bg", dark))
        p.drawRoundedRect(panel_r, pr, pr)

        f = QFont(self.font())
        f.setPointSize(11)
        p.setFont(f)
        p.setPen(theme.st("placeholder", dark))
        p.drawText(panel_r, Qt.AlignCenter, "内容占位区 — 可在此放入自定义功能模块")
        p.end()


class SegmentControl(QWidget):
    """分段胶囊：档位等分，焦点气泡随选中档位滑动（220ms OutCubic）。

    取自 LANSyncBox 的投递模式切换控件：浅色下为白气泡 + 淡阴影，
    深色下为浅灰气泡；未选档位悬停时叠一层淡色作为反馈。
    """

    valueChanged = Signal(str)

    _MARGIN = 3
    _H = 26

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(self._H)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self._keys, self._labels = [], []
        self._value = ""
        self._pos = 0.0
        self._hover_side = -1
        self._anim = None

    def add_segment(self, key: str, label: str):
        self._keys.append(key)
        self._labels.append(label)
        if len(self._keys) == 1:
            self._value = key
        # 等分档位：宽度取最宽文字，各档一致，气泡位置 = 档位序号
        fm = QFontMetrics(self._seg_font())
        seg = max(fm.horizontalAdvance(t) for t in self._labels) + 30
        self.setFixedWidth(seg * len(self._keys))

    def value(self) -> str:
        return self._value

    def set_value(self, value: str, animate: bool = True):
        """切换档位；animate=False 时直接到位"""
        if value not in self._keys:
            return
        self._value = value
        target = float(self._keys.index(value))
        if animate and abs(target - self._pos) > 1e-3:
            self._stop_anim()
            anim = QVariantAnimation(self)
            anim.setDuration(220)
            anim.setStartValue(self._pos)
            anim.setEndValue(target)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.valueChanged.connect(lambda v: self._set_pos(float(v)))
            anim.finished.connect(self._on_anim_finished)
            self._anim = anim
            anim.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
        else:
            self._stop_anim()
            self._pos = target
            self.update()

    def _set_pos(self, v: float):
        self._pos = v
        self.update()

    def _stop_anim(self):
        # DeleteWhenStopped 会让动画在停止时被 Qt 删除，先摘掉引用再 stop
        anim = self._anim
        self._anim = None
        if anim is not None:
            anim.stop()

    def _on_anim_finished(self):
        self._anim = None

    def _seg_font(self) -> QFont:
        f = QFont(self.font())
        f.setPointSize(10)
        f.setWeight(QFont.Weight.DemiBold)
        return f

    def _side_at(self, x: float) -> int:
        n = len(self._keys)
        if n == 0 or x < 0:
            return -1
        return min(int(x / (self.width() / float(n))), n - 1)

    def enterEvent(self, e):
        self._hover_side = self._side_at(e.position().x())
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover_side = -1
        self.update()
        super().leaveEvent(e)

    def mouseMoveEvent(self, e):
        self._hover_side = self._side_at(e.position().x())
        self.update()
        super().mouseMoveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            side = self._side_at(e.position().x())
            if side >= 0 and self._keys[side] != self._value:
                self.valueChanged.emit(self._keys[side])
        super().mousePressEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = is_dark(self)
        w, h = self.width(), self.height()
        n = len(self._keys)
        if n == 0:
            p.end()
            return
        r = h / 2.0
        m = self._MARGIN
        seg_w = w / float(n)

        # 胶囊底板（中性玻璃）
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 26) if dark else QColor(15, 23, 42, 24))
        p.drawRoundedRect(QRectF(0, 0, w, h), r, r)

        active_i = self._keys.index(self._value) if self._value in self._keys else 0
        # 未选中档位的悬浮反馈
        if 0 <= self._hover_side != active_i:
            hover = QRectF(self._hover_side * seg_w + m, m,
                           seg_w - 2 * m, h - 2 * m)
            p.setBrush(QColor(255, 255, 255, 30) if dark else QColor(15, 23, 42, 32))
            p.drawRoundedRect(hover, (h - 2 * m) / 2.0, (h - 2 * m) / 2.0)

        # 焦点气泡：随 _pos 滑动，与档位中心严格对齐
        bubble = QRectF(m + self._pos * seg_w, m, seg_w - 2 * m, h - 2 * m)
        radius = (h - 2 * m) / 2.0
        if not dark:
            # 浅色下加深色淡阴影 + 描边，避免白气泡与灰底板糊在一起
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(15, 23, 42, 22))
            p.drawRoundedRect(QRectF(bubble.x(), bubble.y() + 1,
                                     bubble.width(), bubble.height()), radius, radius)
            p.setPen(QPen(QColor(15, 23, 42, 18), 1))
        else:
            p.setPen(Qt.NoPen)
        p.setBrush(QColor("#eceef2") if dark else QColor("#ffffff"))
        p.drawRoundedRect(bubble, radius, radius)

        # 档位文字
        p.setFont(self._seg_font())
        for i, label in enumerate(self._labels):
            if i == active_i:
                color = QColor("#1f2328")
            else:
                color = QColor("#a0a0a0") if dark else QColor("#6b7280")
            p.setPen(color)
            p.drawText(QRectF(i * seg_w, 0, seg_w, h),
                       Qt.AlignHCenter | Qt.AlignVCenter, label)
        p.end()


class SettingRow(QWidget):
    """设置行：左侧分组标题，右侧分段胶囊；只有一个选项时右侧显示取值文本"""

    valueChanged = Signal(str)

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.title = title
        self._value_text = ""
        self._base = (-99999, -99999, 1, 1)
        self.seg = SegmentControl(self)
        self.seg.valueChanged.connect(self.valueChanged)

    def add_segment(self, key: str, label: str):
        self.seg.add_segment(key, label)

    def set_value_text(self, text: str):
        self._value_text = text
        self.seg.setVisible(not text)
        self.update()

    def set_value(self, key: str, animate: bool = True):
        self.seg.set_value(key, animate)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.seg.move(self.width() - self.seg.width() - 16,
                      (self.height() - self.seg.height()) // 2)

    def paintEvent(self, e):
        # 行本身不画卡片底/描边，只画左侧标题；控件由子级胶囊负责
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = is_dark(self)

        cy = self.height() / 2
        tf = QFont(self.font())
        tf.setPointSize(11)
        tf.setBold(True)
        p.setFont(tf)
        p.setPen(theme.st("title_text", dark))
        p.drawText(QRectF(16, cy - 16, self.width() - 32, 32),
                   Qt.AlignLeft | Qt.AlignVCenter, self.title)

        if self._value_text:
            p.setFont(self.seg._seg_font())
            p.setPen(theme.st("sub_text", dark))
            p.drawText(QRectF(16, cy - 16, self.width() - 32, 32),
                       Qt.AlignRight | Qt.AlignVCenter, self._value_text)
        p.end()


class AboutPage(ContentArea):
    """关于页：内容已清空，保留页面占位。"""

    def __init__(self, parent=None):
        super().__init__("", "")

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), theme.st("content_bg", is_dark(self)))
        p.end()


class CategoryList(QWidget):
    """设置分类子菜单：左侧竖直胶囊列表，支持选中高亮与悬停，点击切换分类。"""

    picked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = []
        self._active = 0
        self._hover = -1
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)

    def set_items(self, titles):
        self.items = list(titles)
        self._active = min(self._active, len(self.items) - 1)
        self._hover = -1
        self.update()

    def set_active(self, idx):
        if idx is not None and idx != self._active:
            self._active = idx
            self.update()

    # 每个选项高度/间距，与 paint 保持一致
    ITEM_H, GAP, START = 38, 6, 4

    def _index_at(self, p):
        if not self.items:
            return -1
        rel = p.y() - self.START
        if rel < 0:
            return -1
        step = self.ITEM_H + self.GAP
        idx = rel // step
        return idx if idx < len(self.items) else -1

    def _item_rect(self, i):
        y = self.START + i * (self.ITEM_H + self.GAP)
        return QRectF(self.START, y, self.width() - 2 * self.START, self.ITEM_H)

    def paintEvent(self, _):
        if not self.items:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = is_dark(self)
        accent = theme.st("accent", dark)
        f = QFont(self.font()); f.setPointSize(10); f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        for i, t in enumerate(self.items):
            r = self._item_rect(i)
            if i == self._active:
                sel = QColor(accent.red(), accent.green(), accent.blue(), 42)
                p.setPen(Qt.NoPen)
                p.setBrush(sel)
                p.drawRoundedRect(r, 8, 8)
                p.setPen(accent)
            elif i == self._hover:
                p.setPen(Qt.NoPen)
                p.setBrush(theme.st("nav_hover", dark))
                p.drawRoundedRect(r, 8, 8)
                p.setPen(theme.st("title_text", dark))
            else:
                p.setPen(theme.st("sub_text", dark))
            p.drawText(r, Qt.AlignCenter, t)
        p.end()

    def mousePressEvent(self, e):
        idx = self._index_at(e.position().toPoint())
        if idx >= 0:
            self.picked.emit(idx)
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        h = self._index_at(e.position().toPoint())
        if h != self._hover:
            self._hover = h
            self.update()

    def leaveEvent(self, e):
        if self._hover != -1:
            self._hover = -1
            self.update()
        super().leaveEvent(e)


class _RightArea(QWidget):
    """右侧设置区：承载当前分类的选项卡，并绘制分组标题。

    作为整体容器做分类切换时的淡出/淡入过渡；自身透明，露出页面底色。
    """

    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)

    # 分组标题画在 SettingRow 卡片里，容器本身只负责承载与滚动


class SettingsPage(ContentArea):
    """设置页：两级结构 = 分类(Category) → 分组(Section) → 选项(Option)。

    左侧为分类子菜单（CategoryList），右侧展示当前分类下的分组与选项卡。
    全部分类/分组/选项通过数据注册按序构建：
      add_category → add_section → add_option
    菜单顺序即注册顺序，因此要在「个性化」之前插入「常规」，只需先注册常规。
    内容超高时右侧区域鼠标滚轮滚动，左侧菜单与页头保持固定。
    """

    option_picked = Signal(str, str)      # (分组id, 选项key)，分发层只需关心分组
    CARD_H = 68
    MENU_W = 96                           # 左侧分类菜单宽度

    def __init__(self, parent=None):
        super().__init__("设置", "个性化外观与行为")
        # [cid, title, sections]；sections=[sid, 标题, [(key,label)], 行控件]
        self.categories = []
        self._active = 0
        self._content_top = 0
        self._content_w = 0
        self._content_h = 0
        self._scroll = 0
        self._cat_anim = None                 # 分类切换过渡动画
        # 分类子菜单控件 + 右侧内容容器（作为整体做切换过渡）
        self._menu = CategoryList(self)
        self._menu.picked.connect(self._switch_category)
        self._right = _RightArea(self)
        # 注册内置设置（顺序即侧菜单顺序：常规在前，个性化在后）
        self._register_builtin()
        self._refresh_menu()
        self._preselect()

    def add_category(self, cid: str, title: str):
        self.categories.append([cid, title, []])
        self._refresh_menu()

    def add_section(self, cid: str, section_id: str, title: str):
        for cat in self.categories:
            if cat[0] == cid:
                row = SettingRow(title, self._right)
                row.valueChanged.connect(
                    lambda k, sid=section_id: self.option_picked.emit(sid, k))
                cat[2].append([section_id, title, [], row])
                return

    def add_option(self, cid: str, section_id: str, key: str, label: str):
        for cat in self.categories:
            if cat[0] != cid:
                continue
            for sec in cat[2]:
                if sec[0] == section_id:
                    sec[2].append((key, label))
                    sec[3].add_segment(key, label)
                    return

    def _register_builtin(self):
        # 「常规」注册在「个性化」之前，故侧菜单排在前面
        self.add_category("general", "常规")
        self.add_section("general", "about", "通用")
        self.add_option("general", "about", "version", f"应用 · {Config.APP_NAME}")

        self.add_category("personal", "个性化")
        self.add_section("personal", "style", "界面风格")
        for key in theme.STYLE_KEYS:
            self.add_option("personal", "style", key, theme.STYLE_LABEL[key])
        self.add_section("personal", "theme", "深浅色模式")
        for key in theme.THEMES:
            self.add_option("personal", "theme", key, theme.THEME_LABEL[key])

        self.add_category("security", "安全")
        self.add_section("security", "sensitive", "敏感操作二次校验")
        self.add_option("security", "sensitive", "off", "关闭")
        self.add_option("security", "sensitive", "on", "开启")

    def _refresh_menu(self):
        self._menu.set_items([c[1] for c in self.categories])

    def _preselect(self):
        for cat in self.categories:
            for sid, _, items, row in cat[2]:
                if sid == "style":
                    self.select(sid, theme.style_name())
                elif sid == "theme":
                    self.select(sid, theme.theme_mode_name())
                elif sid == "sensitive":
                    self.select(sid, "on" if store.sensitive_verify_required() else "off")
        # 初始选中首个包含分组内容的分类
        self._active = next((i for i, c in enumerate(self.categories) if c[2]), 0)
        self._menu.set_active(self._active)

    def _switch_category(self, idx):
        self._active = idx
        self._menu.set_active(idx)
        self._scroll = 0
        self._measure()
        self._apply_scroll()

    def select(self, section_id: str, key: str, animate: bool = True):
        for cat in self.categories:
            for sid, _, items, row in cat[2]:
                if sid == section_id:
                    row.set_value(key, animate)

    def _measure(self):
        gap = 16
        y = 0
        for sid, sec_title, items, row in self.categories[self._active][2]:
            if not items:
                row.setVisible(False)
                continue
            # 单选项的分组（如版本信息）不显示胶囊，右侧直接显示取值
            row.set_value_text(items[0][1] if len(items) == 1 else "")
            row._base = (0, y, self._content_w, self.CARD_H)
            y += self.CARD_H + gap
        self._content_h = max(0, y - gap)

    def _layout_right(self):
        """左侧菜单 + 右侧容器几何，并重排当前分类内容。"""
        _, x0, top, _ = self.header_geometry()
        # 与概览等 ContentArea 页面内容面板顶部(top+72)保持同一高度，全局布局统一
        self._content_top = top + 72
        self._content_w = self.width() - 2 * x0 - self.MENU_W - 24
        self._menu.setGeometry(x0, self._content_top, self.MENU_W,
                               self.height() - self._content_top)
        self._right.setGeometry(x0 + self.MENU_W + 24, self._content_top,
                                self._content_w, self.height() - self._content_top)
        self._measure()
        self._clamp_scroll()
        self._apply_scroll()

    def _clamp_scroll(self):
        view_h = self._right.height()
        self._scroll = max(0, min(self._scroll, self._content_h - view_h))

    def _apply_scroll(self):
        """按激活分类定位设置行；其余分类的行隐藏，避免不同分类间互串重叠。"""
        for i, cat in enumerate(self.categories):
            for _, _, items, row in cat[2]:
                active = i == self._active and items
                if not active:
                    row.setVisible(False)
                    continue
                x, y, w, h = row._base
                row.setGeometry(x, y - self._scroll, w, h)
                row.setVisible(True)
        self._right.update()

    def wheelEvent(self, e):
        if self._content_h > self._right.height():
            delta = e.angleDelta().y()
            self._scroll -= delta // 8
            self._clamp_scroll()
            self._apply_scroll()
            e.accept()
        else:
            super().wheelEvent(e)

    def _switch_category(self, idx):
        """分类切换：对右侧容器做一次淡出+淡入过渡。"""
        if idx < 0 or idx >= len(self.categories) or idx == self._active:
            return
        if self._cat_anim is not None:
            self._cat_anim.stop()
            self._cat_anim = None
        right = self._right
        eff = QGraphicsOpacityEffect(right)
        right.setGraphicsEffect(eff)

        def _finish_anim(a):
            if right.graphicsEffect() is eff:
                right.setGraphicsEffect(None)
            if self._cat_anim is a:
                self._cat_anim = None

        def _do_switch():
            self._active = idx
            self._menu.set_active(idx)
            self._scroll = 0
            self._layout_right()
            eff.setOpacity(0.0)
            a2 = QVariantAnimation(right)
            a2.setDuration(130)
            a2.setStartValue(0.0)
            a2.setEndValue(1.0)
            a2.setEasingCurve(QEasingCurve.OutCubic)
            a2.valueChanged.connect(lambda v: eff.setOpacity(float(v)))
            a2.finished.connect(lambda: _finish_anim(a2))
            a2.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
            self._cat_anim = a2

        a1 = QVariantAnimation(right)
        a1.setDuration(110)
        a1.setStartValue(1.0)
        a1.setEndValue(0.0)
        a1.setEasingCurve(QEasingCurve.OutCubic)
        a1.valueChanged.connect(lambda v: eff.setOpacity(float(v)) )
        a1.finished.connect(lambda: (eff.setOpacity(0.0), _do_switch()))
        a1.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
        self._cat_anim = a1

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = is_dark(self)

        p.setPen(Qt.NoPen)
        p.setBrush(theme.st("content_bg", dark))
        p.drawRect(self.rect())

        title_font = QFont(self.font()); title_font.setPointSize(18); title_font.setBold(True)
        sub_font = QFont(self.font()); sub_font.setPointSize(10)

        _, left, top, w = self.header_geometry()
        p.setFont(title_font)
        p.setPen(theme.st("title_text", dark))
        p.drawText(QRectF(left, top, w, 30), Qt.AlignVCenter | Qt.AlignLeft, self.title)
        p.setFont(sub_font)
        p.setPen(theme.st("sub_text", dark))
        p.drawText(QRectF(left, top + 34, w, 22), Qt.AlignVCenter | Qt.AlignLeft, self.subtitle)
        p.end()

    def resizeEvent(self, e):
        self._layout_right()
        super().resizeEvent(e)


class PageStack(QStackedWidget):
    """页面容器：以当前内容区底色填充自身背景。

    默认的 QStackedWidget 背景透明，页面在切换动画中滑出/淡出后，露出的
    底层会呈现深色（浅色主题下即为黑色断层）。这里像各内容页一样用指定
    主题色绘制底色，保证浅色模式下过渡为白色、深色模式下为深色。
    """

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(theme.st("content_bg", is_dark(self)))
        p.drawRect(self.rect())
        p.end()
        super().paintEvent(e)


class AppWindow(QWidget):
    """主窗口：系统原生圆角(DWM) + 原生展开/收起/最小化动画 + 左侧导航"""

    def __init__(self):
        super().__init__()
        # 保留系统原生外壳(Win11 自带圆角/阴影)，标题栏内容用
        # WM_NCCALCSIZE 裁掉，从而获得原生最大化/最小化/贴边动画
        self.setMinimumSize(_DEF_MIN_W, _DEF_MIN_H)
        self.setWindowTitle(Config.APP_NAME)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.sidebar = Sidebar()
        self.sidebar.traffic_signal.connect(self._on_traffic)
        self.sidebar.navigate_signal.connect(self._switch_page)
        root.addWidget(self.sidebar)

        self.stack = PageStack()
        self.pages = {}
        root.addWidget(self.stack, 1)

        # 注册内容页（设置页使用专门的交互页面，关于页使用独立信息页）
        self.settings_page = None
        self.repo_page = None
        self.sources_page = None
        self.home_page = None
        for item in self.sidebar.nav_items:
            if item.key == "settings":
                p = SettingsPage()
                self.settings_page = p
                p.option_picked.connect(self._on_settings_option)
            elif item.key == "about":
                p = AboutPage()
            elif item.key == "home":
                p = HomePage()
                self.home_page = p
            elif item.key == "sources":
                p = SourcesPage()
                self.sources_page = p
            elif item.key == "repos":
                p = RepoPage()
                self.repo_page = p
            else:
                p = ContentArea(item.label, "自定义功能待填充")
            self.add_page(item.key, p)

        # 内容区顶部透明拖拽条（仅 macOS 自绘顶栏使用）
        self._topdrag = TopDragBar(self)
        self._topdrag.traffic_signal.connect(self._on_traffic)
        self._topdrag.setVisible(theme.is_mac())
        self._topdrag.raise_()

        self._opened = False
        self._zoomed = False
        self._normal_geom = None
        self._zoom_anim = None
        self._switch_anim = None
        self._switch_widgets = None

    def showEvent(self, e):
        super().showEvent(e)
        if not self._opened:
            self._opened = True
            QTimer.singleShot(0, lambda: set_native_round(self, True))
        # 用 QWindow::activeChanged 可靠跟踪窗口焦点（Windows 上比 changeEvent 稳定）
        handle = self.windowHandle()
        if handle is not None and not getattr(self, '_active_connected', False):
            handle.activeChanged.connect(self._on_window_active_changed)
            self._active_connected = True

    def _on_window_active_changed(self):
        if self.windowHandle() is not None:
            self.sidebar.header.set_window_active(self.windowHandle().isActive())

    def nativeEvent(self, eventType, message):
        """Windows 原生事件：macOS 自绘顶栏模式裁掉原生标题栏，并在 WM_NCHITTEST
        中把窗口边缘伪装成对应缩放码，从而由系统接管边缘缩放（Win11 用系统原生标题栏，
        此路径不进入）。Windows 原生最大化/最小化动画均由 DWM 提供、不闪烁。
        """
        # Win11 采用系统原生标题栏，不做任何裁剪/命中伪装，全部由系统接管；
        # 仅 macOS 自绘顶栏才需要裁剪原生标题栏并伪装命中码。
        if not _WIN32 or theme.is_win():
            return super().nativeEvent(eventType, message)
        try:
            import ctypes
            from ctypes import wintypes
            msg = wintypes.MSG.from_address(int(message))
            m = msg.message
            if m == _WM_NCCALCSIZE:                 # 裁掉原生标题栏/边框
                return True, 0
            if m == _WM_NCHITTEST and not self.isMaximized():
                ht = _edge_hit_test(self, msg.lParam)
                if ht:
                    return True, ht
        except Exception:
            pass
        return super().nativeEvent(eventType, message)

    def add_page(self, key: str, widget: QWidget):
        self.pages[key] = widget
        self.stack.addWidget(widget)
        if len(self.pages) == 1:
            self.stack.setCurrentWidget(widget)

    def _reset_switch_widgets(self):
        """动画被中止后复位受影响页面：清除透明效果与位移，避免残留/错位。"""
        ws = self._switch_widgets or ()
        for w in ws:
            if w is not None:
                w.setGraphicsEffect(None)
                w.move(0, 0)
        self._switch_widgets = None

    def _switch_page(self, key: str):
        for item in self.sidebar.nav_items:
            item.set_active(item.key == key)
        if key not in self.pages or self.stack.currentWidget() is self.pages[key]:
            return
        # 防抖：上一轮过渡仍在播放时（并非因中途停止而残留透明效果/位移），
        # 先中止并复位，再重新开启本轮过渡。
        if self._switch_anim is not None:
            self._switch_anim.stop()
            self._switch_anim = None
            self._reset_switch_widgets()

        old = self.stack.currentWidget()
        new = self.pages[key]
        self._switch_widgets = [old, new]
        SHIFT = 30          # 滑移距离(px)，对齐 github.io 的温和幅度
        MS = 200            # 单段动画时长

        # ---- 阶段1：旧页向左滑出并淡出 ----
        old_eff = QGraphicsOpacityEffect(old)
        old.setGraphicsEffect(old_eff)
        a1 = QVariantAnimation(old)
        a1.setDuration(MS)
        a1.setStartValue(0.0)
        a1.setEndValue(1.0)
        a1.setEasingCurve(QEasingCurve.OutCubic)

        def f1(t):
            old.move(-int(SHIFT * t), 0)
            old_eff.setOpacity(1.0 - t)
        a1.valueChanged.connect(f1)

        # ---- 阶段2：新页自右滑入并淡入（旧页退场完成后开始）----
        def _play_in():
            new_eff = QGraphicsOpacityEffect(new)
            new.setGraphicsEffect(new_eff)
            new.move(SHIFT, 0)
            new_eff.setOpacity(0.0)
            self.stack.setCurrentWidget(new)
            a2 = QVariantAnimation(new)
            a2.setDuration(MS)
            a2.setStartValue(0.0)
            a2.setEndValue(1.0)
            a2.setEasingCurve(QEasingCurve.OutCubic)

            def f2(t):
                new.move(int(SHIFT * (1 - t)), 0)
                new_eff.setOpacity(t)

            def finish_a2():
                new.setGraphicsEffect(None)
                new.move(0, 0)
                if self._switch_anim is a2:
                    self._switch_anim = None
                    self._switch_widgets = None
            a2.valueChanged.connect(f2)
            a2.finished.connect(finish_a2)
            a2.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
            self._switch_anim = a2

        def finish_a1():
            old.setGraphicsEffect(None)
            old.move(0, 0)
            _play_in()
        a1.finished.connect(finish_a1)
        a1.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
        self._switch_anim = a1

    def set_style(self, key: str):
        # 状态与校验由 theme 模块负责，这里只执行 UI 层刷新
        if not theme.set_style(key):
            return
        QApplication.instance().setStyleSheet(apply_style())
        # 顶栏随风格切换：Win11 由系统原生标题栏承载，仅 macOS 使用自绘顶栏
        self._topdrag.setVisible(theme.is_mac())
        self.sidebar.apply_style()
        self.sidebar.header.apply_style()
        self._relayout_overlays()
        # 强制 Windows 重算非客户区，让原生标题栏在 mac 裁剪与 win 展示间即时切换
        _force_frame_recalc(self)
        # 最小尺寸贴合当前风格的实际客户区，见 _adapt_min_size 注释。
        # 必须等 frame 重算事件流处理完（geometry 还原为真实客户区）后再同步。
        QTimer.singleShot(0, self._adapt_min_size)
        # 全量重绘：侧栏、各内容页、红绿灯、设置卡
        for w in [self.sidebar, self.settings_page, self.stack] + list(self.pages.values()):
            w.update()
        if self.repo_page is not None:
            self.repo_page.apply_style()
        if self.sources_page is not None:
            self.sources_page.apply_style()
        for b in self.sidebar.header.findChildren(TrafficLightButton):
            b.update()
        self.settings_page.select("style", key)

    def _on_settings_option(self, sid: str, key: str):
        # 外观偏好即时写回配置文件（键名与 theme 模块的模式名一致）
        if sid == "style":
            self.set_style(key)
            store.set_value("style", theme.style_name())
        elif sid == "theme":
            self.set_theme(key)
            store.set_value("theme", theme.theme_mode_name())
        elif sid == "sensitive":
            if key == "on":
                store.set_value("sensitive_verify", True)
            else:
                self._disable_sensitive_guard()

    def _disable_sensitive_guard(self):
        """关闭敏感操作二次校验本身需要验证身份；不通过则保持开启。"""
        def done(result):
            if not result.ok:
                QMessageBox.information(self, "未关闭",
                                        f"{result.message}，该保护保持开启")
                return
            store.set_value("sensitive_verify", False)
            self.settings_page.select("sensitive", "off")

        self.repo_page.confirm("GiTool：关闭敏感操作二次校验需要验证身份", done)

    def set_theme(self, key: str):
        if not theme.set_theme(key):
            return
        QApplication.instance().setStyleSheet(apply_style())
        # 全量重绘：侧栏、各内容页、红绿灯、设置卡；深浅色不影响窗口框架，无须重算非客户区
        for w in [self.sidebar, self.settings_page, self.stack] + list(self.pages.values()):
            w.update()
        if self.repo_page is not None:
            self.repo_page.apply_style()
        if self.sources_page is not None:
            self.sources_page.apply_style()
        for b in self.sidebar.header.findChildren(TrafficLightButton):
            b.update()
        self.settings_page.select("theme", key)

    def changeEvent(self, e):
        # 窗口失焦/回焦时同步红绿灯亮灰状态（macOS 行为）
        if e.type() == QEvent.WindowDeactivate:
            self.sidebar.header.set_window_active(False)
        elif e.type() == QEvent.WindowActivate:
            self.sidebar.header.set_window_active(True)
        elif e.type() == QEvent.WindowStateChange:
            self._sync_light_poll()
        super().changeEvent(e)

    def _sync_light_poll(self):
        """最小化时暂停红绿灯悬停轮询、还原后恢复（仅 macOS 风格，最小化不可见无须轮询）"""
        if theme.is_win():
            return
        header = self.sidebar.header
        if self.isMinimized():
            header.stop_polling()
        else:
            header.start_polling()

    def _on_traffic(self, idx: int):
        if idx == 0:
            self.close()                     # 原生关闭
        elif idx == 1:
            if self._zoom_anim:
                self._zoom_anim.stop()
            self.showMinimized()             # 原生最小化到任务栏动画
        else:
            self._toggle_zoom()              # 几何展开/收起动画

    def _toggle_zoom(self):
        if _WIN32:
            # 保留原生外壳 → 由 DWM 播放原生的最大化/还原动画
            if self.isMaximized():
                self.showNormal()
            else:
                self.showMaximized()
            return
        # 非 Windows 回退：自绘几何动画
        if self._zoomed:
            target = QRect(self._normal_geom) if self._normal_geom else self._fallback_rect()
            self._run_zoom(target, end_zoomed=False)
        else:
            self._normal_geom = self.frameGeometry()
            screen = QGuiApplication.screenAt(self._normal_geom.center()) or self.screen()
            self._run_zoom(screen.availableGeometry(), end_zoomed=True)

    def _fallback_rect(self):
        screen = self.screen()
        sg = screen.availableGeometry()
        w, h = min(1000, sg.width() - 60), min(680, sg.height() - 60)
        return QRect(sg.center().x() - w // 2, sg.center().y() - h // 2, w, h)

    def _run_zoom(self, target: QRect, end_zoomed: bool):
        if self._zoom_anim:
            self._zoom_anim.stop()
        # 最大化铺屏时去圆角，还原时恢复圆角
        set_native_round(self, not end_zoomed)
        anim = QVariantAnimation(self)
        anim.setDuration(ZOOM_MS)
        anim.setStartValue(self.geometry())
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.valueChanged.connect(self.setGeometry)
        anim.finished.connect(lambda: self._finish_zoom(anim, end_zoomed, target))
        anim.start()
        self._zoom_anim = anim

    def _finish_zoom(self, anim, end_zoomed: bool, target: QRect):
        if anim is not self._zoom_anim:
            return
        self.setGeometry(target)
        self._zoomed = end_zoomed
        QTimer.singleShot(0, lambda: set_native_round(self, not self._zoomed))

    def resizeEvent(self, e):
        self._relayout_overlays()
        super().resizeEvent(e)

    def _relayout_overlays(self):
        """按当前风格摆放顶层覆盖控件（仅 macOS 拖拽条；Win11 用系统原生标题栏）"""
        if theme.is_mac():
            self._topdrag.setGeometry(
                self.sidebar.width(), 0, self.width() - self.sidebar.width(), bar_h())
            self._topdrag.raise_()

    def _adapt_min_size(self):
        """随风格把最小尺寸同步到当前实际客户区。

        保持外框不变时，Win11 原生标题栏/边框会占去一部分客户区；若仍按 macOS
        的全尺寸下限，Qt 会在拖拽/移动时把窗口按旧的最小尺寸重新撑大，导致底部
        多出一截。因此切换到带原生标题栏的风格后，按 Qt 已还原的真实客户区重申
        下限；切回 macOS 再恢复默认。
        """
        if theme.is_win():
            g = self.normalGeometry() if self.isMaximized() else self.geometry()
            self.setMinimumSize(max(1, g.width()), max(1, g.height()))
        else:
            self.setMinimumSize(_DEF_MIN_W, _DEF_MIN_H)

    def closeEvent(self, e):
        # 关闭前收敛后台扫描/验证线程，避免 QThread 在运行中被销毁
        if self.repo_page is not None:
            self.repo_page.shutdown()
        scan_service().shutdown()
        super().closeEvent(e)


def apply_style(dark: bool = None):
    """应用当前界面风格的 QSS（文字颜色取自风格注册表 + 系统主题）"""
    if dark is None:
        ov = theme.dark_override()
        if ov is not None:
            dark = ov
        else:
            app = QApplication.instance()
            dark = app.palette().color(QPalette.ColorRole.Window).lightness() < 128
    title_col = theme.st("title_text", dark).name()
    sub_col = theme.st("sub_text", dark).name()
    section_col = theme.st("section_text", dark).name()
    return f"""
    QWidget {{ font-family: "Microsoft YaHei UI"; color: {title_col}; }}
    #TitleLabel {{ font-size: 12px; color: {sub_col}; background: transparent; border: none; }}
    #SectionLabel {{ font-size: 10px; color: {section_col}; background: transparent; }}
    """