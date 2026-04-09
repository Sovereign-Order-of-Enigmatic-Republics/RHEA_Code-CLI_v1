# -*- coding: utf-8 -*-
from __future__ import annotations

import shlex
from typing import Any, Dict, Optional, Tuple


class GlyphParser:
    def __init__(self, engine) -> None:
        self.engine = engine

    def parse(self, user_input: str) -> Dict[str, Any]:
        entropy = self.engine.compute_entropy(user_input)
        trust_glyph = self.engine.update_trust(entropy)

        cmd = user_input.lower().strip()
        role = self._detect_role(cmd)

        return {
            "input": user_input,
            "original_cmd": user_input,
            "entropy": round(entropy, 4),
            "trust": round(self.engine.trust, 4),
            "glyph": "Ψ",
            "trust_glyph": trust_glyph,
            "role": role,
        }

    def _detect_role(self, cmd: str) -> str:
        # ---------------------- Planning / repo inspection ----------------------
        if cmd == "inspect repo":
            return "inspect_repo"
        if cmd.startswith("find symbol "):
            return "find_symbol"
        if cmd.startswith("where used "):
            return "where_used"
        if cmd.startswith("find tests "):
            return "find_tests"

        if cmd == "show task":
            return "show_task"

        if cmd == "task":
            return "task"
        if cmd == "task execute":
            return "task_execute"
        if cmd == "task validate":
            return "task_validate"
        if cmd == "task checkpoint":
            return "task_checkpoint"
        if cmd == "task clear":
            return "task_clear"
        if cmd.startswith("task checkpoint "):
            return "task_checkpoint"
        if cmd.startswith("task "):
            return "task"

        # ---------------------- Output / truncation controls ----------------------
        if (
            cmd in {
                "full output",
                "no truncate",
                "no_truncate",
                "no truncation",
                "disable truncation",
                "truncate off",
            }
            or "full output" in cmd
            or "no truncate" in cmd
            or "no_truncate" in cmd
            or "no truncation" in cmd
            or "disable truncation" in cmd
            or "truncate off" in cmd
        ):
            return "no_truncate"

        if (
            cmd in {"truncate on", "enable truncation"}
            or "truncate on" in cmd
            or "enable truncation" in cmd
        ):
            return "truncate_on"

        if cmd.startswith("set limit ") or cmd.startswith("truncate limit "):
            return "set_limit"

        # ---------------------- Diff controls ----------------------
        if cmd in {"diff on", "preview on", "confirm on"}:
            return "diff_on"
        if cmd in {"diff off", "preview off", "confirm off"}:
            return "diff_off"

        # ---------------------- Trace profiler ----------------------
        if cmd == "trace status":
            return "trace_status"
        if cmd == "trace last":
            return "trace_last"
        if cmd == "trace on":
            return "trace_on"
        if cmd == "trace off":
            return "trace_off"
        if cmd == "trace clear failures":
            return "trace_clear"
        if cmd == "trace clear":
            return "trace_clear"
        if cmd.startswith("trace failures"):
            return "trace_failures"
        if cmd.startswith("trace list"):
            return "trace_list"
        if cmd.startswith("trace open"):
            return "trace_open"

        # ---------------------- Selection ----------------------
        if cmd.startswith("show selection"):
            return "show_selection"
        if cmd.startswith("read selection"):
            return "read_selection"
        if cmd.startswith("replace selection"):
            return "replace_selection"
        if cmd.startswith("select "):
            return "select_object"

        # ---------------------- VCS / Git wrappers ----------------------
        if cmd.startswith("vcs status"):
            return "vcs_status"
        if cmd.startswith("vcs diff"):
            return "vcs_diff"
        if cmd.startswith("vcs log"):
            return "vcs_log"
        if cmd.startswith("vcs filelog"):
            return "vcs_filelog"
        if cmd.startswith("checkpoint "):
            return "checkpoint"
        if cmd == "checkpoint":
            return "checkpoint"
        if cmd.startswith("rollback show"):
            return "rollback_show"
        if cmd.startswith("rollback last"):
            return "rollback_last"
        if cmd.startswith("rollback file"):
            return "rollback_file"
        if cmd.startswith("rollback to"):
            return "rollback_to"
        if cmd == "git mode":
            return "git_mode"
        if cmd.startswith("git mode "):
            return "git_mode"

        # ---------------------- Structured code / text ops ----------------------
        if cmd.startswith("list defs ") or cmd == "list defs":
            return "list_defs"
        if cmd.startswith("list classes ") or cmd == "list classes":
            return "list_classes"
        if cmd.startswith("list dataclasses ") or cmd == "list dataclasses":
            return "list_dataclasses"
        if cmd.startswith("list methods ") or cmd == "list methods":
            return "list_methods"
        if cmd.startswith("list async defs ") or cmd == "list async defs":
            return "list_async_defs"
        if cmd.startswith("list lines ") or cmd == "list lines":
            return "list_lines"
        if cmd.startswith("read line "):
            return "read_line"
        if cmd.startswith("read lines "):
            return "read_lines"
        if cmd.startswith("read def "):
            return "read_def"
        if cmd.startswith("read class "):
            return "read_class"
        if cmd.startswith("read dataclass "):
            return "read_dataclass"
        if cmd.startswith("read method "):
            return "read_method"
        if cmd.startswith("replace def "):
            return "replace_def"
        if cmd.startswith("replace class "):
            return "replace_class"
        if cmd.startswith("replace dataclass "):
            return "replace_dataclass"
        if cmd.startswith("replace method "):
            return "replace_method"
        if cmd.startswith("replace line "):
            return "replace_line"
        if cmd.startswith("replace lines "):
            return "replace_lines"
        if cmd.startswith("replace char "):
            return "replace_char"
        if cmd.startswith("insert char "):
            return "insert_char"
        if cmd.startswith("delete char "):
            return "delete_char"
        if cmd.startswith("replace word "):
            return "replace_word"
        if cmd.startswith("replace in "):
            return "replace"
        if cmd.startswith("insert after "):
            return "insert_after"
        if cmd.startswith("insert before "):
            return "insert_before"
        if cmd.startswith("prepend "):
            return "prepend"
        if cmd.startswith("pastefile "):
            return "pastefile"
        if cmd.startswith("pasteappend "):
            return "pasteappend"

        # ---------------------- Simple controls ----------------------
        if cmd in {"help", "?", "commands"}:
            return "help"
        if cmd in {"pwd", "where am i", "current dir"}:
            return "pwd"
        if cmd in {"trust", "status", "rhea status"}:
            return "status"
        if cmd in {"history", "entropy history"}:
            return "history"

        # ---------------------- Generic command buckets ----------------------
        if (
            cmd.startswith("run ")
            or cmd.startswith("execute ")
            or cmd.startswith("test ")
            or cmd.startswith("shell ")
            or cmd.startswith("cmd ")
            or cmd.startswith("python ")
        ):
            return "run"

        if cmd == "git" or cmd.startswith("git "):
            return "git"

        if (
            cmd == "list"
            or cmd == "ls"
            or cmd == "dir"
            or cmd == "files"
            or cmd == "directory"
            or cmd.startswith("list ")
            or cmd.startswith("ls ")
            or cmd.startswith("dir ")
            or cmd.startswith("files ")
            or cmd.startswith("directory ")
        ):
            return "list"

        if (
            cmd == "read"
            or cmd == "cat"
            or cmd == "show"
            or cmd == "view"
            or cmd == "open"
            or cmd.startswith("read ")
            or cmd.startswith("cat ")
            or cmd.startswith("show ")
            or cmd.startswith("view ")
            or cmd.startswith("open ")
        ):
            return "read"

        if (
            cmd == "edit"
            or cmd == "write"
            or cmd == "change"
            or cmd == "update"
            or cmd == "append"
            or cmd == "create"
            or cmd.startswith("edit ")
            or cmd.startswith("write ")
            or cmd.startswith("change ")
            or cmd.startswith("update ")
            or cmd.startswith("append ")
            or cmd.startswith("create ")
        ):
            return "edit"

        return "help"


