"""The three-screen desktop experience. Camera algorithms live in engine/tracking."""
import base64
import sys
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QDialog, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar,
    QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)

import study


STYLE = """
QWidget { color: #202c32; font-family: 'Inter', 'DejaVu Sans', sans-serif; font-size: 13px; }
QMainWindow, QDialog, QScrollArea, QWidget#page { background: #f5f7f6; }
QLabel { background: transparent; }
QLabel#brand { font-size: 21px; font-weight: 700; letter-spacing: -0.6px; }
QLabel#title { font-size: 32px; font-weight: 650; letter-spacing: -0.8px; }
QLabel#subtitle, QLabel#muted { color: #73817e; }
QLabel#eyebrow { color: #548175; font-size: 10px; font-weight: 700; letter-spacing: 1.8px; }
QLabel#section { font-size: 15px; font-weight: 650; }
QLabel#timer { font-size: 88px; font-weight: 500; letter-spacing: -4px; }
QLabel#stat { font-size: 28px; font-weight: 600; }
QLabel#badge { background: #e7eeeb; border-radius: 12px; padding: 7px 13px; color: #526b62; font-size: 11px; }
QLabel#step { color: #98a29f; padding: 7px 0; }
QLabel#step[current='true'] { color: #296953; font-weight: 700; }
QFrame#card { background: white; border: 1px solid #e1e8e4; border-radius: 16px; }
QFrame#checkin { background: #fff8e9; border: 1px solid #efddba; border-radius: 14px; }
QPushButton { background: white; border: 1px solid #dce4df; border-radius: 9px; padding: 10px 17px; font-weight: 550; }
QPushButton:hover { background: #eef4f0; border-color: #a9c0b3; }
QPushButton:pressed { background: #e1ebe5; }
QPushButton:focus, QLineEdit:focus { border: 2px solid #4c9875; }
QPushButton:disabled { color: #a4aeaa; border-color: #e6ebe8; background: #f4f6f4; }
QPushButton#primary { background: #266b50; color: white; border: 1px solid #266b50; padding: 12px 22px; }
QPushButton#primary:hover { background: #19563f; }
QPushButton#quiet { color: #6d7c75; background: transparent; border: 0; padding: 7px 9px; }
QPushButton#choice { text-align: left; padding: 15px 17px; border-radius: 11px; }
QPushButton#choice:checked, QPushButton#pill:checked { background: #edf5ef; border: 2px solid #4d8b69; color: #24563e; }
QPushButton#pill { padding: 10px 16px; }
QLineEdit { background: #fafcfb; border: 1px solid #dce4df; border-radius: 10px; padding: 13px 15px; selection-background-color: #c8dfcf; }
QCheckBox { spacing: 10px; }
QCheckBox::indicator { width: 19px; height: 19px; border: 1px solid #bdcdc4; border-radius: 5px; background: white; }
QCheckBox::indicator:checked { background: #367d59; border: 1px solid #367d59; image: none; }
QProgressBar { border: 0; border-radius: 3px; background: #eaf0ec; height: 5px; }
QProgressBar::chunk { background: #65a07b; border-radius: 3px; }
QScrollArea { border: 0; }
QScrollBar:vertical { background: transparent; width: 8px; }
QScrollBar::handle:vertical { background: #cad5ce; border-radius: 4px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


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


def card():
    w = QFrame()
    w.setObjectName("card")
    layout = QVBoxLayout(w)
    layout.setContentsMargins(23, 21, 23, 21)
    layout.setSpacing(13)
    return w, layout


class FocusWindow(QMainWindow):
    def __init__(self, engine, start_timer=True):
        super().__init__()
        self.engine = engine
        self.controller = engine.camera_controller
        self.report = None
        self.checkin_visible = False
        self.last_tick = time.monotonic()
        self.setWindowTitle("EyeTrack")
        self.resize(970, 840)
        self.setMinimumSize(760, 650)
        self.setStyleSheet(STYLE)
        self.engine.show_preview = False
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(35, 21, 35, 17)
        outer.setSpacing(20)
        header = QHBoxLayout()
        header.addWidget(label("●  eyetrack", "brand"))
        header.addStretch()
        self.connection = label("Chrome not connected", "badge")
        header.addWidget(self.connection)
        header.addWidget(button("Diagnostics", self.diagnostics, "quiet"))
        outer.addLayout(header)
        nav = QHBoxLayout()
        self.steps = []
        for text in ("01  Set up", "02  Work", "03  Review"):
            step = label(text, "step")
            self.steps.append(step)
            nav.addWidget(step)
        nav.addStretch()
        outer.addLayout(nav)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack, 1)
        self.setup_page = self.page()
        self.session_page = self.page()
        self.summary_page = self.page()
        self.build_setup()
        self.build_session()
        self.build_summary()
        footer = QHBoxLayout()
        footer.addWidget(label("Camera frames stay on this computer.", "muted"))
        footer.addStretch()
        footer.addWidget(button("Connect Chrome", self.connection_help, "quiet"))
        outer.addLayout(footer)
        self.navigate(0)
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.refresh)
        if start_timer:
            self.timer.start()

    def page(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner.setObjectName("page")
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(0, 0, 8, 10)
        layout.setSpacing(17)
        scroll.setWidget(inner)
        self.stack.addWidget(scroll)
        return layout

    def navigate(self, index):
        self.stack.setCurrentIndex(index)
        for i, step in enumerate(self.steps):
            step.setProperty("current", i == index)
            step.style().unpolish(step)
            step.style().polish(step)

    def build_setup(self):
        layout = self.setup_page
        layout.addWidget(label("MAKE SPACE FOR ONE THING", "eyebrow"))
        layout.addWidget(label("What are you working on?", "title"))
        layout.addWidget(label("Choose your setup. The rest can wait.", "subtitle"))
        mode_card, mode_layout = card()
        mode_layout.addWidget(label("Where will you work?", "section"))
        choices = QHBoxLayout()
        self.mode_group = QButtonGroup(self)
        for index, (key, text) in enumerate(study.MODES.items()):
            w = button(text.replace("&", "&&"), name="choice", checkable=True)
            w.setMinimumHeight(65)
            w.setProperty("mode", key)
            self.mode_group.addButton(w, index)
            choices.addWidget(w)
            if key == "pc":
                w.setChecked(True)
        mode_layout.addLayout(choices)
        layout.addWidget(mode_card)
        detail_card, details = card()
        details.addWidget(label("Your session", "section"))
        details.addWidget(label("Session goal · optional", "muted"))
        self.goal_input = QLineEdit()
        self.goal_input.setPlaceholderText("e.g. Finish the first draft of my assignment")
        self.goal_input.setMaxLength(140)
        self.goal_input.setAccessibleName("Session goal, optional")
        details.addWidget(self.goal_input)
        details.addSpacing(3)
        details.addWidget(label("How long?", "muted"))
        durations = QHBoxLayout()
        self.duration_group = QButtonGroup(self)
        for minutes in (15, 25, 45):
            w = button(f"{minutes} minutes", name="pill", checkable=True)
            self.duration_group.addButton(w, minutes)
            w.setChecked(minutes == 25)
            durations.addWidget(w)
        durations.addStretch()
        details.addLayout(durations)
        details.addSpacing(6)
        self.camera_toggle = QCheckBox("Use camera during this session")
        self.camera_toggle.setChecked(True)
        details.addWidget(self.camera_toggle)
        details.addWidget(label("The preview stays hidden until you choose to open it.", "muted"))
        layout.addWidget(detail_card)
        self.setup_error = label("", "muted", True)
        self.setup_error.hide()
        layout.addWidget(self.setup_error)
        actions = QHBoxLayout()
        actions.addWidget(label("Pause whenever you need. Breaks are 5 minutes.", "muted"))
        actions.addStretch()
        self.start_button = button("Start session  →", self.start_session, "primary")
        actions.addWidget(self.start_button)
        layout.addLayout(actions)
        layout.addStretch()

    def build_session(self):
        layout = self.session_page
        self.session_goal = label("Your focus session", "title", True)
        layout.addWidget(self.session_goal)
        self.session_mode = label("", "subtitle")
        layout.addWidget(self.session_mode)
        clock_card, clock_layout = card()
        self.phase_label = label("WORKING", "eyebrow")
        self.phase_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        clock_layout.addWidget(self.phase_label)
        self.timer_label = label("25:00", "timer")
        self.timer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        clock_layout.addWidget(self.timer_label)
        self.clock_note = label("A little time for what matters.", "muted")
        self.clock_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        clock_layout.addWidget(self.clock_note)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        clock_layout.addWidget(self.progress)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 9, 0, 0)
        actions.addStretch()
        self.pause_button = button("Pause", self.toggle_pause, "primary")
        self.break_button = button("Take a break", self.take_break)
        self.end_button = button("End session", self.end_session)
        for w in (self.pause_button, self.break_button, self.end_button):
            actions.addWidget(w)
        actions.addStretch()
        clock_layout.addLayout(actions)
        layout.addWidget(clock_card)
        status_row = QHBoxLayout()
        camera_card, camera_layout = card()
        camera_layout.addWidget(label("CAMERA", "eyebrow"))
        self.camera_status = label("Off", "section")
        self.camera_note = label("", "muted", True)
        camera_layout.addWidget(self.camera_status)
        camera_layout.addWidget(self.camera_note)
        self.preview_toggle = QCheckBox("Show camera preview")
        self.preview_toggle.toggled.connect(self.toggle_preview)
        camera_layout.addWidget(self.preview_toggle)
        self.calibrate_button = button("Calibrate screen", self.calibrate_camera)
        camera_layout.addWidget(self.calibrate_button)
        status_row.addWidget(camera_card, 1)
        browser_card, browser_layout = card()
        browser_layout.addWidget(label("BROWSER", "eyebrow"))
        self.browser_status = label("Not connected", "section", True)
        self.browser_note = label("Connect the Chrome extension to observe your work sites.", "muted", True)
        browser_layout.addWidget(self.browser_status)
        browser_layout.addWidget(self.browser_note)
        browser_layout.addStretch()
        status_row.addWidget(browser_card, 1)
        layout.addLayout(status_row)
        self.preview_label = label("", "muted")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setFixedHeight(230)
        self.preview_label.hide()
        layout.addWidget(self.preview_label)
        self.checkin = QFrame()
        self.checkin.setObjectName("checkin")
        check_layout = QVBoxLayout(self.checkin)
        check_layout.setContentsMargins(20, 16, 20, 16)
        self.checkin_title = label("A quick check-in", "section")
        self.checkin_message = label("", "", True)
        check_layout.addWidget(self.checkin_title)
        check_layout.addWidget(self.checkin_message)
        check_actions = QHBoxLayout()
        check_actions.addWidget(button("Keep working", self.dismiss_checkin))
        check_actions.addWidget(button("Take a break", self.take_break))
        check_actions.addStretch()
        check_layout.addLayout(check_actions)
        layout.addWidget(self.checkin)
        self.checkin.hide()
        self.session_error = label("", "muted", True)
        layout.addWidget(self.session_error)
        layout.addStretch()

    def build_summary(self):
        layout = self.summary_page
        layout.addWidget(label("TIME WELL ACCOUNTED FOR", "eyebrow"))
        self.summary_title = label("Session ended", "title")
        self.summary_goal = label("", "subtitle", True)
        layout.addWidget(self.summary_title)
        layout.addWidget(self.summary_goal)
        grid = QGridLayout()
        self.summary_stats = {}
        for i, name in enumerate(("Active time", "Break time", "Check-ins", "Paused time")):
            w, box = card()
            value = label("—", "stat")
            box.addWidget(value)
            box.addWidget(label(name, "muted"))
            grid.addWidget(w, i // 2, i % 2)
            self.summary_stats[name] = value
        layout.addLayout(grid)
        self.summary_details = label("", "muted", True)
        layout.addWidget(self.summary_details)
        observations, observations_layout = card()
        observations_layout.addWidget(label("What was observed", "section"))
        self.observation_grid = QGridLayout()
        self.observation_values = {}
        names = (("work", "Sites categorized as work"), ("unlisted", "Unlisted sites"),
                 ("distraction", "Selected distracting sites"), ("outside", "Outside Chrome"),
                 ("unavailable", "Browser unavailable"))
        for i, (key, text) in enumerate(names):
            self.observation_grid.addWidget(label(text, "muted"), i, 0)
            value = label("00:00")
            value.setAlignment(Qt.AlignmentFlag.AlignRight)
            self.observation_values[key] = value
            self.observation_grid.addWidget(value, i, 1)
        observations_layout.addLayout(self.observation_grid)
        self.camera_summary = label("", "muted", True)
        observations_layout.addWidget(self.camera_summary)
        observations_layout.addWidget(label("Camera and website observations describe the same time; they are not added together.", "muted", True))
        layout.addWidget(observations)
        result_card, result_layout = card()
        result_layout.addWidget(label("How did your goal go? · optional", "section"))
        results = QHBoxLayout()
        self.result_group = QButtonGroup(self)
        for i, (key, text) in enumerate((("finished", "Finished"), ("partly", "Partly finished"), ("not_finished", "Not finished"))):
            w = button(text, name="pill", checkable=True)
            w.clicked.connect(lambda checked=False, value=key: self.save_result(value))
            self.result_group.addButton(w, i)
            results.addWidget(w)
        result_layout.addLayout(results)
        self.result_note = label("", "muted")
        result_layout.addWidget(self.result_note)
        layout.addWidget(result_card)
        restart = QHBoxLayout()
        restart.addStretch()
        restart.addWidget(button("Start another session  →", self.restart, "primary"))
        layout.addLayout(restart)

    def start_session(self):
        mode = self.mode_group.checkedButton().property("mode")
        ok, message = study.start_session(goal=self.goal_input.text(), work_min=self.duration_group.checkedId(),
                                         mode=mode, camera_enabled=self.camera_toggle.isChecked())
        if not ok:
            self.setup_error.setText(message)
            self.setup_error.show()
            return
        self.setup_error.hide()
        self.engine.events.clear()
        self.session_error.clear()
        self.navigate(1)
        self.refresh()

    def sync_camera(self, view):
        if view and view["phase"] == "work" and view["camera_enabled"]:
            self.controller.start()
        elif self.controller.enabled:
            self.controller.stop()

    def toggle_pause(self):
        view = study.session_view()
        if not view:
            return
        if view["phase"] == "complete":
            self.end_session(confirm=False)
        elif view["phase"] == "work":
            study.pause_session()
        else:
            study.resume_work()
        self.dismiss_checkin()
        self.refresh()

    def take_break(self):
        study.start_break()
        self.dismiss_checkin()
        self.refresh()

    def end_session(self, checked=False, confirm=True):
        view = study.session_view()
        if not view:
            return True
        if confirm and view["phase"] != "complete":
            answer = QMessageBox.question(self, "End this session?", "Your time will be saved in a session summary.",
                                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                          QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return False
        try:
            report = study.stop_session()
        except OSError:
            self.session_error.setText("Couldn't save the summary. Your session is still open; free some space and try again.")
            return False
        self.controller.stop()
        self.engine.events.clear()
        self.dismiss_checkin()
        self.report = report
        self.show_report(report)
        return True

    def show_report(self, report):
        self.summary_title.setText("Block complete" if report["completed"] else "Session ended")
        self.summary_goal.setText(report["goal"] or "You made time for a focus session.")
        for name, value in (("Active time", study.format_duration(report["active_seconds"])),
                            ("Break time", study.format_duration(report["break_seconds"])),
                            ("Check-ins", str(report["nudges"])),
                            ("Paused time", study.format_duration(report["paused_seconds"]))):
            self.summary_stats[name].setText(value)
        self.summary_details.setText(f"{study.MODES[report['mode']]} · Planned {report['planned_seconds'] // 60} minutes · "
                                     f"{report['break_count']} {'break' if report['break_count'] == 1 else 'breaks'}")
        for key, value in self.observation_values.items():
            value.setText(study.format_duration(report["website"][key]))
        c = report["camera"]
        self.camera_summary.setText(
            f"Camera: face present {study.format_duration(c['present'])} · no face {study.format_duration(c['no_face'])} · "
            f"unavailable {study.format_duration(c['unavailable'])}" if report["camera_enabled"] else "Camera was off for this session.")
        self.result_group.setExclusive(False)
        for w in self.result_group.buttons():
            w.setChecked(False)
        self.result_group.setExclusive(True)
        self.result_note.clear()
        self.navigate(2)

    def save_result(self, result):
        try:
            study.set_goal_result(result)
            self.result_note.setText("Saved on this computer.")
        except OSError:
            self.result_note.setText("Couldn't save your answer. Please try again.")

    def restart(self):
        self.goal_input.clear()
        self.navigate(0)

    def toggle_preview(self, enabled):
        self.engine.show_preview = enabled
        self.preview_label.setVisible(enabled)
        if not enabled:
            self.preview_label.clear()

    def calibrate_camera(self):
        from camera_calibration import show_calibration
        self.engine.reset_calibration(guided=True)
        show_calibration(self.engine.calib, lambda: self.engine.camera["status"], self)

    def dismiss_checkin(self):
        self.checkin.hide()
        self.checkin_visible = False

    def show_checkin(self, message, preview=False):
        if self.checkin_visible:
            return
        self.checkin_visible = True
        self.checkin_title.setText("Preview check-in" if preview else "A quick check-in")
        self.checkin_message.setText(message)
        self.checkin.show()
        if not preview:
            study.record_event("nudge")
            QApplication.alert(self)

    def refresh(self):
        now = time.monotonic()
        dt, self.last_tick = max(0, now - self.last_tick), now
        if self.controller.simulated and self.controller.enabled:
            self.engine.set_camera(observed_at=now, last_seen=time.time())
        self.engine.tick(dt)
        view = study.session_view()
        self.sync_camera(view)
        with self.engine.lock:
            camera, browser = dict(self.engine.camera), dict(self.engine.browser)
        connected = bool(browser["updated"] and time.time() - browser["updated"] <= 75)
        self.connection.setText("Chrome connected" if connected else "Chrome not connected")
        if view and self.stack.currentIndex() == 1:
            phase = view["phase"]
            self.session_goal.setText(view["goal"] or "Your focus session")
            self.session_mode.setText(f"{study.MODES[view['mode']]} · {view['planned_seconds'] // 60}-minute block")
            self.phase_label.setText({"work": "WORKING", "paused": "PAUSED", "break": "TAKE YOUR TIME", "complete": "BLOCK COMPLETE"}[phase])
            self.timer_label.setText(study.format_duration(view["phase_left"]))
            note = {"work": f"Active time · {study.format_duration(view['active_seconds'])}",
                    "paused": "The clock is paused. Resume when you're ready.",
                    "break": "Your work time is saved. Resume early or stay longer.",
                    "complete": "Your planned block is done. Review it or take a break."}[phase]
            self.clock_note.setText(note)
            self.progress.setValue(round(1000 * view["active_seconds"] / view["planned_seconds"]))
            self.pause_button.setText("Pause" if phase == "work" else "Review session" if phase == "complete" else "Resume")
            self.break_button.setEnabled(phase != "break")
            self.preview_toggle.setEnabled(view["camera_enabled"] and phase == "work")
            self.calibrate_button.setEnabled(view["camera_enabled"] and phase == "work"
                                             and camera["status"] == "ok" and not self.controller.simulated)
            if phase != "work":
                self.dismiss_checkin()
            if not view["camera_enabled"]:
                status, note = "Camera off", "This session works without a camera."
            elif phase != "work":
                status, note = "Camera off", "Capture stops while paused, on a break, and at completion."
            elif self.controller.simulated:
                status, note = "Simulated camera", "Camera input is simulated for testing."
            elif camera["status"] == "ok":
                fresh = camera.get("observed_at") is not None and now - camera["observed_at"] <= 1
                status = "Face visible" if camera["present"] else "No face observed"
                if not fresh:
                    status = "Tracking unavailable"
                note = "An observation, not a measure of attention."
                calibration = self.engine.calib.view()
                if calibration["active"] or calibration["quality"] == "limited":
                    note = calibration["message"]
            elif camera["status"] == "starting":
                status, note = "Starting camera…", "Your session clock is already running."
            else:
                status, note = "Camera unavailable", "You can continue this session without it. See Diagnostics for details."
            self.camera_status.setText(status)
            self.camera_note.setText(note)
            self.browser_status.setText(browser["domain"] if connected else "Not connected")
            self.browser_note.setText({"productive": "Site categorized as work", "neutral": "Unlisted site",
                                       "distraction": "Selected distracting site", "other": "Outside Chrome; other apps aren't identified."}.get(browser["category"], "Unavailable")
                                      if connected else "Connect the extension to observe your work sites.")
            if self.preview_toggle.isChecked():
                data = self.engine.preview["png"]
                if data and phase == "work":
                    image = QImage.fromData(base64.b64decode(data))
                    self.preview_label.setPixmap(QPixmap.fromImage(image).scaled(420, 230, Qt.AspectRatioMode.KeepAspectRatio,
                                                                                 Qt.TransformationMode.SmoothTransformation))
                else:
                    self.preview_label.clear()
                    self.preview_label.setText("Camera preview is unavailable." if phase == "work" else "Camera is off.")
        while self.engine.events:
            kind, message = self.engine.events.pop(0)
            if view and view["phase"] == "work" and kind in ("nudge", "phone", "doomscroll", "lookaway"):
                self.show_checkin(message)

    def connection_help(self):
        from pathlib import Path
        path = Path(__file__).resolve().parents[1] / "extension"
        QMessageBox.information(self, "Connect Chrome", "Open chrome://extensions, turn on Developer mode, then choose Load unpacked.\n\n"
                                f"Select this folder:\n{path}\n\nReload your existing work tabs after loading the extension.")

    def diagnostics(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Diagnostics")
        dialog.resize(560, 360)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.addWidget(label("Tracking details", "section"))
        details = label("", "muted", True)
        details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(details)
        def update():
            with self.engine.lock:
                c = dict(self.engine.camera)
            details.setText(f"Camera: {c['status']}\nObservation: {c['reason']}\n"
                            f"Head: yaw {c['yaw']:.3f}, pitch {c['pitch']:.3f}\n"
                            f"Eye estimate: {c['gaze_h']:.3f}, {c['gaze_v']:.3f}\n"
                            f"Phone detector: {c['phone_status']}\n"
                            "These estimates do not establish attention or phone activity.")
        update()
        timer = QTimer(dialog)
        timer.timeout.connect(update)
        timer.start(400)
        recalibrate = button("Calibrate screen", lambda: (dialog.accept(), self.calibrate_camera()))
        recalibrate.setEnabled(self.controller.enabled and not self.controller.simulated)
        layout.addWidget(recalibrate)
        preview = button("Preview check-in", lambda: (dialog.accept(), self.show_checkin("Is this part of your task?", preview=True)))
        preview.setEnabled(self.stack.currentIndex() == 1)
        layout.addWidget(preview)
        layout.addWidget(button("Close", dialog.accept, "primary"))
        dialog.exec()

    def closeEvent(self, event):
        if study.session_view() and not self.end_session():
            event.ignore()
            return
        self.timer.stop()
        self.controller.stop()
        self.engine.running = False
        event.accept()


def run(engine, compact=False):
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("EyeTrack")
    app.setFont(QFont("DejaVu Sans", 10))
    window = FocusWindow(engine)
    if compact:
        window.resize(800, 720)
    window.show()
    app.exec()
