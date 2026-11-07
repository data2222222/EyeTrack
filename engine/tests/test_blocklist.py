"""Fully blocked sites and apps: normalizing, preferences, app closing, the extension reply and the Settings editor."""
import http.client
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

import appmonitor
import blocklist
import engine
import preferences
from appmonitor import AppMonitor, Snapshot
from test_settings_ui import app, open_from_menu, started_tones, window  # noqa: F401  (fixtures)


# ---------------------------------------------------------------- normalizing
@pytest.mark.parametrize("raw, site", [
    ("Reddit.com", "reddit.com"),
    ("https://www.reddit.com/r/all?x=1#top", "reddit.com"),
    ("  www.YouTube.com/watch ", "youtube.com"),
    ("http://user:pw@news.ycombinator.com:8080/item", "news.ycombinator.com"),
    ("bücher.de", "xn--bcher-kva.de"),
])
def test_sites_normalize_to_bare_hostnames(raw, site):
    assert blocklist.normalize_site(raw) == site


@pytest.mark.parametrize("raw", ["", "   ", "localhost", "127.0.0.1", "[::1]", "a b.com", "-bad-.com",
                                 "x" * 64 + ".com", "reddit..com", 5, None, ["reddit.com"]])
def test_unusable_sites_are_rejected_not_repaired(raw):
    assert blocklist.normalize_site(raw) is None


@pytest.mark.parametrize("raw, app_name", [("Discord.exe", "discord"), ("Steam.app", "steam"), (" Roblox ", "roblox"),
                                           ("Visual Studio Code", "visual studio code")])
def test_apps_normalize_to_process_names(raw, app_name):
    assert blocklist.normalize_app(raw) == app_name


@pytest.mark.parametrize("raw", ["", "ab", "a.exe", "*", "../../bin/sh", "dis/cord", "x" * 65, 5, None])
def test_short_or_odd_app_names_are_rejected(raw):
    # two letters would match half the system; path-like text is never a process name
    assert blocklist.normalize_app(raw) is None


def test_lists_are_deduplicated_sorted_and_capped():
    assert blocklist.clean_sites(["B.com", "a.com", "https://www.b.com/x", "nope", 3]) == ["a.com", "b.com"]
    assert blocklist.clean_sites("reddit.com") == [] and blocklist.clean_sites(None) == []
    many = [f"site{i}.com" for i in range(blocklist.MAX_ENTRIES + 20)]
    assert len(blocklist.clean_sites(many)) == blocklist.MAX_ENTRIES


# ---------------------------------------------------------------- preferences
def test_blocklists_default_empty_and_defaults_are_never_shared():
    first = preferences.validate_preferences({})
    assert first["blocked_sites"] == [] and first["blocked_apps"] == []
    first["blocked_sites"].append("reddit.com")
    assert preferences.DEFAULTS["blocked_sites"] == []
    assert preferences.validate_preferences({})["blocked_sites"] == []


def test_blocklists_are_cleaned_and_survive_a_save_and_load(tmp_path):
    path = tmp_path / "preferences.json"
    saved = preferences.save_preferences({"blocked_sites": ["https://www.Reddit.com/", "bad host", "reddit.com"],
                                          "blocked_apps": ["Discord.exe", "x"]}, path)
    assert saved["blocked_sites"] == ["reddit.com"] and saved["blocked_apps"] == ["discord"]
    assert preferences.load_preferences(path)["blocked_apps"] == ["discord"]


@pytest.mark.parametrize("value", ["reddit.com", 5, {"a": 1}, None, True])
def test_malformed_blocklist_falls_back_without_touching_other_fields(value):
    result = preferences.validate_preferences({"blocked_sites": value, "blocked_apps": value, "work_minutes": 40})
    assert result["blocked_sites"] == [] and result["blocked_apps"] == [] and result["work_minutes"] == 40


# ---------------------------------------------------------------- closing apps
class Rig:
    def __init__(self, blocked, protected=()):
        self.closed_calls = []
        self.monitor = AppMonitor(scanner=lambda: self.snapshot, clock=lambda: 100.0, own_pid=2, blocked=blocked,
                                  killer=lambda pid, name: self.closed_calls.append((pid, name)) or True,
                                  protected_pids=protected)
        self.snapshot = Snapshot({})

    def scan(self, processes, front=None):
        self.snapshot = Snapshot(processes, front)
        self.monitor.refresh()


def test_blocked_apps_are_closed_on_the_next_scan_without_a_session():
    rig = Rig(["discord", "Steam.exe"])
    rig.scan({1: "code", 3: "discord", 4: "steam", 5: "steamwebhelper", 6: "notdiscord"})
    assert sorted(rig.closed_calls) == [(3, "discord"), (4, "steam"), (5, "steamwebhelper")]
    assert rig.monitor.take_closed() == ["discord", "steam", "steamwebhelper"]
    assert rig.monitor.take_closed() == []


def test_nothing_is_closed_when_the_list_is_empty_or_cleared():
    rig = Rig([])
    rig.scan({3: "discord"})
    assert rig.closed_calls == []
    rig.monitor.set_blocked(["discord"])
    rig.scan({3: "discord"})
    assert rig.closed_calls == [(3, "discord")]
    rig.monitor.set_blocked([])
    rig.scan({3: "discord"})
    assert len(rig.closed_calls) == 1


