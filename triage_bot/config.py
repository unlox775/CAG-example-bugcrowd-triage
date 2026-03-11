#!/usr/bin/env python3
"""
Shared config helpers for triage bot scripts.

This file keeps split-out configuration in one place so the example can be
re-used with different report schemas and repository sets.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Legacy env vars are still supported for backward compatibility.
LEGACY_REPO_CONFIG = {
    "REPO_CODE_DOT_ORG": ("staging", "code-dot-org"),
    "REPO_MARKETING_SITES": ("main", "marketing-sites"),
    "REPO_INFRASTRUCTURE": ("main", "infrastructure"),
    "REPO_JAVABUILDER": ("main", "javabuilder"),
    "REPO_AIPROXY": ("main", "aiproxy"),
}


@dataclass(frozen=True)
class RepoTarget:
    name: str
    branch: str
    path: Path


@dataclass(frozen=True)
class ReportSettings:
    report_dir: Path
    filename_template: str
    analyze_key: str
    short_id_key: str
    title_key: str
    priority_key: str
    runtimes_key: str
    pentest_folder_key: str
    pen_test_created_key: str


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse KEY=value pairs from a file, ignoring comments."""
    result: dict[str, str] = {}
    if not path.exists():
        return result
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                result[k.strip()] = v.strip()
    return result


def load_env(script_dir: Path) -> dict[str, str]:
    """Load env with `env.example` defaults overridden by `.env`."""
    return {
        **parse_env_file(script_dir / "env.example"),
        **parse_env_file(script_dir / ".env"),
    }


def _resolve_path(raw_path: str, base_dir: Path) -> Path:
    p = Path(raw_path).expanduser()
    if not p.is_absolute():
        p = base_dir / p
    return p.resolve()


def get_report_settings(script_dir: Path, env: dict[str, str]) -> ReportSettings:
    """Resolve report schema/path settings from env."""
    default_report_dir = script_dir.parent / "secretary" / "blocked_report"
    report_dir = _resolve_path(
        env.get("BLOCKER_REPORT_DIR", str(default_report_dir)),
        script_dir,
    )

    filename_template = env.get(
        "BLOCKER_REPORT_FILENAME_TEMPLATE",
        "{date}_blocker_report.json",
    ).strip()
    if "{date}" not in filename_template:
        raise ValueError(
            "BLOCKER_REPORT_FILENAME_TEMPLATE must include '{date}', "
            "for example '{date}_blocker_report.json'"
        )

    return ReportSettings(
        report_dir=report_dir,
        filename_template=filename_template,
        analyze_key=env.get("REPORT_ANALYZE_KEY", "analyze_pen_test"),
        short_id_key=env.get("REPORT_SHORT_ID_KEY", "short_id"),
        title_key=env.get("REPORT_TITLE_KEY", "title"),
        priority_key=env.get("REPORT_PRIORITY_KEY", "urgency"),
        runtimes_key=env.get("REPORT_RUNTIMES_KEY", "agent_runtimes"),
        pentest_folder_key=env.get("REPORT_PENTEST_FOLDER_KEY", "pentest_folder"),
        pen_test_created_key=env.get(
            "REPORT_PEN_TEST_CREATED_KEY", "pen_test_already_created"
        ),
    )


def report_path_for_date(date: str, settings: ReportSettings) -> Path:
    """Resolve report path for a date from settings."""
    return settings.report_dir / settings.filename_template.format(date=date)


def parse_analysis_repos(
    env: dict[str, str],
    base_dir: Path | None = None,
) -> list[RepoTarget]:
    """
    Parse configured read-only analysis repos.

    Preferred format (ANALYSIS_REPOS):
      name|branch|/abs/path;name2|main|/abs/path2
    Branch is optional:
      name|/abs/path
    """
    raw = (env.get("ANALYSIS_REPOS") or "").strip()
    root = (base_dir or Path.cwd()).resolve()
    if raw:
        repos: list[RepoTarget] = []
        for idx, chunk in enumerate(raw.split(";"), 1):
            piece = chunk.strip()
            if not piece:
                continue
            parts = [p.strip() for p in piece.split("|")]
            if len(parts) == 2:
                name, path_str = parts
                branch = "main"
            elif len(parts) == 3:
                name, branch, path_str = parts
            else:
                raise ValueError(
                    f"Invalid ANALYSIS_REPOS entry #{idx}: '{piece}'. "
                    "Expected 'name|path' or 'name|branch|path'."
                )

            if not name:
                raise ValueError(f"Invalid ANALYSIS_REPOS entry #{idx}: empty repo name.")
            if not path_str:
                raise ValueError(
                    f"Invalid ANALYSIS_REPOS entry #{idx}: empty repo path."
                )

            repos.append(
                RepoTarget(
                    name=name,
                    branch=(branch or "main"),
                    path=_resolve_path(path_str, root),
                )
            )
        return repos

    # Legacy compatibility.
    repos = []
    for env_var, (default_branch, name) in LEGACY_REPO_CONFIG.items():
        path_str = (env.get(env_var) or "").strip()
        if not path_str:
            continue
        repos.append(
            RepoTarget(
                name=name,
                branch=default_branch,
                path=_resolve_path(path_str, root),
            )
        )
    return repos


def max_validation_retries(env: dict[str, str], default: int = 3) -> int:
    raw = (env.get("MAX_VALIDATION_RETRIES") or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("MAX_VALIDATION_RETRIES must be an integer >= 1") from exc
    if value < 1:
        raise ValueError("MAX_VALIDATION_RETRIES must be >= 1")
    return value
