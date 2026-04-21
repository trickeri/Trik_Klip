"""Background workers using QThread + signals."""

import io
import os
import re
import sys
import tempfile
import threading
import time

from PySide6.QtCore import QThread
from rich.console import Console as RichConsole

import clip_finder as cf
from gui_qt.signals import WorkerSignals


class GuiConsole:
    """Adapter that redirects cf.console calls to WorkerSignals.

    Replaces the rich Console so pipeline functions can emit log messages
    to the GUI without knowing about Qt. Unknown attributes fall through to a
    real (buffered) rich Console so rich internals like Progress/Status that
    call things like `get_time`, `is_terminal`, `size`, etc. keep working.
    """

    _TAG_RE = re.compile(r"\[/?[^\]]*\]")

    def __init__(self, signals: WorkerSignals):
        self._signals = signals
        # Fallback for anything not overridden below. Writing to a StringIO
        # buffer means rich's output (bars, tables) is harmlessly discarded
        # while its internal plumbing (timers, sizing) still works.
        self._fallback = RichConsole(file=io.StringIO(), force_terminal=False)

    def __getattr__(self, name):
        # __getattr__ is only invoked when normal lookup fails, so it won't
        # shadow any of the explicit methods below.
        return getattr(self._fallback, name)

    def _strip(self, text: str) -> str:
        return self._TAG_RE.sub("", str(text))

    def log(self, *args, **kwargs):
        text = " ".join(str(a) for a in args)
        self._signals.log.emit(self._strip(text) + "\n")

    def print(self, *args, **kwargs):
        text = " ".join(str(a) for a in args)
        self._signals.log.emit(self._strip(text) + "\n")

    # Rich's Progress calls this to timestamp events.
    def get_time(self):
        return time.monotonic()

    # Match rich Console interface methods the pipeline might call
    def rule(self, *a, **kw):
        pass

    def status(self, *a, **kw):
        class _Dummy:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def update(self, *a): pass
        return _Dummy()


