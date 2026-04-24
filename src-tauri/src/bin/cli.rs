use std::path::PathBuf;
use std::sync::Arc;

use anyhow::{Context, Result};
use clap::{Parser, Subcommand};
use serde_json::json;

use trik_klip_core::{
    chunking, clip_scoring, ffmpeg,
    llm::{self, LlmProvider},
    models::{AnalysisChunk, ClipSuggestion, TranscriptSegment, VolumeSpike, fmt_time},
    prompts::{self, build_editing_prompt, parse_cut_list},
    spike_detection, whisper,
};

#[derive(Parser)]
#[command(name = "trik-klip", about = "Trik Klip — long-form stream to short-form clip pipeline")]
struct Cli {
    #[command(subcommand)]
    command: Commands,

    /// Path to ffmpeg binary
    #[arg(long, global = true, default_value = "ffmpeg")]
    ffmpeg_path: String,

    /// Path to ffprobe binary
    #[arg(long, global = true, default_value = "ffprobe")]
    ffprobe_path: String,

    /// Path to whisper-cli binary
    #[arg(long, global = true, default_value = "whisper-cli")]
    whisper_cli_path: String,

    /// Path to whisper GGML model file
    #[arg(long, global = true, default_value = "ggml-base.bin")]
    model_path: String,
}

