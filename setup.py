#!/usr/bin/env python3
"""One-command setup for Study Focus: python setup.py   (python3 setup.py on macOS/Linux)

Stdlib only, so it runs on any system Python 3.10 to 3.12. Safe to re-run: finished steps are skipped.
Chrome does not allow installing an unpacked extension silently, so the one manual part is Chrome's
own Developer mode toggle + "Load unpacked"; this script opens the right page and puts the folder
path on your clipboard.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENGINE_DIR = ROOT / "engine"
EXTENSION_DIR = ROOT / "extension"
VENV_DIR = ENGINE_DIR / ".venv"
CONFIG_PATH = ENGINE_DIR / "data" / "config.json"
PORT = 8000
EXTENSION_WAIT_SECONDS = 5 * 60
SUPPORTED = ((3, 10), (3, 12))  # mediapipe wheels

OK, WARN, FAIL = "[ok]", "[!]", "[x]"


def say(mark: str, text: str) -> None:
    print(f"{mark} {text}", flush=True)


# ---------------- pure helpers (unit-tested) ----------------

def venv_python(venv: Path = VENV_DIR, platform: str = sys.platform) -> Path:
    return venv / ("Scripts/python.exe" if platform == "win32" else "bin/python")


def python_ok(version: tuple[int, int]) -> bool:
    return SUPPORTED[0] <= version <= SUPPORTED[1]


def python_help(platform: str) -> str:
    if platform == "win32":
        return "Install Python 3.12 from https://www.python.org/downloads/ (or `winget install Python.Python.3.12`), then run `py -3.12 setup.py`."
    if platform == "darwin":
        return "Install Python 3.12 from https://www.python.org/downloads/ (or `brew install python@3.12`), then run `python3.12 setup.py`."
    return "Install Python 3.12 (Debian/Ubuntu: `sudo apt install python3.12 python3.12-venv`, Fedora: `sudo dnf install python3.12`), then run `python3.12 setup.py`."


def tk_help(platform: str) -> str:
    if platform == "darwin":
        return "Use the python.org installer (includes Tk) or run `brew install python-tk`."
    if platform == "win32":
        return "Reinstall Python from python.org with the 'tcl/tk and IDLE' option enabled."
    return "Run `sudo apt install python3-tk` (Fedora: `sudo dnf install python3-tkinter`)."


def browser_candidates(
    platform: str,
    env: Mapping[str, str],
    which: Callable[[str], str | None],
    exists: Callable[[str], bool],
) -> list[tuple[str, str]]:
    """Installed browsers in preference order as (name, executable or macOS app name).
    Chrome first, Edge as a fallback. `which`/`exists` are injected so this is testable."""
    found: list[tuple[str, str]] = []
    if platform == "win32":
        roots = [env.get(k) for k in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        for name, rel in (("Google Chrome", r"Google\Chrome\Application\chrome.exe"),
                          ("Microsoft Edge", r"Microsoft\Edge\Application\msedge.exe")):
            for root in filter(None, roots):
                path = os.path.join(root, rel)
                if exists(path):
                    found.append((name, path))
                    break
    elif platform == "darwin":
        for name in ("Google Chrome", "Microsoft Edge"):
            if exists(f"/Applications/{name}.app"):
                found.append((name, name))
    else:
        for exe in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge"):
            path = which(exe)
            if path:
                found.append((exe, path))
    return found


def extensions_url(browser_name: str) -> str:
    return "edge://extensions" if "dge" in browser_name else "chrome://extensions"


def validate_manifest(ext_dir: Path) -> list[str]:
    """Problems with manifest.json (empty list = fine): bad JSON or a referenced file that is missing."""
    try:
        manifest = json.loads((ext_dir / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return [f"manifest.json unreadable: {e}"]
    if not isinstance(manifest, dict):
        return ["manifest.json is not an object"]
    refs: list[str] = []
    background = manifest.get("background", {})
    if background.get("service_worker"):
        refs.append(background["service_worker"])
    for script in manifest.get("content_scripts", []):
        refs += script.get("js", []) + script.get("css", [])
    refs += list(manifest.get("icons", {}).values())
    action = manifest.get("action", {})
    if isinstance(action.get("default_icon"), str):
        refs.append(action["default_icon"])
    if action.get("default_popup"):
        refs.append(action["default_popup"])
    return [f"missing file: {ref}" for ref in refs if not (ext_dir / ref).is_file()]


def read_config(path: Path = CONFIG_PATH) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_api_key(key: str, path: Path = CONFIG_PATH) -> None:
    """Set typesafe_api_key in config.json, keeping every other key."""
    config = read_config(path)
    config["typesafe_api_key"] = key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")


def has_api_key(env: Mapping[str, str], path: Path = CONFIG_PATH) -> bool:
    return bool(env.get("TYPESAFE_API_KEY") or read_config(path).get("typesafe_api_key"))


# ---------------- steps ----------------

def run_captured(cmd: list[str], cwd: Path | None = None) -> bool:
    """Run quietly; on failure print the tail of the output."""
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        print("\n".join((result.stdout + result.stderr).strip().splitlines()[-25:]), flush=True)
    return result.returncode == 0


def step_python() -> bool:
    version = sys.version_info[:2]
    label = f"{version[0]}.{version[1]}"
    if not python_ok(version):
        say(FAIL, f"Python {label} is not supported (need 3.10 to 3.12; mediapipe has no wheels for other versions).")
        print("    " + python_help(sys.platform))
        return False
    say(OK, f"Python {label}")
    try:
        import tkinter  # noqa: F401
    except ImportError:
        say(FAIL, "tkinter is missing (the Study Focus window needs it).")
        print("    " + tk_help(sys.platform))
        return False
    say(OK, "tkinter available")
    return True


def step_venv() -> bool:
    py = venv_python()
    if not py.exists():
        say("...", "Creating engine/.venv")
        if not run_captured([sys.executable, "-m", "venv", str(VENV_DIR)]):
            say(FAIL, "Could not create the virtual environment (Linux: `sudo apt install python3-venv`).")
            return False
    # The stamp holds the requirements text that was installed, so re-runs skip pip.
    requirements = ENGINE_DIR / "requirements.txt"
    stamp = VENV_DIR / ".requirements.stamp"
    if stamp.exists() and stamp.read_text() == requirements.read_text():
        say(OK, "Dependencies already installed (skipped)")
        return True
    say("...", "Installing dependencies (a few minutes the first time)")
    if not run_captured([str(py), "-m", "pip", "install", "--upgrade", "pip"]):
        say(WARN, "pip upgrade failed, continuing")
    if not run_captured([str(py), "-m", "pip", "install", "-r", str(requirements)]):
        say(FAIL, "pip install failed (output above).")
        return False
    stamp.write_text(requirements.read_text())
    say(OK, "Dependencies installed")
    return True


# Runs inside the venv so it reuses engine.py's URLs and download helper (cwd = engine/).
_FETCH_FACE_MODELS = (
    "import engine\n"
    "for url, path in ((engine.MODEL_URL, engine.MODEL_PATH), (engine.PHONE_MODEL_URL, engine.PHONE_MODEL_PATH)):\n"
    "    engine.download(url, path)\n"
)


def step_models() -> None:
    py = str(venv_python())
    face = [ENGINE_DIR / "face_landmarker.task", ENGINE_DIR / "efficientdet_lite0.tflite"]
    if all(p.exists() for p in face):
        say(OK, "Camera models present (skipped)")
    elif run_captured([py, "-c", _FETCH_FACE_MODELS], cwd=ENGINE_DIR):
        say(OK, "Camera models downloaded")
    else:
        say(WARN, "Camera model download failed; the engine retries on first run.")

    minilm = ENGINE_DIR / "models"
    if (minilm / "model.onnx").exists() and (minilm / "tokenizer.json").exists():
        say(OK, "MiniLM model present (skipped)")
    elif run_captured([py, "-m", "classifier.fetch_model"], cwd=ENGINE_DIR):
        say(OK, "MiniLM model downloaded")
    else:
        say(WARN, "MiniLM download failed (optional offline classifier; safe to ignore).")


def step_api_key(interactive: bool) -> None:
    if has_api_key(os.environ):
        say(OK, "Jev API key already configured (skipped)")
        return
    if not interactive:
        say(OK, "Jev API key not set (optional; skipped, no prompts)")
        return
    key = getpass.getpass("    Jev (TypeSafe) API key for goal-aware classification, Enter to skip: ").strip()
    if key:
        save_api_key(key)
        say(OK, "Jev API key saved to engine/data/config.json")
    else:
        say(OK, "Jev API key skipped (the site lists are used instead)")


def step_extension() -> bool:
    problems = validate_manifest(EXTENSION_DIR)
    if problems:
        say(FAIL, "Extension check failed: " + "; ".join(problems))
        return False
    say(OK, f"Extension ready (no build needed): {EXTENSION_DIR}")
    return True


def copy_to_clipboard(text: str) -> bool:
    try:
        import tkinter
        root = tkinter.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()  # hands the text to the OS clipboard
        time.sleep(0.3)
        root.update()
        root.destroy()
        return True
    except Exception:
        return False


def open_in_file_manager(path: Path) -> bool:
    try:
        if sys.platform == "win32":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False


def open_extensions_page(name: str, target: str) -> bool:
    url = extensions_url(name)
    try:
        if sys.platform == "darwin":
            return subprocess.run(["open", "-a", target, url]).returncode == 0
        subprocess.Popen([target, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False


def step_add_to_chrome() -> None:
    path = str(EXTENSION_DIR)
    if copy_to_clipboard(path):
        say(OK, "Extension folder path copied to the clipboard")
    else:
        say(WARN, f"Clipboard unavailable. Extension folder: {path}")
    browsers = browser_candidates(sys.platform, os.environ, shutil.which, os.path.exists)
    if browsers:
        name, target = browsers[0]
        if open_extensions_page(name, target):
            say(OK, f"Opened {extensions_url(name)} in {name}")
        else:
            say(WARN, f"Could not launch {name}. Open {extensions_url(name)} yourself.")
    else:
        say(WARN, "No Chrome or Edge found. Open chrome://extensions in your browser.")
    if open_in_file_manager(EXTENSION_DIR):
        say(OK, "Opened the extension folder")
    print(f"""
    In the browser window that just opened:
      1. Turn on "Developer mode" (top right).
      2. Click "Load unpacked".
      3. Paste the path (Ctrl+L in the dialog, Cmd+Shift+G on macOS) or select the folder that just opened.
         {path}
