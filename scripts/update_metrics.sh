#!/usr/bin/env bash
# update_metrics.sh — Generate line-count and token-estimate metrics
# Run from repo root: bash scripts/update_metrics.sh

set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

METRICS_DIR="metrics"
mkdir -p "$METRICS_DIR"

# ── 1. Run cloc ─────────────────────────────────────────────────────────────

echo "Running cloc..."
cloc . --vcs=git --json --quiet > "$METRICS_DIR/cloc.json"
cloc . --vcs=git --quiet       > "$METRICS_DIR/cloc.txt"

echo "  cloc.json and cloc.txt written to $METRICS_DIR/"

# ── 2. Token estimates ──────────────────────────────────────────────────────

python3 - <<'PYEOF'
import json, os, subprocess, sys

metrics_dir = "metrics"

# Total bytes of all git-tracked files
result = subprocess.run(
    ["git", "ls-files", "-z"],
    capture_output=True, text=True, check=True,
)
paths = [p for p in result.stdout.split("\0") if p]

total_bytes = 0
for p in paths:
    try:
        total_bytes += os.path.getsize(p)
    except OSError:
        pass

total_chars = total_bytes  # approximate: 1 byte ≈ 1 char for source code
total_tokens = int(total_chars / 3.5)

# Context windows to compare against (80% threshold)
windows = {
    "Claude 200k": 200_000,
    "GPT-4o 128k": 128_000,
    "Gemini 1M":  1_000_000,
}

# Build summary lines
lines = []
lines.append("")
lines.append("=" * 64)
lines.append("TOKEN ESTIMATE (all git-tracked files)")
lines.append("=" * 64)
lines.append(f"  Total bytes:      {total_bytes:>12,}")
lines.append(f"  Est. tokens:      {total_tokens:>12,}  (~3.5 chars/token)")
lines.append("")
lines.append(f"  {'Model':<20} {'Window':>10} {'Usage':>8} {'Fits (<80%)?':>14}")
lines.append(f"  {'-'*20} {'-'*10} {'-'*8} {'-'*14}")

token_summary = {}
for name, window in windows.items():
    pct = total_tokens / window * 100
    fits = "Yes" if pct < 80 else "No"
    lines.append(f"  {name:<20} {window:>10,} {pct:>7.1f}% {fits:>14}")
    token_summary[name] = {"window": window, "usage_pct": round(pct, 1), "fits": fits}

lines.append("")
lines.append("  'Fits' = Yes when usage < 80% (leaves room for prompts/responses)")
lines.append("=" * 64)
summary_text = "\n".join(lines)

# Append to cloc.txt
with open(os.path.join(metrics_dir, "cloc.txt"), "a") as f:
    f.write("\n" + summary_text + "\n")

# Append to cloc.json
with open(os.path.join(metrics_dir, "cloc.json"), "r") as f:
    data = json.load(f)

data["token_estimate"] = {
    "total_bytes": total_bytes,
    "total_tokens_est": total_tokens,
    "chars_per_token": 3.5,
    "context_windows": token_summary,
}

with open(os.path.join(metrics_dir, "cloc.json"), "w") as f:
    json.dump(data, f, indent=2)

print(summary_text)
PYEOF

echo ""
echo "Done. Results in $METRICS_DIR/cloc.json and $METRICS_DIR/cloc.txt"
