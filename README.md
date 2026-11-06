# Study Focus: a camera + browser study coach

Study Focus watches *how* you study (browser activity plus your webcam, processed only on your laptop) and helps you stay focused: Pomodoro sessions, distraction and doom-scroll detection, phone detection, tiredness and frustration alerts, study tips when you're stuck, session reports, XP and streaks.

Two parts:
- `extension/`: Chrome extension. Sends the active **domain**, the **URL path** (query string and fragment stripped, at most 3 segments, e.g. `youtube.com/watch`), the **page title**, scrolling amount, idle state and tab switches to the engine. Incognito tabs send the domain only. Shows the focus-mode screen on distracting sites during a study session.
- `engine/engine.py`: Python. Camera tracking (MediaPipe face landmarks, eyes, expressions, phone detector), the decision engine, the desktop window (the only UI: live view, study sessions, reports) and the local server on `127.0.0.1:8000` that the extension talks to.
- `engine/study.py`: study sessions, XP, reports and study tips, used by the window.

## Setup

```bash
cd engine
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python engine.py                   # first run downloads 2 small models (~10 MB)
```
Options: `--no-camera` (simulate with keys P / F), `--compact` (small status bar only).
Linux: `sudo apt install python3-tk` if Tk is missing. macOS: allow camera access for the terminal.

Extension: `chrome://extensions` → **Developer mode** → **Load unpacked** → select `extension/`.
After updating the extension, press ↻ on its card and **reload open tabs** (scroll tracking and the focus screen only run in tabs opened/reloaded after that).

Start a study session in the engine window (live view, **Study session** panel at the bottom).

## Features

