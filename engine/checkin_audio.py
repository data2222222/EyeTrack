"""Play the sound for a visible desktop check-in."""
from pathlib import Path

from PySide6.QtCore import QObject, QUrl
from PySide6.QtWidgets import QApplication


class CheckinSound(QObject):
    def __init__(self, parent):
        super().__init__(parent)
        self._chime = QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / "assets" / "checkin-chime.wav"))
        self._player = None

    def play(self, music=None):
        if self._player is None:
            try:
                from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
            except ImportError:
                QApplication.beep()
                return
            self._player = QMediaPlayer(self)
            self._player.setAudioOutput(QAudioOutput(self._player))
            self._player.errorOccurred.connect(self._play_fallback)
        self._play_source(QUrl.fromLocalFile(music) if music else self._chime)

    def stop(self):
        if self._player is not None:
            self._player.setSource(QUrl())

    def _play_source(self, source):
        self._player.audioOutput().setVolume(0.70 if source == self._chime else 0.30)
        self._player.setSource(source)
        if self._player.source() == source:
            self._player.play()

    def _play_fallback(self, *_):
        source = self._player.source()
        if source.isEmpty():
            return
        if source != self._chime:
            self._play_source(self._chime)
        else:
            self.stop()
            QApplication.beep()
