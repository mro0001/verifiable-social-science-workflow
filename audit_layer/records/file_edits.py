"""The written-out record of the AI's file edits, with each edit's text before and after.

The data procedure's final-numbers report shows each AI change to a pipeline
script with the change and the AI's stated reason, and lists each parameter
the AI set (Track V, step V2). A change is the AI's when the record shows an
AI tool call made it (choice 2), and a stated reason is taken from the record
(choice 3). The file writes record names only the file, and the rationales
record splits one source's edits into sentences, so neither carries the code
an edit replaced. This record gives one entry for each edit an AI tool call
made to a file inside the project, with an id, the file relative to the
project with forward slashes, a kind, the text before and after, the stated
reason, the harness's id for the session, and its public id as session_ref.

An Edit gives one entry of kind edit, and each edit of a MultiEdit one more.
A Write gives one entry of kind write, whose text before is empty and whose
text after is the whole file, since a Write does not carry what it replaced.
The stated reason is the assistant's text before the call, read from the
session's ordered parts as the rationales record reads it, and an empty
rationale when none was written. The sessions are those with a current event
that may write a file inside the project (an edited or wrote event on one,
compared as real paths, or a MultiEdit), wherever they ran, in the order they
started. Only sessions whose harness's adapter has the AI flag are read, and
another session is skipped and named on standard error. Edits made through
shell commands are not in the record.
"""
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

from audit_layer.capture import ADAPTERS, read_stored
from audit_layer.queries import current_session
from audit_layer.records.rationales import stated_reasons
from audit_layer.records.session_index import public_id
from audit_layer.store import Store, current

FIELDS = ("id", "path", "kind", "before", "after", "rationale", "session", "session_ref")
TOOLS = ("Edit", "MultiEdit", "Write")


def file_edits(store: Store, project) -> List[Dict[str, str]]:
    """One entry for each edit an AI Edit, MultiEdit, or Write call made to a file inside the project."""
    top = os.path.realpath(str(project))
    entries: List[Dict[str, str]] = []
    for harness, session_id in _writing_sessions(store, top):
        if getattr(ADAPTERS.get(harness), "AI", False) is not True:
            print(
                f"skipped session {session_id} from harness {harness},"
                " which is not a harness of AI sessions",
                file=sys.stderr,
            )
            continue
        row = current_session(store, harness, session_id)
        if row is None:
            raise ValueError(f"session {session_id} has no current row in the store")
        session = read_stored(store, row)
        reasons = stated_reasons(session.parts)
        for tool_call in session.tool_calls:
            if tool_call.name not in TOOLS:
                continue
            given = tool_call.input if isinstance(tool_call.input, dict) else {}
            path_given = given.get("file_path")
            if not isinstance(path_given, str) or not path_given.strip():
                continue
            real = os.path.realpath(os.path.normpath(os.path.join(session.cwd, path_given)))
            if not _inside(real, top):
                continue
            path = os.path.relpath(real, top).replace(os.sep, "/")
            reason = reasons.get(tool_call.record_id, "")
            for kind, before, after in _call_edits(tool_call.name, given):
                entries.append(
                    {
                        "id": "e{:02d}".format(len(entries) + 1),
                        "path": path,
                        "kind": kind,
                        "before": before,
                        "after": after,
                        "rationale": reason,
                        "session": session_id,
                        "session_ref": public_id(session_id),
                    }
                )
    return entries


def write_file_edits(entries: List[Dict[str, str]], out) -> None:
    """Write the entries to the file out as a YAML list, each in the field order."""
    ordered = [{name: entry[name] for name in FIELDS} for entry in entries]
    text = yaml.safe_dump(
        ordered, sort_keys=False, default_flow_style=False, allow_unicode=True, width=4096
    )
    Path(out).write_text(text, encoding="utf-8")


def _inside(real: str, top: str) -> bool:
    return real.startswith(top.rstrip(os.sep) + os.sep)


def _writing_sessions(store: Store, top: str) -> List[Tuple[str, str]]:
    """The harness and session id of each session with a current event that may write a file
    inside top, earliest start first, and sessions with the same start in the order their
    first such event was stored."""
    found: Dict[str, Tuple[str, str]] = {}
    for event in current(store, "events"):
        if not _may_write(event, top):
            continue
        row = store.db.execute(
            "SELECT harness, harness_session_id, started_at FROM sessions WHERE id = ?",
            (event["session_row_id"],),
        ).fetchone()
        if row is None:
            raise ValueError(
                f"event {event['id']} points to session row {event['session_row_id']},"
                " which the store does not hold"
            )
        harness, session_id, started_at = row
        if session_id not in found:
            found[session_id] = (started_at or "", harness)
    ordered = sorted(found.items(), key=lambda item: item[1][0])
    return [(harness, session_id) for session_id, (_, harness) in ordered]


def _may_write(event: Dict[str, Any], top: str) -> bool:
    if event["verb"] == "ran":
        return event["object"] == "MultiEdit"
    if event["verb"] not in ("edited", "wrote") or not isinstance(event["object"], str):
        return False
    return _inside(os.path.realpath(event["object"]), top)


def _call_edits(name: str, given: Dict[str, Any]) -> List[Tuple[str, str, str]]:
    """The (kind, before, after) edits one Edit, MultiEdit, or Write call made."""
    if name == "Write":
        return [("write", "", _text(given.get("content")))]
    if name == "MultiEdit":
        edits = given.get("edits")
        pairs = [edit for edit in edits if isinstance(edit, dict)] if isinstance(edits, list) else []
    else:
        pairs = [given]
    return [("edit", _text(edit.get("old_string")), _text(edit.get("new_string"))) for edit in pairs]


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""
