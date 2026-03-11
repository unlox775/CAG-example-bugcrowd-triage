#!/usr/bin/env python3
"""
Journal helper for triage bot and secretary — news-minimalist-style output.

Two journal types (same timestamp, paired):
  - *_agent.txt   — full Codex/agent output (prompts, transcript)
  - *_commands.txt — commands we run (validator, update_blocker_json, etc.) with args and output

Format for each block:
  COMMAND:
  ════════════════════════════════════════════════════════════════════
  <full command>
  
  OUTPUT:
  ════════════════════════════════════════════════════════════════════
  
  <captured stdout/stderr>
  
  ════════════════════════════════════════════════════════════════════ END OUTPUT ════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

SEP = "════════════════════════════════════════════════════════════════"
BLANK_LINES = 5


def journals_dir(base: Path) -> Path:
    """Return journals directory; create if needed."""
    d = base / "journals"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H%M%S")


def run_header(command: str) -> str:
    return f"""COMMAND:
{SEP}
{command}

OUTPUT:
{SEP}

"""


def run_footer() -> str:
    blank = "\n" * BLANK_LINES
    return f"""

{SEP} END OUTPUT {SEP}
{blank}
"""


def create_run_journals(base: Path, ts: str | None = None) -> tuple[Path, Path]:
    """
    Create paired agent and commands journal files.
    Returns (agent_path, commands_path) with same timestamp.
    """
    ts = ts or _timestamp()
    jdir = journals_dir(base)
    agent_path = jdir / f"{ts}_agent.txt"
    commands_path = jdir / f"{ts}_commands.txt"
    agent_path.write_text("", encoding="utf-8")
    commands_path.write_text("", encoding="utf-8")
    return agent_path, commands_path


# --- Triage-specific: per-issue folder with agent + commands per issue ---

def _flatten_title(title: str, max_len: int = 80) -> str:
    """Convert title to lowercase snake_case, safe for filenames."""
    if not title:
        return "untitled"
    s = title.lower()
    s = "".join(c if c.isalnum() or c in " _-" else " " for c in s)
    s = "_".join(s.split())
    while "__" in s:
        s = s.replace("__", "_")
    s = s.strip("_")
    return s[:max_len] if len(s) > max_len else s


def create_triage_journal_folder(base: Path, ts: str | None = None) -> Path:
    """
    Create a folder for this triage run: journals/YYYY-MM-DD_HHMMSS/
    Returns the folder path. Per-issue files go inside.
    """
    ts = ts or _timestamp()
    jdir = journals_dir(base)
    folder = jdir / ts
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _progress_path(folder: Path) -> Path:
    return folder / "00_progress.txt"


def init_triage_progress(
    folder: Path,
    base_cmd: str,
    items: list[tuple[dict, int]],
    revalidate_output: str | None = None,
) -> None:
    """
    Write 00_progress.txt with the run header, optional revalidate section, and list of items.
    items: list of (entry, idx) from analyze_pen_test.
    revalidate_output: stdout from update_blocker_json revalidate (OK/FAIL lines).
    """
    path = _progress_path(folder)
    lines = [f"Triage run: {base_cmd}", ""]

    if revalidate_output and revalidate_output.strip():
        lines.append("Revalidating existing validated runtimes:")
        for raw in revalidate_output.strip().splitlines():
            line = raw.strip()
            if not line:
                continue
            lines.append(f"  {line}")
        fails = [l for l in revalidate_output.splitlines() if l.strip().startswith("FAIL:")]
        if fails:
            lines.append(f"  → {len(fails)} runtime(s) demoted to error (stricter validation)")
        lines.append("")

    lines.append(f"Items to process: {len(items)}")
    lines.append("")
    for seq, (entry, idx) in enumerate(items, 1):
        short_id = entry.get("short_id", "?")
        title = entry.get("title", "untitled")
        lines.append(f"  {seq:02d} {short_id} - {title}")
    lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def append_triage_progress(folder: Path, line: str) -> None:
    """Append a timestamped line to 00_progress.txt."""
    from datetime import datetime
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    path = _progress_path(folder)
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{ts} - {line}\n")
        f.flush()


def triage_issue_paths(folder: Path, seq: int, short_id: str, title: str) -> tuple[Path, Path]:
    """
    Return (agent_path, commands_path) for this issue.
    seq: 1-based index (01, 02, 03...)
    short_id: 8-char hex (e.g. e35ad693)
    title: used for flattened filename suffix
    """
    flat = _flatten_title(title)
    prefix = f"{seq:02d}_{short_id}_{flat}"
    return folder / f"{prefix}_agent.txt", folder / f"{prefix}_commands.txt"


def append_triage_agent_block(path: Path, command: str, prompt: str, output: str) -> None:
    """
    Append COMMAND + PROMPT + OUTPUT block to triage agent journal.
    Agent file shows: make command, full prompt to Codex, then Codex output.
    """
    content = f"""COMMAND:
{SEP}
{command}

