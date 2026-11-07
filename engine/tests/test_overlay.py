"""The always-on-top overlay: what it shows, how it hides, and how Settings switches it off."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QRect, QTime
from PySide6.QtWidgets import QApplication

import engine
import overlay
import preferences
import sounds
import study
from desktop import FocusWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, monkeypatch, tmp_path):
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
    monkeypatch.setattr(sounds, "_start_audio", lambda *args: (None, None))
    w = FocusWindow(engine, start_timer=False)
    w.show()
    app.processEvents()
    yield w, clock
    if study.session_view():
        w.end_session(confirm=False)
    w.close()
    app.processEvents()


def view(phase="work", left=754, score=None):
    return {"phase": phase, "phase_left": left, "score": score}


def save_settings(w, app, **changes):
    w.open_settings()
    app.processEvents()
    dialog = w.settings_dialog
    if "overlay_enabled" in changes:
        dialog.overlay_enabled.setChecked(changes["overlay_enabled"])
    if "overlay_corner" in changes:
        dialog.overlay_corner.setCurrentIndex(dialog.overlay_corner.findData(changes["overlay_corner"]))
    dialog.save_button.click()
    app.processEvents()


def test_summary_text_follows_the_session_phase():
    assert overlay.summarize(None)[0] == "No session"
    assert overlay.summarize(view("work", 754))[0] == "Focus 12:34"
    assert overlay.summarize(view("work", 754, 82))[0] == "Focus 12:34 · 82"
    assert overlay.summarize(view("paused", 61))[0] == "Paused 01:01"
    assert overlay.summarize(view("break", 300))[0] == "Break 05:00"
    assert overlay.summarize(view("complete", 0))[0] == "Block done"


def test_corner_for_picks_the_nearest_corner():
    area = QRect(0, 0, 1000, 600)
    assert overlay.corner_for(QPoint(100, 50), area) == "top_left"
    assert overlay.corner_for(QPoint(900, 50), area) == "top_right"
    assert overlay.corner_for(QPoint(100, 550), area) == "bottom_left"
    assert overlay.corner_for(QPoint(900, 550), area) == "bottom_right"


def test_overlay_is_on_by_default_and_shows_clock_and_session(window, app):
    w, _ = window
    assert w.overlay.isVisible()
    w.overlay.update_state(None, QTime(14, 5))
    assert w.overlay.clock.text() and "5" in w.overlay.clock.text()
    assert w.overlay.status.text() == "No session"
    w.start_button.click()
    w.refresh()
    assert w.overlay.status.text().startswith("Focus ")
    w.toggle_pause()
    w.refresh()
    assert w.overlay.status.text().startswith("Paused ")
    w.end_session(confirm=False)
    w.refresh()
    assert w.overlay.status.text() == "No session"


def test_overlay_never_takes_focus_or_touches_the_camera(window, app):
    w, _ = window
    assert not w.overlay.isActiveWindow()
    assert not engine.camera_controller.enabled
    w.overlay.update_state(view())
    assert not engine.camera_controller.enabled


def test_x_button_hides_it_for_now_and_the_menu_brings_it_back(window, app):
    w, _ = window
    w.overlay.close_button.click()
    app.processEvents()
    assert not w.overlay.isVisible() and w.overlay_hidden
    assert preferences.load_preferences()["overlay_enabled"] is True      # not a lasting change
    w.update_menu()
    assert w.overlay_action.text() == "Show overlay" and w.overlay_action.isEnabled()
    w.overlay_action.trigger()
    assert w.overlay.isVisible() and not w.overlay_hidden
    w.update_menu()
    assert w.overlay_action.text() == "Hide overlay"


def test_hidden_overlay_stays_hidden_across_refreshes_and_sessions(window, app):
    w, _ = window
    w.hide_overlay()
    w.start_button.click()
    w.refresh()
    assert not w.overlay.isVisible()


def test_settings_can_turn_it_off_completely(window, app):
    w, _ = window
    save_settings(w, app, overlay_enabled=False)
    assert not w.overlay.isVisible()
    assert preferences.load_preferences()["overlay_enabled"] is False
    w.update_menu()
    assert not w.overlay_action.isEnabled() and "Settings" in w.overlay_action.text()
    w.toggle_overlay()                      # the shortcut cannot override the setting
    assert not w.overlay.isVisible()
    w.refresh()
    assert not w.overlay.isVisible()


def test_turning_it_back_on_in_settings_shows_it_even_after_the_x_button(window, app):
    w, _ = window
    save_settings(w, app, overlay_enabled=False)
    w.overlay_hidden = True
    save_settings(w, app, overlay_enabled=True)
    assert w.overlay.isVisible() and not w.overlay_hidden


def test_saving_other_settings_does_not_bring_back_a_hidden_overlay(window, app):
    w, _ = window
    w.hide_overlay()
    save_settings(w, app)
    assert not w.overlay.isVisible()


def test_corner_setting_moves_the_overlay(window, app):
    w, _ = window
    save_settings(w, app, overlay_corner="bottom_left")
    area = w.overlay.available_area()
    assert w.overlay.corner == "bottom_left"
    assert w.overlay.x() == area.left() + overlay.MARGIN
    assert w.overlay.y() + w.overlay.height() == area.bottom() + 1 - overlay.MARGIN
    assert preferences.load_preferences()["overlay_corner"] == "bottom_left"


def test_dropping_the_overlay_snaps_to_a_corner_and_remembers_it(window, app):
    w, _ = window
    area = w.overlay.available_area()
    w.overlay.move(area.left() + 30, area.bottom() - w.overlay.height() - 30)
    w.overlay.snap()
    assert w.overlay.corner == "bottom_left"
    assert preferences.load_preferences()["overlay_corner"] == "bottom_left"
    assert w.prefs["overlay_corner"] == "bottom_left"


def test_closing_the_window_closes_the_overlay(window, app):
    w, _ = window
    w.close()
    app.processEvents()
    assert not w.overlay.isVisible()
