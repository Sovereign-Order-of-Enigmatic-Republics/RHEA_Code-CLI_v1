# -*- coding: utf-8 -*-
# vcs/git_policy.py
# RHEA Code CLI — Git policy controls

from __future__ import annotations

from typing import Optional


VALID_GIT_MODES = {"off", "manual", "checkpoint_only", "auto_commit"}


def normalize_git_mode(mode: Optional[str]) -> str:
    if not mode:
        return "manual"
    mode = mode.strip().lower()
    return mode if mode in VALID_GIT_MODES else "manual"


def should_checkpoint_before_edit(git_mode: str, trust: float) -> bool:
    git_mode = normalize_git_mode(git_mode)

    if git_mode == "off":
        return False
    if git_mode == "manual":
        return False
    if git_mode == "checkpoint_only":
        return True
    if git_mode == "auto_commit":
        return True

    return False


def allow_auto_commit(git_mode: str, trust: float) -> bool:
    git_mode = normalize_git_mode(git_mode)
    return git_mode == "auto_commit" and trust >= 0.60