PROMPT:
{SEP}
{prompt}

OUTPUT:
{SEP}

{output}
{run_footer()}"""
    with open(path, "a", encoding="utf-8") as f:
        f.write(content)
        f.flush()


def append_triage_command_block(path: Path, command: str, output: str) -> None:
    """Append COMMAND + OUTPUT block to triage commands journal."""
    append_block(path, command, output)


def append_block(path: Path, command: str, output: str) -> None:
    """Append a COMMAND + OUTPUT + END block to a journal file."""
    content = run_header(command) + output + run_footer()
    with open(path, "a", encoding="utf-8") as f:
        f.write(content)
        f.flush()


def run_command_logged(
    commands_path: Path,
    cmd: list[str],
    cwd: str | Path,
    env: dict | None = None,
) -> subprocess.CompletedProcess:
    """
    Run a command, capture output, append to commands journal, return result.
    Output is also printed (pass-through) so user sees it.
    """
    r = subprocess.run(
        cmd,
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
    )
    cmd_str = " ".join(c for c in cmd)
    output = (r.stdout or "") + (r.stderr or "")
    append_block(commands_path, cmd_str, output)
    if r.stdout:
        print(r.stdout, end="", flush=True)
    if r.stderr:
        print(r.stderr, end="", file=sys.stderr, flush=True)
    return r


def write_journal(base: Path, command: str, output: str, suffix: str = "agent") -> Path:
    """
    Write a single journal entry (legacy / convenience).
    suffix: "agent" or "commands"
    """
    ts = _timestamp()
    jdir = journals_dir(base)
    path = jdir / f"{ts}_{suffix}.txt"
    content = run_header(command) + output + run_footer()
    path.write_text(content, encoding="utf-8")
    return path


def main() -> int:
    """CLI for journal operations from Makefile/scripts."""
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="Base dir (secretary or triage_bot)")
    sub = ap.add_subparsers(dest="mode", required=True)

    # append-agent: append agent output from file
    p_agent = sub.add_parser("append-agent")
    p_agent.add_argument("--ts", required=True, help="Timestamp (YYYY-MM-DD_HHMMSS)")
    p_agent.add_argument("--cmd", required=True, help="Full command that produced the output")
    p_agent.add_argument("--output-file", required=True, help="Path to file containing output")

    # append-commands: append a command block (run command and capture, or provide output)
    p_cmd = sub.add_parser("append-commands")
    p_cmd.add_argument("--ts", required=True, help="Timestamp")
    p_cmd.add_argument("--cmd", required=True, help="Full command string (including args)")
    p_cmd.add_argument("--output", default=None, help="Output text (if not running)")
    p_cmd.add_argument("--output-file", default=None, help="Or path to file with output")
    p_cmd.add_argument("--run", action="store_true", help="Run the command and capture output")
    p_cmd.add_argument("cmd_args", nargs="*", help="If --run: command and args to run")

    # create: create both journal files, print paths
    p_create = sub.add_parser("create")
    p_create.add_argument("--ts", default=None, help="Timestamp (default: now)")

    args = ap.parse_args()
    base = Path(args.dir).resolve()
    jdir = journals_dir(base)

    if args.mode == "append-agent":
        path = jdir / f"{args.ts}_agent.txt"
        out_file = Path(args.output_file).resolve()
        output = out_file.read_text(encoding="utf-8", errors="replace") if out_file.exists() else "(no output file)"
        append_block(path, args.cmd, output)
        print(f"Appended to agent journal: {path}", flush=True)

    elif args.mode == "append-commands":
        path = jdir / f"{args.ts}_commands.txt"
        if args.run:
            if not args.cmd_args:
                print("append-commands --run requires cmd_args", file=sys.stderr)
                return 1
            r = subprocess.run(args.cmd_args, capture_output=True, text=True, cwd=base.parent.parent)
            output = (r.stdout or "") + (r.stderr or "")
            cmd_str = " ".join(args.cmd_args)
            append_block(path, cmd_str, output)
            if r.stdout:
                print(r.stdout, end="", flush=True)
            if r.stderr:
                print(r.stderr, end="", file=sys.stderr, flush=True)
            print(f"Appended to commands journal: {path}", flush=True)
            return r.returncode
        else:
            output = args.output or ""
            if args.output_file:
                out_file = Path(args.output_file).resolve()
                output = out_file.read_text(encoding="utf-8", errors="replace") if out_file.exists() else output
            append_block(path, args.cmd, output)
            print(f"Appended to commands journal: {path}", flush=True)

    elif args.mode == "create":
        ts = args.ts or _timestamp()
        agent_path, commands_path = create_run_journals(base, ts)
        print(f"agent={agent_path}", flush=True)
        print(f"commands={commands_path}", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
