# BugCrowd Reporting Standards (Example)

This document is a lightweight, public-safe reference for writing consistent triage outputs.

## 1. Title Format

Use:

`[Product Area] / [Specific Vulnerability Description]`

Good examples:

- `Identity / IDOR in /api/v1/users/:id/profile`
- `Admin Console / Command Injection in Backup Job Parameter`
- `Content API / Stored XSS in Comment Renderer`

Avoid vague titles:

- `SQL Injection bug`
- `XSS issue`

## 2. Summary Block

Start with a concise technical summary that answers:

- What the bug is
- Where it exists (endpoint/component)
- What preconditions are required
- What impact is confirmed

## 3. Severity Notes

Capture severity as observed impact, not only researcher-claimed impact.

Include:

- attack preconditions
- affected user role
- data/system impact
- exploit reliability

## 4. Investigation Artifacts

For this example repository, each triage output folder must include:

- `README.md`
- `IMPACT_ASSESSMENT.md`
- `BUGCROWD_TITLE_AND_SUMMARY.md`
- `FOLLOWUP_JIRA_TASK.md`
- `POSSIBLE_BUGCROWD_DUPLICATES.md`
- `SLACK_MESSAGE.md`

## 5. Human Escalation

Escalate to human review when:

- application access is blocked
- scope is ambiguous
- conflicting historical folders exist for the same submission
- validation keeps failing after retry budget is exhausted

This standard keeps triage output predictable so automation can enforce quality gates.
