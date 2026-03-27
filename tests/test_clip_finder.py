"""Tests for clip_finder.py — pure functions and data models."""

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

import pytest

# Ensure the parent directory is importable
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import clip_finder as cf


# ════════════════════════════════════════════════════════════════════════════
# fmt_time / parse_time
# ════════════════════════════════════════════════════════════════════════════

class TestFmtTime:
    def test_zero(self):
        assert cf.fmt_time(0) == "00:00:00"

    def test_seconds_only(self):
        assert cf.fmt_time(45) == "00:00:45"

    def test_minutes_and_seconds(self):
        assert cf.fmt_time(125) == "00:02:05"

    def test_hours(self):
        assert cf.fmt_time(3661) == "01:01:01"

    def test_large_value(self):
        assert cf.fmt_time(7200) == "02:00:00"

    def test_fractional_seconds_truncated(self):
        # fmt_time uses int() so fractional seconds are floored
        assert cf.fmt_time(59.9) == "00:00:59"


class TestParseTime:
    def test_hms(self):
        assert cf.parse_time("01:02:03") == 3723.0

    def test_ms(self):
        assert cf.parse_time("02:30") == 150.0

    def test_seconds_only(self):
        assert cf.parse_time("45") == 45.0

    def test_fractional(self):
        assert cf.parse_time("01:30.5") == 90.5

    def test_hms_fractional(self):
        assert cf.parse_time("01:00:30.5") == 3630.5

    def test_whitespace(self):
        assert cf.parse_time("  01:00  ") == 60.0

    def test_roundtrip(self):
        """parse_time(fmt_time(x)) should return the truncated integer."""
        for secs in [0, 59, 125, 3661, 7200]:
            assert cf.parse_time(cf.fmt_time(secs)) == secs


# ════════════════════════════════════════════════════════════════════════════
# Data models
# ════════════════════════════════════════════════════════════════════════════

class TestTranscriptSegment:
    def test_creation(self):
        seg = cf.TranscriptSegment(start=0.0, end=5.0, text="Hello")
        assert seg.start == 0.0
        assert seg.end == 5.0
        assert seg.text == "Hello"

    def test_asdict(self):
        seg = cf.TranscriptSegment(start=1.0, end=2.5, text="Test")
        d = asdict(seg)
        assert d == {"start": 1.0, "end": 2.5, "text": "Test"}


class TestClipSuggestion:
    def test_creation(self):
        clip = cf.ClipSuggestion(
            rank=1, title="Test", hook="hook", segment_start=0,
            segment_end=300, clip_start=0, clip_end=120,
            clip_duration=120, content_type="story",
            virality_score=8, transcript_excerpt="exc"
        )
        assert clip.rank == 1
        assert clip.clip_duration == 120
        assert clip.virality_score == 8


# ════════════════════════════════════════════════════════════════════════════
# Transcript load / save
# ════════════════════════════════════════════════════════════════════════════

class TestTranscriptIO:
    def test_save_and_load(self, tmp_path):
        segs = [
            cf.TranscriptSegment(0.0, 5.0, "Hello"),
            cf.TranscriptSegment(5.0, 10.0, "World"),
        ]
        path = str(tmp_path / "transcript.json")
        cf.save_transcript(segs, path)

        loaded = cf.load_transcript_from_json(path)
        assert len(loaded) == 2
        assert loaded[0].text == "Hello"
        assert loaded[1].start == 5.0

    def test_load_preserves_types(self, tmp_path):
        data = [{"start": 1.5, "end": 3.7, "text": "Test"}]
        path = tmp_path / "t.json"
        path.write_text(json.dumps(data))
        segs = cf.load_transcript_from_json(str(path))
        assert isinstance(segs[0].start, float)
        assert segs[0].text == "Test"


# ════════════════════════════════════════════════════════════════════════════
# chunk_transcript
# ════════════════════════════════════════════════════════════════════════════

