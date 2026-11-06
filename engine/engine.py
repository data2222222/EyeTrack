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
    C  guided screen calibration (follow five dots with your eyes)
    V  show / hide the live view
    Q  quit
Study sessions are started in the live view: subject, goal, work/break minutes, Start / Break / Stop, History.
Optional global hotkeys (if `pip install pynput`): Ctrl+Shift+D, Ctrl+Shift+B
"""
import argparse
import collections
from contextlib import ExitStack
import json
import os
import shutil
import ssl
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Optional for app monitoring; the rest of the engine remains importable if an
# optional platform dependency is unavailable.
try:
    import psutil
except ImportError:
    psutil = None
try:
    import pygetwindow
except ImportError:
    pygetwindow = None

import phone_detection
import study
import tracking

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

# App checks run on a worker thread so process enumeration cannot stall the UI
# or camera path. Tokens match process names/executable names case-insensitively.
APP_BLACKLIST = ["roblox", "tlauncher", "javaw", "steam", "discord"]
APP_MONITOR_INTERVAL = 1.0

CAMERA_INDEX = 0
CAMERA_FPS = 15                  # high enough to catch blinks
CAMERA_READ_TIMEOUT = 5.0        # stop a disconnected/stalled feed with a useful error

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
PHONE_SCORE = phone_detection.RAW_SCORE_THRESHOLD    # lenient raw threshold; PhoneTracker filters
PHONE_EVERY_N_FRAMES = phone_detection.DETECT_EVERY_N_FRAMES  # detector cadence (CPU vs. latency)
CONTEXT_WINDOW = 30 * 60         # context-switch stats over the last 30 minutes

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/face_landmarker/"
             "face_landmarker/float16/1/face_landmarker.task")
MODEL_PATH = os.path.join(HERE, "face_landmarker.task")
PHONE_MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/object_detector/"
                   "efficientdet_lite0/float16/1/efficientdet_lite0.tflite")
PHONE_MODEL_PATH = os.path.join(HERE, "efficientdet_lite0.tflite")

# Tk fonts; run_ui replaces these once Tk can list the installed families (see pick_fonts)
UI_FONT, MONO_FONT = "Helvetica", "Courier"
FONT_PREFERENCES = {   # sys.platform prefix -> (UI families, monospace families), best first
    "win": (("Segoe UI",), ("Consolas",)),
    "darwin": (("SF Pro Text", "Helvetica Neue"), ("Menlo",)),
    "linux": (("DejaVu Sans",), ("DejaVu Sans Mono",)),
}

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
    "appblock": ("Distracting app detected", "#b3261e"),
    "nudge": ("Focus check", "#b3261e"),
    "break": ("Eye-rest break", "#1d6b7a"),
    "tired": ("Feeling tired?", "#5b3a8a"),
    "stuck": ("Stuck?", "#b26a00"),
    "doomscroll": ("Doom-scroll alert", "#8e24aa"),
    "phone": ("Phone check", "#c2185b"),
    "pomodoro": ("Pomodoro", "#2e7d6b"),
}
EXPRESSION_NAMES = ["Smile", "Frown", "Brow down", "Brow raise", "Jaw open", "Eyes closed"]

# ---------------- shared state ----------------
lock = threading.Lock()
running = True
camera_controller = None
app_monitor_stop = threading.Event()
app_monitor_worker = None
app_monitor_previous_running = set()
app_monitor_previous_foreground = set()
show_preview = True
browser = {"domain": "waiting for extension", "category": "neutral", "idle": "active",
           "switches": 0, "updated": 0.0, "scroll_px": 0, "swipes": 0, "feed": False,
           "category_source": "list", "category_confidence": None, "category_pending": False}
jev = None            # goal-aware classifier (engine/classifier), None if unavailable
JevSurface = None
camera = {"status": "starting", "present": False, "facing": False, "reason": "-",
          "yaw": 0.0, "pitch": 0.0, "gaze_h": 0.5, "gaze_v": 0.0, "gaze_text": "-",
          "eyes_closed": False, "closed_since": None, "expression": "-", "looking_down": False,
          "scores": {n: 0.0 for n in EXPRESSION_NAMES},
          "phone": False, "phone_since": None, "phone_status": "starting", "phone_confidence": 0.0,
          "yawns_total": 0,
          "last_seen": time.time(), "started": time.time()}
calib = tracking.Calibration()
blinks = collections.deque()          # timestamps
yawns = collections.deque()           # timestamps
expression_log = collections.deque()  # (timestamp, label)
presence_log = collections.deque()    # (timestamp, present) from the engine tick
session = {"active_seconds": 0.0, "focused_seconds": 0.0, "distracted_seconds": 0.0,
           "since_break": 0.0, "distraction_streak": 0.0, "nudged": False,
           "doom_streak": 0.0, "doom_alerted": False, "on_phone": False,
           "state": "Starting", "index": 100}
switch_log = collections.deque()      # timestamps of website/app switches
last_alert = {}                       # wellbeing popup kind -> time shown
history = collections.deque()         # (timestamp, score, weight_seconds)
timeline = collections.deque()        # (timestamp, state) for the colored strip
preview = {"png": None}               # latest annotated camera frame (base64 PNG, memory only)
events = []                           # popups for the UI: (kind, message)
demo_requests = []                    # filled by global hotkeys (other thread)


# ---------------- decision engine ----------------
def emit(kind, message):
    """Queue a popup for the window."""
    events.append((kind, message))


# ---------------- desktop app monitoring / distraction alerts ----------------
def _matching_blacklist(text):
    """Return blacklist tokens contained in a process name, path, or window title."""
    haystack = (text or "").casefold()
    return [token for token in APP_BLACKLIST if token.casefold() in haystack]


def check_blocklisted_apps():
    """Return matching process identities and blacklist tokens in the active title."""
    running_matches = set()  # (pid, process name, matching blacklist token)
    foreground_matches = set()
    if psutil is not None:
        try:
            for proc in psutil.process_iter(["name", "exe"]):
                try:
                    info = proc.info
                    process_name = info.get("name") or os.path.basename(info.get("exe") or "")
                    text = " ".join((process_name, info.get("exe") or ""))
                    for token in _matching_blacklist(text):
                        running_matches.add((proc.pid, process_name, token))
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
        except Exception as exc:
            print(f"Process scan unavailable ({type(exc).__name__}).")

    if pygetwindow is not None:
        try:
            window = pygetwindow.getActiveWindow()
            if window is not None:
                foreground_matches.update(_matching_blacklist(getattr(window, "title", "")))
        except Exception:
            pass  # Process scanning remains available if foreground lookup fails.
    return running_matches, foreground_matches


def app_monitor_loop(stop_event):
    """Alert on newly running or foreground blacklisted apps; allow break time."""
    global app_monitor_previous_running, app_monitor_previous_foreground
    while running and not stop_event.is_set():
        view = study.session_view()
        if view and view.get("phase") == "break":
            # Defer checks during breaks; apps still open are detected when work resumes.
            stop_event.wait(APP_MONITOR_INTERVAL)
            continue

        running_apps, foreground_apps = check_blocklisted_apps()
        newly_running = running_apps - app_monitor_previous_running
        newly_foreground = foreground_apps - app_monitor_previous_foreground
        newly_running_tokens = {token for _, _, token in newly_running}
        for pid, process_name, token in sorted(newly_running):
            emit("appblock", f"Detected process '{process_name}' (PID {pid}); its name matches '{token}'.\n"
                             "Close it and return to your task.")
        for token in sorted(newly_foreground - newly_running_tokens):
            emit("appblock", f"'{token}' is in the foreground. Close it and return to your task.")
        app_monitor_previous_running = running_apps
        app_monitor_previous_foreground = foreground_apps
        stop_event.wait(APP_MONITOR_INTERVAL)


def start_app_monitor():
    """Start the app monitor without blocking the UI or webcam loop."""
    global app_monitor_worker
    if psutil is None and pygetwindow is None:
        print("App monitoring unavailable; install psutil and pygetwindow from requirements.txt.")
        return
    app_monitor_stop.clear()
    app_monitor_worker = threading.Thread(target=app_monitor_loop, args=(app_monitor_stop,),
                                          name="app-monitor", daemon=True)
    app_monitor_worker.start()


def stop_app_monitor():
    """Stop and join the app monitor during shutdown."""
    app_monitor_stop.set()
    if app_monitor_worker is not None:
        app_monitor_worker.join(timeout=2.0)


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
    on_break = not bool(sv and sv["phase"] == "work")

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
            "blink_rate": blink_rate(now), "yawns_total": c["yawns_total"],
            "browser_age": max(0, now - b["updated"]) if b["updated"] else None,
            "camera_category": ("present" if c["present"] else "no_face") if c["status"] == "ok" else "unavailable",
            "camera_observed_at": c.get("observed_at"),
            "attention": tracking.attention_bucket(c, sv["mode"] if sv else "pc", time.monotonic(), on_phone)}):
        emit(kind, message)

    sv = study.session_view()
    if not sv or sv["phase"] != "work":
        session["distraction_streak"] = 0
        session["nudged"] = False
        session["doom_streak"] = 0
        session["doom_alerted"] = False
        return

    session["active_seconds"] = sv["active_seconds"]
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

    # Expression/fatigue heuristics remain diagnostic rather than session interventions.
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


def camera_text():
    s = camera["status"]
    if s != "ok":
        return s
    if not camera["present"]:
        return "No Face"
    return "Present & Facing" if camera["facing"] else "Present, Looking Away"


# ---------------- local bridge (HTTP) ----------------
class Handler(BaseHTTPRequestHandler):
    """Only this machine and the Chrome extension may talk to the engine.
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
        if path == "/status":
            self.send_json(200, snapshot())
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
        elif path == "/api/override":
            study.record_event("override")
            self.send_json(200, {"ok": True})
        else:
            self.send_json(404, {"error": "not found"})

    def log_message(self, *args):
        pass


