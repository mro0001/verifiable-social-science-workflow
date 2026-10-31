"""Reads of the audit store that more than one part of the audit layer needs.

A session is kept as a chain of rows. Capture writes a new session row that
supersedes the old one when the session's file has grown, and the events and
transcripts written at each capture name the session row current then
(capture/__init__.py). So a session's events and transcripts are found across
every row the session has had, which all carry the same harness and harness
session id.

A subagent conversation is a session of its own, whose id is its parent's id
followed by /agent- and the agent id (plan choice 5). With no links table, the
id is what ties it to its parent.

The working store's snapshots are kept by project folder, and
latest_snapshots gives the newest of each path.
"""
from typing import Any, Dict, List, Optional, Tuple

from audit_layer.store import Store, current


def current_session(store: Store, harness: str, harness_session_id: str) -> Optional[Dict[str, Any]]:
    """The session's current row, the latest written, or None when the store holds none."""
    rows = current(store, "sessions", harness=harness, harness_session_id=harness_session_id)
    return rows[-1] if rows else None


def subagents(store: Store, session_row: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The current session rows of the session's subagent conversations, in the order written.

    Each has the parent's harness and an id that is the parent's id followed
    by /agent- and an agent id, which holds no / of its own.
    """
    prefix = session_row["harness_session_id"] + "/agent-"
    found = []
    for row in current(store, "sessions", harness=session_row["harness"]):
        name = row["harness_session_id"] or ""
        agent = name[len(prefix):]
        if name.startswith(prefix) and agent and "/" not in agent:
            found.append(row)
    return found


def session_events(store: Store, session_row: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The session's current events across every row of it, in ordinal order.

    An event a later row supersedes is given in its current version.
    """
    ids = set(_session_row_ids(store, session_row))
    events = [row for row in current(store, "events") if row["session_row_id"] in ids]
    return sorted(events, key=lambda row: row["ordinal"])


def latest_transcript(store: Store, session_row: Dict[str, Any]) -> Tuple[Dict[str, Any], bytes]:
    """The session's latest stored transcript row and the bytes the file store keeps for it.

    Capture stores the whole file again each time it has grown, so the latest
    transcript holds every record captured so far.
    """
    ids = set(_session_row_ids(store, session_row))
    rows = [row for row in current(store, "transcripts") if row["session_row_id"] in ids]
    if not rows:
        raise ValueError(
            f"session {session_row['harness_session_id']} has no stored transcript,"
            " so capture it again"
        )
    row = rows[-1]
    return row, (store.files / row["file_sha256"]).read_bytes()


def latest_snapshots(store: Store, project: str) -> Dict[str, Dict[str, Any]]:
    """The newest snapshot of each path in the project folder, by its path relative to the folder.

    The working store keeps every snapshot (stores/working.py), so the newest
    of a path is the last written.
    """
    latest = {}  # type: Dict[str, Dict[str, Any]]
    for row in current(store, "snapshots", project=project):
        latest[row["path"]] = row
    return latest


def _session_row_ids(store: Store, session_row: Dict[str, Any]) -> List[str]:
    """The ids of every row the session has had, current or superseded, in the order written."""
    cursor = store.db.execute(
        "SELECT id FROM sessions WHERE harness IS ? AND harness_session_id IS ? ORDER BY rowid",
        (session_row["harness"], session_row["harness_session_id"]),
    )
    return [row[0] for row in cursor.fetchall()]
