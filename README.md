# Study Focus: a camera + browser study coach

Study Focus watches *how* you study (browser activity plus your webcam, processed only on your laptop) and helps you stay focused: Pomodoro sessions, distraction and doom-scroll detection, phone detection, tiredness and frustration alerts, an AI tutor, session reports, XP and streaks.

Three parts:
- `extension/`: Chrome extension. Sends the active **domain** (never the full URL), scrolling amount, idle state and tab switches to the engine. Shows the focus-mode screen on distracting sites during a study session. Clicking the icon opens the dashboard.
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
Camera frames stay in memory and are never saved or uploaded. The extension sends domains and scroll counts only to `127.0.0.1`. The local server refuses requests from other websites. Only the AI helper sends text (your question + subject) to the AI provider, and only when you click it.
