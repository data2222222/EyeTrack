"""Timestamp-based timing for one focus block. Camera never pauses the clock."""
import collections
import copy
import json
import math
import os
import threading
import time
import uuid

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
REPORTS_PATH = os.path.join(DATA_DIR, "sessions.json")
MODES = {"pc": "Computer only", "both": "Computer + paper", "notebook": "Paper"}   # "notebook" only labels older reports
SETUP_MODES = ("pc", "both")
RHYTHMS = ((25, 5), (50, 10), (15, 3))         # (focus minutes, break minutes); the first is the default
WEBSITE_CATEGORIES = ("work", "unlisted", "distraction", "outside", "unavailable")
CAMERA_CATEGORIES = ("present", "no_face", "unavailable")
ATTENTION = ("screen", "paper", "away", "no_face", "phone", "unavailable")
ON_TASK = ("screen", "paper")                   # camera states that count toward the focus score
SCORE_WINDOW = 300                              # seconds of active time behind the live score
TRACE_STEP = 10                                 # seconds of active time per trend-graph point
MIN_TRACKED = 5                                 # tracked seconds needed before a score is shown
AWAY_EPISODE_SECONDS = 3                        # looking away this long counts as one look-away
lock = threading.RLock()
session = None
last_report = None


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


reports = load_json(REPORTS_PATH, [])


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(path + ".tmp", path)


def format_duration(seconds):
    seconds = max(0, int(seconds))
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"


def start_session(subject="", goal="", work_min=25, break_min=5,
                  mode="pc", camera_enabled=True):
    global session, last_report
    with lock:
        if session is not None:
            return False, "End the current session before starting another."
        if mode not in MODES:
            return False, "Choose how you will work."
        try:
            work_min = max(1, min(120, int(work_min)))
            break_min = max(1, min(60, int(break_min)))
        except (ValueError, TypeError):
            return False, "Choose a valid session length."
        now = time.monotonic()
        session = {
            "id": uuid.uuid4().hex[:8], "subject": str(subject).strip()[:60] or "Focus session",
            "goal": str(goal).strip()[:140], "mode": mode,
            "camera_enabled": bool(camera_enabled), "started": time.time(),
            "work_min": work_min, "break_min": break_min, "phase": "work",
            "cursor": now, "active": 0.0, "paused": 0.0, "break_seconds": 0.0,
            "current_break": 0.0, "break_count": 0, "breaks": [],
            "counts": {"nudge": 0, "phone": 0, "doom": 0, "override": 0},
            "website": dict.fromkeys(WEBSITE_CATEGORIES, 0.0),
            "camera": dict.fromkeys(CAMERA_CATEGORIES, 0.0),
            "focus": dict.fromkeys(ATTENTION, 0.0), "recent": collections.deque(),
            "trace": {}, "tracked": 0.0, "on_task": 0.0, "look_aways": 0,
            "now": "unavailable", "now_since": now, "away_since": None, "away_counted": False,
            "info": {}, "completed": False, "completion_announced": False,
        }
        last_report = None
        return True, "started"


