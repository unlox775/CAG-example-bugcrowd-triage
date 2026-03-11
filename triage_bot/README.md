# Triage Bot

Agent orchestration loop for security triage reports.

The bot reads pending items from a blocker report, runs an agent, validates output, retries with fix instructions, and escalates to `needs_human` after max retries.

## Setup

1. Install Codex CLI:

```bash
npm i -g @openai/codex
codex login
```

2. Create `.env` from template:

```bash
make env_setup
```

3. Edit `triage_bot/.env` for your paths and report schema.

4. Optional: verify configured analysis repos:

```bash
make check_repos
```

## Usage

Process one pending item:

```bash
make triage date=2026-01-15
```

Process all pending items:

```bash
make triage date=2026-01-15 all=1
```

Dry run (prints Codex command + full prompt):

```bash
make triage date=2026-01-15 dry_run=1
```

Revalidate previously validated runtime outputs:

```bash
make revalidate date=2026-01-15
```

## Config Highlights

`triage_bot/.env` controls:

- Report location and schema keys (`BLOCKER_REPORT_DIR`, `REPORT_ANALYZE_KEY`, etc.)
- Validation behavior (`MAX_VALIDATION_RETRIES`, optional `VALIDATOR_CMD`)
- Read-only analysis repositories (`ANALYSIS_REPOS`)

See `env.example` for all options.

## Runtime Journals

Each run writes journal artifacts to `triage_bot/journals/`:

- `00_progress.txt` for run progress
- `*_agent.txt` for agent prompt + output
- `*_commands.txt` for validator/update commands and output

The journal format is implemented by `journal_helper.py` at repository root.
