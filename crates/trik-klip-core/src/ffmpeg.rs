// FFmpeg subprocess wrapper — audio extraction, clip export, slice extraction.

use anyhow::{Context, Result};
use tokio::process::Command;
use tracing::{debug, error, info};

use crate::models::ProgressEvent;

/// Windows CREATE_NO_WINDOW flag to suppress console popups.
#[cfg(target_os = "windows")]
const CREATE_NO_WINDOW: u32 = 0x08000000;

/// Apply platform-specific creation flags to a command.
#[cfg(target_os = "windows")]
fn apply_creation_flags(cmd: &mut Command) {
    #[allow(unused_imports)]
    use std::os::windows::process::CommandExt;
    cmd.creation_flags(CREATE_NO_WINDOW);
}

#[cfg(not(target_os = "windows"))]
fn apply_creation_flags(_cmd: &mut Command) {}

/// Get the duration of a media file in seconds via ffprobe.
pub async fn get_duration(ffprobe_path: &str, media_path: &str) -> Result<f64> {
    debug!(media_path, "querying duration via ffprobe");

    let mut cmd = Command::new(ffprobe_path);
    cmd.args([
        "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        media_path,
    ])
    .stdout(std::process::Stdio::piped())
    .stderr(std::process::Stdio::piped());
    apply_creation_flags(&mut cmd);

    let output = cmd
        .output()
        .await
        .context("failed to run ffprobe")?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        error!(%stderr, "ffprobe failed");
        anyhow::bail!("ffprobe exited with status {}: {}", output.status, stderr);
    }

    let stdout = String::from_utf8_lossy(&output.stdout);
    let duration: f64 = stdout
        .trim()
        .parse()
        .context("failed to parse duration from ffprobe output")?;

    debug!(duration, "got media duration");
    Ok(duration)
}

/// Extract audio from a media file to a 16 kHz mono WAV.
///
/// If `progress_tx` is provided, progress events are sent as
/// `ProgressEvent::AudioExtraction { percent }` by parsing ffmpeg stderr.
pub async fn extract_audio(
    ffmpeg_path: &str,
    ffprobe_path: &str,
    mp4_path: &str,
    output_wav: &str,
    audio_track: Option<u32>,
    progress_tx: Option<tokio::sync::broadcast::Sender<ProgressEvent>>,
) -> Result<()> {
    // If progress reporting is requested, get the total duration first.
    let total_duration_us: Option<f64> = if progress_tx.is_some() {
        let dur = get_duration(ffprobe_path, mp4_path).await?;
        Some(dur * 1_000_000.0)
    } else {
        None
    };

    info!(mp4_path, output_wav, "extracting audio");

    let mut args: Vec<String> = Vec::new();
    args.push("-y".into());

    // Request progress output on stderr when we have a sender.
    if progress_tx.is_some() {
        args.push("-progress".into());
        args.push("pipe:2".into());
    }

    args.push("-i".into());
    args.push(mp4_path.into());

    if let Some(track) = audio_track {
        args.push("-map".into());
        args.push(format!("0:a:{}", track));
    }

    args.extend([
        "-vn".into(),
        "-acodec".into(),
        "pcm_s16le".into(),
        "-ar".into(),
        "16000".into(),
        "-ac".into(),
        "1".into(),
        output_wav.into(),
    ]);

    let mut cmd = Command::new(ffmpeg_path);
    cmd.args(&args)
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::piped());
    apply_creation_flags(&mut cmd);

    if let Some(ref tx) = progress_tx {
        // Spawn and stream stderr for progress.
        let mut child = cmd.spawn().context("failed to spawn ffmpeg for audio extraction")?;

        let stderr = child
            .stderr
            .take()
            .context("failed to capture ffmpeg stderr")?;

        let tx = tx.clone();
        let total_us = total_duration_us.unwrap_or(1.0);

        // Read stderr line by line in a blocking-friendly way.
        let reader_handle = tokio::spawn(async move {
            use tokio::io::{AsyncBufReadExt, BufReader};
            let mut reader = BufReader::new(stderr);
            let mut line = String::new();
            let mut last_percent: u8 = 0;

            loop {
                line.clear();
                match reader.read_line(&mut line).await {
                    Ok(0) => break, // EOF
                    Ok(_) => {
                        if let Some(val) = line.strip_prefix("out_time_us=") {
                            if let Ok(us) = val.trim().parse::<f64>() {
                                let pct = ((us / total_us) * 100.0).clamp(0.0, 100.0) as u8;
                                if pct != last_percent {
                                    last_percent = pct;
                                    let _ = tx.send(ProgressEvent::AudioExtraction {
                                        percent: pct,
                                    });
                                }
                            }
                        }
                    }
                    Err(e) => {
                        debug!("error reading ffmpeg stderr: {}", e);
                        break;
                    }
                }
            }
        });

        let status = child.wait().await.context("ffmpeg audio extraction failed")?;
        // Wait for the reader to finish draining.
        let _ = reader_handle.await;

        if !status.success() {
            anyhow::bail!("ffmpeg audio extraction exited with status {}", status);
        }
    } else {
        // No progress — just run to completion.
        let output = cmd.output().await.context("failed to run ffmpeg for audio extraction")?;
        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            error!(%stderr, "ffmpeg audio extraction failed");
            anyhow::bail!("ffmpeg audio extraction exited with status {}: {}", output.status, stderr);
        }
    }

    info!(output_wav, "audio extraction complete");
    Ok(())
}

