use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TranscriptSegment {
    pub start: f64,
    pub end: f64,
    pub text: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ClipSuggestion {
    pub rank: i32,
    pub title: String,
    pub hook: String,
    pub segment_start: f64,
    pub segment_end: f64,
    pub clip_start: f64,
    pub clip_end: f64,
    pub clip_duration: f64,
    pub content_type: String,
    pub virality_score: i32,
    pub transcript_excerpt: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VolumeSpike {
    pub start: f64,
    pub end: f64,
    pub intensity: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AnalysisChunk {
    pub window_start: f64,
    pub window_end: f64,
    pub text: String,
}

/// Progress events streamed to the frontend via SSE.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type")]
pub enum ProgressEvent {
    Hashing { percent: u8 },
    AudioExtraction { percent: u8 },
    SpikeDetection { spike_count: usize },
    Transcription { percent: u8, label: String },
    Chunking { chunk_count: usize },
    Analysis { done: usize, total: usize },
    ClipExtraction { done: usize, total: usize, clip_name: String },
    SliceGeneration { done: usize, total: usize },
    ClipsReady { clips: Vec<ClipSuggestion> },
    Log { level: String, message: String },
    PipelineDone,
    PipelineError { message: String },
}

/// Format seconds as HH:MM:SS.
pub fn fmt_time(seconds: f64) -> String {
    let total = seconds as u64;
    let h = total / 3600;
    let m = (total % 3600) / 60;
    let s = total % 60;
    format!("{:02}:{:02}:{:02}", h, m, s)
}

/// Parse a timestamp string (HH:MM:SS, MM:SS, or raw seconds) into seconds.
pub fn parse_time(ts: &str) -> anyhow::Result<f64> {
    let parts: Vec<&str> = ts.trim().split(':').collect();
    match parts.len() {
        3 => {
            let h: f64 = parts[0].parse()?;
            let m: f64 = parts[1].parse()?;
            let s: f64 = parts[2].parse()?;
            Ok(h * 3600.0 + m * 60.0 + s)
        }
        2 => {
            let m: f64 = parts[0].parse()?;
            let s: f64 = parts[1].parse()?;
            Ok(m * 60.0 + s)
        }
        1 => Ok(parts[0].parse()?),
        _ => anyhow::bail!("Invalid timestamp: {}", ts),
    }
}
