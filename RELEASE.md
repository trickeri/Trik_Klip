# Release Guide — Trik_Klip

Trik_Klip uses a **local-build, CI-distribute** architecture.

The Tauri app + Rust binaries are built on the developer's Windows machine (this one)
because Trik_Klip depends on the Vulkan-accelerated build of whisper.cpp, which is not
available as a prebuilt CI-friendly artifact. The GitHub Actions workflow only handles
the distribution side: downloading the pre-built zip from the release assets, uploading
to Cloudflare R2, and registering the release with the Nuldrums website.

## To cut a release

The preferred way is to use `/deploy` from Claude Code, which walks through everything
interactively. The manual flow is:

### 1. Pre-flight checks

Verify `target/release/resources/` is populated with the runtime binaries:

```bash
ls -la target/release/resources/
```

You should see: `ffmpeg.exe`, `ffprobe.exe`, `whisper-cli.exe`, `whisper.dll`,
`ggml.dll`, `ggml-base.dll`, `ggml-cpu.dll`, `ggml-vulkan.dll`, `ggml-base.bin`.
If any are missing, the zipped release will be broken. Restore them before continuing —
these files must already be in place on your machine, they are not committed to the repo.

### 2. Bump the version

Update **both** `src-tauri/tauri.conf.json` **and** `package.json` to the new version.
They must match. Only the third number (patch) changes for a normal release —
increment it by **1**. Examples:

- `0.1.0` → `0.1.1`
- `0.1.9` → `0.1.10`
- `0.1.99` → `0.1.100`

Do **not** zero-pad (`0.1.07` is wrong — leading zeros get stripped by tooling).

### 3. Build locally

```bash
npm run tauri build
```

This takes ~5-10 minutes on a reasonable machine. The output lands at
`target/release/trik-klip.exe` plus supporting files in `target/release/`.
The existing `target/release/resources/` folder is reused (not rebuilt).

### 4. Assemble the portable zip

```bash
VERSION=<new version>
ZIP_NAME="trik-klip_${VERSION}_windows-x86_64.zip"

rm -rf portable-staging
mkdir -p portable-staging/resources
cp target/release/trik-klip.exe portable-staging/
cp target/release/trik-klip-cli.exe portable-staging/
cp target/release/resources/* portable-staging/resources/

rm -f "$ZIP_NAME"
powershell -Command "Compress-Archive -Path 'portable-staging/*' -DestinationPath '$ZIP_NAME' -Force"

ls -lh "$ZIP_NAME"
```

The zip's final structure is:
```
trik-klip.exe
trik-klip-cli.exe
resources/
  ffmpeg.exe
  ffprobe.exe
  whisper-cli.exe
  whisper.dll
  ggml.dll
  ggml-base.dll
  ggml-cpu.dll
  ggml-vulkan.dll
  ggml-base.bin
```

This matches the layout the app expects at runtime — resources live in a sibling
`resources/` folder next to the exe.

### 5. Commit, push, and create the GitHub release

```bash
git add src-tauri/tauri.conf.json package.json
git commit -m "Bump version to $VERSION"
git push origin main

gh release create "v$VERSION" \
  --title "Trik_Klip v$VERSION" \
  --notes "What changed in this release" \
  "$ZIP_NAME"
```

Attaching the zip as a positional arg to `gh release create` uploads it as a release
asset. This is what the distribution workflow downloads.

### 6. Watch the distribution workflow

```bash
gh run list --limit 1
gh run watch <run-id>
```

The distribution workflow is fast (~30 seconds) — no compilation step. It just
downloads the zip, computes the hash, uploads to R2, and POSTs to the website.

### 7. Promote the draft to active

New releases land in **draft** status so you can verify they work before pushing
them to launcher users.

1. Go to `https://nuldrums.world/admin/titles`
2. Expand the Trik_Klip row
3. Scroll to the Releases section
4. Find the new version in the releases table
5. Change its status dropdown from `draft` to `active`

Flipping a release to active automatically yanks any prior active release for the
same platform, so users always see exactly one active version per platform.

## What the CI workflow actually does

