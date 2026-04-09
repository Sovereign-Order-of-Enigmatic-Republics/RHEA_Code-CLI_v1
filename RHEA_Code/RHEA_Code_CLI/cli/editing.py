# -*- coding: utf-8 -*-
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from RHEA_Code_CLI.diff.diff_ops import build_unified_diff
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

        start_line = node.lineno
        if node.decorator_list:
            try:
                start_line = min(getattr(dec, "lineno", node.lineno) for dec in node.decorator_list)
            except Exception:
                start_line = node.lineno

        self.objects.append(
            CodeObject(
                kind=kind,
                name=node.name,
                start_line=start_line,
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


class EditingMixin:
    # ---------------------- File / Text Helpers ----------------------

    def _resolve_file(self, file: Optional[str]) -> Optional[Path]:
        safe_file = self._validate_user_token(file, "file path") if file is not None else None
        return resolve_file(self.cwd, safe_file)

    def _read_text_file(self, target: Path) -> str:
        return read_text_file(target)

    def _write_text_file(self, target: Path, content: str) -> None:
        write_text_file(target, content)

    def _safe_existing_text(self, target: Path) -> str:
        return safe_existing_text(target)

    def _split_lines_keepends(self, text: str) -> list[str]:
        return split_lines_keepends(text)

    def _ensure_python_file(self, target: Path) -> Optional[str]:
        return ensure_python_file(target)

    def _extract_line_range(self, text: str, start_line: int, end_line: int) -> str:
        return extract_line_range(text, start_line, end_line)

    def _replace_line_range(self, text: str, start_line: int, end_line: int, replacement: str) -> str:
        return replace_line_range(text, start_line, end_line, replacement)

    def _normalize_escaped_newlines(self, content: Optional[str], content_mode: Optional[str] = None) -> Optional[str]:
        if content is None:
            return None
        if content_mode == "pastefile":
            return content
        if "\\n" in content:
            return content.replace("\\n", "\n")
        return content

    def _join_for_append(self, old_text: str, payload: str) -> str:
        if not old_text:
            return payload
        if not payload:
            return old_text
        if not old_text.endswith(("\n", "\r")) and not payload.startswith(("\n", "\r")):
            return old_text + "\n" + payload
        return old_text + payload

    def _collect_multiline_input(
        self,
        sentinel: str = "__END__",
        initial_content: Optional[str] = None,
    ) -> str:
        self._out(f"Paste content below. End with a line containing only {sentinel}")
        lines: list[str] = []

        if initial_content:
            lines.append(initial_content)

        while True:
            try:
                line = input()
            except EOFError:
                break
            if line == sentinel:
                break
            if "\x00" in line:
                raise ValueError("Unsafe pasted content: null byte is not allowed")
            lines.append(line)

        return "\n".join(lines)

    def _build_unified_diff(self, target: Path, old_text: str, new_text: str) -> str:
        return build_unified_diff(target, old_text, new_text)

    def _confirm_change(self, target: Path, old_text: str, new_text: str) -> tuple[bool, str]:
        if old_text == new_text:
            return False, f"No changes to apply for {target}"

        if not self.diff_preview_enabled or not self.show_future_diffs:
            return True, "Change applied."

        diff_text = self._build_unified_diff(target, old_text, new_text)
        self._out("Preview diff:")
        self._out("-" * 88)
        self._out(diff_text)
        self._out("-" * 88)

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
                self._out("-" * 88)
                self._out(diff_text)
                self._out("-" * 88)
                continue

            self._out("Please enter y, n, s, or d.")

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

    def _finalize_edit_result(
        self,
        *,
        result: str,
        success_suffix: str,
        op: str,
        file: Optional[str] = None,
        target: Optional[str] = None,
        lines: Optional[str] = None,
        checkpoint_note: str = "",
    ) -> str:
        if not result.startswith("Change applied"):
            return result

        commit_note = self._maybe_commit_after_edit(
            op=op,
            file=file,
            target=target,
            lines=lines,
        )

        prefix_parts = []
        if checkpoint_note:
            prefix_parts.append(checkpoint_note)
        if commit_note:
            prefix_parts.append(commit_note)

        prefix = ("\n".join(prefix_parts) + "\n") if prefix_parts else ""
        return f"{prefix}{result} {success_suffix}"

    # ---------------------- Python Code Index Helpers ----------------------

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

    def _read_text_range(self, target: Path, start_line: int, end_line: int) -> str:
        text = self._safe_existing_text(target)
        lines = self._split_lines_keepends(text)
        if start_line < 1 or end_line < start_line or end_line > len(lines):
            return "Line range out of bounds"

        out = [f"--- {target.name} | lines {start_line}:{end_line} ---"]
        for i in range(start_line, end_line + 1):
            out.append(f"{i:04d}: {lines[i - 1].rstrip()}")
        return "\n".join(out)

        # ---------------------- Generic File Listing / Reading ----------------------

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

    # ---------------------- Generic File Editing ----------------------

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

        checkpoint_note = self._maybe_checkpoint_before_edit(op="edit", file=file)

        if content_mode in {"pastefile", "pasteappend"}:
            payload = self._collect_multiline_input(initial_content=content)
            do_append = append or (content_mode == "pasteappend")
            new_text = self._join_for_append(old_text, payload) if do_append else payload

            result = self._apply_change_with_preview(target, new_text)
            if not result.startswith("Change applied"):
                return result

            commit_note = self._maybe_commit_after_edit(
                op="edit",
                file=file,
            )

            prefix_parts = []
            if checkpoint_note:
                prefix_parts.append(checkpoint_note)
            if commit_note:
                prefix_parts.append(commit_note)
            prefix = ("\n".join(prefix_parts) + "\n") if prefix_parts else ""

            if do_append:
                return f"{prefix}{result} Appended pasted content to {target}"
            return f"{prefix}{result} Wrote pasted content to {target}"

        payload = self._normalize_escaped_newlines(content or "# RHEA edit\n", content_mode)
        new_text = self._join_for_append(old_text, payload or "") if append else (payload or "")

        result = self._apply_change_with_preview(target, new_text)
        if not result.startswith("Change applied"):
            return result

        commit_note = self._maybe_commit_after_edit(
            op="edit",
            file=file,
        )

        prefix_parts = []
        if checkpoint_note:
            prefix_parts.append(checkpoint_note)
        if commit_note:
            prefix_parts.append(commit_note)
        prefix = ("\n".join(prefix_parts) + "\n") if prefix_parts else ""

        if append:
            return f"{prefix}{result} Appended to {target}"
        return f"{prefix}{result} Wrote {target}"

    def tool_write(self, file: str, content: str = "", **kwargs: Any) -> str:
        return self.tool_edit(file=file, content=content, append=False, **kwargs)

    def tool_append(self, file: str, content: str = "", **kwargs: Any) -> str:
        return self.tool_edit(file=file, content=content, append=True, **kwargs)

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

        checkpoint_note = self._maybe_checkpoint_before_edit(op="replace", file=file)
        updated = text.replace(old, new) if count == -1 else text.replace(old, new, count)
        replaced = occurrences if count == -1 else min(occurrences, count)

        result = self._apply_change_with_preview(target, updated)
        return self._finalize_edit_result(
            result=result,
            success_suffix=f"Replaced {replaced} occurrence(s) in {target}",
            op="replace",
            file=file,
            checkpoint_note=checkpoint_note,
        )

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

        checkpoint_note = self._maybe_checkpoint_before_edit(
            op="insert_before" if before else "insert_after",
            file=file,
        )

        if before:
            updated = text[:idx] + content + text[idx:]
            action = "Inserted before"
        else:
            insert_pos = idx + len(anchor)
            updated = text[:insert_pos] + content + text[insert_pos:]
            action = "Inserted after"

        result = self._apply_change_with_preview(target, updated)
        return self._finalize_edit_result(
            result=result,
            success_suffix=f'{action} anchor in {target.name}: "{anchor}"',
            op="insert_before" if before else "insert_after",
            file=file,
            checkpoint_note=checkpoint_note,
        )

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

        checkpoint_note = self._maybe_checkpoint_before_edit(op="prepend", file=file)
        updated = content + existing
        result = self._apply_change_with_preview(target, updated)
        return self._finalize_edit_result(
            result=result,
            success_suffix=f"Prepended content to {target}",
            op="prepend",
            file=file,
            checkpoint_note=checkpoint_note,
        )

    def tool_pastefile(
        self,
        file: Optional[str] = None,
        initial_content: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        target = self._resolve_file(file)
        if not target:
            return "Paste failed - no file specified"

        checkpoint_note = self._maybe_checkpoint_before_edit(op="pastefile", file=file)
        content = self._collect_multiline_input(initial_content=initial_content)

        result = self._apply_change_with_preview(target, content)
        if not result.startswith("Change applied"):
            return result

        commit_note = self._maybe_commit_after_edit(
            op="pastefile",
            file=file,
        )

        prefix_parts = []
        if checkpoint_note:
            prefix_parts.append(checkpoint_note)
        if commit_note:
            prefix_parts.append(commit_note)
        prefix = ("\n".join(prefix_parts) + "\n") if prefix_parts else ""

        return f"{prefix}{result} Wrote pasted content to {target}"

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

        checkpoint_note = self._maybe_checkpoint_before_edit(op="pasteappend", file=file)
        content = self._collect_multiline_input(initial_content=initial_content)
        updated = self._join_for_append(old_text, content)

        result = self._apply_change_with_preview(target, updated)
        if not result.startswith("Change applied"):
            return result

        commit_note = self._maybe_commit_after_edit(
            op="pasteappend",
            file=file,
        )

        prefix_parts = []
        if checkpoint_note:
            prefix_parts.append(checkpoint_note)
        if commit_note:
            prefix_parts.append(commit_note)
        prefix = ("\n".join(prefix_parts) + "\n") if prefix_parts else ""

        return f"{prefix}{result} Appended pasted content to {target}"

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
        repl = self._normalize_escaped_newlines(repl, content_mode)
        if repl is None:
            return "No replacement content provided"

        obj = self._find_code_object(target, "method", method_name, class_name)
        kind = "method"
        if not obj:
            obj = self._find_code_object(target, "async_method", method_name, class_name)
            kind = "async_method"
        if not obj:
            return f"Method not found: {class_name}.{method_name}"

        checkpoint_note = self._maybe_checkpoint_before_edit(
            op="replace_method",
            file=file,
            target=f"{class_name}.{method_name}",
        )

        result = self._replace_code_object(target, kind, method_name, repl, class_name)
        return self._finalize_edit_result(
            result=result,
            success_suffix="",
            op="replace_method",
            file=file,
            target=f"{class_name}.{method_name}",
            checkpoint_note=checkpoint_note,
        ).rstrip()

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
        repl = self._normalize_escaped_newlines(repl, content_mode)
        if repl is None:
            return "No replacement content provided"

        checkpoint_note = self._maybe_checkpoint_before_edit(
            op=f"replace_{kind}",
            file=file,
            target=name,
        )

        result = self._replace_code_object(target, kind, name, repl)
        return self._finalize_edit_result(
            result=result,
            success_suffix="",
            op=f"replace_{kind}",
            file=file,
            target=name,
            checkpoint_note=checkpoint_note,
        ).rstrip()

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
        repl = self._normalize_escaped_newlines(repl, content_mode)
        if repl is None:
            return "No replacement content provided"

        checkpoint_note = self._maybe_checkpoint_before_edit(
            op="replace_line",
            file=file,
            lines=str(line_no),
        )

        try:
            new_text = self._replace_line(old_text, line_no, repl)
        except ValueError as e:
            return str(e)

        result = self._apply_change_with_preview(target, new_text)
        return self._finalize_edit_result(
            result=result,
            success_suffix=f"Replaced line {line_no} in {target}",
            op="replace_line",
            file=file,
            lines=str(line_no),
            checkpoint_note=checkpoint_note,
        )

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
        repl = self._normalize_escaped_newlines(repl, content_mode)
        if repl is None:
            return "No replacement content provided"

        checkpoint_note = self._maybe_checkpoint_before_edit(
            op="replace_lines",
            file=file,
            lines=f"{start_line}:{end_line}",
        )

        try:
            new_text = self._replace_lines(old_text, start_line, end_line, repl)
        except ValueError as e:
            return str(e)

        result = self._apply_change_with_preview(target, new_text)
        return self._finalize_edit_result(
            result=result,
            success_suffix=f"Replaced lines {start_line}:{end_line} in {target}",
            op="replace_lines",
            file=file,
            lines=f"{start_line}:{end_line}",
            checkpoint_note=checkpoint_note,
        )

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

        checkpoint_note = self._maybe_checkpoint_before_edit(
            op=f"{mode}_char",
            file=file,
            lines=str(line_no),
        )

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

        mode_word = {
            "replace": "Replaced",
            "insert": "Inserted",
            "delete": "Deleted",
        }.get(mode, mode.title())

        return self._finalize_edit_result(
            result=result,
            success_suffix=f"{mode_word} char at line {line_no}, char {char_pos} in {target}",
            op=f"{mode}_char",
            file=file,
            lines=str(line_no),
            checkpoint_note=checkpoint_note,
        )

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

        checkpoint_note = self._maybe_checkpoint_before_edit(
            op="replace_word",
            file=file,
            lines=str(scope),
        )

        try:
            if str(scope).lower() == "all":
                new_text = self._replace_word_in_file(old_text, old, new, True)
            else:
                line_no = int(str(scope))
                new_text = self._replace_word_in_line(old_text, line_no, old, new, True)
        except ValueError as e:
            return str(e)

        result = self._apply_change_with_preview(target, new_text)
        return self._finalize_edit_result(
            result=result,
            success_suffix=f"Replaced word in {target}",
            op="replace_word",
            file=file,
            lines=str(scope),
            checkpoint_note=checkpoint_note,
        )

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
        repl = self._normalize_escaped_newlines(repl, content_mode)
        if repl is None:
            return "No replacement content provided"

        checkpoint_note = self._maybe_checkpoint_before_edit(
            op="replace_selection",
            file=target.name,
            lines=f"{self.selection['start_line']}:{self.selection['end_line']}",
        )

        new_text = self._replace_line_range(
            old_text,
            self.selection["start_line"],
            self.selection["end_line"],
            repl,
        )
        result = self._apply_change_with_preview(target, new_text)
        return self._finalize_edit_result(
            result=result,
            success_suffix=f"Replaced current selection in {target}",
            op="replace_selection",
            file=target.name,
            lines=f"{self.selection['start_line']}:{self.selection['end_line']}",
            checkpoint_note=checkpoint_note,
        )