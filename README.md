# Stream Clipper

Find long-form editing sections inside MP4 streams using Whisper + Claude, then cut them with a point-and-click GUI or the command line.

---

## Setup

### Prerequisites

- Python 3.10+
- [ffmpeg](https://ffmpeg.org/download.html) installed and on your PATH
  - **Windows:** download from ffmpeg.org and add the `bin` folder to your PATH, or install via `winget install ffmpeg`
  - **macOS:** `brew install ffmpeg`
  - **Linux:** `sudo apt install ffmpeg`
- An [Anthropic API key](https://console.anthropic.com/)

### Install

```bash
# 1. Clone the repo
git clone https://github.com/your-username/streamclipper.git
cd streamclipper

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # macOS/Linux
.venv\Scripts\activate           # Windows

# 3. Install PyTorch with GPU (CUDA) support — do this BEFORE requirements.txt
#    Check your CUDA version with: nvidia-smi
#    CUDA 11.8 (most common):
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu118
#    CUDA 12.1:
#    pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121

# 4. Install remaining dependencies
pip install -r requirements.txt

# 5. Configure your API key
cp .env.example .env
```

Open `.env` and add your key:
```
ANTHROPIC_API_KEY=sk-ant-...
```

### Run

**GUI (recommended):**
```bash
python gui.py
```

**CLI:**
```bash
python clip_finder.py stream.mp4 --whisper-model small --top-n 10
```

---

## What it does

1. **Extracts audio** from any MP4 with `ffmpeg` (choose a specific audio track if the file has multiple)
2. **Transcribes** speech using OpenAI Whisper (runs locally, no cloud needed) with a live progress bar
3. **Slides an analysis window** across the entire stream
4. **Asks Claude** to identify the best 1–3 minute core clip in each window
5. **Expands each clip** by a configurable padding (default ±3 min) so the exported video contains the full topic discussion for editing
6. **Returns ranked suggestions** with timestamps and virality scores
7. **Exports** an `extract_clips.sh` script, a results JSON, and optionally the WAV transcript audio

---

## Two ways to use it

### Option A — GUI (`gui.py`)

The recommended way. A dark-themed desktop app with drag-and-drop, live progress, and a clip selection panel.

**Run:**
```bash
python gui.py
```

#### GUI overview

| Section | Description |
|---------|-------------|
| **Drop zone** | Drag an MP4 onto it, or click Browse |
| **Options** | Whisper model, Top N clips, Analysis window size, Padding, Audio track |
| **File Paths** | Load/save transcript JSON, save WAV, save results JSON, set export dir |
| **Run Mode** | Choose what to run (see below) |
| **Load Existing Clips Script** | Parse a previously generated `extract_clips.sh` and open the clip panel |
| **Run / Cancel** | Start or abort the selected pipeline |
| **Whisper progress bar** | Appears during transcription, shows percent complete and current timestamp |
| **Output Log** | Live streaming log of every step |
| **Clip Extraction Panel** | Appears after analysis; check/uncheck clips, then extract selected |

#### Run modes

| Mode | What it does |
|------|-------------|
| **Full Pipeline** | Extract audio → Whisper transcription → Claude analysis → clip suggestions |
| **Extract + Transcribe Only** | Extract audio and run Whisper, save transcript JSON for later use |
| **Analyze Transcript Only** | Load an existing transcript JSON and run Claude analysis (no audio needed) |

#### Clip extraction panel

After the analysis completes (or after loading an existing `extract_clips.sh`), a panel appears in the settings area:

- Every suggested clip gets a row: virality score, rank, title, timestamps, duration
- Check or uncheck individual clips
- **Select All / Deselect All** buttons with a live selection counter
- **Output dir** field to control where files land
- **Extract Selected Clips** runs `ffmpeg` directly for each checked clip and streams per-clip status to the log

#### Default output paths

When an MP4 is loaded, all output paths are automatically set to:
```
D:\Videos\Streams\Clips\<StreamName>\<StreamName>_transcript.json
D:\Videos\Streams\Clips\<StreamName>\<StreamName>_audio.wav
D:\Videos\Streams\Clips\<StreamName>\<StreamName>_clips.json
D:\Videos\Streams\Clips\<StreamName>\<StreamName>_clips\
```
Each stream gets its own subfolder. Paths can be overridden at any time.

---

### Option B — CLI (`clip_finder.py`)

See [Setup](#setup) above for install instructions. Once done:

**Run:**
```bash
python clip_finder.py stream.mp4 \
  --whisper-model small \
  --top-n 10 \
  --padding-minutes 3 \
  --output-json results.json \
  --export-clips-dir ./clips
```

This writes a `clips/extract_clips.sh` script you can run to cut all suggested clips.

**Full options:**
```
Arguments:
  MP4_FILE                    Path to your MP4 file

Options:
  --whisper-model             tiny | base | small | medium | large
                              Default: base
  --top-n INT                 Max clip suggestions to return. Default: 10
  --window-minutes INT        Analysis window size in minutes. Default: 5
  --padding-minutes FLOAT     Minutes of context added before and after each
                              identified core clip for editing headroom.
                              Default: 3  (gives ~7–9 min output clips)
  --audio-track INT           0-based index of the audio stream to extract.
                              Use 'ffmpeg -i <file>' to list tracks.
                              Default: first track
  --transcript PATH           Skip transcription, load existing JSON
  --save-transcript PATH      Save transcript JSON for future reuse
  --output-json PATH          Save results as JSON
  --export-clips-dir PATH     Write ffmpeg extraction script here
```

**Tip — save transcripts to skip re-transcribing:**
```bash
# First run: transcribe and save
python clip_finder.py stream.mp4 --save-transcript transcript.json

# Future runs: skip transcription entirely
python clip_finder.py stream.mp4 --transcript transcript.json
```

---

## Clip padding

By default, Stream Clipper adds **3 minutes before and after** each core clip identified by Claude. This means:

- Claude finds a 1–3 minute highlight
- The exported file contains that highlight **plus surrounding context**
- Resulting clips are typically **7–9 minutes** long
- Editors have the full topic discussion to cut from rather than a tight window

Set `--padding-minutes 0` (CLI) or the Padding spinbox to `0.0` (GUI) to export the raw tight boundaries instead.

---

## How clips are scored

Each window is evaluated by Claude against these criteria:

| Type | Description |
|------|-------------|
| `story` | Narrative arc with beginning, middle, end |
| `advice` | Actionable guidance with clear stakes |
| `moment` | Funny, emotional, or surprising instant |
| `debate` | Heated or thought-provoking exchange |
| `rant` | Passionate monologue on a strong opinion |
| `revelation` | Counterintuitive take or surprising fact |

**Virality score (1–10):** Claude rates each candidate based on:
- Hook strength (would someone stop scrolling?)
- Story completeness in the clip window
- Quotability and shareability
- Emotional or informational value density

Score colour coding in the GUI: green (7–10), amber (4–6), red (1–3).

---

## Output example (CLI)

```
#1 — "How a stranger's question changed how I see money"
  STORY  ████████░░  8/10
  Hook: A stranger's 5-word question rewired this person's entire
        relationship with money — and led to paying off debt in 18 months.
  5-min window:   00:03:30 → 00:08:30
  Clip timestamps: 00:01:00 → 00:09:45  (525s / 8.8 min, incl. ±3 min padding)

  "That question haunted me for weeks. Money is just stored time..."
```

---

## Architecture

```
MP4 file
  └─► ffmpeg            extract mono 16kHz WAV (specific audio track optional)
        └─► Whisper     local transcription → timestamped segments
                        (GUI shows live progress bar)
              └─► Chunker     sliding analysis windows (configurable size + 1-min overlap)
                    └─► Claude      score each window for clip potential
                          └─► Padder     expand core clip by ±padding minutes
                                └─► Ranker    sort + deduplicate by virality score
                                      └─► Output   log / JSON / ffmpeg script / GUI panel
```

---

## File overview

| File | Purpose |
|------|---------|
| `clip_finder.py` | Core pipeline: audio extraction, Whisper, Claude analysis, output |
| `gui.py` | Desktop GUI front-end for `clip_finder.py` |
| `StreamClipper.jsx` | Standalone React component (browser-based, paste-transcript workflow) |

---

## Tips for best results

- **Whisper model:** `small` hits the best speed/accuracy balance for most streams. Use `medium` or `large` for heavy accents or technical jargon.
- **Window size:** 5 minutes is tuned for conversational content. For fast-paced or highly edited content, try `--window-minutes 3`.
- **Padding:** 3 minutes is a good default for podcast/stream content. Reduce to 1–2 minutes for tightly scripted content where the topic doesn't need much run-up.
- **Re-use transcripts:** transcribing a 3-hour stream takes ~10 minutes with `small`. Save it once with `--save-transcript` and re-run the analysis for free as many times as you like.
- **Multiple audio tracks:** if your recording software lays down a game audio track and a mic track separately, use `--audio-track 1` (or the Padding field in the GUI) to pick the correct one for transcription.
- **ffmpeg copy mode:** extracted clips use `-c:v copy` — cuts are instant and lossless, no re-encoding.
- **Load existing script:** if you already have an `extract_clips.sh` from a previous run, use the GUI's "Load Existing Clips Script" section to re-open the selection panel and extract a different subset of clips without re-running the full pipeline.
