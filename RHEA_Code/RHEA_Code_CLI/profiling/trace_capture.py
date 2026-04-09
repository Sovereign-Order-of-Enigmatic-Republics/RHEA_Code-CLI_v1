# -*- coding: utf-8 -*-
# profiling/trace_capture.py
# RHEA Code CLI — Traceback and frame capture

from __future__ import annotations

import linecache
import traceback
from types import TracebackType
from typing import Any, Optional

from RHEA_Code_CLI.profiling.failure_context import FrameSnapshot


def safe_repr(value: Any, max_len: int = 160) -> str:
    try:
        text = repr(value)
    except Exception:
        text = "<unrepr-able>"
    if len(text) > max_len:
        return text[:max_len] + "...[truncated]"
    return text


def capture_traceback_text(exc: BaseException) -> str:
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))


def capture_frames_from_traceback(
    tb: Optional[TracebackType],
    include_locals: bool = True,
    max_locals_per_frame: int = 12,
) -> list[FrameSnapshot]:
    frames: list[FrameSnapshot] = []

    current = tb
    while current is not None:
        frame = current.tb_frame
        lineno = current.tb_lineno
        filename = frame.f_code.co_filename
        function = frame.f_code.co_name
        code_line = linecache.getline(filename, lineno).rstrip()

        locals_preview: dict[str, str] = {}
        if include_locals:
            for idx, (key, value) in enumerate(frame.f_locals.items()):
                if idx >= max_locals_per_frame:
                    locals_preview["..."] = "[locals truncated]"
                    break
                locals_preview[str(key)] = safe_repr(value)

        frames.append(
            FrameSnapshot(
                filename=filename,
                function=function,
                lineno=lineno,
                code_line=code_line,
                locals_preview=locals_preview,
            )
        )
        current = current.tb_next

    return frames