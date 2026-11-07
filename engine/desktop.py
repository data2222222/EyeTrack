"""The desktop window: a quiet setup screen, a live focus dashboard and a summary.

Camera algorithms live in tracking.py, session timing in study.py; this module only presents them.
"""
import base64
import sys
import time

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QFont, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QDialog, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
    QPushButton, QScrollArea, QSizePolicy, QStackedWidget, QToolButton,
    QVBoxLayout, QWidget,
)

import preferences
import sounds
import study
from settings_dialog import SettingsDialog
from wellbeing import MAX_SAMPLE_GAP
from widgets import (
    AWAY, BG, BREAK, GOOD, IDLE, LINE, MUTED, PAPER, PHONE, RAISED, SURFACE, TEXT,
    Check, Dropdown, PreviewView, Ring, SplitBar, Trend, button, card, label, score_style,
)

_STYLE = """
QWidget { color: @TEXT; font-family: 'Inter', 'Segoe UI', 'Helvetica Neue', 'DejaVu Sans', sans-serif; font-size: 13px; }
QMainWindow, QDialog, QScrollArea, QWidget#page, QWidget#root { background: @BG; }
QLabel { background: transparent; }
QLabel#brand { font-size: 15px; font-weight: 700; letter-spacing: 0.3px; }
QLabel#title { font-size: 30px; font-weight: 650; }
QLabel#subtitle, QLabel#muted { color: @MUTED; }
QLabel#wellbeing { color: @MUTED; font-size: 11px; }
QLabel#eyebrow { color: @MUTED; font-size: 11px; font-weight: 650; letter-spacing: 1.6px; }
QLabel#section { font-size: 14px; font-weight: 650; }
QLabel#goal { font-size: 16px; font-weight: 600; }
QLabel#score { font-size: 64px; font-weight: 600; }
QLabel#word { font-size: 15px; font-weight: 650; }
QLabel#stat { font-size: 22px; font-weight: 600; }
QLabel#error { color: #ff8fb0; background: #2a1820; border: 1px solid #5c2a3c; border-radius: 12px; padding: 10px 14px; }
QLabel#notice { color: @TEXT; background: #16302a; border: 1px solid #2c5f4e; border-radius: 14px; padding: 8px 16px; }
QLabel#mono { font-family: 'JetBrains Mono', 'DejaVu Sans Mono', 'Menlo', 'Consolas', monospace; }
QFrame#card { background: @SURFACE; border: 1px solid @LINE; border-radius: 18px; }
QFrame#toast { background: @RAISED; border: 1px solid @AWAY; border-radius: 16px; }
QPushButton { background: @RAISED; border: 1px solid @LINE; border-radius: 12px; padding: 10px 18px; font-weight: 600; }
QPushButton:hover { background: #283036; border-color: #3a454c; }
QPushButton:pressed { background: #20272b; }
QPushButton:focus, QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border: 1px solid @GOOD; }
QPushButton#primary:focus { border: 2px solid #c9f5e6; }
QPushButton#step { padding: 0; font-size: 18px; font-weight: 500; color: @MUTED; border-radius: 20px; }
QPushButton#step:hover { color: @TEXT; }
QPushButton:disabled { color: #5b676e; background: #14181a; border-color: #20272b; }
QPushButton#primary { background: @GOOD; color: #07140e; border: 1px solid @GOOD; padding: 12px 22px; }
QPushButton#primary:hover { background: #6be0b8; }
QPushButton#primary:disabled { background: #1f3a31; color: #5f8c7c; border-color: #1f3a31; }
QPushButton#quiet { background: transparent; border: 0; color: @MUTED; padding: 8px 10px; }
QPushButton#quiet:hover { color: @TEXT; background: @RAISED; }
QPushButton#overlay { background: rgba(14, 17, 19, 200); border: 0; color: @TEXT; padding: 6px 12px; border-radius: 12px; font-size: 12px; }
QPushButton#overlay:hover { background: rgba(14, 17, 19, 245); }
QPushButton#pill { padding: 8px 16px; color: @MUTED; }
QPushButton#pill:checked { background: #1d3a31; border: 1px solid @GOOD; color: @TEXT; }
QPushButton#chrome { background: @SURFACE; border: 1px solid @LINE; border-radius: 15px; padding: 6px 14px; font-weight: 500; font-size: 12px; color: @MUTED; }
QPushButton#chrome[ok='true'] { color: @TEXT; }
QToolButton { background: transparent; border: 1px solid transparent; border-radius: 14px; padding: 4px 12px; color: @MUTED; font-size: 18px; }
QToolButton:hover { background: @RAISED; color: @TEXT; }
QToolButton:focus { border: 1px solid @GOOD; color: @TEXT; }
QToolButton::menu-indicator { image: none; width: 0; }
QMenu { background: @RAISED; border: 1px solid @LINE; border-radius: 12px; padding: 6px; }
QMenu::item { padding: 8px 20px; border-radius: 8px; }
QMenu::item:selected { background: #2b343a; }
QMenu::item:disabled { color: #5b676e; }
QLineEdit { background: @SURFACE; border: 1px solid @LINE; border-radius: 14px; padding: 15px 17px; font-size: 15px; selection-background-color: #2f5f4e; }
QComboBox { background: @SURFACE; border: 1px solid @LINE; border-radius: 12px; padding: 10px 40px 10px 14px; font-weight: 550; }
QComboBox:hover { border-color: #3a454c; }
QComboBox::drop-down { border: 0; width: 0; }
QComboBox QAbstractItemView { background: @RAISED; border: 1px solid @LINE; selection-background-color: #2b343a; selection-color: @TEXT; outline: 0; padding: 4px; }
QCheckBox { spacing: 10px; color: @MUTED; padding: 3px 0; }
QCheckBox#option { color: @TEXT; font-weight: 550; padding: 5px 0; }
QCheckBox:disabled, QCheckBox#option:disabled { color: #5b676e; }
QCheckBox::indicator { width: 18px; height: 18px; border: 1px solid #3a454c; border-radius: 6px; background: @SURFACE; }
QCheckBox::indicator:hover { border-color: #5b676e; }
QCheckBox::indicator:checked { background: @GOOD; border: 1px solid @GOOD; }
QCheckBox::indicator:focus { border: 2px solid #c9f5e6; }
QCheckBox::indicator:disabled { background: #14181a; border-color: #20272b; }
QCheckBox::indicator:checked:disabled { background: #1f3a31; border-color: #1f3a31; }
QSpinBox QLineEdit { background: transparent; border: 0; padding: 0; }
QSpinBox::up-button, QSpinBox::down-button { width: 0; border: 0; }
QSpinBox { background: @SURFACE; border: 1px solid @LINE; border-radius: 12px; padding: 9px 4px; font-size: 15px; font-weight: 600; selection-background-color: #2f5f4e; }
QSlider::groove:horizontal { height: 6px; background: @RAISED; border-radius: 3px; }
QSlider::sub-page:horizontal { background: @GOOD; border-radius: 3px; }
QSlider::sub-page:horizontal:disabled { background: #1f3a31; }
QSlider::handle:horizontal { width: 18px; height: 18px; margin: -6px 0; background: @TEXT; border-radius: 9px; }
QSlider::handle:horizontal:focus { background: #c9f5e6; border: 2px solid @GOOD; }
QSlider::handle:horizontal:disabled { background: #3a454c; }
QComboBox:disabled { color: #5b676e; background: #14181a; border-color: #20272b; }
QLabel:disabled { color: #5b676e; }
QScrollArea { border: 0; }
QScrollBar:vertical { background: transparent; width: 8px; }
QScrollBar::handle:vertical { background: #2c353a; border-radius: 4px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QToolTip { background: @RAISED; color: @TEXT; border: 1px solid @LINE; padding: 6px; }
"""
STYLE = _STYLE
for _name, _value in {"BG": BG, "SURFACE": SURFACE, "RAISED": RAISED, "LINE": LINE, "TEXT": TEXT,
                      "MUTED": MUTED, "GOOD": GOOD, "AWAY": AWAY}.items():
    STYLE = STYLE.replace("@" + _name, _value)