def test_own_process_ancestors_and_system_processes_are_never_closed():
    rig = Rig(["eye", "sys", "explor", "bash", "pyth", "launch"], protected=[9])
    rig.scan({2: "eyetrack-ui", 9: "launcher-shell", 10: "systemd", 11: "explorer.exe", 12: "bash", 13: "python3"})
    assert rig.closed_calls == []


def test_entries_shorter_than_three_letters_are_dropped_from_the_monitor():
    rig = Rig(["di", "discord"])
    assert rig.monitor.blocked == ("discord",)


def test_failed_close_is_not_reported_as_closed():
    monitor = AppMonitor(scanner=lambda: Snapshot({3: "discord"}), clock=lambda: 1.0, own_pid=2,
                         blocked=["discord"], killer=lambda pid, name: False)
    monitor.refresh()
    assert monitor.take_closed() == []


def test_terminate_refuses_a_process_that_is_no_longer_that_app():
    psutil = pytest.importorskip("psutil")
    assert appmonitor.terminate(os.getpid(), "definitely-not-this-process") is False
    assert psutil.Process(os.getpid()).is_running()


# ---------------------------------------------------------------- bridge reply
def post(server, path, body):
    conn = http.client.HTTPConnection(*server.server_address, timeout=5)
    try:
        conn.request("POST", path, body=json.dumps(body), headers={"Content-Type": "application/json"})
        return json.loads(conn.getresponse().read())
    finally:
        conn.close()


def test_extension_reply_carries_the_cleaned_blocked_sites(monkeypatch):
    monkeypatch.setattr(engine, "blocked_sites", [])
    monkeypatch.setattr(engine, "app_monitor", None)
    monkeypatch.setattr(engine, "browser", dict(engine.browser))       # /activity writes the shared browser state
    monkeypatch.setattr(engine, "switch_log", type(engine.switch_log)())
    server = engine.start_server(0)
    try:
        assert post(server, "/activity", {"domain": "example.com"})["blocked_sites"] == []
        engine.set_blocklist(["https://www.Reddit.com/r", "nope", "reddit.com"], ["discord"])
        assert post(server, "/activity", {"domain": "example.com"})["blocked_sites"] == ["reddit.com"]
    finally:
        server.shutdown()
        server.server_close()


def test_set_blocklist_updates_the_running_monitor(monkeypatch):
    monitor = AppMonitor(scanner=lambda: Snapshot({}), own_pid=2)
    monkeypatch.setattr(engine, "app_monitor", monitor)
    monkeypatch.setattr(engine, "blocked_sites", [])
    engine.set_blocklist([], ["Discord.exe", "ab"])
    assert monitor.blocked == ("discord",)


# ---------------------------------------------------------------- Settings
def test_settings_lists_save_apply_immediately_and_reload(window, app, tmp_path, monkeypatch):
    w, _ = window
    applied = []
    monkeypatch.setattr(engine, "set_blocklist", lambda sites, apps: applied.append((sites, apps)))
    dialog = open_from_menu(w, app)

    dialog.sites_editor.entry.setText("https://www.Reddit.com/r/all")
    QTest.mouseClick(dialog.sites_editor.add_button, Qt.MouseButton.LeftButton)
    dialog.apps_editor.entry.setText("Discord.exe")      # typed but never added: Save still counts it
    dialog.accept()
    app.processEvents()

    saved = json.loads((tmp_path / "preferences.json").read_text())
    assert saved["blocked_sites"] == ["reddit.com"] and saved["blocked_apps"] == ["discord"]
    assert w.prefs["blocked_sites"] == ["reddit.com"]
    assert applied == [(["reddit.com"], ["discord"])]

    again = open_from_menu(w, app)
    assert again.sites_editor.items() == ["reddit.com"] and again.apps_editor.items() == ["discord"]
    again.sites_editor.list.setCurrentRow(0)
    QTest.mouseClick(again.sites_editor.remove_button, Qt.MouseButton.LeftButton)
    again.accept()
    app.processEvents()
    assert applied[-1] == ([], ["discord"])


def test_invalid_entry_stops_the_save_and_enter_adds_instead_of_saving(window, app, tmp_path):
    w, _ = window
    dialog = open_from_menu(w, app)
    dialog.sites_editor.entry.setText("not a site")
    dialog.accept()
    app.processEvents()
    assert dialog.sites_editor.message.isVisibleTo(dialog) and not dialog.error.isHidden()
    assert not (tmp_path / "preferences.json").exists() and w.settings_dialog is dialog

    dialog.sites_editor.entry.setText("news.example.org")
    QTest.keyClick(dialog.sites_editor.entry, Qt.Key.Key_Return)
    app.processEvents()
    assert dialog.sites_editor.items() == ["news.example.org"]
    assert w.settings_dialog is dialog and not (tmp_path / "preferences.json").exists()   # Enter did not save


def test_cancel_leaves_the_blocklist_alone(window, app, monkeypatch):
    w, _ = window
    applied = []
    monkeypatch.setattr(engine, "set_blocklist", lambda *a: applied.append(a))
    dialog = open_from_menu(w, app)
    dialog.sites_editor.entry.setText("reddit.com")
    dialog.sites_editor.add_pending()
    dialog.reject()
    app.processEvents()
    assert applied == [] and w.prefs["blocked_sites"] == []
