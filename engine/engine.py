"""
Study Focus Engine
Fuses browser activity (from the Chrome extension) with camera tracking:
presence, head direction, eye gaze, blinks, yawns and facial expression.
Computes a Productivity Index and shows nudges, break and wellbeing reminders.

Run:
    python engine.py                 # with camera + live view
    python engine.py --compact       # only the small status bar
    python engine.py --no-camera     # simulate camera with keys P (presence) and F (facing)

Window keys (click the window first):
    D  demo: 20 minutes of distraction   -> focus popup
    B  demo: 50 minutes of study         -> eye-rest popup
    T  demo: tired (yawning)             -> tired popup
    X  demo: frustrated face             -> "stuck?" popup
    C  recalibrate "looking at the screen" (look at the screen center for 2 s)
    V  show / hide the live view
    Q  quit
Optional global hotkeys (if `pip install pynput`): Ctrl+Shift+D, Ctrl+Shift+B
"""
import argparse
import collections
import json
import os
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ---------------- settings ----------------
PORT = 8000
UI_REFRESH_MS = 100              # camera preview refresh; logic + info update every 5th frame
PREVIEW_WIDTH = 480
TIMELINE_SECONDS = 5 * 60        # colored state strip in the info panel
AFK_AFTER_SECONDS = 180          # face missing this long -> AFK, session clock pauses
NUDGE_AFTER_SECONDS = 60         # continuous distraction before the soft nudge
SNOOZE_SECONDS = 5 * 60
BREAK_AFTER_SECONDS = 50 * 60    # study time before an eye-rest reminder
EYE_REST_SECONDS = 20
INDEX_WINDOW_SECONDS = 10 * 60   # Productivity Index = weighted average over this window
SCATTERED_SWITCHES = 15          # tab switches in 5 min that count as "scattered"
EXTENSION_STALE_SECONDS = 75     # extension heartbeat is every 30 s

CAMERA_INDEX = 0
CAMERA_FPS = 15                  # high enough to catch blinks
CENTER_BAND = 0.6                # nose must be inside the central 60% of the frame
YAW_TOLERANCE = 0.15             # head: allowed deviation from the calibrated pose
PITCH_TOLERANCE = 0.10
GAZE_H_TOLERANCE = 0.10          # eyes: iris position left/right inside the eye
GAZE_V_TOLERANCE = 0.35          # eyes: looking up/down score
CALIBRATION_FRAMES = 30          # ~2 s at 15 FPS
SMOOTHING_FRAMES = 10            # majority vote over the last N frames

EYES_CLOSED_LEVEL = 0.5          # blink score above this = eyes closed
BLINK_MAX_SECONDS = 0.5          # closed shorter than this = a blink
DROWSY_SECONDS = 2.0             # eyes closed this long = sleepy
YAWN_JAW_LEVEL = 0.5
YAWN_MIN_SECONDS = 1.2           # mouth wide open this long = yawn (talking is shorter)
TIRED_YAWNS = 3                  # yawns in YAWN_WINDOW -> tired popup
YAWN_WINDOW = 10 * 60
BLINK_WINDOW = 2 * 60
LOW_BLINK_RATE = 6               # blinks/min; normal is ~15, staring at screens drops it
FRUSTRATED_SHARE = 0.6           # share of the last minute with a frustrated face
EXPRESSION_WINDOW = 60
WELLBEING_COOLDOWN = 10 * 60     # don't repeat the same wellbeing popup sooner

MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/face_landmarker/"
             "face_landmarker/float16/1/face_landmarker.task")
MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "face_landmarker.task")

# score of each state for the Productivity Index (AFK is not counted)
STATE_SCORES = {
    "Focused": 1.0,
    "Reading / Thinking": 0.8,
    "Other App": 0.7,
    "Browsing": 0.6,
    "Looking Away": 0.5,
    "Away": 0.5,
    "Scattered": 0.3,
    "Idle Tab": 0.3,
    "Distracted": 0.0,
}
STATE_COLORS = {
    "Focused": "#1f7a4d",
    "Reading / Thinking": "#1d6b7a",
    "Other App": "#2f5f8a",
    "Browsing": "#4a5568",
    "Looking Away": "#4a5568",
    "Away": "#6b6b6b",
    "AFK": "#3a3a3a",
    "Scattered": "#b26a00",
    "Idle Tab": "#8a5a00",
    "Distracted": "#b3261e",
    "Starting": "#4a5568",
}
POPUP_STYLE = {  # kind: (title, color)
    "nudge": ("Focus check", "#b3261e"),
    "break": ("Eye-rest break", "#1d6b7a"),
    "tired": ("Feeling tired?", "#5b3a8a"),
    "stuck": ("Stuck?", "#b26a00"),
}
EXPRESSION_NAMES = ["Smile", "Frown", "Brow down", "Brow raise", "Jaw open", "Eyes closed"]

# ---------------- shared state ----------------
lock = threading.Lock()
running = True
show_preview = True
browser = {"domain": "waiting for extension", "category": "neutral", "idle": "active",
           "switches": 0, "updated": 0.0}
camera = {"status": "starting", "present": False, "facing": False, "reason": "-",
          "yaw": 0.0, "pitch": 0.0, "gaze_h": 0.5, "gaze_v": 0.0, "gaze_text": "-",
          "eyes_closed": False, "closed_since": None, "expression": "-",
          "scores": {n: 0.0 for n in EXPRESSION_NAMES},
          "last_seen": time.time(), "started": time.time()}
