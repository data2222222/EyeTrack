# Study Focus: browser activity + camera attention

Two parts:
- `extension/`: Chrome extension (MV3). Sends the active **domain** (never the full URL), its category, idle state and tab-switch count to the engine.
- `engine/engine.py`: Python. Runs the camera tracker (MediaPipe Face Landmarker, ~8 FPS, frames only in memory), the local HTTP bridge on `127.0.0.1:8000` and the always-on-top status overlay with popups.

## Setup (≈5 min)

```bash
cd engine
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python engine.py               # first run downloads face_landmarker.task (~3 MB)
python engine.py --no-camera   # fallback: simulate the camera with keys P / F
```
On Linux, install Tk if it's missing: `sudo apt install python3-tk`. On macOS, allow camera access for your terminal.

Extension: open `chrome://extensions`, turn on **Developer mode**, click **Load unpacked** and select `extension/`.
Badge: `ON` = focused, `!` = distracted, `AFK`, `off` = engine not running.

## Decision matrix

| Browser | Camera | State | Action |
|---|---|---|---|
| Productive | Facing | Focused | silent |
| Productive | Away / looking down | Reading / Thinking | silent (no false alarm) |
| Distraction | Facing | Distracted | nudge popup after 60 s ("5 more minutes" snoozes) |
| Distraction | Not facing | Idle Tab | silent |
| Other app in front (VS Code, PDF…) | Facing | Other App | silent |
| Neutral + ≥15 tab switches / 5 min | Facing | Scattered | lowers the index |
| Any | No face < 3 min | Away | clock keeps running |
| Any | No face ≥ 3 min, or screen locked | AFK | session clock paused, counts as a break |

- **Productivity Index:** time-weighted average of state scores over the last 10 minutes (Focused 1.0 … Distracted 0.0).
- **Eye-rest break:** after 50 min of active time, a 20-second countdown popup appears.
- **Calibration:** for the first ~2 s the engine learns your "looking at the screen" pose. Press **C** to recalibrate (e.g. after moving the laptop).

## Demo keys (click the overlay first)
- **D:** simulate 20 min of distraction → index drops and the focus popup appears
- **B:** simulate 50 min of study → eye-rest popup
- **C:** recalibrate, **Q:** quit
- `pip install pynput` adds global hotkeys **Ctrl+Shift+D / Ctrl+Shift+B** (macOS asks for Accessibility permission).

## Tuning
All thresholds are at the top of `engine.py` (`NUDGE_AFTER_SECONDS`, `AFK_AFTER_SECONDS`, `YAW_TOLERANCE`, …). Domain lists are at the top of `extension/background.js`.
For a live demo, set `NUDGE_AFTER_SECONDS = 15` so the nudge fires quickly.

`GET http://127.0.0.1:8000/status` returns the current state as JSON (handy for a future web dashboard).
