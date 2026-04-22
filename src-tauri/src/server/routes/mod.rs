use std::convert::Infallible;
use std::sync::atomic::Ordering;
use std::sync::Arc;

use axum::extract::{Path, State};
use axum::http::StatusCode;
use axum::response::sse::{Event, Sse};
use axum::response::IntoResponse;
use axum::routing::{get, post, put};
use axum::{Json, Router};
use chrono::Utc;
use futures_core::Stream;
use serde::{Deserialize, Serialize};
use serde_json::json;
use tokio_stream::wrappers::BroadcastStream;
use tokio_stream::StreamExt;

use trik_klip_core::db::{self, models::ProviderProfileRow};
use trik_klip_core::licensing;
use trik_klip_core::llm::provider_registry::{
    self, fetch_anthropic_models, fetch_gemini_models, fetch_grok_models, fetch_openai_models,
    list_ollama_models,
};
use crate::server::error::AppError;
use crate::server::pipeline::{
    self, AnalyzeOnlyParams, ExtractParams, PipelineParams, SliceParams,
};
use crate::server::AppState;

// ---------------------------------------------------------------------------
// Router
// ---------------------------------------------------------------------------

pub fn build_routes() -> Router<Arc<AppState>> {
    Router::new()
        .route("/api/health", get(health_check))
        // Pipeline
        .route("/api/pipeline/run", post(pipeline_run))
        .route("/api/pipeline/transcribe", post(pipeline_transcribe))
        .route("/api/pipeline/analyze", post(pipeline_analyze))
        .route("/api/pipeline/extract", post(pipeline_extract))
        .route("/api/pipeline/slices", post(pipeline_slices))
        .route("/api/slices/clips", get(list_clip_folders))
        .route("/api/slices/premiere-prompt", post(write_premiere_prompt))
        .route(
            "/api/settings/premiere",
            get(get_premiere_settings).put(put_premiere_settings),
        )
        .route("/api/pipeline/cancel", post(pipeline_cancel))
        .route("/api/pipeline/status", get(pipeline_status))
        .route("/api/pipeline/progress", get(pipeline_progress_sse))
        // Providers
        .route("/api/providers", get(list_providers_handler))
        .route("/api/providers/{name}/models", get(provider_models))
        .route("/api/providers/test", post(test_provider))
        // Profiles
        .route("/api/profiles", get(list_profiles).post(create_profile))
        .route(
            "/api/profiles/{id}",
            put(update_profile).delete(delete_profile),
        )
        // License
        .route("/api/license/verify", post(verify_license_handler))
        .route("/api/license/verify-saved", post(verify_saved_license_handler))
        .route("/api/license/status", get(license_status))
        // Transcripts
        .route("/api/transcripts", get(list_transcripts))
}

// ---------------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------------

async fn health_check() -> Json<serde_json::Value> {
    Json(json!({
        "status": "ok",
        "timestamp": Utc::now().to_rfc3339(),
        "version": "1.1.0"
    }))
}

// ---------------------------------------------------------------------------
// Pipeline routes
// ---------------------------------------------------------------------------

async fn pipeline_run(
    State(state): State<Arc<AppState>>,
    Json(params): Json<PipelineParams>,
) -> Result<impl IntoResponse, AppError> {
    if state.pipeline_running.load(Ordering::SeqCst) {
        return Err(AppError::Conflict("Pipeline is already running".into()));
    }

    let s = state.clone();
    tokio::spawn(async move {
        if let Err(e) = pipeline::run_full_pipeline(s, params).await {
            tracing::error!("Pipeline failed: {:?}", e);
        }
    });

    Ok((StatusCode::ACCEPTED, Json(json!({"status": "started"}))))
}

async fn pipeline_transcribe(
    State(state): State<Arc<AppState>>,
    Json(params): Json<PipelineParams>,
) -> Result<impl IntoResponse, AppError> {
    if state.pipeline_running.load(Ordering::SeqCst) {
        return Err(AppError::Conflict("Pipeline is already running".into()));
    }

    let s = state.clone();
    tokio::spawn(async move {
        if let Err(e) = pipeline::run_transcribe_only(s, params).await {
            tracing::error!("Transcribe pipeline failed: {:?}", e);
        }
    });

    Ok((StatusCode::ACCEPTED, Json(json!({"status": "started"}))))
}

