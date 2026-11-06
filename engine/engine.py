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
import base64
import collections
import json
import os
import threading
import time
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import study

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

DOOM_SCROLL_PX = 8000            # scrolled pixels per minute (~8 screens) on a non-study site
DOOM_SWIPES = 4                  # or this many new videos per minute in a short-video feed
DOOM_AFTER_SECONDS = 60          # sustained this long -> "Doom-scrolling"
PHONE_AFTER_SECONDS = 3          # phone visible this long -> "On Phone"
PHONE_NUDGE_SECONDS = 20
PHONE_COOLDOWN = 5 * 60
PHONE_SCORE = 0.35               # object detector confidence
PHONE_EVERY_N_FRAMES = 3         # run the phone detector on every 3rd frame (saves CPU)
CONTEXT_WINDOW = 30 * 60         # context-switch stats over the last 30 minutes

HERE = os.path.dirname(os.path.abspath(__file__))
DASHBOARD_PATH = os.path.join(HERE, "dashboard.html")
MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/face_landmarker/"
             "face_landmarker/float16/1/face_landmarker.task")
MODEL_PATH = os.path.join(HERE, "face_landmarker.task")
PHONE_MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/object_detector/"
                   "efficientdet_lite0/float16/1/efficientdet_lite0.tflite")
PHONE_MODEL_PATH = os.path.join(HERE, "efficientdet_lite0.tflite")

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
    "Doom-scrolling": 0.0,
    "On Phone": 0.0,
}
STATE_COLORS = {
    "Doom-scrolling": "#8e24aa",
    "On Phone": "#c2185b",
    "Break": "#2e7d6b",
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
    "doomscroll": ("Doom-scroll alert", "#8e24aa"),
    "phone": ("Phone check", "#c2185b"),
    "pomodoro": ("Pomodoro", "#2e7d6b"),
}
DASHBOARD_URL = "http://127.0.0.1:8000/"
EXPRESSION_NAMES = ["Smile", "Frown", "Brow down", "Brow raise", "Jaw open", "Eyes closed"]

# ---------------- shared state ----------------
lock = threading.Lock()
running = True
show_preview = True
browser = {"domain": "waiting for extension", "category": "neutral", "idle": "active",
           "switches": 0, "updated": 0.0, "scroll_px": 0, "swipes": 0, "feed": False,
           "category_source": "list", "category_confidence": None, "category_pending": False}
jev = None            # goal-aware classifier (engine/classifier), None if unavailable
JevSurface = None
camera = {"status": "starting", "present": False, "facing": False, "reason": "-",
          "yaw": 0.0, "pitch": 0.0, "gaze_h": 0.5, "gaze_v": 0.0, "gaze_text": "-",
          "eyes_closed": False, "closed_since": None, "expression": "-",
          "scores": {n: 0.0 for n in EXPRESSION_NAMES},
          "phone": False, "phone_since": None, "phone_status": "starting", "yawns_total": 0,
          "last_seen": time.time(), "started": time.time()}
calib = {"yaw": None, "pitch": None, "gaze_h": None, "gaze_v": None, "samples": [], "active": True}
blinks = collections.deque()          # timestamps
yawns = collections.deque()           # timestamps
expression_log = collections.deque()  # (timestamp, label)
presence_log = collections.deque()    # (timestamp, present) from the engine tick
session = {"active_seconds": 0.0, "focused_seconds": 0.0, "distracted_seconds": 0.0,
           "since_break": 0.0, "distraction_streak": 0.0, "nudged": False,
           "doom_streak": 0.0, "doom_alerted": False, "on_phone": False,
           "state": "Starting", "index": 100}
switch_log = collections.deque()      # timestamps of website/app switches
recent_events = collections.deque(maxlen=20)  # popups, also shown as toasts on the dashboard
last_alert = {}                       # wellbeing popup kind -> time shown
history = collections.deque()         # (timestamp, score, weight_seconds)
timeline = collections.deque()        # (timestamp, state) for the colored strip
preview = {"png": None}               # latest annotated camera frame (base64 PNG, memory only)
events = []                           # popups for the UI: (kind, message)
demo_requests = []                    # filled by global hotkeys (other thread)


# ---------------- decision engine ----------------
def emit(kind, message):
    """Queue a popup; the window shows it and the dashboard gets it as a toast."""
    events.append((kind, message))


