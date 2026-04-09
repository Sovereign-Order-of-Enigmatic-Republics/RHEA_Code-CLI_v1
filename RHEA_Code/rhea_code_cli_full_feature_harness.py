# -*- coding: utf-8 -*-
"""
RHEA Code CLI — Split Architecture Full Feature / Edge Case Harness
"""

from __future__ import annotations

import os
import re
import sys
import time
import shutil
import tempfile
import threading
import subprocess
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BANNER_TIMEOUT = 15.0
PROMPT_TIMEOUT = 20.0
LONG_TIMEOUT = 45.0

PACKAGE_DIRNAME = "RHEA_Code_CLI"
APP_MODULE = "RHEA_Code_CLI.cli.app"


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

@dataclass
class TestResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class ResultCollector:
    results: list[TestResult] = field(default_factory=list)

    def add(self, name: str, passed: bool, detail: str = "") -> None:
        self.results.append(TestResult(name=name, passed=passed, detail=detail))

    def require(self, name: str, condition: bool, detail: str = "") -> None:
        self.add(name, bool(condition), detail if not condition else detail)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.passed)

    def print_summary(self) -> None:
        print("\n" + "=" * 88)
        print("RHEA CODE CLI HARNESS SUMMARY")
        print("=" * 88)
        for idx, r in enumerate(self.results, 1):
            status = "PASS" if r.passed else "FAIL"
            print(f"{idx:03d}. [{status}] {r.name}")
            if r.detail and not r.passed:
                print(f"      {r.detail}")
        print("-" * 88)
        print(f"Passed: {self.passed}")
        print(f"Failed: {self.failed}")
        print("=" * 88)


# ---------------------------------------------------------------------------
# Interactive CLI driver
# ---------------------------------------------------------------------------

