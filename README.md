# Study Focus: a camera + browser study coach

Study Focus watches *how* you study (browser activity plus your webcam, processed only on your laptop) and helps you stay focused: Pomodoro sessions, distraction and doom-scroll detection, phone detection, tiredness and frustration alerts, an AI tutor, session reports, XP and streaks.

Three parts:
- `extension/`: Chrome extension. Sends the active **domain**, the **URL path** (query string and fragment stripped, at most 3 segments, e.g. `youtube.com/watch`), the **page title**, scrolling amount, idle state and tab switches to the engine. Incognito tabs send the domain only. Shows the focus-mode screen on distracting sites during a study session. Clicking the icon opens the dashboard.
- `engine/engine.py`: Python. Camera tracking (MediaPipe face landmarks, eyes, expressions, phone detector), the decision engine, the desktop window and the local server on `127.0.0.1:8000`.
- `engine/study.py` + `engine/dashboard.html`: study sessions, XP, reports, AI helper, and the web dashboard at **http://127.0.0.1:8000**.

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

Open the dashboard: click the extension icon, or go to http://127.0.0.1:8000

## Features

**Study sessions (dashboard)**: subject + goal + Pomodoro (25/5 by default). During focus blocks, **Focus mode** is on: distracting sites get a full-page "You're in a study session" screen with *Back to studying* or *Continue anyway* (enabled after 10 s, allows that site for 5 min; counted in the report). During breaks there are no distraction alerts.

**Distraction detection**
- *Distracted*: distracting site + eyes on it → nudge after 60 s.
- *Doom-scrolling*: on any non-study site, ≥8000 px of scrolling per minute (~8 screens) or ≥4 new short videos per minute (Shorts, Reels, TikTok), sustained 60 s → alert.
- *On Phone*: the camera's object detector sees a phone for 3+ s → state "On Phone", counts a pickup; popup after 20 s.
- *Context switching*: switches between sites/apps in the last 30 min and the average minutes per task (attention span).

**Wellbeing (camera)**: eye gaze (iris + model eye-direction), blink rate, eyes closed ≥2 s (sleepy), yawns, expressions (Happy, Concentrating, Frustrated, Confused, Unhappy, Yawning). Tired → "Start break now"; frustrated for most of a minute → "Stuck?" with a button to the AI helper; blink rate < 6/min → eye-rest popup. Expressions are estimates of facial movement, not mind reading.

**AI study helper**: *Explain simpler*, *Easy examples*, *Quiz me* for whatever you're stuck on, in your language. Needs an Anthropic API key:
```bash
export ANTHROPIC_API_KEY=sk-ant-...      # before python engine.py
```
or create `engine/data/config.json`: `{"anthropic_api_key": "sk-ant-..."}`. Without a key you get offline study tips.

**Reports, XP, streaks**: at the end of a session you get a report: focus %, timeline, distractions, phone pickups, doom-scroll episodes, attention span, mood, blink rate, tips. XP: 2/min focused, 1/min reading or other app, +20 per pomodoro, +30 for reaching your goal. Levels, daily streak (≥10 focused min per day) and badges (First Session, Deep Diver, Phone-Free, Pomodoro Pro, Goal Getter, On Fire). Saved in `engine/data/`.

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

**Where you see it**: the *Category* row shows the verdict and its source, e.g. `distraction (Jev 0.97)`, `productive (Jev, cached)`, `productive (list)`. `GET /api/state` has `category_source` (`jev`, `cache`, `override`, `private`, `list`), `category_confidence`, `category_pending` and `jev_online`.

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

## Demo keys (desktop window) / demo buttons (dashboard)
D distraction · S doom-scroll · M phone · T tired · X stuck · B eye break · C recalibrate · V live view · Q quit.

## Accuracy tips
Look at the middle of the screen and press **C** (2 s). Light on your face, no bright window behind you. Thresholds are at the top of `engine.py` (`YAW_TOLERANCE`, `GAZE_H_TOLERANCE`, `DOOM_SCROLL_PX`, `PHONE_SCORE`, …). For a live demo, `NUDGE_AFTER_SECONDS = 15` and `DOOM_AFTER_SECONDS = 20` make alerts fire faster.

## Privacy
Camera frames stay in memory and are never saved or uploaded. The extension sends the domain, the URL path (no query string or fragment), the page title and scroll counts to `127.0.0.1` only; incognito tabs send the domain only. The local server refuses requests from other websites. Text leaves your laptop in two cases: the AI helper sends your question + subject to the AI provider when you click it, and, **during a study session with a Jev key configured**, your goal, the domain, URL path and page title of the active tab are sent to the Jev API to classify it (see *Goal-aware classification*). Without a key, nothing about your pages leaves the machine.