""", flush=True)


class _ActivityHandler(BaseHTTPRequestHandler):
    """Stands in for the engine: answers the extension's POST /activity with the fields background.js reads."""
    connected: threading.Event

    def _json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.end_headers()

    def do_POST(self) -> None:
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        from_extension = (self.headers.get("Origin") or "").startswith("chrome-extension://")
        if self.path.split("?")[0] == "/activity" and from_extension:
            self._json(200, {"state": "Setup", "index": 0, "block": False, "subject": "", "goal": ""})
            self.connected.set()
        else:
            self._json(403, {"error": "forbidden"})

    def log_message(self, *args) -> None:
        pass


def wait_for_extension(port: int = PORT, timeout: float = EXTENSION_WAIT_SECONDS) -> str:
    """Returns "connected", "timeout", "busy" (port in use, e.g. the engine is running) or "skipped" (Ctrl+C)."""
    handler = type("Handler", (_ActivityHandler,), {"connected": threading.Event()})
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    except OSError:
        return "busy"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        print("    Waiting for the extension... (Ctrl+C to skip)", flush=True)
        return "connected" if handler.connected.wait(timeout) else "timeout"
    except KeyboardInterrupt:
        return "skipped"
    finally:
        server.shutdown()
        server.server_close()


def step_confirm() -> None:
    result = wait_for_extension()
    if result == "connected":
        say(OK, "Extension connected")
    elif result == "busy":
        say(OK, f"Port {PORT} is in use (the engine is probably running); skipped the connection check")
    elif result == "skipped":
        say(OK, "Connection check skipped")
    else:
        say(WARN, "No message from the extension after 5 minutes. Check that Developer mode is on, "
                  "the extension is enabled on the extensions page, and no other program uses port 8000.")


def start_engine() -> int:
    return subprocess.call([str(venv_python()), str(ENGINE_DIR / "engine.py")])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Set up Study Focus: environment, models, extension.")
    parser.add_argument("--no-input", action="store_true", help="never prompt")
    parser.add_argument("--skip-models", action="store_true", help="do not download models")
    parser.add_argument("--skip-extension", action="store_true", help="do not validate or open the extension in Chrome")
    parser.add_argument("--start", action="store_true", help="start Study Focus at the end without asking")
    args = parser.parse_args(argv)
    interactive = not args.no_input and sys.stdin.isatty()

    if not step_python() or not step_venv():
        return 1
    if not args.skip_models:
        step_models()
    step_api_key(interactive)
    if not args.skip_extension:
        if not step_extension():
            return 1
        step_add_to_chrome()
        step_confirm()

    if args.start:
        return start_engine()
    if interactive and input("Start Study Focus now? [Y/n] ").strip().lower() in ("", "y", "yes"):
        return start_engine()
    say(OK, "Done. Next time run start.bat (Windows) or ./start.sh (macOS/Linux).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
