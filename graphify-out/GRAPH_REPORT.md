# Graph Report - .  (2026-04-24)

## Corpus Check
- 89 files · ~124,484 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1205 nodes · 2311 edges · 48 communities detected
- Extraction: 70% EXTRACTED · 30% INFERRED · 0% AMBIGUOUS · INFERRED: 704 edges (avg confidence: 0.72)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Qt GUI (legacy tabs & widgets)|Qt GUI (legacy tabs & widgets)]]
- [[_COMMUNITY_Python Clip Analysis Pipeline|Python Clip Analysis Pipeline]]
- [[_COMMUNITY_Python Utilities & Helpers|Python Utilities & Helpers]]
- [[_COMMUNITY_Tauri Server + LLM Provider Layer|Tauri Server + LLM Provider Layer]]
- [[_COMMUNITY_Rust LLM Provider Implementations|Rust LLM Provider Implementations]]
- [[_COMMUNITY_Rust Prompts & Transcript Models|Rust Prompts & Transcript Models]]
- [[_COMMUNITY_Py-Rust Port Bridge (data models)|Py->Rust Port Bridge (data models)]]
- [[_COMMUNITY_Tauri Bootstrap & Settings|Tauri Bootstrap & Settings]]
- [[_COMMUNITY_Spike Detection & Chunking Tests|Spike Detection & Chunking Tests]]
- [[_COMMUNITY_GuiConsole & License Verification|GuiConsole & License Verification]]
- [[_COMMUNITY_App Entry, Fonts & Licensing|App Entry, Fonts & Licensing]]
- [[_COMMUNITY_Image Re-encoding Tests|Image Re-encoding Tests]]
- [[_COMMUNITY_Svelte Frontend UI|Svelte Frontend UI]]
- [[_COMMUNITY_Clip Finder Pipeline Integration|Clip Finder Pipeline Integration]]
- [[_COMMUNITY_Provider Rate Limits & Model Fetch|Provider Rate Limits & Model Fetch]]
- [[_COMMUNITY_Premiere Prompt Template Tests|Premiere Prompt Template Tests]]
- [[_COMMUNITY_Cancellation & Whisper Models|Cancellation & Whisper Models]]
- [[_COMMUNITY_Claude CLI Subprocess Provider|Claude CLI Subprocess Provider]]
- [[_COMMUNITY_Whisper Timestamp Parsing|Whisper Timestamp Parsing]]
- [[_COMMUNITY_External Dependencies|External Dependencies]]
- [[_COMMUNITY_About Profile Artwork|About Profile Artwork]]
- [[_COMMUNITY_Svelte API Client (fetchSSE)|Svelte API Client (fetch/SSE)]]
- [[_COMMUNITY_DB Row Struct Models|DB Row Struct Models]]
- [[_COMMUNITY_Svelte Log Store|Svelte Log Store]]
- [[_COMMUNITY_LLM Provider Trait|LLM Provider Trait]]
- [[_COMMUNITY_License Verification (PyRust port)|License Verification (Py/Rust port)]]
- [[_COMMUNITY_Tauri Build & Signing|Tauri Build & Signing]]
- [[_COMMUNITY_PyInstaller Legacy Build|PyInstaller Legacy Build]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 53|Community 53]]
- [[_COMMUNITY_Community 54|Community 54]]
- [[_COMMUNITY_Community 56|Community 56]]
- [[_COMMUNITY_Community 57|Community 57]]
- [[_COMMUNITY_Community 58|Community 58]]
- [[_COMMUNITY_Community 59|Community 59]]
- [[_COMMUNITY_Community 60|Community 60]]
- [[_COMMUNITY_Community 61|Community 61]]
- [[_COMMUNITY_Community 62|Community 62]]
- [[_COMMUNITY_Community 63|Community 63]]
- [[_COMMUNITY_Community 64|Community 64]]
- [[_COMMUNITY_Community 65|Community 65]]
- [[_COMMUNITY_Community 66|Community 66]]
- [[_COMMUNITY_Community 67|Community 67]]