class TestChunkTranscript:
    def _make_segments(self, duration_sec, interval=5.0):
        """Create evenly spaced segments."""
        segs = []
        t = 0.0
        while t < duration_sec:
            segs.append(cf.TranscriptSegment(t, t + interval, f"seg at {t}"))
            t += interval
        return segs

    def test_empty(self):
        assert cf.chunk_transcript([]) == []

    def test_short_stream(self):
        """Stream shorter than one window => one chunk."""
        segs = self._make_segments(120)  # 2 minutes
        chunks = cf.chunk_transcript(segs, window_minutes=5, overlap_minutes=1)
        assert len(chunks) == 1
        assert chunks[0]["window_start"] == 0.0

    def test_multiple_windows(self):
        segs = self._make_segments(900)  # 15 minutes
        chunks = cf.chunk_transcript(segs, window_minutes=5, overlap_minutes=1)
        assert len(chunks) > 1
        # First window starts at 0
        assert chunks[0]["window_start"] == 0.0

    def test_overlap(self):
        segs = self._make_segments(900)
        chunks = cf.chunk_transcript(segs, window_minutes=5, overlap_minutes=1)
        # Windows should overlap by 1 min = 60s
        if len(chunks) >= 2:
            step = chunks[1]["window_start"] - chunks[0]["window_start"]
            assert step == (5 - 1) * 60  # 4 minutes

    def test_window_text_not_empty(self):
        segs = self._make_segments(600)
        chunks = cf.chunk_transcript(segs, window_minutes=5, overlap_minutes=1)
        for chunk in chunks:
            assert len(chunk["text"]) > 0


# ════════════════════════════════════════════════════════════════════════════
# parse_cut_list
# ════════════════════════════════════════════════════════════════════════════

class TestParseCutList:
    def test_basic(self):
        text = """CUT LIST:
1. [00:01:00] → [00:01:30] | Opening statement
2. [00:02:00] → [00:02:45] | Main point
3. [00:03:10] → [00:04:00] | Conclusion
"""
        cuts = cf.parse_cut_list(text)
        assert len(cuts) == 3
        assert cuts[0]["start"] == 60.0
        assert cuts[0]["end"] == 90.0
        assert "Opening" in cuts[0]["reason"]
        assert cuts[2]["end"] == 240.0

    def test_mm_ss_format(self):
        text = "1. 01:00 → 01:30 | something"
        cuts = cf.parse_cut_list(text)
        assert len(cuts) == 1
        assert cuts[0]["start"] == 60.0
        assert cuts[0]["end"] == 90.0

    def test_fractional_seconds(self):
        text = "1. [00:01:00.5] → [00:01:30.0] | detail"
        cuts = cf.parse_cut_list(text)
        assert len(cuts) == 1
        assert cuts[0]["start"] == 60.5

    def test_empty_text(self):
        assert cf.parse_cut_list("") == []

    def test_no_valid_cuts(self):
        assert cf.parse_cut_list("This has no cuts at all") == []

    def test_invalid_range_skipped(self):
        """End before start should be skipped."""
        text = """1. [00:02:00] → [00:01:00] | backwards
2. [00:01:00] → [00:02:00] | valid"""
        cuts = cf.parse_cut_list(text)
        assert len(cuts) == 1
        assert cuts[0]["reason"] == "valid"

    def test_various_arrow_styles(self):
        """Should handle different arrow separators."""
        for arrow in ["→", "-->", "-"]:
            text = f"1. [00:01:00] {arrow} [00:02:00] | test"
            cuts = cf.parse_cut_list(text)
            assert len(cuts) == 1, f"Failed for arrow style: {arrow}"

    def test_parenthesis_style_numbering(self):
        text = "1) 00:01:00 → 00:02:00 | test"
        cuts = cf.parse_cut_list(text)
        assert len(cuts) == 1


# ════════════════════════════════════════════════════════════════════════════
# snap_cut_end
# ════════════════════════════════════════════════════════════════════════════

class TestSnapCutEnd:
    def _segments(self):
        return [
            cf.TranscriptSegment(0.0, 5.0, "First"),
            cf.TranscriptSegment(5.0, 12.0, "Second"),
            cf.TranscriptSegment(12.0, 18.0, "Third"),
            cf.TranscriptSegment(18.0, 25.0, "Fourth"),
        ]

    def test_snaps_to_segment_end(self):
        segs = self._segments()
        # cut_end=10 falls in the second segment (5-12)
        result = cf.snap_cut_end(10.0, segs, padding=0.0)
        # Should snap to end of second segment (12.0) since that's the
        # segment whose start is closest to but not after 10.0
        assert result == 12.0

    def test_adds_padding(self):
        segs = self._segments()
        result = cf.snap_cut_end(10.0, segs, padding=2.0)
        assert result == 14.0  # 12.0 + 2.0

    def test_hard_limit(self):
        segs = self._segments()
        result = cf.snap_cut_end(10.0, segs, padding=2.0, hard_limit=13.0)
        assert result == 13.0

    def test_no_segments(self):
        result = cf.snap_cut_end(10.0, [], padding=2.0)
        assert result == 12.0  # original + padding

    def test_never_goes_backwards(self):
        segs = self._segments()
        # cut_end=20 — candidate segment starts at 18, ends at 25
        result = cf.snap_cut_end(20.0, segs, padding=0.0)
        assert result >= 20.0

    def test_hard_limit_none(self):
        segs = self._segments()
        result = cf.snap_cut_end(10.0, segs, padding=2.0, hard_limit=None)
        assert result == 14.0


