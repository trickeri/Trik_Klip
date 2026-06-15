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
    /// Timeline placement + opacity fade, all in frames @ the project fps (30).
    /// start_frame: where the banner begins on the timeline; duration_frames: how
    /// long it stays; fade_in_frames / fade_out_frames: opacity ramps at the
    /// banner's start / end (0 = no fade on that edge).
    pub start_frame: i64,
    pub duration_frames: i64,
    pub fade_in_frames: i64,
    pub fade_out_frames: i64,
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
                // YouTube shows first: solid 0-5s, then a 1s fade-out (6s total).
                BannerEntry {
                    label: "YouTube banner".into(),
                    path: String::new(),
                    video_track_index: 4,
                    rect: [0, 1760, 1080, 100],
                    start_frame: 0,
                    duration_frames: 180, // 6s @30fps
                    fade_in_frames: 0,
                    fade_out_frames: 30, // 1s fade-out at the 5s mark
                },
                // Twitch takes over at the 5s mark: fades in over 1s, runs to the
                // 60s mark (typical Shorts length).
                BannerEntry {
                    label: "Twitch banner".into(),
                    path: String::new(),
                    video_track_index: 3,
                    rect: [0, 1760, 1080, 100],
                    start_frame: 150,      // 5s @30fps
                    duration_frames: 1650, // 5s -> 60s
                    fade_in_frames: 30,    // 1s fade-in (crossfades with YouTube's fade-out)
                    fade_out_frames: 0,
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

Step 1 — Create a vertical project FROM SCRATCH (no template)
Launch Kdenlive offscreen with no document, wait for the scripting service, then
create a new project on the Vertical HD 30fps preset and save it into the clip
folder. Discover the MLT profile path with a glob so it survives MLT version bumps:
  rm -f /tmp/kdenlivelock
  QT_QPA_PLATFORM=offscreen setsid kdenlive --no-welcome >/tmp/kdenlive.log 2>&1 < /dev/null &
  until qdbus6 2>/dev/null | grep -q org.kde.kdenlive.scripting; do sleep 1; done
  PROFILE=$(ls /usr/share/mlt*/profiles/vertical_hd_30 2>/dev/null | head -1)
  qdbus6 org.kde.kdenlive.scripting /kdenlive newProject "$PROFILE" "{clip_folder}/{sequence_name}.kdenlive"
  qdbus6 org.kde.kdenlive.scripting /kdenlive projectInfo
projectInfo must report width=1080 height=1920 fps=30 docOpen=true. If width/height
are swapped or fps is wrong, $PROFILE was empty — find the correct vertical 1080x1920
30fps profile under /usr/share/mlt*/profiles and re-run newProject before continuing.

Step 1b — Ensure enough video tracks
A fresh project may have fewer than the {needed_tracks} video tracks this layout
needs. Add tracks until there are enough:
  while [ "$(qdbus6 org.kde.kdenlive.scripting /kdenlive videoTrackCount)" -lt {needed_tracks} ]; do
    qdbus6 org.kde.kdenlive.scripting /kdenlive addVideoTrack; done

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
    // Highest video track index any element lands on -> how many tracks the fresh
    // project must have before we start placing clips.
    let needed_tracks = cfg
        .clip_layers
        .iter()
        .map(|l| l.video_track_index)
        .chain(banners.iter().map(|b| b.video_track_index))
        .chain(std::iter::once(visual_track))
        .max()
        .unwrap_or(visual_track);

    // Banner steps — import, place at start_frame, stretch to duration, then apply
    // the rect + opacity fade. setClipFade keeps position/size fixed at x,y,w,h and
    // ramps opacity at the clip edges, so the two banners crossfade at the handoff.
    let mut banner_steps = String::new();
    let mut step_num = 6;
    for banner in &banners {
        let [x, y, w, h] = banner.rect;
        banner_steps.push_str(&format!(
            "Step {step} — Add {label} (start {start}f, {dur}f long, fade in {fin}f / out {fout}f)\n\
             * importClip \"{path}\"\n\
             * addClipToTrack \"{path}\" {track} {start}  (poll until positive id)\n\
             * id=$(clipIdsOnTrack {track}); resizeClip $id {dur}\n\
             * setClipFade $id {x} {y} {w} {h} {fin} {fout}\n\n",
            step = step_num,
            label = banner.label,
            path = banner.path,
            track = banner.video_track_index,
            start = banner.start_frame,
            dur = banner.duration_frames,
            fin = banner.fade_in_frames,
            fout = banner.fade_out_frames,
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
        .replace("{needed_tracks}", &needed_tracks.to_string())
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
