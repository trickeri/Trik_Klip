"""Transcribe tab — drop zone, options, custom prompts, file paths, run mode."""

from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QSpinBox, QDoubleSpinBox, QLineEdit, QPushButton, QRadioButton,
    QButtonGroup, QFileDialog, QFrame,
)
from PySide6.QtCore import Qt, Signal

from gui_qt import theme
from gui_qt.widgets.drop_zone import DropZone


def _card(layout_cls=QVBoxLayout):
    """Create a styled card frame with a layout."""
    frame = QFrame()
    frame.setProperty("cssClass", "card")
    lay = layout_cls(frame)
    lay.setContentsMargins(12, 10, 12, 10)
    lay.setSpacing(6)
    return frame, lay


def _section_label(text: str) -> QLabel:
    lbl = QLabel(f"<b>{text}</b>")
    lbl.setStyleSheet(f"color: {theme.TEXT}; font-size: 10pt;")
    return lbl


class TranscribeTab(QWidget):
    """The primary tab: file input, options, run controls."""

    run_requested = Signal(dict)   # emits all params as a dict

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # ── Drop zone ────────────────────────────────────────────────────
        self.drop_zone = DropZone()
        self.drop_zone.file_selected.connect(self._on_file_selected)
        layout.addWidget(self.drop_zone)

        # ── Options card ─────────────────────────────────────────────────
        card, clayout = _card()
        layout.addWidget(card)

        clayout.addWidget(_section_label("Options"))

        opts_grid = QHBoxLayout()
        opts_grid.setSpacing(16)
        clayout.addLayout(opts_grid)

        # Whisper model
        col1 = QVBoxLayout()
        col1.addWidget(QLabel("Whisper Model"))
        self.whisper_model = QComboBox()
        self.whisper_model.addItems(["tiny", "base", "small", "medium", "large"])
        self.whisper_model.setCurrentText("base")
        col1.addWidget(self.whisper_model)
        opts_grid.addLayout(col1)

        # Max clips
        col2 = QVBoxLayout()
        col2.addWidget(QLabel("Max Clips"))
        self.top_n = QSpinBox()
        self.top_n.setRange(1, 50)
        self.top_n.setValue(10)
        col2.addWidget(self.top_n)
        opts_grid.addLayout(col2)

        # Window minutes
        col3 = QVBoxLayout()
        col3.addWidget(QLabel("Window (min)"))
        self.window_minutes = QSpinBox()
        self.window_minutes.setRange(1, 30)
        self.window_minutes.setValue(5)
        col3.addWidget(self.window_minutes)
        opts_grid.addLayout(col3)

        # Padding
        col4 = QVBoxLayout()
        col4.addWidget(QLabel("Padding (min)"))
        self.padding_minutes = QDoubleSpinBox()
        self.padding_minutes.setRange(0, 10)
        self.padding_minutes.setValue(3.0)
        self.padding_minutes.setSingleStep(0.5)
        col4.addWidget(self.padding_minutes)
        opts_grid.addLayout(col4)

        # Audio track
        col5 = QVBoxLayout()
        col5.addWidget(QLabel("Audio Track"))
        self.audio_track = QSpinBox()
        self.audio_track.setRange(-1, 20)
        self.audio_track.setValue(-1)
        self.audio_track.setSpecialValueText("auto")
        col5.addWidget(self.audio_track)
        opts_grid.addLayout(col5)

        # ── Custom search prompts ────────────────────────────────────────
        prompt_card, playout = _card()
        layout.addWidget(prompt_card)

        prompt_header = QHBoxLayout()
        playout.addLayout(prompt_header)
        prompt_header.addWidget(_section_label("Custom Search Prompts"))
        prompt_header.addStretch()

        add_prompt_btn = QPushButton("+ Add")
        add_prompt_btn.setProperty("cssClass", "small")
        add_prompt_btn.setFixedHeight(26)
        add_prompt_btn.clicked.connect(self._add_prompt_row)
        prompt_header.addWidget(add_prompt_btn)

        self._prompt_container = QVBoxLayout()
        self._prompt_container.setSpacing(4)
        playout.addLayout(self._prompt_container)
        self._prompt_entries: list[QLineEdit] = []

        hint = QLabel("Tell the AI what specific things to look for "
                       "(e.g., 'funny reactions', 'advice moments')")
        hint.setStyleSheet(f"color: {theme.DIM}; font-size: 8pt;")
        hint.setWordWrap(True)
        playout.addWidget(hint)

        # ── File paths card ──────────────────────────────────────────────
        path_card, path_layout = _card()
        layout.addWidget(path_card)

        path_layout.addWidget(_section_label("File Paths"))

        # Transcript load
        t_row = QHBoxLayout()
        t_row.addWidget(QLabel("Load Transcript"))
        self.transcript_path = QLineEdit()
        self.transcript_path.setPlaceholderText("(optional) existing transcript JSON")
        t_row.addWidget(self.transcript_path, 1)
        t_browse = QPushButton("Browse")
        t_browse.setProperty("cssClass", "secondary")
        t_browse.setProperty("cssClass", "small")
        t_browse.setFixedHeight(28)
        t_browse.clicked.connect(self._browse_transcript)
        t_row.addWidget(t_browse)
        path_layout.addLayout(t_row)

        # Save transcript
        s_row = QHBoxLayout()
        s_row.addWidget(QLabel("Save Transcript"))
        self.save_transcript_path = QLineEdit()
        self.save_transcript_path.setPlaceholderText("(auto-filled from video)")
        s_row.addWidget(self.save_transcript_path, 1)
        path_layout.addLayout(s_row)

        # Output JSON
        o_row = QHBoxLayout()
        o_row.addWidget(QLabel("Output JSON"))
        self.output_json_path = QLineEdit()
        self.output_json_path.setPlaceholderText("(auto-filled from video)")
        o_row.addWidget(self.output_json_path, 1)
        path_layout.addLayout(o_row)

        # ── Run mode ─────────────────────────────────────────────────────
        mode_card, mode_layout = _card()
        layout.addWidget(mode_card)

        mode_layout.addWidget(_section_label("Run Mode"))
        mode_row = QHBoxLayout()
        mode_layout.addLayout(mode_row)

        self._mode_group = QButtonGroup(self)
        self.mode_full = QRadioButton("Full Pipeline")
        self.mode_full.setChecked(True)
        self.mode_transcribe = QRadioButton("Transcribe Only")
        self.mode_analyze = QRadioButton("Analyze Only")
        self._mode_group.addButton(self.mode_full, 0)
        self._mode_group.addButton(self.mode_transcribe, 1)
        self._mode_group.addButton(self.mode_analyze, 2)
        mode_row.addWidget(self.mode_full)
        mode_row.addWidget(self.mode_transcribe)
        mode_row.addWidget(self.mode_analyze)
        mode_row.addStretch()

        layout.addStretch()

    def get_params(self) -> dict:
        """Collect all parameters into a dict for the worker."""
        audio_track = self.audio_track.value()
        return {
            "mp4_file": self.drop_zone.path,
            "whisper_model": self.whisper_model.currentText(),
            "top_n": self.top_n.value(),
            "window_minutes": self.window_minutes.value(),
            "padding_minutes": self.padding_minutes.value(),
            "audio_track": audio_track if audio_track >= 0 else None,
            "transcript_path": self.transcript_path.text() or None,
            "save_transcript_path": self.save_transcript_path.text() or None,
            "output_json_path": self.output_json_path.text() or None,
            "custom_prompts": [e.text() for e in self._prompt_entries
                               if e.text().strip()],
            "mode": self._mode_group.checkedId(),  # 0=full, 1=transcribe, 2=analyze
        }

    def _on_file_selected(self, path: str):
        stem = Path(path).stem
        parent = str(Path(path).parent)
        if not self.save_transcript_path.text():
            self.save_transcript_path.setText(f"{parent}/{stem}_transcript.json")
        if not self.output_json_path.text():
            self.output_json_path.setText(f"{parent}/{stem}_clips.json")

    def _browse_transcript(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select transcript JSON", "",
            "JSON files (*.json);;All files (*)")
        if path:
            self.transcript_path.setText(path)

    def _add_prompt_row(self):
        row = QHBoxLayout()
        entry = QLineEdit()
        entry.setPlaceholderText("What to look for...")
        row.addWidget(entry, 1)

        remove_btn = QPushButton("x")
        remove_btn.setFixedSize(24, 24)
        remove_btn.setProperty("cssClass", "small")
        remove_btn.clicked.connect(lambda: self._remove_prompt_row(row, entry))
        row.addWidget(remove_btn)

        self._prompt_container.addLayout(row)
        self._prompt_entries.append(entry)
        entry.setFocus()

    def _remove_prompt_row(self, layout_item, entry):
        self._prompt_entries.remove(entry)
        while layout_item.count():
            w = layout_item.takeAt(0).widget()
            if w:
                w.deleteLater()
        self._prompt_container.removeItem(layout_item)
