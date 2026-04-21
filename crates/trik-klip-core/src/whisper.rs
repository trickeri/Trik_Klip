// Whisper-cli subprocess wrapper — transcription via whisper.cpp Vulkan.

use anyhow::{bail, Context};
use regex::Regex;
use serde::Deserialize;
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::Command;
use tracing::{debug, info, warn};

use crate::cancel::{wait_cancelled, CancelRx};
use crate::models::{ProgressEvent, TranscriptSegment};

// ---------------------------------------------------------------------------
// JSON schema returned by whisper-cli --output-json
// ---------------------------------------------------------------------------

#[derive(Debug, Deserialize)]
struct WhisperJsonOutput {
    transcription: Vec<WhisperJsonSegment>,
}

#[derive(Debug, Deserialize)]
struct WhisperJsonSegment {
    timestamps: WhisperTimestamps,
    text: String,
}

#[derive(Debug, Deserialize)]
struct WhisperTimestamps {
    from: String,
    to: String,
}

// ---------------------------------------------------------------------------
// Timestamp parsing
// ---------------------------------------------------------------------------

/// Parse a whisper-cli timestamp (`HH:MM:SS,mmm` or `HH:MM:SS.mmm`) to seconds.
pub fn parse_whisper_timestamp(ts: &str) -> anyhow::Result<f64> {
    // Accept both comma and period as the fractional separator.
    let normalised = ts.replace(',', ".");
    let parts: Vec<&str> = normalised.split(':').collect();
    if parts.len() != 3 {
        bail!("Invalid whisper timestamp (expected HH:MM:SS,mmm): {}", ts);
    }
    let h: f64 = parts[0]
        .parse()
        .with_context(|| format!("Bad hours component in timestamp: {}", ts))?;
    let m: f64 = parts[1]
        .parse()
        .with_context(|| format!("Bad minutes component in timestamp: {}", ts))?;
    let s: f64 = parts[2]
        .parse()
        .with_context(|| format!("Bad seconds component in timestamp: {}", ts))?;
    Ok(h * 3600.0 + m * 60.0 + s)
}

// ---------------------------------------------------------------------------
// Main transcription entry point
// ---------------------------------------------------------------------------