def publish(kind, message):
    title = POPUP_STYLE.get(kind, ("Study Focus", ""))[0]
    recent_events.append({"id": f"{time.time():.3f}", "kind": kind, "title": title, "text": message})


def assess(category, idle, switches, present, facing, missing_seconds, on_phone=False, doom=False):
    """The decision matrix: browser category + camera state -> engine state."""
    if idle == "locked":
        return "AFK"
    if on_phone:
        return "On Phone"
    if not present:
        return "AFK" if missing_seconds >= AFK_AFTER_SECONDS else "Away"
    if doom:
        return "Doom-scrolling"
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
        study.record_event(kind)
        emit(kind, message)


def context_stats(now):
    """(switches in the last 30 min, average minutes spent per site/app before switching)."""
    with lock:
        trim(switch_log, now, CONTEXT_WINDOW)
        times = list(switch_log)
    if len(times) < 2:
        return len(times), None
    gaps = [b - a for a, b in zip(times, times[1:])] + [now - times[-1]]
    return len(times), round(sum(gaps) / len(gaps) / 60, 1)


def is_doom_scrolling(b, now):
    if b["category"] == "productive" or b["idle"] != "active" or now - b["updated"] > 20:
        return False
    return b["scroll_px"] >= DOOM_SCROLL_PX or (b["feed"] and b["swipes"] >= DOOM_SWIPES)


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
    sv = study.session_view()
    on_break = bool(sv and sv["phase"] == "break")   # Pomodoro break: no distraction alerts

    # doom-scrolling: lots of scrolling / short videos on a non-study site, sustained
    if is_doom_scrolling(b, now):
        session["doom_streak"] += dt
    else:
        session["doom_streak"] = max(0.0, session["doom_streak"] - 2 * dt)
        if session["doom_streak"] == 0:
            session["doom_alerted"] = False
    doom = session["doom_streak"] >= DOOM_AFTER_SECONDS

    # phone in hand (seen by the object detector for a few seconds)
    on_phone = bool(c["phone_since"] and now - c["phone_since"] >= PHONE_AFTER_SECONDS)
    if on_phone and not session["on_phone"] and not on_break:
        study.record_event("phone")              # one pickup
    session["on_phone"] = on_phone

    state = assess(b["category"], b["idle"], b["switches"], c["present"] or c["phone"],
                   c["facing"], now - c["last_seen"], on_phone, doom)
    session["state"] = state
    timeline.append((now, "Break" if on_break else state))
    trim(timeline, now, TIMELINE_SECONDS)

    for kind, message in study.tick(dt, {
            "state": state, "index": session["index"], "domain": b["domain"],
            "category": b["category"], "expression": c["expression"],
            "blink_rate": blink_rate(now), "yawns_total": c["yawns_total"]}):
        emit(kind, message)

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
    if state in ("Distracted", "Doom-scrolling", "On Phone"):
        session["distracted_seconds"] += dt

    if on_break:
        session["distraction_streak"] = 0
    elif state == "Distracted":
        session["distraction_streak"] += dt
        if session["distraction_streak"] >= NUDGE_AFTER_SECONDS and not session["nudged"]:
            session["nudged"] = True
            minutes = max(1, round(session["distraction_streak"] / 60))
            study.record_event("nudge")
            emit("nudge", f"You've been on {b['domain']} for {minutes} min.\n"
                          "Ready to get back to studying?")
    elif state != "Away":  # a short glance away doesn't reset the streak
        session["distraction_streak"] = 0
        session["nudged"] = False

    if doom and not session["doom_alerted"] and not on_break:
        session["doom_alerted"] = True
        study.record_event("doom")
        what = "short videos" if b["feed"] else "the feed"
        emit("doomscroll", f"You've been scrolling {what} on {b['domain']}\n"
                           "non-stop for a minute. That's doom-scrolling.\n"
                           "Close it and get back to your goal?")

    if (on_phone and c["phone_since"] and now - c["phone_since"] >= PHONE_NUDGE_SECONDS
            and not on_break and now - last_alert.get("phone", -1e9) >= PHONE_COOLDOWN):
        last_alert["phone"] = now
        emit("phone", "Your phone has been in your hand for 20 seconds.\n"
                      "Put it face down, out of reach,\nand get back to studying.")

    if session["since_break"] >= BREAK_AFTER_SECONDS:
        session["since_break"] = 0
        if not sv:  # during a study session the Pomodoro timer handles breaks
            emit("break", "You've been studying for 50 minutes.\n"
                          "Look at something ~6 m away for 20 seconds.")

    if not on_break:
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
    study.record_event("nudge")
    emit("nudge", "20 minutes on distracting sites.\n"
                  "Your focus is dropping. Switch back to your subject?")


