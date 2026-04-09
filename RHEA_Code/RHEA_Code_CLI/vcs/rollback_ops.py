# -*- coding: utf-8 -*-
# vcs/rollback_ops.py
# RHEA Code CLI — Rollback helpers

from __future__ import annotations

from pathlib import Path
from typing import Optional

from RHEA_Code_CLI.vcs.git_ops import run_git_command


def rollback_show(cwd: Path, limit: int = 20) -> str:
    limit = max(1, int(limit))
    return run_git_command(cwd, f"log --oneline -n {limit}")


def rollback_last_preview(cwd: Path) -> str:
    return run_git_command(cwd, "show --stat --oneline HEAD~1..HEAD")


def rollback_file_preview(cwd: Path, file: str) -> str:
    return run_git_command(cwd, f'diff HEAD~1 HEAD -- "{file}"')


def rollback_to_commit_preview(cwd: Path, commit: str) -> str:
    return run_git_command(cwd, f"show --stat --oneline {commit}")


def rollback_file_to_head(cwd: Path, file: str) -> str:
    return run_git_command(cwd, f'checkout HEAD -- "{file}"')


def rollback_file_to_commit(cwd: Path, commit: str, file: str) -> str:
    return run_git_command(cwd, f'checkout {commit} -- "{file}"')


def rollback_last_hard(cwd: Path) -> str:
    return run_git_command(cwd, "reset --hard HEAD~1")


def rollback_to_commit_hard(cwd: Path, commit: str) -> str:
    return run_git_command(cwd, f"reset --hard {commit}")