"""About tab — profile image, social links, message."""

import webbrowser
from pathlib import Path

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from PySide6.QtGui import QPixmap, QFont, QCursor
from PySide6.QtCore import Qt

from gui_qt import theme


class _ClickableLabel(QLabel):
    """Label that opens a URL on click."""

    def __init__(self, text: str, url: str, parent=None):
        super().__init__(text, parent)
        self._url = url
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setStyleSheet(
            f"color: {theme.ACCENT}; font-size: 9pt; "
            "text-decoration: underline;")

    def mousePressEvent(self, event):
        webbrowser.open(self._url)


class AboutTab(QWidget):
    """Static about page with profile image and social links."""

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 30, 20, 20)
        layout.setAlignment(Qt.AlignCenter)

        # Profile image
        img_path = Path(__file__).parent.parent.parent / "assets" / "about_profile.png"
        if img_path.exists():
            pixmap = QPixmap(str(img_path)).scaled(
                180, 180, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            img_label = QLabel()
            img_label.setPixmap(pixmap)
            img_label.setAlignment(Qt.AlignCenter)
            layout.addWidget(img_label)
        layout.addSpacing(16)

        # App name
        title = QLabel("Trik_Klip")
        title.setFont(QFont("Segoe UI", 20, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(f"color: {theme.ACCENT};")
        layout.addWidget(title)

        subtitle = QLabel("Long-form stream to short-form clip finder")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet(f"color: {theme.DIM}; font-size: 10pt;")
        layout.addWidget(subtitle)

        layout.addSpacing(20)

        # Social links
        links_row = QHBoxLayout()
        links_row.setAlignment(Qt.AlignCenter)
        links_row.setSpacing(20)
        layout.addLayout(links_row)

        socials = [
            ("Twitter/X", "https://x.com/Trickeri_"),
            ("YouTube", "https://youtube.com/@Trickeri"),
            ("TikTok", "https://tiktok.com/@trickeri"),
            ("Twitch", "https://twitch.tv/trickeri"),
            ("GitHub", "https://github.com/trickeri"),
        ]
        for label, url in socials:
            links_row.addWidget(_ClickableLabel(label, url))

        layout.addSpacing(20)

        # Message
        msg = QLabel(
            "Built with love for content creators.\n"
            "Find the best moments in your streams automatically."
        )
        msg.setAlignment(Qt.AlignCenter)
        msg.setStyleSheet(f"color: {theme.DIM}; font-size: 9pt;")
        msg.setWordWrap(True)
        layout.addWidget(msg)

        layout.addStretch()
