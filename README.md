# EyeTrack — desktop focus sessions

A calm desktop flow for one focus block: optionally enter a goal, start a 25-minute session (5-minute break), watch a live camera view with a focus score, and review where your attention went. The Chrome extension supplies website activity to the desktop app. Camera observations are estimates, not proof of attention or productivity.

Two parts:
- `extension/`: Chrome extension. Sends the active **domain**, the **URL path** (query string and fragment stripped, at most 3 segments, e.g. `youtube.com/watch`), the **page title**, scrolling amount, idle state and tab switches to the engine. Incognito tabs send the domain only. Shows the focus-mode screen on distracting sites during a study session.
- `engine/engine.py`: Python. Camera tracking (MediaPipe face landmarks, eyes, expressions, phone detector), the decision engine, the desktop window (the only UI: live view, study sessions, reports) and the local server on `127.0.0.1:8000` that the extension talks to.
- `engine/desktop.py`: PySide6 setup, live dashboard and summary screens; `engine/widgets.py`: its painted widgets (camera view, timer ring, trend, split bar).
- `engine/study.py`: timestamp-based session clock, pauses, actual breaks and session summaries.

## Quick start

```bash
python setup.py        # python3 setup.py on macOS/Linux
```
One script, safe to re-run. It checks Python (3.10 to 3.14) and creates `engine/.venv`, installs the dependencies, downloads the models, optionally stores your Jev API key (Enter to skip), checks the extension files, then opens `chrome://extensions` with the extension folder path on your clipboard and the folder open in your file manager. It waits until the extension reports in ("Extension connected") and offers to start the app. Flags: `--no-input`, `--skip-models`, `--skip-extension`, `--start`.

**The one manual step** (Chrome does not allow installing an extension silently): on the page that opens, turn on **Developer mode** (top right), click **Load unpacked**, paste the path (Ctrl+L, or Cmd+Shift+G on macOS) or pick the folder that opened.

Later runs: `start.bat` (Windows) or `./start.sh` (macOS/Linux). Both pass options through to the engine: `--no-camera` (simulated camera input for testing), `--compact` (smaller desktop window). See *Platforms* below for OS notes.

After updating the extension, press the reload icon on its card and **reload open tabs** (scroll tracking and the focus screen only run in tabs opened/reloaded after that). Choose your setup in the desktop window and press **Start session**. The camera stays off until you start a camera-enabled session.

<details>
<summary>Manual setup</summary>

```bash
cd engine
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python engine.py                   # first run downloads 2 small models (~10 MB)
```
Extension: `chrome://extensions` > **Developer mode** > **Load unpacked** > select `extension/`.
</details>

## Platforms

Windows, macOS and Linux run the same code (CI tests all three on Python 3.12). Use Python 3.10 to 3.14.

- **Windows**: camera via DirectShow; Qt supplies the desktop interface.
- **macOS**: allow camera access for your terminal/Python in System Settings > Privacy & Security > Camera. Model downloads use the `certifi` CA bundle. Qt is installed with the Python requirements.
- **Linux**: camera via V4L2 (`/dev/video0`, with camera access for your desktop user). If Qt reports a missing XCB cursor library, install `libxcb-cursor0` using your distribution package manager. The desktop interface no longer requires Tk.

Technical camera measurements and a UI-only check-in preview are behind the ⋯ menu.

## Desktop session flow

1. **Set up:** an optional goal, plus two small dropdowns: *Working with* (**Computer only** or **Computer + paper**) and *Rhythm* (**25 min focus · 5 min break** by default; also 50/10 and 15/3). The camera is on by default and can be switched off. In *Computer + paper* mode, looking down toward the desk counts as on task.
2. **Work:** the camera preview is shown by default (a **Hide** button on it hides the picture while tracking continues), with a live state chip (**On screen**, **On paper**, **Looking away**, **Out of view**, **On phone**) and how long it has lasted. Beside it, a countdown ring with **Pause / Resume**, **Take a break** and **End**, and a live **Focus score** with a trend line, look-away and phone counts and the current site. A bar shows where your attention went this session. The ⋯ menu holds screen calibration, tracking details and Chrome setup.
3. **Review:** the final focus score and trend, active/break/paused time, look-aways, phone pickups, where your attention and time went, and an optional goal-completion self-report. **New session** returns to setup.