async fn pipeline_analyze(
    State(state): State<Arc<AppState>>,
    Json(params): Json<AnalyzeOnlyParams>,
) -> Result<impl IntoResponse, AppError> {
    if state.pipeline_running.load(Ordering::SeqCst) {
        return Err(AppError::Conflict("Pipeline is already running".into()));
    }

    let s = state.clone();
    tokio::spawn(async move {
        if let Err(e) = pipeline::run_analyze_only(s, params).await {
            tracing::error!("Analyze pipeline failed: {:?}", e);
        }
    });

    Ok((StatusCode::ACCEPTED, Json(json!({"status": "started"}))))
}

async fn pipeline_extract(
    State(state): State<Arc<AppState>>,
    Json(params): Json<ExtractParams>,
) -> Result<impl IntoResponse, AppError> {
    if state.pipeline_running.load(Ordering::SeqCst) {
        return Err(AppError::Conflict("Pipeline is already running".into()));
    }

    let s = state.clone();
    tokio::spawn(async move {
        if let Err(e) = pipeline::run_extract_clips(s, params).await {
            tracing::error!("Extract pipeline failed: {:?}", e);
        }
    });

    Ok((StatusCode::ACCEPTED, Json(json!({"status": "started"}))))
}

async fn pipeline_slices(
    State(state): State<Arc<AppState>>,
    Json(params): Json<SliceParams>,
) -> Result<impl IntoResponse, AppError> {
    if state.pipeline_running.load(Ordering::SeqCst) {
        return Err(AppError::Conflict("Pipeline is already running".into()));
    }

    let s = state.clone();
    tokio::spawn(async move {
        if let Err(e) = pipeline::run_generate_slices(s, params).await {
            tracing::error!("Slice generation failed: {:?}", e);
        }
    });

    Ok((StatusCode::ACCEPTED, Json(json!({"status": "started"}))))
}

#[derive(Deserialize)]
struct ListClipsQuery {
    dir: String,
}

#[derive(Serialize)]
struct ClipFolderEntry {
    folder_name: String,
    path: String,
    has_edit_plan: bool,
    slice_count: usize,
}

async fn list_clip_folders(
    axum::extract::Query(q): axum::extract::Query<ListClipsQuery>,
) -> Result<Json<Vec<ClipFolderEntry>>, AppError> {
    let root = std::path::Path::new(&q.dir);
    if !root.is_dir() {
        return Err(AppError::BadRequest(format!(
            "Not a directory: {}",
            q.dir
        )));
    }

    let mut entries: Vec<ClipFolderEntry> = Vec::new();
    let dir_entries = std::fs::read_dir(root)
        .map_err(|e| AppError::Internal(format!("Failed to read directory: {}", e)))?;

    for entry in dir_entries.flatten() {
        let path = entry.path();
        if !path.is_dir() {
            continue;
        }
        // Require at least one non-slice .mp4 to qualify as a clip folder.
        let mut has_clip_mp4 = false;
        let mut slice_count = 0usize;
        let mut has_edit_plan = false;
        if let Ok(children) = std::fs::read_dir(&path) {
            for child in children.flatten() {
                let p = child.path();
                if !p.is_file() {
                    continue;
                }
                let stem = p.file_stem().and_then(|s| s.to_str()).unwrap_or("");
                let ext = p.extension().and_then(|s| s.to_str()).unwrap_or("");
                if ext == "mp4" {
                    if stem.starts_with("slice_") {
                        slice_count += 1;
                    } else {
                        has_clip_mp4 = true;
                    }
                } else if ext == "txt" && stem.ends_with("_edit_plan") {
                    has_edit_plan = true;
                }
            }
        }
        if has_clip_mp4 {
            let folder_name = path
                .file_name()
                .and_then(|s| s.to_str())
                .unwrap_or("")
                .to_string();
            entries.push(ClipFolderEntry {
                folder_name,
                path: path.to_string_lossy().into_owned(),
                has_edit_plan,
                slice_count,
            });
        }
    }

    // If the directory itself is a single clip folder, return it alone.
    if entries.is_empty() {
        let mut has_clip_mp4 = false;
        let mut slice_count = 0usize;
        let mut has_edit_plan = false;
        if let Ok(children) = std::fs::read_dir(root) {
            for child in children.flatten() {
                let p = child.path();
                if !p.is_file() {
                    continue;
                }
                let stem = p.file_stem().and_then(|s| s.to_str()).unwrap_or("");
                let ext = p.extension().and_then(|s| s.to_str()).unwrap_or("");
                if ext == "mp4" {
                    if stem.starts_with("slice_") {
                        slice_count += 1;
                    } else {
                        has_clip_mp4 = true;
                    }
                } else if ext == "txt" && stem.ends_with("_edit_plan") {
                    has_edit_plan = true;
                }
            }
        }
        if has_clip_mp4 {
            entries.push(ClipFolderEntry {
                folder_name: root
                    .file_name()
                    .and_then(|s| s.to_str())
                    .unwrap_or("")
                    .to_string(),
                path: root.to_string_lossy().into_owned(),
                has_edit_plan,
                slice_count,
            });
        }
    }

    entries.sort_by(|a, b| a.folder_name.cmp(&b.folder_name));
    Ok(Json(entries))
}

