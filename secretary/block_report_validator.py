#!/usr/bin/env python3
"""
Validate a blocker report JSON file against the expected schema.

Usage:
  python block_report_validator.py [path/to/YYYY-MM-DD_blocker_report.json]
  If no path given, validates all *_blocker_report.json in blocked_report/.
"""

import json
import os
import re
import sys
from pathlib import Path

REQUIRED_TOP_LEVEL_KEYS = frozenset({
    "simple_reply",
    "pen_test_already_created",
    "analyze_pen_test",
})

REQUIRED_SUBMISSION_KEYS = frozenset({
    "short_id",
    "title",
    "urgency",
    "tldr",
    "why_blocked",
    "researcher_claim",
    "secretary_urgency",
    "quick_analysis",
    "web",
    "local",
})

SIMPLE_REPLY_REQUIRED_KEYS = frozenset({
    "simple_reply_reason",
})

PEN_TEST_ALREADY_CREATED_KEYS = frozenset({
    "pentest_folder",
    "tag_exists",
})

# Optional keys added by triage_bot (agent_runtimes)
ALLOWED_OPTIONAL_KEYS = frozenset({"agent_runtimes"})

TAG_PREFIX = ".tag-bugcrowd-"
SHORT_ID_RE = re.compile(r"^[0-9a-f]{8}$")


def _expected_tag_file(folder: Path, short_id: str) -> Path:
    return folder / f"{TAG_PREFIX}{short_id}"


def _pen_test_root() -> Path:
    configured = os.environ.get("PENTEST_ROOT")
    if configured:
        p = Path(configured).expanduser()
        if not p.is_absolute():
            p = Path(__file__).resolve().parent / p
        return p.resolve()
    # Default to this split-out repository root.
    return Path(__file__).resolve().parent.parent


def _report_filename_glob() -> str:
    template = os.environ.get("BLOCKER_REPORT_FILENAME_TEMPLATE", "{date}_blocker_report.json")
    return template.replace("{date}", "*")


def _blocked_report_dir() -> Path:
    configured = os.environ.get("BLOCKER_REPORT_DIR")
    if configured:
        p = Path(configured).expanduser()
        if not p.is_absolute():
            p = Path(__file__).resolve().parent / p
        return p.resolve()
    return Path(__file__).resolve().parent / "blocked_report"


def _scan_tag_index() -> tuple[dict[str, list[Path]], list[str]]:
    """
    Scan top-level pen-test folders for .tag-bugcrowd-<short_id> markers.

    Returns:
      (tag_index, errors)
      tag_index: short_id -> [folder_paths]
    """
    root = _pen_test_root()
    tag_index: dict[str, list[Path]] = {}
    errors: list[str] = []

    for folder in sorted(root.glob("20[0-9][0-9]-[0-1][0-9]-[0-3][0-9]_*")):
        if not folder.is_dir():
            continue

        tags = sorted(p for p in folder.glob(f"{TAG_PREFIX}*") if p.is_file())
        if len(tags) > 1:
            tag_names = ", ".join(t.name for t in tags)
            errors.append(
                f"{folder}: has multiple BugCrowd tags ({tag_names}). Keep exactly one tag file per folder."
            )

        for tag_path in tags:
            short_id = tag_path.name[len(TAG_PREFIX):]
            if not SHORT_ID_RE.fullmatch(short_id):
                errors.append(
                    f"{tag_path}: invalid short_id format in tag filename; expected {TAG_PREFIX}<8 hex chars>."
                )
                continue
            tag_index.setdefault(short_id, []).append(folder.resolve())

    for short_id, folders in tag_index.items():
        if len(folders) > 1:
            folder_list = ", ".join(str(p) for p in folders)
            errors.append(
                f"short_id {short_id}: appears in multiple tag files across folders ({folder_list}). Keep a one-to-one mapping."
            )

    return tag_index, errors


