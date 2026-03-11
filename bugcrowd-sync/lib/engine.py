import re
from pathlib import Path
from typing import Dict, Any, List, Set, Optional, Tuple
import json
import signal
import sys
import time

from .fs import ensure_dir, prune_empty_dirs, cleanup_tree, remove_if_exists, move_submission_files
from .models import SubmissionState, categorize_state
from .progress import SyncProgress
from .writer import write_submission_markdown
from .paths import compute_md_path

# Global state for signal handling
_current_state: Optional[Dict[str, SubmissionState]] = None
_current_state_path: Optional[Path] = None


class SyncResult:
  def __init__(self, total: int, skipped: int, updated: int, deleted: int, removed_extra: int, shallow: int = 0):
    self.total = total
    self.skipped = skipped
    self.updated = updated
    self.deleted = deleted
    self.removed_extra = removed_extra
    self.shallow = shallow


def _load_state(path: Path) -> Dict[str, Any]:
  """Load state from file and normalize old format."""
  try:
    state = json.loads(path.read_text(encoding="utf-8"))
    # Normalize old state format: add sync_version, is_blocked, blocker_review if missing
    if "submissions" in state:
      for sub_id, sub_data in state["submissions"].items():
        if isinstance(sub_data, dict):
          if "sync_version" not in sub_data:
            sub_data["sync_version"] = None  # None = version 1 or older
          if "is_blocked" not in sub_data:
            sub_data["is_blocked"] = False  # Default to False for old state format
          if "blocker_review" not in sub_data:
            sub_data["blocker_review"] = False  # Default to False for old state format
    return state
  except Exception:
    return {"submissions": {}}


def _normalize_loaded_state(state: Dict[str, Any]) -> Dict[str, SubmissionState]:
  """Convert loaded state dict to SubmissionState objects, normalizing old format."""
  submissions = state.get("submissions", {}) if isinstance(state, dict) else {}
  normalized = {}
  for sub_id, sub_data in submissions.items():
    if isinstance(sub_data, dict):
      normalized[sub_id] = SubmissionState(
        updated_at=sub_data.get("updated_at", ""),
        created_at=sub_data.get("created_at", ""),
        md_path=sub_data.get("md_path", ""),
        sync_state=sub_data.get("sync_state", "shallow"),
        sync_version=sub_data.get("sync_version") if sub_data.get("sync_version") is not None else None,
        is_blocked=sub_data.get("is_blocked", False),  # Default to False for old state format
        blocker_review=sub_data.get("blocker_review", False),  # Default to False for old state format
      )
  return normalized


# Current sync version - increment when sync format changes
CURRENT_SYNC_VERSION = 4

def _save_state(path: Path, submissions: Dict[str, SubmissionState]) -> None:
  """Save state to file."""
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(
    json.dumps(
      {
        "submissions": {
          k: {
            "updated_at": v.updated_at,
            "created_at": v.created_at,
            "md_path": v.md_path,
            "sync_state": v.sync_state,
            "sync_version": v.sync_version if v.sync_version is not None else None,
            "is_blocked": v.is_blocked,
            "blocker_review": v.blocker_review,
          }
          for k, v in submissions.items()
        }
      },
      indent=2,
      sort_keys=True,
    ),
    encoding="utf-8",
  )


def _signal_handler(signum, frame):
  """Handle SIGINT (Ctrl+C) by saving state before exiting."""
  if _current_state is not None and _current_state_path is not None:
    print("\n[bugcrowd] Interrupted - saving state...", file=sys.stderr, flush=True)
    try:
      _save_state(_current_state_path, _current_state)
      print(f"[bugcrowd] State saved to {_current_state_path}", file=sys.stderr, flush=True)
    except Exception as e:
      print(f"[bugcrowd] Error saving state: {e}", file=sys.stderr, flush=True)
  sys.exit(130)  # Exit with code 130 for SIGINT


def _detect_blocker_status(comments: List[Dict[str, Any]]) -> bool:
  """Detect if a submission is currently blocked by analyzing activities.
  
  Looks for "blocker.created" and "blocker.unblocked" events in chronological order.
  The most recent event determines the current status.
  
  Returns True if currently blocked, False otherwise.
  """
  blocker_events = []
  
  for c in comments or []:
    attrs = c.get("attributes", {}) if isinstance(c, dict) and "attributes" in c else c
    event_key = attrs.get("key") or attrs.get("event") or attrs.get("event_type") or ""
    created_at = attrs.get("created_at") or attrs.get("created") or ""
    
    # Look for blocker events
    if event_key in ("blocker.created", "blocker.unblocked"):
      if created_at:
        blocker_events.append((created_at, event_key))
  
  if not blocker_events:
    # No blocker events found - not blocked
    return False
  
  # Sort by date (newest first)
  blocker_events.sort(key=lambda x: x[0], reverse=True)
  
  # Most recent event determines current status
  latest_event = blocker_events[0][1]
  return latest_event == "blocker.created"


# Regex to extract 8-char UUID prefix from markdown filenames: ...-{8hex}.md
_FILENAME_ID_PATTERN = re.compile(r"-([a-f0-9]{8})\.md$", re.IGNORECASE)


