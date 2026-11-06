"""Phone-in-hand tracking on top of raw object-detector output.

Pure logic: no camera, OpenCV, MediaPipe, or GUI imports, so it can be unit tested with
synthetic detections and fake timestamps. A camera-based phone estimate is a hint, not
proof; the tracker therefore trades a little latency for stability:

* sanity filters drop boxes that are too small, too large, or the wrong shape;
* a detection is associated with the tracked box by IoU, so a second object elsewhere in
  the frame does not keep a stale track alive;
* confidence is an exponential moving average of evidence (0 when the detector is silent),
  boosted a little by context (low in the frame, near the face, head pitched down);
* hysteresis: the smoothed confidence must reach ENTER_CONFIDENCE for MIN_ENTER_SECONDS to
  report a phone, and then it is kept until it falls below EXIT_CONFIDENCE AND the phone
  has not been seen for GRACE_SECONDS.
"""

from dataclasses import dataclass
from typing import Optional, Tuple

Box = Tuple[float, float, float, float]  # x, y, w, h in pixels

# --- raw detector (used by engine.make_phone_detector) ---
RAW_SCORE_THRESHOLD = 0.25     # lenient: the tracker does the real filtering
DETECT_EVERY_N_FRAMES = 2

# --- sanity filters (fractions of the frame) ---
MIN_AREA_FRACTION = 0.004      # smaller than ~6% x 6% of the frame: a speck, not a phone
MAX_AREA_FRACTION = 0.45       # bigger than this is a monitor/notebook, not a hand-held phone
MIN_ASPECT = 0.30              # short side / long side; phones are ~0.45-0.6, allow tilt/foreshortening
MAX_ASPECT = 0.95              # a square-ish box is usually a wallet, coaster or sticky note
MIN_RAW_SCORE = 0.25

# --- tracking / hysteresis ---
ASSOCIATION_IOU = 0.15         # new detection continues the track if it overlaps this much
EMA_ALPHA = 0.5                # weight of the newest observation
ENTER_CONFIDENCE = 0.50        # smoothed confidence needed to start
EXIT_CONFIDENCE = 0.25         # smoothed confidence below which it may end
MIN_ENTER_SECONDS = 0.5        # evidence must persist this long before "seen"
GRACE_SECONDS = 1.5            # keep reporting a phone this long after the last detection
STALE_TRACK_SECONDS = 3.0      # drop an unassociated, unconfirmed track after this long

# --- context boosts (added to the evidence of a detection, capped at 1) ---
LOWER_FRAME_BOOST = 0.10       # box center in the lower 45% of the frame
NEAR_FACE_BOOST = 0.08         # box within ~1.5 face-heights of the face
HEAD_DOWN_BOOST = 0.10         # scaled by how far the head is pitched down (0..1)
OVERLAP_FACE_PENALTY = 0.15    # box mostly inside the face box: likely a face mis-detection
EXTERNAL_CONTEXT_MAX_BOOST = 0.25


@dataclass(frozen=True)
class FaceContext:
    """What the face tracker knows this frame (all optional).

    face_box: (x, y, w, h) in pixels, or None when no face is visible.
    head_down: 0..1, how far the head is pitched down relative to calibration.
    """
    face_box: Optional[Box] = None
    head_down: float = 0.0


@dataclass(frozen=True)
class PhoneState:
    seen: bool = False
    confidence: float = 0.0
    box: Optional[Box] = None
    since: Optional[float] = None   # timestamp (same clock as update()) when "seen" began


def box_iou(a: Box, b: Box) -> float:
    ax2, ay2, bx2, by2 = a[0] + a[2], a[1] + a[3], b[0] + b[2], b[1] + b[3]
    iw = min(ax2, bx2) - max(a[0], b[0])
    ih = min(ay2, by2) - max(a[1], b[1])
    if iw <= 0 or ih <= 0:
        return 0.0
    inter = iw * ih
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def head_down_from_pitch(pitch: float, center_pitch: float, span: float = 0.15) -> float:
    """Map the face tracker's pitch (relative to the calibrated centre) to 0..1.

    Only downward deviation counts; looking up or at the screen gives 0.
    """
    return max(0.0, min(1.0, (pitch - center_pitch) / span))


def face_context_from_landmarks(lm, frame_size, pitch=None, center_pitch=None) -> FaceContext:
    """Build a FaceContext from normalised face landmarks (objects with .x/.y), or none."""
    fw, fh = frame_size
    if not lm or fw <= 0 or fh <= 0:
        return FaceContext()
    xs = [p.x for p in lm]
    ys = [p.y for p in lm]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    head_down = 0.0
    if pitch is not None and center_pitch is not None:
        head_down = head_down_from_pitch(pitch, center_pitch)
    return FaceContext((x0 * fw, y0 * fh, (x1 - x0) * fw, (y1 - y0) * fh), head_down)


