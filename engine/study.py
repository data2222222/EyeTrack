"""
Study sessions for Study Focus: Pomodoro timer, XP / levels / streaks / badges,
end-of-session reports with tips, and built-in study tips for when you're stuck.
The engine calls tick() twice per second; the engine window starts and stops sessions and shows the views below.
"""
import datetime
import json
import os
import threading
import time
import uuid

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
PROFILE_PATH = os.path.join(DATA_DIR, "profile.json")
REPORTS_PATH = os.path.join(DATA_DIR, "sessions.json")

XP_PER_MINUTE = {"Focused": 2, "Reading / Thinking": 1, "Other App": 1}
POMODORO_XP = 20
GOAL_XP = 30
STREAK_MIN_FOCUS_MINUTES = 10
TIMELINE_STEP = 5                     # seconds between timeline samples
FOCUS_STATES = ("Focused", "Reading / Thinking", "Other App")
DISTRACTED_STATES = ("Distracted", "Doom-scrolling", "On Phone")
BAD_STATES = DISTRACTED_STATES + ("Idle Tab", "Scattered")

BADGES = {
    "first": ("First Session", "Finished your first study session"),
    "deep": ("Deep Diver", "25 minutes in a row without any distraction"),
    "phonefree": ("Phone-Free", "25+ minute session without touching your phone"),
    "pomo4": ("Pomodoro Pro", "4 pomodoros in one session"),
    "goal": ("Goal Getter", "Reached the goal you set"),
    "streak3": ("On Fire", "Studied 3 days in a row"),
}

lock = threading.RLock()


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, data):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


profile = load_json(PROFILE_PATH, {})
profile = {"xp": 0, "streak": 0, "last_day": None, "badges": [], "sessions": 0,
           "focus_minutes": 0, **profile}
reports = load_json(REPORTS_PATH, [])
session = None   # dict while a study session is running


# ---------------- levels ----------------
def level_info(xp):
    """Level n starts at 50*n*(n-1) XP: 0, 100, 300, 600, 1000, ..."""
    level = 1
    while 50 * (level + 1) * level <= xp:
        level += 1
    start = 50 * level * (level - 1)
    end = 50 * (level + 1) * level
    return level, xp - start, end - start


# ---------------- session control ----------------
def start_session(subject, goal, work_min=25, break_min=5):
    global session
    with lock:
        if session:
            return False, "A session is already running"
        now = time.time()
        session = {
            "id": uuid.uuid4().hex[:8], "subject": subject.strip()[:60] or "Study",
            "goal": goal.strip()[:140], "started": now,
            "work_min": max(1, min(120, int(work_min))), "break_min": max(1, min(60, int(break_min))),
            "phase": "work", "phase_started": now, "pomodoros": 0,
            "xp": 0.0, "clean_run": 0.0, "last_domain": None, "last_sample": 0.0,
            "stats": {"active": 0.0, "states": {}, "moods": {}, "domains": {}, "index_sum": 0.0,
                      "blink_sum": 0.0, "blink_time": 0.0, "switches": 0, "best_clean_run": 0.0,
                      "counts": {"doom": 0, "phone": 0, "nudge": 0, "override": 0,
                                 "stuck": 0, "tired": 0}},
            "yawns_at_start": None, "yawns": 0, "timeline": [],
        }
        return True, "started"


def start_break():
    with lock:
        if session and session["phase"] == "work":
            elapsed = time.time() - session["phase_started"]
            if elapsed >= 0.8 * session["work_min"] * 60:   # nearly done counts as a pomodoro
                session["pomodoros"] += 1
                session["xp"] += POMODORO_XP
            session["phase"], session["phase_started"] = "break", time.time()
            return True
    return False


def resume_work():
    with lock:
        if session and session["phase"] == "break":
            session["phase"], session["phase_started"] = "work", time.time()
            return True
    return False


def focus_mode_active():
    with lock:
        return bool(session and session["phase"] == "work")


def record_event(kind):
    with lock:
        if session and kind in session["stats"]["counts"]:
            session["stats"]["counts"][kind] += 1