# ---------------- ARG PARSING ----------------

def safe_split(text: str) -> list[str]:
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


def extract_file_and_content(tokens: list[str]) -> Tuple[Optional[str], Optional[str]]:
    if len(tokens) < 2:
        return None, None
    file_name = tokens[1]
    content = " ".join(tokens[2:]) if len(tokens) > 2 else None
    return file_name, content


def parse_line_range(text: str) -> Tuple[int, int]:
    if ":" in text:
        left, right = text.split(":", 1)
        return int(left), int(right)
    value = int(text)
    return value, value


def extract_inline_after_marker(raw: str, marker: str) -> str:
    lower_raw = raw.lower()
    lower_marker = marker.lower()
    idx = lower_raw.find(lower_marker)
    if idx == -1:
        return ""
    remainder = raw[idx + len(marker):]
    return remainder.lstrip()


def extract_path_for_list(text: str) -> Optional[str]:
    tokens = safe_split(text)
    for i, token in enumerate(tokens):
        if token.lower() in {"list", "ls", "dir", "files", "directory"} and i + 1 < len(tokens):
            return tokens[i + 1]
    return None


def extract_read_args(text: str) -> dict:
    tokens = safe_split(text)
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


def extract_edit_args(text: str) -> dict:
    tokens = safe_split(text)
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
            inline = extract_inline_after_marker(text, tokens[2])
            content = inline if inline else None
        elif len(tokens) >= 3:
            content = " ".join(tokens[2:])

    return {"file": file_name, "content": content, "append": append, "content_mode": content_mode}


