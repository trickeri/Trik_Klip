"""Color palette and global QSS stylesheet for Trik_Klip."""

# ── Color palette (matches the original tkinter theme) ───────────────────────

BG       = "#1e1e2e"
PANEL    = "#252535"
CARD     = "#2a2a3e"
ACCENT   = "#7c3aed"
ACCENT2  = "#6d28d9"
TEXT     = "#e2e8f0"
DIM      = "#94a3b8"
SUCCESS  = "#22c55e"
ERR      = "#ef4444"
WARN     = "#f59e0b"
BORDER   = "#374151"
ENTRY_BG = "#1a1a2e"
SEP      = "#3f3f5a"

# ── Global stylesheet ────────────────────────────────────────────────────────

STYLESHEET = f"""
/* ── Base ─────────────────────────────────────────────── */
QMainWindow, QWidget {{
    background-color: {BG};
    color: {TEXT};
    font-family: "Segoe UI";
    font-size: 10pt;
}}

QLabel {{
    background: transparent;
    color: {TEXT};
}}

/* ── Tabs ─────────────────────────────────────────────── */
QTabWidget::pane {{
    background-color: {BG};
    border: none;
}}
QTabBar::tab {{
    background: {PANEL};
    color: {DIM};
    padding: 7px 18px;
    margin-right: 2px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    font-size: 10pt;
}}
QTabBar::tab:selected {{
    background: {CARD};
    color: {TEXT};
    font-weight: bold;
}}
QTabBar::tab:hover:!selected {{
    background: {CARD};
    color: {TEXT};
}}

/* ── Buttons ──────────────────────────────────────────── */
QPushButton {{
    background-color: {ACCENT};
    color: white;
    border: none;
    border-radius: 8px;
    padding: 8px 20px;
    font-weight: bold;
    font-size: 9pt;
}}
QPushButton:hover {{
    background-color: {ACCENT2};
}}
QPushButton:disabled {{
    background-color: {BORDER};
    color: {DIM};
}}
QPushButton[cssClass="secondary"] {{
    background-color: {CARD};
    color: {TEXT};
    border: 1px solid {BORDER};
}}
QPushButton[cssClass="secondary"]:hover {{
    background-color: {PANEL};
}}
QPushButton[cssClass="danger"] {{
    background-color: {ERR};
}}
QPushButton[cssClass="danger"]:hover {{
    background-color: #dc2626;
}}
QPushButton[cssClass="small"] {{
    padding: 4px 12px;
    font-size: 8pt;
    border-radius: 4px;
}}

/* ── Inputs ───────────────────────────────────────────── */
QLineEdit {{
    background-color: {ENTRY_BG};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 5px 8px;
    font-size: 9pt;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus {{
    border-color: {ACCENT};
}}

QTextEdit {{
    background-color: {ENTRY_BG};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px;
    font-size: 9pt;
    selection-background-color: {ACCENT};
}}

QSpinBox, QDoubleSpinBox {{
    background-color: {ENTRY_BG};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px 8px;
    font-size: 9pt;
}}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    background-color: {CARD};
    border: none;
    width: 16px;
}}

QComboBox {{
    background-color: {ENTRY_BG};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 5px 8px;
    font-size: 9pt;
    min-width: 80px;
}}
QComboBox::drop-down {{
    border: none;
    background: {ACCENT};
    border-top-right-radius: 6px;
    border-bottom-right-radius: 6px;
    width: 24px;
}}
QComboBox::down-arrow {{
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid white;
    margin-top: 2px;
}}
QComboBox QAbstractItemView {{
    background-color: {ENTRY_BG};
    color: {TEXT};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT};
    selection-color: white;
    outline: none;
}}
QComboBox QAbstractItemView::item {{
    padding: 5px 8px;
}}
QComboBox QAbstractItemView::item:hover {{
    background-color: {ACCENT};
    color: white;
}}

/* ── Checkboxes & Radio ───────────────────────────────── */
QCheckBox {{
    spacing: 8px;
    color: {TEXT};
    font-size: 9pt;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 2px solid {BORDER};
    border-radius: 4px;
    background: {ENTRY_BG};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}

QRadioButton {{
    spacing: 8px;
    color: {TEXT};
    font-size: 9pt;
}}
QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border: 2px solid {BORDER};
    border-radius: 9px;
    background: {ENTRY_BG};
}}
QRadioButton::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}

/* ── Progress bars ────────────────────────────────────── */
QProgressBar {{
    background-color: {ENTRY_BG};
    border: none;
    border-radius: 4px;
    text-align: center;
    color: {TEXT};
    font-size: 8pt;
    max-height: 18px;
}}
QProgressBar::chunk {{
    background-color: {ACCENT};
    border-radius: 4px;
}}

/* ── Scroll bars ──────────────────────────────────────── */
QScrollBar:vertical {{
    background: {BG};
    width: 10px;
    margin: 0;
    border: none;
}}
QScrollBar::handle:vertical {{
    background: {ACCENT};
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: #9b5de5;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: none;
}}

QScrollBar:horizontal {{
    background: {BG};
    height: 10px;
    margin: 0;
    border: none;
}}
QScrollBar::handle:horizontal {{
    background: {ACCENT};
    border-radius: 4px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{
    background: #9b5de5;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* ── Scroll area ──────────────────────────────────────── */
QScrollArea {{
    background-color: {BG};
    border: none;
}}

/* ── Splitter ─────────────────────────────────────────── */
QSplitter::handle {{
    background-color: {SEP};
    height: 3px;
}}
QSplitter::handle:hover {{
    background-color: {ACCENT};
}}

/* ── Cards (custom property) ──────────────────────────── */
QFrame[cssClass="card"] {{
    background-color: {CARD};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 12px;
}}

QFrame[cssClass="header"] {{
    background-color: {ACCENT};
    border: none;
}}

/* ── Separator lines ──────────────────────────────────── */
QFrame[cssClass="separator"] {{
    background-color: {SEP};
    max-height: 1px;
    min-height: 1px;
}}
"""