def _attribute(s, start, end):
    """Only fresh observed portions get known categories; gaps are unavailable."""
    info = s["info"]
    duration = end - start
    website = info.get("website", "unavailable")
    if website not in WEBSITE_CATEGORIES:
        website = "unavailable"
    web_fresh = max(0.0, min(end, info.get("website_until", start)) - start)
    s["website"][website] += web_fresh
    s["website"]["unavailable"] += duration - web_fresh
    camera = info.get("camera", "unavailable") if s["camera_enabled"] else "unavailable"
    if camera not in CAMERA_CATEGORIES:
        camera = "unavailable"
    cam_fresh = max(0.0, min(end, info.get("camera_until", start)) - start)
    s["camera"][camera] += cam_fresh
    s["camera"]["unavailable"] += duration - cam_fresh
    # Where the eyes were: what the camera saw, only for fresh observations.
    bucket = info.get("attention", "unavailable") if s["camera_enabled"] else "unavailable"
    if bucket not in ATTENTION:
        bucket = "unavailable"
    att_fresh = max(0.0, min(end, info.get("attention_until", start)) - start)
    s["focus"][bucket] += att_fresh
    s["focus"]["unavailable"] += duration - att_fresh
    # Focus score: share of tracked time spent on task. Without a camera only the site counts.
    if s["camera_enabled"]:
        tracked = att_fresh
        on = att_fresh if bucket in ON_TASK else 0.0
        if website == "distraction":
            on -= min(on, web_fresh)
    else:
        tracked = web_fresh if website in ("work", "unlisted", "distraction") else 0.0
        on = web_fresh if website in ("work", "unlisted") else 0.0
    if tracked > 0:
        s["tracked"] += tracked
        s["on_task"] += on
        s["recent"].append((s["active"] + duration, tracked, on))
        slot = s["trace"].setdefault(int((s["active"] + duration / 2) // TRACE_STEP), [0.0, 0.0])
        slot[0] += tracked
        slot[1] += on


def _score(tracked, on):
    return round(100 * on / tracked) if tracked >= MIN_TRACKED else None


def _recent_score(s):
    horizon = s["active"] - SCORE_WINDOW
    recent = s["recent"]
    while recent and recent[0][0] <= horizon:
        recent.popleft()
    return _score(sum(r[1] for r in recent), sum(r[2] for r in recent))


def _trace(s):
    """Per-step scores for the trend graph; None marks steps without observations."""
    steps = int(s["active"] // TRACE_STEP) + 1
    return [_score(*s["trace"][i]) if i in s["trace"] and s["trace"][i][0] >= 1 else None
            for i in range(steps)]


def _settle():
    s = session
    if s is None:
        return
    now = time.monotonic()
    start = s["cursor"]
    elapsed = max(0.0, now - start)
    s["cursor"] = now
    if s["phase"] == "work":
        elapsed = min(elapsed, max(0.0, s["work_min"] * 60 - s["active"]))
        _attribute(s, start, start + elapsed)
        s["active"] += elapsed
        if s["active"] >= s["work_min"] * 60:
            s["phase"] = "complete"
            s["completed"] = True
    elif s["phase"] == "paused":
        s["paused"] += elapsed
    elif s["phase"] == "break":
        s["break_seconds"] += elapsed
        s["current_break"] += elapsed


def _finish_break():
    if session["phase"] == "break":
        session["breaks"].append(session["current_break"])
        session["break_count"] += 1
        session["current_break"] = 0.0


def pause_session():
    with lock:
        _settle()
        if session is None or session["phase"] != "work":
            return False
        session["phase"] = "paused"
        return True


def start_break():
    with lock:
        _settle()
        if session is None or session["phase"] not in ("work", "paused", "complete"):
            return False
        session["phase"] = "break"
        session["current_break"] = 0.0
        return True


def resume_work():
    with lock:
        _settle()
        if session is None or session["phase"] not in ("paused", "break"):
            return False
        _finish_break()
        session["phase"] = "complete" if session["completed"] else "work"
        session["info"] = {}
        return True


def focus_mode_active():
    with lock:
        _settle()
        return bool(session and session["phase"] == "work")


def record_event(kind):
    with lock:
        _settle()
        if session and session["phase"] == "work" and kind in session["counts"]:
            session["counts"][kind] += 1


def _track_now(s, bucket, now):
    """Remember the current camera state and count a look-away once it lasts a few seconds."""
    if bucket != s["now"]:
        s["now"], s["now_since"] = bucket, now
    if bucket in ("away", "no_face"):
        if s["away_since"] is None:
            s["away_since"], s["away_counted"] = now, False
        elif not s["away_counted"] and now - s["away_since"] >= AWAY_EPISODE_SECONDS:
            s["away_counted"] = True
            s["look_aways"] += 1
    elif bucket != "unavailable":
        s["away_since"] = None


def tick(dt, info):
    """Accept dt for bridge compatibility; timestamps remain authoritative."""
    with lock:
        _settle()
        if session is None:
            return []
        now = time.monotonic()
        category = {"productive": "work", "distraction": "distraction",
                    "neutral": "unlisted", "other": "outside"}.get(info.get("category"), "unavailable")
        browser_age = info.get("browser_age")
        website_until = now + max(0, 75 - browser_age) if browser_age is not None else now
        observed_at = info.get("camera_observed_at")
        session["info"] = {
            "website": category, "website_until": website_until,
            "camera": info.get("camera_category", "unavailable"),
            "camera_until": observed_at + 1 if observed_at is not None else now,
            "attention": info.get("attention", "unavailable"),
            "attention_until": observed_at + 1 if observed_at is not None else now,
        }
        if session["phase"] == "work":
            _track_now(session, session["info"]["attention"] if session["info"]["attention_until"] > now
                       else "unavailable", now)
        if session["completed"] and not session["completion_announced"]:
            session["completion_announced"] = True
            return [("complete", "Your planned block is complete. Take a break or review your session.")]
        return []


def session_view():
    with lock:
        _settle()
        if session is None:
            return None
        s = session
        remaining = max(0.0, s["work_min"] * 60 - s["active"])
        phase_left = max(0.0, s["break_min"] * 60 - s["current_break"]) if s["phase"] == "break" else remaining
        return {
            "id": s["id"], "subject": s["subject"], "goal": s["goal"],
            "mode": s["mode"], "camera_enabled": s["camera_enabled"], "phase": s["phase"],
            "phase_left": math.ceil(phase_left), "remaining": remaining,
            "phase_total": (s["break_min"] if s["phase"] == "break" else s["work_min"]) * 60,
            "planned_seconds": s["work_min"] * 60, "active_seconds": s["active"],
            "paused_seconds": s["paused"], "break_seconds": s["break_seconds"],
            "break_count": s["break_count"], "current_break": s["current_break"],
            "counts": dict(s["counts"]), "completed": s["completed"],
            "break_planned": s["break_min"] * 60, "website": dict(s["website"]),
            "focus": dict(s["focus"]), "score": _recent_score(s),
            "session_score": _score(s["tracked"], s["on_task"]), "trace": _trace(s),
            "look_aways": s["look_aways"], "now": s["now"],
            "now_seconds": max(0.0, time.monotonic() - s["now_since"]),
        }


def stop_session(goal_done=None):
    global session, last_report
    with lock:
        _settle()
        if session is None:
            return None
        # Build the final break into the report without changing live state before saving.
        s = session
        breaks = [*s["breaks"], s["current_break"]] if s["phase"] == "break" else list(s["breaks"])
        report = {
            "id": s["id"], "subject": s["subject"], "goal": s["goal"],
            "mode": s["mode"], "camera_enabled": s["camera_enabled"],
            "started": s["started"], "ended": time.time(),
            "planned_seconds": s["work_min"] * 60, "active_seconds": s["active"],
            "paused_seconds": s["paused"], "break_seconds": s["break_seconds"],
            "break_count": len(breaks), "breaks": breaks,
            "completed": s["completed"], "goal_done": goal_done,
            "nudges": s["counts"]["nudge"], "counts": dict(s["counts"]),
            "website": dict(s["website"]), "camera": dict(s["camera"]),
            "focus": dict(s["focus"]), "score": _score(s["tracked"], s["on_task"]),
            "trace": _trace(s), "look_aways": s["look_aways"],
        }
        save_json(REPORTS_PATH, [*reports, report])
        reports.append(report)
        last_report = report
        session = None
        return copy.deepcopy(report)


def set_goal_result(result):
    global last_report
    if result not in (None, "finished", "partly", "not_finished"):
        raise ValueError("Unknown goal result")
    with lock:
        if last_report is None:
            return
        updated = {**last_report, "goal_done": result}
        updated_reports = [updated if r.get("id") == updated["id"] else r for r in reports]
        save_json(REPORTS_PATH, updated_reports)
        reports[:] = updated_reports
        last_report = updated
