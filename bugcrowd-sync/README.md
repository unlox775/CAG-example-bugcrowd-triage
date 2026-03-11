# bugcrowd-sync

Deterministic one-way sync from the BugCrowd API to local markdown files.

In this CAG example, `bugcrowd-sync/` is the upstream data feed:

- Deterministic phase: pull and normalize submissions into local files
- Agentic phases: secretary + triage gates consume those files

This sync itself is not an agentic gate. It provides the structured input that the gates enforce downstream.

## Setup

1. Install dependencies:

```bash
make install
```

2. Create local env file:

```bash
make env_setup
```

3. Edit `.env` with credentials:

- `BUGCROWD_USERNAME` and `BUGCROWD_PASSWORD`, or
- `BUGCROWD_AUTHHEADER` (token auth header value)

Optional:

- `BUGCROWD_BASE_URL` (defaults to `https://api.bugcrowd.com`)
- `BUGCROWD_SSL_UNVERIFIED` (`true` only for local SSL debugging)

## Run

Sync all submissions:

```bash
make sync
```

Force deep re-sync:

```bash
make sync-force
```

Sync one submission:

```bash
make sync-issue ISSUE_ID=<submission_uuid>
```

Count submissions in sync state:

```bash
make submissions-count SINCE=2026-01-01
```

## Output Layout

Default output path: `bugcrowd-sync/data/`

- `new/`
- `blocked/`
- `unresolved/`
- `resolved/`
- `rejected/`

Each submission writes:

- `<category>/<priority>/<YYYY-MM>-<slug>-<shortid>.md`
- Optional sibling attachment folder for downloaded files

Sync state is tracked in `bugcrowd-sync/.state/bugcrowd.json`.

Both `data/` and `.state/` are git-ignored in this split-out.

## Pipeline Handoff

Use sync output as secretary inputs, then run triage:

```bash
make -C bugcrowd-sync sync
make -C secretary run-agent \
  SOURCE_BLOCKED=bugcrowd-sync/data/blocked \
  SOURCE_TO_REVIEW=bugcrowd-sync/data/new
make -C triage_bot triage date=YYYY-MM-DD
```

This is the full deterministic-to-agentic flow documented in `../docs/AGENTIC-FLOW.md`.

## Sync Versioning

Sync format changes are tracked in `sync_versions.md`.

If format changes require rewriting existing files:

1. Increment `CURRENT_SYNC_VERSION` in `lib/engine.py`
2. Add changelog entry in `sync_versions.md`
3. Run `make sync` (or `make sync-force` if needed)