**Study sessions (engine window)**: type a subject and goal, set work/break minutes (25/5 by default) and press **Start session**. While it runs the panel shows the phase and countdown with **Break / Resume** and **Stop** (asks "Did you reach your goal?", then shows the report). A profile line shows level, XP to the next level, streak and badges; **History** lists past sessions and opens their reports. During focus blocks, **Focus mode** is on: distracting sites get a full-page "You're in a study session" screen with *Back to studying* (goes back in the tab's history, or to a new tab) or *Continue anyway* (enabled after 10 s, allows that site for 5 min; counted in the report). During breaks there are no distraction alerts.

**Distraction detection**
- *Distracted*: distracting site + eyes on it → nudge after 60 s.
- *Doom-scrolling*: on any non-study site, ≥8000 px of scrolling per minute (~8 screens) or ≥4 new short videos per minute (Shorts, Reels, TikTok), sustained 60 s → alert.
- *On Phone*: the camera's object detector sees a phone for 3+ s → state "On Phone", counts a pickup; popup after 20 s.
- *Context switching*: switches between sites/apps in the last 30 min and the average minutes per task (attention span).

**Wellbeing (camera)**: eye gaze (iris + model eye-direction), blink rate, eyes closed ≥2 s (sleepy), yawns, expressions (Happy, Concentrating, Frustrated, Confused, Unhappy, Yawning). Tired → "Start break now"; frustrated for most of a minute → "Stuck?" with a button to the study tips; blink rate < 6/min → eye-rest popup. Expressions are estimates of facial movement, not mind reading.

**Study tips**: *Explain simpler*, *Easy examples*, *Quiz me* in the "Stuck?" popup (button *Study tips*) give a built-in study technique for when you're stuck. They work offline and send nothing anywhere.

**Reports, XP, streaks**: when you stop a session a report window opens: focus %, timeline, distractions, phone pickups, doom-scroll episodes, attention span, mood, blink rate, tips. XP: 2/min focused, 1/min reading or other app, +20 per pomodoro, +30 for reaching your goal. Levels, daily streak (≥10 focused min per day) and badges (First Session, Deep Diver, Phone-Free, Pomodoro Pro, Goal Getter, On Fire). Saved in `engine/data/`.

## Goal-aware classification (Jev)

During a study session, the site lists in the extension are only a fallback. Each tab is also judged against your session (`subject: goal`) by Jev (TypeSafe), so a physics lecture on youtube.com can count as *productive* and funny cats as *distraction*. The decision matrix below is unchanged; only the category it receives gets smarter. Outside a study session nothing is sent and the extension's lists apply as before.

**Setup**
```bash
pip install -r requirements.txt
export TYPESAFE_API_KEY=...                 # or {"typesafe_api_key": "..."} in engine/data/config.json
python -m classifier.fetch_model            # optional offline model (~90 MB) into engine/models/
python -m classifier.spike                  # optional: try 5 sample pages against Jev
```

**What is sent to Jev**: your goal (subject + goal text), the domain, the URL path without query or fragment, and the page title (plus the browser name, "Chrome"). Never camera frames. Never incognito tabs, password managers, banking sites or anything on your own never-send list (`"classifier": {"never_send": {"domains": [...], "apps": [...]}}` in `config.json`): those are not sent, not even to the local model.

**How it behaves**: one question per page ("productive, neutral or distraction?"). Answers are cached in `engine/data/classifications.json` for 7 days, per site + page title + goal. At most 5 requests per domain per hour; after that the latest answer for that domain is reused. Answers with confidence below 0.5 are discarded. Requests run in the background, so a new page keeps its list category until Jev answers (a few seconds, shown as "Jev pending").

**Where you see it**: the *Category* row shows the verdict and its source, e.g. `distraction (Jev 0.97)`, `productive (Jev, cached)`, `productive (list)`. The source is one of `jev`, `cache`, `override`, `private`, `list`; "Jev pending" is shown while an answer is on its way.

**Fallbacks**: no key, no `typesafe-sdk` or no network → the extension's lists are used (the engine never needs Jev to run). A small local model (MiniLM, `engine/models/`) scores similarity to your goal as a second opinion; its guesses are never strong enough to override the lists today. If the classifier cannot be imported the engine prints one line and behaves exactly as before.

## Decision matrix

| Browser / camera | State | Action |
|---|---|---|
| Phone in hand (camera) | On Phone | popup after 20 s, pickup counted |
| Non-study site + endless scrolling / short videos | Doom-scrolling | alert after 60 s |
| Study site + eyes on screen | Focused | silent |
| Study site + looking away / down | Reading / Thinking | silent (no false alarm) |
| Distracting site + eyes on it | Distracted | nudge after 60 s; focus screen in a session |
| Distracting site, not watching | Idle Tab | silent |
| Other app in front (VS Code, PDF…) | Other App | silent |
| Neutral + ≥15 tab switches / 5 min | Scattered | lowers the index |
| No face < 3 min / ≥ 3 min or screen locked | Away / AFK | AFK pauses the clock |

**Productivity Index**: time-weighted average of state scores over the last 10 minutes.

## Demo keys (desktop window)
D distraction · S doom-scroll · M phone · T tired · X stuck · B eye break · C recalibrate · V live view · Q quit.

## Accuracy tips
Look at the middle of the screen and press **C** (2 s). Light on your face, no bright window behind you. Thresholds are at the top of `engine.py` (`YAW_TOLERANCE`, `GAZE_H_TOLERANCE`, `DOOM_SCROLL_PX`, `PHONE_SCORE`, …). For a live demo, `NUDGE_AFTER_SECONDS = 15` and `DOOM_AFTER_SECONDS = 20` make alerts fire faster.

## Privacy
Camera frames stay in memory and are never saved or uploaded. The extension sends the domain, the URL path (no query string or fragment), the page title and scroll counts to `127.0.0.1` only; incognito tabs send the domain only. The local server refuses requests from other websites. Text leaves your laptop in one case only: **during a study session with a Jev key configured**, your goal, the domain, URL path and page title of the active tab are sent to the Jev API to classify it (see *Goal-aware classification*). Without a key, nothing about your pages leaves the machine.
