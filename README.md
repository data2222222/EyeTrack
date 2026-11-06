# EyeTrack — desktop focus sessions

A clean desktop flow for one focus block: choose computer, notebook or both; optionally enter a goal; work with a timer and optional local camera; then review actual session time. The Chrome extension supplies website activity to the desktop app. Camera observations are estimates, not proof of attention or productivity.

Two parts:
- `extension/`: Chrome extension. Sends the active **domain**, the **URL path** (query string and fragment stripped, at most 3 segments, e.g. `youtube.com/watch`), the **page title**, scrolling amount, idle state and tab switches to the engine. Incognito tabs send the domain only. Shows the focus-mode screen on distracting sites during a study session.
- `engine/engine.py`: Python. Camera tracking (MediaPipe face landmarks, eyes, expressions, phone detector), the decision engine, the desktop window (the only UI: live view, study sessions, reports) and the local server on `127.0.0.1:8000` that the extension talks to.
- `engine/desktop.py`: PySide6 setup, active-session and summary screens.
- `engine/study.py`: timestamp-based session clock, pauses, actual breaks and session summaries.

## Quick start

```bash
python setup.py        # python3 setup.py on macOS/Linux
```
One script, safe to re-run. It checks Python (3.10 to 3.12) and creates `engine/.venv`, installs the dependencies, downloads the models, optionally stores your Jev API key (Enter to skip), checks the extension files, then opens `chrome://extensions` with the extension folder path on your clipboard and the folder open in your file manager. It waits until the extension reports in ("Extension connected") and offers to start the app. Flags: `--no-input`, `--skip-models`, `--skip-extension`, `--start`.

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

Windows, macOS and Linux run the same code (CI tests all three on Python 3.11 and 3.12). Use Python 3.10 to 3.12: the `mediapipe` wheels do not cover newer versions yet.

- **Windows**: camera via DirectShow; Qt supplies the desktop interface.
- **macOS**: allow camera access for your terminal/Python in System Settings > Privacy & Security > Camera. Model downloads use the `certifi` CA bundle. Qt is installed with the Python requirements.
- **Linux**: camera via V4L2 (`/dev/video0`, with camera access for your desktop user). If Qt reports a missing XCB cursor library, install `libxcb-cursor0` using your distribution package manager. The desktop interface no longer requires Tk.

The session UI uses visible controls. Technical camera measurements and a UI-only check-in preview are behind **Diagnostics**.

## Desktop session flow

1. **Set up:** choose Computer / Notebook / Computer & notebook, enter an optional goal, choose 15 / 25 / 45 minutes, and choose whether to use the camera. The mode is saved with the session; notebook-specific calibration is a separate work item.
2. **Work:** a large remaining-time clock, camera/browser status and **Pause / Resume**, **Take a break**, **End session** controls. Camera preview is collapsible; measurements stay in Diagnostics.
3. **Review:** actual active time, paused time, actual break duration/count, check-ins shown, separate website/camera observations and optional goal-completion self-report. **Start another session** returns to setup.

Only an explicit pause or break stops active time. Camera absence and AFK do not pause it. Resuming preserves the remaining work block. Five-minute breaks can end early or stay open longer; they never auto-resume. A completed block stops at its planned duration instead of automatically starting another block.

The camera starts only for camera-enabled work and is stopped/joined on pause, break, completion, end and app close. The real camera and both detector resources are released before shutdown. Calibration/tracking remains in `tracking.py` and is being developed separately.

Reports are saved locally in `engine/data/sessions.json`; older reports are preserved. The UI does not show productivity scores, mood, XP or streaks. Website and camera categories each describe active time independently. Missing/stale camera observations are unavailable after one second. Browser observation freshness still follows the existing collector's heartbeat; improving event-boundary accounting is a remaining browser task.

The extension's existing focus overlay is an intervention, not navigation blocking. User domain settings, return-to-work behavior and overlay cleanup remain browser-integration work. Loud strict-mode alarms are not implemented in this interface change.

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

Camera and website observations are kept separate in the summary. A visible phone is not proof of phone use; an off-camera phone is unobserved. The camera-derived legacy state does not control the session timer. Expression/fatigue heuristics and the old fake-time keyboard demos are not part of the new session interface. **Diagnostics → Preview check-in** previews UI without incrementing tracked nudges.

## Accuracy tips
During a session with the camera enabled, choose **Calibrate screen** in the camera panel or **Diagnostics**. Follow the five dots with your eyes, keeping your usual sitting position; the ring fills while tracking is stable. Repeat this after moving your camera, chair, or screen. **Esc** cancels and keeps the last completed calibration. If eye movement is unclear, calibration shows a warning and keeps the previous profile (or a center-only fallback on the first run). Without guided calibration, look at screen center and hold still for about three seconds for the automatic center calibration. Calibration is kept for the current run.

Use even light on your face and avoid a bright window behind you. Brief blinks are ignored for attention; prolonged eye closure still registers. Head tilt and sitting off-center no longer count as looking away by themselves. Tiny, clipped, or unreliable eye landmarks show a tracking hint and are excluded from calibration. This is a webcam estimate of attention, not a precise screen-coordinate eye tracker. Calibration defaults are in `engine/tracking.py`; other thresholds such as `DOOM_SCROLL_PX` and `PHONE_SCORE` remain at the top of `engine.py`.

## Privacy
Camera frames stay in memory and are never saved or uploaded. The extension sends the domain, the URL path (no query string or fragment), the page title and scroll counts to `127.0.0.1` only; incognito tabs send the domain only. The local server refuses requests from other websites. Text leaves your laptop in one case only: **during a study session with a Jev key configured**, your goal, the domain, URL path and page title of the active tab are sent to the Jev API to classify it (see *Goal-aware classification*). Without a key, nothing about your pages leaves the machine.