class InteractiveCLI:
    def __init__(self, cwd: Path, env: dict[str, str]) -> None:
        self.cwd = cwd
        self.env = env
        self.proc: Optional[subprocess.Popen[str]] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._buffer = ""
        self._buffer_lock = threading.Lock()
        self._stop_reader = threading.Event()

    def start(self) -> None:
        self.proc = subprocess.Popen(
            [sys.executable, "-m", APP_MODULE],
            cwd=str(self.cwd),
            env=self.env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=0,
        )
        assert self.proc.stdout is not None
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

    def stop(self) -> None:
        if self.proc is None:
            return
        try:
            if self.proc.stdin:
                try:
                    self.proc.stdin.write("exit\n")
                    self.proc.stdin.flush()
                except Exception:
                    pass
            self.proc.terminate()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=5)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass
        self._stop_reader.set()

    def _reader_loop(self) -> None:
        assert self.proc is not None
        assert self.proc.stdout is not None
        while not self._stop_reader.is_set():
            ch = self.proc.stdout.read(1)
            if ch == "":
                break
            with self._buffer_lock:
                self._buffer += ch

    def get_buffer(self) -> str:
        with self._buffer_lock:
            return self._buffer

    def _buffer_slice(self, start: int) -> str:
        with self._buffer_lock:
            return self._buffer[start:]

    def wait_for(self, needle: str, timeout: float = PROMPT_TIMEOUT) -> str:
        start = time.time()
        while time.time() - start < timeout:
            buf = self.get_buffer()
            if needle in buf:
                return buf
            if self.proc and self.proc.poll() is not None:
                return buf
            time.sleep(0.02)
        raise TimeoutError(f"Timed out waiting for: {needle!r}")

    def send_line(self, text: str) -> None:
        if self.proc is None or self.proc.stdin is None:
            raise RuntimeError("CLI process is not running")
        self.proc.stdin.write(text + "\n")
        self.proc.stdin.flush()

    def send_lines(self, lines: list[str]) -> None:
        for line in lines:
            self.send_line(line)

    def command(
        self,
        text: str,
        *,
        responses: Optional[list[tuple[str, str]]] = None,
        final_prompt: str = "RHEA> ",
        timeout: float = PROMPT_TIMEOUT,
    ) -> str:
        start_idx = len(self.get_buffer())
        self.send_line(text)

        handled: set[int] = set()
        start = time.time()

        while time.time() - start < timeout:
            chunk = self._buffer_slice(start_idx)

            if responses:
                for i, (prompt_text, reply) in enumerate(responses):
                    if i in handled:
                        continue
                    if prompt_text in chunk:
                        self.send_line(reply)
                        handled.add(i)

            if final_prompt in chunk:
                return chunk

            if self.proc and self.proc.poll() is not None:
                return chunk

            time.sleep(0.02)

        raise TimeoutError(f"Timed out waiting for final prompt after command: {text!r}")

    def interact_until_prompt(
        self,
        *,
        start_idx: int,
        final_prompt: str = "RHEA> ",
        responses: Optional[list[tuple[str, str]]] = None,
        timeout: float = LONG_TIMEOUT,
    ) -> str:
        handled: set[int] = set()
        start = time.time()

        while time.time() - start < timeout:
            chunk = self._buffer_slice(start_idx)

            if responses:
                for i, (prompt_text, reply) in enumerate(responses):
                    if i in handled:
                        continue
                    if prompt_text in chunk:
                        self.send_line(reply)
                        handled.add(i)

            if final_prompt in chunk:
                return chunk

            if self.proc and self.proc.poll() is not None:
                return chunk

            time.sleep(0.02)

        raise TimeoutError("Timed out waiting for interactive flow to return to prompt")

    def paste_command(
        self,
        command_text: str,
        paste_lines: list[str],
        *,
        expect_diff: bool = False,
        expect_commit_prompt: bool = False,
        timeout: float = LONG_TIMEOUT,
    ) -> str:
        start_idx = len(self.get_buffer())
        self.send_line(command_text)

        self.wait_for("Paste content below.", timeout=timeout)
        self.send_lines(paste_lines + ["__END__"])

        responses: list[tuple[str, str]] = []
        if expect_diff:
            responses.append(("Apply change?", "y"))
        if expect_commit_prompt:
            responses.append(("Commit this change now?", "n"))

        return self.interact_until_prompt(
            start_idx=start_idx,
            final_prompt="RHEA> ",
            responses=responses,
            timeout=timeout,
        )


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def ensure_repo_root() -> Path:
    here = Path.cwd()
    pkg = here / PACKAGE_DIRNAME
    if not pkg.exists():
        raise FileNotFoundError(f"Missing {PACKAGE_DIRNAME}/ in {here}")
    return here


def git_available() -> bool:
    return shutil.which("git") is not None


def run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def make_workspace() -> Path:
    return Path(tempfile.mkdtemp(prefix="rhea_code_cli_harness_"))