def simulate_long_session():
    """Demo key B: pretend 50 minutes of study have passed."""
    session["since_break"] = BREAK_AFTER_SECONDS
    if study.session_view():  # inside a study session, B ends the current pomodoro instead
        emit("break", "You've been studying for 50 minutes.\n"
                      "Look at something ~6 m away for 20 seconds.")


def simulate_tired():
    study.record_event("tired")
    emit("tired", "You yawned 3 times in 10 minutes.\n"
                  "Your brain needs a break, or switch to\nan easier subject for a while.")


def simulate_stuck():
    study.record_event("stuck")
    emit("stuck", "You look stuck or frustrated.\n"
                  "Try an easier example, re-read the basics,\nor open the study tips.")


def simulate_phone():
    study.record_event("phone")
    emit("phone", "Your phone has been in your hand for 20 seconds.\n"
                  "Put it face down, out of reach,\nand get back to studying.")


def simulate_doom():
    study.record_event("doom")
    emit("doomscroll", "You've been scrolling short videos on youtube.com\n"
                       "non-stop for a minute. That's doom-scrolling.\n"
                       "Close it and get back to your goal?")


DEMO_ACTIONS = {"d": simulate_distraction, "b": simulate_long_session, "t": simulate_tired,
                "x": simulate_stuck, "m": simulate_phone, "s": simulate_doom}


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
        "Doom-scrolling": "endless scrolling / short videos on a non-study site",
        "On Phone": "phone in your hand (camera)",
        "Starting": "waiting for data",
    }
    return reasons.get(state, category)


def snooze():
    session["distraction_streak"] = -SNOOZE_SECONDS + NUDGE_AFTER_SECONDS
    session["nudged"] = False


def init_classifier():
    """Optional goal-aware classifier. Any failure leaves the extension's list categories in charge."""
    global jev, JevSurface
    try:
        from classifier import Surface, build_default
        jev, JevSurface = build_default(), Surface
    except Exception as e:
        print(f"Goal-aware classifier unavailable ({type(e).__name__}); using the extension's site lists.")


def judge(data, domain):
    """Goal-aware verdict for the active tab, or None to keep the extension's list category.
    Only during a study session (the goal is the context). Never blocks: Jev answers in the background."""
    sv = study.session_view()
    if jev is None or not sv or data.get("category") == "other":
        return None
    surface = JevSurface("browser", "Chrome", None, domain, str(data.get("path") or "")[:200] or None,
                         str(data.get("title") or "")[:200] or None, bool(data.get("incognito")))
    try:
        return jev.classify(f"{sv['subject']}: {sv['goal']}", surface)
    except Exception:
        return None


def category_text(b):
    """'distraction (Jev 0.97)' / 'productive (list)' for the info panel."""
    src, conf = b["category_source"], b["category_confidence"]
    how = {"jev": f"Jev {conf:.2f}" if conf is not None else "Jev", "cache": "Jev, cached",
           "override": "override", "private": "list, private"}.get(src, "list")
    return f"{b['category']} ({how}{', Jev pending' if b['category_pending'] else ''})"


def snapshot():
    with lock:
        snap = {"state": session["state"], "index": session["index"],
                "domain": browser["domain"], "category": browser["category"],
                "camera": camera_text(), "expression": camera["expression"]}
    sv = study.session_view()
    snap["focus_mode"] = bool(sv and sv["phase"] == "work")
    snap["block"] = snap["focus_mode"] and snap["category"] == "distraction"
    snap["subject"] = sv["subject"] if sv else ""
    snap["goal"] = sv["goal"] if sv else ""
    return snap


