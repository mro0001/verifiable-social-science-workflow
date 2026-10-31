"""The Make trigger, which starts the stale streams before a build (Track D, step D20).

Appendix-only, since the proposal's Table 1 names Make only as a build tool.
A3 counts the Make trigger among item 2's acceptance tests, and A2.2 says AI
work in another harness is caught at build time.

python3 -m connections trigger make --project DIR [--source FILE] [--numbers FILE]

For each registered procedure that is one of the four streams, the covered
input is the source text (--source, manuscript.md by default) for prose,
citations, and build, and the numbers file (--numbers, numbers.yml by
default) for data. Both are taken from the project folder when relative. A
stream is current when <project>/verification/<stream>.json parses and its
inputs checksums include the covered input's sha256: checksum, and stale
otherwise (the slice's choice 8). A missing covered input is reported and
skipped.

Each stale stream's start command, the scholar's own in triggers.yaml (Track
D choice 19), runs in the foreground in the project folder, so it finishes
before the build. Each start is logged as a ran action event (choice 21).
Nothing starts in an excluded folder or while the audit settings file is
missing (choice 3). The command always exits 0, so it never fails the make
(choice 20). connections/triggers/verify.mk gives a project's Makefile the
verify target that runs it.
"""
import hashlib
import json
import os
import subprocess
import sys
from typing import List, Optional

from connections.events import append_event, make_event
from connections.home import recording_allowed
from connections.triggers.registry import load_registry, load_trigger_settings, start_command

STREAMS = ("prose", "citations", "data", "build")
PROGRAM = "trigger"
OFF = "verify skipped, recording is off for this folder"


def make_trigger(project, source="manuscript.md", numbers="numbers.yml") -> List[str]:
    """Start each stale stream's command for the project, and print and give one line per stream."""
    if not recording_allowed(project):
        return _say([OFF])
    settings = load_trigger_settings()
    registry = load_registry(settings["registry"])
    lines = []
    for entry in registry:
        stream = entry["id"]
        if stream not in STREAMS:
            continue
        covered = numbers if stream == "data" else source
        path = covered if os.path.isabs(covered) else os.path.join(str(project), covered)
        digest = _checksum(path)
        if digest is None:
            lines.append(_say_one(f"verify {stream} skipped, {covered} missing"))
            continue
        if _current(project, stream, digest):
            lines.append(_say_one(f"verify {stream} current"))
            continue
        command = start_command(settings, stream, project)
        if command is None:
            lines.append(_say_one(f"verify {stream} stale, no start command"))
            continue
        code = _run(command, project)
        if code is None:
            continue
        _log_start(stream, covered, code, project)
        lines.append(_say_one(f"verify {stream} stale, started, exit {code}"))
    return lines


def _checksum(path) -> Optional[str]:
    """sha256: and the hex digest of the file, as a verification run records it, or None."""
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
    except OSError:
        return None
    return "sha256:" + digest.hexdigest()


def _current(project, stream, digest) -> bool:
    """Whether verification/<stream>.json parses and its inputs checksums include digest."""
    path = os.path.join(str(project), "verification", f"{stream}.json")
    try:
        with open(path, encoding="utf-8") as handle:
            results = json.load(handle)
    except (OSError, ValueError, RecursionError):
        return False
    if not isinstance(results, dict):
        return False
    inputs = results.get("inputs")
    if not isinstance(inputs, dict):
        return False
    return digest in inputs.values()


def _run(command, project) -> Optional[int]:
    """Run command in the foreground in the project folder and give its exit code.

    Earlier lines are flushed first, so the command's own output follows
    them. None when the command cannot be started at all.
    """
    sys.stdout.flush()
    try:
        return subprocess.run(command, shell=True, cwd=str(project)).returncode
    except Exception:
        return None


def _log_start(stream, covered, code, project) -> None:
    try:
        rationale = (
            f"started before the build because verification/{stream}.json does not cover "
            f"{covered}, exit {code}"
        )
        event = make_event(
            project, "ran", "action", f"{stream} procedure started", rationale=rationale, program=PROGRAM
        )
        append_event(event)
    except Exception:
        return


def _say_one(line) -> str:
    print(line, flush=True)
    return line


def _say(lines) -> List[str]:
    for line in lines:
        _say_one(line)
    return lines
