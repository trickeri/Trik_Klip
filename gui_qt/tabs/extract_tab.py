"""Extract tab — clip selection panel with checkboxes, extraction trigger."""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QCheckBox, QScrollArea, QFileDialog, QFrame,
)
from PySide6.QtCore import Qt, Signal

from gui_qt import theme


class _ClipRow(QWidget):
    """Single clip row with checkbox, score, title, and timecodes."""

    def __init__(self, index: int, clip, parent=None):
        super().__init__(parent)
        self.clip = clip
        self.index = index

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(8)

        self.checkbox = QCheckBox()
        self.checkbox.setChecked(True)
        layout.addWidget(self.checkbox)

        score_lbl = QLabel(f"{clip.virality_score}/10")
        score_color = theme.SUCCESS if clip.virality_score >= 7 else (
            theme.WARN if clip.virality_score >= 4 else theme.ERR)
        score_lbl.setStyleSheet(
            f"color: {score_color}; font-weight: bold; font-size: 9pt;")
        score_lbl.setFixedWidth(40)
        layout.addWidget(score_lbl)

        title_lbl = QLabel(f"#{clip.rank} {clip.title}")
        title_lbl.setStyleSheet(f"color: {theme.TEXT}; font-size: 9pt;")
        layout.addWidget(title_lbl, 1)

        from clip_finder import fmt_time
        time_lbl = QLabel(
            f"{fmt_time(clip.clip_start)} - {fmt_time(clip.clip_end)}")
        time_lbl.setStyleSheet(f"color: {theme.DIM}; font-size: 8pt;")
        layout.addWidget(time_lbl)


class ExtractTab(QWidget):
    """Clip selection and extraction controls."""

    extract_requested = Signal(list, str, str)  # selected clips, mp4, output_dir

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # ── Header row ───────────────────────────────────────────────────
        header = QHBoxLayout()
        layout.addLayout(header)

        header.addWidget(QLabel("<b>Clip Selection</b>"))
        header.addStretch()

        self._count_label = QLabel("0 clips")
        self._count_label.setStyleSheet(f"color: {theme.DIM};")
        header.addWidget(self._count_label)

        select_all = QPushButton("Select All")
        select_all.setProperty("cssClass", "small")
        select_all.setFixedHeight(26)
        select_all.clicked.connect(lambda: self._set_all(True))
        header.addWidget(select_all)

        deselect_all = QPushButton("Deselect All")
        deselect_all.setProperty("cssClass", "small")
        deselect_all.setFixedHeight(26)
        deselect_all.clicked.connect(lambda: self._set_all(False))
        header.addWidget(deselect_all)

        # ── Scrollable clip list ─────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(200)
        layout.addWidget(scroll, 1)

        self._clip_container = QWidget()
        self._clip_layout = QVBoxLayout(self._clip_container)
        self._clip_layout.setContentsMargins(0, 0, 0, 0)
        self._clip_layout.setSpacing(2)
        self._clip_layout.addStretch()
        scroll.setWidget(self._clip_container)

        self._rows: list[_ClipRow] = []

        # ── Output dir ───────────────────────────────────────────────────
        dir_card = QFrame()
        dir_card.setProperty("cssClass", "card")
        dir_layout = QHBoxLayout(dir_card)
        dir_layout.setContentsMargins(12, 8, 12, 8)
        layout.addWidget(dir_card)

        dir_layout.addWidget(QLabel("Output Dir"))
        self._output_dir = QLineEdit("./clips")
        dir_layout.addWidget(self._output_dir, 1)
        browse = QPushButton("Browse")
        browse.setProperty("cssClass", "secondary")
        browse.setProperty("cssClass", "small")
        browse.setFixedHeight(28)
        browse.clicked.connect(self._browse_dir)
        dir_layout.addWidget(browse)

        # ── Extract button ───────────────────────────────────────────────
        self._extract_btn = QPushButton("Extract Selected Clips")
        self._extract_btn.setEnabled(False)
        self._extract_btn.clicked.connect(self._on_extract)
        layout.addWidget(self._extract_btn)

    def populate(self, clips: list):
        """Fill the clip list from analysis results."""
        self.clear()
        for i, clip in enumerate(clips):
            row = _ClipRow(i, clip)
            self._rows.append(row)
            # Insert before the stretch
            self._clip_layout.insertWidget(self._clip_layout.count() - 1, row)
        self._count_label.setText(f"{len(clips)} clips")
        self._extract_btn.setEnabled(len(clips) > 0)

    def clear(self):
        for row in self._rows:
            row.deleteLater()
        self._rows.clear()
        self._count_label.setText("0 clips")
        self._extract_btn.setEnabled(False)

    def remove_row(self, index: int):
        """Remove a clip row by index (after extraction)."""
        for row in self._rows:
            if row.index == index:
                row.deleteLater()
                self._rows.remove(row)
                break

    def get_selected(self) -> list:
        """Return list of (index, clip) for checked rows."""
        return [(r.index, r.clip) for r in self._rows if r.checkbox.isChecked()]

    def set_mp4_path(self, path: str):
        """Auto-fill output dir based on video path."""
        if path:
            from pathlib import Path
            self._output_dir.setText(
                str(Path(path).parent / (Path(path).stem + "_clips")))

    def _set_all(self, checked: bool):
        for row in self._rows:
            row.checkbox.setChecked(checked)

    def _browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select output directory")
        if d:
            self._output_dir.setText(d)

    def _on_extract(self):
        selected = self.get_selected()
        if selected:
            self.extract_requested.emit(
                selected, "", self._output_dir.text())