def tick(dt, info):
    """info: state, index, domain, category, expression, blink_rate, yawns_total. Returns popup events."""
    events = []
    with lock:
        s = session
        if not s:
            return events
        now = time.time()
        st = s["stats"]
        state = info["state"]

        if s["yawns_at_start"] is None:
            s["yawns_at_start"] = info.get("yawns_total", 0)
        s["yawns"] = info.get("yawns_total", 0) - s["yawns_at_start"]

        if state != "AFK" and s["phase"] == "work":
            st["active"] += dt
            st["states"][state] = st["states"].get(state, 0) + dt
            st["index_sum"] += info["index"] * dt
            mood = info.get("expression")
            if mood and mood != "-":
                st["moods"][mood] = st["moods"].get(mood, 0) + dt
            if state in ("Distracted", "Doom-scrolling", "Idle Tab") and info.get("domain"):
                st["domains"][info["domain"]] = st["domains"].get(info["domain"], 0) + dt
            s["xp"] += XP_PER_MINUTE.get(state, 0) * dt / 60
            if state in BAD_STATES:
                s["clean_run"] = 0.0
            else:
                s["clean_run"] += dt
                st["best_clean_run"] = max(st["best_clean_run"], s["clean_run"])
            if info.get("blink_rate") is not None:
                st["blink_sum"] += info["blink_rate"] * dt
                st["blink_time"] += dt

        domain = info.get("domain")
        if domain and s["last_domain"] and domain != s["last_domain"]:
            st["switches"] += 1
        s["last_domain"] = domain or s["last_domain"]

        if now - s["last_sample"] >= TIMELINE_STEP:
            s["last_sample"] = now
            s["timeline"].append([round(now - s["started"]), "Break" if s["phase"] == "break" else state])

        elapsed = now - s["phase_started"]
        if s["phase"] == "work" and elapsed >= s["work_min"] * 60:
            s["pomodoros"] += 1
            s["xp"] += POMODORO_XP
            s["phase"], s["phase_started"] = "break", now
            events.append(("pomodoro", f"Pomodoro #{s['pomodoros']} done!  +{POMODORO_XP} XP\n"
                                       f"Take a {s['break_min']}-minute break: stand up,\n"
                                       "drink water, look out of the window."))
        elif s["phase"] == "break" and elapsed >= s["break_min"] * 60:
            s["phase"], s["phase_started"] = "work", now
            goal = f": {s['goal']}" if s["goal"] else ""
            events.append(("pomodoro", f"Break is over.\nBack to {s['subject']}{goal}"))
    return events


def stop_session(goal_done=False):
    global session
    with lock:
        s = session
        if not s:
            return None
        session = None
        report = build_report(s, goal_done, time.time())
        reports.append(report)
        save_json(REPORTS_PATH, reports)
        save_json(PROFILE_PATH, profile)
        return report


# ---------------- reports ----------------
def top_items(d, n, total=None):
    items = sorted(d.items(), key=lambda kv: kv[1], reverse=True)[:n]
    if total:
        return [[k, round(100 * v / total)] for k, v in items]
    return [[k, round(v / 60, 1)] for k, v in items if v >= 6]


def make_tips(r):
    tips = []
    if r["doom_episodes"]:
        tips.append(f"You started doom-scrolling {r['doom_episodes']}x. Log out of the feed apps "
                    "while studying, or keep Focus mode on.")
    if r["phone_pickups"]:
        tips.append(f"You picked up your phone {r['phone_pickups']}x. Put it in another room "
                    "or face down out of reach.")
    if r["attention_span_min"] < 3 and r["switches"] >= 5:
        tips.append(f"You switched tasks every {r['attention_span_min']} min on average. "
                    "Close extra tabs and work on one thing per pomodoro.")
    if r["avg_blink"] is not None and r["avg_blink"] < 8:
        tips.append("You blinked rarely. Use the 20-20-20 rule: every 20 min, look 6 m away for 20 s.")
    stuck = sum(p for m, p in r["moods"] if m in ("Frustrated", "Confused / Surprised"))
    if stuck >= 20 or r["stuck_alerts"]:
        tips.append("The topic seemed hard. Try the 'explain simpler' study tip or start "
                    "from an easier example next time.")
    if r["yawns"] >= 3 or r["tired_alerts"]:
        tips.append("You looked tired. Short breaks, water and fresh air help more than pushing through.")
    if r["focus_pct"] >= 80:
        tips.append("Great focus! Keep the same setup and time of day.")
    if not tips:
        tips.append("Solid session. Next time, set a concrete goal to measure progress.")
    return tips[:4]