#[derive(Deserialize)]
struct PremierePromptRequest {
    clip_dir: String,
}

/// Scans a folder name for the first digit run that follows "clip" (case
/// insensitive), e.g. "clip_01_Foo" → Some(1), "CLIP 42" → Some(42).
fn extract_clip_number(folder: &str) -> Option<u32> {
    let lower = folder.to_lowercase();
    let idx = lower.find("clip")?;
    let rest = &folder[idx + 4..];
    let mut digits = String::new();
    for c in rest.chars() {
        if c.is_ascii_digit() {
            digits.push(c);
        } else if !digits.is_empty() {
            break;
        }
    }
    digits.parse().ok()
}


async fn write_premiere_prompt(
    State(state): State<Arc<AppState>>,
    Json(body): Json<PremierePromptRequest>,
) -> Result<Json<serde_json::Value>, AppError> {
    let clip_dir = std::path::Path::new(&body.clip_dir);
    if !clip_dir.is_dir() {
        return Err(AppError::BadRequest(format!(
            "Not a directory: {}",
            body.clip_dir
        )));
    }
    let folder_name = clip_dir
        .file_name()
        .and_then(|s| s.to_str())
        .unwrap_or("clip");

    let seq_name = match extract_clip_number(folder_name) {
        Some(n) => format!("clip_{:02}_Shorts", n),
        None => format!("{}_Shorts", folder_name),
    };

    let cfg = crate::server::premiere::load_config(&state.db)
        .await
        .map_err(|e| AppError::Internal(format!("Failed to load premiere config: {}", e)))?;
    let prompt = crate::server::premiere::build_prompt(&cfg, &body.clip_dir, &seq_name);

    let out_path = clip_dir.join("premiere_setup_prompt.md");
    let _ = std::fs::write(&out_path, &prompt);

    Ok(Json(json!({
        "status": "ok",
        "path": out_path.to_string_lossy(),
        "prompt": prompt,
        "sequence_name": seq_name,
    })))
}

async fn get_premiere_settings(
    State(state): State<Arc<AppState>>,
) -> Result<Json<crate::server::premiere::PremiereConfig>, AppError> {
    let cfg = crate::server::premiere::load_config(&state.db)
        .await
        .map_err(|e| AppError::Internal(format!("Failed to load premiere config: {}", e)))?;
    Ok(Json(cfg))
}

