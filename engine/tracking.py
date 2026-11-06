"""Camera geometry and calibration; no GUI, camera, or ML dependencies."""

import math
import statistics
import threading


DEFAULT_CENTER = (0.5, 0.5, 0.5, 0.0)
TOLERANCES = (0.15, 0.10, 0.10, 0.35)
TARGETS = (("center", .5, .5), ("left", .08, .5), ("right", .92, .5),
           ("up", .5, .08), ("down", .5, .92))
# Edge dots sit 8% inside the screen; scale what they measured out to the real edge.
EDGE_REACH = .5 / .42
# Leaning closer makes the screen span a wider angle, so the same edge needs more
# head/eye rotation. Bounds widen with apparent face size (never narrow) up to this.
MAX_PROXIMITY_SCALE = 1.5
# Head and eyes may each pass their own limit when the other turns back toward the
# screen (e.g. head tilted down while the eyes look up), but not beyond this.
MAX_COMPENSATED = 2.0
OUTLINE = (10, 152, 234, 454)


def projection(point, start, end, aspect=1.0):
    """Position along a landmark axis, accounting for the frame's aspect ratio."""
    dx, dy = (end.x - start.x) * aspect, end.y - start.y
    length2 = dx * dx + dy * dy
    if length2 < 1e-8:
        raise ValueError("landmark axis too small")
    return (((point.x - start.x) * aspect) * dx + (point.y - start.y) * dy) / length2


def head_pose(lm, aspect=1.0):
    """Nose position across the cheeks (yaw) and from forehead to chin (pitch).

    Yaw is measured left-to-right in the image, like eye_gaze, so that head and eye
    values increase in the same direction and can compensate for each other.
    """
    nose = lm[1]
    left, right = (234, 454) if lm[234].x <= lm[454].x else (454, 234)
    return (nose, projection(nose, lm[left], lm[right], aspect),
            projection(nose, lm[10], lm[152], aspect))


def face_size(lm, aspect=1.0):
    """Apparent face width and height; both grow as the user moves closer."""
    def distance(a, b):
        return math.hypot((lm[b].x - lm[a].x) * aspect, lm[b].y - lm[a].y)
    return distance(234, 454), distance(10, 152)


def eye_gaze(lm, bs, aspect=1.0):
    """Project each iris onto its eye axis so head roll doesn't look like eye motion.

    A wink/occluded eye is excluded. Reject inconsistent irises rather than averaging
    a bad eye into a convincing looking estimate, except when the head is turned so
    far that one eye is clearly foreshortened: then the nearer eye is trusted.
    """
    eyes = []
    # MediaPipe uses anatomical sides: iris 468 belongs to eyeBlinkRight.
    for iris, a, b, side in ((468, 33, 133, "Right"), (473, 362, 263, "Left")):
        if bs.get("eyeBlink" + side, 0) > .5:
            continue
        if lm[a].x > lm[b].x:
            a, b = b, a
        width = math.hypot((lm[b].x - lm[a].x) * aspect, lm[b].y - lm[a].y)
        eyes.append((projection(lm[iris], lm[a], lm[b], aspect), width))
    if not eyes:
        raise ValueError("eyes closed")
    if len(eyes) == 2:
        near, far = sorted(eyes, key=lambda eye: eye[1], reverse=True)
        foreshortened = near[1] > far[1] * 1.25
        if foreshortened and (not -.1 <= far[0] <= 1.1 or abs(near[0] - far[0]) > .3):
            eyes = [near]
    for value, _ in eyes:
        if not -.1 <= value <= 1.1:
            raise ValueError("iris not visible")
    if len(eyes) == 2 and abs(eyes[0][0] - eyes[1][0]) > .3:
        raise ValueError("eyes not tracked reliably")
    # The wider (nearer) eye is measured with more pixels; equal weights when frontal.
    value = sum(v * w for v, w in eyes) / sum(w for _, w in eyes)
    down = (bs.get("eyeLookDownLeft", 0) + bs.get("eyeLookDownRight", 0)) / 2
    up = (bs.get("eyeLookUpLeft", 0) + bs.get("eyeLookUpRight", 0)) / 2
    return value, down - up


