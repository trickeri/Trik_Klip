"""Main application window — assembles all tabs, log, and progress panels."""

import os
import sys
import logging
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QSplitter, QTabWidget, QScrollArea, QMessageBox, QApplication,
)
from PySide6.QtGui import QFont, QClipboard
from PySide6.QtCore import Qt

from gui_qt import theme
from gui_qt.signals import WorkerSignals
from gui_qt.widgets.log_panel import LogPanel
from gui_qt.widgets.progress_panel import ProgressPanel
from gui_qt.tabs.transcribe_tab import TranscribeTab
from gui_qt.tabs.extract_tab import ExtractTab
from gui_qt.tabs.slice_tab import SliceTab
from gui_qt.tabs.about_tab import AboutTab
from gui_qt.tabs.settings_tab import SettingsTab
from gui_qt.workers import PipelineWorker, ExtractWorker, SliceWorker

VERSION = "1.0.02_a"


def _scroll_wrap(widget: QWidget) -> QScrollArea:
    """Wrap a widget in a QScrollArea."""
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(widget)
    scroll.setFrameShape(QScrollArea.NoFrame)
    return scroll


class MainWindow(QMainWindow):
    """The primary application window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Trik_Klip v{VERSION}")
        self.setMinimumSize(860, 1000)
        self.resize(860, 1000)

        # Signals for worker communication
        self._signals = WorkerSignals()

        # Active worker references
        self._worker = None
        self._extract_worker = None
        self._slice_worker = None

        # File logger
        self._setup_file_logger()

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── Header ───────────────────────────────────────────────────────
        header = QWidget()
        header.setFixedHeight(52)
        header.setStyleSheet(f"background-color: {theme.ACCENT};")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 0, 16, 0)

        logo = QLabel("Trik_Klip")
        logo.setFont(QFont("Segoe UI", 18, QFont.Bold))
        logo.setStyleSheet("color: white; background: transparent;")
        header_layout.addWidget(logo)

        version_lbl = QLabel(f"v{VERSION}")
        version_lbl.setStyleSheet(
            "color: rgba(255,255,255,0.7); background: transparent; "
            "font-size: 9pt;")
        header_layout.addWidget(version_lbl)
        header_layout.addStretch()

        main_layout.addWidget(header)

        # ── Splitter ─────────────────────────────────────────────────────
        splitter = QSplitter(Qt.Vertical)
        main_layout.addWidget(splitter, 1)

        # ── Top: Tab widget ──────────────────────────────────────────────
        self._tabs = QTabWidget()
        splitter.addWidget(self._tabs)

        self._transcribe_tab = TranscribeTab()
        self._extract_tab = ExtractTab()
        self._slice_tab = SliceTab()
        self._about_tab = AboutTab()
        self._settings_tab = SettingsTab()

        self._tabs.addTab(_scroll_wrap(self._transcribe_tab), "Transcribe")
        self._tabs.addTab(_scroll_wrap(self._extract_tab), "Extract")
        self._tabs.addTab(_scroll_wrap(self._slice_tab), "Slice")
        self._tabs.addTab(self._about_tab, "About")
        self._tabs.addTab(_scroll_wrap(self._settings_tab), "Settings")

        # ── Bottom: Log + progress ───────────────────────────────────────
        bottom = QWidget()
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(8, 4, 8, 8)
        bottom_layout.setSpacing(4)
        splitter.addWidget(bottom)

        log_header = QLabel("<b>Output Log</b>")
        log_header.setStyleSheet(f"color: {theme.DIM}; font-size: 9pt;")
        bottom_layout.addWidget(log_header)

        self._progress = ProgressPanel()
        bottom_layout.addWidget(self._progress)

        self._log = LogPanel()
        bottom_layout.addWidget(self._log, 1)

        # Set splitter proportions (60% tabs, 40% log)
        splitter.setSizes([600, 400])
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)

        # ── Connect signals ──────────────────────────────────────────────
        self._connect_signals()

        # Welcome message
        self._log.append(f"Welcome to Trik_Klip v{VERSION}\n", "head")
        self._log.append("Ready. Drop a video file or click Browse to begin.\n", "dim")

    def _setup_file_logger(self):
        log_dir = Path(__file__).parent.parent / "logs"
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / f"trik_klip_{datetime.now():%Y%m%d_%H%M%S}.log"
        self._file_logger = logging.getLogger("trik_klip")
        self._file_logger.setLevel(logging.DEBUG)
        fh = logging.FileHandler(str(log_file), encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        self._file_logger.addHandler(fh)

    def _connect_signals(self):
        s = self._signals

        # Log panel
        self._log.connect_signals(s)

        # Also log to file
        for sig_name in ("log", "ok", "err", "warn", "head", "dim"):
            getattr(s, sig_name).connect(
                lambda t, tag=sig_name: self._file_logger.info(
                    f"[{tag}] {t.rstrip()}"))

        # Progress bars
        self._progress.connect_signals(s)

        # Transcribe tab → run
        self._transcribe_tab.drop_zone.run_clicked.connect(self._on_run)
        self._transcribe_tab.drop_zone.cancel_clicked.connect(self._on_cancel)

        # Pipeline done → re-enable UI
        s.done.connect(self._on_done)

        # Results → populate extract tab
        s.results.connect(self._on_results)

        # Extract tab → extract worker
        self._extract_tab.extract_requested.connect(self._on_extract)

        # Extract done → populate slice tab
        s.extract_done.connect(self._on_extract_done)
        s.extract_progress.connect(
            lambda done, total, row_idx: self._extract_tab.remove_row(row_idx))

        # Slice tab → slice worker
        self._slice_tab.slice_requested.connect(self._on_slice)

        # Slice done → remove section
        s.slice_done.connect(
            lambda sid: self._slice_tab.remove_section_by_id(sid)
            if sid else None)

        # Premiere clipboard
        s.premiere_clipboard.connect(
            lambda text: QApplication.clipboard().setText(text))

        # Settings → update profile label on slice tab
        self._settings_tab.profile_changed.connect(self._on_profile_changed)

        # File selection → auto-fill extract output dir
        self._transcribe_tab.drop_zone.file_selected.connect(
            self._extract_tab.set_mp4_path)

    # ── Run pipeline ─────────────────────────────────────────────────────

    def _on_run(self):
        params = self._transcribe_tab.get_params()

        # Validation
        mode = params["mode"]
        if mode != 2 and not params["mp4_file"]:
            QMessageBox.warning(self, "Error", "No video file selected.")
            return
        if mode == 2 and not params["transcript_path"]:
            QMessageBox.warning(
                self, "Error",
                "Analyze mode requires a transcript. "
                "Load one in the File Paths section.")
            return

        # Get profile
        profile = self._settings_tab.get_active_profile()
        if mode != 1 and not profile:
            QMessageBox.warning(
                self, "Error",
                "No model profile configured. "
                "Go to Settings and create/apply a profile.")
            return

        # Add language from settings
        params["language"] = self._settings_tab.language_code

        self._transcribe_tab.drop_zone.set_running(True)
        self._worker = PipelineWorker(self._signals, params, profile or {})
        self._worker.start()

    def _on_cancel(self):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._signals.warn.emit("Cancelling...\n")

    def _on_done(self):
        self._transcribe_tab.drop_zone.set_running(False)
        self._worker = None

    def _on_results(self, clips):
        self._extract_tab.populate(clips)
        self._tabs.setCurrentIndex(1)  # Switch to Extract tab

    # ── Extract ──────────────────────────────────────────────────────────

    def _on_extract(self, selected, _mp4_unused, output_dir):
        mp4_path = self._transcribe_tab.drop_zone.path
        if not mp4_path:
            QMessageBox.warning(self, "Error", "No source video loaded.")
            return

        # Load transcript for per-clip slicing
        transcript_path = self._transcribe_tab.save_transcript_path.text()
        segments = None
        if transcript_path and os.path.exists(transcript_path):
            try:
                import clip_finder as cf
                segments = cf.load_transcript_from_json(transcript_path)
            except Exception:
                pass

        self._extract_worker = ExtractWorker(
            self._signals, selected, mp4_path, output_dir, segments)
        self._extract_worker.start()

    def _on_extract_done(self, clip_dirs):
        self._extract_worker = None
        if clip_dirs:
            self._slice_tab.populate_from_extraction(clip_dirs)
            self._tabs.setCurrentIndex(2)  # Switch to Slice tab
            self._signals.ok.emit(
                f"\n{len(clip_dirs)} clip(s) extracted. "
                "Switch to Slice tab to generate edits.\n")

    # ── Slice ────────────────────────────────────────────────────────────

    def _on_slice(self, clip_dir, notes, premiere, section_id):
        profile = self._settings_tab.get_active_profile()
        if not profile:
            QMessageBox.warning(
                self, "Error",
                "No model profile configured. Apply one in Settings.")
            return

        self._slice_worker = SliceWorker(
            self._signals, clip_dir, profile,
            editing_notes=notes, premiere=premiere,
            section_id=section_id)
        self._slice_worker.start()

    def _on_profile_changed(self, profile):
        from providers import PROVIDERS
        provider = profile.get("provider", "")
        label = PROVIDERS.get(provider, {}).get("label", provider)
        model = profile.get("model", "")
        text = f"Profile: {label} / {model}"
        self._slice_tab.set_profile_text(text)

    # ── Close ────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        # Cancel any running workers
        for worker in (self._worker, self._extract_worker, self._slice_worker):
            if worker and worker.isRunning():
                worker.cancel()
                worker.wait(2000)

        event.accept()
        # Force exit to kill any lingering subprocesses
        QApplication.quit()
        os._exit(0)
