// Per-slice visual-aid fetching. Ports `gui.py::_download_visual_aids` +
// `_search_and_download_image`.
//
// For each parsed cut, ask the LLM for a short image-search query, scrape
// Bing Images for a candidate URL, download it, validate the magic bytes,
// and re-encode through the `image` crate as a clean JPEG named
// `visual_NN.jpg` in the clip folder.

use std::path::{Path, PathBuf};
use std::time::Duration;

use anyhow::{Context, Result};
use regex::Regex;
use reqwest::Client;
use tracing::{debug, info, warn};

use crate::cancel::{is_cancelled, CancelRx};
use crate::llm::provider::LlmProvider;
use crate::models::ProgressEvent;
use crate::prompts::CutEntry;

const USER_AGENT: &str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) \
                          AppleWebKit/537.36 (KHTML, like Gecko) \
                          Chrome/120.0.0.0 Safari/537.36";

/// Ask the LLM for per-slice image search queries, then download one image
/// per query into `clip_dir` as `visual_NN.jpg`. Returns the number of
/// images saved (can be less than `cuts.len()` if some slices had no visual
/// topic or no download succeeded).
pub async fn generate_visual_aids(
    clip_dir: &Path,
    cuts: &[CutEntry],
    provider: &dyn LlmProvider,
    model: &str,
    http: &Client,
    cancel_rx: Option<&CancelRx>,
    progress: Option<&tokio::sync::broadcast::Sender<ProgressEvent>>,
) -> Result<usize> {
    if cuts.is_empty() {
        return Ok(0);
    }

    let queries = ask_for_queries(provider, model, cuts).await?;
    let total = cuts.len();

    // Pad / truncate to match cuts count so indices line up.
    let queries = pad_or_truncate(queries, total);

    let mut downloaded = 0usize;
    for (i, query) in queries.iter().enumerate() {
        if let Some(rx) = cancel_rx {
            if is_cancelled(rx) {
                anyhow::bail!("Pipeline cancelled by user");
            }
        }

        if let Some(tx) = progress {
            let _ = tx.send(ProgressEvent::VisualAids {
                done: i,
                total,
            });
        }

        let Some(q) = query.as_deref().map(str::trim).filter(|s| !s.is_empty()) else {
            debug!("slice {} — skipped (no visual topic)", i + 1);
            continue;
        };

        let stem = format!("visual_{:02}", i + 1);
        match search_and_download_image(http, q, clip_dir, &stem).await {
            Ok(Some(p)) => {
                info!("slice {} — saved {}", i + 1, p.display());
                downloaded += 1;
            }
            Ok(None) => {
                warn!("slice {} — no usable image for query {:?}", i + 1, q);
            }
            Err(e) => {
                warn!("slice {} — image download failed for {:?}: {}", i + 1, q, e);
            }
        }
    }

    if let Some(tx) = progress {
        let _ = tx.send(ProgressEvent::VisualAids {
            done: total,
            total,
        });
    }

    Ok(downloaded)
}

fn pad_or_truncate(mut v: Vec<Option<String>>, want: usize) -> Vec<Option<String>> {
    if v.len() >= want {
        v.truncate(want);
    } else {
        v.resize(want, None);
    }
    v
}

async fn ask_for_queries(
    provider: &dyn LlmProvider,
    model: &str,
    cuts: &[CutEntry],
) -> Result<Vec<Option<String>>> {
    let descriptions: String = cuts
        .iter()
        .enumerate()
        .map(|(i, c)| {
            let reason = if c.reason.trim().is_empty() {
                "no description"
            } else {
                c.reason.trim()
            };
            format!("{}. {}", i + 1, reason)
        })
        .collect::<Vec<_>>()
        .join("\n");

    let system = "You are helping find visual aid images for a YouTube Shorts video.";
    let user = format!(
        "You are helping find visual aid images for a YouTube Shorts video.\n\
         Below are descriptions of each video slice. For each one, suggest a\n\
         short Google Image search query (3-6 words) for a relevant visual aid\n\
         image that would support the topic being discussed.\n\n\
         Rules:\n\
         - Only suggest images for slices that discuss a specific concept, game,\n\
           tool, product, place, or visual topic.\n\
         - For slices that are purely personal opinion, emotion, or talking with\n\
           no visual subject, return null for that entry.\n\
         - Return ONLY a JSON array with one entry per slice. Each entry is\n\
           either a search query string or null.\n\
         - No markdown fences, no explanation — just the raw JSON array.\n\n\
         Slices:\n{}",
        descriptions
    );

    let response = provider.message(model, &user, system, 1024).await?;

    let cleaned = strip_code_fences(response.text.trim());
    let parsed: Vec<serde_json::Value> = serde_json::from_str(&cleaned)
        .with_context(|| format!("LLM returned non-JSON for visual queries: {:?}", cleaned))?;

    Ok(parsed
        .into_iter()
        .map(|v| v.as_str().map(|s| s.trim().to_string()))
        .collect())
}