def landmark_quality(lm, aspect=1.0):
    if len(lm) < 478:
        return "iris landmarks missing"
    for i in (1, 10, 152, 234, 454, 33, 133, 362, 263, 468, 473):
        p = lm[i]
        # Sitting close can clip the forehead/chin/cheek edge slightly. The model
        # still places those outline points reliably; eyes and nose must be in view.
        edge = -.04 if i in OUTLINE else .01
        if not (math.isfinite(p.x) and math.isfinite(p.y) and edge < p.x < 1 - edge
                and edge < p.y < 1 - edge):
            return "keep your whole face in view"
    width = math.hypot((lm[454].x - lm[234].x) * aspect, lm[454].y - lm[234].y)
    if width < .16:
        return "move closer to the camera"
    return None


class Calibration:
    """Stable center calibration, optionally extended to five screen targets.

    The last completed profile stays usable while a replacement is collected.
    All access is locked because the UI changes targets while the camera samples.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self.center = None
        self.bounds = None
        self.size = None  # face (width, height) during the center calibration
        self.quality = "pending"
        self.generation = 0
        self.start()

    def start(self, guided=False):
        with self._lock:
            self.guided = guided
            self.active = True
            self.stage = 0
            self.samples = []
            self.points = []
            self.candidate_size = None
            self.ready_at = None
            self.progress = 0.0
            self.message = "Look at the dot" if guided else "Look at screen center and hold still"
            self.generation += 1

    def cancel(self):
        with self._lock:
            if self.center is None:
                self.start()
            else:
                self.active = False
                self.samples = []
                self.message = "Using previous calibration"
            self.generation += 1

    def view(self):
        with self._lock:
            return dict(active=self.active, guided=self.guided, stage=self.stage,
                        target=TARGETS[min(self.stage, len(TARGETS) - 1)],
                        progress=self.progress, message=self.message,
                        calibrated=self.center is not None, quality=self.quality,
                        generation=self.generation)

    def profile(self, size=None):
        """Center and per-feature bounds, widened when the face is closer than calibrated."""
        with self._lock:
            center = self.center or DEFAULT_CENTER
            bounds = self.bounds or tuple((v - t, v + t) for v, t in zip(center, TOLERANCES))
            reference = self.size
        scale = proximity_scale(size, reference)
        if scale > 1:
            bounds = tuple((c - (c - lo) * scale, c + (hi - c) * scale)
                           for c, (lo, hi) in zip(center, bounds))
        return center, bounds

    def interrupt(self, message):
        with self._lock:
            if self.active:
                self.samples = []
                self.ready_at = None
                self.progress = 0.0
                self.message = message

    def add(self, values, now, size=None):
        with self._lock:
            if not self.active:
                return
            if not all(math.isfinite(v) for v in values):
                self.interrupt("Tracking unclear; face the camera")
                return
            if self.samples and now - self.samples[-1][0] > .4:
                self.interrupt("Tracking interrupted; hold still")
            if self.ready_at is None:
                self.ready_at = now + .7  # time to find the new target before sampling
            if now < self.ready_at:
                self.message = "Look at the dot" if self.guided else "Look at screen center"
                return
            self.samples.append((now, values, size))
            columns = list(zip(*(s[1] for s in self.samples)))
            # Ignore isolated outliers, but never calibrate across a head/eye movement.
            stability = (.045, .045, .045, .16)
            for column, limit in zip(columns, stability):
                ordered = sorted(column)
                low, high = ordered[int((len(ordered) - 1) * .1)], ordered[int((len(ordered) - 1) * .9)]
                if high - low > limit or abs(column[-1] - statistics.median(column)) > limit * 2:
                    self.interrupt("Hold still on the target")
                    return
            duration = 1.2 if self.guided else 2.0
            elapsed = now - self.samples[0][0]
            self.progress = min(1.0, elapsed / duration, len(self.samples) / 12)
            self.message = "Hold still on the dot" if self.guided else "Hold still at screen center"
            if self.progress < 1:
                return
            self.points.append(tuple(statistics.median(c) for c in columns))
            if self.stage == 0:
                sizes = [s[2] for s in self.samples if s[2] is not None]
                self.candidate_size = (tuple(statistics.median(c) for c in zip(*sizes))
                                       if sizes else None)
            self.samples = []
            self.stage += 1
            self.ready_at = None
            self.progress = 0.0
            if self.guided and self.stage < len(TARGETS):
                return
            usable_screen = True
            if self.guided:
                left, right, up, down = self.points[1:]
                horizontal = abs(left[2] - right[2]) >= .035 or abs(left[0] - right[0]) >= .06
                vertical = abs(up[3] - down[3]) >= .10 or abs(up[1] - down[1]) >= .05
                usable_screen = horizontal and vertical
            candidate_center = self.points[0]
            margins = (.04, .04, .025, .08)
            # Screen edge samples extend, but never shrink, the neutral comfort zone.
            if usable_screen:
                self.center = candidate_center
                self.size = self.candidate_size
                edges = [tuple(c + (v - c) * EDGE_REACH for c, v in zip(self.center, p))
                         for p in self.points[1:]] or [self.center]
                self.bounds = tuple((min(c - t, min(p[i] for p in edges) - m),
                                     max(c + t, max(p[i] for p in edges) + m))
                                    for i, (c, t, m) in enumerate(zip(self.center, TOLERANCES, margins)))
            elif self.center is None:
                self.center = candidate_center
                self.size = self.candidate_size
                self.bounds = tuple((v - t, v + t) for v, t in zip(self.center, TOLERANCES))
            self.active = False
            self.progress = 1.0
            self.quality = "screen" if self.guided and usable_screen else ("limited" if self.guided else "center")
            if not usable_screen:
                self.message = "Eye movement was unclear. Improve lighting and try Calibrate screen again."
            else:
                self.message = "Screen calibrated" if self.guided else "Center calibrated; use Calibrate screen for edges"
            self.generation += 1


def proximity_scale(size, reference):
    """How much wider the screen looks than at calibration (1 when unknown or farther)."""
    if not size or not reference:
        return 1.0
    ratios = [s / r for s, r in zip(size, reference) if r > 1e-6 and math.isfinite(s)]
    # A head turn shortens the width and a nod the height; the larger ratio is robust.
    return min(MAX_PROXIMITY_SCALE, max([1.0] + ratios))


def normalized(value, center, bounds):
    """Signed offset from center: -1 and 1 are the calibrated lower and upper limits."""
    low, high = bounds
    span = high - center if value >= center else center - low
    return (value - center) / max(span, 1e-6)


def _axis_on_screen(head, eyes):
    if abs(head) <= 1 and abs(eyes) <= 1:
        return True
    # Turning the head one way and the eyes the other keeps the gaze on the screen.
    return (head * eyes < 0 and abs(head) <= MAX_COMPENSATED
            and abs(eyes) <= MAX_COMPENSATED and abs(head + eyes) <= 1)


def screen_attention(values, center, bounds):
    """(looking, reason) for smoothed (yaw, pitch, gaze_h, gaze_v) values."""
    yaw, pitch, horizontal, vertical = (normalized(v, c, b) for v, c, b in zip(values, center, bounds))
    across = _axis_on_screen(yaw, horizontal)
    along = _axis_on_screen(pitch, vertical)
    if not across and abs(yaw) > 1:
        return False, "head turned away"
    if not along and abs(pitch) > 1:
        return False, "head tilted"
    parts = []
    if not along:
        parts.append("down" if vertical > 0 else "up")
    if not across:
        parts.append("right" if horizontal > 0 else "left")
    if parts:
        return False, "eyes looking " + "-".join(parts)
    return True, "eyes on screen"


class AttentionFilter:
    """Time-based feature smoothing and hysteresis, independent of camera FPS."""

    def __init__(self):
        self.values = None
        self.last_time = None
        self.facing = True
        self.reason = "eyes on screen"
        self.pending = None
        self.pending_since = None

    def smooth(self, values, now):
        dt = now - self.last_time if self.last_time is not None else 1
        if self.values is None or dt > .5:
            self.values = values
        else:
            alpha = 1 - math.exp(-max(0, dt) / .10)
            self.values = tuple(old + alpha * (new - old) for old, new in zip(self.values, values))
        self.last_time = now
        return self.values

    def update(self, looking, reason, now):
        if looking == self.facing:
            self.pending = None
            self.reason = reason
        else:
            if looking != self.pending:
                self.pending = looking
                self.pending_since = now
            if now - self.pending_since >= (.18 if looking else .30):
                self.facing = looking
                self.reason = reason
                self.pending = None
        return self.facing, self.reason


def attention_bucket(camera, mode, now, on_phone=False, fresh_seconds=1.0):
    """Where the user's attention appears to be, from one camera snapshot.

    "screen", "paper" (looking down in paper mode), "away", "no_face", "phone" or
    "unavailable". An estimate, not proof of what the person is doing.
    """
    observed = camera.get("observed_at")
    if camera.get("status") != "ok" or observed is None or now - observed > fresh_seconds:
        return "unavailable"
    if on_phone:
        return "phone"
    if not camera.get("present"):
        return "no_face"
    if camera.get("facing"):
        return "screen"
    if mode == "both" and camera.get("looking_down"):
        return "paper"
    return "away"
