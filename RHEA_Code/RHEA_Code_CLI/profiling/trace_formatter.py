# -*- coding: utf-8 -*-
# profiling/trace_formatter.py
# RHEA Code CLI — Human-readable trace formatting

from __future__ import annotations

from RHEA_Code_CLI.profiling.failure_context import TraceContext


def format_trace_context(ctx: TraceContext) -> str:
    lines = [
        "RHEA Stack-To-Trace Profile",
        "===========================",
        f"Timestamp: {ctx.timestamp}",
        f"Command: {ctx.command}",
        f"Role: {ctx.role}",
        f"Glyph: {ctx.glyph}",
        f"Trust Glyph: {ctx.trust_glyph}",
        f"Trust: {ctx.trust:.4f}",
        f"Entropy: {ctx.entropy:.4f}",
        f"CWD: {ctx.cwd}",
        f"Git Mode: {ctx.git_mode}",
        f"Selection Active: {ctx.selection is not None}",
        f"Success: {ctx.success}",
        f"Duration (ms): {ctx.duration_ms:.3f}",
    ]

    if ctx.result_preview:
        lines.extend([
            "",
            "Result Preview",
            "--------------",
            ctx.result_preview,
        ])

    if not ctx.success:
        lines.extend([
            "",
            "Error",
            "-----",
            f"{ctx.error_type}: {ctx.error_message}",
        ])

    if ctx.traceback_text:
        lines.extend([
            "",
            "Traceback",
            "---------",
            ctx.traceback_text.rstrip(),
        ])

    if ctx.frames:
        lines.extend([
            "",
            "Frames",
            "------",
        ])
        for i, frame in enumerate(ctx.frames, 1):
            lines.append(
                f"{i:02d}. {frame.function} | {frame.filename}:{frame.lineno}"
            )
            if frame.code_line:
                lines.append(f"    code: {frame.code_line}")
            if frame.locals_preview:
                lines.append("    locals:")
                for key, value in frame.locals_preview.items():
                    lines.append(f"      - {key} = {value}")

    return "\n".join(lines)