calib = {"yaw": None, "pitch": None, "gaze_h": None, "gaze_v": None, "samples": [], "active": True}
blinks = collections.deque()          # timestamps
yawns = collections.deque()           # timestamps
expression_log = collections.deque()  # (timestamp, label)
presence_log = collections.deque()    # (timestamp, present) from the engine tick
session = {"active_seconds": 0.0, "focused_seconds": 0.0, "distracted_seconds": 0.0,
           "since_break": 0.0, "distraction_streak": 0.0, "nudged": False,
           "state": "Starting", "index": 100}
last_alert = {}                       # wellbeing popup kind -> time shown
history = collections.deque()         # (timestamp, score, weight_seconds)
timeline = collections.deque()        # (timestamp, state) for the colored strip
preview = {"png": None}               # latest annotated camera frame (base64 PNG, memory only)
events = []                           # popups for the UI: (kind, message)
demo_requests = []                    # filled by global hotkeys (other thread)


# ---------------- decision engine ----------------
def assess(category, idle, switches, present, facing, missing_seconds):
    """The decision matrix: browser category + camera state -> engine state."""
    if idle == "locked":
        return "AFK"
    if not present:
        return "AFK" if missing_seconds >= AFK_AFTER_SECONDS else "Away"
    if category == "productive":
        return "Focused" if facing else "Reading / Thinking"
    if category == "distraction":
        return "Distracted" if facing else "Idle Tab"
    if category == "other":  # another app (VS Code, PDF reader...) is in front
        return "Other App" if facing else "Reading / Thinking"
    if switches >= SCATTERED_SWITCHES:
        return "Scattered"
    return "Browsing" if facing else "Looking Away"


def update_index(now):
    while history and now - history[0][0] > INDEX_WINDOW_SECONDS:
        history.popleft()
    total = sum(w for _, _, w in history)
    if total > 0:
        session["index"] = round(100 * sum(s * w for _, s, w in history) / total)


def trim(log, now, window):
    while log and now - (log[0][0] if isinstance(log[0], tuple) else log[0]) > window:
        log.popleft()


def blink_rate(now):
    """Blinks per minute over the last BLINK_WINDOW (None until enough data)."""
    with lock:
        trim(blinks, now, BLINK_WINDOW)
        count = len(blinks)
        started = camera["started"]
    seconds = min(BLINK_WINDOW, now - started)
    return None if seconds < 30 else count * 60 / seconds


def alert(kind, message, now):
    if now - last_alert.get(kind, -1e9) >= WELLBEING_COOLDOWN:
        last_alert[kind] = now
        events.append((kind, message))


def wellbeing_checks(now, b, c, state):
    """Tired / stuck / eye-strain detection from eyes and expressions."""
    if not c["present"] or c["reason"] == "simulated":  # no real camera data in --no-camera mode
        return
    if c["closed_since"] and now - c["closed_since"] >= DROWSY_SECONDS:
        alert("tired", "Your eyes were closed for a few seconds.\n"
                       "Feeling sleepy? Stand up, drink water,\nand take a 5-minute break.", now)

    with lock:
        trim(yawns, now, YAWN_WINDOW)
        yawn_count = len(yawns)
        trim(expression_log, now, EXPRESSION_WINDOW)
        labels = [label for _, label in expression_log]
    if yawn_count >= TIRED_YAWNS:
        alert("tired", f"You yawned {yawn_count} times in 10 minutes.\n"
                       "Your brain needs a break, or switch to\nan easier subject for a while.", now)

    # frustrated for most of the last minute while studying -> offer help
    if len(labels) > CAMERA_FPS * 40 and state in ("Focused", "Reading / Thinking", "Other App"):
        if labels.count("Frustrated") / len(labels) >= FRUSTRATED_SHARE:
            alert("stuck", "You look stuck or frustrated.\n"
                           "Try an easier example, re-read the basics,\nor take a 2-minute break.", now)

    # low blink rate while looking at the screen -> dry eyes
    rate = blink_rate(now)
    presence_log.append((now, c["present"]))
    trim(presence_log, now, BLINK_WINDOW)
    present_share = sum(p for _, p in presence_log) / len(presence_log)
    if (rate is not None and now - c["started"] >= BLINK_WINDOW and present_share > 0.9
            and c["facing"] and rate < LOW_BLINK_RATE):
        alert("break", f"You blink only {rate:.0f} times per minute (normal ~15).\n"
                       "Your eyes are drying out. Look away\nfor 20 seconds and blink a few times.", now)


