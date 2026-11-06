"""Platform helpers in engine.py: font choice, camera backend order, model download (no network, no GUI)."""

import types

import engine

FAKE_CV2 = types.SimpleNamespace(CAP_DSHOW=700, CAP_AVFOUNDATION=1200, CAP_V4L2=200)


def test_pick_fonts_prefers_the_platform_fonts():
    assert engine.pick_fonts("win32", {"Segoe UI", "Consolas", "Arial"}, "TkD", "TkF") == ("Segoe UI", "Consolas")
    assert engine.pick_fonts("darwin", {"Helvetica Neue", "Menlo"}, "TkD", "TkF") == ("Helvetica Neue", "Menlo")
    assert engine.pick_fonts("darwin", {"SF Pro Text", "Helvetica Neue", "Menlo"}, "TkD", "TkF")[0] == "SF Pro Text"
    assert engine.pick_fonts("linux", {"DejaVu Sans", "DejaVu Sans Mono"}, "TkD", "TkF") == (
        "DejaVu Sans", "DejaVu Sans Mono")


def test_pick_fonts_falls_back_to_tk_defaults():
    assert engine.pick_fonts("linux", {"Liberation Sans"}, "TkD", "TkF") == ("TkD", "TkF")
    assert engine.pick_fonts("freebsd", {"DejaVu Sans"}, "TkD", "TkF") == ("TkD", "TkF")
    assert engine.pick_fonts("win32", {"Segoe UI"}, "TkD", "TkF") == ("Segoe UI", "TkF")


def test_camera_backends_per_platform():
    assert engine.camera_backends(FAKE_CV2, "win32") == [700]
    assert engine.camera_backends(FAKE_CV2, "darwin") == [1200]
    assert engine.camera_backends(FAKE_CV2, "linux") == [200]
    assert engine.camera_backends(FAKE_CV2, "freebsd") == []
    assert engine.camera_backends(types.SimpleNamespace(), "linux") == []   # old OpenCV without the constant


class FakeCapture:
    def __init__(self, opened):
        self.opened, self.released = opened, False

    def isOpened(self):
        return self.opened

    def release(self):
        self.released = True


def fake_cv2(opens):
    """cv2 stand-in whose VideoCapture opens only for the backends listed in `opens` (None = default)."""
    calls = []

    def video_capture(index, backend=None):
        calls.append(backend)
        return FakeCapture(backend in opens)

    return types.SimpleNamespace(VideoCapture=video_capture, calls=calls, **vars(FAKE_CV2))


def test_open_camera_tries_preferred_backend_then_default():
    cv2 = fake_cv2(opens={700})
    assert engine.open_camera(cv2, 0, "win32").isOpened() and cv2.calls == [700]

    cv2 = fake_cv2(opens={None})
    assert engine.open_camera(cv2, 0, "win32").isOpened() and cv2.calls == [700, None]

    cv2 = fake_cv2(opens=set())
    assert engine.open_camera(cv2, 0, "darwin") is None and cv2.calls == [1200, None]


def test_download_writes_file_atomically(tmp_path, monkeypatch):
    source = tmp_path / "src.bin"
    source.write_bytes(b"model-bytes")
    dest = tmp_path / "out" / "model.bin"
    dest.parent.mkdir()
    monkeypatch.setattr(engine, "ssl_context", lambda: None)   # file:// ignores TLS
    engine.download(source.as_uri(), str(dest))
    assert dest.read_bytes() == b"model-bytes"
    assert not (dest.parent / "model.bin.part").exists()


def test_download_skips_existing_file(tmp_path):
    dest = tmp_path / "model.bin"
    dest.write_bytes(b"old")
    engine.download("file:///does/not/exist", str(dest))
    assert dest.read_bytes() == b"old"
