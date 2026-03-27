# Trik_Klip

**Automatically find the best short-form clips in long-form video streams using AI.**

Trik_Klip analyzes MP4 video files -- streams, podcasts, interviews, VODs -- and identifies the moments most likely to succeed as short-form content. It transcribes the audio locally, sends the transcript to an LLM of your choice for scoring, and ranks every potential clip by viral potential. You then pick the clips you want and extract them as standalone MP4 files, ready for editing.

No cloud transcription. No subscriptions. One executable.

---

## Table of Contents

- [Requirements](#requirements)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [How It Works](#how-it-works)
- [Application Tabs](#application-tabs)
  - [Analysis](#analysis-tab)
  - [File Paths](#file-paths-tab)
  - [Run Mode](#run-mode-tab)
  - [Load Existing Clips](#load-existing-clips-tab)
  - [Clip Extraction Panel](#clip-extraction-panel)
  - [Settings](#settings-tab)
  - [Editing](#editing-tab)
  - [Log](#log-tab)
- [Whisper Model Guide](#whisper-model-guide)
- [Content Types](#content-types)
- [LLM Provider Setup](#llm-provider-setup)
- [Tips and Best Practices](#tips-and-best-practices)
- [Troubleshooting](#troubleshooting)

---

## Requirements

- **Windows 10 or Windows 11**
- **An API key for at least one LLM provider**, or a local Ollama installation (see [LLM Provider Setup](#llm-provider-setup))
- A GPU is not required but will significantly speed up transcription with larger Whisper models

ffmpeg is bundled with the release. You do not need to install it separately.

---

## Installation

1. Download the latest `.zip` file from the [GitHub Releases](../../releases) page.
2. Extract the zip to any folder on your computer (for example, `C:\Trik_Klip`).
3. Double-click **Trik_Klip.exe** to launch the application.
4. On first run, go to the **Settings** tab and configure at least one LLM provider with your API key.
5. You are ready to analyze videos.

No installer is needed. To uninstall, simply delete the folder.

---

## Quick Start

1. Launch **Trik_Klip.exe**.
2. In the **Settings** tab, add an API key for your preferred LLM provider (Claude, ChatGPT, Gemini, or Grok) or configure Ollama.
3. In the **Analysis** tab, drag and drop an MP4 file onto the window or use the file picker to select one.
4. Choose a Whisper model (start with **small** if unsure).
5. Click **Run**. The app will extract audio, transcribe it, analyze the transcript with AI, and present ranked clip suggestions.
6. In the **Clip Extraction Panel**, check the clips you want and click extract. Each selected clip is saved as its own MP4 file.

---

## How It Works

Trik_Klip runs a multi-stage pipeline on your video:

1. **Audio Extraction** -- ffmpeg pulls the audio track from the MP4 file.
2. **Transcription** -- OpenAI Whisper runs locally on your machine to convert speech to text. No audio is sent to the cloud.
3. **Windowed Analysis** -- The transcript is split into overlapping 5-minute windows so the AI can evaluate each segment in context.
4. **AI Scoring** -- Each window is sent to your chosen LLM, which scores it for viral potential, assigns a content type, and suggests a clip title.
5. **Ranking and Deduplication** -- Overlapping or near-duplicate results are merged, and the best clips are ranked by score.
6. **Clip Extraction** -- You select the clips you want, and ffmpeg extracts them as individual MP4 files using lossless video copy (fast, no re-encoding, no quality loss).

---

## Application Tabs

### Analysis Tab

This is the main control panel for processing a video.

- **MP4 File** -- Drag and drop a file or click to browse. This is the source video to analyze.
- **Whisper Model** -- Choose the transcription model: tiny, base, small, medium, or large. See the [Whisper Model Guide](#whisper-model-guide) for details.
- **Top Clips** -- How many top-ranked clips to return after analysis.
- **Window Size** -- The length of each transcript window sent to the LLM (default is 5 minutes).
- **Padding Minutes** -- Extra time added before and after each clip's timestamps during extraction, giving you editing headroom (default is 3 minutes).
- **Audio Track** -- If your video has multiple audio tracks, select which one to use for transcription.

### File Paths Tab

Configure where output files are saved. Paths auto-fill based on the video filename, but you can customize each one:

- **Transcript file** -- Where the Whisper transcription is saved.
- **Extracted audio file** -- Where the intermediate audio file is stored.
- **Results JSON** -- Where the full analysis results (scores, timestamps, titles) are saved.
- **Clip export folder** -- Where extracted MP4 clips are written.

Saving these paths is useful when re-running analysis on the same video or sharing results.

### Run Mode Tab

Three modes let you skip stages you have already completed:

- **Full Pipeline** -- Extract audio, transcribe, analyze, and rank. Use this the first time you process a video.
- **Extract + Transcribe Only** -- Extract audio and generate a transcript without running LLM analysis. Useful if you want to review the transcript first or plan to analyze it later.
- **Analyze Existing Transcript Only** -- Skip audio extraction and transcription entirely. Point the app at a transcript file you already have and run it through the LLM for scoring. This is the fastest way to compare results across different LLM providers.

### Load Existing Clips Tab

If you have previously generated a clip extraction script or results file, you can reload it here. This lets you come back to a past analysis and extract additional clips without re-running the full pipeline.

### Clip Extraction Panel

After analysis completes, this panel displays every clip the AI identified. Each entry shows:

- **Rank** -- Position in the overall ranking.
- **Title** -- A suggested clip title generated by the AI.
- **Virality Score** -- A score from 1 to 10 indicating estimated viral potential.
- **Timestamps** -- Start and end times within the original video.
- **Content Type** -- The category assigned by the AI (Story, Advice, Moment, etc.).

Each clip has a checkbox. Use **Select All** or **Deselect All** for bulk actions, or pick individual clips. Click **Extract** to save the selected clips as separate MP4 files.

### Settings Tab

Manage your LLM provider profiles here. You can configure multiple providers and switch between them.

Supported providers:

| Provider | Requires API Key | Notes |
|---|---|---|
| Anthropic (Claude) | Yes | Get a key at [console.anthropic.com](https://console.anthropic.com/) |
| OpenAI (ChatGPT) | Yes | Get a key at [platform.openai.com](https://platform.openai.com/) |
| Google (Gemini) | Yes | Get a key at [aistudio.google.com](https://aistudio.google.com/) |
| xAI (Grok) | Yes | Get a key at [console.x.ai](https://console.x.ai/) |
| Ollama (Local) | No | Requires Ollama installed on your machine |

You can save multiple profiles (for example, one for Claude and one for Gemini) and switch between them to compare results.

### Editing Tab

Advanced tools for refining clips after extraction:

- **Per-section cut lists** -- Define precise cut points within a clip to remove dead air, off-topic tangents, or other unwanted sections.
- **Image search and download** -- Search for and download images to use as thumbnails or overlays.
- **Premiere Pro prompt generation** -- Generate editing prompts formatted for Adobe Premiere Pro workflows.

### Log Tab

Displays real-time output from the pipeline as it runs. Useful for monitoring progress, checking for warnings, and diagnosing issues.

---

## Whisper Model Guide

Whisper is the speech-to-text engine that runs locally on your computer. Larger models produce better transcriptions but require more memory and processing time.

| Model | Speed | Accuracy | RAM Usage | GPU Recommended? |
|---|---|---|---|---|
| tiny | Fastest | Lowest | ~1 GB | No |
| base | Fast | Moderate | ~1 GB | No |
| small | Moderate | Good | ~2 GB | No |
| medium | Slow | High | ~5 GB | Yes |
| large | Slowest | Highest | ~10 GB | Yes |

**Recommendation:** Start with **small** for a good balance of speed and accuracy. Use **tiny** or **base** for quick tests. Use **medium** or **large** when transcription quality is critical and you have the hardware for it.

---

## Content Types

The AI categorizes each potential clip into one of the following types:

- **Story** -- A narrative segment with a strong hook, buildup, and payoff. These tend to hold viewer attention well.
- **Advice** -- Actionable tips, wisdom, or how-to information. High share potential when the advice is specific and useful.
- **Moment** -- A surprising, emotional, or memorable reaction. These are often the most immediately engaging clips.
- **Debate** -- A heated discussion or disagreement between participants. Conflict drives engagement.
- **Rant** -- A passionate, extended monologue on a topic. Works well when the speaker is charismatic and the topic resonates.
- **Revelation** -- A shocking disclosure, realization, or plot twist in the conversation. High replay value.

---

## LLM Provider Setup

You need at least one LLM provider configured to analyze transcripts. Here is how to set up each option:

### Cloud Providers (API Key Required)

1. Create an account with your chosen provider.
2. Generate an API key from their developer console.
3. In Trik_Klip, go to **Settings**, select the provider, paste your API key, and save the profile.

API usage will be billed by your provider according to their pricing. A typical 2-hour video costs a few cents to analyze.

### Ollama (Free, Local, No API Key)

Ollama lets you run LLMs entirely on your own machine at no cost.

1. Download and install Ollama from [ollama.com](https://ollama.com/).
2. Open a terminal and pull a model:
   ```
   ollama pull qwen3.5:27b
   ```
3. In Trik_Klip, go to **Settings**, select **Ollama** as the provider, and save. No API key is needed.

Ollama requires sufficient RAM and ideally a GPU to run larger models. Smaller models like `qwen3.5:14b` will work on most modern machines.

---

## Tips and Best Practices

- **Save your transcripts.** Transcription is the slowest step. Once you have a transcript, you can re-analyze it as many times as you want without waiting for Whisper again.

- **Compare LLM providers.** Use the "Analyze Existing Transcript Only" run mode to send the same transcript to different providers and compare their clip suggestions. Different models often surface different moments.

- **Clips include padding by default.** Each extracted clip adds approximately 3 minutes of padding before and after the identified timestamps. This gives you editing headroom so you can choose the perfect in and out points.

- **Extraction is fast and lossless.** Clips are extracted using ffmpeg stream copy, which means no re-encoding. The process takes seconds regardless of clip length, and there is zero quality loss.

- **Start with a shorter video for testing.** If this is your first time using Trik_Klip, try a 30-60 minute video to get familiar with the workflow before processing multi-hour streams.

- **Check the Log tab if something seems stuck.** The log shows exactly where the pipeline is in the process. Whisper transcription of long videos can take a while, especially with larger models.

---

## Troubleshooting

**The app does not start.**
Make sure you extracted the full zip contents, not just the exe. The application depends on files in the same folder.

**Whisper transcription is very slow.**
Try a smaller model (tiny or base) for faster results, or use a machine with a dedicated GPU. Transcription speed depends heavily on hardware.

**Analysis returns no clips.**
Verify your API key is correct in the Settings tab. Check the Log tab for error messages from the LLM provider.

**Extracted clips have slightly different start/end times than shown.**
ffmpeg seeks to the nearest keyframe when extracting without re-encoding. This can shift timestamps by a few seconds. The padding helps account for this.

**Windows SmartScreen blocks the application.**
Click "More info" and then "Run anyway." This warning appears because the application is not code-signed. It is safe to run.

---

## License and Credits

Trik_Klip uses the following open-source components:

- [OpenAI Whisper](https://github.com/openai/whisper) for local speech-to-text transcription
- [ffmpeg](https://ffmpeg.org/) for audio extraction and clip export

---

*Trik_Klip -- Find the best clips in any stream, automatically.*