# ════════════════════════════════════════════════════════════════════════════
# clip_transcript_segments
# ════════════════════════════════════════════════════════════════════════════

class TestClipTranscriptSegments:
    def _segments(self):
        return [
            cf.TranscriptSegment(0.0, 5.0, "A"),
            cf.TranscriptSegment(5.0, 10.0, "B"),
            cf.TranscriptSegment(10.0, 15.0, "C"),
            cf.TranscriptSegment(15.0, 20.0, "D"),
        ]

    def test_full_range(self):
        segs = self._segments()
        result = cf.clip_transcript_segments(segs, 0.0, 20.0)
        assert len(result) == 4

    def test_partial_overlap_start(self):
        segs = self._segments()
        # clip starts at 3.0, so first segment (0-5) overlaps
        result = cf.clip_transcript_segments(segs, 3.0, 12.0)
        assert len(result) == 3  # A(0-5), B(5-10), C(10-15)

    def test_partial_overlap_end(self):
        segs = self._segments()
        result = cf.clip_transcript_segments(segs, 8.0, 17.0)
        assert len(result) == 3  # B(5-10), C(10-15), D(15-20)

    def test_no_overlap(self):
        segs = self._segments()
        result = cf.clip_transcript_segments(segs, 25.0, 30.0)
        assert len(result) == 0

    def test_exact_boundary(self):
        segs = self._segments()
        # end=5.0 and start=5.0 should NOT overlap (end > clip_start)
        result = cf.clip_transcript_segments(segs, 5.0, 10.0)
        assert len(result) == 1  # only B(5-10)


# ════════════════════════════════════════════════════════════════════════════
# save_clip_transcript
# ════════════════════════════════════════════════════════════════════════════

class TestSaveClipTranscript:
    def test_save_and_read(self, tmp_path):
        segs = [
            cf.TranscriptSegment(0.0, 5.0, "Hello"),
            cf.TranscriptSegment(5.0, 10.0, "World"),
            cf.TranscriptSegment(10.0, 15.0, "End"),
        ]
        path = str(tmp_path / "sub" / "clip_transcript.json")
        result = cf.save_clip_transcript(segs, 3.0, 12.0, path)
        assert len(result) == 3  # all three overlap [3, 12)

        with open(path) as f:
            data = json.load(f)
        assert len(data) == 3
        assert data[0]["text"] == "Hello"


# ════════════════════════════════════════════════════════════════════════════
# build_editing_prompt
# ════════════════════════════════════════════════════════════════════════════

class TestBuildEditingPrompt:
    def test_contains_metadata(self):
        clip = cf.ClipSuggestion(
            rank=1, title="Test Clip", hook="Great hook",
            segment_start=0, segment_end=300,
            clip_start=60, clip_end=180, clip_duration=120,
            content_type="story", virality_score=8,
            transcript_excerpt="excerpt"
        )
        segs = [cf.TranscriptSegment(60, 70, "Hello world")]
        prompt = cf.build_editing_prompt(clip, segs)

        assert "Test Clip" in prompt
        assert "#1" in prompt
        assert "story" in prompt.lower() or "STORY" in prompt
        assert "8/10" in prompt
        assert "Hello world" in prompt
        assert "00:01:00" in prompt  # clip_start formatted

    def test_no_segments(self):
        clip = cf.ClipSuggestion(
            rank=2, title="No Segs", hook="h",
            segment_start=0, segment_end=300,
            clip_start=0, clip_end=60, clip_duration=60,
            content_type="advice", virality_score=5,
            transcript_excerpt=""
        )
        prompt = cf.build_editing_prompt(clip, [])
        assert "transcript not available" in prompt


# ════════════════════════════════════════════════════════════════════════════
# save_results / export_ffmpeg_commands
# ════════════════════════════════════════════════════════════════════════════

