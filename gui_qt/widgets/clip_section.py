"""Reusable clip section widget for the Slice tab."""

from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTextEdit, QFileDialog,
)
from PySide6.QtCore import Signal

from gui_qt import theme


class ClipSection(QWidget):
    """A single clip folder section with editing controls."""

    slice_requested    = Signal(str, str, bool)   # clip_dir, notes, premiere
    premiere_requested = Signal(str, str)          # clip_dir, notes
    remove_requested   = Signal(int)               # section_id

    _next_id = 0

    def __init__(self, clip_dir: str = "", is_permanent: bool = False,
                 parent=None):
        super().__init__(parent)
        ClipSection._next_id += 1
        self.section_id = ClipSection._next_id
        self._is_permanent = is_permanent

        self.setStyleSheet(
            f"ClipSection {{ background-color: {theme.CARD}; "
            f"border: 1px solid {theme.BORDER}; border-radius: 8px; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        # Header: title + close button
        header = QHBoxLayout()
        header.setSpacing(8)
        layout.addLayout(header)

        title = "Generate Slices from Clip" if is_permanent else "Extracted Clip"
        self._title_label = QLabel(f"<b>{title}</b>")
        header.addWidget(self._title_label, 1)

        if not is_permanent:
            close_btn = QPushButton("x")
            close_btn.setFixedSize(24, 24)
            close_btn.setProperty("cssClass", "small")
            close_btn.clicked.connect(
                lambda: self.remove_requested.emit(self.section_id))
            header.addWidget(close_btn)

        # Clip folder path
        path_row = QHBoxLayout()
        path_row.setSpacing(6)
        layout.addLayout(path_row)

        self._dir_entry = QLineEdit(clip_dir)
        self._dir_entry.setPlaceholderText("Path to clip folder...")
        self._dir_entry.textChanged.connect(self._on_dir_changed)
        path_row.addWidget(self._dir_entry, 1)

        browse_btn = QPushButton("Browse")
        browse_btn.setProperty("cssClass", "secondary")
        browse_btn.setProperty("cssClass", "small")
        browse_btn.setFixedHeight(28)
        browse_btn.clicked.connect(self._browse)
        path_row.addWidget(browse_btn)

        # Profile status
        self._profile_label = QLabel("")
        self._profile_label.setStyleSheet(f"color: {theme.DIM}; font-size: 8pt;")
        layout.addWidget(self._profile_label)

        # Files detected
        self._files_label = QLabel("")
        self._files_label.setStyleSheet(f"color: {theme.DIM}; font-size: 8pt;")
        self._files_label.setWordWrap(True)
        layout.addWidget(self._files_label)

        # Editing notes
        notes_label = QLabel("Editing Notes (optional)")
        notes_label.setStyleSheet(f"color: {theme.DIM}; font-size: 8pt;")
        layout.addWidget(notes_label)

        self._notes = QTextEdit()
        self._notes.setPlaceholderText(
            "Add custom editing instructions here (e.g., 'focus on funny moments', "
            "'keep the energy high', 'include the part where they react to...')")
        self._notes.setMaximumHeight(80)
        layout.addWidget(self._notes)

        # Buttons row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        layout.addLayout(btn_row)

        self._slice_premiere_btn = QPushButton("Slice + Premiere")
        self._slice_premiere_btn.clicked.connect(
            lambda: self.slice_requested.emit(
                self._dir_entry.text(), self._notes.toPlainText(), True))
        btn_row.addWidget(self._slice_premiere_btn)

        self._slice_btn = QPushButton("Slice Only")
        self._slice_btn.setProperty("cssClass", "secondary")
        self._slice_btn.clicked.connect(
            lambda: self.slice_requested.emit(
                self._dir_entry.text(), self._notes.toPlainText(), False))
        btn_row.addWidget(self._slice_btn)

        self._premiere_btn = QPushButton("Premiere Only")
        self._premiere_btn.setProperty("cssClass", "secondary")
        self._premiere_btn.clicked.connect(
            lambda: self.premiere_requested.emit(
                self._dir_entry.text(), self._notes.toPlainText()))
        btn_row.addWidget(self._premiere_btn)

        # Scan initial dir
        if clip_dir:
            self._on_dir_changed(clip_dir)

    @property
    def clip_dir(self) -> str:
        return self._dir_entry.text()

    def set_profile_text(self, text: str):
        self._profile_label.setText(text)

    def set_enabled_buttons(self, enabled: bool):
        self._slice_premiere_btn.setEnabled(enabled)
        self._slice_btn.setEnabled(enabled)
        self._premiere_btn.setEnabled(enabled)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Select clip folder")
        if d:
            self._dir_entry.setText(d)

    def _on_dir_changed(self, path: str):
        """Scan folder and list detected files."""
        p = Path(path)
        if not p.is_dir():
            self._files_label.setText("")
            return
        mp4s = [f.name for f in sorted(p.glob("*.mp4"))
                if not f.name.startswith("slice_")]
        prompts = [f.name for f in sorted(p.glob("*_editing_prompt.txt"))]
        transcripts = [f.name for f in sorted(p.glob("*_transcript.json"))]
        parts = []
        if mp4s:
            parts.append(f"Video: {mp4s[0]}")
        if prompts:
            parts.append(f"Prompt: {prompts[0]}")
        if transcripts:
            parts.append(f"Transcript: {transcripts[0]}")
        self._files_label.setText(" | ".join(parts) if parts else "No files found")
