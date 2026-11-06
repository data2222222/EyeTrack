# Agent Guide

## Project overview

EyeTrack is a local desktop focus-session app with a Chrome extension. The Python
engine combines browser activity with optional webcam observations; PySide6 is the
desktop interface. Camera signals are estimates, not proof of attention or
productivity. Read `README.md` for setup, session behavior, and privacy details.

## Repository map

- `setup.py`: cross-platform bootstrap, virtual environment, dependencies, model
  downloads, optional Jev configuration, and extension onboarding.
- `start.sh` / `start.bat`: launch the engine using `engine/.venv`, forwarding CLI
  arguments.
- `engine/engine.py`: application entry point, camera lifecycle, legacy observation
  logic, and the extension's loopback HTTP bridge on port 8000.
- `engine/desktop.py`: PySide6 setup, active-session, diagnostics, and summary UI.
- `engine/study.py`: timestamp-based session clock, pauses, breaks, persistence,
  and reports.
- `engine/tracking.py`: camera geometry and calibration logic without GUI, camera,
  or ML dependencies.
- `engine/camera_calibration.py`: guided calibration dialog.
- `engine/classifier/`: optional Jev classification, local fallback, privacy
  filtering, cache keys, and model utilities.
- `extension/`: Manifest V3 extension; `background.js` collects browser activity,
  while `content.js` handles page-side scrolling and focus-mode UI.
- `engine/tests/`: pytest coverage, including simulated camera and offscreen UI
  tests; `conftest.py` adds `engine/` to the import path.
- `.github/workflows/ci.yml`: Windows, macOS, and Linux checks on Python 3.12.

## Setup and commands

Use Python 3.10–3.14. Run commands from the repository root unless noted otherwise.
There is no frontend package manager or JavaScript build step.

```sh
# Development setup without model downloads or interactive onboarding
python setup.py --no-input --skip-models --skip-extension
engine/.venv/bin/python -m pip install pytest

# Full test suite; prefer the relevant test file while iterating
engine/.venv/bin/python -m pytest engine/tests -q
engine/.venv/bin/python -m pytest engine/tests/test_study.py -q

# Syntax checks used by CI
python -m py_compile engine/engine.py engine/study.py
node --check extension/background.js
node --check extension/content.js

# Manual desktop smoke test with simulated camera input
./start.sh --no-camera
```

On Windows, use `engine\.venv\Scripts\python.exe` instead of
`engine/.venv/bin/python`, and `start.bat` instead of `./start.sh`.
For normal onboarding, use `python setup.py`; this can download models and open
Chrome. Load `extension/` as an unpacked extension. After extension changes, reload
its card in `chrome://extensions` and reload affected tabs.

## Implementation guidelines

- Keep changes focused and follow the surrounding Python or plain JavaScript
  style. No standalone formatter or linter configuration is currently present.
- Keep session timing in `study.py`, geometry in `tracking.py`, and Qt presentation
  in the UI modules rather than adding more responsibilities to `engine.py`.
- Preserve lightweight imports: importing the engine must not require Tkinter,
  OpenCV, or MediaPipe. Keep heavyweight runtime imports deferred. Keep pure
  timing and tracking logic independent of GUI and hardware dependencies.
- Support Windows, macOS, and Linux; use portable paths and preserve the
  platform-specific camera backends and launchers.
- Keep the UI responsive: classification and camera work must not block the Qt
  event loop. Release capture/detector resources and stop/join workers on shutdown.
- Treat the visible desktop flow and regression tests as authoritative when old
  engine comments or legacy demo code describe a different interface.
- Update `README.md` when changing setup, user-visible behavior, or privacy.

## Behavioral and privacy invariants

- Only explicit pauses and breaks suspend active session time; camera absence and
  AFK must not pause the session. Use monotonic timestamps, not UI callback counts.
- Resuming preserves remaining work. Breaks never auto-resume; completed work
  blocks stop rather than automatically starting another block.
- Keep the camera off until camera-enabled work starts. Stop it on pause, break,
  completion, session end, and app close. Keep camera and website observations
  separate in summaries; diagnostic previews must not increment tracked nudges.
- Keep frames in memory: never save or upload them. Bind the HTTP bridge to
  loopback and retain foreign-origin rejection.
- Strip URL query strings and fragments and limit paths to three segments.
  Incognito activity sends only the domain. Preserve classifier privacy filters.
- Jev is optional. Preserve local/list fallback when no key, dependency, or network
  is available. Do not broaden what browser/goal data is sent externally.
- Never commit secrets, session data, classification caches, downloaded models,
  or virtual environments. Runtime data and models belong in ignored locations.

## Validation

Add regression tests alongside related tests for behavioral changes. Use fake
clocks, temporary data directories, mocked classifiers, and simulated cameras;
automated tests should not require real hardware, API keys, or external services.
Qt tests use `QT_QPA_PLATFORM=offscreen`. Run targeted tests first, then the full
suite and relevant syntax checks. Report any checks you could not run. Changes to
camera behavior or the desktop journey may also need a manual hardware/UI check.
