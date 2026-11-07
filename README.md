# EyeTrack — desktop focus sessions

Presenting the project? See the [hackathon demo guide](docs/DEMO.md) for a short walkthrough and hardware-free fallback.

A calm desktop flow for one focus block: optionally enter a goal, start a 25-minute session (5-minute break), watch a live camera view with a focus score, and review where your attention went. The Chrome extension supplies website activity to the desktop app. Camera observations are estimates, not proof of attention or productivity.

Two parts:
- `extension/`: Chrome extension. Sends the active **domain**, the **URL path** (query string and fragment stripped, at most 3 segments, e.g. `youtube.com/watch`), the **page title**, scrolling amount, idle state and tab switches to the engine. Incognito tabs send the domain only. Shows the focus-mode screen on distracting sites during a study session.
- `engine/engine.py`: Python. Camera tracking (MediaPipe face landmarks, eyes, expressions, phone detector), the decision engine, the desktop window (the only UI: live view, study sessions, reports) and the local server on `127.0.0.1:8000` that the extension talks to.
- `engine/desktop.py`: PySide6 setup, live dashboard and summary screens; `engine/widgets.py`: its painted widgets (camera view, timer ring, trend, split bar).
- `engine/study.py`: timestamp-based session clock, pauses, actual breaks and session summaries.
- `engine/appmonitor.py`: desktop-app awareness (foreground app and a distracting-apps list), independent of Chrome.

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

## Developer testing

Run the extension regression tests from the repository root with Node.js 18 or newer:

```bash
node --test extension/tests/*.test.js
```

These dependency-free tests execute the actual background script with mocked Chrome APIs,
local-engine responses, and a deterministic clock. They cover delayed page titles, URL and
incognito privacy, and engine-unavailable fail-open behavior without Chrome or a running engine.
No npm install, model downloads, camera, or network access is needed.

After development setup, run the Python suite with `engine/.venv/bin/python -m pytest engine/tests -q`
(Windows: `engine\.venv\Scripts\python.exe -m pytest engine/tests -q`). Install `pytest` in that
environment first if needed. CI runs Python tests on all three platforms and extension tests on Linux.

## Platforms

Windows, macOS and Linux run the same code (CI tests all three on Python 3.12). Use Python 3.10 to 3.14.

- **Windows**: camera via DirectShow; Qt supplies the desktop interface.
- **macOS**: allow camera access for your terminal/Python in System Settings > Privacy & Security > Camera. Model downloads use the `certifi` CA bundle. Qt is installed with the Python requirements.
- **Linux**: camera via V4L2 (`/dev/video0`, with camera access for your desktop user). If Qt reports a missing XCB cursor library, install `libxcb-cursor0` using your distribution package manager. The desktop interface no longer requires Tk.

Settings, technical camera measurements and a UI-only check-in preview are behind the ⋯ menu.

## Desktop session flow

1. **Set up:** an optional goal, plus two small dropdowns: *Working with* (**Computer only** or **Computer + paper**) and *Rhythm* (**25 min focus · 5 min break** by default; also 50/10 and 15/3). The camera is on by default and can be switched off. In *Computer + paper* mode, looking down toward the desk counts as on task.
2. **Work:** the camera preview is shown by default (a **Hide** button on it hides the picture while tracking continues), with a live state chip (**On screen**, **On paper**, **Looking away**, **Out of view**, **On phone**) and how long it has lasted. Beside it, a countdown ring with **Pause / Resume**, **Take a break** and **End**, and a live **Focus score** with a trend line, look-away and phone counts. A compact status pill in the top bar, beside **Chrome connected**, shows the current Chrome tab or foreground app. Long titles are shortened, with the full title, domain and category on hover. Stale or disconnected observations show an unavailable state; pauses, breaks and completed blocks clear the live activity. Tab titles stay in memory and incognito tabs show only their domain. A bar shows where your attention went this session. The ⋯ menu holds settings, screen calibration, tracking details and Chrome setup.
3. **Review:** the final focus score and trend, active/break/paused time, look-aways, phone pickups, where your attention and time went, and an optional goal-completion self-report. **New session** returns to setup.

**Focus score (0 to 100):** the share of tracked time spent on task. On task means the camera sees you looking at the screen (or at paper, in *Computer + paper* mode) and you are not on a distracting site or in a distracting desktop app. Looking away, being out of view, a phone in view, or a distracting site or app all count as off task. Time without a fresh camera observation is not scored, and the live number covers the last 5 minutes of active time and appears after about 5 tracked seconds. Without a camera, the score comes from the Chrome site or desktop app in front. A look-away is counted when you look away for 3 seconds or more. It is an estimate from a webcam, not a measure of productivity.

