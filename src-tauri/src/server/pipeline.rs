// Pipeline orchestrator — runs the full clip-finding pipeline as a background task.

use std::path::{Path, PathBuf};
use std::sync::atomic::Ordering;
use std::sync::Arc;

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use tokio::sync::watch;
use tracing::warn;

use trik_klip_core::chunking::{annotate_chunks_with_spikes, chunk_transcript};
use trik_klip_core::clip_scoring::find_clips;
use trik_klip_core::db;
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
    /// Whisper model name selected in the UI (e.g. "small", "large-v3-turbo").
    /// Resolved against shipped resources dir + data_dir/whisper_models/;
    /// downloaded from HuggingFace if missing. If unset, uses the configured
    /// default (usually the shipped base model).
    #[serde(default)]
    pub whisper_model: Option<String>,
    /// Absolute path to write the full transcript JSON to. The UI's
    /// "Save Transcript" field — matches the Python layout so users can reuse
    /// transcripts across runs. Parent dirs are created. Silently skipped
    /// when empty/absent.
    #[serde(default)]
    pub save_transcript_path: Option<String>,
    /// Absolute path to write the found clips JSON to. The UI's "Output JSON"
    /// field. Written only for Full Pipeline / Analyze Only (not Transcribe Only).
    #[serde(default)]
    pub output_json_path: Option<String>,
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
    /// Full transcript for the source, used to write per-clip transcript
    /// slices. Optional — if omitted, per-clip transcripts are skipped.
    #[serde(default)]
    pub segments: Vec<TranscriptSegment>,
    /// Audio track index to carry into each extracted clip. When unset,
    /// ffmpeg picks the default (first) audio stream — which is wrong for
    /// multi-track recordings where the user wants the mic track.
    #[serde(default)]
    pub audio_track: Option<u32>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct SliceParams {
    /// Parent directory containing per-clip subfolders (output of Extract).
    /// Each subfolder is expected to hold a `clip_NN_Title.mp4` + matching
    /// `clip_NN_Title.json` metadata, and optionally `_transcript.json`.
    /// As a fallback, if `clip_dir` itself contains a clip mp4 (not starting
    /// with `slice_`), it's treated as a single-clip folder.
    pub clip_dir: String,
    pub provider: String,
    pub model: String,
    #[serde(default)]
    pub api_key: Option<String>,
    #[serde(default)]
    pub base_url: Option<String>,
    #[serde(default)]
    pub editing_notes: Option<String>,
    #[serde(default)]
    pub premiere: bool,
    #[serde(default)]
    pub davinci: bool,
    #[serde(default)]
    pub auto_remove: bool,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct AnalyzeOnlyParams {
    #[serde(default)]
    pub source_path: String,
    #[serde(default)]
    pub output_dir: String,
    /// SHA-256 of the source file (used to look up a cached transcript in the
    /// DB). One of `transcript_hash` or `transcript_path` must be provided.
    #[serde(default)]
    pub transcript_hash: String,
    /// Path to a transcript JSON file on disk (Python-compatible format:
    /// `[{"start": number, "end": number, "text": string}, ...]`).
    #[serde(default)]
    pub transcript_path: Option<String>,
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
    /// Full transcript for the source — forwarded to the client in the
    /// ClipsReady SSE event so it can pass them back on Extract.
    #[serde(default)]
    pub segments: Vec<TranscriptSegment>,
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
    pub clips_processed: usize,
    pub total_slices: usize,
    pub per_clip: Vec<ClipSliceInfo>,
}

#[derive(Debug, Clone, Serialize)]
pub struct ClipSliceInfo {
    pub clip_dir: String,
    pub edit_plan_path: String,
    pub slice_paths: Vec<String>,
    pub error: Option<String>,
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

/// Resolve the whisper model path for a pipeline run.
///
/// If `selected` is None (or empty), returns the configured default
/// `whisper_model_path` (usually the shipped ggml-base.bin). Otherwise,
/// looks for `ggml-{selected}.bin` in the shipped resources dir first,
/// then in `<data_dir>/whisper_models/`. Downloads from HuggingFace into
/// the latter if missing, emitting WhisperDownload progress events.
async fn resolve_whisper_model(
    state: &Arc<AppState>,
    selected: Option<&str>,
    tx: &tokio::sync::broadcast::Sender<ProgressEvent>,
    cancel_rx: &watch::Receiver<bool>,
) -> Result<String> {
    let name = match selected {
        Some(s) if !s.trim().is_empty() => s.trim(),
        _ => {
            // No selection — use the configured default path verbatim.
            return Ok(state.settings.whisper_model_path.clone());
        }
    };

    let resources_dir = std::path::Path::new(&state.settings.resources_dir);
    let data_dir = std::path::Path::new(&state.settings.data_dir);

    let path = trik_klip_core::whisper_models::ensure_downloaded(
        resources_dir,
        data_dir,
        name,
        &state.http_client,
        Some(tx),
        Some(cancel_rx),
    )
    .await?;
    Ok(path.to_string_lossy().into_owned())
}

// ---------------------------------------------------------------------------
// Write a user-specified JSON sidecar (e.g. transcript JSON, clips JSON).
// Creates the parent dir, pretty-prints the value, and emits a log event on
// either success or failure — failures don't abort the pipeline since the
// primary output (DB cache / extracted clips) is already persisted elsewhere.
// ---------------------------------------------------------------------------

async fn write_sidecar_json<T: serde::Serialize>(
    path: Option<&str>,
    value: &T,
    label: &str,
    tx: &tokio::sync::broadcast::Sender<ProgressEvent>,
) {
    let Some(path) = path.filter(|s| !s.is_empty()) else {
        return;
    };
    let result: Result<()> = async {
        if let Some(parent) = std::path::Path::new(path).parent() {
            tokio::fs::create_dir_all(parent)
                .await
                .with_context(|| format!("create dir for {}", path))?;
        }
        let body = serde_json::to_string_pretty(value)?;
        tokio::fs::write(path, body)
            .await
            .with_context(|| format!("write {}", path))?;
        Ok(())
    }
    .await;

    match result {
        Ok(_) => {
            let _ = tx.send(ProgressEvent::Log {
                level: "info".into(),
                message: format!("Saved {} to {}", label, path),
            });
        }
        Err(e) => {
            warn!(path, error = %e, "Failed to write {}", label);
            let _ = tx.send(ProgressEvent::Log {
                level: "warn".into(),
                message: format!("Failed to save {} to {}: {}", label, path, e),
            });
        }
    }
}

/// Resolve the bundled Silero VAD model path, returning None if the file
/// is missing (e.g. on a pre-VAD install that updated in place). whisper-cli
/// then runs without VAD — still works, just back to the old hallucination
/// behavior on long silent stretches.
fn resolve_vad_model(state: &Arc<AppState>) -> Option<String> {
    let p = std::path::Path::new(&state.settings.resources_dir)
        .join("ggml-silero-v5.1.2.bin");
    if p.exists() {
        Some(p.to_string_lossy().into_owned())
    } else {
        None
    }
}

/// Copy the WAV that whisper actually transcribed into the user's output
/// folder (next to their transcript JSON), named after the source video.
/// Lets the user listen back when a transcript looks suspicious — a common
/// root cause is picking the wrong audio_track index, and the telltale
/// whisper hallucination (`"Thank you. Thank you. Thank you."` loop) is
/// hard to diagnose without the raw audio to compare against.
async fn copy_audio_sidecar(
    wav_path: &str,
    save_transcript_path: Option<&str>,
    source_path: &str,
    tx: &tokio::sync::broadcast::Sender<ProgressEvent>,
) {
    let Some(transcript_path) = save_transcript_path.filter(|s| !s.is_empty()) else {
        return;
    };
    let Some(parent) = std::path::Path::new(transcript_path).parent() else {
        return;
    };
    let stem = std::path::Path::new(source_path)
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("audio");
    let dest = parent.join(format!("{}_audio.wav", stem));

    if let Err(e) = tokio::fs::create_dir_all(parent).await {
        warn!(path = %parent.display(), error = %e, "Could not create audio sidecar parent");
        return;
    }

    match tokio::fs::copy(wav_path, &dest).await {
        Ok(bytes) => {
            let _ = tx.send(ProgressEvent::Log {
                level: "info".into(),
                message: format!(
                    "Saved audio to {} ({} MB)",
                    dest.display(),
                    bytes / (1024 * 1024)
                ),
            });
        }
        Err(e) => {
            warn!(path = %dest.display(), error = %e, "Failed to copy audio sidecar");
            let _ = tx.send(ProgressEvent::Log {
                level: "warn".into(),
                message: format!("Failed to save audio to {}: {}", dest.display(), e),
            });
        }
    }
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

    // Clear any stale cancel signal from a prior run.
    let _ = state.cancel_tx.send(false);

    let result = run_full_pipeline_inner(state.clone(), params).await;

    // Always reset running flag
    state.pipeline_running.store(false, Ordering::SeqCst);
    // Reset cancel signal
    let _ = state.cancel_tx.send(false);

    match &result {
        Ok(pipe_result) => {
            let _ = state.progress_tx.send(ProgressEvent::ClipsReady {
                clips: pipe_result.clips.clone(),
                segments: pipe_result.segments.clone(),
            });
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

    // Extract audio
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
        Some(cancel_rx.clone()),
    )
    .await?;
    check_cancel(&mut cancel_rx)?;

    // Spike detection
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

    // Transcribe
    let _ = tx.send(ProgressEvent::Log {
        level: "info".into(),
        message: "Transcribing audio...".into(),
    });
    let model_path = resolve_whisper_model(
        &state,
        params.whisper_model.as_deref(),
        tx,
        &cancel_rx,
    )
    .await?;
    let vad_model = resolve_vad_model(&state);
    let segments = transcribe(
        &state.settings.whisper_cli_path,
        &model_path,
        &wav_path.to_string_lossy(),
        &params.language,
        vad_model.as_deref(),
        Some(tx.clone()),
        Some(cancel_rx.clone()),
    )
    .await?;
    check_cancel(&mut cancel_rx)?;

    // Get duration
    let duration = get_duration(&state.settings.ffprobe_path, &params.source_path).await?;

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
        make_provider(&params.provider, &api_key, &base_url, state.http_client.clone(), Some(cancel_rx.clone()))?;
    let provider_arc: Arc<dyn trik_klip_core::llm::LlmProvider> = Arc::from(provider_box);

    let custom_prompts_ref = params.custom_prompts.as_deref();

    // Save the transcript to the user-specified path before analysis — so
    // even if the LLM step dies, the transcript is on disk.
    write_sidecar_json(
        params.save_transcript_path.as_deref(),
        &segments,
        "transcript",
        tx,
    )
    .await;

    // Drop the raw WAV next to the transcript for offline verification.
    let wav_path_str = temp_wav_path(&state, &params.source_path)
        .to_string_lossy()
        .into_owned();
    copy_audio_sidecar(
        &wav_path_str,
        params.save_transcript_path.as_deref(),
        &params.source_path,
        tx,
    )
    .await;

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

    write_sidecar_json(
        params.output_json_path.as_deref(),
        &clips,
        "clips JSON",
        tx,
    )
    .await;

    // The audio sidecar exists only for verifying whisper's output against
    // the chosen audio track. Once the extraction list (clips JSON) is on
    // disk the pipeline has everything it needs and the ~900 MB WAV is
    // dead weight — delete it here AND the temp working copy.
    cleanup_audio_artifacts(
        &temp_wav_path(&state, &params.source_path),
        params.save_transcript_path.as_deref(),
        &params.source_path,
        tx,
    )
    .await;

    Ok(PipelineResult {
        clips,
        transcript_hash: String::new(),
        duration_seconds: duration,
        segments,
    })
}

/// Remove the sidecar WAV (next to the transcript JSON) and the temp WAV
/// (in AppData). Silent on "file didn't exist"; warns on real errors.
/// Called at the end of Full Pipeline once the clips JSON is written.
async fn cleanup_audio_artifacts(
    temp_wav: &std::path::Path,
    save_transcript_path: Option<&str>,
    source_path: &str,
    tx: &tokio::sync::broadcast::Sender<ProgressEvent>,
) {
    // Temp WAV in AppData.
    if temp_wav.is_file() {
        match tokio::fs::remove_file(temp_wav).await {
            Ok(_) => {}
            Err(e) => warn!(path = %temp_wav.display(), error = %e, "Could not delete temp WAV"),
        }
    }

    // Sidecar WAV next to the transcript — built with the same derivation
    // that copy_audio_sidecar used, so we know where to look.
    let Some(transcript_path) = save_transcript_path.filter(|s| !s.is_empty()) else {
        return;
    };
    let Some(parent) = std::path::Path::new(transcript_path).parent() else {
        return;
    };
    let stem = std::path::Path::new(source_path)
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("audio");
    let sidecar = parent.join(format!("{}_audio.wav", stem));

    if sidecar.is_file() {
        match tokio::fs::remove_file(&sidecar).await {
            Ok(_) => {
                let _ = tx.send(ProgressEvent::Log {
                    level: "info".into(),
                    message: format!("Cleaned up audio WAV at {}", sidecar.display()),
                });
            }
            Err(e) => {
                warn!(path = %sidecar.display(), error = %e, "Could not delete audio sidecar");
                let _ = tx.send(ProgressEvent::Log {
                    level: "warn".into(),
                    message: format!("Failed to clean up {}: {}", sidecar.display(), e),
                });
            }
        }
    }
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

    // Clear any stale cancel signal from a prior run.
    let _ = state.cancel_tx.send(false);

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
        Some(cancel_rx.clone()),
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
    let model_path = resolve_whisper_model(
        &state,
        params.whisper_model.as_deref(),
        tx,
        &cancel_rx,
    )
    .await?;
    let vad_model = resolve_vad_model(&state);
    let segments = transcribe(
        &state.settings.whisper_cli_path,
        &model_path,
        &wav_path.to_string_lossy(),
        &params.language,
        vad_model.as_deref(),
        Some(tx.clone()),
        Some(cancel_rx.clone()),
    )
    .await?;
    check_cancel(&mut cancel_rx)?;

    let duration = get_duration(&state.settings.ffprobe_path, &params.source_path).await?;

    write_sidecar_json(
        params.save_transcript_path.as_deref(),
        &segments,
        "transcript",
        tx,
    )
    .await;

    copy_audio_sidecar(
        &wav_path.to_string_lossy(),
        params.save_transcript_path.as_deref(),
        &params.source_path,
        tx,
    )
    .await;

    Ok(TranscribeResult {
        transcript_hash: String::new(),
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

    // Clear any stale cancel signal from a prior run.
    let _ = state.cancel_tx.send(false);

    let result = run_analyze_only_inner(state.clone(), params).await;

    state.pipeline_running.store(false, Ordering::SeqCst);
    let _ = state.cancel_tx.send(false);

    match &result {
        Ok(pipe_result) => {
            let _ = state.progress_tx.send(ProgressEvent::ClipsReady {
                clips: pipe_result.clips.clone(),
                segments: pipe_result.segments.clone(),
            });
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

    // Load transcript. Prefer an explicit file path (Python-compatible JSON);
    // fall back to a DB lookup by hash.
    let (segments, duration, source_hash) = if let Some(path) = params
        .transcript_path
        .as_ref()
        .filter(|p| !p.is_empty())
    {
        let _ = tx.send(ProgressEvent::Log {
            level: "info".into(),
            message: format!("Loading transcript from file: {}", path),
        });
        let bytes = tokio::fs::read(path)
            .await
            .with_context(|| format!("Failed to read transcript file: {}", path))?;
        let segs: Vec<TranscriptSegment> = serde_json::from_slice(&bytes)
            .with_context(|| format!("Transcript JSON did not match expected schema at {}", path))?;
        if segs.is_empty() {
            anyhow::bail!("Transcript file contained no segments: {}", path);
        }
        // Duration = end of last segment (no source media to probe).
        let dur = segs
            .iter()
            .map(|s| s.end)
            .fold(0.0_f64, f64::max);
        (segs, dur, params.transcript_hash.clone())
    } else if !params.transcript_hash.is_empty() {
        let row = db::get_transcript_by_hash(&state.db, &params.transcript_hash)
            .await?
            .ok_or_else(|| {
                anyhow::anyhow!(
                    "No cached transcript for hash: {}",
                    params.transcript_hash
                )
            })?;
        let segs: Vec<TranscriptSegment> = serde_json::from_str(&row.segments_json)?;
        (segs, row.duration_seconds, row.file_hash)
    } else {
        anyhow::bail!(
            "Analyze Only requires either `transcript_path` or `transcript_hash`"
        );
    };

    // Re-detect spikes if WAV available (only when we have a source path).
    let spikes = if params.source_path.is_empty() {
        Vec::new()
    } else {
        let wav_path = temp_wav_path(&state, &params.source_path);
        if wav_path.exists() {
            let wp = wav_path.to_string_lossy().to_string();
            tokio::task::spawn_blocking(move || detect_volume_spikes_default(&wp)).await??
        } else {
            warn!("WAV not found for spike detection, skipping spike annotation");
            Vec::new()
        }
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
        make_provider(&params.provider, &api_key, &base_url, state.http_client.clone(), Some(cancel_rx.clone()))?;
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
        transcript_hash: source_hash,
        duration_seconds: duration,
        segments,
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

    // Clear any stale cancel signal from a prior run.
    let _ = state.cancel_tx.send(false);

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

    // Per-clip transcript slices are written when the client provides the
    // full transcript via `segments`. We do NOT hash the source file here —
    // hashing multi-GB videos takes minutes and would block extraction for
    // no good reason.
    let all_segments: Option<&Vec<TranscriptSegment>> = if params.segments.is_empty() {
        None
    } else {
        Some(&params.segments)
    };

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
        let truncated_title = if safe_title.len() > 40 {
            &safe_title[..40]
        } else {
            &safe_title
        };
        let clip_name = format!("clip_{:02}_{}", clip.rank, truncated_title);

        // Each clip goes in its own subfolder (matches Python layout):
        //   <output_dir>/clip_NN_Title/
        //     clip_NN_Title.mp4
        //     clip_NN_Title.json         — metadata
        //     clip_NN_Title_transcript.json  — transcript slice (if available)
        let clip_dir = Path::new(&params.output_dir).join(&clip_name);
        std::fs::create_dir_all(&clip_dir)?;

        let clip_filename = format!("{}.mp4", clip_name);
        let clip_path = clip_dir.join(&clip_filename);

        let duration = clip.clip_end - clip.clip_start;

        extract_clip(
            &state.settings.ffmpeg_path,
            &params.source_path,
            &clip_path.to_string_lossy(),
            clip.clip_start,
            duration,
            params.audio_track,
            Some(cancel_rx.clone()),
        )
        .await?;

        // Metadata sidecar
        let meta_path = clip_dir.join(format!("{}.json", clip_name));
        let meta_json = serde_json::to_string_pretty(clip)?;
        tokio::fs::write(&meta_path, meta_json).await?;

        // Per-clip transcript slice (if we have the full transcript handy)
        if let Some(segments) = all_segments {
            let clip_segs: Vec<&TranscriptSegment> = segments
                .iter()
                .filter(|s| s.start >= clip.clip_start && s.end <= clip.clip_end)
                .collect();
            if !clip_segs.is_empty() {
                let transcript_path =
                    clip_dir.join(format!("{}_transcript.json", clip_name));
                let transcript_json = serde_json::to_string_pretty(&clip_segs)?;
                tokio::fs::write(&transcript_path, transcript_json).await?;
            }
        }

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

    // Clear any stale cancel signal from a prior run.
    let _ = state.cancel_tx.send(false);

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

    let root = Path::new(&params.clip_dir);
    if !root.is_dir() {
        anyhow::bail!("clip_dir is not a directory: {}", params.clip_dir);
    }

    // Discover per-clip folders. We first check subdirectories; if none
    // contain a clip mp4, treat the root itself as a single clip folder.
    let mut clip_folders: Vec<PathBuf> = Vec::new();
    for entry in std::fs::read_dir(root)? {
        let Ok(entry) = entry else { continue; };
        let p = entry.path();
        if p.is_dir() && folder_has_clip_mp4(&p) {
            clip_folders.push(p);
        }
    }
    clip_folders.sort();

    if clip_folders.is_empty() && folder_has_clip_mp4(root) {
        clip_folders.push(root.to_path_buf());
    }

    if clip_folders.is_empty() {
        anyhow::bail!("No clip folders found in: {}", params.clip_dir);
    }

    let api_key = resolve_api_key(&state, &params.provider, params.api_key.as_deref());
    let base_url = resolve_base_url(&state, &params.provider, params.base_url.as_deref());
    let provider_box = make_provider(
        &params.provider,
        &api_key,
        &base_url,
        state.http_client.clone(),
        Some(cancel_rx.clone()),
    )?;

    let editing_notes = params
        .editing_notes
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty());

    let total_clips = clip_folders.len();
    let mut per_clip_results: Vec<ClipSliceInfo> = Vec::new();
    let mut total_slices = 0usize;

    for (clip_idx, clip_dir) in clip_folders.iter().enumerate() {
        check_cancel(&mut cancel_rx)?;

        let folder_name = clip_dir
            .file_name()
            .and_then(|s| s.to_str())
            .unwrap_or("clip")
            .to_string();

        let _ = tx.send(ProgressEvent::Log {
            level: "info".into(),
            message: format!(
                "[{}/{}] Generating slices for {}",
                clip_idx + 1,
                total_clips,
                folder_name
            ),
        });

        match process_single_clip_dir(
            clip_dir,
            provider_box.as_ref(),
            &params.model,
            editing_notes,
            params.premiere,
            &state.settings.ffmpeg_path,
            &state.http_client,
            &mut cancel_rx,
            tx,
            &mut total_slices,
        )
        .await
        {
            Ok(info) => per_clip_results.push(info),
            Err(e) => {
                warn!("Slice generation failed for {}: {}", clip_dir.display(), e);
                let _ = tx.send(ProgressEvent::Log {
                    level: "warn".into(),
                    message: format!("Skipping {}: {}", folder_name, e),
                });
                per_clip_results.push(ClipSliceInfo {
                    clip_dir: clip_dir.to_string_lossy().into_owned(),
                    edit_plan_path: String::new(),
                    slice_paths: Vec::new(),
                    error: Some(e.to_string()),
                });
            }
        }
    }

    Ok(SliceResult {
        clips_processed: total_clips,
        total_slices,
        per_clip: per_clip_results,
    })
}

/// Returns true if `folder` directly contains a `.mp4` whose name doesn't
/// start with `slice_` (i.e., it looks like an extracted clip).
fn folder_has_clip_mp4(folder: &Path) -> bool {
    let Ok(entries) = std::fs::read_dir(folder) else {
        return false;
    };
    for entry in entries.flatten() {
        let p = entry.path();
        if !p.is_file() {
            continue;
        }
        let ext_mp4 = p.extension().and_then(|s| s.to_str()) == Some("mp4");
        let stem = p.file_stem().and_then(|s| s.to_str()).unwrap_or("");
        if ext_mp4 && !stem.starts_with("slice_") {
            return true;
        }
    }
    false
}

#[allow(clippy::too_many_arguments)]
async fn process_single_clip_dir(
    clip_dir: &Path,
    provider: &dyn trik_klip_core::llm::LlmProvider,
    model: &str,
    editing_notes: Option<&str>,
    premiere: bool,
    ffmpeg_path: &str,
    http_client: &reqwest::Client,
    cancel_rx: &mut watch::Receiver<bool>,
    tx: &tokio::sync::broadcast::Sender<ProgressEvent>,
    total_slices_counter: &mut usize,
) -> Result<ClipSliceInfo> {
    // Locate the clip mp4, metadata json, transcript json, and a possible
    // Python-written editing-prompt text file inside this folder.
    let mut clip_mp4: Option<PathBuf> = None;
    let mut meta_json: Option<PathBuf> = None;
    let mut transcript_json: Option<PathBuf> = None;
    let mut editing_prompt_txt: Option<PathBuf> = None;

    for entry in std::fs::read_dir(clip_dir)? {
        let Ok(entry) = entry else { continue; };
        let p = entry.path();
        if !p.is_file() {
            continue;
        }
        let stem = p.file_stem().and_then(|s| s.to_str()).unwrap_or("");
        let ext = p.extension().and_then(|s| s.to_str()).unwrap_or("");
        match ext {
            "mp4" if !stem.starts_with("slice_") => clip_mp4 = Some(p),
            "json" if stem.ends_with("_transcript") => transcript_json = Some(p),
            "json" => {
                if meta_json.is_none() {
                    meta_json = Some(p);
                }
            }
            "txt" if stem.ends_with("_editing_prompt") => editing_prompt_txt = Some(p),
            _ => {}
        }
    }

    let clip_mp4 = clip_mp4.ok_or_else(|| anyhow::anyhow!("No clip .mp4 found in folder"))?;

    // Load transcript segments (optional — used for sentence-boundary snapping)
    let segments: Vec<TranscriptSegment> = if let Some(tp) = &transcript_json {
        match tokio::fs::read(tp).await {
            Ok(bytes) => serde_json::from_slice(&bytes).unwrap_or_default(),
            Err(_) => Vec::new(),
        }
    } else {
        Vec::new()
    };

    // Resolve the (clip, editing_prompt) pair using one of three paths:
    // 1. Rust-native: read `<clip>.json` → ClipSuggestion, then regenerate
    //    the prompt with `build_editing_prompt`.
    // 2. Python-compat: no metadata json but a `*_editing_prompt.txt` exists
    //    → use that prompt verbatim and reconstruct a minimal ClipSuggestion
    //    from its "Source range" header.
    // 3. Neither: bail with a clear error.
    let (clip, mut editing_prompt): (ClipSuggestion, String) = if let Some(mp) = &meta_json {
        let bytes = tokio::fs::read(mp).await?;
        let parsed: ClipSuggestion = serde_json::from_slice(&bytes)
            .with_context(|| format!("Failed to parse clip metadata: {}", mp.display()))?;
        let prompt = build_editing_prompt(&parsed, &segments);
        (parsed, prompt)
    } else if let Some(tp) = &editing_prompt_txt {
        let prompt = tokio::fs::read_to_string(tp)
            .await
            .with_context(|| format!("Failed to read {}", tp.display()))?;
        let suggestion = reconstruct_clip_suggestion_from_prompt(&prompt, clip_mp4.as_path());
        (suggestion, prompt)
    } else {
        anyhow::bail!(
            "No clip metadata found. Expected either a <clip>.json or <clip>_editing_prompt.txt \
             alongside the clip MP4 (run Extract first)."
        );
    };
    if let Some(notes) = editing_notes {
        editing_prompt.push_str(
            "\n\n\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\n\
             ADDITIONAL EDITING NOTES FROM THE USER\n\
             \u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\u{2501}\n\
             Follow these instructions alongside the standard rules above:\n\n",
        );
        editing_prompt.push_str(notes);
        editing_prompt.push('\n');
    }

    // Call the LLM for the editing plan.
    let response = provider
        .message(
            model,
            &editing_prompt,
            "You are an expert short-form video editor.",
            4096,
        )
        .await?;

    check_cancel(cancel_rx)?;

    // Save the edit plan next to the clip.
    let clip_stem = clip_mp4
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("clip")
        .to_string();
    let plan_path = clip_dir.join(format!("{}_edit_plan.txt", clip_stem));
    tokio::fs::write(&plan_path, &response.text).await?;

    // Parse the cut list.
    let cuts = parse_cut_list(&response.text);
    if cuts.is_empty() {
        let folder = clip_dir
            .file_name()
            .and_then(|s| s.to_str())
            .unwrap_or("clip");
        let msg = format!(
            "No slices for {}: LLM response didn't match the expected \
             CUT LIST format. Edit plan saved at {} — re-run Slice to retry.",
            folder,
            plan_path.display()
        );
        warn!("{}", msg);
        let _ = tx.send(ProgressEvent::Log {
            level: "warn".into(),
            message: msg,
        });
        return Ok(ClipSliceInfo {
            clip_dir: clip_dir.to_string_lossy().into_owned(),
            edit_plan_path: plan_path.to_string_lossy().into_owned(),
            slice_paths: Vec::new(),
            error: Some("LLM returned no parseable cuts".into()),
        });
    }

    // Clean up old slice_*.mp4 files so we don't mix old and new results.
    if let Ok(entries) = std::fs::read_dir(clip_dir) {
        for entry in entries.flatten() {
            let p = entry.path();
            let stem = p.file_stem().and_then(|s| s.to_str()).unwrap_or("");
            let ext_mp4 = p.extension().and_then(|s| s.to_str()) == Some("mp4");
            if ext_mp4 && stem.starts_with("slice_") {
                let _ = std::fs::remove_file(&p);
            }
        }
    }

    // Get clip duration for clamping.
    let clip_duration = clip.clip_end - clip.clip_start;

    let mut slice_paths: Vec<String> = Vec::new();
    let total_cuts = cuts.len();

    // Emit a 0/N event so the UI bar can size itself immediately.
    let _ = tx.send(ProgressEvent::SliceGeneration {
        done: 0,
        total: total_cuts,
    });

    for (i, cut) in cuts.iter().enumerate() {
        check_cancel(cancel_rx)?;

        // Snap end to sentence boundary using the transcript segments.
        let snapped_end = snap_cut_end(cut.end, &segments, 2.0, Some(clip.clip_end));

        // Source-file timestamps → clip-file relative timestamps.
        let seek = (cut.start - clip.clip_start).max(0.0);
        let duration = (snapped_end - cut.start).min(clip_duration - seek).max(0.0);

        if duration < 1.0 {
            warn!(
                "Skipping slice {} in {} — duration too short ({:.1}s)",
                i + 1,
                clip_dir.display(),
                duration
            );
            let _ = tx.send(ProgressEvent::SliceGeneration {
                done: i + 1,
                total: total_cuts,
            });
            continue;
        }

        let slice_path = clip_dir.join(format!("slice_{:02}.mp4", i + 1));

        extract_slice(
            ffmpeg_path,
            &clip_mp4.to_string_lossy(),
            &slice_path.to_string_lossy(),
            seek,
            duration,
            Some(cancel_rx.clone()),
        )
        .await?;

        slice_paths.push(slice_path.to_string_lossy().into_owned());
        *total_slices_counter += 1;

        let _ = tx.send(ProgressEvent::SliceGeneration {
            done: i + 1,
            total: total_cuts,
        });
    }

    // Visual aid image fetch — ask the LLM for per-slice search queries,
    // scrape Bing, download + re-encode as clean JPEGs named
    // `visual_NN.jpg` next to the slices. Non-fatal on failure.
    let _ = tx.send(ProgressEvent::Log {
        level: "info".into(),
        message: format!(
            "Fetching visual aids for {}…",
            clip_dir
                .file_name()
                .and_then(|s| s.to_str())
                .unwrap_or("clip")
        ),
    });
    match trik_klip_core::visuals::generate_visual_aids(
        clip_dir,
        &cuts,
        provider,
        model,
        http_client,
        Some(&*cancel_rx),
        Some(tx),
    )
    .await
    {
        Ok(n) => {
            let _ = tx.send(ProgressEvent::Log {
                level: "info".into(),
                message: format!("Visual aids: {} image(s) saved", n),
            });
        }
        Err(e) => {
            let _ = tx.send(ProgressEvent::Log {
                level: "warn".into(),
                message: format!("Visual aid step failed (non-fatal): {}", e),
            });
        }
    }

    // Optional Premiere setup prompt (matches Python's output).
    if premiere {
        let folder_name = clip_dir
            .file_name()
            .and_then(|s| s.to_str())
            .unwrap_or("clip");
        let seq_name = format!("{}_Shorts", folder_name);
        let premiere_prompt = format!(
            "# Premiere Pro Setup\n\n\
             1. Import all files from: {}\n\
             2. Create sequence named: {}\n\
             3. Place slices in order on timeline\n",
            clip_dir.to_string_lossy().replace('\\', "/"),
            seq_name,
        );
        let _ = tokio::fs::write(clip_dir.join("premiere_setup_prompt.md"), premiere_prompt).await;
    }

    Ok(ClipSliceInfo {
        clip_dir: clip_dir.to_string_lossy().into_owned(),
        edit_plan_path: plan_path.to_string_lossy().into_owned(),
        slice_paths,
        error: None,
    })
}

/// For clip folders written by the Python version (which emits a
/// `*_editing_prompt.txt` instead of a JSON metadata sidecar), reconstruct
/// a minimal `ClipSuggestion` by parsing the prompt header.
///
/// The prompt has a line like:  Source range:  00:12:34 → 00:15:00
/// We extract the two timestamps into `clip_start` / `clip_end`. Title,
/// content_type, etc. come from the folder name so the per-clip edit plan
/// and slice files are still labeled sensibly.
fn reconstruct_clip_suggestion_from_prompt(prompt: &str, clip_mp4: &Path) -> ClipSuggestion {
    let (clip_start, clip_end) = parse_source_range(prompt).unwrap_or((0.0, 0.0));

    let title = clip_mp4
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("Clip")
        .to_string();

    // Best-effort: pull the "Title:" line if the Python prompt has one.
    let better_title = extract_prompt_field(prompt, "Title:").unwrap_or_else(|| title.clone());
    let content_type = extract_prompt_field(prompt, "Content type:")
        .unwrap_or_else(|| "other".into());
    let hook = extract_prompt_field(prompt, "Auto-detected hook note:")
        .unwrap_or_default();

    ClipSuggestion {
        rank: 0,
        title: better_title,
        hook,
        segment_start: clip_start,
        segment_end: clip_end,
        clip_start,
        clip_end,
        clip_duration: (clip_end - clip_start).max(0.0),
        content_type,
        virality_score: 0,
        transcript_excerpt: String::new(),
    }
}

/// Parse "Source range:  HH:MM:SS → HH:MM:SS" out of a prompt body.
/// Accepts "→", "->", "-", "–", "—" as the separator.
fn parse_source_range(prompt: &str) -> Option<(f64, f64)> {
    for line in prompt.lines() {
        let trimmed = line.trim();
        if let Some(rest) = trimmed.strip_prefix("Source range:") {
            // Replace common separators with a single ASCII one so splitting
            // is predictable regardless of what character the writer used.
            let normalised = rest
                .replace('\u{2192}', " ")  // →
                .replace('\u{2013}', " ")  // –
                .replace('\u{2014}', " ")  // —
                .replace("->", " ");
            let parts: Vec<&str> = normalised.split_whitespace().collect();
            if parts.len() >= 2 {
                if let (Ok(a), Ok(b)) = (parse_time(parts[0]), parse_time(parts[1])) {
                    return Some((a, b));
                }
            }
        }
    }
    None
}

/// Pull a single-line value that follows a prefix like "Title:" on its own
/// line or inline. Returns the trimmed value, or None if the field isn't
/// present (or is empty).
fn extract_prompt_field(prompt: &str, prefix: &str) -> Option<String> {
    for line in prompt.lines() {
        let trimmed = line.trim();
        if let Some(rest) = trimmed.strip_prefix(prefix) {
            let value = rest.trim().trim_start_matches('|').trim();
            if !value.is_empty() {
                return Some(value.to_string());
            }
        }
    }
    None
}
