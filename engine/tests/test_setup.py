"""Pure parts of setup.py: browser lookup, manifest validation, config.json key merge."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import setup as study_setup  # noqa: E402


def candidates(platform, existing=(), on_path=(), env=None):
    return study_setup.browser_candidates(
        platform, env or {}, lambda exe: f"/usr/bin/{exe}" if exe in on_path else None, lambda p: p in existing)


def test_windows_prefers_chrome_in_program_files_then_edge():
    env = {"PROGRAMFILES": r"C:\PF", "LOCALAPPDATA": r"C:\Local"}
    chrome = r"C:\PF\Google\Chrome\Application\chrome.exe"
    edge = r"C:\Local\Microsoft\Edge\Application\msedge.exe"
    assert candidates("win32", {edge, chrome}, env=env) == [("Google Chrome", chrome), ("Microsoft Edge", edge)]
    assert candidates("win32", {edge}, env=env) == [("Microsoft Edge", edge)]
    assert candidates("win32", env=env) == []


def test_macos_uses_app_names():
    assert candidates("darwin", {"/Applications/Google Chrome.app"}) == [("Google Chrome", "Google Chrome")]


def test_linux_checks_path_in_order():
    found = candidates("linux", on_path={"chromium", "google-chrome"})
    assert [name for name, _ in found] == ["google-chrome", "chromium"]


def test_python_versions():
    assert study_setup.python_ok((3, 10)) and study_setup.python_ok((3, 14))
    assert not study_setup.python_ok((3, 9)) and not study_setup.python_ok((3, 15))


def test_manifest_validation(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({
        "background": {"service_worker": "bg.js"},
        "content_scripts": [{"js": ["c.js"]}],
    }))
    assert study_setup.validate_manifest(tmp_path) == ["missing file: bg.js", "missing file: c.js"]
    (tmp_path / "bg.js").write_text("")
    (tmp_path / "c.js").write_text("")
    assert study_setup.validate_manifest(tmp_path) == []
    (tmp_path / "manifest.json").write_text("{nope")
    assert "unreadable" in study_setup.validate_manifest(tmp_path)[0]


def test_real_extension_manifest_is_valid():
    assert study_setup.validate_manifest(study_setup.EXTENSION_DIR) == []


def test_save_api_key_keeps_other_keys(tmp_path):
    cfg = tmp_path / "data" / "config.json"
    cfg.parent.mkdir()
    cfg.write_text(json.dumps({"classifier": {"never_send": {"domains": ["bank.com"]}}}))
    study_setup.save_api_key("secret", cfg)
    assert json.loads(cfg.read_text()) == {
        "classifier": {"never_send": {"domains": ["bank.com"]}}, "typesafe_api_key": "secret"}
    assert study_setup.has_api_key({}, cfg)
    assert not study_setup.has_api_key({}, tmp_path / "none.json")
    assert study_setup.has_api_key({"TYPESAFE_API_KEY": "x"}, tmp_path / "none.json")
