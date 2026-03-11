import re
import warnings
from typing import Dict, Optional

# Suppress BeautifulSoup XML parsing warnings - we're converting HTML to Markdown,
# so HTML parser is fine even if content looks XML-like
# This warning appears when BeautifulSoup encounters XML-like content with HTML parser
warnings.filterwarnings("ignore", message=".*XMLParsedAsHTMLWarning.*", category=UserWarning)
warnings.filterwarnings("ignore", message=".*parsing an XML document using an HTML parser.*", category=UserWarning)


def html_to_markdown(html_str: str) -> str:
  """Convert HTML to Markdown, preserving any existing markdown syntax.
  
  BugCrowd descriptions may contain markdown that's been HTML-escaped.
  We want to preserve the markdown syntax, not escape it further.
  """
  html_str = html_str or ""
  
  # If the string doesn't look like HTML (no tags), it might already be markdown
  if not re.search(r'<[a-z][\s>]', html_str, re.IGNORECASE):
    # Already markdown or plain text - return as-is (but unescape any HTML entities)
    import html
    return html.unescape(html_str)
  
  try:
    from markdownify import markdownify as _md  # type: ignore
    
    # Convert HTML to markdown
    md = _md(html_str, heading_style="ATX", escape_misc=False)
    
    # Unescape markdown characters that were escaped by markdownify
    # markdownify sometimes escapes #, +, -, !, etc. when they're in code blocks or other contexts
    # We want to preserve markdown syntax, so unescape common markdown characters
    md = re.sub(r'\\([#*_`\[\]()!+\-])', r'\1', md)
    
    return md
  except Exception:
    try:
      import html2text  # type: ignore

      h = html2text.HTML2Text()
      h.body_width = 0
      h.ignore_images = False
      h.ignore_links = False
      h.single_line_break = True
      md = h.handle(html_str)
      
      # Unescape markdown characters
      md = re.sub(r'\\([#*_`\[\]()!+\-])', r'\1', md)
      
      return md
    except Exception as e:
      raise RuntimeError(
        "Missing HTML->Markdown dependency. Install: pip install -r requirements.txt"
      ) from e


def rewrite_bugcrowd_links_to_local(md: str, submission_id_to_md: Dict[str, str], base_url: str) -> str:
  """Rewrite BugCrowd submission links to local markdown files."""
  base = base_url.rstrip("/")
  # BugCrowd links might be in format: /submissions/{id} or full URL
  pattern = re.compile(rf"{re.escape(base)}/submissions/([a-zA-Z0-9_-]+)", re.IGNORECASE)

  def repl(match: re.Match) -> str:
    sub_id = match.group(1)
    dest = submission_id_to_md.get(sub_id)
    if not dest:
      return match.group(0)
    return f"[Submission {sub_id}]({dest})"

  return pattern.sub(repl, md)