fn strip_code_fences(s: &str) -> String {
    let s = s.trim();
    if let Some(rest) = s.strip_prefix("```") {
        // Skip optional language tag on the first line.
        let after_lang = match rest.find('\n') {
            Some(idx) => &rest[idx + 1..],
            None => rest,
        };
        let cleaned = after_lang.trim_end();
        if let Some(stripped) = cleaned.strip_suffix("```") {
            return stripped.trim().to_string();
        }
        return cleaned.trim().to_string();
    }
    s.to_string()
}

async fn search_and_download_image(
    http: &Client,
    query: &str,
    out_dir: &Path,
    filename_stem: &str,
) -> Result<Option<PathBuf>> {
    let resp = http
        .get("https://www.bing.com/images/search")
        .query(&[
            ("q", query),
            ("form", "HDRSC2"),
            ("first", "1"),
            ("safeSearch", "Moderate"),
        ])
        .header("User-Agent", USER_AGENT)
        .timeout(Duration::from_secs(15))
        .send()
        .await
        .context("Bing search request failed")?;

    let html = resp.text().await?;

    // Bing embeds full-size image URLs as "murl":"https://..." per thumbnail.
    let murl_re = Regex::new(r#""murl"\s*:\s*"(https?://[^"]+)""#).expect("valid regex");
    let mut candidates: Vec<String> = murl_re
        .captures_iter(&html)
        .filter_map(|c| c.get(1).map(|m| m.as_str().to_string()))
        .collect();

    if candidates.is_empty() {
        // Fallback — any direct image URL in the page that isn't Bing itself.
        let fallback_re =
            Regex::new(r#"(?i)(https?://[^\s"<>]+\.(?:jpg|jpeg|png|webp))"#).expect("valid regex");
        candidates = fallback_re
            .captures_iter(&html)
            .filter_map(|c| c.get(1).map(|m| m.as_str().to_string()))
            .filter(|u| {
                !u.contains("bing.com")
                    && !u.contains("microsoft.com")
                    && !u.to_lowercase().contains("favicon")
            })
            .collect();
    }

    if candidates.is_empty() {
        return Ok(None);
    }

    // Try up to 8 candidates until one downloads + decodes cleanly.
    for img_url in candidates.iter().take(8) {
        match try_download_and_reencode(http, img_url, out_dir, filename_stem).await {
            Ok(Some(p)) => return Ok(Some(p)),
            Ok(None) => continue,
            Err(e) => {
                debug!("candidate {} failed: {}", img_url, e);
                continue;
            }
        }
    }
    Ok(None)
}

async fn try_download_and_reencode(
    http: &Client,
    url: &str,
    out_dir: &Path,
    filename_stem: &str,
) -> Result<Option<PathBuf>> {
    let resp = http
        .get(url)
        .header("User-Agent", USER_AGENT)
        .timeout(Duration::from_secs(10))
        .send()
        .await
        .with_context(|| format!("image fetch failed: {}", url))?;

    let bytes = resp.bytes().await?;

    // Too-small responses are usually 1×1 trackers or error pages.
    if bytes.len() < 5_000 {
        return Ok(None);
    }

    if !is_supported_image(&bytes) {
        return Ok(None);
    }

    // Decode via the image crate. This rejects malformed headers that would
    // have passed a magic-byte check but still break downstream consumers.
    let img = match image::load_from_memory(&bytes) {
        Ok(i) => i,
        Err(_) => return Ok(None),
    };
    // Normalise to RGB and re-encode as a clean JPEG — matches Python's
    // Pillow → "JPEG, quality=95" normalisation and ensures Premiere can
    // import whatever came back (including WebP originals).
    let rgb = img.to_rgb8();

    let out_path = out_dir.join(format!("{}.jpg", filename_stem));
    let file = std::fs::File::create(&out_path)
        .with_context(|| format!("Failed to create {}", out_path.display()))?;
    let mut writer = std::io::BufWriter::new(file);
    let mut encoder = image::codecs::jpeg::JpegEncoder::new_with_quality(&mut writer, 95);
    encoder
        .encode(&rgb, rgb.width(), rgb.height(), image::ExtendedColorType::Rgb8)
        .context("JPEG re-encode failed")?;
    Ok(Some(out_path))
}

fn is_supported_image(data: &[u8]) -> bool {
    if data.len() < 12 {
        return false;
    }
    let m = &data[..12];
    // JPEG: FF D8 FF
    if m[0] == 0xFF && m[1] == 0xD8 && m[2] == 0xFF {
        return true;
    }
    // PNG: 89 50 4E 47 0D 0A 1A 0A
    if m[..8] == [0x89, b'P', b'N', b'G', 0x0D, 0x0A, 0x1A, 0x0A] {
        return true;
    }
    // WebP: "RIFF....WEBP"
    if &m[..4] == b"RIFF" && &m[8..12] == b"WEBP" {
        return true;
    }
    // GIF: "GIF8"
    if &m[..4] == b"GIF8" {
        return true;
    }
    false
}