def tick(dt):
    now = time.time()
    with lock:
        b = dict(browser)
        c = dict(camera)
    state = assess(b["category"], b["idle"], b["switches"],
                   c["present"], c["facing"], now - c["last_seen"])
    session["state"] = state
    timeline.append((now, state))
    trim(timeline, now, TIMELINE_SECONDS)

    if state == "AFK":
        # clock paused; being away for a while also counts as a break
        session["since_break"] = 0
        session["distraction_streak"] = 0
        session["nudged"] = False
        return

    session["active_seconds"] += dt
    session["since_break"] += dt
    if state == "Focused":
        session["focused_seconds"] += dt

    if state == "Distracted":
        session["distracted_seconds"] += dt
        session["distraction_streak"] += dt
        if session["distraction_streak"] >= NUDGE_AFTER_SECONDS and not session["nudged"]:
            session["nudged"] = True
            minutes = max(1, round(session["distraction_streak"] / 60))
            events.append(("nudge", f"You've been on {b['domain']} for {minutes} min.\n"
                                    "Ready to get back to studying?"))
    elif state != "Away":  # a short glance away doesn't reset the streak
        session["distraction_streak"] = 0
        session["nudged"] = False

    if session["since_break"] >= BREAK_AFTER_SECONDS:
        session["since_break"] = 0
        events.append(("break", "You've been studying for 50 minutes.\n"
                                "Look at something ~6 m away for 20 seconds."))

    wellbeing_checks(now, b, c, state)
    history.append((now, STATE_SCORES.get(state, 0.5), dt))
    update_index(now)


def simulate_distraction():
    """Demo key D: pretend the last 20 minutes were spent on distracting sites."""
    fake = 20 * 60
    session["distracted_seconds"] += fake
    session["active_seconds"] += fake
    history.append((time.time(), 0.0, fake))
    update_index(time.time())
    events.append(("nudge", "20 minutes on distracting sites.\n"
                            "Your focus is dropping. Switch back to your subject?"))


def simulate_long_session():
    """Demo key B: pretend 50 minutes of study have passed."""
    session["since_break"] = BREAK_AFTER_SECONDS


def simulate_tired():
    events.append(("tired", "You yawned 3 times in 10 minutes.\n"
                            "Your brain needs a break, or switch to\nan easier subject for a while."))


def simulate_stuck():
    events.append(("stuck", "You look stuck or frustrated.\n"
                            "Try an easier example, re-read the basics,\nor take a 2-minute break."))


def explain(state, category):
    """One line telling the viewer why the engine picked this state."""
    reasons = {
        "Focused": "study site + eyes on the screen",
        "Reading / Thinking": "not looking at the screen, but on study material: no alert",
        "Other App": "another app is in front (e.g. code editor) + eyes on the screen",
        "Browsing": "neutral site + eyes on the screen",
        "Looking Away": "neutral site + looking away",
        "Away": f"no face for a moment (AFK after {AFK_AFTER_SECONDS // 60} min)",
        "AFK": "no face for a while or screen locked: session clock paused",
        "Scattered": f"{SCATTERED_SWITCHES}+ tab switches in 5 min",
        "Idle Tab": "distracting site open, but not watching it",
        "Distracted": f"distracting site + eyes on it: nudge after {NUDGE_AFTER_SECONDS}s",
        "Starting": "waiting for data",
    }
    return reasons.get(state, category)


def snooze():
    session["distraction_streak"] = -SNOOZE_SECONDS + NUDGE_AFTER_SECONDS
    session["nudged"] = False


def snapshot():
    with lock:
        return {"state": session["state"], "index": session["index"],
                "domain": browser["domain"], "category": browser["category"],
                "camera": camera_text(), "expression": camera["expression"]}


def camera_text():
    s = camera["status"]
    if s != "ok":
        return s
    if not camera["present"]:
        return "No Face"
    return "Present & Facing" if camera["facing"] else "Present, Looking Away"


# ---------------- local bridge (HTTP) ----------------
class Handler(BaseHTTPRequestHandler):
    def send_json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        if self.path == "/status":
            self.send_json(200, snapshot())
        else:
            self.send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/activity":
            self.send_json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            self.send_json(400, {"error": "bad json"})
            return
        with lock:
            browser["domain"] = str(data.get("domain", "-"))[:80]
            if data.get("category") in ("productive", "distraction", "neutral", "other"):
                browser["category"] = data["category"]
            if data.get("idle") in ("active", "idle", "locked"):
                browser["idle"] = data["idle"]
            try:
                browser["switches"] = int(data.get("switches", 0))
            except (TypeError, ValueError):
                pass
            browser["updated"] = time.time()
        self.send_json(200, snapshot())

    def log_message(self, *args):
        pass


def start_server(port):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


# ---------------- face analysis ----------------
LEFT_EYE = [33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246]
RIGHT_EYE = [362, 382, 381, 380, 374, 373, 390, 249, 263, 466, 388, 387, 386, 385, 384, 398]
LEFT_IRIS, RIGHT_IRIS = 468, 473  # iris centers (Face Landmarker gives 478 points)


def set_camera(**values):
    with lock:
        camera.update(values)


def head_pose(lm):
    """Rough yaw/pitch ratios from face landmarks (0.5 ~ centered)."""
    nose = lm[1]
    left, right = lm[234], lm[454]      # cheek edges
    top, chin = lm[10], lm[152]         # forehead, chin
    yaw = (nose.x - left.x) / ((right.x - left.x) or 1e-6)
    pitch = (nose.y - top.y) / ((chin.y - top.y) or 1e-6)
    return nose, yaw, pitch


def eye_gaze(lm, bs):
    """gaze_h: iris position between the eye corners (0.5 = center, averaged over both eyes).
    gaze_v: looking down (+) / up (-) from the model's eye blendshapes."""
    def ratio(iris, a, b):
        lo, hi = min(lm[a].x, lm[b].x), max(lm[a].x, lm[b].x)
        return (lm[iris].x - lo) / ((hi - lo) or 1e-6)
    gaze_h = (ratio(LEFT_IRIS, 33, 133) + ratio(RIGHT_IRIS, 362, 263)) / 2
    down = (bs.get("eyeLookDownLeft", 0) + bs.get("eyeLookDownRight", 0)) / 2
    up = (bs.get("eyeLookUpLeft", 0) + bs.get("eyeLookUpRight", 0)) / 2
    return gaze_h, down - up


