import phone_detection as pd
from phone_detection import FaceContext, PhoneTracker

FRAME = (640, 480)
PHONE = (400.0, 300.0, 70.0, 130.0)      # upright phone in the lower right
STEP = 1 / 7.5                           # detector runs on every 2nd frame at 15 fps


def run(tracker, hits, start=0.0, box=PHONE, score=0.7, context=None):
    """Feed one detector run per entry in `hits` (True = phone detected)."""
    t, state = start, tracker.state
    for hit in hits:
        state = tracker.update([(box, score)] if hit else [], FRAME, t, context)
        t += STEP
    return state, t


def test_steady_phone_is_seen_after_min_duration_with_confidence():
    tracker = PhoneTracker()
    state, t = run(tracker, [True] * 3)
    assert not state.seen                       # not yet: evidence must persist
    state, t = run(tracker, [True] * 10, start=t)
    assert state.seen
    assert 0.5 < state.confidence <= 1.0
    assert state.box is not None and abs(state.box[0] - PHONE[0]) < 1
    assert state.since is not None and state.since < t


def test_single_frame_false_positive_is_ignored():
    state, _ = run(PhoneTracker(), [True] + [False] * 10)
    assert not state.seen and state.confidence < 0.2


def test_brief_false_positive_burst_is_ignored():
    tracker = PhoneTracker()
    seen = False
    t = 0.0
    for hits in ([True, True], [False] * 10, [True, True], [False] * 10):
        state, t = run(tracker, hits, start=t, score=0.45)
        seen = seen or state.seen
    assert not seen


def test_flickering_but_present_phone_stays_seen_once_entered():
    tracker = PhoneTracker()
    state, t = run(tracker, [True] * 8)
    assert state.seen
    flicker = [True, False, True, False, False, True, False, True, True, False] * 3
    for hit in flicker:
        state, t = run(tracker, [hit], start=t)
        assert state.seen


def test_half_rate_flicker_still_enters():
    state, _ = run(PhoneTracker(), [True, False] * 12, score=0.8)
    assert state.seen


def test_phone_leaving_ends_after_grace_period_not_before():
    tracker = PhoneTracker()
    state, t = run(tracker, [True] * 10)
    assert state.seen
    # shortly after it disappears the grace period still holds the state
    state, t2 = run(tracker, [False] * 3, start=t)
    assert state.seen
    state, _ = run(tracker, [False] * 20, start=t2)
    assert not state.seen
    assert state.confidence == 0.0 and state.box is None and state.since is None


def test_hysteresis_enter_high_stay_low():
    tracker = PhoneTracker()
    # a weak, steady detection (score 0.3) never enters...
    state, t = run(PhoneTracker(), [True] * 20, score=0.3)
    assert not state.seen
    # ...but once a strong detection has entered, weak ones keep it alive
    state, t = run(tracker, [True] * 8, score=0.8)
    assert state.seen
    state, _ = run(tracker, [True] * 20, start=t, score=0.3)
    assert state.seen


def test_low_score_detection_below_raw_minimum_is_discarded():
    state, _ = run(PhoneTracker(), [True] * 20, score=0.1)
    assert not state.seen and state.confidence == 0.0


def test_tiny_box_is_rejected():
    state, _ = run(PhoneTracker(), [True] * 20, box=(300.0, 300.0, 12.0, 20.0), score=0.9)
    assert not state.seen


def test_huge_box_is_rejected():
    state, _ = run(PhoneTracker(), [True] * 20, box=(0.0, 0.0, 600.0, 460.0), score=0.9)
    assert not state.seen


def test_square_and_extreme_aspect_boxes_are_rejected():
    assert not run(PhoneTracker(), [True] * 20, box=(200.0, 200.0, 100.0, 100.0), score=0.9)[0].seen
    assert not run(PhoneTracker(), [True] * 20, box=(100.0, 300.0, 300.0, 30.0), score=0.9)[0].seen


def test_landscape_phone_is_accepted():
    state, _ = run(PhoneTracker(), [True] * 10, box=(300.0, 330.0, 140.0, 70.0), score=0.8)
    assert state.seen


def test_box_mostly_outside_frame_is_rejected():
    assert not pd.box_is_plausible((600.0, 400.0, 100.0, 160.0), FRAME, 0.9)
    assert pd.box_is_plausible((560.0, 340.0, 100.0, 160.0), FRAME, 0.9)


def test_context_boosts_borderline_detection():
    plain, _ = run(PhoneTracker(), [True] * 4, score=0.4, box=(400.0, 80.0, 60.0, 110.0))
    ctx = FaceContext(face_box=(250.0, 60.0, 140.0, 190.0), head_down=1.0)
    boosted, _ = run(PhoneTracker(), [True] * 4, score=0.4, box=(400.0, 80.0, 60.0, 110.0), context=ctx)
    assert boosted.confidence > plain.confidence


def test_lower_frame_box_scores_higher_than_top_of_frame():
    low, _ = run(PhoneTracker(), [True] * 4, score=0.4, box=(400.0, 330.0, 60.0, 110.0))
    high, _ = run(PhoneTracker(), [True] * 4, score=0.4, box=(400.0, 20.0, 60.0, 110.0))
    assert low.confidence > high.confidence


def test_detection_inside_face_is_penalised():
    face = (200.0, 100.0, 220.0, 280.0)
    ctx = FaceContext(face_box=face)
    inside = (260.0, 150.0, 90.0, 160.0)
    with_ctx, _ = run(PhoneTracker(), [True] * 4, score=0.5, box=inside, context=ctx)
    without, _ = run(PhoneTracker(), [True] * 4, score=0.5, box=inside)
    assert with_ctx.confidence < without.confidence


