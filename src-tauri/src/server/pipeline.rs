// Pipeline orchestrator — runs the full clip-finding pipeline as a background task.

use std::path::{Path, PathBuf};
use std::sync::atomic::Ordering;
use std::sync::Arc;

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use tokio::sync::watch;
use tracing::{info, warn};

use trik_klip_core::chunking::{annotate_chunks_with_spikes, chunk_transcript};
use trik_klip_core::clip_scoring::find_clips;
use trik_klip_core::db::{self, models::TranscriptRow};
use trik_klip_core::ffmpeg::{extract_audio, extract_clip, extract_slice, get_duration};
use trik_klip_core::llm::make_provider;
use trik_klip_core::models::*;
use trik_klip_core::prompts::{build_editing_prompt, parse_cut_list, snap_cut_end};
use trik_klip_core::spike_detection::detect_volume_spikes_default;
use trik_klip_core::whisper::transcribe;

use crate::server::AppState;

// ---------------------------------------------------------------------------
// Request / response types
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct PipelineParams {
    pub source_path: String,
    pub output_dir: String,
    #[serde(default = "default_language")]
    pub language: String,
    #[serde(default)]
    pub audio_track: Option<u32>,
    /// LLM provider key (e.g. "anthropic", "openai", "gemini", "grok", "ollama", "claude_code")
    pub provider: String,
    pub model: String,
    #[serde(default)]
    pub api_key: Option<String>,
    #[serde(default)]
    pub base_url: Option<String>,
    #[serde(default = "default_top_n")]
    pub top_n: usize,
    #[serde(default = "default_padding")]
    pub padding_seconds: f64,
    #[serde(default = "default_max_workers")]
    pub max_workers: usize,
    #[serde(default = "default_window_minutes")]
    pub window_minutes: f64,
    #[serde(default = "default_overlap_minutes")]
    pub overlap_minutes: f64,
    #[serde(default)]
    pub custom_prompts: Option<Vec<String>>,
}