Only an explicit pause or break stops active time. Camera absence and AFK do not pause it. Resuming preserves the remaining work block. Five-minute breaks can end early or stay open longer; they never auto-resume. A completed block stops at its planned duration instead of automatically starting another block.

### Settings and sounds

Open **⋯ → Settings…** from any screen to choose your defaults. Session length, break length, working mode, camera use and camera-preview visibility apply to the **next session**, never to a running block. Opening settings does not turn on the camera; hiding its preview does not stop tracking. **Cancel** discards changes and **Save settings** keeps them for your next launch.

Sounds are short, locally generated cues, with a master switch, volume, tone choices and separate switches for focus check-ins and block completion. **Sound changes apply as soon as you save**, including during a running session. You can preview a tone in settings. A completed block plays its cue once, not every timer refresh; the diagnostic check-in preview does not play a sound or count as a tracked nudge. Sounds are optional: if an audio backend or output device is unavailable, the session and visual reminders still work.

**Overlay:** a small always-on-top pill shows the time and your session state (`Focus 12:34 · 82`, `Paused`, `Break`, or `No session`). It is on by default, never takes keyboard focus and never uses the camera. Drag it and it snaps to the nearest screen corner (remembered); double-click it to bring EyeTrack forward; right-click for a menu. Hide it for now with the **×** that appears on hover, with **Ctrl+Shift+O**, or from **⋯ → Hide overlay**; bring it back the same way. To remove it completely, untick **Settings → Overlay → Show the overlay**; that setting persists and takes priority over the shortcut and menu. Some Linux Wayland desktops ignore always-on-top and window placement for apps.

**Phone and looking-away alerts:** Settings includes **Light**, **Strict** (default), and **Asian parent** modes. A confirmed phone continuously in view, looking away, or being out of view chimes after 3 seconds. Looking at paper in *Computer + paper* mode does not trigger looking-away alerts. Light starts gentle beep pairs at 30 seconds, repeating every 10 seconds; Strict starts the recorded hard beep (`engine/assets/beep-alarm.mp3`) at 15 seconds, repeating every 3 seconds; Asian parent plays the same hard beep from 10 seconds, restarting every second. If the file is missing or can't be decoded, a synthesized burst plays instead, and Light always uses its gentle synthesized pairs. Strictness changes apply as soon as settings are saved. Beeps respect the master sound switch, selected volume and check-in sound switch. Dismissing a check-in does not silence a continued episode; removing the phone stops its alarm, and returning to the screen (or paper in *Computer + paper* mode) stops looking-away alerts. Once the repeating looking-away alarm starts, you must stay on task for 2 continuous seconds to clear it; a shorter glance back keeps the same alarm episode and cadence. During that return, the check-in shows **Locking back in…** with a circular border that fills over the same 2 seconds. Looking away again resets the ring; completing it clears the alert. Phone and looking-away episodes have separate timers; switching between them starts a new episode. Alerts also stop on pause, break, completion, session end, camera failure or stale observations. Tentative detections never trigger alerts. Timing uses a monotonic clock and requires continuous fresh camera observations; phone and attention detection remain webcam estimates.

At the bottom of Settings, **Jev API key** offers a masked, write-only field and **Set key** button. Set key saves immediately, independently of Save settings/Cancel, and clears the field. The saved key is never displayed or loaded back into the field. Restart EyeTrack to use a new key. It is stored locally in `engine/data/config.json`, preserving other configuration; `TYPESAFE_API_KEY` in the environment takes priority. This is local file storage, not an operating-system credential vault. Leaving the field blank keeps the existing key.

**Blocked apps and sites:** **Settings → Blocked apps and sites** lists distractions you never want open. This is separate from the *distracting* lists, which only warn or count as off task; a blocked entry is closed or refused outright, during sessions and between them, and applies as soon as you save.

- *Sites:* type a domain (`reddit.com`; a pasted URL is reduced to its domain). The extension turns the list into browser redirect rules, so Chrome never loads the site or any subdomain, and tabs already open on it are replaced by a "This site is blocked" page. The extension picks up changes on its next report (within about 30 s, sooner when you switch tabs). The rules live in Chrome, so they keep working while EyeTrack is closed until the list changes; if the extension is not loaded, nothing is blocked. After updating, reload the extension in `chrome://extensions` (it now asks for the `declarativeNetRequest` permission). Incognito windows are only covered if you allow the extension there.
- *Apps:* type an app's process name (`discord`; `Discord.exe` works too, at least 3 letters). While EyeTrack is running, any process whose name starts with it is asked to close within about 2 s of opening (`steam` also closes `steamwebhelper`), and a notice names what was closed. Unsaved work in a closed app can be lost. Your own EyeTrack process, the programs that launched it, and core system processes (shells, the desktop, `systemd`, `explorer` and similar) are never closed. EyeTrack cannot stop an app from starting when it is not running.

