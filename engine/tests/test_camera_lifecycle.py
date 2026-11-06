"""Camera resources must finish before MediaPipe's executors shut down."""

import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import engine


@pytest.fixture
def camera_runtime(monkeypatch, tmp_path):
    model = tmp_path / "face.task"
    model.touch()
    monkeypatch.setattr(engine, "MODEL_PATH", str(model))
    monkeypatch.setattr(engine, "running", True)
    monkeypatch.setattr(engine, "show_preview", False)
    monkeypatch.setattr(engine, "camera", dict(engine.camera))

    face, phone, capture = Mock(), Mock(), Mock()
    capture.read.return_value = (True, object())
    vision = SimpleNamespace(
        FaceLandmarkerOptions=lambda **kw: kw,
        FaceLandmarker=SimpleNamespace(create_from_options=lambda options: face),
        RunningMode=SimpleNamespace(VIDEO="video"),
    )
    mp_python = SimpleNamespace(BaseOptions=lambda **kw: kw, vision=vision)
    cv2 = SimpleNamespace(flip=lambda frame, mode: frame,
                         cvtColor=lambda frame, mode: frame, COLOR_BGR2RGB=1)
    mp = SimpleNamespace(Image=lambda **kw: object(),
                         ImageFormat=SimpleNamespace(SRGB=1))
    for name, module in {
        "cv2": cv2, "mediapipe": mp,
        "mediapipe.tasks": SimpleNamespace(python=mp_python),
        "mediapipe.tasks.python": mp_python,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(engine, "make_phone_detector", lambda *args: phone)
    monkeypatch.setattr(engine, "open_camera", lambda *args: capture)
    return face, phone, capture


def test_failed_camera_open_closes_both_detectors(camera_runtime, monkeypatch):
    face, phone, _ = camera_runtime
    monkeypatch.setattr(engine, "open_camera", lambda *args: None)
    engine.camera_loop(0)
    face.close.assert_called_once()
    phone.close.assert_called_once()
    assert "camera not available" in engine.camera["status"]


def test_inference_failure_releases_camera_and_clears_observations(camera_runtime):
    face, phone, capture = camera_runtime
    face.detect_for_video.side_effect = RuntimeError("inference failed")
    engine.camera.update(present=True, facing=True, phone=True, phone_since=1)
    engine.camera_loop(0)
    capture.release.assert_called_once()
    face.close.assert_called_once()
    phone.close.assert_called_once()
    assert "inference failed" in engine.camera["status"]
    assert not engine.camera["present"] and not engine.camera["facing"]
    assert not engine.camera["phone"] and engine.camera["phone_since"] is None


def test_stop_during_a_frame_releases_camera_and_detectors(camera_runtime, monkeypatch):
    face, phone, capture = camera_runtime

    def finish_frame(*args):
        engine.running = False
        return SimpleNamespace(face_landmarks=[])

    face.detect_for_video.side_effect = finish_frame
    engine.camera_loop(0)
    capture.release.assert_called_once()
    face.close.assert_called_once()
    phone.close.assert_called_once()
    assert engine.camera["status"] == "stopped"


@pytest.mark.parametrize("ui_failure", [False, True])
def test_main_waits_for_camera_cleanup_before_returning(monkeypatch, ui_failure):
    started, cleaned = threading.Event(), threading.Event()
    worker = []
    server, classifier = Mock(), Mock()
    server.server_address = ("127.0.0.1", 8000)
    monkeypatch.setattr(sys, "argv", ["engine.py"])
    monkeypatch.setattr(engine, "running", True)
    monkeypatch.setattr(engine, "jev", classifier)
    monkeypatch.setattr(engine, "init_classifier", lambda: None)
    monkeypatch.setattr(engine, "start_server", lambda port: server)
    monkeypatch.setattr(engine, "start_global_hotkeys", lambda: False)

    def camera_loop(index, stop_event=None):
        worker.append(threading.current_thread())
        started.set()
        while engine.running:
            cleaned.wait(0.005)
        # An in-flight frame needs time to finish and release native resources.
        cleaned.wait(0.05)
        cleaned.set()

    def run_ui(*args):
        engine.camera_controller.start()
        assert started.wait(2)
        if ui_failure:
            raise RuntimeError("UI failed")
        engine.running = False

    monkeypatch.setattr(engine, "camera_loop", camera_loop)
    monkeypatch.setattr(engine, "run_ui", run_ui)
    try:
        if ui_failure:
            with pytest.raises(RuntimeError, match="UI failed"):
                engine.main()
        else:
            engine.main()
        assert cleaned.is_set(), "main returned while the camera was still processing"
        assert not worker[0].is_alive()
        server.shutdown.assert_called_once()
        server.server_close.assert_called_once()
        classifier.close.assert_called_once()
    finally:
        engine.running = False
        for thread in worker:
            thread.join(2)


def test_session_stop_releases_worker_without_stopping_the_app(monkeypatch):
    started, finished = threading.Event(), threading.Event()
    monkeypatch.setattr(engine, "running", True)
    monkeypatch.setattr(engine, "camera", dict(engine.camera))

    def camera_loop(index, stop_event):
        started.set()
        stop_event.wait(2)
        finished.set()

    monkeypatch.setattr(engine, "camera_loop", camera_loop)
    controller = engine.CameraController()
    try:
        controller.start()
        assert started.wait(1)
        controller.stop()
        assert finished.is_set()
        assert controller.worker is None
        assert engine.running
        assert engine.camera["status"] == "off"
    finally:
        controller.stop()
