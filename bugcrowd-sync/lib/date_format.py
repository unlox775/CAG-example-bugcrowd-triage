"""Date formatting utilities for BugCrowd sync."""
from datetime import datetime
from typing import Optional
import pytz


def format_date_pacific(iso_date_str: str) -> str:
  """Convert ISO 8601 date string to human-readable Pacific time format.
  
  Example: "2023-03-10T13:16:44.566Z" -> "March 10th, 2023 at 6:16 a.m. Pacific"
  """
  if not iso_date_str:
    return ""
  
  try:
    # Parse ISO 8601 date (may or may not have Z suffix)
    if iso_date_str.endswith("Z"):
      dt = datetime.fromisoformat(iso_date_str.replace("Z", "+00:00"))
    elif "+" in iso_date_str or iso_date_str.count("-") >= 3:
      dt = datetime.fromisoformat(iso_date_str)
    else:
      # Try parsing without timezone
      dt = datetime.fromisoformat(iso_date_str.replace("Z", ""))
      dt = pytz.UTC.localize(dt)
    
    # Ensure it's timezone-aware (assume UTC if not)
    if dt.tzinfo is None:
      dt = pytz.UTC.localize(dt)
    
    # Convert to Pacific time
    pacific = pytz.timezone("America/Los_Angeles")
    dt_pacific = dt.astimezone(pacific)
    
    # Format date
    day = dt_pacific.day
    day_suffix = {
      1: "st", 2: "nd", 3: "rd", 21: "st", 22: "nd", 23: "rd", 31: "st"
    }.get(day % 10 if day % 10 in (1, 2, 3) and day not in (11, 12, 13) else 0, "th")
    
    month_name = dt_pacific.strftime("%B")
    year = dt_pacific.year
    
    # Format time (12-hour format with a.m./p.m., including seconds)
    hour = dt_pacific.hour
    minute = dt_pacific.minute
    second = dt_pacific.second
    if hour == 0:
      time_str = f"12:{minute:02d}:{second:02d} a.m."
    elif hour < 12:
      time_str = f"{hour}:{minute:02d}:{second:02d} a.m."
    elif hour == 12:
      time_str = f"12:{minute:02d}:{second:02d} p.m."
    else:
      time_str = f"{hour - 12}:{minute:02d}:{second:02d} p.m."
    
    return f"{month_name} {day}{day_suffix}, {year} at {time_str} Pacific"
  except Exception:
    # If parsing fails, return original string
    return iso_date_str