def start_server(port):
    """Start the local bridge in a daemon thread; port 0 picks a free one (see server.server_address)."""
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


# ---------------- face analysis ----------------
RIGHT_EYE = [33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246]
LEFT_EYE = [362, 382, 381, 380, 374, 373, 390, 249, 263, 466, 388, 387, 386, 385, 384, 398]
LEFT_IRIS, RIGHT_IRIS = 473, 468  # anatomical sides; Face Landmarker gives 478 points


def set_camera(**values):
    with lock:
        camera.update(values)


def head_pose(lm, aspect=1.0):
    return tracking.head_pose(lm, aspect)


def eye_gaze(lm, bs, aspect=1.0):
    return tracking.eye_gaze(lm, bs, aspect)


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
    _, bounds = calib.profile()
    (lo_h, hi_h), (lo_v, hi_v) = bounds[2:]
    parts = []
    if gaze_v > hi_v:
        parts.append("down")
    elif gaze_v < lo_v:
        parts.append("up")
    if gaze_h > hi_h:
        parts.append("right")
    elif gaze_h < lo_h:
        parts.append("left")
    return "-".join(parts) if parts else "center"


def head_or_eyes_down(pitch, gaze_h, gaze_v):
    """Head tipped or eyes lowered past the calibrated screen area (reading paper, a desk, a lap)."""
    _, bounds = calib.profile()
    return pitch > bounds[1][1] or "down" in gaze_direction(gaze_h, gaze_v)


def attention(nose, yaw, pitch, gaze_h, gaze_v, eyes_closed):
    """Is the user looking at the screen? Returns (bool, reason)."""
    if eyes_closed:
        return False, "eyes closed"
    _, bounds = calib.profile()
    if not bounds[0][0] <= yaw <= bounds[0][1]:
        return False, "head turned away"
    if not bounds[1][0] <= pitch <= bounds[1][1]:
        return False, "head tilted"
    direction = gaze_direction(gaze_h, gaze_v)
    if direction != "center":
        return False, f"eyes looking {direction}"
    return True, "eyes on screen"


def reset_calibration(guided=False):
    calib.start(guided=guided)


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