## God Nodes (most connected - your core abstractions)
1. `StreamClipperGUI` - 90 edges
2. `LLMClient` - 59 edges
3. `ClipSuggestion` - 51 edges
4. `path()` - 40 edges
5. `MainWindow` - 31 edges
6. `run_command()` - 24 edges
7. `SettingsTab` - 22 edges
8. `GuiConsole` - 21 edges
9. `run_full_pipeline_inner()` - 21 edges
10. `WorkerSignals` - 20 edges

## Surprising Connections (you probably didn't know these)
- `detect_volume_spikes()` --semantically_similar_to--> `detect_volume_spikes (rust)`  [INFERRED] [semantically similar]
  C:\Programming\StreamClipper\clip_finder.py → crates/trik-klip-core/src/spike_detection.rs
- `extract_audio()` --semantically_similar_to--> `extract_audio (rust, 16kHz mono WAV)`  [INFERRED] [semantically similar]
  C:\Programming\StreamClipper\clip_finder.py → crates/trik-klip-core/src/ffmpeg.rs
- `call_claude_cli()` --semantically_similar_to--> `AnthropicProvider (re-used from anthropic.rs)`  [INFERRED] [semantically similar]
  C:\Programming\StreamClipper\crates\trik-klip-core\src\llm\claude_cli.rs → crates/trik-klip-core/src/llm/claude_cli.rs
- `test_gui_helpers.py (GUI parsers + Premiere prompt)` --semantically_similar_to--> `build_prompt()`  [INFERRED] [semantically similar]
  tests/test_gui_helpers.py → C:\Programming\StreamClipper\src-tauri\src\server\premiere.rs
- `TranscriptSegment dataclass (py)` --semantically_similar_to--> `TranscriptSegment (rust)`  [INFERRED] [semantically similar]
  clip_finder.py → crates/trik-klip-core/src/models.rs

## Hyperedges (group relationships)
- **End-to-end clip pipeline (audio → spikes → chunks → LLM scoring → clips)** — core_extract_audio, core_detect_volume_spikes, core_transcribe, core_chunk_transcript, core_annotate_chunks_with_spikes, core_find_clips, core_extract_clip [INFERRED 0.90]
- **Cooperative cancellation pattern across long-running stages** — core_wait_cancelled, core_extract_audio, core_extract_clip, core_extract_slice, core_ensure_downloaded, core_transcribe, core_generate_visual_aids [EXTRACTED 0.95]
- **ProgressEvent SSE producers (stages that emit UI progress)** — core_ProgressEvent, core_extract_audio, core_ensure_downloaded, core_find_clips, core_transcribe, core_generate_visual_aids, core_detect_volume_spikes [EXTRACTED 0.90]
- **LlmProvider trait implementations** — provider_LlmProvider, claude_cli_ClaudeCliProvider, gemini_GeminiProvider, openai_compat_OpenAiCompatProvider, anthropic_provider_ref [EXTRACTED 1.00]
- **Qt background worker pipeline** — workers_PipelineWorker, workers_ExtractWorker, workers_SliceWorker, signals_WorkerSignals, workers_GuiConsole [EXTRACTED 0.95]
- **MainWindow tab assembly** — main_window_MainWindow, transcribe_tab_TranscribeTab, extract_tab_ExtractTab, slice_tab_SliceTab [EXTRACTED 1.00]
- **App.svelte tabs router (5 tabs)** — App_svelte, Transcribe_svelte, Extract_svelte, Slice_svelte, Settings_svelte [EXTRACTED 0.95]
- **Pipeline progress SSE flow** — tauri_run, sse_connectProgress, stores_ts, ProgressBar_svelte [INFERRED 0.85]
- **Dynamic API port discovery** — tauri_find_free_port, tauri_get_api_port, api_getApiBase [EXTRACTED 0.95]
- **Full Pipeline Stages (extract-audio → spikes → transcribe → chunk → analyze → extract)** — pipeline_run_full, pipeline_resolve_whisper_model, pipeline_copy_audio_sidecar [EXTRACTED 0.90]
- **HTTP Routing Stack (router + middleware + error model)** — routes_build_routes, server_log_request, error_app_error [EXTRACTED 0.90]
- **Release Flow (local build + CI distribute + launcher)** — doc_release_md, rationale_local_build, cite_nuldrums_launcher [EXTRACTED 0.90]

