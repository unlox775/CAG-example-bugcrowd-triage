import re
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime

SLUG_MAX_LEN = 100  # Increased for better titles


def slugify(text: str, max_len: int = SLUG_MAX_LEN) -> str:
  text = text or ""
  text = text.lower()
  text = re.sub(r"[^a-z0-9]+", "-", text)
  text = text.strip("-")
  if len(text) > max_len:
    text = text[:max_len].rstrip("-")
  return text or "untitled"


# Maximum filename length (excluding directory path)
# Leave room for "attachment-" prefix (12 chars) and path overhead
# Most filesystems support 255 chars per filename, but we'll be conservative
MAX_FILENAME_LEN = 200  # Total including "attachment-" prefix
MAX_SANITIZED_FILENAME_LEN = MAX_FILENAME_LEN - 12  # Leave room for "attachment-" prefix
MAX_EXTENSION_LEN = 20  # Reasonable max for file extensions (e.g., ".png", ".jpeg", ".pdf")

def sanitize_filename(name: str) -> str:
  """Sanitize filename and truncate if too long, preserving extension."""
  name = name or "attachment"
  # Preserve extension
  if "." in name:
    name_base, ext = name.rsplit(".", 1)
    # Sanitize base and extension separately
    name_base = re.sub(r"[^A-Za-z0-9._-]+", "-", name_base)
    ext = re.sub(r"[^A-Za-z0-9_-]+", "-", ext)
    # Truncate extension if too long
    if len(ext) > MAX_EXTENSION_LEN:
      ext = ext[:MAX_EXTENSION_LEN]
    # Truncate base if needed, leaving room for extension and dot
    max_base_len = MAX_SANITIZED_FILENAME_LEN - len(ext) - 1  # -1 for the dot
    if max_base_len < 1:
      # Extension is too long, just use a default base
      name_base = "attachment"
    elif len(name_base) > max_base_len:
      name_base = name_base[:max_base_len].rstrip("-")
    name = f"{name_base}.{ext}" if name_base else f"attachment.{ext}"
  else:
    # No extension, just sanitize and truncate
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name)
    if len(name) > MAX_SANITIZED_FILENAME_LEN:
      name = name[:MAX_SANITIZED_FILENAME_LEN].rstrip("-")
  
  name = name.strip("-")
  # Final check: if still too long, truncate more aggressively
  if len(name) > MAX_SANITIZED_FILENAME_LEN:
    if "." in name:
      name_base, ext = name.rsplit(".", 1)
      # Truncate extension if needed
      if len(ext) > MAX_EXTENSION_LEN:
        ext = ext[:MAX_EXTENSION_LEN]
      max_base_len = MAX_SANITIZED_FILENAME_LEN - len(ext) - 1
      if max_base_len < 1:
        name = f"attachment.{ext}"
      else:
        name = f"{name_base[:max_base_len]}.{ext}"
    else:
      name = name[:MAX_SANITIZED_FILENAME_LEN]
  
  return name or "attachment"


def priority_folder(priority: Optional[int]) -> str:
  """Convert priority number to folder name."""
  if priority is None:
    return "unset"
  if priority in (1, 2, 3, 4, 5):
    return f"P{priority}"
  return "unset"


def extract_year_month(created_at: str) -> str:
  """Extract YYYY-MM from created_at timestamp. Returns 'YYYY-MM' or 'unknown' if parsing fails."""
  if not created_at:
    return "unknown"
  try:
    # BugCrowd timestamps are ISO 8601 format: "2024-01-15T10:30:00Z" or similar
    # Try to parse and extract year-month
    if "T" in created_at:
      date_part = created_at.split("T")[0]
    else:
      date_part = created_at.split(" ")[0]
    # Validate format YYYY-MM-DD
    parts = date_part.split("-")
    if len(parts) >= 2:
      year = parts[0]
      month = parts[1]
      if len(year) == 4 and len(month) == 2:
        return f"{year}-{month}"
  except Exception:
    pass
  return "unknown"


def compute_md_path(*, submission_id: str, title: str, base: Path, state: str, priority: Optional[int] = None, created_at: str = "", is_blocked: bool = False) -> Path:
  """Compute the markdown file path for a submission.
  
  Format: data/{new|unresolved|resolved|rejected|blocked}/{P1|P2|P3|P4|P5|unset}/{YYYY-MM}-{slug-title-{first8chars}}.md
  
  Args:
    submission_id: Submission UUID
    title: Submission title
    base: Base directory (e.g., data/)
    state: Submission state string (e.g., "new", "triaged", "unresolved", "resolved", "not_applicable", "blocked - by: customer", etc.)
    priority: Priority number (1-5) or None
    created_at: Creation timestamp (for YYYY-MM prefix)
    is_blocked: Whether this submission is currently blocked (overrides state categorization)
  """
  from .models import categorize_state
  
  slug = slugify(title, max_len=100)
  # If blocked, always use "blocked" folder regardless of state
  if is_blocked:
    folder = "blocked"
  else:
    folder = categorize_state(state)  # new, unresolved, resolved, rejected, or blocked
  priority_dir = priority_folder(priority)
  date_prefix = extract_year_month(created_at)
  # First 8 characters of UUID for uniqueness
  id_suffix = submission_id[:8] if len(submission_id) >= 8 else submission_id
  filename = f"{date_prefix}-{slug}-{id_suffix}.md"
  return base / folder / priority_dir / filename

