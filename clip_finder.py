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
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")
import json
import math
import tempfile
import subprocess
from pathlib import Path
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

console = Console()


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
                                stderr=subprocess.PIPE, text=True)
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
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            console.print(f"[red]ffmpeg error:[/red]\n{result.stderr}")
            sys.exit(1)
    console.log("[green]✓ Audio extracted[/green]")


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

ANALYSIS_SYSTEM_PROMPT = """You are an expert short-form content strategist with deep knowledge of what makes clips go viral on TikTok, YouTube Shorts, and Instagram Reels.

You will be given a 5-minute transcript chunk from a long-form stream or podcast. Your job is to identify if there is a compelling 1–3 minute clip hidden inside it.

A great clip has ONE OR MORE of:
- A clear narrative arc or story with a beginning, middle, end
- A surprising reveal, strong opinion, or counterintuitive take
- A genuinely funny or emotional moment
- Practical, actionable advice with clear stakes
- A heated or interesting debate moment
- A quotable, memorable one-liner or monologue

Return ONLY valid JSON (no markdown fences, no extra text) in this exact schema:
{
  "has_clip": true or false,
  "virality_score": 1-10,
  "content_type": "story|advice|moment|debate|rant|revelation|other",
  "title": "Short punchy title for the clip (max 60 chars)",
  "hook": "One sentence explaining why someone would watch this",
  "clip_start_offset": seconds from window_start where the clip should begin,
  "clip_end_offset": seconds from window_start where the clip should end,
  "transcript_excerpt": "The most compelling 1-2 sentences from this segment"
}

If there is no compelling clip, return {"has_clip": false}.
clip_end_offset - clip_start_offset should be between 60 and 180 seconds."""


def analyze_chunk(chunk: dict, client, model: str = "claude-opus-4-6") -> Optional[dict]:
    """Send a transcript chunk to the LLM for clip analysis.

    *client* can be either a ``providers.LLMClient`` (preferred) or a legacy
    ``anthropic.Anthropic`` instance for backward-compatibility.
    """
    window_duration = chunk["window_end"] - chunk["window_start"]
    user_prompt = (
        f"Window timestamps: {fmt_time(chunk['window_start'])} → {fmt_time(chunk['window_end'])} "
        f"({window_duration/60:.1f} min)\n\n"
        f"Transcript:\n{chunk['text']}"
    )

    try:
        from providers import LLMClient
        if isinstance(client, LLMClient):
            raw = client.message(
                model=model,
                user_prompt=user_prompt,
                system_prompt=ANALYSIS_SYSTEM_PROMPT,
                max_tokens=600,
            )
        else:
            # Legacy Anthropic client fallback
            response = client.messages.create(
                model=model,
                max_tokens=600,
                system=ANALYSIS_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}]
            )
            raw = response.content[0].text
    except Exception as exc:
        console.log(f"[yellow]Warning: API error for chunk at {fmt_time(chunk['window_start'])}: {exc}[/yellow]")
        return None

    raw = raw.strip()
    # Strip any accidental markdown fences
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        console.log(f"[yellow]Warning: Could not parse LLM response for chunk at {fmt_time(chunk['window_start'])}[/yellow]")
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
) -> list[ClipSuggestion]:
    """Analyze all chunks and return the top N clip suggestions.

    padding_seconds: seconds of context added before and after each identified
                     core clip, giving editors room to work (default 3 min).
    total_duration:  total audio length in seconds used to clamp the end of
                     padded clips (pass segments[-1].end).
    """
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

        for chunk in chunks:
            result = analyze_chunk(chunk, client, model=model)
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


# ── CLI ───────────────────────────────────────────────────────────────────────

@click.command()
@click.argument("mp4_file", type=click.Path(exists=True))
@click.option("--whisper-model", default="base", type=click.Choice(["tiny", "base", "small", "medium", "large"]),
              help="Whisper model size (larger = more accurate, slower). Default: base")
