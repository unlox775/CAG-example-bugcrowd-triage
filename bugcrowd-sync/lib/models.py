from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class BugCrowdSubmission:
  id: str
  title: str
  state: str
  severity: Optional[str]
  updated_at: str
  created_at: str
  description: Optional[str]
  reproduction_steps: Optional[str]
  raw_data: Dict[str, Any]


@dataclass(frozen=True)
class AttachmentMeta:
  id: str
  filename: str
  content_url: str
  content_type: Optional[str]


@dataclass(frozen=True)
class SubmissionState:
  updated_at: str
  created_at: str
  md_path: str
  sync_state: str  # "shallow" or "deep"
  sync_version: Optional[int] = None  # Version of sync format this was synced with (None = version 1 or older)
  is_blocked: bool = False  # Whether this submission is currently blocked (from blocker.created/unblocked events)
  blocker_review: bool = False  # Whether this submission needs to be moved between blocked/ and non-blocked folders


# Categorize states into six folders:
# - "new": new (triage still looking at it)
# - "to_review": triaged (triage validated; awaiting customer/Dave review — BugCrowd "To review")
# - "unresolved": unresolved, not_resolved, not_reproducible (active issues being worked on)
# - "resolved": resolved, informational (fixed or accepted)
# - "rejected": not_applicable, out_of_scope (invalid/rejected from start)
# - "blocked": blocked_by_customer, blocked - by: customer (blocked by customer)

NEW_STATES = {
  "new",
}

TO_REVIEW_STATES = {
  "triaged",
}

UNRESOLVED_STATES = {
  "unresolved",
  "not_resolved",
  "not_reproducible",
}

RESOLVED_STATES = {
  "resolved",
  "informational",
}

REJECTED_STATES = {
  "not_applicable",
  "out_of_scope",
}

BLOCKED_STATES = {
  "blocked_by_customer",
  "blocked",
}


def categorize_state(state: str) -> str:
  """Categorize a submission state into folder name: new, unresolved, resolved, rejected, or blocked.
  
  BugCrowd UI shows "blocked-by: customer" as a filter, which appears in the API as:
  - "blocked - by: customer" (with spaces and colons)
  - "blocked-by: customer" (with hyphen and colon)
  - "blocked_by_customer" (normalized format)
  
  We normalize by lowercasing and replacing spaces/hyphens with underscores, then check for
  "blocked" + "customer" keywords.
  """
  if not state:
    return "unresolved"  # Default for empty state
  
  state_lower = state.lower()
  # Normalize: replace spaces, hyphens, colons with underscores for consistent matching
  state_normalized = state_lower.replace(" ", "_").replace("-", "_").replace(":", "_")
  
  # Check for blocked states - only "blocked by customer" goes to blocked folder
  # The UI filter "blocked-by: customer" should match here
  if "blocked" in state_normalized:
    # Check if it's blocked by customer (vs other types of blocked)
    # Match: "blocked_by_customer", "blocked_by:customer", "blocked_by_customer", etc.
    if "customer" in state_normalized or "by_customer" in state_normalized:
      return "blocked"
    # Also check original state_lower for patterns like "blocked - by: customer"
    if "customer" in state_lower:
      return "blocked"
    # Other blocked types (if any) default to unresolved for now
    # Could add other blocked types here if needed
  
  if state_lower in NEW_STATES:
    return "new"
  elif state_lower in TO_REVIEW_STATES:
    return "to_review"
  elif state_lower in UNRESOLVED_STATES:
    return "unresolved"
  elif state_lower in REJECTED_STATES:
    return "rejected"
  elif state_lower in RESOLVED_STATES:
    return "resolved"
  else:
    # Default to unresolved for unknown states
    return "unresolved"


def is_resolved(state: str) -> bool:
  """Check if a submission state is considered resolved (deprecated - use categorize_state instead)."""
  category = categorize_state(state)
  return category == "resolved"

