#!/usr/bin/env python3
"""
StreamClipper - Analyze long-form MP4 streams and find short-form clip opportunities.

Requirements:
    pip install openai-whisper anthropic openai google-genai rich click

Also requires:
    - ffmpeg installed on system (brew install ffmpeg / apt install ffmpeg)
    - An API key for your chosen provider (see .env.example)
"""

import os
import re
import sys

# PyInstaller --windowed sets sys.stdout/stderr to None.  Guard here too
# so clip_finder works whether launched via gui.py or standalone.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
elif hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")
elif hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import json
import math
import tempfile
import subprocess
from pathlib import Path

# Hide console windows spawned by subprocess on Windows (PyInstaller --windowed)
_SUBPROCESS_FLAGS = (
    subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
)
from dataclasses import dataclass, asdict
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.table import Table
from rich.panel import Panel
from rich import print as rprint

console = Console(stderr=True)


# ── Data models ──────────────────────────────────────────────────────────────

@dataclass
class TranscriptSegment:
    start: float   # seconds
    end: float     # seconds
    text: str


@dataclass
class ClipSuggestion:
    rank: int
    title: str
    hook: str                    # Why someone would watch this
    segment_start: float         # 5-min window start (seconds)
    segment_end: float           # 5-min window end   (seconds)
    clip_start: float            # Exact clip start   (seconds)
    clip_end: float              # Exact clip end      (seconds)
    clip_duration: float         # seconds
    content_type: str            # "story", "advice", "moment", "debate", etc.
    virality_score: int          # 1-10
    transcript_excerpt: str


def fmt_time(seconds: float) -> str:
    """Convert seconds to HH:MM:SS string."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def parse_time(ts: str) -> float:
    """Convert HH:MM:SS or MM:SS to seconds."""
    parts = ts.strip().split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    elif len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(parts[0])


# ── Step 1: Extract audio ─────────────────────────────────────────────────────

def _get_duration(mp4_path: str) -> float | None:
    """Return the duration in seconds of a media file, or None on failure."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", mp4_path],
            capture_output=True, text=True,
            creationflags=_SUBPROCESS_FLAGS,
        )
        return float(result.stdout.strip())
    except (ValueError, OSError):
        return None


def extract_audio(mp4_path: str, output_wav: str,
                  audio_track: int | None = None,
                  progress_cb=None) -> None:
    """Extract mono 16kHz WAV from MP4 using ffmpeg.

    audio_track: 0-based index of the audio stream to extract (None = default/first track).
    progress_cb: optional callable(pct: int) called with 0-100 as extraction progresses.
    """
    track_label = f"track {audio_track}" if audio_track is not None else "default track"
    console.log(f"[cyan]Extracting audio from:[/cyan] {mp4_path} [dim]({track_label})[/dim]")
    out_dir = os.path.dirname(output_wav)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    duration = _get_duration(mp4_path) if progress_cb else None

    cmd = ["ffmpeg", "-y"]
    if progress_cb and duration and duration > 0:
        cmd += ["-progress", "pipe:2"]   # progress on stderr
    cmd += ["-i", mp4_path]
    if audio_track is not None:
        cmd += ["-map", f"0:a:{audio_track}"]
    cmd += [
        "-vn",                  # no video
        "-acodec", "pcm_s16le", # PCM WAV
        "-ar", "16000",         # 16 kHz (Whisper optimal)
        "-ac", "1",             # mono
        output_wav
    ]

    if progress_cb and duration and duration > 0:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE, text=True,
                                creationflags=_SUBPROCESS_FLAGS)
        for line in proc.stderr:
            line = line.strip()
            if line.startswith("out_time_us="):
                try:
                    us = int(line.split("=", 1)[1])
                    pct = min(100, int(us / (duration * 1_000_000) * 100))
                    progress_cb(pct)
                except (ValueError, ZeroDivisionError):
                    pass
        proc.wait()
        if proc.returncode != 0:
            console.print("[red]ffmpeg error during audio extraction[/red]")
            sys.exit(1)
        progress_cb(100)
    else:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                creationflags=_SUBPROCESS_FLAGS)
        if result.returncode != 0:
            console.print(f"[red]ffmpeg error:[/red]\n{result.stderr}")
            sys.exit(1)
    console.log("[green]✓ Audio extracted[/green]")


# ── Step 1b: Detect volume spikes ────────────────────────────────────────────

def detect_volume_spikes(
    wav_path: str,
    frame_ms: int = 25,
    hop_ms: int = 10,
    baseline_seconds: float = 15.0,
    spike_threshold: float = 2.0,
    min_spike_seconds: float = 0.3,
    merge_gap_seconds: float = 2.0,
) -> list[tuple[float, float, float]]:
    """Detect sudden volume spikes in a WAV file.

    Returns a list of (start_seconds, end_seconds, peak_intensity) tuples
    where peak_intensity is the multiplier above the rolling average.
    """
    import wave
    import numpy as np

    with wave.open(wav_path, "r") as wf:
        sample_rate = wf.getframerate()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)

    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

    if len(samples) == 0:
        return []

    frame_samples = int(sample_rate * frame_ms / 1000)
    hop_samples = int(sample_rate * hop_ms / 1000)

    if len(samples) < frame_samples:
        return []

    # Compute RMS per frame using sliding window
    frames = np.lib.stride_tricks.sliding_window_view(
        samples, frame_samples)[::hop_samples]
    rms = np.sqrt(np.mean(frames ** 2, axis=1))

    # Rolling average baseline
    baseline_frames = max(1, int(baseline_seconds / (hop_ms / 1000)))
    # For very short audio, just use the full-length mean
    if baseline_frames >= len(rms):
        rolling_avg = np.full_like(rms, np.mean(rms))
    else:
        kernel = np.ones(baseline_frames) / baseline_frames
        rolling_avg = np.convolve(rms, kernel, mode="same")

    # Avoid division by zero in silent regions
    rolling_avg = np.maximum(rolling_avg, np.finfo(np.float32).eps)

    ratio = rms / rolling_avg

    # Find contiguous regions above threshold
    above = ratio > spike_threshold
    spikes_raw: list[tuple[int, int, float]] = []
    i = 0
    while i < len(above):
        if above[i]:
            start = i
            while i < len(above) and above[i]:
                i += 1
            end = i
            duration_sec = (end - start) * hop_ms / 1000
            if duration_sec >= min_spike_seconds:
                peak = float(np.max(ratio[start:end]))
                spikes_raw.append((start, end, peak))
        else:
            i += 1

    if not spikes_raw:
        return []

    # Merge spikes within merge_gap_seconds
    merge_gap_frames = int(merge_gap_seconds / (hop_ms / 1000))
    merged: list[tuple[int, int, float]] = [spikes_raw[0]]
    for start, end, peak in spikes_raw[1:]:
        prev_start, prev_end, prev_peak = merged[-1]
        if start - prev_end <= merge_gap_frames:
            merged[-1] = (prev_start, end, max(prev_peak, peak))
        else:
            merged.append((start, end, peak))

    # Convert frame indices to seconds
    result = []
    for start, end, peak in merged:
        start_sec = start * hop_ms / 1000
        end_sec = end * hop_ms / 1000
        result.append((start_sec, end_sec, round(peak, 1)))

    console.log(f"[green]✓ Detected {len(result)} volume spike(s)[/green]")
    return result