## Communities

### Community 0 - "Qt GUI (legacy tabs & widgets)"
Cohesion: 0.02
Nodes (70): AboutTab, _ClickableLabel, About tab — profile image, social links, message., Label that opens a URL on click., Static about page with profile image and social links., ClipSection, Reusable clip section widget for the Slice tab., Scan folder and list detected files. (+62 more)

### Community 1 - "Python Clip Analysis Pipeline"
Cohesion: 0.03
Nodes (102): analyze_chunk(), annotate_chunks_with_spikes(), build_editing_prompt(), build_system_prompt(), chunk_transcript(), cli(), cmd_analyze(), cmd_chunk() (+94 more)

### Community 2 - "Python Utilities & Helpers"
Cohesion: 0.03
Nodes (41): ClipSuggestion, path(), _load_bundled_fonts(), Return the Whisper language code for the currently selected language., A canvas-drawn scrollbar with a rounded purple thumb and no arrows., Build the About tab with profile image, social icons, and message., Called by the scrollable widget to update thumb position., Query the Ollama server and populate the model dropdown. (+33 more)

### Community 3 - "Tauri Server + LLM Provider Layer"
Cohesion: 0.04
Nodes (85): AnthropicProvider (re-used from anthropic.rs), ClaudeCliProvider struct, Cli, Commands, CLI Commands Enum (10 subcommands), create_provider(), default_output(), exit_error() (+77 more)

### Community 4 - "Rust LLM Provider Implementations"
Cohesion: 0.03
Nodes (69): AnthropicProvider, GeminiProvider, AppState, build_routes(), ClipFolderEntry, create_profile(), CreateProfileRequest, delete_profile() (+61 more)

### Community 5 - "Rust Prompts & Transcript Models"
Cohesion: 0.04
Nodes (45): clip_transcript_segments(), Return only the segments that overlap [clip_start, clip_end]., AnalysisChunk, ClipSuggestion, fmt_time(), ProgressEvent, TranscriptSegment, VolumeSpike (+37 more)

### Community 6 - "Py->Rust Port Bridge (data models)"
Cohesion: 0.05
Nodes (52): ClipSuggestion dataclass (py), TranscriptSegment dataclass (py), ANALYSIS_SYSTEM_PROMPT constant, AVAILABLE_MODELS constant, AnalysisChunk (rust), ClipSuggestion (rust), CutEntry (parsed CUT LIST), LlmProvider trait (implied) (+44 more)

### Community 7 - "Tauri Bootstrap & Settings"
Cohesion: 0.06
Nodes (30): main(), env_or(), env_search_paths (.env lookup order), resolve_resources_dir (exe/NSIS/dev fallback), Settings, index.html (Tauri WebView shell), AppError enum, AppError (+22 more)

### Community 8 - "Spike Detection & Chunking Tests"
Cohesion: 0.09
Nodes (21): annotate_chunks_with_spikes(), chunk_transcript(), empty_segments_returns_empty(), make_segments(), no_spikes_leaves_text_unchanged(), overlapping_windows(), single_segment_produces_one_chunk(), spike_annotation() (+13 more)

### Community 9 - "GuiConsole & License Verification"
Cohesion: 0.07
Nodes (15): GuiConsole, _parse_clip_range_from_prompt(), _parse_clip_start_from_prompt(), parse_clips_script(), Parse an extract_clips.sh and return (mp4_source, list[ShellClip])., Drop-in replacement for rich.Console that routes output to a Queue., ShellClip, parse_time() (+7 more)

