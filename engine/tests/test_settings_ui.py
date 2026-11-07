"""Settings reached from the header menu: saving, cancelling, next-session semantics and sound cues."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QScrollArea

import engine
import preferences
import sounds
import study
from desktop import FocusWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def started_tones(monkeypatch):
    """Replaces real audio output: every tone that would have played is recorded instead."""
    tones = []

    def fake_start(samples, volume, parent):
        tones.append(volume)
        return None, None

    monkeypatch.setattr(sounds, "_start_audio", fake_start)
    return tones


@pytest.fixture
def window(app, monkeypatch, tmp_path, started_tones):
    clock = [1000.0]
    monkeypatch.setattr(study.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(study.time, "time", lambda: clock[0] + 100000)
    monkeypatch.setattr(study, "session", None)
    monkeypatch.setattr(study, "last_report", None)
    monkeypatch.setattr(study, "reports", [])
    monkeypatch.setattr(study, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(study, "REPORTS_PATH", str(tmp_path / "sessions.json"))
    monkeypatch.setattr(engine, "camera", dict(engine.camera))
    monkeypatch.setattr(engine, "browser", dict(engine.browser))
    monkeypatch.setattr(engine, "session", dict(engine.session))
    monkeypatch.setattr(engine, "events", [])
    monkeypatch.setattr(engine, "running", True)
    monkeypatch.setattr(engine, "camera_controller", engine.CameraController(simulated=True))
    w = FocusWindow(engine, start_timer=False)
    w.show()
    app.processEvents()
    yield w, clock
    if study.session_view():
        w.end_session(confirm=False)
    w.close()
    app.processEvents()


def open_from_menu(w, app):
    action = w.menu_button.menu().actions()[0]
    assert action.text() == "Settings…"
    action.trigger()
    app.processEvents()
    assert w.settings_dialog is not None
    return w.settings_dialog


def saved_file(tmp_path):
    return tmp_path / "preferences.json"


def test_settings_is_first_menu_item_and_opening_it_never_starts_the_camera(window, app):
    w, _ = window
    dialog = open_from_menu(w, app)
    assert dialog.isVisible() and dialog.windowTitle() == "Settings"
    assert not engine.camera_controller.enabled
    assert engine.camera["status"] == "off"
    assert dialog.focusWidget() is dialog.master
    assert dialog.save_button.isDefault()


def test_dialog_explains_that_defaults_apply_next_session(window, app):
    w, _ = window
    dialog = open_from_menu(w, app)
    text = " ".join(label.text() for label in dialog.findChildren(type(dialog.error)))
    assert "next session" in text
    assert "never turned on from Settings" in text
    assert "only hides it" in text


def test_save_persists_and_points_setup_at_the_new_defaults(window, app, tmp_path):
    w, _ = window
    dialog = open_from_menu(w, app)
    dialog.work.setValue(40)
    dialog.rest.setValue(8)
    dialog.mode_box.setCurrentIndex(1)
    dialog.camera_use.setChecked(False)
    dialog.preview_default.setChecked(False)
    dialog.volume.setValue(60)
    dialog.style_box.setCurrentIndex(2)
    dialog.save_button.click()
    app.processEvents()
    assert w.settings_dialog is None
    stored = preferences.load_preferences()
    assert (stored["work_minutes"], stored["break_minutes"], stored["mode"]) == (40, 8, "both")
    assert (stored["camera_enabled"], stored["show_preview"]) == (False, False)
    assert (stored["sound_volume"], stored["sound_style"]) == (60, "soft")
    assert saved_file(tmp_path).exists()
    assert (w.work_minutes, w.break_minutes) == (40, 8)
    assert w.mode_box.currentData() == "both"
    assert not w.camera_toggle.isChecked()
    assert "40-minute" in w.start_button.text()
    assert w.notice.isVisibleTo(w) and "next session" in w.notice.text()
    assert not engine.camera_controller.enabled


def test_next_session_uses_saved_defaults_and_hidden_preview(window, app):
    w, _ = window
    dialog = open_from_menu(w, app)
    dialog.work.setValue(40)
    dialog.rest.setValue(8)
    dialog.preview_default.setChecked(False)
    dialog.save_button.click()
    w.start_button.click()
    view = study.session_view()
    assert view["planned_seconds"] == 40 * 60 and view["break_planned"] == 8 * 60
    assert w.preview_hidden and not engine.show_preview
    assert engine.camera_controller.enabled


def test_standard_rhythm_keeps_dropdown_order_and_drops_the_custom_entry(window, app):
    w, _ = window
    dialog = open_from_menu(w, app)
    dialog.work.setValue(33)
    dialog.save_button.click()
    assert w.rhythm_box.count() == len(study.RHYTHMS) + 1
    dialog = open_from_menu(w, app)
    dialog.use_preset(15, 3)
    dialog.save_button.click()
    assert w.rhythm_box.count() == len(study.RHYTHMS)
    assert (w.work_minutes, w.break_minutes) == (15, 3)


def test_cancel_discards_changes(window, app, tmp_path):
    w, _ = window
    dialog = open_from_menu(w, app)
    dialog.work.setValue(90)
    dialog.master.setChecked(False)
    dialog.cancel_button.click()
    app.processEvents()
    assert w.settings_dialog is None
    assert not saved_file(tmp_path).exists()
    assert w.prefs == preferences.DEFAULTS
    assert w.work_minutes == 25 and not w.notice.isVisibleTo(w)


def test_save_failure_is_shown_and_nothing_changes(window, app, monkeypatch, tmp_path):
    w, _ = window

    def refuse(values, path=None):
        raise OSError("disk full")

    monkeypatch.setattr(preferences, "save_preferences", refuse)
    dialog = open_from_menu(w, app)
    dialog.work.setValue(90)
    dialog.save_button.click()
    app.processEvents()
    assert w.settings_dialog is dialog and dialog.isVisible()
    assert dialog.error.isVisibleTo(dialog) and "Couldn't save" in dialog.error.text()
    assert "disk full" not in dialog.error.text()
    assert w.prefs == preferences.DEFAULTS and w.work_minutes == 25
    assert not saved_file(tmp_path).exists()
    dialog.cancel_button.click()


def test_saving_during_a_session_leaves_timers_preview_and_camera_alone(window, app):
    w, clock = window
    w.start_button.click()
    clock[0] += 60
    w.refresh()
    before = study.session_view()
    dialog = open_from_menu(w, app)
    dialog.work.setValue(50)
    dialog.rest.setValue(10)
    dialog.camera_use.setChecked(False)
    dialog.preview_default.setChecked(False)
    dialog.save_button.click()
    app.processEvents()
    after = study.session_view()
    assert after["planned_seconds"] == before["planned_seconds"] == 25 * 60
    assert after["break_planned"] == before["break_planned"] == 5 * 60
    assert after["camera_enabled"] and after["phase"] == "work"
    assert engine.camera_controller.enabled
    assert not w.preview_hidden and engine.show_preview
    assert w.stack.currentIndex() == 1
    assert (w.work_minutes, w.break_minutes) == (50, 10)
    assert not w.camera_toggle.isChecked()


def test_camera_still_stops_on_pause_break_and_end_after_settings_changes(window, app):
    w, clock = window
    w.start_button.click()
    open_from_menu(w, app).save_button.click()
    assert engine.camera_controller.enabled
    w.pause_button.click()
    assert not engine.camera_controller.enabled
    open_from_menu(w, app).save_button.click()
    assert not engine.camera_controller.enabled
    w.pause_button.click()
    w.break_button.click()
    assert not engine.camera_controller.enabled
    open_from_menu(w, app).cancel_button.click()
    w.refresh()
    assert not engine.camera_controller.enabled
    assert w.end_session(confirm=False)
    assert not engine.camera_controller.enabled


def test_completion_cue_plays_once_not_on_every_refresh(window, started_tones):
    w, clock = window
    w.start_button.click()
    clock[0] += 1501
    for _ in range(5):
        w.refresh()
    assert study.session_view()["phase"] == "complete"
    assert started_tones == [35]


def test_checkin_cue_plays_once_and_previews_stay_silent(window, started_tones):
    w, _ = window
    w.start_button.click()
    w.show_checkin("Preview", preview=True)
    w.preview_checkin()
    assert started_tones == []
    w.dismiss_checkin()
    w.show_checkin("A real one")
    w.show_checkin("A duplicate")
    w.refresh()
    assert started_tones == [35]


def test_master_switch_silences_every_cue(window, app, started_tones):
    w, clock = window
    dialog = open_from_menu(w, app)
    dialog.master.setChecked(False)
    assert not dialog.preview_button.isEnabled()
    assert not dialog.volume.isEnabled() and not dialog.checkins.isEnabled()
    dialog.save_button.click()
    w.start_button.click()
    w.show_checkin("Real check-in")
    clock[0] += 1501
    w.refresh()
    assert study.session_view()["phase"] == "complete"
    assert started_tones == []


def test_per_event_switches_are_honoured(window, app, started_tones):
    w, clock = window
    dialog = open_from_menu(w, app)
    dialog.checkins.setChecked(False)
    dialog.save_button.click()
    w.start_button.click()
    w.show_checkin("Quiet check-in")
    assert started_tones == []
    clock[0] += 1501
    w.refresh()
    assert started_tones == [35]


def test_preview_button_ignores_event_switches_but_not_volume(window, app, started_tones, tmp_path):
    w, _ = window
    dialog = open_from_menu(w, app)
    dialog.checkins.setChecked(False)
    dialog.completion.setChecked(False)
    dialog.volume.setValue(70)
    dialog.preview_button.click()
    assert started_tones == [70]
    dialog.volume.setValue(0)
    dialog.preview_button.click()
    assert started_tones == [70]
    dialog.cancel_button.click()
    assert not saved_file(tmp_path).exists()


def test_closing_the_window_stops_audio_and_the_dialog(window, app, monkeypatch):
    w, _ = window
    stops = []
    monkeypatch.setattr(w.sounds, "stop", lambda: stops.append(1))
    open_from_menu(w, app)
    w.close()
    app.processEvents()
    assert w.settings_dialog is None
    assert stops


def test_unavailable_preview_explains_visual_reminders_still_work(window, app, monkeypatch):
    focus_window, _ = window
    dialog = open_from_menu(focus_window, app)
    monkeypatch.setattr(focus_window.sounds, "play", lambda *args, **kwargs: False)
    dialog.preview_button.click()
    assert dialog.error.isVisibleTo(dialog)
    assert "Visual reminders still work" in dialog.error.text()
    monkeypatch.setattr(focus_window.sounds, "play", lambda *args, **kwargs: True)
    dialog.preview_button.click()
    assert not dialog.error.isVisibleTo(dialog)


def test_unreadable_saved_settings_fall_back_to_defaults_with_a_notice(app, monkeypatch, tmp_path, started_tones):
    monkeypatch.setattr(study, "session", None)
    monkeypatch.setattr(study, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(study, "REPORTS_PATH", str(tmp_path / "sessions.json"))
    monkeypatch.setattr(engine, "camera_controller", engine.CameraController(simulated=True))

    def unreadable(path=None):
        raise PermissionError("denied")

    monkeypatch.setattr(preferences, "load_preferences", unreadable)
    w = FocusWindow(engine, start_timer=False)
    w.show()
    app.processEvents()
    assert w.prefs == preferences.DEFAULTS
    assert w.notice.isVisibleTo(w) and "standard defaults" in w.notice.text()
    assert (w.work_minutes, w.break_minutes) == (25, 5)
    w.close()


@pytest.mark.parametrize("size", [(520, 440), (600, 720)])
def test_settings_fit_without_horizontal_overflow_or_clipped_actions(window, app, size):
    w, _ = window
    dialog = open_from_menu(w, app)
    dialog.resize(*size)
    app.processEvents()
    scroll = dialog.findChild(QScrollArea)
    assert not scroll.horizontalScrollBar().isVisible()
    assert scroll.widget().width() <= scroll.viewport().width()
    bounds = dialog.rect()
    for button in (dialog.cancel_button, dialog.save_button):
        assert button.isVisible() and bounds.contains(button.geometry())
    dialog.cancel_button.click()


def test_setup_screen_offers_settings_by_keyboard_and_from_the_page(window, app, tmp_path):
    w, _ = window
    assert w.settings_link.accessibleName() == "Open settings"
    w.settings_link.click()
    app.processEvents()
    assert w.settings_dialog is not None
    w.open_settings()
    assert w.settings_dialog is not None
    w.settings_dialog.cancel_button.click()
    app.processEvents()
    assert w.settings_dialog is None
    w.activateWindow()
    app.processEvents()
    QTest.keyClick(w, Qt.Key.Key_Comma, Qt.KeyboardModifier.ControlModifier)
    app.processEvents()
    assert w.settings_dialog is not None
    w.settings_dialog.volume.setValue(90)
    QTest.keyClick(w.settings_dialog, Qt.Key.Key_Escape)
    app.processEvents()
    assert w.settings_dialog is None
    assert not saved_file(tmp_path).exists()


def test_keyboard_focus_scrolls_settings_controls_into_view(window, app):
    focus_window, _ = window
    dialog = open_from_menu(focus_window, app)
    dialog.resize(520, 440)
    app.processEvents()
    dialog.master.setFocus()
    app.processEvents()
    assert dialog.scroll.verticalScrollBar().value() == 0
    for index in range(18):
        current = app.focusWidget()
        if current is dialog.preview_default:
            break
        QTest.keyClick(current, Qt.Key.Key_Tab)
        app.processEvents()
    assert app.focusWidget() is dialog.preview_default
    assert dialog.scroll.verticalScrollBar().value() > 0
    position = dialog.preview_default.mapTo(dialog.scroll.viewport(), dialog.preview_default.rect().topLeft())
    assert dialog.scroll.viewport().rect().contains(position)


def test_sound_only_save_preserves_unfinished_setup_choices(window, app):
    focus_window, _ = window
    focus_window.rhythm_box.setCurrentIndex(1)
    focus_window.mode_box.setCurrentIndex(1)
    focus_window.camera_toggle.setChecked(False)
    dialog = open_from_menu(focus_window, app)
    dialog.volume.setValue(60)
    dialog.save_button.click()
    assert (focus_window.work_minutes, focus_window.break_minutes) == (50, 10)
    assert focus_window.mode_box.currentData() == "both"
    assert not focus_window.camera_toggle.isChecked()


def test_settings_notice_keeps_the_live_layout_stable(window, app):
    focus_window, _ = window
    focus_window.start_button.click()
    app.processEvents()
    original = focus_window.stack.geometry()
    dialog = open_from_menu(focus_window, app)
    dialog.save_button.click()
    app.processEvents()
    assert focus_window.stack.geometry() == original
    assert "Sounds apply now" in focus_window.notice.text()
    focus_window.notice.hide()
    app.processEvents()
    assert focus_window.stack.geometry() == original


def test_zero_volume_has_an_explicit_muted_hint(window, app):
    focus_window, _ = window
    dialog = open_from_menu(focus_window, app)
    dialog.volume.setValue(0)
    assert dialog.sound_note.isVisibleTo(dialog)
    assert "Volume is 0" in dialog.sound_note.text()


def test_closing_settings_disconnects_focus_following(window, app, monkeypatch):
    focus_window, _ = window
    dialog = open_from_menu(focus_window, app)
    revealed = []
    monkeypatch.setattr(dialog.scroll, "ensureWidgetVisible", lambda *args: revealed.append(args))
    app.focusChanged.emit(None, dialog.preview_default)
    assert revealed
    revealed.clear()
    dialog.reject()
    app.focusChanged.emit(None, dialog.preview_default)
    assert not revealed
