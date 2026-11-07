"""Small painted widgets for the desktop UI. Qt only; no camera or engine imports."""
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen,
)
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QSpinBox, QStyle,
    QStyleOptionButton, QVBoxLayout, QWidget,
)

# One palette for the whole window; the stylesheet in desktop.py reads the same values.
BG = "#0e1113"
SURFACE = "#161a1d"
RAISED = "#1e2428"
LINE = "#283035"
TEXT = "#e9eef0"
MUTED = "#8c99a0"
GOOD = "#4fd1a5"        # on screen / well focused
PAPER = "#6ea8fe"       # looking down at paper
AWAY = "#f2b84b"        # looking away
PHONE = "#ff6b9a"       # phone in view
IDLE = "#4a555c"        # not observed
BREAK = "#8fa8ff"

ATTENTION_COLORS = {"screen": GOOD, "paper": PAPER, "away": AWAY, "no_face": AWAY,
                    "phone": PHONE, "unavailable": IDLE}


def score_style(score):
    """(color, word) for a 0-100 focus score."""
    if score is None:
        return MUTED, "Collecting…"
    if score >= 85:
        return GOOD, "Locked in"
    if score >= 65:
        return GOOD, "Steady"
    if score >= 40:
        return AWAY, "Drifting"
    return PHONE, "Off track"


def mono_font(size, weight=QFont.Weight.Medium):
    font = QFont()
    font.setFamilies(["JetBrains Mono", "DejaVu Sans Mono", "Menlo", "Consolas", "monospace"])
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPixelSize(size)
    font.setWeight(weight)
    return font


def label(text="", name="", wrap=False):
    w = QLabel(text)
    w.setObjectName(name)
    w.setWordWrap(wrap)
    w.setTextFormat(Qt.TextFormat.PlainText)
    return w


def button(text, action=None, name="", checkable=False):
    w = QPushButton(text)
    w.setObjectName(name)
    w.setCheckable(checkable)
    w.setCursor(Qt.CursorShape.PointingHandCursor)
    if action:
        w.clicked.connect(action)
    return w


def card(margins=(22, 20, 22, 20), spacing=12):
    w = QFrame()
    w.setObjectName("card")
    layout = QVBoxLayout(w)
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    return w, layout


class ElidedLabel(QLabel):
    """A single line that keeps its full text when resized."""

    def __init__(self, text="", name=""):
        super().__init__()
        self.setObjectName(name)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setText(text)

    def setText(self, text):
        self.full_text = text
        self._elide()

    def _elide(self):
        super().setText(self.fontMetrics().elidedText(
            self.full_text, Qt.TextElideMode.ElideRight, max(0, self.contentsRect().width())))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()


class Check(QCheckBox):
    """Check box that draws its own tick, so the checked state reads clearly under any Qt style."""

    def __init__(self, text="", name=""):
        super().__init__(text)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if name:
            self.setAccessibleName(name)

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.isChecked():
            return
        option = QStyleOptionButton()
        self.initStyleOption(option)
        box = QRectF(self.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, option, self))
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor("#07140e" if self.isEnabled() else "#5f8c7c"), 2.0, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        w, h = box.width(), box.height()
        p.drawPolyline([QPointF(box.left() + w * .28, box.top() + h * .52),
                        QPointF(box.left() + w * .44, box.top() + h * .68),
                        QPointF(box.left() + w * .73, box.top() + h * .33)])


class Dropdown(QComboBox):
    """Combo box with its own chevron, so it looks the same under any Qt style."""

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(MUTED), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        cx, cy = self.width() - 18, self.height() / 2
        p.drawPolyline([QPointF(cx - 4, cy - 2), QPointF(cx, cy + 2), QPointF(cx + 4, cy - 2)])


class Stepper(QWidget):
    """A number field with large minus/plus buttons that look the same under any Qt style."""

    def __init__(self, minimum, maximum, value, suffix=" min", name=""):
        super().__init__()
        self.spin = QSpinBox()
        self.spin.setRange(minimum, maximum)
        self.spin.setValue(value)
        self.spin.setSuffix(suffix)
        self.spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.spin.setAccessibleName(name)
        self.spin.setMinimumWidth(56)
        self.less = button("\u2212", lambda: self.spin.stepDown(), "step")
        self.more = button("+", lambda: self.spin.stepUp(), "step")
        self.less.setAccessibleName(f"Decrease {name.lower()}")
        self.more.setAccessibleName(f"Increase {name.lower()}")
        for w in (self.less, self.more):
            w.setAutoRepeat(True)
            w.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            w.setFixedSize(40, 40)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(self.less)
        row.addWidget(self.spin, 1)
        row.addWidget(self.more)
        self.setFocusProxy(self.spin)

    def value(self):
        return self.spin.value()

    def setValue(self, value):
        self.spin.setValue(value)


