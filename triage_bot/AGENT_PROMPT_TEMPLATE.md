# Security Triage Agent Task

You are triaging one security submission from the blocker report.

## Submission Context

- `short_id`: {{SHORT_ID}}
- `title`: {{TITLE}}
- `urgency`: {{URGENCY}}
- `tldr`: {{TLDR}}
- `why_blocked`: {{WHY_BLOCKED}}
- `researcher_claim`: {{RESEARCHER_CLAIM}}
- `secretary_urgency`: {{SECRETARY_URGENCY}}
- `quick_analysis`: {{QUICK_ANALYSIS}}
- `web`: {{WEB}}
- `local`: {{LOCAL}}

{{FIX_INSTRUCTIONS}}

## Required Workflow

1. Read the local submission at `{{LOCAL}}` first.
2. Create an investigation folder under `{{PENTEST_ROOT}}` named `YYYY-MM-DD_descriptive-slug`.
3. Immediately record the folder so retries can recover state:

```bash
python triage_bot/update_blocker_json.py record-pentest-folder --date {{REPORT_DATE}} --short-id {{SHORT_ID}} --runtime-id {{RUNTIME_ID}} --pentest-folder {{PENTEST_ROOT}}/FOLDER_NAME
```

4. Complete the investigation output and create the required files in the folder root:
- `README.md`
- `IMPACT_ASSESSMENT.md`
- `BUGCROWD_TITLE_AND_SUMMARY.md`
- `FOLLOWUP_JIRA_TASK.md`
- `POSSIBLE_BUGCROWD_DUPLICATES.md`
- `SLACK_MESSAGE.md`

5. Use these repositories as read-only analysis context:
{{REPO_LIST}}

6. If you cannot complete the investigation, record human escalation and stop:

```bash
python triage_bot/update_blocker_json.py human-intervention --date {{REPORT_DATE}} --short-id {{SHORT_ID}} --runtime-id {{RUNTIME_ID}} --reason "YOUR_REASON"
```

7. Before finishing, run validation and fix any failures:

```bash
python triage_bot/validate_pentest.py YOUR_FOLDER_PATH
```

Do not consider the task complete until validation passes, or until human escalation has been recorded.
