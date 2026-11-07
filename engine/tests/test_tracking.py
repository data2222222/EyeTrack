"""Camera regressions with controlled landmarks and clocks, without camera/GUI imports."""

import collections
import math
import sys
from types import SimpleNamespace as Point
from unittest.mock import Mock

import pytest

import engine
import tracking


def face(gaze=.5):
    lm = [Point(x=.5, y=.5) for _ in range(478)]
    for i, x, y in ((1, .5, .5), (234, .25, .5), (454, .75, .5),
                    (10, .5, .2), (152, .5, .8), (33, .32, .4), (133, .44, .4),
                    (362, .56, .4), (263, .68, .4),
                    (468, .32 + .12 * gaze, .41), (473, .56 + .12 * gaze, .41)):
        lm[i] = Point(x=x, y=y)
    return lm


def transformed(lm, angle=0, aspect=4 / 3, scale=1, dx=0, dy=0):
    c, s = math.cos(angle), math.sin(angle)
    result = []
    for p in lm:
        x, y = (p.x - .5) * aspect * scale, (p.y - .5) * scale
        result.append(Point(x=.5 + (x * c - y * s) / aspect + dx,
                            y=.5 + x * s + y * c + dy))
    return result


def gesture_face():
    landmarks = face()
    for index, horizontal, vertical in (
            (160, .35, .382), (144, .35, .418), (158, .41, .382), (153, .41, .418),
            (385, .59, .382), (380, .59, .418), (387, .65, .382), (373, .65, .418),
            (61, .4, .65), (291, .6, .65), (13, .5, .64), (14, .5, .66)):
        landmarks[index] = Point(x=horizontal, y=vertical)
    return landmarks


@pytest.mark.parametrize("angle", [-.4, 0, .4])
@pytest.mark.parametrize("aspect", [1, 4 / 3, 16 / 9])
def test_gesture_ratios_survive_roll_distance_and_aspect(angle, aspect):
    original = gesture_face()
    changed = transformed(original, angle, aspect, .8, .08, -.04)
    assert tracking.gesture_ratios(original) == pytest.approx((.3, .3, .1))
    assert tracking.gesture_ratios(changed, aspect) == pytest.approx(tracking.gesture_ratios(original, aspect))


def test_gesture_geometry_does_not_require_valid_irises_or_other_eye():
    landmarks = gesture_face()
    landmarks[468].x = math.nan
    assert tracking.gesture_ratios(landmarks) == pytest.approx((.3, .3, .1))
    landmarks[160].x = math.nan
    left, right, mouth = tracking.gesture_ratios(landmarks)
    assert left is None
    assert (right, mouth) == pytest.approx((.3, .1))


def test_gesture_geometry_rejects_small_or_missing_landmarks():
    assert tracking.gesture_ratios([]) == (None, None, None)
    assert tracking.gesture_ratios(transformed(gesture_face(), scale=.1)) == (None, None, None)
    landmarks = gesture_face()
    landmarks[291] = landmarks[61]
    assert tracking.gesture_ratios(landmarks)[2] is None


def collect(calibration, values, start=0, fps=15):
    """Collect precisely one target, including its settling period."""
    stage = calibration.view()["stage"]
    now = start
    for _ in range(200):
        calibration.add(values, now)
        now += 1 / fps
        state = calibration.view()
        if not state["active"] or state["stage"] != stage:
            return now
    pytest.fail("stationary target never finished")


@pytest.mark.parametrize("angle", [-.45, 0, .45])
@pytest.mark.parametrize("aspect", [4 / 3, 16 / 9])
def test_gaze_and_head_ratios_survive_head_roll_distance_and_translation(angle, aspect):
    original = face(.63)
    moved = transformed(original, angle, aspect, .7, .12, -.04)
    assert tracking.head_pose(moved, aspect)[1:] == pytest.approx(tracking.head_pose(original, aspect)[1:])
    assert tracking.eye_gaze(moved, {}, aspect) == pytest.approx((.63, 0))