class PipelineWorker(QThread):
    """Runs the main pipeline (full / transcribe / analyze)."""

    def __init__(self, signals: WorkerSignals, params: dict, profile: dict):
        super().__init__()
        self.signals = signals
        self.params = params
        self.profile = profile
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    def run(self):
        mode = self.params.get("mode", 0)
        gui_console = GuiConsole(self.signals)
        original_console = cf.console
        cf.console = gui_console

        try:
            if mode == 0:
                self._run_full()
            elif mode == 1:
                self._run_transcribe()
            elif mode == 2:
                self._run_analyze()
        except Exception as exc:
            self.signals.err.emit(f"Pipeline error: {exc}\n")
        finally:
            cf.console = original_console
            self.signals.done.emit()

    def _run_full(self):
        p = self.params
        segments, spikes = self._do_transcription(p)
        if self._cancel.is_set():
            self.signals.warn.emit("Cancelled.\n")
            return
        if not segments:
            self.signals.err.emit("No transcript segments found.\n")
            return

        if p.get("save_transcript_path"):
            cf.save_transcript(segments, p["save_transcript_path"])
            self.signals.ok.emit(
                f"Transcript saved: {p['save_transcript_path']}\n")

        total_duration = segments[-1].end
        self.signals.log.emit(
            f"Total duration: {cf.fmt_time(total_duration)}\n")

        # Chunk and annotate
        chunks = cf.chunk_transcript(
            segments, window_minutes=p.get("window_minutes", 5))
        if spikes:
            chunks = cf.annotate_chunks_with_spikes(chunks, spikes)

        if self._cancel.is_set():
            self.signals.warn.emit("Cancelled.\n")
            return

        # Analyze
        clips = self._do_analysis(chunks, total_duration, p)

        if p.get("output_json_path") and clips:
            cf.save_results(clips, p["output_json_path"])
            self.signals.ok.emit(
                f"Results saved: {p['output_json_path']}\n")

        if clips:
            self.signals.results.emit(clips)
            self.signals.ok.emit(
                f"\nFound {len(clips)} clip suggestions.\n")
        else:
            self.signals.warn.emit("No compelling clip suggestions found.\n")

    def _run_transcribe(self):
        p = self.params
        segments, spikes = self._do_transcription(p)
        if segments and p.get("save_transcript_path"):
            cf.save_transcript(segments, p["save_transcript_path"])
            self.signals.ok.emit(
                f"Transcript saved: {p['save_transcript_path']}\n")
            if spikes:
                spike_path = p["save_transcript_path"].replace(
                    ".json", "_spikes.json")
                cf.save_spikes(spikes, spike_path)
                self.signals.ok.emit(f"Spikes saved: {spike_path}\n")

    def _run_analyze(self):
        p = self.params
        transcript_path = p.get("transcript_path")
        if not transcript_path:
            self.signals.err.emit("No transcript loaded for analysis.\n")
            return

        segments = cf.load_transcript_from_json(transcript_path)
        if not segments:
            self.signals.err.emit("Empty transcript.\n")
            return

        total_duration = segments[-1].end
        chunks = cf.chunk_transcript(
            segments, window_minutes=p.get("window_minutes", 5))

        # Try to load spikes sidecar
        spike_path = transcript_path.replace(".json", "_spikes.json")
        if os.path.exists(spike_path):
            spikes = cf.load_spikes(spike_path)
            if spikes:
                chunks = cf.annotate_chunks_with_spikes(chunks, spikes)

        clips = self._do_analysis(chunks, total_duration, p)
        if clips:
            self.signals.results.emit(clips)
            if p.get("output_json_path"):
                cf.save_results(clips, p["output_json_path"])

    def _do_transcription(self, p):
        """Extract audio + detect spikes + transcribe. Returns (segments, spikes)."""
        transcript_path = p.get("transcript_path")
        if transcript_path:
            self.signals.log.emit(f"Loading transcript: {transcript_path}\n")
            segments = cf.load_transcript_from_json(transcript_path)
            return segments, []

        mp4_file = p["mp4_file"]

        with tempfile.TemporaryDirectory() as tmpdir:
            wav_path = os.path.join(tmpdir, "audio.wav")

            # Audio extraction
            self.signals.audio_start.emit()
            cf.extract_audio(
                mp4_file, wav_path,
                audio_track=p.get("audio_track"),
                progress_cb=lambda pct: self.signals.audio_progress.emit(pct),
            )
            self.signals.audio_done.emit()

            if self._cancel.is_set():
                return [], []

            # Volume spike detection
            self.signals.log.emit("Detecting volume spikes...\n")
            spikes = cf.detect_volume_spikes(wav_path)
            self.signals.ok.emit(f"Detected {len(spikes)} volume spike(s)\n")

            if self._cancel.is_set():
                return [], spikes

            # Whisper transcription
            self.signals.whisper_start.emit()
            segments = cf.transcribe_audio(
                wav_path,
                model_size=p.get("whisper_model", "base"),
                language=p.get("language", "en"),
                progress_cb=lambda pct, lbl:
                    self.signals.whisper_progress.emit(pct, lbl),
            )
            self.signals.whisper_done.emit()

            return segments, spikes

    def _do_analysis(self, chunks, total_duration, p):
        """Run LLM analysis on chunks."""
        profile = self.profile
        if not profile:
            self.signals.err.emit("No model profile configured.\n")
            return []

        from providers import PROVIDERS, make_client

        provider = profile.get("provider", "anthropic")
        prov_info = PROVIDERS.get(provider, {})
        model = profile.get("model") or prov_info.get("default_model", "")
        api_key = profile.get("api_key", "")
        base_url = profile.get("base_url", "")

        if provider == "ollama":
            api_key = "ollama"
            base_url = base_url or "http://localhost:11434"
        elif provider != "claude_code" and not api_key:
            env_key = prov_info.get("env_key", "")
            api_key = os.environ.get(env_key, "")
            if not api_key:
                self.signals.err.emit(
                    f"No API key for {provider}. Set {env_key} or configure a profile.\n")
                return []

        try:
            client = make_client(provider, api_key, base_url=base_url)
        except Exception as exc:
            self.signals.err.emit(f"Could not create client: {exc}\n")
            return []

        max_workers = 4 if provider == "claude_code" else 1
        custom_prompts = p.get("custom_prompts") or None

        total = len(chunks)
        self.signals.analysis_start.emit(total)

        done_count = [0]
        _orig_advance = None

        # Monkey-patch progress tracking into find_clips
        clips = cf.find_clips(
            chunks, client,
            top_n=p.get("top_n", 10),
            padding_seconds=p.get("padding_minutes", 3) * 60,
            total_duration=total_duration,
            model=model,
            max_workers=max_workers,
            custom_prompts=custom_prompts,
        )

        self.signals.analysis_done.emit()

        if client.fallback_activated:
            self.signals.warn.emit(
                "Claude Code rate limit hit — fell back to API key.\n")

        return clips


