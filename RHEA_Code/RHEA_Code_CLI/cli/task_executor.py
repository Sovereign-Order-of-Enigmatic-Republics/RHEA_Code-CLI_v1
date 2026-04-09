# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from .tasking import TaskPlan


@dataclass
class TaskExecutionResult:
    success: bool
    summary: str
    details: list[str] = field(default_factory=list)


class TaskExecutor:
    def __init__(self, root: Path, tool_runner: Callable[[str, dict[str, Any]], str]) -> None:
        self.root = root
        self.tool_runner = tool_runner

    def execute_plan(self, plan: TaskPlan) -> TaskExecutionResult:
        if not plan.steps:
            plan.set_execution(
                action="task_execute",
                success=False,
                summary="No task steps available to execute.",
                details=["Task plan has no steps."],
            )
            return TaskExecutionResult(
                success=False,
                summary="No task steps available to execute.",
                details=["Task plan has no steps."],
            )

        plan.clear_execution()
        details: list[str] = []

        for idx, step in enumerate(plan.steps):
            if step.status in {"done", "skipped"}:
                details.append(f"Skipped step {idx + 1}: already {step.status}.")
                continue

            plan.mark_step(idx, "in_progress", "Executing step.")
            ok, summary = self._execute_step(step.kind, step.target)
            if ok:
                plan.mark_step(idx, "done", summary)
                details.append(f"Step {idx + 1} done: {summary}")
            else:
                plan.mark_step(idx, "failed", summary)
                details.append(f"Step {idx + 1} failed: {summary}")
                plan.set_execution(
                    action="task_execute",
                    success=False,
                    summary=f"Execution stopped on step {idx + 1}.",
                    details=details,
                )
                return TaskExecutionResult(
                    success=False,
                    summary=f"Execution stopped on step {idx + 1}.",
                    details=details,
                )

        plan.set_execution(
            action="task_execute",
            success=True,
            summary="Task plan executed successfully.",
            details=details,
        )
        return TaskExecutionResult(
            success=True,
            summary="Task plan executed successfully.",
            details=details,
        )

    def validate_plan(self, plan: TaskPlan) -> TaskExecutionResult:
        details: list[str] = []

        if not plan.validation_steps:
            plan.set_execution(
                action="task_validate",
                success=True,
                summary="No explicit validation steps were defined.",
                details=[],
            )
            return TaskExecutionResult(
                success=True,
                summary="No explicit validation steps were defined.",
                details=[],
            )

        for item in plan.validation_steps:
            details.append(item)

        plan.set_execution(
            action="task_validate",
            success=True,
            summary="Validation plan recorded.",
            details=details,
        )
        return TaskExecutionResult(
            success=True,
            summary="Validation plan recorded.",
            details=details,
        )

    def checkpoint_plan(self, plan: TaskPlan, note: Optional[str] = None) -> TaskExecutionResult:
        message = note or f"task checkpoint: {plan.goal}"
        result = self.tool_runner("checkpoint", {"note": message})
        success = "[exit=0]" in result or "No changes to checkpoint." in result or "Checkpoint" in result
        summary = "Checkpoint command executed." if success else "Checkpoint command failed."

        plan.set_execution(
            action="task_checkpoint",
            success=success,
            summary=summary,
            details=[result],
        )
        return TaskExecutionResult(
            success=success,
            summary=summary,
            details=[result],
        )

    def clear_plan_execution(self, plan: TaskPlan) -> TaskExecutionResult:
        plan.reset_step_statuses()
        plan.clear_execution()
        return TaskExecutionResult(
            success=True,
            summary="Task execution state cleared.",
            details=[],
        )

    def _execute_step(self, kind: str, target: Optional[str]) -> tuple[bool, str]:
        try:
            if kind == "inspect":
                self.tool_runner("inspect_repo", {})
                return True, "Repository inspected."
            if kind == "inspect_file":
                if not target:
                    return False, "Missing inspect_file target."
                self.tool_runner("read", {"file": target, "full": True})
                return True, f"Inspected file: {target}"
            if kind == "find_tests":
                if target:
                    self.tool_runner("find_tests", {"target": target})
                return True, "Related tests inspected."
            if kind == "edit":
                return True, "Edit step acknowledged for operator execution."
            if kind == "validate":
                return True, "Validation step recorded."
            return True, f"No executor action mapped for step kind: {kind}"
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"