"""The Settings dialog: sound cues, next-session defaults and camera defaults.

Nothing here touches the clock or the camera. Saved values are returned to the window, which applies
them to the setup screen so they take effect when the next session starts.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QDialog, QFrame, QGridLayout, QHBoxLayout, QScrollArea, QSlider, QVBoxLayout, QWidget,
)

import preferences
import study
from widgets import Check, Dropdown, Stepper, button, card, label

SOUND_STYLES = (("Chime", "chime"), ("Bell", "bell"), ("Soft", "soft"))
WORK_RANGE = (1, 120)
BREAK_RANGE = (1, 60)


def checkbox(text, name=""):
    box = Check(text, name or text)
    box.setObjectName("option")
    return box


class SettingsDialog(QDialog):
    """Edits a copy of the preferences; nothing changes until Save succeeds."""

    saved = Signal(dict)

    def __init__(self, values, parent=None, sound_player=None, save=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setObjectName("settings")
        self.setMinimumSize(520, 440)
        self.resize(600, 720)
        self.original = dict(values)
        self.sound_player = sound_player
        self.save = save
        self.saved_values = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 22)
        outer.setSpacing(14)
        outer.addWidget(label("Settings", "title"))
        banner = label("Sounds apply as soon as you save. Session length, mode and camera defaults apply "
                       "from your next session; a running session keeps its timers and camera.", "subtitle", True)
        outer.addWidget(banner)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("page")
        column = QVBoxLayout(body)
        column.setContentsMargins(0, 2, 10, 2)
        column.setSpacing(16)
        column.addWidget(self.build_sound())
        column.addWidget(self.build_session())
        column.addWidget(self.build_camera())
        column.addStretch(1)
        scroll.setWidget(body)
        self.scroll = scroll
        self.settings_body = body
        outer.addWidget(scroll, 1)

        self.error = label("", "error", True)
        self.error.setAccessibleName("Settings error")
        self.error.hide()
        outer.addWidget(self.error)
        actions = QHBoxLayout()
        actions.setSpacing(10)
        actions.addStretch()
        self.cancel_button = button("Cancel", self.reject)
        self.save_button = button("Save settings", self.accept, "primary")
        self.save_button.setDefault(True)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.save_button)
        outer.addLayout(actions)

        self.load(values)
        self.master.toggled.connect(self.update_enabled)
        self.camera_use.toggled.connect(self.update_enabled)
        self.volume.valueChanged.connect(lambda volume: self.volume_text.setText(f"{volume}%"))
        self.volume.valueChanged.connect(self.update_enabled)
        self.work.spin.valueChanged.connect(self.sync_presets)
        self.rest.spin.valueChanged.connect(self.sync_presets)
        self.update_enabled()
        self.sync_presets()
        for first, second in ((self.master, self.volume), (self.volume, self.style_box),
                              (self.style_box, self.preview_button), (self.preview_button, self.checkins),
                              (self.checkins, self.completion), (self.completion, self.work),
                              (self.work, self.rest), (self.rest, self.mode_box),
                              (self.mode_box, self.camera_use), (self.camera_use, self.preview_default),
                              (self.preview_default, self.cancel_button), (self.cancel_button, self.save_button)):
            QWidget.setTabOrder(first, second)
        self.master.setFocus()
        QApplication.instance().focusChanged.connect(self.reveal_focus)

    def reveal_focus(self, previous, current):
        if current is not None and self.settings_body.isAncestorOf(current):
            self.scroll.ensureWidgetVisible(current, 0, 24)

    def section(self, title, note):
        box, layout = card(spacing=14)
        layout.addWidget(label(title, "section"))
        if note:
            layout.addWidget(label(note, "muted", True))
        return box, layout

    def field(self, caption, control, hint=""):
        """A captioned control; the caption is the control's buddy so Alt-keys and screen readers find it."""
        cell = QVBoxLayout()
        cell.setSpacing(6)
        text = label(caption, "eyebrow")
        text.setBuddy(control)
        cell.addWidget(text)
        cell.addWidget(control)
        if hint:
            cell.addWidget(label(hint, "muted", True))
        return cell

    def build_sound(self):
        box, layout = self.section("Sound", "Soft cues for check-ins and when a focus block ends. "
                                            "Nothing plays unless sounds are on.")
        self.master = checkbox("Play sounds", "Play sounds")
        layout.addWidget(self.master)

        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setSingleStep(5)
        self.volume.setPageStep(10)
        self.volume.setAccessibleName("Sound volume")
        self.volume_text = label("", "mono")
        self.volume_text.setMinimumWidth(44)
        self.volume_text.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        slider_row = QHBoxLayout()
        slider_row.setSpacing(12)
        slider_row.addWidget(self.volume, 1)
        slider_row.addWidget(self.volume_text)
        self.volume_caption = label("VOLUME", "eyebrow")
        self.volume_caption.setBuddy(self.volume)
        layout.addWidget(self.volume_caption)
        layout.addLayout(slider_row)

        self.style_box = Dropdown()
        self.style_box.setAccessibleName("Sound style")
        for text, key in SOUND_STYLES:
            self.style_box.addItem(text, key)
        self.preview_button = button("Play preview", self.play_preview)
        self.preview_button.setAccessibleName("Play a preview of the selected sound")
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addLayout(self.field("STYLE", self.style_box), 1)
        preview_cell = QVBoxLayout()
        preview_cell.setSpacing(6)
        preview_cell.addWidget(label(" ", "eyebrow"))
        preview_cell.addWidget(self.preview_button)
        row.addLayout(preview_cell)
        layout.addLayout(row)

        self.checkins = checkbox("Play a cue for check-ins", "Cue for check-ins")
        self.completion = checkbox("Play a cue when a focus block is complete", "Cue when a focus block is complete")
        layout.addWidget(self.checkins)
        layout.addWidget(self.completion)
        self.sound_note = label("Turn on sounds to hear previews.", "muted")
        layout.addWidget(self.sound_note)
        return box

    def build_session(self):
        box, layout = self.section("Next session", "Used the next time you start a session.")
        self.work = Stepper(*WORK_RANGE, 25, name="Focus minutes")
        self.rest = Stepper(*BREAK_RANGE, 5, name="Break minutes")
        row = QHBoxLayout()
        row.setSpacing(16)
        row.addLayout(self.field("FOCUS", self.work), 1)
        row.addLayout(self.field("BREAK", self.rest), 1)
        layout.addLayout(row)
        presets = QHBoxLayout()
        presets.setSpacing(8)
        self.preset_buttons = []
        for work, rest in study.RHYTHMS:
            pill = button(f"{work} / {rest}", name="pill", checkable=True)
            pill.setAccessibleName(f"{work} minute focus, {rest} minute break")
            pill.clicked.connect(lambda checked=False, w=work, r=rest: self.use_preset(w, r))
            presets.addWidget(pill)
            self.preset_buttons.append(((work, rest), pill))
        presets.addStretch()
        layout.addLayout(presets)
        self.mode_box = Dropdown()
        self.mode_box.setAccessibleName("Default way of working")
        for key in study.SETUP_MODES:
            self.mode_box.addItem(study.MODES[key], key)
        layout.addLayout(self.field("DEFAULT WORKING MODE", self.mode_box))
        return box

    def build_camera(self):
        box, layout = self.section("Camera", "The camera is never turned on from Settings. It starts only when a "
                                             "session with the camera begins its focus time, and stops on pause, "
                                             "break or end.")
        self.camera_use = checkbox("Use the camera by default", "Use the camera by default")
        self.preview_default = checkbox("Show the camera picture by default", "Show the camera picture by default")
        layout.addWidget(self.camera_use)
        layout.addWidget(self.preview_default)
        self.preview_note = label("Hiding the picture only hides it. Tracking continues, and frames are never "
                                  "saved or uploaded.", "muted", True)
        layout.addWidget(self.preview_note)
        return box

    def load(self, values):
        v = {**preferences.DEFAULTS, **values}
        self.master.setChecked(bool(v["sounds_enabled"]))
        self.volume.setValue(int(v["sound_volume"]))
        self.volume_text.setText(f"{self.volume.value()}%")
        self.style_box.setCurrentIndex(max(0, self.style_box.findData(v["sound_style"])))
        self.checkins.setChecked(bool(v["sound_checkins"]))
        self.completion.setChecked(bool(v["sound_completion"]))
        self.work.setValue(int(v["work_minutes"]))
        self.rest.setValue(int(v["break_minutes"]))
        self.mode_box.setCurrentIndex(max(0, self.mode_box.findData(v["mode"])))
        self.camera_use.setChecked(bool(v["camera_enabled"]))
        self.preview_default.setChecked(bool(v["show_preview"]))

    def values(self):
        return {**self.original,
                "sounds_enabled": self.master.isChecked(), "sound_volume": self.volume.value(),
                "sound_style": self.style_box.currentData(), "sound_checkins": self.checkins.isChecked(),
                "sound_completion": self.completion.isChecked(), "work_minutes": self.work.value(),
                "break_minutes": self.rest.value(), "mode": self.mode_box.currentData(),
                "camera_enabled": self.camera_use.isChecked(), "show_preview": self.preview_default.isChecked()}

    def update_enabled(self, *_):
        sound = self.master.isChecked()
        for w in (self.volume, self.volume_caption, self.volume_text, self.style_box,
                  self.preview_button, self.checkins, self.completion):
            w.setEnabled(sound)
        self.sound_note.setText("Turn on sounds to hear previews." if not sound else
                                "Volume is 0. Raise it to hear previews and cues.")
        self.sound_note.setVisible(not sound or self.volume.value() == 0)
        self.preview_default.setEnabled(self.camera_use.isChecked())

    def use_preset(self, work, rest):
        self.work.setValue(work)
        self.rest.setValue(rest)

    def sync_presets(self, *_):
        current = (self.work.value(), self.rest.value())
        for rhythm, pill in self.preset_buttons:
            pill.setChecked(rhythm == current)

    def play_preview(self):
        """Plays the chosen sound with the values on screen; the per-event switches do not apply."""
        if self.sound_player is None:
            import sounds
            self.sound_player = sounds.SoundPlayer(self)
        try:
            played = self.sound_player.play("checkin", self.values(), preview=True)
            if not played and self.master.isChecked() and self.volume.value() > 0:
                self.show_error("Audio isn't available on this computer. Visual reminders still work.")
            elif played:
                self.error.hide()
        except Exception:
            self.show_error("The preview couldn't play on this computer. Your other settings still work.")

    def show_error(self, text):
        self.error.setText(text)
        self.error.show()

    def accept(self):
        save = self.save or preferences.save_preferences
        try:
            saved = save(self.values())
        except (OSError, ValueError):
            self.show_error("Couldn't save your settings. Nothing was changed; check that this computer has free "
                            "disk space and try again.")
            return
        self.error.hide()
        self.saved_values = dict(saved)
        self.saved.emit(self.saved_values)
        super().accept()

    def done(self, result):
        try:
            QApplication.instance().focusChanged.disconnect(self.reveal_focus)
        except (RuntimeError, TypeError):
            pass
        if self.sound_player is not None:
            try:
                self.sound_player.stop()
            except Exception:
                pass
        super().done(result)
