# Secretary (Optional Phase)

The secretary phase prepares daily blocker reports for triage automation.

This split-out keeps secretary as an optional component so the CAG loop can be understood without external BugCrowd sync infrastructure.

## What It Produces

- `secretary/blocked_report/YYYY-MM-DD_blocker_report.md`
- `secretary/blocked_report/YYYY-MM-DD_blocker_report.json`

The JSON report is consumed by `triage_bot/run_triage.py`.

## Validate a Report

```bash
python secretary/block_report_validator.py secretary/blocked_report/2026-01-15_blocker_report.json
```

## Run Agent-Driven Secretary Flow

If you have Codex CLI configured and your own submission source directories, run:

```bash
make -C secretary run-agent
```

Edit `secretary/INSTRUCTIONS.md` and `secretary/Makefile` variables for your local data source paths.