**Focus score (0 to 100):** the share of tracked time spent on task. On task means the camera sees you looking at the screen (or at paper, in *Computer + paper* mode) and you are not on a distracting site. Looking away, being out of view, a phone in view, or a distracting site all count as off task. Time without a fresh camera observation is not scored, and the live number covers the last 5 minutes of active time and appears after about 5 tracked seconds. Without a camera, the score comes from Chrome sites only. A look-away is counted when you look away for 3 seconds or more. It is an estimate from a webcam, not a measure of productivity.

Only an explicit pause or break stops active time. Camera absence and AFK do not pause it. Resuming preserves the remaining work block. Five-minute breaks can end early or stay open longer; they never auto-resume. A completed block stops at its planned duration instead of automatically starting another block.

The camera starts only for camera-enabled work and is stopped/joined on pause, break, completion, end and app close. The real camera and both detector resources are released before shutdown. Calibration/tracking remains in `tracking.py` and is being developed separately.

Reports are saved locally in `engine/data/sessions.json`; older reports are preserved. The UI shows the focus score described above, but no mood, XP or streaks. Website and camera categories each describe active time independently. Missing/stale camera observations are unavailable after one second. Browser observation freshness still follows the existing collector's heartbeat; improving event-boundary accounting is a remaining browser task.

**Focus screen (extension):** during a work block, a distracting site is covered by a screen showing the time left in the block, your goal, and who called the site a distraction (`Jev 0.97`, `Jev, cached` or `site list`). **Back to studying** goes back in the tab's history (or to a new tab); **Give me 5 min** unlocks after 10 s, allows that site for 5 minutes and is counted as a skip, shown on the screen. While it is up, keys, scrolling and media playback do not reach the page. It disappears by itself when the block ends, and within 30 s (the extension's heartbeat) when you pause, take a break or end the session. It is an intervention, not navigation blocking. User domain settings remain browser-integration work. Loud strict-mode alarms are not implemented in this interface change.

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

**Where you see it**: the desktop Browser card shows the current domain and effective category. The classifier retains verdict source/confidence internally; Jev is optional and the app runs without a key.

**Fallbacks**: no key, no `typesafe-sdk` or no network → the extension's lists are used (the engine never needs Jev to run). A small local model (MiniLM, `engine/models/`) scores similarity to your goal as a second opinion; its guesses are never strong enough to override the lists today. If the classifier cannot be imported the engine prints one line and behaves exactly as before.

## Observation signals

Camera and website observations are kept separate in the summary. A visible phone is not proof of phone use; an off-camera phone is unobserved. The camera-derived legacy state does not control the session timer. Expression/fatigue heuristics and the old fake-time keyboard demos are not part of the new session interface. **⋯ → Preview a check-in** previews UI without incrementing tracked nudges.

## Accuracy tips
During a session with the camera enabled, choose **Calibrate screen…** in the ⋯ menu. Follow the five dots with your eyes, keeping your usual sitting position; the ring fills while tracking is stable. Repeat this after moving your camera, chair, or screen. **Esc** cancels and keeps the last completed calibration. If eye movement is unclear, calibration shows a warning and keeps the previous profile (or a center-only fallback on the first run). Without guided calibration, look at screen center and hold still for about three seconds for the automatic center calibration. Calibration is kept for the current run.

Use even light on your face and avoid a bright window behind you. Brief blinks are ignored for attention; prolonged eye closure still registers. Head tilt and sitting off-center no longer count as looking away by themselves. Leaning closer than you were when calibrating widens the screen limits (the screen spans a wider angle), a head turned one way with the eyes turned back toward the screen still counts as on screen, and with a strongly turned head the nearer, less foreshortened eye is trusted. Guided calibration extends the edge dots out to the real screen edges, so the corners count as on screen. Tiny, clipped, or unreliable eye landmarks show a tracking hint and are excluded from calibration. This is a webcam estimate of attention, not a precise screen-coordinate eye tracker. Calibration defaults are in `engine/tracking.py`; other thresholds such as `DOOM_SCROLL_PX` and `PHONE_SCORE` remain at the top of `engine.py`.

## Privacy
Camera frames stay in memory and are never saved or uploaded. The extension sends the domain, the URL path (no query string or fragment), the page title and scroll counts to `127.0.0.1` only; incognito tabs send the domain only. The local server refuses requests from other websites. Text leaves your laptop in one case only: **during a study session with a Jev key configured**, your goal, the domain, URL path and page title of the active tab are sent to the Jev API to classify it (see *Goal-aware classification*). Without a key, nothing about your pages leaves the machine.