def extract_replace_args(text: str) -> dict:
    tokens = safe_split(text)
    if len(tokens) < 5:
        return {"file": None, "old": None, "new": None}

    if tokens[0].lower() == "replace" and tokens[1].lower() == "in":
        return {"file": tokens[2], "old": tokens[3], "new": tokens[4]}

    return {"file": None, "old": None, "new": None}


def extract_insert_args(text: str, after: bool) -> dict:
    tokens = safe_split(text)
    if len(tokens) < 5:
        return {"file": None, "anchor": None, "content": None}

    expected = "after" if after else "before"
    if tokens[0].lower() == "insert" and tokens[1].lower() == expected:
        return {"file": tokens[2], "anchor": tokens[3], "content": tokens[4]}

    return {"file": None, "anchor": None, "content": None}


def extract_prepend_args(text: str) -> dict:
    tokens = safe_split(text)
    if len(tokens) < 3:
        return {"file": None, "content": None}
    return {"file": tokens[1], "content": " ".join(tokens[2:])}


def extract_paste_args(text: str) -> dict:
    tokens = safe_split(text)
    if len(tokens) < 2:
        return {"file": None, "initial_content": None}

    initial_content = None
    if len(tokens) >= 3:
        initial_content = extract_inline_after_marker(text, tokens[1])

    return {"file": tokens[1], "initial_content": initial_content}


def extract_single_file_arg_after_two_tokens(text: str) -> dict:
    tokens = safe_split(text)
    return {"file": tokens[2]} if len(tokens) >= 3 else {"file": None}


def extract_single_file_arg_after_three_tokens(text: str) -> dict:
    tokens = safe_split(text)
    return {"file": tokens[3]} if len(tokens) >= 4 else {"file": None}


def extract_list_methods_args(text: str) -> dict:
    tokens = safe_split(text)
    if len(tokens) >= 4:
        return {"file": tokens[2], "class_name": tokens[3]}
    if len(tokens) >= 3:
        return {"file": tokens[2], "class_name": None}
    return {"file": None, "class_name": None}


def extract_read_line_args(text: str) -> dict:
    tokens = safe_split(text)
    if len(tokens) < 4:
        return {"file": None, "line_no": None}
    return {"file": tokens[2], "line_no": int(tokens[3])}


def extract_read_linesArgs_base(tokens: list[str]) -> dict:
    if len(tokens) < 4:
        return {"file": None, "start_line": None, "end_line": None}
    start, end = parse_line_range(tokens[3])
    return {"file": tokens[2], "start_line": start, "end_line": end}


def extract_read_lines_args(text: str) -> dict:
    return extract_read_linesArgs_base(safe_split(text))


def extract_read_named_object_args(text: str, kind: str) -> dict:
    tokens = safe_split(text)
    if len(tokens) < 4:
        return {"file": None, "name": None}
    return {"file": tokens[2], "name": tokens[3]}


def extract_read_method_args(text: str) -> dict:
    tokens = safe_split(text)
    if len(tokens) < 5:
        return {"file": None, "class_name": None, "method_name": None}
    return {"file": tokens[2], "class_name": tokens[3], "method_name": tokens[4]}


