# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from pathlib import Path

from .tasking import TaskPlan, TaskStep
from .workspace import WorkspaceInspector


class TaskPlanner:
    """
    Builds a conservative, line-aware execution plan from a human-readable request.

    Design goals:
    - Prefer exact file matches when the user names a file explicitly.
    - Prefer exact module-hint matches for CLI-oriented requests.
    - Keep plans inspect-first and validation-heavy.
    - Avoid drifting into unrelated files when a specific module noun is present.
    """

    MODULE_HINTS: dict[str, tuple[str, ...]] = {
        "parser": ("RHEA_Code_CLI/cli/parsing.py",),
        "parsing": ("RHEA_Code_CLI/cli/parsing.py",),
        "integration": ("RHEA_Code_CLI/cli/integration.py",),
        "session": ("RHEA_Code_CLI/cli/session.py",),
        "app": ("RHEA_Code_CLI/cli/app.py",),
        "planner": ("RHEA_Code_CLI/cli/planner.py",),
        "planning": ("RHEA_Code_CLI/cli/planner.py",),
        "task": (
            "RHEA_Code_CLI/cli/tasking.py",
            "RHEA_Code_CLI/cli/task_executor.py",
            "RHEA_Code_CLI/cli/planner.py",
        ),
        "tasking": ("RHEA_Code_CLI/cli/tasking.py",),
        "executor": ("RHEA_Code_CLI/cli/task_executor.py",),
        "execution": ("RHEA_Code_CLI/cli/task_executor.py",),
        "task_executor": ("RHEA_Code_CLI/cli/task_executor.py",),
        "workspace": ("RHEA_Code_CLI/cli/workspace.py",),
        "registry": ("RHEA_Code_CLI/registry/tool_registry.py",),
        "tool_registry": ("RHEA_Code_CLI/registry/tool_registry.py",),
        "history": ("RHEA_Code_CLI/vcs/git_history.py",),
        "git_history": ("RHEA_Code_CLI/vcs/git_history.py",),
        "help": ("RHEA_Code_CLI/cli/integration.py",),
        "trace": ("RHEA_Code_CLI/cli/integration.py",),
        "harness": ("RHEA_Code_CLI_full_feature_harness.py",),
        "cli": (
            "RHEA_Code_CLI/cli/parsing.py",
            "RHEA_Code_CLI/cli/integration.py",
            "RHEA_Code_CLI/cli/session.py",
            "RHEA_Code_CLI/cli/app.py",
        ),
    }

    EDIT_VERBS = {
        "add",
        "update",
        "change",
        "modify",
        "patch",
        "fix",
        "replace",
        "refactor",
        "improve",
        "enhance",
        "extend",
        "tighten",
        "harden",
        "remove",
    }

    STOPWORDS = {
        "and",
        "the",
        "a",
        "an",
        "to",
        "for",
        "in",
        "on",
        "with",
        "of",
        "tests",
        "test",
        "code",
        "module",
        "file",
        "files",
        "line",
        "lines",
    }

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.inspector = WorkspaceInspector(self.root)

    def build_plan(self, request: str) -> TaskPlan:
        lowered = request.lower().strip()

        target_files = self._infer_target_files(lowered)
        validation = self._infer_validation_steps(lowered, target_files)

        steps: list[TaskStep] = [
            TaskStep(
                kind="inspect",
                description="Inspect repository context before editing",
                detail="inspect repo",
            ),
        ]

        for file in target_files:
            steps.append(
                TaskStep(
                    kind="inspect_file",
                    description="Read target file before editing",
                    target=file,
                    detail=f"read {file} full",
                )
            )
            steps.append(
                TaskStep(
                    kind="inspect_lines",
                    description="List lines to capture exact edit positions before changing code",
                    target=file,
                    detail=f"list lines {file}",
                )
            )

        if "test" in lowered:
            test_target = target_files[0] if target_files else request
            steps.append(
                TaskStep(
                    kind="find_tests",
                    description="Locate related tests for requested change",
                    detail=f"find tests {test_target}",
                )
            )

        if any(word in lowered for word in self.EDIT_VERBS):
            steps.append(
                TaskStep(
                    kind="edit",
                    description="Apply requested code changes using exact lines or anchored replacements",
                    target=", ".join(target_files) if target_files else None,
                    detail=self._build_edit_guidance(target_files),
                )
            )

        for file in target_files:
            steps.append(
                TaskStep(
                    kind="verify_lines",
                    description="Re-list lines after editing to confirm final positions and content",
                    target=file,
                    detail=f"list lines {file}",
                )
            )

        for item in validation:
            steps.append(
                TaskStep(
                    kind="validate",
                    description="Validate result",
                    detail=item,
                )
            )

        rollback_hint = "Use checkpoint before execution or rollback show / rollback file after execution."

        return TaskPlan(
            goal=request,
            summary=self._summarize_request(request, target_files),
            target_files=target_files,
            validation_steps=validation,
            rollback_hint=rollback_hint,
            steps=steps,
        )

    def _summarize_request(self, request: str, target_files: list[str]) -> str:
        if target_files:
            return (
                f"Plan requested change against {len(target_files)} likely target file(s), "
                "with line-aware inspection before edits."
            )
        return "Plan requested change with repository inspection required before editing."

    def _build_edit_guidance(self, target_files: list[str]) -> str:
        if not target_files:
            return "inspect repo, identify exact file, then use list lines before any replace / insert command"

        if len(target_files) == 1:
            file = target_files[0]
            return (
                f"start with: list lines {file} then use replace line / replace lines / "
                f"insert after / replace def as needed"
            )

        return (
            "start with line-aware inspection of each target file, then use replace / insert / write commands as needed"
        )

    def _infer_target_files(self, lowered: str) -> list[str]:
        explicit = self._extract_explicit_file_targets(lowered)
        if explicit:
            return explicit

        exact_hint = self._extract_exact_context_hint_targets(lowered)
        if exact_hint:
            return exact_hint

        hinted = self._extract_hint_targets(lowered)
        if hinted:
            return hinted

        scored = self._score_repo_files(lowered)
        if scored:
            return scored

        return []

    def _extract_explicit_file_targets(self, lowered: str) -> list[str]:
        candidates: list[str] = []

        pattern = re.findall(r"[\w\-/\\\.]+\.(?:py|txt|md|json|yaml|yml)", lowered)
        for raw in pattern:
            normalized = raw.replace("\\", "/").strip()
            if normalized not in candidates:
                candidates.append(normalized)

        if not candidates:
            return []

        existing: list[str] = []
        for item in candidates:
            resolved = (self.root / item).resolve()
            if resolved.exists():
                try:
                    existing.append(str(resolved.relative_to(self.root)).replace("\\", "/"))
                except Exception:
                    existing.append(item)

        return existing or candidates

    def _extract_exact_context_hint_targets(self, lowered: str) -> list[str]:
        """
        Strongest hint layer. This is where we prevent generic fallback from
        stealing a request that clearly names a known module concept.
        """
        results: list[str] = []
        seen: set[str] = set()

        def add(path_str: str) -> None:
            normalized = path_str.replace("\\", "/")
            if normalized in seen:
                return
            path = (self.root / normalized).resolve()
            if path.exists():
                seen.add(normalized)
                results.append(normalized)

        if re.search(r"\bparser\b", lowered) or re.search(r"\bparsing\b", lowered):
            add("RHEA_Code_CLI/cli/parsing.py")

        if re.search(r"\bintegration\b", lowered):
            add("RHEA_Code_CLI/cli/integration.py")

        if re.search(r"\bsession\b", lowered):
            add("RHEA_Code_CLI/cli/session.py")

        if re.search(r"\bplanner\b", lowered) or re.search(r"\bplanning\b", lowered):
            add("RHEA_Code_CLI/cli/planner.py")

        if re.search(r"\btask execution\b", lowered) or re.search(r"\btask executor\b", lowered):
            add("RHEA_Code_CLI/cli/task_executor.py")

        if re.search(r"\btasking\b", lowered):
            add("RHEA_Code_CLI/cli/tasking.py")

        if re.search(r"\bworkspace\b", lowered):
            add("RHEA_Code_CLI/cli/workspace.py")

        if re.search(r"\btrace\b", lowered) or re.search(r"\bhelp\b", lowered):
            add("RHEA_Code_CLI/cli/integration.py")

        return results[:5]

    def _extract_hint_targets(self, lowered: str) -> list[str]:
        tokens = self._keywords(lowered)
        out: list[str] = []
        seen: set[str] = set()

        for token in tokens:
            for candidate in self.MODULE_HINTS.get(token, ()):
                normalized = candidate.replace("\\", "/")
                if normalized in seen:
                    continue
                path = (self.root / normalized).resolve()
                if path.exists():
                    seen.add(normalized)
                    out.append(normalized)

        return out[:5]

    def _score_repo_files(self, lowered: str) -> list[str]:
        keywords = self._keywords(lowered)
        if not keywords:
            return []

        py_files = list(self.inspector._iter_files(exts=(".py",)))
        scored: list[tuple[int, str]] = []

        cli_bias = any(
            token in lowered
            for token in (
                "cli",
                "parser",
                "parsing",
                "integration",
                "session",
                "planner",
                "task",
                "tasking",
                "workspace",
                "executor",
                "execution",
                "command",
                "routing",
                "help",
                "trace",
            )
        )

        for path in py_files:
            try:
                rel = str(path.relative_to(self.root)).replace("\\", "/")
            except Exception:
                rel = str(path).replace("\\", "/")

            rel_lower = rel.lower()
            filename = path.name.lower()
            stem = path.stem.lower()
            parts = [p.lower() for p in path.parts]

            score = 0

            for key in keywords:
                if key == stem:
                    score += 12
                if key == filename:
                    score += 14
                if f"{key}.py" == filename:
                    score += 16
                if key in stem:
                    score += 8
                if key in filename:
                    score += 6
                if key in rel_lower:
                    score += 3
                if key in parts:
                    score += 4

            if cli_bias and "rhea_code_cli/cli/" in rel_lower:
                score += 6

            if "test" in lowered and ("test" in rel_lower or "tests" in rel_lower):
                score += 5

            if score > 0:
                scored.append((score, rel))

        scored.sort(key=lambda item: (-item[0], item[1]))
        return [item[1] for item in scored[:5]]

    def _infer_validation_steps(self, lowered: str, target_files: list[str]) -> list[str]:
        steps: list[str] = []

        if target_files:
            steps.append(f"read {target_files[0]} full")
            steps.append(f"list lines {target_files[0]}")
        else:
            steps.append("Re-read changed files")
            steps.append("Re-run list lines on changed files")

        if any(word in lowered for word in ("test", "tests", "testing")):
            steps.append("run pytest or project test command")
        elif target_files:
            steps.append("run python -m py_compile <file> or import validation")

        if any(word in lowered for word in ("parser", "cli", "command", "routing")):
            steps.append("run CLI harness or regression commands")

        return steps

    def _keywords(self, lowered: str) -> list[str]:
        raw = re.split(r"[^a-z0-9_]+", lowered)
        out: list[str] = []
        seen: set[str] = set()

        for token in raw:
            token = token.strip().lower()
            if not token:
                continue
            if token in self.STOPWORDS:
                continue
            if len(token) == 1:
                continue
            if token not in seen:
                seen.add(token)
                out.append(token)

        return out