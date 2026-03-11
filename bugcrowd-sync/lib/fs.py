"""Filesystem helpers for bugcrowd_sync."""

import shutil
from pathlib import Path


def ensure_dir(path: Path) -> None:
  path.mkdir(parents=True, exist_ok=True)


def remove_if_exists(path: Path) -> None:
  if not path.exists():
    return
  if path.is_file() or path.is_symlink():
    path.unlink()
  elif path.is_dir():
    shutil.rmtree(path)


def move_submission_files(old_path: Path, new_path: Path) -> bool:
  """
  Move a submission's markdown file and attachment folder from old_path to new_path.
  
  Returns True if move was successful, False otherwise.
  """
  if not old_path.exists():
    return False
  
  try:
    # Ensure new directory exists
    new_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Move the markdown file
    if old_path.is_file():
      shutil.move(str(old_path), str(new_path))
    elif old_path.is_dir():
      # If it's a directory, move the whole thing (shouldn't happen, but handle it)
      shutil.move(str(old_path), str(new_path))
      return True
    
    # Move attachment folder if it exists
    old_attach_dir = old_path.with_suffix("")  # Remove .md extension
    new_attach_dir = new_path.with_suffix("")
    
    if old_attach_dir.exists() and old_attach_dir.is_dir():
      if new_attach_dir.exists():
        # If new attachment dir exists, merge contents (move files from old to new)
        for item in old_attach_dir.iterdir():
          dest = new_attach_dir / item.name
          if item.is_file():
            if not dest.exists():
              shutil.move(str(item), str(dest))
            else:
              # File already exists, remove old one
              item.unlink()
          elif item.is_dir():
            if not dest.exists():
              shutil.move(str(item), str(dest))
            else:
              # Directory exists, merge recursively
              for subitem in item.rglob("*"):
                rel_path = subitem.relative_to(item)
                dest_subitem = dest / rel_path
                dest_subitem.parent.mkdir(parents=True, exist_ok=True)
                if subitem.is_file() and not dest_subitem.exists():
                  shutil.move(str(subitem), str(dest_subitem))
                elif subitem.is_file():
                  subitem.unlink()
              item.rmdir()
        # Remove old attachment dir if empty
        try:
          old_attach_dir.rmdir()
        except OSError:
          pass  # Not empty or doesn't exist
      else:
        # New attachment dir doesn't exist, just move the whole folder
        shutil.move(str(old_attach_dir), str(new_attach_dir))
    
    return True
  except Exception as e:
    # Move failed, return False
    return False


def prune_empty_dirs(root: Path, *, keep_root: bool = True) -> None:
  """
  Recursively delete empty directories under root.
  """
  if not root.exists() or not root.is_dir():
    return
  # Walk bottom-up
  for d in sorted([p for p in root.rglob("*") if p.is_dir()], key=lambda p: len(str(p)), reverse=True):
    try:
      if any(d.iterdir()):
        continue
      if keep_root and d == root:
        continue
      d.rmdir()
    except Exception:
      pass


def cleanup_tree(data_dir: Path, *, allowed_files: set[Path], allowed_dirs: set[Path]) -> int:
  """
  Remove any files/dirs under data_dir not in allowed sets.

  Returns number of removed paths.
  
  Note: Files inside allowed_dirs are preserved even if not in allowed_files.
  This prevents deletion of attachment files in attachment folders.
  """
  removed = 0
  data_dir = data_dir.resolve()

  # Check if a file is inside any allowed directory
  def is_in_allowed_dir(file_path: Path) -> bool:
    file_resolved = file_path.resolve()
    for allowed_dir in allowed_dirs:
      try:
        # Check if file is inside this allowed directory
        file_resolved.relative_to(allowed_dir)
        return True
      except ValueError:
        # Not inside this directory, try next
        continue
    return False

  # Delete files first (deepest first)
  for p in sorted([x for x in data_dir.rglob("*") if x.is_file() or x.is_symlink()], key=lambda x: len(str(x)), reverse=True):
    rp = p.resolve()
    # Preserve file if it's explicitly allowed OR if it's inside an allowed directory
    if rp not in allowed_files and not is_in_allowed_dir(rp):
      try:
        p.unlink()
        removed += 1
      except Exception:
        pass

  # Delete directories that aren't allowed (deepest first)
  for d in sorted([x for x in data_dir.rglob("*") if x.is_dir()], key=lambda x: len(str(x)), reverse=True):
    rd = d.resolve()
    if rd not in allowed_dirs:
      try:
        shutil.rmtree(d)
        removed += 1
      except Exception:
        pass

  return removed

