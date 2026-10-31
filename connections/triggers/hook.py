"""The AI-edit and end-of-turn triggers, for Claude Code's hooks (Track D, step D10).

The proposal says events in the harness, such as an AI edit or the end of a
turn, start the verification procedures (Overview paragraph 2). Appendix A2.2
says triggers are designed for one harness's hooks, and Claude Code comes
first by the authors' ruling.

python3 -m connections trigger hook reads one Claude Code hook input on
standard input and prints what handle_hook returns.

- PostToolUse for Edit, Write, MultiEdit, or NotebookEdit marks as due the
  registered procedures whose file patterns match the edited file, with the
  file, in <connections home>/triggers/due/<folder key>.json.
- Stop reads and clears those marks and starts each due procedure once, in
  the background, through the scholar's start command in triggers.yaml. So a
  turn with many edits starts one run per procedure and the hook returns at
  once (Track D choice 18). Each start is logged as a ran action event
  (choice 21), and the status line names what was started and what has no
  start command.

The project is the input's cwd, else the working folder. Nothing is marked,
started, or printed in an excluded folder or while the audit settings file is
missing (choice 3). The hook always exits 0, writes nothing to standard
error, and never asks the harness to block or continue, so a failure here
never changes the turn (the track's rule that logging never interrupts).
"""
import fcntl
import json
import os
import subprocess
from datetime import datetime
from typing import Dict, List

from connections.events import append_event, make_event
from connections.home import connections_home, folder_key, recording_allowed
from connections.triggers.registry import (
    load_registry,
    load_trigger_settings,
    matching,
    start_command,
)

EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
TRIGGERS_FOLDER = "triggers"
DUE_FOLDER = "due"
LOGS_FOLDER = "logs"
PROGRAM = "trigger"


def handle_hook(text) -> str:
    """The text to print for one hook input, or empty text when there is nothing to say.

    Input that is not a JSON object, a hook event other than PostToolUse for
    an edit tool or Stop, and any failure all give empty text.
    """
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return ""
    if not isinstance(data, dict):
        return ""
    try:
        cwd = data.get("cwd")
        project = cwd if isinstance(cwd, str) and cwd else os.getcwd()
        event = data.get("hook_event_name")
        if event == "PostToolUse":
            _mark(data, project)
            return ""
        if event == "Stop":
            return _start_due(project)
    except Exception:
        return ""
    return ""


def due_path(project):
    """<connections home>/triggers/due/<folder key>.json for the project folder."""
    return connections_home() / TRIGGERS_FOLDER / DUE_FOLDER / f"{folder_key(project)}.json"


def _edited_file(data):
    if data.get("tool_name") not in EDIT_TOOLS:
        return None
    tool_input = data.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    for key in ("file_path", "notebook_path"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _relative(path, project) -> str:
    """The edited file as the project names it, relative with / between parts."""
    top = os.path.realpath(str(project))
    edited = path if os.path.isabs(path) else os.path.join(top, path)
    return os.path.relpath(os.path.realpath(edited), top).replace(os.sep, "/")


def _mark(data, project) -> None:
    path = _edited_file(data)
    if path is None or not recording_allowed(project):
        return
    settings = load_trigger_settings()
    ids = matching(load_registry(settings["registry"]), path, project)
    if not ids:
        return
    edited = _relative(path, project)

    def add(marks):
        for pid in ids:
            files = marks.setdefault(pid, [])
            if edited not in files:
                files.append(edited)
        return marks

    _under_lock(project, add)


def _under_lock(project, change) -> Dict[str, List[str]]:
    """Read the due marks, write back what change returns, and give the marks read.

    An exclusive flock is held on the due file from the read to the write, so
    hooks running at the same time never lose each other's marks. A file that
    cannot be read counts as holding no marks.
    """
    path = due_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(handle, fcntl.LOCK_EX)
        chunks = []
        while True:
            chunk = os.read(handle, 65536)
            if not chunk:
                break
            chunks.append(chunk)
        marks = _parse_marks(b"".join(chunks))
        kept = change(json.loads(json.dumps(marks)))
        os.lseek(handle, 0, os.SEEK_SET)
        os.ftruncate(handle, 0)
        if kept:
            line = (json.dumps(kept, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            while line:
                line = line[os.write(handle, line) :]
        return marks
    finally:
        os.close(handle)


def _parse_marks(data) -> Dict[str, List[str]]:
    try:
        marks = json.loads(data.decode("utf-8")) if data.strip() else {}
    except (UnicodeDecodeError, ValueError):
        return {}
    if not isinstance(marks, dict):
        return {}
    kept = {}
    for pid, files in marks.items():
        if isinstance(files, list):
            kept[pid] = [f for f in files if isinstance(f, str)]
    return kept


def _start_due(project) -> str:
    if not recording_allowed(project):
        return ""
    marks = _under_lock(project, lambda marks: {})
    if not marks:
        return ""
    settings = load_trigger_settings()
    started, missing = [], []
    for pid, files in marks.items():
        command = start_command(settings, pid, project)
        if command is None:
            missing.append(pid)
            continue
        if _start(pid, command, project):
            started.append(pid)
            _log_start(pid, files, project)
    lines = []
    if started:
        lines.append(f"Verification started for {', '.join(started)}.")
    if missing:
        lines.append(f"No start command for {', '.join(missing)}.")
    return " ".join(lines)


def _start(pid, command, project) -> bool:
    """Start command detached in the project folder, its output in its own log file."""
    logs = connections_home() / TRIGGERS_FOLDER / LOGS_FOLDER
    try:
        logs.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        with open(str(logs / f"{stamp}_{pid}.log"), "ab") as log:
            subprocess.Popen(
                command,
                shell=True,
                cwd=str(project),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
        return True
    except Exception:
        return False


def _log_start(pid, files, project) -> None:
    try:
        rationale = "started at the end of the turn after AI edits to " + ", ".join(files)
        event = make_event(
            project, "ran", "action", f"{pid} procedure started", rationale=rationale, program=PROGRAM
        )
        append_event(event)
    except Exception:
        return