def build_env(repo_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    current_pythonpath = env.get("PYTHONPATH", "")
    entries = [str(repo_root)]
    if current_pythonpath:
        entries.append(current_pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(entries)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def write_sample_files(workspace: Path) -> None:
    (workspace / "sample_module.py").write_text(
        '''from dataclasses import dataclass

@dataclass
class Point:
    x: int
    y: int

def top_fn(value: int) -> int:
    return value + 1

class Demo:
    def method_a(self, text: str) -> str:
        return text.upper()

    async def method_b(self) -> str:
        return "async-ok"
''',
        encoding="utf-8",
    )

    (workspace / "multi.txt").write_text(
        "alpha\nbeta\ngamma\ndelta\n",
        encoding="utf-8",
    )

    (workspace / "notes.txt").write_text(
        "header\nbody\nfooter\n",
        encoding="utf-8",
    )

    (workspace / "empty.txt").write_text("", encoding="utf-8")


def maybe_init_git_repo(workspace: Path) -> bool:
    if not git_available():
        return False

    run_git(["init"], workspace)
    run_git(["config", "user.name", "RHEA Harness"], workspace)
    run_git(["config", "user.email", "rhea-harness@example.invalid"], workspace)
    run_git(["add", "."], workspace)
    first_commit = run_git(["commit", "-m", "Initial harness baseline"], workspace)
    return first_commit.returncode == 0


def contains(output: str, needle: str) -> bool:
    return needle in output


def role_is(output: str, role: str) -> bool:
    return f"Role: {role}" in output


def parse_first_trace_filename(output: str) -> Optional[str]:
    for line in output.splitlines():
        m = re.match(r"\s*\d+\.\s+(.+\.jsonl)\s*$", line)
        if m:
            return m.group(1).strip()
    return None


# ---------------------------------------------------------------------------
# Test suite
# ---------------------------------------------------------------------------

def run_suite(cli: InteractiveCLI, repo_enabled: bool, rc: ResultCollector) -> None:
    banner = cli.wait_for("RHEA> ", timeout=BANNER_TIMEOUT)
    rc.require("banner shows CLI title", "RHEA Code CLI" in banner, "Banner missing expected title")

    out = cli.command("help")
    rc.require("help command routes to help", role_is(out, "help"), out)
    rc.require("help contains VCS section", contains(out, "VCS / Git"), out)
    rc.require("help contains Trace section", contains(out, "Trace Profiler"), out)
    rc.require("help contains planning section", contains(out, "Repo inspection / planning"), out)
    rc.require("help contains task execute", contains(out, "task execute"), out)
    rc.require("help contains task validate", contains(out, "task validate"), out)
    rc.require("help contains task checkpoint", contains(out, "task checkpoint"), out)
    rc.require("help contains task clear", contains(out, "task clear"), out)

    # ---------------------- New planning / repo inspection surface ----------------------
    out = cli.command("inspect repo")
    rc.require("inspect repo routes correctly", role_is(out, "inspect_repo"), out)
    rc.require("inspect repo reports root", contains(out, "Root:"), out)
    rc.require("inspect repo reports python files", contains(out, "Python Files:"), out)

    out = cli.command("find symbol top_fn")
    rc.require("find symbol routes correctly", role_is(out, "find_symbol"), out)
    rc.require("find symbol finds top_fn", contains(out, "top_fn"), out)
    rc.require("find symbol identifies sample module", contains(out, "sample_module.py"), out)

    out = cli.command("where used method_a")
    rc.require("where used routes correctly", role_is(out, "where_used"), out)
    rc.require("where used finds method_a", contains(out, "method_a"), out)
    rc.require("where used finds sample module", contains(out, "sample_module.py"), out)

    out = cli.command("find tests sample_module")
    rc.require("find tests routes correctly", role_is(out, "find_tests"), out)
    rc.require(
        "find tests handles empty result sanely",
        ("No test files found for: sample_module" in out) or ("Related Tests: sample_module" in out),
        out,
    )

    out = cli.command("task add logging to sample_module.py and update tests")
    rc.require("task routes correctly", role_is(out, "task"), out)
    rc.require("task renders plan header", contains(out, "RHEA Task Plan"), out)
    rc.require("task includes goal", contains(out, "Goal:"), out)
    rc.require("task includes validation", contains(out, "Validation:"), out)
    rc.require("task includes rollback", contains(out, "Rollback:"), out)
    rc.require("task includes steps", contains(out, "Steps:"), out)

    out = cli.command("show task")
    rc.require("show task routes correctly", role_is(out, "show_task"), out)
    rc.require("show task displays active plan", contains(out, "RHEA Task Plan"), out)

    out = cli.command("find symbol does_not_exist_symbol_xyz")
    rc.require(
        "find symbol missing symbol handled",
        contains(out, "No symbol definitions found for: does_not_exist_symbol_xyz"),
        out,
    )

    out = cli.command("where used does_not_exist_symbol_xyz")
    rc.require(
        "where used missing symbol handled",
        contains(out, "No usages found for: does_not_exist_symbol_xyz"),
        out,
    )

    out = cli.command("task")
    rc.require(
        "bare task falls back sanely",
        contains(out, "Usage: task <human-readable request>"),
        out,
    )

    # ---------------------- Task execution surface ----------------------
    out = cli.command("task execute")
    rc.require("task execute routes correctly", role_is(out, "task_execute"), out)
    rc.require("task execute shows plan", contains(out, "RHEA Task Plan"), out)
    rc.require("task execute records execution section", contains(out, "Task Execution"), out)
    rc.require("task execute records action", contains(out, "Action: execute"), out)
    rc.require("task execute records success", contains(out, "Success:"), out)

    out = cli.command("task validate")
    rc.require("task validate routes correctly", role_is(out, "task_validate"), out)
    rc.require("task validate shows plan", contains(out, "RHEA Task Plan"), out)
    rc.require("task validate records execution section", contains(out, "Task Execution"), out)
    rc.require("task validate records action", contains(out, "Action: validate"), out)
    rc.require(
        "task validate records validation result",
        contains(out, "Validation passed.") or contains(out, "Validation failed.") or contains(out, "syntax"),
        out,
    )

    if repo_enabled:
        out = cli.command("task checkpoint")
        rc.require("task checkpoint routes correctly", role_is(out, "task_checkpoint"), out)
        rc.require("task checkpoint shows plan", contains(out, "RHEA Task Plan"), out)
        rc.require("task checkpoint records execution section", contains(out, "Task Execution"), out)
        rc.require("task checkpoint records action", contains(out, "Action: task_checkpoint"), out)
        rc.require(
            "task checkpoint records checkpoint result",
            contains(out, "Task checkpoint created.")
            or contains(out, "Task checkpoint failed.")
            or contains(out, "No task target files could be staged."),
            out,
        )

    out = cli.command("task clear")
    rc.require("task clear routes correctly", role_is(out, "task_clear"), out)
    rc.require("task clear clears active plan", contains(out, "Cleared active task plan."), out)

    out = cli.command("show task")
    rc.require("show task after clear reports empty", contains(out, "No active task plan."), out)

    out = cli.command("task validate")
    rc.require("task validate without task handled", contains(out, "No active task plan."), out)

    out = cli.command("task execute")
    rc.require("task execute without task handled", contains(out, "No active task plan."), out)

    out = cli.command("task checkpoint")
    rc.require("task checkpoint without task handled", contains(out, "No active task plan."), out)

    out = cli.command("task clear")
    rc.require("task clear without task handled", contains(out, "No active task plan."), out)

    # Recreate task so later status/history continue to show task support exercised.
    out = cli.command("task add logging to sample_module.py and update tests")
    rc.require("task recreated after clear", contains(out, "RHEA Task Plan"), out)

    # ---------------------- Existing trace / control surface ----------------------
    out = cli.command("trace status")
    rc.require("trace status routes correctly", role_is(out, "trace_status"), out)
    rc.require("trace status prints enabled flag", contains(out, "Profiling Enabled"), out)

    out = cli.command("trace list")
    rc.require("trace list routes correctly", role_is(out, "trace_list"), out)

    out = cli.command("trace failures")
    rc.require("trace failures routes correctly", role_is(out, "trace_failures"), out)

    out = cli.command("trace open")
    rc.require("trace open routes correctly", role_is(out, "trace_open"), out)
    rc.require("trace open without filename gives usage", contains(out, "Usage: trace open <filename>"), out)

    out = cli.command("no_truncate")
    rc.require("no_truncate routes correctly", role_is(out, "no_truncate"), out)

    out = cli.command("no truncate")
    rc.require("no truncate routes correctly", role_is(out, "no_truncate"), out)

    out = cli.command("no truncation")
    rc.require("no truncation routes correctly", role_is(out, "no_truncate"), out)

    out = cli.command("truncate on")
    rc.require("truncate on routes correctly", role_is(out, "truncate_on"), out)

    out = cli.command("set limit 4096")
    rc.require("set limit routes correctly", role_is(out, "set_limit"), out)
    rc.require("set limit applies", contains(out, "4096"), out)

    out = cli.command("set limit nope")
    rc.require("invalid set limit handled", contains(out, "Usage: set limit <number>"), out)

    out = cli.command("diff off")
    rc.require("diff off routes correctly", role_is(out, "diff_off"), out)

    if repo_enabled:
        out = cli.command("git mode off")
        rc.require("git mode off routes", role_is(out, "git_mode"), out)
        rc.require("git mode off applies", contains(out, "off"), out)

    out = cli.command("write test_1.py")
    rc.require("write test_1.py routes as edit", role_is(out, "edit"), out)
    rc.require("write test_1.py creates file", contains(out, "Wrote"), out)

    out = cli.command('write test_2.py "print(\'hello\')"')
    rc.require("write with inline content routes as edit", role_is(out, "edit"), out)
    rc.require("write inline content writes file", contains(out, "Wrote"), out)

    out = cli.command(r'append test_2.py "\nprint(\'world\')"')
    rc.require("append routes as edit", role_is(out, "edit"), out)
    rc.require("append appends content", contains(out, "Appended"), out)

    out = cli.command("read test_2.py full")
    rc.require("read file routes as read", role_is(out, "read"), out)
    rc.require("read file contains hello", contains(out, "hello"), out)
    rc.require("read file contains world", contains(out, "world"), out)

    out = cli.command("list")
    rc.require("list routes correctly", role_is(out, "list"), out)
    rc.require("list shows created file", contains(out, "test_2.py"), out)

    out = cli.command("read does_not_exist.txt")
    rc.require("read missing file handled", contains(out, "File not found"), out)

    out = cli.paste_command(
        "write combo.py pastefile # -*- coding: utf-8 -*-",
        [
            "def combo():",
            "    return 'combo-ok'",
        ],
        expect_diff=False,
        expect_commit_prompt=False,
    )
    rc.require("combined pastefile command routes as edit", "Role: edit" in out, out)
    rc.require("combined pastefile writes content", ("Wrote pasted content" in out) or ("Wrote" in out), out)

    out = cli.command("read combo.py full")
    rc.require("combined pastefile preserves inline seed line", contains(out, "# -*- coding: utf-8 -*-"), out)
    rc.require("combined pastefile writes function body", contains(out, "def combo()"), out)
    rc.require("combined pastefile writes return body", contains(out, "combo-ok"), out)

    out = cli.paste_command(
        "pastefile test_2.py",
        [
            "# -*- coding: utf-8 -*-",
            "def pasted():",
            "    return 'ok'",
        ],
        expect_diff=False,
        expect_commit_prompt=False,
    )
    rc.require("pastefile writes content", "Wrote pasted content" in out, out)

    out = cli.command("read test_2.py full")
    rc.require("test_2.py contains utf8 header", contains(out, "# -*- coding: utf-8 -*-"), out)
    rc.require("test_2.py contains function", contains(out, "def pasted"), out)

    out = cli.paste_command(
        "pasteappend test_2.py",
        [
            "",
            "def appended():",
            "    return 'more'",
        ],
        expect_diff=False,
        expect_commit_prompt=False,
    )
    rc.require("pasteappend appends content", "Appended pasted content" in out, out)

    out = cli.command("read test_2.py full")
    rc.require("pasteappend content present", contains(out, "def appended"), out)

    out = cli.command('replace in notes.txt "body" "BODY"')
    rc.require("replace anchor works", contains(out, "Replaced 1 occurrence"), out)

    out = cli.command('replace in notes.txt "missing" "x"')
    rc.require("replace missing anchor handled", contains(out, "Anchor text not found"), out)

    out = cli.command('insert after notes.txt "header" "\\nAFTER_HEADER"')
    rc.require("insert after works", contains(out, "Inserted after"), out)

    out = cli.command('insert before notes.txt "footer" "BEFORE_FOOTER\\n"')
    rc.require("insert before works", contains(out, "Inserted before"), out)

    out = cli.command('prepend notes.txt "PREPENDED\\n"')
    rc.require("prepend works", contains(out, "Prepended content"), out)

    out = cli.command("read notes.txt full")
    rc.require("prepend content present", contains(out, "PREPENDED"), out)
    rc.require("insert after content present", contains(out, "AFTER_HEADER"), out)
    rc.require("insert before content present", contains(out, "BEFORE_FOOTER"), out)

    out = cli.command('replace line multi.txt 2 "BETA"')
    rc.require("replace line works", contains(out, "Replaced line 2"), out)

    out = cli.command('replace lines multi.txt 3:4 "GAMMA\\nDELTA"')
    rc.require("replace lines works", contains(out, "Replaced lines 3:4"), out)

    out = cli.command('replace char multi.txt 1 1 "A"')
    rc.require("replace char works", contains(out, "Replaced char"), out)

    out = cli.command('insert char multi.txt 1 2 "Z"')
    rc.require("insert char works", contains(out, "Inserted char"), out)

    out = cli.command("delete char multi.txt 1 2")
    rc.require("delete char works", contains(out, "Deleted char"), out)

    out = cli.command('replace word multi.txt 2 "BETA" "beta"')
    rc.require("replace word line-scope works", contains(out, "Replaced word"), out)

    out = cli.command('replace word multi.txt all "DELTA" "delta"')
    rc.require("replace word file-scope works", contains(out, "Replaced word"), out)

    out = cli.command("read multi.txt full")
    rc.require("replace line content present", contains(out, "beta"), out)
    rc.require("replace lines content present", contains(out, "GAMMA"), out)
    rc.require("replace word file-scope content present", contains(out, "delta"), out)

    out = cli.command('replace line multi.txt 999 "oops"')
    rc.require("replace line out-of-bounds handled", contains(out, "Line range out of bounds"), out)

    out = cli.command('replace char multi.txt 1 999 "x"')
    rc.require("replace char out-of-bounds handled", contains(out, "Character position out of range"), out)

    out = cli.command("list defs sample_module.py")
    rc.require("list defs works", contains(out, "top_fn"), out)

    out = cli.command("list classes sample_module.py")
    rc.require("list classes works", contains(out, "Demo"), out)

    out = cli.command("list dataclasses sample_module.py")
    rc.require("list dataclasses works", contains(out, "Point"), out)

    out = cli.command("list methods sample_module.py Demo")
    rc.require("list methods works", contains(out, "method_a"), out)

    out = cli.command("list async defs sample_module.py")
    rc.require("list async defs works", contains(out, "Async defs"), out)

    out = cli.command("read def sample_module.py top_fn")
    rc.require("read def works", contains(out, "def top_fn"), out)

    out = cli.command("read class sample_module.py Demo")
    rc.require("read class works", contains(out, "class Demo"), out)

    out = cli.command("read dataclass sample_module.py Point")
    rc.require("read dataclass works", contains(out, "@dataclass"), out)

    out = cli.command("read method sample_module.py Demo method_a")
    rc.require("read method works", contains(out, "def method_a"), out)

    out = cli.command("read def sample_module.py method_a")
    rc.require("read def fallback to method works", contains(out, "Found method"), out)

    out = cli.command("select method sample_module.py Demo method_a")
    rc.require("select method works", contains(out, "Selected method"), out)

    out = cli.command("show selection")
    rc.require("show selection works", contains(out, "Current Selection"), out)

    out = cli.command("read selection")
    rc.require("read selection works", contains(out, "method_a"), out)

    out = cli.command(
        'replace selection "    def method_a(self, text: str) -> str:\\n        return text.lower()\\n"'
    )
    rc.require("replace selection works", contains(out, "Replaced current selection"), out)

    out = cli.command("read method sample_module.py Demo method_a")
    rc.require("replace selection changed method", contains(out, "lower"), out)

    out = cli.command(
        'replace def sample_module.py top_fn "def top_fn(value: int) -> int:\\n    return value + 2\\n"'
    )
    rc.require("replace def works", contains(out, "Replaced def top_fn"), out)

    out = cli.command("read def sample_module.py top_fn")
    rc.require("replace def changed content", contains(out, "value + 2"), out)

    out = cli.command(
        'replace method sample_module.py Demo method_a "    def method_a(self, text: str) -> str:\\n        return text[::-1]\\n"'
    )
    rc.require("replace method works", contains(out, "Replaced"), out)

    out = cli.command("read method sample_module.py Demo method_a")
    rc.require("replace method changed content", contains(out, "[::-1]"), out)

    out = cli.command('run python -c "print(\'ok\')"')
    rc.require("run python -c success routes as run", role_is(out, "run"), out)
    rc.require("run python -c success output present", contains(out, "ok"), out)

    out = cli.command('run python -c "raise RuntimeError(\'boom\')"')
    rc.require("run python failure emits failure profile", contains(out, "Success: False"), out)

    out = cli.command("trace last")
    rc.require("trace last shows most recent run command", contains(out, "RuntimeError"), out)

    out = cli.command("run python")
    rc.require("interactive python blocked", contains(out, "Interactive Python sessions are disabled"), out)

    out = cli.command("trace list")
    rc.require("trace list prints files", contains(out, "Saved Trace Files"), out)
    first_trace = parse_first_trace_filename(out)

    out = cli.command("trace failures")
    rc.require(
        "trace failures prints list or empty message",
        contains(out, "Saved Failure Trace Files") or contains(out, "No saved failure trace files found."),
        out,
    )

    if first_trace:
        out = cli.command(f"trace open {first_trace}")
        rc.require(
            "trace open reads saved file",
            contains(out, "Timestamp:") or contains(out, '"command"') or contains(out, "Command:"),
            out,
        )

    out = cli.command("trace clear failures", responses=[("Clear failure saved trace files?", "n")])
    rc.require("trace clear failures cancel path works", contains(out.lower(), "canceled") or contains(out, "Trace clear canceled."), out)

    if repo_enabled:
        out = cli.command("git mode manual")
        rc.require("git mode manual works", contains(out, "manual"), out)

        out = cli.command("vcs status")
        rc.require("vcs status works", contains(out, "RHEA VCS Status"), out)

        out = cli.command("vcs log")
        rc.require(
            "vcs log works",
            contains(out, "No commits yet") or contains(out, "Initial harness baseline") or contains(out, "RHEA_CHECKPOINT"),
            out,
        )

        out = cli.command("vcs filelog sample_module.py")
        rc.require(
            "vcs filelog works",
            contains(out, "sample_module.py") or contains(out, "No commit history yet") or contains(out, "[exit=0]"),
            out,
        )

        cli.command('append notes.txt "\\nrepo-change"')
        out = cli.command("checkpoint")
        rc.require("checkpoint works", contains(out, "[exit=0]") or contains(out, "No changes to checkpoint."), out)

        out = cli.command("rollback show")
        rc.require("rollback show works", contains(out, "[exit=0]") or contains(out, "No commits yet"), out)

    out = cli.command("history")
    rc.require("history works", contains(out, "Recent Commands:"), out)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    rc = ResultCollector()
    cli: Optional[InteractiveCLI] = None
    workspace: Optional[Path] = None

    try:
        repo_root = ensure_repo_root()
        workspace = make_workspace()
        write_sample_files(workspace)
        repo_enabled = maybe_init_git_repo(workspace)

        env = build_env(repo_root)
        cli = InteractiveCLI(cwd=workspace, env=env)
        cli.start()

        run_suite(cli, repo_enabled=repo_enabled, rc=rc)

    except Exception as e:
        rc.add("harness fatal error", False, f"{type(e).__name__}: {e}")
    finally:
        if cli is not None:
            try:
                cli.stop()
            except Exception:
                pass

    rc.print_summary()

    if workspace:
        print(f"\nWorkspace kept at: {workspace}")

    return 1 if rc.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())