PREVIEW_FPS_MS = 66
SCORE_TREND_POINTS = 36           # 6 minutes of 10-second steps in the live trend
CHIPS = {"screen": ("On screen", GOOD), "paper": ("On paper", PAPER), "away": ("Looking away", AWAY),
         "no_face": ("Out of view", AWAY), "phone": ("On phone", PHONE)}
SITE_TEXT = {"productive": "work site", "neutral": "unlisted site", "distraction": "distracting site",
             "other": "another app"}


def tint(widget, color):
    widget.setStyleSheet(f"color: {color};")


def percent(part, total):
    return f"{round(100 * part / total)}%" if total > 0 else "–"


class SplitCard(QFrame):
    """A titled stacked bar with one legend row per share."""

    def __init__(self, title, note=""):
        super().__init__()
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(12)
        head = QHBoxLayout()
        head.addWidget(label(title, "section"))
        head.addStretch()
        self.note = label(note, "muted")
        head.addWidget(self.note)
        layout.addLayout(head)
        self.bar = SplitBar()
        layout.addWidget(self.bar)
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(10)
        self.grid.setVerticalSpacing(7)
        self.grid.setColumnStretch(1, 1)
        layout.addLayout(self.grid)
        self.detail = label("", "muted", True)
        self.detail.hide()
        layout.addWidget(self.detail)
        self.keys = None
        self.rows = []

    def set_detail(self, text):
        self.detail.setText(text)
        self.detail.setVisible(bool(text))

    def set_rows(self, rows):
        """rows: [(name, color, seconds)]"""
        keys = [(name, color) for name, color, _ in rows]
        if keys != self.keys:
            while self.grid.count():
                item = self.grid.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            self.rows = []
            for i, (name, color) in enumerate(keys):
                dot = QLabel()
                dot.setFixedSize(10, 10)
                dot.setStyleSheet(f"background: {color}; border-radius: 5px;")
                time_label = label("00:00", "mono")
                share = label("–", "muted")
                share.setMinimumWidth(40)
                share.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                for col, w in enumerate((dot, label(name), time_label, share)):
                    self.grid.addWidget(w, i, col, Qt.AlignmentFlag.AlignVCenter)
                self.rows.append((time_label, share))
            self.keys = keys
        total = sum(seconds for _, _, seconds in rows)
        for (time_label, share), (_, _, seconds) in zip(self.rows, rows):
            time_label.setText(study.format_duration(seconds))
            share.setText(percent(seconds, total))
        self.bar.set_parts([(seconds, color) for _, color, seconds in rows])