def test_winking_eye_is_excluded_and_inconsistent_irises_are_rejected():
    lm = face()
    lm[468].x = .32
    assert tracking.eye_gaze(lm, {"eyeBlinkRight": .8}) == pytest.approx((.5, 0))
    with pytest.raises(ValueError, match="reliably"):
        tracking.eye_gaze(lm, {})


def test_quality_rejects_tiny_clipped_or_nonfinite_faces():
    assert tracking.landmark_quality(face()) is None
    assert tracking.landmark_quality(transformed(face(), scale=.1)) == "move closer to the camera"
    assert tracking.landmark_quality(transformed(face(), dx=.3)) == "keep your whole face in view"
    lm = face()
    lm[468].x = math.nan
    assert tracking.landmark_quality(lm) is not None


@pytest.mark.parametrize("fps", [5, 15, 30])
def test_center_calibration_requires_settling_and_elapsed_time(fps):
    calibration = tracking.Calibration()
    values = (.47, .56, .52, -.03)
    done_at = collect(calibration, values, fps=fps)
    assert done_at >= 2.7
    assert not calibration.view()["active"]
    assert calibration.profile()[0] == pytest.approx(values)


def test_calibration_does_not_learn_moving_face_or_sample_across_missing_face():
    calibration = tracking.Calibration()
    for i in range(100):
        calibration.add((.5 + (i % 2) * .15, .5, .5, 0), i / 15)
    assert not calibration.view()["calibrated"]
    calibration.start()
    for i in range(30):
        calibration.add((.5, .5, .5, 0), i / 15)
    assert calibration.view()["progress"] > 0
    calibration.interrupt("no face")
    calibration.add((.7, .5, .5, 0), 10)
    assert calibration.view()["progress"] == 0
    collect(calibration, (.7, .5, .5, 0), 10.1)
    assert calibration.profile()[0][0] == pytest.approx(.7)


def test_five_point_calibration_keeps_screen_edges_in_range_and_away_outside():
    calibration = tracking.Calibration()
    calibration.start(guided=True)
    points = ((.50, .5, .5, 0), (.47, .5, .31, 0), (.53, .5, .69, 0),
              (.5, .47, .5, -.5), (.5, .53, .5, .55))
    now = 0
    for values in points:
        now = collect(calibration, values, now)
    center, bounds = calibration.profile()
    assert center == points[0]
    assert not calibration.view()["active"]
    for point in points:
        assert all(lo <= value <= hi for value, (lo, hi) in zip(point, bounds))
    assert .85 > bounds[2][1]
    assert -.8 < bounds[3][0]


def test_cancel_preserves_last_completed_profile_and_restarts_initial_center():
    calibration = tracking.Calibration()
    calibration.start(guided=True)
    calibration.cancel()
    assert calibration.view()["active"] and not calibration.view()["guided"]
    collect(calibration, (.5, .6, .52, 0))
    previous = calibration.profile()
    calibration.start(guided=True)
    collect(calibration, (.6, .6, .6, 0), 10)
    calibration.cancel()
    assert calibration.profile() == previous
    assert not calibration.view()["active"]


def test_unresponsive_gaze_does_not_claim_success_or_replace_previous_calibration():
    calibration = tracking.Calibration()
    collect(calibration, (.5, .5, .5, 0))
    previous = calibration.profile()
    calibration.start(guided=True)
    now = 10
    for _ in range(5):
        now = collect(calibration, (.6, .6, .6, .1), now)
    assert calibration.view()["quality"] == "limited"
    assert calibration.profile() == previous
    assert "unclear" in calibration.view()["message"]


def test_calibration_rejects_nonfinite_input():
    calibration = tracking.Calibration()
    calibration.add((math.nan, .5, .5, 0), 0)
    assert not calibration.view()["calibrated"]
    assert calibration.samples == []