def annotate_chunks_with_spikes(
    chunks: list[dict],
    spikes: list[tuple[float, float, float]],
) -> list[dict]:
    """Append volume spike annotations to chunk text before LLM analysis."""
    if not spikes:
        return chunks

    for chunk in chunks:
        w_start = chunk["window_start"]
        w_end = chunk["window_end"]
        # Find spikes overlapping this window
        hits = [
            (s, e, intensity) for s, e, intensity in spikes
            if s < w_end and e > w_start
        ]
        if hits:
            lines = ["\n\n[AUDIO ENERGY NOTES]"]
            for s, e, intensity in hits:
                dur = e - s
                lines.append(
                    f"- Volume spike at {fmt_time(s)} "
                    f"({intensity}x above average, {dur:.1f}s duration)"
                )
            chunk["text"] += "\n".join(lines)

    return chunks


def save_spikes(spikes: list[tuple[float, float, float]], path: str) -> None:
    """Save volume spikes to a JSON file."""
    data = [{"start": s, "end": e, "intensity": i} for s, e, i in spikes]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_spikes(path: str) -> list[tuple[float, float, float]]:
    """Load volume spikes from a JSON file."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return [(d["start"], d["end"], d["intensity"]) for d in data]
    except Exception:
        return []


def save_chunks(chunks: list[dict], path: str, total_duration: float = 0) -> None:
    """Save analysis chunks to a JSON file with metadata."""
    data = {
        "total_duration": total_duration,
        "chunk_count": len(chunks),
        "chunks": chunks,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_chunks(path: str) -> tuple[list[dict], float]:
    """Load analysis chunks from a JSON file.

    Returns (chunks_list, total_duration).
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data["chunks"], data.get("total_duration", 0)


def load_clips_json(path: str) -> list[ClipSuggestion]:
    """Load clip suggestions from a previously saved JSON file."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    results = []
    for d in data:
        # Strip the formatted time fields that save_results adds
        d.pop("segment_start_fmt", None)
        d.pop("segment_end_fmt", None)
        d.pop("clip_start_fmt", None)
        d.pop("clip_end_fmt", None)
        results.append(ClipSuggestion(**d))
    return results


# ── Step 2: Transcribe with Whisper ──────────────────────────────────────────

def transcribe_audio(wav_path: str, model_size: str = "base",
                     language: str = "en",
                     progress_cb=None) -> list[TranscriptSegment]:
    """Run OpenAI Whisper locally and return timestamped segments.

    progress_cb: optional callable(pct: int, label: str) called with 0-100
                 as transcription progresses. Passed the current segment
                 timestamp as a label.
    """
    try:
        import whisper
    except ImportError:
        console.print("[red]whisper not installed. Run: pip install openai-whisper[/red]")
        sys.exit(1)

    # Monkey-patch whisper.audio.load_audio to hide the ffmpeg console
    # window on Windows (it calls subprocess.run without CREATE_NO_WINDOW).
    if sys.platform == "win32":
        import whisper.audio as _wa
        _orig_load = _wa.load_audio
        def _patched_load(file, sr=16000):
            from subprocess import run as _run, CalledProcessError
            import numpy as np
            cmd = [
                "ffmpeg", "-nostdin", "-threads", "0",
                "-i", file, "-f", "s16le", "-ac", "1",
                "-acodec", "pcm_s16le", "-ar", str(sr), "-"
            ]
            try:
                out = _run(cmd, capture_output=True, check=True,
                           creationflags=_SUBPROCESS_FLAGS).stdout
            except CalledProcessError as e:
                raise RuntimeError(f"Failed to load audio: {e.stderr.decode()}") from e
            return np.frombuffer(out, np.int16).flatten().astype(np.float32) / 32768.0
        _wa.load_audio = _patched_load

    console.log(f"[cyan]Loading Whisper model:[/cyan] {model_size}")
    model = whisper.load_model(model_size)
    console.log("[cyan]Transcribing... (this may take a while for long files)[/cyan]")

    if progress_cb is not None:
        import wave, re as _re

        # Total duration lets us turn segment timestamps into a percentage.
        try:
            with wave.open(wav_path, "r") as wf:
                total_sec = wf.getnframes() / wf.getframerate()
        except Exception:
            total_sec = 0.0

        # Whisper uses MM:SS.sss below 1 h, then switches to HH:MM:SS.sss — match both.
        _ts_re = _re.compile(
            r"\[(\d+:\d+(?::\d+)?\.\d+)\s*-->\s*(\d+:\d+(?::\d+)?\.\d+)\]"
        )

        def _parse_ts(ts: str) -> float:
            parts = ts.split(":")
            if len(parts) == 3:                           # HH:MM:SS.sss
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
            return int(parts[0]) * 60 + float(parts[1])  # MM:SS.sss

        class _StdoutProxy:
            """Intercepts Whisper's verbose segment lines to extract progress."""
            def __init__(self, orig):
                self._orig = orig
            def write(self, text):
                if self._orig is not None:
                    self._orig.write(text)
                m = _ts_re.search(text)
                if m and total_sec > 0:
                    end_ts = _parse_ts(m.group(2))
                    pct = min(99, int(end_ts / total_sec * 100))
                    progress_cb(pct, m.group(2))
            def flush(self):
                if self._orig is not None:
                    self._orig.flush()

        import sys as _sys
        _orig = _sys.stdout
        _sys.stdout = _StdoutProxy(_orig)
        try:
            result = model.transcribe(wav_path, verbose=True,
                                      word_timestamps=False, language=language)
        finally:
            _sys.stdout = _orig
            progress_cb(100, "done")
    else:
        result = model.transcribe(wav_path, verbose=False,
                                  word_timestamps=False, language=language)

    segments = []
    for seg in result["segments"]:
        segments.append(TranscriptSegment(
            start=seg["start"],
            end=seg["end"],
            text=seg["text"].strip()
        ))

    console.log(f"[green]✓ Transcribed {len(segments)} segments[/green]")
    return segments


def load_transcript_from_json(path: str) -> list[TranscriptSegment]:
    """Load a previously saved transcript JSON."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return [TranscriptSegment(**s) for s in data]


def save_transcript(segments: list[TranscriptSegment], path: str) -> None:
    """Save transcript to JSON for reuse."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump([asdict(s) for s in segments], f, indent=2)
    console.log(f"[green]✓ Transcript saved to:[/green] {path}")


# ── Step 3: Chunk transcript into 5-minute windows ───────────────────────────

def chunk_transcript(
    segments: list[TranscriptSegment],
    window_minutes: int = 8,
    overlap_minutes: int = 1
) -> list[dict]:
    """
    Slide a window over the transcript and return text chunks with timestamps.
    Each chunk = ~window_minutes of content with overlap to avoid missing clips
    that straddle chunk boundaries.
    """
    window_sec = window_minutes * 60
    overlap_sec = overlap_minutes * 60
    step_sec = window_sec - overlap_sec

    if not segments:
        return []

    total_duration = segments[-1].end
    chunks = []
    t = 0.0

    while t < total_duration:
        chunk_end = t + window_sec
        chunk_segs = [s for s in segments if s.start >= t and s.start < chunk_end]
        if chunk_segs:
            text = " ".join(s.text for s in chunk_segs)
            chunks.append({
                "window_start": t,
                "window_end": min(chunk_end, total_duration),
                "text": text
            })
        t += step_sec

    console.log(f"[green]✓ Created {len(chunks)} analysis windows[/green]")
    return chunks


