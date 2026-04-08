# Release Guide — Trik_Klip

Releases are **fully automated** by GitHub Actions (`.github/workflows/release.yml`).
The workflow triggers on a published GitHub release and handles everything end-to-end.

> **Note:** The legacy `BUILD.md` in this repo describes the old PyInstaller-based
> Python build and is no longer relevant to the current Rust/Tauri version.

## To cut a release

Three steps:

1. **Bump the version** in BOTH `src-tauri/tauri.conf.json` **and** `package.json`
   (they must match). Only the third number (patch) changes for a normal release — increment
   it by **1**. Examples:
   - `0.1.0` → `0.1.1`
   - `0.1.9` → `0.1.10`
   - `0.1.99` → `0.1.100`

   Do **not** zero-pad (`0.1.07` is wrong — leading zeros get stripped by tooling).

2. **Commit and push** to `main`:
   ```bash
   git add src-tauri/tauri.conf.json package.json
   git commit -m "Bump version to X.X.X"
   git push origin main
   ```

3. **Create the GitHub release** to trigger the workflow:
   ```bash
   gh release create vX.X.X --title "Trik_Klip vX.X.X" --notes "What changed in this release"
   ```

Watch the build with `gh run watch <run-id>` (find the ID via `gh run list --limit 1`).

Or just use `/deploy` from Claude Code — it walks through all of this interactively and is the preferred method.

## What the workflow does

1. Checks out the repo on a `windows-latest` GitHub Actions runner
2. Runs `scripts/fetch-resources.ps1` to download the ~470 MB of runtime binaries
   from upstream sources (these aren't committed — see "Runtime resources" below)
3. Runs `npm ci` + `npm run tauri build` to produce the Rust release binaries
4. Assembles a portable zip: `trik-klip.exe` + `trik-klip-cli.exe` + `resources/` folder
5. Computes SHA-256 and file size of the zip
6. Uploads the zip to Cloudflare R2 at
   `s3://nuldrums-releases/releases/trik-klip/X.X.X/windows-x86_64.zip`
7. POSTs a release manifest to `https://nuldrums.world/api/admin/title-releases`
   with `set_active: false` — the new release lands as a **draft** on the website
8. Attaches the zip to the GitHub Release for direct download

## Promoting a draft to active

New releases land in draft status so you can test them before pushing to launcher users.

1. Go to `https://nuldrums.world/admin/titles`
2. Expand the Trik_Klip row
3. Scroll to the Releases section
4. Find the new version in the releases table
5. Change its status dropdown from `draft` to `active`

Flipping a release to active automatically yanks any prior active release for the
same platform, so users always see exactly one active version per platform.

## Secrets the workflow needs

These must be set as GitHub repository secrets on `trickeri/Trik_Klip`
(Settings → Secrets and variables → Actions → New repository secret):

| Secret | What it is |
|---|---|
| `R2_ACCESS_KEY_ID` | Cloudflare R2 Account API token — Access Key ID |
| `R2_SECRET_ACCESS_KEY` | Cloudflare R2 Account API token — Secret Access Key |
| `R2_ENDPOINT` | `https://<cloudflare-account-id>.r2.cloudflarestorage.com` |
| `TITLE_RELEASE_API_KEY` | Shared secret, must match the same env var on the Nuldrums website deployment |

## Runtime resources (ffmpeg, whisper.cpp, model)

Trik_Klip needs four categories of runtime binaries at execution time:

| File(s) | Purpose | Source |
|---|---|---|
| `ffmpeg.exe`, `ffprobe.exe` | Audio/video extraction | BtbN FFmpeg-Builds (GitHub Releases) |
| `whisper-cli.exe` + ggml DLLs | Local speech-to-text (CPU build) | whisper.cpp release (GitHub Releases) |
| `ggml-base.bin` | Whisper "base" model weights | HuggingFace (`ggerganov/whisper.cpp`) |

These total ~470 MB and are **not committed to the repo**. Instead,
`scripts/fetch-resources.ps1` downloads them from pinned upstream URLs into
`src-tauri/resources/`. The script is idempotent — re-running it skips files that
already exist locally.

**Run it once after cloning:**
```powershell
.\scripts\fetch-resources.ps1
```

Or from git bash:
```bash
powershell -File scripts/fetch-resources.ps1
```

The CI/CD workflow runs this same script on every build.

### Bumping the bundled versions

Edit the `*_VERSION` / `*_URL` variables at the top of `scripts/fetch-resources.ps1`
and commit the change. Delete the cached files in `src-tauri/resources/` locally if
you want to force a re-fetch; CI will pick up the new version on the next release.

### CPU vs GPU-accelerated whisper.cpp

The fetch script pulls the **CPU build** of whisper.cpp (`whisper-bin-x64.zip`).
This is the most portable and works on any Windows machine, but transcription will
be slower than the Vulkan or CUDA builds you may be using locally.

If you want to ship a GPU-accelerated build, swap the `$WHISPER_ASSET` value in
`fetch-resources.ps1` to one of the CUDA variants published alongside each
whisper.cpp release:
- `whisper-cublas-12.4.0-bin-x64.zip` (NVIDIA CUDA 12.4)
- `whisper-cublas-11.8.0-bin-x64.zip` (NVIDIA CUDA 11.8)
- `whisper-blas-bin-x64.zip` (CPU with BLAS SIMD — middle ground, still CPU-only)

Note that CUDA builds require a matching CUDA runtime on the end user's system,
which limits who can run it. The Vulkan build used in local dev is not published
as a prebuilt release asset — it has to be built from source, which would add
significant complexity to the CI workflow.

## How auto-update for Trik_Klip works

Trik_Klip itself does **not** have an in-app auto-updater. Updates are pushed
through the Nuldrums launcher:

1. User launches Nuldrums Launcher
2. Launcher fetches the catalog and sees Trik_Klip has a newer active release
3. Launcher offers to update/re-download the title
4. Launcher downloads the new zip from R2, verifies SHA-256, and extracts to
   the install directory, replacing the old files

So the flow is: cut a release here → flip it to active in the website admin →
launcher users get the update on their next catalog refresh.

## Troubleshooting

**Workflow fails at the "Register release with website" step with a 401.**
The `TITLE_RELEASE_API_KEY` secret on this repo doesn't match the env var on the
Nuldrums website deployment in Coolify. Check both, make sure they're identical.

**Workflow fails at "Upload to Cloudflare R2" with an auth error.**
The `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` secrets are wrong or have been
rolled. Create a new API token in the Cloudflare R2 dashboard and update both
secrets.

**Workflow fails at "Fetch runtime resources" with a 404.**
An upstream release URL has moved. Check the latest release tags at
`https://github.com/ggml-org/whisper.cpp/releases` and
`https://github.com/BtbN/FFmpeg-Builds/releases`, update the URLs in
`scripts/fetch-resources.ps1`, commit, and re-trigger the release.

**Workflow succeeds but launcher users don't see the new version.**
The release landed as a draft. Go to `/admin/titles`, expand Trik_Klip, and
flip the new release from draft to active.
