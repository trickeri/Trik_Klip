"""Application entry point — QApplication setup, font loading, launch."""

import os
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase

from gui_qt import theme


def _load_fonts():
    """Load bundled custom fonts."""
    fonts_dir = Path(__file__).parent.parent / "fonts"
    if fonts_dir.is_dir():
        for ttf in fonts_dir.glob("*.ttf"):
            QFontDatabase.addApplicationFont(str(ttf))


def main():
    # PyInstaller windowed mode guards
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    elif hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    elif hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    app = QApplication(sys.argv)
    app.setApplicationName("Trik_Klip")
    app.setStyle("Fusion")  # Consistent cross-platform base style

    # Load fonts and apply global stylesheet
    _load_fonts()
    app.setStyleSheet(theme.STYLESHEET)

    # License gate (only in packaged builds)
    if getattr(sys, "frozen", False):
        from gui_qt.license_dialog import LicenseDialog
        dialog = LicenseDialog()
        if not dialog.is_verified:
            dialog.exec()
            if not dialog.is_verified:
                sys.exit(0)

    # Launch main window
    from gui_qt.main_window import MainWindow
    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
