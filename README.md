# Trik_Klip

Find long-form editing sections inside MP4 streams using Whisper + an LLM of your choice, then cut them with a point-and-click desktop app.

Trik_Klip is a Rust + Tauri + Svelte desktop application. The engine is `trik-klip-core` (Rust), the UI is Svelte, and the two are glued together by Tauri.

---

## Install

Pre-built Windows releases are published via the **[Nuldrums launcher](https://nuldrums.world)** and as portable zips on the [GitHub Releases](../../releases) page.

Unzip anywhere and double-click `trik-klip.exe`. No installer needed. ffmpeg and whisper.cpp (Vulkan) binaries ship inside the zip.

For developers who want to run from source, see [BUILD.md](BUILD.md).

---

## What it does

1. **Extracts audio** from any MP4 with `ffmpeg` (choose a specific audio track if the file has multiple)
2. **Transcribes** speech using whisper.cpp with the Vulkan backend (runs locally on GPU, no cloud needed) with a live progress bar
3. **Slides an analysis window** across the entire stream
4. **Asks an LLM** to identify the best 1–3 minute core clip in each window
5. **Expands each clip** by a configurable padding (default ±3 min) so the exported video contains the full topic discussion for editing
6. **Returns ranked suggestions** with timestamps and virality scores
7. **Exports** individual clip MP4s via lossless ffmpeg stream copy, plus optional Premiere Pro setup prompts

---

## LLM providers

Trik_Klip supports multiple LLM providers for the analysis step. Configure them in the **Settings** tab or via environment variables.

| Provider | API Key? | Notes |
|---|---|---|
| Anthropic (Claude) | Yes | Standard API billing per token |
| OpenAI (ChatGPT) | Yes | Standard API billing per token |
| Google (Gemini) | Yes | Standard API billing per token |
| xAI (Grok) | Yes | Standard API billing per token |
| Ollama (Local) | No | Free, runs models locally |
| **Claude Code (Subscription)** | **No** | **Uses your Claude Pro/Max subscription via the Claude Code CLI** |

### Claude Code (Subscription) provider

Lets you use your existing Claude Pro or Max subscription for the analysis step instead of paying per-token API costs. It calls the `claude` CLI tool in the background.

**Requirements:**
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed and on your PATH
- An active Claude Pro or Max subscription, authenticated via `claude auth`

**Setup:**
1. Open the **Settings** tab and create a profile with provider **Claude Code (Subscription)**.
2. Choose a model (default: `claude-sonnet-4-6`).
3. Optionally enter an Anthropic API key as a **fallback** — if the CLI hits your subscription's rate limit mid-analysis, the remaining windows will automatically switch to the standard Anthropic API.

**How it works:**
- Each transcript window is sent to `claude -p` as a subprocess.
- Analysis runs **4 windows in parallel** for faster throughput.
- If a rate limit is hit and a fallback API key is configured, the remaining windows seamlessly switch to the Anthropic API. A warning is logged when this happens.
- Token usage is not tracked for CLI calls (only for API fallback calls).

---

## Clip padding

By default Trik_Klip adds **3 minutes before and after** each core clip identified by the LLM. This means:

- The LLM finds a 1–3 minute highlight
- The exported file contains that highlight **plus surrounding context**
- Resulting clips are typically **7–9 minutes** long
- Editors have the full topic discussion to cut from rather than a tight window

Set the Padding field to `0.0` to export the raw tight boundaries instead.

---

## How clips are scored

Each window is evaluated by the LLM against these criteria:

| Type | Description |
|------|-------------|
| `story` | Narrative arc with beginning, middle, end |
| `advice` | Actionable guidance with clear stakes |
| `moment` | Funny, emotional, or surprising instant |
| `debate` | Heated or thought-provoking exchange |
| `rant` | Passionate monologue on a strong opinion |
| `revelation` | Counterintuitive take or surprising fact |

**Virality score (1–10):** the model rates each candidate based on:
- Hook strength (would someone stop scrolling?)
- Story completeness in the clip window
- Quotability and shareability
- Emotional or informational value density

Score colour coding in the UI: green (7–10), amber (4–6), red (1–3).

---

## Architecture

```
MP4 file
  └─► ffmpeg              extract mono 16kHz WAV (specific audio track optional)
        └─► whisper.cpp   local Vulkan-GPU transcription → timestamped segments
                          (UI shows live progress bar)
              └─► Chunker     sliding analysis windows (configurable size + 1-min overlap)
                    └─► LLM         score each window for clip potential
                    │               (4x parallel when using Claude Code provider)
                          └─► Padder     expand core clip by ±padding minutes
                                └─► Ranker    sort + deduplicate by virality score
                                      └─► Output   per-clip MP4s / JSON / Premiere prompts / UI panel
```

---

## Repo layout

| Path | Purpose |
|------|---------|
| `crates/trik-klip-core/` | Core Rust library: pipeline, whisper/ffmpeg wrappers, LLM providers, chunking, spike detection, DB |
| `src-tauri/` | Tauri shell + HTTP server that brokers between the Svelte UI and `trik-klip-core` |
| `src/` | Svelte frontend (Transcribe / Extract / Slice / Settings / About tabs) |
| `scripts/` | Build + signing helpers (`sign.ps1`, `update_metrics.sh`) |
| `metrics/` | Pre-computed cloc output for AI agents (see CLAUDE.md) |

---

## Tips for best results

- **Whisper model:** `small` hits the best speed/accuracy balance for most streams. Use `medium` or `large` for heavy accents or technical jargon.
- **Window size:** 5 minutes is tuned for conversational content. For fast-paced or highly edited content, try 3 minutes.
- **Padding:** 3 minutes is a good default for podcast/stream content. Reduce to 1–2 minutes for tightly scripted content where the topic doesn't need much run-up.
- **Re-use transcripts:** transcribing a 3-hour stream takes ~10 minutes with `small`. Once transcribed it's cached in the local DB — you can re-run the analysis for free as many times as you like, including against different LLM providers.
- **Multiple audio tracks:** if your recording software lays down a game audio track and a mic track separately, pick the correct one in the Audio Track field.
- **ffmpeg copy mode:** extracted clips use `-c:v copy` — cuts are instant and lossless, no re-encoding.