def extract_replace_named_object_args(text: str, kind: str) -> dict:
    tokens = safe_split(text)
    if len(tokens) < 5:
        return {"file": None, "name": None, "replacement": None, "content_mode": None}

    file_name = tokens[2]
    name = tokens[3]
    replacement = None
    content_mode = None

    if tokens[4].lower() == "pastefile":
        content_mode = "pastefile"
        inline = extract_inline_after_marker(text, tokens[4])
        replacement = inline if inline else None
    else:
        replacement = " ".join(tokens[4:])

    return {
        "file": file_name,
        "name": name,
        "replacement": replacement,
        "content_mode": content_mode,
    }


def extract_replace_method_args(text: str) -> dict:
    tokens = safe_split(text)
    if len(tokens) < 6:
        return {
            "file": None,
            "class_name": None,
            "method_name": None,
            "replacement": None,
            "content_mode": None,
        }

    file_name = tokens[2]
    class_name = tokens[3]
    method_name = tokens[4]
    replacement = None
    content_mode = None

    if tokens[5].lower() == "pastefile":
        content_mode = "pastefile"
        inline = extract_inline_after_marker(text, tokens[5])
        replacement = inline if inline else None
    else:
        replacement = " ".join(tokens[5:])

    return {
        "file": file_name,
        "class_name": class_name,
        "method_name": method_name,
        "replacement": replacement,
        "content_mode": content_mode,
    }


def extract_replace_line_args(text: str) -> dict:
    tokens = safe_split(text)
    if len(tokens) < 5:
        return {"file": None, "line_no": None, "replacement": None, "content_mode": None}

    if tokens[4].lower() == "pastefile":
        content_mode = "pastefile"
        inline = extract_inline_after_marker(text, tokens[4])
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


def extract_replace_lines_args(text: str) -> dict:
    tokens = safe_split(text)
    if len(tokens) < 5:
        return {"file": None, "start_line": None, "end_line": None, "replacement": None, "content_mode": None}

    start, end = parse_line_range(tokens[3])

    if tokens[4].lower() == "pastefile":
        content_mode = "pastefile"
        inline = extract_inline_after_marker(text, tokens[4])
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


def extract_replace_char_args(text: str) -> dict:
    tokens = safe_split(text)
    if len(tokens) < 6:
        return {"file": None, "line_no": None, "char_pos": None, "new_char": None}
    return {
        "file": tokens[2],
        "line_no": int(tokens[3]),
        "char_pos": int(tokens[4]),
        "new_char": tokens[5],
    }


def extract_insert_char_args(text: str) -> dict:
    tokens = safe_split(text)
    if len(tokens) < 6:
        return {"file": None, "line_no": None, "char_pos": None, "char": None}
    return {
        "file": tokens[2],
        "line_no": int(tokens[3]),
        "char_pos": int(tokens[4]),
        "char": tokens[5],
    }


def extract_delete_char_args(text: str) -> dict:
    tokens = safe_split(text)
    if len(tokens) < 5:
        return {"file": None, "line_no": None, "char_pos": None}
    return {
        "file": tokens[2],
        "line_no": int(tokens[3]),
        "char_pos": int(tokens[4]),
    }


def extract_replace_word_args(text: str) -> dict:
    tokens = safe_split(text)
    if len(tokens) < 6:
        return {"file": None, "scope": None, "old": None, "new": None}
    return {
        "file": tokens[2],
        "scope": tokens[3],
        "old": tokens[4],
        "new": tokens[5],
    }


def extract_select_object_args(text: str) -> dict:
    tokens = safe_split(text)
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


def extract_replace_selection_args(text: str) -> dict:
    tokens = safe_split(text)
    if len(tokens) < 3:
        return {"replacement": None, "content_mode": None}

    if tokens[2].lower() == "pastefile":
        inline = extract_inline_after_marker(text, tokens[2])
        return {"replacement": inline if inline else None, "content_mode": "pastefile"}

    return {"replacement": " ".join(tokens[2:]), "content_mode": None}


def extract_vcs_diff_args(text: str) -> dict:
    tokens = safe_split(text)
    cached = "--cached" in tokens
    file_name = None
    for token in tokens[2:]:
        if token != "--cached":
            file_name = token
            break
    return {"file": file_name, "cached": cached}


def extract_vcs_log_args(text: str) -> dict:
    tokens = safe_split(text)
    limit = 10
    if len(tokens) >= 3:
        try:
            limit = int(tokens[2])
        except ValueError:
            pass
    return {"limit": limit}


