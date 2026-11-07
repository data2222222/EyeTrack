"""A small always-on-top pill with the clock and the session state. Qt only.

It never touches the camera, the clock or the session: the window feeds it a session view
(or None) and it paints text. Drag it anywhere; on release it snaps to the nearest screen
corner. The x button hides it for now; Settings can switch it off for good.
"""
from PySide6.QtCore import QLocale, QRectF, Qt, QTime, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLayout, QMenu, QToolButton, QWidget

import study
from widgets import AWAY, BREAK, GOOD, LINE, MUTED, TEXT, mono_font

CORNERS = (("Top right", "top_right"), ("Top left", "top_left"),
           ("Bottom right", "bottom_right"), ("Bottom left", "bottom_left"))
DEFAULT_CORNER = "top_right"
MARGIN = 16
DRAG_THRESHOLD = 4
_FILL = QColor(14, 17, 19, 226)

_STYLE = f"""
QLabel {{ background: transparent; color: {TEXT}; }}
QToolButton {{ background: transparent; border: 0; border-radius: 9px; color: {MUTED}; font-size: 14px; padding: 0; }}
QToolButton:hover {{ background: #283036; color: {TEXT}; }}
QToolButton:focus {{ border: 1px solid {GOOD}; color: {TEXT}; }}
QMenu {{ background: #1e2428; color: {TEXT}; border: 1px solid {LINE}; border-radius: 10px; padding: 5px; }}
QMenu::item {{ padding: 7px 18px; border-radius: 7px; }}
QMenu::item:selected {{ background: #2b343a; }}
"""


def summarize(view):
    """(text, color) for the session half of the overlay; pure so it can be tested without Qt."""
    if not view:
        return "No session", MUTED
    left = study.format_duration(view["phase_left"])
    phase = view["phase"]
    if phase == "work":
        score = view.get("score")
        return f"Focus {left}" + ("" if score is None else f" · {score}"), GOOD
    if phase == "paused":
        return f"Paused {left}", AWAY
    if phase == "break":
        return f"Break {left}", BREAK
    return "Block done", GOOD


def corner_for(center, area):
    """Nearest corner name of a rectangle for a point."""
    vertical = "top" if center.y() < area.center().y() else "bottom"
    horizontal = "left" if center.x() < area.center().x() else "right"
    return f"{vertical}_{horizontal}"


class Overlay(QWidget):
    hide_requested = Signal()
    open_requested = Signal()
    settings_requested = Signal()
    corner_changed = Signal(str)

    def __init__(self, corner=DEFAULT_CORNER):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow, True)
        self.setWindowTitle("EyeTrack overlay")
        self.setAccessibleName("EyeTrack overlay")
        self.setStyleSheet(_STYLE)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.corner = corner if corner in dict(CORNERS).values() else DEFAULT_CORNER
        self.press_at = None
        self.dragging = False

        row = QHBoxLayout(self)
        row.setContentsMargins(14, 7, 7, 7)
        row.setSpacing(10)
        row.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)
        self.clock = QLabel()
        self.clock.setFont(mono_font(15, QFont.Weight.DemiBold))
        self.dot = QLabel("●")
        self.dot.setFont(mono_font(9))
        self.status = QLabel()
        self.status.setFont(mono_font(12))
        self.close_button = QToolButton()
        self.close_button.setText("×")
        self.close_button.setFixedSize(20, 20)
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.setToolTip("Hide the overlay. Bring it back from the ⋯ menu, or turn it off in Settings.")
        self.close_button.setAccessibleName("Hide overlay")
        self.close_button.clicked.connect(self.hide_requested)
        keep = self.close_button.sizePolicy()
        keep.setRetainSizeWhenHidden(True)
        self.close_button.setSizePolicy(keep)
        self.close_button.hide()
        for widget in (self.clock, self.dot, self.status, self.close_button):
            row.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)
        self.update_state(None)

    # ------------------------------------------------------------------ content
    def update_state(self, view, now=None):
        """Show the clock and the session state; cheap to call every refresh."""
        clock_text = QLocale.system().toString(now or QTime.currentTime(), QLocale.FormatType.ShortFormat)
        text, color = summarize(view)
        if clock_text != self.clock.text():
            self.clock.setText(clock_text)
        if text != self.status.text():
            self.status.setText(text)
        self.status.setStyleSheet(f"color: {TEXT if view else MUTED};")
        self.dot.setStyleSheet(f"color: {color};")
        self.setAccessibleDescription(f"{clock_text}. {text}")

    # ------------------------------------------------------------------ placement
    def available_area(self):
        screen = self.screen() or QGuiApplication.primaryScreen()
        return screen.availableGeometry() if screen else None

    def place(self):
        area = self.available_area()
        if area is None or self.dragging:
            return
        x = area.left() + MARGIN if self.corner.endswith("left") else area.right() + 1 - self.width() - MARGIN
        y = area.top() + MARGIN if self.corner.startswith("top") else area.bottom() + 1 - self.height() - MARGIN
        self.move(x, y)

    def set_corner(self, corner):
        if corner in dict(CORNERS).values():
            self.corner = corner
            self.place()

    def showEvent(self, event):
        super().showEvent(event)
        self.place()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.place()

    # ------------------------------------------------------------------ painting
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(LINE), 1))
        p.setBrush(_FILL)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 14, 14)

    def enterEvent(self, event):
        self.close_button.show()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self.close_button.hasFocus():
            self.close_button.hide()
        super().leaveEvent(event)

    # ------------------------------------------------------------------ mouse
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.press_at = event.globalPosition().toPoint() - self.pos()
            self.dragging = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.press_at is None or not event.buttons() & Qt.MouseButton.LeftButton:
            return
        target = event.globalPosition().toPoint() - self.press_at
        if not self.dragging and (target - self.pos()).manhattanLength() < DRAG_THRESHOLD:
            return
        self.dragging = True
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        self.move(target)

    def mouseReleaseEvent(self, event):
        dragged, self.dragging, self.press_at = self.dragging, False, None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        if dragged:
            self.snap()
        super().mouseReleaseEvent(event)

    def snap(self):
        """Settle into the nearest corner of the screen the overlay was dropped on."""
        center = self.frameGeometry().center()
        screen = QGuiApplication.screenAt(center) or self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return
        corner = corner_for(center, screen.availableGeometry())
        changed = corner != self.corner
        self.corner = corner
        self.place()
        if changed:
            self.corner_changed.emit(corner)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.open_requested.emit()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.addAction("Hide overlay", self.hide_requested.emit)
        menu.addAction("Open EyeTrack", self.open_requested.emit)
        menu.addAction("Overlay settings…", self.settings_requested.emit)
        menu.exec(event.globalPos())
