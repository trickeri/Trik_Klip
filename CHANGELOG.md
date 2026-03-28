# Trik_Klip Changelog

## Versioning Rules

- **Bug fixes** (small patches, crash fixes): increment by 0.01 (e.g. 1.0.00 -> 1.0.01)
- **Major updates** (new features, significant changes): increment the second number by 1 (e.g. 1.0.xx -> 1.1.00)
- When the update type is unclear, confirm the new version number with the user before packaging.

---

## v1.0.02 (not yet packaged)

- Fixed app not fully shutting down when clicking the X button. Added WM_DELETE_WINDOW handler that signals workers to stop and force-exits the process, preventing zombie threads and lingering ffmpeg subprocesses.
- Added stdout/stderr None guard in clip_finder.py as defense-in-depth for PyInstaller windowed mode (the gui.py guard may not cover all code paths during import).
- Made _StdoutProxy.write() and flush() handle None original stdout defensively.
- Added version number display: "Welcome to Trik_Klip v1.0.02" appears in the output log on startup.

## v1.0.01

- Fixed crash on Whisper model load in packaged build. PyInstaller windowed mode sets sys.stdout/stderr to None, causing Whisper to crash when printing progress. Redirected None streams to devnull at startup.

## v1.0.00

- Initial packaged release for Windows.
- Full GUI with drag-and-drop, analysis pipeline, clip extraction.
- CUDA-enabled Whisper transcription bundled.
- Multi-provider LLM support (Anthropic, OpenAI, Gemini, Grok, Ollama).
- Bundled ffmpeg/ffprobe.
- Gumroad license key verification on launch.