def test_unrelated_second_object_does_not_hijack_an_established_track():
    tracker = PhoneTracker()
    state, t = run(tracker, [True] * 8)
    assert state.seen
    box = state.box
    other = (30.0, 40.0, 60.0, 100.0)
    state = tracker.update([(PHONE, 0.7), (other, 0.9)], FRAME, t)
    assert state.seen
    assert abs(state.box[0] - box[0]) < 20    # still following the original phone


def test_strongest_candidate_is_used_when_no_track_exists():
    tracker = PhoneTracker()
    t = 0.0
    for _ in range(10):
        state = tracker.update([((30.0, 40.0, 60.0, 100.0), 0.4), (PHONE, 0.8)], FRAME, t)
        t += STEP
    assert state.seen and abs(state.box[0] - PHONE[0]) < 20


def test_reset_clears_everything():
    tracker = PhoneTracker()
    run(tracker, [True] * 10)
    tracker.reset()
    assert tracker.state == pd.PhoneState()


def test_stale_unconfirmed_track_is_dropped():
    tracker = PhoneTracker()
    run(tracker, [True, True])                       # builds some unconfirmed evidence
    state = tracker.update([], FRAME, 10.0)          # long silence
    assert not state.seen and state.confidence == 0.0


def test_head_down_and_face_context_helpers():
    assert pd.head_down_from_pitch(0.5, 0.5) == 0.0
    assert pd.head_down_from_pitch(0.4, 0.5) == 0.0          # looking up never counts
    assert pd.head_down_from_pitch(0.9, 0.5) == 1.0

    class P:
        def __init__(self, x, y):
            self.x, self.y = x, y

    ctx = pd.face_context_from_landmarks([P(0.4, 0.2), P(0.6, 0.6)], FRAME, 0.65, 0.5)
    assert all(abs(a - b) < 1e-6 for a, b in zip(ctx.face_box, (256.0, 96.0, 128.0, 192.0)))
    assert 0.9 < ctx.head_down <= 1.0
    assert pd.face_context_from_landmarks(None, FRAME) == FaceContext()


def test_invalid_input_is_tolerated():
    tracker = PhoneTracker()
    state = tracker.update(None, FRAME, 0.0)
    assert not state.seen
    state = tracker.update([((0, 0, 0, 0), 0.9)], (0, 0), 0.1)
    assert not state.seen


def test_engine_detect_phone_updates_shared_state_and_confidence(monkeypatch):
    from types import SimpleNamespace as NS
    import engine

    clock = {"t": 1000.0}
    monkeypatch.setattr(engine.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(engine, "camera", dict(engine.camera))
    detection = NS(bounding_box=NS(origin_x=400, origin_y=300, width=70, height=130),
                   categories=[NS(score=0.8)])
    detector = NS(detect_for_video=lambda image, ts: NS(detections=[detection]))
    tracker = PhoneTracker()
    for _ in range(12):
        state = engine.detect_phone(detector, object(), tracker, FRAME)
        clock["t"] += STEP
    assert state.seen
    assert engine.camera["phone"] is True
    assert engine.camera["phone_since"] is not None
    assert 0.5 < engine.camera["phone_confidence"] <= 1.0

    detector.detect_for_video = lambda image, ts: NS(detections=[])
    for _ in range(25):
        engine.detect_phone(detector, object(), tracker, FRAME)
        clock["t"] += STEP
    assert engine.camera["phone"] is False
    assert engine.camera["phone_since"] is None and engine.camera["phone_confidence"] == 0.0


def test_unconfirmed_phone_is_tentative_and_never_seen():
    tracker = PhoneTracker()
    # moderate scores build confidence above the tentative line but never confirm
    state, t = run(tracker, [True] * 20, score=0.3)
    assert not state.seen
    assert state.tentative and state.box is not None and state.since is None
    assert 0.3 <= state.confidence < pd.ENTER_CONFIDENCE + 0.2


def test_tentative_becomes_confident_with_a_strong_detection_and_clears_flag():
    tracker = PhoneTracker()
    state, t = run(tracker, [True] * 2, score=0.8)
    assert state.tentative and not state.seen
    state, t = run(tracker, [True] * 8, start=t, score=0.8)
    assert state.seen and not state.tentative


def test_tentative_disappears_when_detections_stop():
    tracker = PhoneTracker()
    state, t = run(tracker, [True] * 2, score=0.7)
    assert state.tentative
    state, _ = run(tracker, [False] * 6, start=t)
    assert not state.tentative and not state.seen and state.box is None


def test_weak_repeated_detections_need_a_strong_peak_to_confirm():
    # lower-frame boost makes the smoothed confidence high, but no raw score is strong
    state, _ = run(PhoneTracker(), [True] * 30, score=0.40)
    assert not state.seen


def test_single_strong_hit_does_not_confirm_without_repeated_hits():
    tracker = PhoneTracker()
    state, _ = run(tracker, [True, False, False, False, True, False, False], score=0.9)
    assert not state.seen


def test_engine_does_not_start_phone_timer_for_tentative_phone(monkeypatch):
    from types import SimpleNamespace as NS
    import engine

    clock = {"t": 1000.0}
    monkeypatch.setattr(engine.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(engine, "camera", dict(engine.camera))
    detection = NS(bounding_box=NS(origin_x=400, origin_y=300, width=70, height=130),
                   categories=[NS(score=0.3)])
    detector = NS(detect_for_video=lambda image, ts: NS(detections=[detection]))
    tracker = PhoneTracker()
    for _ in range(20):
        state = engine.detect_phone(detector, object(), tracker, FRAME)
        clock["t"] += STEP
    assert state.tentative
    assert engine.camera["phone"] is False and engine.camera["phone_since"] is None
    assert engine.camera["phone_tentative"] is True
    assert engine.camera["phone_confidence"] > 0
