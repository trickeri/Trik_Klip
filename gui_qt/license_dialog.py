"""License activation dialog — modal gate for packaged builds."""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton,
)
from PySide6.QtGui import QFont
from PySide6.QtCore import Qt, QTimer

from gui_qt import theme


class LicenseDialog(QDialog):
    """Modal dialog that verifies a Gumroad license key before the app starts."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Trik_Klip — License Activation")
        self.setFixedSize(480, 280)
        self.setStyleSheet(
            f"QDialog {{ background-color: {theme.BG}; }}"
        )
        self._verified = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 25, 30, 25)
        layout.setSpacing(12)

        # Title
        title = QLabel("Trik_Klip")
        title.setFont(QFont("Segoe UI", 18, QFont.Bold))
        title.setStyleSheet(f"color: {theme.ACCENT};")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # Instructions
        instructions = QLabel("Enter your license key to activate:")
        instructions.setAlignment(Qt.AlignCenter)
        instructions.setStyleSheet(f"color: {theme.DIM};")
        layout.addWidget(instructions)

        layout.addSpacing(8)

        # Key entry
        self._key_entry = QLineEdit()
        self._key_entry.setPlaceholderText("XXXXXXXX-XXXXXXXX-XXXXXXXX-XXXXXXXX")
        self._key_entry.setAlignment(Qt.AlignCenter)
        self._key_entry.returnPressed.connect(self._activate)
        layout.addWidget(self._key_entry)

        # Status
        self._status = QLabel("")
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        # Activate button
        self._activate_btn = QPushButton("Activate")
        self._activate_btn.setFixedHeight(36)
        self._activate_btn.clicked.connect(self._activate)
        layout.addWidget(self._activate_btn)

        layout.addStretch()

        # Try saved license first
        self._try_saved()

    @property
    def is_verified(self) -> bool:
        return self._verified

    def _try_saved(self):
        """Check for a previously saved license."""
        from licensing import load_saved_license, verify_license
        saved_key = load_saved_license()
        if saved_key:
            result = verify_license(saved_key, increment_uses=False)
            if result.valid:
                self._verified = True
                self.accept()

    def _activate(self):
        key = self._key_entry.text().strip()
        if not key:
            self._status.setText("Please enter a license key.")
            self._status.setStyleSheet(f"color: {theme.WARN};")
            return

        self._activate_btn.setEnabled(False)
        self._activate_btn.setText("Verifying...")
        self._status.setText("")

        from licensing import verify_license, save_license

        result = verify_license(key, increment_uses=True)

        if result.valid:
            save_license(key)
            self._verified = True
            self._status.setText("License activated!")
            self._status.setStyleSheet(f"color: {theme.SUCCESS};")
            QTimer.singleShot(600, self.accept)
        else:
            self._status.setText(result.message)
            self._status.setStyleSheet(f"color: {theme.ERR};")
            self._activate_btn.setEnabled(True)
            self._activate_btn.setText("Activate")