class TestSaveResults:
    def _clips(self):
        return [
            cf.ClipSuggestion(
                rank=1, title="First Clip", hook="h1",
                segment_start=0, segment_end=300,
                clip_start=30, clip_end=150, clip_duration=120,
                content_type="story", virality_score=8,
                transcript_excerpt="exc1"
            ),
            cf.ClipSuggestion(
                rank=2, title="Second Clip", hook="h2",
                segment_start=300, segment_end=600,
                clip_start=330, clip_end=450, clip_duration=120,
                content_type="advice", virality_score=6,
                transcript_excerpt="exc2"
            ),
        ]

    def test_save_json(self, tmp_path):
        clips = self._clips()
        path = str(tmp_path / "results.json")
        cf.save_results(clips, path)

        with open(path) as f:
            data = json.load(f)
        assert len(data) == 2
        assert data[0]["rank"] == 1
        assert "clip_start_fmt" in data[0]
        assert "clip_end_fmt" in data[0]

    def test_export_ffmpeg(self, tmp_path):
        clips = self._clips()
        out_dir = str(tmp_path / "clips")
        script_path = cf.export_ffmpeg_commands(clips, "source.mp4", out_dir)
        assert os.path.exists(script_path)

        with open(script_path) as f:
            content = f.read()
        assert "#!/bin/bash" in content
        assert "source.mp4" in content
        assert "ffmpeg" in content
        # Should have commands for both clips
        assert "Clip 1" in content
        assert "Clip 2" in content


# ════════════════════════════════════════════════════════════════════════════
# find_clips — deduplication logic (mock Claude responses)
# ════════════════════════════════════════════════════════════════════════════

class TestFindClipsDedup:
    """Test the overlap dedup logic in find_clips using a fake client."""

    class FakeResponse:
        def __init__(self, text):
            self.content = [type("Obj", (), {"text": text})()]

    class FakeClient:
        """Returns canned responses for each chunk."""
        def __init__(self, responses):
            self._responses = iter(responses)
            self.messages = self

        def create(self, **kwargs):
            return next(self._responses)

    def test_overlapping_clips_deduped(self):
        """Two chunks with overlapping clip ranges — only highest score kept."""
        chunks = [
            {"window_start": 0, "window_end": 300, "text": "chunk1"},
            {"window_start": 60, "window_end": 360, "text": "chunk2"},
        ]
        r1 = json.dumps({
            "has_clip": True, "virality_score": 9,
            "content_type": "story", "title": "High Score",
            "hook": "h", "clip_start_offset": 60,
            "clip_end_offset": 180, "transcript_excerpt": "e"
        })
        r2 = json.dumps({
            "has_clip": True, "virality_score": 5,
            "content_type": "advice", "title": "Low Score",
            "hook": "h", "clip_start_offset": 30,
            "clip_end_offset": 150, "transcript_excerpt": "e"
        })
        client = self.FakeClient([
            self.FakeResponse(r1),
            self.FakeResponse(r2),
        ])
        clips = cf.find_clips(chunks, client, top_n=10,
                              padding_seconds=0, total_duration=600)
        # The two clips heavily overlap, so only the higher-scored one survives
        assert len(clips) == 1
        assert clips[0].title == "High Score"

    def test_non_overlapping_both_kept(self):
        chunks = [
            {"window_start": 0, "window_end": 300, "text": "chunk1"},
            {"window_start": 500, "window_end": 800, "text": "chunk2"},
        ]
        r1 = json.dumps({
            "has_clip": True, "virality_score": 7,
            "content_type": "story", "title": "Clip A",
            "hook": "h", "clip_start_offset": 60,
            "clip_end_offset": 180, "transcript_excerpt": "e"
        })
        r2 = json.dumps({
            "has_clip": True, "virality_score": 6,
            "content_type": "advice", "title": "Clip B",
            "hook": "h", "clip_start_offset": 60,
            "clip_end_offset": 180, "transcript_excerpt": "e"
        })
        client = self.FakeClient([
            self.FakeResponse(r1),
            self.FakeResponse(r2),
        ])
        clips = cf.find_clips(chunks, client, top_n=10,
                              padding_seconds=0, total_duration=1000)
        assert len(clips) == 2

    def test_has_clip_false_skipped(self):
        chunks = [{"window_start": 0, "window_end": 300, "text": "x"}]
        r = json.dumps({"has_clip": False})
        client = self.FakeClient([self.FakeResponse(r)])
        clips = cf.find_clips(chunks, client, top_n=10,
                              padding_seconds=0, total_duration=600)
        assert len(clips) == 0
