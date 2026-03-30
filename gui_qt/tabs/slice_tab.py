"""Slice tab — dynamic clip sections for editing/slicing."""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QCheckBox, QScrollArea, QLabel,
)
from PySide6.QtCore import Signal

from gui_qt import theme
from gui_qt.widgets.clip_section import ClipSection


class SliceTab(QWidget):
    """Tab with permanent + dynamic clip sections for slice generation."""

    slice_requested    = Signal(str, str, bool, int)  # dir, notes, premiere, section_id
    premiere_requested = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # Permanent section
        self._permanent = ClipSection(is_permanent=True)
        self._permanent.slice_requested.connect(
            lambda d, n, p: self.slice_requested.emit(
                d, n, p, self._permanent.section_id))
        self._permanent.premiere_requested.connect(self.premiere_requested)
        layout.addWidget(self._permanent)

        # Auto-remove checkbox
        self._auto_remove = QCheckBox("Auto-remove sections after slicing")
        self._auto_remove.setChecked(True)
        layout.addWidget(self._auto_remove)

        # Dynamic sections container (scrollable)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        layout.addWidget(scroll, 1)

        self._container = QWidget()
        self._container_layout = QVBoxLayout(self._container)
        self._container_layout.setContentsMargins(0, 0, 0, 0)
        self._container_layout.setSpacing(8)
        self._container_layout.addStretch()
        scroll.setWidget(self._container)

        self._sections: list[ClipSection] = []

    def add_section(self, clip_dir: str) -> ClipSection:
        """Add a dynamic clip section for an extracted clip folder."""
        section = ClipSection(clip_dir=clip_dir)
        section.slice_requested.connect(
            lambda d, n, p: self.slice_requested.emit(
                d, n, p, section.section_id))
        section.premiere_requested.connect(self.premiere_requested)
        section.remove_requested.connect(self._remove_section)
        self._sections.append(section)
        self._container_layout.insertWidget(
            self._container_layout.count() - 1, section)
        return section

    def remove_section_by_id(self, section_id: int):
        """Remove a section after slicing completes (if auto-remove on)."""
        if self._auto_remove.isChecked():
            self._remove_section(section_id)

    def _remove_section(self, section_id: int):
        for sec in self._sections:
            if sec.section_id == section_id:
                sec.deleteLater()
                self._sections.remove(sec)
                break

    def populate_from_extraction(self, clip_dirs: list[str]):
        """Add sections for each extracted clip directory."""
        for d in clip_dirs:
            self.add_section(d)

    def set_profile_text(self, text: str):
        """Update profile label on all sections."""
        self._permanent.set_profile_text(text)
        for sec in self._sections:
            sec.set_profile_text(text)
