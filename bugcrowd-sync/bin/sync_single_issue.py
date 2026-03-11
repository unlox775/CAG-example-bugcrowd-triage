#!/usr/bin/env python3
"""Sync a single BugCrowd issue for debugging/examination."""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
  sys.path.insert(0, str(ROOT_DIR))

from lib.bugcrowd_api import BugCrowdClient, BugCrowdConfig
from lib.engine import _extract_submission_info, _load_state, _save_state, CURRENT_SYNC_VERSION, _detect_blocker_status
from lib.paths import compute_md_path
from lib.writer import write_submission_markdown
from lib.models import categorize_state, SubmissionState
from lib.fs import prune_empty_dirs, remove_if_exists, move_submission_files

DEFAULT_BASE_URL = os.environ.get("BUGCROWD_BASE_URL", "https://api.bugcrowd.com")


def main() -> int:
  ap = argparse.ArgumentParser(description="Sync a single BugCrowd issue")
  ap.add_argument("submission_id", help="BugCrowd submission ID (UUID)")
  ap.add_argument("--out", default="data", help="Output directory")
  ap.add_argument("--dump-json", action="store_true", help="Dump full JSON response to stdout")
  args = ap.parse_args()

  username = os.environ.get("BUGCROWD_USERNAME", "").strip()
  password = os.environ.get("BUGCROWD_PASSWORD", "").strip()
  auth_header = os.environ.get("BUGCROWD_AUTHHEADER", "").strip()
  
  if not auth_header and (not username or not password):
    raise SystemExit("Set BUGCROWD_AUTHHEADER (Token auth) or BUGCROWD_USERNAME and BUGCROWD_PASSWORD (Basic auth)")

  client = BugCrowdClient(
    BugCrowdConfig(
      base_url=DEFAULT_BASE_URL,
      username=username,
      password=password,
      auth_header=auth_header,
    )
  )

  submission_id = args.submission_id
  print(f"Fetching submission {submission_id}...", file=sys.stderr)
  
  # Get full submission - try to include author/identity data for comments
  # Blockers are NOT a valid include parameter, but we can try to include author data
  # Try including author/identity relationships for comments
  full_submission = client.get_submission(submission_id, include=["researcher", "comments", "comments.author", "activities", "activities.actor", "file_attachments"])
  
  if args.dump_json:
    print(json.dumps(full_submission, indent=2))
    return 0
  
  # Extract info
  info = _extract_submission_info(full_submission)
  if not info:
    print("ERROR: Could not extract submission info", file=sys.stderr)
    return 1
  
  submission_id_parsed, title, state_str, priority, category, created_at, updated_at, attachment_count = info
  
  print(f"\nSubmission Info:", file=sys.stderr)
  print(f"  ID: {submission_id_parsed}", file=sys.stderr)
  print(f"  Title: {title}", file=sys.stderr)
  print(f"  State: {state_str!r} → Category: {category}", file=sys.stderr)
  print(f"  Priority: {'P' + str(priority) if priority else 'unset'}", file=sys.stderr)
  print(f"  Created: {created_at}", file=sys.stderr)
  print(f"  Updated: {updated_at}", file=sys.stderr)
  
  # Get comments, attachments, and external issues
  comments = client.get_submission_comments(submission_id)
  
  # Also try to get activities separately (API v2025-04-23+) for blocker detection
  activities = client.get_submission_activities(submission_id)
  
  # Merge activities into comments for processing
  if activities:
    comment_ids = {c.get("id") for c in comments if isinstance(c, dict) and c.get("id")}
    for act in activities:
      if isinstance(act, dict) and act.get("id") not in comment_ids:
        comments.append(act)
  
  attachments = client.get_submission_attachments(submission_id)
  external_issues = client.get_submission_external_issues(submission_id)
  
  print(f"\nContent Summary:", file=sys.stderr)
  print(f"  Comments/Activities: {len(comments)}", file=sys.stderr)
  print(f"  Attachments: {len(attachments)}", file=sys.stderr)
  print(f"  External Issues: {len(external_issues)}", file=sys.stderr)
  if external_issues:
    for ext_issue in external_issues:
      attrs = ext_issue.get("attributes", {}) if isinstance(ext_issue, dict) and "attributes" in ext_issue else ext_issue
      issue_key = attrs.get("remote_id") or attrs.get("issue_key") or attrs.get("key") or ""
      issue_url = attrs.get("remote_url") or attrs.get("issue_url") or ""
      print(f"    - {issue_key}: {issue_url}", file=sys.stderr)
  
  # Load state
  out_dir = Path(args.out)
  state_dir = out_dir.parent / ".state"
  state_path = state_dir / "bugcrowd.json"
  state = _load_state(state_path)
  prev_submissions = state.get("submissions", {}) if isinstance(state, dict) else {}
  prev = prev_submissions.get(submission_id_parsed) if isinstance(prev_submissions, dict) else None
  
  # Phase 1: Check previous blocked status and compute initial path
  prev_is_blocked = prev.get("is_blocked") if isinstance(prev, dict) else False
  prev_blocker_review = prev.get("blocker_review") if isinstance(prev, dict) else False
  is_blocked_prev = prev_is_blocked or prev_blocker_review  # If in blocker_review, assume still blocked
  
  # Phase 1: Compute path based on previous blocked status (like full sync Phase 1)
  md_path_phase1 = compute_md_path(
    submission_id=submission_id_parsed,
    title=title,
    base=out_dir,
    state=state_str,
    priority=priority,
    created_at=created_at,
    is_blocked=is_blocked_prev,  # Use previous blocked status for Phase 1
  )
  
  print(f"\nPhase 1: Initial path (based on previous blocked status): {md_path_phase1}", file=sys.stderr)
  
  # Phase 2: Detect blocker status from activities (like full sync Phase 2)
  # Merge activities from activities endpoint with comments for blocker detection
  activities_for_blocker = list(comments or [])
  if activities:
    comment_ids = {c.get("id") for c in comments if isinstance(c, dict) and c.get("id")}
    for act in activities:
      if isinstance(act, dict) and act.get("id") not in comment_ids:
        activities_for_blocker.append(act)
  
  # Detect current blocked status from activities
  is_blocked_current = _detect_blocker_status(activities_for_blocker)
  
  # Check if blocked status changed
  blocker_status_changed = (prev_is_blocked != is_blocked_current)
  
  if blocker_status_changed:
    print(f"\nPhase 2: Blocked status changed: {prev_is_blocked} -> {is_blocked_current}", file=sys.stderr)
  else:
    print(f"\nPhase 2: Blocked status unchanged: {is_blocked_current}", file=sys.stderr)
  
  # Phase 2: Compute final path based on current blocked status
  md_path_phase2 = compute_md_path(
    submission_id=submission_id_parsed,
    title=title,
    base=out_dir,
    state=state_str,
    priority=priority,
    created_at=created_at,
    is_blocked=is_blocked_current,  # Use current blocked status for Phase 2
  )
  
  print(f"Phase 2: Final path (based on current blocked status): {md_path_phase2}", file=sys.stderr)
  
  # Use Phase 1 path initially (will move in Phase 3 if needed)
  md_path = md_path_phase1
  
  # Phase 2: Deep sync - write markdown file
  submission_id_to_md = {submission_id_parsed: md_path}
  attach_dir = md_path.with_suffix("") if attachments else None
  
  write_submission_markdown(
    out_path=md_path,
    submission=full_submission,
    comments=comments,
    attachments=attachments,
    external_issues=external_issues,
    base_url=DEFAULT_BASE_URL,
    submission_id_to_md=submission_id_to_md,
    attachment_dir=attach_dir,
    download_attachment=client.download_attachment,
    client=client,  # Pass client for downloading embed attachments from comments
    full_submission=full_submission,  # Pass full submission for author resolution from included resources
    shallow=False,
    verbose=True,  # Enable verbose output for single-issue sync
  )
  
  print(f"\n✓ Phase 2: Written to {md_path}", file=sys.stderr)
  
  # Phase 3: Blocker review - move file if blocked status changed (like full sync Phase 3)
  if blocker_status_changed and md_path_phase1 != md_path_phase2:
    print(f"\nPhase 3: Moving file due to blocked status change...", file=sys.stderr)
    prev_path = Path(prev.get("md_path")) if isinstance(prev, dict) and prev.get("md_path") else None
    
    # Determine source path: use previous path if it exists, otherwise use Phase 1 path
    source_path = prev_path if prev_path and prev_path.exists() else md_path_phase1 if md_path_phase1.exists() else None
    
    if source_path and source_path.exists() and source_path != md_path_phase2:
      print(f"  Moving from {source_path} to {md_path_phase2}", file=sys.stderr)
      if move_submission_files(source_path, md_path_phase2):
        md_path = md_path_phase2  # Update to final path after successful move
        print(f"✓ Phase 3: Moved to {md_path_phase2}", file=sys.stderr)
      else:
        print(f"✗ Phase 3: Failed to move - keeping at {source_path}", file=sys.stderr)
        md_path = source_path  # Keep at source if move failed
        # Keep blocker_review flag so full sync will retry
    elif not source_path or not source_path.exists():
      # File doesn't exist at source - already at correct location or needs to be created
      md_path = md_path_phase2  # Use final path
      print(f"Phase 3: Using final path (file doesn't exist at initial location)", file=sys.stderr)
    else:
      # Paths are the same - no move needed
      print(f"Phase 3: No move needed (already at correct location)", file=sys.stderr)
  else:
    print(f"\nPhase 3: No blocker status change - no move needed", file=sys.stderr)
  
  # Narrow-scope cleanup for this single issue:
  # Find all files matching this submission ID across all possible locations
  id_prefix = submission_id_parsed[:8]
  removed_old_files = 0
  
  # Search in all possible folders: new, unresolved, resolved, rejected, blocked
  for category_folder in ["new", "unresolved", "resolved", "rejected", "blocked"]:
    category_base = out_dir / category_folder
    if category_base.exists():
      for priority_folder in ["P1", "P2", "P3", "P4", "P5", "unset"]:
        priority_base = category_base / priority_folder
        if priority_base.exists():
          for old_file in priority_base.glob(f"*-{id_prefix}.md"):
            if old_file != md_path:
              # This is an old file for this submission in a different location
              print(f"  Removing old file: {old_file}", file=sys.stderr)
              remove_if_exists(old_file)
              # Also remove its attachment folder if it exists
              old_attach_folder = old_file.with_suffix("")
              if old_attach_folder.exists() and old_attach_folder.is_dir():
                remove_if_exists(old_attach_folder)
              removed_old_files += 1
  
  if removed_old_files > 0:
    print(f"✓ Removed {removed_old_files} old file(s) for this submission", file=sys.stderr)
  
  # Remove attachment folder if it exists but has no attachments
  attach_folder = md_path.with_suffix("")
  if attach_folder.exists() and attach_folder.is_dir():
    if not attachments:
      remove_if_exists(attach_folder)
    else:
      has_files = any(attach_folder.iterdir())
      if not has_files:
        remove_if_exists(attach_folder)
  
  # Prune any empty parent directories (but keep the data root)
  prune_empty_dirs(out_dir, keep_root=True)
  
  # Update state file with current blocked status and blocker_review flag
  # Save state (preserve all previous state for other submissions, update this one)
  new_state = {}
  for k, v in prev_submissions.items():
    if isinstance(v, dict):
      new_state[k] = SubmissionState(
        updated_at=v.get("updated_at", ""),
        created_at=v.get("created_at", ""),
        md_path=v.get("md_path", ""),
        sync_state=v.get("sync_state", "shallow"),
        sync_version=v.get("sync_version") if v.get("sync_version") is not None else None,
        is_blocked=v.get("is_blocked", False),
        blocker_review=v.get("blocker_review", False),
      )
  
  # Update state for the synced submission with current blocked status
  # Clear blocker_review if move succeeded or wasn't needed
  move_succeeded = blocker_status_changed and md_path == md_path_phase2
  blocker_review_flag = blocker_status_changed and not move_succeeded  # Keep flag if move failed
  
  new_state[submission_id_parsed] = SubmissionState(
    updated_at=updated_at if updated_at else "",
    created_at=created_at if created_at else "",
    md_path=str(md_path),  # Use final path (after Phase 3 move if it happened)
    sync_state="deep",
    sync_version=CURRENT_SYNC_VERSION,
    is_blocked=is_blocked_current,  # Current blocked status (from Phase 2 detection)
    blocker_review=blocker_review_flag,  # Mark for review if move failed (full sync will retry)
  )
  _save_state(state_path, new_state)
  
  print(f"✓ Updated state file: {state_path}", file=sys.stderr)
  return 0


if __name__ == "__main__":
  raise SystemExit(main())

