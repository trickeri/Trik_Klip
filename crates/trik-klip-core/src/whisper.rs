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

/// Parse whisper-cli's stdout segment timestamp to seconds. Accepts both
/// `HH:MM:SS.sss` (long files) and `MM:SS.sss` (short files), with `,` or
/// `.` as the fractional separator. Returns None on any parse error.
fn parse_flex_ts(ts: &str) -> Option<f64> {
    let normalised = ts.replace(',', ".");
    let parts: Vec<&str> = normalised.split(':').collect();
    match parts.len() {
        3 => {
            let h: f64 = parts[0].parse().ok()?;
            let m: f64 = parts[1].parse().ok()?;
            let s: f64 = parts[2].parse().ok()?;
            Some(h * 3600.0 + m * 60.0 + s)
        }
        2 => {
            let m: f64 = parts[0].parse().ok()?;
            let s: f64 = parts[1].parse().ok()?;
            Some(m * 60.0 + s)
        }
        _ => None,
    }
}

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

    // Read WAV duration up front. whisper-cli prints each transcribed
    // segment as a line on stdout (e.g. "[00:12:34.000 --> 00:12:39.500]  …")
    // — dividing the end-timestamp of each segment by the WAV duration gives
    // us a smooth progress percentage. whisper-cli's own `--print-progress`
    // output on stderr only fires at 5% steps, which is why the bar used to
    // jump in chunks and not appear at all until the first 5% tick.
    let total_sec: f64 = {
        let path = wav_path.to_string();
        tokio::task::spawn_blocking(move || -> anyhow::Result<f64> {
            let reader = hound::WavReader::open(&path)?;
            let spec = reader.spec();
            let samples = reader.duration() as f64;
            Ok(samples / spec.sample_rate as f64)
        })
        .await
        .ok()
        .and_then(|r| r.ok())
        .unwrap_or(0.0)
    };

    // Build the command. --print-progress keeps the stderr 5%-step fallback
    // around in case stdout parsing misses anything.
    let mut cmd = Command::new(whisper_cli_path);
    cmd.args([
        "-m", model_path,
        "-f", wav_path,
        "-l", language,
        "--output-json",
        "--print-progress",
    ]);

    // Both pipes MUST be drained. Piping stdout without draining deadlocks
    // whisper-cli on long files (the ~64 KB Windows pipe buffer fills up and
    // the process blocks on every segment write). We spawn a reader task for
    // each below.
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

    // ---------- stream stderr for the 5%-step progress fallback ----------
    let stderr = child.stderr.take().expect("stderr was piped");
    let stderr_handle = {
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
                                percent: pct.min(99),
                                label: format!("Transcribing… {}%", pct.min(99)),
                            });
                        }
                    }
                }
            }
        })
    };

    // ---------- stream stdout for smooth per-segment progress ----------
    let stdout = child.stdout.take().expect("stdout was piped");
    let stdout_handle = {
        let tx = progress_tx.clone();
        tokio::spawn(async move {
            let reader = BufReader::new(stdout);
            let mut lines = reader.lines();
            // Match the END timestamp of `[HH:MM:SS.sss --> HH:MM:SS.sss]`.
            // Short files may omit the HH segment, so accept both forms.
            let ts_re = Regex::new(
                r"-->\s+(\d+:\d+(?::\d+)?\.\d+)\]",
            )
            .expect("valid regex");
            let mut last_percent: u8 = 0;

            while let Ok(Some(line)) = lines.next_line().await {
                if total_sec <= 0.0 {
                    continue;
                }
                let Some(caps) = ts_re.captures(&line) else {
                    continue;
                };
                let Some(end_ts) = caps.get(1).and_then(|m| parse_flex_ts(m.as_str()))
                else {
                    continue;
                };
                let pct = ((end_ts / total_sec) * 100.0).clamp(0.0, 99.0) as u8;
                if pct != last_percent {
                    last_percent = pct;
                    if let Some(ref tx) = tx {
                        let _ = tx.send(ProgressEvent::Transcription {
                            percent: pct,
                            label: format!("Transcribing… {}%", pct),
                        });
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
            let _ = stderr_handle.await;
            let _ = stdout_handle.await;
            bail!("Pipeline cancelled by user");
        }
    };

    // Make sure both readers finish.
    let _ = stderr_handle.await;
    let _ = stdout_handle.await;

    if !status.success() {
        let code = status.code().unwrap_or(-1);
        bail!("whisper-cli exited with code {}", code);
    }

    // Snap the bar to 100% — the last timestamp line usually lands in the
    // high 90s, and whisper-cli's "progress = 100%" emission sometimes loses
    // the race with process exit.
    if let Some(ref tx) = progress_tx {
        let _ = tx.send(ProgressEvent::Transcription {
            percent: 100,
            label: "Transcribing… 100%".into(),
        });
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
