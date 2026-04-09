# -*- coding: utf-8 -*-
# registry/tool_registry.py
# RHEA Code CLI — Tool registration and dispatch

from __future__ import annotations

from typing import Any, Callable, Dict, Optional


class ToolRegistry:
    def __init__(self) -> None:
        self.tools: Dict[str, Dict[str, Any]] = {}

    def register(self, name: str, func: Callable[..., Any], description: str) -> None:
        self.tools[name] = {"func": func, "desc": description}

    def execute(
        self,
        name: str,
        args: Optional[dict] = None,
        *,
        raise_errors: bool = False,
    ) -> str:
        if name not in self.tools:
            msg = f"Unknown tool: {name}"
            if raise_errors:
                raise KeyError(msg)
            return msg

        try:
            result = self.tools[name]["func"](**(args or {}))
            return result if isinstance(result, str) else str(result)
        except Exception as e:
            if raise_errors:
                raise
            return f"Tool '{name}' error: {e}"

    def get_help_text(self) -> str:
        lines = ["Available tools:"]
        for name in sorted(self.tools):
            lines.append(f"  - {name:<18} : {self.tools[name]['desc']}")
        return "\n".join(lines)