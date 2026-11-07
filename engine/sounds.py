"""Optional synthesized notification tones; Qt audio is imported only on play.

No files, devices, or Qt objects are opened at import or construction time. Call
play/stop on the Qt UI thread. A successful play means audio was submitted, not
that a physical speaker is audible; backend errors may also occur asynchronously.
"""
from array import array
import math
import sys
from types import SimpleNamespace

from preferences import validate_preferences


_SAMPLE_RATE = 24000
_EVENT_PREFERENCES = {"checkin": "sound_checkins", "completion": "sound_completion"}
_FREQUENCIES = {
    "chime": (659.25, 880.0, 1108.73),
    "bell": (523.25, 659.25, 783.99),
    "soft": (392.0, 493.88, 587.33),
}


def _synthesize(event, style):
    frequencies = _FREQUENCIES[style]
    if event == "checkin":
        frequencies = frequencies[:2]
    duration = 0.11 if event == "checkin" else 0.16
    note_samples = int(_SAMPLE_RATE * duration)
    silence_samples = int(_SAMPLE_RATE * 0.025)
    samples = array("h")
    for frequency in frequencies:
        for sample_index in range(note_samples):
            progress = sample_index / (note_samples - 1)
            envelope = math.sin(math.pi * progress) ** 2
            phase = 2 * math.pi * frequency * sample_index / _SAMPLE_RATE
            tone = math.sin(phase)
            if style == "bell":
                tone = (tone + 0.2 * math.sin(phase * 2.01)) / 1.2
                envelope *= math.exp(-2 * progress)
            elif style == "soft":
                tone *= 0.7
            samples.append(round(32767 * 0.22 * envelope * tone))
        samples.extend([0] * silence_samples)
    if sys.byteorder != "little":
        samples.byteswap()
    return samples.tobytes()


def _load_qt_audio():
    from PySide6.QtCore import QByteArray, QBuffer, QCoreApplication, QIODevice
    from PySide6.QtMultimedia import QAudio, QAudioFormat, QAudioSink, QMediaDevices

    return SimpleNamespace(
        QByteArray=QByteArray, QBuffer=QBuffer, QCoreApplication=QCoreApplication,
        QIODevice=QIODevice, QAudio=QAudio, QAudioFormat=QAudioFormat,
        QAudioSink=QAudioSink, QMediaDevices=QMediaDevices,
    )


def _release_audio(sink, buffer):
    for resource, method_names in (
        (sink, ("stop", "deleteLater")),
        (buffer, ("close", "deleteLater")),
    ):
        if resource is not None:
            for method_name in method_names:
                try:
                    getattr(resource, method_name)()
                except Exception:
                    pass


def _start_audio(samples, volume, parent):
    audio = _load_qt_audio()
    if audio.QCoreApplication.instance() is None:
        return None
    device = audio.QMediaDevices.defaultAudioOutput()
    if device.isNull():
        return None
    audio_format = audio.QAudioFormat()
    audio_format.setSampleRate(_SAMPLE_RATE)
    audio_format.setChannelCount(1)
    audio_format.setSampleFormat(audio.QAudioFormat.SampleFormat.Int16)
    if not device.isFormatSupported(audio_format):
        return None
    sink = None
    buffer = None
    try:
        buffer = audio.QBuffer()
        buffer.setData(audio.QByteArray(samples))
        if not buffer.open(audio.QIODevice.OpenModeFlag.ReadOnly):
            _release_audio(sink, buffer)
            return None
        sink = audio.QAudioSink(device, audio_format, parent)
        sink.setVolume(volume / 100.0)
        sink.start(buffer)
        if sink.error() != audio.QAudio.Error.NoError:
            _release_audio(sink, buffer)
            return None
        return sink, buffer
    except Exception:
        _release_audio(sink, buffer)
        raise


class SoundPlayer:
    """Play short, nonblocking tones, retaining Qt buffers until stop/replay."""

    def __init__(self, parent=None):
        self._parent = parent
        self._output = None

    def play(self, event, preferences, preview=False):
        """Return False for muted/unsupported audio; never require multimedia.

        Preview skips only the event toggle, never master mute or zero volume.
        Each accepted playback replaces the previous tone rather than stacking.
        """
        if not isinstance(event, str) or event not in _EVENT_PREFERENCES:
            return False
        values = validate_preferences(preferences)
        if not values["sounds_enabled"] or values["sound_volume"] == 0:
            return False
        if not preview and not values[_EVENT_PREFERENCES[event]]:
            return False
        self.stop()
        try:
            samples = _synthesize(event, values["sound_style"])
            self._output = _start_audio(samples, values["sound_volume"], self._parent)
        except Exception:
            self._output = None
        return self._output is not None

    def stop(self):
        """Stop immediately and release retained resources; safe to repeat."""
        output, self._output = self._output, None
        if output is not None:
            _release_audio(*output)
