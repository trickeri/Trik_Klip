// Clip analysis, scoring, and deduplication.
// Ported from Python clip_finder.py: analyze_chunk() + find_clips().

use std::sync::Arc;
use serde::Deserialize;
use tokio::task::JoinSet;
use tracing::{info, warn};

use crate::llm::provider::LlmProvider;
use crate::models::{fmt_time, AnalysisChunk, ClipSuggestion, ProgressEvent};
use crate::prompts::build_system_prompt;

/// Response from LLM analysis of a single chunk.
#[derive(Debug, Deserialize)]
struct ChunkAnalysis {
    has_clip: bool,
    #[serde(default)]
    virality_score: i32,
    #[serde(default)]
    content_type: String,
    #[serde(default)]
    title: String,
    #[serde(default)]
    hook: String,
    #[serde(default)]
    clip_start_offset: f64,
    #[serde(default)]
    clip_end_offset: f64,
    #[serde(default)]
    transcript_excerpt: String,
}

/// Strip markdown code fences that LLMs sometimes wrap around JSON.
fn strip_fences(raw: &str) -> &str {
    let s = raw.trim();
    let s = s.strip_prefix("```json").unwrap_or(s);
    let s = s.strip_prefix("```").unwrap_or(s);
    let s = s.strip_suffix("```").unwrap_or(s);
    s.trim()
}

/// Analyze a single transcript chunk with the LLM.
///
/// Returns `None` on any error (API failure, unparseable JSON, etc.).
async fn analyze_chunk(
    chunk: &AnalysisChunk,
    provider: &dyn LlmProvider,
    model: &str,
    custom_prompts: Option<&[String]>,
) -> Option<ChunkAnalysis> {
    let system_prompt = build_system_prompt(custom_prompts);

    let window_duration = chunk.window_end - chunk.window_start;
    let user_prompt = format!(
        "Window timestamps: {} → {} ({:.1} min)\n\n\
         Transcript:\n{}\n\n\
         Respond with ONLY the JSON object. No markdown, no explanation, no code fences.",
        fmt_time(chunk.window_start),
        fmt_time(chunk.window_end),
        window_duration / 60.0,
        chunk.text,
    );

    let response = match provider.message(model, &user_prompt, &system_prompt, 600).await {
        Ok(r) => r,
        Err(e) => {
            warn!(
                "LLM error for chunk at {}: {}",
                fmt_time(chunk.window_start),
                e
            );
            return None;
        }
    };

    let cleaned = strip_fences(&response.text);

    match serde_json::from_str::<ChunkAnalysis>(cleaned) {
        Ok(analysis) => Some(analysis),
        Err(e) => {
            let preview: String = cleaned.chars().take(200).collect();
            warn!(
                "Could not parse LLM response for chunk at {}: {}. Preview: {:?}",
                fmt_time(chunk.window_start),
                e,
                preview,
            );
            None
        }
    }
}

/// Internal candidate produced during analysis before ranking/dedup.
struct Candidate {
    chunk_window_start: f64,
    chunk_window_end: f64,
    clip_start: f64,
    clip_end: f64,
    duration: f64,
    score: i32,
    title: String,
    hook: String,
    content_type: String,
    virality_score: i32,
    transcript_excerpt: String,
}