def extract_vcs_filelog_args(text: str) -> dict:
    tokens = safe_split(text)
    file_name = None
    limit = 10
    if len(tokens) >= 3:
        file_name = tokens[2]
    if len(tokens) >= 4:
        try:
            limit = int(tokens[3])
        except ValueError:
            pass
    return {"file": file_name, "limit": limit}


def extract_checkpoint_args(text: str) -> dict:
    tokens = safe_split(text)
    note = None
    if len(tokens) >= 2:
        if tokens[1].lower() == "now":
            note = None
        else:
            note = " ".join(tokens[1:])
    return {"note": note}


def extract_rollback_show_args(text: str) -> dict:
    tokens = safe_split(text)
    limit = 20
    if len(tokens) >= 3:
        try:
            limit = int(tokens[2])
        except ValueError:
            pass
    return {"limit": limit}


def extract_rollback_file_args(text: str) -> dict:
    tokens = safe_split(text)
    file_name = tokens[2] if len(tokens) >= 3 else None
    return {"file": file_name}


def extract_rollback_to_args(text: str) -> dict:
    tokens = safe_split(text)
    commit = tokens[2] if len(tokens) >= 3 else None
    return {"commit": commit}


def extract_git_mode_args(text: str) -> dict:
    tokens = safe_split(text)
    mode = tokens[2] if len(tokens) >= 3 else None
    return {"mode": mode}


def extract_trace_list_args(text: str) -> dict:
    tokens = safe_split(text)
    limit = 20
    if len(tokens) >= 3:
        try:
            limit = int(tokens[2])
        except ValueError:
            pass
    return {"limit": limit}


def extract_trace_failures_args(text: str) -> dict:
    tokens = safe_split(text)
    limit = 20
    if len(tokens) >= 3:
        try:
            limit = int(tokens[2])
        except ValueError:
            pass
    return {"limit": limit}


def extract_trace_open_args(text: str) -> dict:
    tokens = safe_split(text)
    filename = tokens[2] if len(tokens) >= 3 else None
    return {"filename": filename}


def extract_trace_clear_args(text: str) -> dict:
    lowered = text.strip().lower()
    failures_only = lowered == "trace clear failures"
    return {"failures_only": failures_only}


def extract_run_command(text: str) -> Optional[str]:
    lowered = text.lower()
    prefixes = ["run ", "execute ", "test ", "shell ", "cmd "]
    for prefix in prefixes:
        if lowered.startswith(prefix):
            return text[len(prefix):].strip()
    if lowered.startswith("python "):
        return text
    return None


def extract_git_command(text: str) -> Optional[str]:
    stripped = text.strip()
    lowered = stripped.lower()

    if lowered == "git":
        return "git status"

    idx = lowered.find("git")
    if idx >= 0:
        git_cmd = stripped[idx:].strip()
        return git_cmd if git_cmd else "git status"

    return "git status"


# ---------------- Planning / repo inspection extractors ----------------

def extract_find_symbol_args(text: str) -> dict:
    tokens = safe_split(text)
    if len(tokens) < 3:
        return {"symbol": None}
    return {"symbol": " ".join(tokens[2:])}


def extract_where_used_args(text: str) -> dict:
    tokens = safe_split(text)
    if len(tokens) < 3:
        return {"needle": None}
    return {"needle": " ".join(tokens[2:])}


def extract_find_tests_args(text: str) -> dict:
    tokens = safe_split(text)
    if len(tokens) < 3:
        return {"target": None}
    return {"target": " ".join(tokens[2:])}


def extract_task_args(text: str) -> dict:
    stripped = text.strip()
    lowered = stripped.lower()

    if lowered == "task":
        return {"request": None}
    if lowered.startswith("task "):
        return {"request": stripped[5:].strip()}
    return {"request": None}


def extract_task_checkpoint_args(text: str) -> dict:
    stripped = text.strip()
    lowered = stripped.lower()
    if lowered == "task checkpoint":
        return {"note": None}
    if lowered.startswith("task checkpoint "):
        return {"note": stripped[len("task checkpoint "):].strip()}
    return {"note": None}


