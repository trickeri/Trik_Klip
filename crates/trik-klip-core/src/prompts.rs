// System/user prompt templates for clip analysis and editing.

use regex::Regex;
use std::sync::LazyLock;

use crate::models::{ClipSuggestion, TranscriptSegment, fmt_time, parse_time};

/// A single entry from a parsed CUT LIST block.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct CutEntry {
    pub start: f64,
    pub end: f64,
    pub reason: String,
}

// ---------------------------------------------------------------------------
// Analysis prompt
// ---------------------------------------------------------------------------

const ANALYSIS_SYSTEM_PROMPT: &str = r#"You are a clip-finding assistant. You receive a transcript window and return a single JSON object. You NEVER return markdown, explanations, or commentary — ONLY raw JSON.

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
- If the transcript contains [AUDIO ENERGY NOTES], these indicate moments where the speaker's volume spiked significantly (yelling, excitement, reactions). Treat these as strong positive signals for clip-worthiness — try to include these moments in your clip selection."#;

/// Build the system prompt for clip analysis, optionally appending custom
/// user instructions.
pub fn build_system_prompt(custom_prompts: Option<&[String]>) -> String {
    let extras = custom_prompts
        .unwrap_or(&[])
        .iter()
        .map(|p| p.trim())
        .filter(|p| !p.is_empty())
        .map(|p| format!("- {p}"))
        .collect::<Vec<_>>();

    if extras.is_empty() {
        return ANALYSIS_SYSTEM_PROMPT.to_string();
    }

    format!(
        "{}\n\nThe user has also asked you to look for the following specific things in the transcript. \
         Prioritise these alongside the standard criteria above:\n{}",
        ANALYSIS_SYSTEM_PROMPT,
        extras.join("\n"),
    )
}

// ---------------------------------------------------------------------------
// Editing prompt
// ---------------------------------------------------------------------------

/// Build the full editing prompt for a single clip.
///
/// `clip_segments` should contain only the transcript segments that overlap
/// the clip's time range.
pub fn build_editing_prompt(
    clip: &ClipSuggestion,
    clip_segments: &[TranscriptSegment],
) -> String {
    let duration_s = clip.clip_end - clip.clip_start;

    let transcript_text = if clip_segments.is_empty() {
        String::from("(transcript not available)")
    } else {
        clip_segments
            .iter()
            .map(|s| format!("[{}]  {}", fmt_time(s.start), s.text.trim()))
            .collect::<Vec<_>>()
            .join("\n")
    };

    format!(
        "\
You are an expert short-form video editor.
Your job is to turn a raw stream clip into a punchy, engaging short (60\u{2013}150 seconds).

\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}
CLIP METADATA
\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}
  Rank:             #{rank}
  Title:            {title}
  Content type:     {content_type}
  Virality score:   {virality}/10
  Source range:     {range_start} \u{2192} {range_end}
  Available length: {dur_s:.0} s  ({dur_m:.1} min)
  Auto-detected hook note:
    {hook}

\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}
TRANSCRIPT  (timestamps are relative to the original source file)
\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}
{transcript}

\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}
YOUR TASK
\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}
Produce an editing outline that follows this story structure:

  1. HOOK (first ~5\u{2013}15 s)
     The single most attention-grabbing moment in the clip.
     Can be a provocative statement, a surprising reveal, a question,
     or the climactic beat brought to the very start.

  2. CONFLICT / TENSION  (include only if naturally present)
     A problem being solved, a challenge faced, or tension that
     builds curiosity and makes the payoff feel earned.

  3. PAYOFF / CONCLUSION
     The satisfying resolution, key insight, result, or call-to-action
     that gives viewers a reason to have watched.

\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}
CUT LIST RULES
\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}
\u{2022} List every segment to keep as a precise time range.
\u{2022} Timestamps MUST be relative to the original source file (not the clip file).
\u{2022} REMOVE: pauses longer than 1 s, filler words / phrases
  (um, uh, like, you know, sort of, basically, I mean, right?),
  false starts, repeated words, off-topic tangents.
\u{2022} Segments MAY be reordered to improve story flow \u{2014} flag this if so.
\u{2022} The sum of all segment durations MUST be between 60 and 150 seconds.
\u{2022} Aim for natural sentence/thought breaks at cut points.

\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}
RESPOND IN EXACTLY THIS FORMAT  (no extra commentary outside it)
\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}

PURPOSE:
[One sentence \u{2014} what is this clip about and why will viewers care?]

HOOK:
[Describe the hook moment and why it grabs attention]

