"""The written-out record of file writes, which names each AI write into a project.

Appendix A2.4 writes a project's records out as files, and Table A5 lists the
file writes among the records the procedures read, which nothing wrote
before. Table A4 gives the mechanical pass each file touched and each action
with a verb from a fixed list. The build procedure's reader, check_ai_touch,
reads one line per write, with the session, the actor, the tool, and the path.

session_writes reads every current event whose verb is wrote or edited, from
any recorded session whose harness's adapter has the AI flag, wherever the
session ran, and keeps those whose file lies inside the project. A session of
a harness without the flag, or with no adapter, gives no row (reconciliation,
Track A). Folders are compared as real paths, so a link to the
project counts. Each row names the actor ai, the file relative to the project
with forward slashes, the harness's id for the session, the session's public
id as session_ref (Track P, step P2), and the event's verb as the tool (Track
W choice 8). Rows come in the order the sessions started,
then in the order of the events within a session.

Writes made through shell commands, and the scholar's and the build's own
writes, are not in the record (Track W gap G8).
"""
import json
import os
from pathlib import Path
from typing import Any, Dict, List

from audit_layer.capture import ADAPTERS
from audit_layer.records.session_index import public_id
from audit_layer.store import Store, current

# The verbs the mechanical pass gives a call that writes a file.
WRITES = ("wrote", "edited")


def session_writes(store: Store, project) -> List[Dict[str, Any]]:
    """The AI writes into the project as rows of actor, path, session, session_ref, and tool."""
    top = os.path.realpath(str(project))
    found = []
    for event in current(store, "events"):
        if event["verb"] not in WRITES:
            continue
        target = event["object"]
        if not isinstance(target, str) or not target.strip():
            continue
        real = os.path.realpath(target)
        if not real.startswith(top.rstrip(os.sep) + os.sep):
            continue
        harness, harness_session_id, started_at = _session(store, event)
        if getattr(ADAPTERS.get(harness), "AI", False) is not True:
            continue
        row = {
            "actor": "ai",
            "path": os.path.relpath(real, top).replace(os.sep, "/"),
            "session": harness_session_id,
            "session_ref": public_id(harness_session_id),
            "tool": event["verb"],
        }
        found.append(((started_at or "", event["ordinal"]), row))
    # The sort keeps the order written for events with the same start and ordinal.
    found.sort(key=lambda pair: pair[0])
    return [row for _, row in found]


def write_session_writes(rows: List[Dict[str, Any]], out) -> None:
    """Write one JSON line per row to the file out, with a final newline, or an empty file."""
    text = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    Path(out).write_bytes(text.encode("utf-8"))


def _session(store: Store, event: Dict[str, Any]):
    """The harness, the harness's session id, and the start of the sessions row the event points to.

    Capture writes a session row that supersedes the old one when the file has
    grown, and the events stored before keep pointing to the old row, so the
    row is read whether or not it is current.
    """
    found = store.db.execute(
        "SELECT harness, harness_session_id, started_at FROM sessions WHERE id = ?",
        (event["session_row_id"],),
    ).fetchone()
    if found is None:
        raise ValueError(
            f"event {event['id']} points to session row {event['session_row_id']},"
            " which the store does not hold"
        )
    return found[0], found[1], found[2]
