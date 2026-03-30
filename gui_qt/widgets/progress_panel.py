"""Progress bars panel — 6 bars that show/hide on demand."""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QProgressBar, QLabel,
)
from PySide6.QtCore import QTimer


class _ProgressRow(QWidget):
    """Single progress bar row with label and counter."""

    def __init__(self, label_text: str, parent=None):
        super().__init__(parent)
        self.setVisible(False)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(8)

        self._label = QLabel(label_text)
        self._label.setFixedWidth(130)
        layout.addWidget(self._label)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(16)
        layout.addWidget(self._bar, 1)

        self._pct_label = QLabel("0%")
        self._pct_label.setFixedWidth(40)
        layout.addWidget(self._pct_label)

        self._counter = QLabel("")
        self._counter.setFixedWidth(80)
        layout.addWidget(self._counter)

    def start(self, total: int = 0):
        self._bar.setValue(0)
        self._pct_label.setText("0%")
        self._counter.setText(f"0 / {total}" if total else "")
        self.setVisible(True)

    def set_progress(self, value: int, done: int = 0, total: int = 0,
                     label: str = ""):
        self._bar.setValue(value)
        self._pct_label.setText(f"{value}%")
        if total:
            self._counter.setText(f"{done} / {total}")
        elif label:
            self._counter.setText(label)

    def finish(self, delay_ms: int = 1500):
        self._bar.setValue(100)
        self._pct_label.setText("100%")
        QTimer.singleShot(delay_ms, lambda: self.setVisible(False))


class ProgressPanel(QWidget):
    """Container for all 6 progress bar rows."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.audio     = _ProgressRow("Audio extraction")
        self.whisper   = _ProgressRow("Transcription")
        self.analysis  = _ProgressRow("LLM analysis")
        self.extract   = _ProgressRow("Clip extraction")
        self.slicing   = _ProgressRow("Slicing")
        self.images    = _ProgressRow("Visual aids")

        for row in (self.audio, self.whisper, self.analysis,
                    self.extract, self.slicing, self.images):
            layout.addWidget(row)

    def connect_signals(self, signals):
        """Wire WorkerSignals to progress bars."""
        # Audio
        signals.audio_start.connect(lambda: self.audio.start())
        signals.audio_progress.connect(
            lambda pct: self.audio.set_progress(pct))
        signals.audio_done.connect(lambda: self.audio.finish())

        # Whisper
        signals.whisper_start.connect(lambda: self.whisper.start())
        signals.whisper_progress.connect(
            lambda pct, lbl: self.whisper.set_progress(pct, label=lbl))
        signals.whisper_done.connect(lambda: self.whisper.finish())

        # Analysis
        signals.analysis_start.connect(lambda t: self.analysis.start(t))
        signals.analysis_progress.connect(
            lambda d, t: self.analysis.set_progress(
                int(d / t * 100) if t else 0, d, t))
        signals.analysis_done.connect(lambda: self.analysis.finish())

        # Extraction
        signals.extract_start.connect(lambda t: self.extract.start(t))
        signals.extract_progress.connect(
            lambda d, t, _: self.extract.set_progress(
                int(d / t * 100) if t else 0, d, t))
        signals.extract_done.connect(lambda _: self.extract.finish())

        # Slicing
        signals.slice_start.connect(lambda t: self.slicing.start(t))
        signals.slice_progress.connect(
            lambda d, t: self.slicing.set_progress(
                int(d / t * 100) if t else 0, d, t))
        signals.slice_complete.connect(lambda: self.slicing.finish())

        # Images
        signals.image_start.connect(lambda t: self.images.start(t))
        signals.image_progress.connect(
            lambda d, t: self.images.set_progress(
                int(d / t * 100) if t else 0, d, t))
        signals.image_complete.connect(lambda: self.images.finish())
