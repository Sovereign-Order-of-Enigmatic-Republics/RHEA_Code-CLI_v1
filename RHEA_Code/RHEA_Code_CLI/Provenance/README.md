# RHEA Code CLI — Provenance & Usage (README_CLI.md)

---

## Overview

RHEA Code CLI is a structured, human-readable coding interface that translates plain-language commands into deterministic file operations, code navigation, repository inspection, and controlled automation workflows.

It is built on a split architecture designed for:

* clarity (no monolithic black boxes)
* testability (harness-driven validation)
* control (explicit operator intent)

---

## Architecture (Where Things Live)

```
RHEA_Code_CLI/cli/
├── app.py          # Entry point
├── session.py      # Runtime loop + state
├── parsing.py      # Command routing + argument extraction
├── editing.py      # File + code-object operations
├── integration.py  # VCS, trace, repo tools, shell
├── tasking.py      # Task model
├── planner.py      # Task generation
├── workspace.py    # Repo inspection + symbol analysis
```

---

## Core Command Families

### Planning & Repo Intelligence

```
inspect repo
find symbol <name>
where used <name>
find tests <name>
```

### Task System

```
task <request>
show task
task execute
task validate
task checkpoint [note]
task clear
```

### File Operations

```
read <file>
write <file> "text"
append <file> "text"
pastefile <file>
pasteappend <file>
```

### Line / Range Editing

```
replace line <file> <n> "text"
replace lines <file> <start:end> pastefile
```

### Character-Level Editing

```
replace char <file> <line> <pos> "X"
insert char <file> <line> <pos> "("
delete char <file> <line> <pos>
```

### Word / Anchor Editing

```
replace word <file> <line|all> <old> <new>
replace in <file> <old> <new>
insert after <file> <anchor> <content>
insert before <file> <anchor> <content>
prepend <file> <content>
```

---

## Structured Python Navigation

### Inspect Code

```
list defs <file>
list classes <file>
list dataclasses <file>
list methods <file> <Class>
list async defs <file>
```

### Read Objects

```
read def <file> <name>
read class <file> <name>
read dataclass <file> <name>
read method <file> <Class> <method>
```

### Replace Objects

```
replace def <file> <name> pastefile
replace class <file> <name> pastefile
replace method <file> <Class> <method> pastefile
```

---

## Selection Workflow (Precision Editing)

```
select method <file> <Class> <method>
show selection
read selection
replace selection pastefile
```

---

## Trace & Diagnostics

```
trace status
trace last
trace list
trace failures
trace open <file>
trace clear
trace clear failures
```

---

## Git / Safety Layer

```
vcs status
vcs diff
vcs log
vcs filelog <file>
checkpoint
rollback show
rollback file <file>
rollback to <commit>

git mode off|manual|checkpoint_only|auto_commit
```

---

## Output Controls

```
no truncate
truncate on
set limit <n>
diff on
diff off
```

---

## Shell Execution

```
run python script.py
run python -c "print('ok')"
git status
```

Guardrails prevent unsafe interactive shells.

---

## Startup

```
python -m RHEA_Code_CLI.cli.app
```

Prompt:

```
RHEA>
```

---

## Typical Workflows

### 1. Inspect Before Editing

```
inspect repo
find symbol parser
where used parser
```

### 2. Direct Change

```
read file.py full
replace line file.py 20 "return x + 1"
```

### 3. Structured Edit

```
list defs file.py
replace def file.py my_func pastefile
```

### 4. Selection Editing

```
select method file.py Demo run
replace selection pastefile
```

### 5. Task Workflow

```
task add logging to parser
show task
task validate
task checkpoint
```

### 6. Safe Workflow (Git)

```
git mode checkpoint_only
checkpoint
rollback show
```

### 7. Debug Failure

```
trace last
trace failures
```

---

## Provenance Summary

| Feature         | Module                  |
| --------------- | ----------------------- |
| Command parsing | parsing.py              |
| Editing engine  | editing.py              |
| Repo inspection | workspace.py            |
| Task planning   | planner.py / tasking.py |
| Trace system    | integration.py          |
| Git / VCS       | integration.py          |
| Runtime loop    | session.py              |

All features are validated through the CLI harness (routing, editing, tracing, VCS, and planning flows).

---

## Philosophy (Why It Works)

* Explicit commands over guesswork
* Structure over string-hacking
* Safety before speed
* Small tools that actually do what they say

Or put plainly: fewer magic tricks, more working parts.

---

## Next Steps (Natural Evolution)

* Step-aware task execution
* Auto-validation hooks
* Repo-aware planning heuristics
* Semi-automated refactor flows

That’s where this stops being a tool… and starts acting like an operator.