def _reconcile_data_corruption(
  data_dir: Path,
  submission_id_to_md: Dict[str, Path],
  prev_submissions: Dict[str, Any],
  remove_if_exists_fn,
  move_submission_files_fn,
  progress: Optional[SyncProgress],
) -> Tuple[int, Set[str], Dict[str, int]]:
  """Detect and fix duplicate/orphaned/wrong-place submission files.
  
  - Duplicates: same submission appears in multiple paths. Keep the one matching API
    (submission_id_to_md), delete the rest. Mark kept submission for full resync.
  - Wrong place: single copy exists at wrong path. Move to correct path (saves re-transfer).
  - Orphans: files on disk that don't match any current submission (handled by cleanup_tree).
  
  Returns: (deleted_or_moved_count, needs_resync_ids, stats_dict for telemetry)
  """
  data_dir_resolved = data_dir.resolve()

  # Map 8-char suffix -> full submission_id (from API)
  suffix_to_id: Dict[str, str] = {}
  for sid in submission_id_to_md:
    if len(sid) >= 8:
      suffix_to_id[sid[:8].lower()] = sid

  # Scan all .md files, group by submission_id
  id_to_paths: Dict[str, List[Path]] = {}

  for md_file in data_dir_resolved.rglob("*.md"):
    if not md_file.is_file():
      continue
    match = _FILENAME_ID_PATTERN.search(md_file.name)
    if not match:
      continue
    suffix = match.group(1).lower()
    submission_id = suffix_to_id.get(suffix)
    if not submission_id:
      continue
    path_resolved = md_file.resolve()
    id_to_paths.setdefault(submission_id, []).append(path_resolved)

  action_count = 0
  needs_resync: Set[str] = set()
  stats: Dict[str, int] = {
    "duplicate_copies_removed": 0,
    "moved_from_wrong_place": 0,
    "submissions_marked_resync": 0,
  }

  for submission_id, paths in id_to_paths.items():
    correct_path = submission_id_to_md[submission_id].resolve()
    paths_resolved = [p.resolve() for p in paths]

    if len(paths_resolved) > 1:
      # Duplicates: keep correct_path copy, delete others
      # If correct_path has no file, move best copy there first
      correct_has_file = correct_path in paths_resolved or correct_path.exists()
      if not correct_has_file:
        # Move first copy to correct location (preserves content)
        src = paths_resolved[0]
        if move_submission_files_fn(src, correct_path):
          action_count += 1
          stats["moved_from_wrong_place"] += 1
          paths_resolved = [p for p in paths_resolved if p != src]
          paths_resolved.append(correct_path)
      to_delete = [p for p in paths_resolved if p != correct_path]
      for wrong_path in to_delete:
        try:
          remove_if_exists_fn(wrong_path)
          remove_if_exists_fn(wrong_path.with_suffix(""))  # attachment folder
          action_count += 1
          stats["duplicate_copies_removed"] += 1
        except Exception:
          pass
      needs_resync.add(submission_id)
      stats["submissions_marked_resync"] += 1
    elif len(paths_resolved) == 1 and paths_resolved[0] != correct_path:
      # Wrong place (single copy): move to correct path
      src = paths_resolved[0]
      if move_submission_files_fn(src, correct_path):
        action_count += 1
        stats["moved_from_wrong_place"] += 1
        needs_resync.add(submission_id)
        stats["submissions_marked_resync"] += 1

  return action_count, needs_resync, stats


def _extract_submission_info(sub: Dict[str, Any]) -> Optional[Tuple[str, str, str, Optional[int], str, str, str, Optional[int]]]:
  """Extract submission info from API response. Returns (id, title, state, priority, category, created_at, updated_at, attachment_count) or None.
  
  attachment_count is extracted from relationships.file_attachments if available, otherwise None.
  """
  # Handle JSON API format (with "data" wrapper) or direct format
  if isinstance(sub, dict) and "data" in sub:
    sub_data = sub.get("data", {})
  else:
    sub_data = sub if isinstance(sub, dict) else {}
  
  if not isinstance(sub_data, dict):
    return None
  
  attrs = sub_data.get("attributes", {}) if isinstance(sub_data, dict) else {}
  submission_id = sub_data.get("id", "") if isinstance(sub_data, dict) else ""
  if not submission_id and isinstance(sub, dict):
    submission_id = sub.get("id", "")
  
  if not submission_id:
    return None
  
  title = attrs.get("title") or attrs.get("name") or "untitled"
  # Extract state - check multiple possible fields
  state_str = (
    attrs.get("state") or 
    attrs.get("status") or  # Some APIs use "status" instead of "state"
    attrs.get("current_state") or  # Alternative field name
    ""
  )
  category = categorize_state(state_str)  # new, unresolved, resolved, rejected, or blocked
  # BugCrowd uses submitted_at for creation date, not created_at
  created_at = attrs.get("submitted_at") or attrs.get("created_at") or attrs.get("created") or ""
  # For updated_at, try various transition fields or use submitted_at if none found
  updated_at = (
    attrs.get("last_transitioned_to_resolved_at") or
    attrs.get("last_transitioned_to_unresolved_at") or
    attrs.get("last_transitioned_to_triaged_at") or
    attrs.get("last_transitioned_to_informational_at") or
    attrs.get("last_transitioned_to_not_applicable_at") or
    attrs.get("last_transitioned_to_not_reproducible_at") or
    attrs.get("last_transitioned_to_out_of_scope_at") or
    attrs.get("updated_at") or
    attrs.get("updated") or
    created_at  # Fallback to submitted_at if no update date found
  )
  
  # Priority: BugCrowd uses "severity" field with numbers (1-5) or null
  # Severity 1 = P1 (Critical), 2 = P2 (High), 3 = P3 (Medium), 4 = P4 (Low), 5 = P5 (Info)
  priority = attrs.get("severity") or attrs.get("priority")
  if priority is not None:
    try:
      priority = int(priority)
      if priority not in (1, 2, 3, 4, 5):
        priority = None
    except (ValueError, TypeError):
      priority = None
  
  # Check relationships for file_attachments count
  attachment_count = None
  relationships = sub_data.get("relationships", {}) if isinstance(sub_data, dict) else {}
  if isinstance(relationships, dict) and "file_attachments" in relationships:
    file_attachments_rel = relationships.get("file_attachments", {})
    if isinstance(file_attachments_rel, dict):
      # JSON API format: relationships.file_attachments.data is an array
      att_data = file_attachments_rel.get("data", [])
      if isinstance(att_data, list):
        attachment_count = len(att_data)
      # Some APIs might have a "meta" field with count
      elif isinstance(file_attachments_rel, dict) and "meta" in file_attachments_rel:
        meta = file_attachments_rel.get("meta", {})
        if isinstance(meta, dict) and "count" in meta:
          try:
            attachment_count = int(meta["count"])
          except (ValueError, TypeError):
            pass
  
  return (submission_id, title, state_str, priority, category, created_at, updated_at, attachment_count)


