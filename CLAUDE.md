# Project Notes for AI Agents

## Repo size and context window

Pre-computed line counts and token estimates are available in `metrics/`.
Read `metrics/cloc.txt` (human-readable) or `metrics/cloc.json` (machine-readable)
instead of manually counting lines or crawling every file.

To regenerate after significant code changes:
```bash
bash scripts/update_metrics.sh
```