def test_isolated_calibration_outlier_does_not_bias_the_center():
    calibration = tracking.Calibration()
    for i in range(50):
        values = (.53, .5, .55, .1) if i == 27 else (.5, .5, .5, 0)
        calibration.add(values, i / 15)
    assert calibration.profile()[0] == pytest.approx((.5, .5, .5, 0))
    assert calibration.view()["calibrated"]


def test_feature_smoothing_uses_elapsed_time_and_resets_after_a_gap():
    slow, fast = tracking.AttentionFilter(), tracking.AttentionFilter()
    for smoother, fps in ((slow, 5), (fast, 30)):
        smoother.smooth((0, 0, 0, 0), 0)
        for i in range(1, fps + 1):
            smoother.smooth((1, 1, 1, 1), i / fps)
    assert slow.values == pytest.approx(fast.values)
    assert slow.smooth((.5, .5, .5, .5), 2) == (.5, .5, .5, .5)


@pytest.mark.parametrize("fps", [5, 15, 30])
def test_attention_hysteresis_ignores_short_jitter_and_detects_sustained_away(fps):
    smoother = tracking.AttentionFilter()
    assert smoother.update(False, "away", 0)[0]
    assert smoother.update(True, "screen", .15)[0]
    away_at = None
    for i in range(fps):
        now = 1 + i / fps
        if not smoother.update(False, "away", now)[0]:
            away_at = now
            break
    assert 1.3 <= away_at <= 1.5
    assert not smoother.update(True, "screen", 2)[0]
    assert smoother.update(True, "screen", 2.2) == (True, "screen")


def test_yaw_uses_image_left_to_right_like_eye_gaze():
    lm = face()
    lm[1] = Point(x=.6, y=.5)
    mirrored = face()
    mirrored[1] = Point(x=.6, y=.5)
    mirrored[234], mirrored[454] = mirrored[454], mirrored[234]
    assert tracking.head_pose(lm)[1] == pytest.approx(.7)
    assert tracking.head_pose(mirrored)[1] == pytest.approx(.7)


def test_turned_head_trusts_the_nearer_eye_instead_of_rejecting_gaze():
    lm = face(.7)
    # The far eye is foreshortened by the head turn and its iris estimate is poor.
    lm[362], lm[263], lm[473] = Point(x=.58, y=.4), Point(x=.64, y=.4), Point(x=.645, y=.41)
    assert tracking.eye_gaze(lm, {})[0] == pytest.approx(.7)
    lm[473] = Point(x=.70, y=.41)  # far iris outside its eye
    assert tracking.eye_gaze(lm, {})[0] == pytest.approx(.7)


def test_consistent_eyes_are_weighted_toward_the_nearer_eye():
    lm = face()
    lm[362], lm[263] = Point(x=.58, y=.4), Point(x=.64, y=.4)
    lm[468], lm[473] = Point(x=.32 + .12 * .6, y=.41), Point(x=.58 + .06 * .45, y=.41)
    assert tracking.eye_gaze(lm, {})[0] == pytest.approx((.6 * .12 + .45 * .06) / .18)


def test_slightly_clipped_face_outline_is_tolerated_but_clipped_eyes_are_not():
    lm = face()
    lm[152] = Point(x=.5, y=1.02)
    assert tracking.landmark_quality(lm) is None
    lm[152] = Point(x=.5, y=1.1)
    assert tracking.landmark_quality(lm) == "keep your whole face in view"
    lm = face()
    lm[33] = Point(x=-.01, y=.4)
    assert tracking.landmark_quality(lm) == "keep your whole face in view"


