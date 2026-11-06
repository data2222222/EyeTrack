"""Guided calibration renders and cancels without opening a real camera."""

import os
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
qt_widgets = pytest.importorskip("PySide6.QtWidgets")
QApplication, QDialog = qt_widgets.QApplication, qt_widgets.QDialog

import camera_calibration
import tracking


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def sample_target(calibration, values, now):
    stage = calibration.view()["stage"]
    for i in range(50):
        calibration.add(values, now + i / 15)
        if calibration.view()["stage"] != stage:
            return
    pytest.fail("target did not finish")


def test_five_targets_render_and_success_closes_dialog(app, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(camera_calibration.time, "monotonic", lambda: clock[0])
    calibration = tracking.Calibration()
    calibration.start(guided=True)
    dialog = camera_calibration.CalibrationDialog(calibration, lambda: "ok")
    dialog.showFullScreen()
    try:
        points = ((.5, .5, .5, 0), (.5, .5, .35, 0), (.5, .5, .65, 0),
                  (.5, .5, .5, -.4), (.5, .5, .5, .4))
        for stage, values in enumerate(points):
            assert not dialog.grab().isNull()
            sample_target(calibration, values, stage * 10)
        assert calibration.view()["quality"] == "screen"
        dialog.refresh()
        assert not dialog.grab().isNull()
        clock[0] += 1
        dialog.refresh()
        assert dialog.result() == QDialog.DialogCode.Accepted
        assert not dialog.isVisible()
    finally:
        dialog.close()


def test_escape_cancels_and_preserves_previous_profile(app):
    calibration = tracking.Calibration()
    for i in range(60):
        calibration.add((.5, .5, .5, 0), i / 15)
    previous = calibration.profile()
    calibration.start(guided=True)
    dialog = camera_calibration.show_calibration(calibration, lambda: "ok")
    assert camera_calibration.show_calibration(calibration, lambda: "ok") is dialog
    dialog.reject()  # QDialog's Escape action
    assert not calibration.view()["active"]
    assert calibration.profile() == previous
    assert camera_calibration._dialog is None


def test_pausing_capture_closes_calibration_and_resets_initial_samples(app):
    calibration = tracking.Calibration()
    calibration.start(guided=True)
    dialog = camera_calibration.CalibrationDialog(calibration, lambda: "off")
    dialog.show()
    dialog.refresh()
    assert not dialog.isVisible()
    assert calibration.view()["active"]
    assert not calibration.view()["guided"]


def test_desktop_calibration_control_starts_guided_calibration(app, monkeypatch):
    FocusWindow = pytest.importorskip("desktop").FocusWindow
    import study

    monkeypatch.setattr(study, "session", None)
    calibration = tracking.Calibration()
    runtime = SimpleNamespace(camera_controller=Mock(simulated=False), calib=calibration,
                              reset_calibration=lambda guided=False: calibration.start(guided=guided),
                              camera={"status": "ok"})
    window = FocusWindow(runtime, start_timer=False)
    try:
        window.calibrate_button.click()
        assert calibration.view()["guided"]
        assert camera_calibration._dialog is not None
        camera_calibration._dialog.reject()
    finally:
        window.close()
