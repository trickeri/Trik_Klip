# Trik_Klip — Build Guide

Trik_Klip is a Rust + Tauri + Svelte desktop app. The release flow is documented in
[RELEASE.md](RELEASE.md) — this file just covers getting a local dev build running.

## Prerequisites

- Windows 10/11
- [Rust toolchain](https://rustup.rs/) (latest stable)
- Node.js 20+ (`npm` in PATH)
- Vulkan SDK (required by the whisper.cpp Vulkan backend)
- `src-tauri/resources/` populated with runtime binaries:
  - `ffmpeg.exe`, `ffprobe.exe`
  - `whisper-cli.exe` + `whisper.dll`, `ggml*.dll`, `ggml-base.bin`

See [RELEASE.md](RELEASE.md#if-the-resources-folder-gets-wiped) for where to get those
binaries if the folder is missing.

## Dev loop

```bash
npm install
npm run tauri dev
```

Hot reload covers the Svelte frontend (`src/`) and rebuilds the Rust shell
(`src-tauri/`, `crates/`) on file changes.

## Release build

```bash
npm run tauri build
```

Full packaging + GitHub release is handled by `/deploy` from Claude Code, or manually
via the steps in [RELEASE.md](RELEASE.md).