def test_sitting_closer_widens_limits_but_farther_never_narrows_them():
    calibration = tracking.Calibration()
    values = (.5, .5, .5, 0)
    now = 0
    while calibration.view()["active"]:
        calibration.add(values, now, (.4, .5))
        now += 1 / 15
    assert calibration.size == pytest.approx((.4, .5))
    base = calibration.profile()[1]
    assert calibration.profile((.3, .4))[1] == base
    # Head turned (narrower) while closer (taller): the height still shows proximity.
    closer = calibration.profile((.36, .6))[1]
    for (lo, hi), (clo, chi), c in zip(base, closer, values):
        assert clo == pytest.approx(c - (c - lo) * 1.2)
        assert chi == pytest.approx(c + (hi - c) * 1.2)
    capped = calibration.profile((2, 2))[1]
    assert capped[2][1] == pytest.approx(.5 + .10 * tracking.MAX_PROXIMITY_SCALE)


def test_guided_calibration_reaches_the_real_screen_edge_beyond_the_dots():
    calibration = tracking.Calibration()
    calibration.start(guided=True)
    points = ((.50, .5, .5, 0), (.47, .5, .31, 0), (.53, .5, .69, 0),
              (.5, .47, .5, -.5), (.5, .53, .5, .55))
    now = 0
    for values in points:
        now = collect(calibration, values, now)
    center, bounds = calibration.profile()
    # Looking at the actual top-right corner needs ~19% more than the inset dots.
    corner = (.5, .5, .5 + .19 * tracking.EDGE_REACH, -.5 * tracking.EDGE_REACH)
    assert tracking.screen_attention(corner, center, bounds) == (True, "eyes on screen")
    assert not tracking.screen_attention((.5, .5, .85, 0), center, bounds)[0]


@pytest.mark.parametrize("values, expected", [
    ((.5, .5, .5, 0), (True, "eyes on screen")),
    ((.5, .62, .5, -.2), (True, "eyes on screen")),           # head down, eyes up
    ((.68, .5, .44, 0), (True, "eyes on screen")),            # head right, eyes left
    ((.5, .62, .5, .2), (False, "head tilted")),              # head and eyes down
    ((.5, .62, .5, 0), (False, "head tilted")),
    ((.5, .75, .5, -.7), (False, "head tilted")),             # beyond compensation
    ((.5, .5, .5, -.5), (False, "eyes looking up")),
    ((.5, .5, .65, -.5), (False, "eyes looking up-right")),
    ((.85, .5, .4, 0), (False, "head turned away")),          # beyond compensation
])
def test_head_and_eyes_can_compensate_each_other(values, expected):
    center = tracking.DEFAULT_CENTER
    bounds = tuple((c - t, c + t) for c, t in zip(center, tracking.TOLERANCES))
    assert tracking.screen_attention(values, center, bounds) == expected


@pytest.fixture
def runtime(monkeypatch):
    monkeypatch.setattr(engine, "camera", dict(engine.camera))
    monkeypatch.setattr(engine, "calib", tracking.Calibration())
    monkeypatch.setattr(engine, "blinks", collections.deque())
    monkeypatch.setattr(engine, "yawns", collections.deque())
    monkeypatch.setattr(engine, "expression_log", collections.deque())
    clock = [100.0]
    monkeypatch.setattr(engine.time, "time", lambda: clock[0])
    monkeypatch.setattr(engine.time, "monotonic", lambda: clock[0])
    st = {"closed_since": None, "jaw_since": None}
    expressions = collections.deque(maxlen=30)
    return clock, st, expressions


def test_blink_does_not_change_attention_or_contaminate_calibration(runtime):
    clock, st, expressions = runtime
    lm = face()
    assert engine.analyze_face(lm, {}, st, expressions)[0]
    clock[0] += .1
    assert engine.analyze_face(lm, {"eyeBlinkLeft": .9, "eyeBlinkRight": .9}, st, expressions)[0]
    clock[0] += .1
    assert engine.analyze_face(lm, {}, st, expressions)[0]
    assert len(engine.blinks) == 1
    assert not engine.calib.view()["calibrated"]