# ── Step 4: Analyze with Claude ──────────────────────────────────────────────

ANALYSIS_SYSTEM_PROMPT = """You are a clip-finding assistant. You receive a transcript window and return a single JSON object. You NEVER return markdown, explanations, or commentary — ONLY raw JSON.

TASK: Decide if the transcript contains a compelling 1-3 minute clip for TikTok/YouTube Shorts/Reels.

A great clip has ONE OR MORE of: a narrative arc, a surprising reveal, a funny/emotional moment, actionable advice, a debate moment, or a quotable one-liner.

YOU MUST USE THIS EXACT JSON SCHEMA — do not invent your own fields:

{"has_clip": true, "virality_score": 7, "content_type": "story", "title": "Short Title Here", "hook": "Why someone would watch this", "clip_start_offset": 30, "clip_end_offset": 150, "transcript_excerpt": "Best 1-2 sentences from the segment"}

RULES:
- "has_clip": boolean — true if there's a good clip, false if not
- "virality_score": integer 1-10
- "content_type": one of "story", "advice", "moment", "debate", "rant", "revelation", "other"
- "clip_start_offset": integer, seconds from the START of this window
- "clip_end_offset": integer, seconds from the START of this window
- clip_end_offset minus clip_start_offset must be between 60 and 180
- If no good clip exists, return EXACTLY: {"has_clip": false}
- Do NOT wrap in markdown fences. Do NOT add extra fields. Do NOT use a different schema.
- If the transcript contains [AUDIO ENERGY NOTES], these indicate moments where the speaker's volume spiked significantly (yelling, excitement, reactions). Treat these as strong positive signals for clip-worthiness — try to include these moments in your clip selection."""


_consecutive_errors = 0
_last_error_msg = ""


def build_system_prompt(custom_prompts: list[str] | None = None) -> str:
    """Return the analysis system prompt, optionally extended with custom
    search criteria supplied by the user."""
    if not custom_prompts:
        return ANALYSIS_SYSTEM_PROMPT
    extras = "\n".join(f"- {p.strip()}" for p in custom_prompts if p.strip())
    if not extras:
        return ANALYSIS_SYSTEM_PROMPT
    return (
        ANALYSIS_SYSTEM_PROMPT
        + "\n\nThe user has also asked you to look for the following "
        "specific things in the transcript. Prioritise these alongside "
        "the standard criteria above:\n"
        + extras
    )


def analyze_chunk(
    chunk: dict,
    client,
    model: str = "claude-opus-4-6",
    custom_prompts: list[str] | None = None,
) -> Optional[dict]:
    """Send a transcript chunk to the LLM for clip analysis.

    *client* can be either a ``providers.LLMClient`` (preferred) or a legacy
    ``anthropic.Anthropic`` instance for backward-compatibility.
    *custom_prompts* is an optional list of user-supplied search criteria
    to append to the system prompt.
    """
    global _consecutive_errors, _last_error_msg

    system_prompt = build_system_prompt(custom_prompts)

    window_duration = chunk["window_end"] - chunk["window_start"]
    user_prompt = (
        f"Window timestamps: {fmt_time(chunk['window_start'])} → {fmt_time(chunk['window_end'])} "
        f"({window_duration/60:.1f} min)\n\n"
        f"Transcript:\n{chunk['text']}\n\n"
        f"Respond with ONLY the JSON object. No markdown, no explanation, no code fences."
    )

    try:
        from providers import LLMClient
        if isinstance(client, LLMClient):
            raw = client.message(
                model=model,
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                max_tokens=600,
            )
        else:
            # Legacy Anthropic client fallback
            response = client.messages.create(
                model=model,
                max_tokens=600,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}]
            )
            raw = response.content[0].text
    except Exception as exc:
        exc_type = type(exc).__name__
        err_str = str(exc)
        _consecutive_errors += 1
        # Log full detail for the first 3 failures, then summarise
        if _consecutive_errors <= 3:
            console.log(f"[yellow]Warning: {exc_type} for chunk at "
                         f"{fmt_time(chunk['window_start'])}: {err_str}[/yellow]")
        elif _consecutive_errors == 4:
            console.log(f"[yellow]Suppressing further duplicate errors "
                         f"(same issue repeating)…[/yellow]")
        _last_error_msg = f"{exc_type}: {err_str}"
        return None

    # Reset consecutive error counter on success
    _consecutive_errors = 0

    raw = raw.strip()
    # Strip any accidental markdown fences
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Track JSON parse failures the same way as API errors so that
        # the GUI can distinguish "all windows failed" from "no clips"
        _consecutive_errors += 1
        preview = raw[:200] + ("…" if len(raw) > 200 else "")
        if _consecutive_errors <= 3:
            console.log(f"[yellow]Warning: Could not parse LLM response for "
                         f"chunk at {fmt_time(chunk['window_start'])}. "
                         f"Response preview: {preview!r}[/yellow]")
        elif _consecutive_errors == 4:
            console.log(f"[yellow]Suppressing further parse errors "
                         f"(same issue repeating)…[/yellow]")
        _last_error_msg = f"Unparseable response: {preview!r}"
        return None


# Keep old name as alias for backward-compatibility
analyze_chunk_with_claude = analyze_chunk


