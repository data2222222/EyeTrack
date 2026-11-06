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


def test_get_status_ok_and_root_404(server):
    assert request(server, "GET", "/status")[0] == 200
    assert request(server, "GET", "/")[0] == 404


def test_foreign_origin_is_refused(server):
    status, _ = request(server, "GET", "/status", headers={"Origin": "https://evil.example"})
    assert status == 403