async fn put_premiere_settings(
    State(state): State<Arc<AppState>>,
    Json(body): Json<crate::server::premiere::PremiereConfig>,
) -> Result<Json<serde_json::Value>, AppError> {
    crate::server::premiere::save_config(&state.db, &body)
        .await
        .map_err(|e| AppError::Internal(format!("Failed to save premiere config: {}", e)))?;
    Ok(Json(json!({"status": "ok"})))
}

async fn pipeline_cancel(
    State(state): State<Arc<AppState>>,
) -> Result<Json<serde_json::Value>, AppError> {
    let _ = state.cancel_tx.send(true);
    Ok(Json(json!({"status": "cancel_requested"})))
}

async fn pipeline_status(
    State(state): State<Arc<AppState>>,
) -> Json<serde_json::Value> {
    let running = state.pipeline_running.load(Ordering::SeqCst);
    Json(json!({"running": running}))
}

async fn pipeline_progress_sse(
    State(state): State<Arc<AppState>>,
) -> Sse<impl Stream<Item = Result<Event, Infallible>>> {
    let rx = state.progress_tx.subscribe();
    let stream = BroadcastStream::new(rx).filter_map(|result| match result {
        Ok(event) => {
            let data = serde_json::to_string(&event).unwrap_or_default();
            Some(Ok(Event::default().data(data)))
        }
        Err(_) => None,
    });
    Sse::new(stream).keep_alive(
        axum::response::sse::KeepAlive::new()
            .interval(std::time::Duration::from_secs(15))
            .text("ping"),
    )
}

// ---------------------------------------------------------------------------
// Provider routes
// ---------------------------------------------------------------------------

#[derive(Serialize)]
struct ProviderListEntry {
    key: String,
    label: &'static str,
    default_model: &'static str,
    models: Vec<String>,
    has_key: bool,
}

async fn list_providers_handler(
    State(state): State<Arc<AppState>>,
) -> Json<Vec<ProviderListEntry>> {
    let providers = provider_registry::list_providers();
    let settings = &state.settings;
    let model_cache = state.provider_models.read().await;

    let mut entries: Vec<ProviderListEntry> = providers
        .into_iter()
        .map(|(key, info)| {
            let has_key = match key {
                "anthropic" => !settings.anthropic_api_key.is_empty(),
                "openai" => !settings.openai_api_key.is_empty(),
                "gemini" => !settings.gemini_api_key.is_empty(),
                "grok" => !settings.xai_api_key.is_empty(),
                "ollama" => true,   // no key needed
                "claude_code" => true, // uses CLI
                _ => false,
            };
            let models = model_cache
                .get(key)
                .cloned()
                .unwrap_or_else(|| info.models.clone());
            ProviderListEntry {
                key: key.to_string(),
                label: info.label,
                default_model: info.default_model,
                models,
                has_key,
            }
        })
        .collect();

    entries.sort_by(|a, b| a.key.cmp(&b.key));
    Json(entries)
}

async fn provider_models(
    State(state): State<Arc<AppState>>,
    Path(name): Path<String>,
) -> Result<Json<Vec<String>>, AppError> {
    let client = &state.http_client;
    let settings = &state.settings;

    let models = match name.as_str() {
        "anthropic" => {
            if settings.anthropic_api_key.is_empty() {
                return Err(AppError::BadRequest("Anthropic API key not configured".into()));
            }
            fetch_anthropic_models(client, &settings.anthropic_api_key)
                .await
                .map_err(|e| AppError::Internal(format!("Failed to fetch Anthropic models: {}", e)))?
        }
        "openai" => {
            if settings.openai_api_key.is_empty() {
                return Err(AppError::BadRequest("OpenAI API key not configured".into()));
            }
            fetch_openai_models(client, &settings.openai_api_key)
                .await
                .map_err(|e| AppError::Internal(format!("Failed to fetch OpenAI models: {}", e)))?
        }
        "gemini" => {
            if settings.gemini_api_key.is_empty() {
                return Err(AppError::BadRequest("Gemini API key not configured".into()));
            }
            fetch_gemini_models(client, &settings.gemini_api_key)
                .await
                .map_err(|e| AppError::Internal(format!("Failed to fetch Gemini models: {}", e)))?
        }
        "grok" => {
            if settings.xai_api_key.is_empty() {
                return Err(AppError::BadRequest("xAI API key not configured".into()));
            }
            fetch_grok_models(client, &settings.xai_api_key)
                .await
                .map_err(|e| AppError::Internal(format!("Failed to fetch Grok models: {}", e)))?
        }
        "ollama" => {
            list_ollama_models(client, &settings.ollama_base_url)
                .await
                .map_err(|e| AppError::Internal(format!("Failed to list Ollama models: {}", e)))?
        }
        "claude_code" => {
            // Claude Code uses the CLI — return static list
            let providers = provider_registry::list_providers();
            providers
                .get("claude_code")
                .map(|p| p.models.clone())
                .unwrap_or_default()
        }
        other => {
            return Err(AppError::NotFound(format!("Unknown provider: {}", other)));
        }
    };

    if !models.is_empty() {
        state
            .provider_models
            .write()
            .await
            .insert(name.clone(), models.clone());
    }

    Ok(Json(models))
}

