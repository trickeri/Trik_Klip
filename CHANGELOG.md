# Trik_Klip Changelog

## Versioning Rules

- **Bug fixes** (small patches, crash fixes): increment by 0.01 (e.g. 1.0.00 -> 1.0.01)
- **Major updates** (new features, significant changes): increment the second number by 1 (e.g. 1.0.xx -> 1.1.00)
- When the update type is unclear, confirm the new version number with the user before packaging.

---

## v1.0.01

- Fixed crash on Whisper model load in packaged build. PyInstaller windowed mode sets sys.stdout/stderr to None, causing Whisper to crash when printing progress. Redirected None streams to devnull at startup.

## v1.0.00

- Initial packaged release for Windows.
- Full GUI with drag-and-drop, analysis pipeline, clip extraction.
- CUDA-enabled Whisper transcription bundled.
- Multi-provider LLM support (Anthropic, OpenAI, Gemini, Grok, Ollama).
- Bundled ffmpeg/ffprobe.
- Gumroad license key verification on launch.
