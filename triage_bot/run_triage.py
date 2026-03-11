#!/usr/bin/env python3
"""
Triage Bot: Run Codex agent on the next pending item from a blocker report.

Usage:
  python run_triage.py --date YYYY-MM-DD [--all] [--dry-run]

  --all: Process all pending items (default: just the next one)
  --dry-run: Print what would run, do not execute Codex
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shlex
import string
import subprocess
import sys
from pathlib import Path

from config import (
    ReportSettings,
    get_report_settings,
    load_env,
    max_validation_retries,
    parse_analysis_repos,
    report_path_for_date,
)

# Priority order for sorting (highest first)
PRIORITY_ORDER = {
    "P1": 0,
    "P2": 1,
    "P3": 2,
    "P4": 3,
    "unset": 4,
    "~P1": 0,
    "~P2": 1,
    "~P3": 2,
    "~P4": 3,
}


def _script_dir() -> Path:
    return Path(__file__).resolve().parent


def _triage_bot_dir() -> Path:
    return _script_dir()


def _pen_test_root(env: dict[str, str] | None = None) -> Path:
    loaded = env or load_env(_script_dir())
    default_root = _script_dir().parent
    raw = loaded.get("PENTEST_ROOT", str(default_root))
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = _script_dir() / p
    return p.resolve()


def urgency_sort_key(entry: dict, report_settings: ReportSettings) -> tuple[int, str]:
    urgency = entry.get(report_settings.priority_key, "unset")
    priority = PRIORITY_ORDER.get(urgency, 99)
    return (priority, entry.get(report_settings.short_id_key, ""))


def has_completed_runtime(entry: dict, report_settings: ReportSettings) -> bool:
    for runtime in entry.get(report_settings.runtimes_key, []):
        status = runtime.get("status", "")
        if status in ("validated", "completed", "needs_human"):
            return True
    return False


def pick_next_item(data: dict, do_all: bool, report_settings: ReportSettings) -> list[tuple[dict, int]]:
    """Pick item(s) to process. Returns list of (entry, index) or empty."""
    items = data.get(report_settings.analyze_key, [])
    if not items:
        return []

    sorted_items = sorted(
        enumerate(items),
        key=lambda pair: urgency_sort_key(pair[1], report_settings),
    )

    if do_all:
        return [
            (entry, index)
            for index, entry in sorted_items
            if not has_completed_runtime(entry, report_settings)
        ]

    for index, entry in sorted_items:
        if not has_completed_runtime(entry, report_settings):
            return [(entry, index)]
    return []


def gen_runtime_id() -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=6))


def _get_fix_instructions(entry: dict, report_settings: ReportSettings) -> str:
    """If previous run failed validation, return instructions to fix existing folder."""
    for runtime in entry.get(report_settings.runtimes_key, []):
        pentest_folder = runtime.get(report_settings.pentest_folder_key)
        if runtime.get("validation_status") == "error" and pentest_folder:
            reason = runtime.get("validation_reason", "validation failed")
            return (
                f"**CRITICAL: Previous run failed validation:** {reason}\n\n"
                f"**Do not create a new folder.** Add the missing file(s) to: {pentest_folder}\n\n"
                f"Re-run `python triage_bot/validate_pentest.py {pentest_folder}` after fixing."
            )
    return ""


def _render_repo_list(repo_targets: list) -> str:
    if not repo_targets:
        return "- (none configured; set ANALYSIS_REPOS in triage_bot/.env if needed)"
    return "\n".join(f"- {repo.name}: {repo.path}" for repo in repo_targets)


def render_prompt(
    entry: dict,
    report_date: str,
    runtime_id: str,
    env: dict[str, str],
    report_settings: ReportSettings,
    repo_targets: list,
) -> str:
    template_path = _script_dir() / "AGENT_PROMPT_TEMPLATE.md"
    with open(template_path, encoding="utf-8") as f:
        template = f.read()

    pentest_root = _pen_test_root(env)
    fix = _get_fix_instructions(entry, report_settings)

    repl = {
        "{{SHORT_ID}}": str(entry.get(report_settings.short_id_key, "")),
        "{{PENTEST_ROOT}}": str(pentest_root),
        "{{TITLE}}": str(entry.get(report_settings.title_key, "")),
        "{{URGENCY}}": str(entry.get(report_settings.priority_key, "")),
        "{{TLDR}}": str(entry.get("tldr", "")),
        "{{WHY_BLOCKED}}": str(entry.get("why_blocked", "")),
        "{{RESEARCHER_CLAIM}}": str(entry.get("researcher_claim", "")),
        "{{SECRETARY_URGENCY}}": str(entry.get("secretary_urgency", "")),
        "{{QUICK_ANALYSIS}}": str(entry.get("quick_analysis", "")),
        "{{WEB}}": str(entry.get("web", "")),
        "{{LOCAL}}": str(entry.get("local", "")),
        "{{REPORT_DATE}}": report_date,
        "{{RUNTIME_ID}}": runtime_id,
        "{{REPO_LIST}}": _render_repo_list(repo_targets),
        "{{FIX_INSTRUCTIONS}}": fix,
    }
    for k, v in repl.items():
        template = template.replace(k, v)
    return template


def build_codex_cmd(
    prompt: str,
    pentest_root: Path,
    add_dirs: list[Path],
) -> tuple[list[str], str]:
    """Returns (cmd, stdin_content). Uses stdin to avoid argv length limits."""
    cmd = [
        "codex",
        "exec",
        "--full-auto",
        "--cd",
        str(pentest_root),
        "--skip-git-repo-check",
    ]
    for directory in add_dirs:
        if directory.exists():
            cmd.extend(["--add-dir", str(directory)])
    cmd.append("-")  # read prompt from stdin
    return cmd, prompt


def _load_journal_helper():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "journal_helper",
        _triage_bot_dir().parent / "journal_helper.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _build_validator_cmd(pentest_folder: Path, env: dict[str, str]) -> list[str]:
    template = (env.get("VALIDATOR_CMD") or "").strip()
    if not template:
        validate_script = _triage_bot_dir() / "validate_pentest.py"
        return [sys.executable, str(validate_script), str(pentest_folder)]

    try:
        rendered = template.format(
            pentest_folder=str(pentest_folder),
            folder=str(pentest_folder),
            triage_bot_dir=str(_triage_bot_dir()),
        )
    except KeyError as exc:
        raise ValueError(
            "VALIDATOR_CMD has an unknown placeholder. "
            "Use {pentest_folder}, {folder}, or {triage_bot_dir}."
        ) from exc

    cmd = shlex.split(rendered)
    if not cmd:
        raise ValueError("VALIDATOR_CMD resolved to an empty command")
    return cmd


def run_validator_and_update(
    report_date: str,
    short_id: str,
    runtime_id: str,
    pentest_folder: Path,
    commands_path: Path | None = None,
    env: dict[str, str] | None = None,
) -> tuple[str, str]:
    """
    Run validator and update JSON.

    Returns status + reason where status is one of: validated, error, needs_human.
    If commands_path is set, both commands are appended to command journals.
    """
    triage_dir = _triage_bot_dir()
    update_script = triage_dir / "update_blocker_json.py"
    pentest_root = _pen_test_root(env)
    merged_env = {**os.environ, **(env or {})}

    validate_cmd = _build_validator_cmd(pentest_folder, merged_env)
    if commands_path:
        jh = _load_journal_helper()
        result = jh.run_command_logged(commands_path, validate_cmd, pentest_root, merged_env)
    else:
        result = subprocess.run(
            validate_cmd,
            capture_output=True,
            text=True,
            cwd=str(pentest_root),
            env=merged_env,
        )

    status = "validated" if result.returncode == 0 else "error"
    reason = (result.stderr or "").strip() or (
        "OK" if result.returncode == 0 else "Validation failed"
    )

    update_cmd = [
        sys.executable,
        str(update_script),
        "validate-result",
        "--date",
        report_date,
        "--short-id",
        short_id,
        "--runtime-id",
        runtime_id,
        "--status",
        status,
        "--reason",
        reason[:500],
    ]
    if commands_path:
        jh = _load_journal_helper()
        jh.run_command_logged(commands_path, update_cmd, pentest_root, merged_env)
    else:
        subprocess.run(
            update_cmd,
            capture_output=True,
            cwd=str(pentest_root),
            env=merged_env,
        )

    return status, reason


def write_runtime_md(rerun_cmd: str, runtime_id: str, report_date: str) -> Path:
    md_path = _triage_bot_dir() / "runtime.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# Triage Bot Runtime - {runtime_id}\n\n")
        f.write(f"Report date: {report_date}\n\n")
        f.write("## Rerun this triage\n\n")
        f.write("```bash\n")
        f.write(rerun_cmd + "\n")
        f.write("```\n")
    return md_path


def _create_triage_journal_folder():
    """Create per-run journal folder; return folder path or None."""
    try:
        jh = _load_journal_helper()
        return jh.create_triage_journal_folder(_triage_bot_dir())
    except Exception:
        return None


def _triage_issue_paths(
    folder: Path | None,
    seq: int,
    short_id: str,
    title: str,
) -> tuple[Path | None, Path | None]:
    """Return (agent_path, commands_path) for this issue."""
    if not folder:
        return None, None
    try:
        jh = _load_journal_helper()
        return jh.triage_issue_paths(folder, seq, short_id, title)
    except Exception:
        return None, None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="Blocker report date (YYYY-MM-DD)")
    parser.add_argument(
        "--all", action="store_true", help="Process all items (default: next one only)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Print commands, do not run")
    parser.add_argument(
        "--skip-repos-check",
        action="store_true",
        help="Skip repo branch/freshness check",
    )
    args = parser.parse_args()

    env = {**os.environ, **load_env(_script_dir())}
    try:
        report_settings = get_report_settings(_script_dir(), env)
        repo_targets = parse_analysis_repos(env, _script_dir())
        retry_limit = max_validation_retries(env)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if not args.skip_repos_check and not args.dry_run:
        check_script = _triage_bot_dir() / "check_repos.py"
        result = subprocess.run(
            [sys.executable, str(check_script)],
            capture_output=True,
            text=True,
            env=env,
        )
        if result.returncode != 0:
            print(result.stderr, file=sys.stderr)
            print(
                "Fix branch issues or run `make up_to_date` before triage.",
                file=sys.stderr,
            )
            print("To bypass: make triage date=... skip_repos=1", file=sys.stderr)
            return 1

    pentest_root = _pen_test_root(env)
    report_path = report_path_for_date(args.date, report_settings)

    if not report_path.exists():
        print(f"ERROR: Blocker report not found: {report_path}", file=sys.stderr)
        return 1

    with open(report_path, encoding="utf-8") as f:
        data = json.load(f)

    # Revalidate all runtimes that claim validation_status=validated.
    # Updates in-place to error if validation fails (no new agent_runtime block).
    revalidate_stdout = ""
    if not args.dry_run:
        update_script = _triage_bot_dir() / "update_blocker_json.py"
        result = subprocess.run(
            [sys.executable, str(update_script), "revalidate", "--date", args.date],
            capture_output=True,
            text=True,
            cwd=str(pentest_root),
            env=env,
        )
        revalidate_stdout = result.stdout or ""
        if result.stdout:
            print(result.stdout, end="")
        if result.returncode != 0:
            with open(report_path, encoding="utf-8") as f:
                data = json.load(f)

    items = pick_next_item(data, args.all, report_settings)
    if not items:
        print(
            f"No items to process (all '{report_settings.analyze_key}' entries are complete)"
        )
        return 0

    add_dirs = [repo.path for repo in repo_targets]

    triage_bot_dir = _triage_bot_dir()
    target = "triage-dry" if args.dry_run else "triage"
    base_rerun_cmd = f"cd {triage_bot_dir} && make {target} date={args.date}"
    if args.all:
        base_rerun_cmd += " all=1"

    journal_folder = _create_triage_journal_folder()
    if journal_folder:
        print(f"Journal folder: {journal_folder}\n", file=sys.stderr)
        jh = _load_journal_helper()
        jh.init_triage_progress(
            journal_folder,
            base_rerun_cmd,
            items,
            revalidate_output=revalidate_stdout,
        )

    exit_code = 0
    analyze_entries = data.get(report_settings.analyze_key, [])
    for seq, (entry, idx) in enumerate(items, 1):
        short_id = str(entry.get(report_settings.short_id_key, "unknown"))
        title = str(entry.get(report_settings.title_key, "untitled"))
        agent_path, commands_path = _triage_issue_paths(journal_folder, seq, short_id, title)
        validated = False

        for attempt in range(retry_limit):
            if journal_folder:
                jh = _load_journal_helper()
                if attempt == 0:
                    truncated = title[:50] + ("..." if len(title) > 50 else "")
                    jh.append_triage_progress(
                        journal_folder,
                        f"Now starting {seq:02d} {short_id} ({truncated}) - first run",
                    )
                else:
                    jh.append_triage_progress(
                        journal_folder,
                        f"Now starting {seq:02d} {short_id} - retry attempt {attempt + 1}",
                    )

            runtime_id = gen_runtime_id()
            prompt = render_prompt(
                entry,
                args.date,
                runtime_id,
                env,
                report_settings,
                repo_targets,
            )
            cmd, stdin_content = build_codex_cmd(prompt, pentest_root, add_dirs)
            rerun_cmd = base_rerun_cmd

            print("\n" + "=" * 60)
            print(f"short_id={short_id} attempt={attempt + 1}/{retry_limit}")
            print("RERUN COMMAND (save this):")
            print(rerun_cmd)
            print("=" * 60 + "\n")

            runtime_md = write_runtime_md(rerun_cmd, runtime_id, args.date)
            print(f"Rerun command saved to: {runtime_md}\n")

            if args.dry_run:
                print("DRY RUN - would execute:")
                print(" ".join(cmd))
                print("\n" + "=" * 60)
                print("PROMPT (would be sent via stdin):")
                print("=" * 60)
                print(stdin_content)
                print("=" * 60)
                validated = True
                break

            import threading

            captured_lines: list[str] = []

            def read_and_tee(pipe):
                for line in iter(pipe.readline, ""):
                    captured_lines.append(line)
                    print(line, end="", flush=True)
                pipe.close()

            proc = subprocess.Popen(
                cmd,
                cwd=str(pentest_root),
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            t = threading.Thread(target=read_and_tee, args=(proc.stdout,))
            t.start()
            proc.stdin.write(stdin_content)
            proc.stdin.close()
            proc.wait()
            t.join()
            captured = "".join(captured_lines)

            if proc.returncode != 0:
                print(f"Codex exited with {proc.returncode}", file=sys.stderr)
                exit_code = proc.returncode

            if agent_path:
                jh = _load_journal_helper()
                journal_cmd = (
                    f"make triage date={args.date}"
                    + (" all=1" if args.all else "")
                    + f"  # short_id={short_id} attempt={attempt + 1}"
                )
                jh.append_triage_agent_block(agent_path, journal_cmd, stdin_content, captured)

            with open(report_path, encoding="utf-8") as f:
                data = json.load(f)

            analyze_entries = data.get(report_settings.analyze_key, [])
            if idx >= len(analyze_entries):
                print(
                    f"ERROR: Expected index {idx} in '{report_settings.analyze_key}' after run.",
                    file=sys.stderr,
                )
                exit_code = 1
                break

            entry_after = analyze_entries[idx]
            runtimes = entry_after.get(report_settings.runtimes_key, [])
            pentest_folder = None
            for runtime in runtimes:
                if (
                    runtime.get("agent_id") == runtime_id
                    and runtime.get(report_settings.pentest_folder_key)
                ):
                    pentest_folder = Path(runtime[report_settings.pentest_folder_key])
                    break

            if not pentest_folder:
                for runtime in reversed(runtimes):
                    folder = runtime.get(report_settings.pentest_folder_key)
                    if folder:
                        pentest_folder = Path(folder)
                        break

            if pentest_folder and pentest_folder.exists():
                status, reason = run_validator_and_update(
                    args.date,
                    short_id,
                    runtime_id,
                    pentest_folder,
                    commands_path=commands_path,
                    env=env,
                )
                print(f"\nValidation: {status} (attempt {attempt + 1}/{retry_limit})")

                if status == "validated":
                    validated = True
                    if journal_folder:
                        _load_journal_helper().append_triage_progress(
                            journal_folder,
                            f"{seq:02d} {short_id} - validated",
                        )
                    break

                if attempt < retry_limit - 1:
                    if journal_folder:
                        _load_journal_helper().append_triage_progress(
                            journal_folder,
                            f"{seq:02d} {short_id} - validation failed: {reason}, retrying",
                        )
                    print(f"\n-> Re-running agent with fix instructions for {short_id}...")
                    entry = entry_after
                else:
                    update_script = _triage_bot_dir() / "update_blocker_json.py"
                    subprocess.run(
                        [
                            sys.executable,
                            str(update_script),
                            "validate-result",
                            "--date",
                            args.date,
                            "--short-id",
                            short_id,
                            "--runtime-id",
                            runtime_id,
                            "--status",
                            "needs_human",
                            "--reason",
                            f"Max retries ({retry_limit}); validation still failing",
                        ],
                        capture_output=True,
                        cwd=str(_pen_test_root(env)),
                        env=env,
                    )
                    if commands_path:
                        jh = _load_journal_helper()
                        update_cmd = [
                            sys.executable,
                            str(update_script),
                            "validate-result",
                            "--date",
                            args.date,
                            "--short-id",
                            short_id,
                            "--runtime-id",
                            runtime_id,
                            "--status",
                            "needs_human",
                            "--reason",
                            f"Max retries ({retry_limit})",
                        ]
                        jh.run_command_logged(
                            commands_path,
                            update_cmd,
                            _pen_test_root(env),
                            env,
                        )
                    if journal_folder:
                        _load_journal_helper().append_triage_progress(
                            journal_folder,
                            f"{seq:02d} {short_id} - needs_human (max retries)",
                        )
                    print(f"\n-> Max retries reached for {short_id}; marked needs_human")
            else:
                if journal_folder:
                    _load_journal_helper().append_triage_progress(
                        journal_folder,
                        f"{seq:02d} {short_id} - no pentest_folder found, cannot validate",
                    )
                print(
                    f"\nNo pentest_folder found for {short_id}; cannot validate",
                    file=sys.stderr,
                )
                if attempt >= retry_limit - 1:
                    break

        if not validated and not args.dry_run:
            print(f"\nWARNING: {short_id} did not reach validated status", file=sys.stderr)

    if not args.dry_run and items:
        with open(report_path, encoding="utf-8") as f:
            data = json.load(f)
        print("\n" + "=" * 60)
        print("BLOCKER REPORT STATUS SUMMARY")
        print("=" * 60)
        needs_human_entries: list[tuple[str, str]] = []
        for entry in data.get(report_settings.analyze_key, []):
            sid = entry.get(report_settings.short_id_key, "?")
            runtimes = entry.get(report_settings.runtimes_key, [])
            statuses = [runtime.get("validation_status") or runtime.get("status", "?") for runtime in runtimes]
            latest = statuses[-1] if statuses else "-"
            print(f"  {sid}: {latest}")
            if latest == "needs_human" and runtimes:
                reason = (
                    runtimes[-1].get("validation_reason")
                    or runtimes[-1].get("human_intervention_reason")
                    or ""
                )
                if reason:
                    needs_human_entries.append((str(sid), reason))
        print("=" * 60)
        if needs_human_entries:
            print("\n" + "=" * 60)
            print("NEEDS_HUMAN - resolve these:")
            print("=" * 60)
            for sid, reason in needs_human_entries:
                print(f"  {sid}:")
                print(f"    {reason}")
            print("=" * 60)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