Both lists are kept in `preferences.json`; the site list is sent only to the local extension on `127.0.0.1`, and neither list goes to Jev.

Preferences are stored locally in `engine/data/preferences.json`, separately from Jev configuration and session reports. No API key, camera image or browsing data is stored in preferences, and settings never send anything externally.

The camera starts only for camera-enabled work and is stopped/joined on pause, break, completion, end and app close. The real camera and both detector resources are released before shutdown. Calibration/tracking remains in `tracking.py` and is being developed separately.

Reports are saved locally in `engine/data/sessions.json`; older reports are preserved. The UI shows the focus score described above, but no mood, XP or streaks. Website and camera categories each describe active time independently. Missing/stale camera observations are unavailable after one second. Browser observation freshness still follows the existing collector's heartbeat; improving event-boundary accounting is a remaining browser task.

**Focus screen (extension):** during a work block, a distracting site is covered by a screen showing the time left in the block, your goal, and who called the site a distraction (`Jev 0.97`, `Jev, cached` or `site list`). **Back to studying** goes back in the tab's history (or to a new tab); **Give me 5 min** unlocks after 10 s, allows that site for 5 minutes and is counted as a skip, shown on the screen. While it is up, keys, scrolling and media playback do not reach the page. It disappears by itself when the block ends, and within 30 s (the extension's heartbeat) when you pause, take a break or end the session. It is an intervention; fully blocking a site is a separate setting (see *Blocked apps and sites*). Phone and looking-away alarm strictness is controlled in desktop Settings.

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

**How it behaves**: one question per page ("productive, neutral or distraction?"), asked once the page's title has loaded, so Jev always sees the title and never just a URL. Answers are cached in `engine/data/classifications.json` per page (URL path + title) and goal: for 1 day, or 2 hours on sites where pages vary a lot (Google, Bing, DuckDuckGo, YouTube, Wikipedia and LLM chats such as ChatGPT, Claude, Perplexity; set `"classifier": {"mixed_domains": [...]}` to change the list). One page's answer is never reused for another page of the same site. At most 30 requests per domain per hour; past that, new pages keep their list category until the hour rolls over. Answers with confidence below 0.5 are discarded. Requests run in the background, so a new page keeps its list category until Jev answers (a few seconds, shown as "Jev pending").

**Where you see it**: the desktop activity pill shows the current tab title, with its domain and effective category on hover. The classifier retains verdict source/confidence internally; Jev is optional and the app runs without a key.

**Fallbacks**: no key, no `typesafe-sdk` or no network → the extension's lists are used (the engine never needs Jev to run). A small local model (MiniLM, `engine/models/`) scores similarity to your goal as a second opinion; its guesses are never strong enough to override the lists today. If the classifier cannot be imported the engine prints one line and behaves exactly as before.

## Desktop apps

Besides Chrome tabs, the engine notices which desktop application is in front and which distracting apps are running (`psutil` plus a small per-OS foreground lookup, scanned every 2 s on a background thread). It does not read window titles, file paths or anything inside an app: only process names.

- **Alerts:** during *work* only, a topmost popup appears when an app on your distracting-apps list starts or comes to the front (at most once per app every 2 minutes). Apps that were already open in the background are not announced until you bring them forward. Nothing is queued or shown during pauses and breaks; if a distracting app is still in front when work resumes, you are told then. Alerts count as *app alerts*, not check-ins, and do not depend on the camera.
- **Live view:** the top-bar activity pill names what is in front: Chrome with the active tab title (domain and category on hover), or the desktop app (*Discord · distracting app*) when Chrome is not in front. With the camera off, the attention card shows the same sites-and-apps split.
- **Summary:** one *Where your time went* card covers Chrome and apps together: work sites, other sites, distracting sites, distracting apps and other apps, with your top apps by name underneath. While Chrome reports it is in front, its report wins; otherwise the foreground app fills in (also when the extension is disconnected). Time in a distracting app counts as off task in the focus score, like a distracting site. Other apps are neutral. The saved report keeps the 8 most-used app names and their seconds.
- **Your list:** defaults are `roblox`, `tlauncher`, `minecraft`, `steam`, `discord`. Override it in `engine/data/config.json`: `{"apps": {"distracting": ["discord", "slack", "steam"]}}`. A name matches a process whose name starts with it (`steam` covers `steamwebhelper`).
- **Platforms:** the running-process check works everywhere `psutil` does. The foreground app is read with the Windows API, `osascript` on macOS (allow your terminal to control *System Events* if prompted), or `xprop` on Linux X11/XWayland. Native Wayland windows cannot be seen, and without `xprop` Linux only reports launches. If `psutil` is not installed, this feature is simply off.

