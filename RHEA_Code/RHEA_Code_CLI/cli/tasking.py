# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


VALID_STEP_STATUSES = {
    "pending",
    "in_progress",
    "done",
    "failed",
    "skipped",
}

STEP_KIND_LABELS = {
    "inspect": "Inspect repository context",
    "inspect_file": "Inspect file",
    "inspect_lines": "List exact lines",
    "find_tests": "Find related tests",
    "edit": "Apply edits",
    "verify_lines": "Verify final lines",
    "validate": "Validate result",
}


@dataclass
class TaskStep:
    kind: str
    description: str
    target: Optional[str] = None
    status: str = "pending"
    detail: str = ""

    def set_status(self, status: str, detail: str = "") -> None:
        normalized = status.strip().lower()
        if normalized not in VALID_STEP_STATUSES:
            raise ValueError(f"Invalid task step status: {status}")
        self.status = normalized
        self.detail = detail

    def display_kind(self) -> str:
        return STEP_KIND_LABELS.get(self.kind, self.kind.replace("_", " ").strip().title())

    def render_line(self, index: int) -> str:
        target = f" | target={self.target}" if self.target else ""
        suffix = f" | detail={self.detail}" if self.detail else ""
        return (
            f"  {index:02d}. [{self.status}] "
            f"{self.display_kind()}: {self.description}"
            f"{target}{suffix}"
        )


@dataclass
class TaskExecutionRecord:
    action: str
    success: bool
    summary: str
    details: list[str] = field(default_factory=list)

    def render(self) -> str:
        lines = [
            "Task Execution",
            "--------------",
            f"Action: {self.action}",
            f"Success: {self.success}",
            f"Summary: {self.summary}",
        ]
        if self.details:
            lines.append("")
            lines.append("Details:")
            for item in self.details:
                lines.append(f"  - {item}")
        return "\n".join(lines)


@dataclass
class TaskPlan:
    goal: str
    summary: str
    target_files: list[str] = field(default_factory=list)
    validation_steps: list[str] = field(default_factory=list)
    rollback_hint: str = ""
    steps: list[TaskStep] = field(default_factory=list)
    last_execution: Optional[TaskExecutionRecord] = None

    def render(self) -> str:
        lines = [
            "RHEA Task Plan",
            "--------------",
            f"Goal: {self.goal}",
            f"Summary: {self.summary}",
        ]

        if self.target_files:
            lines.append("")
            lines.append("Target Files:")
            for path in self.target_files:
                lines.append(f"  - {path}")

        if self.steps:
            lines.append("")
            lines.append("Steps:")
            for i, step in enumerate(self.steps, 1):
                lines.append(step.render_line(i))

            counts = self.counts_by_status()
            lines.append("")
            lines.append(
                "Step Status Counts: "
                f"pending={counts['pending']} | "
                f"in_progress={counts['in_progress']} | "
                f"done={counts['done']} | "
                f"failed={counts['failed']} | "
                f"skipped={counts['skipped']}"
            )

        if self.validation_steps:
            lines.append("")
            lines.append("Validation:")
            for item in self.validation_steps:
                lines.append(f"  - {item}")

        if self.rollback_hint:
            lines.append("")
            lines.append(f"Rollback: {self.rollback_hint}")

        if self.last_execution:
            lines.append("")
            lines.append(self.last_execution.render())

        return "\n".join(lines)

    def reset_step_statuses(self) -> None:
        for step in self.steps:
            step.status = "pending"
            step.detail = ""

    def set_execution(
        self,
        action: str,
        success: bool,
        summary: str,
        details: Optional[list[str]] = None,
    ) -> None:
        self.last_execution = TaskExecutionRecord(
            action=action,
            success=success,
            summary=summary,
            details=list(details or []),
        )

    def clear_execution(self) -> None:
        self.last_execution = None

    def mark_step(
        self,
        index: int,
        status: str,
        detail: str = "",
    ) -> None:
        if index < 0 or index >= len(self.steps):
            raise IndexError(f"Task step index out of range: {index}")
        self.steps[index].set_status(status, detail)

    def first_pending_step_index(self) -> Optional[int]:
        for i, step in enumerate(self.steps):
            if step.status == "pending":
                return i
        return None

    def counts_by_status(self) -> dict[str, int]:
        counts = {key: 0 for key in VALID_STEP_STATUSES}
        for step in self.steps:
            counts[step.status] = counts.get(step.status, 0) + 1
        return counts

    def is_complete(self) -> bool:
        if not self.steps:
            return False
        return all(step.status in {"done", "skipped"} for step in self.steps)

    def has_failures(self) -> bool:
        return any(step.status == "failed" for step in self.steps)

    def render_compact(self) -> str:
        counts = self.counts_by_status()
        return (
            "Task Plan Summary\n"
            "-----------------\n"
            f"Goal: {self.goal}\n"
            f"Files: {len(self.target_files)}\n"
            f"Steps: {len(self.steps)}\n"
            f"Pending: {counts['pending']}\n"
            f"In Progress: {counts['in_progress']}\n"
            f"Done: {counts['done']}\n"
            f"Failed: {counts['failed']}\n"
            f"Skipped: {counts['skipped']}"
        )