from array import array
import builtins
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import preferences
import sounds


@pytest.fixture
def audio(monkeypatch):
    sink, buffer = Mock(), Mock()
    start = Mock(return_value=(sink, buffer))
    monkeypatch.setattr(sounds, "_start_audio", start)
    return start, sink, buffer


def test_import_and_construction_do_not_import_qt_or_open_hardware():
    script = """
import builtins
original_import = builtins.__import__
def guarded_import(name, *args, **kwargs):
    if name.startswith(('PySide6', 'cv2', 'mediapipe', 'study')):
        raise AssertionError(name)
    return original_import(name, *args, **kwargs)
builtins.__import__ = guarded_import
import sounds
player = sounds.SoundPlayer()
player.stop()
"""
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=Path(sounds.__file__).parent,
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("event", ["checkin", "completion"])
@pytest.mark.parametrize("style", preferences.SOUND_STYLES)
def test_play_submits_synthesized_audio_with_parent_and_volume(audio, event, style):
    start, sink, buffer = audio
    parent = object()
    player = sounds.SoundPlayer(parent)
    assert player.play(event, {"sound_style": style, "sound_volume": 67})
    samples, volume, passed_parent = start.call_args.args
    assert isinstance(samples, bytes) and any(samples)
    assert volume == 67 and passed_parent is parent
    player.stop()
    sink.stop.assert_called_once()
    buffer.close.assert_called_once()


@pytest.mark.parametrize("preview", [False, True])
@pytest.mark.parametrize("settings", [{"sounds_enabled": False}, {"sound_volume": 0}])
def test_master_and_volume_gates_also_apply_to_preview(audio, preview, settings):
    assert not sounds.SoundPlayer().play("checkin", settings, preview=preview)
    audio[0].assert_not_called()


@pytest.mark.parametrize("event,toggle", [("checkin", "sound_checkins"), ("completion", "sound_completion")])
def test_preview_bypasses_only_event_gate(audio, event, toggle):
    player = sounds.SoundPlayer()
    assert not player.play(event, {toggle: False})
    audio[0].assert_not_called()
    assert player.play(event, {toggle: False}, preview=True)


@pytest.mark.parametrize("event", [None, "unknown", "complete", [], {}])
def test_unknown_events_do_not_start_audio(audio, event):
    assert not sounds.SoundPlayer().play(event, {})
    audio[0].assert_not_called()


def test_replay_stops_previous_audio_and_stop_is_idempotent(audio):
    start, sink, buffer = audio
    player = sounds.SoundPlayer()
    assert player.play("checkin", {})
    assert player.play("completion", {})
    sink.stop.assert_called_once()
    buffer.close.assert_called_once()
    player.stop()
    player.stop()
    assert sink.stop.call_count == buffer.close.call_count == 2
    assert start.call_count == 2


@pytest.mark.parametrize("failure", [ImportError("no multimedia"), RuntimeError("no backend"), OSError("no device")])
def test_audio_errors_are_optional_and_can_be_retried(audio, failure):
    start, sink, buffer = audio
    start.side_effect = failure
    player = sounds.SoundPlayer()
    assert not player.play("checkin", {})
    player.stop()
    start.side_effect = None
    assert player.play("checkin", {})


def test_missing_multimedia_is_graceful(monkeypatch):
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.startswith("PySide6"):
            raise ImportError("optional multimedia unavailable")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    assert not sounds.SoundPlayer().play("completion", {})


def test_invalid_preferences_use_safe_validated_defaults(audio):
    assert sounds.SoundPlayer().play("checkin", {"sound_style": [], "sound_volume": -10})
    assert audio[0].call_args.args[1] == 35


def test_stop_tolerates_deleted_qt_objects(audio):
    start, sink, buffer = audio
    sink.stop.side_effect = RuntimeError("deleted")
    player = sounds.SoundPlayer()
    assert player.play("checkin", {})
    player.stop()
    buffer.close.assert_called_once()
    sink.deleteLater.assert_called_once()


@pytest.mark.parametrize("style", preferences.SOUND_STYLES)
def test_tones_are_short_bounded_pcm_with_gentle_endpoints(style):
    waveforms = []
    for event in ("checkin", "completion"):
        raw = sounds._synthesize(event, style)
        samples = array("h")
        samples.frombytes(raw)
        if sys.byteorder != "little":
            samples.byteswap()
        assert 0 < len(samples) < sounds._SAMPLE_RATE
        assert samples[0] == samples[-1] == 0
        assert 0 < max(abs(sample) for sample in samples) <= 7500
        waveforms.append(raw)
    assert len(waveforms[1]) > len(waveforms[0])


@pytest.fixture
def qt_audio(monkeypatch):
    device = Mock()
    device.isNull.return_value = False
    device.isFormatSupported.return_value = True
    sink, buffer = Mock(), Mock()
    sink.error.return_value = 0
    buffer.open.return_value = True
    audio = SimpleNamespace(
        QCoreApplication=Mock(), QMediaDevices=Mock(), QAudioFormat=Mock(),
        QAudioSink=Mock(return_value=sink), QBuffer=Mock(return_value=buffer),
        QByteArray=bytes, QIODevice=SimpleNamespace(OpenModeFlag=SimpleNamespace(ReadOnly=1)),
        QAudio=SimpleNamespace(Error=SimpleNamespace(NoError=0)),
    )
    audio.QMediaDevices.defaultAudioOutput.return_value = device
    monkeypatch.setattr(sounds, "_load_qt_audio", lambda: audio)
    return audio, device, sink, buffer


def test_qt_backend_uses_pcm_buffer_and_nonblocking_sink(qt_audio):
    audio, device, sink, buffer = qt_audio
    parent = object()
    assert sounds._start_audio(b"\x00\x00", 35, parent) == (sink, buffer)
    audio.QAudioFormat.return_value.setSampleRate.assert_called_once_with(24000)
    audio.QAudioFormat.return_value.setChannelCount.assert_called_once_with(1)
    sink.setVolume.assert_called_once_with(0.35)
    sink.start.assert_called_once_with(buffer)
    buffer.setData.assert_called_once_with(b"\x00\x00")
    assert audio.QAudioSink.call_args.args[2] is parent


@pytest.mark.parametrize("unavailable", ["application", "device", "format", "buffer", "sink"])
def test_qt_backend_unavailable_paths_are_graceful(qt_audio, unavailable):
    audio, device, sink, buffer = qt_audio
    if unavailable == "application":
        audio.QCoreApplication.instance.return_value = None
    elif unavailable == "device":
        device.isNull.return_value = True
    elif unavailable == "format":
        device.isFormatSupported.return_value = False
    elif unavailable == "buffer":
        buffer.open.return_value = False
    else:
        sink.error.return_value = 1
    assert not sounds.SoundPlayer().play("checkin", {})
    if unavailable in ("buffer", "sink"):
        buffer.close.assert_called_once()
    else:
        audio.QAudioSink.assert_not_called()


def test_qt_backend_failure_releases_partial_resources(qt_audio):
    audio, device, sink, buffer = qt_audio
    sink.start.side_effect = RuntimeError("backend failed")
    assert not sounds.SoundPlayer().play("completion", {})
    sink.stop.assert_called_once()
    buffer.close.assert_called_once()
