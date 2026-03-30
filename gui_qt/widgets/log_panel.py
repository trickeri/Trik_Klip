"""Output log panel with colored message formatting."""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QTextEdit
from PySide6.QtGui import QTextCharFormat, QColor, QFont, QTextCursor
from PySide6.QtCore import Qt

from gui_qt import theme


class LogPanel(QWidget):
    """Read-only text log with color-tagged messages and clear button."""

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Log text area
        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setFont(QFont("Consolas", 9))
        self._text.setStyleSheet(
            f"QTextEdit {{ background-color: {theme.ENTRY_BG}; "
            f"color: {theme.TEXT}; border: none; padding: 6px; }}"
        )
        layout.addWidget(self._text)

        # Clear button
        clear_btn = QPushButton("Clear Log")
        clear_btn.setProperty("cssClass", "secondary")
        clear_btn.setProperty("cssClass", "small")
        clear_btn.setFixedHeight(28)
        clear_btn.clicked.connect(self._text.clear)
        layout.addWidget(clear_btn, alignment=Qt.AlignRight)

        # Pre-build text formats for each tag
        self._formats = {
            "log":  self._make_fmt(theme.TEXT),
            "ok":   self._make_fmt(theme.SUCCESS),
            "err":  self._make_fmt(theme.ERR),
            "warn": self._make_fmt(theme.WARN),
            "head": self._make_fmt(theme.ACCENT, bold=True),
            "dim":  self._make_fmt(theme.DIM),
        }

    @staticmethod
    def _make_fmt(color: str, bold: bool = False) -> QTextCharFormat:
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        if bold:
            fmt.setFontWeight(QFont.Bold)
        return fmt

    def append(self, text: str, tag: str = "log"):
        """Append colored text to the log."""
        fmt = self._formats.get(tag, self._formats["log"])
        cursor = self._text.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(text, fmt)
        self._text.setTextCursor(cursor)
        self._text.ensureCursorVisible()

    def connect_signals(self, signals):
        """Wire WorkerSignals to this log panel."""
        signals.log.connect(lambda t: self.append(t, "log"))
        signals.ok.connect(lambda t: self.append(t, "ok"))
        signals.err.connect(lambda t: self.append(t, "err"))
        signals.warn.connect(lambda t: self.append(t, "warn"))
        signals.head.connect(lambda t: self.append(t, "head"))
        signals.dim.connect(lambda t: self.append(t, "dim"))
