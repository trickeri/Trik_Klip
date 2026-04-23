// Whisper model catalog + auto-download from HuggingFace.
//
// Models are stored in two possible locations and resolved in this order:
//   1. Shipped resources dir (e.g. ggml-base.bin packaged with the app)
//   2. User data dir under whisper_models/ (downloaded on demand)
//
// If the selected model exists at neither, we download it from HuggingFace
// into the user data dir.

use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
use reqwest::Client;
use tokio::io::AsyncWriteExt;
use tokio::sync::broadcast;
use tokio::sync::watch;
use tracing::info;

use crate::cancel::is_cancelled;
use crate::models::ProgressEvent;

/// All whisper model names the UI can select.
pub const AVAILABLE_MODELS: &[&str] = &[
    "tiny",
    "tiny.en",
    "base",
    "base.en",
    "small",
    "small.en",
    "medium",
    "medium.en",
    "large-v3",
    "large-v3-turbo",
];

fn huggingface_url(model: &str) -> String {
    // https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-<name>.bin
    format!(
        "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{}.bin",
        model
    )
}

fn filename_for(model: &str) -> String {
    format!("ggml-{}.bin", model)
}

/// Resolve the absolute path for a given model name. Does not download —
/// returns the location it *would* live at in the user data dir if not found.
/// Checks shipped resources dir first, then data_dir/whisper_models/.
pub fn resolve_path(
    resources_dir: &Path,
    data_dir: &Path,
    model: &str,
) -> PathBuf {
    let filename = filename_for(model);
    let shipped = resources_dir.join(&filename);
    if shipped.exists() {
        return shipped;
    }
    data_dir.join("whisper_models").join(filename)
}

/// Ensure the given whisper model is available locally. If it's already in
/// resources/ or data_dir/whisper_models/, returns the path. Otherwise
/// downloads it from HuggingFace, emitting `WhisperDownload` progress events
/// as it streams.
///
/// Respects the cancel signal — if the user cancels mid-download, the
/// partial file is deleted and an error is returned.
pub async fn ensure_downloaded(
    resources_dir: &Path,
    data_dir: &Path,
    model: &str,
    http: &Client,
    progress: Option<&broadcast::Sender<ProgressEvent>>,
    cancel_rx: Option<&watch::Receiver<bool>>,
) -> Result<PathBuf> {
    if !AVAILABLE_MODELS.contains(&model) {
        anyhow::bail!(
            "Unknown whisper model: {:?} — expected one of {:?}",
            model,
            AVAILABLE_MODELS
        );
    }

    let path = resolve_path(resources_dir, data_dir, model);
    if path.exists() {
        return Ok(path);
    }

    // Need to download.
    let parent = path
        .parent()
        .ok_or_else(|| anyhow::anyhow!("Invalid whisper model path: {}", path.display()))?;
    tokio::fs::create_dir_all(parent).await?;

    let url = huggingface_url(model);
    info!("Downloading whisper model {} from {}", model, url);

    if let Some(tx) = progress {
        let _ = tx.send(ProgressEvent::WhisperDownload {
            model: model.to_string(),
            percent: 0,
            bytes_done: 0,
            bytes_total: 0,
        });
    }

    let resp = http
        .get(&url)
        .send()
        .await
        .with_context(|| format!("Failed to start download for {}", model))?;

    if !resp.status().is_success() {
        anyhow::bail!(
            "Download for {} failed: HTTP {}",
            model,
            resp.status()
        );
    }

    let total = resp.content_length().unwrap_or(0);

    // Stream to a .part file and rename on success so a cancelled or failed
    // download doesn't leave a bogus model that looks complete.
    let part_path = path.with_extension("bin.part");
    // Scope the file so it's dropped before the rename.
    {
        let mut file = tokio::fs::File::create(&part_path)
            .await
            .with_context(|| format!("Failed to create {}", part_path.display()))?;

        let mut resp = resp;
        let mut downloaded: u64 = 0;
        let mut last_percent: u8 = 0;

        loop {
            if let Some(rx) = cancel_rx {
                if is_cancelled(rx) {
                    drop(file);
                    let _ = tokio::fs::remove_file(&part_path).await;
                    anyhow::bail!("Whisper model download cancelled by user");
                }
            }

            let chunk = resp
                .chunk()
                .await
                .with_context(|| format!("Download stream error for {}", model))?;
            let Some(chunk) = chunk else { break };

            file.write_all(&chunk).await?;
            downloaded += chunk.len() as u64;

            if let Some(tx) = progress {
                let pct = if total > 0 {
                    ((downloaded as f64 / total as f64) * 100.0).clamp(0.0, 100.0) as u8
                } else {
                    0
                };
                if pct != last_percent {
                    last_percent = pct;
                    let _ = tx.send(ProgressEvent::WhisperDownload {
                        model: model.to_string(),
                        percent: pct,
                        bytes_done: downloaded,
                        bytes_total: total,
                    });
                }
            }
        }

        file.flush().await?;
    }

    // Atomic rename to the final name.
    tokio::fs::rename(&part_path, &path)
        .await
        .with_context(|| format!("Failed to finalize {}", path.display()))?;

    if let Some(tx) = progress {
        let _ = tx.send(ProgressEvent::WhisperDownload {
            model: model.to_string(),
            percent: 100,
            bytes_done: total,
            bytes_total: total,
        });
    }

    info!(
        "Downloaded whisper model {} to {} ({} bytes)",
        model,
        path.display(),
        total
    );
    Ok(path)
}
