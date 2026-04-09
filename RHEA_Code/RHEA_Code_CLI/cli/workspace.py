# -*- coding: utf-8 -*-
from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable


class WorkspaceInspector:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _iter_files(self, exts: tuple[str, ...] = (".py", ".txt", ".md")) -> Iterable[Path]:
        skip_dirs = {
            ".git",
            "__pycache__",
            ".pytest_cache",
            ".mypy_cache",
            ".venv",
            "venv",
            "node_modules",
            "dist",
            "build",
        }
        for path in self.root.rglob("*"):
            if not path.is_file():
                continue
            if any(part in skip_dirs for part in path.parts):
                continue
            if path.suffix.lower() in exts:
                yield path

    def inspect_repo(self) -> str:
        py_files = []
        test_files = []
        other_files = []

        for path in self._iter_files():
            rel = path.relative_to(self.root)
            if path.suffix.lower() == ".py":
                py_files.append(rel)
                if "test" in path.name.lower() or "tests" in rel.parts:
                    test_files.append(rel)
            else:
                other_files.append(rel)

        lines = [
            "RHEA Repo Inspection",
            "--------------------",
            f"Root: {self.root}",
            f"Python Files: {len(py_files)}",
            f"Test-like Files: {len(test_files)}",
            f"Other Indexed Files: {len(other_files)}",
        ]

        if py_files:
            lines.append("")
            lines.append("Sample Python Files:")
            for rel in py_files[:15]:
                lines.append(f"  - {rel}")

        if test_files:
            lines.append("")
            lines.append("Sample Test Files:")
            for rel in test_files[:10]:
                lines.append(f"  - {rel}")

        return "\n".join(lines)

    def find_symbol(self, symbol: str) -> str:
        matches: list[str] = []

        for path in self._iter_files(exts=(".py",)):
            try:
                source = path.read_text(encoding="utf-8")
                tree = ast.parse(source)
            except Exception:
                continue

            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    if node.name == symbol:
                        rel = path.relative_to(self.root)
                        kind = type(node).__name__
                        matches.append(f"{rel}:{node.lineno} [{kind}] {symbol}")

        if not matches:
            return f"No symbol definitions found for: {symbol}"

        lines = [f"Symbol Definitions: {symbol}", "-------------------------"]
        lines.extend(f"  - {m}" for m in matches)
        return "\n".join(lines)

    def where_used(self, needle: str) -> str:
        matches: list[str] = []

        for path in self._iter_files(exts=(".py", ".txt", ".md")):
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except Exception:
                continue

            rel = path.relative_to(self.root)
            for idx, line in enumerate(lines, 1):
                if needle in line:
                    snippet = line.strip()
                    if len(snippet) > 140:
                        snippet = snippet[:140] + "..."
                    matches.append(f"{rel}:{idx} | {snippet}")

        if not matches:
            return f"No usages found for: {needle}"

        lines = [f"Usages: {needle}", "----------------"]
        lines.extend(f"  - {m}" for m in matches[:100])
        if len(matches) > 100:
            lines.append(f"  ... {len(matches) - 100} more omitted")
        return "\n".join(lines)

    def find_tests(self, target: str) -> str:
        matches: list[str] = []

        lowered_target = target.lower()
        for path in self._iter_files(exts=(".py",)):
            rel = path.relative_to(self.root)
            rel_text = str(rel).lower()
            if "test" not in rel_text and "tests" not in rel.parts:
                continue

            try:
                text = path.read_text(encoding="utf-8")
            except Exception:
                continue

            if lowered_target in text.lower() or lowered_target in path.name.lower():
                matches.append(str(rel))

        if not matches:
            return f"No test files found for: {target}"

        lines = [f"Related Tests: {target}", "----------------------"]
        lines.extend(f"  - {m}" for m in matches)
        return "\n".join(lines)