class ExtractWorker(QThread):
    """Extract clip MP4s from source video."""

    def __init__(self, signals: WorkerSignals, selected: list,
                 mp4_path: str, output_dir: str,
                 segments=None):
        super().__init__()
        self.signals = signals
        self.selected = selected  # list of (index, clip)
        self.mp4_path = mp4_path
        self.output_dir = output_dir
        self.segments = segments
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    def run(self):
        original_console = cf.console
        cf.console = GuiConsole(self.signals)

        try:
            os.makedirs(self.output_dir, exist_ok=True)
            total = len(self.selected)
            self.signals.extract_start.emit(total)
            extracted_dirs = []

            for i, (row_idx, clip) in enumerate(self.selected, 1):
                if self._cancel.is_set():
                    self.signals.warn.emit("Extraction cancelled.\n")
                    break

                self.signals.log.emit(
                    f"[{i}/{total}] #{clip.rank} {clip.title}\n")

                try:
                    info = cf.extract_clip_with_assets(
                        clip, self.mp4_path, self.output_dir, self.segments)
                    extracted_dirs.append(info["clip_dir"])
                    self.signals.ok.emit(f"  Done: {info['clip_name']}\n")
                except Exception as exc:
                    self.signals.err.emit(f"  Failed: {exc}\n")

                self.signals.extract_progress.emit(i, total, row_idx)

            self.signals.extract_done.emit(extracted_dirs)
        except Exception as exc:
            self.signals.err.emit(f"Extraction error: {exc}\n")
        finally:
            cf.console = original_console


class SliceWorker(QThread):
    """Generate editing slices for a clip directory."""

    def __init__(self, signals: WorkerSignals, clip_dir: str,
                 profile: dict, editing_notes: str = "",
                 premiere: bool = True, section_id: int = 0):
        super().__init__()
        self.signals = signals
        self.clip_dir = clip_dir
        self.profile = profile
        self.editing_notes = editing_notes
        self.premiere = premiere
        self.section_id = section_id
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    def run(self):
        original_console = cf.console
        cf.console = GuiConsole(self.signals)

        try:
            from providers import PROVIDERS, make_client

            provider = self.profile.get("provider", "anthropic")
            prov_info = PROVIDERS.get(provider, {})
            model = self.profile.get("model") or prov_info.get("default_model", "")
            api_key = self.profile.get("api_key", "")
            base_url = self.profile.get("base_url", "")

            if provider == "ollama":
                api_key = "ollama"
                base_url = base_url or "http://localhost:11434"
            elif provider != "claude_code" and not api_key:
                env_key = prov_info.get("env_key", "")
                api_key = os.environ.get(env_key, "")

            client = make_client(provider, api_key, base_url=base_url)

            self.signals.head.emit(
                f"\n=== Generate Slices: {os.path.basename(self.clip_dir)} ===\n")

            result = cf.generate_slices(
                self.clip_dir, client, model,
                editing_notes=self.editing_notes,
                premiere=self.premiere,
            )

            slices = result.get("slices", [])
            total_dur = result.get("total_duration", 0)

            if slices:
                self.signals.ok.emit(
                    f"{len(slices)} slices written, "
                    f"total {total_dur:.1f}s\n")
            elif result.get("error"):
                self.signals.err.emit(f"{result['error']}\n")

            self.signals.slice_done.emit(self.section_id)

        except Exception as exc:
            self.signals.err.emit(f"Slice error: {exc}\n")
            self.signals.slice_done.emit(self.section_id)
        finally:
            cf.console = original_console
