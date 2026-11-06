"""Session-clock invariants, using deterministic timestamps rather than sleeps."""
import pytest

import study


@pytest.fixture
def clock(monkeypatch, tmp_path):
    now = [1000.0]
    monkeypatch.setattr(study.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(study.time, "time", lambda: now[0] + 100000)
    monkeypatch.setattr(study, "session", None)
    monkeypatch.setattr(study, "last_report", None)
    monkeypatch.setattr(study, "reports", [])
    monkeypatch.setattr(study, "REPORTS_PATH", str(tmp_path / "sessions.json"))
    return now


def start(**kwargs):
    assert study.start_session("", "", **kwargs)[0]


def test_clock_uses_timestamps_not_callback_dt(clock):
    start()
    clock[0] += 12
    study.tick(9999, {"state": "AFK"})
    assert study.session_view()["active_seconds"] == 12
    study.tick(9999, {})
    assert study.session_view()["active_seconds"] == 12


def test_pause_and_resume_preserve_remaining_work(clock):
    start()
    clock[0] += 60
    assert study.pause_session()
    clock[0] += 200
    assert study.session_view()["phase_left"] == 1440
    assert study.resume_work()
    clock[0] += 10
    view = study.session_view()
    assert view["active_seconds"] == 70
    assert view["phase_left"] == 1430
    assert view["paused_seconds"] == 200


def test_break_counts_once_on_resume_with_actual_duration(clock):
    start()
    clock[0] += 60
    assert study.start_break()
    clock[0] += 15
    assert study.session_view()["break_count"] == 0
    assert study.resume_work()
    assert not study.resume_work()
    view = study.session_view()
    assert view["phase_left"] == 1440
    assert view["break_count"] == 1
    assert view["break_seconds"] == 15


def test_break_deadline_does_not_automatically_resume(clock):
    start()
    study.start_break()
    clock[0] += 420
    view = study.session_view()
    assert view["phase"] == "break"
    assert view["phase_left"] == 0
    assert view["active_seconds"] == 0
    report = study.stop_session()
    assert report["break_count"] == 1
    assert report["breaks"] == [420]


def test_completion_caps_time_and_never_starts_another_block(clock):
    start(work_min=1)
    clock[0] += 300
    events = study.tick(0, {})
    assert len(events) == 1 and events[0][0] == "complete"
    assert not study.tick(0, {})
    assert study.session_view()["active_seconds"] == 60
    assert study.session_view()["phase"] == "complete"
    assert not study.focus_mode_active()
    assert study.start_break()
    clock[0] += 10
    assert study.resume_work()
    assert study.session_view()["phase"] == "complete"


def test_stop_settles_last_fraction_and_zero_is_not_invented(clock):
    start()
    assert study.stop_session()["active_seconds"] == 0
    start()
    clock[0] += 2.25
    assert study.stop_session()["active_seconds"] == 2.25
    assert study.session_view() is None


def test_observation_partitions_equal_active_time_and_expire(clock):
    start()
    study.tick(0, {"category": "productive", "browser_age": 0,
                   "camera_category": "present", "camera_observed_at": clock[0]})
    clock[0] += 5
    report = study.stop_session()
    assert sum(report["website"].values()) == report["active_seconds"] == 5
    assert sum(report["camera"].values()) == 5
    assert report["camera"]["present"] == 1
    assert report["camera"]["unavailable"] == 4


def test_resume_does_not_attribute_the_previous_camera_state(clock):
    start()
    study.tick(0, {"camera_category": "present", "camera_observed_at": clock[0]})
    study.pause_session()
    clock[0] += 30
    study.resume_work()
    clock[0] += 1
    assert study.stop_session()["camera"] == {"present": 0, "no_face": 0, "unavailable": 1}


def test_mode_optional_goal_and_self_report(clock):
    start(mode="both", camera_enabled=False)
    assert study.session_view()["mode"] == "both"
    report = study.stop_session()
    assert report["goal"] == "" and report["goal_done"] is None
    study.set_goal_result("partly")
    assert study.load_json(study.REPORTS_PATH, [])[0]["goal_done"] == "partly"


def test_events_are_not_counted_when_paused_or_after_end(clock):
    start()
    study.record_event("nudge")
    study.pause_session()
    study.record_event("nudge")
    assert study.stop_session()["nudges"] == 1
    study.record_event("nudge")


def test_save_failure_preserves_live_session_and_break(clock, monkeypatch):
    start()
    study.start_break()
    clock[0] += 10
    def fail(*args):
        raise OSError("disk full")
    monkeypatch.setattr(study, "save_json", fail)
    with pytest.raises(OSError):
        study.stop_session()
    assert study.session_view()["phase"] == "break"
    assert study.session_view()["break_count"] == 0


def test_clock_ignores_wall_clock_changes(clock, monkeypatch):
    start()
    monkeypatch.setattr(study.time, "time", lambda: -9999)
    clock[0] += 60
    assert study.session_view()["phase_left"] == 1440
