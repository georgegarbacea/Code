"""Custom widgets: toggle switch, slider rows, navigation rail, effect cards, meters."""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import (Property, QEasingCurve, QPoint, QPointF, QPropertyAnimation, QRect, QRectF, QSize, Qt,
                            QTimer, Signal)
from PySide6.QtGui import (QBrush, QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen,
                           QRadialGradient)
from PySide6.QtWidgets import (QAbstractButton, QColorDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLayout,
                               QPushButton, QSizePolicy, QSlider, QVBoxLayout, QWidget)

from . import theme as T


def label(text: str, role: str | None = None, wrap: bool = False) -> QLabel:
    l = QLabel(text)
    if role:
        l.setProperty("role", role)
    l.setWordWrap(wrap)
    return l


def card(title: str | None = None, subtitle: str | None = None, flat: bool = False) -> tuple[QFrame, QVBoxLayout]:
    f = QFrame()
    f.setProperty("card", "flat" if flat else "true")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(16, 14, 16, 16)
    lay.setSpacing(10)
    if title:
        lay.addWidget(label(title.upper(), "section"))
    if subtitle:
        lay.addWidget(label(subtitle, "muted", wrap=True))
    return f, lay


def button(text: str, kind: str | None = None, checkable: bool = False, tip: str = "") -> QPushButton:
    b = QPushButton(text)
    if kind:
        b.setProperty("kind", kind)
    b.setCheckable(checkable)
    b.setCursor(Qt.PointingHandCursor)
    if tip:
        b.setToolTip(tip)
    return b


def hbox(*widgets, spacing: int = 8, margins=(0, 0, 0, 0)) -> QHBoxLayout:
    h = QHBoxLayout()
    h.setSpacing(spacing)
    h.setContentsMargins(*margins)
    for w in widgets:
        if w == "stretch":
            h.addStretch(1)
        elif isinstance(w, int):
            h.addSpacing(w)
        elif hasattr(w, "setParent") and not isinstance(w, (QHBoxLayout, QVBoxLayout)):
            h.addWidget(w)
        else:
            h.addLayout(w)
    return h


