# Deploy Trik_Klip

Deploy a new release of Trik_Klip through the Nuldrums launcher distribution pipeline. Bumps the version, commits, pushes, and creates a GitHub Release which triggers the CI/CD workflow (fetch resources → build → zip → upload to R2 → register with website → attach to GitHub Release).

Releases are registered on the website in **draft** status by default. After CI finishes, go to the admin dashboard at `https://nuldrums.world/admin/titles` → find Trik_Klip → expand → find the new release in the releases table → flip its status to **active** to push it to launcher users.

## Arguments

- `$ARGUMENTS` — Optional version override (e.g. `0.2.0`). If omitted, auto-increments the patch number by 1.

## Steps

1. **Read current version** from `src-tauri/tauri.conf.json`.

2. **Determine new version:**
   - If `$ARGUMENTS` is provided and non-empty, use that as the new version.
   - Otherwise, auto-increment **only the third number** (the patch / last segment) by **1**.
     The first and second numbers stay the same unless the user explicitly asks for a
     minor or major bump.
     - Examples: `0.1.0` → `0.1.1`, `0.1.9` → `0.1.10`, `0.1.99` → `0.1.100`
     - **Important:** Do NOT zero-pad. Use `10`, `11`, `100` — not `010`, `011`, `0100` —
       leading zeros get stripped by tooling.
     - **Do not** bump the middle number (e.g. `0.1.5` → `0.2.0`) unless the user
       explicitly asks for a minor release.
   - Confirm the new version with the user before proceeding.

3. **Update version in two places** — both `src-tauri/tauri.conf.json` AND `package.json` need the new version. (The Tauri build reads from `tauri.conf.json`, but `package.json` is the frontend's source of truth and should match.)

4. **Commit and push:**
   ```bash
   git add src-tauri/tauri.conf.json package.json && git commit -m "Bump version to X.X.X" && git push origin main
   ```

5. **Create GitHub Release** to trigger the CI/CD workflow:
   ```bash
   gh release create vX.X.X --title "Trik_Klip vX.X.X" --notes "Release notes here"
   ```
   - Ask the user for release notes, or summarize recent commits since the last release tag.

6. **Monitor the workflow:**
   ```bash
   gh run list --limit 1
   ```
   - Give the user the run ID so they can watch with `gh run watch <id>` in a separate terminal.

7. **Report:**
   - The GitHub Release URL
   - The Actions run ID for monitoring
   - **Reminder:** The release lands in the website as a DRAFT. To publish it to launcher users, go to `https://nuldrums.world/admin/titles`, expand the Trik_Klip row, find the new release, and flip its status dropdown from `draft` to `active`. This will automatically yank any prior active release for the same platform.

## Version scheme

- `MAJOR.MINOR.PATCH` — semver-style
- PATCH: bug fixes, small improvements (most common bump)
- MINOR: new features, backward-compatible changes
- MAJOR: breaking changes / milestones
- Never bump version without the user's say-so — they batch changes first.

## What the CI/CD workflow does (for reference)

1. Checks out the repo on a `windows-latest` runner
2. Runs `scripts/fetch-resources.ps1` to pull ffmpeg, whisper.cpp binaries, and the ggml-base model from upstream sources (these aren't committed to the repo)
3. Runs `npm ci` and `npm run tauri build` to produce the release binaries
4. Assembles a portable zip containing `trik-klip.exe` + `trik-klip-cli.exe` + `resources/` folder
5. Uploads the zip to Cloudflare R2 at `releases/trik-klip/X.X.X/windows-x86_64.zip`
6. POSTs a release manifest to `https://nuldrums.world/api/admin/title-releases` with `set_active: false` (draft)
7. Attaches the zip to the GitHub Release for direct download

The launcher's `/api/download-url/[title_id]` endpoint returns the presigned R2 URL for whichever release has `status = 'active'` — flipping a draft to active in the admin UI is what actually makes it go live for users.
