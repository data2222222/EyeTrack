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
    w.mode_group.button(1).click()
    w.duration_group.button(15).click()
    w.start_button.click()
    assert w.stack.currentIndex() == 1
    assert study.session_view()["mode"] == "notebook"
    assert study.session_view()["goal"] == ""
    assert engine.camera_controller.enabled


def test_complete_visible_journey_preserves_work_and_releases_camera(window):
    w, clock = window
    w.goal_input.setText("Research quantum computing")
    w.start_button.click()
    clock[0] += 60
    w.pause_button.click()
    assert not engine.camera_controller.enabled
    clock[0] += 30
    w.refresh()
    assert w.timer_label.text() == "24:00"
    w.pause_button.click()
    assert engine.camera_controller.enabled
    clock[0] += 10
    w.break_button.click()
    assert not engine.camera_controller.enabled
    clock[0] += 20
    w.pause_button.click()
    assert study.session_view()["break_count"] == 1
    assert w.timer_label.text() == "23:50"
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
    assert w.timer_label.text() == "00:00"
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
