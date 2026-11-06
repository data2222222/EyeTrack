"""Timestamp-based timing for one focus block. Camera never pauses the clock."""
import copy
import json
import math
import os
import threading
import time
import uuid

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
REPORTS_PATH = os.path.join(DATA_DIR, "sessions.json")
MODES = {"pc": "Computer", "notebook": "Notebook", "both": "Computer & notebook"}
WEBSITE_CATEGORIES = ("work", "unlisted", "distraction", "outside", "unavailable")
CAMERA_CATEGORIES = ("present", "no_face", "unavailable")
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
            return False, "Choose computer, notebook, or both."
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
    fresh = max(0.0, min(end, info.get("website_until", start)) - start)
    s["website"][website] += fresh
    s["website"]["unavailable"] += duration - fresh
    camera = info.get("camera", "unavailable") if s["camera_enabled"] else "unavailable"
    if camera not in CAMERA_CATEGORIES:
        camera = "unavailable"
    fresh = max(0.0, min(end, info.get("camera_until", start)) - start)
    s["camera"][camera] += fresh
    s["camera"]["unavailable"] += duration - fresh


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
        }
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
