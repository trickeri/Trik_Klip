# Deploy Trik_Klip

Deploy a new release of Trik_Klip through the Nuldrums launcher distribution pipeline.

Trik_Klip uses a **local-build, CI-distribute** architecture because the Vulkan-accelerated whisper.cpp binaries in `target/release/resources/` are not available as prebuilt CI-friendly artifacts. The build happens on this machine; the GitHub Actions workflow only handles distribution (R2 upload + website registration).

Releases are registered on the website in **draft** status by default. After the workflow finishes, go to `https://nuldrums.world/admin/titles`, expand Trik_Klip, find the new release in the releases table, and flip its status from `draft` to `active` to push it to launcher users.

## Arguments

- `$ARGUMENTS` — Optional version override (e.g. `1.2.0`). If omitted, auto-increments the patch number by 1.

## Pre-flight checks (do these BEFORE bumping the version)

1. **Verify `target/release/resources/` is populated** with the runtime binaries:
   ```bash
   ls -la target/release/resources/ | grep -E "ffmpeg|whisper|ggml"
   ```
   You should see all of: `ffmpeg.exe`, `ffprobe.exe`, `whisper-cli.exe`, `whisper.dll`, `ggml*.dll`, `ggml-base.bin`. If any are missing, the zipped release will be broken — stop and ask the user to restore them before continuing.

2. **Verify `gh` is authenticated** to the `trickeri/Trik_Klip` repo:
   ```bash
   gh auth status
   ```

## Steps

1. **Read current version** from `src-tauri/tauri.conf.json`.

2. **Determine new version:**
   - If `$ARGUMENTS` is provided and non-empty, use that as the new version.
   - Otherwise, auto-increment **only the third number** (the patch) by **1**.
     - Examples: `0.1.0` → `0.1.1`, `0.1.9` → `0.1.10`, `1.2.99` → `1.2.100`
     - **Do not** zero-pad. Use `10`, `11`, `100` — not `010`, `011`, `0100`.
     - **Do not** bump the middle number unless the user explicitly asks for a minor release.
   - **Confirm the new version with the user before proceeding.**

3. **Update version in BOTH files** (they must match):
   - `src-tauri/tauri.conf.json` — the Tauri build reads this (update both `"version"` and the `"title"` field which includes the version string)
   - `package.json` — the frontend's source of truth

4. **Build locally** — this takes ~5-10 minutes:
   ```bash
   npm run tauri build
   ```
   If the build fails, stop and report the error. Do NOT commit the version bump if the build fails.

5. **Verify the build output exists:**
   ```bash
   ls target/release/trik-klip.exe target/release/trik-klip-cli.exe
   ls target/release/resources/
   ```
   If either is missing, stop and investigate.

6. **Assemble the portable zip** using PowerShell for the `Compress-Archive` step (it's the most reliable Windows zip tool available from bash):
   ```bash
   VERSION=<new version>
   ZIP_NAME="trik-klip_${VERSION}_windows-x86_64.zip"

   # Clean any stale staging dir
   rm -rf portable-staging
   mkdir -p portable-staging/resources

   # Copy the main exe + cli exe
   cp target/release/trik-klip.exe portable-staging/
   cp target/release/trik-klip-cli.exe portable-staging/

   # Copy the runtime resources (ffmpeg, whisper, model)
   cp target/release/resources/* portable-staging/resources/

   # Create the zip (delete old one first if it exists)
   rm -f "$ZIP_NAME"
   powershell -Command "Compress-Archive -Path 'portable-staging/*' -DestinationPath '$ZIP_NAME' -Force"

   # Verify the zip was created and show size
   ls -lh "$ZIP_NAME"
   ```

7. **Commit and push the version bump:**
   ```bash
   git add src-tauri/tauri.conf.json package.json
   git commit -m "Bump version to $VERSION"
   git push origin main
   ```

8. **Create the GitHub release** with the zip attached as an asset. This is what triggers the distribution workflow:
   ```bash
   gh release create "v$VERSION" \
     --title "Trik_Klip v$VERSION" \
     --notes "$RELEASE_NOTES" \
     "$ZIP_NAME"
   ```
   Ask the user for release notes, or summarize recent commits since the last release tag.

9. **Monitor the distribution workflow:**
   ```bash
   gh run list --limit 1
   ```
   Give the user the run ID so they can watch with `gh run watch <id>` in another terminal. The distribution-only workflow is fast — typically under a minute since it just downloads the zip from the release, uploads to R2, and POSTs to the website.

10. **Clean up** the local staging directory (optional but tidy):
    ```bash
    rm -rf portable-staging
    ```

11. **Report to the user:**
    - The GitHub Release URL
    - The Actions run ID
    - **Reminder:** the release landed as a DRAFT. To push it to launcher users, go to `https://nuldrums.world/admin/titles`, expand Trik_Klip, find the new release row, and flip its status dropdown from `draft` to `active`.

## Failure handling

- **`npm run tauri build` fails:** stop, report the error, do not touch git.
- **Resources folder is missing files:** stop, do not bump the version.
- **`git push` fails (e.g., non-fast-forward):** the version bump is still in the local commit. Tell the user to resolve with `git pull --rebase` or similar, then re-run `git push`.
- **`gh release create` fails AFTER the version bump has been pushed:** the commit is live but the release doesn't exist yet. Re-run just the `gh release create` step once resolved — the CI workflow will fire on the next successful release creation.
- **CI workflow fails during distribution:** the zip is attached to the GH release and the version is pushed, but R2 upload or website registration failed. Investigate via `gh run view <id> --log-failed`. Common causes: stale `TITLE_RELEASE_API_KEY` secret, R2 credentials rolled, website endpoint down.
- **CI workflow uses old workflow file:** GitHub Actions runs the workflow from the **tag ref**, not `main`. If the workflow file was changed after the tag was created, the old version runs. Fix: delete the release AND the tag, retag at HEAD, then recreate the release with the zip attached.

## Version scheme

- `MAJOR.MINOR.PATCH` — semver-style
- PATCH: bug fixes, small improvements (most common bump)
- MINOR: new features, backward-compatible changes
- MAJOR: breaking changes / milestones
- Never bump version without the user's say-so — they batch changes first.

## What the CI workflow does (for reference)

The distribution workflow (`.github/workflows/release.yml`) runs on `ubuntu-latest` (no Windows build tools needed since there's no build step) and only:
1. Parses the version from the release tag (strips `v` prefix)
2. Downloads `trik-klip_X.X.X_windows-x86_64.zip` from the release assets via `gh release download`
3. Computes SHA-256 and size of the zip
4. Uploads the zip to `s3://nuldrums-releases/releases/trik-klip/X.X.X/windows-x86_64.zip`
5. POSTs a release manifest to `https://nuldrums.world/api/admin/title-releases` with `set_active: false` (draft)

The workflow is fast (~30 seconds on average) because there's no compilation step.