def api_state():
    """Everything the dashboard shows, in one JSON."""
    now = time.time()
    rate = blink_rate(now)
    switches, span = context_stats(now)
    with lock:
        b = dict(browser)
        c = dict(camera)
        cam = camera_text()
        yawn_count = sum(1 for t in yawns if now - t <= YAWN_WINDOW)
    state = session["state"]
    live = {
        "state": state, "color": STATE_COLORS.get(state, "#4a5568"), "explain": explain(state, b["category"]),
        "index": session["index"], "domain": b["domain"], "category": b["category"],
        "category_source": b["category_source"], "category_confidence": b["category_confidence"],
        "category_pending": b["category_pending"], "jev_online": bool(jev and jev.jev_online),
        "extension_ok": bool(b["updated"]) and now - b["updated"] <= EXTENSION_STALE_SECONDS,
        "camera": cam, "camera_status": c["status"], "attention": c["reason"],
        "calibrating": calib["active"] and c["status"] == "ok",
        "gaze": c["gaze_text"], "expression": c["expression"], "scores": c["scores"],
        "blink_rate": round(rate) if rate is not None else None, "yawns_10min": yawn_count,
        "phone": session["on_phone"], "phone_status": c["phone_status"],
        "doom_level": round(min(1.0, session["doom_streak"] / DOOM_AFTER_SECONDS), 2),
        "scroll_px": b["scroll_px"], "swipes": b["swipes"], "feed": b["feed"],
        "switches_30min": switches, "attention_span_min": span,
        "active_seconds": round(session["active_seconds"]),
        "focused_seconds": round(session["focused_seconds"]),
        "distracted_seconds": round(session["distracted_seconds"]),
        "has_frame": preview["png"] is not None,
    }
    return {"live": live, "session": study.session_view(), "profile": study.profile_view(),
            "events": list(recent_events)}


def camera_text():
    s = camera["status"]
    if s != "ok":
        return s
    if not camera["present"]:
        return "No Face"
    return "Present & Facing" if camera["facing"] else "Present, Looking Away"


# ---------------- local bridge (HTTP) ----------------
class Handler(BaseHTTPRequestHandler):
    """Only this machine's dashboard and the Chrome extension may talk to the engine.
    Other websites can't read camera frames or state (no CORS headers, Origin + Host checks)."""

    def allowed(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost"):
            return False
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        return origin.startswith("chrome-extension://") or origin.split("://")[-1].split(":")[0] in (
            "127.0.0.1", "localhost")

    def send_body(self, code, body, content_type):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, code, obj):
        self.send_body(code, json.dumps(obj).encode(), "application/json")

    def read_json(self):
        if "application/json" not in (self.headers.get("Content-Type") or ""):
            return None
        try:
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length) or b"{}")
            return data if isinstance(data, dict) else None
        except ValueError:
            return None

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        if not self.allowed():
            return self.send_json(403, {"error": "forbidden"})
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            try:
                with open(DASHBOARD_PATH, "rb") as f:
                    self.send_body(200, f.read(), "text/html; charset=utf-8")
            except OSError:
                self.send_json(404, {"error": "dashboard.html missing"})
        elif path == "/status":
            self.send_json(200, snapshot())
        elif path == "/api/state":
            self.send_json(200, api_state())
        elif path == "/api/frame":
            data = preview["png"]
            if data:
                self.send_body(200, base64.b64decode(data), "image/png")
            else:
                self.send_json(404, {"error": "no frame"})
        elif path == "/api/reports":
            self.send_json(200, study.report_list())
        elif path.startswith("/api/reports/"):
            report = study.get_report(path.rsplit("/", 1)[-1])
            self.send_json(200 if report else 404, report or {"error": "not found"})
        else:
            self.send_json(404, {"error": "not found"})

    def do_POST(self):
        if not self.allowed():
            return self.send_json(403, {"error": "forbidden"})
        data = self.read_json()
        if data is None:
            return self.send_json(400, {"error": "send JSON with Content-Type: application/json"})
        path = self.path.split("?")[0]

        if path == "/activity":
            now = time.time()
            domain = str(data.get("domain", "-"))[:80]
            verdict = judge(data, domain)   # outside the lock; never blocks
            with lock:
                if domain != browser["domain"] and browser["updated"]:
                    switch_log.append(now)
                browser["domain"] = domain
                if data.get("category") in ("productive", "distraction", "neutral", "other"):
                    browser["category"] = data["category"]
                # Jev/cache/override replace the list category; local guesses never do (list stays)
                browser.update(category_source="list", category_confidence=None, category_pending=False)
                if verdict:
                    browser["category_pending"] = verdict.pending
                    if verdict.source == "private":
                        browser["category_source"] = "private"
                    elif verdict.category and not verdict.pending and verdict.source in ("jev", "cache", "override"):
                        browser.update(category=verdict.category, category_source=verdict.source,
                                       category_confidence=verdict.confidence)
                if data.get("idle") in ("active", "idle", "locked"):
                    browser["idle"] = data["idle"]
                for key in ("switches", "scroll_px", "swipes"):
                    try:
                        browser[key] = max(0, int(data.get(key, 0)))
                    except (TypeError, ValueError):
                        browser[key] = 0
                browser["feed"] = bool(data.get("feed", False))
                browser["updated"] = now
            self.send_json(200, snapshot())
        elif path == "/api/session/start":
            ok, message = study.start_session(str(data.get("subject", "")), str(data.get("goal", "")),
                                              data.get("work", 25), data.get("break", 5))
            self.send_json(200 if ok else 409, {"ok": ok, "message": message})
        elif path == "/api/session/stop":
            report = study.stop_session(bool(data.get("goal_done")))
            self.send_json(200 if report else 409, report or {"error": "no session"})
        elif path == "/api/session/break":
            self.send_json(200, {"ok": study.start_break()})
        elif path == "/api/session/resume":
            self.send_json(200, {"ok": study.resume_work()})
        elif path == "/api/tip":
            self.send_json(200, study.study_tip(str(data.get("mode", "explain"))))
        elif path == "/api/override":
            study.record_event("override")
            self.send_json(200, {"ok": True})
        elif path == "/api/calibrate":
            reset_calibration()
            self.send_json(200, {"ok": True})
        elif path.startswith("/api/demo/"):
            key = path.rsplit("/", 1)[-1]
            if key in DEMO_ACTIONS:
                demo_requests.append(key)
                self.send_json(200, {"ok": True})
            else:
                self.send_json(404, {"error": "unknown demo"})
        else:
            self.send_json(404, {"error": "not found"})

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
                camera["yawns_total"] += 1
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


