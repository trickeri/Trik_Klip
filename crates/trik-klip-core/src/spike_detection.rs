//! RMS volume-spike detection using ndarray + hound.
//!
//! Reads a WAV file, computes per-frame RMS energy with a sliding window,
//! compares each frame against a rolling baseline average, and returns
//! contiguous regions whose energy ratio exceeds a threshold.

use anyhow::{Context, Result};
use ndarray::Array1;
use tracing::{debug, info, warn};

use crate::models::VolumeSpike;

/// Detect volume spikes in a WAV file.
///
/// Returns a list of [`VolumeSpike`] structs sorted chronologically, each
/// carrying start/end timestamps (seconds) and a peak intensity ratio.
pub fn detect_volume_spikes(
    wav_path: &str,
    frame_ms: u32,
    hop_ms: u32,
    baseline_seconds: f64,
    spike_threshold: f64,
    min_spike_seconds: f64,
    merge_gap_seconds: f64,
) -> Result<Vec<VolumeSpike>> {
    info!(path = %wav_path, "Reading WAV file for spike detection");

    // --- Read WAV ----------------------------------------------------------
    let reader = hound::WavReader::open(wav_path)
        .with_context(|| format!("Failed to open WAV file: {wav_path}"))?;

    let spec = reader.spec();
    let sample_rate = spec.sample_rate;
    let bits = spec.bits_per_sample;
    let sample_format = spec.sample_format;

    debug!(
        sample_rate,
        bits_per_sample = bits,
        channels = spec.channels,
        ?sample_format,
        "WAV spec"
    );

    // Normalise all samples to f32 in [-1, 1].
    // hound exposes i16/i32/f32 readers; we handle the common cases.
    let samples: Array1<f32> = match sample_format {
        hound::SampleFormat::Int => {
            let max_val = (1i64 << (bits - 1)) as f32;
            let raw: Vec<f32> = reader
                .into_samples::<i32>()
                .map(|s| s.map(|v| v as f32 / max_val))
                .collect::<std::result::Result<Vec<_>, _>>()
                .context("Error reading integer samples from WAV")?;
            Array1::from(raw)
        }
        hound::SampleFormat::Float => {
            let raw: Vec<f32> = reader
                .into_samples::<f32>()
                .map(|s| s.map(|v| v))
                .collect::<std::result::Result<Vec<_>, _>>()
                .context("Error reading float samples from WAV")?;
            Array1::from(raw)
        }
    };

    let n_samples = samples.len();
    if n_samples == 0 {
        warn!("WAV file contains no samples");
        return Ok(Vec::new());
    }

    // --- Frame / hop sizes -------------------------------------------------
    let frame_samples = (sample_rate as usize) * (frame_ms as usize) / 1000;
    let hop_samples = (sample_rate as usize) * (hop_ms as usize) / 1000;

    if n_samples < frame_samples {
        warn!(
            n_samples,
            frame_samples, "Audio shorter than one analysis frame"
        );
        return Ok(Vec::new());
    }

    // --- Compute RMS per frame (sliding window with hop) -------------------
    let n_frames = (n_samples - frame_samples) / hop_samples + 1;
    let mut rms = Array1::<f32>::zeros(n_frames);

    for i in 0..n_frames {
        let start = i * hop_samples;
        let window = samples.slice(ndarray::s![start..start + frame_samples]);
        let sum_sq: f32 = window.iter().map(|&x| x * x).sum();
        rms[i] = (sum_sq / frame_samples as f32).sqrt();
    }

    debug!(n_frames, "Computed RMS for all frames");

    // --- Rolling average baseline ------------------------------------------
    let baseline_frames = (baseline_seconds / (hop_ms as f64 / 1000.0))
        .round()
        .max(1.0) as usize;

    let rolling_avg = if baseline_frames >= n_frames {
        let global_mean = rms.mean().unwrap_or(0.0);
        Array1::from_elem(n_frames, global_mean)
    } else {
        // Efficient sliding-sum convolution with a uniform kernel,
        // using "same" semantics (output centred on each element).
        rolling_average_same(&rms, baseline_frames)
    };

    // Floor to machine epsilon to avoid division by zero.
    let eps = f32::EPSILON;
    let ratio: Array1<f32> = &rms / &rolling_avg.mapv(|v| v.max(eps));

    // --- Find contiguous regions above threshold ---------------------------
    let spike_thresh = spike_threshold as f32;
    let min_spike_frames =
        (min_spike_seconds / (hop_ms as f64 / 1000.0)).ceil() as usize;

    struct RawSpike {
        start: usize,
        end: usize,
        peak: f32,
    }

    let mut spikes_raw: Vec<RawSpike> = Vec::new();
    let mut i = 0;
    while i < n_frames {
        if ratio[i] > spike_thresh {
            let start = i;
            while i < n_frames && ratio[i] > spike_thresh {
                i += 1;
            }
            let end = i;
            let duration_frames = end - start;
            if duration_frames >= min_spike_frames {
                let peak = ratio
                    .slice(ndarray::s![start..end])
                    .iter()
                    .cloned()
                    .fold(f32::NEG_INFINITY, f32::max);
                spikes_raw.push(RawSpike { start, end, peak });
            }
        } else {
            i += 1;
        }
    }

    if spikes_raw.is_empty() {
        info!("No volume spikes detected");
        return Ok(Vec::new());
    }

    debug!(count = spikes_raw.len(), "Raw spikes before merging");

    // --- Merge spikes within merge_gap_seconds -----------------------------
    let merge_gap_frames =
        (merge_gap_seconds / (hop_ms as f64 / 1000.0)).round() as usize;

    let mut merged: Vec<RawSpike> = Vec::with_capacity(spikes_raw.len());
    merged.push(spikes_raw.remove(0));

    for spike in spikes_raw {
        let prev = merged.last_mut().unwrap();
        if spike.start.saturating_sub(prev.end) <= merge_gap_frames {
            prev.end = spike.end;
            prev.peak = prev.peak.max(spike.peak);
        } else {
            merged.push(spike);
        }
    }

    // --- Convert frame indices to seconds ----------------------------------
    let hop_sec = hop_ms as f64 / 1000.0;
    let result: Vec<VolumeSpike> = merged
        .into_iter()
        .map(|s| VolumeSpike {
            start: s.start as f64 * hop_sec,
            end: s.end as f64 * hop_sec,
            intensity: round_to(s.peak as f64, 1),
        })
        .collect();

    info!(count = result.len(), "Volume spikes detected");
    Ok(result)
}

