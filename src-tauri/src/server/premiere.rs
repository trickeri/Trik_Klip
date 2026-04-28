// Premiere Pro setup prompt — user-configurable banners and track position
// overrides, serialized into system_state as a single JSON blob.

use serde::{Deserialize, Serialize};
use sqlx::SqlitePool;
use trik_klip_core::db;

const STATE_KEY: &str = "premiere_config";

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PremiereConfig {
    /// Ordered list of banner images that should be imported for every clip.
    /// Renders Steps 9, 10, … at tracks 6, 7, … (+1 Premiere offset applied).
    pub banners: Vec<BannerEntry>,
    /// Position overrides for clips the MCP agent places on the timeline.
    /// Reported at the end of the prompt so the user can punch them into
    /// Premiere's Effect Controls panel manually (documented Adobe UXP API
    /// limitation — position cannot be set via the official MCP).
    pub positions: Vec<TrackPosition>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BannerEntry {
    pub label: String, // e.g. "Twitch banner"
    pub path: String,  // absolute file path; may be empty until the user sets it
    /// Optional x/y position to emit in the end-of-prompt reminder list.
    /// `None` → renders as "position as needed" so the user can decide later.
    #[serde(default)]
    pub position: Option<[f64; 2]>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TrackPosition {
    pub label: String,
    pub track_index: u32,
    pub x: f64,
    pub y: f64,
}

impl Default for PremiereConfig {
    fn default() -> Self {
        Self {
            banners: vec![
                BannerEntry {
                    label: "Twitch banner".into(),
                    path: String::new(),
                    position: None,
                },
                BannerEntry {
                    label: "YouTube banner".into(),
                    path: String::new(),
                    position: None,
                },
            ],
            // Match the legacy Python defaults.
            positions: vec![
                TrackPosition {
                    label: "Main clip (scale 198)".into(),
                    track_index: 0,
                    x: 1900.0,
                    y: 860.0,
                },
                TrackPosition {
                    label: "Main clip (scale 234)".into(),
                    track_index: 1,
                    x: -1163.0,
                    y: -480.0,
                },
            ],
        }
    }
}

pub async fn load_config(pool: &SqlitePool) -> anyhow::Result<PremiereConfig> {
    match db::get_system_state(pool, STATE_KEY).await? {
        Some(json) => Ok(serde_json::from_str(&json).unwrap_or_default()),
        None => Ok(PremiereConfig::default()),
    }
}

pub async fn save_config(pool: &SqlitePool, cfg: &PremiereConfig) -> anyhow::Result<()> {
    let json = serde_json::to_string(cfg)?;
    db::set_system_state(pool, STATE_KEY, &json).await?;
    Ok(())
}

// ---------------------------------------------------------------------------
// Prompt generator
// ---------------------------------------------------------------------------

const PREMIERE_PROMPT_INTRO: &str = r#"Execute the following steps using your available MCP
tools to set up a Premiere Pro Shorts project. You MUST call the tools
described in each step — do NOT just describe what you would do. Actually
invoke create_project, get_project_info, import_media, etc.

Use Adobe's official Premiere Pro MCP connector (the mcp__pr-mcp__* tools
exposed by the "Adobe for creativity" connector in Claude) for all Premiere
operations, and Filesystem MCP (mcp__Windows-MCP__FileSystem) for file
discovery only. Do NOT use any third-party or custom Premiere plugin —
only the official Adobe-provided pr-mcp tool namespace.

Context & Known Behaviors
* create_project will time out — this is expected behavior. Always follow it
  immediately with get_project_info to confirm the project was created
  successfully.
* When a Shorts sequence is created via the official connector it starts
  with 0 empty tracks — clips are added directly by targeting track indices.
* KNOWN OFFSET: When add_media_to_sequence targets an index that requires
  Premiere to auto-create gap tracks, the resulting track index as reported
  by the API may be 1 lower than requested (e.g. requesting index 5 may
  land on index 4). To compensate, all post-gap track indices in this
  prompt are set 1 higher than the desired final position.
* set_clip_transform scale works reliably. Position does NOT — this is a
  documented Adobe UXP API limitation in the official connector, not a bug
  in this tool. Do not attempt to set position via set_clip_transform; set
  it manually in Premiere's Effect Controls panel after the script completes.

Task
You will be given a clip folder path. The folder contains a main .mp4 file
(the full-length clip) with the same name as the folder, plus additional slice
files.

CLIP FOLDER PATH: {clip_folder}

Step 1 — Create the project
Call create_project with:
* directory_path: the clip folder path
* project_name: the folder name (same as the .prproj filename, without
  extension)
Then immediately call get_project_info to confirm it opened. Note the project
ID and sequence list.

Step 2 — Discover and import media
Use Filesystem MCP to list the clip folder. Find the main full-length .mp4
file (the one matching the folder name), all slice_*.mp4 files, and all
visual_*.jpg / visual_*.png / visual_*.webp files (visual aid images).

Import media in TWO separate import_media calls to avoid timeouts:

Call 1 — Video files:
* The main full-length .mp4 from the clip folder
* ALL slice_*.mp4 files found in the clip folder

If the first import call times out, that is expected (same as
create_project). Do NOT retry — proceed to Call 2.

Call 2 — Image files:
* ALL visual_*.jpg, visual_*.png, and visual_*.webp files found in the clip folder (visual aid images for B-roll)
{banner_import_list}

If this call also times out, do NOT retry. Proceed to get_project_info
to verify which files were imported successfully.

IMPORTANT: import_media may time out on large batches — this is normal
and does NOT mean the import failed. Never retry a timed-out import.
Always move forward and verify with get_project_info.

If any image files failed to import (missing from the project after
get_project_info), skip them entirely — do not retry and do not let
missing images block the rest of the setup. Just proceed with whatever
media imported successfully.

Step 3 — Create the Shorts sequence
Call create_shorts_sequence with sequence name {sequence_name} (where the
number matches the clip number). This creates a 1080x1920, 30fps vertical
sequence.

Step 4 — Add the full clip to Track 1 (video index 0)
Call add_media_to_sequence:
* item_name: the main .mp4 filename
* video_track_index: 0
* audio_track_index: 0
* insertion_time_ticks: 0

Step 5 — Add the full clip again to Track 2 (video index 1)
Call add_media_to_sequence again with the same clip:
* item_name: the main .mp4 filename
* video_track_index: 1
* audio_track_index: 1
* insertion_time_ticks: 0

Step 6 — Set scale on Track 1 clip
Call set_clip_transform:
* video_track_index: 0
* track_item_index: 0
* scale: 198

Step 7 — Set scale on Track 2 clip
Call set_clip_transform:
* video_track_index: 1
* track_item_index: 0
* scale: 234

Step 8 — Add visual images to video track index 5
IMPORTANT: Do NOT use add_media_on_new_track — it appends to the next
available index which does not leave the 2-track gap we need.
Instead, use add_media_to_sequence which places media on an exact index
and Premiere will auto-create any missing tracks in between.

Add ALL visual_* files (visual_01, visual_02, etc.) to video track index 5,
placed sequentially one after another starting at insertion_time_ticks: 0.
For each visual image, call add_media_to_sequence:
* item_name: the visual filename (e.g. visual_01.jpg)
* video_track_index: 5
* audio_track_index: 2
* insertion_time_ticks: 0 for the first image; for subsequent images, use
  the end_time_ticks of the previous image so they sit back-to-back.
* overwrite: false

This forces Premiere to create empty tracks at indices 2, 3, and 4, then
places the first visual on index 5. The 2 empty gap tracks (indices 2-3)
plus the visual images track (index 4 once the offset settles) are all
created before the banners.

If a visual file was not imported (timed out or failed during Step 2),
skip it — do not retry the import. Just continue with the remaining
visuals that are available in the project.

{banner_steps}
Step {notify_step} — Notify completion
Report back with:
* Project path
* Sequence name and ID
* Final track layout:
{track_layout}
* Reminder that position must be set manually in Effect Controls:
{position_list}
* Note: Track indices above are the intended layout. Due to Premiere's
  known offset behavior, the API may report indices shifted by 1. Verify
  the visual layout in the Premiere UI matches the intended structure.

Notes
* Only use Filesystem/Windows-MCP for listing files and discovering paths.
  Never use them to click, navigate, or interact with the Premiere UI.
* If create_project times out, that is normal — proceed to get_project_info
  without retrying.
* Do not add slice files to the timeline in this task.
"#;

pub fn build_prompt(cfg: &PremiereConfig, clip_folder: &str, sequence_name: &str) -> String {
    let banners = filter_valid_banners(&cfg.banners);

    // Step 2 — Image file import list (bullet per banner + the shared visual_* line).
    let banner_import_list = if banners.is_empty() {
        String::new()
    } else {
        banners
            .iter()
            .map(|b| format!("* {}", b.path))
            .collect::<Vec<_>>()
            .join("\n")
    };

    // Banner steps start at 9 and each banner gets its own step targeting
    // track index 6 + i (+1 offset accounted for).
    let mut banner_steps = String::new();
    for (i, banner) in banners.iter().enumerate() {
        let step_num = 9 + i;
        let track_idx = 6 + i;
        let audio_idx = 3 + i;
        let filename = banner_filename(&banner.path);
        banner_steps.push_str(&format!(
            "Step {step} — Add {label} on video track index {track}\n\
             Call add_media_to_sequence:\n\
             * item_name: {filename}\n\
             * video_track_index: {track}\n\
             * audio_track_index: {audio}\n\
             * insertion_time_ticks: 0\n\n",
            step = step_num,
            label = banner.label,
            track = track_idx,
            audio = audio_idx,
            filename = filename
        ));
    }

    let notify_step = 9 + banners.len();

    // Track layout bullets — fixed for the first 5 tracks, then one line per
    // banner. Labels come from config for the main clip rows.
    let clip_0_label = cfg
        .positions
        .iter()
        .find(|p| p.track_index == 0)
        .map(|p| p.label.as_str())
        .unwrap_or("Main clip (scale 198)");
    let clip_1_label = cfg
        .positions
        .iter()
        .find(|p| p.track_index == 1)
        .map(|p| p.label.as_str())
        .unwrap_or("Main clip (scale 234)");

    let mut track_layout = String::new();
    track_layout.push_str(&format!("  - Video 0: {}\n", clip_0_label));
    track_layout.push_str(&format!("  - Video 1: {}\n", clip_1_label));
    track_layout.push_str("  - Video 2: (empty)\n");
    track_layout.push_str("  - Video 3: (empty)\n");
    track_layout.push_str("  - Video 4: Visual images (B-roll stills)\n");
    for (i, banner) in banners.iter().enumerate() {
        track_layout.push_str(&format!("  - Video {}: {}\n", 5 + i, banner.label));
    }
    // Trim the trailing newline so joining flows cleanly.
    let track_layout = track_layout.trim_end().to_string();

    // Position reminders — one line per configured override, with the final
    // (post-offset) track index so the user can find the clip in the UI.
    // Any position whose track_index >= 6 is interpreted as a banner position;
    // we shift those down by 1 to reflect the post-offset landing index.
    let mut position_list = String::new();
    for p in &cfg.positions {
        let shown_track = if p.track_index >= 6 {
            p.track_index - 1
        } else {
            p.track_index
        };
        position_list.push_str(&format!(
            "   * Video {} ({}): position {{{x}, {y}}}\n",
            shown_track,
            p.label,
            x = p.x,
            y = p.y
        ));
    }
    // Emit one line per banner. If the user configured an explicit x/y on
    // the banner row, use it; else if a matching TrackPosition override
    // already exists we already emitted it above; otherwise fall back to
    // "position as needed".
    for (i, banner) in banners.iter().enumerate() {
        let banner_track = 5 + i; // post-offset
        let already_in_positions = cfg
            .positions
            .iter()
            .any(|p| p.track_index == (6 + i as u32) || p.track_index == banner_track as u32);
        if already_in_positions {
            continue;
        }
        match banner.position {
            Some([x, y]) => position_list.push_str(&format!(
                "   * Video {} ({}): position {{{}, {}}}\n",
                banner_track, banner.label, x, y
            )),
            None => position_list.push_str(&format!(
                "   * Video {} ({}): position as needed\n",
                banner_track, banner.label
            )),
        }
    }
    let position_list = position_list.trim_end().to_string();

    let clip_folder_fwd = clip_folder.replace('\\', "/");
    PREMIERE_PROMPT_INTRO
        .replace("{clip_folder}", &clip_folder_fwd)
        .replace("{sequence_name}", sequence_name)
        .replace("{banner_import_list}", &banner_import_list)
        .replace("{banner_steps}", &banner_steps)
        .replace("{notify_step}", &notify_step.to_string())
        .replace("{track_layout}", &track_layout)
        .replace("{position_list}", &position_list)
}

fn filter_valid_banners(banners: &[BannerEntry]) -> Vec<&BannerEntry> {
    banners
        .iter()
        .filter(|b| !b.path.trim().is_empty())
        .collect()
}

fn banner_filename(path: &str) -> String {
    std::path::Path::new(path)
        .file_name()
        .and_then(|s| s.to_str())
        .map(|s| s.to_string())
        .unwrap_or_else(|| path.to_string())
}