def sync_bugcrowd(
  *,
  data_dir: Path,
  state_path: Path,
  client,
  progress: SyncProgress,
  base_url: str,
  force_deep_sync: bool = False,
) -> SyncResult:
  """Sync all BugCrowd submissions to markdown files with two-phase sync.
  
  Args:
    force_deep_sync: If True, skip the optimization that skips already-deep-synced submissions.
                     This forces a full deep sync on all submissions, useful for recovering from corruption.
  """
  global _current_state, _current_state_path
  
  # Initialize result variables (in case of early exception)
  total = 0
  shallow_count = 0
  skipped_shallow = 0
  updated_count = 0
  skipped_deep = 0
  deleted = 0
  removed_extra_phase1 = 0
  removed_extra_phase2 = 0
  
  # Set up signal handler for Ctrl+C to save state before exiting
  _current_state_path = state_path
  original_sigint = signal.signal(signal.SIGINT, _signal_handler)
  
  try:
    ensure_dir(data_dir)
    state = _load_state(state_path)
    prev_submissions_raw = state.get("submissions", {}) if isinstance(state, dict) else {}
    # Keep as dict for easier access, but normalize when reading
    prev_submissions: Dict[str, Any] = prev_submissions_raw

    if progress:
      progress.update("[bugcrowd] Phase 1: Fetching submission index…", force=True)
    
    # Phase 1: Fetch lightweight index of all submissions with progress
    def fetch_progress(count, page):
      if progress:
        progress.update(f"[bugcrowd] Phase 1: Fetching submission index… (page {page}, {count} submissions so far)", force=(page % 5 == 0))
    
    submissions_index = client.get_all_submissions(progress_callback=fetch_progress)
    
    if progress:
      progress.print_final(f"[bugcrowd] Phase 1: Found {len(submissions_index)} submissions total")

    # Build paths for all submissions and extract info
    # Phase 1: Check previous is_blocked state to determine folder location
    # Tuple: (id, title, priority, category, created_at, updated_at, md_path, state_str, attachment_count, is_blocked_prev)
    submission_info: List[Tuple[str, str, Optional[int], str, str, str, Path, str, Optional[int], bool]] = []
    submission_id_to_md: Dict[str, Path] = {}
    
    for sub in submissions_index:
      info = _extract_submission_info(sub)
      if not info:
        continue
      
      submission_id, title, state_str, priority, category, created_at, updated_at, attachment_count = info
      
      # Phase 1: Check previous is_blocked state (if in blocker_review, assume still blocked)
      prev = prev_submissions.get(submission_id) if isinstance(prev_submissions, dict) else None
      prev_is_blocked = prev.get("is_blocked") if isinstance(prev, dict) else False
      prev_blocker_review = prev.get("blocker_review") if isinstance(prev, dict) else False
      # If in blocker_review, assume it's still blocked (Phase 3 will move it if needed)
      is_blocked_prev = prev_is_blocked or prev_blocker_review
      
      md_path = compute_md_path(
        submission_id=submission_id,
        title=title,
        base=data_dir,
        state=state_str,
        priority=priority,
        created_at=created_at,
        is_blocked=is_blocked_prev,  # Use previous blocked status for Phase 1
      )
      submission_id_to_md[submission_id] = md_path
      submission_info.append((submission_id, title, priority, category, created_at, updated_at, md_path, state_str, attachment_count, is_blocked_prev))

    current_ids = set(submission_id_to_md.keys())
    new_state: Dict[str, SubmissionState] = {}

    # Reconciliation: detect duplicates, delete wrong copies, mark kept for full resync
    recon_deleted = 0
    recon_stats: Dict[str, int] = {}
    if submission_id_to_md:
      recon_deleted, needs_resync_ids, recon_stats = _reconcile_data_corruption(
        data_dir=data_dir,
        submission_id_to_md=submission_id_to_md,
        prev_submissions=prev_submissions,
        remove_if_exists_fn=remove_if_exists,
        move_submission_files_fn=move_submission_files,
        progress=progress,
      )
      for sid in needs_resync_ids:
        prev = prev_submissions.get(sid) if isinstance(prev_submissions, dict) else None
        if isinstance(prev, dict):
          prev["sync_state"] = "shallow"  # Force full resync in Phase 2
          prev["sync_version"] = None
      if recon_stats and (
        recon_stats.get("duplicate_copies_removed", 0) > 0
        or recon_stats.get("moved_from_wrong_place", 0) > 0
        or recon_stats.get("submissions_marked_resync", 0) > 0
      ):
        if progress:
          dup = recon_stats.get("duplicate_copies_removed", 0)
          moved = recon_stats.get("moved_from_wrong_place", 0)
          subs = recon_stats.get("submissions_marked_resync", 0)
          parts = []
          if dup:
            parts.append(f"{dup} duplicate(s) removed")
          if moved:
            parts.append(f"{moved} moved to correct path")
          parts.append(f"{subs} marked for full resync")
          progress.print_final(f"[bugcrowd] Reconciliation: {', '.join(parts)}")

    # Handle deletions
    deleted = 0
    for old_id, old_meta in prev_submissions.items():
      if old_id not in current_ids:
        old_md = Path(old_meta.get("md_path")) if isinstance(old_meta, dict) and old_meta.get("md_path") else None
        if old_md:
          remove_if_exists(old_md)
          remove_if_exists(old_md.with_suffix(""))  # Remove attachment folder
        deleted += 1

    # Phase 1: Fast shallow sync - create all markdown files with minimal data
    if progress:
      progress.update("[bugcrowd] Phase 1: Creating shallow markdown files…", force=True)
    
    shallow_count = 0
    skipped_shallow = 0
    total = len(submission_info)
    processed_shallow = 0
    
    for submission_id, title, priority, category, created_at, updated_at, out_path, state_str, attachment_count, is_blocked_prev in submission_info:
      processed_shallow += 1
      prev = prev_submissions.get(submission_id) if isinstance(prev_submissions, dict) else None
      prev_path = Path(prev.get("md_path")) if isinstance(prev, dict) and prev.get("md_path") else None
      prev_sync_state = prev.get("sync_state") if isinstance(prev, dict) else None
      
      # Check if file needs to be moved (path changed due to state/priority change)
      moved = False
      if prev_path and prev_path.exists() and prev_path != out_path:
        # Path changed - move files to new location
        if move_submission_files(prev_path, out_path):
          moved = True
          if progress:
            progress.update(f"[bugcrowd] Phase 1: Moved {submission_id[:8]} to new location", force=True)
      
      # CRITICAL: Don't create shallow files if file already exists and looks deep-synced
      # Sync version changes should trigger deep re-sync in Phase 2, NOT shallow overwrite in Phase 1
      prev_sync_version = prev.get("sync_version") if isinstance(prev, dict) else None
      prev_is_blocked = prev.get("is_blocked") if isinstance(prev, dict) else False
      prev_blocker_review = prev.get("blocker_review") if isinstance(prev, dict) else False
      
      if out_path.exists():
        # Check if file looks deep-synced (not just a shallow placeholder)
        # Shallow files have "_This file will be updated with full details in Phase 2._"
        try:
          file_content = out_path.read_text(encoding="utf-8")
          is_shallow_placeholder = "_This file will be updated with full details in Phase 2._" in file_content
        except Exception:
          # Can't read file - assume it's not a shallow placeholder
          is_shallow_placeholder = False
        
        if not is_shallow_placeholder or prev_sync_state == "deep" or prev_sync_version is not None:
          # File exists and is either:
          # 1. Deep-synced (has content beyond shallow placeholder), OR
          # 2. Marked as deep in state, OR
          # 3. Has sync_version in state (was deep-synced before)
          # Keep existing file - don't overwrite with shallow file
          # Phase 2 will update it if sync_version is wrong or other changes needed
          prev_created = prev.get("created_at", "") if isinstance(prev, dict) else ""
          prev_updated = prev.get("updated_at", "") if isinstance(prev, dict) else ""
          # Preserve existing state (including old sync_version - will be updated in Phase 2 if needed)
          # If prev_sync_version is None but file looks deep-synced, infer it was an older version
          inferred_version = prev_sync_version if prev_sync_version is not None else (CURRENT_SYNC_VERSION - 1 if CURRENT_SYNC_VERSION > 1 else None)
          new_state[submission_id] = SubmissionState(
            updated_at=updated_at if updated_at else prev_updated if prev_updated else "",
            created_at=created_at if created_at else prev_created if prev_created else "",
            md_path=str(out_path),
            sync_state=prev_sync_state if prev_sync_state else "deep",  # Preserve or assume deep
            sync_version=inferred_version,  # Use inferred version - Phase 2 will update if needed
            is_blocked=prev_is_blocked,  # Preserve previous blocked status
            blocker_review=prev_blocker_review,  # Preserve blocker_review flag
          )
          skipped_shallow += 1
          continue
      
      # File doesn't exist OR is a shallow placeholder - create/update shallow file
      
      # Create shallow markdown file (include severity/priority so it displays correctly)
      shallow_submission = {
        "data": {
          "id": submission_id,
          "attributes": {
            "title": title,
            "state": state_str,
            "severity": priority,  # Include severity so it displays correctly
            "created_at": created_at,
            "updated_at": updated_at,
          }
        }
      }
      
      write_submission_markdown(
        out_path=out_path,
        submission=shallow_submission,
        comments=[],
        attachments=[],
        base_url=base_url,
        submission_id_to_md=submission_id_to_md,
        attachment_dir=None,
        download_attachment=lambda x: b"",
        shallow=True,
      )
      
      # Phase 1: Preserve previous blocked status (if in blocker_review, keep it)
      new_state[submission_id] = SubmissionState(
        updated_at=updated_at if updated_at else "",
        created_at=created_at if created_at else "",
        md_path=str(out_path),
        sync_state="shallow",
        sync_version=None,  # Shallow sync doesn't have a version yet
        is_blocked=prev_is_blocked,  # Preserve previous blocked status
        blocker_review=prev_blocker_review,  # Preserve blocker_review flag
      )
      shallow_count += 1
      
      # Update progress with ETA every 10 items or at completion
      if progress and (processed_shallow % 10 == 0 or processed_shallow == total):
        progress.update_with_eta(
          f"[bugcrowd] Phase 1: Creating shallow files ({shallow_count} new, {skipped_shallow} already synced)",
          processed_shallow,
          total,
          status="bugcrowd",
          force=(processed_shallow % 10 == 0)
        )

    # Analyze what will need deep sync in Phase 2 (like Jira sync)
    # Go through all submissions and determine sync reasons (same logic as Phase 2 start)
    phase1_need_sync_count = 0
    phase1_reason_counts: Dict[str, int] = {}
    
    for submission_id, title, priority, category, created_at, updated_at, out_path, state_str, attachment_count, is_blocked_prev in submission_info:
      prev = prev_submissions.get(submission_id) if isinstance(prev_submissions, dict) else None
      prev_sync_state = prev.get("sync_state") if isinstance(prev, dict) else None
      prev_sync_version = prev.get("sync_version") if isinstance(prev, dict) else None
      prev_updated = prev.get("updated_at") if isinstance(prev, dict) else None
      
      # Determine sync reason (same logic as Phase 2)
      sync_reason = None
      
      if prev_sync_state != "deep":
        sync_reason = "not-deep-synced"
      elif prev_sync_version != CURRENT_SYNC_VERSION:
        sync_reason = f"sync-version-mismatch (v{prev_sync_version} -> v{CURRENT_SYNC_VERSION})"
      elif prev_updated != updated_at:
        sync_reason = "updated-at-changed"
      elif not out_path.exists():
        sync_reason = "file-missing"
      else:
        # Check attachment count mismatch
        if attachment_count is not None and prev_sync_state == "deep":
          attach_folder = out_path.with_suffix("")
          if attach_folder.exists():
            actual_count = len([f for f in attach_folder.iterdir() if f.is_file()])
            if actual_count != attachment_count:
              sync_reason = "attachment-count-mismatch"
          elif attachment_count > 0:
            sync_reason = "attachment-folder-missing"
      
      if sync_reason:
        phase1_need_sync_count += 1
        # For sync-version-mismatch, preserve full reason with version numbers
        # For other reasons, extract reason type (before parentheses) for grouping
        if sync_reason.startswith("sync-version-mismatch"):
          # Keep full reason with version numbers (e.g., "sync-version-mismatch (v2 -> v3)")
          phase1_reason_counts[sync_reason] = phase1_reason_counts.get(sync_reason, 0) + 1
        else:
          # Extract reason type for grouping (before parentheses)
          reason_type = sync_reason.split("(")[0].strip() if "(" in sync_reason else sync_reason
          phase1_reason_counts[reason_type] = phase1_reason_counts.get(reason_type, 0) + 1
    
    # Show comprehensive Phase 1 summary (like Jira sync)
    if progress:
      phase1_summary = f"[bugcrowd] Phase 1: Complete - Created {shallow_count} shallow files, skipped {skipped_shallow} already synced"
      if phase1_need_sync_count > 0:
        # Build reason summary string (sorted for consistent output)
        reason_summary = ", ".join([f"{count} {reason}" for reason, count in sorted(phase1_reason_counts.items())])
        phase1_summary += f", {phase1_need_sync_count} need deep sync ({reason_summary})"
      else:
        phase1_summary += ", 0 need deep sync"
      progress.print_final(phase1_summary)

    # Save state after Phase 1 completes (so progress is preserved if interrupted)
    _current_state = new_state
    _save_state(state_path, new_state)
    if progress:
      progress.print_final(f"[bugcrowd] Phase 1: State saved ({len(new_state)} submissions tracked)")
    
    # Cleanup at end of Phase 1: remove files/dirs not in expected set
    if progress:
      progress.update("[bugcrowd] Phase 1: Cleaning up old files...", force=True)
    
    allowed_files: Set[Path] = set()
    allowed_dirs: Set[Path] = {data_dir.resolve()}
    for p in submission_id_to_md.values():
      rp = p.resolve()
      allowed_files.add(rp)
      # Always add attachment folder path (even if it doesn't exist yet)
      # This preserves attachment folders from previous deep syncs during Phase 1 cleanup
      attach_folder = rp.with_suffix("")
      allowed_dirs.add(attach_folder.resolve())
      # Add all parent directories
      cur = rp.parent.resolve()
      while str(cur).startswith(str(data_dir.resolve())):
        allowed_dirs.add(cur)
        if cur == data_dir.resolve():
          break
        cur = cur.parent.resolve()
    
    # Also preserve attachment folders from previous deep syncs (check state file)
    for submission_id, prev_meta in prev_submissions.items():
      if not isinstance(prev_meta, dict):
        continue
      prev_md_path = prev_meta.get("md_path")
      if prev_md_path:
        prev_md = Path(prev_md_path)
        if prev_md.exists():
          # Add the attachment folder for this previously-synced submission
          prev_attach_folder = prev_md.with_suffix("")
          allowed_dirs.add(prev_attach_folder.resolve())
    
    removed_extra_phase1 = cleanup_tree(data_dir, allowed_files=allowed_files, allowed_dirs=allowed_dirs)
    prune_empty_dirs(data_dir, keep_root=True)
    
    if progress:
      if removed_extra_phase1 > 0:
        progress.print_final(f"[bugcrowd] Phase 1: Cleanup complete - removed {removed_extra_phase1} old files/dirs")
      else:
        progress.print_final(f"[bugcrowd] Phase 1: Cleanup complete - no files to remove")

    # Phase 2: Deep sync - update files with full data, sorted by:
    # 1. Category order: new, to_review, blocked, unresolved, resolved, rejected (order: 0..5)
    # 2. Highest priority first: P1 (1), P2 (2), P3 (3), P4 (4), P5 (5), then unset (999)
    # 3. Newest issues first (created_at descending - most recent first)
    # Note: This sorts submission_info (without reason), need_sync will be sorted separately
    def priority_sort_key(item: Tuple[str, str, Optional[int], str, str, str, Path, str, Optional[int], bool]) -> Tuple[int, int, int]:
      _, _, priority, category, created_at, _, _, _, _, _ = item
      # Category order: new=0, to_review=1, blocked=2, unresolved=3, resolved=4, rejected=5
      category_order = {"new": 0, "to_review": 1, "blocked": 2, "unresolved": 3, "resolved": 4, "rejected": 5}.get(category, 3)
      # Lower number = higher priority: P1=1 (highest), P2=2, etc., unset=999 (lowest)
      priority_key = priority if priority is not None else 999
      # Parse ISO date to timestamp for proper reverse sorting (newest first)
      try:
        from datetime import datetime
        if created_at:
          if created_at.endswith('Z'):
            dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
          else:
            dt = datetime.fromisoformat(created_at)
          # Use negative timestamp so newest (larger timestamp) sorts first
          ts = int(dt.timestamp())
          return (category_order, priority_key, -ts)
      except Exception:
        pass
      # Fallback: use 0 if date parsing fails
      return (category_order, priority_key, 0)
    
    submission_info.sort(key=priority_sort_key)

    # Calculate upfront which items need syncing (after Phase 1, we know updated_at values)
    # Tuple: (id, title, priority, category, created_at, updated_at, md_path, state_str, attachment_count, is_blocked_prev, reason)
    need_sync: List[Tuple[str, str, Optional[int], str, str, str, Path, str, Optional[int], bool, str]] = []
    will_skip = []
    moved_count = 0
    for submission_id, title, priority, category, created_at, updated_at, out_path, state_str, attachment_count, is_blocked_prev in submission_info:
      prev = prev_submissions.get(submission_id) if isinstance(prev_submissions, dict) else None
      prev_path = Path(prev.get("md_path")) if isinstance(prev, dict) and prev.get("md_path") else None
      prev_updated = prev.get("updated_at") if isinstance(prev, dict) else None
      prev_sync_state = prev.get("sync_state") if isinstance(prev, dict) else None
      prev_sync_version = prev.get("sync_version") if isinstance(prev, dict) else None
      
      # Check if file needs to be moved (path changed due to state/priority change)
      # This can happen if state changed (e.g., unresolved -> blocked) or priority changed
      if prev_path and prev_path.exists() and prev_path != out_path:
        # Path changed - move files to new location
        if move_submission_files(prev_path, out_path):
          moved_count += 1
          if progress:
            progress.update(f"[bugcrowd] Phase 2: Moved {submission_id[:8]} to new location ({category})", force=True)
      
      # Determine why we need to sync (if we do)
      sync_reason = None
      
      if force_deep_sync:
        sync_reason = "force-deep-sync"
      elif prev_sync_state != "deep":
        sync_reason = "not-deep-synced"
      elif prev_sync_version != CURRENT_SYNC_VERSION:
        sync_reason = f"sync-version-mismatch (v{prev_sync_version} -> v{CURRENT_SYNC_VERSION})"
      elif prev_updated != updated_at:
        sync_reason = f"updated-at-changed ({prev_updated} -> {updated_at})"
      elif not out_path.exists():
        sync_reason = "file-missing"
      else:
        # Check attachment count mismatch
        attachment_mismatch = False
        if attachment_count is not None and prev_sync_state == "deep":
          # Check if attachment folder exists and count matches
          attach_folder = out_path.with_suffix("")
          if attach_folder.exists():
            actual_count = len([f for f in attach_folder.iterdir() if f.is_file()])
            if actual_count != attachment_count:
              attachment_mismatch = True
              sync_reason = f"attachment-count-mismatch (expected {attachment_count}, found {actual_count})"
          elif attachment_count > 0:
            # API says there should be attachments but folder doesn't exist
            attachment_mismatch = True
            sync_reason = f"attachment-folder-missing (expected {attachment_count} attachments)"
        
        if not attachment_mismatch:
          # No reason to sync - can skip
          will_skip.append((submission_id, title, priority, category, created_at, updated_at, out_path, state_str, attachment_count, is_blocked_prev))
          continue
      
      # Need to sync - add with reason
      if sync_reason is None:
        sync_reason = "unknown"  # Fallback
      need_sync.append((submission_id, title, priority, category, created_at, updated_at, out_path, state_str, attachment_count, is_blocked_prev, sync_reason))
    
    # Sort need_sync by the same criteria (category, priority, date)
    def need_sync_sort_key(item: Tuple[str, str, Optional[int], str, str, str, Path, str, Optional[int], bool, str]) -> Tuple[int, int, int]:
      _, _, priority, category, created_at, _, _, _, _, _, _ = item
      # Category order: new=0, to_review=1, blocked=2, unresolved=3, resolved=4, rejected=5
      category_order = {"new": 0, "to_review": 1, "blocked": 2, "unresolved": 3, "resolved": 4, "rejected": 5}.get(category, 3)
      priority_key = priority if priority is not None else 999
      try:
        from datetime import datetime
        if created_at:
          if created_at.endswith('Z'):
            dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
          else:
            dt = datetime.fromisoformat(created_at)
          ts = int(dt.timestamp())
          return (category_order, priority_key, -ts)
      except Exception:
        pass
      return (category_order, priority_key, 0)
    
    need_sync.sort(key=need_sync_sort_key)
    
    # Show upfront summary with breakdown of reasons
    if progress:
      progress.print_final(f"[bugcrowd] Phase 2: Starting deep sync ({len(submission_info)} total submissions)")
      if moved_count > 0:
        progress.print_final(f"[bugcrowd] Phase 2: Moved {moved_count} submissions to new locations")
      progress.print_final(f"[bugcrowd] Phase 2: {len(will_skip)} don't need sync (unchanged), {len(need_sync)} need updates")
      if need_sync:
        # Count reasons and group by type
        reason_counts: Dict[str, int] = {}
        for _, _, _, _, _, _, _, _, _, _, reason in need_sync:
          reason_counts[reason] = reason_counts.get(reason, 0) + 1
        
        # Group reasons into categories for cleaner summary
        attachment_issues = 0
        version_updates = 0
        content_updates = 0
        other_issues = 0
        
        for reason, count in reason_counts.items():
          if "attachment" in reason.lower():
            attachment_issues += count
          elif "version" in reason.lower():
            version_updates += count
          elif "updated-at-changed" in reason.lower() or "not-deep-synced" in reason.lower():
            content_updates += count
          else:
            other_issues += count
        
        # Show concise summary
        summary_parts = []
        if content_updates > 0:
          summary_parts.append(f"{content_updates} content updates")
        if attachment_issues > 0:
          summary_parts.append(f"{attachment_issues} attachment issues")
        if version_updates > 0:
          summary_parts.append(f"{version_updates} version updates")
        if other_issues > 0:
          summary_parts.append(f"{other_issues} other")
        
        if summary_parts:
          progress.print_final(f"[bugcrowd] Phase 2: Sync reasons: {', '.join(summary_parts)}")
        progress.print_final(f"[bugcrowd] Phase 2: Syncing {len(need_sync)} items (order: new → blocked → unresolved → resolved → rejected, high-prio first)")

    processed = 0
    actually_processed = 0  # Items that actually took time (not skipped)
    updated_count = 0
    skipped_deep = 0
    total = len(submission_info)
    
    # First, quickly skip all items that don't need syncing
    skip_start_time = time.time()
    for submission_id, title, priority, category, created_at, updated_at, out_path, state_str, attachment_count, is_blocked_prev in will_skip:
      # Preserve previous blocked status during skip
      prev = prev_submissions.get(submission_id) if isinstance(prev_submissions, dict) else None
      prev_is_blocked = prev.get("is_blocked") if isinstance(prev, dict) else False
      prev_blocker_review = prev.get("blocker_review") if isinstance(prev, dict) else False
      
      new_state[submission_id] = SubmissionState(
        updated_at=updated_at,
        created_at=created_at,
        md_path=str(out_path),
        sync_state="deep",
        sync_version=CURRENT_SYNC_VERSION,
        is_blocked=prev_is_blocked,  # Preserve previous blocked status
        blocker_review=prev_blocker_review,  # Preserve blocker_review flag
      )
      skipped_deep += 1
      processed += 1
      
      # Show progress every 100 skipped items (fast, so less frequent updates)
      if progress and (processed % 100 == 0 or processed == len(will_skip)):
        pct = int(100.0 * processed / total) if total > 0 else 0
        progress.update(f"[bugcrowd] Phase 2: Skipping unchanged items... {processed}/{total} ({pct}%)", force=(processed % 100 == 0))
      
      # Save state periodically (every 500 skipped items)
      if processed % 500 == 0:
        _current_state = new_state
        _save_state(state_path, new_state)
        if progress:
          progress.update(f"[bugcrowd] State saved ({processed}/{total} skipped)", force=True)
    
    if progress and len(will_skip) > 0:
      skip_time = time.time() - skip_start_time
      progress.print_final(f"[bugcrowd] Phase 2: Skipped {len(will_skip)} unchanged items in {skip_time:.1f}s")
    
    # Now process items that actually need syncing
    if progress and need_sync:
      progress.print_final(f"[bugcrowd] Phase 2: Syncing {len(need_sync)} items that need updates...")
    
    # Process each submission that needs syncing (sorted by category, priority, then date)
    sync_start_time = time.time()
    for idx, (submission_id, title, priority, category, created_at, updated_at, out_path, state_str, attachment_count, is_blocked_prev, reason) in enumerate(need_sync, 1):
      # Phase 2: Fetch full submission details for items that need syncing
      # Track start time for this item
      item_start_time = time.time() if progress else None
      
      # Show which item we're syncing with ETA (concise, single line that gets overwritten)
      # Don't show reason here - it's already in the summary, just show progress with ETA
      if progress:
        priority_str = f"P{priority}" if priority else "unset"
        # Use first 15 chars of title instead of submission ID (much more useful)
        title_preview = (title[:15] + "...") if len(title) > 15 else title if title else "untitled"
        # Use update_with_eta so ETA is visible while syncing
        progress.update_with_eta(
          f"Phase 2: Syncing {category} {priority_str} #{idx}/{len(need_sync)} ({title_preview})",
          idx,
          len(need_sync),
          status="bugcrowd",
          force=True,
          actually_processed=idx,  # All items in need_sync take time, so idx = actually_processed
        )
      
      full_submission = client.get_submission(submission_id, include=["researcher", "comments", "activities", "file_attachments", "external_issues"])
      comments = client.get_submission_comments(submission_id)
      attachments = client.get_submission_attachments(submission_id)
      external_issues = client.get_submission_external_issues(submission_id)
      
      # Phase 2: Detect blocker status from activities
      # Merge activities from activities endpoint with comments for blocker detection
      activities = client.get_submission_activities(submission_id)
      all_activities = list(comments or [])
      if activities:
        comment_ids = {c.get("id") for c in comments if isinstance(c, dict) and c.get("id")}
        for act in activities:
          if isinstance(act, dict) and act.get("id") not in comment_ids:
            all_activities.append(act)
      
      # Detect current blocked status from activities
      is_blocked_current = _detect_blocker_status(all_activities)
      
      # Check if blocked status changed
      prev = prev_submissions.get(submission_id) if isinstance(prev_submissions, dict) else None
      prev_is_blocked = prev.get("is_blocked") if isinstance(prev, dict) else False
      blocker_status_changed = (prev_is_blocked != is_blocked_current)
      
      # Phase 2: Don't move files here - just detect and mark for blocker_review
      # Phase 3 will handle the actual moves
      # Note: out_path is still based on previous blocked status (from Phase 1)
      # We'll compute the correct path in Phase 3 based on current blocked status
      
      # Only create attachment directory if there are actually attachments
      attach_dir = out_path.with_suffix("") if attachments else None
      write_submission_markdown(
        out_path=out_path,
        submission=full_submission,
        comments=comments,
        attachments=attachments,
        external_issues=external_issues,
        base_url=base_url,
        submission_id_to_md=submission_id_to_md,
        attachment_dir=attach_dir,
        download_attachment=client.download_attachment,
        client=client,  # Pass client for downloading embed attachments from comments
        full_submission=full_submission,  # Pass full submission for author resolution from included resources
        shallow=False,
      )
      
      # Phase 2: Update state with current blocked status
      # Mark for blocker_review if status changed (Phase 3 will move it if needed)
      new_state[submission_id] = SubmissionState(
        updated_at=updated_at if updated_at else "",
        created_at=created_at if created_at else "",
        md_path=str(out_path),
        sync_state="deep",
        sync_version=CURRENT_SYNC_VERSION,
        is_blocked=is_blocked_current,  # Current blocked status
        blocker_review=blocker_status_changed,  # Mark for review if status changed
      )
      updated_count += 1
      processed += 1
      actually_processed += 1  # This item actually took time to process
      
      # Show progress after processing (so ETA reflects actual work done)
      # Keep it concise - just show progress with ETA
      if progress:
        priority_str = f"P{priority}" if priority else "unset"
        # Use first 15 chars of title instead of submission ID (much more useful)
        title_preview = (title[:15] + "...") if len(title) > 15 else title if title else "untitled"
        # Use update_with_eta with idx/len(need_sync) for items being synced
        # This gives accurate ETA based only on items that take time
        # Keep message short so ETA is always visible
        progress.update_with_eta(
          f"Phase 2: {category} {priority_str} #{idx}/{len(need_sync)} ({title_preview})",
          idx,
          len(need_sync),
          status="bugcrowd",
          force=True,
          actually_processed=idx,  # All items in need_sync take time, so idx = actually_processed
        )
      
      # Save state periodically (every 10 items for syncing, since they take time)
      if idx % 10 == 0:
        _current_state = new_state
        _save_state(state_path, new_state)
        if progress:
          progress.update(f"[bugcrowd] State saved ({idx}/{len(need_sync)} synced)", force=True)

    # Save final state before Phase 3
    _current_state = new_state
    _save_state(state_path, new_state)

    # Phase 2 cleanup is already done at end of Phase 1, but do final cleanup of empty dirs
    prune_empty_dirs(data_dir, keep_root=True)

    if progress:
      progress.print_final(f"[bugcrowd] Phase 2: Complete - Deep synced {updated_count} submissions, skipped {skipped_deep} already synced")
    
    # Phase 3: Blocker review - move submissions between blocked and non-blocked folders
    if progress:
      progress.update("[bugcrowd] Phase 3: Reviewing blocker status changes...", force=True)
    
    blocker_review_items = []
    for submission_id, state_obj in new_state.items():
      if state_obj.blocker_review:
        # This submission's blocked status changed - needs to be moved
        blocker_review_items.append((submission_id, state_obj))
    
    if blocker_review_items:
      if progress:
        progress.print_final(f"[bugcrowd] Phase 3: Found {len(blocker_review_items)} submissions with changed blocker status")
      
      moved_count_phase3 = 0
      # Build lookup dict from submission_info (includes state_str)
      submission_info_lookup = {sid: (title, priority, category, state_str, created_at) for sid, title, priority, category, created_at, _, _, state_str, _, _ in submission_info}
      
      for submission_id, state_obj in blocker_review_items:
        submission_tuple = submission_info_lookup.get(submission_id)
        
        if not submission_tuple:
          # Can't find submission info - skip
          continue
        
        title, priority, category, state_str, created_at = submission_tuple
        
        # Compute new path based on current blocked status
        current_path = Path(state_obj.md_path)
        new_path = compute_md_path(
          submission_id=submission_id,
          title=title,
          base=data_dir,
          state=state_str,  # Use original state string for path computation
          priority=priority,
          created_at=created_at,
          is_blocked=state_obj.is_blocked,  # Use current blocked status (overrides state)
        )
        
        # If path changed, move the file
        if current_path.exists() and current_path != new_path:
          if move_submission_files(current_path, new_path):
            moved_count_phase3 += 1
            # Update state with new path and clear blocker_review flag
            new_state[submission_id] = SubmissionState(
              updated_at=state_obj.updated_at,
              created_at=state_obj.created_at,
              md_path=str(new_path),
              sync_state=state_obj.sync_state,
              sync_version=state_obj.sync_version,
              is_blocked=state_obj.is_blocked,  # Keep current blocked status
              blocker_review=False,  # Clear blocker_review flag after move
            )
            
            if progress:
              folder_name = "blocked" if state_obj.is_blocked else category
              progress.update(f"[bugcrowd] Phase 3: Moved {submission_id[:8]} to {folder_name}/", force=True)
          else:
            # Move failed - keep blocker_review flag so we try again next time
            if progress:
              progress.update(f"[bugcrowd] Phase 3: Failed to move {submission_id[:8]} - will retry next sync", force=True)
        else:
          # Path didn't change (already in correct location) - just clear blocker_review flag
          new_state[submission_id] = SubmissionState(
            updated_at=state_obj.updated_at,
            created_at=state_obj.created_at,
            md_path=state_obj.md_path,
            sync_state=state_obj.sync_state,
            sync_version=state_obj.sync_version,
            is_blocked=state_obj.is_blocked,
            blocker_review=False,  # Clear blocker_review flag
          )
      
      # Save state after Phase 3
      _current_state = new_state
      _save_state(state_path, new_state)
      
      if progress:
        progress.print_final(f"[bugcrowd] Phase 3: Complete - Moved {moved_count_phase3} submissions between blocked and non-blocked folders")
    else:
      if progress:
        progress.print_final(f"[bugcrowd] Phase 3: Complete - No blocker status changes to review")

    # Final cleanup of empty dirs
    prune_empty_dirs(data_dir, keep_root=True)

    if progress:
      summary_parts = [f"{total} total", f"{shallow_count} shallow created", f"{deleted} deleted", f"{removed_extra_phase1 + removed_extra_phase2} cleaned up"]
      if recon_deleted > 0:
        summary_parts.append(f"{recon_deleted} reconciled (dup/move)")
      progress.print_final(f"[bugcrowd] Summary: {', '.join(summary_parts)}")
      progress.done()
  
  finally:
    # Always save state before exiting (even if interrupted)
    if _current_state is not None and _current_state_path is not None:
      try:
        _save_state(_current_state_path, _current_state)
      except Exception:
        pass
    # Restore original signal handler
    signal.signal(signal.SIGINT, original_sigint)
    _current_state = None
    _current_state_path = None

  return SyncResult(total, skipped_deep + skipped_shallow, updated_count, deleted, removed_extra_phase1 + removed_extra_phase2, shallow=shallow_count)