def validate_submission(obj: dict, category: str, index: int) -> list[str]:
    errors = []
    if not isinstance(obj, dict):
        errors.append(f"{category}[{index}]: must be an object")
        return errors

    required_keys = set(REQUIRED_SUBMISSION_KEYS)
    allowed_extra = set(ALLOWED_OPTIONAL_KEYS)

    if category == "simple_reply":
        required_keys |= set(SIMPLE_REPLY_REQUIRED_KEYS)

    if category == "pen_test_already_created":
        required_keys |= set(PEN_TEST_ALREADY_CREATED_KEYS)

    missing = required_keys - set(obj.keys())
    if missing:
        errors.append(f"{category}[{index}]: missing keys: {sorted(missing)}")

    extra = set(obj.keys()) - required_keys - allowed_extra
    if extra:
        errors.append(f"{category}[{index}]: unknown keys: {sorted(extra)}")

    for key in REQUIRED_SUBMISSION_KEYS:
        if key not in obj:
            continue
        val = obj[key]
        if not isinstance(val, str):
            errors.append(f"{category}[{index}].{key}: must be string, got {type(val).__name__}")

    if category == "simple_reply":
        sr = obj.get("simple_reply_reason")
        if not isinstance(sr, str):
            errors.append(f"{category}[{index}].simple_reply_reason: must be string")
        elif not sr.strip():
            errors.append(f"{category}[{index}].simple_reply_reason: must not be empty")

    if "web" in obj and isinstance(obj["web"], str) and not obj["web"].startswith("http"):
        errors.append(f"{category}[{index}].web: must be a URL (http/https)")

    if "local" in obj and isinstance(obj["local"], str):
        if not obj["local"].endswith(".md"):
            errors.append(f"{category}[{index}].local: should be path to .md file")
        if not obj["local"].startswith("/"):
            errors.append(f"{category}[{index}].local: must be full (absolute) path")

    if "short_id" in obj and isinstance(obj.get("short_id"), str):
        if not SHORT_ID_RE.fullmatch(obj["short_id"]):
            errors.append(f"{category}[{index}].short_id: must be 8 lowercase hex chars")

    if category == "pen_test_already_created":
        pf = obj.get("pentest_folder")
        te = obj.get("tag_exists")
        sid = obj.get("short_id")

        if "pentest_folder" in obj:
            if not isinstance(pf, str):
                errors.append(f"{category}[{index}].pentest_folder: must be string")
            else:
                p = Path(pf)
                if not p.is_absolute():
                    errors.append(
                        f"{category}[{index}].pentest_folder: must be absolute path"
                    )
                elif not p.exists() or not p.is_dir():
                    errors.append(
                        f"{category}[{index}].pentest_folder: directory not found: {pf}"
                    )

        if "tag_exists" in obj and not isinstance(te, bool):
            errors.append(f"{category}[{index}].tag_exists: must be boolean true/false")

        if isinstance(pf, str) and isinstance(sid, str) and SHORT_ID_RE.fullmatch(sid):
            expected = _expected_tag_file(Path(pf), sid)
            expected_exists = expected.is_file()

            if isinstance(te, bool):
                if te is False:
                    errors.append(
                        f"{category}[{index}] ({sid}): tag_exists=false is not allowed. "
                        f"Create tag file with: touch '{expected}' and set tag_exists=true."
                    )
                if te != expected_exists:
                    state = "exists" if expected_exists else "missing"
                    errors.append(
                        f"{category}[{index}] ({sid}): tag_exists={te} does not match filesystem ({state}) at {expected}."
                    )

            if not expected_exists:
                errors.append(
                    f"{category}[{index}] ({sid}): missing expected tag file {expected}. "
                    f"Create with: touch '{expected}'"
                )

    return errors


def validate_report(data: dict) -> list[str]:
    errors = []
    if not isinstance(data, dict):
        return ["Root must be a JSON object"]

    keys = set(data.keys())
    if keys != REQUIRED_TOP_LEVEL_KEYS:
        missing = REQUIRED_TOP_LEVEL_KEYS - keys
        extra = keys - REQUIRED_TOP_LEVEL_KEYS
        if missing:
            errors.append(f"Missing top-level keys: {sorted(missing)}")
        if extra:
            errors.append(f"Unknown top-level keys: {sorted(extra)}")

    for key in REQUIRED_TOP_LEVEL_KEYS:
        if key not in data:
            continue
        val = data[key]
        if not isinstance(val, list):
            errors.append(f"{key}: must be an array, got {type(val).__name__}")
            continue
        for i, item in enumerate(val):
            errors.extend(validate_submission(item, key, i))

    # Cross-check tag index globally for one-to-one consistency.
    tag_index, tag_scan_errors = _scan_tag_index()
    errors.extend(tag_scan_errors)

    # pen_test_already_created entries must point to the same folder as the tag index.
    seen_short_ids: set[str] = set()
    for item in data.get("pen_test_already_created", []):
        if not isinstance(item, dict):
            continue
        sid = item.get("short_id")
        pf = item.get("pentest_folder")

        if not isinstance(sid, str) or not SHORT_ID_RE.fullmatch(sid):
            continue
        if sid in seen_short_ids:
            errors.append(
                f"pen_test_already_created: duplicate short_id {sid}. Keep exactly one entry per short_id."
            )
        seen_short_ids.add(sid)

        if not isinstance(pf, str):
            continue

        tagged_folders = tag_index.get(sid, [])
        if len(tagged_folders) == 0:
            errors.append(
                f"pen_test_already_created ({sid}): no tag file found anywhere. "
                f"Expected {TAG_PREFIX}{sid} in folder {pf}."
            )
            continue

        if len(tagged_folders) == 1:
            tagged_folder = tagged_folders[0]
            if tagged_folder != Path(pf).resolve():
                errors.append(
                    f"pen_test_already_created ({sid}): pentest_folder mismatch. "
                    f"JSON has {pf} but tag index points to {tagged_folder}."
                )

    return errors


def main() -> int:
    if len(sys.argv) > 1:
        paths = [Path(sys.argv[1])]
    else:
        blocked_report_dir = _blocked_report_dir()
        if not blocked_report_dir.is_dir():
            print("blocked_report/ not found", file=sys.stderr)
            return 1
        paths = sorted(blocked_report_dir.glob(_report_filename_glob()))

    if not paths:
        print(f"No report files found matching {_report_filename_glob()}", file=sys.stderr)
        return 1

    exit_code = 0
    for path in paths:
        print(f"Validating {path.name} ...")
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"  ERROR: {e}", file=sys.stderr)
            exit_code = 1
            continue

        errs = validate_report(data)
        if errs:
            for e in errs:
                print(f"  ERROR: {e}", file=sys.stderr)
            exit_code = 1
        else:
            total = sum(len(data[k]) for k in REQUIRED_TOP_LEVEL_KEYS if k in data)
            print(f"  OK (total submissions: {total})")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