## Observation signals

Camera, website and desktop-app observations are kept separate in the summary. The phone detector only confirms a phone after repeated, reasonably confident detections; a less certain candidate is drawn as a faint, thin "PHONE?" box in the preview and is not counted as being on the phone or as a pickup. A visible phone is not proof of phone use; an off-camera phone is unobserved. The camera-derived legacy state does not control the session timer. Expression heuristics and the old fake-time keyboard demos are not part of the new session interface. **⋯ → Preview a check-in** previews UI without incrementing tracked nudges.

### Quiet blink and yawn estimates

During camera-enabled work, a small muted readout in the bottom-right corner shows estimated blink and yawn counts plus a rough sleepiness cue. It uses the existing camera feed, including when the preview is hidden; it never starts a second camera or changes focus scores, timers, check-ins or breaks. There are no sleepiness popups, sounds or automatic actions. The readout is hidden during pauses, breaks, completed blocks, camera-free sessions and simulated-camera testing.

The cue starts at **learning…**, then **no clear signs** after 30 seconds of usable observations in the last two minutes. **Possible signs** means three estimated yawns in ten minutes, two prolonged eye closures in two minutes, or a current eye closure lasting at least two seconds. Blink detection measures eyelid opening relative to each eye's width and learns an open-eye reference separately for each eye. Start with your eyes naturally open and mouth relaxed. Brief bilateral closures (0.03–0.5 seconds) count on reopening; winks and rapid threshold chatter are excluded. Yawn detection measures inner-mouth opening relative to mouth width and counts a sustained wide opening after about one second, while the mouth is still open. It counts once until the mouth closes, tolerating a brief single-frame dropout. Talking can still produce false detections.

These measurements do not depend on the iris/gaze estimate, so uncertain gaze does not discard an otherwise visible yawn or blink. Missing/unreliable facial regions discard partial gestures only for that region; a stale or incomplete observation makes the sleepiness cue **unavailable**. Counts survive pauses and breaks but reset for each new session. **⋯ → Tracking details** shows live eyelid/mouth ratios and the camera analysis rate for troubleshooting. Very fast blinks between camera frames may still be missed.

These are heuristic webcam estimates, not a medical assessment or proof of sleepiness or alertness. Talking, glasses and lighting can cause missed or false detections; **no clear signs** does not mean you are alert. Counts and recent signal history stay only in memory, are not included in saved reports, and are never sent to Jev or the extension. Frames remain unsaved and unuploaded.

## Accuracy tips
During a session with the camera enabled, choose **Calibrate screen…** in the ⋯ menu. Follow the five dots with your eyes, keeping your usual sitting position; the ring fills while tracking is stable. Repeat this after moving your camera, chair, or screen. **Esc** cancels and keeps the last completed calibration. If eye movement is unclear, calibration shows a warning and keeps the previous profile (or a center-only fallback on the first run). Without guided calibration, look at screen center and hold still for about three seconds for the automatic center calibration. Calibration is kept for the current run.

Use even light on your face and avoid a bright window behind you. Brief blinks are ignored for attention; prolonged eye closure still registers. Head tilt and sitting off-center no longer count as looking away by themselves. Leaning closer than you were when calibrating widens the screen limits (the screen spans a wider angle), a head turned one way with the eyes turned back toward the screen still counts as on screen, and with a strongly turned head the nearer, less foreshortened eye is trusted. Guided calibration extends the edge dots out to the real screen edges, so the corners count as on screen. Tiny, clipped, or unreliable eye landmarks show a tracking hint and are excluded from calibration. This is a webcam estimate of attention, not a precise screen-coordinate eye tracker. Calibration defaults are in `engine/tracking.py`; other thresholds such as `DOOM_SCROLL_PX` and `PHONE_SCORE` remain at the top of `engine.py`.

## Privacy
Camera frames stay in memory and are never saved or uploaded. Desktop-app monitoring reads process names only (no window titles or paths), stays on this computer and is never sent to Jev; reports save the names of your most-used apps in `engine/data/sessions.json`. The extension sends the domain, the URL path (no query string or fragment), the page title and scroll counts to `127.0.0.1` only; incognito tabs send the domain only. The local server refuses requests from other websites. Text leaves your laptop in one case only: **during a study session with a Jev key configured**, your goal, the domain, URL path and page title of the active tab are sent to the Jev API to classify it (see *Goal-aware classification*). Without a key, nothing about your pages leaves the machine.