#[derive(Deserialize)]
struct TestProviderRequest {
    provider: String,
    model: String,
    #[serde(default)]
    api_key: String,
    #[serde(default)]
    base_url: String,
}

async fn test_provider(
    State(state): State<Arc<AppState>>,
    Json(body): Json<TestProviderRequest>,
) -> Json<serde_json::Value> {
    // Resolve API key: fall back to the settings-level key for the provider
    // if the profile doesn't have one.
    let api_key = if body.api_key.is_empty() {
        match body.provider.as_str() {
            "anthropic" | "claude_code" => state.settings.anthropic_api_key.clone(),
            "openai" => state.settings.openai_api_key.clone(),
            "gemini" => state.settings.gemini_api_key.clone(),
            "grok" => state.settings.xai_api_key.clone(),
            _ => String::new(),
        }
    } else {
        body.api_key.clone()
    };

    let provider_box = match provider_registry::make_provider(
        &body.provider,
        &api_key,
        &body.base_url,
        state.http_client.clone(),
        None,
    ) {
        Ok(p) => p,
        Err(e) => {
            return Json(json!({
                "success": false,
                "error": format!("Failed to construct provider: {}", e),
            }));
        }
    };

    let system = "You are connected to Trik_Klip for a connection test.";
    let user = "Respond with exactly the single word: OK";

    match provider_box.message(&body.model, user, system, 64).await {
        Ok(resp) => {
            let preview = resp.text.chars().take(200).collect::<String>();
            Json(json!({
                "success": true,
                "provider": body.provider,
                "model": body.model,
                "response": preview,
                "input_tokens": resp.input_tokens,
                "output_tokens": resp.output_tokens,
            }))
        }
        Err(e) => Json(json!({
            "success": false,
            "provider": body.provider,
            "model": body.model,
            "error": format!("{}", e),
        })),
    }
}

// ---------------------------------------------------------------------------
// Profile routes
// ---------------------------------------------------------------------------

async fn list_profiles(
    State(state): State<Arc<AppState>>,
) -> Result<Json<Vec<ProviderProfileRow>>, AppError> {
    let profiles = db::list_provider_profiles(&state.db).await?;
    Ok(Json(profiles))
}

#[derive(Deserialize)]
struct CreateProfileRequest {
    name: String,
    provider: String,
    model: String,
    #[serde(default)]
    api_key: String,
    #[serde(default)]
    base_url: String,
    #[serde(default)]
    is_default: bool,
}

async fn create_profile(
    State(state): State<Arc<AppState>>,
    Json(body): Json<CreateProfileRequest>,
) -> Result<impl IntoResponse, AppError> {
    let row = ProviderProfileRow {
        id: String::new(), // will be generated
        name: body.name,
        provider: body.provider,
        model: body.model,
        api_key: body.api_key,
        base_url: body.base_url,
        is_default: if body.is_default { 1 } else { 0 },
        created_at: String::new(),
    };
    db::save_provider_profile(&state.db, &row).await?;

    Ok((StatusCode::CREATED, Json(json!({"status": "created"}))))
}

