"""Guided screen targets for the Qt desktop; camera sampling stays in tracking.py."""

import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QDialog


class CalibrationDialog(QDialog):
    def __init__(self, calibration, camera_status, parent=None):
        super().__init__(parent)
        self.calibration = calibration
        self.camera_status = camera_status
        self.completed_at = None
        self.setWindowTitle("Calibrate screen")
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()

    def refresh(self):
        state = self.calibration.view()
        if self.camera_status() in ("off", "stopped"):
            self.reject()
            return
        if not state["active"]:
            if self.completed_at is None:
                self.completed_at = time.monotonic()
            duration = 3.5 if state["quality"] == "limited" else .8
            if time.monotonic() - self.completed_at >= duration:
                self.accept()
                return
        self.update()

    def done(self, result):
        self.timer.stop()
        if self.calibration.view()["active"]:
            self.calibration.cancel()
        super().done(result)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#15171a"))
        state = self.calibration.view()
        width, height = self.width(), self.height()

        def text(value, y, color="#f2f2f2", size=22):
            painter.setPen(QColor(color))
            painter.setFont(QFont("DejaVu Sans", size))
            painter.drawText(QRectF(width * .1, height * y, width * .8, height * .18),
                             Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, value)

        if not state["active"]:
            text(state["message"], .4, "#ffcc80" if state["quality"] == "limited" else "#80dca2")
            return
        _, x, y = state["target"]
        cx, cy = width * x, height * y
        painter.setPen(QPen(QColor("#5b8def"), 3))
        painter.drawEllipse(QPointF(cx, cy), 22, 22)
        painter.setPen(QPen(QColor("#80dca2"), 4))
        painter.drawArc(QRectF(cx - 29, cy - 29, 58, 58), 90 * 16,
                        int(-359 * 16 * state["progress"]))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("white"))
        painter.drawEllipse(QPointF(cx, cy), 5, 5)
        text("Follow the dot with your eyes\nKeep your usual sitting position", .22)
        status = self.camera_status()
        message = state["message"] if status == "ok" else status
        text(f"Point {state['stage'] + 1} of 5 · {message}\nEsc to cancel", .66, "#a5b1ab", 15)


_dialog = None


def show_calibration(calibration, camera_status, parent=None):
    """Keep one nonblocking dialog; the desktop's timers and camera keep running."""
    global _dialog
    if _dialog is not None:
        _dialog.raise_()
        _dialog.activateWindow()
        return _dialog
    _dialog = CalibrationDialog(calibration, camera_status, parent)

    def finished(_result):
        global _dialog
        dialog, _dialog = _dialog, None
        dialog.deleteLater()

    _dialog.finished.connect(finished)
    _dialog.showFullScreen()
    return _dialog
