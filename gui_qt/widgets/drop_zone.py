"""Drag-and-drop file input zone with browse button."""

from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QFileDialog,
    QLineEdit,
)
from PySide6.QtCore import Qt, Signal

from gui_qt import theme


class DropZone(QWidget):
    """File drop zone with path display, browse, run, and cancel buttons."""

    file_selected = Signal(str)
    run_clicked   = Signal()
    cancel_clicked = Signal()

    _EXTENSIONS = (".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".ts")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMinimumHeight(80)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # Main row: drop area + buttons
        row = QHBoxLayout()
        row.setSpacing(8)
        outer.addLayout(row)

        # Left: drop label + path
        left = QVBoxLayout()
        left.setSpacing(4)
        row.addLayout(left, 1)

        self._drop_label = QLabel("Drop MP4 here or click Browse")
        self._drop_label.setAlignment(Qt.AlignCenter)
        self._drop_label.setStyleSheet(
            f"QLabel {{ background-color: {theme.CARD}; "
            f"border: 2px dashed {theme.BORDER}; border-radius: 8px; "
            f"color: {theme.DIM}; padding: 16px; font-size: 10pt; }}"
        )
        self._drop_label.setMinimumHeight(54)
        left.addWidget(self._drop_label)

        self._path_entry = QLineEdit()
        self._path_entry.setPlaceholderText("No file selected")
        self._path_entry.setReadOnly(True)
        left.addWidget(self._path_entry)

        # Right: buttons
        btn_col = QVBoxLayout()
        btn_col.setSpacing(6)
        row.addLayout(btn_col)

        self._browse_btn = QPushButton("Browse")
        self._browse_btn.setProperty("cssClass", "secondary")
        self._browse_btn.clicked.connect(self._browse)
        btn_col.addWidget(self._browse_btn)

        self._run_btn = QPushButton("Run")
        self._run_btn.clicked.connect(self.run_clicked)
        btn_col.addWidget(self._run_btn)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setProperty("cssClass", "danger")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self.cancel_clicked)
        btn_col.addWidget(self._cancel_btn)

    @property
    def path(self) -> str:
        return self._path_entry.text()

    def set_path(self, path: str):
        self._path_entry.setText(path)
        name = Path(path).name if path else "No file selected"
        self._drop_label.setText(name)

    def set_running(self, running: bool):
        self._run_btn.setEnabled(not running)
        self._browse_btn.setEnabled(not running)
        self._cancel_btn.setEnabled(running)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select video file", "",
            "Video files (*.mp4 *.mkv *.mov *.avi *.webm *.flv *.ts);;All files (*)"
        )
        if path:
            self.set_path(path)
            self.file_selected.emit(path)

    # ── Drag and drop ────────────────────────────────────────────────────

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.toLocalFile().lower().endswith(self._EXTENSIONS):
                    event.acceptProposedAction()
                    self._drop_label.setStyleSheet(
                        f"QLabel {{ background-color: {theme.CARD}; "
                        f"border: 2px dashed {theme.ACCENT}; border-radius: 8px; "
                        f"color: {theme.ACCENT}; padding: 16px; font-size: 10pt; }}"
                    )
                    return
        event.ignore()

    def dragLeaveEvent(self, event):
        self._drop_label.setStyleSheet(
            f"QLabel {{ background-color: {theme.CARD}; "
            f"border: 2px dashed {theme.BORDER}; border-radius: 8px; "
            f"color: {theme.DIM}; padding: 16px; font-size: 10pt; }}"
        )

    def dropEvent(self, event):
        self.dragLeaveEvent(event)
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(self._EXTENSIONS):
                self.set_path(path)
                self.file_selected.emit(path)
                return
