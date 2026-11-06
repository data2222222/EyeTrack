"""Exercise the visible session journey with a simulated camera, no image capture."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

import engine
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


def test_setup_is_camera_off_and_goal_is_optional(window):
    w, _ = window
    assert w.stack.currentIndex() == 0
    assert not engine.camera_controller.enabled
    assert engine.camera["status"] == "off"
    w.mode_box.setCurrentIndex(1)
    w.rhythm_box.setCurrentIndex(2)
    w.start_button.click()
    assert w.stack.currentIndex() == 1
    assert study.session_view()["mode"] == "both"
    assert study.session_view()["planned_seconds"] == 15 * 60
    assert study.session_view()["break_planned"] == 3 * 60
    assert study.session_view()["goal"] == ""
    assert engine.camera_controller.enabled


def test_defaults_are_25_5_computer_with_camera_and_preview(window):
    w, _ = window
    assert w.mode_box.count() == 2 and w.mode_box.currentData() == "pc"
    assert (w.work_minutes, w.break_minutes) == (25, 5)
    assert w.camera_toggle.isChecked()
    assert "25-minute" in w.start_button.text()
    assert not w.mode_note.isVisibleTo(w)
    w.mode_box.setCurrentIndex(1)
    assert w.mode_note.isVisibleTo(w)
    w.start_button.click()
    assert engine.show_preview and not w.preview_hidden
    assert w.ring.time_text == "25:00"
    assert study.session_view()["break_planned"] == 300


def test_complete_visible_journey_preserves_work_and_releases_camera(window):
    w, clock = window
    w.goal_input.setText("Research quantum computing")
    w.start_button.click()
    clock[0] += 60
    w.pause_button.click()
    assert not engine.camera_controller.enabled
    clock[0] += 30
    w.refresh()
    assert w.ring.time_text == "24:00"
    w.pause_button.click()
    assert engine.camera_controller.enabled
    clock[0] += 10
    w.break_button.click()
    assert not engine.camera_controller.enabled
    clock[0] += 20
    w.pause_button.click()
    assert study.session_view()["break_count"] == 1
    assert w.ring.time_text == "23:50"
    assert w.end_session(confirm=False)
    assert w.stack.currentIndex() == 2
    assert not engine.camera_controller.enabled
    assert w.summary_stats["Active time"].text() == "01:10"
    assert w.summary_stats["Break time"].text() == "00:20"
    assert w.summary_stats["Paused time"].text() == "00:30"
    w.result_group.button(1).click()
    assert study.load_json(study.REPORTS_PATH, [])[0]["goal_done"] == "partly"
    w.restart()
    assert w.stack.currentIndex() == 0 and not w.goal_input.text()


def test_camera_can_be_disabled_and_completion_stays_complete(window):
    w, clock = window
    w.camera_toggle.setChecked(False)
    w.start_button.click()
    assert not engine.camera_controller.enabled
    clock[0] += 1501
    w.refresh()
    assert w.ring.time_text == "00:00"
    assert study.session_view()["phase"] == "complete"
    w.pause_button.click()
    assert w.stack.currentIndex() == 2
    assert w.report["active_seconds"] == 1500


def test_preview_does_not_create_tracked_nudges(window):
    w, _ = window
    w.start_button.click()
    w.show_checkin("Preview", preview=True)
    assert study.session_view()["counts"]["nudge"] == 0
    w.dismiss_checkin()
    w.show_checkin("Real check-in")
    assert study.session_view()["counts"]["nudge"] == 1
    w.show_checkin("Duplicate")
    assert study.session_view()["counts"]["nudge"] == 1


def test_live_scoring_and_looking_away_show_in_dashboard(window):
    w, clock = window
    w.start_button.click()
    for _ in range(20):                      # 20 s on screen (simulated camera reports facing)
        clock[0] += 1
        w.refresh()
    assert w.score_value.text() == "100"
    assert w.score_word.text() == "Locked in"
    engine.camera.update(facing=False, reason="eyes looking left")
    for _ in range(20):
        clock[0] += 1
        w.refresh()
    assert study.session_view()["now"] == "away"
    assert w.preview.chip.startswith("Looking away")
    assert w.fact_aways.text() == "1 look-away"
    assert 45 <= int(w.score_value.text()) <= 55
    focus = study.session_view()["focus"]
    assert 19 <= focus["screen"] <= 21 and 19 <= focus["away"] <= 21


def test_phone_shows_as_its_own_state(window):
    w, clock = window
    w.start_button.click()
    engine.camera.update(phone=True, phone_since=study.time.time() - 10)
    clock[0] += 1
    w.refresh()
    assert study.session_view()["now"] == "phone"
    assert w.preview.chip.startswith("On phone")


def test_preview_can_be_hidden_without_stopping_camera(window):
    w, _ = window
    w.start_button.click()
    w.toggle_preview()
    assert w.preview_hidden and not engine.show_preview
    assert engine.camera_controller.enabled
    w.toggle_preview()
    assert engine.show_preview


def test_summary_reports_score_and_attention(window):
    w, clock = window
    w.start_button.click()
    for _ in range(30):
        clock[0] += 1
        w.refresh()
    assert w.end_session(confirm=False)
    assert w.summary_score.text() == "100"
    assert w.summary_attention.isVisibleTo(w)
    assert w.report["score"] == 100