CONFLICT:
[Describe the tension/problem, or write: N/A]

PAYOFF:
[Describe the resolution, key insight, or takeaway]

CUT LIST:
1. [HH:MM:SS.s] \u{2192} [HH:MM:SS.s] | [what's happening / why keep it]
2. [HH:MM:SS.s] \u{2192} [HH:MM:SS.s] | [what's happening / why keep it]
... (one line per segment, no gaps)

ESTIMATED TOTAL: [X] seconds
REORDERED: [Yes \u{2014} explain / No]
NOTES: [Optional: music mood, caption style, thumbnail idea, B-roll suggestions]
",
        rank = clip.rank,
        title = clip.title,
        content_type = clip.content_type,
        virality = clip.virality_score,
        range_start = fmt_time(clip.clip_start),
        range_end = fmt_time(clip.clip_end),
        dur_s = duration_s,
        dur_m = duration_s / 60.0,
        hook = clip.hook,
        transcript = transcript_text,
    )
}

// ---------------------------------------------------------------------------
// Cut-list parsing
// ---------------------------------------------------------------------------

/// Regex matching cut-list lines like:
///   1. [00:12:34.5] -> [00:13:00.0] | reason text
///   2) 12:34 → 13:00 | reason text
///
/// Matches HH:MM:SS, HH:MM:SS.s, MM:SS, MM:SS.s with optional brackets.
static CUT_RE: LazyLock<Regex> = LazyLock::new(|| {
    let ts = r"\[?(\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?)\]?";
    let pattern = [
        r"(?m)^\s*\d+[.)]\s*",
        ts,
        r"\s*[-\u{2192}\u{2013}\u{2014}>]+\s*",
        ts,
        r"\s*[|]?\s*(.*)",
    ].concat();
    Regex::new(&pattern).expect("CUT_RE must compile")
});

/// Parse a CUT LIST block from an LLM edit-plan response.
///
/// Returns entries with source-file-relative timestamps.  The caller is
/// responsible for adjusting them to clip-relative if needed.
pub fn parse_cut_list(text: &str) -> Vec<CutEntry> {
    let mut cuts = Vec::new();

    for caps in CUT_RE.captures_iter(text) {
        let start_str = caps.get(1).map(|m| m.as_str()).unwrap_or("");
        let end_str = caps.get(2).map(|m| m.as_str()).unwrap_or("");
        let reason = caps
            .get(3)
            .map(|m| m.as_str().trim().to_string())
            .unwrap_or_default();

        let (Ok(start), Ok(end)) = (parse_time(start_str), parse_time(end_str)) else {
            continue;
        };

        if end > start {
            cuts.push(CutEntry { start, end, reason });
        }
    }

    cuts
}

