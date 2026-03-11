#!/usr/bin/env python3
"""Count BugCrowd submissions by date range (created_at).
Reads from .state/bugcrowd.json - run sync first for accurate counts.
Usage:
  --since YYYY-MM-DD       Count submissions created on or after this date
  --between START,END      Count submissions created between START and END (inclusive)
Either --since or --between is required.
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / ".state" / "bugcrowd.json"


def parse_date(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d")


def parse_iso(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        if ts.endswith("Z"):
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Count submissions by date range (created_at)")
    ap.add_argument("--since", metavar="YYYY-MM-DD", help="Count created on or after this date")
    ap.add_argument(
        "--between",
        metavar="START,END",
        help="Count created between START and END (inclusive), e.g. 2025-01-01,2026-01-01",
    )
    args = ap.parse_args()

    if not args.since and not args.between:
        ap.error("Either --since or --between is required")

    if not STATE_PATH.exists():
        print(f"Error: State file not found: {STATE_PATH}", file=sys.stderr)
        print("Run 'make sync' first to populate state.", file=sys.stderr)
        return 1

    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    submissions = state.get("submissions", {})
    if not isinstance(submissions, dict):
        submissions = {}

    count = 0
    for sid, meta in submissions.items():
        if not isinstance(meta, dict):
            continue
        created = parse_iso(meta.get("created_at", ""))
        if not created:
            continue
        created_date = created.date()

        if args.since:
            since_date = parse_date(args.since).date()
            if created_date >= since_date:
                count += 1
        else:
            start_s, end_s = args.between.split(",", 1)
            start_date = parse_date(start_s.strip()).date()
            end_date = parse_date(end_s.strip()).date()
            if start_date <= created_date <= end_date:
                count += 1

    print(count)
    return 0


if __name__ == "__main__":
    sys.exit(main())