/// Extract a clip from a media file using stream copy for video and AAC for audio.
pub async fn extract_clip(
    ffmpeg_path: &str,
    mp4_path: &str,
    output_path: &str,
    clip_start: f64,
    duration: f64,
) -> Result<()> {
    info!(
        mp4_path,
        output_path,
        clip_start,
        duration,
        "extracting clip"
    );

    let mut cmd = Command::new(ffmpeg_path);
    cmd.args([
        "-y",
        "-ss", &format!("{:.2}", clip_start),
        "-i", mp4_path,
        "-t", &format!("{:.2}", duration),
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        output_path,
    ])
    .stdout(std::process::Stdio::null())
    .stderr(std::process::Stdio::piped());
    apply_creation_flags(&mut cmd);

    let output = cmd
        .output()
        .await
        .context("failed to run ffmpeg for clip extraction")?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        error!(%stderr, "ffmpeg clip extraction failed");
        anyhow::bail!(
            "ffmpeg clip extraction exited with status {}: {}",
            output.status,
            stderr
        );
    }

    info!(output_path, "clip extraction complete");
    Ok(())
}

/// Extract a slice from an already-cut clip file (used for cut list slices).
///
/// Identical operation to `extract_clip` but semantically distinct —
/// it seeks within a clip rather than the original source.
pub async fn extract_slice(
    ffmpeg_path: &str,
    clip_mp4: &str,
    output_path: &str,
    seek_seconds: f64,
    duration: f64,
) -> Result<()> {
    info!(
        clip_mp4,
        output_path,
        seek_seconds,
        duration,
        "extracting slice"
    );

    let mut cmd = Command::new(ffmpeg_path);
    cmd.args([
        "-y",
        "-ss", &format!("{:.2}", seek_seconds),
        "-i", clip_mp4,
        "-t", &format!("{:.2}", duration),
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        output_path,
    ])
    .stdout(std::process::Stdio::null())
    .stderr(std::process::Stdio::piped());
    apply_creation_flags(&mut cmd);

    let output = cmd
        .output()
        .await
        .context("failed to run ffmpeg for slice extraction")?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        error!(%stderr, "ffmpeg slice extraction failed");
        anyhow::bail!(
            "ffmpeg slice extraction exited with status {}: {}",
            output.status,
            stderr
        );
    }

    info!(output_path, "slice extraction complete");
    Ok(())
}
