# Trik_Klip Changelog

## Versioning Rules

- **Bug fixes** (small patches, crash fixes): increment by 0.01 (e.g. 1.0.00 -> 1.0.01)
- **Hotfixes** (rapid follow-up patches to a version): append a letter suffix (e.g. 1.0.01_a, 1.0.01_b, 1.0.01_c). Use when bundling multiple small fixes before the next full version bump.
- **Major updates** (new features, significant changes): increment the second number by 1 (e.g. 1.0.xx -> 1.1.00)
- When the update type is unclear, confirm the new version number with the user before packaging.

---

## v1.0.02_a

- Added audio volume spike detection to the pipeline. Uses numpy RMS energy analysis with adaptive rolling baseline to detect moments of excitement (yelling, reactions). Spikes are annotated into transcript chunks before LLM analysis as `[AUDIO ENERGY NOTES]`, giving the AI strong signals for clip-worthiness.
- Added full CLI interface for AI agent automation. Every pipeline step is now independently runnable via subcommands: `extract-audio`, `detect-spikes`, `transcribe`, `chunk`, `analyze`, `extract`, `generate-slices`, `run`, `providers`, `commands`. All commands output JSON by default for easy chaining.
- Added `commands` subcommand that outputs a machine-readable directory of all CLI commands, options, inputs, and outputs — designed for AI agents to discover and use the pipeline.
- Added `claude_code` as a selectable provider in the CLI (previously only available in GUI).
- Refactored clip extraction and slice generation logic from GUI into reusable functions in `clip_finder.py`.
- Added `list_providers()` function to `providers.py`.
- Console output from pipeline functions now goes to stderr to avoid contaminating JSON output on stdout.

## v1.0.01_e

- Fixed Claude Code (Subscription) provider billing API credits instead of using subscription tokens. The CLI was picking up the `ANTHROPIC_API_KEY` environment variable and using it over OAuth auth. Now strips that env var from the subprocess so `claude -p` uses subscription tokens as intended.
- Moved license activation file to `%APPDATA%/Trik_Klip/` so it persists across rebuilds and updates — users no longer need to re-enter their license key after updating.

## v1.0.01_d

- Fixed Claude Code CLI returning markdown instead of JSON. The `--system-prompt` flag was being ignored by the CLI's internal prompt, so analysis instructions are now passed in the user message instead, ensuring the model follows the correct JSON schema.
- Fixed `--bare` flag silently billing users' API keys instead of using their subscription (OAuth auth was disabled by `--bare`). Removed the flag.
- Fixed UnicodeEncodeError on Windows caused by `→` character in prompts. Added `encoding="utf-8"` to subprocess calls and reconfigured stdout/stderr to UTF-8 at startup.
- Fixed console windows popping up during audio extraction, whisper transcription, and Claude Code CLI calls on Windows. Added `CREATE_NO_WINDOW` to all subprocess calls including a monkey-patch for Whisper's internal ffmpeg call.
- Fixed cancel button not stopping the pipeline between audio extraction and whisper transcription. Added cancel checks between every pipeline step.
- Added custom editing notes UI for the slice generation step (mirrors the custom search prompts for clip analysis).
- Added file logging to `logs/` directory for debugging.
- Renamed "Top N Clips" label to "Max Clips".
- Rewrote analysis system prompt for stricter JSON schema compliance.

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
