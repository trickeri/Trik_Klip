"""Tests for gui.py — helper functions, parsers, and Premiere prompt generation.

These tests cover the non-GUI logic without instantiating any tkinter windows.
"""

import json
import os
import re
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import clip_finder as cf


# ════════════════════════════════════════════════════════════════════════════
# Import gui module carefully (skip tkinter init)
# ════════════════════════════════════════════════════════════════════════════

# We can import the module-level functions and the class definition
# without actually creating GUI widgets.
import gui


# ════════════════════════════════════════════════════════════════════════════
# GuiConsole
# ════════════════════════════════════════════════════════════════════════════

class TestGuiConsole:
    def test_log_strips_rich_tags(self):
        import queue
        q = queue.Queue()
        gc = gui.GuiConsole(q)
        gc.log("[cyan]Hello[/cyan] [bold]world[/bold]")
        kind, msg = q.get_nowait()
        assert kind == "log"
        assert msg == "Hello world"

    def test_print_strips_tags(self):
        import queue
        q = queue.Queue()
        gc = gui.GuiConsole(q)
        gc.print("[red]Error:[/red] something")
        kind, msg = q.get_nowait()
        assert "Error: something" in msg

    def test_nested_tags(self):
        import queue
        q = queue.Queue()
        gc = gui.GuiConsole(q)
        gc.log("[bold][cyan]Nested[/cyan][/bold]")
        _, msg = q.get_nowait()
        assert msg == "Nested"


# ════════════════════════════════════════════════════════════════════════════
# parse_clips_script
# ════════════════════════════════════════════════════════════════════════════

class TestParseClipsScript:
    SAMPLE_SCRIPT = """#!/bin/bash
# Auto-generated clip extraction script
# Source: /videos/stream.mp4

# Clip 1: Great Story (00:01:00 → 00:03:00)
ffmpeg -ss 60.00 -i "/videos/stream.mp4" -t 120.00 -c:v copy -c:a aac -b:a 192k "clips/clip_01_Great_Story.mp4"

# Clip 2: Hot Take (00:10:00 → 00:12:30)
ffmpeg -ss 600.00 -i "/videos/stream.mp4" -t 150.00 -c:v copy -c:a aac -b:a 192k "clips/clip_02_Hot_Take.mp4"
"""

    def test_parses_source(self, tmp_path):
        p = tmp_path / "extract.sh"
        p.write_text(self.SAMPLE_SCRIPT, encoding="utf-8")
        source, clips = gui.parse_clips_script(str(p))
        assert source == "/videos/stream.mp4"

    def test_parses_clips(self, tmp_path):
        p = tmp_path / "extract.sh"
        p.write_text(self.SAMPLE_SCRIPT, encoding="utf-8")
        _, clips = gui.parse_clips_script(str(p))
        assert len(clips) == 2

    def test_clip_attributes(self, tmp_path):
        p = tmp_path / "extract.sh"
        p.write_text(self.SAMPLE_SCRIPT, encoding="utf-8")
        _, clips = gui.parse_clips_script(str(p))

        assert clips[0].rank == 1
        assert clips[0].title == "Great Story"
        assert clips[0].clip_start == 60.0
        assert clips[0].clip_duration == 120.0
        assert clips[0].clip_end == 180.0

        assert clips[1].rank == 2
        assert clips[1].clip_start == 600.0
        assert clips[1].clip_duration == 150.0

    def test_empty_script(self, tmp_path):
        p = tmp_path / "empty.sh"
        p.write_text("#!/bin/bash\n# nothing here\n")
        source, clips = gui.parse_clips_script(str(p))
        assert source == ""
        assert clips == []


# ════════════════════════════════════════════════════════════════════════════
# _parse_clip_range_from_prompt  (static method)
# ════════════════════════════════════════════════════════════════════════════

class TestParseClipRangeFromPrompt:
    def test_normal(self):
        prompt = "  Source range:     00:05:30 → 00:08:45\n  Other stuff"
        start, end = gui.StreamClipperGUI._parse_clip_range_from_prompt(prompt)
        assert start == 330.0  # 5*60 + 30
        assert end == 525.0    # 8*60 + 45

    def test_hours(self):
        prompt = "  Source range:     01:05:30 → 01:08:45\n"
        start, end = gui.StreamClipperGUI._parse_clip_range_from_prompt(prompt)
        assert start == 3930.0
        assert end == 4125.0

    def test_missing(self):
        prompt = "No source range here"
        start, end = gui.StreamClipperGUI._parse_clip_range_from_prompt(prompt)
        assert start == 0.0
        assert end == float("inf")

    def test_parse_start_compat(self):
        prompt = "  Source range:     00:02:00 → 00:04:00\n"
        start = gui.StreamClipperGUI._parse_clip_start_from_prompt(prompt)
        assert start == 120.0


