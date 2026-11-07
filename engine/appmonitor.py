"""Desktop-app awareness for focus sessions: which app is in front and which distracting
apps are running. Kept local and lightweight: only process names are read (never window
titles, executable paths or command lines), nothing here touches the network, and the
module imports no GUI, camera or ML libraries. psutil is optional and imported lazily; when
it is missing the monitor reports itself unavailable and sessions work exactly as before."""
import json
import os
import shutil
import subprocess
import sys
import threading
import time

DEFAULT_DISTRACTING = ("roblox", "tlauncher", "minecraft", "steam", "discord")
SCAN_INTERVAL = 2.0          # seconds between scans on the worker thread
FRESH_SECONDS = 6.0          # a scan stays valid this long (a few missed scans are tolerated)
ALERT_COOLDOWN = 120.0       # seconds before the same app can alert again
SUBPROCESS_TIMEOUT = 1.5
# Never terminated even if a blocked-app entry happens to prefix them (e.g. "sys" or "exp").
PROTECTED = frozenset({
    "system", "systemd", "init", "launchd", "kernel_task", "kthreadd", "dbus-daemon", "dbus-broker", "sshd",
    "xorg", "xwayland", "wayland", "gnome-shell", "plasmashell", "kwin", "mutter", "login", "loginwindow",
    "windowserver", "finder", "dock", "explorer", "dwm", "winlogon", "csrss", "wininit", "services", "lsass",
    "svchost", "smss", "taskmgr", "cmd", "powershell", "pwsh", "conhost", "bash", "zsh", "fish", "sh",
    "python", "python3", "pythonw", "eyetrack",
})


def normalize(name):
    """'Discord.exe' -> 'discord', 'Steam.app' -> 'steam'."""
    name = (name or "").strip().casefold()
    for suffix in (".exe", ".app"):
        if name.endswith(suffix):
            name = name[:-len(suffix)]
    return name


def matches(name, watchlist):
    """Whole-name prefix match, so 'steam' covers 'steamwebhelper' but not 'upsteam-tool'."""
    name = normalize(name)
    return bool(name) and any(name.startswith(token) for token in watchlist)


def blocked_match(name, blocked):
    """Whole-name prefix match against the blocked list, minus protected system processes."""
    name = normalize(name)
    return bool(name) and name not in PROTECTED and any(name.startswith(token) for token in blocked)


def terminate(pid, name):
    """Politely ask one process to exit; False if it is gone, not ours, or no longer that app.

    The name is re-read first so a recycled pid is never signalled by mistake."""
    try:
        import psutil
        proc = psutil.Process(pid)
        if normalize(proc.name()) != name:
            return False
        proc.terminate()
        return True
    except Exception:
        return False


def load_watchlist(config_path):
    """Distracting-app tokens from config.json {"apps": {"distracting": [...]}}, else the defaults."""
    try:
        with open(config_path, encoding="utf-8") as f:
            tokens = json.load(f).get("apps", {}).get("distracting")
    except (OSError, ValueError, AttributeError):
        tokens = None
    if isinstance(tokens, list):
        cleaned = tuple(sorted({normalize(t) for t in tokens if isinstance(t, str) and normalize(t)}))
        return cleaned
    return DEFAULT_DISTRACTING


class Snapshot:
    """One scan: every running process name by pid and the pid in front (None when unknown)."""

    def __init__(self, processes=None, foreground_pid=None):
        self.processes = dict(processes or {})
        self.foreground_pid = foreground_pid

    @property
    def foreground(self):
        return self.processes.get(self.foreground_pid)


# ---------------------------------------------------------------- platform scanning
def _run(command):
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout if done.returncode == 0 else ""


def _foreground_pid_windows():
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value or None


def _foreground_pid_macos():
    out = _run(["osascript", "-e", 'tell application "System Events" to get unix id of '
                                    "first application process whose frontmost is true"])
    return int(out) if out.strip().isdigit() else None


def _foreground_pid_linux():
    """X11 (including XWayland) only; native Wayland windows are not visible, so we report None."""
    if not os.environ.get("DISPLAY") or not shutil.which("xprop"):
        return None
    out = _run(["xprop", "-root", "_NET_ACTIVE_WINDOW"])
    window = out.rsplit("#", 1)[-1].strip() if "#" in out else ""
    if not window.startswith("0x") or int(window, 16) == 0:
        return None
    out = _run(["xprop", "-id", window, "_NET_WM_PID"])
    value = out.rsplit("=", 1)[-1].strip() if "=" in out else ""
    return int(value) if value.isdigit() else None


def foreground_pid():
    try:
        if sys.platform == "win32":
            return _foreground_pid_windows()
        if sys.platform == "darwin":
            return _foreground_pid_macos()
        return _foreground_pid_linux()
    except Exception:
        return None


def scan():
    """Snapshot of running process names, or None when psutil is not installed."""
    try:
        import psutil
    except ImportError:
        return None
    processes = {}
    for proc in psutil.process_iter(["name"]):
        try:
            name = normalize(proc.info.get("name"))
        except (psutil.Error, OSError):
            continue
        if name:
            processes[proc.pid] = name
    return Snapshot(processes, foreground_pid())