@click.option("--top-n", default=10, help="Number of clip suggestions to return. Default: 10")
@click.option("--window-minutes", default=5, help="Analysis window size in minutes. Default: 5")
@click.option("--transcript", default=None, help="Path to existing transcript JSON to skip transcription")
@click.option("--save-transcript", "save_transcript_path", default=None,
              help="Path to save transcript JSON for future reuse")
@click.option("--output-json", default=None, help="Path to save results JSON")
@click.option("--export-clips-dir", default=None,
              help="Directory to write ffmpeg clip extraction script")
@click.option("--audio-track", default=None, type=int,
              help="0-based index of the audio track to extract (default: first track). "
                   "Use ffprobe or 'ffmpeg -i <file>' to list available tracks.")
@click.option("--padding-minutes", default=3, type=float,
              help="Minutes of context added before/after each identified clip for editing headroom. Default: 3")
@click.option("--provider", default="anthropic",
              type=click.Choice(["anthropic", "openai", "gemini", "grok", "ollama"]),
              help="LLM provider. Default: anthropic")
@click.option("--model", "llm_model", default=None,
              help="LLM model ID (defaults to provider's best model)")
@click.option("--base-url", default=None,
              help="Custom API base URL (used with ollama, e.g. http://localhost:11434). "
                   "Defaults to provider's built-in URL.")
def main(
    mp4_file,
    whisper_model,
    top_n,
    window_minutes,
    transcript,
    save_transcript_path,
    output_json,
    export_clips_dir,
    audio_track,
    padding_minutes,
    provider,
    llm_model,
    base_url,
):
    """
    StreamClipper — Analyze a long-form MP4 and find short-form clip opportunities.

    Example:
        python clip_finder.py stream.mp4 --whisper-model small --top-n 10 --export-clips-dir ./clips
    """
    from providers import PROVIDERS, make_client

    prov_info = PROVIDERS[provider]
    model = llm_model or prov_info["default_model"]

    if provider == "ollama":
        api_key = "ollama"
        url = base_url or prov_info.get("base_url", "http://localhost:11434")
    else:
        api_key = os.environ.get(prov_info["env_key"], "")
        url = base_url or ""
        if not api_key:
            console.print(f"[red]Error: {prov_info['env_key']} environment variable not set.[/red]")
            sys.exit(1)

    try:
        client = make_client(provider, api_key, base_url=url)
    except Exception as exc:
        console.print(f"[red]Could not create {provider} client: {exc}[/red]")
        sys.exit(1)

    console.print(Panel.fit(
        "[bold cyan]StreamClipper[/bold cyan]\n[dim]Long-form → Short-form clip finder[/dim]",
        border_style="cyan"
    ))

    # ── Transcription ──────────────────────────────────────────────────────
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
        console.print("[red]No transcript segments found. Exiting.[/red]")
        sys.exit(1)

    total_duration = segments[-1].end
    console.log(f"[cyan]Total stream duration:[/cyan] {fmt_time(total_duration)} ({total_duration/3600:.2f} hrs)")

    # ── Chunk & Analyze ────────────────────────────────────────────────────
    chunks = chunk_transcript(segments, window_minutes=window_minutes)
    clips = find_clips(chunks, client, top_n=top_n,
                       padding_seconds=padding_minutes * 60,
                       total_duration=total_duration,
                       model=model)

    if not clips:
        console.print("[yellow]No compelling clip suggestions found.[/yellow]")
        sys.exit(0)

    # ── Output ─────────────────────────────────────────────────────────────
    print_results(clips)

    if output_json:
        save_results(clips, output_json)

    if export_clips_dir:
        script = export_ffmpeg_commands(clips, mp4_file, export_clips_dir)
        console.print(f"\n[green]✓ Clip extraction script written to:[/green] {script}")
        console.print("[dim]Run it with:  bash " + script + "[/dim]")

    console.print()
    console.print("[bold green]Done![/bold green]")


if __name__ == "__main__":
    main()
