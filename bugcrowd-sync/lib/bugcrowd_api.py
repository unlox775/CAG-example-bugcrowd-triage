import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

DEFAULT_BASE_URL = "https://api.bugcrowd.com"
API_PREFIX = ""
USER_AGENT = "cag-example-bugcrowd-sync/1.0"


@dataclass(frozen=True)
class BugCrowdConfig:
  base_url: str
  username: str
  password: str
  auth_header: Optional[str] = None


class BugCrowdClient:
  def __init__(self, cfg: BugCrowdConfig):
    self._cfg = cfg
    self._base_url = cfg.base_url.rstrip("/")

  def _auth_headers(self) -> Dict[str, str]:
    # BugCrowd supports both Basic Auth and Token auth
    headers = {
      "Accept": "application/vnd.bugcrowd+json",
      "User-Agent": USER_AGENT,
    }
    
    # Prefer auth header if provided (Token auth)
    if self._cfg.auth_header:
      # auth_header format: "Authorization: Token username:password"
      # or just "Token username:password"
      auth_value = self._cfg.auth_header.strip()
      if auth_value.startswith("Authorization:"):
        # Extract just the value part after "Authorization: "
        auth_value = auth_value.split(":", 1)[1].strip()
      # Use the value as-is (should be "Token username:password")
      headers["Authorization"] = auth_value
    else:
      # Fall back to Basic Auth
      import base64
      user_pass = f"{self._cfg.username}:{self._cfg.password}"
      auth_str = base64.b64encode(user_pass.encode("utf-8")).decode("utf-8")
      headers["Authorization"] = f"Basic {auth_str}"
    
    return headers

  def _url(self, path: str, query: Optional[Dict[str, Any]] = None) -> str:
    if not path.startswith("/"):
      path = "/" + path
    url = self._base_url + path
    if query:
      url += "?" + urllib.parse.urlencode({k: v for k, v in query.items() if v is not None})
    return url

  def _request_json(self, path: str, query: Optional[Dict[str, Any]] = None, *, retries: int = 5) -> Any:
    url = self._url(path, query)
    headers = self._auth_headers()

    # Handle SSL context (allow unverified for testing if env var set)
    ssl_context = None
    if os.environ.get("BUGCROWD_SSL_UNVERIFIED", "").lower() == "true":
      ssl_context = ssl._create_unverified_context()

    last_err: Optional[Exception] = None
    for attempt in range(retries):
      req = urllib.request.Request(url, headers=headers, method="GET")
      try:
        with urllib.request.urlopen(req, timeout=60, context=ssl_context) as resp:
          raw = resp.read().decode("utf-8")
          return json.loads(raw) if raw else None
      except urllib.error.HTTPError as e:
        body = None
        try:
          body = e.read().decode("utf-8")
        except Exception:
          body = None

        if e.code in (429, 500, 502, 503, 504):
          retry_after = e.headers.get("Retry-After")
          sleep_s = int(retry_after) if retry_after and retry_after.isdigit() else (2 ** attempt)
          time.sleep(min(30, sleep_s))
          last_err = RuntimeError(f"HTTP {e.code} for {url}: {body}")
          continue

        raise RuntimeError(f"HTTP {e.code} for {url}: {body}") from e
      except Exception as e:
        last_err = e
        time.sleep(min(30, 2 ** attempt))

    raise RuntimeError(f"Failed after retries for {url}: {last_err}")

  def _request_bytes(self, url: str, *, retries: int = 5) -> bytes:
    # For S3 signed URLs (e.g., files.bugcrowd.com), don't send Authorization header
    # S3 signed URLs have authentication in the query string and will reject Authorization headers
    is_s3_url = "files.bugcrowd.com" in url or "s3" in url.lower()
    
    if is_s3_url:
      headers = {
        "User-Agent": USER_AGENT,
      }
    else:
      headers = self._auth_headers()
    
    # Handle SSL context (allow unverified for testing if env var set)
    ssl_context = None
    if os.environ.get("BUGCROWD_SSL_UNVERIFIED", "").lower() == "true":
      ssl_context = ssl._create_unverified_context()
    
    last_err: Optional[Exception] = None
    for attempt in range(retries):
      req = urllib.request.Request(url, headers=headers, method="GET")
      try:
        with urllib.request.urlopen(req, timeout=120, context=ssl_context) as resp:
          return resp.read()
      except urllib.error.HTTPError as e:
        body = None
        try:
          body = e.read().decode("utf-8")
        except Exception:
          body = None
        if e.code in (429, 500, 502, 503, 504):
          retry_after = e.headers.get("Retry-After")
          sleep_s = int(retry_after) if retry_after and retry_after.isdigit() else (2 ** attempt)
          time.sleep(min(30, sleep_s))
          last_err = RuntimeError(f"HTTP {e.code} for {url}: {body}")
          continue
        raise RuntimeError(f"HTTP {e.code} for {url}: {body}") from e
      except Exception as e:
        last_err = e
        time.sleep(min(30, 2 ** attempt))
    raise RuntimeError(f"Failed after retries for {url}: {last_err}")

  def get_all_submissions(self, *, page_size: int = 100, progress_callback=None) -> List[Dict[str, Any]]:
    """Fetch all submissions from BugCrowd with pagination.
    
    Args:
      page_size: Number of submissions per page
      progress_callback: Optional callback function(submission_count, page_num) for progress updates
    """
    submissions: List[Dict[str, Any]] = []
    offset = 0
    limit = page_size
    total_count = None
    consecutive_empty = 0
    page_num = 1

    while True:
      # BugCrowd API uses offset/limit pagination (JSON API format)
      # Don't specify fields - let API return defaults which should include dates
      data = self._request_json(
        f"{API_PREFIX}/submissions",
        {
          "page[offset]": offset,
          "page[limit]": limit,
        },
      )

      if not isinstance(data, dict):
        break

      # BugCrowd JSON API format: data is in "data" array
      chunk = data.get("data", []) if isinstance(data, dict) else []
      
      if not chunk:
        # Empty page - we're done
        break
      
      submissions.extend(chunk)
      
      # Report progress
      if progress_callback:
        progress_callback(len(submissions), page_num)
      
      # Check if we got fewer results than requested (last page)
      if len(chunk) < limit:
        break
      
      # Move to next page (we got a full page, so there might be more)
      offset += len(chunk)
      page_num += 1
      
      # Safety limit to prevent infinite loops (should handle 1891 submissions easily)
      if offset >= 10000:
        break

    return submissions

  def get_submission(self, submission_id: str, *, include: Optional[List[str]] = None) -> Dict[str, Any]:
    """Get full submission details with optional includes.
    
    Returns JSON API format with data and included resources.
    """
    query = {}
    if include:
      query["include"] = ",".join(include)
    return self._request_json(f"{API_PREFIX}/submissions/{submission_id}", query)

  def get_submission_comments(self, submission_id: str) -> List[Dict[str, Any]]:
    """Get all comments/activities for a submission.
    
    Returns list of comment/activity resources in JSON API format.
    """
    # Get comments via include parameter (try including file_attachments for comment attachments)
    full = self.get_submission(submission_id, include=["comments", "activities", "file_attachments"])
    
    # Extract comments from included resources (JSON API format)
    comments = []
    included = full.get("included", []) if isinstance(full, dict) else []
    for item in included:
      if not isinstance(item, dict):
        continue
      item_type = item.get("type", "")
      # BugCrowd might use "comments" or "activities" as type
      if item_type in ("comment", "comments", "activity", "activities"):
        comments.append(item)
    
    # Also try direct comments endpoint with file_attachment include (API v2025-04-23+)
    try:
      comments_data = self._request_json(f"{API_PREFIX}/submissions/{submission_id}/comments", {"include": "file_attachment"})
      if isinstance(comments_data, dict):
        comments_list = comments_data.get("data", [])
        if isinstance(comments_list, list):
          comments.extend(comments_list)
        # Also check included resources for file_attachments
        included_attachments = comments_data.get("included", [])
        if isinstance(included_attachments, list):
          # These might be referenced in comment relationships
          pass  # We'll handle these when processing comments
    except Exception:
      pass  # Comments endpoint might not exist or might not support include, that's okay

    return comments
  
  def get_submission_activities(self, submission_id: str) -> List[Dict[str, Any]]:
    """Get all activities for a submission (API v2025-04-23+).
    
    Returns list of activity resources in JSON API format.
    Activities include events like "blocker.created", "blocker.resolved", etc.
    """
    try:
      # Try the submission_activities endpoint (API v2025-04-23+)
      activities_data = self._request_json(f"{API_PREFIX}/submissions/{submission_id}/activities", {"include": "actor,event"})
      if isinstance(activities_data, dict):
        activities_list = activities_data.get("data", [])
        if isinstance(activities_list, list):
          return activities_list
        # Also check included resources
        included = activities_data.get("included", [])
        if isinstance(included, list):
          # Activities might be in included resources
          activities = [item for item in included if isinstance(item, dict) and item.get("type", "").lower() in ("activity", "activities")]
          if activities:
            return activities
    except Exception as e:
      # Endpoint might not exist or might not support include, that's okay
      pass
    
    # Fallback: try to get activities from submission include
    try:
      full = self.get_submission(submission_id, include=["activities", "activities.actor", "activities.event"])
      included = full.get("included", []) if isinstance(full, dict) else []
      activities = [item for item in included if isinstance(item, dict) and item.get("type", "").lower() in ("activity", "activities")]
      if activities:
        return activities
    except Exception:
      pass
    
    return []

  def get_submission_external_issues(self, submission_id: str) -> List[Dict[str, Any]]:
    """Get external issues (e.g., Jira integration) for a submission.
    
    Returns list of external issue resources in JSON API format.
    """
    # Try to get external issues via include parameter
    try:
      full = self.get_submission(submission_id, include=["external_issues"])
    except Exception:
      # If external_issues include doesn't work, try without it and check relationships
      full = self.get_submission(submission_id)
    
    external_issues = []
    
    # Extract from included resources (JSON API format)
    included = full.get("included", []) if isinstance(full, dict) else []
    for item in included:
      if not isinstance(item, dict):
        continue
      item_type = item.get("type", "")
      if item_type in ("external_issue", "external_issues"):
        external_issues.append(item)
    
    # Also check relationships in the main data object
    data = full.get("data", {}) if isinstance(full, dict) else {}
    if isinstance(data, dict):
      relationships = data.get("relationships", {})
      if isinstance(relationships, dict):
        ext_issues_rel = relationships.get("external_issues", {})
        if isinstance(ext_issues_rel, dict):
          ext_issues_data = ext_issues_rel.get("data", [])
          if isinstance(ext_issues_data, list):
            # These are references, try to find them in included
            for ref in ext_issues_data:
              if isinstance(ref, dict):
                ref_id = ref.get("id", "")
                ref_type = ref.get("type", "")
                # Find matching item in included
                for item in included:
                  if isinstance(item, dict) and item.get("id") == ref_id and item.get("type") == ref_type:
                    if item not in external_issues:
                      external_issues.append(item)
    
    # Also try direct external_issues endpoint
    try:
      ext_issues_data = self._request_json(f"{API_PREFIX}/submissions/{submission_id}/external_issues")
      if isinstance(ext_issues_data, dict):
        ext_issues_list = ext_issues_data.get("data", [])
        if isinstance(ext_issues_list, list):
          for item in ext_issues_list:
            if item not in external_issues:
              external_issues.append(item)
    except Exception:
      pass  # External issues endpoint might not exist, that's okay
    
    return external_issues

  def get_submission_attachments(self, submission_id: str) -> List[Dict[str, Any]]:
    """Get all attachments for a submission.
    
    Returns list of attachment resources in JSON API format.
    """
    # BugCrowd uses "file_attachments" not "attachments"
    full = self.get_submission(submission_id, include=["file_attachments"])
    
    attachments = []
    # Extract from included resources (JSON API format)
    included = full.get("included", []) if isinstance(full, dict) else []
    for item in included:
      if not isinstance(item, dict):
        continue
      if item.get("type") in ("file_attachment", "file_attachments"):
        attachments.append(item)
    
    # Also check attributes for attachment links (some APIs embed them)
    data = full.get("data", {}) if isinstance(full, dict) else {}
    if isinstance(data, dict):
      attributes = data.get("attributes", {}) if isinstance(data, dict) else {}
      if "file_attachments" in attributes:
        att_list = attributes.get("file_attachments", [])
        if isinstance(att_list, list):
          # If attachments are embedded as objects, add them
          attachments.extend(att_list)

    return attachments

  def download_attachment(self, attachment_url: str) -> bytes:
    """Download an attachment by URL.
    
    This can handle:
    - Direct download URLs (S3 signed URLs, API endpoints)
    - Embed URLs (if accessible with authentication)
    """
    return self._request_bytes(attachment_url)
  
  def get_attachment_by_id(self, submission_id: str, attachment_id: str) -> Optional[Dict[str, Any]]:
    """Get a specific attachment by ID.
    
    Returns attachment resource in JSON API format, or None if not found.
    """
    try:
      # Try to get the attachment directly
      att_data = self._request_json(f"{API_PREFIX}/submissions/{submission_id}/attachments/{attachment_id}")
      if isinstance(att_data, dict):
        # Check if it's JSON API format
        if "data" in att_data:
          return att_data.get("data")
        return att_data
    except Exception:
      pass
    
    # Fallback: get all attachments and find the one with matching ID
    try:
      attachments = self.get_submission_attachments(submission_id)
      for att in attachments:
        att_id = att.get("id", "") if isinstance(att, dict) else ""
        if att_id == attachment_id:
          return att
    except Exception:
      pass
    
    return None
  
  def download_attachment_by_id(self, submission_id: str, attachment_id: str) -> Optional[bytes]:
    """Download an attachment by submission ID and attachment ID.
    
    Returns bytes if successful, None otherwise.
    """
    # First try to get attachment metadata to find download URL
    att = self.get_attachment_by_id(submission_id, attachment_id)
    if att:
      att_data = att.get("attributes", {}) if isinstance(att, dict) and "attributes" in att else att
      # Try various URL fields
      download_url = (
        att_data.get("s3_signed_url") or
        att_data.get("download_url") or
        att_data.get("url") or
        att_data.get("content_url") or
        ""
      )
      
      if download_url:
        try:
          return self._request_bytes(download_url)
        except Exception:
          pass
      
      # Fallback: try constructing download URL
      try:
        download_url = f"{API_PREFIX}/submissions/{submission_id}/attachments/{attachment_id}/download"
        return self._request_bytes(download_url)
      except Exception:
        pass
    
    return None