/// Analyze all chunks in parallel and return the top-N clip suggestions.
///
/// * `max_workers` — concurrency limit for LLM calls.
/// * `padding_seconds` — seconds of context added before/after each core clip.
/// * `total_duration` — total source audio length used to clamp clip ends.
/// * `progress_tx` — optional broadcast sender to emit `ProgressEvent::Analysis`.
pub async fn find_clips(
    chunks: &[AnalysisChunk],
    provider: Arc<dyn LlmProvider>,
    model: &str,
    top_n: usize,
    padding_seconds: f64,
    total_duration: f64,
    max_workers: usize,
    custom_prompts: Option<&[String]>,
    progress_tx: Option<&tokio::sync::broadcast::Sender<ProgressEvent>>,
) -> Vec<ClipSuggestion> {
    let total = chunks.len();
    info!(
        "find_clips: starting analysis of {} chunks, top_n={}, provider={}",
        total,
        top_n,
        provider.provider_name()
    );
    let semaphore = Arc::new(tokio::sync::Semaphore::new(max_workers));
    let mut join_set: JoinSet<Option<(usize, ChunkAnalysis)>> = JoinSet::new();

    let model_owned = model.to_owned();
    let custom_owned: Option<Vec<String>> = custom_prompts.map(|s| s.to_vec());

    for (idx, chunk) in chunks.iter().enumerate() {
        let sem = semaphore.clone();
        let model_c = model_owned.clone();
        let custom_c = custom_owned.clone();
        let chunk_c = chunk.clone();
        let provider_c = provider.clone();

        join_set.spawn(async move {
            let _permit = sem.acquire().await.ok()?;
            let prompts_ref = custom_c.as_deref().map(|v| &v[..]);
            let result = analyze_chunk(&chunk_c, provider_c.as_ref(), &model_c, prompts_ref).await?;
            Some((idx, result))
        });
    }

    let mut candidates: Vec<Candidate> = Vec::new();
    let mut done = 0usize;

    while let Some(join_result) = join_set.join_next().await {
        done += 1;

        // Emit progress
        if let Some(tx) = progress_tx {
            let _ = tx.send(ProgressEvent::Analysis { done, total });
        }

        let task_result = match join_result {
            Ok(r) => r,
            Err(e) => {
                warn!("Task join error: {}", e);
                continue;
            }
        };

        let (idx, analysis) = match task_result {
            Some(pair) => pair,
            None => continue,
        };

        if !analysis.has_clip {
            continue;
        }

        let chunk = &chunks[idx];

        // Core clip as identified by the LLM (clamped to window)
        let core_start = (chunk.window_start + analysis.clip_start_offset)
            .max(chunk.window_start);
        let core_end = (chunk.window_start + analysis.clip_end_offset)
            .min(chunk.window_end);

        // Skip tiny fragments (< 30s)
        if core_end - core_start < 30.0 {
            continue;
        }

        // Expand with padding for editing headroom
        let clip_start = (core_start - padding_seconds).max(0.0);
        let mut clip_end = core_end + padding_seconds;
        if total_duration > 0.0 {
            clip_end = clip_end.min(total_duration);
        }
        let duration = clip_end - clip_start;

        candidates.push(Candidate {
            chunk_window_start: chunk.window_start,
            chunk_window_end: chunk.window_end,
            clip_start,
            clip_end,
            duration,
            score: analysis.virality_score,
            title: if analysis.title.is_empty() {
                "Untitled Clip".to_owned()
            } else {
                analysis.title
            },
            hook: analysis.hook,
            content_type: if analysis.content_type.is_empty() {
                "other".to_owned()
            } else {
                analysis.content_type
            },
            virality_score: analysis.virality_score,
            transcript_excerpt: analysis.transcript_excerpt,
        });
    }

    let candidates_len = candidates.len();

    // Sort by virality score descending
    candidates.sort_by(|a, b| b.score.cmp(&a.score));

    // Deduplicate overlapping ranges
    let mut selected: Vec<ClipSuggestion> = Vec::new();
    let mut used_ranges: Vec<(f64, f64)> = Vec::new();
    let mut rank = 0i32;

    for c in candidates {
        let cs = c.clip_start;
        let ce = c.clip_end;
        let overlap = used_ranges
            .iter()
            .any(|&(s, e)| !(ce <= s || cs >= e));
        if overlap {
            continue;
        }
        used_ranges.push((cs, ce));
        rank += 1;

        selected.push(ClipSuggestion {
            rank,
            title: c.title,
            hook: c.hook,
            segment_start: c.chunk_window_start,
            segment_end: c.chunk_window_end,
            clip_start: c.clip_start,
            clip_end: c.clip_end,
            clip_duration: c.duration,
            content_type: c.content_type,
            virality_score: c.virality_score,
            transcript_excerpt: c.transcript_excerpt,
        });

        if selected.len() >= top_n {
            break;
        }
    }

    info!(
        "find_clips: finished. {} chunks analyzed, {} candidates (has_clip=true), {} selected after dedup",
        total,
        candidates_len,
        selected.len(),
    );

    selected
}