def download(url, path):
    if not os.path.exists(path):
        urllib.request.urlretrieve(url, path + ".part")
        os.replace(path + ".part", path)


def make_phone_detector(vision, mp_python):
    """Object detector limited to 'cell phone'. Returns None if the model can't be loaded."""
    try:
        download(PHONE_MODEL_URL, PHONE_MODEL_PATH)
        options = vision.ObjectDetectorOptions(
            base_options=mp_python.BaseOptions(model_asset_path=PHONE_MODEL_PATH),
            running_mode=vision.RunningMode.VIDEO,
            max_results=2, score_threshold=PHONE_SCORE,
            category_allowlist=["cell phone"])
        detector = vision.ObjectDetector.create_from_options(options)
        set_camera(phone_status="on")
        return detector
    except Exception as e:
        set_camera(phone_status=f"off ({str(e)[:60]})")
        return None


def detect_phone(detector, image, phone_votes):
    """Returns the phone box (x, y, w, h) in pixels or None, and updates the shared state."""
    result = detector.detect_for_video(image, int(time.monotonic() * 1000))
    box = None
    if result.detections:
        b = result.detections[0].bounding_box
        box = (b.origin_x, b.origin_y, b.width, b.height)
    phone_votes.append(box is not None)
    seen = sum(phone_votes) >= 2
    with lock:
        if seen and camera["phone_since"] is None:
            camera["phone_since"] = time.time()
        elif not seen:
            camera["phone_since"] = None
        camera["phone"] = seen
    return box


