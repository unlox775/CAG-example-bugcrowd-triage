# CAG Example: BugCrowd Security Triage

This repository is a standalone Composite Agentic Gate (CAG) example built from the workflow where the pattern was first recognized (`dave-style-attempt-1`).

**What’s a CAG?** A Composite Agentic Gate is a checkpoint where code pauses and hands off to an AI agent (or human): the gate gives context, asks for a decision or artifact, and tells you exactly how to re-enter the flow. That turns triage and validation into a repeatable, enforceable pipeline instead of best-effort prompting. **Read more:** [The Compound Agentic Workflow — How AI agents can solve messy real-world problems](https://medium.com/constant-total-amazement/the-compound-agentic-workflow-how-ai-agents-can-solve-messy-real-world-problems-25561e482876).

**About this repo.** This code was extracted from a private monorepo, sanitized, and AI-ported to demonstrate a CAG example. It may be usable—you’re welcome to use it under the MIT license—but it is not intended (yet) as a ready-to-use, production tool.

It shows a full deterministic-to-agentic pipeline:

1. `bugcrowd-sync/` (deterministic): sync BugCrowd API data to local markdown
2. `secretary/` (agentic gate): normalize submissions into a validated blocker report
3. `triage_bot/` (agentic gate loop): run investigation, validate outputs, retry, escalate

The core idea is process enforcement through gates, not best-effort prompting.

## Why This Is a CAG Example

For each queued triage item, the flow is a hard contract:

1. Condition: validator must pass
2. Prompt: agent gets item context plus failure reason (if any)
3. Mutation: fix investigation artifacts or report runtime state
4. Re-entry: rerun exact command (`make triage date=...`) from `triage_bot/runtime.md`

If retries are exhausted, runtime is deterministically marked `needs_human`.

Full gate-by-gate breakdown: `docs/AGENTIC-FLOW.md`.

## Run with an AI Agent (Primary)

The point of this repo is to run the triage pipeline with an AI agent. You do one-time setup (sync, secretary if desired), then the agent runs triage and handles gate output (fix artifacts, rerun) for each item.

**Agent runner:** This is configured for **Codex**. Have Codex installed and logged in so it can run in this repo. Secretary and triage_bot both invoke Codex; the gate output and flow are the same for any runner. To use another agent (Cursor, Claude, etc.), port the runner; it should work with minimal changes.

**Codex setup (brief):** Install the Codex CLI, log in, and ensure it can execute in this directory. Once that’s done, you’re ready to run the flow with an agent.

**One-time setup (you):**

1. BugCrowd sync (if you have credentials): `make -C bugcrowd-sync install`, `make -C bugcrowd-sync env_setup`, edit `bugcrowd-sync/.env`, then `make -C bugcrowd-sync sync`.
2. Secretary (optional): `make -C secretary run-agent SOURCE_BLOCKED=bugcrowd-sync/data/blocked SOURCE_TO_REVIEW=bugcrowd-sync/data/new` — this uses Codex to produce blocker reports.
3. Triage bot: `make -C triage_bot env_setup`.

**Run the flow with your agent:** Run triage for a given date. Codex is invoked per item; when a gate fails, it gets the failure reason and rerun command, fixes artifacts, and reruns until the validator passes or the item is marked `needs_human`:

```bash
make -C triage_bot triage date=YYYY-MM-DD
```

That’s it. The agent does the triage loop; process is enforced instead of assumed.

**Dry run (no credentials):** To see the exact Codex command and rerun text without running live:

```bash
make -C triage_bot env_setup
make -C triage_bot triage-dry date=2026-01-15 skip_repos=1
```

## Repository Layout

- `bugcrowd-sync/`: deterministic BugCrowd API export (upstream input feed)
- `secretary/`: blocker report generation and report-schema validator gate
- `triage_bot/`: per-item triage loop with validation-retry-escalation gates
- `docs/AGENTIC-FLOW.md`: complete CAG flow map and gate contracts
- `split-out-TODO.md`: split-out checklist and notes
- `journal_helper.py`: shared journal logging utility

## Pluggability

`triage_bot/env.example` supports adaptation beyond BugCrowd:

- report path and schema keys (`BLOCKER_REPORT_DIR`, `REPORT_*`)
- validator command override (`VALIDATOR_CMD`)
- read-only analysis repo list (`ANALYSIS_REPOS`)

`bugcrowd-sync/env.example` contains credential placeholders only.
