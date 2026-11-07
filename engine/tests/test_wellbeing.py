"""Optional wellbeing signals use synthetic scores and monotonic time, not hardware."""
import collections
import math

import pytest

import engine
from wellbeing import WellbeingTracker


def scores(eyes=0.0, jaw=0.0):
    return {"eyeBlinkLeft": eyes, "eyeBlinkRight": eyes, "jawOpen": jaw}


def observe(tracker, start, duration, eyes=0.0, jaw=0.0, fps=20):
    for frame in range(round(duration * fps) + 1):
        result = tracker.update(start + frame / fps, scores(eyes, jaw))
    return result


@pytest.mark.parametrize("fps", [10, 15, 30])
def test_blink_count_is_time_based_and_counts_once_on_reopening(fps):
    tracker = WellbeingTracker()
    tracker.update(0, scores())
    closed = observe(tracker, .1, .2, eyes=.9, fps=fps)
    assert closed["blinks"] == 0
    assert tracker.update(.4, scores())["blinks"] == 1
    assert tracker.update(.5, scores())["blinks"] == 1


@pytest.mark.parametrize("duration,expected", [(0.005, 0), (0.2, 1), (0.7, 0), (2.5, 0)])
def test_blink_duration_limits(duration, expected):
    tracker = WellbeingTracker()
    tracker.update(0, scores())
    observe(tracker, .1, duration, eyes=.9)
    assert tracker.update(.1 + duration + .01, scores())["blinks"] == expected


def test_winks_do_not_count_as_blinks_or_sleepiness():
    tracker = WellbeingTracker()
    tracker.update(0, scores())
    for frame in range(1, 61):
        tracker.update(frame / 20, {"eyeBlinkLeft": .9, "eyeBlinkRight": 0.0, "jawOpen": 0.0})
    result = tracker.update(3.1, scores())
    assert result["blinks"] == 0
    assert result["state"] == "collecting"


def test_threshold_noise_does_not_duplicate_a_gesture():
    tracker = WellbeingTracker()
    tracker.update(0, scores())
    tracker.update(.1, scores(.9, .9))
    for frame in range(2, 6):
        tracker.update(frame / 10, scores(.45, .45))
    assert tracker.update(.55, scores())["blinks"] == 1
    tracker.update(.6, scores(0, .9))
    observe(tracker, .7, 1.0, jaw=.45)
    assert tracker.update(1.9, scores())["yawns"] == 1


@pytest.mark.parametrize("duration,expected", [(.3, 0), (1.5, 1), (9.0, 1)])
def test_yawns_count_once_while_still_open(duration, expected):
    tracker = WellbeingTracker()
    tracker.update(0, scores())
    result = observe(tracker, .1, duration, jaw=.9)
    assert result["yawns"] == expected
    assert tracker.update(duration + .2, scores())["yawns"] == expected
    assert tracker.update(duration + .3, scores())["yawns"] == expected


def test_starting_mid_gesture_does_not_count_partial_events():
    tracker = WellbeingTracker()
    observe(tracker, 0, 2, eyes=.9, jaw=.9)
    result = tracker.update(2.1, scores())
    assert result["blinks"] == result["yawns"] == 0
    assert not tracker.long_closures


@pytest.mark.parametrize("interruption", ["missing", "invalid", "gap", "backwards"])
def test_interruptions_discard_inflight_gestures(interruption):
    tracker = WellbeingTracker()
    tracker.update(0, scores())
    observe(tracker, .1, .7, eyes=.9, jaw=.9)
    finish = 1.0
    if interruption == "missing":
        tracker.update(.9, scores(), reliable=False)
    elif interruption == "invalid":
        tracker.update(.9, {})
    elif interruption == "backwards":
        tracker.update(.6, scores(.9, .9))
    else:
        tracker.update(3.0, scores(.9, .9))
        finish = 3.1
    result = tracker.update(finish, scores())
    assert result["blinks"] == result["yawns"] == 0