def read_expression(bs):
    """Facial expression from blendshapes. These are expression estimates, not true feelings."""
    def avg(a, b):
        return (bs.get(a, 0) + bs.get(b, 0)) / 2
    scores = {
        "Smile": avg("mouthSmileLeft", "mouthSmileRight"),
        "Frown": avg("mouthFrownLeft", "mouthFrownRight"),
        "Brow down": avg("browDownLeft", "browDownRight"),
        "Brow raise": bs.get("browInnerUp", 0),
        "Jaw open": bs.get("jawOpen", 0),
        "Eyes closed": avg("eyeBlinkLeft", "eyeBlinkRight"),
    }
    press = avg("mouthPressLeft", "mouthPressRight")
    if scores["Eyes closed"] > EYES_CLOSED_LEVEL and scores["Jaw open"] > YAWN_JAW_LEVEL:
        label = "Yawning"
    elif scores["Smile"] > 0.5:
        label = "Happy"
    elif scores["Brow down"] > 0.35 and (press > 0.25 or scores["Frown"] > 0.2):
        label = "Frustrated"
    elif scores["Brow raise"] > 0.5:
        label = "Confused / Surprised"
    elif scores["Brow down"] > 0.3:
        label = "Concentrating"
    elif scores["Frown"] > 0.35:
        label = "Unhappy"
    else:
        label = "Neutral"
    return label, scores


def gaze_direction(gaze_h, gaze_v):
    base_h = calib["gaze_h"] if calib["gaze_h"] is not None else 0.5
    base_v = calib["gaze_v"] if calib["gaze_v"] is not None else 0.0
    parts = []
    if gaze_v - base_v > GAZE_V_TOLERANCE:
        parts.append("down")
    elif gaze_v - base_v < -GAZE_V_TOLERANCE:
        parts.append("up")
    if gaze_h - base_h > GAZE_H_TOLERANCE:
        parts.append("right")
    elif gaze_h - base_h < -GAZE_H_TOLERANCE:
        parts.append("left")
    return "-".join(parts) if parts else "center"


def attention(nose, yaw, pitch, gaze_h, gaze_v, eyes_closed):
    """Is the user looking at the screen? Returns (bool, reason)."""
    if eyes_closed:
        return False, "eyes closed"
    margin = (1 - CENTER_BAND) / 2
    if not (margin <= nose.x <= 1 - margin):
        return False, "face off-center"
    base_yaw = calib["yaw"] if calib["yaw"] is not None else 0.5
    if abs(yaw - base_yaw) > YAW_TOLERANCE:
        return False, "head turned away"
    if calib["pitch"] is not None and abs(pitch - calib["pitch"]) > PITCH_TOLERANCE:
        return False, "head tilted"
    direction = gaze_direction(gaze_h, gaze_v)
    if direction != "center":
        return False, f"eyes looking {direction}"
    return True, "eyes on screen"


def calibrate(yaw, pitch, gaze_h, gaze_v):
    calib["samples"].append((yaw, pitch, gaze_h, gaze_v))
    if len(calib["samples"]) >= CALIBRATION_FRAMES:
        n = len(calib["samples"])
        for i, key in enumerate(("yaw", "pitch", "gaze_h", "gaze_v")):
            calib[key] = sum(s[i] for s in calib["samples"]) / n
        calib["samples"] = []
        calib["active"] = False


def reset_calibration():
    calib.update(yaw=None, pitch=None, gaze_h=None, gaze_v=None, samples=[], active=True)


def track_blinks_and_yawns(now, eyes_closed, jaw, st):
    """st keeps the eye/mouth timers between frames."""
    if eyes_closed:
        if st["closed_since"] is None:
            st["closed_since"] = now
    else:
        if st["closed_since"] is not None and now - st["closed_since"] < BLINK_MAX_SECONDS:
            with lock:
                blinks.append(now)
        st["closed_since"] = None
    if jaw > YAWN_JAW_LEVEL:
        if st["jaw_since"] is None:
            st["jaw_since"] = now
    else:
        if st["jaw_since"] is not None and now - st["jaw_since"] >= YAWN_MIN_SECONDS:
            with lock:
                yawns.append(now)
        st["jaw_since"] = None


def analyze_face(lm, bs, st, votes, expression_votes):
    """All per-frame analysis for one detected face; updates shared camera state."""
    now = time.time()
    nose, yaw, pitch = head_pose(lm)
    gaze_h, gaze_v = eye_gaze(lm, bs)
    label, scores = read_expression(bs)
    eyes_closed = scores["Eyes closed"] > EYES_CLOSED_LEVEL
    track_blinks_and_yawns(now, eyes_closed, scores["Jaw open"], st)

    if calib["active"] and not eyes_closed:
        calibrate(yaw, pitch, gaze_h, gaze_v)
    looking, reason = attention(nose, yaw, pitch, gaze_h, gaze_v, eyes_closed)
    votes.append(looking)
    facing = sum(votes) * 2 > len(votes)
    expression_votes.append(label)
    expression = collections.Counter(expression_votes).most_common(1)[0][0]

    with lock:
        expression_log.append((now, expression))
        camera.update(present=True, facing=facing, reason=reason, yaw=yaw, pitch=pitch,
                      gaze_h=gaze_h, gaze_v=gaze_v,
                      gaze_text="closed" if eyes_closed else gaze_direction(gaze_h, gaze_v),
                      eyes_closed=eyes_closed, closed_since=st["closed_since"],
                      expression=expression, scores=scores, last_seen=now)
    return facing, reason


