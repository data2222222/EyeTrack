# EyeTrack hackathon demo

For the pitch script, timed live-demo runbook and slide outline, see the [presentation plan](PITCH_PLAN.md).

## Before presenting

1. Run `python setup.py` and load `extension/` as an unpacked Chrome extension.
2. Launch `./start.sh` on macOS/Linux or `start.bat` on Windows. Keep only one engine running; the extension uses loopback port 8000.
3. Reload the extension and your demo tabs after pulling an update. Look for **Chrome connected** in the desktop header.
4. Open **⋯ → Settings…**. Pick a comfortable sound volume and preview it. Use a **1-minute focus block** if you want to demonstrate completion live; save settings before starting.
5. For real camera tracking, check lighting and camera permissions. Camera access begins only when you start a camera-enabled session. Calibration is available through **⋯ → Calibrate screen…** during work.

## A three-minute walkthrough

- **Start with intent.** Enter a concrete goal such as “Revise capacitors for my physics exam.” Choose computer-only or computer + paper, then start the block.
- **Show the live view.** Point out the remaining time, the recent focus estimate, and the separate camera-attention and computer-activity readouts. Hide the preview to show that tracking continues without displaying your face.
- **Demonstrate control.** Pause, wait, and resume: the remaining work stays intact. Take a break and show that returning to work requires an explicit action.
- **Personalize without disruption.** Open settings during the block. Sound changes apply after saving; duration, working-mode and camera defaults are for the next session, not a running timer.
- **Finish and reflect.** Let a short block complete or end it explicitly. Show active/break/paused time, the attention/activity breakdowns, and optional goal completion. These are estimates and self-reflection tools, not proof of productivity.

If demonstrating goal-aware Jev classification, configure a key using setup first. Choose two pages with clear, different titles: one relevant to the goal, one unrelated. Verdicts are per page and goal, not a single judgement for an entire domain. Without a key or network, explain that list/local fallback remains available rather than promising the same semantic verdict.

## Hardware-free fallback

Run `./start.sh --no-camera` or `start.bat --no-camera` for **simulated input**, clearly marked as a test view. This is not live eye tracking. Alternatively, disable **Use the camera** on the setup screen to demonstrate a genuine camera-free session using browser/app observations. No real camera or Jev key is needed for either fallback.

If Chrome is not connected, open **⋯ → Connect Chrome…** for help; sessions still work, but missing browser observations must not be presented as tracked website time. If audio is unavailable, visual state changes remain usable. Sound playback also depends on the system output device and mute settings.

## Privacy explanation

Camera frames remain in memory: never saved or uploaded. Foreground app names stay local. The Chrome bridge binds to `127.0.0.1`, rejects foreign origins, removes URL queries/fragments, limits paths, and suppresses incognito titles/paths. Optional Jev classification sends only the documented goal and page context; it never receives camera frames. Preferences, reports and classifier data live in ignored `engine/data/` files—do not add them to the repository or your presentation assets.

## Quick verification

```sh
QT_QPA_PLATFORM=offscreen engine/.venv/bin/python -m pytest engine/tests -q
python -m py_compile engine/engine.py engine/study.py engine/desktop.py engine/settings_dialog.py engine/preferences.py engine/sounds.py
node --check extension/background.js
node --check extension/content.js
```

On Windows, use `engine\.venv\Scripts\python.exe` and set `QT_QPA_PLATFORM=offscreen` using your shell's environment syntax. Automated checks use fake clocks and simulated cameras; real camera accuracy, OS permissions and physical speaker output still need a manual check on the presentation machine.
