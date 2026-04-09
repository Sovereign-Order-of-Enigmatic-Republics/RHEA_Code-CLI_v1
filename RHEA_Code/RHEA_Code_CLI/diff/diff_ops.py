# -*- coding: utf-8 -*-
# diff/diff_ops.py
# RHEA Code CLI — Unified diff generation

from __future__ import annotations

import difflib
from pathlib import Path


def build_unified_diff(target: Path, old_text: str, new_text: str) -> str:
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)
    diff_lines = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"{target.name} (before)",
            tofile=f"{target.name} (after)",
            lineterm="",
        )
    )
    return "\n".join(diff_lines) if diff_lines else "[no changes]"