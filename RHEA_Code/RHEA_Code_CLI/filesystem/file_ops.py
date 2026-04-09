# -*- coding: utf-8 -*-
# filesystem/file_ops.py
# RHEA Code CLI — File IO and text helpers

from __future__ import annotations

from pathlib import Path
from typing import Optional


def resolve_file(cwd: Path, file: Optional[str]) -> Optional[Path]:
    if not file:
        return None
    return (cwd / file).resolve()


def read_text_file(target: Path) -> str:
    return target.read_text(encoding="utf-8")


def write_text_file(target: Path, content: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def safe_existing_text(target: Path) -> str:
    if not target.exists():
        return ""
    if not target.is_file():
        raise ValueError(f"Not a file: {target}")
    try:
        return read_text_file(target)
    except UnicodeDecodeError:
        raise ValueError(f"File is not valid UTF-8 text: {target}")


def split_lines_keepends(text: str) -> list[str]:
    return text.splitlines(keepends=True)

def extract_line_range(text: str, start_line: int, end_line: int) -> str:
    lines = split_lines_keepends(text)
    return "".join(lines[start_line - 1:end_line])


def replace_line_range(text: str, start_line: int, end_line: int, replacement: str) -> str:
    lines = split_lines_keepends(text)
    replacement_lines = split_lines_keepends(replacement)
    if replacement and not replacement.endswith(("\n", "\r")):
        replacement_lines = [replacement]
    new_lines = lines[:start_line - 1] + replacement_lines + lines[end_line:]
    return "".join(new_lines)


def ensure_python_file(target: Path) -> Optional[str]:
    if target.suffix.lower() != ".py":
        return f"Not a Python source file: {target}"
    return None