# ════════════════════════════════════════════════════════════════════════════
# ShellClip dataclass
# ════════════════════════════════════════════════════════════════════════════

class TestShellClip:
    def test_defaults(self):
        clip = gui.ShellClip(rank=1, title="T", clip_start=0, clip_end=60,
                             clip_duration=60)
        assert clip.virality_score == 0
        assert clip.content_type == "imported"


# ════════════════════════════════════════════════════════════════════════════
# Premiere prompt template
# ════════════════════════════════════════════════════════════════════════════

class TestPremierePrompt:
    """Verify the Premiere prompt template has the right structure."""

    @property
    def prompt(self):
        return gui.StreamClipperGUI._PREMIERE_PROMPT.format(
            clip_folder="D:/test/clip_01",
            sequence_name="clip_01_Shorts",
        )

    def test_contains_all_steps(self):
        p = self.prompt
        for step in ["Step 1", "Step 2", "Step 3", "Step 4", "Step 5",
                      "Step 6", "Step 7", "Step 8", "Step 9", "Step 10",
                      "Step 11"]:
            assert step in p, f"Missing {step} in Premiere prompt"

    def test_clip_folder_injected(self):
        assert "D:/test/clip_01" in self.prompt

    def test_sequence_name_injected(self):
        assert "clip_01_Shorts" in self.prompt

    def test_two_import_calls(self):
        """Import should be split into two calls (videos then images)."""
        p = self.prompt
        assert "Call 1" in p
        assert "Call 2" in p

    def test_no_retry_on_timeout(self):
        p = self.prompt
        assert "do NOT retry" in p or "Do NOT retry" in p

    def test_visual_images_track(self):
        """Visuals should be placed on their own track before banners."""
        p = self.prompt
        assert "visual" in p.lower()
        # Step 8 should be about visuals, Step 9 about Twitch
        step8_idx = p.index("Step 8")
        step9_idx = p.index("Step 9")
        visual_idx = p.lower().index("visual images", step8_idx)
        assert step8_idx < visual_idx < step9_idx

    def test_banner_tracks_after_visuals(self):
        """Twitch and YouTube banners should be on higher track indices than visuals."""
        p = self.prompt
        # Find the track indices mentioned for each
        twitch_match = re.search(r"Twitch banner.*?video_track_index:\s*(\d+)",
                                 p, re.DOTALL)
        youtube_match = re.search(r"YouTube banner.*?video_track_index:\s*(\d+)",
                                  p, re.DOTALL)
        visual_match = re.search(r"visual images.*?video_track_index:\s*(\d+)",
                                 p, re.DOTALL | re.IGNORECASE)

        assert visual_match is not None, "Visual track index not found"
        assert twitch_match is not None, "Twitch track index not found"
        assert youtube_match is not None, "YouTube track index not found"

        v_idx = int(visual_match.group(1))
        t_idx = int(twitch_match.group(1))
        y_idx = int(youtube_match.group(1))

        assert t_idx > v_idx, f"Twitch ({t_idx}) should be above visuals ({v_idx})"
        assert y_idx > t_idx, f"YouTube ({y_idx}) should be above Twitch ({t_idx})"

    def test_two_empty_gap_tracks_in_layout(self):
        """Final layout should show 2 empty tracks."""
        p = self.prompt
        empty_count = p.count("(empty)")
        assert empty_count >= 2, f"Expected 2+ empty tracks, found {empty_count}"

    def test_offset_compensation_documented(self):
        """The known offset behavior should be documented."""
        p = self.prompt
        assert "KNOWN OFFSET" in p or "known offset" in p.lower()

    def test_create_shorts_sequence(self):
        assert "create_shorts_sequence" in self.prompt

    def test_scale_values(self):
        p = self.prompt
        assert "scale: 198" in p
        assert "scale: 234" in p

    def test_do_not_use_add_media_on_new_track(self):
        p = self.prompt
        assert "Do NOT use add_media_on_new_track" in p


# ════════════════════════════════════════════════════════════════════════════
# Rich tag stripper regex
# ════════════════════════════════════════════════════════════════════════════

class TestRichTagRegex:
    def test_strips_simple_tag(self):
        assert gui._RICH_TAG.sub("", "[cyan]Hello[/cyan]") == "Hello"

    def test_strips_nested(self):
        assert gui._RICH_TAG.sub("", "[bold][red]X[/red][/bold]") == "X"

    def test_preserves_plain_text(self):
        assert gui._RICH_TAG.sub("", "No tags here") == "No tags here"

    def test_complex_tag(self):
        assert gui._RICH_TAG.sub("", "[dim italic]text[/dim italic]") == "text"
