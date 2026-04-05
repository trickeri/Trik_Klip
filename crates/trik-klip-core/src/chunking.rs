// Transcript chunking with sliding windows and spike annotation.

use crate::models::{AnalysisChunk, TranscriptSegment, VolumeSpike, fmt_time};

/// Split transcript segments into overlapping time-windowed chunks.
///
/// Each chunk covers `window_minutes` of audio with `overlap_minutes` of
/// overlap between consecutive windows.  Segments whose `start` falls
/// within the window are concatenated into the chunk text.
pub fn chunk_transcript(
    segments: &[TranscriptSegment],
    window_minutes: f64,
    overlap_minutes: f64,
) -> Vec<AnalysisChunk> {
    let window_sec = window_minutes * 60.0;
    let overlap_sec = overlap_minutes * 60.0;
    let step_sec = window_sec - overlap_sec;

    if segments.is_empty() {
        return Vec::new();
    }

    let total_duration = segments
        .last()
        .expect("checked non-empty above")
        .end;

    let mut chunks = Vec::new();
    let mut t = 0.0_f64;

    while t < total_duration {
        let chunk_end = t + window_sec;

        let chunk_segs: Vec<&TranscriptSegment> = segments
            .iter()
            .filter(|s| s.start >= t && s.start < chunk_end)
            .collect();

        if !chunk_segs.is_empty() {
            let text = chunk_segs
                .iter()
                .map(|s| s.text.as_str())
                .collect::<Vec<_>>()
                .join(" ");

            chunks.push(AnalysisChunk {
                window_start: t,
                window_end: chunk_end.min(total_duration),
                text,
            });
        }

        t += step_sec;
    }

    chunks
}

/// Annotate chunks in-place with audio energy spike information.
///
/// For each chunk, any spikes that overlap the chunk's time window are
/// appended as `[AUDIO ENERGY NOTES]` lines describing the spike
/// timestamp, intensity, and duration.
pub fn annotate_chunks_with_spikes(
    chunks: &mut Vec<AnalysisChunk>,
    spikes: &[VolumeSpike],
) {
    if spikes.is_empty() {
        return;
    }

    for chunk in chunks.iter_mut() {
        let w_start = chunk.window_start;
        let w_end = chunk.window_end;

        let hits: Vec<&VolumeSpike> = spikes
            .iter()
            .filter(|s| s.start < w_end && s.end > w_start)
            .collect();

        if !hits.is_empty() {
            let mut lines = vec![String::from("\n\n[AUDIO ENERGY NOTES]")];
            for spike in &hits {
                let dur = spike.end - spike.start;
                lines.push(format!(
                    "- Volume spike at {} ({:.0}x above average, {:.1}s duration)",
                    fmt_time(spike.start),
                    spike.intensity,
                    dur,
                ));
            }
            chunk.text.push_str(&lines.join("\n"));
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_segments(intervals: &[(f64, f64, &str)]) -> Vec<TranscriptSegment> {
        intervals
            .iter()
            .map(|(start, end, text)| TranscriptSegment {
                start: *start,
                end: *end,
                text: text.to_string(),
            })
            .collect()
    }

    #[test]
    fn empty_segments_returns_empty() {
        let result = chunk_transcript(&[], 8.0, 1.0);
        assert!(result.is_empty());
    }

    #[test]
    fn single_segment_produces_one_chunk() {
        let segs = make_segments(&[(0.0, 5.0, "hello world")]);
        let chunks = chunk_transcript(&segs, 8.0, 1.0);
        assert_eq!(chunks.len(), 1);
        assert_eq!(chunks[0].window_start, 0.0);
        assert!((chunks[0].window_end - 5.0).abs() < f64::EPSILON);
        assert_eq!(chunks[0].text, "hello world");
    }

    #[test]
    fn overlapping_windows() {
        // 15 minutes of segments at 1-minute intervals
        let segs: Vec<TranscriptSegment> = (0..15)
            .map(|i| TranscriptSegment {
                start: i as f64 * 60.0,
                end: (i as f64 + 1.0) * 60.0,
                text: format!("seg{}", i),
            })
            .collect();
        // window=8min, overlap=1min => step=7min
        let chunks = chunk_transcript(&segs, 8.0, 1.0);
        // Window 0: 0..480, Window 1: 420..900, Window 2: 840..1320
        assert!(chunks.len() >= 2);
        // Second chunk should start at 420
        assert!((chunks[1].window_start - 420.0).abs() < f64::EPSILON);
    }

    #[test]
    fn spike_annotation() {
        let segs = make_segments(&[(0.0, 60.0, "some text")]);
        let mut chunks = chunk_transcript(&segs, 8.0, 1.0);
        let spikes = vec![VolumeSpike {
            start: 10.0,
            end: 12.0,
            intensity: 3.5,
        }];
        annotate_chunks_with_spikes(&mut chunks, &spikes);
        assert!(chunks[0].text.contains("[AUDIO ENERGY NOTES]"));
        assert!(chunks[0].text.contains("4x above average"));
        assert!(chunks[0].text.contains("2.0s duration"));
    }

    #[test]
    fn no_spikes_leaves_text_unchanged() {
        let segs = make_segments(&[(0.0, 60.0, "original text")]);
        let mut chunks = chunk_transcript(&segs, 8.0, 1.0);
        annotate_chunks_with_spikes(&mut chunks, &[]);
        assert_eq!(chunks[0].text, "original text");
    }
}