def build_report(s, goal_done, now):
    st = s["stats"]
    active = max(1.0, st["active"])
    states = st["states"]
    focus = sum(states.get(k, 0) for k in FOCUS_STATES)
    distracted = sum(states.get(k, 0) for k in DISTRACTED_STATES)
    counts = st["counts"]
    xp = s["xp"] + (GOAL_XP if goal_done else 0)
    xp = int(round(xp))

    # streak + profile
    today = datetime.date.today()
    if focus / 60 >= STREAK_MIN_FOCUS_MINUTES:
        last = profile["last_day"]
        if last != today.isoformat():
            yesterday = (today - datetime.timedelta(days=1)).isoformat()
            profile["streak"] = profile["streak"] + 1 if last == yesterday else 1
            profile["last_day"] = today.isoformat()
    profile["xp"] += xp
    profile["sessions"] += 1
    profile["focus_minutes"] = round(profile["focus_minutes"] + focus / 60, 1)

    earned = []
    def badge(key, condition):
        if condition and key not in profile["badges"]:
            profile["badges"].append(key)
            earned.append(key)
    badge("first", True)
    badge("deep", st["best_clean_run"] >= 25 * 60)
    badge("phonefree", active >= 25 * 60 and counts["phone"] == 0)
    badge("pomo4", s["pomodoros"] >= 4)
    badge("goal", goal_done)
    badge("streak3", profile["streak"] >= 3)

    report = {
        "id": s["id"], "subject": s["subject"], "goal": s["goal"], "goal_done": bool(goal_done),
        "started": s["started"], "ended": now,
        "duration_min": round((now - s["started"]) / 60, 1),
        "active_min": round(active / 60, 1),
        "focus_pct": round(100 * focus / active),
        "focused_min": round(focus / 60, 1),
        "distracted_min": round(distracted / 60, 1),
        "pomodoros": s["pomodoros"],
        "avg_index": round(st["index_sum"] / active),
        "doom_episodes": counts["doom"], "phone_pickups": counts["phone"],
        "nudges": counts["nudge"], "overrides": counts["override"],
        "stuck_alerts": counts["stuck"], "tired_alerts": counts["tired"],
        "switches": st["switches"],
        "attention_span_min": round(active / 60 / (st["switches"] + 1), 1),
        "best_streak_min": round(st["best_clean_run"] / 60, 1),
        "top_distractions": top_items(st["domains"], 3),
        "moods": top_items(st["moods"], 4, total=sum(st["moods"].values()) or 1),
        "avg_blink": round(st["blink_sum"] / st["blink_time"]) if st["blink_time"] > 60 else None,
        "yawns": s["yawns"],
        "xp_earned": xp,
        "new_badges": [BADGES[k][0] for k in earned],
        "timeline": s["timeline"],
    }
    report["tips"] = make_tips(report)
    return report


# ---------------- views for the window ----------------
def session_view():
    with lock:
        s = session
        if not s:
            return None
        now = time.time()
        st = s["stats"]
        active = max(1.0, st["active"])
        focus = sum(st["states"].get(k, 0) for k in FOCUS_STATES)
        phase_total = (s["work_min"] if s["phase"] == "work" else s["break_min"]) * 60
        return {
            "id": s["id"], "subject": s["subject"], "goal": s["goal"], "phase": s["phase"],
            "phase_left": max(0, round(phase_total - (now - s["phase_started"]))),
            "phase_total": phase_total, "elapsed": round(now - s["started"]),
            "pomodoros": s["pomodoros"], "xp": int(s["xp"]),
            "focus_pct": round(100 * focus / active) if st["active"] > 5 else None,
            "counts": dict(st["counts"]), "switches": st["switches"],
            "timeline": s["timeline"][-720:],
        }


def profile_view():
    with lock:
        level, have, need = level_info(profile["xp"])
        return {"xp": profile["xp"], "level": level, "level_xp": have, "level_need": need,
                "streak": profile["streak"], "sessions": profile["sessions"],
                "focus_minutes": profile["focus_minutes"],
                "badges": [{"name": BADGES[k][0], "info": BADGES[k][1]} for k in profile["badges"] if k in BADGES]}


def report_list():
    with lock:
        return [{k: r[k] for k in ("id", "subject", "goal", "started", "duration_min", "focus_pct", "xp_earned")}
                for r in reversed(reports[-30:])]


def get_report(report_id):
    with lock:
        for r in reports:
            if r["id"] == report_id:
                return r
    return None


# ---------------- study tips ----------------
STUDY_TIPS = {
    "explain": "Try the Feynman trick: explain the topic out loud in simple words as if to a 10-year-old. "
               "Where you get stuck is exactly the part to re-read.",
    "example": "Find the simplest possible example in your notes or textbook and solve it step by step. "
               "Then change one number and solve it again.",
    "quiz": "Cover your notes and write down 3 questions about the topic. Answer them, then check.",
}


def study_tip(mode):
    """A built-in study technique for when you're stuck. Works offline; nothing is sent anywhere."""
    return {"ok": True, "text": STUDY_TIPS.get(mode, STUDY_TIPS["explain"])}
