# -*- coding: utf-8 -*-
# profiling/failure_context.py
# RHEA Code CLI — Structured trace context models

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class FrameSnapshot:
    filename: str
    function: str
    lineno: int
    code_line: str = ""
    locals_preview: dict[str, str] = field(default_factory=dict)


@dataclass
class TraceContext:
    timestamp: str
    command: str
    role: str
    glyph: str
    trust_glyph: str
    trust: float
    entropy: float
    cwd: str
    git_mode: str
    selection: Optional[dict[str, Any]]
    success: bool
    duration_ms: float
    result_preview: str = ""
    error_type: str = ""
    error_message: str = ""
    traceback_text: str = ""
    frames: list[FrameSnapshot] = field(default_factory=list)