#[derive(Subcommand)]
enum Commands {
    /// Extract mono 16kHz WAV audio from a video file
    ExtractAudio {
        mp4_file: PathBuf,
        #[arg(long, short)]
        output: Option<PathBuf>,
        #[arg(long)]
        audio_track: Option<u32>,
    },
    /// Detect volume spikes in extracted audio
    DetectSpikes {
        wav_file: PathBuf,
        #[arg(long, short)]
        output: Option<PathBuf>,
        #[arg(long, default_value_t = 2.0)]
        spike_threshold: f64,
        #[arg(long, default_value_t = 15.0)]
        baseline_seconds: f64,
        #[arg(long, default_value_t = 0.3)]
        min_spike_seconds: f64,
        #[arg(long, default_value_t = 2.0)]
        merge_gap_seconds: f64,
    },
    /// Transcribe audio using whisper.cpp
    Transcribe {
        wav_file: PathBuf,
        #[arg(long, short)]
        output: Option<PathBuf>,
        #[arg(long, default_value = "en")]
        language: String,
    },
    /// Chunk a transcript into analysis windows
    Chunk {
        transcript_json: PathBuf,
        #[arg(long, short)]
        output: Option<PathBuf>,
        #[arg(long, default_value_t = 8)]
        window_minutes: u32,
        #[arg(long, default_value_t = 1)]
        overlap_minutes: u32,
        #[arg(long)]
        spikes: Option<PathBuf>,
    },
    /// Run LLM analysis on transcript chunks to find clip candidates
    Analyze {
        chunks_json: PathBuf,
        #[arg(long, short)]
        output: Option<PathBuf>,
        #[arg(long, default_value_t = 10)]
        top_n: usize,
        #[arg(long, default_value_t = 3.0)]
        padding_minutes: f64,
        #[arg(long, default_value = "claude_code")]
        provider: String,
        #[arg(long)]
        model: Option<String>,
        #[arg(long)]
        api_key: Option<String>,
        #[arg(long)]
        base_url: Option<String>,
        #[arg(long)]
        max_workers: Option<usize>,
        #[arg(long)]
        custom_prompt: Vec<String>,
        /// Total duration of the source media (seconds); auto-detected if omitted
        #[arg(long)]
        total_duration: Option<f64>,
        /// Path to the source media file for auto-detecting duration
        #[arg(long)]
        source_file: Option<PathBuf>,
    },
    /// Extract clip MP4s and assets from source video
    Extract {
        mp4_file: PathBuf,
        clips_json: PathBuf,
        #[arg(long, short, default_value = "./clips")]
        output_dir: PathBuf,
        #[arg(long)]
        transcript: Option<PathBuf>,
        #[arg(long)]
        audio_track: Option<u32>,
    },
    /// Generate editing slices from an extracted clip
    GenerateSlices {
        clip_dir: PathBuf,
        #[arg(long)]
        editing_notes: Option<String>,
        #[arg(long)]
        premiere: bool,
        #[arg(long, default_value = "claude_code")]
        provider: String,
        #[arg(long)]
        model: Option<String>,
        #[arg(long)]
        api_key: Option<String>,
        #[arg(long)]
        base_url: Option<String>,
    },
    /// List available LLM providers and models
    Providers,
    /// Machine-readable directory of all commands
    CommandList,
    /// Run the full pipeline (transcribe + analyze + extract)
    Run {
        mp4_file: PathBuf,
        #[arg(long, short, default_value = "./clips")]
        output_dir: PathBuf,
        #[arg(long, default_value = "en")]
        language: String,
        #[arg(long, default_value_t = 10)]
        top_n: usize,
        #[arg(long, default_value_t = 3.0)]
        padding_minutes: f64,
        #[arg(long, default_value = "claude_code")]
        provider: String,
        #[arg(long)]
        model: Option<String>,
        #[arg(long)]
        api_key: Option<String>,
        #[arg(long)]
        base_url: Option<String>,
        #[arg(long)]
        max_workers: Option<usize>,
        #[arg(long)]
        custom_prompt: Vec<String>,
        #[arg(long)]
        audio_track: Option<u32>,
    },
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/// Print a JSON error envelope to stdout and exit.
fn exit_error(msg: &str, code: i32) -> ! {
    let envelope = json!({ "error": msg, "exit_code": code });
    println!("{}", serde_json::to_string_pretty(&envelope).unwrap());
    std::process::exit(code);
}

/// Resolve the LLM model name: use the explicit flag, or fall back to the
/// provider's default from the registry.
fn resolve_model(provider_key: &str, explicit: &Option<String>) -> String {
    if let Some(m) = explicit {
        return m.clone();
    }
    let providers = llm::list_providers();
    providers
        .get(provider_key)
        .map(|p| p.default_model.to_string())
        .unwrap_or_else(|| "claude-sonnet-4-6".to_string())
}

/// Create an LLM provider instance.
fn create_provider(
    provider_key: &str,
    api_key: &Option<String>,
    base_url: &Option<String>,
) -> Result<Box<dyn LlmProvider>> {
    let key = api_key.as_deref().unwrap_or("");
    let url = base_url.as_deref().unwrap_or("");
    let client = reqwest::Client::new();
    llm::make_provider(provider_key, key, url, client, None)
}

/// Default output path: replace extension on input path.
fn default_output(input: &PathBuf, new_ext: &str) -> PathBuf {
    input.with_extension(new_ext)
}

/// Read and deserialize a JSON file.
fn read_json_file<T: serde::de::DeserializeOwned>(path: &PathBuf) -> Result<T> {
    let data = std::fs::read_to_string(path)
        .with_context(|| format!("Failed to read {}", path.display()))?;
    serde_json::from_str(&data)
        .with_context(|| format!("Failed to parse JSON from {}", path.display()))
}

/// Write a value as pretty JSON to a file.
fn write_json_file<T: serde::Serialize>(path: &PathBuf, value: &T) -> Result<()> {
    let json = serde_json::to_string_pretty(value)?;
    std::fs::write(path, &json)
        .with_context(|| format!("Failed to write {}", path.display()))?;
    Ok(())
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

#[tokio::main]
async fn main() {
    let cli = Cli::parse();

    let result = run_command(cli).await;
    if let Err(e) = result {
        exit_error(&format!("{:#}", e), 1);
    }
}

async fn run_command(cli: Cli) -> Result<()> {
    match cli.command {
        // -----------------------------------------------------------------
        // 1. ExtractAudio
        // -----------------------------------------------------------------
        Commands::ExtractAudio {
            mp4_file,
            output,
            audio_track,
        } => {
            let output_wav = output.unwrap_or_else(|| default_output(&mp4_file, "wav"));
            let mp4_str = mp4_file.to_string_lossy().to_string();
            let wav_str = output_wav.to_string_lossy().to_string();

            ffmpeg::extract_audio(
                &cli.ffmpeg_path,
                &cli.ffprobe_path,
                &mp4_str,
                &wav_str,
                audio_track,
                None,
                None,
            )
            .await?;

            let result = json!({
                "status": "ok",
                "output": wav_str,
            });
            println!("{}", serde_json::to_string_pretty(&result)?);
        }

        // -----------------------------------------------------------------
        // 2. DetectSpikes
        // -----------------------------------------------------------------
        Commands::DetectSpikes {
            wav_file,
            output,
            spike_threshold,
            baseline_seconds,
            min_spike_seconds,
            merge_gap_seconds,
        } => {
            let wav_str = wav_file.to_string_lossy().to_string();
            let output_path = output.unwrap_or_else(|| default_output(&wav_file, "spikes.json"));

            // detect_volume_spikes is sync (CPU-bound), run on blocking thread
            let spikes = tokio::task::spawn_blocking(move || {
                spike_detection::detect_volume_spikes(
                    &wav_str,
                    25,  // frame_ms
                    10,  // hop_ms
                    baseline_seconds,
                    spike_threshold,
                    min_spike_seconds,
                    merge_gap_seconds,
                )
            })
            .await??;

            write_json_file(&output_path, &spikes)?;

            let result = json!({
                "status": "ok",
                "spike_count": spikes.len(),
                "output": output_path.to_string_lossy(),
            });
            println!("{}", serde_json::to_string_pretty(&result)?);
        }

        // -----------------------------------------------------------------
        // 3. Transcribe
        // -----------------------------------------------------------------
        Commands::Transcribe {
            wav_file,
            output,
            language,
        } => {
            let wav_str = wav_file.to_string_lossy().to_string();
            let output_path =
                output.unwrap_or_else(|| default_output(&wav_file, "transcript.json"));

            let segments = whisper::transcribe(
                &cli.whisper_cli_path,
                &cli.model_path,
                &wav_str,
                &language,
                None,
                None,
                None,
            )
            .await?;

            write_json_file(&output_path, &segments)?;

            let result = json!({
                "status": "ok",
                "segment_count": segments.len(),
                "output": output_path.to_string_lossy(),
            });
            println!("{}", serde_json::to_string_pretty(&result)?);
        }

        // -----------------------------------------------------------------
        // 4. Chunk
        // -----------------------------------------------------------------
        Commands::Chunk {
            transcript_json,
            output,
            window_minutes,
            overlap_minutes,
            spikes,
        } => {
            let segments: Vec<TranscriptSegment> = read_json_file(&transcript_json)?;
            let output_path =
                output.unwrap_or_else(|| default_output(&transcript_json, "chunks.json"));

            let mut chunks = chunking::chunk_transcript(
                &segments,
                window_minutes as f64,
                overlap_minutes as f64,
            );

            if let Some(spikes_path) = spikes {
                let spike_data: Vec<VolumeSpike> = read_json_file(&spikes_path)?;
                chunking::annotate_chunks_with_spikes(&mut chunks, &spike_data);
            }

            write_json_file(&output_path, &chunks)?;

            let result = json!({
                "status": "ok",
                "chunk_count": chunks.len(),
                "output": output_path.to_string_lossy(),
            });
            println!("{}", serde_json::to_string_pretty(&result)?);
        }

        // -----------------------------------------------------------------
        // 5. Analyze
        // -----------------------------------------------------------------
        Commands::Analyze {
            chunks_json,
            output,
            top_n,
            padding_minutes,
            provider,
            model,
            api_key,
            base_url,
            max_workers,
            custom_prompt,
            total_duration,
            source_file,
        } => {
            let chunks: Vec<AnalysisChunk> = read_json_file(&chunks_json)?;
            let output_path =
                output.unwrap_or_else(|| default_output(&chunks_json, "clips.json"));

            let model_name = resolve_model(&provider, &model);
            let llm_provider: Arc<dyn LlmProvider> =
                Arc::from(create_provider(&provider, &api_key, &base_url)?);

            let padding_seconds = padding_minutes * 60.0;
            let workers = max_workers.unwrap_or(3);

            // Determine total duration
            let duration = if let Some(d) = total_duration {
                d
            } else if let Some(ref src) = source_file {
                ffmpeg::get_duration(&cli.ffprobe_path, &src.to_string_lossy())
                    .await
                    .unwrap_or(0.0)
            } else {
                // Estimate from chunk data
                chunks
                    .iter()
                    .map(|c| c.window_end)
                    .fold(0.0_f64, f64::max)
            };

            let custom_refs: Vec<String> = custom_prompt;
            let custom_slice: Option<&[String]> = if custom_refs.is_empty() {
                None
            } else {
                Some(&custom_refs)
            };

            let clips = clip_scoring::find_clips(
                &chunks,
                llm_provider,
                &model_name,
                top_n,
                padding_seconds,
                duration,
                workers,
                custom_slice,
                None,
            )
            .await;

            write_json_file(&output_path, &clips)?;

            let result = json!({
                "status": "ok",
                "clip_count": clips.len(),
                "output": output_path.to_string_lossy(),
            });
            println!("{}", serde_json::to_string_pretty(&result)?);
        }

        // -----------------------------------------------------------------
        // 6. Extract
        // -----------------------------------------------------------------
        Commands::Extract {
            mp4_file,
            clips_json,
            output_dir,
            transcript,
            audio_track,
        } => {
            let clips: Vec<ClipSuggestion> = read_json_file(&clips_json)?;
            let mp4_str = mp4_file.to_string_lossy().to_string();

            // Optionally load transcript for editing prompts
            let segments: Option<Vec<TranscriptSegment>> = transcript
                .as_ref()
                .and_then(|p| read_json_file(p).ok());

            std::fs::create_dir_all(&output_dir)
                .with_context(|| format!("Failed to create output dir {}", output_dir.display()))?;

            let mut extracted = 0u32;

            for clip in &clips {
                let clip_name = format!(
                    "clip_{:02}_{}_{}",
                    clip.rank,
                    fmt_time(clip.clip_start).replace(':', "-"),
                    fmt_time(clip.clip_end).replace(':', "-"),
                );
                let clip_dir = output_dir.join(&clip_name);
                std::fs::create_dir_all(&clip_dir)?;

                // Extract clip MP4
                let clip_mp4 = clip_dir.join(format!("{}.mp4", clip_name));
                let duration = clip.clip_end - clip.clip_start;
                ffmpeg::extract_clip(
                    &cli.ffmpeg_path,
                    &mp4_str,
                    &clip_mp4.to_string_lossy(),
                    clip.clip_start,
                    duration,
                    audio_track,
                    None,
                )
                .await?;

                // Save clip metadata
                write_json_file(&clip_dir.join("clip.json"), clip)?;

                // Save per-clip transcript excerpt
                if let Some(ref all_segs) = segments {
                    let clip_segs: Vec<TranscriptSegment> = all_segs
                        .iter()
                        .filter(|s| s.start >= clip.clip_start && s.start < clip.clip_end)
                        .cloned()
                        .collect();

                    write_json_file(&clip_dir.join("transcript.json"), &clip_segs)?;

                    // Build and save editing prompt
                    let editing_prompt = build_editing_prompt(clip, &clip_segs);
                    std::fs::write(clip_dir.join("editing_prompt.txt"), &editing_prompt)?;
                }

                extracted += 1;
            }

            let result = json!({
                "status": "ok",
                "extracted_count": extracted,
                "output_dir": output_dir.to_string_lossy(),
            });
            println!("{}", serde_json::to_string_pretty(&result)?);
        }

        // -----------------------------------------------------------------
        // 7. GenerateSlices
        // -----------------------------------------------------------------
        Commands::GenerateSlices {
            clip_dir,
            editing_notes,
            premiere: _premiere,
            provider,
            model,
            api_key,
            base_url,
        } => {
            // Read the clip metadata
            let clip: ClipSuggestion =
                read_json_file(&clip_dir.join("clip.json"))?;

            // Read editing prompt (generated during Extract)
            let prompt_path = clip_dir.join("editing_prompt.txt");
            let mut prompt = std::fs::read_to_string(&prompt_path)
                .with_context(|| {
                    format!("No editing_prompt.txt in {}", clip_dir.display())
                })?;

            // Append user editing notes if provided
            if let Some(notes) = &editing_notes {
                prompt.push_str(&format!(
                    "\n\nADDITIONAL EDITING NOTES FROM USER:\n{}\n",
                    notes
                ));
            }

            // Send prompt to LLM
            let model_name = resolve_model(&provider, &model);
            let llm_provider = create_provider(&provider, &api_key, &base_url)?;

            let response = llm_provider
                .message(
                    &model_name,
                    &prompt,
                    "You are an expert short-form video editor.",
                    2000,
                )
                .await?;

            // Save the raw LLM response
            let response_path = clip_dir.join("edit_plan.txt");
            std::fs::write(&response_path, &response.text)?;

            // Parse the cut list
            let cuts = parse_cut_list(&response.text);

            if cuts.is_empty() {
                let result = json!({
                    "status": "ok",
                    "slice_count": 0,
                    "message": "LLM returned no parseable cut list entries",
                    "edit_plan": response_path.to_string_lossy(),
                });
                println!("{}", serde_json::to_string_pretty(&result)?);
                return Ok(());
            }

            // Save parsed cuts
            write_json_file(&clip_dir.join("cuts.json"), &cuts)?;

            // Find the clip MP4 file
            let clip_mp4 = find_clip_mp4(&clip_dir)?;
            let clip_mp4_str = clip_mp4.to_string_lossy().to_string();

            // Optionally load transcript for snap_cut_end
            let segments: Vec<TranscriptSegment> = read_json_file(&clip_dir.join("transcript.json"))
                .unwrap_or_default();

            let clip_duration = clip.clip_end - clip.clip_start;
            let slices_dir = clip_dir.join("slices");
            std::fs::create_dir_all(&slices_dir)?;

            let mut slice_count = 0u32;

            for (i, cut) in cuts.iter().enumerate() {
                // Convert source-relative timestamps to clip-relative
                let seek = (cut.start - clip.clip_start).max(0.0);
                let mut end = cut.end - clip.clip_start;

                // Snap cut end to sentence boundary if transcript available
                if !segments.is_empty() {
                    end = prompts::snap_cut_end(
                        cut.end,
                        &segments,
                        0.5,
                        Some(clip.clip_end),
                    ) - clip.clip_start;
                }

                let dur = (end - seek).min(clip_duration - seek).max(0.0);
                if dur < 1.0 {
                    continue;
                }

                let slice_path = slices_dir.join(format!("slice_{:02}.mp4", i + 1));

                ffmpeg::extract_slice(
                    &cli.ffmpeg_path,
                    &clip_mp4_str,
                    &slice_path.to_string_lossy(),
                    seek,
                    dur,
                    None,
                )
                .await?;

                slice_count += 1;
            }

            let result = json!({
                "status": "ok",
                "slice_count": slice_count,
                "edit_plan": response_path.to_string_lossy(),
                "slices_dir": slices_dir.to_string_lossy(),
            });
            println!("{}", serde_json::to_string_pretty(&result)?);
        }

        // -----------------------------------------------------------------
        // 8. Providers
        // -----------------------------------------------------------------
        Commands::Providers => {
            let providers = llm::list_providers();
            let mut entries: Vec<serde_json::Value> = providers
                .iter()
                .map(|(key, info)| {
                    json!({
                        "key": key,
                        "label": info.label,
                        "env_key": info.env_key,
                        "default_model": info.default_model,
                        "models": info.models,
                        "base_url": info.base_url,
                    })
                })
                .collect();
            entries.sort_by(|a, b| {
                a["key"].as_str().unwrap_or("").cmp(b["key"].as_str().unwrap_or(""))
            });

            let result = json!({
                "status": "ok",
                "providers": entries,
            });
            println!("{}", serde_json::to_string_pretty(&result)?);
        }

        // -----------------------------------------------------------------
        // 9. CommandList
        // -----------------------------------------------------------------
        Commands::CommandList => {
            let commands = json!({
                "status": "ok",
                "commands": [
                    {
                        "name": "extract-audio",
                        "description": "Extract mono 16kHz WAV audio from a video file",
                        "args": ["mp4_file"],
                        "options": ["--output", "--audio-track"]
                    },
                    {
                        "name": "detect-spikes",
                        "description": "Detect volume spikes in extracted audio",
                        "args": ["wav_file"],
                        "options": ["--output", "--spike-threshold", "--baseline-seconds", "--min-spike-seconds", "--merge-gap-seconds"]
                    },
                    {
                        "name": "transcribe",
                        "description": "Transcribe audio using whisper.cpp",
                        "args": ["wav_file"],
                        "options": ["--output", "--language"]
                    },
                    {
                        "name": "chunk",
                        "description": "Chunk a transcript into analysis windows",
                        "args": ["transcript_json"],
                        "options": ["--output", "--window-minutes", "--overlap-minutes", "--spikes"]
                    },
                    {
                        "name": "analyze",
                        "description": "Run LLM analysis on transcript chunks to find clip candidates",
                        "args": ["chunks_json"],
                        "options": ["--output", "--top-n", "--padding-minutes", "--provider", "--model", "--api-key", "--base-url", "--max-workers", "--custom-prompt", "--total-duration", "--source-file"]
                    },
                    {
                        "name": "extract",
                        "description": "Extract clip MP4s and assets from source video",
                        "args": ["mp4_file", "clips_json"],
                        "options": ["--output-dir", "--transcript"]
                    },
                    {
                        "name": "generate-slices",
                        "description": "Generate editing slices from an extracted clip",
                        "args": ["clip_dir"],
                        "options": ["--editing-notes", "--premiere", "--provider", "--model", "--api-key", "--base-url"]
                    },
                    {
                        "name": "providers",
                        "description": "List available LLM providers and models",
                        "args": [],
                        "options": []
                    },
                    {
                        "name": "command-list",
                        "description": "Machine-readable directory of all commands",
                        "args": [],
                        "options": []
                    },
                    {
                        "name": "run",
                        "description": "Run the full pipeline (extract audio, detect spikes, transcribe, chunk, analyze, extract clips)",
                        "args": ["mp4_file"],
                        "options": ["--output-dir", "--language", "--top-n", "--padding-minutes", "--provider", "--model", "--api-key", "--base-url", "--max-workers", "--custom-prompt", "--audio-track"]
                    }
                ]
            });
            println!("{}", serde_json::to_string_pretty(&commands)?);
        }

        // -----------------------------------------------------------------
        // 10. Run (full pipeline)
        // -----------------------------------------------------------------
        Commands::Run {
            mp4_file,
            output_dir,
            language,
            top_n,
            padding_minutes,
            provider,
            model,
            api_key,
            base_url,
            max_workers,
            custom_prompt,
            audio_track,
        } => {
            let mp4_str = mp4_file.to_string_lossy().to_string();

            std::fs::create_dir_all(&output_dir)?;

            // --- Step 1: Extract audio ---
            eprintln!("[1/6] Extracting audio...");
            let wav_path = output_dir.join("audio.wav");
            let wav_str = wav_path.to_string_lossy().to_string();

            ffmpeg::extract_audio(
                &cli.ffmpeg_path,
                &cli.ffprobe_path,
                &mp4_str,
                &wav_str,
                audio_track,
                None,
                None,
            )
            .await?;

            // --- Step 2: Detect spikes ---
            eprintln!("[2/6] Detecting volume spikes...");
            let wav_str_clone = wav_str.clone();
            let spikes = tokio::task::spawn_blocking(move || {
                spike_detection::detect_volume_spikes_default(&wav_str_clone)
            })
            .await??;

            let spikes_path = output_dir.join("spikes.json");
            write_json_file(&spikes_path, &spikes)?;
            eprintln!("       Found {} spikes", spikes.len());

            // --- Step 3: Transcribe ---
            eprintln!("[3/6] Transcribing audio...");
            let segments = whisper::transcribe(
                &cli.whisper_cli_path,
                &cli.model_path,
                &wav_str,
                &language,
                None,
                None,
                None,
            )
            .await?;

            let transcript_path = output_dir.join("transcript.json");
            write_json_file(&transcript_path, &segments)?;
            eprintln!("       {} transcript segments", segments.len());

            // --- Step 4: Chunk + annotate ---
            eprintln!("[4/6] Chunking transcript...");
            let mut chunks = chunking::chunk_transcript(&segments, 8.0, 1.0);
            chunking::annotate_chunks_with_spikes(&mut chunks, &spikes);

            let chunks_path = output_dir.join("chunks.json");
            write_json_file(&chunks_path, &chunks)?;
            eprintln!("       {} chunks", chunks.len());

            // --- Step 5: Analyze ---
            eprintln!("[5/6] Analyzing chunks with LLM...");
            let model_name = resolve_model(&provider, &model);
            let llm_provider: Arc<dyn LlmProvider> =
                Arc::from(create_provider(&provider, &api_key, &base_url)?);

            let padding_seconds = padding_minutes * 60.0;
            let workers = max_workers.unwrap_or(3);

            let total_duration =
                ffmpeg::get_duration(&cli.ffprobe_path, &mp4_str)
                    .await
                    .unwrap_or(0.0);

            let custom_slice: Option<&[String]> = if custom_prompt.is_empty() {
                None
            } else {
                Some(&custom_prompt)
            };

            let clips = clip_scoring::find_clips(
                &chunks,
                llm_provider,
                &model_name,
                top_n,
                padding_seconds,
                total_duration,
                workers,
                custom_slice,
                None,
            )
            .await;

            let clips_path = output_dir.join("clips.json");
            write_json_file(&clips_path, &clips)?;
            eprintln!("       {} clips found", clips.len());

            // --- Step 6: Extract clips ---
            eprintln!("[6/6] Extracting clips...");
            let mut extracted = 0u32;

            for clip in &clips {
                let clip_name = format!(
                    "clip_{:02}_{}_{}",
                    clip.rank,
                    fmt_time(clip.clip_start).replace(':', "-"),
                    fmt_time(clip.clip_end).replace(':', "-"),
                );
                let clip_dir = output_dir.join(&clip_name);
                std::fs::create_dir_all(&clip_dir)?;

                let clip_mp4 = clip_dir.join(format!("{}.mp4", clip_name));
                let duration = clip.clip_end - clip.clip_start;

                ffmpeg::extract_clip(
                    &cli.ffmpeg_path,
                    &mp4_str,
                    &clip_mp4.to_string_lossy(),
                    clip.clip_start,
                    duration,
                    audio_track,
                    None,
                )
                .await?;

                write_json_file(&clip_dir.join("clip.json"), clip)?;

                // Per-clip transcript
                let clip_segs: Vec<TranscriptSegment> = segments
                    .iter()
                    .filter(|s| s.start >= clip.clip_start && s.start < clip.clip_end)
                    .cloned()
                    .collect();

                write_json_file(&clip_dir.join("transcript.json"), &clip_segs)?;

                let editing_prompt = build_editing_prompt(clip, &clip_segs);
                std::fs::write(clip_dir.join("editing_prompt.txt"), &editing_prompt)?;

                extracted += 1;
            }

            eprintln!("       {} clips extracted", extracted);

            let result = json!({
                "status": "ok",
                "pipeline": "complete",
                "spike_count": spikes.len(),
                "segment_count": segments.len(),
                "chunk_count": chunks.len(),
                "clip_count": clips.len(),
                "extracted_count": extracted,
                "output_dir": output_dir.to_string_lossy(),
            });
            println!("{}", serde_json::to_string_pretty(&result)?);
        }
    }

    Ok(())
}

/// Find the .mp4 file inside a clip directory.
fn find_clip_mp4(clip_dir: &PathBuf) -> Result<PathBuf> {
    for entry in std::fs::read_dir(clip_dir)? {
        let entry = entry?;
        let path = entry.path();
        if path.extension().map(|e| e == "mp4").unwrap_or(false) {
            return Ok(path);
        }
    }
    anyhow::bail!(
        "No .mp4 file found in clip directory {}",
        clip_dir.display()
    )
}
