#!/usr/bin/env python3
"""
StreamClipper GUI — graphical front-end for clip_finder.py

Dependencies (beyond clip_finder requirements):
    pip install tkinterdnd2   # optional — enables drag-and-drop
"""

import os
import sys

# PyInstaller --windowed sets sys.stdout/stderr to None, which crashes any
# library that tries to print (e.g. Whisper model loading).  Redirect to
# devnull so those writes silently succeed.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

import re
import json
import queue
import threading
import tempfile
import subprocess
import ctypes
import urllib.request
import urllib.error
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import customtkinter as ctk
from pathlib import Path
from dataclasses import dataclass

# Optional drag-and-drop support
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except ImportError:
    HAS_DND = False

# Make sure clip_finder is importable from same directory
sys.path.insert(0, str(Path(__file__).parent))
import clip_finder as cf


def _load_bundled_fonts():
    """Load all .ttf files from the fonts/ directory for this process."""
    font_dir = Path(__file__).parent / "fonts"
    if not font_dir.is_dir():
        return
    FR_PRIVATE = 0x10
    for ttf in font_dir.glob("*.ttf"):
        ctypes.windll.gdi32.AddFontResourceExW(str(ttf), FR_PRIVATE, 0)

_load_bundled_fonts()


# ── Rich-output redirector ────────────────────────────────────────────────────

_RICH_TAG = re.compile(r"\[/?[^\]]*\]")


class GuiConsole:
    """Drop-in replacement for rich.Console that routes output to a Queue."""

    def __init__(self, q: queue.Queue):
        self._q = q

    def log(self, msg, *_, **__):
        self._q.put(("log", _RICH_TAG.sub("", str(msg))))

    def print(self, msg="", *_, **__):
        self._q.put(("log", _RICH_TAG.sub("", str(msg))))


VERSION = "1.0.02"

# ── Colour palette ────────────────────────────────────────────────────────────

BG       = "#1e1e2e"
PANEL    = "#252535"
CARD     = "#2a2a3e"
ACCENT   = "#7c3aed"
ACCENT2  = "#6d28d9"
TEXT     = "#e2e8f0"
DIM      = "#94a3b8"
SUCCESS  = "#22c55e"
ERR      = "#ef4444"
WARN     = "#f59e0b"
BORDER   = "#374151"
ENTRY_BG = "#1a1a2e"
SEP      = "#3f3f5a"


# ── Custom rounded scrollbar ─────────────────────────────────────────────────