@pytest.mark.parametrize("value", [None, math.nan, math.inf, -0.1, 1.1, "0.9"])
def test_unusable_scores_are_unavailable(value):
    tracker = WellbeingTracker()
    tracker.update(0, scores())
    result = tracker.update(.1, dict(scores(), jawOpen=value))
    assert result["state"] == "unavailable"
    assert result["observed_at"] is None


def test_warmup_requires_observed_time_not_elapsed_time():
    tracker = WellbeingTracker()
    assert tracker.snapshot(0)["state"] == "unavailable"
    assert observe(tracker, 0, 29)["state"] == "collecting"
    assert observe(tracker, 29.1, 1)["state"] == "no_clear_signs"
    assert tracker.snapshot(31)["state"] == "unavailable"
    assert tracker.update(1000, scores())["state"] == "collecting"
    assert len(tracker.observations) == 0


def test_single_long_closure_is_not_a_blink_and_only_records_once():
    tracker = WellbeingTracker()
    tracker.update(0, scores())
    assert observe(tracker, .1, 4, eyes=.9)["state"] == "possible"
    assert len(tracker.long_closures) == 1
    result = tracker.update(4.2, scores())
    assert result["blinks"] == 0
    assert result["state"] == "collecting"
    assert observe(tracker, 4.3, 2.2, eyes=.9)["state"] == "possible"
    assert tracker.update(6.6, scores())["state"] == "possible"
    assert observe(tracker, 6.7, 122)["state"] == "no_clear_signs"


def test_repeated_yawns_raise_only_a_temporary_cue_not_a_score():
    tracker = WellbeingTracker()
    tracker.update(0, scores())
    for start in (.1, 2.1, 4.1):
        observe(tracker, start, 1.5, jaw=.9)
        result = tracker.update(start + 1.6, scores())
    assert result["state"] == "possible"
    assert result["yawns"] == 3
    result = observe(tracker, 5.8, 607)
    assert result["state"] == "no_clear_signs"
    assert result["yawns"] == 3
    assert not tracker.recent_yawns
    assert len(tracker.observations) == 1


def test_interrupt_preserves_counts_but_new_session_resets_them():
    tracker = WellbeingTracker()
    tracker.update(0, scores())
    tracker.update(.1, scores(.9))
    tracker.update(.2, scores())
    tracker.interrupt()
    assert tracker.snapshot(.3)["blinks"] == 1
    assert tracker.snapshot(.3)["state"] == "unavailable"
    tracker.reset()
    assert tracker.snapshot(.3)["blinks"] == 0
    assert not tracker.observations


@pytest.fixture
def isolated_engine(monkeypatch):
    monkeypatch.setattr(engine, "wellbeing_tracker", WellbeingTracker())
    monkeypatch.setattr(engine, "camera", dict(engine.camera))
    monkeypatch.setattr(engine, "events", [])
    return engine