The `.github/workflows/release.yml` workflow runs on `ubuntu-latest` (no Windows
build tools needed since there's no build step) and only does distribution:

1. Parses the version from the release tag (strips the `v` prefix)
2. Downloads the portable zip from the release assets via `gh release download`
3. Computes SHA-256 and size of the zip
4. Uploads the zip to `s3://nuldrums-releases/releases/trik-klip/X.X.X/windows-x86_64.zip`
5. POSTs a release manifest to `https://nuldrums.world/api/admin/title-releases` with
   `set_active: false`

Total runtime: ~30 seconds.

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

| File(s) | Purpose |
|---|---|
| `ffmpeg.exe`, `ffprobe.exe` | Audio/video extraction |
| `whisper-cli.exe` + ggml DLLs (including `ggml-vulkan.dll`) | Local GPU-accelerated speech-to-text |
| `ggml-base.bin` | Whisper "base" model weights |

These files live in `target/release/resources/` on this machine. They are:

- **Not committed to the repo** (see `.gitignore` — the `src-tauri/resources/*` patterns are a defense-in-depth)
- **Not rebuilt by `npm run tauri build`** — Cargo just compiles the Rust code; the resources are expected to already be in place from a previous manual setup
- **Part of every portable zip** — the deploy flow copies them from `target/release/resources/` into the zip alongside `trik-klip.exe`

### If the resources folder gets wiped

If `target/` is cleaned (via `cargo clean` or similar) and the resources folder is gone,
you need to restore it before building a new release. The binaries were originally
acquired as follows (document as you go):

- **ffmpeg / ffprobe**: Gyan's full Windows build (full_build variant) from
  https://www.gyan.dev/ffmpeg/builds/ — whatever current release is fine, any
  reasonably recent version works
- **whisper.cpp with Vulkan**: built from source with `cmake -DGGML_VULKAN=1 ..` —
  the whisper.cpp repo at https://github.com/ggml-org/whisper.cpp has the instructions.
  Requires the Vulkan SDK installed
- **ggml-base.bin**: downloaded from
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin

Drop all of them into `target/release/resources/` before running a release build.

## Why this flow and not CI-based builds

Most projects build in CI because it gives reproducibility and lets multiple developers
release from anywhere. Trik_Klip deliberately doesn't because:

1. **This is a single-developer project** on a single machine. Reproducibility from the
   repo alone isn't a constraint worth paying for.
2. **The Vulkan-enabled whisper.cpp isn't available as a prebuilt release asset.**
   Building it in CI would require the Vulkan SDK, cmake, MSVC build tools, and
   ~10-15 extra minutes per CI run. Doing it locally sidesteps all of that.
3. **The local build environment is already proven to work.** Moving it to CI would
   risk "works on my machine, breaks in CI" drift.
4. **Deploy is faster.** Local build (~5-10 min) + distribution CI (~30 sec) beats
   a full CI build (~15-20 min with Vulkan SDK setup).

The tradeoff is that if this machine dies mid-release, the release has to wait until
the dev environment is rebuilt on a new machine. For a one-dev project, that's acceptable.

## How auto-update for Trik_Klip works

Trik_Klip itself does **not** have an in-app auto-updater. Updates are pushed through
the Nuldrums launcher:

1. User launches Nuldrums Launcher
2. Launcher fetches the catalog and sees Trik_Klip has a newer active release
3. Launcher offers to update or re-download the title
4. Launcher downloads the new zip from R2, verifies SHA-256, and extracts to the
   install directory, replacing the old files

So the flow is: cut a release here → flip it to active in the website admin → launcher
users get the update on their next catalog refresh.

## Troubleshooting

**`npm run tauri build` fails.**
Stop and investigate before touching git. Common causes: missing Rust toolchain, stale
`target/` cache (`cargo clean` and retry), missing `node_modules` (`npm ci`).

**Portable zip is missing files.**
The resources folder is probably not fully populated. Check
`ls target/release/resources/` — it should contain 9 files (ffmpeg, ffprobe, whisper-cli,
whisper.dll, four ggml .dll files, ggml-base.bin).

**CI workflow fails at "Download portable zip from release assets".**
The zip wasn't attached to the GH release. Re-run `gh release create` with the zip as
a positional argument, or use `gh release upload vX.X.X path/to/zip` to add it to an
existing release. The workflow will need to be re-triggered — the easiest way is to
delete and recreate the release, or manually trigger the workflow if you've added
workflow_dispatch.

**CI workflow fails at "Register release with website" with a 401.**
The `TITLE_RELEASE_API_KEY` secret on this repo doesn't match the env var on the
Nuldrums website deployment in Coolify. Check both, make sure they're identical.

**CI workflow fails at "Upload zip to Cloudflare R2" with an auth error.**
The `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` secrets are wrong or have been rolled.
Create a new API token in the Cloudflare R2 dashboard and update both secrets.

**Workflow succeeds but launcher users don't see the new version.**
The release landed as a draft. Go to `/admin/titles`, expand Trik_Klip, and flip the
new release from draft to active.