def test_prolonged_eye_closure_is_detected(runtime):
    clock, st, expressions = runtime
    closed = {"eyeBlinkLeft": .9, "eyeBlinkRight": .9}
    for _ in range(20):
        engine.analyze_face(face(), closed, st, expressions)
        clock[0] += .1
    assert not engine.camera["facing"]
    assert engine.camera["reason"] == "eyes closed"


def test_wink_uses_the_open_eye_and_is_not_counted_as_both_eyes_closed(runtime):
    _, st, expressions = runtime
    lm = face()
    lm[468].x = .8
    assert engine.analyze_face(lm, {"eyeBlinkRight": .99, "eyeBlinkLeft": .1}, st, expressions)[0]
    assert not engine.camera["eyes_closed"]
    assert engine.camera["gaze_h"] == pytest.approx(.5)


def test_face_loss_clears_expression_timers_filters_and_calibration(runtime):
    clock, st, expressions = runtime
    for _ in range(20):
        engine.analyze_face(face(), {"mouthSmileLeft": .8, "mouthSmileRight": .8}, st, expressions)
        clock[0] += .1
    assert engine.camera["expression"] == "Happy"
    assert engine.calib.view()["progress"] > 0
    engine.clear_face_tracking(st, expressions)
    assert not engine.camera["present"] and not engine.camera["facing"]
    assert engine.camera["expression"] == "-"
    assert "filter" not in st
    assert not expressions
    assert engine.calib.view()["progress"] == 0
    engine.analyze_face(face(), {}, st, expressions)
    assert engine.camera["expression"] == "Neutral"


def test_off_center_seating_is_not_looking_away(runtime):
    collect(engine.calib, (.5, .5, .5, 0))
    assert engine.attention(Point(x=.15, y=.5), .5, .5, .5, 0, False) == (True, "eyes on screen")


def test_leaning_close_to_look_at_the_top_right_edge_stays_on_screen(runtime):
    clock, st, expressions = runtime
    looking_up = {"eyeLookUpLeft": .4, "eyeLookUpRight": .4}

    def observe(lm, blendshapes, frames):
        results = []
        for _ in range(frames):
            clock[0] += 1 / 15
            results.append(engine.analyze_face(lm, blendshapes, st, expressions)[0])
        return results

    observe(face(), {}, 60)  # automatic center calibration at a normal distance
    assert engine.calib.view()["calibrated"]
    # The same eye rotation is past the edge from the calibrated distance...
    assert not observe(face(.62), looking_up, 15)[-1]
    # ...but reaches only the top-right edge when leaning in close.
    # (The first frames only settle smoothing and the return-to-screen hysteresis.)
    assert all(observe(transformed(face(.62), scale=1.4, dy=.02), looking_up, 15)[5:])


def test_bad_iris_reports_uncertainty_without_learning_it(runtime):
    _, st, expressions = runtime
    lm = face()
    lm[468].x = .8
    facing, reason = engine.analyze_face(lm, {}, st, expressions)
    assert not facing and reason == "iris not visible"
    assert engine.camera["gaze_text"] == "uncertain"
    assert not engine.calib.samples