def analyze_face(lm, bs, st, expression_votes, aspect=1.0):
    """All per-frame analysis for one detected face; updates shared camera state."""
    now = time.time()
    stamp = time.monotonic()
    label, scores = read_expression(bs)
    eyes_closed = min(bs.get("eyeBlinkLeft", 0), bs.get("eyeBlinkRight", 0)) > EYES_CLOSED_LEVEL
    track_blinks_and_yawns(now, eyes_closed, scores["Jaw open"], st)

    generation = calib.view()["generation"]
    if st.get("calibration_generation") != generation:
        st["filter"] = tracking.AttentionFilter()
        st["calibration_generation"] = generation
    smoother = st.setdefault("filter", tracking.AttentionFilter())
    quality = tracking.landmark_quality(lm, aspect)
    yaw, pitch, gaze_h, gaze_v = camera["yaw"], camera["pitch"], camera["gaze_h"], camera["gaze_v"]
    if quality is None:
        try:
            nose, yaw, pitch = head_pose(lm, aspect)
            if not eyes_closed:
                gaze_h, gaze_v = eye_gaze(lm, bs, aspect)
        except ValueError as exc:
            quality = str(exc)
    if quality:
        calib.interrupt(quality)
        st.pop("filter", None)
        facing, reason = False, quality
    elif eyes_closed:
        # Freeze the last good gaze through normal blinks; don't filter bad iris points.
        if st["closed_since"] is not None and now - st["closed_since"] < BLINK_MAX_SECONDS:
            smoother.pending = None
            facing, reason = smoother.facing, "blinking"
        else:
            facing, reason = smoother.update(False, "eyes closed", stamp)
    else:
        values = (yaw, pitch, gaze_h, gaze_v)
        # Either eyelid closing makes the iris position unsuitable for calibration.
        if max(bs.get("eyeBlinkLeft", 0), bs.get("eyeBlinkRight", 0)) < .35:
            calib.add(values, stamp)
        yaw, pitch, gaze_h, gaze_v = smoother.smooth(values, stamp)
        state = calib.view()
        if state["active"]:
            facing, reason = True, "calibrating: " + state["message"]
        else:
            looking, detail = attention(nose, yaw, pitch, gaze_h, gaze_v, False)
            facing, reason = smoother.update(looking, detail, stamp)
    expression_votes.append(label)
    expression = collections.Counter(expression_votes).most_common(1)[0][0]

    with lock:
        expression_log.append((now, expression))
        camera.update(present=True, facing=facing, reason=reason, yaw=yaw, pitch=pitch,
                      gaze_h=gaze_h, gaze_v=gaze_v,
                      gaze_text="uncertain" if quality else ("closed" if eyes_closed else gaze_direction(gaze_h, gaze_v)),
                      eyes_closed=eyes_closed, closed_since=st["closed_since"],
                      expression=expression, scores=scores, last_seen=now,
                      looking_down=not quality and not eyes_closed and head_or_eyes_down(pitch, gaze_h, gaze_v))
    return facing, reason


def clear_face_tracking(st, expression_votes, reason="no face"):
    """Discard timers, filters and calibration samples when observations stop."""
    expression_votes.clear()
    st.clear()
    st.update(closed_since=None, jaw_since=None)
    calib.interrupt("Move into view and look at the target")
    set_camera(present=False, facing=False, reason=reason, closed_since=None,
               eyes_closed=False, looking_down=False, gaze_text="-", expression="-",
               scores={n: 0.0 for n in EXPRESSION_NAMES})


def pick_fonts(platform, families, default_family, fixed_family):
    """(UI font, monospace font): the platform's first installed preference, else Tk's own default fonts."""
    ui, mono = next((p for prefix, p in FONT_PREFERENCES.items() if platform.startswith(prefix)), ((), ()))
    return (next((f for f in ui if f in families), default_family),
            next((f for f in mono if f in families), fixed_family))


def camera_backends(cv2, platform):
    """OpenCV backends to try for this OS, preferred first; 0 (CAP_ANY) is the default backend."""
    preferred = {"win": "CAP_DSHOW", "darwin": "CAP_AVFOUNDATION", "linux": "CAP_V4L2"}
    name = next((n for prefix, n in preferred.items() if platform.startswith(prefix)), None)
    return [getattr(cv2, name)] if name and hasattr(cv2, name) else []


def open_camera(cv2, index, platform=sys.platform):
    """An opened cv2.VideoCapture for the camera, or None. Tries the OS's preferred backend, then the default."""
    for backend in [*camera_backends(cv2, platform), None]:
        cap = cv2.VideoCapture(index) if backend is None else cv2.VideoCapture(index, backend)
        if cap.isOpened():
            # Modest capture size keeps inference responsive on laptop CPUs. Some
            # drivers ignore these requests; tracking uses the actual frame aspect.
            for name, value in (("CAP_PROP_FRAME_WIDTH", 640), ("CAP_PROP_FRAME_HEIGHT", 480),
                                ("CAP_PROP_FPS", CAMERA_FPS), ("CAP_PROP_BUFFERSIZE", 1)):
                if hasattr(cv2, name) and hasattr(cap, "set"):
                    cap.set(getattr(cv2, name), value)
            return cap
        cap.release()
    return None


def ssl_context():
    """certifi's CA bundle when installed (python.org builds on macOS ship without usable certificates)."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def download(url, path):
    """Fetch url to path through a .part file so an interrupted download never leaves a broken model."""
    if not os.path.exists(path):
        with urllib.request.urlopen(url, context=ssl_context(), timeout=60) as response, open(path + ".part", "wb") as f:
            shutil.copyfileobj(response, f)
        os.replace(path + ".part", path)


def make_phone_detector(vision, mp_python):
    """Object detector limited to 'cell phone'. Returns None if the model can't be loaded."""
    try:
        download(PHONE_MODEL_URL, PHONE_MODEL_PATH)
        options = vision.ObjectDetectorOptions(
            base_options=mp_python.BaseOptions(model_asset_path=PHONE_MODEL_PATH),
            running_mode=vision.RunningMode.VIDEO,
            max_results=3, score_threshold=PHONE_SCORE,
            category_allowlist=["cell phone"])
        detector = vision.ObjectDetector.create_from_options(options)
        set_camera(phone_status="on")
        return detector
    except Exception as e:
        set_camera(phone_status=f"off ({str(e)[:60]})")
        return None


