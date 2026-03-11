# BugCrowd Sync Research

Tools for debugging and inspecting BugCrowd API responses when modifying the sync.

## export_submission.py

Export all API data for a single submission to a JSON file. Use when you need to:

- Inspect the raw API response structure
- Debug how the sync interprets a submission
- Understand what fields are available (state, severity, etc.)

**Usage:**

```bash
cd bugcrowd-sync
# Load env from .env if present
set -a; [ -f .env ] && . ./.env; set +a
# Use full UUID or short 8-char ID
python research/export_submission.py 4228ee3e-da2f-4c39-a2cb-1c38994cc1d8
# or
python research/export_submission.py 4228ee3e
```

**Output:** `research/exports/<short_id>_<slug>_<timestamp>.json`

Requires `BUGCROWD_AUTHHEADER` or `BUGCROWD_USERNAME`/`BUGCROWD_PASSWORD`.
