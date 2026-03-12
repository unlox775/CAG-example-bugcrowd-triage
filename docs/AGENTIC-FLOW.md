# Agentic Flow

This standalone repo demonstrates a composite flow:

1. deterministic upstream sync (`bugcrowd-sync/`)
2. secretary gate (report validation)
3. triage gate loop (validation, retries, escalation)

It descends from `dave-style-attempt-1`, which used this CAG pattern for process control.

## Pipeline Map

```text
BugCrowd API
  -> bugcrowd-sync (deterministic export)
  -> secretary (agent + report validator gate)
  -> triage_bot (agent + output validator gate loop)
  -> validated or needs_human
```

## Phase 0: BugCrowd Sync (Deterministic Feed)

Purpose: fetch submissions and normalize them into local markdown inputs.

Entry command:

```bash
make -C bugcrowd-sync sync
```

Outputs:

- `bugcrowd-sync/data/{new,blocked,unresolved,resolved,rejected}/...`
- `bugcrowd-sync/.state/bugcrowd.json`

CAG relevance:

- no agentic stop here
- this phase is deterministic input preparation for downstream gates

## Phase 1: Secretary Gate (Optional but First Agentic Stop)

Purpose: create `secretary/blocked_report/YYYY-MM-DD_blocker_report.json` for triage.

Typical command:

```bash
make -C secretary run-agent \
  SOURCE_BLOCKED=bugcrowd-sync/data/blocked \
  SOURCE_TO_REVIEW=bugcrowd-sync/data/new
```

Gate contract:

- Condition: `python secretary/block_report_validator.py <report.json>` must pass.
- Gate output on failure: explicit schema and path-level errors.
- Mutation: fix report data (data mutation).
- Re-entry command:

```bash
python secretary/block_report_validator.py secretary/blocked_report/YYYY-MM-DD_blocker_report.json
```

## Phase 2: Triage Bot (Primary CAG Loop)

Purpose: for each pending `analyze_pen_test` item, run agent + validation until pass or escalation.

Entry command:

```bash
make -C triage_bot triage date=YYYY-MM-DD
```

### Gate A: Runtime State Capture

- Condition: agent records `pentest_folder` via `record-pentest-folder`.
- Gate output on failure: runtime cannot proceed to validation.
- Mutation: write/update runtime JSON with the created folder path.
- Re-entry command: rerun the command in `triage_bot/runtime.md`.

### Gate B: Investigation Output Validation

- Condition: validator passes (`triage_bot/validate_pentest.py`, or `VALIDATOR_CMD` override).
- Gate output on failure:
  - validation reason is written into runtime state
  - next prompt includes concrete fix instructions
- Mutation: add/fix required investigation artifacts.
- Re-entry command:

```bash
cd /absolute/path/to/triage_bot && make triage date=YYYY-MM-DD
```

### Gate C: Retry Budget / Escalation

- Condition: pass validation within `MAX_VALIDATION_RETRIES`.
- Gate output on failure: runtime marked `needs_human` with reason.
- Mutation: human resolves blocker or adjusts artifacts/config.
- Re-entry command: rerun triage for the same date.

## Why the Composite Pattern Matters

This flow does not rely on agent compliance alone:

- deterministic code decides progression
- gates enforce hard checkpoints
- agents perform judgment/artifact creation inside bounded steps
- each stop includes explicit mutation target + exact rerun command

That contract is the CAG value: reliable iterative control instead of brittle one-shot automation.