def _ancestor_pids():
    """Parents of this process (launcher shell, terminal): never closed by a blocked-app entry."""
    try:
        import psutil
        return frozenset(p.pid for p in psutil.Process().parents())
    except Exception:
        return frozenset()


# ---------------------------------------------------------------- monitor
class AppMonitor:
    """Scans on a worker thread; observe() is cheap and safe to call from the UI timer.

    Alerts fire only while the caller says the user is working, on a state change (a
    distracting app starts, or one comes to the front), at most once per cooldown per app.
    Apps already open in the background when work begins are not announced until they
    come to the front, and nothing is queued across pauses or breaks."""

    def __init__(self, scanner=scan, watchlist=DEFAULT_DISTRACTING, interval=SCAN_INTERVAL,
                 cooldown=ALERT_COOLDOWN, clock=None, own_pid=None, blocked=(), killer=terminate,
                 protected_pids=()):
        self.scanner = scanner
        self.killer = killer
        self.set_blocked(blocked)
        self.protected_pids = frozenset(protected_pids)
        self.closed = []              # recently closed blocked-app names, drained by take_closed()
        self.watchlist = tuple(normalize(t) for t in watchlist if normalize(t))
        self.interval = interval
        self.cooldown = cooldown
        self.clock = clock or (lambda: time.monotonic())   # looked up late so tests can fake time
        self.own_pid = os.getpid() if own_pid is None else own_pid
        if own_pid is None:
            self.protected_pids = self.protected_pids | _ancestor_pids()
        self.available = True
        self._lock = threading.Lock()
        self._snapshot = None
        self._observed_at = None
        self._running = None          # distracting app names seen at the last evaluation
        self._front = None            # distracting app that was in front at the last evaluation
        self._last_alert = {}
        self._stop = threading.Event()
        self._worker = None

    def set_blocked(self, names):
        """Replace the fully blocked app list; takes effect on the next scan."""
        from blocklist import normalize_app
        self.blocked = tuple(sorted({n for n in map(normalize_app, names) if n}))

    def take_closed(self):
        """Names of blocked apps closed since the last call (for a one-line notice in the UI)."""
        with self._lock:
            closed, self.closed = self.closed, []
        return closed

    # worker side
    def refresh(self):
        try:
            snapshot = self.scanner()
        except Exception:
            snapshot = None
        with self._lock:
            if snapshot is None:
                self.available = False
                return
            self.available = True
            self._snapshot, self._observed_at = snapshot, self.clock()
        self.enforce(snapshot)

    def enforce(self, snapshot):
        """Close every running process on the blocked list. Runs on the worker thread, whether or
        not a session is active, so a blocked app is gone within one scan of opening."""
        blocked = self.blocked
        if not blocked:
            return
        keep = {self.own_pid, *self.protected_pids}
        closed = set()
        for pid, name in snapshot.processes.items():
            if pid in keep or not blocked_match(name, blocked):
                continue
            if self.killer(pid, name):
                closed.add(name)
        if closed:
            with self._lock:
                self.closed.extend(sorted(closed - set(self.closed)))

    def start(self):
        if self._worker is not None:
            return
        self._stop.clear()
        self._worker = threading.Thread(target=self._loop, name="app-monitor", daemon=True)
        self._worker.start()

    def stop(self):
        self._stop.set()
        if self._worker is not None:
            self._worker.join(timeout=SUBPROCESS_TIMEOUT * 3 + self.interval)
            self._worker = None

    def _loop(self):
        while not self._stop.is_set():
            self.refresh()
            self._stop.wait(self.interval)

    # UI side
    def observe(self, working):
        """Return (info, alerts). info feeds study.tick; alerts are user-facing messages."""
        with self._lock:
            snapshot, observed_at = self._snapshot, self._observed_at
        if snapshot is None or observed_at is None:
            return {}, []
        now = self.clock()
        running = {n for pid, n in snapshot.processes.items()
                   if pid != self.own_pid and self._distracting(n)}
        front_name = None if snapshot.foreground_pid == self.own_pid else snapshot.foreground
        front = front_name if front_name and self._distracting(front_name) else None
        fresh = now - observed_at <= FRESH_SECONDS
        info = {"app": front_name if fresh else None, "app_distracting": bool(front) and fresh,
                "app_until": observed_at + FRESH_SECONDS}
        alerts = []
        if working and fresh:
            candidates = []
            if self._running is not None:
                candidates += [(n, "started") for n in sorted(running - self._running)]
            if front and front != self._front:
                candidates.append((front, "front"))
            for name, how in candidates:
                if any(name == shown for shown, _ in alerts):
                    continue
                if now - self._last_alert.get(name, -self.cooldown) < self.cooldown:
                    continue
                self._last_alert[name] = now
                alerts.append((name, how))
        if working and fresh:
            self._running, self._front = running, front
        else:
            # Learn silently during breaks and pauses; a distracting app still in front
            # when work resumes is announced because _front is reset here.
            self._running = running if fresh else self._running
            self._front = None
        return info, [self._message(name, how) for name, how in alerts]

    def _distracting(self, name):
        return matches(name, self.watchlist)

    @staticmethod
    def _message(name, how):
        label = name.title()
        lead = f"{label} just started." if how == "started" else f"{label} is in front."
        return f"{lead}\nIt's on your distracting-apps list. Close it and get back to your task?"
