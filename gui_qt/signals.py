"""Typed signals for worker → GUI communication."""

from PySide6.QtCore import QObject, Signal


class WorkerSignals(QObject):
    """All signals emitted by background workers.

    PySide6 signals are thread-safe: emitting from a QThread delivers
    the call to connected slots on the main thread via the event loop.
    """

    # ── Log messages ──────────────────────────────────────────────────────
    log  = Signal(str)
    ok   = Signal(str)
    err  = Signal(str)
    warn = Signal(str)
    head = Signal(str)
    dim  = Signal(str)

    # ── Pipeline lifecycle ────────────────────────────────────────────────
    done    = Signal()
    results = Signal(list)   # list[ClipSuggestion]

    # ── Audio extraction ──────────────────────────────────────────────────
    audio_start    = Signal()
    audio_progress = Signal(int)          # pct 0-100
    audio_done     = Signal()

    # ── Whisper transcription ─────────────────────────────────────────────
    whisper_start    = Signal()
    whisper_progress = Signal(int, str)   # pct, label
    whisper_done     = Signal()

    # ── LLM analysis ─────────────────────────────────────────────────────
    analysis_start    = Signal(int)       # total windows
    analysis_progress = Signal(int, int)  # done, total
    analysis_done     = Signal()

    # ── Clip extraction ───────────────────────────────────────────────────
    extract_start    = Signal(int)        # total clips
    extract_progress = Signal(int, int, int)  # done, total, row_idx
    extract_done     = Signal(list)       # list of clip dir paths

    # ── Slice generation ──────────────────────────────────────────────────
    slice_start    = Signal(int)          # total cuts
    slice_progress = Signal(int, int)     # done, total
    slice_complete = Signal()
    slice_done     = Signal(object)       # section_id

    # ── Visual aid images ─────────────────────────────────────────────────
    image_start    = Signal(int)          # total images
    image_progress = Signal(int, int)     # done, total
    image_complete = Signal()

    # ── Misc ──────────────────────────────────────────────────────────────
    premiere_clipboard = Signal(str)
