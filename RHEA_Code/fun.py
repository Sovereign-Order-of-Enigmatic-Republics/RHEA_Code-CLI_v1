# -*- coding: utf-8 -*-
# RHEA_Code-CLI.py
# RHEA Code CLI – Full Native RHEA-UCM Agentic Coding Assistant (v4.1 Phase 1)

from __future__ import annotations

import ast
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from collections import deque
from typing import Any, Dict, Optional

from RHEA_Code_CLI.core.engine import (
    LOW_TRUST_TRUNCATE_FLOOR,
    RHEAEngine,
)
from RHEA_Code_CLI.registry.tool_registry import ToolRegistry
from RHEA_Code_CLI.io.pager import open_in_pager
from RHEA_Code_CLI.filesystem.file_ops import (
    ensure_python_file,
    extract_line_range,
    read_text_file,
    replace_line_range,
    resolve_file,
    safe_existing_text,
    split_lines_keepends,
    write_text_file,
)
from RHEA_Code_CLI.diff.diff_ops import build_unified_diff

from RHEA_Code_CLI.vcs.git_ops import (
    git_diff,
    git_log,
    git_stage_file,
    git_status,
    git_unstage_file,
    git_commit,
    is_git_available,
    is_git_repo,
    get_current_branch,
    working_tree_dirty,
    run_git_command,
)
from RHEA_Code_CLI.vcs.git_history import (
    build_checkpoint_message,
    get_checkpoint_log,
    get_file_history,
)
from RHEA_Code_CLI.vcs.rollback_ops import (
    rollback_show,
    rollback_last_preview,
    rollback_file_preview,
    rollback_to_commit_preview,
    rollback_file_to_head,
    rollback_file_to_commit,
    rollback_last_hard,
    rollback_to_commit_hard,
)
from RHEA_Code_CLI.vcs.git_policy import (
    normalize_git_mode,
    should_checkpoint_before_edit,
    allow_auto_commit,
)

from RHEA_Code_CLI.profiling.stack_profiler import StackToTraceProfiler

# ====================== CODE OBJECT INDEX ======================

@dataclass
class CodeObject:
    kind: str
    name: str
    start_line: int
    end_line: int
    parent: Optional[str] = None


class PythonCodeIndexer(ast.NodeVisitor):
    def __init__(self) -> None:
        self.objects: list[CodeObject] = []
        self.class_stack: list[str] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        kind = "dataclass" if self._is_dataclass(node) else "class"
        self.objects.append(
            CodeObject(
                kind=kind,
                name=node.name,
                start_line=node.lineno,
                end_line=getattr(node, "end_lineno", node.lineno),
                parent=self.class_stack[-1] if self.class_stack else None,
            )
        )

        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.objects.append(
            CodeObject(
                kind="method" if self.class_stack else "def",
                name=node.name,
                start_line=node.lineno,
                end_line=getattr(node, "end_lineno", node.lineno),
                parent=self.class_stack[-1] if self.class_stack else None,
            )
        )
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.objects.append(
            CodeObject(
                kind="async_method" if self.class_stack else "async_def",
                name=node.name,
                start_line=node.lineno,
                end_line=getattr(node, "end_lineno", node.lineno),
                parent=self.class_stack[-1] if self.class_stack else None,
            )
        )
        self.generic_visit(node)

    def _is_dataclass(self, node: ast.ClassDef) -> bool:
        for dec in node.decorator_list:
            if isinstance(dec, ast.Name) and dec.id == "dataclass":
                return True
            if isinstance(dec, ast.Attribute) and dec.attr == "dataclass":
                return True
            if isinstance(dec, ast.Call):
                fn = dec.func
                if isinstance(fn, ast.Name) and fn.id == "dataclass":
                    return True
                if isinstance(fn, ast.Attribute) and fn.attr == "dataclass":
                    return True
        return False


# ====================== GLYPH PARSER ======================
class GlyphParser:
    def __init__(self, engine: RHEAEngine) -> None:
        self.engine = engine

    def parse(self, text: str) -> Dict[str, Any]:
        entropy = self.engine.compute_entropy(text)
        trust_glyph = self.engine.update_trust(entropy)

        cmd = text.lower().strip()
        role = "help"

        if (
            cmd in {"full output", "no truncate", "disable truncation", "truncate off"}
            or "full output" in cmd
            or "no truncate" in cmd
            or "disable truncation" in cmd
            or "truncate off" in cmd
        ):
            role = "no_truncate"
        elif cmd in {"truncate on", "enable truncation"} or "truncate on" in cmd or "enable truncation" in cmd:
            role = "truncate_on"
        elif cmd.startswith("set limit ") or cmd.startswith("truncate limit "):
            role = "set_limit"
        elif cmd in {"diff on", "preview on", "confirm on"}:
            role = "diff_on"
        elif cmd in {"diff off", "preview off", "confirm off"}:
            role = "diff_off"
        elif cmd.startswith("show selection"):
            role = "show_selection"
        elif cmd.startswith("read selection"):
            role = "read_selection"
        elif cmd.startswith("replace selection"):
            role = "replace_selection"
        elif cmd.startswith("select "):
            role = "select_object"
        elif cmd.startswith("vcs status"):
            role = "vcs_status"
        elif cmd.startswith("vcs diff"):
            role = "vcs_diff"
        elif cmd.startswith("vcs log"):
            role = "vcs_log"
        elif cmd.startswith("vcs filelog"):
            role = "vcs_filelog"
        elif cmd.startswith("checkpoint "):
            role = "checkpoint"
        elif cmd == "checkpoint":
            role = "checkpoint"
        elif cmd.startswith("rollback show"):
            role = "rollback_show"
        elif cmd.startswith("rollback last"):
            role = "rollback_last"
        elif cmd.startswith("rollback file"):
            role = "rollback_file"
        elif cmd.startswith("rollback to"):
            role = "rollback_to"
        elif cmd == "git mode":
            role = "git_mode"
        elif cmd.startswith("git mode "):
            role = "git_mode"
        elif cmd.startswith("list defs ") or cmd == "list defs":
            role = "list_defs"
        elif cmd.startswith("list classes ") or cmd == "list classes":
            role = "list_classes"
        elif cmd.startswith("list dataclasses ") or cmd == "list dataclasses":
            role = "list_dataclasses"
        elif cmd.startswith("list methods ") or cmd == "list methods":
            role = "list_methods"
        elif cmd.startswith("list async defs ") or cmd == "list async defs":
            role = "list_async_defs"
        elif cmd.startswith("list lines ") or cmd == "list lines":
            role = "list_lines"
        elif cmd.startswith("read line "):
            role = "read_line"
        elif cmd.startswith("read lines "):
            role = "read_lines"
        elif cmd.startswith("read def "):
            role = "read_def"
        elif cmd.startswith("read class "):
            role = "read_class"
        elif cmd.startswith("read dataclass "):
            role = "read_dataclass"
        elif cmd.startswith("read method "):
            role = "read_method"
        elif cmd.startswith("replace def "):
            role = "replace_def"
        elif cmd.startswith("replace class "):
            role = "replace_class"
        elif cmd.startswith("replace dataclass "):
            role = "replace_dataclass"
        elif cmd.startswith("replace method "):
            role = "replace_method"
        elif cmd.startswith("replace line "):
            role = "replace_line"
        elif cmd.startswith("replace lines "):
            role = "replace_lines"
        elif cmd.startswith("replace char "):
            role = "replace_char"
        elif cmd.startswith("insert char "):
            role = "insert_char"
        elif cmd.startswith("delete char "):
            role = "delete_char"
        elif cmd.startswith("replace word "):
            role = "replace_word"
        elif cmd.startswith("replace in "):
            role = "replace"
        elif cmd.startswith("insert after "):
            role = "insert_after"
        elif cmd.startswith("insert before "):
            role = "insert_before"
        elif cmd.startswith("prepend "):
            role = "prepend"
        elif cmd.startswith("pastefile "):
            role = "pastefile"
        elif cmd.startswith("pasteappend "):
            role = "pasteappend"
        elif any(w in cmd for w in ["list", "ls", "files", "dir", "directory"]):
            role = "list"
        elif any(w in cmd for w in ["read", "cat", "show", "view", "open"]):
            role = "read"
        elif any(w in cmd for w in ["edit", "write", "change", "update", "append", "create"]):
            role = "edit"
        elif any(w in cmd for w in ["run ", "execute", "test", "shell ", "cmd ", "python "]):
            role = "run"
        elif "git" in cmd:
            role = "git"
        elif cmd == "trace status":
            role = "trace_status"
        elif cmd == "trace last":
            role = "trace_last"
        elif cmd == "trace on":
            role = "trace_on"
        elif cmd == "trace off":
            role = "trace_off"
        elif cmd in {"help", "?", "commands"}:
             role = "help"
        elif cmd in {"pwd", "where am i", "current dir"}:
            role = "pwd"
        elif cmd in {"trust", "status", "rhea status"}:
            role = "status"
        elif cmd in {"history", "entropy history"}:
            role = "history"

        return {
            "glyph": "Ψ",
            "role": role,
            "entropy": round(entropy, 4),
            "trust_glyph": trust_glyph,
            "trust": round(self.engine.trust, 4),
            "original_cmd": text,
        }