/// Run whisper-cli as a subprocess and return parsed transcript segments.
///
/// `whisper_cli_path` — path to the whisper-cli executable.
/// `model_path`       — path to the GGML model file.
/// `wav_path`         — path to the 16-kHz mono WAV to transcribe.
/// `language`         — BCP-47 language code (e.g. "en").
/// `progress_tx`      — optional broadcast channel for progress events.
pub async fn transcribe(
    whisper_cli_path: &str,
    model_path: &str,
    wav_path: &str,
    language: &str,
    progress_tx: Option<tokio::sync::broadcast::Sender<ProgressEvent>>,
    mut cancel_rx: Option<CancelRx>,
) -> anyhow::Result<Vec<TranscriptSegment>> {
    info!(
        whisper_cli = whisper_cli_path,
        model = model_path,
        wav = wav_path,
        language,
        "Starting whisper-cli transcription"
    );

    // Build the command. We intentionally omit --no-prints so that whisper-cli
    // writes progress lines to stderr that we can parse.
    let mut cmd = Command::new(whisper_cli_path);
    cmd.args(["-m", model_path, "-f", wav_path, "-l", language, "--output-json"]);

    // Pipe stderr for progress; stdout is unused but pipe it to avoid blocking.
    cmd.stderr(std::process::Stdio::piped());
    cmd.stdout(std::process::Stdio::piped());

    // On Windows, suppress the console window that would otherwise flash open.
    #[cfg(target_os = "windows")]
    {
        #[allow(unused_imports)]
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }

    let mut child = cmd
        .spawn()
        .with_context(|| format!("Failed to spawn whisper-cli at '{}'", whisper_cli_path))?;

    // ---------- stream stderr for progress ----------
    let stderr = child.stderr.take().expect("stderr was piped");
    let progress_handle = {
        let tx = progress_tx.clone();
        tokio::spawn(async move {
            let reader = BufReader::new(stderr);
            let mut lines = reader.lines();
            let re = Regex::new(r"progress\s*=\s*(\d+)%").expect("valid regex");

            while let Ok(Some(line)) = lines.next_line().await {
                debug!(stderr_line = %line, "whisper-cli stderr");
                if let Some(caps) = re.captures(&line) {
                    if let Ok(pct) = caps[1].parse::<u8>() {
                        if let Some(ref tx) = tx {
                            let _ = tx.send(ProgressEvent::Transcription {
                                percent: pct,
                                label: format!("Transcribing… {}%", pct),
                            });
                        }
                    }
                }
            }
        })
    };

    // ---------- wait for the process to finish (or cancel) ----------
    let status = tokio::select! {
        s = child.wait() => s.context("Failed to wait on whisper-cli process")?,
        _ = wait_cancelled(cancel_rx.as_mut()) => {
            let _ = child.kill().await;
            let _ = progress_handle.await;
            bail!("Pipeline cancelled by user");
        }
    };

    // Make sure the progress reader finishes.
    let _ = progress_handle.await;

    if !status.success() {
        let code = status.code().unwrap_or(-1);
        bail!("whisper-cli exited with code {}", code);
    }

    info!("whisper-cli finished successfully");

    // ---------- read the JSON output ----------
    // whisper-cli --output-json writes to `<wav_path>.json`
    let json_path = format!("{}.json", wav_path);
    let json_bytes = tokio::fs::read(&json_path)
        .await
        .with_context(|| format!("Failed to read whisper JSON output at '{}'", json_path))?;

    let whisper_output: WhisperJsonOutput = serde_json::from_slice(&json_bytes)
        .with_context(|| format!("Failed to parse whisper JSON at '{}'", json_path))?;

    // ---------- convert to our segment type ----------
    let mut segments = Vec::with_capacity(whisper_output.transcription.len());
    for seg in &whisper_output.transcription {
        let start = parse_whisper_timestamp(&seg.timestamps.from)
            .with_context(|| format!("Bad 'from' timestamp: {}", seg.timestamps.from))?;
        let end = parse_whisper_timestamp(&seg.timestamps.to)
            .with_context(|| format!("Bad 'to' timestamp: {}", seg.timestamps.to))?;
        let text = seg.text.trim().to_string();
        if !text.is_empty() {
            segments.push(TranscriptSegment { start, end, text });
        }
    }

    info!(segment_count = segments.len(), "Transcription complete");

    // Clean up the temporary JSON file — best-effort.
    if let Err(e) = tokio::fs::remove_file(&json_path).await {
        warn!(path = %json_path, error = %e, "Could not remove whisper JSON output");
    }

    Ok(segments)
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_whisper_timestamp_comma() {
        let secs = parse_whisper_timestamp("00:01:23,456").unwrap();
        // 1*60 + 23.456
        assert!((secs - 83.456).abs() < 1e-6);
    }

    #[test]
    fn test_parse_whisper_timestamp_dot() {
        let secs = parse_whisper_timestamp("01:02:03.500").unwrap();
        // 3600 + 120 + 3.5
        assert!((secs - 3723.5).abs() < 1e-6);
    }

    #[test]
    fn test_parse_whisper_timestamp_zero() {
        let secs = parse_whisper_timestamp("00:00:00,000").unwrap();
        assert!((secs - 0.0).abs() < 1e-6);
    }

    #[test]
    fn test_parse_whisper_timestamp_invalid() {
        assert!(parse_whisper_timestamp("12:34").is_err());
        assert!(parse_whisper_timestamp("garbage").is_err());
    }

    #[test]
    fn test_json_deserialization() {
        let json = r#"{
            "transcription": [
                {
                    "timestamps": { "from": "00:00:00,000", "to": "00:00:05,120" },
                    "text": " Hello world"
                },
                {
                    "timestamps": { "from": "00:00:05,120", "to": "00:00:10,000" },
                    "text": " Second segment"
                }
            ]
        }"#;
        let output: WhisperJsonOutput = serde_json::from_str(json).unwrap();
        assert_eq!(output.transcription.len(), 2);
        assert_eq!(output.transcription[0].text, " Hello world");
    }
}
