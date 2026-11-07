"""Quiet, in-memory blink/yawn estimates, independent of focus and session timing."""
from collections import deque
import math


MAX_SAMPLE_GAP = 0.5
BLINK_MIN_SECONDS = 0.03
BLINK_MAX_SECONDS = 0.5
BLINK_REFRACTORY_SECONDS = 0.12
EYE_REOPEN_GRACE = 0.15
YAWN_MIN_SECONDS = 1.0
MOUTH_REARM_SECONDS = 0.18
LONG_CLOSURE_SECONDS = 2.0
OBSERVATION_WINDOW = 120.0
YAWN_WINDOW = 600.0
WARMUP_SECONDS = 30.0


class WellbeingTracker:
    """Accept monotonic timestamps and existing face measurements; never emit alerts."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.blinks = 0
        self.yawns = 0
        self.recent_yawns = deque()
        self.long_closures = deque()
        self.observations = deque()
        self.interrupt()

    def interrupt(self):
        """Discard partial gestures, not session totals, on any tracking interruption."""
        self.last_sample = None
        self.sample_hz = None
        self.signals_ready = False
        self.eye_baselines = [None, None]
        self.eye_ratios = (None, None)
        self.eye_states = [False, False]
        self.mouth_baseline = None
        self.mouth_ratio = None
        self.closed_since = None
        self.last_bilateral = None
        self.last_blink = None
        self.jaw_since = None
        self.jaw_low_since = None
        self.yawn_recorded = False
        self.mouth_open = False
        self.eyes_armed = False
        self.mouth_armed = False
        self.closure_recorded = False

    def snapshot(self, now):
        while self.recent_yawns and now - self.recent_yawns[0] > YAWN_WINDOW:
            self.recent_yawns.popleft()
        while self.long_closures and now - self.long_closures[0] > OBSERVATION_WINDOW:
            self.long_closures.popleft()
        while self.observations and self.observations[0][1] <= now - OBSERVATION_WINDOW:
            self.observations.popleft()
        observed = sum(end - max(start, now - OBSERVATION_WINDOW)
                       for start, end in self.observations)
        available = (self.signals_ready and self.last_sample is not None
                     and 0 <= now - self.last_sample <= MAX_SAMPLE_GAP)
        if not available:
            state = "unavailable"
        elif (len(self.recent_yawns) >= 3 or len(self.long_closures) >= 2
              or (self.closed_since is not None and now - self.closed_since >= LONG_CLOSURE_SECONDS)):
            state = "possible"
        elif observed < WARMUP_SECONDS:
            state = "collecting"
        else:
            state = "no_clear_signs"
        return {"blinks": self.blinks, "yawns": self.yawns, "state": state,
                "observed_at": self.last_sample if self.signals_ready else None,
                "eye_ratios": self.eye_ratios, "eye_baselines": tuple(self.eye_baselines),
                "mouth_ratio": self.mouth_ratio, "mouth_open": self.mouth_open,
                "sample_hz": self.sample_hz}

    def eye_closed(self, index, score, ratio, elapsed):
        baseline = self.eye_baselines[index]
        closed = self.eye_states[index]
        if ratio is None:
            if score > .4:
                return True
            return closed and score >= .25
        if baseline is None and ratio >= .13:
            baseline = ratio
        close_level = min(.20, baseline * .68) if baseline is not None else .18
        open_level = min(.24, baseline * .82) if baseline is not None else .22
        if ratio < close_level:
            closed = True
        elif ratio > open_level:
            closed = False
        if not closed and ratio >= .13 and (baseline is None or ratio >= baseline * .8):
            weight = 1 - math.exp(-elapsed / 4)
            baseline = ratio if baseline is None else baseline + weight * (ratio - baseline)
        self.eye_baselines[index] = baseline
        return closed

    def update_blinks(self, now):
        if all(self.eye_states):
            if self.closed_since is None and self.eyes_armed:
                self.closed_since = now
            self.last_bilateral = now
            if (self.closed_since is not None and not self.closure_recorded
                    and now - self.closed_since >= LONG_CLOSURE_SECONDS):
                self.long_closures.append(now)
                self.closure_recorded = True
        elif not any(self.eye_states):
            if self.closed_since is not None:
                duration = now - self.closed_since
                if (BLINK_MIN_SECONDS <= duration <= BLINK_MAX_SECONDS
                        and (self.last_blink is None or now - self.last_blink >= BLINK_REFRACTORY_SECONDS)):
                    self.blinks += 1
                    self.last_blink = now
            self.closed_since = None
            self.closure_recorded = False
            self.eyes_armed = True
        elif self.closed_since is not None and now - self.last_bilateral > EYE_REOPEN_GRACE:
            self.closed_since = None
            self.closure_recorded = False
            self.eyes_armed = False

    def update_yawns(self, now, jaw, ratio, elapsed):
        if ratio is None:
            opened, shut = jaw > .3, jaw < .16
        else:
            baseline = self.mouth_baseline
            if baseline is None and ratio < .35:
                baseline = ratio
            opened = ratio > max(.40, (baseline or 0) + .25)
            shut = ratio < max(.22, (baseline or 0) + .10)
            if self.jaw_since is None and shut:
                weight = 1 - math.exp(-elapsed / 4)
                baseline = ratio if baseline is None else baseline + weight * (ratio - baseline)
            self.mouth_baseline = baseline
        if self.jaw_low_since is not None and now - self.jaw_low_since >= MOUTH_REARM_SECONDS:
            self.jaw_since = None
            self.yawn_recorded = False
            self.mouth_armed = True
        self.mouth_open = opened or (self.jaw_since is not None and not shut)
        if self.mouth_open and self.mouth_armed:
            if self.jaw_since is None:
                self.jaw_since = now
            self.jaw_low_since = None
            if not self.yawn_recorded and now - self.jaw_since >= YAWN_MIN_SECONDS:
                self.yawns += 1
                self.recent_yawns.append(now)
                self.yawn_recorded = True
        elif shut:
            if self.jaw_low_since is None:
                self.jaw_low_since = now
            if self.jaw_since is None:
                self.mouth_armed = True

    def update(self, now, blendshapes, reliable=True, geometry=None):
        names = ("eyeBlinkLeft", "eyeBlinkRight", "jawOpen")
        scores = [blendshapes.get(name) for name in names]
        scores = [score if isinstance(score, (float, int)) and math.isfinite(score)
                  and 0 <= score <= 1 else None for score in scores]
        if (not reliable or (geometry is None and None in scores)
                or (geometry is not None and all(ratio is None for ratio in geometry))):
            self.interrupt()
            return self.snapshot(now)
        elapsed = 0.0
        if self.last_sample is not None:
            elapsed = now - self.last_sample
            if not 0 < elapsed <= MAX_SAMPLE_GAP:
                self.interrupt()
                elapsed = 0.0
            else:
                self.sample_hz = (1 / elapsed if self.sample_hz is None
                                  else .8 * self.sample_hz + .2 / elapsed)
        left_ratio, right_ratio, mouth_ratio = geometry if geometry is not None else (None, None, None)
        eyes_ready = geometry is None or (left_ratio is not None and right_ratio is not None)
        mouth_ready = geometry is None or mouth_ratio is not None
        if elapsed and eyes_ready and mouth_ready and self.signals_ready:
            if self.observations and self.observations[-1][1] == self.last_sample:
                start, _ = self.observations.pop()
                self.observations.append((start, now))
            else:
                self.observations.append((self.last_sample, now))
        self.last_sample = now
        self.signals_ready = eyes_ready and mouth_ready
        self.eye_ratios = (left_ratio, right_ratio)
        self.mouth_ratio = mouth_ratio
        left_eye, right_eye, jaw = scores
        if eyes_ready:
            self.eye_states = [self.eye_closed(0, left_eye, left_ratio, elapsed),
                               self.eye_closed(1, right_eye, right_ratio, elapsed)]
            self.update_blinks(now)
        else:
            self.closed_since = None
            self.closure_recorded = False
            self.eyes_armed = False
        if mouth_ready:
            self.update_yawns(now, jaw, mouth_ratio, elapsed)
        else:
            self.jaw_since = self.jaw_low_since = None
            self.yawn_recorded = self.mouth_armed = self.mouth_open = False
        return self.snapshot(now)