class PreviewView(QWidget):
    """Camera picture with a live state chip. Frames arrive as QPixmaps from memory."""

    hide_requested = Signal()

    def __init__(self):
        super().__init__()
        self.pixmap = None
        self.message = ""
        self.chip = ""
        self.color = IDLE
        self.setMinimumSize(320, 240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.toggle = QPushButton("Hide", self)
        self.toggle.setObjectName("overlay")
        self.toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle.setToolTip("Hide or show the camera picture. Tracking continues either way.")
        self.toggle.clicked.connect(self.hide_requested)
        self.toggle.hide()

    def set_toggle(self, text, visible):
        self.toggle.setText(text)
        self.toggle.setVisible(visible)
        self.toggle.adjustSize()
        self.place_toggle()

    def place_toggle(self):
        self.toggle.move(self.width() - self.toggle.width() - 16, 16)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.place_toggle()

    def set_frame(self, pixmap):
        self.pixmap = pixmap
        self.update()

    def set_state(self, message, chip, color):
        if (message, chip, color) != (self.message, self.chip, self.color):
            self.message, self.chip, self.color = message, chip, color
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        outer = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        shape = QPainterPath()
        shape.addRoundedRect(outer, 18, 18)
        p.fillPath(shape, QColor(SURFACE))
        if self.pixmap is not None and not self.pixmap.isNull():
            p.save()
            p.setClipPath(shape)
            scale = max(outer.width() / self.pixmap.width(), outer.height() / self.pixmap.height())
            w, h = self.pixmap.width() * scale, self.pixmap.height() * scale
            p.drawPixmap(QRectF(outer.center().x() - w / 2, outer.center().y() - h / 2, w, h),
                         self.pixmap, QRectF(self.pixmap.rect()))
            fade = QLinearGradient(0, outer.bottom() - 110, 0, outer.bottom())
            fade.setColorAt(0, QColor(0, 0, 0, 0))
            fade.setColorAt(1, QColor(0, 0, 0, 150))
            p.fillRect(outer, QBrush(fade))
            p.restore()
        elif self.message:
            p.setPen(QColor(MUTED))
            font = p.font()
            font.setPixelSize(14)
            p.setFont(font)
            p.drawText(outer.adjusted(30, 0, -30, 0), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                       self.message)
        p.setPen(QPen(QColor(self.color if self.chip else LINE), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(outer, 18, 18)
        if self.chip:
            font = p.font()
            font.setPixelSize(14)
            font.setWeight(QFont.Weight.DemiBold)
            p.setFont(font)
            width = p.fontMetrics().horizontalAdvance(self.chip) + 44
            pill = QRectF(outer.left() + 16, outer.bottom() - 48, width, 32)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(14, 17, 19, 215))
            p.drawRoundedRect(pill, 16, 16)
            p.setBrush(QColor(self.color))
            p.drawEllipse(QPointF(pill.left() + 16, pill.center().y()), 5, 5)
            p.setPen(QColor(TEXT))
            p.drawText(pill.adjusted(30, 0, -12, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.chip)


class ProgressRing(QWidget):
    """Small circular progress border for the return-to-task check-in."""

    def __init__(self):
        super().__init__()
        self.fraction = None
        self.setFixedSize(64, 64)
        self.setAccessibleName("Return-to-task progress")
        self.hide()

    def set_progress(self, fraction):
        self.fraction = None if fraction is None else max(0.0, min(1.0, fraction))
        self.setVisible(self.fraction is not None)
        self.setAccessibleDescription("" if self.fraction is None else
                                      f"Locking back in: {round(self.fraction * 100)} percent")
        self.update()

    def paintEvent(self, event):
        if self.fraction is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        border = QRectF(self.rect()).adjusted(4, 4, -4, -4)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(LINE), 4))
        p.drawEllipse(border)
        p.setPen(QPen(QColor(GOOD), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(border, 90 * 16, int(-360 * 16 * self.fraction))
        p.setPen(QColor(TEXT))
        p.setFont(mono_font(13))
        p.drawText(border, Qt.AlignmentFlag.AlignCenter, f"{round(self.fraction * 100)}%")


class Ring(QWidget):
    """Countdown ring with the time in the middle."""

    def __init__(self):
        super().__init__()
        self.fraction = 0.0
        self.time_text = "25:00"
        self.caption = "FOCUS"
        self.color = GOOD
        self.dim = False
        self.setMinimumSize(210, 210)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_state(self, fraction, time_text, caption, color, dim=False):
        self.fraction, self.time_text, self.caption, self.color, self.dim = fraction, time_text, caption, color, dim
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width(), self.height()) - 16
        box = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        thickness = max(8, side * 0.055)
        arc = box.adjusted(thickness / 2, thickness / 2, -thickness / 2, -thickness / 2)
        p.setPen(QPen(QColor(RAISED), thickness, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(arc, 0, 360 * 16)
        color = QColor(self.color)
        if self.dim:
            color.setAlphaF(0.45)
        if self.fraction > 0:
            p.setPen(QPen(color, thickness, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(arc, 90 * 16, int(-360 * 16 * min(1.0, self.fraction)))
        p.setPen(QColor(TEXT))
        p.setFont(mono_font(int(side * 0.23)))
        p.drawText(box.adjusted(0, -side * 0.03, 0, 0), Qt.AlignmentFlag.AlignCenter, self.time_text)
        p.setPen(QColor(MUTED))
        font = p.font()
        font.setFamilies(["Inter", "DejaVu Sans", "sans-serif"])
        font.setPixelSize(max(11, int(side * 0.055)))
        font.setWeight(QFont.Weight.DemiBold)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.8)
        p.setFont(font)
        p.drawText(box.adjusted(0, side * 0.30, 0, 0), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                   self.caption)


class Trend(QWidget):
    """A quiet line graph of the focus score over time. None values leave gaps."""

    def __init__(self, show_axis=False):
        super().__init__()
        self.values = []
        self.show_axis = show_axis
        self.setMinimumHeight(64)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_values(self, values):
        if list(values) != self.values:
            self.values = list(values)
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = QRectF(self.rect()).adjusted(2, 6, -2, -6)
        for level in (0, 50, 100):
            y = area.bottom() - area.height() * level / 100
            p.setPen(QPen(QColor(LINE), 1, Qt.PenStyle.DashLine if level == 50 else Qt.PenStyle.SolidLine))
            p.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
        points = [(i, v) for i, v in enumerate(self.values) if v is not None]
        if not points:
            p.setPen(QColor(MUTED))
            p.drawText(area, Qt.AlignmentFlag.AlignCenter, "The trend appears after a few seconds of tracking")
            return
        span = max(1, len(self.values) - 1)

        def at(i, v):
            return QPointF(area.left() + area.width() * i / span, area.bottom() - area.height() * v / 100)

        # Contiguous runs are drawn as lines with a soft fill below.
        runs, run = [], []
        for i, v in enumerate(self.values):
            if v is None:
                if run:
                    runs.append(run)
                run = []
            else:
                run.append(at(i, v))
        if run:
            runs.append(run)
        for run in runs:
            path = QPainterPath(run[0])
            for point in run[1:]:
                path.lineTo(point)
            fill = QPainterPath(path)
            fill.lineTo(run[-1].x(), area.bottom())
            fill.lineTo(run[0].x(), area.bottom())
            fill.closeSubpath()
            gradient = QLinearGradient(0, area.top(), 0, area.bottom())
            top = QColor(GOOD)
            top.setAlpha(70)
            bottom = QColor(GOOD)
            bottom.setAlpha(0)
            gradient.setColorAt(0, top)
            gradient.setColorAt(1, bottom)
            p.fillPath(fill, QBrush(gradient))
            p.setPen(QPen(QColor(GOOD), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.setBrush(Qt.BrushStyle.NoBrush)
            if len(run) == 1:
                p.setBrush(QColor(GOOD))
                p.drawEllipse(run[0], 2.5, 2.5)
            else:
                p.drawPath(path)
        last = at(*points[-1])
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(BG))
        p.drawEllipse(last, 5, 5)
        p.setBrush(QColor(GOOD))
        p.drawEllipse(last, 3.5, 3.5)


class SplitBar(QWidget):
    """One horizontal bar divided into colored shares."""

    def __init__(self):
        super().__init__()
        self.parts = []
        self.setFixedHeight(12)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_parts(self, parts):
        """parts: [(seconds, "#color"), ...]"""
        if list(parts) != self.parts:
            self.parts = list(parts)
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        shape = QPainterPath()
        shape.addRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        p.fillPath(shape, QColor(RAISED))
        total = sum(seconds for seconds, _ in self.parts)
        if total <= 0:
            return
        p.setClipPath(shape)
        x = rect.left()
        visible = [(s, c) for s, c in self.parts if s > 0]
        for index, (seconds, color) in enumerate(visible):
            width = rect.width() * seconds / total
            gap = 2 if index < len(visible) - 1 else 0
            p.fillRect(QRectF(x, rect.top(), max(0.0, width - gap), rect.height()), QColor(color))
            x += width
