import os
from pathlib import Path
from typing import Dict, Any, List, Optional

from .html_md import html_to_markdown, rewrite_bugcrowd_links_to_local, rewrite_attachment_links_to_local
from .paths import sanitize_filename
from .date_format import format_date_pacific


def write_submission_markdown(
  *,
  out_path: Path,
  submission: Dict[str, Any],
  comments: List[Dict[str, Any]],
  attachments: List[Dict[str, Any]],
  external_issues: Optional[List[Dict[str, Any]]] = None,
  base_url: str,
  submission_id_to_md: Dict[str, Path],
  attachment_dir: Optional[Path],
  download_attachment,
  client=None,  # Optional BugCrowdClient for downloading embed attachments
  shallow: bool = False,
  full_submission: Optional[Dict[str, Any]] = None,  # Full submission with included resources for author resolution
  verbose: bool = False,  # If True, print verbose debug output (for single-issue sync)
) -> None:
  """Write a BugCrowd submission to markdown format.
  
  If shallow=True, only write basic info from index without fetching full details.
  """
  # Extract submission data (BugCrowd JSON API format)
  # Handle both JSON API format (with "data" wrapper) and direct format
  if isinstance(submission, dict) and "data" in submission:
    data = submission.get("data", {})
  else:
    data = submission if isinstance(submission, dict) else {}
  
  attributes = data.get("attributes", {}) if isinstance(data, dict) else {}
  
  # Get ID from data.id or fallback to submission.id
  submission_id = data.get("id", "") if isinstance(data, dict) else ""
  if not submission_id and isinstance(submission, dict):
    submission_id = submission.get("id", "")
  
  title = attributes.get("title") or attributes.get("name") or ""
  state = attributes.get("state") or ""
  severity = attributes.get("severity") or attributes.get("priority") or ""
  # BugCrowd uses submitted_at for creation date, not created_at
  created_at = (
    attributes.get("submitted_at") or
    attributes.get("created_at") or
    attributes.get("created") or
    ""
  )
  # For updated_at, try various transition fields or use submitted_at if none found
  updated_at = (
    attributes.get("last_transitioned_to_resolved_at") or
    attributes.get("last_transitioned_to_unresolved_at") or
    attributes.get("last_transitioned_to_triaged_at") or
    attributes.get("last_transitioned_to_informational_at") or
    attributes.get("last_transitioned_to_not_applicable_at") or
    attributes.get("last_transitioned_to_not_reproducible_at") or
    attributes.get("last_transitioned_to_out_of_scope_at") or
    attributes.get("updated_at") or
    attributes.get("updated") or
    created_at  # Fallback to submitted_at if no update date found
  )
  description = attributes.get("description") or ""
  reproduction_steps = attributes.get("reproduction_steps") or attributes.get("reproduction") or ""
  reproduced = attributes.get("reproduced") or False

  # Reporter (submitter): from attributes or relationships + included
  reporter = ""
  if isinstance(data, dict):
    # 1. Direct attributes (if API embeds submitter info)
    reporter = (
      attributes.get("submitter_username") or
      attributes.get("reporter_username") or
      attributes.get("submitter_name") or
      attributes.get("reporter_name") or
      attributes.get("submitter_email") or
      attributes.get("reporter_email") or
      ""
    )
    # 2. relationships.submitter or .reporter + resolve from included
    if not reporter and full_submission:
      relationships = data.get("relationships", {}) or {}
      submitter_rel = relationships.get("researcher") or relationships.get("submitter") or relationships.get("reporter") or relationships.get("creator") or {}
      if isinstance(submitter_rel, dict):
        ref = submitter_rel.get("data")
        if isinstance(ref, list):
          ref = ref[0] if ref else {}
        if not isinstance(ref, dict):
          ref = {}
        if ref:
          author_id = ref.get("id", "")
          author_type = ref.get("type", "")
          included = full_submission.get("included", []) if isinstance(full_submission, dict) else []
          for item in included:
            if isinstance(item, dict) and item.get("id") == author_id and item.get("type") == author_type:
              author_attrs = item.get("attributes", {}) or {}
              reporter = author_attrs.get("username") or author_attrs.get("name") or author_attrs.get("email") or ""
              break
  if reporter is None or (isinstance(reporter, str) and not reporter.strip()):
    reporter = "—"

  # Submission ID as clickable link to BugCrowd tracker (security-inbox = current UI)
  bugcrowd_tracker_url = f"https://tracker.bugcrowd.com/codeorg/security-inbox/submissions/{submission_id}"
  
  lines = [
    f"# {title}",
    "",
    f"**Submission ID:** [`{submission_id}`]({bugcrowd_tracker_url})",
    "",
  ]
  
  # Reporter first (so it's visible at top of metadata)
  lines.append(f"- Reporter: {reporter}")
  lines.append("")
  
  # Add external issues (Jira integration) if present
  if external_issues and not shallow:
    jira_issues = []
    for ext_issue in external_issues:
      if not isinstance(ext_issue, dict):
        continue
      attrs = ext_issue.get("attributes", {}) if isinstance(ext_issue, dict) and "attributes" in ext_issue else ext_issue
      # BugCrowd uses remote_id and remote_url for external issues
      issue_key = attrs.get("remote_id") or attrs.get("issue_key") or attrs.get("key") or ""
      issue_url = attrs.get("remote_url") or attrs.get("issue_url") or attrs.get("url") or ""
      
      # Check relationships to see if it's a Jira integration
      relationships = ext_issue.get("relationships", {}) if isinstance(ext_issue, dict) else {}
      integration_data = relationships.get("integration", {}).get("data", {}) if isinstance(relationships, dict) else {}
      integration_type = integration_data.get("type", "") if isinstance(integration_data, dict) else ""
      
      # Check if it's a Jira integration (either by integration type or by issue key pattern)
      is_jira = (
        "jira" in integration_type.lower() or
        (issue_key and issue_key.startswith(("BC-", "SEC-", "INF-", "JIRA-")))
      )
      
      if is_jira and issue_key:
        if issue_url:
          jira_issues.append(f"[{issue_key}]({issue_url})")
        else:
          # Construct Jira URL if we have the key but no URL
          jira_base = "https://codedotorg.atlassian.net"
          jira_issues.append(f"[{issue_key}]({jira_base}/browse/{issue_key})")
    
    if jira_issues:
      lines.append(f"- Jira: {', '.join(jira_issues)}")
  
  lines.extend([
    f"- State: {state}",
    f"- Severity: {severity}" if severity else "- Severity: (not set)",
    f"- Reproduced: {reproduced}",
    f"- Created: {created_at}",
    f"- Updated: {updated_at}",
    "",
  ])
  
  if shallow:
    # Shallow mode: just basic info, mark as incomplete
    lines.append("> **Note:** This is a shallow sync. Full details will be synced in a subsequent run.")
    lines.append("")
  else:
    # Deep mode: full content
    description_md = html_to_markdown(description) if description else ""
    reproduction_md = html_to_markdown(reproduction_steps) if reproduction_steps else ""

    # Initialize attachment maps (will be populated later if attachments exist)
    attachment_url_to_rel: Dict[str, str] = {}
    attachment_id_to_rel: Dict[str, str] = {}  # Map attachment ID to local file
    attachment_filename_to_rel: Dict[str, str] = {}  # Map filename to local file (for fallback matching)
    
    # Build attachment map and download first (only in deep mode, and only if attachment_dir is provided)
    has_attachments = bool(attachments)
    use_attachment_dir = has_attachments and attachment_dir is not None and "/tmp/bugcrowd-no-attachments" not in str(attachment_dir)
    
    if use_attachment_dir:
      # Don't create directory yet - only create when we actually have a file to write
      for att in attachments:
        # Handle both included resources and direct attachment objects
        att_data = att.get("attributes", {}) if isinstance(att, dict) and "attributes" in att else att
        att_id = att.get("id", "") if isinstance(att, dict) else ""
        filename = att_data.get("file_name") or att_data.get("filename") or att_data.get("name") or "attachment"
        # BugCrowd provides s3_signed_url which is the actual S3 signed URL we should use
        # This is preferred over download_url which is just a redirect
        content_url = att_data.get("s3_signed_url") or att_data.get("url") or att_data.get("content_url") or att_data.get("download_url") or ""
        
        if not content_url:
          # Try to construct URL from attachment ID
          content_url = f"{base_url}/submissions/{submission_id}/attachments/{att_id}/download"
        
        if content_url:
          fname = sanitize_filename(filename)
          local_name = f"attachment-{fname}"
          local_path = attachment_dir / local_name
          # Download only if missing
          if not local_path.exists() and content_url:
            try:
              # Create directory only when we're about to write a file
              attachment_dir.mkdir(parents=True, exist_ok=True)
              data_bytes = download_attachment(content_url)
              local_path.write_bytes(data_bytes)
            except Exception as e:
              # If download fails, still create the link
              print(f"Warning: Failed to download attachment {filename}: {e}", file=os.sys.stderr)
          
          if local_path.exists():
            rel = os.path.relpath(local_path, out_path.parent)
            attachment_url_to_rel[content_url] = rel
            # Also map by attachment ID for URL pattern matching
            if att_id:
              attachment_id_to_rel[att_id] = rel
            # Map by filename for fallback matching
            if filename:
              attachment_filename_to_rel[filename] = rel
              # Also map sanitized filename
              attachment_filename_to_rel[fname] = rel
              # Map original filename variations
              attachment_filename_to_rel[local_name] = rel
            # Map BugCrowd web UI URLs (various formats):
            # Format: /submissions/{id}/attachments/{att_id}
            bugcrowd_web_url = f"{base_url}/submissions/{submission_id}/attachments/{att_id}"
            attachment_url_to_rel[bugcrowd_web_url] = rel
            # Also try with https://bugcrowd.com prefix (with and without /codeorg, and with /engagements)
            attachment_url_to_rel[f"https://bugcrowd.com/submissions/{submission_id}/attachments/{att_id}"] = rel
            attachment_url_to_rel[f"https://bugcrowd.com/codeorg/security-inbox/submissions/{submission_id}/attachments/{att_id}"] = rel
            attachment_url_to_rel[f"https://bugcrowd.com/engagements/codeorg/security-inbox/submissions/{submission_id}/attachments/{att_id}"] = rel
            # Map by filename for fallback matching (various formats)
            if filename:
              attachment_filename_to_rel[filename] = rel
              # Also map sanitized filename
              attachment_filename_to_rel[fname] = rel
              # Map original filename variations
              attachment_filename_to_rel[local_name] = rel
              # Also map URL-based filename matching
              attachment_url_to_rel[f"https://bugcrowd.com/engagements/codeorg/security-inbox/submissions/{submission_id}/attachments/{filename}"] = rel
              attachment_url_to_rel[f"https://bugcrowd.com/submissions/{submission_id}/attachments/{filename}"] = rel
            # Map embed URLs: https://bugcrowd.com/embed/{submission_uuid}/{attachment_uuid}
            # The embed URL format uses the submission ID and attachment ID
            if submission_id and att_id:
              attachment_url_to_rel[f"https://bugcrowd.com/embed/{submission_id}/{att_id}"] = rel
              # Also try with the actual submission UUID from the API if different
              # Note: The embed URL might use a different UUID format than submission_id
              # We'll rely on pattern matching in rewrite_attachment_links_to_local for this
            # Map any S3 or files.bugcrowd.com URLs we have
            if content_url:
              attachment_url_to_rel[content_url] = rel
    
    # Rewrite links (after attachment map is built)
    submission_id_to_md_str = {k: os.path.relpath(v, out_path.parent) for k, v in submission_id_to_md.items()}
    description_md = rewrite_bugcrowd_links_to_local(description_md, submission_id_to_md_str, base_url)
    reproduction_md = rewrite_bugcrowd_links_to_local(reproduction_md, submission_id_to_md_str, base_url)
    # Rewrite attachment links in description/reproduction
    description_md = rewrite_attachment_links_to_local(description_md, attachment_url_to_rel, attachment_id_to_rel, submission_id, base_url, attachment_filename_to_rel)
    reproduction_md = rewrite_attachment_links_to_local(reproduction_md, attachment_url_to_rel, attachment_id_to_rel, submission_id, base_url, attachment_filename_to_rel)
    
    # Now add the rewritten description/reproduction to lines
    if description_md.strip():
      lines.append("## Description")
      lines.append("")
      lines.append(description_md.strip())
      lines.append("")
    
    if reproduction_md.strip():
      lines.append("## Reproduction Steps")
      lines.append("")
      lines.append(reproduction_md.strip())
      lines.append("")

    # Attachments section (separate from reproduction steps - always show if attachments exist)
    if has_attachments and attachments:
      lines.append("## Attachments")
      lines.append("")
      for att in attachments:
        att_data = att.get("attributes", {}) if isinstance(att, dict) and "attributes" in att else att
        filename = att_data.get("filename") or att_data.get("name") or att_data.get("file_name") or "attachment"
        content_url = att_data.get("url") or att_data.get("content_url") or att_data.get("download_url") or att_data.get("s3_signed_url") or ""
        att_id = att.get("id", "") if isinstance(att, dict) else ""
        if not content_url and att_id:
          content_url = f"{base_url}/submissions/{submission_id}/attachments/{att_id}/download"
        
        if use_attachment_dir:
          fname = sanitize_filename(filename)
          local_name = f"attachment-{fname}"
          local_path = attachment_dir / local_name
          rel = os.path.relpath(local_path, out_path.parent) if local_path.exists() else None
          if rel:
            lines.append(f"- [{filename}]({rel})")
          else:
            lines.append(f"- {filename} (download failed or URL missing)")
        else:
          # No attachment directory, just list the filename
          lines.append(f"- {filename} (URL: {content_url})" if content_url else f"- {filename}")
      lines.append("")

    # Extract embed URLs from comments before processing
    # These might reference attachments not in the main attachments list
    import re
    embed_urls_found = set()  # Set of (attachment_id, full_embed_url, embed_sub_id)
    for c in comments or []:
      attrs = c.get("attributes", {}) if isinstance(c, dict) and "attributes" in c else c
      body = attrs.get("body") or attrs.get("message") or attrs.get("content") or ""
      if body:
        # Find embed URLs: https://bugcrowd.com/embed/{uuid1}/{uuid2}
        # The first UUID might be submission ID or a different UUID format
        # The second UUID is usually the attachment ID
        embed_pattern = re.compile(r"https?://bugcrowd\.com/embed/([a-zA-Z0-9_-]+)/([a-zA-Z0-9_-]+)", re.IGNORECASE)
        for match in embed_pattern.finditer(body):
          embed_sub_id = match.group(1)
          embed_att_id = match.group(2)
          full_embed_url = match.group(0)
          # Add all embed URLs - we'll try to download them
          # The submission_id in embed URL might be different format, so we'll try both
          embed_urls_found.add((embed_att_id, full_embed_url, embed_sub_id))
    
    # Debug output for embed URLs found (only in verbose mode)
    if embed_urls_found and not shallow and verbose:
      print(f"Found {len(embed_urls_found)} embed URL(s) in comments:", file=os.sys.stderr)
      for embed_att_id, embed_url, embed_sub_id in embed_urls_found:
        print(f"  - Attachment ID: {embed_att_id[:20]}... (submission UUID in URL: {embed_sub_id[:20]}...)", file=os.sys.stderr)
    
    # Download attachments from embed URLs that aren't already downloaded
    # NOTE: Embed URLs in comments appear to be web UI only and are NOT accessible via the API.
    # All API endpoints return 404. These attachments may only be accessible through the web interface.
    if use_attachment_dir and embed_urls_found and client:
      matched_count = 0
      unmatched_count = 0
      if verbose:
        print(f"Checking {len(embed_urls_found)} embed URL(s) in comments...", file=os.sys.stderr)
      for embed_att_id, embed_url, embed_sub_id in embed_urls_found:
        # First check if this attachment ID matches any attachment we already downloaded
        # (sometimes embed URLs reference attachments that are in the main attachments list)
        matched = False
        for att in attachments:
          att_id = att.get("id", "") if isinstance(att, dict) else ""
          if att_id == embed_att_id:
            # This embed attachment is actually in the main attachments list - already downloaded!
            if embed_att_id in attachment_id_to_rel:
              attachment_url_to_rel[embed_url] = attachment_id_to_rel[embed_att_id]
              attachment_url_to_rel[f"https://bugcrowd.com/embed/{submission_id}/{embed_att_id}"] = attachment_id_to_rel[embed_att_id]
              attachment_url_to_rel[f"https://bugcrowd.com/embed/{embed_sub_id}/{embed_att_id}"] = attachment_id_to_rel[embed_att_id]
              if verbose:
                print(f"  ✓ Embed attachment {embed_att_id[:20]}... matches main attachment (already downloaded)", file=os.sys.stderr)
              matched = True
              matched_count += 1
              break
        
        if matched:
          continue
        
        # Embed attachment is NOT in the main attachments list
        # These embed URLs are web UI only - BugCrowd API does not provide access to them
        # All API endpoints tested return 404:
        # - /submissions/{id}/attachments/{embed_att_id}/download → 404
        # - /submissions/{embed_sub_id}/attachments/{embed_att_id}/download → 404
        # - Direct embed URL access → 404
        # 
        # These attachments are only accessible through the BugCrowd web interface with browser authentication.
        # We cannot download them via the API.
        if verbose:
          print(f"  ✗ Embed attachment {embed_att_id[:20]}... is NOT in main attachments list", file=os.sys.stderr)
          print(f"    → This attachment is only accessible via BugCrowd web UI (not API)", file=os.sys.stderr)
          print(f"    → Embed URL will remain as remote link in markdown", file=os.sys.stderr)
        unmatched_count += 1
        
        # COMMENTED OUT: All these methods return 404 - embed URLs are not API accessible
        # if not data_bytes:
        #   # Try API methods (all return 404 - embed URLs are web UI only)
        #   try:
        #     att_meta = client.get_attachment_by_id(submission_id, embed_att_id)
        #     if att_meta:
        #       data_bytes = client.download_attachment_by_id(submission_id, embed_att_id)
        #   except Exception:
        #     pass
        # 
        # if not data_bytes:
        #   try:
        #     download_url = f"{base_url}/submissions/{submission_id}/attachments/{embed_att_id}/download"
        #     data_bytes = download_attachment(download_url)
        #   except Exception:
        #     data_bytes = None
      
      # Summary
      if matched_count > 0 or unmatched_count > 0:
        if verbose:
          print(f"Embed attachment summary: {matched_count} matched main attachments, {unmatched_count} web UI only (not API accessible)", file=os.sys.stderr)
    
    # Process comments/activities (only in deep mode)
    # Deduplicate comments by ID and by content+date+author (comments might come from multiple sources)
    seen_comment_ids = set()
    seen_comment_hashes = set()
    unique_comments = []
    for c in comments or []:
      comment_id = c.get("id", "") if isinstance(c, dict) else ""
      
      # Check by ID first
      if comment_id and comment_id in seen_comment_ids:
        continue
      
      # Also check by content+date+author hash (for comments without IDs or duplicates)
      attrs = c.get("attributes", {}) if isinstance(c, dict) and "attributes" in c else c
      body = attrs.get("body") or attrs.get("message") or attrs.get("content") or ""
      created = attrs.get("created_at") or attrs.get("created") or ""
      author_data = attrs.get("author") or attrs.get("user") or {}
      if isinstance(author_data, dict):
        author = author_data.get("username") or author_data.get("name") or author_data.get("email") or "unknown"
      else:
        author = str(author_data) if author_data else "unknown"
      
      comment_hash = f"{author}|{created}|{body[:100]}"  # First 100 chars of body for hash
      if comment_hash in seen_comment_hashes:
        continue
      
      # Add to seen sets
      if comment_id:
        seen_comment_ids.add(comment_id)
      seen_comment_hashes.add(comment_hash)
      unique_comments.append(c)
    
    comment_blocks = []
    for c in unique_comments:
      # Handle both comment and activity types
      attrs = c.get("attributes", {}) if isinstance(c, dict) and "attributes" in c else c
      body = attrs.get("body") or attrs.get("message") or attrs.get("content") or ""
      body_md = html_to_markdown(body) if body else ""
      
      # Get author info - check multiple locations
      author = "unknown"
      
      # 1. Check attributes.author (direct)
      author_data = attrs.get("author") or attrs.get("user") or {}
      if isinstance(author_data, dict):
        author = author_data.get("username") or author_data.get("name") or author_data.get("email") or "unknown"
      elif author_data:
        author = str(author_data)
      
      # 2. Check relationships.author or relationships.actor (JSON API format) and resolve from included resources
      # Activities use "actor", comments use "author"
      if author == "unknown" and isinstance(c, dict):
        rels = c.get("relationships", {})
        # Try "actor" first (for activities), then "author" (for comments)
        author_rel = None
        if isinstance(rels, dict):
          author_rel = rels.get("actor") or rels.get("author") or {}
        
        if isinstance(author_rel, dict):
          author_data = author_rel.get("data", {})
          if isinstance(author_data, dict):
            author_id = author_data.get("id", "")
            author_type = author_data.get("type", "")
            
            # Try to resolve from included resources if we have full_submission
            if author_id and author_type and full_submission:
              included = full_submission.get("included", []) if isinstance(full_submission, dict) else []
              for item in included:
                if isinstance(item, dict) and item.get("id") == author_id and item.get("type") == author_type:
                  author_attrs = item.get("attributes", {})
                  if isinstance(author_attrs, dict):
                    author = author_attrs.get("username") or author_attrs.get("name") or author_attrs.get("email") or "unknown"
                    break
            
            # Fallback: try attributes directly in relationship data
            if author == "unknown":
              author_attrs = author_data.get("attributes", {})
              if isinstance(author_attrs, dict):
                author = author_attrs.get("username") or author_attrs.get("name") or author_attrs.get("email") or "unknown"
      
      created_raw = attrs.get("created_at") or attrs.get("created") or ""
      created_formatted = format_date_pacific(created_raw)
      comment_type = c.get("type", "") if isinstance(c, dict) else ""
      
      # Get activity event/action metadata (for activities like "created a blocker")
      # Activities use "key" field (e.g., "blocker.created"), comments/other might use "event"
      event_key = attrs.get("key") or attrs.get("event") or attrs.get("event_type") or attrs.get("action") or ""
      activity_text = ""
      if event_key:
        # Format activity text like "Created A Blocker", "Sent A Message", etc.
        # Key might be like "blocker.created", "comment.created", etc.
        # Convert to readable text: "blocker.created" -> "Created A Blocker"
        # Split by dot, reverse, title case, join
        parts = event_key.split(".")
        if len(parts) == 2:
          # Format: "blocker.created" -> "Created A Blocker"
          action, object_type = parts[1], parts[0]
          activity_text = f"{action.replace('_', ' ').title()} A {object_type.replace('_', ' ').title()}"
        else:
          # Fallback: just replace underscores/dashes and title case
          activity_text = event_key.replace("_", " ").replace("-", " ").title()
      
      # Check if this is an activity (not a comment with body)
      is_activity = comment_type and "activity" in comment_type.lower()
      has_no_body = not body_md or not body_md.strip()
      
      # Format as H3 header with author, activity, and date
      # Show activity text if it's an activity (not a regular comment)
      if activity_text and is_activity:
        type_label = f" ({activity_text})"
      elif activity_text and has_no_body:
        # Even if type isn't "activity", if there's an event and no body, it's likely an activity
        type_label = f" ({activity_text})"
      elif comment_type and comment_type != "comment":
        type_label = f" ({comment_type})"
      else:
        type_label = ""
      
      # For activities with no body, show the activity text as the content
      # This handles cases like "created a blocker" where there's an event but no message body
      if has_no_body and activity_text:
        body_md = f"*{activity_text}*"  # Italicize the activity text as content
      elif has_no_body and not activity_text and not is_activity:
        # Skip entries with no body, no activity text, and not marked as activity
        # (These are likely empty comments that aren't useful)
        continue
      elif has_no_body and is_activity:
        # Activities without body or event text - show a generic activity indicator
        body_md = "*Activity*"
      
      header = f"### {author}{type_label} — {created_formatted}" if created_formatted else f"### {author}{type_label}"
      comment_blocks.append((created_raw, header, body_md))  # Store with raw date for sorting

    # Sort comments by date (newest first - reverse order)
    comment_blocks.sort(key=lambda x: x[0] if x[0] else "", reverse=True)

    # Rewrite links in comments and build final formatted blocks
    formatted_blocks = []
    for created_raw, header, body_md in comment_blocks:
      # Rewrite links in body
      body_md = rewrite_bugcrowd_links_to_local(body_md, submission_id_to_md_str, base_url)
      body_md = rewrite_attachment_links_to_local(body_md, attachment_url_to_rel, attachment_id_to_rel, submission_id, base_url, attachment_filename_to_rel)
      
      formatted_blocks.append(f"{header}\n\n{body_md.strip()}")

    lines.append("## Comments / Activity")
    lines.append("")
    if formatted_blocks:
      lines.extend(formatted_blocks)
      lines.append("")
    else:
      lines.append("_No comments or activity_")
      lines.append("")

  out_path.parent.mkdir(parents=True, exist_ok=True)
  out_path.write_text("\n".join(lines), encoding="utf-8")