# ---------------------------------------------------------------------------- toggle
class Toggle(QAbstractButton):
    def __init__(self, checked: bool = False, parent=None, warn: bool = False):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self._pos = 1.0 if checked else 0.0
        self.warn = warn
        self.anim = QPropertyAnimation(self, b"knob", self)
        self.anim.setDuration(160)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)

    def sizeHint(self):
        return QSize(46, 26)

    def _animate(self, on: bool):
        self.anim.stop()
        self.anim.setStartValue(self._pos)
        self.anim.setEndValue(1.0 if on else 0.0)
        self.anim.start()

    def setCheckedSilent(self, on: bool):
        self.blockSignals(True)
        self.setChecked(on)
        self.blockSignals(False)
        self._pos = 1.0 if on else 0.0
        self.update()

    def get_knob(self):
        return self._pos

    def set_knob(self, v):
        self._pos = v
        self.update()

    knob = Property(float, get_knob, set_knob)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(1, 1, self.width() - 2, self.height() - 2)
        off = QColor(T.SURFACE3)
        if self.warn:
            on1, on2 = QColor(T.WARN), QColor("#ff7a45")
        else:
            on1, on2 = QColor(T.A1), QColor(T.A2)
        g = QLinearGradient(r.topLeft(), r.topRight())
        k = self._pos
        c1 = QColor.fromRgbF(off.redF() + (on1.redF() - off.redF()) * k, off.greenF() + (on1.greenF() - off.greenF()) * k,
                             off.blueF() + (on1.blueF() - off.blueF()) * k)
        c2 = QColor.fromRgbF(off.redF() + (on2.redF() - off.redF()) * k, off.greenF() + (on2.greenF() - off.greenF()) * k,
                             off.blueF() + (on2.blueF() - off.blueF()) * k)
        g.setColorAt(0, c1)
        g.setColorAt(1, c2)
        p.setPen(QPen(QColor(T.BORDER2), 1) if k < 0.5 else Qt.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 6
        x = r.left() + 3 + (r.width() - d - 6) * k
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(QRectF(x, r.top() + 3, d, d))
        if not self.isEnabled():
            p.fillRect(r, QColor(0, 0, 0, 120))


class ToggleRow(QWidget):
    toggled = Signal(bool)

    def __init__(self, text: str, checked: bool = False, sub: str = "", warn: bool = False):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(label(text))
        if sub:
            col.addWidget(label(sub, "dim", wrap=True))
        lay.addLayout(col, 1)
        self.toggle = Toggle(checked, warn=warn)
        self.toggle.toggled.connect(self.toggled)
        lay.addWidget(self.toggle, 0, Qt.AlignVCenter)

    def setChecked(self, v: bool):
        self.toggle.setCheckedSilent(v)

    def isChecked(self) -> bool:
        return self.toggle.isChecked()


# ---------------------------------------------------------------------------- slider
class SliderRow(QWidget):
    valueChanged = Signal(float)

    def __init__(self, text: str, lo: float, hi: float, value: float, fmt=None, warm: bool = False,
                 decimals: int = 2, tip: str = ""):
        super().__init__()
        self.lo, self.hi = lo, hi
        self.fmt = fmt or (lambda v: f"{v:.{decimals}f}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        top = QHBoxLayout()
        self.name = label(text, "muted")
        self.val = label("", "value")
        top.addWidget(self.name)
        top.addStretch(1)
        top.addWidget(self.val)
        lay.addLayout(top)
        self.s = QSlider(Qt.Horizontal)
        self.s.setRange(0, 1000)
        if warm:
            self.s.setProperty("warm", True)
        self.s.setCursor(Qt.PointingHandCursor)
        if tip:
            self.setToolTip(tip)
        lay.addWidget(self.s)
        self.s.valueChanged.connect(self._changed)
        self.setValue(value)

    def _to_slider(self, v: float) -> int:
        return int(round((v - self.lo) / (self.hi - self.lo) * 1000))

    def value(self) -> float:
        return self.lo + (self.hi - self.lo) * self.s.value() / 1000.0

    def setValue(self, v: float, silent: bool = True):
        if silent:
            self.s.blockSignals(True)
        self.s.setValue(self._to_slider(float(v)))
        self.s.blockSignals(False)
        self.val.setText(self.fmt(self.value()))

    def _changed(self, _):
        v = self.value()
        self.val.setText(self.fmt(v))
        self.valueChanged.emit(v)


# ---------------------------------------------------------------------------- icons
def icon_path(name: str, s: float) -> QPainterPath:
    p = QPainterPath()
    u = s / 24.0

    def P(x, y):
        return QPointF(x * u, y * u)

    if name == "music":
        p.addEllipse(QRectF(3 * u, 15 * u, 6 * u, 5 * u))
        p.addEllipse(QRectF(13 * u, 13 * u, 6 * u, 5 * u))
        p.moveTo(P(9, 17.5)); p.lineTo(P(9, 5)); p.lineTo(P(19, 3)); p.lineTo(P(19, 15.5))
    elif name == "party":
        for a in range(4):
            ang = a * math.pi / 2
            p.moveTo(P(12, 12)); p.lineTo(P(12 + 9 * math.cos(ang), 12 + 9 * math.sin(ang)))
        for a in range(4):
            ang = a * math.pi / 2 + math.pi / 4
            p.moveTo(P(12 + 2 * math.cos(ang), 12 + 2 * math.sin(ang)))
            p.lineTo(P(12 + 5.5 * math.cos(ang), 12 + 5.5 * math.sin(ang)))
    elif name == "ambient":
        p.moveTo(P(12, 3))
        p.cubicTo(P(17, 9), P(19, 12), P(17, 17))
        p.cubicTo(P(15, 21), P(9, 21), P(7, 17))
        p.cubicTo(P(5, 13), P(8, 10), P(10, 7))
        p.cubicTo(P(10.5, 10), P(12, 11), P(12, 3))
    elif name == "studio":
        for x, y in ((6, 8), (12, 15), (18, 10)):
            p.moveTo(P(x, 4)); p.lineTo(P(x, 20))
            p.addEllipse(QRectF((x - 2) * u, (y - 2) * u, 4 * u, 4 * u))
    elif name == "wall":
        for x in (4, 7, 10, 14, 17, 20):
            p.moveTo(P(x, 4)); p.lineTo(P(x, 20))
    elif name == "network":
        p.moveTo(P(3, 9)); p.quadTo(P(12, 1), P(21, 9))
        p.moveTo(P(6, 12.5)); p.quadTo(P(12, 7), P(18, 12.5))
        p.moveTo(P(9, 16)); p.quadTo(P(12, 13), P(15, 16))
        p.addEllipse(QRectF(11 * u, 18.5 * u, 2 * u, 2 * u))
    elif name == "phone":
        p.addRoundedRect(QRectF(7 * u, 2.5 * u, 10 * u, 19 * u), 2.5 * u, 2.5 * u)
        p.moveTo(P(11, 18.5)); p.lineTo(P(13, 18.5))
    elif name == "settings":
        p.addEllipse(QRectF(8.5 * u, 8.5 * u, 7 * u, 7 * u))
        for a in range(8):
            ang = a * math.pi / 4
            p.moveTo(P(12 + 6 * math.cos(ang), 12 + 6 * math.sin(ang)))
            p.lineTo(P(12 + 9 * math.cos(ang), 12 + 9 * math.sin(ang)))
    elif name == "presets":
        p.moveTo(P(6, 3)); p.lineTo(P(18, 3)); p.lineTo(P(18, 21)); p.lineTo(P(12, 16.5)); p.lineTo(P(6, 21))
        p.closeSubpath()
    elif name == "power":
        p.moveTo(P(12, 3)); p.lineTo(P(12, 11))
        p.arcMoveTo(QRectF(4 * u, 4.5 * u, 16 * u, 16 * u), 60)
        p.arcTo(QRectF(4 * u, 4.5 * u, 16 * u, 16 * u), 60, -300)
    return p


class NavButton(QAbstractButton):
    def __init__(self, icon: str, text: str):
        super().__init__()
        self.icon_name = icon
        self.setText(text)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(78, 64)
        self._hover = False

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(8, 4, -8, -4)
        on = self.isChecked()
        if on:
            g = QLinearGradient(r.topLeft(), r.bottomRight())
            g.setColorAt(0, QColor(124, 92, 255, 70))
            g.setColorAt(1, QColor(34, 211, 238, 40))
            p.setBrush(g)
            p.setPen(QPen(QColor(124, 92, 255, 140), 1))
            p.drawRoundedRect(r, 12, 12)
        elif self._hover:
            p.setBrush(QColor(255, 255, 255, 12))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(r, 12, 12)
        col = QColor("#ffffff") if on else QColor(T.MUTED if not self._hover else T.TEXT)
        s = 22
        p.save()
        p.translate(self.width() / 2 - s / 2, 10)
        pen = QPen(col, 1.8)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(icon_path(self.icon_name, s))
        p.restore()
        f = p.font()
        f.setPointSizeF(8.2)
        f.setBold(on)
        p.setFont(f)
        p.setPen(col)
        p.drawText(QRectF(0, 38, self.width(), 18), Qt.AlignHCenter | Qt.AlignTop, self.text())


# ---------------------------------------------------------------------------- effect card
def render_thumb(frame: np.ndarray, w: int = 160, h: int = 84) -> QImage:
    """Small stylised wall image from a (12, rows, 3) frame."""
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(QColor("#06070b"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    cols, rows, _ = frame.shape
    gap = w * 0.24
    sp = (w - gap - 16) / 10.0
    xs = [8 + i * sp for i in range(6)] + [w - 8 - (5 - i) * sp for i in range(6)]
    top, bot = 8, h - 8
    v = np.clip(frame, 0, 1) ** (1 / 2.2)
    seg = max(1, rows // 28)
    p.setCompositionMode(QPainter.CompositionMode_Plus)
    for c in range(cols):
        x = xs[c]
        for r0 in range(0, rows, seg):
            col = v[c, r0:r0 + seg].mean(axis=0)
            if col.sum() < 0.02:
                continue
            y1 = bot - (r0 + seg) / rows * (bot - top)
            y0 = bot - r0 / rows * (bot - top)
            qc = QColor.fromRgbF(*col)
            glow = QColor(qc)
            glow.setAlphaF(0.22)
            p.fillRect(QRectF(x - sp * 0.45, y1, sp * 0.9, y0 - y1 + 0.5), glow)
            p.fillRect(QRectF(x - 1.2, y1, 2.4, y0 - y1 + 0.5), qc)
    p.setCompositionMode(QPainter.CompositionMode_SourceOver)
    fx = w / 2 - gap * 0.32
    p.fillRect(QRectF(fx, h * 0.62, gap * 0.64, h * 0.16), QColor(18, 19, 25))
    p.end()
    return img


class EffectCard(QAbstractButton):
    def __init__(self, eff_id: str, name: str, category: str, desc: str = ""):
        super().__init__()
        self.eff_id = eff_id
        self.name = name
        self.category = category
        self.setToolTip(f"<b>{name}</b><br>{desc}" if desc else name)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(152, 118)
        self.thumb: QImage | None = None
        self._hover = 0.0
        self.anim = QPropertyAnimation(self, b"hover", self)
        self.anim.setDuration(140)

    def get_hover(self):
        return self._hover

    def set_hover(self, v):
        self._hover = v
        self.update()

    hover = Property(float, get_hover, set_hover)

    def enterEvent(self, e):
        self.anim.stop(); self.anim.setStartValue(self._hover); self.anim.setEndValue(1.0); self.anim.start()

    def leaveEvent(self, e):
        self.anim.stop(); self.anim.setStartValue(self._hover); self.anim.setEndValue(0.0); self.anim.start()

    def set_thumb(self, img: QImage):
        self.thumb = img
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        on = self.isChecked()
        path = QPainterPath()
        path.addRoundedRect(r, 12, 12)
        p.fillPath(path, QColor(T.SURFACE if not on else "#151530"))
        tr = QRectF(r.left() + 4, r.top() + 4, r.width() - 8, 76)
        tp = QPainterPath()
        tp.addRoundedRect(tr, 9, 9)
        p.save()
        p.setClipPath(tp)
        if self.thumb is not None:
            p.drawImage(tr, self.thumb)
        else:
            p.fillRect(tr, QColor("#0a0b10"))
        p.restore()
        f = p.font()
        f.setPointSizeF(9.0)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(T.TEXT))
        p.drawText(QRectF(r.left() + 10, tr.bottom() + 6, r.width() - 26, 22), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(self.name, Qt.ElideRight, int(r.width() - 26)))
        dot = {"special": T.A3, "ambient": T.WARN}.get(self.category, T.A2)
        p.setBrush(QColor(dot))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QRectF(r.right() - 14, tr.bottom() + 14, 6, 6))
        if on:
            g = QLinearGradient(r.topLeft(), r.bottomRight())
            g.setColorAt(0, QColor(T.A1)); g.setColorAt(0.5, QColor(T.A2)); g.setColorAt(1, QColor(T.A3))
            p.setPen(QPen(QBrush(g), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 11, 11)
        else:
            c = QColor(T.BORDER)
            c2 = QColor(T.BORDER2)
            k = self._hover
            p.setPen(QPen(QColor.fromRgbF(c.redF() + (c2.redF() - c.redF()) * k + 0.08 * k,
                                          c.greenF() + (c2.greenF() - c.greenF()) * k + 0.08 * k,
                                          c.blueF() + (c2.blueF() - c.blueF()) * k + 0.15 * k), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r, 12, 12)


class FlowLayout(QLayout):
    """Wrapping layout (Qt flow layout example) for chips and cards."""

    def __init__(self, parent=None, spacing: int = 8):
        super().__init__(parent)
        self._items = []
        self._sp = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._do(QRect(0, 0, w, 0), True)

    def setGeometry(self, r):
        super().setGeometry(r)
        self._do(r, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        return s

    def _do(self, rect, test):
        x, y, line_h = rect.x(), rect.y(), 0
        for it in self._items:
            if it.widget() is not None and it.widget().isHidden():
                continue
            hint = it.sizeHint()
            nx = x + hint.width() + self._sp
            if nx - self._sp > rect.right() + 1 and line_h > 0:
                x = rect.x()
                y += line_h + self._sp
                nx = x + hint.width() + self._sp
                line_h = 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x = nx
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y()


class FlowGrid(QWidget):
    """Container whose children wrap to the available width."""

    def __init__(self, item_w: int = 172, spacing: int = 8):
        super().__init__()
        self.items: list[QWidget] = []
        self.flow = FlowLayout(self, spacing)
        sp = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        sp.setHeightForWidth(True)
        self.setSizePolicy(sp)

    def add(self, w: QWidget):
        self.items.append(w)
        self.flow.addWidget(w)

    def clear(self):
        for w in self.items:
            w.setParent(None)
            w.deleteLater()
        self.items = []

    def refilter(self):
        self.flow.invalidate()
        self.updateGeometry()

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self.flow.heightForWidth(w)


# ---------------------------------------------------------------------------- meters
class SpectrumBar(QWidget):
    """Live spectrum + beat pulse used under the simulator."""

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(54)
        self.setMaximumHeight(150)
        self.bands = np.zeros(32, np.float32)
        self.peaks = np.zeros(32, np.float32)
        self.beat = 0.0
        self.level = 0.0
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_data(self, bands, peaks, beat_pulse: float, level: float):
        self.bands = bands
        self.peaks = peaks
        self.beat = beat_pulse
        self.level = level
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        n = len(self.bands)
        w = r.width() / n
        g = QLinearGradient(0, r.bottom(), 0, r.top())
        g.setColorAt(0, QColor(T.A1))
        g.setColorAt(0.6, QColor(T.A2))
        g.setColorAt(1, QColor(T.A3))
        p.setPen(Qt.NoPen)
        for i in range(n):
            h = float(self.bands[i]) * (r.height() - 4)
            p.setBrush(g)
            p.drawRoundedRect(QRectF(r.left() + i * w + 1.5, r.bottom() - h, w - 3, h), 2, 2)
            pk = float(self.peaks[i]) * (r.height() - 4)
            p.setBrush(QColor(255, 255, 255, 170))
            p.drawRect(QRectF(r.left() + i * w + 1.5, r.bottom() - pk - 2, w - 3, 2))


class Pill(QWidget):
    """Status chip: coloured dot + text."""

    def __init__(self, text: str = "", color: str = T.MUTED):
        super().__init__()
        self.text = text
        self.color = color
        self.pulse = 0.0
        self.setFixedHeight(28)

    def set(self, text: str, color: str | None = None):
        changed = text != self.text or (color and color != self.color)
        self.text = text
        if color:
            self.color = color
        if changed:
            self.updateGeometry()
            self.update()

    def sizeHint(self):
        fm = self.fontMetrics()
        return QSize(fm.horizontalAdvance(self.text) + 34, 28)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(T.BORDER), 1))
        p.setBrush(QColor(T.SURFACE))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        c = QColor(self.color)
        if self.pulse > 0:
            gl = QRadialGradient(QPointF(14, r.center().y()), 9)
            cc = QColor(c)
            cc.setAlphaF(0.6 * self.pulse)
            gl.setColorAt(0, cc)
            gl.setColorAt(1, QColor(0, 0, 0, 0))
            p.setBrush(gl)
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(14, r.center().y()), 9, 9)
        p.setBrush(c)
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(14, r.center().y()), 4, 4)
        p.setPen(QColor(T.TEXT))
        p.drawText(r.adjusted(24, 0, -8, 0), Qt.AlignVCenter | Qt.AlignLeft, self.text)


class ColorButton(QPushButton):
    colorChanged = Signal(str)

    def __init__(self, color: str = "#ff8a3d", size: int = 34):
        super().__init__()
        self.color = color
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self.clicked.connect(self.pick)

    def setColor(self, c: str):
        self.color = c
        self.update()

    def pick(self):
        c = QColorDialog.getColor(QColor(self.color), self, "Alege culoarea")
        if c.isValid():
            self.setColor(c.name())
            self.colorChanged.emit(c.name())

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        p.setPen(QPen(QColor(255, 255, 255, 60), 2))
        p.setBrush(QColor(self.color))
        p.drawRoundedRect(r, 9, 9)


class PaletteChip(QAbstractButton):
    def __init__(self, pid: str, name: str, stops: list[str]):
        super().__init__()
        self.pid = pid
        self.name = name
        self.stops = stops
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(name)
        self.setFixedSize(92, 46)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        sw = QRectF(r.left() + 4, r.top() + 4, r.width() - 8, 14)
        g = QLinearGradient(sw.topLeft(), sw.topRight())
        n = max(1, len(self.stops) - 1)
        for i, s in enumerate(self.stops):
            g.setColorAt(i / n, QColor(s))
        p.setPen(QPen(QColor(T.A2) if self.isChecked() else QColor(T.BORDER), 1.5 if self.isChecked() else 1))
        p.setBrush(QColor(T.SURFACE2 if self.isChecked() else T.SURFACE))
        p.drawRoundedRect(r, 9, 9)
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(sw, 6, 6)
        f = p.font()
        f.setPointSizeF(8)
        p.setFont(f)
        p.setPen(QColor(T.TEXT if self.isChecked() else T.MUTED))
        p.drawText(QRectF(r.left(), sw.bottom() + 2, r.width(), r.bottom() - sw.bottom() - 2), Qt.AlignCenter,
                   p.fontMetrics().elidedText(self.name, Qt.ElideRight, int(r.width() - 6)))


class BigToggleButton(QAbstractButton):
    """Large glowing round button (LED on/off, Party start)."""

    def __init__(self, text: str, sub: str = "", size: int = 58):
        super().__init__()
        self.setText(text)
        self.sub = sub
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(size)
        self.setMinimumWidth(size)
        self.glow = 0.0
        self._t = QTimer(self)
        self._t.timeout.connect(self._tick)
        self._t.start(33)
        self._ph = 0.0

    def _tick(self):
        if self.isChecked():
            self._ph += 0.05
            self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        on = self.isChecked()
        rad = r.height() / 2
        if on:
            g = QLinearGradient(r.topLeft(), r.bottomRight())
            g.setColorAt(0, QColor(T.A1))
            g.setColorAt(1, QColor(T.A3))
            glow = QColor(255, 79, 163, int(60 + 40 * math.sin(self._ph)))
            p.setPen(QPen(glow, 4))
            p.setBrush(g)
        else:
            p.setPen(QPen(QColor(T.BORDER2), 1))
            p.setBrush(QColor(T.SURFACE2))
        p.drawRoundedRect(r, rad, rad)
        p.setPen(QColor("#ffffff") if on else QColor(T.MUTED))
        f = p.font()
        f.setBold(True)
        f.setPointSizeF(10.5)
        p.setFont(f)
        if self.sub:
            p.drawText(r.adjusted(0, 4, 0, -r.height() / 2 + 2), Qt.AlignHCenter | Qt.AlignBottom, self.text())
            f.setBold(False)
            f.setPointSizeF(8)
            p.setFont(f)
            p.drawText(r.adjusted(0, r.height() / 2, 0, -2), Qt.AlignHCenter | Qt.AlignTop, self.sub)
        else:
            p.drawText(r, Qt.AlignCenter, self.text())