def extract_args(role: str, raw_cmd: str) -> dict:
    stripped = raw_cmd.strip()

    # ---------------- Planning / repo inspection ----------------
    if role == "inspect_repo":
        return {}
    if role == "find_symbol":
        return extract_find_symbol_args(stripped)
    if role == "where_used":
        return extract_where_used_args(stripped)
    if role == "find_tests":
        return extract_find_tests_args(stripped)
    if role == "task":
        return extract_task_args(stripped)
    if role == "show_task":
        return {}
    if role == "task_execute":
        return {}
    if role == "task_validate":
        return {}
    if role == "task_checkpoint":
        return extract_task_checkpoint_args(stripped)
    if role == "task_clear":
        return {}

    if role == "list":
        return {"path": extract_path_for_list(stripped)}
    if role == "read":
        return extract_read_args(stripped)
    if role == "edit":
        return extract_edit_args(stripped)

    if role == "replace":
        return extract_replaceArgs(stripped)  # intentionally corrected below
    if role == "replace_line":
        return extract_replace_line_args(stripped)
    if role == "replace_lines":
        return extract_replace_lines_args(stripped)
    if role == "replace_char":
        return extract_replace_char_args(stripped)
    if role == "insert_char":
        return extract_insert_char_args(stripped)
    if role == "delete_char":
        return extract_delete_char_args(stripped)
    if role == "replace_word":
        return extract_replace_word_args(stripped)

    if role == "insert_after":
        return extract_insert_args(stripped, after=True)
    if role == "insert_before":
        return extract_insert_args(stripped, after=False)
    if role == "prepend":
        return extract_prepend_args(stripped)

    if role == "pastefile":
        return extract_paste_args(stripped)
    if role == "pasteappend":
        return extract_paste_args(stripped)

    if role == "list_defs":
        return extract_single_file_arg_after_two_tokens(stripped)
    if role == "list_classes":
        return extract_single_file_arg_after_two_tokens(stripped)
    if role == "list_dataclasses":
        return extract_single_file_arg_after_two_tokens(stripped)
    if role == "list_async_defs":
        return extract_single_file_arg_after_three_tokens(stripped)
    if role == "list_methods":
        return extract_list_methods_args(stripped)
    if role == "list_lines":
        return extract_single_file_arg_after_two_tokens(stripped)

    if role == "read_line":
        return extract_read_line_args(stripped)
    if role == "read_lines":
        return extract_read_lines_args(stripped)
    if role == "read_def":
        return extract_read_named_object_args(stripped, "def")
    if role == "read_class":
        return extract_read_named_object_args(stripped, "class")
    if role == "read_dataclass":
        return extract_read_named_object_args(stripped, "dataclass")
    if role == "read_method":
        return extract_read_method_args(stripped)

    if role == "replace_def":
        return extract_replace_named_object_args(stripped, "def")
    if role == "replace_class":
        return extract_replace_named_object_args(stripped, "class")
    if role == "replace_dataclass":
        return extract_replace_named_object_args(stripped, "dataclass")
    if role == "replace_method":
        return extract_replace_method_args(stripped)

    if role == "select_object":
        return extract_select_object_args(stripped)
    if role == "replace_selection":
        return extract_replace_selection_args(stripped)

    if role == "vcs_status":
        return {}
    if role == "vcs_diff":
        return extract_vcs_diff_args(stripped)
    if role == "vcs_log":
        return extract_vcs_log_args(stripped)
    if role == "vcs_filelog":
        return extract_vcs_filelog_args(stripped)
    if role == "checkpoint":
        return extract_checkpoint_args(stripped)
    if role == "rollback_show":
        return extract_rollback_show_args(stripped)
    if role == "rollback_last":
        return {}
    if role == "rollback_file":
        return extract_rollback_file_args(stripped)
    if role == "rollback_to":
        return extract_rollback_to_args(stripped)
    if role == "git_mode":
        return extract_git_mode_args(stripped)

    if role == "trace_status":
        return {}
    if role == "trace_last":
        return {}
    if role == "trace_on":
        return {}
    if role == "trace_off":
        return {}
    if role == "trace_list":
        return extract_trace_list_args(stripped)
    if role == "trace_failures":
        return extract_trace_failures_args(stripped)
    if role == "trace_open":
        return extract_trace_open_args(stripped)
    if role == "trace_clear":
        return extract_trace_clear_args(stripped)

    if role == "run":
        return {"cmd": extract_run_command(stripped), "check": True}
    if role == "git":
        return {"cmd": extract_git_command(stripped)}
    if role == "set_limit":
        return {"cmd": stripped}

    return {}


# alias guard for typo compatibility if any external code referenced the old internal name pattern
def extract_replaceArgs(text: str) -> dict:
    return extract_replace_args(text)