"""Exercise the visible session journey with a simulated camera, no image capture."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QLabel

import engine
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
    monkeypatch.setattr(sounds, "_start_audio", lambda *args: None)
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


def test_wellbeing_readout_is_quiet_and_survives_hidden_preview(window):
    w, clock = window
    w.start_button.click()
    view = study.session_view()
    camera = dict(engine.camera, wellbeing={"blinks": 12, "yawns": 1, "state": "possible",
                                           "observed_at": clock[0]})
    w.controller.simulated = False
    w.refresh_wellbeing(view, camera, clock[0])
    assert w.wellbeing_status.isVisibleTo(w)
    assert w.wellbeing_status.text() == "12 blinks · 1 yawn · Sleepiness: possible signs"
    assert w.wellbeing_status.objectName() == "wellbeing"
    assert "not a diagnosis" in w.wellbeing_status.toolTip()
    w.preview_hidden = True
    w.refresh_wellbeing(view, camera, clock[0])
    assert w.wellbeing_status.isVisibleTo(w)
    assert study.session_view() == view
    assert not engine.events
    assert not w.checkin_visible


@pytest.mark.parametrize("phase", ["paused", "break", "complete"])
def test_wellbeing_readout_hides_outside_work(window, phase):
    w, clock = window
    w.start_button.click()
    w.controller.simulated = False
    w.refresh_wellbeing(dict(study.session_view(), phase=phase), engine.camera, clock[0])
    assert not w.wellbeing_status.isVisibleTo(w)


def test_wellbeing_readout_hides_for_camera_free_or_simulated_sessions(window):
    w, clock = window
    w.start_button.click()
    assert not w.wellbeing_status.isVisibleTo(w)
    w.controller.simulated = False
    w.refresh_wellbeing(dict(study.session_view(), camera_enabled=False), engine.camera, clock[0])
    assert not w.wellbeing_status.isVisibleTo(w)


@pytest.mark.parametrize("reason", ["stale", "missing", "off", "unusable"])
def test_wellbeing_readout_never_presents_stale_sleepiness_as_live(window, reason):
    w, clock = window
    w.start_button.click()
    w.controller.simulated = False
    camera = dict(engine.camera, wellbeing={"blinks": 1, "yawns": 0, "state": "no_clear_signs",
                                           "observed_at": clock[0]})
    if reason == "stale":
        clock[0] += 1
    elif reason == "missing":
        camera["present"] = False
    elif reason == "off":
        camera["status"] = "off"
    else:
        camera["wellbeing"]["observed_at"] = None
    w.refresh_wellbeing(study.session_view(), camera, clock[0])
    assert w.wellbeing_status.text() == "1 blink · 0 yawns · Sleepiness: unavailable"


def test_starting_a_new_session_resets_wellbeing_and_does_not_save_it(window):
    w, _ = window
    engine.wellbeing_tracker.blinks = 42
    engine.wellbeing_tracker.yawns = 3
    w.start_button.click()
    assert engine.camera["wellbeing"]["blinks"] == engine.camera["wellbeing"]["yawns"] == 0
    w.end_session(confirm=False)
    assert "wellbeing" not in study.last_report


def test_tracking_details_include_live_blink_yawn_geometry(window, monkeypatch):
    w, _ = window
    engine.camera["wellbeing"] = {"eye_ratios": (.3, .25), "mouth_ratio": .6, "sample_hz": 14.8}
    shown = []

    def inspect_dialog(dialog):
        shown.extend(widget.text() for widget in dialog.findChildren(QLabel))
        return 0

    monkeypatch.setattr(QDialog, "exec", inspect_dialog)
    w.diagnostics()
    details = "\n".join(shown)
    assert "eyelids 0.30/0.25, mouth 0.60" in details
    assert "14.8 frames/s" in details


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


def test_distracting_app_alert_counts_shows_popup_and_reports_apps(window):
    w, clock = window
    snapshot = {"processes": {1: "code", 3: "discord"}, "front": 1}
    monitor = engine.appmonitor.AppMonitor(
        scanner=lambda: engine.appmonitor.Snapshot(snapshot["processes"], snapshot["front"]),
        clock=lambda: clock[0], own_pid=-1)
    engine.app_monitor = monitor
    try:
        w.start_button.click()
        monitor.refresh()
        clock[0] += 1
        w.refresh()
        assert w.app_alert is None
        snapshot["front"] = 3
        monitor.refresh()
        clock[0] += 1
        w.refresh()
        assert w.app_alert is not None and "Discord" in w.app_alert.text()
        assert study.session_view()["counts"]["app"] == 1
        assert w.fact_apps.text() == "1 app alert"
        assert study.session_view()["counts"]["nudge"] == 0
        clock[0] += 3
        w.refresh()
        w.pause_button.click()                           # pausing dismisses the popup
        assert w.app_alert is None
        w.pause_button.click()
        assert w.end_session(confirm=False)
        assert w.summary_sites.isVisibleTo(w)
        apps = {a["name"]: a for a in w.report["apps"]}
        assert apps["discord"]["distracting"] and not apps["code"]["distracting"]
        assert w.report["activity"]["app_distraction"] > 0
        assert w.summary_sites.detail.text().startswith("Top apps: ")
        assert "Discord" in w.summary_sites.detail.text()
    finally:
        engine.app_monitor = None


def test_events_outside_work_are_dropped_not_queued(window):
    w, clock = window
    w.start_button.click()
    w.take_break()
    engine.emit("appblock", "Discord is in front.")
    w.refresh()
    assert w.app_alert is None and not engine.events
    w.pause_button.click()
    w.refresh()
    assert w.app_alert is None


def test_summary_without_site_or_app_data_hides_the_activity_card(window):
    w, clock = window
    w.start_button.click()
    clock[0] += 5
    assert w.end_session(confirm=False)
    assert not w.summary_sites.isVisibleTo(w)
    assert w.summary_sites.detail.text() == ""


def test_now_line_names_the_site_or_the_app_in_front(window):
    w, clock = window
    view = {"current_app": None}
    browser = {"domain": "youtube.com", "category": "distraction"}
    assert w.now_text(view, browser, True) == "youtube.com · distracting site"
    other = {"domain": "(outside browser)", "category": "other"}
    assert w.now_text({"current_app": ("discord", True)}, other, True) == "Discord · distracting app"
    assert w.now_text({"current_app": ("code", False)}, other, True) == "Code · app"
    assert w.now_text(view, other, True) == "Another app"
    assert w.now_text(view, browser, False) == "Chrome not connected"


def test_current_activity_is_a_separate_compact_card_with_plain_tab_titles(window):
    w, _ = window
    w.start_button.click()
    view = study.session_view()
    browser = {"domain": "example.com", "category": "productive", "title": "<Physics> & circuits"}
    w.refresh_activity(view, browser, True)
    assert w.active_app.parentWidget() is w.activity_card
    assert w.active_tab.parentWidget() is w.activity_card
    assert w.active_app.text() == "Chrome · work site"
    assert w.active_tab.toolTip() == "<qt>example.com · &lt;Physics&gt; &amp; circuits</qt>"
    assert w.active_tab.accessibleDescription() == "example.com · <Physics> & circuits"
    from PySide6.QtCore import Qt
    assert w.active_tab.textFormat() == Qt.TextFormat.PlainText
    other = {"domain": "(outside browser)", "category": "other", "title": ""}
    w.refresh_activity(dict(view, current_app=("discord", True)), other, True)
    assert w.active_app.text() == "Discord · distracting app"
    assert w.active_tab.text() == "Chrome is in the background"
    w.refresh_activity(dict(view, current_app=None), other, False)
    assert w.active_app.text() == "Active app unavailable"
    assert w.active_tab.text() == "Chrome not connected"


def test_current_activity_card_remains_visible_at_minimum_window_size(window, app):
    w, _ = window
    w.resize(900, 660)
    w.start_button.click()
    app.processEvents()
    viewport = w.stack.currentWidget().viewport()
    corner = w.activity_card.mapTo(viewport, w.activity_card.rect().bottomRight())
    assert viewport.rect().contains(corner)
    assert w.activity_card.height() < 110


def test_old_reports_still_render_in_the_merged_card(window):
    w, _ = window
    old = {"website": {"work": 10.0, "unlisted": 5.0, "distraction": 2.0, "outside": 3.0, "unavailable": 0.0}}
    activity = w.report_activity(old)
    assert activity["work"] == 10 and activity["app_other"] == 3 and activity["app_distraction"] == 0
    assert [name for name, _, _ in w.activity_rows(activity)] == [
        "Work sites", "Other sites", "Distracting sites", "Distracting apps", "Other apps"]