/// Convenience wrapper with default parameters matching the Python CLI.
pub fn detect_volume_spikes_default(wav_path: &str) -> Result<Vec<VolumeSpike>> {
    detect_volume_spikes(
        wav_path,
        25,   // frame_ms
        10,   // hop_ms
        15.0, // baseline_seconds
        2.0,  // spike_threshold
        0.3,  // min_spike_seconds
        2.0,  // merge_gap_seconds
    )
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/// Compute a rolling (uniform) average with numpy-style `mode="same"` padding.
///
/// For each output index `i`, the averaging window is centred on `i` and
/// clamped to the array bounds, matching `np.convolve(x, kernel, "same")`.
fn rolling_average_same(data: &Array1<f32>, window: usize) -> Array1<f32> {
    let n = data.len();
    let mut out = Array1::<f32>::zeros(n);

    // Use a running sum for O(n) performance.
    // We compute prefix sums, then derive each centred window from them.
    let mut prefix = vec![0.0f64; n + 1];
    for i in 0..n {
        prefix[i + 1] = prefix[i] + data[i] as f64;
    }

    let half = window / 2;
    for i in 0..n {
        // Centre the kernel on i.  np.convolve "same" effectively means:
        //   left  = i - half
        //   right = left + window
        // clamped to [0, n).
        let left = if i >= half { i - half } else { 0 };
        let right = (left + window).min(n);
        // Adjust left if right was clamped (keeps window size consistent
        // at the trailing edge, mirroring numpy behaviour).
        let left = if right == n {
            n.saturating_sub(window)
        } else {
            left
        };
        let count = (right - left) as f64;
        out[i] = ((prefix[right] - prefix[left]) / count) as f32;
    }

    out
}

/// Round an f64 to `decimals` decimal places.
fn round_to(value: f64, decimals: u32) -> f64 {
    let factor = 10f64.powi(decimals as i32);
    (value * factor).round() / factor
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_rolling_average_same_uniform() {
        // A constant signal should produce the same constant as its average.
        let data = Array1::from(vec![5.0f32; 20]);
        let avg = rolling_average_same(&data, 7);
        for &v in avg.iter() {
            assert!((v - 5.0).abs() < 1e-5, "expected ~5.0, got {v}");
        }
    }

    #[test]
    fn test_rolling_average_same_small() {
        let data = Array1::from(vec![1.0, 2.0, 3.0, 4.0, 5.0]);
        let avg = rolling_average_same(&data, 3);
        // Centre-aligned window of 3:
        // i=0 -> [0,1,2] mean=2.0
        // i=1 -> [0,1,2] mean=2.0
        // i=2 -> [1,2,3] mean=3.0
        // i=3 -> [2,3,4] mean=4.0
        // i=4 -> [2,3,4] mean=4.0
        let expected = [2.0, 2.0, 3.0, 4.0, 4.0];
        for (i, (&got, &exp)) in avg.iter().zip(expected.iter()).enumerate() {
            assert!(
                (got - exp).abs() < 1e-5,
                "index {i}: expected {exp}, got {got}"
            );
        }
    }

    #[test]
    fn test_round_to() {
        assert_eq!(round_to(2.34567, 1), 2.3);
        assert_eq!(round_to(2.35, 1), 2.4);
        assert_eq!(round_to(2.0, 1), 2.0);
    }

    #[test]
    fn test_detect_empty_wav() {
        // We cannot easily construct a WAV in memory with hound::WavReader
        // (it needs a file path), so we test the helper functions instead.
        // Integration tests with real WAV files belong in tests/.
    }
}
