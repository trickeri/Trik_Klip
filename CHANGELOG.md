# Trik_Klip Changelog

## Versioning Rules

- **Bug fixes** (small patches, crash fixes): increment by 0.01 (e.g. 1.0.00 -> 1.0.01)
- **Hotfixes** (rapid follow-up patches to a version): append a letter suffix (e.g. 1.0.01_a, 1.0.01_b, 1.0.01_c). Use when bundling multiple small fixes before the next full version bump.
- **Major updates** (new features, significant changes): increment the second number by 1 (e.g. 1.0.xx -> 1.1.00)
- When the update type is unclear, confirm the new version number with the user before packaging.

---

## v1.0.01_a

- Fixed crash on Whisper model load in packaged build. PyInstaller windowed mode sets sys.stdout/stderr to None. Added guards in both gui.py and clip_finder.py.
- Made _StdoutProxy.write() and flush() handle None original stdout defensively (defense-in-depth).
- Fixed app not fully shutting down when clicking the X button. Added WM_DELETE_WINDOW handler that signals workers to stop and force-exits the process.
- Added version number display: "Welcome to Trik_Klip v1.0.01_a" appears in the output log on startup.

## v1.0.00

- Initial packaged release for Windows.
- Full GUI with drag-and-drop, analysis pipeline, clip extraction.
- CUDA-enabled Whisper transcription bundled.
- Multi-provider LLM support (Anthropic, OpenAI, Gemini, Grok, Ollama).
- Bundled ffmpeg/ffprobe.
- Gumroad license key verification on launch.
