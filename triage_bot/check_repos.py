#!/usr/bin/env python3
"""
Check configured analysis repositories:
- on expected branch
- not behind origin/<branch>

Configuration comes from `triage_bot/.env`:
- Preferred: ANALYSIS_REPOS=name|branch|/abs/path;name2|main|/abs/path2
- Legacy fallback: REPO_CODE_DOT_ORG, REPO_MARKETING_SITES, ...

Exit 0 = all OK, 1 = issues found.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from config import load_env, parse_analysis_repos


def _script_dir() -> Path:
    return Path(__file__).resolve().parent


def get_current_branch(repo_path: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def is_behind_upstream(repo_path: Path, branch: str) -> bool:
    """True if local branch is behind origin/branch."""
    try:
        subprocess.run(
            ["git", "fetch", "origin"],
            cwd=repo_path,
            capture_output=True,
            timeout=30,
        )
        result = subprocess.run(
            ["git", "rev-list", f"HEAD..origin/{branch}", "--count"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return False  # no origin/branch or detached edge case
        return int(result.stdout.strip() or "0") > 0
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        return False


def check_repo(path: Path, expected_branch: str, name: str) -> tuple[bool, list[str]]:
    """Returns (ok, list of issues)."""
    issues: list[str] = []

    if not path.exists():
        issues.append(f"{name}: path does not exist: {path}")
        return False, issues

    if not (path / ".git").exists():
        issues.append(f"{name}: not a git repo: {path}")
        return False, issues

    current = get_current_branch(path)
    if current != expected_branch:
        issues.append(f"{name}: on branch '{current}', expected '{expected_branch}'")
    elif is_behind_upstream(path, expected_branch):
        issues.append(f"{name}: behind origin/{expected_branch} (run make up_to_date)")

    return len(issues) == 0, issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Check analysis repo branch/freshness")
    parser.parse_args()

    env = {**os.environ, **load_env(_script_dir())}
    try:
        repo_targets = parse_analysis_repos(env, _script_dir())
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if not repo_targets:
        print("SKIP: no analysis repos configured")
        return 0

    all_ok = True
    for repo in repo_targets:
        ok, issues = check_repo(repo.path, repo.branch, repo.name)
        if not ok:
            all_ok = False
            for issue in issues:
                print(f"ISSUE: {issue}", file=sys.stderr)
        else:
            print(f"OK: {repo.name} on {repo.branch}")

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