fn default_language() -> String {
    "en".into()
}
fn default_top_n() -> usize {
    5
}
fn default_padding() -> f64 {
    30.0
}
fn default_max_workers() -> usize {
    3
}
fn default_window_minutes() -> f64 {
    8.0
}
fn default_overlap_minutes() -> f64 {
    1.0
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct ExtractParams {
    pub source_path: String,
    pub output_dir: String,
    pub clips: Vec<ClipSuggestion>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct SliceParams {
    /// Path to the clip MP4 to slice.
    pub clip_path: String,
    /// The clip suggestion that this clip was extracted from (for prompt building).
    pub clip: ClipSuggestion,
    /// Full transcript segments (source-file timestamps).
    pub segments: Vec<TranscriptSegment>,
    /// LLM provider key.
    pub provider: String,
    pub model: String,
    #[serde(default)]
    pub api_key: Option<String>,
    #[serde(default)]
    pub base_url: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct AnalyzeOnlyParams {
    pub source_path: String,
    pub output_dir: String,
    pub transcript_hash: String,
    pub provider: String,
    pub model: String,
    #[serde(default)]
    pub api_key: Option<String>,
    #[serde(default)]
    pub base_url: Option<String>,
    #[serde(default = "default_top_n")]
    pub top_n: usize,
    #[serde(default = "default_padding")]
    pub padding_seconds: f64,
    #[serde(default = "default_max_workers")]
    pub max_workers: usize,
    #[serde(default = "default_window_minutes")]
    pub window_minutes: f64,
    #[serde(default = "default_overlap_minutes")]
    pub overlap_minutes: f64,
    #[serde(default)]
    pub custom_prompts: Option<Vec<String>>,
}

#[derive(Debug, Clone, Serialize)]
pub struct PipelineResult {
    pub clips: Vec<ClipSuggestion>,
    pub transcript_hash: String,
    pub duration_seconds: f64,
}

#[derive(Debug, Clone, Serialize)]
pub struct TranscribeResult {
    pub transcript_hash: String,
    pub segments: Vec<TranscriptSegment>,
    pub duration_seconds: f64,
    pub spike_count: usize,
}

#[derive(Debug, Clone, Serialize)]
pub struct ExtractResult {
    pub extracted: Vec<ExtractedClipInfo>,
}

#[derive(Debug, Clone, Serialize)]
pub struct ExtractedClipInfo {
    pub rank: i32,
    pub title: String,
    pub path: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct SliceResult {
    pub slices: Vec<String>,
}

// ---------------------------------------------------------------------------
// Cancellation helper
// ---------------------------------------------------------------------------

fn check_cancel(cancel_rx: &mut watch::Receiver<bool>) -> Result<()> {
    if *cancel_rx.borrow() {
        anyhow::bail!("Pipeline cancelled by user");
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// File hashing
// ---------------------------------------------------------------------------

async fn hash_file(path: &str) -> Result<String> {
    use tokio::io::AsyncReadExt;

    let mut file = tokio::fs::File::open(path)
        .await
        .with_context(|| format!("Cannot open file for hashing: {}", path))?;

    let mut hasher = Sha256::new();
    let mut buf = vec![0u8; 1024 * 1024]; // 1 MB chunks

    loop {
        let n = file.read(&mut buf).await?;
        if n == 0 {
            break;
        }
        hasher.update(&buf[..n]);
    }

    Ok(hex::encode(hasher.finalize()))
}

// ---------------------------------------------------------------------------
// Resolve the API key for a provider
// ---------------------------------------------------------------------------

fn resolve_api_key(state: &AppState, provider: &str, override_key: Option<&str>) -> String {
    if let Some(k) = override_key {
        if !k.is_empty() {
            return k.to_string();
        }
    }
    match provider {
        "anthropic" => state.settings.anthropic_api_key.clone(),
        "openai" => state.settings.openai_api_key.clone(),
        "gemini" => state.settings.gemini_api_key.clone(),
        "grok" | "xai" => state.settings.xai_api_key.clone(),
        _ => String::new(),
    }
}

fn resolve_base_url(state: &AppState, provider: &str, override_url: Option<&str>) -> String {
    if let Some(u) = override_url {
        if !u.is_empty() {
            return u.to_string();
        }
    }
    match provider {
        "ollama" => state.settings.ollama_base_url.clone(),
        _ => String::new(),
    }
}

// ---------------------------------------------------------------------------
// Temp WAV path
// ---------------------------------------------------------------------------

fn temp_wav_path(state: &AppState, source_path: &str) -> PathBuf {
    let stem = Path::new(source_path)
        .file_stem()
        .map(|s| s.to_string_lossy().into_owned())
        .unwrap_or_else(|| "audio".into());
    PathBuf::from(&state.settings.data_dir)
        .join("temp")
        .join(format!("{}.wav", stem))
}

// ---------------------------------------------------------------------------
// Full pipeline
// ---------------------------------------------------------------------------

pub async fn run_full_pipeline(
    state: Arc<AppState>,
    params: PipelineParams,
) -> Result<PipelineResult> {
    // 1. Mark pipeline as running
    if state
        .pipeline_running
        .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
        .is_err()
    {
        anyhow::bail!("Pipeline is already running");
    }

    let result = run_full_pipeline_inner(state.clone(), params).await;

    // Always reset running flag
    state.pipeline_running.store(false, Ordering::SeqCst);
    // Reset cancel signal
    let _ = state.cancel_tx.send(false);

    match &result {
        Ok(_) => {
            let _ = state.progress_tx.send(ProgressEvent::PipelineDone);
        }
        Err(e) => {
            let _ = state.progress_tx.send(ProgressEvent::PipelineError {
                message: e.to_string(),
            });
        }
    }

    result
}

async fn run_full_pipeline_inner(
    state: Arc<AppState>,
    params: PipelineParams,
) -> Result<PipelineResult> {
    let mut cancel_rx = state.cancel_tx.subscribe();
    let tx = &state.progress_tx;

    // 2. Hash source file and check transcript cache
    let _ = tx.send(ProgressEvent::Log {
        level: "info".into(),
        message: "Computing file hash...".into(),
    });
    let file_hash = hash_file(&params.source_path).await?;
    check_cancel(&mut cancel_rx)?;

    // Check for cached transcript
    let cached = db::get_transcript_by_hash(&state.db, &file_hash).await?;

    let (segments, duration, spikes) = if let Some(row) = cached {
        info!("Using cached transcript for hash {}", file_hash);
        let _ = tx.send(ProgressEvent::Log {
            level: "info".into(),
            message: "Found cached transcript, skipping extraction and transcription.".into(),
        });
        let segments: Vec<TranscriptSegment> = serde_json::from_str(&row.segments_json)?;
        // We still need spikes for annotation — re-detect or skip if WAV is gone
        let wav_path = temp_wav_path(&state, &params.source_path);
        let spikes = if wav_path.exists() {
            let wp = wav_path.to_string_lossy().to_string();
            tokio::task::spawn_blocking(move || detect_volume_spikes_default(&wp))
                .await??
        } else {
            // Need to re-extract audio for spike detection
            std::fs::create_dir_all(wav_path.parent().unwrap())?;
            extract_audio(
                &state.settings.ffmpeg_path,
                &state.settings.ffprobe_path,
                &params.source_path,
                &wav_path.to_string_lossy(),
                params.audio_track,
                Some(tx.clone()),
            )
            .await?;
            let wp = wav_path.to_string_lossy().to_string();
            tokio::task::spawn_blocking(move || detect_volume_spikes_default(&wp))
                .await??
        };
        (segments, row.duration_seconds, spikes)
    } else {
        // 3. Extract audio
        let wav_path = temp_wav_path(&state, &params.source_path);
        std::fs::create_dir_all(wav_path.parent().unwrap())?;

        let _ = tx.send(ProgressEvent::Log {
            level: "info".into(),
            message: "Extracting audio...".into(),
        });
        extract_audio(
            &state.settings.ffmpeg_path,
            &state.settings.ffprobe_path,
            &params.source_path,
            &wav_path.to_string_lossy(),
            params.audio_track,
            Some(tx.clone()),
        )
        .await?;
        check_cancel(&mut cancel_rx)?;

        // 4. Spike detection
        let _ = tx.send(ProgressEvent::Log {
            level: "info".into(),
            message: "Detecting volume spikes...".into(),
        });
        let wp = wav_path.to_string_lossy().to_string();
        let spikes =
            tokio::task::spawn_blocking(move || detect_volume_spikes_default(&wp)).await??;
        let _ = tx.send(ProgressEvent::SpikeDetection {
            spike_count: spikes.len(),
        });
        check_cancel(&mut cancel_rx)?;

        // 5. Transcribe
        let _ = tx.send(ProgressEvent::Log {
            level: "info".into(),
            message: "Transcribing audio...".into(),
        });
        let segments = transcribe(
            &state.settings.whisper_cli_path,
            &state.settings.whisper_model_path,
            &wav_path.to_string_lossy(),
            &params.language,
            Some(tx.clone()),
        )
        .await?;
        check_cancel(&mut cancel_rx)?;

        // Get duration
        let duration =
            get_duration(&state.settings.ffprobe_path, &params.source_path).await?;

        // 6. Cache transcript
        let segments_json = serde_json::to_string(&segments)?;
        let row = TranscriptRow {
            id: String::new(),
            file_hash: file_hash.clone(),
            source_path: params.source_path.clone(),
            segments_json,
            duration_seconds: duration,
            whisper_model: state
                .settings
                .whisper_model_path
                .split(['/', '\\'])
                .last()
                .unwrap_or("unknown")
                .to_string(),
            language: params.language.clone(),
            created_at: String::new(),
        };
        db::save_transcript(&state.db, &row).await?;

        (segments, duration, spikes)
    };

    check_cancel(&mut cancel_rx)?;

    // 7. Chunk + annotate
    let _ = tx.send(ProgressEvent::Log {
        level: "info".into(),
        message: "Chunking transcript...".into(),
    });
    let mut chunks = chunk_transcript(&segments, params.window_minutes, params.overlap_minutes);
    annotate_chunks_with_spikes(&mut chunks, &spikes);
    let _ = tx.send(ProgressEvent::Chunking {
        chunk_count: chunks.len(),
    });
    check_cancel(&mut cancel_rx)?;

    // 8. Analyze via LLM
    let _ = tx.send(ProgressEvent::Log {
        level: "info".into(),
        message: format!("Analyzing {} chunks with {}...", chunks.len(), params.provider),
    });

    let api_key = resolve_api_key(&state, &params.provider, params.api_key.as_deref());
    let base_url = resolve_base_url(&state, &params.provider, params.base_url.as_deref());
    let provider_box =
        make_provider(&params.provider, &api_key, &base_url, state.http_client.clone())?;
    let provider_arc: Arc<dyn trik_klip_core::llm::LlmProvider> = Arc::from(provider_box);

    let custom_prompts_ref = params.custom_prompts.as_deref();

    let clips = find_clips(
        &chunks,
        provider_arc,
        &params.model,
        params.top_n,
        params.padding_seconds,
        duration,
        params.max_workers,
        custom_prompts_ref.map(|v| &v[..]),
        Some(tx),
    )
    .await;

    Ok(PipelineResult {
        clips,
        transcript_hash: file_hash,
        duration_seconds: duration,
    })
}

// ---------------------------------------------------------------------------
// Transcribe only
// ---------------------------------------------------------------------------

pub async fn run_transcribe_only(
    state: Arc<AppState>,
    params: PipelineParams,
) -> Result<TranscribeResult> {
    if state
        .pipeline_running
        .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
        .is_err()
    {
        anyhow::bail!("Pipeline is already running");
    }

    let result = run_transcribe_only_inner(state.clone(), params).await;

    state.pipeline_running.store(false, Ordering::SeqCst);
    let _ = state.cancel_tx.send(false);

    match &result {
        Ok(_) => {
            let _ = state.progress_tx.send(ProgressEvent::PipelineDone);
        }
        Err(e) => {
            let _ = state.progress_tx.send(ProgressEvent::PipelineError {
                message: e.to_string(),
            });
        }
    }

    result
}

async fn run_transcribe_only_inner(
    state: Arc<AppState>,
    params: PipelineParams,
) -> Result<TranscribeResult> {
    let mut cancel_rx = state.cancel_tx.subscribe();
    let tx = &state.progress_tx;

    let file_hash = hash_file(&params.source_path).await?;
    check_cancel(&mut cancel_rx)?;

    // Check cache
    if let Some(row) = db::get_transcript_by_hash(&state.db, &file_hash).await? {
        let segments: Vec<TranscriptSegment> = serde_json::from_str(&row.segments_json)?;
        let _ = tx.send(ProgressEvent::Log {
            level: "info".into(),
            message: "Transcript already cached.".into(),
        });
        return Ok(TranscribeResult {
            transcript_hash: file_hash,
            segments,
            duration_seconds: row.duration_seconds,
            spike_count: 0,
        });
    }

    // Extract audio
    let wav_path = temp_wav_path(&state, &params.source_path);
    std::fs::create_dir_all(wav_path.parent().unwrap())?;

    extract_audio(
        &state.settings.ffmpeg_path,
        &state.settings.ffprobe_path,
        &params.source_path,
        &wav_path.to_string_lossy(),
        params.audio_track,
        Some(tx.clone()),
    )
    .await?;
    check_cancel(&mut cancel_rx)?;

    // Spike detection
    let wp = wav_path.to_string_lossy().to_string();
    let spikes = tokio::task::spawn_blocking(move || detect_volume_spikes_default(&wp)).await??;
    let _ = tx.send(ProgressEvent::SpikeDetection {
        spike_count: spikes.len(),
    });
    check_cancel(&mut cancel_rx)?;

    // Transcribe
    let segments = transcribe(
        &state.settings.whisper_cli_path,
        &state.settings.whisper_model_path,
        &wav_path.to_string_lossy(),
        &params.language,
        Some(tx.clone()),
    )
    .await?;
    check_cancel(&mut cancel_rx)?;

    let duration = get_duration(&state.settings.ffprobe_path, &params.source_path).await?;

    // Cache
    let segments_json = serde_json::to_string(&segments)?;
    let row = TranscriptRow {
        id: String::new(),
        file_hash: file_hash.clone(),
        source_path: params.source_path.clone(),
        segments_json,
        duration_seconds: duration,
        whisper_model: state
            .settings
            .whisper_model_path
            .split(['/', '\\'])
            .last()
            .unwrap_or("unknown")
            .to_string(),
        language: params.language.clone(),
        created_at: String::new(),
    };
    db::save_transcript(&state.db, &row).await?;

    Ok(TranscribeResult {
        transcript_hash: file_hash,
        segments,
        duration_seconds: duration,
        spike_count: spikes.len(),
    })
}

// ---------------------------------------------------------------------------
// Analyze only (uses cached transcript)
// ---------------------------------------------------------------------------

pub async fn run_analyze_only(
    state: Arc<AppState>,
    params: AnalyzeOnlyParams,
) -> Result<PipelineResult> {
    if state
        .pipeline_running
        .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
        .is_err()
    {
        anyhow::bail!("Pipeline is already running");
    }

    let result = run_analyze_only_inner(state.clone(), params).await;

    state.pipeline_running.store(false, Ordering::SeqCst);
    let _ = state.cancel_tx.send(false);

    match &result {
        Ok(_) => {
            let _ = state.progress_tx.send(ProgressEvent::PipelineDone);
        }
        Err(e) => {
            let _ = state.progress_tx.send(ProgressEvent::PipelineError {
                message: e.to_string(),
            });
        }
    }

    result
}

async fn run_analyze_only_inner(
    state: Arc<AppState>,
    params: AnalyzeOnlyParams,
) -> Result<PipelineResult> {
    let mut cancel_rx = state.cancel_tx.subscribe();
    let tx = &state.progress_tx;

    // Load cached transcript
    let row = db::get_transcript_by_hash(&state.db, &params.transcript_hash)
        .await?
        .ok_or_else(|| anyhow::anyhow!("No cached transcript for hash: {}", params.transcript_hash))?;

    let segments: Vec<TranscriptSegment> = serde_json::from_str(&row.segments_json)?;
    let duration = row.duration_seconds;

    // Re-detect spikes if WAV available
    let wav_path = temp_wav_path(&state, &params.source_path);
    let spikes = if wav_path.exists() {
        let wp = wav_path.to_string_lossy().to_string();
        tokio::task::spawn_blocking(move || detect_volume_spikes_default(&wp)).await??
    } else {
        warn!("WAV not found for spike detection, skipping spike annotation");
        Vec::new()
    };
    check_cancel(&mut cancel_rx)?;

    // Chunk + annotate
    let mut chunks = chunk_transcript(&segments, params.window_minutes, params.overlap_minutes);
    annotate_chunks_with_spikes(&mut chunks, &spikes);
    let _ = tx.send(ProgressEvent::Chunking {
        chunk_count: chunks.len(),
    });
    check_cancel(&mut cancel_rx)?;

    // Analyze
    let api_key = resolve_api_key(&state, &params.provider, params.api_key.as_deref());
    let base_url = resolve_base_url(&state, &params.provider, params.base_url.as_deref());
    let provider_box =
        make_provider(&params.provider, &api_key, &base_url, state.http_client.clone())?;
    let provider_arc: Arc<dyn trik_klip_core::llm::LlmProvider> = Arc::from(provider_box);

    let custom_prompts_ref = params.custom_prompts.as_deref();

    let clips = find_clips(
        &chunks,
        provider_arc,
        &params.model,
        params.top_n,
        params.padding_seconds,
        duration,
        params.max_workers,
        custom_prompts_ref.map(|v| &v[..]),
        Some(tx),
    )
    .await;

    Ok(PipelineResult {
        clips,
        transcript_hash: params.transcript_hash,
        duration_seconds: duration,
    })
}

// ---------------------------------------------------------------------------
// Extract clips to MP4
// ---------------------------------------------------------------------------

pub async fn run_extract_clips(
    state: Arc<AppState>,
    params: ExtractParams,
) -> Result<ExtractResult> {
    if state
        .pipeline_running
        .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
        .is_err()
    {
        anyhow::bail!("Pipeline is already running");
    }

    let result = run_extract_clips_inner(state.clone(), params).await;

    state.pipeline_running.store(false, Ordering::SeqCst);
    let _ = state.cancel_tx.send(false);

    match &result {
        Ok(_) => {
            let _ = state.progress_tx.send(ProgressEvent::PipelineDone);
        }
        Err(e) => {
            let _ = state.progress_tx.send(ProgressEvent::PipelineError {
                message: e.to_string(),
            });
        }
    }

    result
}

async fn run_extract_clips_inner(
    state: Arc<AppState>,
    params: ExtractParams,
) -> Result<ExtractResult> {
    let mut cancel_rx = state.cancel_tx.subscribe();
    let tx = &state.progress_tx;
    let total = params.clips.len();

    std::fs::create_dir_all(&params.output_dir)?;

    let mut extracted = Vec::new();

    for (i, clip) in params.clips.iter().enumerate() {
        check_cancel(&mut cancel_rx)?;

        // Sanitize title for filename
        let safe_title: String = clip
            .title
            .chars()
            .map(|c| if c.is_alphanumeric() || c == ' ' || c == '-' || c == '_' { c } else { '_' })
            .collect();
        let safe_title = safe_title.trim().replace(' ', "_");
        let clip_filename = format!(
            "clip_{:02}_{}.mp4",
            clip.rank,
            if safe_title.len() > 40 {
                &safe_title[..40]
            } else {
                &safe_title
            }
        );
        let clip_path = Path::new(&params.output_dir).join(&clip_filename);

        let duration = clip.clip_end - clip.clip_start;

        extract_clip(
            &state.settings.ffmpeg_path,
            &params.source_path,
            &clip_path.to_string_lossy(),
            clip.clip_start,
            duration,
        )
        .await?;

        // Write sidecar JSON with clip metadata
        let sidecar_path = clip_path.with_extension("json");
        let sidecar = serde_json::to_string_pretty(clip)?;
        tokio::fs::write(&sidecar_path, sidecar).await?;

        let _ = tx.send(ProgressEvent::ClipExtraction {
            done: i + 1,
            total,
            clip_name: clip_filename.clone(),
        });

        extracted.push(ExtractedClipInfo {
            rank: clip.rank,
            title: clip.title.clone(),
            path: clip_path.to_string_lossy().into_owned(),
        });
    }

    Ok(ExtractResult { extracted })
}

// ---------------------------------------------------------------------------
// Generate editing slices for a clip
// ---------------------------------------------------------------------------

pub async fn run_generate_slices(
    state: Arc<AppState>,
    params: SliceParams,
) -> Result<SliceResult> {
    if state
        .pipeline_running
        .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
        .is_err()
    {
        anyhow::bail!("Pipeline is already running");
    }

    let result = run_generate_slices_inner(state.clone(), params).await;

    state.pipeline_running.store(false, Ordering::SeqCst);
    let _ = state.cancel_tx.send(false);

    match &result {
        Ok(_) => {
            let _ = state.progress_tx.send(ProgressEvent::PipelineDone);
        }
        Err(e) => {
            let _ = state.progress_tx.send(ProgressEvent::PipelineError {
                message: e.to_string(),
            });
        }
    }

    result
}

async fn run_generate_slices_inner(
    state: Arc<AppState>,
    params: SliceParams,
) -> Result<SliceResult> {
    let mut cancel_rx = state.cancel_tx.subscribe();
    let tx = &state.progress_tx;

    // Build the editing prompt
    let clip_segments: Vec<TranscriptSegment> = params
        .segments
        .iter()
        .filter(|s| s.start >= params.clip.clip_start && s.end <= params.clip.clip_end)
        .cloned()
        .collect();

    let editing_prompt = build_editing_prompt(&params.clip, &clip_segments);

    // Call LLM for editing plan
    let api_key = resolve_api_key(&state, &params.provider, params.api_key.as_deref());
    let base_url = resolve_base_url(&state, &params.provider, params.base_url.as_deref());
    let provider_box =
        make_provider(&params.provider, &api_key, &base_url, state.http_client.clone())?;

    let _ = tx.send(ProgressEvent::Log {
        level: "info".into(),
        message: "Generating editing plan...".into(),
    });

    let response = provider_box
        .message(
            &params.model,
            &editing_prompt,
            "You are an expert short-form video editor.",
            2000,
        )
        .await?;

    check_cancel(&mut cancel_rx)?;

    // Parse cut list from the response
    let cuts = parse_cut_list(&response.text);

    if cuts.is_empty() {
        anyhow::bail!("LLM returned no valid cut list entries");
    }

    // Get clip duration for clamping
    let clip_duration =
        get_duration(&state.settings.ffprobe_path, &params.clip_path).await?;

    // Extract each slice
    let clip_dir = Path::new(&params.clip_path)
        .parent()
        .unwrap_or_else(|| Path::new("."));
    let clip_stem = Path::new(&params.clip_path)
        .file_stem()
        .map(|s| s.to_string_lossy().into_owned())
        .unwrap_or_else(|| "clip".into());

    let slices_dir = clip_dir.join(format!("{}_slices", clip_stem));
    std::fs::create_dir_all(&slices_dir)?;

    let total = cuts.len();
    let mut slice_paths = Vec::new();

    for (i, cut) in cuts.iter().enumerate() {
        check_cancel(&mut cancel_rx)?;

        // Snap the end to sentence boundaries
        let snapped_end = snap_cut_end(cut.end, &clip_segments, 1.0, Some(params.clip.clip_end));

        // Convert source-file-relative timestamps to clip-relative
        let seek = (cut.start - params.clip.clip_start).max(0.0);
        let duration = (snapped_end - cut.start).min(clip_duration - seek).max(0.0);

        if duration < 1.0 {
            warn!("Skipping slice {} — duration too short ({:.1}s)", i + 1, duration);
            continue;
        }

        let slice_path = slices_dir.join(format!("slice_{:02}.mp4", i + 1));

        extract_slice(
            &state.settings.ffmpeg_path,
            &params.clip_path,
            &slice_path.to_string_lossy(),
            seek,
            duration,
        )
        .await?;

        let _ = tx.send(ProgressEvent::SliceGeneration {
            done: i + 1,
            total,
        });

        slice_paths.push(slice_path.to_string_lossy().into_owned());
    }

    // Write the editing plan as a sidecar
    let plan_path = slices_dir.join("editing_plan.txt");
    tokio::fs::write(&plan_path, &response.text).await?;

    Ok(SliceResult {
        slices: slice_paths,
    })
}
