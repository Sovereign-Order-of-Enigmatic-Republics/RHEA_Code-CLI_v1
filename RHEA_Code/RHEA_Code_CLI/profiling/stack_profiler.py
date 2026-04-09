# -*- coding: utf-8 -*-
# profiling/stack_profiler.py
# RHEA Code CLI — Execution profiler controller

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from RHEA_Code_CLI.profiling.failure_context import TraceContext
from RHEA_Code_CLI.profiling.trace_capture import (
    capture_frames_from_traceback,
    capture_traceback_text,
)
from RHEA_Code_CLI.profiling.trace_formatter import format_trace_context


class StackToTraceProfiler:
    def __init__(self, log_dir: Path) -> None:
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def build_context(
        self,
        *,
        command: str,
        glyph_data: dict[str, Any],
        cwd: str,
        git_mode: str,
        selection: Optional[dict[str, Any]],
        success: bool,
        duration_ms: float,
        result_preview: str = "",
        exc: Optional[BaseException] = None,
    ) -> TraceContext:
        traceback_text = ""
        frames = []
        error_type = ""
        error_message = ""

        if exc is not None:
            traceback_text = capture_traceback_text(exc)
            frames = capture_frames_from_traceback(exc.__traceback__)
            error_type = type(exc).__name__
            error_message = str(exc)

        return TraceContext(
            timestamp=datetime.now().isoformat(timespec="seconds"),
            command=command,
            role=str(glyph_data.get("role", "")),
            glyph=str(glyph_data.get("glyph", "")),
            trust_glyph=str(glyph_data.get("trust_glyph", "")),
            trust=float(glyph_data.get("trust", 0.0)),
            entropy=float(glyph_data.get("entropy", 0.0)),
            cwd=cwd,
            git_mode=git_mode,
            selection=selection,
            success=success,
            duration_ms=duration_ms,
            result_preview=result_preview[:500],
            error_type=error_type,
            error_message=error_message,
            traceback_text=traceback_text,
            frames=frames,
        )

    def save_trace(self, ctx: TraceContext) -> Path:
        ts = ctx.timestamp.replace(":", "-")
        status = "ok" if ctx.success else "fail"
        path = self.log_dir / f"trace_{status}_{ts}.jsonl"

        payload = {
            "timestamp": ctx.timestamp,
            "command": ctx.command,
            "role": ctx.role,
            "glyph": ctx.glyph,
            "trust_glyph": ctx.trust_glyph,
            "trust": ctx.trust,
            "entropy": ctx.entropy,
            "cwd": ctx.cwd,
            "git_mode": ctx.git_mode,
            "selection": ctx.selection,
            "success": ctx.success,
            "duration_ms": ctx.duration_ms,
            "result_preview": ctx.result_preview,
            "error_type": ctx.error_type,
            "error_message": ctx.error_message,
            "traceback_text": ctx.traceback_text,
            "frames": [
                {
                    "filename": f.filename,
                    "function": f.function,
                    "lineno": f.lineno,
                    "code_line": f.code_line,
                    "locals_preview": f.locals_preview,
                }
                for f in ctx.frames
            ],
        }

        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")

        return path

    def format_trace(self, ctx: TraceContext) -> str:
        return format_trace_context(ctx)