def detect_phone(detector, image, tracker, frame_size, context=None):
    """Run the detector, feed the PhoneTracker, update shared state; returns the PhoneState.

    frame_size is (width, height) in pixels; context is an optional phone_detection.FaceContext.
    """
    now = time.monotonic()
    result = detector.detect_for_video(image, int(now * 1000))
    detections = []
    for d in result.detections or ():
        b = d.bounding_box
        detections.append(((b.origin_x, b.origin_y, b.width, b.height), d.categories[0].score))
    state = tracker.update(detections, frame_size, now, context)
    with lock:
        if state.seen and camera["phone_since"] is None:
            # tracker timestamps are monotonic; backdate to when the evidence started
            camera["phone_since"] = time.time() - max(0.0, now - (state.since or now))
        elif not state.seen:
            camera["phone_since"] = None
        camera["phone"] = state.seen
        camera["phone_confidence"] = state.confidence if state.seen else 0.0
    return state


def draw_overlay(cv2, frame, lm, facing, reason, phone_box=None, phone_confidence=None):
    """Draw face points, eyes, gaze arrow and phone box (in memory only)."""
    h, w = frame.shape[:2]
    if phone_box:
        x, y, bw, bh = (int(v) for v in phone_box)
        cv2.rectangle(frame, (x, y), (x + bw, y + bh), (160, 30, 220), 3)
        label = "PHONE" if phone_confidence is None else f"PHONE {phone_confidence:.0%}"
        cv2.putText(frame, label, (x, max(70, y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
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
        if not closed:
            center, _ = calib.profile()
            base_h, base_v = center[2:]
            sx, sy = px(168)
            end = (int(sx + (gh - base_h) * 600), int(sy + (gv - base_v) * 120))
            cv2.arrowedLine(frame, (sx, sy), end, (255, 220, 0), 2, tipLength=0.3)
    # The desktop window draws the verdict itself; keep the frame clean.
    return frame


def store_preview(cv2, frame):
    import base64
    h, w = frame.shape[:2]
    small = cv2.resize(frame, (PREVIEW_WIDTH, int(h * PREVIEW_WIDTH / w)))
    ok, jpg = cv2.imencode(".jpg", small, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
    if ok:
        preview["png"] = base64.b64encode(jpg.tobytes()).decode()   # key kept for callers; JPEG is far cheaper to encode


CAMERA_DENIED_HINT = ("camera not available: allow camera access for your terminal/Python in "
                      "System Settings > Privacy & Security > Camera")


def camera_loop(camera_index, stop_event=None):
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
            download(MODEL_URL, MODEL_PATH)
        except Exception as e:
            set_camera(status=f"model download failed: {e}")
            return

    try:
        with ExitStack() as resources:
            options = vision.FaceLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=MODEL_PATH),
                running_mode=vision.RunningMode.VIDEO,
                output_face_blendshapes=True,
                num_faces=1)
            landmarker = vision.FaceLandmarker.create_from_options(options)
            resources.callback(landmarker.close)
            phone_detector = make_phone_detector(vision, mp_python)
            if phone_detector is not None:
                resources.callback(phone_detector.close)
            phone_tracker = phone_detection.PhoneTracker()
            phone_state = phone_detection.PhoneState()
            frame_number = 0

            cap = open_camera(cv2, camera_index)
            if cap is None:
                set_camera(status=CAMERA_DENIED_HINT if sys.platform == "darwin" else "camera not available")
                return
            resources.callback(cap.release)

            expression_votes = collections.deque(maxlen=CAMERA_FPS * 2)
            st = {"closed_since": None, "jaw_since": None}
            frame_time = 1.0 / CAMERA_FPS
            last_frame = time.monotonic()
            last_timestamp = -1
            set_camera(status="ok", started=time.time())
            while running and not (stop_event is not None and stop_event.is_set()):
                started = time.monotonic()
                ok, frame = cap.read()
                if not ok:
                    clear_face_tracking(st, expression_votes, "camera frame unavailable")
                    phone_tracker.reset()
                    phone_state = phone_detection.PhoneState()
                    set_camera(status="camera interrupted; retrying...", phone=False, phone_since=None,
                               phone_confidence=0.0, observed_at=None)
                    preview["png"] = None
                    if time.monotonic() - last_frame >= CAMERA_READ_TIMEOUT:
                        raise RuntimeError("camera stopped delivering frames; reconnect it and restart")
                    time.sleep(.1)
                    continue
                last_frame = time.monotonic()
                set_camera(status="ok")
                # frames stay in memory only: never saved, never sent anywhere
                frame = cv2.flip(frame, 1)  # mirror view, feels natural in the preview
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                last_timestamp = max(last_timestamp + 1, int(time.monotonic() * 1000))
                result = landmarker.detect_for_video(image, last_timestamp)
                set_camera(observed_at=time.monotonic())

                lm = result.face_landmarks[0] if result.face_landmarks else None
                facing, reason = False, "no face"
                if lm:
                    bs = {}
                    if result.face_blendshapes:
                        bs = {c.category_name: c.score for c in result.face_blendshapes[0]}
                    facing, reason = analyze_face(lm, bs, st, expression_votes,
                                                  aspect=frame.shape[1] / frame.shape[0])
                else:
                    clear_face_tracking(st, expression_votes)

                frame_number += 1
                if phone_detector and frame_number % PHONE_EVERY_N_FRAMES == 0:
                    try:
                        frame_size = (frame.shape[1], frame.shape[0])
                        phone_state = detect_phone(
                            phone_detector, image, phone_tracker, frame_size,
                            phone_detection.face_context_from_landmarks(
                                lm, frame_size, camera["pitch"], calib.profile()[0][1]))
                    except Exception as exc:
                        # Phone detection is optional; it must not take face tracking down.
                        phone_detector = None
                        phone_tracker.reset()
                        phone_state = phone_detection.PhoneState()
                        set_camera(phone=False, phone_since=None, phone_confidence=0.0,
                                   phone_status=f"off (detector error: {str(exc)[:60]})")

                if show_preview:
                    store_preview(cv2, draw_overlay(cv2, frame, lm, facing, reason, phone_state.box,
                                                phone_state.confidence))

                time.sleep(max(0.0, frame_time - (time.monotonic() - started)))
        set_camera(status="stopped")
    except Exception as exc:
        set_camera(status=f"camera error ({type(exc).__name__}): {str(exc)[:100]}")
    finally:
        set_camera(present=False, facing=False, phone=False, phone_since=None,
                   phone_confidence=0.0, phone_status="off", closed_since=None, eyes_closed=False, gaze_text="-",
                   expression="-", scores={n: 0.0 for n in EXPRESSION_NAMES}, observed_at=None)
        calib.interrupt("Camera stopped; look at screen center when it resumes")
        preview["png"] = None


# ---------------- optional global hotkeys ----------------
def start_global_hotkeys():
    """Needs pynput; macOS also needs Accessibility permission and Linux an X11 session. Any failure just means no hotkeys."""
    try:
        from pynput import keyboard
        hotkeys = keyboard.GlobalHotKeys({
            "<ctrl>+<shift>+d": lambda: demo_requests.append("d"),
            "<ctrl>+<shift>+b": lambda: demo_requests.append("b"),
        })
        hotkeys.daemon = True
        hotkeys.start()
    except ImportError:
        return False
    except Exception as e:   # no display server, missing permission, backend import errors
        print(f"Global hotkeys unavailable: {e}")
        return False
    return True


# ---------------- window UI ----------------
def fmt_minutes(seconds):
    return f"{int(seconds // 60)}m"


def fmt_clock(seconds):
    seconds = int(max(0, seconds))
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def run_legacy_ui(fake_camera, global_keys, compact):
    global running, show_preview, UI_FONT, MONO_FONT
    import tkinter as tk
    import tkinter.font as tkfont
    from tkinter import messagebox

    BG, PANEL, FG, MUTED = "#15171a", "#1f2226", "#f2f2f2", "#9aa0a6"
    show_preview = not compact

    if sys.platform == "win32":   # crisp text instead of bitmap-scaled blur on HiDPI screens
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

    root = tk.Tk()
    UI_FONT, MONO_FONT = pick_fonts(
        sys.platform, set(tkfont.families(root)),
        tkfont.nametofont("TkDefaultFont").actual("family"), tkfont.nametofont("TkFixedFont").actual("family"))
    root.title("Study Focus")
    root.attributes("-topmost", True)
    root.geometry("+20+20")
    root.configure(bg=BG)

    # --- top status bar (always visible) ---
    bar = tk.Label(root, font=(MONO_FONT, 12, "bold"), fg="white", padx=12, pady=6, anchor="w")
    stats = tk.Label(root, font=(MONO_FONT, 10), fg="white", padx=12, pady=2, anchor="w")
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
    calibration_button = tk.Button(left, text="Calibrate screen (C)",
                                   state="disabled" if fake_camera else "normal")
    calibration_button.pack(fill="x", pady=(6, 0))
    calibration_status = tk.Label(left, bg=BG, fg=MUTED, font=(UI_FONT, 9),
                                  wraplength=PREVIEW_WIDTH - 12)
    if not fake_camera:
        calibration_status.pack(fill="x", pady=(3, 0))

    expr_frame = tk.Frame(left, bg=PANEL, padx=12, pady=8)
    expr_frame.pack(fill="x", pady=(8, 0))
    expr_title = tk.Label(expr_frame, font=(UI_FONT, 13, "bold"), bg=PANEL, fg=FG, anchor="w")
    expr_title.pack(fill="x")
    expr_canvas = tk.Canvas(expr_frame, width=PREVIEW_WIDTH - 24, height=len(EXPRESSION_NAMES) * 18,
                            bg=PANEL, highlightthickness=0)
    expr_canvas.pack(anchor="w", pady=(4, 0))

    info = tk.Frame(body, bg=PANEL, padx=14, pady=10)
    info.grid(row=0, column=1, padx=(6, 10), pady=10, sticky="nsew")

    state_big = tk.Label(info, font=(UI_FONT, 22, "bold"), bg=PANEL, fg=FG, anchor="w")
    state_big.pack(fill="x")
    reason = tk.Label(info, font=(UI_FONT, 10), bg=PANEL, fg=MUTED, anchor="w",
                      justify="left", wraplength=340)
    reason.pack(fill="x", pady=(0, 8))

    rows = {}
    grid = tk.Frame(info, bg=PANEL)
    grid.pack(fill="x")
    names = ["Study", "Website", "Category", "Attention", "Eyes", "Blinks", "Yawns", "Phone",
             "Doom-scroll", "Context", "Extension", "Active time", "Focused", "Distracted", "Nudge",
             "Next break"]
    for i, name in enumerate(names):
        tk.Label(grid, text=name, font=(UI_FONT, 10), bg=PANEL, fg=MUTED,
                 anchor="w").grid(row=i, column=0, sticky="w", pady=1)
        rows[name] = tk.Label(grid, font=(MONO_FONT, 10), bg=PANEL, fg=FG, anchor="w")
        rows[name].grid(row=i, column=1, sticky="w", padx=(12, 0), pady=1)

    tk.Label(info, text="Productivity Index (last 10 min)", font=(UI_FONT, 10),
             bg=PANEL, fg=MUTED, anchor="w").pack(fill="x", pady=(10, 2))
    index_canvas = tk.Canvas(info, width=340, height=22, bg="#2b2f34", highlightthickness=0)
    index_canvas.pack(anchor="w")

    tk.Label(info, text=f"State timeline (last {TIMELINE_SECONDS // 60} min)", font=(UI_FONT, 10),
             bg=PANEL, fg=MUTED, anchor="w").pack(fill="x", pady=(10, 2))
    timeline_canvas = tk.Canvas(info, width=340, height=18, bg="#2b2f34", highlightthickness=0)
    timeline_canvas.pack(anchor="w")

    # --- study session panel (live view only, so --compact stays compact) ---
    study_panel = tk.Frame(body, bg=PANEL, padx=14, pady=8)
    study_panel.grid(row=1, column=0, columnspan=2, padx=10, pady=(0, 10), sticky="ew")
    subject_var, goal_var = tk.StringVar(), tk.StringVar()
    work_var, break_var = tk.StringVar(value="25"), tk.StringVar(value="5")

    def field(parent, label, **opts):
        tk.Label(parent, text=label, font=(UI_FONT, 10), bg=PANEL, fg=MUTED).pack(side="left", padx=(0, 4))
        w = (tk.Spinbox if "from_" in opts else tk.Entry)(
            parent, font=(MONO_FONT, 10), bg="#2b2f34", fg=FG, insertbackground=FG,
            relief="flat", **opts)
        w.pack(side="left", padx=(0, 10))
        return w

    setup_row = tk.Frame(study_panel, bg=PANEL)
    field(setup_row, "Subject", textvariable=subject_var, width=16)
    field(setup_row, "Goal", textvariable=goal_var, width=26)
    field(setup_row, "Work min", textvariable=work_var, from_=1, to=120, width=4, buttonbackground=PANEL)
    field(setup_row, "Break min", textvariable=break_var, from_=1, to=60, width=4, buttonbackground=PANEL)
    start_button = tk.Button(setup_row, text="Start session", width=14)
    start_button.pack(side="left")

    run_row = tk.Frame(study_panel, bg=PANEL)
    run_label = tk.Label(run_row, font=(MONO_FONT, 10), bg=PANEL, fg=FG, anchor="w")
    run_label.pack(side="left", padx=(0, 14))
    phase_button = tk.Button(run_row, width=10)
    phase_button.pack(side="left", padx=(0, 6))
    stop_button = tk.Button(run_row, text="Stop", width=8)
    stop_button.pack(side="left")

    profile_row = tk.Frame(study_panel, bg=PANEL)
    profile_label = tk.Label(profile_row, font=(UI_FONT, 10), bg=PANEL, fg=MUTED, anchor="w")
    profile_label.pack(side="left")
    history_button = tk.Button(profile_row, text="History", width=8)
    history_button.pack(side="right")
    shown_row = [None]   # which of setup_row / run_row is visible

    keys = ("Demo: D distraction · B break · T tired · X stuck · M phone · S doom-scroll"
            "  |  C calibrate · V live view · Q quit")
    if fake_camera:
        keys += " · P presence · F facing"
    if global_keys:
        keys += "  (global: Ctrl+Shift+D/B)"
    hint = tk.Label(root, text=keys, font=(MONO_FONT, 8), fg="#dddddd", padx=12, pady=4, anchor="w")

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
        tk.Label(win, text=title, font=(UI_FONT, 18, "bold"), bg=color, fg="white").pack(padx=30, pady=(20, 6))
        tk.Label(win, text=message, font=(UI_FONT, 12), bg=color, fg="white", justify="center").pack(padx=30, pady=6)
        buttons = tk.Frame(win, bg=color)
        buttons.pack(pady=(10, 20))
        if kind == "nudge":
            tk.Button(buttons, text="Back to work", width=14, command=win.destroy).pack(side="left", padx=6)
            tk.Button(buttons, text="5 more minutes", width=14,
                      command=lambda: (snooze(), win.destroy())).pack(side="left", padx=6)
        elif kind == "break":
            counter = tk.Label(buttons, font=(MONO_FONT, 22, "bold"), bg=color, fg="white")
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
                      command=lambda: (show_tips(), win.destroy())).pack(side="left", padx=6)
            tk.Button(buttons, text="I'm fine", width=14, command=win.destroy).pack(side="left", padx=6)
        elif kind in ("tired",):
            tk.Button(buttons, text="Take a break", width=14, command=win.destroy).pack(side="left", padx=6)
            tk.Button(buttons, text="I'm fine", width=14, command=win.destroy).pack(side="left", padx=6)
        else:
            tk.Button(buttons, text="Got it", width=14, command=win.destroy).pack(side="left", padx=6)
        win.update_idletasks()
        x = (win.winfo_screenwidth() - win.winfo_width()) // 2
        y = (win.winfo_screenheight() - win.winfo_height()) // 3
        win.geometry(f"+{x}+{y}")
        win.lift()
        win.focus_force()

    # --- study windows: report, history, tips ---
    def new_window(title):
        win = tk.Toplevel(root)
        win.title(title)
        win.attributes("-topmost", True)
        win.configure(bg=BG)
        return win

    def draw_report_timeline(canvas, report, width):
        """Colored state strip for the whole session (same colors as the live strip)."""
        total = max(1.0, report["duration_min"] * 60)
        items = report["timeline"]
        for i, (t, st) in enumerate(items):
            t_end = items[i + 1][0] if i + 1 < len(items) else total
            canvas.create_rectangle(int(width * t / total), 0, int(width * t_end / total) + 1, 18,
                                    fill=STATE_COLORS.get(st, "#4a5568"), width=0)

    def show_report(report):
        win = new_window("Session report")
        box = tk.Frame(win, bg=PANEL, padx=18, pady=14)
        box.pack(padx=10, pady=10)

        def line(text, size=10, color=FG, bold=False, pady=1):
            tk.Label(box, text=text, font=(UI_FONT, size, "bold" if bold else "normal"), bg=PANEL,
                     fg=color, anchor="w", justify="left", wraplength=440).pack(fill="x", pady=pady)

        line(f"{report['subject']} · {report['duration_min']} min", 16, bold=True)
        if report["goal"]:
            line(report["goal"] + ("  (reached)" if report["goal_done"] else "  (not reached)"), color=MUTED)
        line(f"Focus {report['focus_pct']}%", 22, bold=True, pady=(8, 2))
        line(f"Focused {report['focused_min']} min · Distracted {report['distracted_min']} min · "
             f"Pomodoros {report['pomodoros']} · Avg index {report['avg_index']}")
        line(f"Nudges {report['nudges']} · Overrides {report['overrides']} · "
             f"Phone pickups {report['phone_pickups']} · Doom-scroll episodes {report['doom_episodes']}")
        line(f"Attention span {report['attention_span_min']} min per task · best clean run "
             f"{report['best_streak_min']} min")
        if report["top_distractions"]:
            line("Top distractions: " + ", ".join(f"{d} {m} min" for d, m in report["top_distractions"]))
        if report["moods"]:
            line("Mood: " + ", ".join(f"{m} {p}%" for m, p in report["moods"]))
        blink = f"{report['avg_blink']} / min" if report["avg_blink"] is not None else "n/a"
        line(f"Blink rate {blink} · Yawns {report['yawns']}")
        tk.Label(box, text="Timeline", font=(UI_FONT, 10), bg=PANEL, fg=MUTED,
                 anchor="w").pack(fill="x", pady=(8, 2))
        canvas = tk.Canvas(box, width=440, height=18, bg="#2b2f34", highlightthickness=0)
        canvas.pack(anchor="w")
        draw_report_timeline(canvas, report, 440)
        line("Tips", 11, bold=True, pady=(10, 2))
        for tip in report["tips"]:
            line("• " + tip)
        xp = f"+{report['xp_earned']} XP"
        if report["new_badges"]:
            xp += " · New badges: " + ", ".join(report["new_badges"])
        line(xp, 12, bold=True, pady=(10, 0))
        tk.Button(win, text="Close", width=10, command=win.destroy).pack(pady=(0, 10))

    def show_history():
        win = new_window("Past sessions")
        past = study.report_list()
        listbox = tk.Listbox(win, width=64, height=min(15, max(3, len(past))), bg=PANEL, fg=FG,
                             font=(MONO_FONT, 10), selectbackground="#5b8def",
                             highlightthickness=0, relief="flat", exportselection=False)
        listbox.pack(padx=10, pady=10)
        for r in past:
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(r["started"]))
            listbox.insert("end", f"{when}  {r['subject'][:20]:<20}  {r['duration_min']:>5} min  "
                                  f"focus {r['focus_pct']:>3}%  +{r['xp_earned']} XP")
        if not past:
            listbox.insert("end", "no sessions yet")

        def open_selected(_event):
            picked = listbox.curselection()
            report = study.get_report(past[picked[0]]["id"]) if picked and past else None
            if report:
                show_report(report)
        listbox.bind("<<ListboxSelect>>", open_selected)

    def show_tips():
        win = new_window("Study tips")
        tk.Label(win, text="Stuck? Pick a technique", font=(UI_FONT, 12, "bold"), bg=BG,
                 fg=FG).pack(padx=20, pady=(14, 6))
        buttons = tk.Frame(win, bg=BG)
        buttons.pack(padx=20)
        text = tk.Label(win, font=(UI_FONT, 11), bg=PANEL, fg=FG, wraplength=340, justify="left",
                        padx=14, pady=10, text="Try one of the buttons above.")
        for label, mode in (("Explain simpler", "explain"), ("Easy examples", "example"), ("Quiz me", "quiz")):
            tk.Button(buttons, text=label, width=14,
                      command=lambda m=mode: text.config(text=study.study_tip(m)["text"])
                      ).pack(side="left", padx=4)
        text.pack(fill="x", padx=20, pady=(10, 6))
        tk.Button(win, text="Close", width=10, command=win.destroy).pack(pady=(0, 14))

    # --- study session controls ---
    def whole_minutes(var, default):
        try:
            return int(var.get())
        except ValueError:
            return default

    def start_study():
        ok, message = study.start_session(subject_var.get(), goal_var.get(),
                                          whole_minutes(work_var, 25), whole_minutes(break_var, 5))
        if not ok:
            messagebox.showinfo("Study Focus", message, parent=root)

    def stop_study():
        answer = messagebox.askyesnocancel("Study Focus", "Did you reach your goal?", parent=root)
        if answer is None:
            return
        report = study.stop_session(answer)
        if report:
            show_report(report)

    def toggle_phase():
        sv = study.session_view()
        if sv and sv["phase"] == "break":
            study.resume_work()
        elif sv:
            study.start_break()

    start_button.config(command=start_study)
    stop_button.config(command=stop_study)
    phase_button.config(command=toggle_phase)
    history_button.config(command=show_history)

    # --- guided screen calibration ---
    calibration_window = [None]
    offered_calibration = [fake_camera or compact]

    def open_calibration():
        if fake_camera:
            return
        if calibration_window[0] is not None:
            calibration_window[0].lift()
            return
        with lock:
            ready = camera["status"] == "ok"
        if not ready:
            messagebox.showinfo("Camera calibration", "Wait for the camera to be ready first.", parent=root)
            return
        offered_calibration[0] = True
        reset_calibration(guided=True)
        win = tk.Toplevel(root)
        calibration_window[0] = win
        win.title("Calibrate screen")
        win.configure(bg=BG)
        win.attributes("-topmost", True)
        win.attributes("-fullscreen", True)
        canvas = tk.Canvas(win, bg=BG, highlightthickness=0)
        canvas.pack(fill="both", expand=True)

        def close(cancel=True):
            if calibration_window[0] is not win:
                return
            if cancel:
                calib.cancel()
            calibration_window[0] = None
            win.destroy()

        win.bind("<Escape>", lambda event: close())
        win.protocol("WM_DELETE_WINDOW", close)
        win.focus_set()

        def refresh_calibration():
            if not running or calibration_window[0] is not win:
                return
            state = calib.view()
            canvas.delete("all")
            width, height = canvas.winfo_width(), canvas.winfo_height()
            if not state["active"]:
                limited = state["quality"] == "limited"
                canvas.create_text(width / 2, height / 2, text=state["message"],
                                   fill="#ffcc80" if limited else "#80dca2",
                                   font=(UI_FONT, 24, "bold"), width=width * .8, justify="center")
                win.after(3500 if limited else 700, lambda: close(cancel=False))
                return
            _, x, y = state["target"]
            cx, cy = width * x, height * y
            canvas.create_oval(cx - 22, cy - 22, cx + 22, cy + 22, outline="#5b8def", width=3)
            canvas.create_arc(cx - 29, cy - 29, cx + 29, cy + 29, start=90,
                              extent=-359 * state["progress"], style="arc", outline="#80dca2", width=4)
            canvas.create_oval(cx - 5, cy - 5, cx + 5, cy + 5, fill="white", outline="")
            canvas.create_text(width / 2, height * .32,
                               text="Follow the dot with your eyes\nKeep your usual sitting position",
                               fill=FG, font=(UI_FONT, 20), justify="center")
            with lock:
                camera_status = camera["status"]
            message = state["message"] if camera_status == "ok" else camera_status
            canvas.create_text(width / 2, height * .70,
                               text=f"Point {state['stage'] + 1} of 5 · {message}\nEsc to cancel",
                               fill=MUTED, font=(UI_FONT, 14), justify="center")
            win.after(50, refresh_calibration)

        win.after(100, refresh_calibration)

    calibration_button.config(command=open_calibration)

    # --- keys ---
    def handle_key(k):
        global show_preview
        if k in DEMO_ACTIONS:
            DEMO_ACTIONS[k]()
        elif k == "c":
            open_calibration()
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

    def on_key(e):
        if not isinstance(e.widget, (tk.Entry, tk.Spinbox)):   # typing in the session fields is not a hotkey
            handle_key(e.keysym.lower())

    root.bind("<Key>", on_key)
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
                             font=(MONO_FONT, 12), fg=FG)
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
            expr_canvas.create_text(0, y + 8, text=name, anchor="w", fill=MUTED, font=(UI_FONT, 9))
            expr_canvas.create_rectangle(100, y + 3, 100 + width, y + 14, fill="#2b2f34", width=0)
            expr_canvas.create_rectangle(100, y + 3, 100 + int(width * value), y + 14, fill="#5b8def", width=0)
            expr_canvas.create_text(104 + width, y + 8, text=f"{value:.2f}", anchor="w", fill=FG,
                                    font=(MONO_FONT, 8))

    def draw_index(value):
        index_canvas.delete("all")
        color = "#1f7a4d" if value >= 70 else "#b26a00" if value >= 40 else "#b3261e"
        index_canvas.create_rectangle(0, 0, int(340 * value / 100), 22, fill=color, width=0)
        index_canvas.create_text(8, 11, text=f"{value}", anchor="w", fill="white",
                                 font=(MONO_FONT, 10, "bold"))

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
        calibration = calib.view()
        calibration_status.config(text=calibration["message"])
        if calibration["active"] and c["status"] == "ok" and not fake_camera:
            cam += f" · {calibration['message']} {int(calibration['progress'] * 100)}%"
        if not offered_calibration[0] and c["status"] == "ok" and c["present"]:
            open_calibration()
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
            rows["Study"].config(text="no session (start one below)")
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
        update_study_panel(sv)

    def update_study_panel(sv):
        """Swap between the start form and the running-session controls; refresh the profile line."""
        want = run_row if sv else setup_row
        if shown_row[0] is not want:
            if shown_row[0]:
                shown_row[0].pack_forget()
            profile_row.pack_forget()
            want.pack(fill="x")
            profile_row.pack(fill="x", pady=(6, 0))
            shown_row[0] = want
        if sv:
            left = sv["phase_left"]
            goal = f" · goal: {sv['goal'][:30]}" if sv["goal"] else ""
            run_label.config(text=f"{sv['subject'][:20]}{goal} · {sv['phase']} {left // 60}:{left % 60:02d}"
                                  f" · {sv['pomodoros']} pomodoros · +{sv['xp']} XP")
            phase_button.config(text="Resume" if sv["phase"] == "break" else "Break")
        p = study.profile_view()
        badges = ", ".join(b["name"] for b in p["badges"]) or "none yet"
        profile_label.config(text=f"Level {p['level']} · {p['level_need'] - p['level_xp']} XP to next level · "
                                  f"streak {p['streak']} day(s) · badges: {badges}")

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
                show_popup(kind, message)
            update_info()
        root.after(UI_REFRESH_MS, loop)

    loop()
    root.mainloop()
    running = False