# ====================== MAIN CLI ======================
class RHEACodeCLI:
    def __init__(self) -> None:
        self.engine = RHEAEngine()
        self.parser = GlyphParser(self.engine)
        self.registry = ToolRegistry()
        self.cwd = Path.cwd()
        self.command_log = deque(maxlen=50)

        self.max_output_chars = 2500
        self.truncation_enabled = True

        self.diff_preview_enabled = True
        self.show_future_diffs = True

        self.selection: Optional[dict[str, Any]] = None
        self.git_mode = "manual"
        self.profiling_enabled = True
        self.profiling_auto_save = True
        self.last_trace_report = ""
        self.profiler = StackToTraceProfiler(self.cwd / "logs" / "stack_traces")

        self._register_tools()
        self._banner()

    def _banner(self) -> None:
        print("=" * 88)
        print("RHEA Code CLI v4.1 Phase 1 initialized — Full Entropy-Trust Control Active")
        print(f"Working Directory: {self.cwd}")
        print(f"Truncation: {'ON' if self.truncation_enabled else 'OFF'} | Limit: {self.max_output_chars}")
        print(f"Diff Preview: {'ON' if self.diff_preview_enabled else 'OFF'}")
        print("Type 'help' for commands. Type 'exit' to quit.")
        print("=" * 88)
        print()

    def _register_tools(self) -> None:
        self.registry.register("list", self.tool_list, "List current directory contents")
        self.registry.register("read", self.tool_read, "Read a file (supports 'pager' and 'full')")
        self.registry.register("edit", self.tool_edit, "Write, append, or paste content to a file")

        self.registry.register("replace", self.tool_replace, "Replace text in a file")
        self.registry.register("replace_line", self.tool_replace_line, "Replace one line")
        self.registry.register("replace_lines", self.tool_replace_lines, "Replace line range")
        self.registry.register("replace_char", self.tool_replace_char, "Replace one character")
        self.registry.register("insert_char", self.tool_insert_char, "Insert one character")
        self.registry.register("delete_char", self.tool_delete_char, "Delete one character")
        self.registry.register("replace_word", self.tool_replace_word, "Replace word(s)")

        self.registry.register("insert_after", self.tool_insert_after, "Insert text after anchor")
        self.registry.register("insert_before", self.tool_insert_before, "Insert text before anchor")
        self.registry.register("prepend", self.tool_prepend, "Prepend text to a file")

        self.registry.register("pastefile", self.tool_pastefile, "Paste multiline file content into a file")
        self.registry.register("pasteappend", self.tool_pasteappend, "Paste multiline content and append to a file")

        self.registry.register("list_defs", self.tool_list_defs, "List top-level defs in Python file")
        self.registry.register("list_classes", self.tool_list_classes, "List classes in Python file")
        self.registry.register("list_dataclasses", self.tool_list_dataclasses, "List dataclasses in Python file")
        self.registry.register("list_methods", self.tool_list_methods, "List methods in a Python class")
        self.registry.register("list_async_defs", self.tool_list_async_defs, "List async defs in Python file")
        self.registry.register("list_lines", self.tool_list_lines, "List file with line numbers")

        self.registry.register("read_line", self.tool_read_line, "Read one line")
        self.registry.register("read_lines", self.tool_read_lines, "Read line range")
        self.registry.register("read_def", self.tool_read_def, "Read Python def")
        self.registry.register("read_class", self.tool_read_class, "Read Python class")
        self.registry.register("read_dataclass", self.tool_read_dataclass, "Read Python dataclass")
        self.registry.register("read_method", self.tool_read_method, "Read Python method")

        self.registry.register("replace_def", self.tool_replace_def, "Replace Python def")
        self.registry.register("replace_class", self.tool_replace_class, "Replace Python class")
        self.registry.register("replace_dataclass", self.tool_replace_dataclass, "Replace Python dataclass")
        self.registry.register("replace_method", self.tool_replace_method, "Replace Python method")

        self.registry.register("select_object", self.tool_select_object, "Select a code object")
        self.registry.register("show_selection", self.tool_show_selection, "Show current selection")
        self.registry.register("read_selection", self.tool_read_selection, "Read current selection")
        self.registry.register("replace_selection", self.tool_replace_selection, "Replace current selection")
        self.registry.register("vcs_status", self.tool_vcs_status, "Show Git/VCS status")
        self.registry.register("vcs_diff", self.tool_vcs_diff, "Show Git/VCS diff")
        self.registry.register("vcs_log", self.tool_vcs_log, "Show Git/VCS log")
        self.registry.register("vcs_filelog", self.tool_vcs_filelog, "Show Git/VCS file history")
        self.registry.register("checkpoint", self.tool_checkpoint, "Create a Git checkpoint commit")
        self.registry.register("rollback_show", self.tool_rollback_show, "Show rollback history")
        self.registry.register("rollback_last", self.tool_rollback_last, "Rollback last commit")
        self.registry.register("rollback_file", self.tool_rollback_file, "Rollback a file")
        self.registry.register("rollback_to", self.tool_rollback_to, "Rollback to a commit")
        self.registry.register("git_mode", self.tool_git_mode, "Set Git integration mode")

        self.registry.register("trace_status", self.tool_trace_status, "Show trace profiler status")
        self.registry.register("trace_last", self.tool_trace_last, "Show last trace report")
        self.registry.register("trace_on", self.tool_trace_on, "Enable trace profiler")
        self.registry.register("trace_off", self.tool_trace_off, "Disable trace profiler")

        self.registry.register("run", self.tool_run, "Run a shell command")
        self.registry.register("git", self.tool_git, "Run a git command")
        self.registry.register("pwd", self.tool_pwd, "Show current working directory")
        self.registry.register("status", self.tool_status, "Show current trust/entropy/output state")
        self.registry.register("history", self.tool_history, "Show recent command history")
        self.registry.register("help", self.tool_help, "Show help")

        self.registry.register("no_truncate", self.tool_no_truncate, "Disable truncation / enable full output")
        self.registry.register("truncate_on", self.tool_truncate_on, "Enable truncation")
        self.registry.register("set_limit", self.tool_set_limit, "Set truncation output limit")
        self.registry.register("diff_on", self.tool_diff_on, "Enable preview diff confirmation")
        self.registry.register("diff_off", self.tool_diff_off, "Disable preview diff confirmation")

    # ---------------------- Output Policy ----------------------

    def _format_output(self, text: str, force_full: bool = False) -> str:
        if force_full:
            return text

        if self.engine.trust < LOW_TRUST_TRUNCATE_FLOOR:
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

    # ---------------------- File Helpers ----------------------

    def _resolve_file(self, file: Optional[str]) -> Optional[Path]:
        return resolve_file(self.cwd, file)

    def _read_text_file(self, target: Path) -> str:
        return read_text_file(target)

    def _write_text_file(self, target: Path, content: str) -> None:
        write_text_file(target, content)

    def _safe_existing_text(self, target: Path) -> str:
        return safe_existing_text(target)

    def _split_lines_keepends(self, text: str) -> list[str]:
        return split_lines_keepends(text)

    def _collect_multiline_input(
        self,
        sentinel: str = "__END__",
        initial_content: Optional[str] = None,
    ) -> str:
        print(f"Paste content below. End with a line containing only {sentinel}")
        lines = []

        if initial_content:
            lines.append(initial_content)

        while True:
            try:
                line = input()
            except EOFError:
                break
            if line == sentinel:
                break
            lines.append(line)

        return "\n".join(lines)

    def _extract_inline_after_marker(self, raw: str, marker: str) -> str:
        lower_raw = raw.lower()
        lower_marker = marker.lower()
        idx = lower_raw.find(lower_marker)
        if idx == -1:
            return ""
        remainder = raw[idx + len(marker):]
        return remainder.lstrip()

    # ---------------------- Diff / Preview ----------------------

    def _build_unified_diff(self, target: Path, old_text: str, new_text: str) -> str:
        return build_unified_diff(target, old_text, new_text)

    def _confirm_change(self, target: Path, old_text: str, new_text: str) -> tuple[bool, str]:
        if old_text == new_text:
            return False, f"No changes to apply for {target}"

        if not self.diff_preview_enabled or not self.show_future_diffs:
            return True, "Change applied."

        diff_text = self._build_unified_diff(target, old_text, new_text)
        print("Preview diff:")
        print("-" * 88)
        print(diff_text)
        print("-" * 88)

        while True:
            choice = input("Apply change? [y]es / [n]o / [s]kip future diffs / [d]iff: ").strip().lower()

            if choice in {"y", "yes", "apply"}:
                return True, "Change applied."
            if choice in {"n", "no", "cancel"}:
                return False, "Change canceled."
            if choice in {"s", "skip"}:
                self.show_future_diffs = False
                return True, "Change applied. Future diffs skipped for this session."
            if choice in {"d", "diff"}:
                print("-" * 88)
                print(diff_text)
                print("-" * 88)
                continue

            print("Please enter y, n, s, or d.")

    def _apply_change_with_preview(self, target: Path, new_text: str) -> str:
        try:
            old_text = self._safe_existing_text(target)
        except ValueError as e:
            return str(e)

        should_apply, message = self._confirm_change(target, old_text, new_text)
        if not should_apply:
            return message

        self._write_text_file(target, new_text)
        return message

    # ---------------------- Pager ----------------------

    def _open_in_pager(self, text: str) -> str:
        return open_in_pager(text)

    # ---------------------- Python Code Index Helpers ----------------------

    def _ensure_python_file(self, target: Path) -> Optional[str]:
        return ensure_python_file(target)

    def _index_python_file(self, target: Path) -> list[CodeObject]:
        source = self._read_text_file(target)
        tree = ast.parse(source)
        indexer = PythonCodeIndexer()
        indexer.visit(tree)
        return indexer.objects

    def _get_objects_by_kind(self, target: Path, kind: str) -> list[CodeObject]:
        objects = self._index_python_file(target)
        return [obj for obj in objects if obj.kind == kind]

    def _find_code_object(
        self,
        target: Path,
        kind: str,
        name: str,
        parent: Optional[str] = None,
    ) -> Optional[CodeObject]:
        objects = self._index_python_file(target)
        for obj in objects:
            if obj.kind == kind and obj.name == name:
                if parent is None or obj.parent == parent:
                    return obj
        return None

    def _find_method_candidates(self, target: Path, name: str) -> list[CodeObject]:
        objects = self._index_python_file(target)
        return [obj for obj in objects if obj.kind in {"method", "async_method"} and obj.name == name]

    def _extract_line_range(self, text: str, start_line: int, end_line: int) -> str:
        return extract_line_range(text, start_line, end_line)

    def _replace_line_range(self, text: str, start_line: int, end_line: int, replacement: str) -> str:
        return replace_line_range(text, start_line, end_line, replacement)

    def _format_code_objects(self, title: str, items: list[CodeObject]) -> str:
        if not items:
            return f"{title}\n[none found]"
        lines = [title]
        for idx, obj in enumerate(items, 1):
            parent = f" | parent={obj.parent}" if obj.parent else ""
            lines.append(
                f"{idx:02d}. kind={obj.kind} | name={obj.name} | lines={obj.start_line}:{obj.end_line}{parent}"
            )
        return "\n".join(lines)

    def _read_code_object(
        self,
        target: Path,
        kind: str,
        name: str,
        parent: Optional[str] = None,
    ) -> str:
        obj = self._find_code_object(target, kind, name, parent)
        if not obj:
            parent_msg = f" in {parent}" if parent else ""
            return f"{kind} not found: {name}{parent_msg}"

        text = self._safe_existing_text(target)
        block = self._extract_line_range(text, obj.start_line, obj.end_line)
        return (
            f"--- {kind} {name} | lines {obj.start_line}:{obj.end_line}"
            f"{' | parent=' + obj.parent if obj.parent else ''} ---\n"
            f"{block}"
        )

    def _replace_code_object(
        self,
        target: Path,
        kind: str,
        name: str,
        replacement: str,
        parent: Optional[str] = None,
    ) -> str:
        obj = self._find_code_object(target, kind, name, parent)
        if not obj:
            parent_msg = f" in {parent}" if parent else ""
            return f"{kind} not found: {name}{parent_msg}"

        old_text = self._safe_existing_text(target)
        new_text = self._replace_line_range(old_text, obj.start_line, obj.end_line, replacement)
        result = self._apply_change_with_preview(target, new_text)
        if result.startswith("Change applied"):
            return f"{result} Replaced {kind} {name} in {target}"
        return result

    # ---------------------- Raw Text Edit Helpers ----------------------

    def _replace_line(self, text: str, line_no: int, replacement: str) -> str:
        return self._replace_lines(text, line_no, line_no, replacement)

    def _replace_lines(self, text: str, start_line: int, end_line: int, replacement: str) -> str:
        lines = self._split_lines_keepends(text)
        if start_line < 1 or end_line < start_line or end_line > len(lines):
            raise ValueError("Line range out of bounds")

        repl = replacement
        if repl and not repl.endswith("\n") and start_line != end_line:
            repl += "\n"

        replacement_lines = self._split_lines_keepends(repl)
        if replacement and not replacement.endswith(("\n", "\r")) and start_line == end_line:
            replacement_lines = [replacement + ("\n" if lines[start_line - 1].endswith("\n") else "")]

        return "".join(lines[:start_line - 1] + replacement_lines + lines[end_line:])

    def _replace_char_in_line(self, text: str, line_no: int, char_pos: int, new_char: str) -> str:
        lines = self._split_lines_keepends(text)
        idx = line_no - 1
        if idx < 0 or idx >= len(lines):
            raise ValueError("Line out of range")

        line = lines[idx]
        raw = line.rstrip("\r\n")
        ending = line[len(raw):]

        cidx = char_pos - 1
        if cidx < 0 or cidx >= len(raw):
            raise ValueError("Character position out of range")

        raw = raw[:cidx] + new_char + raw[cidx + 1:]
        lines[idx] = raw + ending
        return "".join(lines)

    def _insert_char_in_line(self, text: str, line_no: int, char_pos: int, char: str) -> str:
        lines = self._split_lines_keepends(text)
        idx = line_no - 1
        if idx < 0 or idx >= len(lines):
            raise ValueError("Line out of range")

        line = lines[idx]
        raw = line.rstrip("\r\n")
        ending = line[len(raw):]

        cidx = char_pos - 1
        if cidx < 0 or cidx > len(raw):
            raise ValueError("Character position out of range")

        raw = raw[:cidx] + char + raw[cidx:]
        lines[idx] = raw + ending
        return "".join(lines)

    def _delete_char_in_line(self, text: str, line_no: int, char_pos: int) -> str:
        lines = self._split_lines_keepends(text)
        idx = line_no - 1
        if idx < 0 or idx >= len(lines):
            raise ValueError("Line out of range")

        line = lines[idx]
        raw = line.rstrip("\r\n")
        ending = line[len(raw):]

        cidx = char_pos - 1
        if cidx < 0 or cidx >= len(raw):
            raise ValueError("Character position out of range")

        raw = raw[:cidx] + raw[cidx + 1:]
        lines[idx] = raw + ending
        return "".join(lines)

    def _replace_word_in_line(self, text: str, line_no: int, old: str, new: str, replace_all: bool = True) -> str:
        lines = self._split_lines_keepends(text)
        idx = line_no - 1
        if idx < 0 or idx >= len(lines):
            raise ValueError("Line out of range")

        lines[idx] = lines[idx].replace(old, new) if replace_all else lines[idx].replace(old, new, 1)
        return "".join(lines)

    def _replace_word_in_file(self, text: str, old: str, new: str, replace_all: bool = True) -> str:
        return text.replace(old, new) if replace_all else text.replace(old, new, 1)

    def _parse_line_range(self, value: str) -> tuple[int, int]:
        if ":" in value:
            left, right = value.split(":", 1)
            start = int(left)
            end = int(right)
            return start, end
        line_no = int(value)
        return line_no, line_no

    def _read_text_range(self, target: Path, start_line: int, end_line: int) -> str:
        text = self._safe_existing_text(target)
        lines = self._split_lines_keepends(text)
        if start_line < 1 or end_line < start_line or end_line > len(lines):
            return "Line range out of bounds"

        out = [f"--- {target.name} | lines {start_line}:{end_line} ---"]
        for i in range(start_line, end_line + 1):
            out.append(f"{i:04d}: {lines[i - 1].rstrip()}")
        return "\n".join(out)

    # ---------------------- Generic Tools ----------------------

    def tool_list(self, path: Optional[str] = None, **kwargs: Any) -> str:
        target = (self.cwd / (path or "")).resolve()
        if not target.exists():
            return f"Path not found: {target}"
        if not target.is_dir():
            return f"Not a directory: {target}"

        items = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        if not items:
            return f"{target}\n[empty directory]"

        lines = [f"Directory: {target}"]
        for item in items:
            tag = "[DIR]" if item.is_dir() else "     "
            lines.append(f"{tag} {item.name}")
        return "\n".join(lines)

    def tool_read(
        self,
        file: Optional[str] = None,
        pager: bool = False,
        full: bool = False,
        **kwargs: Any,
    ) -> str:
        target = self._resolve_file(file)
        if not target:
            return "Read failed - no file specified"
        if not target.exists():
            return f"File not found: {target}"
        if not target.is_file():
            return f"Not a file: {target}"

        try:
            text = self._read_text_file(target)
        except UnicodeDecodeError:
            return f"File is not valid UTF-8 text: {target}"

        payload = f"--- {target.name} ---\n{text}"

        if pager:
            return self._open_in_pager(payload)

        return payload if full else self._format_output(payload)

    def tool_edit(
        self,
        file: Optional[str] = None,
        content: Optional[str] = None,
        append: bool = False,
        content_mode: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        target = self._resolve_file(file)
        if not target:
            return "Edit failed - no file specified"

        target.parent.mkdir(parents=True, exist_ok=True)

        try:
            old_text = self._safe_existing_text(target)
        except ValueError as e:
            return str(e)

        if content_mode in {"pastefile", "pasteappend"}:
            payload = self._collect_multiline_input(initial_content=content)
            do_append = append or (content_mode == "pasteappend")
            new_text = old_text + payload if do_append else payload
            result = self._apply_change_with_preview(target, new_text)
            if result.startswith("Change applied"):
                return f"{result} {'Appended pasted content to' if do_append else 'Wrote pasted content to'} {target}"
            return result

        payload = content or "# RHEA edit\n"
        new_text = old_text + payload if append else payload
        result = self._apply_change_with_preview(target, new_text)
        if result.startswith("Change applied"):
            return f"{result} {'Appended to' if append else 'Wrote'} {target}"
        return result

    # ---------------------- Existing Text Replace Tools ----------------------

    def tool_replace(
        self,
        file: Optional[str] = None,
        old: Optional[str] = None,
        new: Optional[str] = None,
        count: int = -1,
        **kwargs: Any,
    ) -> str:
        target = self._resolve_file(file)
        if not target:
            return "Replace failed - no file specified"
        if not target.exists():
            return f"File not found: {target}"
        if old is None or new is None:
            return 'Usage: replace in <file> "old text" "new text"'

        try:
            text = self._safe_existing_text(target)
        except ValueError as e:
            return str(e)

        occurrences = text.count(old)
        if occurrences == 0:
            return f'Anchor text not found in {target.name}: "{old}"'

        updated = text.replace(old, new) if count == -1 else text.replace(old, new, count)
        replaced = occurrences if count == -1 else min(occurrences, count)

        result = self._apply_change_with_preview(target, updated)
        if result.startswith("Change applied"):
            return f"{result} Replaced {replaced} occurrence(s) in {target}"
        return result

    def tool_insert_after(
        self,
        file: Optional[str] = None,
        anchor: Optional[str] = None,
        content: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        return self._insert_relative(file=file, anchor=anchor, content=content, before=False)

    def tool_insert_before(
        self,
        file: Optional[str] = None,
        anchor: Optional[str] = None,
        content: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        return self._insert_relative(file=file, anchor=anchor, content=content, before=True)

    def _insert_relative(
        self,
        file: Optional[str],
        anchor: Optional[str],
        content: Optional[str],
        before: bool,
    ) -> str:
        target = self._resolve_file(file)
        if not target:
            return "Insert failed - no file specified"
        if not target.exists():
            return f"File not found: {target}"
        if anchor is None or content is None:
            direction = "before" if before else "after"
            return f'Usage: insert {direction} <file> "anchor text" "content to insert"'

        try:
            text = self._safe_existing_text(target)
        except ValueError as e:
            return str(e)

        idx = text.find(anchor)
        if idx == -1:
            return f'Anchor text not found in {target.name}: "{anchor}"'

        if before:
            updated = text[:idx] + content + text[idx:]
            action = "Inserted before"
        else:
            insert_pos = idx + len(anchor)
            updated = text[:insert_pos] + content + text[insert_pos:]
            action = "Inserted after"

        result = self._apply_change_with_preview(target, updated)
        if result.startswith("Change applied"):
            return f'{result} {action} anchor in {target.name}: "{anchor}"'
        return result

    def tool_prepend(
        self,
        file: Optional[str] = None,
        content: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        target = self._resolve_file(file)
        if not target:
            return "Prepend failed - no file specified"
        if content is None:
            return 'Usage: prepend <file> "content"'

        try:
            existing = self._safe_existing_text(target)
        except ValueError as e:
            return str(e)

        updated = content + existing
        result = self._apply_change_with_preview(target, updated)
        if result.startswith("Change applied"):
            return f"{result} Prepended content to {target}"
        return result

    # ---------------------- Paste Tools ----------------------

    def tool_pastefile(
        self,
        file: Optional[str] = None,
        initial_content: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        target = self._resolve_file(file)
        if not target:
            return "Paste failed - no file specified"

        content = self._collect_multiline_input(initial_content=initial_content)
        result = self._apply_change_with_preview(target, content)
        if result.startswith("Change applied"):
            return f"{result} Wrote pasted content to {target}"
        return result

    def tool_pasteappend(
        self,
        file: Optional[str] = None,
        initial_content: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        target = self._resolve_file(file)
        if not target:
            return "Paste append failed - no file specified"

        try:
            old_text = self._safe_existing_text(target)
        except ValueError as e:
            return str(e)

        content = self._collect_multiline_input(initial_content=initial_content)
        updated = old_text + content
        result = self._apply_change_with_preview(target, updated)
        if result.startswith("Change applied"):
            return f"{result} Appended pasted content to {target}"
        return result

    # ---------------------- Code Object Listing ----------------------

    def tool_list_defs(self, file: Optional[str] = None, **kwargs: Any) -> str:
        return self._list_python_objects(file, "def", "Defs")

    def tool_list_classes(self, file: Optional[str] = None, **kwargs: Any) -> str:
        return self._list_python_objects(file, "class", "Classes")

    def tool_list_dataclasses(self, file: Optional[str] = None, **kwargs: Any) -> str:
        return self._list_python_objects(file, "dataclass", "Dataclasses")

    def tool_list_methods(self, file: Optional[str] = None, class_name: Optional[str] = None, **kwargs: Any) -> str:
        target = self._resolve_file(file)
        if not target:
            return "No file specified"
        if not target.exists():
            return f"File not found: {target}"
        py_err = self._ensure_python_file(target)
        if py_err:
            return py_err

        try:
            objs = self._get_objects_by_kind(target, "method") + self._get_objects_by_kind(target, "async_method")
        except Exception as e:
            return f"Failed to parse Python file: {e}"

        if class_name:
            objs = [obj for obj in objs if obj.parent == class_name]

        return self._format_code_objects(
            f"Methods in {target.name}" + (f" | class={class_name}" if class_name else ""),
            objs,
        )

    def tool_list_async_defs(self, file: Optional[str] = None, **kwargs: Any) -> str:
        return self._list_python_objects(file, "async_def", "Async defs")

    def _list_python_objects(self, file: Optional[str], kind: str, title: str) -> str:
        target = self._resolve_file(file)
        if not target:
            return "No file specified"
        if not target.exists():
            return f"File not found: {target}"
        py_err = self._ensure_python_file(target)
        if py_err:
            return py_err

        try:
            objs = self._get_objects_by_kind(target, kind)
        except Exception as e:
            return f"Failed to parse Python file: {e}"

        return self._format_code_objects(f"{title} in {target.name}", objs)

    # ---------------------- Line Listing / Reading ----------------------

    def tool_list_lines(self, file: Optional[str] = None, **kwargs: Any) -> str:
        target = self._resolve_file(file)
        if not target:
            return "No file specified"
        if not target.exists():
            return f"File not found: {target}"

        try:
            text = self._safe_existing_text(target)
        except ValueError as e:
            return str(e)

        lines = self._split_lines_keepends(text)
        out = [f"--- {target.name} | numbered lines ---"]
        for i, line in enumerate(lines, 1):
            out.append(f"{i:04d}: {line.rstrip()}")
        return "\n".join(out)

    def tool_read_line(self, file: Optional[str] = None, line_no: Optional[int] = None, **kwargs: Any) -> str:
        target = self._resolve_file(file)
        if not target:
            return "No file specified"
        if line_no is None:
            return "Usage: read line <file> <line_no>"
        return self._read_text_range(target, line_no, line_no)

    def tool_read_lines(
        self,
        file: Optional[str] = None,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        **kwargs: Any,
    ) -> str:
        target = self._resolve_file(file)
        if not target:
            return "No file specified"
        if start_line is None or end_line is None:
            return "Usage: read lines <file> <start:end>"
        return self._read_text_range(target, start_line, end_line)

    # ---------------------- Code Object Reading ----------------------

    def tool_read_def(self, file: Optional[str] = None, name: Optional[str] = None, **kwargs: Any) -> str:
        return self._read_named_code_object(file, "def", name)

    def tool_read_class(self, file: Optional[str] = None, name: Optional[str] = None, **kwargs: Any) -> str:
        return self._read_named_code_object(file, "class", name)

    def tool_read_dataclass(self, file: Optional[str] = None, name: Optional[str] = None, **kwargs: Any) -> str:
        return self._read_named_code_object(file, "dataclass", name)

    def tool_read_method(
        self,
        file: Optional[str] = None,
        class_name: Optional[str] = None,
        method_name: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        target = self._resolve_file(file)
        if not target:
            return "No file specified"
        if not class_name or not method_name:
            return "Usage: read method <file> <ClassName> <method_name>"

        py_err = self._ensure_python_file(target)
        if py_err:
            return py_err

        out = self._read_code_object(target, "method", method_name, class_name)
        if out.startswith("method not found"):
            out = self._read_code_object(target, "async_method", method_name, class_name)
        return out

    def _read_named_code_object(self, file: Optional[str], kind: str, name: Optional[str]) -> str:
        target = self._resolve_file(file)
        if not target:
            return "No file specified"
        if not name:
            return f"Usage: read {kind} <file> <name>"
        if not target.exists():
            return f"File not found: {target}"

        py_err = self._ensure_python_file(target)
        if py_err:
            return py_err

        result = self._read_code_object(target, kind, name)
        if not result.startswith(f"{kind} not found"):
            return result

        if kind == "def":
            try:
                matches = self._find_method_candidates(target, name)
            except Exception as e:
                return f"Failed to parse Python file: {e}"

            if len(matches) == 1:
                obj = matches[0]
                return (
                    f'No top-level def named "{name}" found.\n'
                    f"Found {obj.kind}: {obj.parent}.{obj.name}\n\n"
                    + self._read_code_object(target, obj.kind, obj.name, obj.parent)
                )
            if len(matches) > 1:
                lines = [f'No top-level def named "{name}" found.', "Matching methods:"]
                for obj in matches:
                    lines.append(f"  - {obj.parent}.{obj.name} | lines {obj.start_line}:{obj.end_line}")
                lines.append(f"Try: read method {target.name} <ClassName> {name}")
                return "\n".join(lines)

        return result

    # ---------------------- Code Object Replacing ----------------------

    def tool_replace_def(
        self,
        file: Optional[str] = None,
        name: Optional[str] = None,
        replacement: Optional[str] = None,
        content_mode: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        return self._replace_named_code_object(file, "def", name, replacement, content_mode)

    def tool_replace_class(
        self,
        file: Optional[str] = None,
        name: Optional[str] = None,
        replacement: Optional[str] = None,
        content_mode: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        return self._replace_named_code_object(file, "class", name, replacement, content_mode)

    def tool_replace_dataclass(
        self,
        file: Optional[str] = None,
        name: Optional[str] = None,
        replacement: Optional[str] = None,
        content_mode: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        return self._replace_named_code_object(file, "dataclass", name, replacement, content_mode)

    def tool_replace_method(
        self,
        file: Optional[str] = None,
        class_name: Optional[str] = None,
        method_name: Optional[str] = None,
        replacement: Optional[str] = None,
        content_mode: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        target = self._resolve_file(file)
        if not target:
            return "No file specified"
        if not class_name or not method_name:
            return "Usage: replace method <file> <ClassName> <method_name> <replacement|pastefile>"
        if not target.exists():
            return f"File not found: {target}"

        py_err = self._ensure_python_file(target)
        if py_err:
            return py_err

        repl = self._collect_multiline_input(initial_content=replacement) if content_mode == "pastefile" else replacement
        if repl is None:
            return "No replacement content provided"

        obj = self._find_code_object(target, "method", method_name, class_name)
        kind = "method"
        if not obj:
            obj = self._find_code_object(target, "async_method", method_name, class_name)
            kind = "async_method"
        if not obj:
            return f"Method not found: {class_name}.{method_name}"

        return self._replace_code_object(target, kind, method_name, repl, class_name)

    def _replace_named_code_object(
        self,
        file: Optional[str],
        kind: str,
        name: Optional[str],
        replacement: Optional[str],
        content_mode: Optional[str],
    ) -> str:
        target = self._resolve_file(file)
        if not target:
            return "No file specified"
        if not name:
            return f"Usage: replace {kind} <file> <name> <replacement|pastefile>"
        if not target.exists():
            return f"File not found: {target}"

        py_err = self._ensure_python_file(target)
        if py_err:
            return py_err

        repl = self._collect_multiline_input(initial_content=replacement) if content_mode == "pastefile" else replacement
        if repl is None:
            return "No replacement content provided"

        return self._replace_code_object(target, kind, name, repl)

    # ---------------------- Line / Char / Word Editing ----------------------

    def tool_replace_line(
        self,
        file: Optional[str] = None,
        line_no: Optional[int] = None,
        replacement: Optional[str] = None,
        content_mode: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        target = self._resolve_file(file)
        if not target:
            return "No file specified"
        if line_no is None:
            return "Usage: replace line <file> <line_no> <replacement|pastefile>"

        try:
            old_text = self._safe_existing_text(target)
        except ValueError as e:
            return str(e)

        repl = self._collect_multiline_input(initial_content=replacement) if content_mode == "pastefile" else replacement
        if repl is None:
            return "No replacement content provided"

        try:
            new_text = self._replace_line(old_text, line_no, repl)
        except ValueError as e:
            return str(e)

        result = self._apply_change_with_preview(target, new_text)
        if result.startswith("Change applied"):
            return f"{result} Replaced line {line_no} in {target}"
        return result

    def tool_replace_lines(
        self,
        file: Optional[str] = None,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        replacement: Optional[str] = None,
        content_mode: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        target = self._resolve_file(file)
        if not target:
            return "No file specified"
        if start_line is None or end_line is None:
            return "Usage: replace lines <file> <start:end> <replacement|pastefile>"

        try:
            old_text = self._safe_existing_text(target)
        except ValueError as e:
            return str(e)

        repl = self._collect_multiline_input(initial_content=replacement) if content_mode == "pastefile" else replacement
        if repl is None:
            return "No replacement content provided"

        try:
            new_text = self._replace_lines(old_text, start_line, end_line, repl)
        except ValueError as e:
            return str(e)

        result = self._apply_change_with_preview(target, new_text)
        if result.startswith("Change applied"):
            return f"{result} Replaced lines {start_line}:{end_line} in {target}"
        return result

    def tool_replace_char(
        self,
        file: Optional[str] = None,
        line_no: Optional[int] = None,
        char_pos: Optional[int] = None,
        new_char: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        return self._char_edit(file, line_no, char_pos, "replace", new_char)

    def tool_insert_char(
        self,
        file: Optional[str] = None,
        line_no: Optional[int] = None,
        char_pos: Optional[int] = None,
        char: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        return self._char_edit(file, line_no, char_pos, "insert", char)

    def tool_delete_char(
        self,
        file: Optional[str] = None,
        line_no: Optional[int] = None,
        char_pos: Optional[int] = None,
        **kwargs: Any,
    ) -> str:
        return self._char_edit(file, line_no, char_pos, "delete", None)

    def _char_edit(
        self,
        file: Optional[str],
        line_no: Optional[int],
        char_pos: Optional[int],
        mode: str,
        value: Optional[str],
    ) -> str:
        target = self._resolve_file(file)
        if not target:
            return "No file specified"
        if line_no is None or char_pos is None:
            return f"Usage: {mode} char <file> <line_no> <char_pos>" + (" <char>" if mode != "delete" else "")

        try:
            old_text = self._safe_existing_text(target)
        except ValueError as e:
            return str(e)

        try:
            if mode == "replace":
                if value is None:
                    return 'Usage: replace char <file> <line_no> <char_pos> "<char>"'
                new_text = self._replace_char_in_line(old_text, line_no, char_pos, value)
            elif mode == "insert":
                if value is None:
                    return 'Usage: insert char <file> <line_no> <char_pos> "<char>"'
                new_text = self._insert_char_in_line(old_text, line_no, char_pos, value)
            else:
                new_text = self._delete_char_in_line(old_text, line_no, char_pos)
        except ValueError as e:
            return str(e)

        result = self._apply_change_with_preview(target, new_text)
        if result.startswith("Change applied"):
            return f"{result} {mode.title()}d char at line {line_no}, char {char_pos} in {target}"
        return result

    def tool_replace_word(
        self,
        file: Optional[str] = None,
        scope: Optional[str] = None,
        old: Optional[str] = None,
        new: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        target = self._resolve_file(file)
        if not target:
            return "No file specified"
        if scope is None or old is None or new is None:
            return 'Usage: replace word <file> <line_no|all> "old" "new"'

        try:
            old_text = self._safe_existing_text(target)
        except ValueError as e:
            return str(e)

        try:
            if str(scope).lower() == "all":
                new_text = self._replace_word_in_file(old_text, old, new, True)
            else:
                line_no = int(str(scope))
                new_text = self._replace_word_in_line(old_text, line_no, old, new, True)
        except ValueError as e:
            return str(e)

        result = self._apply_change_with_preview(target, new_text)
        if result.startswith("Change applied"):
            return f"{result} Replaced word in {target}"
        return result

    # ---------------------- Selection ----------------------

    def tool_select_object(
        self,
        file: Optional[str] = None,
        kind: Optional[str] = None,
        name: Optional[str] = None,
        parent: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        target = self._resolve_file(file)
        if not target:
            return "No file specified"
        if not kind or not name:
            return "Usage: select <def|class|dataclass|method> <file> <name> [parent_class_for_method]"
        if not target.exists():
            return f"File not found: {target}"

        py_err = self._ensure_python_file(target)
        if py_err:
            return py_err

        search_kind = kind
        obj = None

        if kind == "method":
            obj = self._find_code_object(target, "method", name, parent)
            search_kind = "method"
            if not obj:
                obj = self._find_code_object(target, "async_method", name, parent)
                search_kind = "async_method"

        elif kind == "def":
            obj = self._find_code_object(target, "def", name, parent)
            search_kind = "def"

            if not obj:
                try:
                    matches = self._find_method_candidates(target, name)
                except Exception as e:
                    return f"Failed to parse Python file: {e}"

                if len(matches) == 1:
                    obj = matches[0]
                    search_kind = obj.kind
                elif len(matches) > 1:
                    lines = [f'No top-level def named "{name}" found.', "Matching methods:"]
                    for match in matches:
                        lines.append(
                            f"  - {match.parent}.{match.name} | lines {match.start_line}:{match.end_line}"
                        )
                    lines.append(f"Try: select method {target.name} <ClassName> {name}")
                    return "\n".join(lines)

        else:
            obj = self._find_code_object(target, kind, name, parent)

        if not obj:
            return f"Selection target not found: kind={kind} name={name}" + (f" parent={parent}" if parent else "")

        self.selection = {
            "file": str(target),
            "kind": search_kind,
            "name": obj.name,
            "parent": obj.parent,
            "start_line": obj.start_line,
            "end_line": obj.end_line,
        }

        return (
            f"Selected {search_kind} {obj.name} in {target.name} | "
            f"lines {obj.start_line}:{obj.end_line}"
            + (f" | parent={obj.parent}" if obj.parent else "")
        )

    def tool_show_selection(self, **kwargs: Any) -> str:
        if not self.selection:
            return "No active selection."

        return (
            "Current Selection\n"
            "-----------------\n"
            f"File: {self.selection['file']}\n"
            f"Kind: {self.selection['kind']}\n"
            f"Name: {self.selection['name']}\n"
            f"Parent: {self.selection.get('parent')}\n"
            f"Lines: {self.selection['start_line']}:{self.selection['end_line']}"
        )

    def tool_read_selection(self, **kwargs: Any) -> str:
        if not self.selection:
            return "No active selection."

        target = Path(self.selection["file"])
        try:
            text = self._safe_existing_text(target)
        except ValueError as e:
            return str(e)

        block = self._extract_line_range(text, self.selection["start_line"], self.selection["end_line"])
        return (
            f"--- selection {self.selection['kind']} {self.selection['name']} "
            f"| lines {self.selection['start_line']}:{self.selection['end_line']} ---\n"
            f"{block}"
        )

    def tool_replace_selection(
        self,
        replacement: Optional[str] = None,
        content_mode: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        if not self.selection:
            return "No active selection."

        target = Path(self.selection["file"])
        try:
            old_text = self._safe_existing_text(target)
        except ValueError as e:
            return str(e)

        repl = self._collect_multiline_input(initial_content=replacement) if content_mode == "pastefile" else replacement
        if repl is None:
            return "No replacement content provided"

        new_text = self._replace_line_range(
            old_text,
            self.selection["start_line"],
            self.selection["end_line"],
            repl,
        )
        result = self._apply_change_with_preview(target, new_text)
        if result.startswith("Change applied"):
            return f"{result} Replaced current selection in {target}"
        return result

    def _ensure_git_repo(self) -> Optional[str]:
        if not is_git_available():
            return (
                "Git is not installed on this system.\n"
                "Install Git to enable git commands in RHEA Code CLI."
            )
        if not is_git_repo(self.cwd):
            return (
                "No Git repository found in current working directory.\n"
                "Run: git init"
            )
        return None

    def _maybe_checkpoint_before_edit(
        self,
        op: str,
        file: Optional[str] = None,
        target: Optional[str] = None,
        lines: Optional[str] = None,
    ) -> str:
        if not should_checkpoint_before_edit(self.git_mode, self.engine.trust):
            return ""

        repo_msg = self._ensure_git_repo()
        if repo_msg:
            return ""

        if file:
            stage_result = git_stage_file(self.cwd, file)
            if "[exit=0]" not in stage_result:
                return f"[checkpoint skipped] Could not stage file: {file}\n{stage_result}"

        msg = build_checkpoint_message(op=op, file=file, target=target, lines=lines)
        commit_result = git_commit(self.cwd, msg)

        if "[exit=0]" in commit_result:
            return f"[checkpoint created] {msg}"
        return f"[checkpoint skipped] {commit_result}"

    def tool_vcs_status(self, **kwargs: Any) -> str:
        repo_msg = self._ensure_git_repo()
        if repo_msg:
            return repo_msg

        branch = get_current_branch(self.cwd) or "(unknown)"
        dirty = working_tree_dirty(self.cwd)
        status_text = git_status(self.cwd)

        summary = [
            "RHEA VCS Status",
            "---------------",
           f"Branch: {branch}",
            f"Dirty: {dirty}",
            f"Git Mode: {self.git_mode}",
            "",
            status_text,
        ]
        return "\n".join(summary)

    def tool_vcs_diff(self, file: Optional[str] = None, cached: bool = False, **kwargs: Any) -> str:
        repo_msg = self._ensure_git_repo()
        if repo_msg:
            return repo_msg
        return git_diff(self.cwd, file=file, cached=cached)

    def tool_vcs_log(self, limit: int = 10, **kwargs: Any) -> str:
        repo_msg = self._ensure_git_repo()
        if repo_msg:
            return repo_msg

        result = get_checkpoint_log(self.cwd, limit=limit)
        if "does not have any commits yet" in result.lower():
            return "No commits yet in this repository."
        return result

    def tool_vcs_filelog(self, file: Optional[str] = None, limit: int = 10, **kwargs: Any) -> str:
        repo_msg = self._ensure_git_repo()
        if repo_msg:
            return repo_msg
        if not file:
            return "Usage: vcs filelog <file> [limit]"

        result = get_file_history(self.cwd, file=file, limit=limit)
        if "does not have any commits yet" in result.lower():
            return f"No commit history yet for repository or file: {file}"
        return result

    def tool_checkpoint(self, note: Optional[str] = None, **kwargs: Any) -> str:
        repo_msg = self._ensure_git_repo()
        if repo_msg:
            return repo_msg

        stage_result = run_git_command(self.cwd, "add -A")
        if "[exit=0]" not in stage_result:
            return f"Checkpoint failed during staging.\n{stage_result}"

        msg = build_checkpoint_message(op="manual", note=note or "manual checkpoint")
        commit_result = git_commit(self.cwd, msg)

        if "[exit=0]" in commit_result:
            return commit_result

        lower = commit_result.lower()
        if "nothing to commit" in lower or "nothing added to commit" in lower:
            return "No changes to checkpoint."

        return f"Checkpoint failed.\n{commit_result}"

    def tool_rollback_show(self, limit: int = 20, **kwargs: Any) -> str:
        repo_msg = self._ensure_git_repo()
        if repo_msg:
            return repo_msg

        result = rollback_show(self.cwd, limit=limit)
        if "does not have any commits yet" in result.lower():
            return "No commits yet in this repository."
        return result

    def tool_rollback_last(self, **kwargs: Any) -> str:
        repo_msg = self._ensure_git_repo()
        if repo_msg:
            return repo_msg

        preview = rollback_last_preview(self.cwd)
        print(preview)
        confirm = input("Rollback last commit with hard reset? [y/N]: ").strip().lower()
        if confirm not in {"y", "yes"}:
            return "Rollback canceled."

        return rollback_last_hard(self.cwd)

    def tool_rollback_file(self, file: Optional[str] = None, **kwargs: Any) -> str:
        repo_msg = self._ensure_git_repo()
        if repo_msg:
            return repo_msg
        if not file:
            return "Usage: rollback file <file>"

        preview = rollback_file_preview(self.cwd, file)
        print(preview)
        confirm = input(f'Rollback file "{file}" to HEAD? [y/N]: ').strip().lower()
        if confirm not in {"y", "yes"}:
            return "Rollback canceled."

        return rollback_file_to_head(self.cwd, file)

    def tool_rollback_to(self, commit: Optional[str] = None, **kwargs: Any) -> str:
        repo_msg = self._ensure_git_repo()
        if repo_msg:
            return repo_msg
        if not commit:
            return "Usage: rollback to <commit>"

        preview = rollback_to_commit_preview(self.cwd, commit)
        print(preview)
        confirm = input(f"Hard reset to commit {commit}? [y/N]: ").strip().lower()
        if confirm not in {"y", "yes"}:
            return "Rollback canceled."

        return rollback_to_commit_hard(self.cwd, commit)

    def tool_git_mode(self, mode: Optional[str] = None, **kwargs: Any) -> str:
        if not mode:
            return f"Git mode: {self.git_mode}"

        self.git_mode = normalize_git_mode(mode)
        return f"Git mode set to: {self.git_mode}"

    # ---------------------- Shell / Misc ----------------------

    def tool_trace_status(self, **kwargs: Any) -> str:
        return (
            "RHEA Trace Profiler Status\n"
            "--------------------------\n"
            f"Profiling Enabled: {self.profiling_enabled}\n"
            f"Auto Save: {self.profiling_auto_save}\n"
            f"Trace Log Dir: {self.profiler.log_dir}\n"
            f"Last Trace Available: {bool(self.last_trace_report)}"
        )

    def tool_trace_last(self, **kwargs: Any) -> str:
        if not self.last_trace_report:
            return "No trace report available yet."
        return self.last_trace_report

    def tool_trace_on(self, **kwargs: Any) -> str:
        self.profiling_enabled = True
        return "Trace profiler enabled."

    def tool_trace_off(self, **kwargs: Any) -> str:
        self.profiling_enabled = False
        return "Trace profiler disabled."

    def tool_run(self, cmd: Optional[str] = None, **kwargs: Any) -> str:
        if not cmd:
            return "No command given"

        completed = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            cwd=str(self.cwd),
        )

        output = completed.stdout.strip()
        err = completed.stderr.strip()

        parts = [f"[exit={completed.returncode}]"]
        if output:
            parts.append("--- stdout ---")
            parts.append(output)
        if err:
            parts.append("--- stderr ---")
            parts.append(err)
        return "\n".join(parts)

    def tool_git(self, cmd: Optional[str] = None, **kwargs: Any) -> str:
        import os
        import shutil

        def find_git_executable() -> Optional[str]:
            git_exe = shutil.which("git")
            if git_exe:
                return git_exe

            candidates = [
                r"C:\Program Files\Git\cmd\git.exe",
                r"C:\Program Files\Git\bin\git.exe",
                r"C:\Program Files (x86)\Git\cmd\git.exe",
                r"C:\Program Files (x86)\Git\bin\git.exe",
                os.path.expandvars(r"%LocalAppData%\Programs\Git\cmd\git.exe"),
                os.path.expandvars(r"%LocalAppData%\Programs\Git\bin\git.exe"),
            ]

            for path in candidates:
                if os.path.exists(path):
                    return path

            return None

        git_exe = find_git_executable()
        if not git_exe:
            return (
                "Git is not available on PATH and was not found in common install locations.\n"
                "Try running: where git\n"
                "If Git is installed, add it to PATH or update the CLI search paths."
            )

        git_cmd = (cmd or "git status").strip()

        if git_cmd.lower() == "git":
            git_cmd = "status"
        elif git_cmd.lower().startswith("git "):
            git_cmd = git_cmd[4:].strip()

        full_cmd = f'"{git_exe}" {git_cmd}'.strip()
        return self.tool_run(cmd=full_cmd)

    def tool_pwd(self, **kwargs: Any) -> str:
        return str(self.cwd)

    def tool_status(self, **kwargs: Any) -> str:
        recent = list(self.engine.entropy_history)
        low_trust_forced = self.engine.trust < LOW_TRUST_TRUNCATE_FLOOR
        return (
            f"RHEA Status\n"
            f"-----------\n"
            f"Trust: {self.engine.trust:.4f}\n"
            f"Recent Entropy Samples: {recent}\n"
            f"Working Directory: {self.cwd}\n"
            f"Truncation Enabled: {self.truncation_enabled}\n"
            f"Output Limit: {self.max_output_chars}\n"
            f"Low-Trust Output Guard Active: {low_trust_forced}\n"
            f"Diff Preview Enabled: {self.diff_preview_enabled}\n"
            f"Show Future Diffs This Session: {self.show_future_diffs}\n"
            f"Git Mode: {self.git_mode}\n"
            f"Selection Active: {self.selection is not None}"
        )

    def tool_history(self, **kwargs: Any) -> str:
        if not self.command_log:
            return "No command history yet."
        lines = ["Recent Commands:"]
        for i, entry in enumerate(self.command_log, 1):
            lines.append(f"{i:02d}. {entry}")
        return "\n".join(lines)

    def tool_no_truncate(self, **kwargs: Any) -> str:
        self.truncation_enabled = False
        return "Truncation disabled. Full output enabled."

    def tool_truncate_on(self, **kwargs: Any) -> str:
        self.truncation_enabled = True
        return f"Truncation enabled (limit={self.max_output_chars})"

    def tool_set_limit(self, cmd: Optional[str] = None, **kwargs: Any) -> str:
        if not cmd:
            return "Usage: set limit <number>"

        parts = cmd.split()
        try:
            value = int(parts[-1])
            if value <= 0:
                return "Limit must be a positive integer."
            self.max_output_chars = value
            return f"Output limit set to {value} characters"
        except (ValueError, IndexError):
            return "Usage: set limit <number>"

    def tool_diff_on(self, **kwargs: Any) -> str:
        self.diff_preview_enabled = True
        self.show_future_diffs = True
        return "Preview diff confirmation enabled."

    def tool_diff_off(self, **kwargs: Any) -> str:
        self.diff_preview_enabled = False
        return "Preview diff confirmation disabled."

    def tool_help(self, **kwargs: Any) -> str:
        return (
            "RHEA Code CLI Help\n"
            "------------------\n"
            "Read / output:\n"
            "  read RHEA_Code-CLI.py\n"
            "  read RHEA_Code-CLI.py full\n"
            "  read RHEA_Code-CLI.py pager\n"
            "  full output\n"
            "  truncate on\n"
            "  set limit 10000\n"
            "\n"
            "Diff preview:\n"
            "  diff on\n"
            "  diff off\n"
            "  Prompt: y / n / s / d\n"
            "\n"
            "Directory / shell:\n"
            "  list\n"
            "  list src\n"
            "  pwd\n"
            "  run python RHEA_Code-CLI.py\n"
            "  git status\n"
            "\n"
            "Whole-file edit / paste:\n"
            "  write RHEA_Code-CLI.py \"print('hello')\"\n"
            "  append RHEA_Code-CLI.py \"\\nprint('world')\"\n"
            "  write RHEA_Code-CLI.py pastefile\n"
            "  pastefile RHEA_Code-CLI.py\n"
            "  pasteappend RHEA_Code-CLI.py\n"
            "  __END__\n"
            "\n"
            "Text addressing:\n"
            "  list lines RHEA_Code-CLI.py\n"
            "  read line RHEA_Code-CLI.py 10\n"
            "  read lines RHEA_Code-CLI.py 10:20\n"
            "  replace line RHEA_Code-CLI.py 10 \"new text\"\n"
            "  replace lines RHEA_Code-CLI.py 10:12 pastefile\n"
            "  replace char RHEA_Code-CLI.py 10 8 \"X\"\n"
            "  insert char RHEA_Code-CLI.py 10 8 \"(\"\n"
            "  delete char RHEA_Code-CLI.py 10 8\n"
            "  replace word RHEA_Code-CLI.py 10 \"trust\" \"signal\"\n"
            "  replace word RHEA_Code-CLI.py all \"old\" \"new\"\n"
            "\n"
            "Python object listing:\n"
            "  list defs RHEA_Code-CLI.py\n"
            "  list classes RHEA_Code-CLI.py\n"
            "  list dataclasses RHEA_Code-CLI.py\n"
            "  list methods RHEA_Code-CLI.py RHEACodeCLI\n"
            "  list async defs RHEA_Code-CLI.py\n"
            "\n"
            "Python object reading:\n"
            "  read def RHEA_Code-CLI.py compute_entropy\n"
            "  read class RHEA_Code-CLI.py RHEACodeCLI\n"
            "  read dataclass RHEA_Code-CLI.py CodeObject\n"
            "  read method RHEA_Code-CLI.py RHEACodeCLI tool_help\n"
            "  read def RHEA_Code-CLI.py tool_help   # falls back to unique method if applicable\n"
            "\n"
            "Python object replacing:\n"
            "  replace def RHEA_Code-CLI.py compute_entropy pastefile\n"
            "  replace class RHEA_Code-CLI.py RHEACodeCLI pastefile\n"
            "  replace dataclass RHEA_Code-CLI.py CodeObject pastefile\n"
            "  replace method RHEA_Code-CLI.py RHEACodeCLI tool_help pastefile\n"
            "\n"
            "Selection:\n"
            "  select def RHEA_Code-CLI.py compute_entropy\n"
            "  select class RHEA_Code-CLI.py RHEACodeCLI\n"
            "  select method RHEA_Code-CLI.py RHEACodeCLI tool_help\n"
            "  select def RHEA_Code-CLI.py tool_help   # falls back to unique method if applicable\n"
            "  show selection\n"
            "  read selection\n"
            "  replace selection pastefile\n"
            "\n"
            "VCS / Git:\n"
            "  vcs status\n"
            "  vcs diff\n"
            "  vcs diff fun.py\n"
            "  vcs diff --cached\n"
            "  vcs log\n"
            "  vcs log 15\n"
            "  vcs filelog fun.py\n"
            "  checkpoint\n"
            "  checkpoint now\n"
            "  checkpoint before parser rewrite\n"
            "  rollback show\n"
            "  rollback show 30\n"
            "  rollback file fun.py\n"
            "  rollback last\n"
            "  rollback to abc1234\n"
            "  git mode\n"
            "  git mode off\n"
            "  git mode manual\n"
            "  git mode checkpoint_only\n"
            "  git mode auto_commit\n"
            + self.registry.get_help_text()
        )

    # ---------------------- Command Extraction ----------------------

    def _extract_args(self, role: str, raw_cmd: str) -> dict:
        stripped = raw_cmd.strip()

        if role == "list":
            return {"path": self._extract_path_for_list(stripped)}
        if role == "read":
            return self._extract_read_args(stripped)
        if role == "edit":
            return self._extract_edit_args(stripped)

        if role == "replace":
            return self._extract_replace_args(stripped)
        if role == "replace_line":
            return self._extract_replace_line_args(stripped)
        if role == "replace_lines":
            return self._extract_replace_lines_args(stripped)
        if role == "replace_char":
            return self._extract_replace_char_args(stripped)
        if role == "insert_char":
            return self._extract_insert_char_args(stripped)
        if role == "delete_char":
            return self._extract_delete_char_args(stripped)
        if role == "replace_word":
            return self._extract_replace_word_args(stripped)

        if role == "insert_after":
            return self._extract_insert_args(stripped, after=True)
        if role == "insert_before":
            return self._extract_insert_args(stripped, after=False)
        if role == "prepend":
            return self._extract_prepend_args(stripped)

        if role == "pastefile":
            return self._extract_paste_args(stripped)
        if role == "pasteappend":
            return self._extract_paste_args(stripped)

        if role == "list_defs":
            return self._extract_single_file_arg_after_two_tokens(stripped)
        if role == "list_classes":
            return self._extract_single_file_arg_after_two_tokens(stripped)
        if role == "list_dataclasses":
            return self._extract_single_file_arg_after_two_tokens(stripped)
        if role == "list_async_defs":
            return self._extract_single_file_arg_after_three_tokens(stripped)
        if role == "list_methods":
            return self._extract_list_methods_args(stripped)
        if role == "list_lines":
            return self._extract_single_file_arg_after_two_tokens(stripped)

        if role == "read_line":
            return self._extract_read_line_args(stripped)
        if role == "read_lines":
            return self._extract_read_lines_args(stripped)
        if role == "read_def":
            return self._extract_read_named_object_args(stripped, "def")
        if role == "read_class":
            return self._extract_read_named_object_args(stripped, "class")
        if role == "read_dataclass":
            return self._extract_read_named_object_args(stripped, "dataclass")
        if role == "read_method":
            return self._extract_read_method_args(stripped)

        if role == "replace_def":
            return self._extract_replace_named_object_args(stripped, "def")
        if role == "replace_class":
            return self._extract_replace_named_object_args(stripped, "class")
        if role == "replace_dataclass":
            return self._extract_replace_named_object_args(stripped, "dataclass")
        if role == "replace_method":
            return self._extract_replace_method_args(stripped)

        if role == "select_object":
            return self._extract_select_object_args(stripped)
        if role == "replace_selection":
            return self._extract_replace_selection_args(stripped)

        if role == "vcs_status":
            return {}
        if role == "vcs_diff":
            return self._extract_vcs_diff_args(stripped)
        if role == "vcs_log":
            return self._extract_vcs_log_args(stripped)
        if role == "vcs_filelog":
            return self._extract_vcs_filelog_args(stripped)
        if role == "checkpoint":
            return self._extract_checkpoint_args(stripped)
        if role == "rollback_show":
            return self._extract_rollback_show_args(stripped)
        if role == "rollback_last":
            return {}
        if role == "rollback_file":
            return self._extract_rollback_file_args(stripped)
        if role == "rollback_to":
            return self._extract_rollback_to_args(stripped)
        if role == "git_mode":
            return self._extract_git_mode_args(stripped)

        if role == "run":
            return {"cmd": self._extract_run_command(stripped)}
        if role == "git":
            return {"cmd": self._extract_git_command(stripped)}
        if role == "set_limit":
            return {"cmd": stripped}

        return {}

    def _safe_split(self, text: str) -> list[str]:
        try:
            return shlex.split(text)
        except ValueError:
            return text.split()

    def _extract_path_for_list(self, text: str) -> Optional[str]:
        tokens = self._safe_split(text)
        for i, token in enumerate(tokens):
            if token.lower() in {"list", "ls", "dir", "files", "directory"} and i + 1 < len(tokens):
                return tokens[i + 1]
        return None

    def _extract_read_args(self, text: str) -> dict:
        tokens = self._safe_split(text)
        lowered = [t.lower() for t in tokens]

        file_name: Optional[str] = None
        pager = "pager" in lowered
        full = "full" in lowered or "all" in lowered

        for i, token in enumerate(lowered):
            if token in {"read", "cat", "show", "view", "open"}:
                if i + 1 < len(tokens):
                    candidate = tokens[i + 1]
                    if candidate.lower() not in {"pager", "full", "all"}:
                        file_name = candidate
                break

        if not file_name:
            for token in tokens:
                if token.lower() not in {"read", "cat", "show", "view", "open", "pager", "full", "all"}:
                    file_name = token
                    break

        return {"file": file_name, "pager": pager, "full": full}

    def _extract_edit_args(self, text: str) -> dict:
        tokens = self._safe_split(text)
        lowered = [t.lower() for t in tokens]

        file_name: Optional[str] = None
        content: Optional[str] = None
        append = False
        content_mode: Optional[str] = None

        if not tokens:
            return {"file": None, "content": None, "append": False, "content_mode": None}

        verb = lowered[0]
        if verb == "append":
            append = True

        if verb in {"edit", "write", "change", "update", "append", "create"}:
            if len(tokens) >= 2:
                file_name = tokens[1]

            if len(tokens) >= 3 and lowered[2] in {"pastefile", "pasteappend"}:
                content_mode = lowered[2]
                if content_mode == "pasteappend":
                    append = True
                inline = self._extract_inline_after_marker(text, tokens[2])
                content = inline if inline else None
            elif len(tokens) >= 3:
                content = " ".join(tokens[2:])

        return {"file": file_name, "content": content, "append": append, "content_mode": content_mode}

    def _extract_replace_args(self, text: str) -> dict:
        tokens = self._safe_split(text)
        if len(tokens) < 5:
            return {"file": None, "old": None, "new": None}

        if tokens[0].lower() == "replace" and tokens[1].lower() == "in":
            return {"file": tokens[2], "old": tokens[3], "new": tokens[4]}

        return {"file": None, "old": None, "new": None}

    def _extract_insert_args(self, text: str, after: bool) -> dict:
        tokens = self._safe_split(text)
        if len(tokens) < 5:
            return {"file": None, "anchor": None, "content": None}

        expected = "after" if after else "before"
        if tokens[0].lower() == "insert" and tokens[1].lower() == expected:
            return {"file": tokens[2], "anchor": tokens[3], "content": tokens[4]}

        return {"file": None, "anchor": None, "content": None}

    def _extract_prepend_args(self, text: str) -> dict:
        tokens = self._safe_split(text)
        if len(tokens) < 3:
            return {"file": None, "content": None}
        return {"file": tokens[1], "content": " ".join(tokens[2:])}

    def _extract_paste_args(self, text: str) -> dict:
        tokens = self._safe_split(text)
        if len(tokens) < 2:
            return {"file": None, "initial_content": None}

        initial_content = None
        if len(tokens) >= 3:
            initial_content = self._extract_inline_after_marker(text, tokens[1])

        return {"file": tokens[1], "initial_content": initial_content}

    def _extract_single_file_arg_after_two_tokens(self, text: str) -> dict:
        tokens = self._safe_split(text)
        return {"file": tokens[2]} if len(tokens) >= 3 else {"file": None}


    def _extract_single_file_arg_after_three_tokens(self, text: str) -> dict:
        tokens = self._safe_split(text)
        return {"file": tokens[3]} if len(tokens) >= 4 else {"file": None}

    def _extract_list_methods_args(self, text: str) -> dict:
        tokens = self._safe_split(text)
        if len(tokens) >= 4:
            return {"file": tokens[2], "class_name": tokens[3]}
        if len(tokens) >= 3:
            return {"file": tokens[2], "class_name": None}
        return {"file": None, "class_name": None}

    def _extract_read_line_args(self, text: str) -> dict:
        tokens = self._safe_split(text)
        if len(tokens) < 4:
            return {"file": None, "line_no": None}
        return {"file": tokens[2], "line_no": int(tokens[3])}

    def _extract_read_lines_args(self, text: str) -> dict:
        tokens = self._safe_split(text)
        if len(tokens) < 4:
            return {"file": None, "start_line": None, "end_line": None}
        start, end = self._parse_line_range(tokens[3])
        return {"file": tokens[2], "start_line": start, "end_line": end}

    def _extract_read_named_object_args(self, text: str, kind: str) -> dict:
        tokens = self._safe_split(text)
        if len(tokens) < 4:
            return {"file": None, "name": None}
        return {"file": tokens[2], "name": tokens[3]}

    def _extract_read_method_args(self, text: str) -> dict:
        tokens = self._safe_split(text)
        if len(tokens) < 5:
            return {"file": None, "class_name": None, "method_name": None}
        return {"file": tokens[2], "class_name": tokens[3], "method_name": tokens[4]}

    def _extract_replace_named_object_args(self, text: str, kind: str) -> dict:
        tokens = self._safe_split(text)
        if len(tokens) < 5:
            return {"file": None, "name": None, "replacement": None, "content_mode": None}

        file = tokens[2]
        name = tokens[3]
        replacement = None
        content_mode = None

        if tokens[4].lower() == "pastefile":
            content_mode = "pastefile"
            inline = self._extract_inline_after_marker(text, tokens[4])
            replacement = inline if inline else None
        else:
            replacement = " ".join(tokens[4:])

        return {"file": file, "name": name, "replacement": replacement, "content_mode": content_mode}

    def _extract_replace_method_args(self, text: str) -> dict:
        tokens = self._safe_split(text)
        if len(tokens) < 6:
            return {
                "file": None,
                "class_name": None,
                "method_name": None,
                "replacement": None,
                "content_mode": None,
            }

        file = tokens[2]
        class_name = tokens[3]
        method_name = tokens[4]
        replacement = None
        content_mode = None

        if tokens[5].lower() == "pastefile":
            content_mode = "pastefile"
            inline = self._extract_inline_after_marker(text, tokens[5])
            replacement = inline if inline else None
        else:
            replacement = " ".join(tokens[5:])

        return {
            "file": file,
            "class_name": class_name,
            "method_name": method_name,
            "replacement": replacement,
            "content_mode": content_mode,
        }

    def _extract_replace_line_args(self, text: str) -> dict:
        tokens = self._safe_split(text)
        if len(tokens) < 5:
            return {"file": None, "line_no": None, "replacement": None, "content_mode": None}

        if tokens[4].lower() == "pastefile":
            content_mode = "pastefile"
            inline = self._extract_inline_after_marker(text, tokens[4])
            return {
                "file": tokens[2],
                "line_no": int(tokens[3]),
                "replacement": inline if inline else None,
                "content_mode": content_mode,
            }

        return {
            "file": tokens[2],
            "line_no": int(tokens[3]),
            "replacement": " ".join(tokens[4:]),
            "content_mode": None,
        }

    def _extract_replace_lines_args(self, text: str) -> dict:
        tokens = self._safe_split(text)
        if len(tokens) < 5:
            return {"file": None, "start_line": None, "end_line": None, "replacement": None, "content_mode": None}

        start, end = self._parse_line_range(tokens[3])

        if tokens[4].lower() == "pastefile":
            content_mode = "pastefile"
            inline = self._extract_inline_after_marker(text, tokens[4])
            return {
                "file": tokens[2],
                "start_line": start,
                "end_line": end,
                "replacement": inline if inline else None,
                "content_mode": content_mode,
            }

        return {
            "file": tokens[2],
            "start_line": start,
            "end_line": end,
            "replacement": " ".join(tokens[4:]),
            "content_mode": None,
        }

    def _extract_replace_char_args(self, text: str) -> dict:
        tokens = self._safe_split(text)
        if len(tokens) < 6:
            return {"file": None, "line_no": None, "char_pos": None, "new_char": None}
        return {
            "file": tokens[2],
            "line_no": int(tokens[3]),
            "char_pos": int(tokens[4]),
            "new_char": tokens[5],
        }

    def _extract_insert_char_args(self, text: str) -> dict:
        tokens = self._safe_split(text)
        if len(tokens) < 6:
            return {"file": None, "line_no": None, "char_pos": None, "char": None}
        return {
            "file": tokens[2],
            "line_no": int(tokens[3]),
            "char_pos": int(tokens[4]),
            "char": tokens[5],
        }

    def _extract_delete_char_args(self, text: str) -> dict:
        tokens = self._safe_split(text)
        if len(tokens) < 5:
            return {"file": None, "line_no": None, "char_pos": None}
        return {
            "file": tokens[2],
            "line_no": int(tokens[3]),
            "char_pos": int(tokens[4]),
        }

    def _extract_replace_word_args(self, text: str) -> dict:
        tokens = self._safe_split(text)
        if len(tokens) < 6:
            return {"file": None, "scope": None, "old": None, "new": None}
        return {
            "file": tokens[2],
            "scope": tokens[3],
            "old": tokens[4],
            "new": tokens[5],
        }

    def _extract_select_object_args(self, text: str) -> dict:
        tokens = self._safe_split(text)
        if len(tokens) < 4:
            return {"kind": None, "file": None, "name": None, "parent": None}

        kind = tokens[1].lower()

        if kind == "method":
            if len(tokens) < 5:
                return {"kind": "method", "file": None, "name": None, "parent": None}
            return {
                "kind": "method",
                "file": tokens[2],
                "name": tokens[4],
                "parent": tokens[3],
            }

        return {
            "kind": kind,
            "file": tokens[2],
            "name": tokens[3],
            "parent": None,
        }

    def _extract_replace_selection_args(self, text: str) -> dict:
        tokens = self._safe_split(text)
        if len(tokens) < 3:
            return {"replacement": None, "content_mode": None}

        if tokens[2].lower() == "pastefile":
            inline = self._extract_inline_after_marker(text, tokens[2])
            return {"replacement": inline if inline else None, "content_mode": "pastefile"}

        return {"replacement": " ".join(tokens[2:]), "content_mode": None}

    def _extract_vcs_diff_args(self, text: str) -> dict:
        tokens = self._safe_split(text)
        cached = "--cached" in tokens
        file = None
        for token in tokens[2:]:
            if token != "--cached":
                file = token
                break
        return {"file": file, "cached": cached}

    def _extract_vcs_log_args(self, text: str) -> dict:
        tokens = self._safe_split(text)
        limit = 10
        if len(tokens) >= 3:
            try:
                limit = int(tokens[2])
            except ValueError:
                pass
        return {"limit": limit}

    def _extract_vcs_filelog_args(self, text: str) -> dict:
        tokens = self._safe_split(text)
        file = None
        limit = 10
        if len(tokens) >= 3:
            file = tokens[2]
        if len(tokens) >= 4:
            try:
                limit = int(tokens[3])
            except ValueError:
                pass
        return {"file": file, "limit": limit}

    def _extract_checkpoint_args(self, text: str) -> dict:
        tokens = self._safe_split(text)
        note = None
        if len(tokens) >= 2:
            if tokens[1].lower() == "now":
                note = None
            else:
                note = " ".join(tokens[1:])
        return {"note": note}

    def _extract_rollback_show_args(self, text: str) -> dict:
        tokens = self._safe_split(text)
        limit = 20
        if len(tokens) >= 3:
            try:
                limit = int(tokens[2])
            except ValueError:
                pass
        return {"limit": limit}

    def _extract_rollback_file_args(self, text: str) -> dict:
        tokens = self._safe_split(text)
        file = tokens[2] if len(tokens) >= 3 else None
        return {"file": file}

    def _extract_rollback_to_args(self, text: str) -> dict:
        tokens = self._safe_split(text)
        commit = tokens[2] if len(tokens) >= 3 else None
        return {"commit": commit}

    def _extract_git_mode_args(self, text: str) -> dict:
        tokens = self._safe_split(text)
        mode = tokens[2] if len(tokens) >= 3 else None
        return {"mode": mode}

    def _extract_run_command(self, text: str) -> Optional[str]:
        lowered = text.lower()
        prefixes = ["run ", "execute ", "test ", "shell ", "cmd "]
        for prefix in prefixes:
            if lowered.startswith(prefix):
                return text[len(prefix):].strip()
        if lowered.startswith("python "):
            return text
        return None

    def _extract_git_command(self, text: str) -> Optional[str]:
        stripped = text.strip()
        lowered = stripped.lower()

        if lowered == "git":
            return "git status"

        idx = lowered.find("git")
        if idx >= 0:
            git_cmd = stripped[idx:].strip()
            return git_cmd if git_cmd else "git status"

        return "git status"

    # ---------------------- Loop ----------------------

    def run(self) -> None:
        while True:
            try:
                cmd = input("RHEA> ").strip()

                if cmd.lower() in {"exit", "quit"}:
                    print("RHEA session ended.")
                    break

                if not cmd:
                    continue

                self.command_log.append(cmd)

                glyph_data = self.parser.parse(cmd)
                print(
                    f"[{glyph_data['trust_glyph']}] "
                    f"Trust: {glyph_data['trust']:.4f} | "
                    f"Entropy: {glyph_data['entropy']:.4f} | "
                    f"Role: {glyph_data['role']}"
                )

                import time

                start = time.perf_counter()
                result = ""
                exc: Optional[BaseException] = None

                try:
                    args = self._extract_args(glyph_data["role"], cmd)
                    result = self.registry.execute(glyph_data["role"], args)

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
                        result = self._format_output(result)

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

                    print(result)
                    print()

                except Exception as e:
                    exc = e
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

                        print(self._format_output(self.last_trace_report, force_full=False))
                        print()
                    else:
                        print(f"Error: {e}")
                        print()

            except KeyboardInterrupt:
                print("\nSession terminated.")
                break
            except EOFError:
                print("\nSession terminated.")
                break


if __name__ == "__main__":
    cli = RHEACodeCLI()
    cli.run()