### Community 10 - "App Entry, Fonts & Licensing"
Cohesion: 0.08
Nodes (27): _load_fonts(), main(), Application entry point — QApplication setup, font loading, launch., Load bundled custom fonts., LicenseDialog, Modal dialog that gates access until a valid Gumroad license is entered., LicenseDialog, License activation dialog — modal gate for packaged builds. (+19 more)

### Community 11 - "Image Re-encoding Tests"
Cohesion: 0.08
Nodes (25): make_corrupt_jpeg(), make_valid_jpeg(), make_valid_png(), make_webp_bytes(), Tests for image re-encoding logic that fixes Premiere Pro header errors.  Tests, Pillow can still open many corrupt JPEGs and re-save them clean., JPEG files always start with FF D8 FF., RGBA images should have alpha dropped when converting to JPEG. (+17 more)

### Community 12 - "Svelte Frontend UI"
Cohesion: 0.13
Nodes (27): About Tab, App.svelte (Root Component), ClipCard Component, DropZone Component, Extract Tab, LicenseGate Component, LogPanel Component, ProgressBar Component (+19 more)

### Community 13 - "Clip Finder Pipeline Integration"
Cohesion: 0.16
Nodes (27): AboutTab, gui_qt/app.py main() entry, claude_cli.rs (Claude CLI subprocess provider), clip_finder (cf) pipeline module, ClipSection widget, DropZone drag-and-drop widget, _ClipRow (per-clip widget), ExtractTab (+19 more)

### Community 14 - "Provider Rate Limits & Model Fetch"
Cohesion: 0.13
Nodes (18): Exception, ClaudeCodeRateLimitError, _fetch_anthropic_models(), _fetch_gemini_models(), _fetch_grok_models(), _fetch_json(), _fetch_openai_models(), list_ollama_models() (+10 more)

### Community 15 - "Premiere Prompt Template Tests"
Cohesion: 0.11
Nodes (7): Verify the Premiere prompt template has the right structure., Import should be split into two calls (videos then images)., Visuals should be placed on their own track before banners., Twitch and YouTube banners should be on higher track indices than visuals., Final layout should show 2 empty tracks., The known offset behavior should be documented., TestPremierePrompt

### Community 16 - "Cancellation & Whisper Models"
Cohesion: 0.2
Nodes (12): is_cancelled(), ask_for_queries(), generate_visual_aids(), is_supported_image(), pad_or_truncate(), search_and_download_image(), strip_code_fences(), try_download_and_reencode() (+4 more)

### Community 17 - "Claude CLI Subprocess Provider"
Cohesion: 0.24
Nodes (8): RATE_LIMIT_PHRASES heuristic, call_claude_cli(), ClaudeCliProvider, CliError, find_claude(), find_claude_uncached(), is_available(), which()

### Community 18 - "Whisper Timestamp Parsing"
Cohesion: 0.24
Nodes (9): parse_flex_ts(), parse_whisper_timestamp(), test_parse_whisper_timestamp_comma(), test_parse_whisper_timestamp_dot(), test_parse_whisper_timestamp_zero(), transcribe(), WhisperJsonOutput, WhisperJsonSegment (+1 more)

### Community 19 - "External Dependencies"
Cohesion: 0.22
Nodes (10): Claude Code CLI, Gyan.dev FFmpeg builds, HuggingFace ggml-base.bin, Nuldrums Launcher distribution, whisper.cpp (Vulkan build), CHANGELOG.md (release history), CLAUDE.md (AI agent notes), README.md (project overview) (+2 more)

### Community 20 - "About Profile Artwork"
Cohesion: 0.25
Nodes (9): About Profile Avatar (assets duplicate), Profile/Branding Artwork, Stylized Profile Avatar Artwork, Stylized Figure with Geometric Mask and Wild Hair, About Profile Image, About Profile Avatar (public), Black and White Ink/Brush Illustration Style, About Tab (Svelte Component Usage) (+1 more)

