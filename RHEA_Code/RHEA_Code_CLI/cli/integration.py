# -*- coding: utf-8 -*-
from __future__ import annotations

import ast
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

from RHEA_Code_CLI.vcs.git_ops import (
    get_current_branch,
    git_commit,
    git_diff,
    git_stage_file,
    git_status,
    is_git_available,
    is_git_repo,
    run_git_command,
    working_tree_dirty,
)
from RHEA_Code_CLI.vcs.git_history import (
    build_checkpoint_message,
    get_checkpoint_log,
    get_file_history,
)
from RHEA_Code_CLI.vcs.git_policy import (
    normalize_git_mode,
    should_checkpoint_before_edit,
)
from RHEA_Code_CLI.vcs.rollback_ops import (
    rollback_file_preview,
    rollback_file_to_head,
    rollback_last_hard,
    rollback_last_preview,
    rollback_show,
    rollback_to_commit_hard,
    rollback_to_commit_preview,
)

from .planner import TaskPlanner 
from .task_executor import TaskExecutor
from .workspace import WorkspaceInspector


class IntegrationMixin:
    def _register_tools(self) -> None:
        self.registry.register("list", self.tool_list, "List current directory contents")
        self.registry.register("read", self.tool_read, "Read a file (supports 'pager' and 'full')")
        self.registry.register("edit", self.tool_edit, "Write, append, or paste content to a file")

        self.registry.register("write", self.tool_write, "Write file content")
        self.registry.register("append", self.tool_append, "Append file content")

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

        # ---------------------- Planning / repo inspection ----------------------
        self.registry.register("inspect_repo", self.tool_inspect_repo, "Inspect repository structure")
        self.registry.register("find_symbol", self.tool_find_symbol, "Find symbol definitions")
        self.registry.register("where_used", self.tool_where_used, "Find symbol or text usages")
        self.registry.register("find_tests", self.tool_find_tests, "Find related tests")
        self.registry.register("task", self.tool_task, "Build a task plan from human-readable request")
        self.registry.register("show_task", self.tool_show_task, "Show current task plan")
        self.registry.register("task_execute", self.tool_task_execute, "Execute current task plan safely")
        self.registry.register("task_validate", self.tool_task_validate, "Validate current task plan targets")
        self.registry.register("task_checkpoint", self.tool_task_checkpoint, "Create a checkpoint for current task")
        self.registry.register("task_clear", self.tool_task_clear, "Clear current task plan")

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
        self.registry.register("trace_list", self.tool_trace_list, "List saved trace files")
        self.registry.register("trace_failures", self.tool_trace_failures, "List failure trace files")
        self.registry.register("trace_open", self.tool_trace_open, "Open a saved trace file")
        self.registry.register("trace_clear", self.tool_trace_clear, "Clear saved trace files")

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

    # ---------------------- Planning / repo inspection helpers ----------------------

    def _workspace_inspector(self) -> WorkspaceInspector:
        return WorkspaceInspector(self.cwd)

    def _task_planner(self) -> TaskPlanner:
        return TaskPlanner(self.cwd)

    def _has_current_task(self) -> bool:
        return getattr(self, "current_task", None) is not None

    def _iter_task_target_paths(self) -> list[Path]:
        task = getattr(self, "current_task", None)
        if not task:
            return []

        out: list[Path] = []
        seen: set[str] = set()

        for item in task.target_files:
            if not item:
                continue
            try:
                resolved = (self.cwd / item).resolve()
            except Exception:
                continue
            key = str(resolved).lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(resolved)
        return out

    def _task_target_files_for_git(self) -> list[str]:
        root = self.cwd.resolve()
        paths: list[str] = []
        for path in self._iter_task_target_paths():
            try:
                rel = path.relative_to(root)
                paths.append(str(rel))
            except Exception:
                paths.append(path.name)
        return paths

    def _validate_python_file_syntax(self, path: Path) -> tuple[bool, str]:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return False, f"{path.name}: read failed: {e}"

        try:
            ast.parse(text, filename=str(path))
            return True, f"{path.name}: syntax OK"
        except SyntaxError as e:
            line = getattr(e, "lineno", "?")
            msg = getattr(e, "msg", str(e))
            return False, f"{path.name}: syntax error at line {line}: {msg}"
        except Exception as e:
            return False, f"{path.name}: parse failed: {e}"

    def _set_task_execution(self, action: str, success: bool, summary: str, details: list[str]) -> None:
        if self._has_current_task():
            self.current_task.set_execution(
                action=action,
                success=success,
                summary=summary,
                details=details,
            )

    # ---------------------- Planning / repo inspection tools ----------------------

    def tool_inspect_repo(self, **kwargs: Any) -> str:
        return self._workspace_inspector().inspect_repo()

    def tool_find_symbol(self, symbol: Optional[str] = None, **kwargs: Any) -> str:
        if not symbol:
            return "Usage: find symbol <name>"
        return self._workspace_inspector().find_symbol(symbol)

    def tool_where_used(self, needle: Optional[str] = None, **kwargs: Any) -> str:
        if not needle:
            return "Usage: where used <name>"
        return self._workspace_inspector().where_used(needle)

    def tool_find_tests(self, target: Optional[str] = None, **kwargs: Any) -> str:
        if not target:
            return "Usage: find tests <file|symbol>"
        return self._workspace_inspector().find_tests(target)

    def tool_task(self, request: Optional[str] = None, **kwargs: Any) -> str:
        if not request:
            return "Usage: task <human-readable request>"

        self.current_task = self._task_planner().build_plan(request)
        return self.current_task.render()

    def tool_show_task(self, **kwargs: Any) -> str:
        if not self._has_current_task():
            return "No active task plan."
        return self.current_task.render()

    def tool_task_execute(self, **kwargs: Any) -> str:
        if not self._has_current_task():
            return "No active task plan."

        task = self.current_task
        task.reset_step_statuses()
        details: list[str] = []
        overall_success = True

        if not task.steps:
            self._set_task_execution(
                action="execute",
                success=False,
                summary="No executable steps were present in the task.",
                details=["Task plan contains no steps."],
            )
            return task.render()

        for idx, step in enumerate(task.steps):
            kind = (step.kind or "").strip().lower()
            target = step.target or ""

            try:
                task.mark_step(idx, "in_progress", "starting")

                if kind == "inspect":
                    report = self._workspace_inspector().inspect_repo()
                    first_line = report.splitlines()[0] if report else "inspect complete"
                    task.mark_step(idx, "done", first_line)
                    details.append(f"Step {idx + 1}: inspect complete")

                elif kind in {"inspect_file", "inspect_lines"}:
                    if not target:
                        task.mark_step(idx, "failed", "missing file target")
                        details.append(f"Step {idx + 1}: missing file target")
                        overall_success = False
                        break

                    path = (self.cwd / target).resolve()
                    if not path.exists():
                        task.mark_step(idx, "failed", "target file not found")
                        details.append(f"Step {idx + 1}: target file not found: {target}")
                        overall_success = False
                        break

                    task.mark_step(idx, "done", f"verified target exists: {target}")
                    details.append(f"Step {idx + 1}: verified target exists: {target}")

                elif kind in {"find_symbol", "symbol"}:
                    if not target:
                        task.mark_step(idx, "failed", "missing symbol target")
                        details.append(f"Step {idx + 1}: missing symbol target")
                        overall_success = False
                        break
                    report = self._workspace_inspector().find_symbol(target)
                    if "No symbol definitions found" in report:
                        task.mark_step(idx, "failed", "symbol not found")
                        details.append(f"Step {idx + 1}: symbol not found: {target}")
                        overall_success = False
                        break
                    task.mark_step(idx, "done", f"symbol checked: {target}")
                    details.append(f"Step {idx + 1}: symbol located: {target}")

                elif kind in {"where_used", "usage"}:
                    if not target:
                        task.mark_step(idx, "failed", "missing usage target")
                        details.append(f"Step {idx + 1}: missing usage target")
                        overall_success = False
                        break
                    report = self._workspace_inspector().where_used(target)
                    if "No usages found" in report:
                        task.mark_step(idx, "failed", "no usages found")
                        details.append(f"Step {idx + 1}: no usages found: {target}")
                        overall_success = False
                        break
                    task.mark_step(idx, "done", f"usages checked: {target}")
                    details.append(f"Step {idx + 1}: usages inspected: {target}")

                elif kind in {"find_tests", "tests"}:
                    test_target = target or (task.target_files[0] if task.target_files else "")
                    if not test_target:
                        task.mark_step(idx, "failed", "missing test target")
                        details.append(f"Step {idx + 1}: missing test target")
                        overall_success = False
                        break
                    report = self._workspace_inspector().find_tests(test_target)
                    if "No test files found" in report:
                        task.mark_step(idx, "skipped", "no related tests found")
                        details.append(f"Step {idx + 1}: no related tests found for {test_target}")
                    else:
                        task.mark_step(idx, "done", f"related tests found for {test_target}")
                        details.append(f"Step {idx + 1}: tests inspected for {test_target}")

                elif kind in {"edit", "patch", "modify", "write"}:
                    task.mark_step(idx, "skipped", "manual patch content required")
                    details.append(
                        f"Step {idx + 1}: skipped edit step for {target or 'unspecified target'}; "
                        "manual patch content required"
                    )

                elif kind in {"validate", "syntax", "verify_lines"}:
                    validated_any = False
                    local_success = True
                    for path in self._iter_task_target_paths():
                        if kind == "verify_lines":
                            if path.exists():
                                validated_any = True
                                details.append(f"{path.name}: file present for post-edit verification")
                            else:
                                validated_any = True
                                local_success = False
                                details.append(f"{path.name}: missing during post-edit verification")
                            continue

                        if path.suffix.lower() != ".py" or not path.exists():
                            continue

                        validated_any = True
                        ok, message = self._validate_python_file_syntax(path)
                        details.append(message)
                        if not ok:
                            local_success = False

                    if not validated_any:
                        task.mark_step(idx, "skipped", "no applicable targets available")
                        details.append(f"Step {idx + 1}: no applicable targets available")
                    elif local_success:
                        if kind == "verify_lines":
                            task.mark_step(idx, "done", "post-edit target verification passed")
                            details.append(f"Step {idx + 1}: post-edit target verification passed")
                        else:
                            task.mark_step(idx, "done", "validation passed")
                            details.append(f"Step {idx + 1}: validation passed")
                    else:
                        if kind == "verify_lines":
                            task.mark_step(idx, "failed", "post-edit target verification failed")
                        else:
                            task.mark_step(idx, "failed", "validation failed")
                        overall_success = False
                        break

                else:
                    task.mark_step(idx, "skipped", f"unsupported step kind: {kind or 'unknown'}")
                    details.append(f"Step {idx + 1}: unsupported step kind skipped: {kind or 'unknown'}")

            except Exception as e:
                task.mark_step(idx, "failed", str(e))
                details.append(f"Step {idx + 1}: failed with error: {e}")
                overall_success = False
                break

        summary = (
            "Task execution completed without blocking failures."
            if overall_success
            else "Task execution stopped due to failure."
        )

        self._set_task_execution(
            action="execute",
            success=overall_success,
            summary=summary,
            details=details,
        )
        return task.render()

    def tool_task_validate(self, **kwargs: Any) -> str:
        if not self._has_current_task():
            return "No active task plan."

        task = self.current_task
        details: list[str] = []
        python_targets = [
            path for path in self._iter_task_target_paths()
            if path.exists() and path.suffix.lower() == ".py"
        ]

        if not python_targets:
            self._set_task_execution(
                action="validate",
                success=False,
                summary="No Python target files were available for validation.",
                details=["Task has no existing Python targets."],
            )
            return task.render()

        success = True
        for path in python_targets:
            ok, message = self._validate_python_file_syntax(path)
            details.append(message)
            if not ok:
                success = False

        summary = "Validation passed." if success else "Validation failed."
        self._set_task_execution(
            action="validate",
            success=success,
            summary=summary,
            details=details,
        )
        return task.render()

    def tool_task_checkpoint(self, note: Optional[str] = None, **kwargs: Any) -> str:
        if not self._has_current_task():
            return "No active task plan."

        repo_msg = self._ensure_git_repo()
        if repo_msg:
            return repo_msg

        task = self.current_task
        details: list[str] = []

        staged_any = False
        for file_name in self._task_target_files_for_git():
            stage_result = git_stage_file(self.cwd, file_name)
            if "[exit=0]" in stage_result:
                staged_any = True
                details.append(f"staged: {file_name}")
            else:
                details.append(f"stage failed: {file_name}")

        if not staged_any:
            self._set_task_execution(
                action="task_checkpoint",
                success=False,
                summary="No task target files could be staged.",
                details=details,
            )
            return task.render()

        commit_note = note or task.goal
        msg = build_checkpoint_message(
            op="task_checkpoint",
            note=f"task checkpoint | {commit_note}",
        )
        commit_result = git_commit(self.cwd, msg)

        if "[exit=0]" in commit_result:
            details.append(f"commit created: {msg}")
            self._set_task_execution(
                action="task_checkpoint",
                success=True,
                summary="Task checkpoint created.",
                details=details,
            )
        else:
            lower = commit_result.lower()
            if "nothing to commit" in lower or "nothing added to commit" in lower:
                details.append("no changes to commit")
            else:
                details.append(commit_result)
            self._set_task_execution(
                action="task_checkpoint",
                success=False,
                summary="Task checkpoint failed.",
                details=details,
            )

        return task.render()

    def tool_task_clear(self, **kwargs: Any) -> str:
        if not self._has_current_task():
            return "No active task plan."

        self.current_task = None
        return "Cleared active task plan."

    # ---------------------- Git / VCS Helpers ----------------------

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

    def _maybe_commit_after_edit(
        self,
        op: str,
        file: Optional[str] = None,
        target: Optional[str] = None,
        lines: Optional[str] = None,
    ) -> str:
        repo_msg = self._ensure_git_repo()
        if repo_msg:
            return ""

        if self.git_mode in {"off", "manual", "checkpoint_only"}:
            return ""

        if self.git_mode == "auto_commit":
            if file:
                stage_result = git_stage_file(self.cwd, file)
                if "[exit=0]" not in stage_result:
                    return f"[auto-commit skipped] Could not stage file: {file}\n{stage_result}"

            msg = build_checkpoint_message(
                op=f"{op}_final",
                file=file,
                target=target,
                lines=lines,
                note="auto commit after successful edit",
            )
            commit_result = git_commit(self.cwd, msg)
            if "[exit=0]" in commit_result:
                return f"[auto-commit created] {msg}"
            lower = commit_result.lower()
            if "nothing to commit" in lower or "nothing added to commit" in lower:
                return "[auto-commit skipped] No changes to commit."
            return f"[auto-commit failed]\n{commit_result}"

        return ""

    # ---------------------- VCS Tools ----------------------

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
        safe_file = self._validate_user_token(file, "diff file") if file else None
        return git_diff(self.cwd, file=safe_file, cached=cached)

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

        safe_file = self._validate_user_token(file, "file history target")
        result = get_file_history(self.cwd, file=safe_file, limit=limit)
        if "does not have any commits yet" in result.lower():
            return f"No commit history yet for repository or file: {safe_file}"
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
        self._out(preview)
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

        safe_file = self._validate_user_token(file, "rollback file")
        preview = rollback_file_preview(self.cwd, safe_file)
        self._out(preview)
        confirm = input(f'Rollback file "{safe_file}" to HEAD? [y/N]: ').strip().lower()
        if confirm not in {"y", "yes"}:
            return "Rollback canceled."

        return rollback_file_to_head(self.cwd, safe_file)

    def tool_rollback_to(self, commit: Optional[str] = None, **kwargs: Any) -> str:
        repo_msg = self._ensure_git_repo()
        if repo_msg:
            return repo_msg
        if not commit:
            return "Usage: rollback to <commit>"

        safe_commit = self._validate_user_token(commit, "commit reference")
        preview = rollback_to_commit_preview(self.cwd, safe_commit)
        self._out(preview)
        confirm = input(f"Hard reset to commit {safe_commit}? [y/N]: ").strip().lower()
        if confirm not in {"y", "yes"}:
            return "Rollback canceled."

        return rollback_to_commit_hard(self.cwd, safe_commit)

    def tool_git_mode(self, mode: Optional[str] = None, **kwargs: Any) -> str:
        if not mode:
            return f"Git mode: {self.git_mode}"

        self.git_mode = normalize_git_mode(mode)
        return f"Git mode set to: {self.git_mode}"

    # ---------------------- Trace Tools ----------------------

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

    def tool_trace_list(self, limit: int = 20, **kwargs: Any) -> str:
        self.profiler.log_dir.mkdir(parents=True, exist_ok=True)
        files = sorted(
            self.profiler.log_dir.glob("*.jsonl"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:limit]

        if not files:
            return "No saved trace files found."

        lines = ["Saved Trace Files", "-----------------"]
        for i, path in enumerate(files, 1):
            lines.append(f"{i:02d}. {path.name}")
        return "\n".join(lines)

    def tool_trace_failures(self, limit: int = 20, **kwargs: Any) -> str:
        self.profiler.log_dir.mkdir(parents=True, exist_ok=True)
        files = sorted(
            self.profiler.log_dir.glob("*.jsonl"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        failures: list[Path] = []
        for path in files:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            lower = text.lower()
            if '"success": false' in lower or "success: false" in lower:
                failures.append(path)
            if len(failures) >= limit:
                break

        if not failures:
            return "No saved failure trace files found."

        lines = ["Saved Failure Trace Files", "-------------------------"]
        for i, path in enumerate(failures, 1):
            lines.append(f"{i:02d}. {path.name}")
        return "\n".join(lines)

    def tool_trace_open(self, filename: Optional[str] = None, **kwargs: Any) -> str:
        if not filename:
            return "Usage: trace open <filename>"
        safe_filename = Path(self._validate_user_token(filename, "trace filename")).name
        path = self.profiler.log_dir / safe_filename
        if not path.exists():
            return f"Trace file not found: {safe_filename}"
        return path.read_text(encoding="utf-8", errors="replace")

    def tool_trace_clear(self, failures_only: bool = False, **kwargs: Any) -> str:
        scope = "failure" if failures_only else "all"
        confirm = input(f"Clear {scope} saved trace files? [y/N]: ").strip().lower()
        if confirm not in {"y", "yes"}:
            return "Trace clear canceled."

        self.profiler.log_dir.mkdir(parents=True, exist_ok=True)
        removed = 0
        for path in self.profiler.log_dir.glob("*.jsonl"):
            if failures_only:
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                lower = text.lower()
                if '"success": false' not in lower and "success: false" not in lower:
                    continue
            try:
                path.unlink()
                removed += 1
            except Exception:
                continue

        return f"Cleared {removed} {scope} trace file(s)."

    # ---------------------- Shell / Git / Misc ----------------------

    def tool_run(
        self,
        cmd: Optional[str] = None,
        command: Optional[str] = None,
        check: bool = False,
        **kwargs: Any,
    ) -> str:
        safe_cmd = self._validate_shell_command(cmd or command)
        if not safe_cmd:
            return "No command given"

        stripped = safe_cmd.strip().lower()

        if stripped == "python" or stripped.startswith("python "):
            if not any(flag in stripped for flag in ["-c", ".py", "-m"]):
                return (
                    "Interactive Python sessions are disabled.\n"
                    "Use one of the following instead:\n"
                    "  run python -c \"print('hello')\"\n"
                    "  run python script.py\n"
                    "  run python -m module_name"
                )

        try:
            completed = subprocess.run(
                safe_cmd,
                shell=True,
                capture_output=True,
                text=True,
                cwd=str(self.cwd),
            )
        except KeyboardInterrupt:
            return "[interrupted] Command execution cancelled (Ctrl+C)"

        output = (completed.stdout or "").strip()
        err = (completed.stderr or "").strip()

        parts = [f"[exit={completed.returncode}]"]

        if output:
            parts.append("--- stdout ---")
            parts.append(output)

        if err:
            parts.append("--- stderr ---")
            parts.append(err)

        result = "\n".join(parts)

        if check and completed.returncode != 0:
            raise RuntimeError(result)

        return result

    def tool_git(self, cmd: Optional[str] = None, **kwargs: Any) -> str:
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

        safe_cmd = self._validate_shell_command(cmd or "git status")
        git_cmd = safe_cmd.strip()

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
        floor = getattr(
            self,
            "low_trust_truncate_floor",
            getattr(self.engine, "LOW_TRUST_TRUNCATE_FLOOR", 0.0),
        )
        low_trust_forced = self.engine.trust < floor

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
            f"Selection Active: {self.selection is not None}\n"
            f"Task Active: {getattr(self, 'current_task', None) is not None}"
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
            "  no truncate\n"
            "  no_truncate\n"
            "  no truncation\n"
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
            "  write RHEA_Code-CLI.py pastefile # inline seed\n"
            "  append RHEA_Code-CLI.py pasteappend\n"
            "  append RHEA_Code-CLI.py pasteappend # inline seed\n"
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
            "Repo inspection / planning:\n"
            "  inspect repo\n"
            "  find symbol tool_edit\n"
            "  where used tool_edit\n"
            "  find tests parser\n"
            "  task add logging to parser and update tests\n"
            "  show task\n"
            "  task execute\n"
            "  task validate\n"
            "  task checkpoint\n"
            "  task checkpoint parser work snapshot\n"
            "  task clear\n"
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
            "\n"
            "Trace Profiler:\n"
            "  trace status\n"
            "  trace last\n"
            "  trace on\n"
            "  trace off\n"
            "  trace list\n"
            "  trace list 50\n"
            "  trace failures\n"
            "  trace failures 20\n"
            "  trace open trace_fail_YYYY-MM-DDTHH-MM-SS.jsonl\n"
            "  trace clear\n"
            "  trace clear failures\n"
            "\n"
            + self.registry.get_help_text()
        )