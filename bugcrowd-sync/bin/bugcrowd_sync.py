#!/usr/bin/env python3
import argparse
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
  sys.path.insert(0, str(ROOT_DIR))

from lib.bugcrowd_api import BugCrowdClient, BugCrowdConfig
from lib.engine import sync_bugcrowd
from lib.progress import SyncProgress

DEFAULT_BASE_URL = os.environ.get("BUGCROWD_BASE_URL", "https://api.bugcrowd.com")
STATE_DIRNAME = ".state"


def main() -> int:
  ap = argparse.ArgumentParser(description="BugCrowd to Markdown exporter")
  ap.add_argument("--out", required=True, help="Output directory for markdown files")
  ap.add_argument("--page-size", type=int, default=100, help="Page size for API pagination")
  ap.add_argument("--no-progress", action="store_true", help="Disable progress output")
  ap.add_argument("--force-deep-sync", action="store_true", help="Force deep sync on all submissions, ignoring skip optimization (useful for recovering from corruption)")
  args = ap.parse_args()

  username = os.environ.get("BUGCROWD_USERNAME", "").strip()
  password = os.environ.get("BUGCROWD_PASSWORD", "").strip()
  auth_header = os.environ.get("BUGCROWD_AUTHHEADER", "").strip()
  
  # Need either auth_header (Token) or username+password (Basic)
  if not auth_header and (not username or not password):
    raise SystemExit("Set BUGCROWD_AUTHHEADER (Token auth) or BUGCROWD_USERNAME and BUGCROWD_PASSWORD (Basic auth)")

  out_dir = Path(args.out)
  state_dir = out_dir.parent / STATE_DIRNAME
  progress = SyncProgress(enabled=not args.no_progress)

  client = BugCrowdClient(
    BugCrowdConfig(
      base_url=DEFAULT_BASE_URL,
      username=username,
      password=password,
      auth_header=auth_header,
    )
  )

  state_path = state_dir / "bugcrowd.json"
  sync_bugcrowd(
    data_dir=out_dir,
    state_path=state_path,
    client=client,
    progress=progress,
    base_url=DEFAULT_BASE_URL,
    force_deep_sync=args.force_deep_sync,
  )

  return 0


if __name__ == "__main__":
  raise SystemExit(main())

