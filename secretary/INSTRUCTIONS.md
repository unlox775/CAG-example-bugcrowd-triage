# Secretary Instructions: Build Daily Blocker Report

Use this only when explicitly asked to run the secretary phase.

## Purpose

Collect blocked/to-review security submissions and produce a normalized report for triage automation.

## Required Outputs

For run date `YYYY-MM-DD`, create:

1. `secretary/blocked_report/YYYY-MM-DD_blocker_report.md`
2. `secretary/blocked_report/YYYY-MM-DD_blocker_report.json`

## JSON Contract

Top-level keys:

- `simple_reply`
- `pen_test_already_created`
- `analyze_pen_test`

Each submission object must include:

- `short_id`, `title`, `urgency`, `tldr`, `why_blocked`, `researcher_claim`,
  `secretary_urgency`, `quick_analysis`, `web`, `local`

Additional requirements:

- `simple_reply` entries require `simple_reply_reason`
- `pen_test_already_created` entries require:
  - `pentest_folder` (absolute path)
  - `tag_exists` (boolean)

## Process

1. Scan your source directories for blocked and to-review submissions.
2. Normalize each submission into one of the three JSON buckets.
3. Cross-check whether an investigation folder already exists.
4. Write markdown and JSON report outputs.
5. Validate JSON:

```bash
python secretary/block_report_validator.py secretary/blocked_report/YYYY-MM-DD_blocker_report.json
```

6. Fix validation errors and rerun until validation passes.

## Categorization Rules

- `simple_reply`: can be resolved with a short response.
- `pen_test_already_created`: investigation folder already exists.
- `analyze_pen_test`: needs a new triage investigation run.

Place each submission in exactly one bucket.