def find_clips(
    chunks: list[dict],
    client,
    top_n: int = 10,
    padding_seconds: float = 180,
    total_duration: float = 0,
    model: str = "claude-opus-4-6",
    max_workers: int = 1,
    custom_prompts: list[str] | None = None,
) -> list[ClipSuggestion]:
    """Analyze all chunks and return the top N clip suggestions.

    padding_seconds: seconds of context added before and after each identified
                     core clip, giving editors room to work (default 3 min).
    total_duration:  total audio length in seconds used to clamp the end of
                     padded clips (pass segments[-1].end).
    max_workers:     number of parallel analysis threads (>1 useful for
                     claude_code provider where each call is a subprocess).
    custom_prompts:  optional list of user-supplied search criteria appended
                     to the system prompt.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    candidates = []
    rank = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total} windows"),
        TimeElapsedColumn(),
        console=console
    ) as progress:
        task = progress.add_task("[cyan]Analyzing windows with LLM...", total=len(chunks))

        def _analyze(chunk):
            return chunk, analyze_chunk(chunk, client, model=model,
                                        custom_prompts=custom_prompts)

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(_analyze, c): c for c in chunks}
            for future in as_completed(futures):
                try:
                    chunk, result = future.result()
                except Exception:
                    progress.advance(task)
                    continue
                progress.advance(task)

                if not result or not result.get("has_clip"):
                    continue

                score = result.get("virality_score", 0)

                # Core clip as identified by Claude (clamped to window)
                core_start = chunk["window_start"] + result.get("clip_start_offset", 0)
                core_end   = chunk["window_start"] + result.get("clip_end_offset", 60)
                core_start = max(core_start, chunk["window_start"])
                core_end   = min(core_end,   chunk["window_end"])

                if core_end - core_start < 30:  # Skip tiny fragments
                    continue

                # Expand with padding for editing headroom
                clip_start = max(0.0, core_start - padding_seconds)
                clip_end   = core_end + padding_seconds
                if total_duration > 0:
                    clip_end = min(clip_end, total_duration)
                duration = clip_end - clip_start

                candidates.append({
                    "chunk": chunk,
                    "result": result,
                    "core_start": core_start,
                    "core_end":   core_end,
                    "clip_start": clip_start,
                    "clip_end":   clip_end,
                    "duration":   duration,
                    "score":      score,
                })

    # Sort by virality score descending, deduplicate on padded ranges
    candidates.sort(key=lambda x: x["score"], reverse=True)
    selected = []
    used_ranges = []

    for c in candidates:
        cs, ce = c["clip_start"], c["clip_end"]
        overlap = any(
            not (ce <= s or cs >= e) for s, e in used_ranges
        )
        if not overlap:
            used_ranges.append((cs, ce))
            rank += 1
            r = c["result"]
            selected.append(ClipSuggestion(
                rank=rank,
                title=r.get("title", "Untitled Clip"),
                hook=r.get("hook", ""),
                segment_start=c["chunk"]["window_start"],
                segment_end=c["chunk"]["window_end"],
                clip_start=cs,
                clip_end=ce,
                clip_duration=c["duration"],
                content_type=r.get("content_type", "other"),
                virality_score=r.get("virality_score", 0),
                transcript_excerpt=r.get("transcript_excerpt", "")
            ))
            if len(selected) >= top_n:
                break

    return selected


# ── Step 5: Output ────────────────────────────────────────────────────────────

def print_results(clips: list[ClipSuggestion]) -> None:
    """Pretty-print results to the terminal."""
    console.print()
    console.print(Panel.fit(
        f"[bold white]Found {len(clips)} clip suggestions[/bold white]",
        border_style="cyan"
    ))

    for clip in clips:
        score_bar = "█" * clip.virality_score + "░" * (10 - clip.virality_score)
        console.print()
        console.print(Panel(
            f"[bold yellow]#{clip.rank} — {clip.title}[/bold yellow]\n"
            f"[dim]{clip.content_type.upper()}[/dim]  Virality: [green]{score_bar}[/green] {clip.virality_score}/10\n\n"
            f"[cyan]Hook:[/cyan] {clip.hook}\n\n"
            f"[cyan]5-min source window:[/cyan]  {fmt_time(clip.segment_start)} → {fmt_time(clip.segment_end)}\n"
            f"[cyan]Clip timestamps:[/cyan]      [bold green]{fmt_time(clip.clip_start)} → {fmt_time(clip.clip_end)}[/bold green]  "
            f"([bold]{clip.clip_duration:.0f}s / {clip.clip_duration/60:.1f}min[/bold])\n\n"
            f"[dim italic]\"{clip.transcript_excerpt}\"[/dim italic]",
            border_style="dim white"
        ))


def save_results(clips: list[ClipSuggestion], output_path: str) -> None:
    """Save results as JSON."""
    data = []
    for clip in clips:
        d = asdict(clip)
        d["segment_start_fmt"] = fmt_time(clip.segment_start)
        d["segment_end_fmt"] = fmt_time(clip.segment_end)
        d["clip_start_fmt"] = fmt_time(clip.clip_start)
        d["clip_end_fmt"] = fmt_time(clip.clip_end)
        data.append(d)

    parent = os.path.dirname(output_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    console.log(f"[green]✓ Results saved to:[/green] {output_path}")


def export_ffmpeg_commands(clips: list[ClipSuggestion], mp4_path: str, output_dir: str) -> str:
    """Generate an ffmpeg shell script to cut all suggested clips."""
    lines = ["#!/bin/bash", f"# Auto-generated clip extraction script", f"# Source: {mp4_path}", ""]
    os.makedirs(output_dir, exist_ok=True)

    for clip in clips:
        safe_title = "".join(c if c.isalnum() or c in "-_ " else "" for c in clip.title)
        safe_title = safe_title.replace(" ", "_")[:50]
        out_file = f"{output_dir}/clip_{clip.rank:02d}_{safe_title}.mp4"
        duration = clip.clip_end - clip.clip_start
        lines.append(f"# Clip {clip.rank}: {clip.title} ({fmt_time(clip.clip_start)} → {fmt_time(clip.clip_end)})")
        lines.append(
            f'ffmpeg -ss {clip.clip_start:.2f} -i "{mp4_path}" '
            f'-t {duration:.2f} -c:v copy -c:a aac -b:a 192k "{out_file}"'
        )
        lines.append("")

    script_path = os.path.join(output_dir, "extract_clips.sh")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    os.chmod(script_path, 0o755)
    return script_path


# ── Per-clip helpers (transcript slice + editing prompt) ─────────────────────

def clip_transcript_segments(
    segments: list[TranscriptSegment],
    clip_start: float,
    clip_end: float,
) -> list[TranscriptSegment]:
    """Return only the segments that overlap [clip_start, clip_end]."""
    return [s for s in segments if s.end > clip_start and s.start < clip_end]


def save_clip_transcript(
    segments: list[TranscriptSegment],
    clip_start: float,
    clip_end: float,
    path: str,
) -> list[TranscriptSegment]:
    """Filter the full transcript to the clip window and save as JSON.

    Returns the filtered segment list so callers can reuse it.
    """
    clip_segs = clip_transcript_segments(segments, clip_start, clip_end)
    data = [{"start": s.start, "end": s.end, "text": s.text} for s in clip_segs]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return clip_segs


def build_editing_prompt(clip, clip_segments: list[TranscriptSegment]) -> str:
    """Return a ready-to-paste LLM prompt for editing a single clip into a short."""
    duration_s  = clip.clip_end - clip.clip_start
    content_tag = getattr(clip, "content_type", "unknown")
    virality    = getattr(clip, "virality_score", "—")
    hook_note   = getattr(clip, "hook", "")

    if clip_segments:
        transcript_text = "\n".join(
            f"[{fmt_time(s.start)}]  {s.text.strip()}"
            for s in clip_segments
        )
    else:
        transcript_text = "(transcript not available)"

    return f"""\