def test_face_analysis_feeds_optional_tracker_without_emitting_events(isolated_engine, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(engine.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(engine.tracking, "landmark_quality", lambda *args: None)
    monkeypatch.setattr(engine.tracking, "gesture_ratios",
                        lambda *args: (.07, .07, .05) if clock[0] == .1 else (.3, .3, .05))
    monkeypatch.setattr(engine.tracking, "face_size", lambda *args: (.5, .5))
    monkeypatch.setattr(engine, "head_pose", lambda *args: (None, .5, .5))
    monkeypatch.setattr(engine, "eye_gaze", lambda *args: (.5, 0.0))
    monkeypatch.setattr(engine, "calib", engine.tracking.Calibration())
    monkeypatch.setattr(engine, "blinks", collections.deque())
    monkeypatch.setattr(engine, "expression_log", collections.deque())
    state = {"closed_since": None, "jaw_since": None}
    votes = collections.deque(maxlen=30)
    for stamp, eyes in ((0, 0), (.1, .9), (.2, 0)):
        clock[0] = stamp
        engine.analyze_face([], scores(eyes), state, votes)
    assert engine.camera["wellbeing"]["blinks"] == 1
    assert engine.events == []
    monkeypatch.setattr(engine.tracking, "landmark_quality", lambda *args: "unreliable")
    clock[0] = .3
    engine.analyze_face([], scores(), state, votes)
    assert engine.camera["wellbeing"]["state"] != "unavailable"
    monkeypatch.setattr(engine.tracking, "gesture_ratios", lambda *args: (None, None, None))
    clock[0] = .4
    engine.analyze_face([], scores(), state, votes)
    assert engine.camera["wellbeing"]["state"] == "unavailable"
    assert engine.camera["wellbeing"]["blinks"] == 1


def test_missing_face_and_camera_stop_clear_partial_events(isolated_engine):
    tracker = engine.wellbeing_tracker
    tracker.update(0, scores())
    tracker.update(.1, scores(.9, .9))
    engine.clear_face_tracking({}, collections.deque())
    assert engine.camera["wellbeing"]["state"] == "unavailable"
    assert tracker.closed_since is tracker.jaw_since is None
    controller = engine.CameraController(simulated=True)
    controller.start()
    tracker.update(1, scores())
    tracker.update(1.1, scores(.9))
    tracker.update(1.2, scores())
    controller.stop()
    assert engine.camera["wellbeing"]["blinks"] == 1
    assert engine.camera["wellbeing"]["state"] == "unavailable"
    engine.reset_wellbeing()
    assert engine.camera["wellbeing"]["blinks"] == 0


@pytest.mark.parametrize("left_open,right_open", [(.18, .22), (.3, .32), (.25, .35)])
@pytest.mark.parametrize("neutral_score", [.08, .35, .7])
def test_geometry_counts_blinks_with_weak_asymmetric_model_scores(left_open, right_open, neutral_score):
    tracker = WellbeingTracker()
    neutral = {"eyeBlinkLeft": neutral_score, "eyeBlinkRight": neutral_score, "jawOpen": .03}
    tracker.update(0, neutral, geometry=(left_open, right_open, .05))
    weak_blink = {"eyeBlinkLeft": .24, "eyeBlinkRight": .43, "jawOpen": .03}
    tracker.update(.1, weak_blink, geometry=(left_open * .3, right_open * .3, .05))
    result = tracker.update(.2, neutral, geometry=(left_open, right_open, .05))
    assert result["blinks"] == 1
    assert result["eye_baselines"] == pytest.approx((left_open, right_open))


@pytest.mark.parametrize("fps", [10, 15, 30])
def test_geometry_detects_a_single_sample_blink_without_blendshapes(fps):
    tracker = WellbeingTracker()
    tracker.update(0, {}, geometry=(.3, .3, .05))
    tracker.update(1 / fps, {}, geometry=(.07, .08, .05))
    assert tracker.update(2 / fps, {}, geometry=(.3, .3, .05))["blinks"] == 1


def test_geometry_rejects_spurious_model_blinks_and_accepts_staggered_reopening():
    tracker = WellbeingTracker()
    tracker.update(0, scores(), geometry=(.3, .3, .05))
    tracker.update(.1, scores(.9), geometry=(.3, .3, .05))
    assert tracker.update(.2, scores(), geometry=(.3, .3, .05))["blinks"] == 0
    tracker.update(.3, scores(.4), geometry=(.07, .3, .05))
    tracker.update(.35, scores(.4), geometry=(.07, .07, .05))
    tracker.update(.4, scores(.4), geometry=(.3, .07, .05))
    assert tracker.update(.45, scores(), geometry=(.3, .3, .05))["blinks"] == 1


def test_a_wink_after_bilateral_closure_does_not_extend_into_a_blink():
    tracker = WellbeingTracker()
    tracker.update(0, {}, geometry=(.3, .3, .05))
    tracker.update(.1, {}, geometry=(.07, .07, .05))
    tracker.update(.2, {}, geometry=(.3, .07, .05))
    tracker.update(.3, {}, geometry=(.3, .07, .05))
    assert tracker.update(.4, {}, geometry=(.3, .3, .05))["blinks"] == 0


def test_blink_refractory_period_rejects_rapid_threshold_chatter():
    tracker = WellbeingTracker()
    for stamp, ratio in ((0, .3), (.1, .07), (.15, .3), (.18, .07), (.22, .3), (.4, .07), (.45, .3)):
        result = tracker.update(stamp, {}, geometry=(ratio, ratio, .05))
    assert result["blinks"] == 2


def test_yawn_uses_mouth_geometry_and_counts_before_the_mouth_closes():
    tracker = WellbeingTracker()
    tracker.update(0, scores(jaw=.04), geometry=(.3, .3, .06))
    for frame in range(1, 45):
        result = tracker.update(frame / 15, scores(eyes=.2, jaw=.18), geometry=(.3, .3, .6))
    assert result["yawns"] == 1
    assert result["mouth_open"]
    assert result["sample_hz"] == pytest.approx(15)
    for frame in range(45, 51):
        tracker.update(frame / 15, scores(), geometry=(.3, .3, .06))
    for frame in range(51, 72):
        result = tracker.update(frame / 15, scores(jaw=.18), geometry=(.3, .3, .6))
    assert result["yawns"] == 2


def test_relaxed_mouth_reference_is_not_blocked_by_a_high_jaw_score():
    tracker = WellbeingTracker()
    tracker.update(0, scores(jaw=.4), geometry=(.3, .3, .25))
    for frame in range(1, 25):
        result = tracker.update(frame / 20, scores(jaw=.2), geometry=(.3, .3, .65))
    assert result["yawns"] == 1


def test_talking_and_brief_mouth_openings_do_not_count_as_yawns():
    tracker = WellbeingTracker()
    for frame in range(101):
        ratio = .6 if frame % 12 < 5 and frame > 0 else .05
        result = tracker.update(frame / 20, scores(jaw=.25), geometry=(.3, .3, ratio))
    assert result["yawns"] == 0


def test_a_single_mouth_score_dropout_does_not_discard_a_yawn():
    tracker = WellbeingTracker()
    tracker.update(0, {}, geometry=(.3, .3, .05))
    for frame in range(1, 30):
        ratio = .05 if frame == 10 else .6
        result = tracker.update(frame / 20, {}, geometry=(.3, .3, ratio))
    assert result["yawns"] == 1


def test_unreliable_eyes_do_not_discard_valid_mouth_observations():
    tracker = WellbeingTracker()
    tracker.update(0, {}, geometry=(.3, .3, .05))
    for frame in range(1, 30):
        result = tracker.update(frame / 20, {}, geometry=(None, None, .6))
    assert result["yawns"] == 1
    assert result["state"] == "unavailable"
    assert result["observed_at"] is None
    assert tracker.update(1.5, {}, geometry=(.3, .3, .6))["yawns"] == 1


def test_yawn_counts_through_gaze_estimation_errors(isolated_engine, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(engine.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(engine.tracking, "landmark_quality", lambda *args: None)
    monkeypatch.setattr(engine.tracking, "gesture_ratios",
                        lambda *args: (.3, .3, .6 if clock[0] else .05))
    monkeypatch.setattr(engine.tracking, "face_size", lambda *args: (.5, .5))
    monkeypatch.setattr(engine, "head_pose", lambda *args: (None, .5, .5))
    monkeypatch.setattr(engine, "calib", engine.tracking.Calibration())
    monkeypatch.setattr(engine, "expression_log", collections.deque())

    def uncertain_gaze(*args):
        raise ValueError("gaze unavailable")

    monkeypatch.setattr(engine, "eye_gaze", uncertain_gaze)
    state = {"closed_since": None, "jaw_since": None}
    votes = collections.deque(maxlen=30)
    for frame in range(24):
        clock[0] = frame / 15
        facing, reason = engine.analyze_face([], scores(jaw=.18), state, votes)
    assert not facing and reason == "gaze unavailable"
    assert engine.camera["wellbeing"]["yawns"] == 1
    assert engine.events == []
