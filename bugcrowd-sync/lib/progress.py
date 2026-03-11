"""Progress helpers for bugcrowd_sync."""

import sys
import time
from datetime import datetime, timedelta
from typing import Optional


class SyncProgress:
  """
  Lightweight, single-line progress output (TTY-friendly) with time estimates.
  """

  def __init__(self, *, enabled: bool = True) -> None:
    self.enabled = enabled
    self.is_tty = sys.stderr.isatty()
    self._last_len = 0
    self._last_print_ts = 0.0
    self._start_time: Optional[float] = None
    self._last_processed = 0
    self._last_actually_processed = 0
    self._last_time = 0.0

  def update(self, msg: str, *, force: bool = False) -> None:
    if not self.enabled:
      return
    now = time.time()
    # Avoid hammering output in non-tty contexts, but allow force updates.
    if not force and not self.is_tty and (now - self._last_print_ts) < 0.5:
      return
    self._last_print_ts = now

    if self.is_tty:
      # Overwrite the current line.
      pad = " " * max(0, self._last_len - len(msg))
      sys.stderr.write("\r" + msg + pad)
      sys.stderr.flush()
      self._last_len = len(msg)
    else:
      # Non-TTY: print newlines for better visibility
      print(msg, file=sys.stderr, flush=True)

  def update_pct(self, processed: int, total: int, *, status: str = "", force: bool = False) -> None:
    if total == 0:
      pct = 0
    else:
      pct = int(100.0 * processed / total)
    msg = f"[{status}] {processed}/{total} ({pct}%)" if status else f"{processed}/{total} ({pct}%)"
    self.update(msg, force=force)

  def update_with_eta(self, msg: str, processed: int, total: int, *, status: str = "", force: bool = False, actually_processed: Optional[int] = None) -> None:
    """Update progress with time estimates (ETA, time remaining, completion time).
    
    Args:
      msg: Status message
      processed: Total items processed (including skipped)
      total: Total items to process
      status: Status prefix
      force: Force update even if not TTY
      actually_processed: Items that actually took time to process (not skipped). If None, uses processed.
                         This is used for accurate ETA calculation - skipped items don't count towards rate.
    """
    if not self.enabled:
      return
    
    # Use actually_processed for rate calculations, but processed for percentage display
    if actually_processed is None:
      actually_processed = processed
    
    now = time.time()
    if self._start_time is None:
      self._start_time = now
      self._last_processed = 0
      self._last_actually_processed = 0
      self._last_time = now
    
    # Calculate progress percentage (based on total processed, including skipped)
    if total == 0:
      pct = 0
      eta_seconds = 0
    else:
      pct = int(100.0 * processed / total)
      
      # Calculate ETA based on rate of actually processed items (not skipped)
      elapsed = now - self._start_time
      if actually_processed > 0 and elapsed > 0:
        rate = actually_processed / elapsed  # items per second (only items that took time)
        remaining = total - processed  # Remaining items to process (including skipped ones)
        eta_seconds = int(remaining / rate) if rate > 0 else 0
      else:
        eta_seconds = 0
      
      # Also calculate based on recent window (last N seconds) - only count actually processed items
      if hasattr(self, '_last_actually_processed') and actually_processed > self._last_actually_processed and (now - self._last_time) > 5:
        recent_rate = (actually_processed - self._last_actually_processed) / (now - self._last_time)
        if recent_rate > 0:
          remaining = total - processed
          eta_seconds = int(remaining / recent_rate)
        self._last_actually_processed = actually_processed
        self._last_processed = processed
        self._last_time = now
      elif not hasattr(self, '_last_actually_processed'):
        self._last_actually_processed = actually_processed
    
    # Format time estimates
    status_prefix = f"[{status}] " if status else ""
    if eta_seconds > 0:
      eta_delta = timedelta(seconds=eta_seconds)
      eta_time = datetime.now() + eta_delta
      
      # Format time remaining
      hours, remainder = divmod(eta_seconds, 3600)
      minutes, seconds = divmod(remainder, 60)
      if hours > 0:
        time_remaining = f"{hours}h {minutes}m"
      elif minutes > 0:
        time_remaining = f"{minutes}m {seconds}s"
      else:
        time_remaining = f"{seconds}s"
      
      # Format completion time
      now = datetime.now()
      if eta_time.date() == now.date():
        completion_time = eta_time.strftime("%I:%M %p")
      else:
        completion_time = eta_time.strftime("%b %d, %I:%M %p")
      
      # Build enhanced message - keep it concise to avoid truncation
      # Truncate msg if too long to ensure ETA is always visible
      # Reserve space for: " - X/Y (Z%) - ETA: Xh Xm (~time)" = ~40 chars
      max_msg_len = 50  # Limit message length so ETA doesn't get cut off
      if len(msg) > max_msg_len:
        msg = msg[:max_msg_len-3] + "..."
      enhanced_msg = f"{status_prefix}{msg} - {processed}/{total} ({pct}%) - ETA: {time_remaining} (~{completion_time})"
    else:
      # Truncate msg if too long (no ETA, so can be longer)
      max_msg_len = 80
      if len(msg) > max_msg_len:
        msg = msg[:max_msg_len-3] + "..."
      enhanced_msg = f"{status_prefix}{msg} - {processed}/{total} ({pct}%)"
    
    self.update(enhanced_msg, force=force)

  def print_final(self, msg: str) -> None:
    """Print a final message that won't be overwritten (permanent line)."""
    if not self.enabled:
      return
    if self.is_tty:
      # Clear the current line first, then print on a new line
      pad = " " * max(0, self._last_len)
      sys.stderr.write("\r" + pad + "\r")  # Clear current line
      sys.stderr.flush()
    # Print the final message (new line, won't be overwritten)
    print(msg, file=sys.stderr, flush=True)
    self._last_len = 0  # Reset for next update cycle

  def done(self) -> None:
    if not self.enabled:
      return
    if self.is_tty:
      sys.stderr.write("\n")
      sys.stderr.flush()
    self._start_time = None  # Reset for next run