def box_is_plausible(box: Box, frame_size: Tuple[float, float], score: float) -> bool:
    """Reject boxes whose size or shape cannot be a hand-held phone."""
    fw, fh = frame_size
    x, y, w, h = box
    if fw <= 0 or fh <= 0 or w <= 0 or h <= 0 or score < MIN_RAW_SCORE:
        return False
    area = (w * h) / (fw * fh)
    if not MIN_AREA_FRACTION <= area <= MAX_AREA_FRACTION:
        return False
    aspect = min(w, h) / max(w, h)
    if not MIN_ASPECT <= aspect <= MAX_ASPECT:
        return False
    # must be mostly inside the frame (a sliver at the edge is not enough to judge)
    visible_w = min(x + w, fw) - max(x, 0)
    visible_h = min(y + h, fh) - max(y, 0)
    return visible_w * visible_h >= 0.5 * w * h


class PhoneTracker:
    def __init__(self):
        self.reset()

    def reset(self):
        self._box: Optional[Box] = None
        self._confidence = 0.0
        self._last_update: Optional[float] = None
        self._last_hit: Optional[float] = None
        self._rising_since: Optional[float] = None
        self._seen = False
        self._since: Optional[float] = None

    @property
    def state(self) -> PhoneState:
        return PhoneState(self._seen, round(self._confidence, 3),
                          self._box if self._seen else None, self._since)

    def _context_evidence(self, box, score, frame_size, context):
        evidence = score
        fw, fh = frame_size
        boost = 0.0
        if box[1] + box[3] / 2 > 0.55 * fh:
            boost += LOWER_FRAME_BOOST
        if context is not None:
            face = context.face_box
            if face and face[2] > 0 and face[3] > 0:
                fx, fy = face[0] + face[2] / 2, face[1] + face[3] / 2
                bx, by = box[0] + box[2] / 2, box[1] + box[3] / 2
                if abs(bx - fx) <= 1.5 * face[3] + face[2] / 2 and abs(by - fy) <= 1.5 * face[3]:
                    boost += NEAR_FACE_BOOST
                if box_iou(box, face) > 0.5 or _containment(box, face) > 0.7:
                    evidence -= OVERLAP_FACE_PENALTY
            boost += HEAD_DOWN_BOOST * max(0.0, min(1.0, context.head_down))
        return min(1.0, max(0.0, evidence + min(boost, EXTERNAL_CONTEXT_MAX_BOOST)))

    def update(self, detections, frame_size, now, context: Optional[FaceContext] = None) -> PhoneState:
        """Feed one detector run.

        detections: iterable of (box, score) with box = (x, y, w, h) in pixels.
        frame_size: (width, height) in pixels. now: monotonic-style seconds (any clock).
        Call once per detector run, including runs with no detections.
        """
        candidates = []
        for box, score in detections or ():
            box = tuple(float(v) for v in box)
            if box_is_plausible(box, frame_size, float(score)):
                candidates.append((box, float(score)))

        # pick the candidate that continues the track, else the strongest one
        chosen = None
        if candidates:
            if self._box is not None:
                near = [c for c in candidates if box_iou(c[0], self._box) >= ASSOCIATION_IOU]
                if near:
                    chosen = max(near, key=lambda c: c[1])
            if chosen is None:
                chosen = max(candidates, key=lambda c: c[1])
                if self._box is not None and self._seen and now - (self._last_hit or now) < GRACE_SECONDS:
                    # a confirmed phone moved/jumped: keep the confirmed track, treat this as
                    # an unassociated hit that starts a fresh (lower-trust) evidence streak
                    self._confidence *= 0.5

        if chosen is not None:
            box, score = chosen
            evidence = self._context_evidence(box, score, frame_size, context)
            if self._last_update is None or self._confidence == 0.0:
                self._confidence = evidence * EMA_ALPHA
            else:
                self._confidence += EMA_ALPHA * (evidence - self._confidence)
            self._box = box if self._box is None else tuple(
                0.5 * o + 0.5 * n for o, n in zip(self._box, box))
            self._last_hit = now
        else:
            self._confidence *= 1.0 - EMA_ALPHA   # silence is evidence of absence
        self._last_update = now

        self._apply_hysteresis(now, hit=chosen is not None)
        return self.state

    def _apply_hysteresis(self, now, hit):
        if not self._seen:
            if self._confidence >= ENTER_CONFIDENCE and hit:
                if self._rising_since is None:
                    self._rising_since = now
                if now - self._rising_since >= MIN_ENTER_SECONDS:
                    self._seen = True
                    self._since = now - MIN_ENTER_SECONDS   # evidence began then
                    self._rising_since = None
            else:
                if self._confidence < EXIT_CONFIDENCE:
                    self._rising_since = None   # a 50% flicker may keep building; silence may not
                if self._last_hit is None or now - self._last_hit > STALE_TRACK_SECONDS:
                    self._rising_since = None
                    self._box = None
                    self._confidence = 0.0
        else:
            idle = now - (self._last_hit if self._last_hit is not None else now)
            if self._confidence < EXIT_CONFIDENCE and idle >= GRACE_SECONDS:
                self._seen = False
                self._since = None
                self._rising_since = None
                self._box = None
                self._confidence = 0.0


def _containment(inner: Box, outer: Box) -> float:
    """Share of `inner`'s area that lies inside `outer`."""
    iw = min(inner[0] + inner[2], outer[0] + outer[2]) - max(inner[0], outer[0])
    ih = min(inner[1] + inner[3], outer[1] + outer[3]) - max(inner[1], outer[1])
    if iw <= 0 or ih <= 0 or inner[2] * inner[3] <= 0:
        return 0.0
    return iw * ih / (inner[2] * inner[3])