def rewrite_attachment_links_to_local(
  md: str,
  attachment_url_to_rel: Dict[str, str],
  attachment_id_to_rel: Dict[str, str],
  submission_id: str,
  base_url: str,
  attachment_filename_to_rel: Optional[Dict[str, str]] = None,
) -> str:
  """Rewrite attachment URLs to local file paths.
  
  Handles multiple URL formats:
  - Direct URLs: https://bugcrowd.com/.../attachments/{id}
  - S3 URLs: https://files.bugcrowd.com/...
  - Attachment IDs in URLs
  - Filename-based matching as fallback
  
  Args:
    attachment_filename_to_rel: Optional mapping of filename -> relative path for fallback matching
  """
  if attachment_filename_to_rel is None:
    attachment_filename_to_rel = {}
  # Pattern 1: Image markdown links with URLs - rewrite the URL part FIRST (before other patterns)
  # Format: ![alt](url "title")
  def repl_image_url(match: re.Match) -> str:
    alt = match.group(1)
    url = match.group(2)
    title = match.group(3) if match.lastindex >= 3 and match.group(3) else ""
    
    # Check if URL is in our direct mapping
    if url in attachment_url_to_rel:
      local_path = attachment_url_to_rel[url]
      if title:
        return f"![{alt}]({local_path} \"{title}\")"
      else:
        return f"![{alt}]({local_path})"
    
    # Check if URL matches any of our patterns and extract attachment ID
    # Try embed URL pattern: https://bugcrowd.com/embed/{uuid1}/{uuid2}
    # First check if the full embed URL is in our mapping (most reliable)
    if url in attachment_url_to_rel:
      local_path = attachment_url_to_rel[url]
      if title:
        return f"![{alt}]({local_path} \"{title}\")"
      else:
        return f"![{alt}]({local_path})"
    
    embed_match = re.match(r"https?://bugcrowd\.com/embed/[^/]+/([a-zA-Z0-9_-]+)", url, re.IGNORECASE)
    if embed_match:
      att_id = embed_match.group(1)
      # Try direct attachment ID mapping
      if att_id in attachment_id_to_rel:
        local_path = attachment_id_to_rel[att_id]
        if title:
          return f"![{alt}]({local_path} \"{title}\")"
        else:
          return f"![{alt}]({local_path})"
      # Also try matching the full embed URL with submission_id pattern
      # The embed URL format is: https://bugcrowd.com/embed/{submission_uuid}/{attachment_uuid}
      embed_full_match = re.match(r"https?://bugcrowd\.com/embed/([^/]+)/([a-zA-Z0-9_-]+)", url, re.IGNORECASE)
      if embed_full_match:
        embed_sub_id = embed_full_match.group(1)
        embed_att_id = embed_full_match.group(2)
        # Try matching with submission_id + attachment_id combination
        embed_key = f"https://bugcrowd.com/embed/{submission_id}/{embed_att_id}"
        if embed_key in attachment_url_to_rel:
          local_path = attachment_url_to_rel[embed_key]
          if title:
            return f"![{alt}]({local_path} \"{title}\")"
          else:
            return f"![{alt}]({local_path})"
    
    # Try submission attachment URL pattern (various formats):
    # - /submissions/{id}/attachments/{att_id}
    # - /codeorg/security-inbox/submissions/{id}/attachments/{att_id}
    # - /engagements/codeorg/security-inbox/submissions/{id}/attachments/{att_id}
    att_url_match = re.match(
      rf"https?://(?:bugcrowd\.com|api\.bugcrowd\.com)(?:/engagements/codeorg|/codeorg)?/submissions/{re.escape(submission_id)}/attachments/([a-zA-Z0-9_-]+)",
      url,
      re.IGNORECASE
    )
    if att_url_match:
      att_id = att_url_match.group(1)
      if att_id in attachment_id_to_rel:
        local_path = attachment_id_to_rel[att_id]
        if title:
          return f"![{alt}]({local_path} \"{title}\")"
        else:
          return f"![{alt}]({local_path})"
    
    # Try matching by filename as fallback (extract filename from URL or alt text)
    # Check if alt text or title matches any downloaded attachment filename
    if (alt or title) and attachment_filename_to_rel:
      # Extract just the filename from alt text (remove path/URL if present)
      filename_from_alt = (alt or title).split("/")[-1].split("\\")[-1]
      # Normalize filename (remove URL encoding, lowercase for comparison)
      filename_clean = filename_from_alt.split("?")[0].lower()
      # Try to find matching attachment by comparing filenames
      for att_filename, rel_path in attachment_filename_to_rel.items():
        att_filename_clean = att_filename.lower()
        # Check if filenames match (with or without attachment- prefix)
        if (filename_clean == att_filename_clean or 
            filename_clean == att_filename_clean.replace("attachment-", "") or
            att_filename_clean.endswith(filename_clean) or
            filename_clean in att_filename_clean):
          if title:
            return f"![{alt}]({rel_path} \"{title}\")"
          else:
            return f"![{alt}]({rel_path})"
    
    return match.group(0)
  
  md = re.sub(r'!\[([^\]]*)\]\(([^\s)]+)(?:\s+"([^"]+)")?\)', repl_image_url, md)
  
  # Pattern 2: Rewrite standalone URLs (not in markdown links)
  def repl_url(match: re.Match) -> str:
    url = match.group(2)
    if url in attachment_url_to_rel:
      return f"{match.group(1)}({attachment_url_to_rel[url]})"
    return match.group(0)
  
  md = re.sub(r"(\]\()(https?://[^\s)]+)", repl_url, md)
  
  # Pattern 3: Standalone BugCrowd attachment URLs (not in markdown links)
  # Pattern: /submissions/{submission_id}/attachments/{attachment_id}
  # Also handles: /engagements/codeorg/security-inbox/submissions/{submission_id}/attachments/{attachment_id}
  pattern1 = re.compile(
    rf"(?<!\]\()(https?://(?:bugcrowd\.com|api\.bugcrowd\.com)(?:/engagements/codeorg|/codeorg)?/submissions/{re.escape(submission_id)}/attachments/([a-zA-Z0-9_-]+))",
    re.IGNORECASE
  )
  
  def repl_attachment_id(match: re.Match) -> str:
    full_url = match.group(1)
    att_id = match.group(2)
    if att_id in attachment_id_to_rel:
      return attachment_id_to_rel[att_id]
    if full_url in attachment_url_to_rel:
      return attachment_url_to_rel[full_url]
    return full_url
  
  md = pattern1.sub(repl_attachment_id, md)
  
  # Pattern 4: Standalone BugCrowd embed URLs: https://bugcrowd.com/embed/{uuid1}/{uuid2}
  # Handle these more carefully - the second UUID is usually the attachment ID
  pattern2 = re.compile(
    r"(?<!\]\()(https?://bugcrowd\.com/embed/([a-zA-Z0-9_-]+)/([a-zA-Z0-9_-]+))",
    re.IGNORECASE
  )
  
  def repl_embed_url(match: re.Match) -> str:
    full_url = match.group(1)
    uuid1 = match.group(2)
    uuid2 = match.group(3)
    
    # First check if the full embed URL is in our mapping (most reliable)
    if full_url in attachment_url_to_rel:
      return attachment_url_to_rel[full_url]
    
    # Try matching with submission_id + uuid2 (attachment ID)
    if submission_id and uuid2:
      embed_key = f"https://bugcrowd.com/embed/{submission_id}/{uuid2}"
      if embed_key in attachment_url_to_rel:
        return attachment_url_to_rel[embed_key]
    
    # Fallback: try both UUIDs as potential attachment IDs (second one is usually the attachment ID)
    if uuid2 in attachment_id_to_rel:
      return attachment_id_to_rel[uuid2]
    if uuid1 in attachment_id_to_rel:
      return attachment_id_to_rel[uuid1]
    
    return full_url
  
  md = pattern2.sub(repl_embed_url, md)
  
  return md