class CameraController:
    """Session-owned capture; joins the worker before releasing the camera."""

    def __init__(self, index=0, simulated=False):
        self.index = index
        self.simulated = simulated
        self.worker = None
        self.stop_event = threading.Event()
        self.enabled = False
        set_camera(status="off", present=False, facing=False, phone=False,
                   phone_since=None, phone_confidence=0.0, observed_at=None,
                   phone_status="off")

    def start(self):
        if self.enabled:
            return
        self.stop_event.clear()
        self.enabled = True
        set_camera(status="starting", present=False, facing=False, phone=False,
                   phone_since=None, phone_confidence=0.0, observed_at=None,
                   last_seen=time.time())
        if self.simulated:
            set_camera(status="ok", present=True, facing=True, reason="simulated",
                       observed_at=time.monotonic())
            return
        self.worker = threading.Thread(target=camera_loop,
                                       args=(self.index, self.stop_event), name="camera")
        try:
            self.worker.start()
        except Exception:
            self.enabled = False
            self.worker = None
            raise

    def stop(self):
        self.enabled = False
        self.stop_event.set()
        if self.worker is not None:
            self.worker.join()
            self.worker = None
        set_camera(status="off", present=False, facing=False, phone=False,
                   phone_since=None, phone_confidence=0.0, observed_at=None,
                   phone_status="off")
        preview["png"] = None


def run_ui(fake_camera=False, global_keys=False, compact=False):
    from desktop import run
    run(sys.modules[__name__], compact=compact)


def main():
    global running, camera_controller
    parser = argparse.ArgumentParser(description="EyeTrack desktop focus sessions")
    parser.add_argument("--no-camera", action="store_true", help="simulate camera input for testing")
    parser.add_argument("--compact", action="store_true", help="use a smaller desktop window")
    parser.add_argument("--camera-index", type=int, default=CAMERA_INDEX)
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()
    running = True
    init_classifier()
    try:
        server = start_server(args.port)
    except OSError:
        print(f"Port {args.port} is busy. Close the other engine or use --port.")
        if jev is not None:
            jev.close()
        return
    print(f"Engine listening on http://127.0.0.1:{server.server_address[1]}  (GET /status)")
    camera_controller = CameraController(args.camera_index, args.no_camera)
    start_app_monitor()
    try:
        run_ui(args.no_camera, False, args.compact)
    finally:
        running = False
        stop_app_monitor()
        camera_controller.stop()
        server.shutdown()
        server.server_close()
        if jev is not None:
            jev.close()


if __name__ == "__main__":
    main()