async fn update_profile(
    State(state): State<Arc<AppState>>,
    Path(id): Path<String>,
    Json(body): Json<CreateProfileRequest>,
) -> Result<Json<serde_json::Value>, AppError> {
    let row = ProviderProfileRow {
        id,
        name: body.name,
        provider: body.provider,
        model: body.model,
        api_key: body.api_key,
        base_url: body.base_url,
        is_default: if body.is_default { 1 } else { 0 },
        created_at: String::new(),
    };
    db::save_provider_profile(&state.db, &row).await?;

    Ok(Json(json!({"status": "updated"})))
}

async fn delete_profile(
    State(state): State<Arc<AppState>>,
    Path(id): Path<String>,
) -> Result<Json<serde_json::Value>, AppError> {
    db::delete_provider_profile(&state.db, &id).await?;
    Ok(Json(json!({"status": "deleted"})))
}

// ---------------------------------------------------------------------------
// License routes
// ---------------------------------------------------------------------------

#[derive(Deserialize)]
struct VerifyLicenseRequest {
    license_key: String,
}

async fn verify_license_handler(
    State(state): State<Arc<AppState>>,
    Json(body): Json<VerifyLicenseRequest>,
) -> Result<Json<serde_json::Value>, AppError> {
    let result =
        licensing::verify_license(&state.http_client, &body.license_key, true).await;

    if result.valid {
        if let Err(e) = licensing::save_license(&body.license_key) {
            tracing::warn!("Failed to save license: {}", e);
        }
    }

    Ok(Json(json!({
        "valid": result.valid,
        "message": result.message,
        "uses": result.uses,
        "test": result.test,
    })))
}

async fn verify_saved_license_handler(
    State(state): State<Arc<AppState>>,
) -> Result<Json<serde_json::Value>, AppError> {
    let saved_key = licensing::load_saved_license();
    match saved_key {
        Some(key) => {
            let result =
                licensing::verify_license(&state.http_client, &key, false).await;
            Ok(Json(json!({
                "valid": result.valid,
                "message": result.message,
            })))
        }
        None => Ok(Json(json!({
            "valid": false,
            "message": "No saved license key found.",
        }))),
    }
}

async fn license_status() -> Json<serde_json::Value> {
    let saved = licensing::load_saved_license();
    Json(json!({
        "has_license": saved.is_some(),
        "license_key_preview": saved.as_deref().map(|k| {
            if k.len() > 8 {
                format!("{}...{}", &k[..4], &k[k.len()-4..])
            } else {
                "****".to_string()
            }
        }),
    }))
}

// ---------------------------------------------------------------------------
// Transcript routes
// ---------------------------------------------------------------------------

async fn list_transcripts(
    State(state): State<Arc<AppState>>,
) -> Result<Json<Vec<TranscriptListEntry>>, AppError> {
    let rows = sqlx::query_as::<_, TranscriptListRow>(
        "SELECT id, file_hash, source_path, duration_seconds, whisper_model, language, created_at \
         FROM transcripts ORDER BY created_at DESC",
    )
    .fetch_all(&state.db)
    .await?;

    let entries: Vec<TranscriptListEntry> = rows
        .into_iter()
        .map(|r| TranscriptListEntry {
            id: r.id,
            file_hash: r.file_hash,
            source_path: r.source_path,
            duration_seconds: r.duration_seconds,
            whisper_model: r.whisper_model,
            language: r.language,
            created_at: r.created_at,
        })
        .collect();

    Ok(Json(entries))
}

#[derive(sqlx::FromRow)]
struct TranscriptListRow {
    id: String,
    file_hash: String,
    source_path: String,
    duration_seconds: f64,
    whisper_model: String,
    language: String,
    created_at: String,
}

#[derive(Serialize)]
struct TranscriptListEntry {
    id: String,
    file_hash: String,
    source_path: String,
    duration_seconds: f64,
    whisper_model: String,
    language: String,
    created_at: String,
}
