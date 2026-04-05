Build the Rust/Tauri release executable for Trik_Klip and publish it as a GitHub Release.

Argument: $ARGUMENTS (optional version number, e.g. "0.2.0")

## Version Bumping

1. Read the current version from `src-tauri/tauri.conf.json` (the `version` field).

2. Determine the new version:
   - **If a version argument is provided**: use that exact version (e.g. `/build 0.2.0`)
   - **If no argument**: auto-increment the patch number, but skip numbers with leading zeros.
     The patch goes: 0, 11, 12, 13, ... 99. So 0.1.0 → 0.1.11, 0.1.11 → 0.1.12, ... 0.1.99 → needs manual bump.
     Never produce patch numbers 1-10 (they have leading zero issues when stripped: 01→1, 02→2, etc.).

3. Update the version in ALL of these files:
   - `src-tauri/tauri.conf.json` — both `version` field and window `title` field ("Trik Klip v{version}")
   - `src-tauri/Cargo.toml` — the `version` field
   - `package.json` — the `version` field

## Build

4. Run `npm run tauri build` from the project root. This will:
   - Build the Svelte frontend via Vite (`npm run build`)
   - Compile the Rust backend in release mode
   - Bundle the NSIS installer

5. If the build fails, check the error output and fix any issues before retrying.
   Do NOT publish the release if the build failed.

## Publish

6. If the build succeeds, find the installer files in `src-tauri/target/release/bundle/nsis/`.

7. Commit the version bump files and create a GitHub Release using `gh release create` with:
   - Tag: `v{version}` (e.g. `v0.1.11`)
   - Title: `Trik_Klip v{version}`
   - Attach all `.exe` files from the NSIS bundle directory
   - Generate release notes from commits since the last tag
