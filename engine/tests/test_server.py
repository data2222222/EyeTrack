"""The engine's local HTTP bridge, started on an ephemeral port. Importing engine must not need tkinter, cv2 or mediapipe."""

import http.client
import json
import sys

import pytest

import engine


@pytest.fixture
def server():
    server = engine.start_server(0)
    yield server
    server.shutdown()
    server.server_close()


def request(server, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection(*server.server_address, timeout=5)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        response = conn.getresponse()
        return response.status, json.loads(response.read() or b"{}")
    finally:
        conn.close()


def test_import_needs_no_gui_or_camera_libs():
    assert not {"tkinter", "cv2", "mediapipe"} & set(sys.modules)


def test_post_activity_returns_state(server):
    body = json.dumps({"domain": "example.com", "category": "neutral", "idle": "active"})
    status, data = request(server, "POST", "/activity", body, {"Content-Type": "application/json"})
    assert status == 200
    assert "state" in data


def test_block_reply_carries_focus_screen_fields(server, monkeypatch, tmp_path):
    study = engine.study
    monkeypatch.setattr(study, "session", None)
    monkeypatch.setattr(study, "REPORTS_PATH", str(tmp_path / "sessions.json"))
    assert study.start_session("Physics", "capacitors", work_min=25)[0]
    study.record_event("override")
    body = json.dumps({"domain": "reddit.com", "category": "distraction", "idle": "active"})
    data = request(server, "POST", "/activity", body, {"Content-Type": "application/json"})[1]
    assert data["block"] and data["category_source"] == "list"
    assert data["block_total"] == 1500 and 1490 <= data["block_left"] <= 1500
    assert data["skips"] == 1


def test_get_status_ok_and_root_404(server):
    assert request(server, "GET", "/status")[0] == 200
    assert request(server, "GET", "/")[0] == 404


def test_foreign_origin_is_refused(server):
    status, _ = request(server, "GET", "/status", headers={"Origin": "https://evil.example"})
    assert status == 403


@pytest.mark.parametrize("incognito,category,expected", [
    (False, "productive", "<Physics> & circuits"),
    (True, "productive", ""),
    (False, "other", ""),
])
def test_current_tab_title_is_in_memory_only_and_hidden_for_incognito(server, monkeypatch, incognito, category, expected):
    monkeypatch.setattr(engine, "browser", dict(engine.browser, title="Previous page"))
    monkeypatch.setattr(engine, "jev", None)
    body = json.dumps({"domain": "example.com", "category": category, "incognito": incognito,
                       "title": "<Physics> & circuits"})
    status, data = request(server, "POST", "/activity", body, {"Content-Type": "application/json"})
    assert status == 200
    assert engine.browser["title"] == expected
    assert "title" not in data
