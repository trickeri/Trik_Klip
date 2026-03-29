# Trik_Klip Changelog

## Versioning Rules

- **Bug fixes** (small patches, crash fixes): increment by 0.01 (e.g. 1.0.00 -> 1.0.01)
- **Hotfixes** (rapid follow-up patches to a version): append a letter suffix (e.g. 1.0.01_a, 1.0.01_b, 1.0.01_c). Use when bundling multiple small fixes before the next full version bump.
- **Major updates** (new features, significant changes): increment the second number by 1 (e.g. 1.0.xx -> 1.1.00)
- When the update type is unclear, confirm the new version number with the user before packaging.

---

## v1.0.01_c

- Fixed Claude Code subscription fallback not activating when user is out of tokens. The CLI exits 0 with the rate-limit error as plain text in stdout, which bypassed the previous detection. Now checks stdout for rate-limit phrases on exit code 0 and triggers the API fallback correctly.
- Fixed misleading "No clip suggestions found" when all analysis windows fail. JSON parse failures now track as errors properly, so the user sees "All X windows failed" with the actual error message.

## v1.0.01_b

- Added "Claude Code (Subscription)" provider: uses `claude -p` CLI so users can analyze clips with their Pro/Max subscription instead of paying API costs. Includes automatic Anthropic API fallback on rate limit.
- Analysis runs 4 windows in parallel when using the Claude Code provider.
- Claude Code is now the default provider (previously Anthropic API).
- Added "Custom Search Prompts" section in the Transcribe tab: expandable list of text fields where users can tell the AI what specific things to look for in the transcript.
- Improved error logging: errors now show exception type, repeated errors are deduplicated after 3 occurrences, and the final summary distinguishes all-failed vs no-clips-found with the last error message displayed.
- Updated README and release README with Claude Code provider documentation, setup instructions, and troubleshooting.

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
