"""Desktop-app monitoring with fake scans and a fake clock: no psutil, windows or processes needed."""
import json
import os
import sys
import time

import pytest

import appmonitor
from appmonitor import AppMonitor, Snapshot


class Rig:
    def __init__(self, **kwargs):
        self.now = [100.0]
        self.snapshot = Snapshot({1: "code", 2: "eyetrack"}, 1)
        self.monitor = AppMonitor(scanner=lambda: self.snapshot, clock=lambda: self.now[0],
                                  own_pid=2, **kwargs)

    def scan(self, processes, front=None, advance=2.0):
        self.now[0] += advance
        self.snapshot = Snapshot(processes, front)
        self.monitor.refresh()

    def observe(self, working=True):
        return self.monitor.observe(working)


def test_name_matching_is_whole_name_prefix():
    watch = appmonitor.DEFAULT_DISTRACTING
    assert appmonitor.matches("Discord.exe", watch)
    assert appmonitor.matches("steamwebhelper", watch)
    assert appmonitor.matches("RobloxPlayerBeta.exe", watch)
    assert not appmonitor.matches("upstream-tool", watch)
    assert not appmonitor.matches("javaw.exe", watch)       # generic Java launcher, too many false alarms
    assert not appmonitor.matches("", watch)


def test_watchlist_comes_from_config_or_defaults(tmp_path):
    config = tmp_path / "config.json"
    assert appmonitor.load_watchlist(config) == appmonitor.DEFAULT_DISTRACTING
    config.write_text(json.dumps({"apps": {"distracting": ["Slack.exe", " ", 5, "slack"]}}))
    assert appmonitor.load_watchlist(config) == ("slack",)
    config.write_text("not json")
    assert appmonitor.load_watchlist(config) == appmonitor.DEFAULT_DISTRACTING


def test_foreground_app_is_reported_without_alert(tmp_path):
    rig = Rig()
    rig.scan({1: "code", 2: "eyetrack"}, 1)
    info, alerts = rig.observe()
    assert info["app"] == "code" and not info["app_distracting"] and alerts == []


def test_own_window_is_not_an_app():
    rig = Rig()
    rig.scan({1: "code", 2: "eyetrack"}, 2)
    assert rig.observe()[0]["app"] is None


def test_alert_when_distracting_app_comes_to_front_then_not_every_scan():
    rig = Rig()
    rig.scan({1: "code", 3: "discord"}, 1)
    assert rig.observe()[1] == []                       # already open in the background: quiet
    rig.scan({1: "code", 3: "discord"}, 3)
    info, alerts = rig.observe()
    assert info["app_distracting"] and len(alerts) == 1 and "Discord" in alerts[0]
    rig.scan({1: "code", 3: "discord"}, 3)
    assert rig.observe()[1] == []                       # still in front, no repeat


def test_alert_when_distracting_app_starts_and_helper_processes_do_not_repeat():
    rig = Rig()
    rig.scan({1: "code"}, 1)
    rig.observe()
    rig.scan({1: "code", 5: "steam", 6: "steamwebhelper", 7: "steamwebhelper"}, 1)
    alerts = rig.observe()[1]
    assert len(alerts) == 2 and any("Steam just started" in a for a in alerts)
    rig.scan({1: "code", 5: "steam", 6: "steamwebhelper", 8: "steamwebhelper"}, 1)
    assert rig.observe()[1] == []


def test_cooldown_limits_repeat_alerts_per_app():
    rig = Rig(cooldown=120.0)
    rig.scan({1: "code", 3: "discord"}, 1)
    rig.observe()
    rig.scan({1: "code", 3: "discord"}, 3)
    assert len(rig.observe()[1]) == 1
    rig.scan({1: "code", 3: "discord"}, 1)
    rig.observe()
    rig.scan({1: "code", 3: "discord"}, 3)
    assert rig.observe()[1] == []                       # switched back too soon
    rig.scan({1: "code", 3: "discord"}, 1, advance=130)
    rig.observe()
    rig.scan({1: "code", 3: "discord"}, 3)
    assert len(rig.observe()[1]) == 1


def test_no_alerts_and_no_backlog_while_not_working():
    rig = Rig()
    rig.scan({1: "code"}, 1)
    rig.observe()
    rig.scan({1: "code", 3: "discord"}, 3)
    info, alerts = rig.observe(working=False)           # break or pause
    assert alerts == [] and info["app_distracting"]     # still tracked for the record
    rig.scan({1: "code", 3: "discord"}, 1)
    assert rig.observe(working=True)[1] == []           # launched during the break: not announced
    rig.scan({1: "code", 3: "discord"}, 3)
    assert len(rig.observe(working=True)[1]) == 1       # announced once it is in front


def test_distracting_app_still_in_front_when_work_resumes_is_announced():
    rig = Rig()
    rig.scan({1: "code", 3: "discord"}, 3)
    rig.observe(working=False)
    rig.scan({1: "code", 3: "discord"}, 3)
    assert len(rig.observe(working=True)[1]) == 1


def test_stale_scan_is_not_attributed_or_alerted():
    rig = Rig()
    rig.scan({1: "code", 3: "discord"}, 3)
    rig.now[0] += appmonitor.FRESH_SECONDS + 1
    info, alerts = rig.observe()
    assert info["app"] is None and alerts == []


def test_unavailable_scanner_is_silent():
    monitor = AppMonitor(scanner=lambda: None)
    monitor.refresh()
    assert not monitor.available and monitor.observe(True) == ({}, [])


def test_scanner_errors_do_not_crash_the_monitor():
    def broken():
        raise RuntimeError("boom")
    monitor = AppMonitor(scanner=broken)
    monitor.refresh()
    assert monitor.observe(True) == ({}, [])


def test_worker_thread_starts_and_stops_cleanly():
    calls = []
    monitor = AppMonitor(scanner=lambda: calls.append(1) or Snapshot({1: "code"}, 1), interval=0.01)
    monitor.start()
    monitor.start()                                      # idempotent
    deadline = time.time() + 2
    while not calls and time.time() < deadline:
        time.sleep(0.005)
    monitor.stop()
    assert calls and monitor._worker is None
    count = len(calls)
    time.sleep(0.05)
    assert len(calls) == count                           # stopped for good


def test_scan_reports_unavailable_without_psutil(monkeypatch):
    monkeypatch.setitem(sys.modules, "psutil", None)   # makes `import psutil` fail
    assert appmonitor.scan() is None


def test_real_scan_lists_this_process():
    pytest.importorskip("psutil")
    snapshot = appmonitor.scan()
    assert os.getpid() in snapshot.processes