class SmoothScrollbar(tk.Canvas):
    """A canvas-drawn scrollbar with a rounded purple thumb and no arrows."""

    WIDTH = 10          # total scrollbar width
    PAD   = 2           # padding around the thumb
    MIN_THUMB = 30      # minimum thumb height in pixels

    def __init__(self, parent, command=None, **kw):
        kw.setdefault("width", self.WIDTH)
        kw.setdefault("bg", BG)
        kw.setdefault("highlightthickness", 0)
        kw.setdefault("bd", 0)
        super().__init__(parent, **kw)
        self._command = command
        self._lo = 0.0          # scrollbar position low
        self._hi = 1.0          # scrollbar position high
        self._drag_y = None     # mouse-y at drag start
        self._drag_lo = 0.0     # _lo at drag start
        self._thumb_color = ACCENT
        self._thumb_hover = "#9b5de5"   # lighter purple on hover
        self._hovering = False

        self.bind("<Configure>", self._draw)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        # mousewheel passthrough
        self.bind("<MouseWheel>", self._on_wheel)

    # -- tkinter scrollbar protocol (called by the scrollable widget) ---------

    def set(self, lo, hi):
        """Called by the scrollable widget to update thumb position."""
        self._lo = float(lo)
        self._hi = float(hi)
        self._draw()

    # -- drawing --------------------------------------------------------------

    def _draw(self, _event=None):
        self.delete("all")
        h = self.winfo_height()
        w = self.winfo_width()
        if h < 1 or self._hi - self._lo >= 1.0:
            return  # nothing to scroll

        thumb_h = max(self.MIN_THUMB, (self._hi - self._lo) * h)
        y1 = self._lo * h
        y2 = y1 + thumb_h
        # clamp
        if y2 > h:
            y2 = h
            y1 = h - thumb_h

        r = (w - self.PAD * 2) / 2   # corner radius
        fill = self._thumb_hover if self._hovering else self._thumb_color
        self._round_rect(self.PAD, y1 + self.PAD,
                         w - self.PAD, y2 - self.PAD, r, fill)

    def _round_rect(self, x1, y1, x2, y2, r, fill):
        """Draw a rounded rectangle on the canvas."""
        r = min(r, (x2 - x1) / 2, (y2 - y1) / 2)
        self.create_arc(x1, y1, x1 + 2*r, y1 + 2*r, start=90,
                        extent=90, fill=fill, outline=fill)
        self.create_arc(x2 - 2*r, y1, x2, y1 + 2*r, start=0,
                        extent=90, fill=fill, outline=fill)
        self.create_arc(x2 - 2*r, y2 - 2*r, x2, y2, start=270,
                        extent=90, fill=fill, outline=fill)
        self.create_arc(x1, y2 - 2*r, x1 + 2*r, y2, start=180,
                        extent=90, fill=fill, outline=fill)
        self.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline=fill)
        self.create_rectangle(x1, y1 + r, x2, y2 - r, fill=fill, outline=fill)

    # -- interaction ----------------------------------------------------------

    def _set_hover(self, hover):
        self._hovering = hover
        self._draw()

    def _on_press(self, event):
        h = self.winfo_height()
        if h < 1:
            return
        thumb_h = max(self.MIN_THUMB, (self._hi - self._lo) * h)
        y1 = self._lo * h
        y2 = y1 + thumb_h
        if y1 <= event.y <= y2:
            # clicking on the thumb — start drag
            self._drag_y = event.y
            self._drag_lo = self._lo
        else:
            # clicking on the trough — jump to position
            frac = event.y / h
            span = self._hi - self._lo
            new_lo = frac - span / 2
            new_lo = max(0.0, min(new_lo, 1.0 - span))
            if self._command:
                self._command("moveto", str(new_lo))

    def _on_drag(self, event):
        if self._drag_y is None:
            return
        h = self.winfo_height()
        if h < 1:
            return
        dy = event.y - self._drag_y
        delta = dy / h
        span = self._hi - self._lo
        new_lo = max(0.0, min(self._drag_lo + delta, 1.0 - span))
        if self._command:
            self._command("moveto", str(new_lo))

    def _on_release(self, _event):
        self._drag_y = None

    def _on_wheel(self, event):
        if self._command:
            self._command("scroll", str(-1 * (event.delta // 120)), "units")


# ── Clip parsed from an existing shell script ────────────────────────────────

@dataclass
class ShellClip:
    rank: int
    title: str
    clip_start: float
    clip_end: float
    clip_duration: float
    virality_score: int = 0
    content_type: str  = "imported"


def parse_clips_script(script_path: str):
    """Parse an extract_clips.sh and return (mp4_source, list[ShellClip])."""
    with open(script_path, encoding="utf-8") as f:
        content = f.read()

    source_m = re.search(r"^# Source: (.+)$", content, re.MULTILINE)
    mp4_source = source_m.group(1).strip() if source_m else ""

    # Match pairs of:  # Clip N: Title (ts → ts)\nffmpeg -ss START -i "..." -t DUR ...
    clip_re = re.compile(
        r"# Clip (\d+): (.+?) \([^)]+\)\s*\n"
        r"ffmpeg -ss ([\d.]+) [^\n]+ -t ([\d.]+) ",
        re.MULTILINE,
    )

    clips = []
    for m in clip_re.finditer(content):
        start    = float(m.group(3))
        duration = float(m.group(4))
        clips.append(ShellClip(
            rank=int(m.group(1)),
            title=m.group(2).strip(),
            clip_start=start,
            clip_end=start + duration,
            clip_duration=duration,
        ))

    return mp4_source, clips


# ── Main GUI class ────────────────────────────────────────────────────────────

class StreamClipperGUI:

    def __init__(self):
        self.root = TkinterDnD.Tk() if HAS_DND else tk.Tk()
        self.root.title("Trik_Klip")
        self.root.geometry("860x1000")
        self.root.resizable(False, False)
        self.root.configure(bg=BG)
        self.root.option_add("*TCombobox*Listbox.background", ENTRY_BG)
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.root.option_add("*TCombobox*Listbox.selectForeground", TEXT)

        self._q: queue.Queue = queue.Queue()
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None

        # ── State variables ──
        self.mp4_path        = tk.StringVar()
        self.whisper_model   = tk.StringVar(value="small")
        self.top_n           = tk.IntVar(value=10)
        self.window_minutes  = tk.IntVar(value=5)
        self.padding_minutes = tk.DoubleVar(value=3.0)
        self.audio_track     = tk.StringVar(value="")
        self.load_transcript = tk.StringVar()
        self.save_transcript = tk.StringVar()
        self.save_wav        = tk.StringVar()
        self.output_json     = tk.StringVar()
        self.export_dir      = tk.StringVar()
        self.run_mode        = tk.StringVar(value="full")

        self.mp4_path.trace_add("write", self._on_mp4_changed)

        self._last_clips:     list = []
        self._clip_vars:      list = []   # tk.BooleanVar per clip
        self._edit_clip_vars: list = []   # (BooleanVar, Path) per editing-tab clip

        # ── Dynamic clip-section state (Editing tab) ──
        self._clip_sections: list[dict] = []   # per-section widget refs
        self._auto_remove_var = tk.BooleanVar(value=True)
        self._next_section_id = 0

        # ── Profile / Settings state ──
        self._profiles:        dict = {}               # name → {provider, api_key, model, base_url}
        self._prof_name        = tk.StringVar()        # name field in editor
        self._prof_provider    = tk.StringVar(value="anthropic")
        self._prof_api_key     = tk.StringVar(value=os.environ.get("ANTHROPIC_API_KEY", ""))  # best-effort default
        self._prof_model       = tk.StringVar(value="claude-opus-4-6")
        self._prof_base_url    = tk.StringVar(value="http://localhost:11434")
        self._prof_active      = tk.StringVar()        # currently selected profile
        self.transcription_language = tk.StringVar(value="English")  # display name

        self._build()
        self._load_profiles()   # populates dropdowns after widgets exist
        self._q.put(("log", f"Welcome to Trik_Klip v{VERSION}\n"))
        self._poll()

    DEFAULT_OUT_DIR = r"D:\Videos\Streams\Clips"

    def _on_mp4_changed(self, *_):
        """Auto-fill output paths whenever a new MP4 is selected."""
        mp4 = self.mp4_path.get().strip()
        if not mp4:
            return
        stem = Path(mp4).stem          # e.g. "my_stream"
        base = Path(self.DEFAULT_OUT_DIR) / stem  # D:\Videos\Streams\Clips\my_stream\

        # Only overwrite a field if the user hasn't customised it already
        # (i.e. it's still empty or was previously auto-generated from a different MP4).
        # We track the last auto-set stem to detect that case.
        prev = getattr(self, "_last_auto_stem", None)

        def _should_set(var: tk.StringVar) -> bool:
            v = var.get().strip()
            if not v:
                return True
            # If the current value was auto-set from the previous stem, replace it
            if prev and prev in v:
                return True
            return False

        if _should_set(self.save_transcript):
            self.save_transcript.set(str(base / f"{stem}_transcript.json"))
        if _should_set(self.save_wav):
            self.save_wav.set(str(base / f"{stem}_audio.wav"))
        if _should_set(self.output_json):
            self.output_json.set(str(base / f"{stem}_clips.json"))
        if _should_set(self.export_dir):
            self.export_dir.set(str(base / f"{stem}_clips"))

        # Mirror the clips folder into the Editing tab's source field
        if hasattr(self, "_edit_clips_dir"):
            ed = self._edit_clips_dir.get().strip()
            if not ed or (prev and prev in ed):
                self._edit_clips_dir.set(str(base / f"{stem}_clips"))
            eo = getattr(self, "_edit_out_dir", None)
            if eo is not None:
                ev = eo.get().strip()
                if not ev or (prev and prev in ev):
                    eo.set(str(base / f"{stem}_clips_edited"))

        self._last_auto_stem = stem

    # ─────────────────────────────────────────────────────────────────────────
    # UI construction
    # ─────────────────────────────────────────────────────────────────────────

    def _build(self):
        # Configure ttk style minimally (we use tk widgets mostly)
        s = ttk.Style()
        s.theme_use("clam")
        s.configure("TCombobox", fieldbackground=ENTRY_BG, background=ENTRY_BG,
                    foreground=TEXT, selectbackground=ACCENT, selectforeground=TEXT)
        s.map("TCombobox",
              fieldbackground=[("readonly", ENTRY_BG)],
              foreground=[("readonly", TEXT)],
              selectbackground=[("readonly", ENTRY_BG)],
              selectforeground=[("readonly", TEXT)])

        # ── Header ──────────────────────────────────────────────────────────
        hdr = tk.Frame(self.root, bg=ACCENT, pady=10)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Trik_Klip", font=("Old English Text MT", 22, "bold"),
                 bg=ACCENT, fg="white").pack()
        tk.Label(hdr, text="Trik_Klip",
                 font=("Nulgl_case2", 12, "bold"), bg=ACCENT, fg="#c4b5fd").pack()

        # ── Resizable paned container (tabs top / log bottom) ────────────────
        paned = tk.PanedWindow(
            self.root, orient="vertical",
            bg=ACCENT, sashwidth=6, sashrelief="flat", sashpad=0,
            opaqueresize=True
        )
        paned.pack(fill="both", expand=True)
        self._paned = paned

        # ── Notebook (top pane) ──────────────────────────────────────────────
        tab_outer = tk.Frame(paned, bg=BG)
        paned.add(tab_outer, stretch="always", minsize=440)

        s.configure("App.TNotebook", background=BG, borderwidth=0, tabmargins=0)
        s.configure("App.TNotebook.Tab",
                    background=PANEL, foreground=DIM,
                    padding=[16, 6], font=("Segoe UI", 9),
                    borderwidth=0, focuscolor="")
        s.layout("App.TNotebook.Tab", [
            ("Notebook.tab", {"sticky": "nswe", "children": [
                ("Notebook.padding", {"side": "top", "sticky": "nswe", "children": [
                    ("Notebook.label", {"side": "top", "sticky": ""})
                ]})
            ]})
        ])
        s.map("App.TNotebook.Tab",
              background=[("disabled", BG), ("selected", CARD)],
              foreground=[("disabled", BG), ("selected", TEXT)],
              padding=[("selected", [20, 8])],
              font=[("selected", ("Segoe UI", 10, "bold"))])

        self._notebook = ttk.Notebook(tab_outer, style="App.TNotebook")
        self._notebook.pack(fill="both", expand=True)

        # ── Helper: build a scrollable canvas inside a notebook tab ──────────
        def _make_scroll_tab(label):
            """Return (tab_frame, canvas, inner_frame) for a scrollable tab."""
            tab_frame = tk.Frame(self._notebook, bg=BG)
            self._notebook.add(tab_frame, text=f"  {label}  ")

            inner_canvas = tk.Canvas(tab_frame, bg=BG, highlightthickness=0)
            tab_vsb = SmoothScrollbar(tab_frame, command=inner_canvas.yview)
            content = tk.Frame(inner_canvas, bg=BG)
            content.bind(
                "<Configure>",
                lambda e, c=inner_canvas: c.configure(scrollregion=c.bbox("all"))
            )
            inner_canvas.create_window((0, 0), window=content,
                                       anchor="n", tags="win")

            def _center(event, c=inner_canvas):
                w = event.width
                c.coords("win", w // 2, 0)
                c.itemconfigure("win", width=min(w, 860))

            inner_canvas.bind("<Configure>", _center)
            inner_canvas.configure(yscrollcommand=tab_vsb.set)
            tab_vsb.pack(side="right", fill="y")
            inner_canvas.pack(side="left", fill="both", expand=True)
            return tab_frame, inner_canvas, content

        # ── Transcribe tab ──────────────────────────────────────────────────
        _trans_tab, trans_canvas, trans_frame = _make_scroll_tab("Transcribe")
        self._settings_frame  = trans_frame
        self._settings_canvas = trans_canvas

        # ── Extract tab ─────────────────────────────────────────────────────
        _extract_tab, extract_canvas, extract_frame = _make_scroll_tab("Extract")
        self._extract_frame  = extract_frame
        self._extract_canvas = extract_canvas

        # ── Editing tab ──────────────────────────────────────────────────────
        _edit_tab, edit_canvas, edit_frame = _make_scroll_tab("Slice")
        self._editing_frame  = edit_frame
        self._editing_canvas = edit_canvas

        # ── Spacer "tab" to push ⚙ to the right ──────────────────────────────
        # A disabled, unselectable frame with a wide text label acts as a spacer
        # since ttk.Notebook doesn't support right-aligning tabs natively.
        _spacer = tk.Frame(self._notebook, bg=BG)
        self._notebook.add(_spacer, text=" " * 74, state="disabled")
        s.configure("App.TNotebook.Tab", borderwidth=0)

        # ── Settings tab ─────────────────────────────────────────────────────
        _prefs_tab, prefs_canvas, prefs_frame = _make_scroll_tab("  ⚙  ")
        self._prefs_frame  = prefs_frame
        self._prefs_canvas = prefs_canvas

        # tab index → canvas (order must match notebook.add() calls above)
        # index 3 is the spacer (disabled), index 4 is settings
        _tab_canvases = [trans_canvas, extract_canvas, edit_canvas, None, prefs_canvas]

        # Scroll whichever tab canvas is currently visible.
        # Guard: if the event originates from inside the log pane (or any
        # other widget that owns its own scroll), do nothing so we don't
        # double-scroll the upper pane while the user is reading the log.
        def _is_inside(widget, ancestor):
            """Return True if widget is ancestor or a descendant of it."""
            try:
                w = widget
                while w is not None:
                    if w is ancestor:
                        return True
                    w = w.master
            except Exception:
                pass
            return False

        def _scroll(event):
            # Ignore scrolls that belong to the log area or either
            # of the internal clip-list canvases (they bind their own handlers)
            ignored = (self._log_text,
                       self._clip_list_canvas,
                       self._edit_list_canvas)
            if any(_is_inside(event.widget, w) for w in ignored):
                return
            tab_id = self._notebook.index(self._notebook.select())
            try:
                target = _tab_canvases[tab_id]
            except IndexError:
                target = trans_canvas
            if target is None:
                return
            target.yview_scroll(-1 * (event.delta // 120), "units")

        self.root.bind("<MouseWheel>", _scroll)

        p  = self._settings_frame   # shorthand for Extraction content
        px = dict(padx=16)

        # ── Drop zone ───────────────────────────────────────────────────────
        self._build_drop_zone(p)

        # ── Options ─────────────────────────────────────────────────────────
        self._section(p, "Options")
        opts = self._card(p)
        self._build_options(opts)

        # ── File paths & script loader ─────────────────────────────────────
        self._section(p, "File Paths")
        paths = self._card(p)
        self._build_paths(paths)
        self._build_script_loader(paths)

        # ── Run mode ────────────────────────────────────────────────────────
        self._section(p, "Run Mode")
        modes = self._card(p)
        self._build_run_mode(modes)

        # ── Extract tab content (clip selection — always visible) ─────────────
        self._build_clips_panel(self._extract_frame)

        # ── Editing tab content ───────────────────────────────────────────────
        self._build_editing_tab(self._editing_frame)

        # ── Settings tab content ──────────────────────────────────────────────
        self._build_settings_tab(self._prefs_frame)

        # ── Log area (bottom pane) ────────────────────────────────────────────
        log_outer = tk.Frame(paned, bg=BG)
        paned.add(log_outer, stretch="always", minsize=120)
        log_outer.pack_propagate(False)

        # inner frame for padding (tk.Frame doesn't take tuple pady)
        log_inner = tk.Frame(log_outer, bg=BG)
        log_inner.pack(fill="both", expand=True, padx=16, pady=(4, 8))
        log_outer = log_inner

        self._section_inline(log_outer, "Output Log")

        # ── Audio extraction progress bar (hidden by default) ──────────────
        self._audio_bar_frame = tk.Frame(log_outer, bg=BG)
        _albl_row = tk.Frame(self._audio_bar_frame, bg=BG)
        _albl_row.pack(fill="x")
        tk.Label(_albl_row, text="Audio extraction",
                 font=("Segoe UI", 8, "bold"), bg=BG, fg=DIM).pack(side="left")
        self._audio_pct_lbl = tk.Label(_albl_row, text="0%",
                                       font=("Segoe UI", 8), bg=BG, fg=ACCENT)
        self._audio_pct_lbl.pack(side="left", padx=(6, 0))

        self._audio_bar = ctk.CTkProgressBar(
            self._audio_bar_frame, orientation="horizontal",
            progress_color=ACCENT, fg_color=ENTRY_BG, corner_radius=4
        )
        self._audio_bar.set(0)
        self._audio_bar.pack(fill="x", pady=(3, 6))
        # hidden until extraction starts — packed in queue handler
        self._audio_bar_frame.pack_forget()

        # ── Whisper progress bar (hidden until transcription starts) ──────────
        self._whisper_bar_frame = tk.Frame(log_outer, bg=BG)
        _wlbl_row = tk.Frame(self._whisper_bar_frame, bg=BG)
        _wlbl_row.pack(fill="x")
        tk.Label(_wlbl_row, text="Whisper transcription",
                 font=("Segoe UI", 8, "bold"), bg=BG, fg=DIM).pack(side="left")
        self._whisper_pct_lbl = tk.Label(_wlbl_row, text="0%",
                                         font=("Segoe UI", 8), bg=BG, fg=ACCENT)
        self._whisper_pct_lbl.pack(side="left", padx=(6, 0))
        self._whisper_ts_lbl = tk.Label(_wlbl_row, text="",
                                        font=("Segoe UI", 8), bg=BG, fg=DIM)
        self._whisper_ts_lbl.pack(side="left", padx=(8, 0))

        self._whisper_bar = ctk.CTkProgressBar(
            self._whisper_bar_frame, orientation="horizontal",
            progress_color=ACCENT, fg_color=ENTRY_BG, corner_radius=4
        )
        self._whisper_bar.set(0)
        self._whisper_bar.pack(fill="x", pady=(3, 6))
        self._whisper_bar_frame.pack_forget()

        # ── LLM analysis progress bar (hidden until analysis starts) ──────
        self._analysis_bar_frame = tk.Frame(log_outer, bg=BG)
        _anlbl_row = tk.Frame(self._analysis_bar_frame, bg=BG)
        _anlbl_row.pack(fill="x")
        tk.Label(_anlbl_row, text="LLM analysis",
                 font=("Segoe UI", 8, "bold"), bg=BG, fg=DIM).pack(side="left")
        self._analysis_pct_lbl = tk.Label(_anlbl_row, text="0%",
                                          font=("Segoe UI", 8), bg=BG, fg=ACCENT)
        self._analysis_pct_lbl.pack(side="left", padx=(6, 0))
        self._analysis_count_lbl = tk.Label(_anlbl_row, text="",
                                            font=("Segoe UI", 8), bg=BG, fg=DIM)
        self._analysis_count_lbl.pack(side="left", padx=(8, 0))

        self._analysis_bar = ctk.CTkProgressBar(
            self._analysis_bar_frame, orientation="horizontal",
            progress_color=ACCENT, fg_color=ENTRY_BG, corner_radius=4
        )
        self._analysis_bar.set(0)
        self._analysis_bar.pack(fill="x", pady=(3, 6))
        self._analysis_bar_frame.pack_forget()

        # ── Clip extraction progress bar (hidden by default) ─────────────
        self._extract_bar_frame = tk.Frame(log_outer, bg=BG)
        _elbl_row = tk.Frame(self._extract_bar_frame, bg=BG)
        _elbl_row.pack(fill="x")
        tk.Label(_elbl_row, text="Clip extraction",
                 font=("Segoe UI", 8, "bold"), bg=BG, fg=DIM).pack(side="left")
        self._extract_pct_lbl = tk.Label(_elbl_row, text="0%",
                                          font=("Segoe UI", 8), bg=BG, fg=ACCENT)
        self._extract_pct_lbl.pack(side="left", padx=(6, 0))
        self._extract_count_lbl = tk.Label(_elbl_row, text="",
                                            font=("Segoe UI", 8), bg=BG, fg=DIM)
        self._extract_count_lbl.pack(side="left", padx=(8, 0))

        self._extract_bar = ctk.CTkProgressBar(
            self._extract_bar_frame, orientation="horizontal",
            progress_color=ACCENT, fg_color=ENTRY_BG, corner_radius=4
        )
        self._extract_bar.set(0)
        self._extract_bar.pack(fill="x", pady=(3, 6))
        self._extract_bar_frame.pack_forget()

        # ── Slice progress bar (hidden until slicing starts) ─────────────
        self._slice_bar_frame = tk.Frame(log_outer, bg=BG)
        _slbl_row = tk.Frame(self._slice_bar_frame, bg=BG)
        _slbl_row.pack(fill="x")
        tk.Label(_slbl_row, text="Slicing",
                 font=("Segoe UI", 8, "bold"), bg=BG, fg=DIM).pack(side="left")
        self._slice_pct_lbl = tk.Label(_slbl_row, text="0%",
                                       font=("Segoe UI", 8), bg=BG, fg=ACCENT)
        self._slice_pct_lbl.pack(side="left", padx=(6, 0))
        self._slice_count_lbl = tk.Label(_slbl_row, text="",
                                         font=("Segoe UI", 8), bg=BG, fg=DIM)
        self._slice_count_lbl.pack(side="left", padx=(8, 0))
        self._slice_bar = ctk.CTkProgressBar(
            self._slice_bar_frame, progress_color=ACCENT,
            fg_color=ENTRY_BG, corner_radius=4,
        )
        self._slice_bar.set(0)
        self._slice_bar.pack(fill="x", pady=(3, 6))
        self._slice_bar_frame.pack_forget()

        # ── Image download progress bar (hidden until image step starts) ──
        self._image_bar_frame = tk.Frame(log_outer, bg=BG)
        _ilbl_row = tk.Frame(self._image_bar_frame, bg=BG)
        _ilbl_row.pack(fill="x")
        tk.Label(_ilbl_row, text="Visual aids",
                 font=("Segoe UI", 8, "bold"), bg=BG, fg=DIM).pack(side="left")
        self._image_pct_lbl = tk.Label(_ilbl_row, text="0%",
                                       font=("Segoe UI", 8), bg=BG, fg=ACCENT)
        self._image_pct_lbl.pack(side="left", padx=(6, 0))
        self._image_count_lbl = tk.Label(_ilbl_row, text="",
                                         font=("Segoe UI", 8), bg=BG, fg=DIM)
        self._image_count_lbl.pack(side="left", padx=(8, 0))
        self._image_bar = ctk.CTkProgressBar(
            self._image_bar_frame, progress_color=ACCENT,
            fg_color=ENTRY_BG, corner_radius=4,
        )
        self._image_bar.set(0)
        self._image_bar.pack(fill="x", pady=(3, 6))
        self._image_bar_frame.pack_forget()

        log_card = tk.Frame(log_outer, bg=CARD, pady=1)
        log_card.pack(fill="both", expand=True)

        self._log_text = tk.Text(
            log_card,
            font=("Consolas", 9), bg=ENTRY_BG, fg=TEXT,
            insertbackground=TEXT, relief="flat",
            padx=10, pady=8, wrap="word",
            state="disabled"
        )
        log_sb = SmoothScrollbar(log_card, command=self._log_text.yview)
        self._log_text.configure(yscrollcommand=log_sb.set)
        log_sb.pack(side="right", fill="y")
        self._log_text.pack(fill="both", expand=True)

        self._log_text.tag_configure("err",  foreground=ERR)
        self._log_text.tag_configure("warn", foreground=WARN)
        self._log_text.tag_configure("ok",   foreground=SUCCESS)
        self._log_text.tag_configure("head", foreground=ACCENT, font=("Consolas", 9, "bold"))
        self._log_text.tag_configure("dim",  foreground=DIM)

        clear_btn = ctk.CTkButton(log_outer, text="Clear log", font=("Segoe UI", 10),
                                   fg_color=BG, text_color=DIM, cursor="hand2",
                                   hover_color=ACCENT2, corner_radius=8,
                                   command=self._clear_log)
        clear_btn.pack(anchor="e", pady=(2, 0))

    # ── Clips extraction panel ────────────────────────────────────────────────

    def _build_clips_panel(self, parent):
        """Build the clip-selection panel in the Extract tab."""
        self._clips_panel = tk.Frame(parent, bg=BG)
        self._clips_panel.pack(fill="x", padx=16, pady=(8, 8))

        # ── Header row ──
        hdr = tk.Frame(self._clips_panel, bg=BG)
        hdr.pack(fill="x", pady=(8, 2))
        tk.Label(hdr, text="CLIP EXTRACTION", font=("Segoe UI", 7, "bold"),
                 bg=BG, fg=ACCENT).pack(side="left")
        tk.Frame(hdr, bg=SEP, height=1).pack(side="left", fill="x", expand=True,
                                              padx=(8, 0), pady=5)

        # ── Control row ──
        ctrl = tk.Frame(self._clips_panel, bg=BG)
        ctrl.pack(fill="x", pady=(0, 4))

        self._btn(ctrl, "Select All", BORDER, TEXT,
                  self._select_all_clips, padx=10, pady=3).pack(side="left", padx=(0, 4))
        self._btn(ctrl, "Deselect All", BORDER, TEXT,
                  self._deselect_all_clips, padx=10, pady=3).pack(side="left", padx=(0, 12))
        self._clip_count_lbl = tk.Label(ctrl, text="", font=("Segoe UI", 8),
                                        bg=BG, fg=DIM)
        self._clip_count_lbl.pack(side="left")

        # ── Scrollable clip list ──
        list_outer = tk.Frame(self._clips_panel, bg=CARD,
                              highlightbackground=BORDER, highlightthickness=1)
        list_outer.pack(fill="x", pady=(0, 6))

        self._clip_list_canvas = tk.Canvas(list_outer, bg=CARD,
                                           highlightthickness=0, height=160)
        list_vsb = SmoothScrollbar(list_outer, command=self._clip_list_canvas.yview)
        self._clip_list_frame = tk.Frame(self._clip_list_canvas, bg=CARD)
        self._clip_list_frame.bind(
            "<Configure>",
            lambda e: self._clip_list_canvas.configure(
                scrollregion=self._clip_list_canvas.bbox("all"))
        )
        self._clip_list_canvas.create_window((0, 0), window=self._clip_list_frame,
                                             anchor="nw", tags="clip_list_win")
        # Empty-state placeholder (destroyed when clips are populated)
        self._clip_empty_lbl = tk.Label(
            self._clip_list_frame,
            text="No clips yet — run a transcription or load a clips script.",
            font=("Segoe UI", 9), bg=CARD, fg=DIM, pady=20,
        )
        self._clip_empty_lbl.pack(fill="x", padx=16)
        self._clip_list_canvas.configure(yscrollcommand=list_vsb.set)
        self._clip_list_canvas.bind(
            "<Configure>",
            lambda e: self._clip_list_canvas.itemconfigure(
                "clip_list_win", width=e.width)
        )
        list_vsb.pack(side="right", fill="y")
        self._clip_list_canvas.pack(side="left", fill="both", expand=True)

        self._clip_list_canvas.bind(
            "<MouseWheel>",
            lambda e: self._clip_list_canvas.yview_scroll(
                -1 * (e.delta // 120), "units")
        )

        # ── Output dir override ──
        out_row = tk.Frame(self._clips_panel, bg=BG)
        out_row.pack(fill="x", pady=(0, 6))
        out_row.columnconfigure(1, weight=1)

        tk.Label(out_row, text="Output dir", font=("Segoe UI", 9),
                 bg=BG, fg=DIM).grid(row=0, column=0, sticky="w", padx=(0, 8))
        ctk.CTkEntry(out_row, textvariable=self.export_dir, font=("Segoe UI", 9),
                     fg_color=ENTRY_BG, text_color=TEXT,
                     corner_radius=6, border_color=BORDER
                     ).grid(row=0, column=1, sticky="ew", padx=(0, 6))
        ctk.CTkButton(out_row, text="Browse", font=("Segoe UI", 10),
                      fg_color=BORDER, text_color=TEXT, cursor="hand2",
                      hover_color=ACCENT2, corner_radius=8,
                      command=lambda: self._browse_path(self.export_dir, "dir")
                      ).grid(row=0, column=2)

        # ── Extract button ──
        self._extract_btn = self._btn(
            self._clips_panel, "⬇  Extract Selected Clips", ACCENT, "white",
            self._on_extract_clips, font=("Segoe UI", 10, "bold"), padx=20, pady=8
        )
        self._extract_btn.pack(anchor="w", pady=(0, 4))

    def _populate_clips_panel(self, clips: list):
        """Fill the clip list with checkboxes and show the panel."""
        # Clear previous rows
        for w in self._clip_list_frame.winfo_children():
            w.destroy()
        self._clip_vars.clear()
        self._clip_rows: list[tk.Frame] = []
        self._last_clips = clips

        for clip in clips:
            var = tk.BooleanVar(value=True)
            self._clip_vars.append(var)

            row = tk.Frame(self._clip_list_frame, bg=CARD)
            row.pack(fill="x", padx=8, pady=2)
            self._clip_rows.append(row)

            ctk.CTkCheckBox(
                row, variable=var,
                fg_color=ACCENT, hover_color=ACCENT2, text_color=TEXT,
                font=("Segoe UI", 10), corner_radius=4, text="",
                command=self._update_clip_count
            ).pack(side="left")

            score_color = SUCCESS if clip.virality_score >= 7 else (
                WARN if clip.virality_score >= 4 else ERR)
            tk.Label(row, text=f"{clip.virality_score}/10",
                     font=("Segoe UI", 8, "bold"), bg=CARD,
                     fg=score_color, width=4).pack(side="left")

            tk.Label(row,
                     text=f"#{clip.rank}  {clip.title}",
                     font=("Segoe UI", 9, "bold"), bg=CARD, fg=TEXT,
                     anchor="w").pack(side="left", padx=(4, 12))

            tk.Label(row,
                     text=f"{cf.fmt_time(clip.clip_start)} → {cf.fmt_time(clip.clip_end)}"
                          f"  ({clip.clip_duration:.0f}s)  {clip.content_type.upper()}",
                     font=("Segoe UI", 8), bg=CARD, fg=DIM,
                     anchor="w").pack(side="left")

        self._update_clip_count()

        # Resize list canvas height to fit clips (max 200px)
        row_h = 28
        height = min(len(clips) * row_h + 8, 200)
        self._clip_list_canvas.configure(height=height)

        # Switch to the Extract tab and scroll to top
        self._notebook.select(1)  # Extract tab is index 1
        self._extract_canvas.after(50, lambda: self._extract_canvas.yview_moveto(0.0))

    def _update_clip_count(self):
        selected = sum(v.get() for v in self._clip_vars)
        total = len(self._clip_vars)
        self._clip_count_lbl.config(text=f"{selected} of {total} selected")

    def _select_all_clips(self):
        for v in self._clip_vars:
            v.set(True)
        self._update_clip_count()

    def _deselect_all_clips(self):
        for v in self._clip_vars:
            v.set(False)
        self._update_clip_count()

    # ── Editing tab ───────────────────────────────────────────────────────────

    def _build_editing_tab(self, parent):
        """Populate the Editing tab with its initial structure."""
        # ── Permanent section (always visible for manual use) ────────────────
        sec = self._create_clip_slice_section(parent, "", is_permanent=True)
        self._clip_sections.append(sec)

        # Keep legacy aliases so existing code doesn't break
        self._slice_clip_dir    = sec["clip_dir_var"]
        self._slice_files_lbl   = sec["files_lbl"]
        self._slice_profile_lbl = sec["profile_lbl"]
        self._slice_btn         = sec["slice_btn"]
        self._slice_only_btn    = sec["slice_only_btn"]
        self._premiere_btn      = sec["premiere_btn"]

        # ── Auto-remove checkbox ─────────────────────────────────────────────
        auto_row = tk.Frame(parent, bg=BG)
        auto_row.pack(fill="x", padx=16, pady=(2, 4))
        ctk.CTkCheckBox(
            auto_row, text="Auto remove clip section after slicing",
            variable=self._auto_remove_var,
            fg_color=ACCENT, hover_color=ACCENT2, text_color=TEXT,
            font=("Segoe UI", 9), corner_radius=4,
        ).pack(side="left")

        # ── Container for dynamically added clip sections ────────────────────
        self._dynamic_clips_container = tk.Frame(parent, bg=BG)
        self._dynamic_clips_container.pack(fill="x")

        # ── Initialise variables used by internal editing methods ────────────
        self._edit_clips_dir = tk.StringVar()
        self._edit_out_dir = tk.StringVar()
        self._edit_crf = tk.IntVar(value=23)
        self._trim_start = tk.DoubleVar(value=0.0)
        self._trim_end = tk.DoubleVar(value=0.0)
        self._edit_clip_vars: list = []
        self._edit_list_canvas = tk.Canvas(parent)
        self._edit_list_frame = tk.Frame(self._edit_list_canvas)
        self._edit_empty_lbl = tk.Label(self._edit_list_frame)

    # ── Reusable clip-section factory ────────────────────────────────────────

    def _create_clip_slice_section(self, parent, clip_dir_path: str,
                                   is_permanent: bool = False) -> dict:
        """Build one complete 'Generate Slices from Clip' widget group.

        Returns a dict of widget references for later manipulation.
        """
        section_id = self._next_section_id
        self._next_section_id += 1

        outer = tk.Frame(parent, bg=BG)
        outer.pack(fill="x")

        # Section header
        if is_permanent:
            self._section(outer, "Generate Slices from Clip")
        else:
            folder_name = Path(clip_dir_path).name if clip_dir_path else "Clip"
            hdr_frame = tk.Frame(outer, bg=BG)
            hdr_frame.pack(fill="x", padx=16, pady=(10, 0))
            tk.Frame(hdr_frame, bg=SEP, height=1).pack(side="left", fill="x", expand=True)
            tk.Label(hdr_frame, text=f"  {folder_name.upper()}  ",
                     font=("Segoe UI", 7, "bold"), bg=BG, fg=ACCENT
                     ).pack(side="left")
            tk.Frame(hdr_frame, bg=SEP, height=1).pack(side="left", fill="x", expand=True)
            # close button
            close_btn = tk.Label(hdr_frame, text=" ✕ ", font=("Segoe UI", 8),
                                 bg=BG, fg=DIM, cursor="hand2")
            close_btn.pack(side="left", padx=(4, 0))

        # Card
        sl_card = self._card(outer)
        sl_card.columnconfigure(1, weight=1)

        clip_dir_var = tk.StringVar(value=clip_dir_path)
        tk.Label(sl_card, text="Clip folder", font=("Segoe UI", 9),
                 bg=CARD, fg=DIM).grid(row=0, column=0, sticky="w",
                                       padx=(0, 8), pady=4)
        ctk.CTkEntry(sl_card, textvariable=clip_dir_var,
                     font=("Segoe UI", 9), fg_color=ENTRY_BG, text_color=TEXT,
                     corner_radius=6, border_color=BORDER
                     ).grid(row=0, column=1, sticky="ew", padx=(0, 6))
        ctk.CTkButton(sl_card, text="Browse", font=("Segoe UI", 10),
                      fg_color=BORDER, text_color=TEXT, cursor="hand2",
                      hover_color=ACCENT2, corner_radius=8,
                      command=lambda: self._browse_slice_dir_for_section(section_id)
                      ).grid(row=0, column=2)

        profile_lbl = tk.Label(sl_card, text="", font=("Segoe UI", 8),
                               bg=CARD, fg=DIM, anchor="w")
        profile_lbl.grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 2))

        files_lbl = tk.Label(sl_card, text="No folder selected.",
                             font=("Consolas", 8), bg=CARD, fg=DIM,
                             justify="left", anchor="w", wraplength=580)
        files_lbl.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(0, 6))

        # Buttons
        btn_row = tk.Frame(outer, bg=BG, pady=8)
        btn_row.pack(fill="x", padx=16)

        slice_btn = self._btn(
            btn_row, "✂  Slice + Premiere", ACCENT, "white",
            lambda sid=section_id: self._on_generate_slices_for_section(sid, premiere=True),
            font=("Segoe UI", 11, "bold"), padx=20, pady=9,
        )
        slice_btn.pack(side="left", padx=(0, 6))
        slice_only_btn = self._btn(
            btn_row, "✂  Slice", BORDER, TEXT,
            lambda sid=section_id: self._on_generate_slices_for_section(sid, premiere=False),
            font=("Segoe UI", 10), padx=16, pady=9,
        )
        slice_only_btn.pack(side="left", padx=(0, 6))
        premiere_btn = self._btn(
            btn_row, "🎬  Premiere", BORDER, TEXT,
            lambda sid=section_id: self._on_premiere_only_for_section(sid),
            font=("Segoe UI", 10), padx=16, pady=9,
        )
        premiere_btn.pack(side="left")

        section = {
            "id": section_id,
            "frame": outer,
            "clip_dir_var": clip_dir_var,
            "files_lbl": files_lbl,
            "profile_lbl": profile_lbl,
            "slice_btn": slice_btn,
            "slice_only_btn": slice_only_btn,
            "premiere_btn": premiere_btn,
            "is_permanent": is_permanent,
        }

        # Wire up folder-change detection
        clip_dir_var.trace_add("write",
            lambda *_, sid=section_id: self._on_slice_dir_changed_for_section(sid))

        # Close button binding (dynamic sections only)
        if not is_permanent:
            close_btn.bind("<Button-1>",
                           lambda e, sid=section_id: self._remove_clip_section(sid))

        # Trigger initial scan if a path was provided
        if clip_dir_path:
            self.root.after(100, lambda sid=section_id: self._on_slice_dir_changed_for_section(sid))

        return section

    def _whisper_lang_code(self) -> str:
        """Return the Whisper language code for the currently selected language."""
        return self._WHISPER_LANGUAGES.get(
            self.transcription_language.get(), "en")

    # ── Settings tab ─────────────────────────────────────────────────────────

    _PROFILES_PATH = Path(__file__).parent / "streamclipper_profiles.json"

    # Display name → Whisper language code (alphabetical, English first)
    _WHISPER_LANGUAGES: dict = {
        "English":            "en",
        "Afrikaans":          "af",
        "Arabic":             "ar",
        "Armenian":           "hy",
        "Azerbaijani":        "az",
        "Belarusian":         "be",
        "Bosnian":            "bs",
        "Bulgarian":          "bg",
        "Catalan":            "ca",
        "Chinese":            "zh",
        "Croatian":           "hr",
        "Czech":              "cs",
        "Danish":             "da",
        "Dutch":              "nl",
        "Estonian":           "et",
        "Finnish":            "fi",
        "French":             "fr",
        "Galician":           "gl",
        "German":             "de",
        "Greek":              "el",
        "Hebrew":             "he",
        "Hindi":              "hi",
        "Hungarian":          "hu",
        "Icelandic":          "is",
        "Indonesian":         "id",
        "Italian":            "it",
        "Japanese":           "ja",
        "Kannada":            "kn",
        "Kazakh":             "kk",
        "Korean":             "ko",
        "Latvian":            "lv",
        "Lithuanian":         "lt",
        "Macedonian":         "mk",
        "Malay":              "ms",
        "Marathi":            "mr",
        "Maori":              "mi",
        "Nepali":             "ne",
        "Norwegian":          "no",
        "Persian":            "fa",
        "Polish":             "pl",
        "Portuguese":         "pt",
        "Romanian":           "ro",
        "Russian":            "ru",
        "Serbian":            "sr",
        "Slovak":             "sk",
        "Slovenian":          "sl",
        "Spanish":            "es",
        "Swahili":            "sw",
        "Swedish":            "sv",
        "Tagalog":            "tl",
        "Tamil":              "ta",
        "Telugu":             "te",
        "Thai":               "th",
        "Turkish":            "tr",
        "Ukrainian":          "uk",
        "Urdu":               "ur",
        "Vietnamese":         "vi",
        "Welsh":              "cy",
    }

    from providers import PROVIDERS as _PROVIDERS
    _KNOWN_MODELS = _PROVIDERS["anthropic"]["models"]  # default; updated by provider selection

    def _build_settings_tab(self, parent):
        px = dict(padx=16)
        s = ttk.Style()
        s.configure("Prof.TCombobox",
                    fieldbackground=ENTRY_BG, background=ENTRY_BG,
                    foreground=TEXT, selectbackground=ACCENT,
                    selectforeground=TEXT)

        # ── Transcription language (at top for quick access) ─────────────
        self._section(parent, "Transcription Language")
        lang_card = self._card(parent)
        lang_card.columnconfigure(1, weight=1)

        tk.Label(lang_card, text="Language", font=("Segoe UI", 9),
                 bg=CARD, fg=DIM).grid(row=0, column=0, sticky="w",
                                       padx=(0, 8), pady=4)
        lang_cb = ctk.CTkComboBox(
            lang_card, variable=self.transcription_language,
            values=list(self._WHISPER_LANGUAGES.keys()),
            state="readonly",
            font=("Segoe UI", 9), width=300,
            fg_color=ENTRY_BG, border_color=BORDER, button_color=ACCENT,
            button_hover_color=ACCENT2, dropdown_fg_color=ENTRY_BG,
            dropdown_hover_color=ACCENT, text_color=TEXT, corner_radius=6,
        )
        lang_cb.grid(row=0, column=1, sticky="w")

        self._lang_code_lbl = tk.Label(
            lang_card, text="", font=("Consolas", 8),
            bg=CARD, fg=DIM,
        )
        self._lang_code_lbl.grid(row=0, column=2, sticky="w", padx=(10, 0))

        def _on_lang_change(*_):
            code = self._WHISPER_LANGUAGES.get(
                self.transcription_language.get(), "en")
            self._lang_code_lbl.config(text=f"code: {code}")

        self.transcription_language.trace_add("write", _on_lang_change)
        _on_lang_change()   # set initial label

        tk.Label(lang_card,
                 text="Whisper will treat the audio as this language.\n"
                      "Leave on English if the stream is in English.",
                 font=("Segoe UI", 8), bg=CARD, fg=DIM, justify="left"
                 ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(2, 4))

        # ── Active model profile ─────────────────────────────────────────
        self._section(parent, "Active Model Profile")
        act_card = self._card(parent)
        act_card.columnconfigure(1, weight=1)

        tk.Label(act_card, text="Profile", font=("Segoe UI", 9),
                 bg=CARD, fg=DIM).grid(row=0, column=0, sticky="w",
                                       padx=(0, 8), pady=4)
        self._prof_dropdown = ctk.CTkComboBox(
            act_card, variable=self._prof_active,
            state="readonly",
            font=("Segoe UI", 9), width=280,
            fg_color=ENTRY_BG, border_color=BORDER, button_color=ACCENT,
            button_hover_color=ACCENT2, dropdown_fg_color=ENTRY_BG,
            dropdown_hover_color=ACCENT, text_color=TEXT, corner_radius=6,
        )
        self._prof_dropdown.grid(row=0, column=1, sticky="ew", padx=(0, 6))
        self._btn(act_card, "Apply", ACCENT, "white",
                  self._apply_profile, padx=14, pady=3
                  ).grid(row=0, column=2)

        self._prof_status_lbl = tk.Label(
            act_card, text="No profiles saved yet.",
            font=("Segoe UI", 8), bg=CARD, fg=DIM, anchor="w",
        )
        self._prof_status_lbl.grid(row=1, column=0, columnspan=3,
                                   sticky="w", pady=(0, 4))

        # ── Profile editor ────────────────────────────────────────────────
        self._section(parent, "Profile Editor")
        ed_card = self._card(parent)
        ed_card.columnconfigure(1, weight=1)

        from providers import PROVIDERS

        # Row 0 — Name
        tk.Label(ed_card, text="Name", font=("Segoe UI", 9),
                 bg=CARD, fg=DIM).grid(row=0, column=0, sticky="w",
                                       padx=(0, 8), pady=4)
        ctk.CTkEntry(ed_card, textvariable=self._prof_name,
                     font=("Segoe UI", 9), fg_color=ENTRY_BG, text_color=TEXT,
                     corner_radius=6, border_color=BORDER
                     ).grid(row=0, column=1, sticky="ew", padx=(0, 6))

        # Row 1 — Provider
        tk.Label(ed_card, text="Provider", font=("Segoe UI", 9),
                 bg=CARD, fg=DIM).grid(row=1, column=0, sticky="w",
                                       padx=(0, 8), pady=4)
        provider_labels = [PROVIDERS[k]["label"] for k in PROVIDERS]
        self._provider_keys = list(PROVIDERS.keys())   # keep in sync
        self._prof_provider_display = tk.StringVar(value=PROVIDERS["anthropic"]["label"])
        self._prof_provider_cb = ctk.CTkComboBox(
            ed_card, variable=self._prof_provider_display,
            values=provider_labels, state="readonly",
            font=("Segoe UI", 9),
            fg_color=ENTRY_BG, border_color=BORDER, button_color=ACCENT,
            button_hover_color=ACCENT2, dropdown_fg_color=ENTRY_BG,
            dropdown_hover_color=ACCENT, text_color=TEXT, corner_radius=6,
        )
        self._prof_provider_cb.grid(row=1, column=1, sticky="ew", padx=(0, 6))

        # Row 2 — Server URL (only visible for Ollama)
        self._url_label = tk.Label(ed_card, text="Server URL", font=("Segoe UI", 9),
                                   bg=CARD, fg=DIM)
        self._url_entry = ctk.CTkEntry(ed_card, textvariable=self._prof_base_url,
                                       font=("Segoe UI", 9), fg_color=ENTRY_BG, text_color=TEXT,
                                       corner_radius=6, border_color=BORDER)
        self._url_label.grid(row=2, column=0, sticky="w", padx=(0, 8), pady=4)
        self._url_entry.grid(row=2, column=1, sticky="ew", padx=(0, 6))
        self._url_label.grid_remove()
        self._url_entry.grid_remove()

        # Row 3 — API key
        self._key_label = tk.Label(ed_card, text="API key", font=("Segoe UI", 9),
                                   bg=CARD, fg=DIM)
        self._key_label.grid(row=3, column=0, sticky="w", padx=(0, 8), pady=4)
        self._prof_key_entry = ctk.CTkEntry(
            ed_card, textvariable=self._prof_api_key,
            font=("Segoe UI", 9), fg_color=ENTRY_BG, text_color=TEXT,
            corner_radius=6, border_color=BORDER, show="•",
        )
        self._prof_key_entry.grid(row=3, column=1, sticky="ew", padx=(0, 6))
        self._prof_key_shown = False

        key_btn_frame = tk.Frame(ed_card, bg=CARD)
        key_btn_frame.grid(row=3, column=2, sticky="w")
        ctk.CTkButton(key_btn_frame, text="Show", font=("Segoe UI", 10),
                      fg_color=BORDER, text_color=TEXT, cursor="hand2",
                      hover_color=ACCENT2, corner_radius=8,
                      command=self._toggle_prof_key,
                      ).pack(side="left")
        self._prof_api_key_hint = tk.Label(
            key_btn_frame, text=f"(env: {PROVIDERS['anthropic']['env_key']})",
            font=("Segoe UI", 7), bg=CARD, fg=DIM,
        )
        self._prof_api_key_hint.pack(side="left", padx=(6, 0))
        self._key_btn_frame = key_btn_frame

        # Row 4 — Model
        tk.Label(ed_card, text="Model", font=("Segoe UI", 9),
                 bg=CARD, fg=DIM).grid(row=4, column=0, sticky="w",
                                       padx=(0, 8), pady=4)
        self._prof_model_cb = ctk.CTkComboBox(
            ed_card, variable=self._prof_model,
            values=PROVIDERS["anthropic"]["models"],
            font=("Segoe UI", 9),
            fg_color=ENTRY_BG, border_color=BORDER, button_color=ACCENT,
            button_hover_color=ACCENT2, dropdown_fg_color=ENTRY_BG,
            dropdown_hover_color=ACCENT, text_color=TEXT, corner_radius=6,
        )
        self._prof_model_cb.grid(row=4, column=1, sticky="ew", padx=(0, 6))

        model_extra = tk.Frame(ed_card, bg=CARD)
        model_extra.grid(row=4, column=2, sticky="w", padx=(2, 0))
        self._model_hint_lbl = tk.Label(
            model_extra, text="(type any model ID)",
            font=("Segoe UI", 8), bg=CARD, fg=DIM,
        )
        self._model_hint_lbl.pack(side="left")
        self._refresh_models_btn = ctk.CTkButton(
            model_extra, text="Refresh", font=("Segoe UI", 10),
            fg_color=BORDER, text_color=TEXT, cursor="hand2",
            hover_color=ACCENT2, corner_radius=8,
            command=self._refresh_ollama_models,
        )
        self._refresh_models_btn.pack(side="left", padx=(4, 0))
        self._refresh_models_btn.pack_forget()   # hidden until Ollama selected

        def _on_provider_change(*_):
            display = self._prof_provider_display.get()
            for key, info in PROVIDERS.items():
                if info["label"] == display:
                    self._prof_provider.set(key)
                    self._prof_model_cb.configure(values=info["models"])
                    self._prof_model.set(info["default_model"])
                    is_ollama = (key == "ollama")
                    # Toggle Server URL row visibility
                    if is_ollama:
                        self._url_label.grid()
                        self._url_entry.grid()
                    else:
                        self._url_label.grid_remove()
                        self._url_entry.grid_remove()
                    # Toggle API key row visibility
                    if is_ollama:
                        self._key_label.grid_remove()
                        self._prof_key_entry.grid_remove()
                        self._key_btn_frame.grid_remove()
                    else:
                        self._key_label.grid()
                        self._prof_key_entry.grid()
                        self._key_btn_frame.grid()
                        self._prof_api_key_hint.config(
                            text=f"(env: {info['env_key']})")
                        env_val = os.environ.get(info.get("env_key", ""), "")
                        if env_val and not self._prof_api_key.get().strip():
                            self._prof_api_key.set(env_val)
                    # Toggle Refresh Models button
                    if is_ollama:
                        self._refresh_models_btn.pack(side="left", padx=(4, 0))
                        self._model_hint_lbl.config(text="(or type a name)")
                    else:
                        self._refresh_models_btn.pack_forget()
                        self._model_hint_lbl.config(text="(type any model ID)")
                    break

        self._prof_provider_display.trace_add("write", _on_provider_change)

        # Save / Delete buttons
        btn_row = tk.Frame(parent, bg=BG, pady=8)
        btn_row.pack(fill="x", **px)
        self._btn(btn_row, "💾  Save Profile", ACCENT, "white",
                  self._save_current_profile,
                  font=("Segoe UI", 10, "bold"), padx=20, pady=7
                  ).pack(side="left", padx=(0, 8))
        self._btn(btn_row, "🗑  Delete Profile", BORDER, ERR,
                  self._delete_current_profile, padx=16, pady=7
                  ).pack(side="left")

        # ── Model reference ───────────────────────────────────────────────
        self._section(parent, "Model Reference")
        ref_card = self._card(parent)
        ref_groups = [
            ("Anthropic (Claude)", [
                ("claude-opus-4-6",              "Most capable — best for edit plans & analysis"),
                ("claude-sonnet-4-6",   "Fast + smart — good balance for most tasks"),
                ("claude-3-5-haiku-20241022",    "Fastest / cheapest — suitable for simple prompts"),
            ]),
            ("OpenAI", [
                ("o3",                           "Reasoning model — best for complex analysis"),
                ("gpt-4.1",                      "Flagship — strong all-around"),
                ("gpt-4.1-mini",                 "Fast + capable — good balance"),
                ("gpt-4.1-nano",                 "Fastest / cheapest — simple prompts"),
            ]),
            ("Google Gemini", [
                ("gemini-2.5-pro-preview-06-05", "Most capable — best for complex tasks"),
                ("gemini-2.5-flash-preview-05-20", "Fast + smart — good balance"),
                ("gemini-2.0-flash",             "Fast general-purpose"),
            ]),
            ("xAI (Grok)", [
                ("grok-3",                       "Most capable Grok model"),
                ("grok-3-fast",                  "Faster variant of Grok 3"),
                ("grok-3-mini",                  "Lightweight — good for simple prompts"),
            ]),
            ("Ollama (Local)", [
                ("qwen3.5:27b",                  "Best for 4090 — 40 tok/s, 262K context"),
                ("qwen3:14b",                    "Smaller Qwen — faster, less capable"),
                ("llama3.1:8b",                   "Fast general-purpose (ollama pull llama3.1:8b)"),
                ("gemma3:12b",                   "Google's local model — good quality"),
                ("deepseek-r1:14b",              "Reasoning model — slower but thorough"),
            ]),
        ]
        for group_name, models in ref_groups:
            tk.Label(ref_card, text=group_name, font=("Segoe UI", 9, "bold"),
                     bg=CARD, fg=ACCENT, anchor="w").pack(fill="x", pady=(6, 2))
            for model_id, desc in models:
                r = tk.Frame(ref_card, bg=CARD)
                r.pack(fill="x", pady=1)
                tk.Label(r, text=model_id, font=("Consolas", 8, "bold"),
                         bg=CARD, fg=TEXT, width=36, anchor="w").pack(side="left")
                tk.Label(r, text=desc, font=("Segoe UI", 8),
                         bg=CARD, fg=DIM, anchor="w").pack(side="left", padx=(8, 0))

    def _toggle_prof_key(self):
        if self._prof_key_entry is None:
            return
        self._prof_key_shown = not self._prof_key_shown
        self._prof_key_entry.configure(show="" if self._prof_key_shown else "•")

    def _refresh_ollama_models(self):
        """Query the Ollama server and populate the model dropdown."""
        from providers import list_ollama_models
        base_url = self._prof_base_url.get().strip() or "http://localhost:11434"
        try:
            models = list_ollama_models(base_url)
        except Exception as exc:
            messagebox.showerror(
                "Ollama not reachable",
                f"Could not connect to Ollama at:\n{base_url}\n\n"
                f"Make sure Ollama is running (ollama serve).\n\n"
                f"Error: {exc}",
            )
            return
        if not models:
            messagebox.showinfo("No models",
                                "Ollama is running but no models are installed.\n\n"
                                "Pull one with:  ollama pull qwen3.5:27b")
            return
        self._prof_model_cb.configure(values=models)
        if self._prof_model.get() not in models:
            self._prof_model.set(models[0])

    def _update_prof_dropdown(self):
        names = sorted(self._profiles.keys())
        self._prof_dropdown.configure(values=names)
        if names and not self._prof_active.get():
            self._prof_active.set(names[0])
        count = len(names)
        self._prof_status_lbl.config(
            text=f"{count} profile{'s' if count != 1 else ''} saved."
                 if count else "No profiles saved yet."
        )
        # Refresh the indicator label in the Editing tab
        self._refresh_slice_profile_label()

    def _refresh_slice_profile_label(self):
        """Update the small 'active profile' hint in the Editing tab."""
        if not hasattr(self, "_slice_profile_lbl"):
            return
        name = self._prof_active.get()
        if name and name in self._profiles:
            p = self._profiles[name]
            provider = p.get("provider", "anthropic")
            model = p.get("model", "—")
            from providers import PROVIDERS
            prov_label = PROVIDERS.get(provider, {}).get("label", provider)
            self._slice_profile_lbl.config(
                text=f"Using profile: {name}  ({prov_label} / {model})",
                fg=SUCCESS,
            )
        else:
            self._slice_profile_lbl.config(
                text="⚠  No active profile — set one in the Settings tab.",
                fg=WARN,
            )

    def _apply_profile(self):
        name = self._prof_active.get()
        if not name or name not in self._profiles:
            messagebox.showwarning("No profile", "Select a profile first.")
            return
        p = self._profiles[name]
        self._prof_name.set(name)
        # Set provider first so the model dropdown & visibility updates
        provider = p.get("provider", "anthropic")
        self._prof_provider.set(provider)
        from providers import PROVIDERS
        info = PROVIDERS.get(provider, PROVIDERS["anthropic"])
        self._prof_provider_display.set(info["label"])  # triggers _on_provider_change
        self._prof_base_url.set(p.get("base_url", info.get("base_url", "http://localhost:11434")))
        self._prof_api_key.set(p.get("api_key", ""))
        self._prof_model.set(p.get("model", info["default_model"]))
        self._refresh_slice_profile_label()

    def _save_current_profile(self):
        name     = self._prof_name.get().strip()
        provider = self._prof_provider.get().strip() or "anthropic"
        api_key  = self._prof_api_key.get().strip()
        model    = self._prof_model.get().strip()
        base_url = self._prof_base_url.get().strip()
        if not name:
            messagebox.showwarning("No name", "Enter a profile name first.")
            return
        if provider != "ollama" and not api_key:
            messagebox.showwarning("No API key", "Enter an API key.")
            return
        if not model:
            from providers import PROVIDERS
            model = PROVIDERS.get(provider, {}).get("default_model", "claude-opus-4-6")
        profile_data = {
            "provider": provider,
            "api_key": api_key,
            "model": model,
        }
        if provider == "ollama":
            profile_data["base_url"] = base_url or "http://localhost:11434"
        self._profiles[name] = profile_data
        self._prof_active.set(name)
        self._save_profiles_file()
        self._update_prof_dropdown()

    def _delete_current_profile(self):
        name = self._prof_active.get()
        if not name or name not in self._profiles:
            messagebox.showwarning("No profile", "Select a profile to delete.")
            return
        if not messagebox.askyesno("Delete profile",
                                   f"Delete profile '{name}'?"):
            return
        del self._profiles[name]
        self._prof_active.set("")
        self._save_profiles_file()
        self._update_prof_dropdown()

    def _load_profiles(self):
        """Load profiles from disk and populate dropdowns."""
        from providers import PROVIDERS
        if self._PROFILES_PATH.exists():
            try:
                data = json.loads(self._PROFILES_PATH.read_text(encoding="utf-8"))
                self._profiles = data.get("profiles", {})
                active = data.get("active", "")
                if active in self._profiles:
                    self._prof_active.set(active)
                    p = self._profiles[active]
                    self._prof_name.set(active)
                    provider = p.get("provider", "anthropic")
                    self._prof_provider.set(provider)
                    info = PROVIDERS.get(provider, PROVIDERS["anthropic"])
                    # Setting display triggers _on_provider_change (shows/hides fields)
                    self._prof_provider_display.set(info["label"])
                    self._prof_base_url.set(
                        p.get("base_url", info.get("base_url", "http://localhost:11434")))
                    self._prof_api_key.set(p.get("api_key", ""))
                    self._prof_model.set(p.get("model", info["default_model"]))
            except Exception:
                pass
        self._update_prof_dropdown()
        self._refresh_slice_profile_label()

        # Refresh model lists from provider APIs in the background
        threading.Thread(
            target=self._background_refresh_models, daemon=True
        ).start()

    def _background_refresh_models(self):
        """Fetch live model lists from each provider we have a key for."""
        from providers import refresh_all_models, PROVIDERS
        try:
            refresh_all_models(self._profiles)
        except Exception:
            return
        # Schedule a UI update on the main thread to refresh combobox values
        self.root.after(0, self._apply_refreshed_models)

    def _apply_refreshed_models(self):
        """Push refreshed model lists into the settings comboboxes."""
        from providers import PROVIDERS
        # Update the model combobox if the currently selected provider has new models
        provider = self._prof_provider.get().strip() or "anthropic"
        info = PROVIDERS.get(provider, PROVIDERS["anthropic"])
        self._prof_model_cb.configure(values=info["models"])

    def _save_profiles_file(self):
        try:
            data = {
                "active":   self._prof_active.get(),
                "profiles": self._profiles,
            }
            self._PROFILES_PATH.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:
            self._q.put(("warn", f"Could not save profiles: {exc}\n"))

    # ── Slice-generation helpers ──────────────────────────────────────────────

    def _find_section(self, section_id: int) -> dict | None:
        for sec in self._clip_sections:
            if sec["id"] == section_id:
                return sec
        return None

    def _browse_slice_dir(self):
        d = filedialog.askdirectory(title="Select Clip Folder")
        if d:
            self._slice_clip_dir.set(d)

    def _browse_slice_dir_for_section(self, section_id: int):
        sec = self._find_section(section_id)
        if not sec:
            return
        d = filedialog.askdirectory(title="Select Clip Folder")
        if d:
            sec["clip_dir_var"].set(d)

    def _on_slice_dir_changed(self, *_):
        """Legacy wrapper for the permanent section."""
        if self._clip_sections:
            self._on_slice_dir_changed_for_section(self._clip_sections[0]["id"])

    def _on_slice_dir_changed_for_section(self, section_id: int):
        """Scan the chosen folder and update the detected-files label.

        If this is the permanent section and the folder contains clip_*
        subdirectories (i.e. a parent clips folder), auto-populate dynamic
        sections for each clip subfolder.
        """
        sec = self._find_section(section_id)
        if not sec:
            return
        folder = sec["clip_dir_var"].get().strip()
        if not folder or not Path(folder).is_dir():
            sec["files_lbl"].config(text="No folder selected.")
            return

        p = Path(folder)

        # If this is the permanent section, check for clip_* subdirectories
        if sec["is_permanent"]:
            clip_subdirs = sorted(
                d for d in p.iterdir()
                if d.is_dir() and d.name.lower().startswith("clip_")
            )
            if clip_subdirs:
                sec["files_lbl"].config(
                    text=f"Found {len(clip_subdirs)} clip folders — loading…")
                self._populate_editing_clip_sections(
                    [str(d) for d in clip_subdirs])
                sec["files_lbl"].config(
                    text=f"Loaded {len(clip_subdirs)} clip folders below.")
                return

        mp4s     = [f.name for f in sorted(p.glob("*.mp4"))
                    if not f.stem.startswith("slice_")]
        jsons    = [f.name for f in sorted(p.glob("*_transcript.json"))]
        prompts  = [f.name for f in sorted(p.glob("*_editing_prompt.txt"))]
        plans    = [f.name for f in sorted(p.glob("*_edit_plan.txt"))]
        slices   = sorted(p.glob("slice_*.mp4"))

        lines = []
        lines.append(f"📹  clip      : {mp4s[0] if mp4s else '⚠ not found'}")
        lines.append(f"📄  transcript: {jsons[0] if jsons else '⚠ not found'}")
        lines.append(f"📝  prompt    : {prompts[0] if prompts else '⚠ not found'}")
        if plans:
            lines.append(f"🗒  edit plan : {plans[0]}  (will be overwritten)")
        if slices:
            lines.append(f"✂  slices    : {len(slices)} existing "
                         f"(slice_01 … slice_{len(slices):02d})  — will be overwritten")
        sec["files_lbl"].config(text="\n".join(lines))

    # ── Premiere project agent prompt ────────────────────────────────────────

    _PREMIERE_PROMPT = r"""Execute the following steps using your available MCP
tools to set up a Premiere Pro Shorts project. You MUST call the tools
described in each step — do NOT just describe what you would do. Actually
invoke create_project, get_project_info, import_media, etc.

Use the Premiere MCP tools (mcp__pr-mcp__*) for all Premiere operations
and Filesystem MCP (mcp__Windows-MCP__FileSystem) for file discovery only.

Context & Known Behaviors
* create_project will time out — this is expected behavior. Always follow it
  immediately with get_project_info to confirm the project was created
  successfully.
* The current plugin version creates 0 empty tracks when a Shorts sequence is
  created — clips are added directly by targeting track indices.
* KNOWN OFFSET: When add_media_to_sequence targets an index that requires
  Premiere to auto-create gap tracks, the resulting track index as reported
  by the API may be 1 lower than requested (e.g. requesting index 5 may
  land on index 4). To compensate, all post-gap track indices in this
  prompt are set 1 higher than the desired final position.
* set_clip_transform scale works reliably. Position does NOT work due to a
  known Premiere UXP API bug — do not attempt to set position via the tool.
  Set position manually in Premiere's Effect Controls panel after the script
  completes.

Task
You will be given a clip folder path. The folder contains a main .mp4 file
(the full-length clip) with the same name as the folder, plus additional slice
files.

CLIP FOLDER PATH: {clip_folder}

Step 1 — Create the project
Call create_project with:
* directory_path: the clip folder path
* project_name: the folder name (same as the .prproj filename, without
  extension)
Then immediately call get_project_info to confirm it opened. Note the project
ID and sequence list.

Step 2 — Discover and import media
Use Filesystem MCP to list the clip folder. Find the main full-length .mp4
file (the one matching the folder name), all slice_*.mp4 files, and all
visual_*.jpg / visual_*.png / visual_*.webp files (visual aid images).

Import media in TWO separate import_media calls to avoid timeouts:

Call 1 — Video files:
* The main full-length .mp4 from the clip folder
* ALL slice_*.mp4 files found in the clip folder

If the first import call times out, that is expected (same as
create_project). Do NOT retry — proceed to Call 2.

Call 2 — Image files:
* ALL visual_*.jpg, visual_*.png, and visual_*.webp files found in the clip folder (visual aid images for B-roll)
* D:\Visual Productions\Photoshop\Trikeri\Shorts_MiniSocialMediaBanner_Twitch.png
* D:\Visual Productions\Photoshop\Trikeri\Shorts_MiniSocialMediaBanner_Youtube.png

If this call also times out, do NOT retry. Proceed to get_project_info
to verify which files were imported successfully.

IMPORTANT: import_media may time out on large batches — this is normal
and does NOT mean the import failed. Never retry a timed-out import.
Always move forward and verify with get_project_info.

If any image files failed to import (missing from the project after
get_project_info), skip them entirely — do not retry and do not let
missing images block the rest of the setup. Just proceed with whatever
media imported successfully.

Step 3 — Create the Shorts sequence
Call create_shorts_sequence with sequence name {sequence_name} (where the
number matches the clip number). This creates a 1080x1920, 30fps vertical
sequence.

Step 4 — Add the full clip to Track 1 (video index 0)
Call add_media_to_sequence:
* item_name: the main .mp4 filename
* video_track_index: 0
* audio_track_index: 0
* insertion_time_ticks: 0

Step 5 — Add the full clip again to Track 2 (video index 1)
Call add_media_to_sequence again with the same clip:
* item_name: the main .mp4 filename
* video_track_index: 1
* audio_track_index: 1
* insertion_time_ticks: 0

Step 6 — Set scale on Track 1 clip
Call set_clip_transform:
* video_track_index: 0
* track_item_index: 0
* scale: 198

Step 7 — Set scale on Track 2 clip
Call set_clip_transform:
* video_track_index: 1
* track_item_index: 0
* scale: 234

Step 8 — Add visual images to video track index 5
IMPORTANT: Do NOT use add_media_on_new_track — it appends to the next
available index which does not leave the 2-track gap we need.
Instead, use add_media_to_sequence which places media on an exact index
and Premiere will auto-create any missing tracks in between.

Add ALL visual_* files (visual_01, visual_02, etc.) to video track index 5,
placed sequentially one after another starting at insertion_time_ticks: 0.
For each visual image, call add_media_to_sequence:
* item_name: the visual filename (e.g. visual_01.jpg)
* video_track_index: 5
* audio_track_index: 2
* insertion_time_ticks: 0 for the first image; for subsequent images, use
  the end_time_ticks of the previous image so they sit back-to-back.
* overwrite: false

This forces Premiere to create empty tracks at indices 2, 3, and 4, then
places the first visual on index 5. The 2 empty gap tracks (indices 2-3)
plus the visual images track (index 4 once the offset settles) are all
created before the banners.

If a visual file was not imported (timed out or failed during Step 2),
skip it — do not retry the import. Just continue with the remaining
visuals that are available in the project.

Step 9 — Add Twitch banner on video track index 6
Call add_media_to_sequence:
* item_name: Shorts_MiniSocialMediaBanner_Twitch.png
* video_track_index: 6
* audio_track_index: 3
* insertion_time_ticks: 0

Step 10 — Add YouTube banner on video track index 7
Call add_media_to_sequence:
* item_name: Shorts_MiniSocialMediaBanner_Youtube.png
* video_track_index: 7
* audio_track_index: 4
* insertion_time_ticks: 0

Step 11 — Notify completion
Report back with:
* Project path
* Sequence name and ID
* Final track layout:
  - Video 0: Main clip (scale 198)
  - Video 1: Main clip (scale 234)
  - Video 2: (empty)
  - Video 3: (empty)
  - Video 4: Visual images (B-roll stills)
  - Video 5: Twitch banner
  - Video 6: YouTube banner
* Reminder that position must be set manually in Effect Controls:
   * Video 0: position {{1900, 860}}
   * Video 1: position {{-1163, -480}}
   * Video 5 (Twitch banner): position as needed
   * Video 6 (YouTube banner): position as needed
* Note: Track indices above are the intended layout. Due to Premiere's
  known offset behavior, the API may report indices shifted by 1. Verify
  the visual layout in the Premiere UI matches the intended structure.

Notes
* Only use Filesystem/Windows-MCP for listing files and discovering paths.
  Never use them to click, navigate, or interact with the Premiere UI.
* If create_project times out, that is normal — proceed to get_project_info
  without retrying.
* Do not add slice files to the timeline in this task.
"""

    def _on_create_premiere_project(self):
        """Spawn a claude agent to create a Premiere project from the selected clip folder."""
        folder = self._slice_clip_dir.get().strip()
        if not folder or not Path(folder).is_dir():
            messagebox.showwarning("No folder",
                                   "Select a clip folder first.")
            return

        folder_name = Path(folder).name

        # Derive a sequence name like clip_01_Shorts from the folder name
        clip_num_m = re.search(r"clip[_\s]*(\d+)", folder_name, re.IGNORECASE)
        if clip_num_m:
            seq_name = f"clip_{int(clip_num_m.group(1)):02d}_Shorts"
        else:
            seq_name = f"{folder_name}_Shorts"

        prompt = self._PREMIERE_PROMPT.format(
            clip_folder=folder.replace("\\", "/"),
            sequence_name=seq_name,
        )

        # Save prompt to file and copy to clipboard.
        # MCP tools (Premiere, Windows-MCP) are only available in an
        # interactive Claude session — can't run via `claude -p`.
        prompt_path = Path(folder) / "premiere_setup_prompt.md"
        prompt_path.write_text(prompt, encoding="utf-8")

        self.root.clipboard_clear()
        self.root.clipboard_append(prompt)
        self.root.update()   # required for clipboard to persist on Windows

        self._q.put(("head",
                      f"\n=== Create Premiere Project: {folder_name} ===\n"))
        self._q.put(("log", f"Sequence: {seq_name}\n"))
        self._q.put(("ok",
                      f"Prompt saved to: {prompt_path}\n"))
        self._q.put(("ok",
                      "Prompt copied to clipboard!\n"))
        self._q.put(("log",
                      "Paste it into Claude Code or Claude Desktop to execute.\n"
                      "(Premiere MCP tools are only available in interactive sessions.)\n"))

    def _check_premiere_ready(self) -> bool:
        """Check if Premiere Pro and the MCP proxy are reachable.

        Returns True if everything looks good, False after showing an error.
        """
        # 1. Check if Adobe Premiere Pro is running
        try:
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq Adobe Premiere Pro.exe", "/NH"],
                capture_output=True, text=True, timeout=5,
            )
            if "Adobe Premiere Pro.exe" not in result.stdout:
                messagebox.showerror(
                    "Premiere Pro not running",
                    "Adobe Premiere Pro does not appear to be running.\n\n"
                    "Please launch Premiere Pro before using the Premiere feature.",
                )
                return False
        except Exception:
            pass  # tasklist failed — skip this check

        # 2. Check if the MCP socket proxy is reachable on localhost:3001
        #    The proxy is a WebSocket server, so an HTTP GET may return an
        #    HTTP error (400/426) — that still proves the server is listening.
        import socket as _socket
        try:
            with _socket.create_connection(("localhost", 3001), timeout=3):
                pass  # TCP connect succeeded — server is up
        except (OSError, _socket.timeout):
            messagebox.showerror(
                "MCP proxy not running",
                "Cannot reach the Premiere MCP proxy at localhost:3001.\n\n"
                "Make sure the adb-proxy-socket server is running:\n"
                "  cd adb-proxy-socket && node proxy.js",
            )
            return False

        return True

    def _on_generate_slices(self, premiere=True):
        """Legacy wrapper — delegates to the permanent section."""
        if self._clip_sections:
            self._on_generate_slices_for_section(self._clip_sections[0]["id"], premiere)

    def _on_generate_slices_for_section(self, section_id: int, premiere=True):
        sec = self._find_section(section_id)
        if not sec:
            return

        if premiere and not self._check_premiere_ready():
            return

        folder = sec["clip_dir_var"].get().strip()
        if not folder or not Path(folder).is_dir():
            messagebox.showwarning("No folder",
                                   "Select a clip folder first.")
            return

        from providers import PROVIDERS

        provider = self._prof_provider.get().strip() or "anthropic"
        prov_info = PROVIDERS.get(provider, PROVIDERS["anthropic"])

        if provider == "ollama":
            api_key = "ollama"
            base_url = self._prof_base_url.get().strip() or \
                       prov_info.get("base_url", "http://localhost:11434")
        else:
            api_key = self._prof_api_key.get().strip() or \
                      os.environ.get(prov_info["env_key"], "")
            base_url = ""
            if not api_key:
                messagebox.showerror(
                    "No API key",
                    f"No API key found.\n\n"
                    f"Add one in the Settings tab and save a profile, or set the\n"
                    f"{prov_info['env_key']} environment variable.",
                )
                return

        model = self._prof_model.get().strip() or prov_info["default_model"]

        sec["slice_btn"].configure(state="disabled")
        sec["slice_only_btn"].configure(state="disabled")
        sec["premiere_btn"].configure(state="disabled")
        threading.Thread(
            target=self._generate_slices_worker,
            args=(folder, provider, api_key, model, base_url, premiere, section_id),
            daemon=True,
        ).start()

    def _on_premiere_only(self):
        """Legacy wrapper — delegates to the permanent section."""
        if self._clip_sections:
            self._on_premiere_only_for_section(self._clip_sections[0]["id"])

    def _on_premiere_only_for_section(self, section_id: int):
        sec = self._find_section(section_id)
        if not sec:
            return

        if not self._check_premiere_ready():
            return

        folder = sec["clip_dir_var"].get().strip()
        if not folder or not Path(folder).is_dir():
            messagebox.showwarning("No folder",
                                   "Select a clip folder first.")
            return

        clip_dir = Path(folder)
        prompt_path = clip_dir / "premiere_setup_prompt.md"

        if prompt_path.exists():
            premiere_prompt = prompt_path.read_text(encoding="utf-8")
        else:
            folder_name = clip_dir.name
            clip_num_m = re.search(r"clip[_\s]*(\d+)", folder_name,
                                   re.IGNORECASE)
            seq_name = (f"clip_{int(clip_num_m.group(1)):02d}_Shorts"
                        if clip_num_m else f"{folder_name}_Shorts")
            premiere_prompt = self._PREMIERE_PROMPT.format(
                clip_folder=folder.replace("\\", "/"),
                sequence_name=seq_name,
            )
            try:
                prompt_path.write_text(premiere_prompt, encoding="utf-8")
            except Exception as exc:
                messagebox.showwarning("Save failed",
                                       f"Could not save prompt: {exc}")

        self.root.clipboard_clear()
        self.root.clipboard_append(premiere_prompt)
        self.root.update()

        self._q.put(("head", "\n=== Premiere Prompt ===\n"))
        if prompt_path.exists():
            self._q.put(("ok", f"Prompt loaded from: {prompt_path.name}\n"))
        self._q.put(("ok",
                      "Premiere setup prompt copied to clipboard — "
                      "paste into Claude Code or Claude Desktop to execute.\n"))

    def _remove_clip_section(self, section_id: int):
        """Destroy a dynamic clip section's widgets and remove from the list."""
        sec = self._find_section(section_id)
        if not sec or sec["is_permanent"]:
            return
        sec["frame"].destroy()
        self._clip_sections = [s for s in self._clip_sections if s["id"] != section_id]

    def _populate_editing_clip_sections(self, extracted_dirs: list[str]):
        """Clear old dynamic sections, create new ones from extraction output."""
        # Remove existing dynamic sections
        for sec in list(self._clip_sections):
            if not sec["is_permanent"]:
                sec["frame"].destroy()
        self._clip_sections = [s for s in self._clip_sections if s["is_permanent"]]

        # Create a section for each extracted clip folder
        for clip_dir_path in extracted_dirs:
            sec = self._create_clip_slice_section(
                self._dynamic_clips_container, clip_dir_path, is_permanent=False)
            self._clip_sections.append(sec)

        # Switch to the Editing tab
        self._notebook.select(2)

    def _generate_slices_worker(self, clip_dir_str: str, provider: str,
                                api_key: str, model: str = "claude-opus-4-6",
                                base_url: str = "", premiere: bool = True,
                                section_id: int = 0):
        try:
            clip_dir = Path(clip_dir_str)

            # ── Locate files ─────────────────────────────────────────────────
            mp4s = [f for f in sorted(clip_dir.glob("*.mp4"))
                    if not f.stem.startswith("slice_")]
            prompts = sorted(clip_dir.glob("*_editing_prompt.txt"))
            transcripts = sorted(clip_dir.glob("*_transcript.json"))

            if not mp4s:
                self._q.put(("err", "No clip .mp4 found in folder.\n"))
                return
            if not prompts:
                self._q.put(("err", "No _editing_prompt.txt found. "
                                    "Run extraction first to generate it.\n"))
                return

            clip_mp4    = mp4s[0]
            prompt_path = prompts[0]

            with open(prompt_path, encoding="utf-8") as f:
                prompt_text = f.read()

            # Parse clip_start / clip_end from the prompt metadata block
            clip_start, clip_end = self._parse_clip_range_from_prompt(prompt_text)

            # Load transcript segments for sentence-boundary snapping
            segments: list = []
            if transcripts:
                try:
                    segments = cf.load_transcript_from_json(str(transcripts[0]))
                    self._q.put(("log",
                                 f"Loaded {len(segments)} transcript segments "
                                 f"for sentence-boundary snapping.\n"))
                except Exception as exc:
                    self._q.put(("warn",
                                 f"Could not load transcript ({exc}) — "
                                 "cuts will use Claude's timestamps as-is.\n"))

            self._q.put(("head",
                         f"\n=== Generate Slices: {clip_mp4.name} ===\n"))
            if clip_start:
                self._q.put(("dim",
                             f"Clip spans {cf.fmt_time(clip_start)} → "
                             f"{cf.fmt_time(clip_end)} in source"
                             f" — will offset cut times accordingly.\n"))

            # ── Send prompt to LLM ────────────────────────────────────────────
            from providers import PROVIDERS, make_client
            prov_label = PROVIDERS.get(provider, {}).get("label", provider)
            self._q.put(("log", f"Sending editing prompt to {prov_label} ({model}) …\n"))
            try:
                client = make_client(provider, api_key, base_url=base_url)
                edit_plan = client.message(
                    model=model,
                    user_prompt=prompt_text,
                    max_tokens=4096,
                )
            except Exception as exc:
                self._q.put(("err", f"API error: {exc}\n"))
                return

            # Save the plan next to the clip
            plan_path = clip_dir / f"{clip_mp4.stem}_edit_plan.txt"
            with open(plan_path, "w", encoding="utf-8") as f:
                f.write(edit_plan)
            self._q.put(("log", f"Edit plan saved → {plan_path.name}\n"))

            # ── Parse cut list ────────────────────────────────────────────────
            cuts = cf.parse_cut_list(edit_plan)
            if not cuts:
                self._q.put(("err",
                             "Could not parse any cuts from Claude's response.\n"
                             f"Check {plan_path.name} for the raw output.\n"))
                return

            self._q.put(("log",
                         f"Parsed {len(cuts)} cuts. Extracting slices …\n"))

            # ── Extract each slice ────────────────────────────────────────────
            # Remove old slices so numbering is always clean
            for old in sorted(clip_dir.glob("slice_*.mp4")):
                try:
                    old.unlink()
                except OSError:
                    pass

            total_dur = 0.0
            written   = 0
            num_cuts  = len(cuts)
            self._q.put(("slice_start", num_cuts))
            for idx, cut in enumerate(cuts, 1):
                if self._cancel.is_set():
                    self._q.put(("warn", "Slice generation cancelled.\n"))
                    break

                # Snap the end of this cut to the nearest Whisper segment
                # boundary so we never chop mid-sentence, then add 2 s padding.
                # hard_limit keeps us inside the clip file (clip_end in source).
                raw_end    = cut["end"]
                snapped_end = cf.snap_cut_end(
                    raw_end,
                    segments,
                    padding=2.0,
                    hard_limit=clip_end if clip_end < float("inf") else None,
                )

                # Timestamps from Claude are source-file relative;
                # the clip.mp4 begins at clip_start in the source.
                ss       = max(0.0, cut["start"] - clip_start)
                duration = snapped_end - cut["start"]   # uses snapped end
                if duration <= 0:
                    self._q.put(("warn",
                                 f"  Slice {idx}: skipped "
                                 f"(invalid duration {duration:.2f}s)\n"))
                    continue

                # Log if snapping meaningfully extended the cut
                extension = snapped_end - raw_end
                snap_note = (f" [snapped +{extension:.1f}s]"
                             if extension > 0.05 else "")

                slice_path = clip_dir / f"slice_{idx:02d}.mp4"
                cmd = [
                    "ffmpeg", "-y",
                    "-ss", f"{ss:.3f}",
                    "-i",  str(clip_mp4),
                    "-t",  f"{duration:.3f}",
                    "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "192k",
                    str(slice_path),
                ]
                res = subprocess.run(cmd, capture_output=True, text=True,
                                     encoding="utf-8", errors="replace")
                if res.returncode == 0:
                    total_dur += duration
                    written   += 1
                    self._q.put(("ok",
                                 f"  ✓ {slice_path.name}"
                                 f"  ({duration:.1f}s{snap_note})"
                                 f"  {cut['reason']}\n"))
                else:
                    self._q.put(("err",
                                 f"  ✗ slice {idx}: "
                                 f"{res.stderr[-200:]}\n"))
                self._q.put(("slice_progress", (idx, num_cuts)))

            self._q.put(("slice_complete", None))

            # ── Summary ───────────────────────────────────────────────────────
            self._q.put(("log",
                         f"\n{written} slices written to: {clip_dir}\n"
                         f"Total duration: {total_dur:.1f}s"
                         f" ({total_dur / 60:.1f} min)\n"))
            if total_dur < 60:
                self._q.put(("warn",
                             "⚠  Total is under 60 s — "
                             "consider reviewing the edit plan.\n"))
            elif total_dur > 150:
                self._q.put(("warn",
                             "⚠  Total exceeds 150 s — "
                             "consider tightening the cut list.\n"))
            else:
                self._q.put(("ok",
                             "✓  Duration is within the 60–150 s target.\n"))

            self._q.put(("ok", "=== Slice generation complete ===\n"))

            # ── Visual aid image search & download ────────────────────────
            self._q.put(("head", "\n=== Searching for visual aid images ===\n"))
            try:
                self._download_visual_aids(cuts, clip_dir, client, model)
            except Exception as exc:
                self._q.put(("warn",
                             f"Visual aid step failed (non-fatal): {exc}\n"))

            # ── Token usage summary ────────────────────────────────────────
            if client.total_tokens > 0:
                self._q.put(("log",
                    f"\nToken usage — input: {client.input_tokens:,}  "
                    f"output: {client.output_tokens:,}  "
                    f"total: {client.total_tokens:,}\n"))

            # ── Generate Premiere setup prompt (if requested) ──────────────
            if premiere:
                folder_name = clip_dir.name
                clip_num_m = re.search(r"clip[_\s]*(\d+)", folder_name,
                                       re.IGNORECASE)
                seq_name = (f"clip_{int(clip_num_m.group(1)):02d}_Shorts"
                            if clip_num_m else f"{folder_name}_Shorts")

                premiere_prompt = self._PREMIERE_PROMPT.format(
                    clip_folder=clip_dir_str.replace("\\", "/"),
                    sequence_name=seq_name,
                )
                prompt_path = clip_dir / "premiere_setup_prompt.md"
                try:
                    prompt_path.write_text(premiere_prompt, encoding="utf-8")
                    self._q.put(("log",
                        f"🎬 Premiere prompt → {prompt_path.name}\n"))
                    self._q.put(("premiere_clipboard", premiere_prompt))
                except Exception as exc:
                    self._q.put(("warn",
                        f"Could not save Premiere prompt: {exc}\n"))

        except Exception as exc:
            self._q.put(("err", f"Unexpected error: {exc}\n"))
        finally:
            self._q.put(("slice_done", section_id))

    def _download_visual_aids(self, cuts: list, clip_dir: Path,
                              client, model: str):
        """Ask the LLM for image search queries, then download one image per slice.

        *client* is a ``providers.LLMClient`` instance.
        """
        import json as _json
        import urllib.request
        import urllib.parse

        # ── 1. Build the list of slice descriptions ──────────────────────
        desc_lines = []
        for i, cut in enumerate(cuts, 1):
            desc_lines.append(f"{i}. {cut.get('reason', 'no description')}")
        descriptions = "\n".join(desc_lines)

        # ── 2. Ask Claude for image search queries ───────────────────────
        search_prompt = (
            "You are helping find visual aid images for a YouTube Shorts video.\n"
            "Below are descriptions of each video slice. For each one, suggest a\n"
            "short Google Image search query (3-6 words) for a relevant visual aid\n"
            "image that would support the topic being discussed.\n\n"
            "Rules:\n"
            "- Only suggest images for slices that discuss a specific concept, game,\n"
            "  tool, product, place, or visual topic.\n"
            "- For slices that are purely personal opinion, emotion, or talking with\n"
            "  no visual subject, return null for that entry.\n"
            "- Return ONLY a JSON array with one entry per slice. Each entry is\n"
            "  either a search query string or null.\n"
            "- No markdown fences, no explanation — just the raw JSON array.\n\n"
            f"Slices:\n{descriptions}"
        )

        self._q.put(("log", "Asking LLM for image search queries…\n"))
        raw = client.message(
            model=model,
            user_prompt=search_prompt,
            max_tokens=1024,
        ).strip()
        # Strip markdown fences if Claude added them anyway
        if raw.startswith("```"):
            raw = re.sub(r"^```\w*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)

        try:
            queries = _json.loads(raw)
        except _json.JSONDecodeError:
            self._q.put(("warn",
                         f"Could not parse image queries from Claude:\n{raw[:300]}\n"))
            return

        if not isinstance(queries, list) or len(queries) != len(cuts):
            self._q.put(("warn",
                         f"Expected {len(cuts)} queries, got {len(queries) if isinstance(queries, list) else 'non-list'}.\n"))
            # Pad or truncate to match
            if isinstance(queries, list):
                queries = (queries + [None] * len(cuts))[:len(cuts)]
            else:
                return

        # ── 3. Download images ───────────────────────────────────────────
        downloaded = 0
        num_queries = len(queries)
        self._q.put(("image_start", num_queries))
        for i, query in enumerate(queries, 1):
            if query is None:
                self._q.put(("dim", f"  slice {i:02d}: skipped (no visual topic)\n"))
                self._q.put(("image_progress", (i, num_queries)))
                continue

            self._q.put(("log", f"  slice {i:02d}: searching \"{query}\"…\n"))
            try:
                img_path = self._search_and_download_image(
                    query, clip_dir, f"visual_{i:02d}")
                if img_path:
                    self._q.put(("ok", f"    ✓ {img_path.name}\n"))
                    downloaded += 1
                else:
                    self._q.put(("warn", f"    ✗ no suitable image found\n"))
            except Exception as exc:
                self._q.put(("warn", f"    ✗ download failed: {exc}\n"))
            self._q.put(("image_progress", (i, num_queries)))

        self._q.put(("image_complete", None))
        self._q.put(("log",
                     f"\n{downloaded} visual aid image(s) saved to {clip_dir}\n"))

    def _search_and_download_image(self, query: str, out_dir: Path,
                                   filename_stem: str) -> Path | None:
        """Search Bing Images and download the first usable result."""
        import urllib.request
        import urllib.parse
        import json as _json

        _UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
               "AppleWebKit/537.36 (KHTML, like Gecko) "
               "Chrome/120.0.0.0 Safari/537.36")

        # ── Bing Image Search — image URLs are in "murl" JSON fields ─────
        search_url = (
            "https://www.bing.com/images/search?q="
            + urllib.parse.quote_plus(query)
            + "&form=HDRSC2&first=1&safeSearch=Moderate"
        )
        req = urllib.request.Request(search_url, headers={"User-Agent": _UA})

        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")

        # Bing embeds full-size image URLs as "murl":"https://..." in the
        # inline JSON metadata for each thumbnail tile.
        candidates = re.findall(r'"murl"\s*:\s*"(https?://[^"]+)"', html)

        if not candidates:
            # Fallback: look for any direct image URL in the page
            candidates = re.findall(
                r'(https?://[^\s"<>]+\.(?:jpg|jpeg|png|webp))',
                html, re.IGNORECASE
            )
            candidates = [
                u for u in candidates
                if "bing.com" not in u and "microsoft.com" not in u
                and "favicon" not in u.lower()
            ]

        if not candidates:
            return None

        # Try downloading the first few candidates until one succeeds
        from PIL import Image
        import io

        for img_url in candidates[:8]:
            try:
                img_req = urllib.request.Request(
                    img_url, headers={"User-Agent": _UA})
                with urllib.request.urlopen(img_req, timeout=10) as img_resp:
                    data = img_resp.read()

                # Skip tiny images (likely thumbnails / icons)
                if len(data) < 5000:
                    continue

                # Validate this is actually an image by checking magic bytes
                # (servers often return HTML error pages with image Content-Type)
                magic = data[:12]
                is_image = (
                    magic[:3] == b"\xff\xd8\xff"            # JPEG
                    or magic[:8] == b"\x89PNG\r\n\x1a\n"    # PNG
                    or magic[:4] == b"RIFF" and magic[8:12] == b"WEBP"  # WebP
                    or magic[:4] == b"GIF8"                  # GIF
                    or magic[:4] == b"\x00\x00\x00\x1c"     # AVIF/HEIF
                )
                if not is_image:
                    continue

                # Always re-encode through Pillow as a clean JPEG.
                # This fixes malformed headers, strips unsupported formats
                # (WebP, AVIF) that Premiere can't open, and normalises
                # colour space to RGB.
                try:
                    img = Image.open(io.BytesIO(data))
                    img = img.convert("RGB")
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=95)
                    data = buf.getvalue()
                except Exception:
                    continue  # Skip images that can't be decoded

                out_path = out_dir / f"{filename_stem}.jpg"
                out_path.write_bytes(data)
                return out_path

            except Exception:
                continue

        return None

    @staticmethod
    def _parse_clip_range_from_prompt(prompt_text: str) -> tuple:
        """Return (clip_start, clip_end) in seconds from the prompt metadata.

        Falls back to (0.0, inf) if the line cannot be parsed.
        """
        m = re.search(r"Source range:\s+(\S+)\s*→\s*(\S+)", prompt_text)
        if m:
            try:
                return cf.parse_time(m.group(1)), cf.parse_time(m.group(2))
            except Exception:
                pass
        return 0.0, float("inf")

    @staticmethod
    def _parse_clip_start_from_prompt(prompt_text: str) -> float:
        """Kept for backwards compatibility — returns clip_start only."""
        m = re.search(r"Source range:\s+(\S+)\s*→", prompt_text)
        if m:
            try:
                return cf.parse_time(m.group(1))
            except Exception:
                pass
        return 0.0

    def _refresh_edit_clip_list(self):
        """Scan the clip-source folder and populate the editing clip list."""
        folder = self._edit_clips_dir.get().strip()
        if not folder or not Path(folder).is_dir():
            messagebox.showwarning("No folder",
                                   "Set a valid Clips folder first.")
            return

        mp4_files = sorted(Path(folder).glob("*.mp4"))

        # Clear existing rows
        for w in self._edit_list_frame.winfo_children():
            w.destroy()
        self._edit_clip_vars = []

        if not mp4_files:
            tk.Label(self._edit_list_frame,
                     text="No .mp4 files found in that folder.",
                     font=("Segoe UI", 9), bg=CARD, fg=DIM,
                     pady=20).pack()
            return

        for mp4 in mp4_files:
            var = tk.BooleanVar(value=True)
            self._edit_clip_vars.append((var, mp4))

            row = tk.Frame(self._edit_list_frame, bg=CARD)
            row.pack(fill="x", padx=8, pady=2)

            ctk.CTkCheckBox(row, variable=var,
                            fg_color=ACCENT, hover_color=ACCENT2, text_color=TEXT,
                            font=("Segoe UI", 10), corner_radius=4, text=""
                            ).pack(side="left")

            size_mb = mp4.stat().st_size / 1_048_576
            tk.Label(row, text=f"{size_mb:6.1f} MB",
                     font=("Segoe UI", 8), bg=CARD, fg=DIM,
                     width=9, anchor="e").pack(side="left")
            tk.Label(row, text=mp4.name,
                     font=("Segoe UI", 9), bg=CARD, fg=TEXT,
                     anchor="w").pack(side="left", padx=(8, 0))

        # Resize canvas
        row_h = 28
        h = min(len(mp4_files) * row_h + 8, 200)
        self._edit_list_canvas.configure(height=h)
        self._editing_canvas.after(
            50, lambda: self._editing_canvas.yview_moveto(0.0))

    def _on_edit_reencode(self):
        """Re-encode selected clips with trim offsets applied."""
        clips = [(v, p) for v, p in getattr(self, "_edit_clip_vars", [])
                 if v.get()]
        if not clips:
            messagebox.showwarning("Nothing selected",
                                   "Tick at least one clip in the list above.")
            return

        out_dir = self._edit_out_dir.get().strip()
        if not out_dir:
            messagebox.showwarning("No output folder",
                                   "Set an output folder in Re-encode & Export.")
            return

        Path(out_dir).mkdir(parents=True, exist_ok=True)
        trim_s = self._trim_start.get()
        trim_e = self._trim_end.get()
        crf    = self._edit_crf.get()

        def _worker():
            self._q.put(("log", f"\n=== Re-encode: {len(clips)} clip(s) ===\n"))
            for _var, src in clips:
                out = Path(out_dir) / src.name
                # Build ffmpeg trim args
                ss_args = ["-ss", str(trim_s)] if trim_s > 0 else []
                # To trim the end we shorten duration by probing — use -sseof for end trim
                to_args = ["-sseof", f"-{trim_e}"] if trim_e > 0 else []
                cmd = (
                    ["ffmpeg", "-y"]
                    + ss_args
                    + ["-i", str(src)]
                    + to_args
                    + ["-c:v", "libx264", "-crf", str(crf),
                       "-c:a", "aac", "-b:a", "192k",
                       "-movflags", "+faststart",
                       str(out)]
                )
                self._q.put(("log", f"Re-encoding: {src.name}\n"))
                try:
                    res = subprocess.run(cmd, capture_output=True,
                                        text=True, encoding="utf-8",
                                        errors="replace")
                    if res.returncode == 0:
                        self._q.put(("log", f"  ✓ → {out.name}\n"))
                    else:
                        self._q.put(("log", f"  ✗ ffmpeg error:\n{res.stderr[-800:]}\n"))
                except FileNotFoundError:
                    self._q.put(("log", "  ✗ ffmpeg not found — is it on your PATH?\n"))
            self._q.put(("log", "=== Re-encode complete ===\n"))

        threading.Thread(target=_worker, daemon=True).start()

    # ── Section helpers ───────────────────────────────────────────────────────

    def _section(self, parent, title):
        f = tk.Frame(parent, bg=BG, padx=16)
        f.pack(fill="x", pady=(10, 2))
        tk.Label(f, text=title.upper(), font=("Segoe UI", 7, "bold"),
                 bg=BG, fg=ACCENT).pack(side="left")
        tk.Frame(f, bg=SEP, height=1).pack(side="left", fill="x", expand=True,
                                            padx=(8, 0), pady=5)

    def _section_inline(self, parent, title):
        f = tk.Frame(parent, bg=BG)
        f.pack(fill="x", pady=(0, 4))
        tk.Label(f, text=title.upper(), font=("Segoe UI", 7, "bold"),
                 bg=BG, fg=ACCENT).pack(side="left")
        tk.Frame(f, bg=SEP, height=1).pack(side="left", fill="x", expand=True,
                                            padx=(8, 0), pady=5)

    def _card(self, parent):
        f = tk.Frame(parent, bg=CARD, padx=16, pady=12)
        f.pack(fill="x", padx=16, pady=(0, 2))
        return f

    def _btn(self, parent, text, bg, fg, cmd, state="normal",
             font=("Segoe UI", 10), **kw):
        # Filter out params CTkButton doesn't support
        kw.pop("padx", None)
        kw.pop("pady", None)
        return ctk.CTkButton(parent, text=text, font=font,
                             fg_color=bg, text_color=fg,
                             hover_color=ACCENT2, corner_radius=8,
                             command=cmd, state=state, **kw)

    def _lbl(self, parent, text, row, col, **grid_kw):
        tk.Label(parent, text=text, font=("Segoe UI", 9), bg=CARD,
                 fg=DIM, anchor="w").grid(row=row, column=col,
                                          sticky="w", pady=4, **grid_kw)

    # ── Drop zone ─────────────────────────────────────────────────────────────

    def _build_drop_zone(self, parent):
        outer = tk.Frame(parent, bg=BG)
        outer.pack(fill="x", padx=16, pady=(12, 4))

        # ── Left side: drop zone ──
        dz = tk.Frame(outer, bg=PANEL,
                      highlightbackground=ACCENT, highlightthickness=2,
                      pady=16)
        dz.pack(side="left", fill="both", expand=True)

        tk.Label(dz, text="🎬", font=("Segoe UI", 20), bg=PANEL, fg=ACCENT).pack()
        self._drop_lbl = tk.Label(
            dz,
            text="Drop MP4 file here" if HAS_DND else "Browse for an MP4 file",
            font=("Segoe UI", 10), bg=PANEL, fg=TEXT
        )
        self._drop_lbl.pack(pady=(4, 2))

        self._file_lbl = tk.Label(dz, textvariable=self.mp4_path,
                                  font=("Segoe UI", 8), bg=PANEL, fg=DIM,
                                  wraplength=400)
        self._file_lbl.pack()

        ctk.CTkButton(dz, text="Browse…", font=("Segoe UI", 9),
                      fg_color=BORDER, text_color=TEXT,
                      cursor="hand2", hover_color=ACCENT2, corner_radius=8,
                      command=self._browse_mp4).pack(pady=(8, 0))

        if HAS_DND:
            for w in (dz, self._drop_lbl, self._file_lbl):
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<Drop>>", self._on_drop)

        # ── Right side: Run / Cancel buttons stacked ──
        btn_col = tk.Frame(outer, bg=BG, padx=8)
        btn_col.pack(side="left", fill="y")

        self._run_btn = self._btn(btn_col, "▶  Run", ACCENT, "white",
                                  self._on_run, font=("Segoe UI", 11, "bold"),
                                  padx=28, pady=12)
        self._run_btn.pack(fill="x", pady=(16, 6))

        self._cancel_btn = self._btn(btn_col, "✕  Cancel", BORDER, DIM,
                                     self._on_cancel, state="disabled",
                                     padx=20, pady=12)
        self._cancel_btn.pack(fill="x")

    # ── Options grid ──────────────────────────────────────────────────────────

    def _build_options(self, parent):
        parent.columnconfigure(1, weight=1, minsize=120)
        parent.columnconfigure(3, weight=1, minsize=120)

        # Row 0
        self._lbl(parent, "Whisper Model", 0, 0, padx=(0, 12))
        cb = ctk.CTkComboBox(parent, variable=self.whisper_model,
                             values=["tiny", "base", "small", "medium", "large"],
                             state="readonly", width=100,
                             fg_color=ENTRY_BG, border_color=BORDER, button_color=ACCENT,
                             button_hover_color=ACCENT2, dropdown_fg_color=ENTRY_BG,
                             dropdown_hover_color=ACCENT, text_color=TEXT, corner_radius=6)
        cb.grid(row=0, column=1, sticky="w", pady=4)

        self._lbl(parent, "Top N Clips", 0, 2, padx=(20, 12))
        tk.Spinbox(parent, textvariable=self.top_n, from_=1, to=50, width=5,
                   bg=ENTRY_BG, fg=TEXT, insertbackground=TEXT,
                   relief="flat", buttonbackground=BORDER
                   ).grid(row=0, column=3, sticky="w", pady=4)

        # Row 1
        self._lbl(parent, "Window (min)", 1, 0, padx=(0, 12))
        tk.Spinbox(parent, textvariable=self.window_minutes, from_=1, to=30, width=5,
                   bg=ENTRY_BG, fg=TEXT, insertbackground=TEXT,
                   relief="flat", buttonbackground=BORDER
                   ).grid(row=1, column=1, sticky="w", pady=4)

        self._lbl(parent, "Audio Track", 1, 2, padx=(20, 12))
        af = tk.Frame(parent, bg=CARD)
        af.grid(row=1, column=3, sticky="w", pady=4)
        ctk.CTkEntry(af, textvariable=self.audio_track, width=40,
                     fg_color=ENTRY_BG, text_color=TEXT,
                     corner_radius=6, border_color=BORDER
                     ).pack(side="left")
        tk.Label(af, text="  (0-based; blank = default)",
                 font=("Segoe UI", 8), bg=CARD, fg=DIM).pack(side="left")

        # Row 2
        self._lbl(parent, "Padding (min)", 2, 0, padx=(0, 12))
        pf = tk.Frame(parent, bg=CARD)
        pf.grid(row=2, column=1, sticky="w", pady=4)
        tk.Spinbox(pf, textvariable=self.padding_minutes,
                   from_=0, to=10, increment=0.5, width=5, format="%.1f",
                   bg=ENTRY_BG, fg=TEXT, insertbackground=TEXT,
                   relief="flat", buttonbackground=BORDER
                   ).pack(side="left")
        tk.Label(pf, text="  added before & after each core clip",
                 font=("Segoe UI", 8), bg=CARD, fg=DIM).pack(side="left")

    # ── File paths grid ───────────────────────────────────────────────────────

    def _build_paths(self, parent):
        parent.columnconfigure(1, weight=1)

        # Row 0: Load Transcript JSON
        self._lbl(parent, "Load Transcript JSON", 0, 0, padx=(0, 10))
        ef = tk.Frame(parent, bg=CARD)
        ef.grid(row=0, column=1, sticky="ew", pady=3)
        ef.columnconfigure(0, weight=1)
        ctk.CTkEntry(ef, textvariable=self.load_transcript, font=("Segoe UI", 9),
                     fg_color=ENTRY_BG, text_color=TEXT,
                     corner_radius=6, border_color=BORDER
                     ).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ctk.CTkButton(ef, text="Browse", font=("Segoe UI", 10),
                      fg_color=BORDER, text_color=TEXT,
                      cursor="hand2", hover_color=ACCENT2, corner_radius=8,
                      command=lambda: self._browse_path(self.load_transcript, "json_open")
                      ).grid(row=0, column=1)
        tk.Label(parent, text="Skip transcription — analyse an existing transcript",
                 font=("Segoe UI", 8), bg=CARD, fg=DIM, anchor="w"
                 ).grid(row=0, column=2, sticky="w", padx=(12, 0))

    # ── Run-mode radios ───────────────────────────────────────────────────────

    def _build_run_mode(self, parent):
        modes = [
            ("full",       "Full Pipeline",
             "Extract audio → Transcribe with Whisper → Analyze with Claude"),
            ("transcribe", "Extract + Transcribe Only",
             "Extract audio and run Whisper (no Claude call; save transcript for later)"),
            ("analyze",    "Analyze Transcript Only",
             "Load an existing transcript JSON and run Claude analysis"),
        ]
        for val, label, desc in modes:
            row = tk.Frame(parent, bg=CARD, pady=3)
            row.pack(fill="x")
            ctk.CTkRadioButton(
                row, variable=self.run_mode, value=val,
                text=label, font=("Segoe UI", 10, "bold"),
                fg_color=ACCENT, hover_color=ACCENT2, text_color=TEXT
            ).pack(side="left")
            tk.Label(row, text=f"  —  {desc}",
                     font=("Segoe UI", 9), bg=CARD, fg=DIM).pack(side="left")

    # ── Script loader ─────────────────────────────────────────────────────────

    def _build_script_loader(self, parent):
        # Row 1: Load existing clips script
        tk.Label(parent, text="Script file", font=("Segoe UI", 9),
                 bg=CARD, fg=DIM).grid(row=1, column=0, sticky="w",
                                       padx=(0, 10), pady=4)

        self._script_path_var = tk.StringVar()
        ef = tk.Frame(parent, bg=CARD)
        ef.grid(row=1, column=1, sticky="ew", pady=4)
        ef.columnconfigure(0, weight=1)

        ctk.CTkEntry(ef, textvariable=self._script_path_var, font=("Segoe UI", 9),
                     fg_color=ENTRY_BG, text_color=TEXT,
                     corner_radius=6, border_color=BORDER
                     ).grid(row=0, column=0, sticky="ew", padx=(0, 6))

        ctk.CTkButton(ef, text="Browse", font=("Segoe UI", 10),
                      fg_color=BORDER, text_color=TEXT, cursor="hand2",
                      hover_color=ACCENT2, corner_radius=8,
                      command=self._browse_script).grid(row=0, column=1)

        self._btn(parent, "Load Clips", ACCENT, "white",
                  self._load_clips_script, padx=14, pady=5
                  ).grid(row=1, column=2, padx=(8, 0), pady=4)

        tk.Label(parent,
                 text="Parses an existing extract_clips.sh and opens the selection panel",
                 font=("Segoe UI", 8), bg=CARD, fg=DIM
                 ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(0, 2))

    def _browse_script(self):
        p = filedialog.askopenfilename(
            title="Select clips script",
            filetypes=[("Shell scripts", "*.sh"), ("All files", "*.*")],
        )
        if p:
            self._script_path_var.set(p)

    def _load_clips_script(self):
        path = self._script_path_var.get().strip()
        if not path:
            messagebox.showerror("No file", "Please select a clips script file first.")
            return
        if not Path(path).exists():
            messagebox.showerror("Not found", f"File not found:\n{path}")
            return

        try:
            mp4_source, clips = parse_clips_script(path)
        except Exception as e:
            messagebox.showerror("Parse error", f"Could not parse script:\n{e}")
            return

        if not clips:
            messagebox.showwarning("No clips found",
                                   "No ffmpeg clip commands were found in that file.")
            return

        # Pre-fill MP4 path and output dir if not already set
        if mp4_source and not self.mp4_path.get().strip():
            self.mp4_path.set(mp4_source)

        script_dir = str(Path(path).parent)
        if not self.export_dir.get().strip():
            self.export_dir.set(script_dir)

        self._append(
            f"\nLoaded {len(clips)} clip(s) from {Path(path).name}"
            + (f"\n  Source: {mp4_source}" if mp4_source else "") + "\n",
            "ok"
        )
        self._populate_clips_panel(clips)

    # ─────────────────────────────────────────────────────────────────────────
    # Browse helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _browse_mp4(self):
        p = filedialog.askopenfilename(
            title="Select video file",
            filetypes=[("Video files", "*.mp4 *.mkv *.mov"),
                       ("MP4 files", "*.mp4"), ("All files", "*.*")]
        )
        if p:
            self.mp4_path.set(p)

    def _browse_path(self, var: tk.StringVar, ftype: str):
        match ftype:
            case "dir":
                p = filedialog.askdirectory(title="Select directory")
            case "json_open":
                p = filedialog.askopenfilename(
                    title="Select JSON file",
                    filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
                )
            case "json_save":
                p = filedialog.asksaveasfilename(
                    title="Save JSON file",
                    defaultextension=".json",
                    filetypes=[("JSON files", "*.json")]
                )
            case "wav_save":
                p = filedialog.asksaveasfilename(
                    title="Save WAV file",
                    defaultextension=".wav",
                    filetypes=[("WAV files", "*.wav")]
                )
            case _:
                p = filedialog.askopenfilename(title="Select file")
        if p:
            var.set(p)

    def _on_drop(self, event):
        raw = event.data.strip()
        # tkinterdnd2 wraps paths containing spaces in {}
        if raw.startswith("{") and raw.endswith("}"):
            raw = raw[1:-1]
        if raw.lower().endswith((".mp4", ".mkv", ".mov")):
            self.mp4_path.set(raw)
            self._append(f"File loaded: {raw}\n", "ok")
        else:
            messagebox.showwarning("Unsupported file",
                                   "Please drop an MP4, MKV, or MOV file.")

    # ─────────────────────────────────────────────────────────────────────────
    # Run logic
    # ─────────────────────────────────────────────────────────────────────────

    def _validate(self) -> bool:
        mode = self.run_mode.get()

        if mode in ("full", "transcribe"):
            mp4 = self.mp4_path.get().strip()
            if not mp4:
                messagebox.showerror("Missing input", "Please select an MP4 file.")
                return False
            if not Path(mp4).exists():
                messagebox.showerror("File not found", f"File not found:\n{mp4}")
                return False

        if mode == "analyze":
            t = self.load_transcript.get().strip()
            if not t:
                messagebox.showerror("Missing transcript",
                                     "Please specify a transcript JSON to analyse.")
                return False
            if not Path(t).exists():
                messagebox.showerror("File not found", f"Transcript not found:\n{t}")
                return False

        if mode in ("full", "analyze"):
            from providers import PROVIDERS
            provider = self._prof_provider.get().strip() or "anthropic"
            if provider != "ollama":
                prov_info = PROVIDERS.get(provider, PROVIDERS["anthropic"])
                api_key = self._prof_api_key.get().strip() or \
                          os.environ.get(prov_info["env_key"], "")
                if not api_key:
                    messagebox.showerror("Missing API key",
                                         f"{prov_info['env_key']} is not set and no "
                                         f"profile API key found.\n\n"
                                         f"Set it in the Settings tab or as an "
                                         f"environment variable.")
                    return False

        return True

    def _on_run(self):
        if not self._validate():
            return
        self._cancel.clear()
        self._run_btn.configure(state="disabled")
        self._cancel_btn.configure(state="normal")
        self._clear_log()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def _on_cancel(self):
        self._cancel.set()
        self._append("Cancelling…\n", "warn")
        self._cancel_btn.configure(state="disabled")

    # ── Worker (background thread) ────────────────────────────────────────────

    def _worker(self):
        orig_console = cf.console
        cf.console = GuiConsole(self._q)
        try:
            mode = self.run_mode.get()
            if mode == "full":
                self._run_full()
            elif mode == "transcribe":
                self._run_transcribe()
            elif mode == "analyze":
                self._run_analyze()
        except SystemExit:
            pass
        except Exception as exc:
            self._q.put(("err", f"Unexpected error: {exc}"))
        finally:
            cf.console = orig_console
            self._q.put(("done", None))

    # ── Run modes ─────────────────────────────────────────────────────────────

    def _run_full(self):
        self._q.put(("head", "=== Full Pipeline ===\n"))
        segments = self._do_transcription()
        if segments is None:
            return

        save_t = self.save_transcript.get().strip()
        if save_t:
            cf.save_transcript(segments, save_t)

        if not segments:
            self._q.put(("err", "No transcript segments found.\n"))
            return

        client = self._make_client()
        if client is None:
            return

        chunks = cf.chunk_transcript(segments, window_minutes=self.window_minutes.get())
        clips = self._do_analysis(chunks, client)
        if clips is None:
            return

        self._save_outputs(clips)
        self._q.put(("results", clips))

    def _run_transcribe(self):
        self._q.put(("head", "=== Extract + Transcribe Only ===\n"))
        segments = self._do_transcription()
        if segments is None:
            return

        save_t = self.save_transcript.get().strip()
        if save_t:
            cf.save_transcript(segments, save_t)
            self._q.put(("ok", f"Transcript saved → {save_t}\n"))
        else:
            self._q.put(("warn",
                "No 'Save Transcript JSON' path set — transcript will not be kept.\n"))

        self._q.put(("ok", f"Done. {len(segments)} segments transcribed.\n"))

    def _run_analyze(self):
        self._q.put(("head", "=== Analyze Transcript Only ===\n"))
        t_path = self.load_transcript.get().strip()
        self._q.put(("log", f"Loading transcript: {t_path}\n"))
        try:
            segments = cf.load_transcript_from_json(t_path)
        except Exception as e:
            self._q.put(("err", f"Failed to load transcript: {e}\n"))
            return
        self._q.put(("log", f"Loaded {len(segments)} segments.\n"))

        client = self._make_client()
        if client is None:
            return

        chunks = cf.chunk_transcript(segments, window_minutes=self.window_minutes.get())
        clips = self._do_analysis(chunks, client)
        if clips is None:
            return

        mp4 = self.mp4_path.get().strip()
        self._save_outputs(clips, mp4_override=mp4)
        self._q.put(("results", clips))

    # ── Shared sub-steps ──────────────────────────────────────────────────────

    def _do_transcription(self):
        """Extract audio then transcribe. Returns segment list or None on error."""
        mp4 = self.mp4_path.get().strip()
        track_str = self.audio_track.get().strip()
        audio_track = int(track_str) if track_str else None
        save_wav = self.save_wav.get().strip()

        def _progress(pct: int, label: str):
            self._q.put(("whisper_progress", (pct, label)))

        def _audio_progress(pct: int):
            self._q.put(("audio_progress", pct))

        self._q.put(("audio_start", None))

        if save_wav:
            wav_path = save_wav
            try:
                cf.extract_audio(mp4, wav_path, audio_track=audio_track,
                                 progress_cb=_audio_progress)
            except SystemExit:
                self._q.put(("audio_done", None))
                self._q.put(("whisper_done", None))
                return None
            self._q.put(("audio_done", None))
            self._q.put(("whisper_start", None))
            return cf.transcribe_audio(wav_path, model_size=self.whisper_model.get(),
                                       language=self._whisper_lang_code(),
                                       progress_cb=_progress)
        else:
            tmpdir = tempfile.mkdtemp()
            wav_path = os.path.join(tmpdir, "audio.wav")
            try:
                cf.extract_audio(mp4, wav_path, audio_track=audio_track,
                                 progress_cb=_audio_progress)
            except SystemExit:
                self._q.put(("audio_done", None))
                self._q.put(("whisper_done", None))
                return None
            self._q.put(("audio_done", None))
            self._q.put(("whisper_start", None))
            segments = cf.transcribe_audio(wav_path, model_size=self.whisper_model.get(),
                                           language=self._whisper_lang_code(),
                                           progress_cb=_progress)
            try:
                os.remove(wav_path)
                os.rmdir(tmpdir)
            except OSError:
                pass
            return segments

    def _make_client(self):
        """Create an LLMClient from the active profile (or env vars)."""
        from providers import PROVIDERS, make_client
        provider = self._prof_provider.get().strip() or "anthropic"
        prov_info = PROVIDERS.get(provider, PROVIDERS["anthropic"])
        if provider == "ollama":
            api_key = "ollama"
            base_url = self._prof_base_url.get().strip() or \
                       prov_info.get("base_url", "http://localhost:11434")
        else:
            api_key = self._prof_api_key.get().strip() or \
                      os.environ.get(prov_info["env_key"], "")
            base_url = ""
            if not api_key:
                self._q.put(("err",
                             f"{prov_info['env_key']} not set and no profile API key found.\n"))
                return None
        try:
            return make_client(provider, api_key, base_url=base_url)
        except Exception as exc:
            self._q.put(("err", f"Could not create {prov_info['label']} client: {exc}\n"))
            return None

    def _do_analysis(self, chunks: list, client) -> list | None:
        """Call the LLM on each chunk; return deduplicated ClipSuggestion list."""
        from providers import PROVIDERS
        provider = self._prof_provider.get().strip() or "anthropic"
        prov_info = PROVIDERS.get(provider, PROVIDERS["anthropic"])
        model = self._prof_model.get().strip() or prov_info["default_model"]

        total = len(chunks)
        padding_sec = self.padding_minutes.get() * 60
        total_duration = max((c["window_end"] for c in chunks), default=0)
        self._q.put(("log", f"Analysing {total} windows with "
                             f"{prov_info['label']} ({model})…\n"))
        self._q.put(("analysis_start", total))
        if padding_sec > 0:
            self._q.put(("log", f"  Padding: ±{self.padding_minutes.get():.1f} min "
                                 f"around each core clip\n"))

        from clip_finder import ClipSuggestion

        candidates = []
        for i, chunk in enumerate(chunks):
            if self._cancel.is_set():
                self._q.put(("warn", "Cancelled by user.\n"))
                self._q.put(("analysis_done", None))
                return None

            self._q.put(("log", f"  Window {i+1}/{total} "
                         f"({cf.fmt_time(chunk['window_start'])} → "
                         f"{cf.fmt_time(chunk['window_end'])})\n"))

            result = cf.analyze_chunk(chunk, client, model=model)
            self._q.put(("analysis_progress", (i + 1, total)))
            if not result or not result.get("has_clip"):
                continue

            # Core clip as identified by Claude
            core_start = chunk["window_start"] + result.get("clip_start_offset", 0)
            core_end   = chunk["window_start"] + result.get("clip_end_offset", 60)
            core_start = max(core_start, chunk["window_start"])
            core_end   = min(core_end,   chunk["window_end"])

            if core_end - core_start < 30:
                continue

            # Expand with padding
            clip_start = max(0.0, core_start - padding_sec)
            clip_end   = core_end + padding_sec
            if total_duration > 0:
                clip_end = min(clip_end, total_duration)
            duration = clip_end - clip_start

            candidates.append({
                "chunk": chunk, "result": result,
                "clip_start": clip_start, "clip_end": clip_end,
                "duration": duration, "score": result.get("virality_score", 0)
            })

        self._q.put(("analysis_done", None))

        # Log token usage for the analysis phase
        if client.total_tokens > 0:
            self._q.put(("log",
                f"  Token usage — input: {client.input_tokens:,}  "
                f"output: {client.output_tokens:,}  "
                f"total: {client.total_tokens:,}\n"))

        candidates.sort(key=lambda x: x["score"], reverse=True)
        top_n = self.top_n.get()
        selected, used, rank = [], [], 0

        for c in candidates:
            cs, ce = c["clip_start"], c["clip_end"]
            if any(not (ce <= s or cs >= e) for s, e in used):
                continue
            used.append((cs, ce))
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

        if not selected:
            self._q.put(("warn", "No compelling clip suggestions found.\n"))

        return selected

    def _save_outputs(self, clips: list, mp4_override: str = ""):
        mp4 = mp4_override or self.mp4_path.get().strip()

        out_json = self.output_json.get().strip()
        if out_json:
            cf.save_results(clips, out_json)
            self._q.put(("ok", f"Results JSON → {out_json}\n"))

        export = self.export_dir.get().strip()
        if export:
            if mp4:
                script = cf.export_ffmpeg_commands(clips, mp4, export)
                self._q.put(("ok", f"Clip script → {script}\n"))
            else:
                self._q.put(("warn",
                    "No MP4 path set — skipping ffmpeg script "
                    "(source path needed).\n"))

    # ─────────────────────────────────────────────────────────────────────────
    # Log area helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _poll(self):
        # Process at most 10 items per cycle so the UI can repaint between batches.
        # Using a tight interval keeps the progress bar smooth even when the window
        # loses and regains focus (Windows can throttle after() during that transition).
        try:
            for _ in range(10):
                kind, data = self._q.get_nowait()
                self._handle(kind, data)
        except queue.Empty:
            pass
        self.root.after(33, self._poll)  # ~30 fps

    def _handle(self, kind: str, data):
        t = self._log_text
        t.config(state="normal")

        if kind == "log":
            t.insert("end", data)
        elif kind == "ok":
            t.insert("end", data, "ok")
        elif kind == "err":
            t.insert("end", data, "err")
        elif kind == "warn":
            t.insert("end", data, "warn")
        elif kind == "head":
            t.insert("end", data, "head")
        elif kind == "results":
            self._render_results(t, data)
            self.root.after(0, lambda: self._populate_clips_panel(data))
        elif kind == "audio_start":
            self._audio_bar.set(0)
            self._audio_pct_lbl.config(text="0%")
            self._audio_bar_frame.pack(fill="x", before=self._log_text.master)
        elif kind == "audio_progress":
            pct = data
            self._audio_bar.set(pct / 100)
            self._audio_pct_lbl.config(text=f"{pct}%")
            self._audio_bar.update_idletasks()
        elif kind == "audio_done":
            self._audio_bar.set(1)
            self._audio_pct_lbl.config(text="100%")
            self.root.after(1500, self._hide_audio_bar)
        elif kind == "whisper_start":
            self._whisper_bar.set(0)
            self._whisper_pct_lbl.config(text="0%")
            self._whisper_ts_lbl.config(text="")
            self._whisper_bar_frame.pack(fill="x", before=self._log_text.master)
        elif kind == "whisper_progress":
            pct, label = data
            self._whisper_bar.set(pct / 100)
            self._whisper_pct_lbl.config(text=f"{pct}%")
            if label == "done":
                self._whisper_ts_lbl.config(text="complete")
                self.root.after(1500, self._hide_whisper_bar)
            else:
                self._whisper_ts_lbl.config(text=f"at {label}")
            self._whisper_bar.update_idletasks()  # flush pending redraws immediately
        elif kind == "whisper_done":
            self._whisper_bar.set(1)
            self._whisper_pct_lbl.config(text="100%")
            self._whisper_ts_lbl.config(text="complete")
            self.root.after(1500, self._hide_whisper_bar)
        elif kind == "premiere_clipboard":
            self.root.clipboard_clear()
            self.root.clipboard_append(data)
            self.root.update()
            t.insert("end",
                     "🎬 Premiere setup prompt copied to clipboard — "
                     "paste into Claude Code or Claude Desktop to execute.\n", "ok")
        elif kind == "analysis_start":
            total = data
            self._analysis_bar.set(0)
            self._analysis_pct_lbl.config(text="0%")
            self._analysis_count_lbl.config(text=f"0 / {total}")
            self._analysis_bar_frame.pack(fill="x", before=self._log_text.master)
        elif kind == "analysis_progress":
            done, total = data
            pct = int(done / total * 100)
            self._analysis_bar.set(pct / 100)
            self._analysis_pct_lbl.config(text=f"{pct}%")
            self._analysis_count_lbl.config(text=f"{done} / {total}")
            self._analysis_bar.update_idletasks()
        elif kind == "analysis_done":
            self._analysis_bar.set(1)
            self._analysis_pct_lbl.config(text="100%")
            self._analysis_count_lbl.config(text="complete")
            self.root.after(1500, self._hide_analysis_bar)
        elif kind == "extract_start":
            total = data
            self._extract_bar.set(0)
            self._extract_pct_lbl.config(text="0%")
            self._extract_count_lbl.config(text=f"0 / {total}")
            self._extract_bar_frame.pack(fill="x", before=self._log_text.master)
        elif kind == "extract_progress":
            done, total, row_idx = data
            pct = int(done / total * 100)
            self._extract_bar.set(pct / 100)
            self._extract_pct_lbl.config(text=f"{pct}%")
            self._extract_count_lbl.config(text=f"{done} / {total}")
            self._extract_bar.update_idletasks()
            # Remove the completed clip row from the list
            if hasattr(self, "_clip_rows") and 0 <= row_idx < len(self._clip_rows):
                self._clip_rows[row_idx].destroy()
                self._update_clip_count()
        elif kind == "extract_done":
            t.insert("end", "─── Extraction complete ───\n", "ok")
            self._extract_btn.configure(state="normal")
            self._extract_bar.set(1)
            self._extract_pct_lbl.config(text="100%")
            self.root.after(1500, self._hide_extract_bar)
            if data:  # list of extracted clip folder paths
                self._populate_editing_clip_sections(data)
        elif kind == "slice_start":
            total = data
            self._slice_bar.set(0)
            self._slice_pct_lbl.config(text="0%")
            self._slice_count_lbl.config(text=f"0 / {total}")
            self._slice_bar_frame.pack(fill="x", before=self._log_text.master)
        elif kind == "slice_progress":
            done, total = data
            pct = int(done / total * 100)
            self._slice_bar.set(done / total)
            self._slice_pct_lbl.config(text=f"{pct}%")
            self._slice_count_lbl.config(text=f"{done} / {total}")
        elif kind == "slice_complete":
            self._slice_bar.set(1)
            self._slice_pct_lbl.config(text="100%")
            self._slice_count_lbl.config(text="complete")
            self.root.after(1500, self._hide_slice_bar)
        elif kind == "image_start":
            total = data
            self._image_bar.set(0)
            self._image_pct_lbl.config(text="0%")
            self._image_count_lbl.config(text=f"0 / {total}")
            self._image_bar_frame.pack(fill="x", before=self._log_text.master)
        elif kind == "image_progress":
            done, total = data
            pct = int(done / total * 100)
            self._image_bar.set(done / total)
            self._image_pct_lbl.config(text=f"{pct}%")
            self._image_count_lbl.config(text=f"{done} / {total}")
        elif kind == "image_complete":
            self._image_bar.set(1)
            self._image_pct_lbl.config(text="100%")
            self._image_count_lbl.config(text="complete")
            self.root.after(1500, self._hide_image_bar)
        elif kind == "slice_done":
            section_id = data
            sec = self._find_section(section_id) if section_id is not None else None
            if sec:
                sec["slice_btn"].configure(state="normal")
                sec["slice_only_btn"].configure(state="normal")
                sec["premiere_btn"].configure(state="normal")
                # Auto-remove dynamic sections after slicing
                if self._auto_remove_var.get() and not sec["is_permanent"]:
                    self.root.after(500, lambda sid=section_id: self._remove_clip_section(sid))
            else:
                # Fallback: re-enable permanent section buttons
                self._slice_btn.configure(state="normal")
                self._slice_only_btn.configure(state="normal")
                self._premiere_btn.configure(state="normal")
        elif kind == "done":
            t.insert("end", "\n─── Finished ───\n", "dim")
            self._run_btn.configure(state="normal")
            self._cancel_btn.configure(state="disabled")
            self.root.after(1500, self._hide_whisper_bar)

        t.config(state="disabled")
        t.see("end")

    def _render_results(self, t: tk.Text, clips: list):
        t.insert("end", f"\n{'─'*52}\n", "dim")
        t.insert("end", f"  {len(clips)} clip suggestion(s) found\n", "head")
        t.insert("end", f"{'─'*52}\n\n", "dim")
        for clip in clips:
            bar = "█" * clip.virality_score + "░" * (10 - clip.virality_score)
            t.insert("end",
                f"#{clip.rank}  {clip.title}\n", "head")
            t.insert("end",
                f"     Virality  {bar}  {clip.virality_score}/10"
                f"   {clip.content_type.upper()}\n")
            t.insert("end",
                f"     Clip      {cf.fmt_time(clip.clip_start)} → "
                f"{cf.fmt_time(clip.clip_end)}"
                f"  ({clip.clip_duration:.0f}s)\n")
            t.insert("end",
                f"     Hook      {clip.hook}\n")
            t.insert("end",
                f"     \"…{clip.transcript_excerpt}…\"\n\n", "dim")

    def _on_extract_clips(self):
        selected_with_idx = [(i, clip, var) for i, (clip, var) in
                             enumerate(zip(self._last_clips, self._clip_vars)) if var.get()]
        if not selected_with_idx:
            messagebox.showwarning("Nothing selected", "Select at least one clip to extract.")
            return

        mp4 = self.mp4_path.get().strip()
        if not mp4:
            messagebox.showerror("No source file", "No MP4 file is set.")
            return

        out_dir = self.export_dir.get().strip()
        if not out_dir:
            messagebox.showerror("No output directory", "Set an output directory first.")
            return

        # Load the full transcript so we can slice per-clip transcripts
        segments: list = []
        transcript_path = self.save_transcript.get().strip()
        if transcript_path and Path(transcript_path).exists():
            try:
                segments = cf.load_transcript_from_json(transcript_path)
            except Exception as exc:
                self._q.put(("warn", f"Could not load transcript for slicing: {exc}\n"))

        self._extract_btn.configure(state="disabled")
        threading.Thread(
            target=self._extract_worker,
            args=(selected_with_idx, mp4, out_dir, segments),
            daemon=True
        ).start()

    def _extract_worker(self, selected_with_idx: list, mp4: str, out_dir: str,
                        segments: list | None = None):
        os.makedirs(out_dir, exist_ok=True)
        total = len(selected_with_idx)
        extracted_dirs: list[str] = []
        self._q.put(("extract_start", total))
        self._q.put(("head", f"\n=== Extracting {total} clip(s) ===\n"))

        for i, (row_idx, clip, _) in enumerate(selected_with_idx, 1):
            if self._cancel.is_set():
                self._q.put(("warn", "Extraction cancelled.\n"))
                break

            # ── Per-clip folder ──────────────────────────────────────────────
            safe = "".join(c if c.isalnum() or c in "-_ " else ""
                           for c in clip.title).replace(" ", "_")[:50]
            clip_name = f"clip_{clip.rank:02d}_{safe}"
            clip_dir  = Path(out_dir) / clip_name
            clip_dir.mkdir(parents=True, exist_ok=True)

            out_file = clip_dir / f"{clip_name}.mp4"
            duration = clip.clip_end - clip.clip_start

            self._q.put(("log", f"[{i}/{total}] #{clip.rank} {clip.title}  "
                                 f"({cf.fmt_time(clip.clip_start)} → "
                                 f"{cf.fmt_time(clip.clip_end)})\n"))

            # ── Extract video ────────────────────────────────────────────────
            cmd = [
                "ffmpeg", "-y",
                "-ss", f"{clip.clip_start:.2f}",
                "-i", mp4,
                "-t", f"{duration:.2f}",
                "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k",
                str(out_file)
            ]
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace")
            if result.returncode == 0:
                self._q.put(("ok", f"    ✓ {out_file.name}\n"))
                extracted_dirs.append(str(clip_dir))
            else:
                self._q.put(("err", f"    ✗ ffmpeg error:\n{result.stderr[-400:]}\n"))
                continue   # don't write prompt/transcript for failed clip

            self._q.put(("extract_progress", (i, total, row_idx)))

            # ── Clip transcript ──────────────────────────────────────────────
            clip_segs: list = []
            if segments:
                transcript_out = clip_dir / f"{clip_name}_transcript.json"
                try:
                    clip_segs = cf.save_clip_transcript(
                        segments, clip.clip_start, clip.clip_end,
                        str(transcript_out)
                    )
                    self._q.put(("log", f"    📄 transcript  → {transcript_out.name}"
                                        f"  ({len(clip_segs)} segments)\n"))
                except Exception as exc:
                    self._q.put(("warn", f"    Could not save clip transcript: {exc}\n"))

            # ── Editing prompt ───────────────────────────────────────────────
            prompt_out = clip_dir / f"{clip_name}_editing_prompt.txt"
            try:
                cf.save_editing_prompt(clip, clip_segs, str(prompt_out))
                self._q.put(("log", f"    📝 editing prompt → {prompt_out.name}\n"))
            except Exception as exc:
                self._q.put(("warn", f"    Could not save editing prompt: {exc}\n"))

        self._q.put(("extract_done", extracted_dirs))

    def _hide_whisper_bar(self):
        self._whisper_bar_frame.pack_forget()

    def _hide_audio_bar(self):
        self._audio_bar_frame.pack_forget()

    def _hide_analysis_bar(self):
        self._analysis_bar_frame.pack_forget()

    def _hide_extract_bar(self):
        self._extract_bar_frame.pack_forget()

    def _hide_slice_bar(self):
        self._slice_bar_frame.pack_forget()

    def _hide_image_bar(self):
        self._image_bar_frame.pack_forget()

    def _append(self, text: str, tag: str = ""):
        t = self._log_text
        t.config(state="normal")
        t.insert("end", text, tag)
        t.config(state="disabled")
        t.see("end")

    def _clear_log(self):
        self._log_text.config(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.config(state="disabled")

    # ─────────────────────────────────────────────────────────────────────────

    def _set_initial_sash(self):
        """Place the sash at ~60% of the window height after layout is complete."""
        total = self._paned.winfo_height()
        if total > 1:
            self._paned.sash_place(0, 0, int(total * 0.60))

    def _on_close(self):
        """Ensure the process fully terminates when the window is closed."""
        self._cancel.set()                    # signal any running worker to stop
        try:
            self.root.destroy()
        except Exception:
            pass
        os._exit(0)                           # force-kill lingering threads/subprocesses

    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(50, self._set_initial_sash)
        self.root.mainloop()


# ── License activation dialog ────────────────────────────────────────────────

class LicenseDialog:
    """Modal dialog that gates access until a valid Gumroad license is entered."""

    def __init__(self):
        from licensing import verify_license, save_license, load_saved_license

        self._verified = False
        self._verify = verify_license
        self._save = save_license

        # Check for existing saved license first
        saved_key = load_saved_license()
        if saved_key:
            result = verify_license(saved_key, increment_uses=False)
            if result.valid:
                self._verified = True
                return

        # No valid saved license — show activation window
        self._root = tk.Tk()
        self._root.title("Trik_Klip — Activate License")
        self._root.geometry("480x300")
        self._root.resizable(False, False)
        self._root.configure(bg=BG)
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Center on screen
        self._root.update_idletasks()
        x = (self._root.winfo_screenwidth() - 480) // 2
        y = (self._root.winfo_screenheight() - 300) // 2
        self._root.geometry(f"480x300+{x}+{y}")

        frame = tk.Frame(self._root, bg=BG)
        frame.pack(expand=True, fill="both", padx=30, pady=20)

        tk.Label(
            frame, text="Trik_Klip", font=("Segoe UI", 22, "bold"),
            bg=BG, fg=ACCENT,
        ).pack(pady=(10, 5))

        tk.Label(
            frame, text="Enter your Gumroad license key to activate",
            font=("Segoe UI", 11), bg=BG, fg=DIM,
        ).pack(pady=(0, 15))

        self._key_var = tk.StringVar()
        self._entry = tk.Entry(
            frame, textvariable=self._key_var, font=("Segoe UI", 12),
            bg=ENTRY_BG, fg=TEXT, insertbackground=TEXT,
            relief="flat", width=40,
        )
        self._entry.pack(ipady=6, pady=(0, 10))
        self._entry.focus_set()
        self._entry.bind("<Return>", lambda _: self._activate())

        self._status_label = tk.Label(
            frame, text="", font=("Segoe UI", 10), bg=BG, fg=ERR,
        )
        self._status_label.pack(pady=(0, 10))

        self._btn = tk.Button(
            frame, text="Activate", font=("Segoe UI", 11, "bold"),
            bg=ACCENT, fg="white", activebackground=ACCENT2,
            activeforeground="white", relief="flat", cursor="hand2",
            command=self._activate, width=20,
        )
        self._btn.pack(ipady=4)

        self._root.mainloop()

    def _activate(self):
        key = self._key_var.get().strip()
        if not key:
            self._status_label.config(text="Please enter a license key.", fg=WARN)
            return

        self._btn.config(state="disabled", text="Verifying...")
        self._status_label.config(text="", fg=DIM)
        self._root.update()

        result = self._verify(key, increment_uses=True)

        if result.valid:
            self._save(key)
            self._verified = True
            self._status_label.config(text="License activated!", fg=SUCCESS)
            self._root.after(600, self._root.destroy)
        else:
            self._btn.config(state="normal", text="Activate")
            self._status_label.config(text=result.message, fg=ERR)

    def _on_close(self):
        self._root.destroy()

    @property
    def is_verified(self) -> bool:
        return self._verified


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    gate = LicenseDialog()
    if gate.is_verified:
        app = StreamClipperGUI()
        app.run()
