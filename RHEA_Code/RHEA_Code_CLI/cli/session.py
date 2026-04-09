# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import time
from collections import deque
from pathlib import Path
from typing import Any, Optional

from RHEA_Code_CLI.core.engine import (
    LOW_TRUST_TRUNCATE_FLOOR,
    RHEAEngine,
)
from RHEA_Code_CLI.io.pager import open_in_pager
from RHEA_Code_CLI.profiling.stack_profiler import StackToTraceProfiler
from RHEA_Code_CLI.registry.tool_registry import ToolRegistry

from .editing import EditingMixin
from .integration import IntegrationMixin
from .parsing import GlyphParser, extract_args


class RHEACodeCLI(EditingMixin, IntegrationMixin):
    def __init__(self) -> None:
        self.engine = RHEAEngine()
        self.parser = GlyphParser(self.engine)
        self.registry = ToolRegistry()
        self.cwd = Path.cwd()
        self.command_log = deque(maxlen=50)

        self.max_output_chars = 2500
        self.truncation_enabled = True
        self.low_trust_truncate_floor = LOW_TRUST_TRUNCATE_FLOOR

        self.diff_preview_enabled = True
        self.show_future_diffs = True

        self.selection: Optional[dict[str, Any]] = None
        self.current_task = None
        self.git_mode = "manual"

        self.profiling_enabled = True
        self.profiling_auto_save = True
        self.last_trace_report = ""
        self.profiler = StackToTraceProfiler(self.cwd / "logs" / "stack_traces")

        self._configure_console_output()
        self._register_tools()
        self._banner()

    # ---------------------- Console / Output ----------------------

    def _configure_console_output(self) -> None:
        try:
            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            if hasattr(sys.stderr, "reconfigure"):
                sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    def _safe_text(self, value: Any) -> str:
        text = str(value)
        try:
            text.encode(sys.stdout.encoding or "utf-8", errors="strict")
            return text
        except Exception:
            return text.encode("utf-8", errors="replace").decode("utf-8", errors="replace")

    def _out(self, *parts: Any, sep: str = " ", end: str = "\n") -> None:
        text = sep.join(self._safe_text(part) for part in parts)
        try:
            print(text, end=end)
        except UnicodeEncodeError:
            fallback = text.encode("ascii", errors="replace").decode("ascii", errors="replace")
            print(fallback, end=end)

    def _banner(self) -> None:
        self._out("=" * 88)
        self._out("RHEA Code CLI v4.2 Split Architecture initialized — Full Entropy-Trust Control Active")
        self._out(f"Working Directory: {self.cwd}")
        self._out(f"Truncation: {'ON' if self.truncation_enabled else 'OFF'} | Limit: {self.max_output_chars}")
        self._out(f"Diff Preview: {'ON' if self.diff_preview_enabled else 'OFF'}")
        self._out("Type 'help' for commands. Type 'exit' to quit.")
        self._out("=" * 88)
        self._out("")

    def _format_output(self, text: str, force_full: bool = False) -> str:
        if force_full:
            return text

        if self.engine.trust < self.low_trust_truncate_floor:
            if len(text) > self.max_output_chars:
                return (
                    text[:self.max_output_chars]
                    + f"\n...[truncated at {self.max_output_chars} chars due to low trust safeguard]..."
                )
            return text

        if not self.truncation_enabled:
            return text

        if len(text) > self.max_output_chars:
            return text[:self.max_output_chars] + f"\n...[truncated at {self.max_output_chars} chars]..."
        return text

    def _open_in_pager(self, text: str) -> str:
        return open_in_pager(text)

    # ---------------------- Input Hardening ----------------------

    def _contains_control_chars(self, value: str) -> bool:
        return any(ch in value for ch in ("\x00", "\r", "\n"))

    def _validate_user_token(self, value: Optional[str], field_name: str = "value") -> Optional[str]:
        if value is None:
            return None
        if self._contains_control_chars(value):
            raise ValueError(f"Unsafe {field_name}: control characters are not allowed")
        return value

    def _validate_shell_command(self, cmd: Optional[str]) -> Optional[str]:
        if cmd is None:
            return None
        if "\x00" in cmd:
            raise ValueError("Unsafe shell command: null byte is not allowed")
        return cmd

    # ---------------------- Main Loop ----------------------

    def run(self) -> None:
        while True:
            try:
                cmd = input("RHEA> ").strip()

                if cmd.lower() in {"exit", "quit"}:
                    self._out("RHEA session ended.")
                    break

                if not cmd:
                    continue

                self.command_log.append(cmd)

                glyph_data = self.parser.parse(cmd)
                self._out(
                    f"[{glyph_data['trust_glyph']}] "
                    f"Trust: {glyph_data['trust']:.4f} | "
                    f"Entropy: {glyph_data['entropy']:.4f} | "
                    f"Role: {glyph_data['role']}"
                )

                start = time.perf_counter()
                result = ""

                try:
                    args = extract_args(glyph_data["role"], cmd)
                    result = self.registry.execute(glyph_data["role"], args, raise_errors=True)

                    force_full = glyph_data["role"] in {"help", "show_task", "task"}

                    if glyph_data["role"] not in {
                        "read",
                        "read_line",
                        "read_lines",
                        "read_def",
                        "read_class",
                        "read_dataclass",
                        "read_method",
                        "read_selection",
                    }:
                        result = self._format_output(result, force_full=force_full)

                    duration_ms = (time.perf_counter() - start) * 1000.0

                    if self.profiling_enabled:
                        ctx = self.profiler.build_context(
                            command=cmd,
                            glyph_data=glyph_data,
                            cwd=str(self.cwd),
                            git_mode=self.git_mode,
                            selection=self.selection,
                            success=True,
                            duration_ms=duration_ms,
                            result_preview=result,
                            exc=None,
                        )
                        self.last_trace_report = self.profiler.format_trace(ctx)
                        if self.profiling_auto_save:
                            self.profiler.save_trace(ctx)

                    self._out(result)
                    self._out("")

                except Exception as e:
                    duration_ms = (time.perf_counter() - start) * 1000.0

                    if self.profiling_enabled:
                        ctx = self.profiler.build_context(
                            command=cmd,
                            glyph_data=glyph_data,
                            cwd=str(self.cwd),
                            git_mode=self.git_mode,
                            selection=self.selection,
                            success=False,
                            duration_ms=duration_ms,
                            result_preview="",
                            exc=e,
                        )
                        self.last_trace_report = self.profiler.format_trace(ctx)
                        if self.profiling_auto_save:
                            self.profiler.save_trace(ctx)

                        self._out(self._format_output(self.last_trace_report, force_full=False))
                        self._out("")
                    else:
                        self._out(f"Error: {e}")
                        self._out("")

            except KeyboardInterrupt:
                self._out("\nSession terminated.")
                break
            except EOFError:
                self._out("\nSession terminated.")
                break