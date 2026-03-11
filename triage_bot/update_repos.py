#!/usr/bin/env python3
"""Run `git pull` for each configured analysis repository."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from config import load_env, parse_analysis_repos


def _script_dir() -> Path:
    return Path(__file__).resolve().parent


def main() -> int:
    env = {**os.environ, **load_env(_script_dir())}
    try:
        repos = parse_analysis_repos(env, _script_dir())
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if not repos:
        print("SKIP: no analysis repos configured")
        return 0

    for repo in repos:
        path = repo.path
        if not path.exists():
            print(f"SKIP: {repo.name} path does not exist: {path}")
            continue
        if not (path / ".git").exists():
            print(f"SKIP: {repo.name} is not a git repo: {path}")
            continue

        print(f"\n--- Updating {repo.name} ({path}) ---")
        result = subprocess.run(["git", "pull"], cwd=path)
        if result.returncode != 0:
            print(
                f"FAILED: git pull in {path} exited with {result.returncode}",
                file=sys.stderr,
            )
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
