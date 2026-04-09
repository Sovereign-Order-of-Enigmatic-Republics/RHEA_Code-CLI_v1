# -*- coding: utf-8 -*-
# vcs/git_history.py
# RHEA Code CLI — Git history / checkpoint helpers

from __future__ import annotations

from pathlib import Path
from typing import Optional

from RHEA_Code_CLI.vcs.git_ops import git_log, git_file_log


def build_checkpoint_message(
    op: str,
    file: Optional[str] = None,
    target: Optional[str] = None,
    lines: Optional[str] = None,
    note: Optional[str] = None,
) -> str:
    parts = ["RHEA_CHECKPOINT"]
    parts.append(f"op={op}")

    if file:
        parts.append(f"file={file}")
    if target:
        parts.append(f"target={target}")
    if lines:
        parts.append(f"lines={lines}")
    if note:
        parts.append(f"note={note}")

    return " | ".join(parts)


def get_checkpoint_log(cwd: Path, limit: int = 20) -> str:
    return git_log(cwd, limit=limit)


def get_file_history(cwd: Path, file: str, limit: int = 20) -> str:
    return git_file_log(cwd, file=file, limit=limit)