You are an expert short-form video editor.
Your job is to turn a raw stream clip into a punchy, engaging short (60–150 seconds).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CLIP METADATA
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Rank:             #{clip.rank}
  Title:            {clip.title}
  Content type:     {content_tag}
  Virality score:   {virality}/10
  Source range:     {fmt_time(clip.clip_start)} → {fmt_time(clip.clip_end)}
  Available length: {duration_s:.0f} s  ({duration_s / 60:.1f} min)
  Auto-detected hook note:
    {hook_note}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TRANSCRIPT  (timestamps are relative to the original source file)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{transcript_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YOUR TASK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Produce an editing outline that follows this story structure:

  1. HOOK (first ~5–15 s)
     The single most attention-grabbing moment in the clip.
     Can be a provocative statement, a surprising reveal, a question,
     or the climactic beat brought to the very start.

  2. CONFLICT / TENSION  (include only if naturally present)
     A problem being solved, a challenge faced, or tension that
     builds curiosity and makes the payoff feel earned.

  3. PAYOFF / CONCLUSION
     The satisfying resolution, key insight, result, or call-to-action
     that gives viewers a reason to have watched.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CUT LIST RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• List every segment to keep as a precise time range.
• Timestamps MUST be relative to the original source file (not the clip file).
• REMOVE: pauses longer than 1 s, filler words / phrases
  (um, uh, like, you know, sort of, basically, I mean, right?),
  false starts, repeated words, off-topic tangents.
• Segments MAY be reordered to improve story flow — flag this if so.
• The sum of all segment durations MUST be between 60 and 150 seconds.
• Aim for natural sentence/thought breaks at cut points.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RESPOND IN EXACTLY THIS FORMAT  (no extra commentary outside it)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PURPOSE:
[One sentence — what is this clip about and why will viewers care?]

HOOK:
[Describe the hook moment and why it grabs attention]

CONFLICT:
[Describe the tension/problem, or write: N/A]

PAYOFF:
[Describe the resolution, key insight, or takeaway]

CUT LIST:
1. [HH:MM:SS.s] → [HH:MM:SS.s] | [what's happening / why keep it]
2. [HH:MM:SS.s] → [HH:MM:SS.s] | [what's happening / why keep it]
... (one line per segment, no gaps)

ESTIMATED TOTAL: [X] seconds
REORDERED: [Yes — explain / No]
NOTES: [Optional: music mood, caption style, thumbnail idea, B-roll suggestions]
"""


def save_editing_prompt(clip, clip_segments: list[TranscriptSegment], path: str) -> None:
    """Write the LLM editing prompt for a clip to a .txt file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(build_editing_prompt(clip, clip_segments))


# ── Timestamp pattern shared by parse_cut_list ───────────────────────────────
# Matches  HH:MM:SS  HH:MM:SS.s  MM:SS  MM:SS.s  (with or without brackets)
_TS = r"\[?(\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?)\]?"
_CUT_RE = re.compile(
    rf"^\s*\d+[.)]\s*{_TS}\s*[→\-–>]+\s*{_TS}\s*[|]?\s*(.*)",
    re.MULTILINE,
)


def parse_cut_list(text: str) -> list[dict]:
    """Parse a CUT LIST block from a Claude edit-plan response.

    Returns a list of dicts::

        {"start": <float seconds>, "end": <float seconds>, "reason": <str>}

    Timestamps are returned as-is (source-file relative).  The caller is
    responsible for adjusting them to be clip-relative if needed.
    """
    cuts = []
    for m in _CUT_RE.finditer(text):
        try:
            start  = parse_time(m.group(1))
            end    = parse_time(m.group(2))
            reason = m.group(3).strip()
            if end > start:
                cuts.append({"start": start, "end": end, "reason": reason})
        except (ValueError, IndexError):
            continue
    return cuts


def snap_cut_end(
    cut_end: float,
    segments: list[TranscriptSegment],
    padding: float = 2.0,
    hard_limit: float | None = None,
) -> float:
    """Extend a cut's end point so it doesn't land mid-sentence.

    Finds the Whisper segment whose *start* is closest to (but not after)
    ``cut_end``, then uses that segment's ``end`` as the new boundary.
    ``padding`` extra seconds are added after that to avoid a hard cut on
    the very last word.  The result is clamped to ``hard_limit`` when given.

    If no matching segment is found the original ``cut_end`` is returned
    (plus padding, clamped).
    """
    candidates = [s for s in segments if s.start <= cut_end]
    if candidates:
        snapped = max(candidates, key=lambda s: s.start).end
        # Never go backwards — if the segment ended before cut_end, keep cut_end
        snapped = max(snapped, cut_end)
    else:
        snapped = cut_end

    result = snapped + padding
    if hard_limit is not None:
        result = min(result, hard_limit)
    return result


# ── Per-clip extraction (refactored from gui.py) ──────────────────────────────

def extract_clip_with_assets(
    clip: ClipSuggestion,
    mp4_path: str,
    output_dir: str,
    segments: list[TranscriptSegment] | None = None,
) -> dict:
    """Extract a single clip MP4 and its sidecar assets (transcript, editing prompt).

    Returns a dict with paths to the created files.
    """
    safe = "".join(c if c.isalnum() or c in "-_ " else ""
                   for c in clip.title).replace(" ", "_")[:50]
    clip_name = f"clip_{clip.rank:02d}_{safe}"
    clip_dir = Path(output_dir) / clip_name
    clip_dir.mkdir(parents=True, exist_ok=True)

    out_file = clip_dir / f"{clip_name}.mp4"
    duration = clip.clip_end - clip.clip_start

    # Extract video segment
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{clip.clip_start:.2f}",
        "-i", mp4_path,
        "-t", f"{duration:.2f}",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        str(out_file)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True,
                            encoding="utf-8", errors="replace",
                            creationflags=_SUBPROCESS_FLAGS)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg error: {result.stderr[-400:]}")

    info = {
        "clip_name": clip_name,
        "clip_dir": str(clip_dir),
        "mp4": str(out_file),
        "rank": clip.rank,
        "title": clip.title,
        "clip_start": clip.clip_start,
        "clip_end": clip.clip_end,
        "duration": duration,
    }

    # Clip transcript
    if segments:
        transcript_out = clip_dir / f"{clip_name}_transcript.json"
        try:
            clip_segs = save_clip_transcript(
                segments, clip.clip_start, clip.clip_end,
                str(transcript_out)
            )
            info["transcript"] = str(transcript_out)
            info["segment_count"] = len(clip_segs)
        except Exception:
            clip_segs = []
    else:
        clip_segs = []

    # Editing prompt
    prompt_out = clip_dir / f"{clip_name}_editing_prompt.txt"
    try:
        save_editing_prompt(clip, clip_segs, str(prompt_out))
        info["editing_prompt"] = str(prompt_out)
    except Exception:
        pass

    return info


def generate_slices(
    clip_dir: str,
    client,
    model: str,
    editing_notes: str = "",
    premiere: bool = False,
) -> dict:
    """Generate editing slices for a clip directory using LLM analysis.

    Refactored from gui.py._generate_slices_worker for CLI use.
    Returns a dict with slice info.
    """
    clip_dir_p = Path(clip_dir)

    # Locate files
    mp4s = [f for f in sorted(clip_dir_p.glob("*.mp4"))
            if not f.stem.startswith("slice_")]
    prompts = sorted(clip_dir_p.glob("*_editing_prompt.txt"))
    transcripts = sorted(clip_dir_p.glob("*_transcript.json"))

    if not mp4s:
        raise FileNotFoundError("No clip .mp4 found in folder.")
    if not prompts:
        raise FileNotFoundError("No _editing_prompt.txt found. Run extraction first.")

    clip_mp4 = mp4s[0]
    prompt_path = prompts[0]

    with open(prompt_path, encoding="utf-8") as f:
        prompt_text = f.read()

    if editing_notes:
        prompt_text += (
            "\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "ADDITIONAL EDITING NOTES FROM THE USER\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Follow these instructions alongside the standard rules above:\n\n"
            f"{editing_notes}\n"
        )

    # Parse clip_start / clip_end from prompt metadata
    clip_start = 0.0
    clip_end = float("inf")
    m = re.search(r"Source range:\s*(\d+:\d+:\d+)\s*[→\-]+\s*(\d+:\d+:\d+)", prompt_text)
    if m:
        clip_start = parse_time(m.group(1))
        clip_end = parse_time(m.group(2))

    # Load transcript segments for sentence-boundary snapping
    segments: list[TranscriptSegment] = []
    if transcripts:
        try:
            segments = load_transcript_from_json(str(transcripts[0]))
        except Exception:
            pass

    # Send prompt to LLM
    console.log(f"[cyan]Sending editing prompt to LLM ({model})...[/cyan]")
    edit_plan = client.message(
        model=model,
        user_prompt=prompt_text,
        max_tokens=4096,
    )

    plan_path = clip_dir_p / f"{clip_mp4.stem}_edit_plan.txt"
    with open(plan_path, "w", encoding="utf-8") as f:
        f.write(edit_plan)
    console.log(f"[green]Edit plan saved: {plan_path.name}[/green]")

    # Parse cut list
    cuts = parse_cut_list(edit_plan)
    if not cuts:
        return {
            "clip_dir": str(clip_dir_p),
            "edit_plan_path": str(plan_path),
            "slices": [],
            "error": "Could not parse any cuts from LLM response.",
        }

    # Remove old slices
    for old in sorted(clip_dir_p.glob("slice_*.mp4")):
        try:
            old.unlink()
        except OSError:
            pass

    # Extract each slice
    total_dur = 0.0
    written = 0
    slices = []
    for idx, cut in enumerate(cuts, 1):
        raw_end = cut["end"]
        snapped_end = snap_cut_end(
            raw_end, segments, padding=2.0,
            hard_limit=clip_end if clip_end < float("inf") else None,
        )

        ss = max(0.0, cut["start"] - clip_start)
        duration = snapped_end - cut["start"]
        if duration <= 0:
            continue

        slice_path = clip_dir_p / f"slice_{idx:02d}.mp4"
        cmd = [
            "ffmpeg", "-y",
            "-ss", f"{ss:.3f}",
            "-i", str(clip_mp4),
            "-t", f"{duration:.3f}",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            str(slice_path),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True,
                             encoding="utf-8", errors="replace",
                             creationflags=_SUBPROCESS_FLAGS)
        if res.returncode == 0:
            total_dur += duration
            written += 1
            slices.append({
                "index": idx,
                "path": str(slice_path),
                "duration": round(duration, 1),
                "reason": cut["reason"],
            })

    result = {
        "clip_dir": str(clip_dir_p),
        "edit_plan_path": str(plan_path),
        "slices": slices,
        "total_duration": round(total_dur, 1),
        "slice_count": written,
    }

    # Generate Premiere setup prompt if requested
    if premiere:
        import re as _re
        folder_name = clip_dir_p.name
        clip_num_m = _re.search(r"clip[_\s]*(\d+)", folder_name, _re.IGNORECASE)
        seq_name = (f"clip_{int(clip_num_m.group(1)):02d}_Shorts"
                    if clip_num_m else f"{folder_name}_Shorts")

        premiere_prompt = (
            f"# Premiere Pro Setup\n\n"
            f"1. Import all files from: {str(clip_dir_p).replace(chr(92), '/')}\n"
            f"2. Create sequence named: {seq_name}\n"
            f"3. Place slices in order on timeline\n"
        )
        prompt_path_pr = clip_dir_p / "premiere_setup_prompt.md"
        try:
            prompt_path_pr.write_text(premiere_prompt, encoding="utf-8")
            result["premiere_prompt_path"] = str(prompt_path_pr)
        except Exception:
            pass

    return result


# ── CLI ───────────────────────────────────────────────────────────────────────

_ALL_PROVIDERS = ["anthropic", "openai", "gemini", "grok", "ollama", "claude_code"]


def _output(data: dict | list, fmt: str):
    """Print structured output — JSON to stdout, human-readable to stderr."""
    if fmt == "json":
        click.echo(json.dumps(data, indent=2))
    else:
        for k, v in (data if isinstance(data, dict) else {"result": data}).items():
            click.echo(f"  {k}: {v}", err=True)


def _error_json(msg: str, exit_code: int = 1):
    """Print a JSON error envelope to stdout and exit."""
    click.echo(json.dumps({"error": msg, "exit_code": exit_code}))
    sys.exit(exit_code)


def _resolve_provider(provider: str, llm_model: str | None, api_key: str | None,
                      base_url: str | None):
    """Resolve provider config and return (client, model, prov_info)."""
    from providers import PROVIDERS, make_client

    prov_info = PROVIDERS.get(provider)
    if not prov_info:
        _error_json(f"Unknown provider: {provider}")

    model = llm_model or prov_info["default_model"]

    if provider == "ollama":
        key = "ollama"
        url = base_url or prov_info.get("base_url", "http://localhost:11434")
    elif provider == "claude_code":
        key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        url = base_url or ""
    else:
        key = api_key or os.environ.get(prov_info["env_key"], "")
        url = base_url or ""
        if not key:
            _error_json(f"{prov_info['env_key']} not set and no --api-key provided.")

    client = make_client(provider, key, base_url=url)
    return client, model, prov_info


def provider_options(f):
    """Shared click options for LLM provider/model/key/url."""
    f = click.option("--provider", default="claude_code",
                     type=click.Choice(_ALL_PROVIDERS),
                     help="LLM provider. Default: claude_code")(f)
    f = click.option("--model", "llm_model", default=None,
                     help="LLM model ID (defaults to provider's best model)")(f)
    f = click.option("--api-key", default=None,
                     help="API key (defaults to env var for the provider)")(f)
    f = click.option("--base-url", default=None,
                     help="Custom API base URL (for ollama, etc.)")(f)
    return f


# ── Command metadata registry for the `commands` subcommand ──────────────────

_COMMAND_META: dict[str, dict] = {}

def _register_meta(name: str, inputs: list[dict], outputs: list[dict]):
    _COMMAND_META[name] = {"inputs": inputs, "outputs": outputs}


# ── Click group ──────────────────────────────────────────────────────────────

@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx):
    """Trik_Klip — Long-form stream to short-form clip pipeline.

    Run any subcommand with --help for details, or use 'commands' for
    a machine-readable directory of all available commands.
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# ── extract-audio ────────────────────────────────────────────────────────────

@cli.command("extract-audio")
@click.argument("mp4_file", type=click.Path(exists=True))
@click.option("--output", "-o", default=None, help="Output WAV path (default: <input_stem>.wav)")
@click.option("--audio-track", default=None, type=int,
              help="0-based audio stream index (default: first track)")
@click.option("--format", "fmt", default="json", type=click.Choice(["json", "human"]),
              help="Output format. Default: json")
def cmd_extract_audio(mp4_file, output, audio_track, fmt):
    """Extract mono 16kHz WAV audio from an MP4 file."""
    try:
        if output is None:
            output = str(Path(mp4_file).with_suffix(".wav"))
        extract_audio(mp4_file, output, audio_track=audio_track)
        _output({"wav_path": output, "source": mp4_file}, fmt)
    except Exception as exc:
        _error_json(str(exc))

_register_meta("extract-audio",
    inputs=[{"name": "mp4_file", "type": "path", "required": True}],
    outputs=[{"name": "wav_path", "type": "path"}])


# ── detect-spikes ────────────────────────────────────────────────────────────

@cli.command("detect-spikes")
@click.argument("wav_file", type=click.Path(exists=True))
@click.option("--output", "-o", default=None, help="Output spikes JSON path")
@click.option("--spike-threshold", default=2.0, help="Multiplier above rolling avg. Default: 2.0")
@click.option("--baseline-seconds", default=15.0, help="Rolling average window. Default: 15.0")
@click.option("--min-spike-seconds", default=0.3, help="Min spike duration. Default: 0.3")
@click.option("--merge-gap-seconds", default=2.0, help="Gap for merging spikes. Default: 2.0")
@click.option("--format", "fmt", default="json", type=click.Choice(["json", "human"]),
              help="Output format. Default: json")
def cmd_detect_spikes(wav_file, output, spike_threshold, baseline_seconds,
                      min_spike_seconds, merge_gap_seconds, fmt):
    """Detect volume spikes in extracted audio."""
    try:
        if output is None:
            output = str(Path(wav_file).with_suffix("")) + "_spikes.json"
        spikes = detect_volume_spikes(
            wav_file,
            spike_threshold=spike_threshold,
            baseline_seconds=baseline_seconds,
            min_spike_seconds=min_spike_seconds,
            merge_gap_seconds=merge_gap_seconds,
        )
        save_spikes(spikes, output)
        _output({
            "spikes_path": output,
            "spike_count": len(spikes),
            "spikes": [{"start": s, "end": e, "intensity": i} for s, e, i in spikes],
        }, fmt)
    except Exception as exc:
        _error_json(str(exc))

_register_meta("detect-spikes",
    inputs=[{"name": "wav_file", "type": "path", "required": True}],
    outputs=[{"name": "spikes_path", "type": "path"}])


# ── transcribe ───────────────────────────────────────────────────────────────

@cli.command("transcribe")
@click.argument("wav_file", type=click.Path(exists=True))
@click.option("--output", "-o", default=None, help="Output transcript JSON path")
@click.option("--whisper-model", default="base",
              type=click.Choice(["tiny", "base", "small", "medium", "large"]),
              help="Whisper model size. Default: base")
@click.option("--language", default="en", help="Language code. Default: en")
@click.option("--format", "fmt", default="json", type=click.Choice(["json", "human"]),
              help="Output format. Default: json")
def cmd_transcribe(wav_file, output, whisper_model, language, fmt):
    """Transcribe audio using Whisper."""
    try:
        if output is None:
            output = str(Path(wav_file).with_suffix("")) + "_transcript.json"
        segments = transcribe_audio(wav_file, model_size=whisper_model, language=language)
        save_transcript(segments, output)
        total_dur = segments[-1].end if segments else 0
        _output({
            "transcript_path": output,
            "segment_count": len(segments),
            "duration_seconds": round(total_dur, 1),
        }, fmt)
    except Exception as exc:
        _error_json(str(exc))

_register_meta("transcribe",
    inputs=[{"name": "wav_file", "type": "path", "required": True}],
    outputs=[{"name": "transcript_path", "type": "path"}])


# ── chunk ────────────────────────────────────────────────────────────────────

@cli.command("chunk")
@click.argument("transcript_json", type=click.Path(exists=True))
@click.option("--output", "-o", default=None, help="Output chunks JSON path")
@click.option("--window-minutes", default=8, help="Window size in minutes. Default: 8")
@click.option("--overlap-minutes", default=1, help="Overlap in minutes. Default: 1")
@click.option("--spikes", default=None, type=click.Path(exists=True),
              help="Path to spikes JSON for annotation")
@click.option("--format", "fmt", default="json", type=click.Choice(["json", "human"]),
              help="Output format. Default: json")
def cmd_chunk(transcript_json, output, window_minutes, overlap_minutes, spikes, fmt):
    """Chunk a transcript into analysis windows and optionally annotate with volume spikes."""
    try:
        if output is None:
            output = str(Path(transcript_json).with_suffix("")) + "_chunks.json"
        segments = load_transcript_from_json(transcript_json)
        if not segments:
            _error_json("No transcript segments found.")
        total_duration = segments[-1].end
        chunks = chunk_transcript(segments, window_minutes=window_minutes,
                                  overlap_minutes=overlap_minutes)
        if spikes:
            spike_data = load_spikes(spikes)
            chunks = annotate_chunks_with_spikes(chunks, spike_data)
        save_chunks(chunks, output, total_duration=total_duration)
        _output({
            "chunks_path": output,
            "chunk_count": len(chunks),
            "total_duration_seconds": round(total_duration, 1),
        }, fmt)
    except Exception as exc:
        _error_json(str(exc))

_register_meta("chunk",
    inputs=[{"name": "transcript_json", "type": "path", "required": True}],
    outputs=[{"name": "chunks_path", "type": "path"}])


# ── analyze ──────────────────────────────────────────────────────────────────

@cli.command("analyze")
@click.argument("chunks_json", type=click.Path(exists=True))
@click.option("--output", "-o", default=None, help="Output clips JSON path")
@click.option("--top-n", default=10, help="Max clips to return. Default: 10")
@click.option("--padding-minutes", default=3.0, type=float,
              help="Context padding in minutes. Default: 3")
@click.option("--max-workers", default=None, type=int,
              help="Parallel threads (default: 1, auto 4 for claude_code)")
@click.option("--custom-prompt", multiple=True,
              help="Custom search criteria (repeatable)")
@click.option("--format", "fmt", default="json", type=click.Choice(["json", "human"]),
              help="Output format. Default: json")
@provider_options
def cmd_analyze(chunks_json, output, top_n, padding_minutes, max_workers,
                custom_prompt, fmt, provider, llm_model, api_key, base_url):
    """Run LLM analysis on transcript chunks to find clip candidates."""
    try:
        if output is None:
            output = str(Path(chunks_json).with_suffix("")) + "_clips.json"
        chunks, total_duration = load_chunks(chunks_json)
        client, model, _ = _resolve_provider(provider, llm_model, api_key, base_url)

        if max_workers is None:
            max_workers = 4 if provider == "claude_code" else 1

        custom_list = list(custom_prompt) if custom_prompt else None
        clips = find_clips(
            chunks, client, top_n=top_n,
            padding_seconds=padding_minutes * 60,
            total_duration=total_duration,
            model=model,
            max_workers=max_workers,
            custom_prompts=custom_list,
        )
        if clips:
            save_results(clips, output)
        _output({
            "clips_path": output,
            "clip_count": len(clips),
            "clips": [asdict(c) for c in clips],
        }, fmt)
    except Exception as exc:
        _error_json(str(exc))

_register_meta("analyze",
    inputs=[{"name": "chunks_json", "type": "path", "required": True}],
    outputs=[{"name": "clips_path", "type": "path"}])


# ── extract ──────────────────────────────────────────────────────────────────

@cli.command("extract")
@click.argument("mp4_file", type=click.Path(exists=True))
@click.argument("clips_json", type=click.Path(exists=True))
@click.option("--output-dir", "-o", default="./clips", help="Output directory. Default: ./clips")
@click.option("--transcript", default=None, type=click.Path(exists=True),
              help="Path to transcript JSON for per-clip transcript slicing")
@click.option("--format", "fmt", default="json", type=click.Choice(["json", "human"]),
              help="Output format. Default: json")
def cmd_extract(mp4_file, clips_json, output_dir, transcript, fmt):
    """Extract clip MP4s and sidecar assets from source video."""
    try:
        clips = load_clips_json(clips_json)
        segments = load_transcript_from_json(transcript) if transcript else None

        os.makedirs(output_dir, exist_ok=True)
        extracted = []
        for clip in clips:
            console.log(f"[cyan]Extracting #{clip.rank}: {clip.title}[/cyan]")
            try:
                info = extract_clip_with_assets(clip, mp4_file, output_dir, segments)
                extracted.append(info)
                console.log(f"[green]  Done: {info['clip_name']}[/green]")
            except Exception as exc:
                console.log(f"[red]  Failed: {exc}[/red]")

        _output({
            "output_dir": output_dir,
            "extracted_count": len(extracted),
            "extracted": extracted,
        }, fmt)
    except Exception as exc:
        _error_json(str(exc))

_register_meta("extract",
    inputs=[
        {"name": "mp4_file", "type": "path", "required": True},
        {"name": "clips_json", "type": "path", "required": True},
    ],
    outputs=[{"name": "output_dir", "type": "directory"}])


# ── generate-slices ──────────────────────────────────────────────────────────

@cli.command("generate-slices")
@click.argument("clip_dir", type=click.Path(exists=True))
@click.option("--editing-notes", default="", help="Custom editing instructions")
@click.option("--premiere/--no-premiere", default=False,
              help="Generate Premiere setup prompt")
@click.option("--format", "fmt", default="json", type=click.Choice(["json", "human"]),
              help="Output format. Default: json")
@provider_options
def cmd_generate_slices(clip_dir, editing_notes, premiere, fmt,
                        provider, llm_model, api_key, base_url):
    """Generate editing slices for an extracted clip directory using LLM."""
    try:
        client, model, _ = _resolve_provider(provider, llm_model, api_key, base_url)
        result = generate_slices(
            clip_dir, client, model,
            editing_notes=editing_notes,
            premiere=premiere,
        )
        _output(result, fmt)
    except Exception as exc:
        _error_json(str(exc))

_register_meta("generate-slices",
    inputs=[{"name": "clip_dir", "type": "directory", "required": True}],
    outputs=[{"name": "slices", "type": "list"}])


# ── providers ────────────────────────────────────────────────────────────────

@cli.command("providers")
@click.option("--format", "fmt", default="json", type=click.Choice(["json", "human"]),
              help="Output format. Default: json")
def cmd_providers(fmt):
    """List available LLM providers and their models."""
    from providers import PROVIDERS
    result = []
    for name, info in PROVIDERS.items():
        env_key = info.get("env_key", "")
        result.append({
            "name": name,
            "label": info.get("label", name),
            "env_key": env_key,
            "key_configured": bool(os.environ.get(env_key)) if env_key else True,
            "default_model": info.get("default_model", ""),
            "models": info.get("models", []),
        })
    _output({"providers": result}, fmt)


# ── commands ─────────────────────────────────────────────────────────────────

@cli.command("commands")
@click.option("--format", "fmt", default="json", type=click.Choice(["json", "human"]),
              help="Output format. Default: json")
def cmd_commands(fmt):
    """Machine-readable directory of all available CLI commands for AI agents."""
    cmds = []
    for name, cmd in sorted(cli.commands.items()):
        if name == "commands":
            continue
        options = []
        for param in cmd.params:
            if isinstance(param, click.Argument):
                continue
            default = param.default
            # Serialize non-JSON-safe defaults to string
            try:
                json.dumps(default)
            except (TypeError, ValueError):
                default = str(default) if default is not None else None
            opt = {
                "name": param.opts[0] if param.opts else param.name,
                "type": param.type.name if hasattr(param.type, "name") else str(param.type),
                "required": param.required,
                "default": default,
                "help": param.help or "",
            }
            options.append(opt)

        meta = _COMMAND_META.get(name, {})
        cmds.append({
            "name": name,
            "description": cmd.help or "",
            "options": options,
            "inputs": meta.get("inputs", []),
            "outputs": meta.get("outputs", []),
        })

    _output(cmds, fmt)


# ── run (full pipeline) ─────────────────────────────────────────────────────

@cli.command("run")
@click.argument("mp4_file", type=click.Path(exists=True))
@click.option("--whisper-model", default="base",
              type=click.Choice(["tiny", "base", "small", "medium", "large"]),
              help="Whisper model size. Default: base")
@click.option("--top-n", default=10, help="Max clip suggestions. Default: 10")
@click.option("--window-minutes", default=5, help="Analysis window in minutes. Default: 5")
@click.option("--transcript", default=None, help="Path to existing transcript JSON")
@click.option("--save-transcript", "save_transcript_path", default=None,
              help="Path to save transcript JSON")
@click.option("--output-json", default=None, help="Path to save results JSON")
@click.option("--export-clips-dir", default=None,
              help="Directory for ffmpeg clip extraction script")
@click.option("--audio-track", default=None, type=int,
              help="0-based audio stream index")
@click.option("--padding-minutes", default=3, type=float,
              help="Context padding in minutes. Default: 3")
@click.option("--max-workers", default=None, type=int,
              help="Parallel analysis threads")
@click.option("--custom-prompt", multiple=True,
              help="Custom search criteria (repeatable)")
@click.option("--format", "fmt", default="json", type=click.Choice(["json", "human"]),
              help="Output format. Default: json")
@provider_options
def cmd_run(
    mp4_file, whisper_model, top_n, window_minutes, transcript,
    save_transcript_path, output_json, export_clips_dir, audio_track,
    padding_minutes, max_workers, custom_prompt, fmt,
    provider, llm_model, api_key, base_url,
):
    """Full pipeline: transcribe, analyze, and find clips in a long-form MP4.

    Example:
        python clip_finder.py run stream.mp4 --whisper-model small --top-n 10
    """
    try:
        client, model, _ = _resolve_provider(provider, llm_model, api_key, base_url)

        if max_workers is None:
            max_workers = 4 if provider == "claude_code" else 1

        console.print(Panel.fit(
            "[bold cyan]StreamClipper[/bold cyan]\n[dim]Long-form -> Short-form clip finder[/dim]",
            border_style="cyan"
        ))

        # Transcription
        if transcript:
            console.log(f"[cyan]Loading existing transcript:[/cyan] {transcript}")
            segments = load_transcript_from_json(transcript)
        else:
            with tempfile.TemporaryDirectory() as tmpdir:
                wav_path = os.path.join(tmpdir, "audio.wav")
                extract_audio(mp4_file, wav_path, audio_track=audio_track)
                segments = transcribe_audio(wav_path, model_size=whisper_model)

        if save_transcript_path:
            save_transcript(segments, save_transcript_path)

        if not segments:
            _error_json("No transcript segments found.")

        total_duration = segments[-1].end
        console.log(f"[cyan]Total duration:[/cyan] {fmt_time(total_duration)}")

        # Chunk & Analyze
        chunks = chunk_transcript(segments, window_minutes=window_minutes)
        custom_list = list(custom_prompt) if custom_prompt else None
        clips = find_clips(
            chunks, client, top_n=top_n,
            padding_seconds=padding_minutes * 60,
            total_duration=total_duration,
            model=model,
            max_workers=max_workers,
            custom_prompts=custom_list,
        )

        if not clips and fmt == "human":
            console.print("[yellow]No compelling clip suggestions found.[/yellow]")
            sys.exit(0)

        if fmt == "human":
            print_results(clips)
        if output_json:
            save_results(clips, output_json)
        if export_clips_dir:
            export_ffmpeg_commands(clips, mp4_file, export_clips_dir)

        _output({
            "clip_count": len(clips),
            "output_json": output_json,
            "clips": [asdict(c) for c in clips],
        }, fmt)
    except Exception as exc:
        _error_json(str(exc))


if __name__ == "__main__":
    cli()