@pytest.fixture
def camera_modules(monkeypatch, tmp_path):
    """Run the complete capture loop with injectable capture/detector failures."""
    model = tmp_path / "face.task"
    model.touch()
    monkeypatch.setattr(engine, "MODEL_PATH", str(model))
    monkeypatch.setattr(engine, "running", True)
    monkeypatch.setattr(engine, "show_preview", False)
    monkeypatch.setattr(engine, "camera", dict(engine.camera))
    monkeypatch.setattr(engine, "calib", tracking.Calibration())
    monkeypatch.setattr(engine, "preview", {"png": "old frame"})
    face_detector, phone_detector, capture = Mock(), Mock(), Mock()
    capture.read.return_value = (True, Point(shape=(480, 640, 3)))
    vision = Point(FaceLandmarkerOptions=lambda **kw: kw,
                   FaceLandmarker=Point(create_from_options=lambda options: face_detector),
                   RunningMode=Point(VIDEO="video"))
    mp_python = Point(BaseOptions=lambda **kw: kw, vision=vision)
    for name, module in {
        "cv2": Point(flip=lambda frame, mode: frame, cvtColor=lambda frame, mode: frame, COLOR_BGR2RGB=1),
        "mediapipe": Point(Image=lambda **kw: object(), ImageFormat=Point(SRGB=1)),
        "mediapipe.tasks": Point(python=mp_python), "mediapipe.tasks.python": mp_python,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(engine, "make_phone_detector", lambda *args: phone_detector)
    monkeypatch.setattr(engine, "open_camera", lambda *args: capture)
    return face_detector, phone_detector, capture


def test_camera_read_failure_clears_stale_observations_and_closes_resources(camera_modules, monkeypatch):
    face_detector, phone_detector, capture = camera_modules
    engine.camera.update(present=True, facing=True, phone=True, phone_since=1)
    capture.read.return_value = (False, None)
    monkeypatch.setattr(engine, "CAMERA_READ_TIMEOUT", 0)
    engine.camera_loop(0)
    assert "stopped delivering frames" in engine.camera["status"]
    assert not engine.camera["present"] and not engine.camera["facing"]
    assert not engine.camera["phone"] and engine.camera["phone_since"] is None
    assert engine.preview["png"] is None
    capture.release.assert_called_once()
    face_detector.close.assert_called_once()
    phone_detector.close.assert_called_once()


def test_phone_failure_does_not_stop_face_tracking_and_timestamps_increase(camera_modules, monkeypatch):
    face_detector, phone_detector, capture = camera_modules
    monkeypatch.setattr(engine.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(engine.time, "sleep", lambda duration: None)
    phone_detector.detect_for_video.side_effect = RuntimeError("phone inference failed")
    timestamps = []

    def detect(image, timestamp):
        timestamps.append(timestamp)
        if len(timestamps) == 6:
            engine.running = False
        return Point(face_landmarks=[])

    face_detector.detect_for_video.side_effect = detect
    engine.camera_loop(0)
    assert timestamps == list(range(100000, 100006))
    assert engine.camera["status"] == "stopped"
    phone_detector.detect_for_video.assert_called_once()
    capture.release.assert_called_once()


def test_camera_recovers_after_a_transient_failed_read(camera_modules, monkeypatch):
    face_detector, _, capture = camera_modules
    monkeypatch.setattr(engine.time, "sleep", lambda duration: None)
    capture.read.side_effect = [(False, None), (True, Point(shape=(480, 640, 3)))]

    def detect(*args):
        assert engine.camera["status"] == "ok"
        engine.running = False
        return Point(face_landmarks=[])

    face_detector.detect_for_video.side_effect = detect
    engine.camera_loop(0)
    assert capture.read.call_count == 2
    assert engine.camera["status"] == "stopped"


def test_attention_bucket_states():
    base = {"status": "ok", "observed_at": 10.0, "present": True, "facing": True, "looking_down": False}
    assert tracking.attention_bucket(base, "pc", 10.5) == "screen"
    assert tracking.attention_bucket(base, "pc", 12.0) == "unavailable"       # stale observation
    assert tracking.attention_bucket({**base, "status": "starting"}, "pc", 10.5) == "unavailable"
    assert tracking.attention_bucket(base, "pc", 10.5, on_phone=True) == "phone"
    assert tracking.attention_bucket({**base, "present": False}, "pc", 10.5) == "no_face"
    looking_down = {**base, "facing": False, "looking_down": True}
    assert tracking.attention_bucket(looking_down, "pc", 10.5) == "away"
    assert tracking.attention_bucket(looking_down, "both", 10.5) == "paper"
    assert tracking.attention_bucket({**base, "facing": False}, "both", 10.5) == "away"