def draw_overlay(cv2, frame, lm, facing, reason, phone_box=None):
    """Draw face points, eyes, gaze arrow, phone box, the center band and the verdict (in memory only)."""
    h, w = frame.shape[:2]
    margin = int(w * (1 - CENTER_BAND) / 2)
    for x in (margin, w - margin):
        cv2.line(frame, (x, 0), (x, h), (180, 180, 180), 1)
    if phone_box:
        x, y, bw, bh = phone_box
        cv2.rectangle(frame, (x, y), (x + bw, y + bh), (160, 30, 220), 3)
        cv2.putText(frame, "PHONE", (x, max(70, y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                    (160, 30, 220), 2, cv2.LINE_AA)

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
    phone_detector = make_phone_detector(vision, mp_python)
    phone_votes = collections.deque(maxlen=4)
    phone_box = None
    frame_number = 0

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

        frame_number += 1
        if phone_detector and frame_number % PHONE_EVERY_N_FRAMES == 0:
            phone_box = detect_phone(phone_detector, image, phone_votes)

        if show_preview:
            store_preview(cv2, draw_overlay(cv2, frame, lm, facing, reason, phone_box))

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
    names = ["Study", "Website", "Category", "Attention", "Eyes", "Blinks", "Yawns", "Phone",
             "Doom-scroll", "Context", "Extension", "Active time", "Focused", "Distracted", "Nudge",
             "Next break"]
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

    keys = ("Demo: D distraction · B break · T tired · X stuck · M phone · S doom-scroll"
            "  |  C calibrate · V live view · Q quit")
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
        elif kind == "tired" and study.session_view():
            tk.Button(buttons, text="Start break now", width=14,
                      command=lambda: (study.start_break(), win.destroy())).pack(side="left", padx=6)
            tk.Button(buttons, text="I'm fine", width=14, command=win.destroy).pack(side="left", padx=6)
        elif kind == "stuck":
            tk.Button(buttons, text="Study tips", width=14,
                      command=lambda: (webbrowser.open(DASHBOARD_URL + "#help"), win.destroy())
                      ).pack(side="left", padx=6)
            tk.Button(buttons, text="I'm fine", width=14, command=win.destroy).pack(side="left", padx=6)
        elif kind in ("tired",):
            tk.Button(buttons, text="Take a break", width=14, command=win.destroy).pack(side="left", padx=6)
            tk.Button(buttons, text="I'm fine", width=14, command=win.destroy).pack(side="left", padx=6)
        else:
            tk.Button(buttons, text="Got it", width=14, command=win.destroy).pack(side="left", padx=6)
            tk.Button(buttons, text="Open dashboard", width=14,
                      command=lambda: (webbrowser.open(DASHBOARD_URL), win.destroy())).pack(side="left", padx=6)
        win.update_idletasks()
        x = (win.winfo_screenwidth() - win.winfo_width()) // 2
        y = (win.winfo_screenheight() - win.winfo_height()) // 3
        win.geometry(f"+{x}+{y}")
        win.lift()
        win.focus_force()

    # --- keys ---
    def handle_key(k):
        global show_preview
        if k in DEMO_ACTIONS:
            DEMO_ACTIONS[k]()
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
        stats.config(text=f"Active {fmt_clock(session['active_seconds'])}{paused} · "
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
        rows["Category"].config(text=category_text(b))
        rows["Attention"].config(text=c["reason"] if live else cam)
        rows["Eyes"].config(text=f"{c['gaze_text']}  (h {c['gaze_h']:.2f}, v {c['gaze_v']:+.2f})" if live else "-")
        rate = blink_rate(now_wall)
        rows["Blinks"].config(text=f"{rate:.0f} / min" if rate is not None and not fake_camera else "measuring...")
        rows["Yawns"].config(text=f"{yawn_count} in last 10 min")
        sv = study.session_view()
        if sv:
            left = sv["phase_left"]
            rows["Study"].config(text=f"{sv['subject'][:18]} · {sv['phase']} {left // 60}:{left % 60:02d}"
                                      f" · {sv['pomodoros']} pomodoros")
        else:
            rows["Study"].config(text="no session (start one in the dashboard)")
        if c["phone_status"] != "on" and not fake_camera:
            rows["Phone"].config(text=f"detector {c['phone_status']}")
        else:
            rows["Phone"].config(text="IN HAND" if session["on_phone"] else ("seen" if c["phone"] else "not seen"))
        doom = min(1.0, session["doom_streak"] / DOOM_AFTER_SECONDS)
        rows["Doom-scroll"].config(text=f"{int(doom * 100)}%  "
                                        f"({b['scroll_px'] // 1000}k px, {b['swipes']} videos /min)")
        switches, span = context_stats(now_wall)
        rows["Context"].config(text=f"{switches} switches / 30 min · "
                                    + (f"{span} min per task" if span is not None else "steady"))
        if b["updated"]:
            ago = int(now_wall - b["updated"])
            ext = f"connected ({ago}s ago)" if ago <= EXTENSION_STALE_SECONDS else f"silent for {ago}s"
        else:
            ext = "waiting for first message"
        rows["Extension"].config(text=ext)
        rows["Active time"].config(text=fmt_clock(session["active_seconds"]) + paused)
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
                kind, message = events.pop(0)
                publish(kind, message)
                show_popup(kind, message)
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

    init_classifier()
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
