# CAG Example: BugCrowd Security Triage

This repository is a standalone Composite Agentic Gate (CAG) example extracted from a real security-triage workflow.

**What’s a CAG?** A Composite Agentic Gate is a checkpoint where code pauses and hands off to an AI agent (or human): the gate gives context, asks for a decision or artifact, and tells you exactly how to re-enter the flow. That turns triage and validation into a repeatable, enforceable pipeline instead of best-effort prompting. **Read more:** [The Compound Agentic Workflow — How AI agents can solve messy real-world problems](https://medium.com/constant-total-amazement/the-compound-agentic-workflow-how-ai-agents-can-solve-messy-real-world-problems-25561e482876).

**About this repo.** This code was extracted from a private monorepo, sanitized, and AI-ported to demonstrate a CAG example. It may be usable—you’re welcome to use it under the MIT license—but it is not intended (yet) as a ready-to-use, production tool.

## The Goal

The end-to-end goal: take a batch of incoming security submissions and, for each one, produce a **pen-test research folder** containing everything a cybersecurity expert would deliver—impact assessment, proof-of-concept work, Jira follow-up tasks, BugCrowd response drafts, Slack summaries. Three components chain together to get there:

**1. BugCrowd sync** — data preparation (deterministic). Pulls submissions from the BugCrowd API into local markdown files. This is a prerequisite for everything downstream. (You could swap in a similar sync for Jira or another task tracker.)

**2. Secretary** — summarize and categorize (agentic gate). Reads the synced submissions at a given status, triages each one into `simple_reply`, `pen_test_already_created`, or `analyze_pen_test`, and produces a validated blocker report (JSON + markdown) that the triage bot consumes.

**3. Triage bot** — deep analysis of secretary-prepared items, one at a time (agentic gate loop). For each `analyze_pen_test` item, an agent:

- Reads the submission and browses the actual codebase where the vulnerability lives (configured via `ANALYSIS_REPOS`)
- Creates a new pen-test research folder for that item
- Does the full job of a security expert: impact assessment, proof-of-concept exploration, forensic data queries, code review
- Writes out all follow-up artifacts: Jira task drafts, BugCrowd response, Slack message, duplicate analysis
- Runs through validation gates—retries with fix instructions until every required artifact passes, or escalates to `needs_human`

The output is a set of research folders, one per submission, each containing the complete investigation and all the write-ups needed to update your trackers and notify stakeholders.

## Why This Is a CAG Example

At every step, deterministic code—not the agent—decides whether to proceed. Each gate is a hard checkpoint:

1. **Validate**: does the output pass the schema/content check?
2. **Fail with context**: if not, the agent gets the exact failure reason and fix instructions
3. **Mutate and retry**: the agent fixes its artifacts, then reruns the same command
4. **Escalate**: after max retries, the item is marked `needs_human` with a reason

The agent does the creative work (research, writing, code analysis). The gates enforce that the work is complete and correct. That makes it a repeatable pipeline instead of a one-shot prompt-and-hope.

Full gate-by-gate breakdown: `docs/AGENTIC-FLOW.md`.

## Run with an AI Agent (Primary)

The point of this repo is to run the triage pipeline with an AI agent. You do one-time setup (sync, secretary if desired), then the agent runs triage and handles gate output (fix artifacts, rerun) for each item.

**Agent runner:** This is configured for **Codex**. Have Codex installed and logged in so it can run in this repo. Secretary and triage_bot both invoke Codex; the gate output and flow are the same for any runner. To use another agent (Cursor, Claude, etc.), port the runner; it should work with minimal changes.

**Codex setup (brief):** Install the Codex CLI, log in, and ensure it can execute in this directory. Once that’s done, you’re ready to run the flow with an agent.

**1. BugCrowd sync** (if you have credentials)

```bash
make -C bugcrowd-sync install
make -C bugcrowd-sync env_setup
# Edit bugcrowd-sync/.env, then:
make -C bugcrowd-sync sync
```

**2. Secretary** (optional—produces blocker reports via Codex)

```bash
make -C secretary run-agent SOURCE_BLOCKED=bugcrowd-sync/data/blocked SOURCE_TO_REVIEW=bugcrowd-sync/data/new
```

**3. Triage bot setup**

```bash
make -C triage_bot env_setup
```

Edit `triage_bot/.env`: set `ANALYSIS_REPOS` to your codebase paths so the agent can browse code. Leave `PENTEST_ROOT=../pentest` so research folders are created in the `pentest/` subfolder (gitignored); the validator will fail if the agent creates folders elsewhere.

**4. Run triage** for a date. The agent handles gates; fix artifacts and rerun until validated or `needs_human`.

```bash
make -C triage_bot triage date=YYYY-MM-DD
```

**5. Dry run** (no credentials)—see the Codex command and rerun text without running live:

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

**Task tracker / upstream sync:** BugCrowd sync is one deterministic feed. You can implement a similar sync for Jira or another task tracker—same idea: export to local markdown and point secretary at those paths.

**Codebase access for triage:** Set `ANALYSIS_REPOS` in `triage_bot/.env` (format: `name|branch|/abs/path`). The triage agent gets these paths via `--add-dir` so it can browse the code and do deeper blocker analysis. Check out your repos before running triage.

**Other `triage_bot/.env` options:** report path and schema keys (`BLOCKER_REPORT_DIR`, `REPORT_`*), validator override (`VALIDATOR_CMD`).

`bugcrowd-sync/env.example` contains credential placeholders only.