class FocusWindow(QMainWindow):
    def __init__(self, engine, start_timer=True):
        super().__init__()
        self.engine = engine
        self.controller = engine.camera_controller
        self.report = None
        self.checkin_visible = False
        self.app_alert = None
        self.prefs_unreadable = False
        try:
            self.prefs = preferences.load_preferences()
        except OSError:
            self.prefs = dict(preferences.DEFAULTS)
            self.prefs_unreadable = True
        self.sounds = sounds.SoundPlayer(self)
        self.settings_dialog = None
        self.preview_hidden = not self.prefs["show_preview"]
        self.last_tick = time.monotonic()
        self.last_frame = None
        self.setWindowTitle("EyeTrack")
        self.resize(1120, 740)
        self.setMinimumSize(900, 660)
        self.setStyleSheet(STYLE)
        self.engine.show_preview = self.prefs["show_preview"]
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(32, 18, 32, 26)
        outer.setSpacing(14)
        header = QHBoxLayout()
        brand = label("●  EyeTrack", "brand")
        brand.setAccessibleName("EyeTrack")
        header.addWidget(brand)
        header.addStretch()
        self.connection = button("Chrome not connected", self.connection_help, "chrome")
        self.connection.setProperty("ok", False)
        header.addWidget(self.connection)
        self.menu_button = QToolButton()
        self.menu_button.setText("⋯")
        self.menu_button.setToolTip("Settings, calibration and tracking details (Ctrl+,)")
        self.menu_button.setAccessibleName("More options and settings")
        self.menu_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.build_menu()
        header.addWidget(self.menu_button)
        outer.addLayout(header)
        self.notice = label("", "notice")
        self.notice.setAccessibleName("Notice")
        self.notice.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.notice.setFixedHeight(self.notice.fontMetrics().height() + 20)
        notice_policy = self.notice.sizePolicy()
        notice_policy.setRetainSizeWhenHidden(True)
        self.notice.setSizePolicy(notice_policy)
        self.notice.hide()
        outer.addWidget(self.notice, 0, Qt.AlignmentFlag.AlignHCenter)
        self.notice_timer = QTimer(self)
        self.notice_timer.setSingleShot(True)
        self.notice_timer.timeout.connect(self.notice.hide)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack, 1)
        self.setup_page = self.page()
        self.session_page = self.page()
        self.summary_page = self.page()
        self.build_setup()
        self.build_session()
        self.build_summary()
        self.build_toast(root)
        self.navigate(0)
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.refresh)
        self.frame_timer = QTimer(self)
        self.frame_timer.setInterval(PREVIEW_FPS_MS)
        self.frame_timer.timeout.connect(self.update_frame)
        QShortcut(QKeySequence("Ctrl+,"), self, self.open_settings)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self.escape_pressed)
        self.apply_defaults()
        if self.prefs_unreadable:
            self.show_notice("Couldn't read your saved settings, so the standard defaults are in use.", 10000)
        if start_timer:
            self.timer.start()
            self.frame_timer.start()

    # ---------------------------------------------------------------- scaffolding
    def page(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        inner.setObjectName("page")
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(16)
        scroll.setWidget(inner)
        self.stack.addWidget(scroll)
        return layout

    def navigate(self, index):
        self.stack.setCurrentIndex(index)
        if index == 0:
            self.show_last_session()

    def build_menu(self):
        menu = QMenu(self.menu_button)
        self.settings_action = menu.addAction("Settings…", self.open_settings)
        menu.addSeparator()
        self.calibrate_action = menu.addAction("Calibrate screen…", self.calibrate_camera)
        menu.addAction("Tracking details…", self.diagnostics)
        self.preview_action = menu.addAction("Preview a check-in", self.preview_checkin)
        menu.addSeparator()
        menu.addAction("Connect Chrome…", self.connection_help)
        menu.aboutToShow.connect(self.update_menu)
        self.menu_button.setMenu(menu)

    def update_menu(self):
        view = study.session_view()
        live = bool(view and view["camera_enabled"] and view["phase"] == "work")
        self.calibrate_action.setEnabled(live and self.engine.camera["status"] == "ok" and not self.controller.simulated)
        self.preview_action.setEnabled(self.stack.currentIndex() == 1)

    def build_toast(self, root):
        self.checkin = QFrame(root)
        self.checkin.setObjectName("toast")
        self.checkin.setFixedWidth(460)
        box = QVBoxLayout(self.checkin)
        box.setContentsMargins(20, 16, 20, 16)
        box.setSpacing(10)
        self.checkin_title = label("A quick check-in", "section")
        self.checkin_message = label("", "", True)
        box.addWidget(self.checkin_title)
        box.addWidget(self.checkin_message)
        actions = QHBoxLayout()
        actions.addWidget(button("Keep working", self.dismiss_checkin, "primary"))
        actions.addWidget(button("Take a break", self.take_break))
        actions.addStretch()
        box.addLayout(actions)
        self.checkin.hide()

    def place_toast(self):
        self.checkin.adjustSize()
        root = self.centralWidget()
        self.checkin.move(QPoint((root.width() - self.checkin.width()) // 2, 66))
        self.checkin.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.checkin_visible:
            self.place_toast()

    # ---------------------------------------------------------------- setup
    def build_setup(self):
        layout = self.setup_page
        row = QHBoxLayout()
        row.addStretch(1)
        column = QVBoxLayout()
        column.setSpacing(14)
        column.addStretch(1)
        column.addWidget(label("Start a focus session", "title"))
        self.setup_summary = label("", "subtitle")
        column.addWidget(self.setup_summary)
        column.addSpacing(6)
        form, form_box = card(margins=(24, 24, 24, 22), spacing=14)
        self.goal_input = QLineEdit()
        self.goal_input.setPlaceholderText("What are you working on? (optional)")
        self.goal_input.setMaxLength(140)
        self.goal_input.setAccessibleName("Session goal, optional")
        self.goal_input.returnPressed.connect(self.start_session)
        form_box.addWidget(self.goal_input)
        options = QHBoxLayout()
        options.setSpacing(12)
        self.mode_box = Dropdown()
        self.mode_box.setAccessibleName("Where you will work")
        for key in study.SETUP_MODES:
            self.mode_box.addItem(study.MODES[key], key)
        self.rhythm_box = Dropdown()
        self.rhythm_box.setAccessibleName("Focus and break length")
        for work, rest in study.RHYTHMS:
            self.rhythm_box.addItem(self.rhythm_text(work, rest), (work, rest))
        for caption, box in (("WORKING WITH", self.mode_box), ("RHYTHM", self.rhythm_box)):
            cell = QVBoxLayout()
            cell.setSpacing(6)
            title = label(caption, "eyebrow")
            title.setBuddy(box)
            cell.addWidget(title)
            cell.addWidget(box)
            options.addLayout(cell, 1)
        form_box.addLayout(options)
        self.mode_note = label("Looking down at paper counts as on task.", "muted", True)
        form_box.addWidget(self.mode_note)
        self.camera_toggle = Check("Use the camera to follow where I look", "Use the camera")
        self.camera_toggle.setObjectName("option")
        self.camera_toggle.setChecked(True)
        form_box.addWidget(self.camera_toggle)
        self.privacy_note = label("Camera frames stay on this computer and are never saved.", "muted", True)
        form_box.addWidget(self.privacy_note)
        column.addWidget(form)
        self.setup_error = label("", "error", True)
        self.setup_error.setAccessibleName("Start error")
        self.setup_error.hide()
        column.addWidget(self.setup_error)
        self.start_button = button("", self.start_session, "primary")
        self.start_button.setMinimumHeight(50)
        column.addWidget(self.start_button)
        column.addSpacing(4)
        self.last_session = label("", "muted")
        self.last_session.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(self.last_session)
        self.settings_link = button("Settings and sound", self.open_settings, "quiet")
        self.settings_link.setAccessibleName("Open settings")
        column.addWidget(self.settings_link, 0, Qt.AlignmentFlag.AlignHCenter)
        column.addStretch(2)
        holder = QWidget()
        holder.setMaximumWidth(560)
        holder.setLayout(column)
        row.addWidget(holder, 4)
        row.addStretch(1)
        layout.addLayout(row, 1)
        self.mode_box.currentIndexChanged.connect(self.update_setup)
        self.rhythm_box.currentIndexChanged.connect(self.update_setup)
        self.camera_toggle.toggled.connect(self.update_setup)
        self.update_setup()

    @property
    def work_minutes(self):
        return self.rhythm_box.currentData()[0]

    @property
    def break_minutes(self):
        return self.rhythm_box.currentData()[1]

    def update_setup(self, *_):
        work, rest = self.rhythm_box.currentData()
        self.setup_summary.setText(f"{work} minutes of focus, then a {rest}-minute break.")
        self.start_button.setText(f"Start {work}-minute session")
        self.mode_note.setVisible(self.mode_box.currentData() == "both")
        self.privacy_note.setVisible(self.camera_toggle.isChecked())

    def show_last_session(self):
        last = study.reports[-1] if study.reports else None
        if not last:
            self.last_session.hide()
            return
        text = f"Last session · {study.format_duration(last['active_seconds'])} focused"
        if last.get("score") is not None:
            text += f" · score {last['score']}"
        self.last_session.setText(text)
        self.last_session.show()

    # ---------------------------------------------------------------- live dashboard
    def build_session(self):
        layout = self.session_page
        body = QHBoxLayout()
        body.setSpacing(18)
        layout.addLayout(body, 1)

        left = QVBoxLayout()
        left.setSpacing(12)
        self.preview = PreviewView()
        self.preview.hide_requested.connect(self.toggle_preview)
        left.addWidget(self.preview, 1)
        self.camera_hint = label("", "muted")
        self.camera_hint.setMinimumHeight(18)
        left.addWidget(self.camera_hint)
        self.attention_card = SplitCard("Where your attention went", "this session")
        left.addWidget(self.attention_card)
        body.addLayout(left, 5)

        right = QVBoxLayout()
        right.setSpacing(16)
        clock, clock_box = card()
        clock_box.setSpacing(6)
        self.session_goal = label("Focus session", "goal", True)
        self.session_goal.setAlignment(Qt.AlignmentFlag.AlignCenter)
        clock_box.addWidget(self.session_goal)
        self.session_mode = label("", "muted")
        self.session_mode.setAlignment(Qt.AlignmentFlag.AlignCenter)
        clock_box.addWidget(self.session_mode)
        self.ring = Ring()
        clock_box.addWidget(self.ring, 1)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.pause_button = button("Pause", self.toggle_pause, "primary")
        self.pause_button.setMinimumWidth(124)
        self.break_button = button("Take a break", self.take_break)
        self.end_button = button("End", self.end_session, "quiet")
        for w in (self.pause_button, self.break_button, self.end_button):
            actions.addWidget(w)
        clock_box.addLayout(actions)
        right.addWidget(clock, 5)

        score, score_box = card(spacing=8)
        head = QHBoxLayout()
        head.addWidget(label("FOCUS SCORE", "eyebrow"))
        head.addStretch()
        head.addWidget(label("last 5 min", "muted"))
        score_box.addLayout(head)
        number = QHBoxLayout()
        number.setSpacing(12)
        self.score_value = label("–", "score")
        self.score_word = label("Collecting…", "word")
        number.addWidget(self.score_value)
        number.addWidget(self.score_word, 1, Qt.AlignmentFlag.AlignBottom)
        score_box.addLayout(number)
        self.trend = Trend()
        self.trend.setMinimumHeight(70)
        score_box.addWidget(self.trend, 1)
        facts = QHBoxLayout()
        self.fact_aways = label("0 look-aways", "muted")
        self.fact_phone = label("0 phone", "muted")
        self.fact_apps = label("0 app alerts", "muted")
        self.now_label = label("", "muted")
        self.now_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        facts.addWidget(self.fact_aways)
        facts.addSpacing(12)
        facts.addWidget(self.fact_phone)
        facts.addSpacing(12)
        facts.addWidget(self.fact_apps)
        facts.addStretch()
        score_box.addWidget(self.now_label)
        score_box.addLayout(facts)
        right.addWidget(score, 4)
        body.addLayout(right, 4)
        self.session_error = label("", "muted", True)
        footer = QHBoxLayout()
        footer.addWidget(self.session_error, 1)
        self.wellbeing_status = label("", "wellbeing")
        self.wellbeing_status.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.wellbeing_status.setToolTip(
            "Estimated blinks and yawns during this session, using the existing camera feed.\n"
            "Sleepiness is only a rough cue from repeated yawns or prolonged eye closure, not a diagnosis.\n"
            "Talking, lighting and glasses can affect these estimates. No clear signs does not mean alert.\n"
            "No alerts, score changes or automatic pauses. Counts stay in memory and reset each session.\n"
            "Live eyelid/mouth measurements are available in Tracking details in the ⋯ menu.")
        self.wellbeing_status.hide()
        footer.addWidget(self.wellbeing_status)
        layout.addLayout(footer)

    def sync_camera(self, view):
        if view and view["phase"] == "work" and view["camera_enabled"]:
            self.controller.start()
        elif self.controller.enabled:
            self.controller.stop()

    def toggle_preview(self):
        self.preview_hidden = not self.preview_hidden
        self.engine.show_preview = not self.preview_hidden
        if self.preview_hidden:
            self.last_frame = None
        self.update_frame()

    def update_frame(self):
        """Fast path: only swap the camera picture; text and numbers update in refresh()."""
        view = study.session_view()
        wanted = bool(view and view["phase"] == "work" and view["camera_enabled"]
                      and not self.preview_hidden and self.stack.currentIndex() == 1)
        data = self.engine.preview["png"] if wanted else None
        if data is None:
            if self.preview.pixmap is not None:
                self.preview.set_frame(None)
            self.last_frame = None
            return
        if data is self.last_frame:
            return
        self.last_frame = data
        image = QImage.fromData(base64.b64decode(data))
        if not image.isNull():
            self.preview.set_frame(QPixmap.fromImage(image))

    # ---------------------------------------------------------------- summary
    def build_summary(self):
        layout = self.summary_page
        self.summary_title = label("Session ended", "title")
        self.summary_goal = label("", "subtitle", True)
        layout.addWidget(self.summary_title)
        layout.addWidget(self.summary_goal)

        top = QHBoxLayout()
        top.setSpacing(18)
        score, score_box = card()
        score_box.addWidget(label("FOCUS SCORE", "eyebrow"))
        number = QHBoxLayout()
        number.setSpacing(14)
        self.summary_score = label("–", "score")
        self.summary_word = label("", "word")
        number.addWidget(self.summary_score)
        number.addWidget(self.summary_word, 1, Qt.AlignmentFlag.AlignBottom)
        score_box.addLayout(number)
        self.summary_trend = Trend()
        self.summary_trend.setMinimumHeight(90)
        score_box.addWidget(self.summary_trend, 1)
        self.summary_note = label("An estimate from the camera and the sites you visited, not a judgement.", "muted", True)
        score_box.addWidget(self.summary_note)
        top.addWidget(score, 5)
        stats, stats_box = card()
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(16)
        self.summary_stats = {}
        for i, name in enumerate(("Active time", "Break time", "Paused time", "Look-aways", "Phone pickups", "Check-ins")):
            cell = QVBoxLayout()
            cell.setSpacing(2)
            value = label("–", "stat")
            cell.addWidget(value)
            cell.addWidget(label(name, "muted"))
            grid.addLayout(cell, i // 2, i % 2)
            self.summary_stats[name] = value
        stats_box.addLayout(grid)
        stats_box.addStretch()
        top.addWidget(stats, 4)
        layout.addLayout(top)

        split = QHBoxLayout()
        split.setSpacing(18)
        self.summary_attention = SplitCard("Where your attention went", "camera estimate")
        self.summary_sites = SplitCard("Where your time went", "Chrome and apps")
        split.addWidget(self.summary_attention, 1)
        split.addWidget(self.summary_sites, 1)
        layout.addLayout(split)

        result, result_box = card(margins=(22, 14, 22, 14))
        line = QHBoxLayout()
        line.addWidget(label("Did you reach your goal?", "section"))
        line.addStretch()
        self.result_group = QButtonGroup(self)
        for i, (key, text) in enumerate((("finished", "Yes"), ("partly", "Partly"), ("not_finished", "Not yet"))):
            w = button(text, name="pill", checkable=True)
            w.clicked.connect(lambda checked=False, value=key: self.save_result(value))
            self.result_group.addButton(w, i)
            line.addWidget(w)
        result_box.addLayout(line)
        self.result_note = label("", "muted")
        result_box.addWidget(self.result_note)
        self.result_card = result
        layout.addWidget(result)
        restart = QHBoxLayout()
        restart.addStretch()
        restart.addWidget(button("New session", self.restart, "primary"))
        layout.addLayout(restart)
        layout.addStretch()

    # ---------------------------------------------------------------- actions
    def start_session(self):
        ok, message = study.start_session(goal=self.goal_input.text(), work_min=self.work_minutes,
                                         break_min=self.break_minutes, mode=self.mode_box.currentData(),
                                         camera_enabled=self.camera_toggle.isChecked())
        if not ok:
            self.setup_error.setText(message)
            self.setup_error.show()
            return
        self.setup_error.hide()
        self.engine.events.clear()
        self.engine.reset_wellbeing()
        self.session_error.clear()
        self.preview_hidden = not self.prefs["show_preview"]
        self.engine.show_preview = self.prefs["show_preview"]
        self.last_frame = None
        self.preview.set_frame(None)
        self.navigate(1)
        self.refresh()

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
        self.summary_goal.setText(f"{report['goal'] or 'Focus session'} · {study.MODES.get(report['mode'], 'Computer only')} · "
                                  f"{report['planned_seconds'] // 60} min planned")
        score = report.get("score")
        color, word = score_style(score)
        self.summary_score.setText("–" if score is None else str(score))
        tint(self.summary_score, color)
        self.summary_word.setText("" if score is None else word)
        self.summary_trend.set_values(report.get("trace", []))
        if score is None:
            self.summary_note.setText("Not enough tracked time for a score. Use the camera and Chrome extension to get one.")
        else:
            self.summary_note.setText("An estimate from the camera and the sites you visited, not a judgement.")
        for name, value in (("Active time", study.format_duration(report["active_seconds"])),
                            ("Break time", study.format_duration(report["break_seconds"])),
                            ("Paused time", study.format_duration(report["paused_seconds"])),
                            ("Look-aways", str(report.get("look_aways", 0))),
                            ("Phone pickups", str(report.get("counts", {}).get("phone", 0))),
                            ("Check-ins", str(report["nudges"]))):
            self.summary_stats[name].setText(value)
        focus = report.get("focus")
        self.summary_attention.setVisible(bool(report["camera_enabled"] and focus))
        if focus:
            self.summary_attention.set_rows(self.attention_rows(focus, report["mode"]))
        activity = self.report_activity(report)
        self.summary_sites.setVisible(any(activity[k] > 0 for k in study.ACTIVITY if k != "unknown"))
        self.summary_sites.set_rows(self.activity_rows(activity))
        self.summary_sites.set_detail(self.apps_detail(report.get("apps")))
        self.result_group.setExclusive(False)
        for w in self.result_group.buttons():
            w.setChecked(False)
        self.result_group.setExclusive(True)
        self.result_note.clear()
        self.navigate(2)

    @staticmethod
    def attention_rows(focus, mode):
        rows = [("On screen", GOOD, focus.get("screen", 0.0))]
        if mode == "both":
            rows.append(("On paper", PAPER, focus.get("paper", 0.0)))
        rows.append(("Looking away", AWAY, focus.get("away", 0.0) + focus.get("no_face", 0.0)))
        rows.append(("On phone", PHONE, focus.get("phone", 0.0)))
        return rows

    @staticmethod
    def report_activity(report):
        """Merged sites + apps seconds; reports from before app tracking only have the Chrome split."""
        if report.get("activity"):
            return {**dict.fromkeys(study.ACTIVITY, 0.0), **report["activity"]}
        site = report["website"]
        return {**dict.fromkeys(study.ACTIVITY, 0.0), "work": site["work"], "unlisted": site["unlisted"],
                "distraction": site["distraction"], "app_other": site["outside"]}

    @staticmethod
    def activity_rows(activity):
        return [("Work sites", GOOD, activity["work"]), ("Other sites", PAPER, activity["unlisted"]),
                ("Distracting sites", PHONE, activity["distraction"]),
                ("Distracting apps", AWAY, activity["app_distraction"]), ("Other apps", IDLE, activity["app_other"])]

    @staticmethod
    def apps_detail(apps):
        """Most-used desktop apps by name and time (no window titles)."""
        top = [f"{app['name'].title()} {study.format_duration(app['seconds'])}" for app in (apps or [])[:3]]
        return "Top apps: " + " · ".join(top) if top else ""

    @staticmethod
    def now_text(view, browser, connected):
        current = view.get("current_app")
        if connected and browser["category"] != "other":
            return f"{browser['domain']} · {SITE_TEXT.get(browser['category'], 'site')}"
        if current:
            return f"{current[0].title()} · {'distracting app' if current[1] else 'app'}"
        return "Another app" if connected else "Chrome not connected"

    def save_result(self, result):
        try:
            study.set_goal_result(result)
            self.result_note.setText("Saved on this computer.")
        except OSError:
            self.result_note.setText("Couldn't save your answer. Please try again.")

    def restart(self):
        self.goal_input.clear()
        self.navigate(0)

    def apply_defaults(self, changed=None):
        """Point the setup screen at the saved defaults; a running session and the camera are never touched."""
        prefs = self.prefs
        changed = set(prefs) if changed is None else set(changed)
        if changed & {"work_minutes", "break_minutes"}:
            self.set_rhythm(prefs["work_minutes"], prefs["break_minutes"])
        if "mode" in changed:
            self.mode_box.setCurrentIndex(max(0, self.mode_box.findData(prefs["mode"])))
        if "camera_enabled" in changed:
            self.camera_toggle.setChecked(bool(prefs["camera_enabled"]))
        self.update_setup()

    def set_rhythm(self, work, rest):
        """Select a standard rhythm, or keep one extra 'custom' entry (always last) for a saved custom length."""
        box = self.rhythm_box
        standard = len(study.RHYTHMS)
        while box.count() > standard:
            box.removeItem(box.count() - 1)
        if (work, rest) in study.RHYTHMS:
            box.setCurrentIndex(study.RHYTHMS.index((work, rest)))
        else:
            box.addItem(self.rhythm_text(work, rest), (work, rest))
            box.setCurrentIndex(box.count() - 1)

    @staticmethod
    def rhythm_text(work, rest):
        return f"{work} min focus · {rest} min break"

    def open_settings(self):
        if self.settings_dialog is not None:
            self.settings_dialog.raise_()
            self.settings_dialog.activateWindow()
            return
        dialog = SettingsDialog(self.prefs, self, sound_player=self.sounds)
        dialog.saved.connect(self.settings_saved)
        dialog.finished.connect(self.forget_settings)
        self.settings_dialog = dialog
        dialog.open()

    def forget_settings(self, *_):
        dialog, self.settings_dialog = self.settings_dialog, None
        if dialog is not None:
            dialog.deleteLater()

    def settings_saved(self, values):
        validated = preferences.validate_preferences(values)
        changed = {name for name, value in validated.items() if value != self.prefs[name]}
        self.prefs = validated
        self.apply_defaults(changed)
        self.show_notice("Settings saved. Sounds apply now; other defaults start with your next session.")

    def show_notice(self, text, milliseconds=6000):
        self.notice.setText(text)
        self.notice.show()
        self.notice_timer.start(milliseconds)

    def escape_pressed(self):
        if self.checkin_visible:
            self.dismiss_checkin()

    def play_sound(self, event):
        """A cue never breaks the session: audio problems are ignored."""
        try:
            self.sounds.play(event, self.prefs)
        except Exception:
            pass

    def calibrate_camera(self):
        from camera_calibration import show_calibration
        self.engine.reset_calibration(guided=True)
        show_calibration(self.engine.calib, lambda: self.engine.camera["status"], self)

    def preview_checkin(self):
        self.show_checkin("Is this part of your task?", preview=True)

    def dismiss_checkin(self):
        self.checkin.hide()
        self.checkin_visible = False
        if self.app_alert is not None:
            alert, self.app_alert = self.app_alert, None
            alert.close()

    def show_app_alert(self, message):
        """A topmost, non-modal popup so the alert is seen even when another app is in front."""
        if self.app_alert is not None:
            return
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Distracting app")
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setText(message)
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.finished.connect(self.forget_app_alert)
        self.app_alert = dialog
        dialog.open()
        QApplication.alert(self)

    def forget_app_alert(self, *_):
        if self.sender() is self.app_alert:
            self.app_alert = None

    def show_checkin(self, message, preview=False):
        if self.checkin_visible:
            return
        self.checkin_visible = True
        self.checkin_title.setText("Preview check-in" if preview else "A quick check-in")
        self.checkin_message.setText(message)
        self.checkin.show()
        self.place_toast()
        if not preview:
            study.record_event("nudge")
            QApplication.alert(self)
            self.play_sound("checkin")

    # ---------------------------------------------------------------- refresh
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
        self.connection.setText(("●  " if connected else "○  ") + ("Chrome connected" if connected else "Chrome not connected"))
        if self.connection.property("ok") != connected:
            self.connection.setProperty("ok", connected)
            self.connection.style().unpolish(self.connection)
            self.connection.style().polish(self.connection)
        if view and self.stack.currentIndex() == 1:
            self.refresh_session(view, camera, browser, connected, now)
        while self.engine.events:
            kind, message = self.engine.events.pop(0)
            if view and view["phase"] == "work" and kind in ("nudge", "phone", "doomscroll", "lookaway"):
                self.show_checkin(message)
            elif view and view["phase"] == "work" and kind == "appblock":
                self.show_app_alert(message)
            elif view and kind == "complete":
                self.play_sound("completion")

    def refresh_session(self, view, camera, browser, connected, now):
        phase = view["phase"]
        self.session_goal.setText(view["goal"] or "Focus session")
        self.session_mode.setText(f"{study.MODES[view['mode']]} · {view['planned_seconds'] // 60} min")
        if phase == "break":
            over = view["current_break"] >= view["break_planned"]
            self.ring.set_state(min(1.0, view["current_break"] / view["break_planned"]), study.format_duration(view["phase_left"]),
                                "BREAK OVER" if over else "BREAK", BREAK)
        else:
            caption = {"work": "FOCUS", "paused": "PAUSED", "complete": "BLOCK DONE"}[phase]
            self.ring.set_state(view["active_seconds"] / view["planned_seconds"], study.format_duration(view["phase_left"]),
                                caption, GOOD, dim=phase == "paused")
        self.pause_button.setText({"work": "Pause", "paused": "Resume", "break": "Back to work", "complete": "Finish"}[phase])
        self.break_button.setText("Start break" if phase == "complete" else "Take a break")
        self.break_button.setEnabled(phase != "break")
        self.end_button.setVisible(phase != "complete")
        if phase != "work":
            self.dismiss_checkin()

        # score card
        score = view["score"]
        color, word = score_style(score if phase == "work" or score is not None else None)
        self.score_value.setText("–" if score is None else str(score))
        tint(self.score_value, color)
        self.score_word.setText(word)
        tint(self.score_word, color)
        self.trend.set_values(view["trace"][-SCORE_TREND_POINTS:])
        self.fact_aways.setText(f"{view['look_aways']} look-away{'' if view['look_aways'] == 1 else 's'}")
        self.fact_phone.setText(f"{view['counts']['phone']} phone")
        app_alerts = view["counts"].get("app", 0)
        self.fact_apps.setText(f"{app_alerts} app alert{'s' if app_alerts != 1 else ''}")
        self.now_label.setText("Now · " + self.now_text(view, browser, connected))

        # attention card and camera view
        if view["camera_enabled"]:
            self.attention_card.set_rows(self.attention_rows(view["focus"], view["mode"]))
            self.attention_card.note.setText("this session")
        else:
            self.attention_card.set_rows(self.activity_rows(view["activity"]))
            self.attention_card.note.setText("Chrome and apps, camera off")
        self.refresh_preview(view, camera, phase)
        self.refresh_wellbeing(view, camera, now)

    def refresh_wellbeing(self, view, camera, now):
        visible = bool(view["camera_enabled"] and view["phase"] == "work" and not self.controller.simulated)
        self.wellbeing_status.setVisible(visible)
        if not visible:
            return
        observation = camera.get("wellbeing", {})
        stamp = observation.get("observed_at")
        state = observation.get("state", "unavailable")
        if (camera["status"] != "ok" or not camera["present"] or stamp is None
                or not 0 <= now - stamp <= MAX_SAMPLE_GAP):
            state = "unavailable"
        status = {"unavailable": "unavailable", "collecting": "learning…",
                  "possible": "possible signs", "no_clear_signs": "no clear signs"}[state]
        blinks, yawns = observation.get("blinks", 0), observation.get("yawns", 0)
        self.wellbeing_status.setText(
            f"{blinks} blink{'' if blinks == 1 else 's'} · {yawns} yawn{'' if yawns == 1 else 's'} · Sleepiness: {status}")

    def refresh_preview(self, view, camera, phase):
        chip, chip_color = "", IDLE
        hint = ""
        if not view["camera_enabled"]:
            message = "The camera is off for this session.\nYour score comes from the sites you visit."
        elif phase != "work":
            message = "The camera is off while you " + {"paused": "are paused", "break": "take a break",
                                                          "complete": "are done"}[phase] + "."
        elif self.controller.simulated:
            message = "Simulated camera for testing."
        elif self.preview_hidden:
            message = "Preview hidden. Tracking continues."
        elif camera["status"] == "ok":
            message = "Waiting for the first picture…"
        elif camera["status"] == "starting":
            message = "Starting the camera…"
        else:
            message = "The camera is unavailable. Your session continues without it.\nSee Tracking details in the ⋯ menu."
        if view["camera_enabled"] and phase == "work" and camera["status"] == "ok":
            name, color = CHIPS.get(view["now"], ("", IDLE))
            if name:
                chip = f"{name} · {study.format_duration(view['now_seconds'])}" if view["now_seconds"] >= 5 else name
                chip_color = color
            calibration = self.engine.calib.view()
            if self.controller.simulated:
                hint = "Camera input is simulated for testing."
            elif calibration["active"] or calibration["quality"] == "limited":
                hint = calibration["message"]
            elif view["now"] in ("away", "no_face"):
                hint = "Looks like: " + (camera["reason"] if camera["reason"] not in ("-", "no face") else "no face in view")
            elif view["now"] == "phone":
                hint = "A phone is visible in the camera. This is an estimate."
            else:
                hint = "A webcam estimate of where you look, not a measure of attention."
        self.camera_hint.setText(hint)
        self.preview.set_state(message, chip, chip_color)
        self.preview.set_toggle("Show" if self.preview_hidden else "Hide",
                                bool(view["camera_enabled"] and phase == "work" and camera["status"] == "ok"
                                     and not self.controller.simulated))
        self.update_frame()

    # ---------------------------------------------------------------- dialogs
    def connection_help(self):
        from pathlib import Path
        path = Path(__file__).resolve().parents[1] / "extension"
        QMessageBox.information(self, "Connect Chrome", "Open chrome://extensions, turn on Developer mode, then choose Load unpacked.\n\n"
                                f"Select this folder:\n{path}\n\nReload your existing work tabs after loading the extension.")

    def diagnostics(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Tracking details")
        dialog.resize(520, 340)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        layout.addWidget(label("Tracking details", "section"))
        details = label("", "muted", True)
        details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(details)

        def update():
            with self.engine.lock:
                c = dict(self.engine.camera)
            confidence = c.get("phone_confidence")
            signals = c.get("wellbeing", {})
            eyelids = "/".join("–" if ratio is None else f"{ratio:.2f}"
                               for ratio in signals.get("eye_ratios", (None, None)))
            mouth = signals.get("mouth_ratio")
            mouth_text = "–" if mouth is None else f"{mouth:.2f}"
            sample_hz = signals.get("sample_hz")
            rate_text = "–" if sample_hz is None else f"{sample_hz:.1f}"
            phone_note = " - possible phone, not counted" if c.get("phone_tentative") else ""
            details.setText(f"Camera: {c['status']}\nObservation: {c['reason']}\n"
                            f"Head: yaw {c['yaw']:.3f}, pitch {c['pitch']:.3f}\n"
                            f"Eye estimate: {c['gaze_h']:.3f}, {c['gaze_v']:.3f}\n"
                            f"Blink/yawn geometry: eyelids {eyelids}, mouth {mouth_text}\n"
                            f"Camera analysis: {rate_text} frames/s\n"
                            f"Phone detector: {c['phone_status']}"
                            + (f" (confidence {confidence:.2f}{phone_note})" if confidence else "") + "\n"
                            "These estimates do not establish attention or phone activity.")
        update()
        timer = QTimer(dialog)
        timer.timeout.connect(update)
        timer.start(400)
        layout.addStretch()
        layout.addWidget(button("Close", dialog.accept, "primary"))
        dialog.exec()

    def closeEvent(self, event):
        if study.session_view() and not self.end_session():
            event.ignore()
            return
        if self.settings_dialog is not None:
            self.settings_dialog.close()
        try:
            self.sounds.stop()
        except Exception:
            pass
        self.timer.stop()
        self.frame_timer.stop()
        self.controller.stop()
        self.engine.running = False
        event.accept()


def run(engine, compact=False):
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("EyeTrack")
    app.setFont(QFont("DejaVu Sans", 10))
    window = FocusWindow(engine)
    if compact:
        window.resize(940, 680)
    window.show()
    app.exec()
