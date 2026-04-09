# -*- coding: utf-8 -*-
# vcs/git_ops.py
# RHEA Code CLI — Core Git operations

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional


def find_git_executable() -> Optional[str]:
    git_exe = shutil.which("git")
    if git_exe:
        return git_exe

    candidates = [
        r"C:\Program Files\Git\cmd\git.exe",
        r"C:\Program Files\Git\bin\git.exe",
        r"C:\Program Files (x86)\Git\cmd\git.exe",
        r"C:\Program Files (x86)\Git\bin\git.exe",
        os.path.expandvars(r"%LocalAppData%\Programs\Git\cmd\git.exe"),
        os.path.expandvars(r"%LocalAppData%\Programs\Git\bin\git.exe"),
    ]

    for path in candidates:
        if os.path.exists(path):
            return path

    return None


def run_git_command(cwd: Path, git_args: str) -> str:
    git_exe = find_git_executable()
    if not git_exe:
        return (
            "Git is not installed on this system.\n"
            "Install Git to enable git commands in RHEA Code CLI."
        )

    cmd = f'"{git_exe}" {git_args}'.strip()
    completed = subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        text=True,
        cwd=str(cwd),
    )

    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()

    parts = [f"[exit={completed.returncode}]"]
    if stdout:
        parts.append("--- stdout ---")
        parts.append(stdout)
    if stderr:
        parts.append("--- stderr ---")
        parts.append(stderr)
    return "\n".join(parts)


def is_git_available() -> bool:
    return find_git_executable() is not None


def is_git_repo(cwd: Path) -> bool:
    result = run_git_command(cwd, "rev-parse --is-inside-work-tree")
    return "true" in result.lower()


def get_repo_root(cwd: Path) -> Optional[Path]:
    result = run_git_command(cwd, "rev-parse --show-toplevel")
    if "[exit=0]" not in result:
        return None

    lines = result.splitlines()
    capture = False
    for line in lines:
        if line.strip() == "--- stdout ---":
            capture = True
            continue
        if capture and line.strip():
            return Path(line.strip())
    return None


def get_current_branch(cwd: Path) -> Optional[str]:
    result = run_git_command(cwd, "branch --show-current")
    if "[exit=0]" not in result:
        return None

    lines = result.splitlines()
    capture = False
    for line in lines:
        if line.strip() == "--- stdout ---":
            capture = True
            continue
        if capture:
            return line.strip()
    return None


def working_tree_dirty(cwd: Path) -> bool:
    result = run_git_command(cwd, "status --porcelain")
    if "[exit=0]" not in result:
        return False
    return "--- stdout ---" in result and any(
        line.strip() and line.strip() != "--- stdout ---"
        for line in result.splitlines()
    )


def git_status(cwd: Path) -> str:
    return run_git_command(cwd, "status")


def git_diff(cwd: Path, file: Optional[str] = None, cached: bool = False) -> str:
    parts = ["diff"]
    if cached:
        parts.append("--cached")
    if file:
        parts.extend(["--", file])
    return run_git_command(cwd, " ".join(parts))


def git_log(cwd: Path, limit: int = 10) -> str:
    limit = max(1, int(limit))
    return run_git_command(cwd, f"log --oneline -n {limit}")


def git_file_log(cwd: Path, file: str, limit: int = 10) -> str:
    limit = max(1, int(limit))
    return run_git_command(cwd, f'log --oneline -n {limit} -- "{file}"')


def git_stage_file(cwd: Path, file: str) -> str:
    return run_git_command(cwd, f'add "{file}"')


def git_unstage_file(cwd: Path, file: str) -> str:
    return run_git_command(cwd, f'reset HEAD -- "{file}"')


def git_commit(cwd: Path, message: str) -> str:
    safe_msg = message.replace('"', '\\"')
    return run_git_command(cwd, f'commit -m "{safe_msg}"')