/// Extend a cut's end point so it doesn't land mid-sentence.
///
/// Finds the Whisper segment whose `start` is closest to (but not after)
/// `cut_end`, then uses that segment's `end` as the new boundary.
/// `padding` extra seconds are added after that to avoid a hard cut on
/// the very last word.  The result is clamped to `hard_limit` when given.
///
/// If no matching segment is found the original `cut_end` is returned
/// (plus padding, clamped).
pub fn snap_cut_end(
    cut_end: f64,
    segments: &[TranscriptSegment],
    padding: f64,
    hard_limit: Option<f64>,
) -> f64 {
    let candidates: Vec<&TranscriptSegment> =
        segments.iter().filter(|s| s.start <= cut_end).collect();

    let snapped = if let Some(best) = candidates.iter().max_by(|a, b| {
        a.start
            .partial_cmp(&b.start)
            .unwrap_or(std::cmp::Ordering::Equal)
    }) {
        // Never go backwards -- if the segment ended before cut_end, keep cut_end
        best.end.max(cut_end)
    } else {
        cut_end
    };

    let result = snapped + padding;
    match hard_limit {
        Some(limit) => result.min(limit),
        None => result,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn system_prompt_no_custom() {
        let prompt = build_system_prompt(None);
        assert!(prompt.contains("clip-finding assistant"));
        assert!(!prompt.contains("Prioritise"));
    }

    #[test]
    fn system_prompt_with_custom() {
        let customs = vec!["look for rage moments".to_string(), "find cooking tips".to_string()];
        let prompt = build_system_prompt(Some(&customs));
        assert!(prompt.contains("Prioritise"));
        assert!(prompt.contains("- look for rage moments"));
        assert!(prompt.contains("- find cooking tips"));
    }

    #[test]
    fn system_prompt_empty_custom() {
        let customs = vec!["  ".to_string(), "".to_string()];
        let prompt = build_system_prompt(Some(&customs));
        assert!(!prompt.contains("Prioritise"));
    }

    #[test]
    fn editing_prompt_contains_metadata() {
        let clip = ClipSuggestion {
            rank: 1,
            title: "Test Clip".to_string(),
            hook: "Great hook".to_string(),
            segment_start: 0.0,
            segment_end: 180.0,
            clip_start: 30.0,
            clip_end: 150.0,
            clip_duration: 120.0,
            content_type: "story".to_string(),
            virality_score: 8,
            transcript_excerpt: "excerpt".to_string(),
        };
        let segs = vec![TranscriptSegment {
            start: 30.0,
            end: 35.0,
            text: "Hello world".to_string(),
        }];
        let prompt = build_editing_prompt(&clip, &segs);
        assert!(prompt.contains("#1"));
        assert!(prompt.contains("Test Clip"));
        assert!(prompt.contains("8/10"));
        assert!(prompt.contains("[00:00:30]  Hello world"));
    }

    #[test]
    fn editing_prompt_no_segments() {
        let clip = ClipSuggestion {
            rank: 2,
            title: "T".to_string(),
            hook: "H".to_string(),
            segment_start: 0.0,
            segment_end: 60.0,
            clip_start: 0.0,
            clip_end: 60.0,
            clip_duration: 60.0,
            content_type: "moment".to_string(),
            virality_score: 5,
            transcript_excerpt: "".to_string(),
        };
        let prompt = build_editing_prompt(&clip, &[]);
        assert!(prompt.contains("(transcript not available)"));
    }

    #[test]
    fn parse_cut_list_basic() {
        let text = r#"
CUT LIST:
1. [00:12:30.0] → [00:13:00.0] | Hook moment
2. [00:14:00] → [00:15:30] | Main content
3. [00:16:00.5] → [00:16:45.0] | Payoff
"#;
        let cuts = parse_cut_list(text);
        assert_eq!(cuts.len(), 3);

        assert!((cuts[0].start - 750.0).abs() < 0.1);
        assert!((cuts[0].end - 780.0).abs() < 0.1);
        assert_eq!(cuts[0].reason, "Hook moment");

        assert!((cuts[1].start - 840.0).abs() < 0.1);
        assert!((cuts[1].end - 930.0).abs() < 0.1);

        assert!((cuts[2].start - 960.5).abs() < 0.1);
    }

    #[test]
    fn parse_cut_list_with_parens() {
        let text = "1) 01:00 -> 02:00 | reason\n";
        let cuts = parse_cut_list(text);
        assert_eq!(cuts.len(), 1);
        assert!((cuts[0].start - 60.0).abs() < 0.1);
        assert!((cuts[0].end - 120.0).abs() < 0.1);
    }

    #[test]
    fn parse_cut_list_invalid_range_skipped() {
        // end <= start should be skipped
        let text = "1. 02:00 → 01:00 | backwards\n";
        let cuts = parse_cut_list(text);
        assert!(cuts.is_empty());
    }

    #[test]
    fn snap_cut_end_basic() {
        let segs = vec![
            TranscriptSegment { start: 10.0, end: 15.0, text: "a".into() },
            TranscriptSegment { start: 15.0, end: 22.0, text: "b".into() },
            TranscriptSegment { start: 23.0, end: 30.0, text: "c".into() },
        ];
        // cut_end=20.0 -> closest segment with start<=20 is seg at 15.0, end=22.0
        // snapped = max(22.0, 20.0) = 22.0, result = 22.0 + 2.0 = 24.0
        let result = snap_cut_end(20.0, &segs, 2.0, None);
        assert!((result - 24.0).abs() < f64::EPSILON);
    }

    #[test]
    fn snap_cut_end_with_hard_limit() {
        let segs = vec![
            TranscriptSegment { start: 10.0, end: 50.0, text: "a".into() },
        ];
        // snapped = max(50.0, 20.0) = 50.0, result = 52.0, clamped to 45.0
        let result = snap_cut_end(20.0, &segs, 2.0, Some(45.0));
        assert!((result - 45.0).abs() < f64::EPSILON);
    }

    #[test]
    fn snap_cut_end_no_candidates() {
        let segs = vec![
            TranscriptSegment { start: 100.0, end: 110.0, text: "a".into() },
        ];
        // No segment with start <= 20.0, so snapped = 20.0, result = 22.0
        let result = snap_cut_end(20.0, &segs, 2.0, None);
        assert!((result - 22.0).abs() < f64::EPSILON);
    }
}
