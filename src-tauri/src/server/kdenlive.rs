// Kdenlive (Nuldrums fork) Shorts setup prompt. Counterpart to premiere.rs, but
// drives the fork's `org.kde.kdenlive.scripting` D-Bus interface via qdbus6 instead
// of the Premiere MCP. User-configurable banners and per-layer qtblend rects,
// serialized into system_state as a single JSON blob.

use serde::{Deserialize, Serialize};
use sqlx::SqlitePool;
use trik_klip_core::db;

const STATE_KEY: &str = "kdenlive_config";

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KdenliveConfig {
    /// Absolute path to the 1080x1920 30fps shorts template `.kdenlive` project
    /// that Step 1 of the prompt copies into the clip folder. May be empty until
    /// the user sets it.
    #[serde(default)]
    pub template_path: String,
    /// The two stacked copies of the main clip (webcam-on-top / content-on-bottom
    /// shorts layout). Each is placed on a video track and given a qtblend rect.
    pub clip_layers: Vec<ClipLayer>,
    /// Banner overlay images (Twitch / YouTube) imported for every clip.
    pub banners: Vec<BannerEntry>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ClipLayer {
    pub label: String,
    /// 1-based video track index from the bottom (V1 = 1). Matches addClipToTrack.
    pub video_track_index: u32,
    /// qtblend rect [x, y, w, h] in project pixels (top-left origin), for setClipTransform.
    pub rect: [i64; 4],
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BannerEntry {
    pub label: String, // e.g. "Twitch banner"
    pub path: String,  // absolute file path; may be empty until the user sets it
    pub video_track_index: u32,
    pub rect: [i64; 4],
}

impl Default for KdenliveConfig {
    fn default() -> Self {
        // Derived from the Adobe Premiere template (premiere.rs) for a 1920x1080
        // source in a 1080x1920 sequence:
        //   Premiere scale S% -> W=1920*S/100, H=1080*S/100
        //   Premiere position {px,py} is the clip CENTER -> rect X=px-W/2, Y=py-H/2
        //   V1: scale 198 / pos {1900, 860}   -> -1   -209  3802 2138
        //   V2: scale 234 / pos {-1163, -480} -> -3410 -1744 4493 2527
        Self {
            template_path: String::new(),
            clip_layers: vec![
                ClipLayer {
                    label: "Content (Premiere scale 198 / pos 1900,860)".into(),
                    video_track_index: 1,
                    rect: [-1, -209, 3802, 2138],
                },
                ClipLayer {
                    label: "Webcam (Premiere scale 234 / pos -1163,-480)".into(),
                    video_track_index: 2,
                    rect: [-3410, -1744, 4493, 2527],
                },
            ],
            banners: vec![
                BannerEntry {
                    label: "Twitch banner".into(),
                    path: String::new(),
                    video_track_index: 3,
                    rect: [0, 1760, 1080, 100],
                },
                BannerEntry {
                    label: "YouTube banner".into(),
                    path: String::new(),
                    video_track_index: 4,
                    rect: [0, 1760, 1080, 100],
                },
            ],
        }
    }
}

pub async fn load_config(pool: &SqlitePool) -> anyhow::Result<KdenliveConfig> {
    match db::get_system_state(pool, STATE_KEY).await? {
        Some(json) => Ok(serde_json::from_str(&json).unwrap_or_default()),
        None => Ok(KdenliveConfig::default()),
    }
}

pub async fn save_config(pool: &SqlitePool, cfg: &KdenliveConfig) -> anyhow::Result<()> {
    let json = serde_json::to_string(cfg)?;
    db::set_system_state(pool, STATE_KEY, &json).await?;
    Ok(())
}

// ---------------------------------------------------------------------------
// Prompt generator
// ---------------------------------------------------------------------------

const KDENLIVE_PROMPT_INTRO: &str = r#"Set up a vertical Shorts project in the Nuldrums Kdenlive fork by driving its
D-Bus scripting interface. You MUST actually run the commands — do not just
describe them. Drive Kdenlive with `qdbus6 org.kde.kdenlive.scripting /kdenlive <method> [args]`
and use shell tools only for file discovery and copying.

Context & known behaviors
* RUN KDENLIVE OFFSCREEN. Always launch with `QT_QPA_PLATFORM=offscreen` so its
  window never appears or steals focus on the user's desktop. The D-Bus scripting
  interface and renderFrame both work fully offscreen. The user opens the saved
  .kdenlive project normally when they want to review it.
* The scripting interface operates on the CURRENTLY OPEN project, so you first
  open a vertical 1080x1920 30fps project, then import + arrange over D-Bus.
* IMPORTS ARE ASYNC: importClip returns immediately, but the clip is not usable
  on the timeline until its producer finishes loading (~8-10s for a long mp4).
  After importClip, POLL addClipToTrack until it returns a positive id (it
  returns -12 "clip not in bin" until the producer is ready). Never assume it
  imported instantly.
* setClipTransform takes a qtblend rect "x y w h" (top-left origin, project px),
  NOT Premiere-style scale+position. It fills the rect with no distortion. There
  is NO position bug — it works reliably (unlike the Premiere UXP path).
* Timeline clip ids are reassigned whenever the project reloads. ALWAYS get live
  ids with `clipIdsOnTrack <videoTrackIndex>` right before transforming.
* Shut down with `quit` (clean, prompt-free) — never kill the process, or the
  next launch shows a crash-recovery dialog. Never rebuild/install Kdenlive
  while it is running.

Task
You are given a clip folder path containing a main .mp4 (same name as the
folder) plus slice_*.mp4 and visual_*.{jpg,png,webp} files.

CLIP FOLDER PATH: {clip_folder}

Step 1 — Open a vertical project
Copy the shorts template project into the clip folder named after the folder,
then open it:
  cp "{template_path}" "{clip_folder}/{sequence_name}.kdenlive"
  rm -f /tmp/kdenlivelock
  QT_QPA_PLATFORM=offscreen setsid kdenlive "{clip_folder}/{sequence_name}.kdenlive" >/tmp/kdenlive.log 2>&1 < /dev/null &
Wait until the service appears, then confirm the profile:
  until qdbus6 2>/dev/null | grep -q org.kde.kdenlive.scripting; do sleep 1; done
  qdbus6 org.kde.kdenlive.scripting /kdenlive projectInfo
projectInfo must report width=1080 height=1920 fps=30 docOpen=true.

Step 2 — Import the main clip
  qdbus6 org.kde.kdenlive.scripting /kdenlive importClip "{clip_folder}/MAIN.mp4"
(MAIN.mp4 = the .mp4 whose name matches the folder.)

Step 3 — Place the two stacked clip copies
For each layer below, poll addClipToTrack until it returns a positive clip id:
  for i in $(seq 1 15); do ID=$(qdbus6 org.kde.kdenlive.scripting /kdenlive addClipToTrack "MAIN.mp4" <track> 0); [ "$ID" -gt 0 ] 2>/dev/null && break; sleep 2; done
{clip_layer_steps}
Step 4 — Transform the two clip copies (fill / reframe)
Get live ids and apply the rects. For each layer:
  ID=$(qdbus6 org.kde.kdenlive.scripting /kdenlive clipIdsOnTrack <track>)
  qdbus6 org.kde.kdenlive.scripting /kdenlive setClipTransform $ID <x> <y> <w> <h>
{clip_layer_transforms}
Step 5 — Add visual B-roll stills
Import every visual_*.{jpg,png,webp} in the clip folder and place them back-to-back
on video track {visual_track} starting at frame 0 (use addClipToTrack; if a file
fails to import, skip it). These are the B-roll overlay stills.

{banner_steps}
Step {save_step} — Save and report
  qdbus6 org.kde.kdenlive.scripting /kdenlive save
Then quit the offscreen instance cleanly (it has no visible window):
  qdbus6 org.kde.kdenlive.scripting /kdenlive quit
Report: project path, the live clip ids per track, and the final track layout:
{track_layout}
The user opens "{clip_folder}/{sequence_name}.kdenlive" normally when they want to
review/finish it.

Notes
* Do not add slice_*.mp4 files to the timeline.
* Verify each step with renderFrame (saves the composited frame to a PNG you can
  inspect) before moving on if anything looks off.
"#;

pub fn build_prompt(cfg: &KdenliveConfig, clip_folder: &str, sequence_name: &str, template_path: &str) -> String {
    let clip_folder = clip_folder.replace('\\', "/");
    let banners = filter_valid_banners(&cfg.banners);

    // Step 3 — one addClipToTrack bullet per clip layer.
    let mut clip_layer_steps = String::new();
    for layer in &cfg.clip_layers {
        clip_layer_steps.push_str(&format!(
            "* {label}: addClipToTrack MAIN.mp4 {track} 0\n",
            label = layer.label,
            track = layer.video_track_index
        ));
    }

    // Step 4 — one setClipTransform bullet per clip layer.
    let mut clip_layer_transforms = String::new();
    for layer in &cfg.clip_layers {
        let [x, y, w, h] = layer.rect;
        clip_layer_transforms.push_str(&format!(
            "* {label} (track {track}): setClipTransform <id> {x} {y} {w} {h}\n",
            label = layer.label,
            track = layer.video_track_index,
            x = x,
            y = y,
            w = w,
            h = h
        ));
    }

    // Visual B-roll track = first free track above the clip layers.
    let max_clip_track = cfg.clip_layers.iter().map(|l| l.video_track_index).max().unwrap_or(2);
    let visual_track = max_clip_track + 1;

    // Banner steps — import, place, transform per configured banner.
    let mut banner_steps = String::new();
    let mut step_num = 6;
    for banner in &banners {
        let [x, y, w, h] = banner.rect;
        banner_steps.push_str(&format!(
            "Step {step} — Add {label}\n\
             * importClip \"{path}\"\n\
             * addClipToTrack \"{path}\" {track} 0  (poll until positive id)\n\
             * id=$(clipIdsOnTrack {track}); setClipTransform $id {x} {y} {w} {h}\n\n",
            step = step_num,
            label = banner.label,
            path = banner.path,
            track = banner.video_track_index,
            x = x,
            y = y,
            w = w,
            h = h
        ));
        step_num += 1;
    }
    let save_step = step_num;

    // Track layout summary.
    let mut track_layout = String::new();
    let mut layers_sorted = cfg.clip_layers.clone();
    layers_sorted.sort_by_key(|l| l.video_track_index);
    for layer in &layers_sorted {
        track_layout.push_str(&format!("  - V{}: {}\n", layer.video_track_index, layer.label));
    }
    track_layout.push_str(&format!("  - V{}: visual B-roll stills\n", visual_track));
    for banner in &banners {
        track_layout.push_str(&format!("  - V{}: {}\n", banner.video_track_index, banner.label));
    }
    let track_layout = track_layout.trim_end().to_string();

    KDENLIVE_PROMPT_INTRO
        .replace("{clip_folder}", &clip_folder)
        .replace("{sequence_name}", sequence_name)
        .replace("{template_path}", template_path)
        .replace("{clip_layer_steps}", clip_layer_steps.trim_end())
        .replace("{clip_layer_transforms}", clip_layer_transforms.trim_end())
        .replace("{visual_track}", &visual_track.to_string())
        .replace("{banner_steps}", &banner_steps)
        .replace("{save_step}", &save_step.to_string())
        .replace("{track_layout}", &track_layout)
}

fn filter_valid_banners(banners: &[BannerEntry]) -> Vec<&BannerEntry> {
    banners.iter().filter(|b| !b.path.trim().is_empty()).collect()
}