def draw_overlay(cv2, frame, lm, facing, reason):
    """Draw face points, eyes, gaze arrow, the center band and the verdict (in memory only)."""
    h, w = frame.shape[:2]
    margin = int(w * (1 - CENTER_BAND) / 2)
    for x in (margin, w - margin):
        cv2.line(frame, (x, 0), (x, h), (180, 180, 180), 1)

    def px(i):
        return int(lm[i].x * w), int(lm[i].y * h)

    if lm:
        color = (80, 200, 80) if facing else (40, 140, 255)
        for p in lm[::6]:
            cv2.circle(frame, (int(p.x * w), int(p.y * h)), 1, color, -1)
        for eye in (LEFT_EYE, RIGHT_EYE):
            for i in eye:
                cv2.circle(frame, px(i), 1, (255, 255, 255), -1)
        for iris, edge in ((LEFT_IRIS, LEFT_IRIS + 1), (RIGHT_IRIS, RIGHT_IRIS + 1)):
            cx, cy = px(iris)
            ex, ey = px(edge)
            radius = max(2, int(((cx - ex) ** 2 + (cy - ey) ** 2) ** 0.5))
            cv2.circle(frame, (cx, cy), radius, (255, 220, 0), 1)
            cv2.circle(frame, (cx, cy), 2, (255, 220, 0), -1)
        # gaze arrow from between the eyes
        with lock:
            gh, gv, closed = camera["gaze_h"], camera["gaze_v"], camera["eyes_closed"]
            expression, scores = camera["expression"], dict(camera["scores"])
        if not closed:
            base_h = calib["gaze_h"] if calib["gaze_h"] is not None else 0.5
            base_v = calib["gaze_v"] if calib["gaze_v"] is not None else 0.0
            sx, sy = px(168)
            end = (int(sx + (gh - base_h) * 600), int(sy + (gv - base_v) * 120))
            cv2.arrowedLine(frame, (sx, sy), end, (255, 220, 0), 2, tipLength=0.3)
        label = "LOOKING AT SCREEN" if facing else "NOT LOOKING"
        detail = reason
        if calib["active"]:
            detail += "  |  calibrating: look at the screen center"
        cv2.rectangle(frame, (0, h - 34), (w, h), (25, 25, 25), -1)
        cv2.putText(frame, f"Expression: {expression}   (smile {scores['Smile']:.2f}, "
                           f"brow down {scores['Brow down']:.2f})",
                    (12, h - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (230, 230, 230), 1, cv2.LINE_AA)
    else:
        color = (60, 60, 220)
        label = "NO FACE"
        detail = "move into the frame"

    cv2.rectangle(frame, (0, 0), (w, 54), (25, 25, 25), -1)
    cv2.putText(frame, label, (12, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2, cv2.LINE_AA)
    cv2.putText(frame, detail, (12, 46), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (230, 230, 230), 1, cv2.LINE_AA)
    return frame


def store_preview(cv2, frame):
    import base64
    h, w = frame.shape[:2]
    small = cv2.resize(frame, (PREVIEW_WIDTH, int(h * PREVIEW_WIDTH / w)))
    ok, png = cv2.imencode(".png", small)
    if ok:
        preview["png"] = base64.b64encode(png.tobytes()).decode()


def camera_loop(camera_index):
    try:
        import cv2
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision
    except ImportError:
        set_camera(status="missing: pip install opencv-python mediapipe")
        return

    if not os.path.exists(MODEL_PATH):
        set_camera(status="downloading face model...")
        try:
            urllib.request.urlretrieve(MODEL_URL, MODEL_PATH + ".part")
            os.replace(MODEL_PATH + ".part", MODEL_PATH)
        except Exception as e:
            set_camera(status=f"model download failed: {e}")
            return

    options = vision.FaceLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=MODEL_PATH),
        running_mode=vision.RunningMode.VIDEO,
        output_face_blendshapes=True,
        num_faces=1)
    landmarker = vision.FaceLandmarker.create_from_options(options)

    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        set_camera(status="camera not available")
        return

    votes = collections.deque(maxlen=SMOOTHING_FRAMES)
    expression_votes = collections.deque(maxlen=CAMERA_FPS * 2)
    st = {"closed_since": None, "jaw_since": None}
    frame_time = 1.0 / CAMERA_FPS
    set_camera(status="ok", started=time.time())
    while running:
        started = time.monotonic()
        ok, frame = cap.read()
        if not ok:
            time.sleep(0.5)
            continue
        # frames stay in memory only: never saved, never sent anywhere
        frame = cv2.flip(frame, 1)  # mirror view, feels natural in the preview
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = landmarker.detect_for_video(image, int(time.monotonic() * 1000))

        lm = result.face_landmarks[0] if result.face_landmarks else None
        facing, reason = False, "no face"
        if lm:
            bs = {}
            if result.face_blendshapes:
                bs = {c.category_name: c.score for c in result.face_blendshapes[0]}
            facing, reason = analyze_face(lm, bs, st, votes, expression_votes)
        else:
            votes.clear()
            st.update(closed_since=None, jaw_since=None)
            set_camera(present=False, facing=False, reason="no face", closed_since=None,
                       eyes_closed=False, gaze_text="-")

        if show_preview:
            store_preview(cv2, draw_overlay(cv2, frame, lm, facing, reason))

        time.sleep(max(0.0, frame_time - (time.monotonic() - started)))
    cap.release()
    landmarker.close()