### Community 21 - "Svelte API Client (fetch/SSE)"
Cohesion: 0.43
Nodes (5): apiFetch(), getApiBase(), healthCheck(), connectProgress(), subscribeProgress()

### Community 22 - "DB Row Struct Models"
Cohesion: 0.4
Nodes (4): ClipResultRow, ProviderProfileRow, SystemStateRow, TranscriptRow

### Community 23 - "Svelte Log Store"
Cohesion: 0.5
Nodes (2): addLog(), if()

### Community 24 - "LLM Provider Trait"
Cohesion: 0.67
Nodes (2): LlmProvider, LlmResponse

### Community 25 - "License Verification (Py/Rust port)"
Cohesion: 0.67
Nodes (3): LicenseResult struct, verify_license (rust), verify_license (py)

### Community 26 - "Tauri Build & Signing"
Cohesion: 0.67
Nodes (3): Tauri build.rs, Azure Trusted Signing Stub, Tauri lib.rs (App Entry)

### Community 27 - "PyInstaller Legacy Build"
Cohesion: 0.67
Nodes (3): BUILD.md (legacy PyInstaller build), requirements.txt (legacy Python deps), Rationale: PyInstaller needs clean build venv (pathlib conflict)

### Community 28 - "Community 28"
Cohesion: 1.0
Nodes (1): Color palette and global QSS stylesheet for Trik_Klip.

### Community 31 - "Community 31"
Cohesion: 1.0
Nodes (2): svelte.config.js (Svelte 4 compat), vite.config.ts (port 5175)

### Community 32 - "Community 32"
Cohesion: 1.0
Nodes (2): init_pool (sqlx WAL), run_migrations (CREATE TABLE IF NOT EXISTS)

### Community 33 - "Community 33"
Cohesion: 1.0
Nodes (2): Concept: ProgressEvent broadcast over SSE, GET /api/pipeline/progress SSE

### Community 34 - "Community 34"
Cohesion: 1.0
Nodes (2): Concept: Premiere header error fixed by re-encode, test_image_reencoding.py (Premiere header fix)

### Community 35 - "Community 35"
Cohesion: 1.0
Nodes (2): OpenAI Whisper, RELEASE_README.md (end-user docs)

### Community 53 - "Community 53"
Cohesion: 1.0
Nodes (1): Replicate the re-encoding logic from gui.py.

### Community 54 - "Community 54"
Cohesion: 1.0
Nodes (1): Images under 5000 bytes should be skipped.

### Community 56 - "Community 56"
Cohesion: 1.0
Nodes (1): GuiConsole (Rich-output redirector)

### Community 57 - "Community 57"
Cohesion: 1.0
Nodes (1): Python licensing module (Gumroad)

### Community 58 - "Community 58"
Cohesion: 1.0
Nodes (1): parse_whisper_timestamp

### Community 59 - "Community 59"
Cohesion: 1.0
Nodes (1): CliError enum

### Community 60 - "Community 60"
Cohesion: 1.0
Nodes (1): gui_qt widgets package init

### Community 61 - "Community 61"
Cohesion: 1.0
Nodes (1): API Fetch Module

### Community 62 - "Community 62"
Cohesion: 1.0
Nodes (1): SSE Progress Subscription

### Community 63 - "Community 63"
Cohesion: 1.0
Nodes (1): PipelineParams Interface

### Community 64 - "Community 64"
Cohesion: 1.0
Nodes (1): CLI Parser Struct

### Community 65 - "Community 65"
Cohesion: 1.0
Nodes (1): PipelineParams request type

### Community 66 - "Community 66"
Cohesion: 1.0
Nodes (1): GET /api/providers/{name}/models

### Community 67 - "Community 67"
Cohesion: 1.0
Nodes (1): POST /api/providers/test

