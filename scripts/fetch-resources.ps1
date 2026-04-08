# fetch-resources.ps1
#
# Downloads the bundled runtime binaries Trik_Klip needs at runtime:
#   - ffmpeg.exe + ffprobe.exe      (audio/video extraction)
#   - whisper-cli.exe + ggml DLLs   (local speech-to-text via whisper.cpp)
#   - ggml-base.bin                 (Whisper base model weights)
#
# These files are NOT committed to the repo (see .gitignore) because they
# total ~470 MB and are sourced from pinned upstream releases instead.
# This script is idempotent: files that already exist are skipped, so it's
# safe to re-run after a partial failure.
#
# Used by:
#   - Local dev: run once after cloning the repo, then `cargo run` works
#   - CI/CD: called from .github/workflows/release.yml before `tauri build`
#
# To bump the bundled versions, edit the *_VERSION / *_URL values below and
# commit the change. The cached files in src-tauri/resources/ are not
# automatically refreshed — delete them manually if you want a clean fetch.

$ErrorActionPreference = "Stop"

# ----------------------------------------------------------------------------
# Pinned upstream versions — edit these to bump bundled components
# ----------------------------------------------------------------------------

# whisper.cpp Windows binary release
# Release list: https://github.com/ggml-org/whisper.cpp/releases
# Using the CPU build (whisper-bin-x64.zip). For CUDA/BLAS variants, swap the
# asset name — but the CPU build is the most portable and works everywhere.
$WHISPER_VERSION = "v1.8.4"
$WHISPER_ASSET = "whisper-bin-x64.zip"
$WHISPER_URL = "https://github.com/ggml-org/whisper.cpp/releases/download/$WHISPER_VERSION/$WHISPER_ASSET"

# ffmpeg static Windows build from BtbN
# The `latest` tag tracks the most recent nightly; for a reproducible pin
# use a dated `autobuild-YYYY-MM-DD-HH-MM` tag from the releases page.
$FFMPEG_URL = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"

# Whisper base model from HuggingFace (GGML format)
$MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin"

# ----------------------------------------------------------------------------

$RESOURCES_DIR = Join-Path $PSScriptRoot "..\src-tauri\resources"
$RESOURCES_DIR = [System.IO.Path]::GetFullPath($RESOURCES_DIR)
if (-not (Test-Path $RESOURCES_DIR)) {
    New-Item -ItemType Directory -Path $RESOURCES_DIR | Out-Null
}

$TEMP_DIR = Join-Path ([System.IO.Path]::GetTempPath()) "trik-klip-resources"
if (-not (Test-Path $TEMP_DIR)) {
    New-Item -ItemType Directory -Path $TEMP_DIR | Out-Null
}

Write-Host "Fetching Trik_Klip runtime resources..."
Write-Host "  Resources dir: $RESOURCES_DIR"
Write-Host "  Temp dir:      $TEMP_DIR"
Write-Host ""

function Download-File {
    param([string]$Url, [string]$DestPath)
    if (Test-Path $DestPath) {
        $size = (Get-Item $DestPath).Length
        Write-Host "  [cached] $(Split-Path $DestPath -Leaf) ($([math]::Round($size/1MB, 1)) MB)"
        return
    }
    Write-Host "  [fetch ] $(Split-Path $DestPath -Leaf)..."
    # Invoke-WebRequest is slow for large files because of progress rendering;
    # WebClient is ~5x faster with a bare stream copy.
    $wc = New-Object System.Net.WebClient
    try {
        $wc.DownloadFile($Url, $DestPath)
    } finally {
        $wc.Dispose()
    }
    $size = (Get-Item $DestPath).Length
    Write-Host "           $([math]::Round($size/1MB, 1)) MB downloaded"
}

function Copy-MatchingFiles {
    param([string]$SourceDir, [string[]]$Patterns, [string]$DestDir)
    foreach ($pattern in $Patterns) {
        $matches = Get-ChildItem -Path $SourceDir -Recurse -File -Filter $pattern
        foreach ($m in $matches) {
            $destPath = Join-Path $DestDir $m.Name
            Copy-Item $m.FullName $destPath -Force
            Write-Host "           → $(Split-Path $destPath -Leaf)"
        }
    }
}

# ----------------------------------------------------------------------------
# 1. whisper.cpp binaries
# ----------------------------------------------------------------------------

Write-Host "[1/3] whisper.cpp $WHISPER_VERSION (CPU build)"
$whisperZip = Join-Path $TEMP_DIR $WHISPER_ASSET

# Skip if the main exe is already present — user can force re-fetch by deleting it
if (-not (Test-Path (Join-Path $RESOURCES_DIR "whisper-cli.exe"))) {
    Download-File -Url $WHISPER_URL -DestPath $whisperZip

    $whisperExtract = Join-Path $TEMP_DIR "whisper-extract"
    if (Test-Path $whisperExtract) { Remove-Item -Recurse -Force $whisperExtract }
    Write-Host "  Extracting..."
    Expand-Archive -Path $whisperZip -DestinationPath $whisperExtract -Force

    # Copy the whisper exe and all DLLs — structure of the zip can vary between
    # releases (sometimes files are at the root, sometimes nested in main/).
    Copy-MatchingFiles -SourceDir $whisperExtract -Patterns @("whisper-cli.exe", "*.dll") -DestDir $RESOURCES_DIR
} else {
    Write-Host "  [cached] whisper-cli.exe already present"
}

# ----------------------------------------------------------------------------
# 2. ffmpeg static binaries
# ----------------------------------------------------------------------------

Write-Host ""
Write-Host "[2/3] ffmpeg / ffprobe (BtbN Windows static build)"
$ffmpegZip = Join-Path $TEMP_DIR "ffmpeg-win64-gpl.zip"

if (-not (Test-Path (Join-Path $RESOURCES_DIR "ffmpeg.exe")) -or
    -not (Test-Path (Join-Path $RESOURCES_DIR "ffprobe.exe"))) {
    Download-File -Url $FFMPEG_URL -DestPath $ffmpegZip

    $ffmpegExtract = Join-Path $TEMP_DIR "ffmpeg-extract"
    if (Test-Path $ffmpegExtract) { Remove-Item -Recurse -Force $ffmpegExtract }
    Write-Host "  Extracting..."
    Expand-Archive -Path $ffmpegZip -DestinationPath $ffmpegExtract -Force

    Copy-MatchingFiles -SourceDir $ffmpegExtract -Patterns @("ffmpeg.exe", "ffprobe.exe") -DestDir $RESOURCES_DIR
} else {
    Write-Host "  [cached] ffmpeg.exe and ffprobe.exe already present"
}

# ----------------------------------------------------------------------------
# 3. Whisper base model
# ----------------------------------------------------------------------------

Write-Host ""
Write-Host "[3/3] Whisper base model (ggml-base.bin)"
$modelPath = Join-Path $RESOURCES_DIR "ggml-base.bin"
Download-File -Url $MODEL_URL -DestPath $modelPath

# ----------------------------------------------------------------------------
# Summary
# ----------------------------------------------------------------------------

Write-Host ""
Write-Host "Done. Resources in ${RESOURCES_DIR}:"
Get-ChildItem -Path $RESOURCES_DIR -File | Sort-Object Name | ForEach-Object {
    $sizeMB = [math]::Round($_.Length / 1MB, 1)
    Write-Host ("  {0,-25} {1,8} MB" -f $_.Name, $sizeMB)
}
