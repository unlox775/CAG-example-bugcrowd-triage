#!/usr/bin/env python3
"""
Update blocker report JSON with agent runtime state.

Used by the triage agent to record progress and by automation to revalidate
existing outputs.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from config import ReportSettings, get_report_settings, load_env, report_path_for_date

# Import validate_folder for revalidate subcommand
sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_pentest import validate_folder  # noqa: E402


def _script_dir() -> Path:
    return Path(__file__).resolve().parent


def _blocked_report_path(date: str, settings: ReportSettings) -> Path:
    return report_path_for_date(date, settings)


def _report_glob(settings: ReportSettings) -> str:
    return settings.filename_template.replace("{date}", "*")


def _extract_report_date(path: Path, settings: ReportSettings) -> str:
    template = settings.filename_template
    prefix, _, suffix = template.partition("{date}")
    name = path.name
    if not name.startswith(prefix):
        return path.stem
    if suffix and not name.endswith(suffix):
        return path.stem
    start = len(prefix)
    end = len(name) - len(suffix) if suffix else len(name)
    if end <= start:
        return path.stem
    return name[start:end]


def _load_report(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_report(path: Path, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _find_analyze_entry(
    data: dict,
    short_id: str,
    settings: ReportSettings,
) -> tuple[dict | None, int]:
    """Find analyze entry for short_id. Returns (entry, index) or (None, -1)."""
    for i, entry in enumerate(data.get(settings.analyze_key, [])):
        if entry.get(settings.short_id_key) == short_id:
            return entry, i
    return None, -1


def _ensure_agent_runtimes(entry: dict, settings: ReportSettings) -> list:
    if settings.runtimes_key not in entry:
        entry[settings.runtimes_key] = []
    return entry[settings.runtimes_key]


def _find_or_create_runtime(runtimes: list, runtime_id: str) -> dict:
    for runtime in runtimes:
        if runtime.get("agent_id") == runtime_id:
            return runtime
    new_runtime = {
        "agent_id": runtime_id,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "running",
    }
    runtimes.append(new_runtime)
    return new_runtime


def cmd_record_pentest_folder(args: argparse.Namespace) -> int:
    path = _blocked_report_path(args.date, args.report_settings)
    if not path.exists():
        print(f"ERROR: Blocker report not found: {path}", file=sys.stderr)
        return 1

    data = _load_report(path)
    entry, _ = _find_analyze_entry(data, args.short_id, args.report_settings)
    if not entry:
        print(
            f"ERROR: No {args.report_settings.analyze_key} entry for "
            f"{args.report_settings.short_id_key}={args.short_id}",
            file=sys.stderr,
        )
        return 1

    runtimes = _ensure_agent_runtimes(entry, args.report_settings)
    runtime = _find_or_create_runtime(runtimes, args.runtime_id)
    runtime[args.report_settings.pentest_folder_key] = args.pentest_folder
    runtime["pentest_folder_recorded_at"] = datetime.now(timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )
    runtime["status"] = "running"

    _save_report(path, data)
    print(f"Recorded pentest_folder for {args.short_id} runtime {args.runtime_id}")
    return 0


def cmd_human_intervention(args: argparse.Namespace) -> int:
    path = _blocked_report_path(args.date, args.report_settings)
    if not path.exists():
        print(f"ERROR: Blocker report not found: {path}", file=sys.stderr)
        return 1

    data = _load_report(path)
    entry, _ = _find_analyze_entry(data, args.short_id, args.report_settings)
    if not entry:
        print(
            f"ERROR: No {args.report_settings.analyze_key} entry for "
            f"{args.report_settings.short_id_key}={args.short_id}",
            file=sys.stderr,
        )
        return 1

    runtimes = _ensure_agent_runtimes(entry, args.report_settings)
    runtime = _find_or_create_runtime(runtimes, args.runtime_id)
    runtime["status"] = "needs_human"
    runtime["human_intervention_reason"] = args.reason
    runtime["human_intervention_at"] = datetime.now(timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )

    _save_report(path, data)
    print(f"Marked {args.short_id} runtime {args.runtime_id} as needs_human")
    return 0


def cmd_validate_result(args: argparse.Namespace) -> int:
    path = _blocked_report_path(args.date, args.report_settings)
    if not path.exists():
        print(f"ERROR: Blocker report not found: {path}", file=sys.stderr)
        return 1

    if args.status not in ("validated", "error", "needs_human"):
        print("ERROR: status must be validated, error, or needs_human", file=sys.stderr)
        return 1

    data = _load_report(path)
    entry, _ = _find_analyze_entry(data, args.short_id, args.report_settings)
    if not entry:
        print(
            f"ERROR: No {args.report_settings.analyze_key} entry for "
            f"{args.report_settings.short_id_key}={args.short_id}",
            file=sys.stderr,
        )
        return 1

    runtimes = _ensure_agent_runtimes(entry, args.report_settings)
    runtime = _find_or_create_runtime(runtimes, args.runtime_id)
    runtime["status"] = args.status
    runtime["validation_status"] = args.status
    runtime["validation_reason"] = args.reason or ""
    runtime["validated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    _save_report(path, data)
    print(
        f"Updated validation status for {args.short_id} runtime "
        f"{args.runtime_id}: {args.status}"
    )
    return 0


def _find_tagged_folders(pentest_root: Path, short_id: str) -> list[Path]:
    """Find folders in pentest_root containing .tag-bugcrowd-{short_id}."""
    tag_name = f".tag-bugcrowd-{short_id}"
    seen: set[Path] = set()
    found: list[Path] = []
    for item in pentest_root.iterdir():
        if item.is_dir() and (item / tag_name).exists():
            resolved = item.resolve()
            if resolved not in seen:
                seen.add(resolved)
                found.append(resolved)
    return found


def _find_blocker_reports_referencing_folder(
    short_id: str,
    blocked_report_dir: Path,
    settings: ReportSettings,
) -> dict[str, list[str]]:
    """
    For a short_id, scan report files and return:
      {folder_name: [report_date, ...]}

    Checks both analyze entries (runtime pentest folder) and
    pre-existing pentest entries.
    """
    result: dict[str, list[str]] = {}

    def add_folder(folder_path: str, report_date: str) -> None:
        if not folder_path:
            return
        resolved = Path(folder_path).resolve()
        name = resolved.name
        if name not in result:
            result[name] = []
        if report_date not in result[name]:
            result[name].append(report_date)

    for fp in blocked_report_dir.glob(_report_glob(settings)):
        report_date = _extract_report_date(fp, settings)
        data = _load_report(fp)

        entry = _find_analyze_entry(data, short_id, settings)[0]
        if entry:
            for runtime in entry.get(settings.runtimes_key) or []:
                add_folder(runtime.get(settings.pentest_folder_key, ""), report_date)

        for existing in data.get(settings.pen_test_created_key) or []:
            if existing.get(settings.short_id_key) == short_id:
                add_folder(existing.get(settings.pentest_folder_key, ""), report_date)
                break

    return result


def _format_multiple_folders_reason(
    short_id: str,
    tagged_folders: list[Path],
    blocker_referenced: dict[str, list[str]],
) -> str:
    """Build a reason string with one line per candidate folder."""
    all_names: set[str] = set()
    for path in tagged_folders:
        all_names.add(path.resolve().name)
    for name in blocker_referenced:
        all_names.add(name)

    lines: list[str] = []
    for name in sorted(all_names):
        tags: list[str] = []
        if any(folder.resolve().name == name for folder in tagged_folders):
            tags.append("tagged")
        refs = blocker_referenced.get(name, [])
        if refs:
            tags.append(f"referenced by {', '.join(refs)} blocker report(s)")
        if not tags:
            tags.append("not referenced by any blocker report")
        lines.append(f"    - {name} ({'; '.join(tags)})")

    return (
        "Multiple folders for this submission:\n"
        + "\n".join(lines)
        + "\n    Human must pick which to keep."
    )


def cmd_revalidate(args: argparse.Namespace) -> int:
    """Re-run validation on all agent runtimes currently marked validated."""
    settings = args.report_settings
    path = _blocked_report_path(args.date, settings)
    if not path.exists():
        print(f"ERROR: Blocker report not found: {path}", file=sys.stderr)
        return 1

    data = _load_report(path)
    entries = data.get(settings.analyze_key, [])

    # Derive pen-test root from first pentest_folder in report.
    pentest_root = None
    for entry in entries:
        for runtime in entry.get(settings.runtimes_key) or []:
            folder = runtime.get(settings.pentest_folder_key)
            if folder:
                pentest_root = Path(folder).resolve().parent
                break
        if pentest_root:
            break

    if not pentest_root or not pentest_root.is_dir():
        fallback = args.env.get("PENTEST_ROOT", str(_script_dir().parent / "pentest"))
        pentest_path = Path(fallback).expanduser()
        if not pentest_path.is_absolute():
            pentest_path = _script_dir() / pentest_path
        pentest_root = pentest_path.resolve()

    blocked_report_dir = path.resolve().parent

    checked = 0
    failed = 0
    needs_human_count = 0
    needs_human_reasons: list[tuple[str, str]] = []

    for entry in entries:
        short_id = entry.get(settings.short_id_key, "?")
        runtimes = entry.get(settings.runtimes_key) or []
        if not runtimes:
            continue

        for runtime in [runtimes[-1]]:
            tagged_folders = _find_tagged_folders(pentest_root, short_id)
            folder_path = runtime.get(settings.pentest_folder_key)
            json_folder = Path(folder_path).resolve() if folder_path else None

            if len(tagged_folders) > 1:
                blocker_referenced = _find_blocker_reports_referencing_folder(
                    short_id,
                    blocked_report_dir,
                    settings,
                )
                reason = _format_multiple_folders_reason(
                    short_id,
                    tagged_folders,
                    blocker_referenced,
                )
                runtime["status"] = "needs_human"
                runtime["validation_status"] = "needs_human"
                runtime["validation_reason"] = reason
                runtime["validated_at"] = datetime.now(timezone.utc).isoformat().replace(
                    "+00:00", "Z"
                )
                needs_human_count += 1
                needs_human_reasons.append((short_id, reason))
                print(f"NEEDS_HUMAN: {short_id} - {reason}")
                continue

            tagged = tagged_folders[0] if tagged_folders else None
            if tagged and json_folder and tagged != json_folder:
                blocker_referenced = _find_blocker_reports_referencing_folder(
                    short_id,
                    blocked_report_dir,
                    settings,
                )
                reason = _format_multiple_folders_reason(
                    short_id,
                    tagged_folders,
                    blocker_referenced,
                )
                runtime["status"] = "needs_human"
                runtime["validation_status"] = "needs_human"
                runtime["validation_reason"] = reason
                runtime["validated_at"] = datetime.now(timezone.utc).isoformat().replace(
                    "+00:00", "Z"
                )
                needs_human_count += 1
                needs_human_reasons.append((short_id, reason))
                print(f"NEEDS_HUMAN: {short_id} - {reason}")
                continue

            folder = tagged or (json_folder if json_folder and json_folder.exists() else None)
            if not folder or not folder.exists():
                continue

            checked += 1
            ok, errors = validate_folder(folder)
            if ok:
                runtime["status"] = "validated"
                runtime["validation_status"] = "validated"
                runtime["validation_reason"] = "OK"
                runtime["validated_at"] = datetime.now(timezone.utc).isoformat().replace(
                    "+00:00", "Z"
                )
                print(f"OK: {short_id} {folder.name}")
            else:
                reason = "; ".join(errors)
                runtime["status"] = "error"
                runtime["validation_status"] = "error"
                runtime["validation_reason"] = reason
                runtime["validated_at"] = datetime.now(timezone.utc).isoformat().replace(
                    "+00:00", "Z"
                )
                failed += 1
                print(f"FAIL: {short_id} {folder.name} - {reason}")

    if checked == 0 and needs_human_count == 0 and failed == 0:
        print("No validated agent runtimes found.")
        return 0

    _save_report(path, data)

    if needs_human_count > 0:
        print("\n" + "=" * 60)
        print("NEEDS_HUMAN - resolve these:")
        print("=" * 60)
        for sid, reason in needs_human_reasons:
            print(f"  {sid}:")
            print(f"    {reason}")
        print("=" * 60)
        return 1

    if failed > 0:
        print(f"\nUpdated blocker report: {failed} runtime(s) marked error.")
        return 1

    existing_needs: list[tuple[str, str]] = []
    for entry in data.get(settings.analyze_key, []):
        sid = entry.get(settings.short_id_key, "?")
        for runtime in reversed(entry.get(settings.runtimes_key) or []):
            if runtime.get("validation_status") == "needs_human" or runtime.get("status") == "needs_human":
                reason = runtime.get("validation_reason") or runtime.get(
                    "human_intervention_reason"
                ) or ""
                if reason and "Multiple folders" in reason:
                    tagged = _find_tagged_folders(pentest_root, sid)
                    blocker_referenced = _find_blocker_reports_referencing_folder(
                        sid,
                        blocked_report_dir,
                        settings,
                    )
                    reason = _format_multiple_folders_reason(sid, tagged, blocker_referenced)
                if reason:
                    existing_needs.append((sid, reason))
                break

    if existing_needs:
        print("\n" + "=" * 60)
        print("NEEDS_HUMAN - resolve these (from blocker report):")
        print("=" * 60)
        for sid, reason in existing_needs:
            print(f"  {sid}:")
            print(f"    {reason}")
        print("=" * 60)
        return 1

    print(f"\nAll {checked} runtime(s) still validate.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Update blocker report JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    # record-pentest-folder
    p1 = sub.add_parser("record-pentest-folder")
    p1.add_argument("--date", required=True, help="Date of blocker report (YYYY-MM-DD)")
    p1.add_argument("--short-id", required=True, help="Short ID of the submission")
    p1.add_argument("--runtime-id", required=True, help="6-char agent runtime identifier")
    p1.add_argument("--pentest-folder", required=True, help="Absolute path to created pen-test folder")
    p1.set_defaults(func=cmd_record_pentest_folder)

    # human-intervention
    p2 = sub.add_parser("human-intervention")
    p2.add_argument("--date", required=True, help="Date of blocker report (YYYY-MM-DD)")
    p2.add_argument("--short-id", required=True, help="Short ID of the submission")
    p2.add_argument("--runtime-id", required=True, help="6-char agent runtime identifier")
    p2.add_argument("--reason", required=True, help="Reason human intervention is needed")
    p2.set_defaults(func=cmd_human_intervention)

    # validate-result
    p3 = sub.add_parser("validate-result")
    p3.add_argument("--date", required=True, help="Date of blocker report (YYYY-MM-DD)")
    p3.add_argument("--short-id", required=True, help="Short ID of the submission")
    p3.add_argument("--runtime-id", required=True, help="6-char agent runtime identifier")
    p3.add_argument("--status", required=True, choices=["validated", "error", "needs_human"])
    p3.add_argument("--reason", default="", help="Optional reason (e.g. validation errors)")
    p3.set_defaults(func=cmd_validate_result)

    # revalidate
    p4 = sub.add_parser("revalidate")
    p4.add_argument("--date", required=True, help="Date of blocker report (YYYY-MM-DD)")
    p4.set_defaults(func=cmd_revalidate)

    args = parser.parse_args()

    env = {**os.environ, **load_env(_script_dir())}
    try:
        report_settings = get_report_settings(_script_dir(), env)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    args.env = env
    args.report_settings = report_settings
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
