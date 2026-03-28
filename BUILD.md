# Trik_Klip — Build & Packaging Guide

Instructions for packaging Trik_Klip as a Windows executable using PyInstaller.

## Prerequisites

- Windows 10/11
- Python 3.11+ (system or Anaconda)
- NVIDIA GPU drivers installed (for CUDA-enabled torch)
- ffmpeg and ffprobe installed at `C:\Program Files\ffmpeg\bin\`
- GitHub CLI (`gh`) authenticated for creating releases

## Build Environment Setup (one-time)

A dedicated venv at `build_env/` keeps the build isolated from the system Python.

```bash
# Create the venv
python -m venv build_env

# Activate it
source build_env/Scripts/activate   # Git Bash
# or: build_env\Scripts\activate    # CMD/PowerShell

# Install CUDA-enabled torch first (cu118 for CUDA 11.8)
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu118

# Install all project dependencies + PyInstaller
pip install -r requirements.txt pyinstaller
```

To verify CUDA is working in the venv:
```bash
python -c "import torch; print(torch.__version__, 'CUDA:', torch.cuda.is_available())"
# Expected: torch 2.7.1+cu118 CUDA: True
```

## Building the Executable

```bash
# Activate the build venv
source build_env/Scripts/activate

# Run PyInstaller with the spec file (cleans previous build automatically)
python -m PyInstaller Trik_Klip.spec --noconfirm

# Copy ffmpeg and ffprobe into the dist folder
cp "/c/Program Files/ffmpeg/bin/ffmpeg.exe" dist/Trik_Klip/
cp "/c/Program Files/ffmpeg/bin/ffprobe.exe" dist/Trik_Klip/

# Copy the release README
cp RELEASE_README.md dist/Trik_Klip/README.md
```

The output is at `dist/Trik_Klip/` with `Trik_Klip.exe` as the entry point.

## Creating the Zip

```bash
cd dist
powershell -Command "Compress-Archive -Path 'Trik_Klip' -DestinationPath 'Trik_Klip_v1.0.0_windows.zip' -Force"
```

The zip will be ~2.9GB (5.7GB uncompressed). This is normal — torch CUDA libraries are the bulk of it.

## Uploading a GitHub Release

GitHub has a 2GB per-file limit. For files over 2GB, split first:

```bash
# Split into sub-2GB parts
split -b 1900m Trik_Klip_v1.0.0_windows.zip Trik_Klip_v1.0.0_windows.zip.part_

# Create release with split parts
gh release create v1.0.0 \
  Trik_Klip_v1.0.0_windows.zip.part_aa \
  Trik_Klip_v1.0.0_windows.zip.part_ab \
  --title "Trik_Klip v1.0.0 - Windows" \
  --notes "Release notes here"
```

For Gumroad or other hosts with no file size limit, upload the unsplit zip directly.

## What the Spec File Does (Trik_Klip.spec)

- **Entry point:** `gui.py`
- **Mode:** onedir (faster startup than onefile)
- **Windowed:** No console window
- **collect_all:** `customtkinter` (theme assets), `whisper` (model/mel filters), `torch` (CUDA DLLs)
- **collect_submodules:** `anthropic`, `openai`, `google.genai`, `google.generativeai` (lazy-loaded provider SDKs)
- **Bundled data:** `fonts/Nulgl_case2-Regular.ttf`, `.env.example`
- **NOT bundled:** ffmpeg/ffprobe (copied manually after build), streamclipper_profiles.json, .trik_klip_license

## Key Files in the Dist

```
dist/Trik_Klip/
  Trik_Klip.exe          # Main executable (double-click to run)
  ffmpeg.exe             # Copied in after build
  ffprobe.exe            # Copied in after build
  README.md              # End-user documentation
  _internal/             # PyInstaller internals (Python, libs, assets)
    fonts/               # Bundled custom font
    .env.example         # API key template
    ...                  # torch, whisper, customtkinter, etc.
```

## Updating the Build

When source code changes:

1. Activate the build venv: `source build_env/Scripts/activate`
2. If dependencies changed: `pip install -r requirements.txt`
3. Run: `python -m PyInstaller Trik_Klip.spec --noconfirm`
4. Copy ffmpeg/ffprobe into `dist/Trik_Klip/`
5. Copy `RELEASE_README.md` to `dist/Trik_Klip/README.md`
6. Re-zip

## Troubleshooting

**"pathlib is an obsolete backport" error:**
You're running PyInstaller from the system Anaconda env instead of the build venv. Make sure to activate `build_env` first.

**CUDA: False in the build venv:**
Reinstall torch with CUDA: `pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu118`

**Missing module errors at runtime:**
Add the module to `hiddenimports` in `Trik_Klip.spec` and rebuild.

**Exe crashes silently:**
Temporarily change `console=False` to `console=True` in the spec file to see error output, rebuild, and run from a terminal.