## Knowledge Gaps
- **224 isolated node(s):** `Return (clip_start, clip_end) in seconds from the prompt metadata.          Fall`, `Kept for backwards compatibility — returns clip_start only.`, `Gumroad license-key verification for Trik_Klip.  API reference: POST https://api`, `Store the license in %APPDATA%/Trik_Klip so it survives rebuilds.`, `Verify a license key against the Gumroad API.      Args:         license_key: Th` (+219 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Svelte Log Store`** (4 nodes): `addLog()`, `Extract.svelte`, `Transcribe.svelte`, `if()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `LLM Provider Trait`** (3 nodes): `provider.rs`, `LlmProvider`, `LlmResponse`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 28`** (2 nodes): `theme.py`, `Color palette and global QSS stylesheet for Trik_Klip.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 31`** (2 nodes): `svelte.config.js (Svelte 4 compat)`, `vite.config.ts (port 5175)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 32`** (2 nodes): `init_pool (sqlx WAL)`, `run_migrations (CREATE TABLE IF NOT EXISTS)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 33`** (2 nodes): `Concept: ProgressEvent broadcast over SSE`, `GET /api/pipeline/progress SSE`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 34`** (2 nodes): `Concept: Premiere header error fixed by re-encode`, `test_image_reencoding.py (Premiere header fix)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 35`** (2 nodes): `OpenAI Whisper`, `RELEASE_README.md (end-user docs)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 53`** (1 nodes): `Replicate the re-encoding logic from gui.py.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 54`** (1 nodes): `Images under 5000 bytes should be skipped.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 56`** (1 nodes): `GuiConsole (Rich-output redirector)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 57`** (1 nodes): `Python licensing module (Gumroad)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 58`** (1 nodes): `parse_whisper_timestamp`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 59`** (1 nodes): `CliError enum`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 60`** (1 nodes): `gui_qt widgets package init`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 61`** (1 nodes): `API Fetch Module`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 62`** (1 nodes): `SSE Progress Subscription`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 63`** (1 nodes): `PipelineParams Interface`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 64`** (1 nodes): `CLI Parser Struct`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 65`** (1 nodes): `PipelineParams request type`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 66`** (1 nodes): `GET /api/providers/{name}/models`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 67`** (1 nodes): `POST /api/providers/test`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `path()` connect `Python Utilities & Helpers` to `Qt GUI (legacy tabs & widgets)`, `Python Clip Analysis Pipeline`, `Tauri Server + LLM Provider Layer`, `Rust LLM Provider Implementations`, `App Entry, Fonts & Licensing`?**
  _High betweenness centrality (0.163) - this node is a cross-community bridge._
- **Why does `StreamClipperGUI` connect `Python Utilities & Helpers` to `Spike Detection & Chunking Tests`, `GuiConsole & License Verification`, `Tauri Server + LLM Provider Layer`?**
  _High betweenness centrality (0.110) - this node is a cross-community bridge._
- **Why does `ClipSuggestion` connect `Python Utilities & Helpers` to `Python Clip Analysis Pipeline`, `Tauri Server + LLM Provider Layer`, `Spike Detection & Chunking Tests`, `GuiConsole & License Verification`, `App Entry, Fonts & Licensing`?**
  _High betweenness centrality (0.066) - this node is a cross-community bridge._
- **Are the 46 inferred relationships involving `LLMClient` (e.g. with `TranscriptSegment` and `ClipSuggestion`) actually correct?**
  _`LLMClient` has 46 INFERRED edges - model-reasoned connections that need verification._
- **Are the 48 inferred relationships involving `ClipSuggestion` (e.g. with `LLMClient` and `GuiConsole`) actually correct?**
  _`ClipSuggestion` has 48 INFERRED edges - model-reasoned connections that need verification._
- **Are the 38 inferred relationships involving `path()` (e.g. with `extract_clip_with_assets()` and `generate_slices()`) actually correct?**
  _`path()` has 38 INFERRED edges - model-reasoned connections that need verification._
- **Are the 14 inferred relationships involving `MainWindow` (e.g. with `Application entry point — QApplication setup, font loading, launch.` and `Load bundled custom fonts.`) actually correct?**
  _`MainWindow` has 14 INFERRED edges - model-reasoned connections that need verification._