# ---------------- optional global hotkeys ----------------
def start_global_hotkeys():
    try:
        from pynput import keyboard
    except ImportError:
        return False
    hotkeys = keyboard.GlobalHotKeys({
        "<ctrl>+<shift>+d": lambda: demo_requests.append("d"),
        "<ctrl>+<shift>+b": lambda: demo_requests.append("b"),
    })
    hotkeys.daemon = True
    hotkeys.start()
    return True


# ---------------- window UI ----------------
def fmt_minutes(seconds):
    return f"{int(seconds // 60)}m"


def fmt_clock(seconds):
    seconds = int(max(0, seconds))
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def run_ui(fake_camera, global_keys, compact):
    global running, show_preview
    import tkinter as tk

    BG, PANEL, FG, MUTED = "#15171a", "#1f2226", "#f2f2f2", "#9aa0a6"
    show_preview = not compact

    root = tk.Tk()
    root.title("Study Focus")
    root.attributes("-topmost", True)
    root.geometry("+20+20")
    root.configure(bg=BG)

    # --- top status bar (always visible) ---
    bar = tk.Label(root, font=("DejaVu Sans Mono", 12, "bold"), fg="white", padx=12, pady=6, anchor="w")
    stats = tk.Label(root, font=("DejaVu Sans Mono", 10), fg="white", padx=12, pady=2, anchor="w")
    bar.pack(fill="x")
    stats.pack(fill="x")

    # --- live view: camera + expression bars on the left, info on the right ---
    body = tk.Frame(root, bg=BG)
    left = tk.Frame(body, bg=BG)
    left.grid(row=0, column=0, padx=(10, 6), pady=10, sticky="n")
    placeholder = tk.PhotoImage(width=PREVIEW_WIDTH, height=360)  # fixes the size in pixels
    cam_label = tk.Label(left, bg="black", fg=MUTED, image=placeholder,
                         text="camera starting...", compound="center")
    cam_label.pack()

    expr_frame = tk.Frame(left, bg=PANEL, padx=12, pady=8)
    expr_frame.pack(fill="x", pady=(8, 0))
    expr_title = tk.Label(expr_frame, font=("DejaVu Sans", 13, "bold"), bg=PANEL, fg=FG, anchor="w")
    expr_title.pack(fill="x")
    expr_canvas = tk.Canvas(expr_frame, width=PREVIEW_WIDTH - 24, height=len(EXPRESSION_NAMES) * 18,
                            bg=PANEL, highlightthickness=0)
    expr_canvas.pack(anchor="w", pady=(4, 0))

    info = tk.Frame(body, bg=PANEL, padx=14, pady=10)
    info.grid(row=0, column=1, padx=(6, 10), pady=10, sticky="nsew")

    state_big = tk.Label(info, font=("DejaVu Sans", 22, "bold"), bg=PANEL, fg=FG, anchor="w")
    state_big.pack(fill="x")
    reason = tk.Label(info, font=("DejaVu Sans", 10), bg=PANEL, fg=MUTED, anchor="w",
                      justify="left", wraplength=340)
    reason.pack(fill="x", pady=(0, 8))

    rows = {}
    grid = tk.Frame(info, bg=PANEL)
    grid.pack(fill="x")
    names = ["Website", "Category", "Attention", "Eyes", "Blinks", "Yawns", "Head pose",
             "Tab switches", "Extension", "Session", "Focused", "Distracted", "Nudge", "Next break"]
    for i, name in enumerate(names):
        tk.Label(grid, text=name, font=("DejaVu Sans", 10), bg=PANEL, fg=MUTED,
                 anchor="w").grid(row=i, column=0, sticky="w", pady=1)
        rows[name] = tk.Label(grid, font=("DejaVu Sans Mono", 10), bg=PANEL, fg=FG, anchor="w")
        rows[name].grid(row=i, column=1, sticky="w", padx=(12, 0), pady=1)

    tk.Label(info, text="Productivity Index (last 10 min)", font=("DejaVu Sans", 10),
             bg=PANEL, fg=MUTED, anchor="w").pack(fill="x", pady=(10, 2))
    index_canvas = tk.Canvas(info, width=340, height=22, bg="#2b2f34", highlightthickness=0)
    index_canvas.pack(anchor="w")

    tk.Label(info, text=f"State timeline (last {TIMELINE_SECONDS // 60} min)", font=("DejaVu Sans", 10),
             bg=PANEL, fg=MUTED, anchor="w").pack(fill="x", pady=(10, 2))
    timeline_canvas = tk.Canvas(info, width=340, height=18, bg="#2b2f34", highlightthickness=0)
    timeline_canvas.pack(anchor="w")

    keys = "D distraction · B break · T tired · X stuck · C calibrate · V live view · Q quit"
    if fake_camera:
        keys += " · P presence · F facing"
    if global_keys:
        keys += "  (global: Ctrl+Shift+D/B)"
    hint = tk.Label(root, text=keys, font=("DejaVu Sans Mono", 8), fg="#dddddd", padx=12, pady=4, anchor="w")

    def layout():
        body.pack_forget()
        hint.pack_forget()
        if show_preview:
            body.pack(fill="both")
        hint.pack(fill="x")

    layout()

    # --- popups ---
    def show_popup(kind, message):
        title, color = POPUP_STYLE.get(kind, ("Study Focus", "#4a5568"))
        win = tk.Toplevel(root)
        win.title("Study Focus")
        win.attributes("-topmost", True)
        win.configure(bg=color)
        tk.Label(win, text=title, font=("DejaVu Sans", 18, "bold"), bg=color, fg="white").pack(padx=30, pady=(20, 6))
        tk.Label(win, text=message, font=("DejaVu Sans", 12), bg=color, fg="white", justify="center").pack(padx=30, pady=6)
        buttons = tk.Frame(win, bg=color)
        buttons.pack(pady=(10, 20))
        if kind == "nudge":
            tk.Button(buttons, text="Back to work", width=14, command=win.destroy).pack(side="left", padx=6)
            tk.Button(buttons, text="5 more minutes", width=14,
                      command=lambda: (snooze(), win.destroy())).pack(side="left", padx=6)
        elif kind == "break":
            counter = tk.Label(buttons, font=("DejaVu Sans Mono", 22, "bold"), bg=color, fg="white")
            counter.pack()

            def countdown(left=EYE_REST_SECONDS):
                if not win.winfo_exists():
                    return
                if left <= 0:
                    win.destroy()
                    return
                counter.config(text=str(left))
                win.after(1000, countdown, left - 1)
            countdown()
        else:
            tk.Button(buttons, text="Take a break", width=14, command=win.destroy).pack(side="left", padx=6)
            tk.Button(buttons, text="I'm fine", width=14, command=win.destroy).pack(side="left", padx=6)
        win.update_idletasks()
        x = (win.winfo_screenwidth() - win.winfo_width()) // 2
        y = (win.winfo_screenheight() - win.winfo_height()) // 3
        win.geometry(f"+{x}+{y}")
        win.lift()
        win.focus_force()

    # --- keys ---
    def handle_key(k):
        global show_preview
        if k == "d":
            simulate_distraction()
        elif k == "b":
            simulate_long_session()
        elif k == "t":
            simulate_tired()
        elif k == "x":
            simulate_stuck()
        elif k == "c":
            reset_calibration()
        elif k == "v":
            show_preview = not show_preview
            preview["png"] = None
            layout()
        elif k == "p" and fake_camera:
            with lock:
                camera["present"] = not camera["present"]
                if not camera["present"]:
                    camera["facing"] = False
        elif k == "f" and fake_camera:
            with lock:
                camera["facing"] = not camera["facing"]
                if camera["facing"]:
                    camera["present"] = True
        elif k == "q":
            quit_app()

    def quit_app():
        global running
        running = False
        root.destroy()

    root.bind("<Key>", lambda e: handle_key(e.keysym.lower()))
    root.protocol("WM_DELETE_WINDOW", quit_app)

    # --- drawing helpers ---
    photo = {"img": None}

    def update_camera_view():
        data = preview["png"]
        if data:
            photo["img"] = tk.PhotoImage(data=data)  # keep a reference or Tk drops it
            cam_label.config(image=photo["img"], text="")
        elif fake_camera:
            with lock:
                fake = "FACE PRESENT" if camera["present"] else "NO FACE"
                fake += " + FACING" if camera["facing"] else ""
            cam_label.config(text=f"--no-camera mode\n\n{fake}\n\nP = presence   F = facing",
                             font=("DejaVu Sans Mono", 12), fg=FG)
        else:
            with lock:
                cam_label.config(text=camera["status"], fg=MUTED)

    def draw_expressions(expression, scores):
        expr_title.config(text=f"Expression: {expression}")
        expr_canvas.delete("all")
        width = PREVIEW_WIDTH - 24 - 100 - 40  # canvas - label column - number column
        for i, name in enumerate(EXPRESSION_NAMES):
            y = i * 18
            value = max(0.0, min(1.0, scores.get(name, 0.0)))
            expr_canvas.create_text(0, y + 8, text=name, anchor="w", fill=MUTED, font=("DejaVu Sans", 9))
            expr_canvas.create_rectangle(100, y + 3, 100 + width, y + 14, fill="#2b2f34", width=0)
            expr_canvas.create_rectangle(100, y + 3, 100 + int(width * value), y + 14, fill="#5b8def", width=0)
            expr_canvas.create_text(104 + width, y + 8, text=f"{value:.2f}", anchor="w", fill=FG,
                                    font=("DejaVu Sans Mono", 8))

    def draw_index(value):
        index_canvas.delete("all")
        color = "#1f7a4d" if value >= 70 else "#b26a00" if value >= 40 else "#b3261e"
        index_canvas.create_rectangle(0, 0, int(340 * value / 100), 22, fill=color, width=0)
        index_canvas.create_text(8, 11, text=f"{value}", anchor="w", fill="white",
                                 font=("DejaVu Sans Mono", 10, "bold"))

    def draw_timeline():
        timeline_canvas.delete("all")
        now = time.time()
        start = now - TIMELINE_SECONDS
        items = list(timeline)
        for i, (t, st) in enumerate(items):
            t_end = items[i + 1][0] if i + 1 < len(items) else now
            x0 = int(340 * (max(t, start) - start) / TIMELINE_SECONDS)
            x1 = int(340 * (t_end - start) / TIMELINE_SECONDS) + 1
            timeline_canvas.create_rectangle(x0, 0, x1, 18, fill=STATE_COLORS.get(st, "#4a5568"), width=0)

    def update_info():
        now_wall = time.time()
        with lock:
            b = dict(browser)
            c = dict(camera)
            cam = camera_text()
            yawn_count = sum(1 for t in yawns if now_wall - t <= YAWN_WINDOW)
        if calib["active"] and c["status"] == "ok" and not fake_camera:
            cam += " · calibrating, look at screen"
        domain = b["domain"]
        if b["updated"] and now_wall - b["updated"] > EXTENSION_STALE_SECONDS:
            domain += " (extension silent)"
        state = session["state"]
        color = STATE_COLORS.get(state, "#4a5568")

        bar.config(text=f"[State: {state}] | [Camera: {cam}] | [Domain: {domain}]", bg=color)
        paused = " (paused)" if state == "AFK" else ""
        stats.config(text=f"Session {fmt_clock(session['active_seconds'])}{paused} · "
                          f"Index {session['index']} · Focused {fmt_minutes(session['focused_seconds'])} · "
                          f"Distracted {fmt_minutes(session['distracted_seconds'])} · "
                          f"Mood {c['expression']}",
                     bg=color)
        hint.config(bg=color)

        if not show_preview:
            return
        live = c["present"] and not fake_camera
        state_big.config(text=state, fg=color if state not in ("AFK", "Starting") else FG)
        reason.config(text=explain(state, b["category"]))
        rows["Website"].config(text=b["domain"])
        rows["Category"].config(text=b["category"])
        rows["Attention"].config(text=c["reason"] if live else cam)
        rows["Eyes"].config(text=f"{c['gaze_text']}  (h {c['gaze_h']:.2f}, v {c['gaze_v']:+.2f})" if live else "-")
        rate = blink_rate(now_wall)
        rows["Blinks"].config(text=f"{rate:.0f} / min" if rate is not None and not fake_camera else "measuring...")
        rows["Yawns"].config(text=f"{yawn_count} in last 10 min")
        rows["Head pose"].config(text=f"yaw {c['yaw']:.2f}  pitch {c['pitch']:.2f}" if live else "-")
        rows["Tab switches"].config(text=f"{b['switches']} in last 5 min")
        if b["updated"]:
            ago = int(now_wall - b["updated"])
            ext = f"connected ({ago}s ago)" if ago <= EXTENSION_STALE_SECONDS else f"silent for {ago}s"
        else:
            ext = "waiting for first message"
        rows["Extension"].config(text=ext)
        rows["Session"].config(text=fmt_clock(session["active_seconds"]) + paused)
        rows["Focused"].config(text=fmt_clock(session["focused_seconds"]))
        rows["Distracted"].config(text=fmt_clock(session["distracted_seconds"]))
        if state == "Distracted" and not session["nudged"]:
            nudge = f"in {int(max(0, NUDGE_AFTER_SECONDS - session['distraction_streak']))}s"
        elif session["nudged"]:
            nudge = "shown"
        else:
            nudge = "-"
        rows["Nudge"].config(text=nudge)
        rows["Next break"].config(text=fmt_clock(BREAK_AFTER_SECONDS - session["since_break"]))
        draw_expressions(c["expression"], c["scores"])
        draw_index(session["index"])
        draw_timeline()

    # --- main loop ---
    last = [time.monotonic()]
    frame_count = [0]

    def loop():
        if not running:
            return
        if show_preview:
            update_camera_view()
        frame_count[0] += 1
        if frame_count[0] % 5 == 0:   # logic + info twice per second
            now = time.monotonic()
            dt, last[0] = now - last[0], now
            if fake_camera:
                with lock:
                    if camera["present"]:
                        camera["last_seen"] = time.time()
            while demo_requests:
                handle_key(demo_requests.pop(0))
            tick(dt)
            while events:
                show_popup(*events.pop(0))
            update_info()
        root.after(UI_REFRESH_MS, loop)

    loop()
    root.mainloop()
    running = False


def main():
    parser = argparse.ArgumentParser(description="Study Focus Engine")
    parser.add_argument("--no-camera", action="store_true", help="simulate the camera with keys P and F")
    parser.add_argument("--compact", action="store_true", help="start with only the small status bar")
    parser.add_argument("--camera-index", type=int, default=CAMERA_INDEX)
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()

    try:
        start_server(args.port)
    except OSError:
        print(f"Port {args.port} is busy. Close the other engine or use --port.")
        return
    print(f"Engine listening on http://127.0.0.1:{args.port}  (GET /status)")

    if args.no_camera:
        set_camera(status="ok", present=True, facing=True, reason="simulated", last_seen=time.time())
        calib["active"] = False
    else:
        threading.Thread(target=camera_loop, args=(args.camera_index,), daemon=True).start()

    run_ui(args.no_camera, start_global_hotkeys(), args.compact)


if __name__ == "__main__":
    main()
