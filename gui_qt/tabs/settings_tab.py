"""Settings tab — profiles, language, model configuration."""

import json
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QLineEdit, QPushButton, QFrame, QMessageBox,
)
from PySide6.QtCore import Signal

from gui_qt import theme

PROFILES_FILE = "streamclipper_profiles.json"

# Language codes (subset)
LANGUAGES = [
    ("English", "en"), ("Spanish", "es"), ("French", "fr"),
    ("German", "de"), ("Italian", "it"), ("Portuguese", "pt"),
    ("Russian", "ru"), ("Japanese", "ja"), ("Korean", "ko"),
    ("Chinese", "zh"), ("Arabic", "ar"), ("Hindi", "hi"),
    ("Dutch", "nl"), ("Polish", "pl"), ("Turkish", "tr"),
    ("Swedish", "sv"), ("Thai", "th"), ("Vietnamese", "vi"),
]


def _card():
    frame = QFrame()
    frame.setProperty("cssClass", "card")
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(12, 10, 12, 10)
    lay.setSpacing(6)
    return frame, lay


def _section_label(text: str) -> QLabel:
    lbl = QLabel(f"<b>{text}</b>")
    lbl.setStyleSheet(f"color: {theme.TEXT}; font-size: 10pt;")
    return lbl


class SettingsTab(QWidget):
    """Profile management, language, and model configuration."""

    profile_changed = Signal(dict)  # emits active profile dict

    def __init__(self, parent=None):
        super().__init__(parent)
        self._profiles: dict[str, dict] = {}
        self._show_key = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # ── Language section ─────────────────────────────────────────────
        lang_card, ll = _card()
        layout.addWidget(lang_card)
        ll.addWidget(_section_label("Transcription Language"))

        lang_row = QHBoxLayout()
        ll.addLayout(lang_row)
        self.language_combo = QComboBox()
        for name, code in LANGUAGES:
            self.language_combo.addItem(f"{name} ({code})", code)
        self.language_combo.setCurrentIndex(0)
        lang_row.addWidget(self.language_combo, 1)

        self._lang_code_label = QLabel("en")
        self._lang_code_label.setStyleSheet(
            f"color: {theme.DIM}; font-size: 9pt;")
        lang_row.addWidget(self._lang_code_label)
        self.language_combo.currentIndexChanged.connect(self._on_lang_changed)

        # ── Active profile section ───────────────────────────────────────
        prof_card, pl = _card()
        layout.addWidget(prof_card)
        pl.addWidget(_section_label("Active Model Profile"))

        active_row = QHBoxLayout()
        pl.addLayout(active_row)

        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(200)
        self.profile_combo.currentTextChanged.connect(self._on_profile_selected)
        active_row.addWidget(self.profile_combo, 1)

        self._apply_btn = QPushButton("Apply")
        self._apply_btn.clicked.connect(self._apply_profile)
        active_row.addWidget(self._apply_btn)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet(f"color: {theme.DIM}; font-size: 8pt;")
        pl.addWidget(self._status_label)

        # ── Profile editor ───────────────────────────────────────────────
        edit_card, el = _card()
        layout.addWidget(edit_card)
        el.addWidget(_section_label("Profile Editor"))

        # Name
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Name"))
        self._prof_name = QLineEdit()
        self._prof_name.setPlaceholderText("Profile name")
        name_row.addWidget(self._prof_name, 1)
        el.addLayout(name_row)

        # Provider
        prov_row = QHBoxLayout()
        prov_row.addWidget(QLabel("Provider"))
        self._prof_provider = QComboBox()
        from providers import PROVIDERS
        for key, info in PROVIDERS.items():
            self._prof_provider.addItem(info["label"], key)
        self._prof_provider.currentIndexChanged.connect(self._on_provider_changed)
        prov_row.addWidget(self._prof_provider, 1)
        el.addLayout(prov_row)

        # Server URL (ollama only)
        self._url_row = QWidget()
        url_layout = QHBoxLayout(self._url_row)
        url_layout.setContentsMargins(0, 0, 0, 0)
        url_layout.addWidget(QLabel("Server URL"))
        self._prof_url = QLineEdit("http://localhost:11434")
        url_layout.addWidget(self._prof_url, 1)
        el.addWidget(self._url_row)
        self._url_row.setVisible(False)

        # API key
        self._key_row = QWidget()
        key_layout = QHBoxLayout(self._key_row)
        key_layout.setContentsMargins(0, 0, 0, 0)
        key_layout.addWidget(QLabel("API Key"))
        self._prof_key = QLineEdit()
        self._prof_key.setEchoMode(QLineEdit.Password)
        self._prof_key.setPlaceholderText("Enter API key")
        key_layout.addWidget(self._prof_key, 1)
        self._show_key_btn = QPushButton("Show")
        self._show_key_btn.setProperty("cssClass", "small")
        self._show_key_btn.setFixedHeight(28)
        self._show_key_btn.clicked.connect(self._toggle_key_visibility)
        key_layout.addWidget(self._show_key_btn)
        el.addWidget(self._key_row)

        self._key_hint = QLabel("")
        self._key_hint.setStyleSheet(f"color: {theme.DIM}; font-size: 8pt;")
        self._key_hint.setWordWrap(True)
        el.addWidget(self._key_hint)

        # Model
        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("Model"))
        self._prof_model = QComboBox()
        self._prof_model.setEditable(True)
        model_row.addWidget(self._prof_model, 1)
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setProperty("cssClass", "small")
        self._refresh_btn.setFixedHeight(28)
        self._refresh_btn.clicked.connect(self._refresh_models)
        model_row.addWidget(self._refresh_btn)
        el.addLayout(model_row)

        # Save / Delete buttons
        btn_row = QHBoxLayout()
        el.addLayout(btn_row)

        save_btn = QPushButton("Save Profile")
        save_btn.clicked.connect(self._save_profile)
        btn_row.addWidget(save_btn)

        delete_btn = QPushButton("Delete Profile")
        delete_btn.setProperty("cssClass", "danger")
        delete_btn.clicked.connect(self._delete_profile)
        btn_row.addWidget(delete_btn)

        btn_row.addStretch()

        layout.addStretch()

        # Load profiles on init
        self._load_profiles()
        self._on_provider_changed()

    @property
    def language_code(self) -> str:
        return self.language_combo.currentData() or "en"

    def get_active_profile(self) -> dict | None:
        name = self.profile_combo.currentText()
        return self._profiles.get(name)

    def _on_lang_changed(self):
        code = self.language_combo.currentData() or "en"
        self._lang_code_label.setText(code)

    def _on_provider_changed(self):
        provider_key = self._prof_provider.currentData()
        from providers import PROVIDERS
        info = PROVIDERS.get(provider_key, {})

        is_ollama = provider_key == "ollama"
        is_claude_code = provider_key == "claude_code"
        needs_key = not is_ollama and not is_claude_code

        self._url_row.setVisible(is_ollama)
        self._key_row.setVisible(needs_key)
        self._key_hint.setVisible(needs_key)

        if needs_key:
            env_key = info.get("env_key", "")
            self._key_hint.setText(f"Set via env var: {env_key}")

        # Update model list
        self._prof_model.clear()
        self._prof_model.addItems(info.get("models", []))
        default = info.get("default_model", "")
        if default:
            idx = self._prof_model.findText(default)
            if idx >= 0:
                self._prof_model.setCurrentIndex(idx)

    def _on_profile_selected(self, name: str):
        prof = self._profiles.get(name, {})
        if not prof:
            return
        self._prof_name.setText(name)

        # Set provider combo
        provider = prof.get("provider", "anthropic")
        for i in range(self._prof_provider.count()):
            if self._prof_provider.itemData(i) == provider:
                self._prof_provider.setCurrentIndex(i)
                break

        self._prof_key.setText(prof.get("api_key", ""))
        self._prof_url.setText(prof.get("base_url", "http://localhost:11434"))

        model = prof.get("model", "")
        if model:
            idx = self._prof_model.findText(model)
            if idx >= 0:
                self._prof_model.setCurrentIndex(idx)
            else:
                self._prof_model.setCurrentText(model)

    def _apply_profile(self):
        prof = self.get_active_profile()
        if prof:
            self._status_label.setText(
                f"Active: {self.profile_combo.currentText()}")
            self._status_label.setStyleSheet(
                f"color: {theme.SUCCESS}; font-size: 8pt;")
            self.profile_changed.emit(prof)

    def _save_profile(self):
        name = self._prof_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Error", "Profile name is required.")
            return

        self._profiles[name] = {
            "provider": self._prof_provider.currentData(),
            "api_key": self._prof_key.text(),
            "model": self._prof_model.currentText(),
            "base_url": self._prof_url.text(),
        }
        self._save_profiles_file()
        self._refresh_profile_combo()
        self.profile_combo.setCurrentText(name)
        self._status_label.setText(f"Saved: {name}")
        self._status_label.setStyleSheet(
            f"color: {theme.SUCCESS}; font-size: 8pt;")

    def _delete_profile(self):
        name = self.profile_combo.currentText()
        if name and name in self._profiles:
            reply = QMessageBox.question(
                self, "Delete Profile",
                f"Delete profile '{name}'?",
                QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                del self._profiles[name]
                self._save_profiles_file()
                self._refresh_profile_combo()

    def _toggle_key_visibility(self):
        self._show_key = not self._show_key
        self._prof_key.setEchoMode(
            QLineEdit.Normal if self._show_key else QLineEdit.Password)
        self._show_key_btn.setText("Hide" if self._show_key else "Show")

    def _refresh_models(self):
        provider_key = self._prof_provider.currentData()
        api_key = self._prof_key.text()
        try:
            if provider_key == "ollama":
                from providers import list_ollama_models
                models = list_ollama_models(self._prof_url.text())
            else:
                from providers import refresh_provider_models
                models = refresh_provider_models(provider_key, api_key)
            if models:
                self._prof_model.clear()
                self._prof_model.addItems(models)
        except Exception as exc:
            QMessageBox.warning(self, "Error", f"Could not refresh models: {exc}")

    def _load_profiles(self):
        p = Path(PROFILES_FILE)
        if p.exists():
            try:
                self._profiles = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                self._profiles = {}
        self._refresh_profile_combo()

    def _save_profiles_file(self):
        Path(PROFILES_FILE).write_text(
            json.dumps(self._profiles, indent=2), encoding="utf-8")

    def _refresh_profile_combo(self):
        current = self.profile_combo.currentText()
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItems(sorted(self._profiles.keys()))
        if current and self.profile_combo.findText(current) >= 0:
            self.profile_combo.setCurrentText(current)
        self.profile_combo.blockSignals(False)
