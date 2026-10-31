"""The audit store server, workflow-audit (Track D, step D7).

Proposal Approach paragraph 5 says any AI contribution can be reviewed live
or formally, and appendix A2.2 and Figure A4 have the harness and the model
read the databases through MCP servers. This server reads the audit store's
database, <home>/audit.sqlite, read only, and offers three tools.

- list_sessions gives sessions newest first, optionally only those run in a
  project folder or a folder inside it.
- get_session gives one session's current row, its events in the order of
  its tool calls, and its transcripts' checksums and sizes.
- search_events gives events whose object or rationale holds a text.

Every tool serves current rows only. A row whose id a later row names in its
supersedes column is left out. A transcript's content is never served, since
a transcript holds whatever a session read (A6), and no review step for
sharing records exists yet (Track D choice 11). The server logs nothing of
its own (choice 10) and writes nothing.

The audit home is the --home option, else AUDIT_HOME, else ~/.audit_layer,
as the audit layer names it. The column names below follow the slice's
audit_layer/store.py, read from that file while building. That code is never
imported, since connections imports no audit layer code.
"""
import json
import os
import sqlite3
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional

from connections.mcp.protocol import Tool

SERVER_NAME = "workflow-audit"
SERVER_VERSION = "0.1.0"

# The audit home, as audit_layer/settings.py names it.
AUDIT_HOME_VARIABLE = "AUDIT_HOME"
AUDIT_DEFAULT_HOME = "~/.audit_layer"
# The database file in the audit home, as audit_layer/store.py names it.
DATABASE = "audit.sqlite"

# Fields audit_layer/store.py keeps as a JSON list.
LISTS = {"sessions": ("tools", "keywords", "models")}


def audit_home(given=None) -> Path:
    """The audit home, which is given, else AUDIT_HOME, else ~/.audit_layer.

    A variable set to nothing counts as not set, as in the audit layer.
    """
    chosen = given or os.environ.get(AUDIT_HOME_VARIABLE) or AUDIT_DEFAULT_HOME
    return Path(os.path.expanduser(str(chosen)))


def open_store(home) -> sqlite3.Connection:
    """The audit database in home, opened read only.

    A missing database raises sqlite3.OperationalError, and no file is made.
    Every write through the connection fails.
    """
    path = os.path.abspath(str(Path(home) / DATABASE))
    uri = "file:" + urllib.parse.quote(path) + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


def tools(home) -> List[Tool]:
    """The server's three tools, each reading the store in home on every call."""
    home = Path(home)

    def list_sessions(project=None, limit=20):
        return _with_store(home, lambda db: _list_sessions(db, project, limit), limit)

    def get_session(harness_session_id):
        return _with_store(home, lambda db: _get_session(db, harness_session_id))

    def search_events(text, project=None, limit=50):
        return _with_store(home, lambda db: _search_events(db, text, project, limit), limit)

    return [
        Tool(
            "list_sessions",
            "List the AI sessions the audit store holds, newest first, with every column. "
            "Give a project folder to see only the sessions run in it or in a folder inside it.",
            {
                "type": "object",
                "properties": {
                    "project": {
                        "type": "string",
                        "description": "a full folder path, the project the sessions ran in",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "the most sessions to give, 20 when left out",
                    },
                },
            },
            list_sessions,
        ),
        Tool(
            "get_session",
            "Give one session's current row, its events in the order of its tool calls, and "
            "its transcripts' checksums and sizes. A transcript's content is never given.",
            {
                "type": "object",
                "properties": {
                    "harness_session_id": {
                        "type": "string",
                        "description": "the harness's own id for the session",
                    },
                },
                "required": ["harness_session_id"],
            },
            get_session,
        ),
        Tool(
            "search_events",
            "Find events whose object or rationale holds the text, ignoring case, each with "
            "its session's harness session id and project.",
            {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "the text to look for"},
                    "project": {
                        "type": "string",
                        "description": "a full folder path, to keep to the sessions run in it",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "the most events to give, 50 when left out",
                    },
                },
                "required": ["text"],
            },
            search_events,
        ),
    ]


def _with_store(home: Path, read, limit: Optional[int] = None) -> Dict[str, Any]:
    if limit is not None and limit < 1:
        return _error("invalid_argument", f"limit must be 1 or more, not {limit}")
    if not (home / DATABASE).is_file():
        return _error(
            "no_store",
            f"there is no audit store at {home}. Run python3 -m audit_layer init, then capture"
            " the sessions",
        )
    db = open_store(home)
    try:
        return read(db)
    finally:
        db.close()


def _error(code: str, message: str) -> Dict[str, Any]:
    return {"error": {"code": code, "message": message}}


def _current(db: sqlite3.Connection, table: str, where: str = "", values=()) -> List[Dict[str, Any]]:
    """The rows of table no later row supersedes, in the order written."""
    sql = (
        f"SELECT * FROM {table} WHERE id NOT IN "
        f"(SELECT supersedes FROM {table} WHERE supersedes IS NOT NULL)"
    )
    if where:
        sql += " AND " + where
    cursor = db.execute(sql + " ORDER BY rowid", list(values))
    names = [d[0] for d in cursor.description]
    rows = []
    for values_ in cursor.fetchall():
        row = dict(zip(names, values_))
        for name in LISTS.get(table, ()):
            if row.get(name) is not None:
                row[name] = json.loads(row[name])
        rows.append(row)
    return rows


def _within(folder: Optional[str], project) -> bool:
    """Whether project is folder or inside it, compared by whole path parts.

    Both the path as given and its real path are tried on each side, since the
    store keeps the project as the harness gave it.
    """
    if folder is None:
        return True
    if not isinstance(project, str) or not project:
        return False
    tops = {Path(os.path.abspath(folder)).parts, Path(os.path.realpath(folder)).parts}
    sides = {Path(os.path.abspath(project)).parts, Path(os.path.realpath(project)).parts}
    return any(side[: len(top)] == top for top in tops for side in sides)


def _newest_first(sessions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # By start time, then by the time the row was written, with a session
    # that has no start time last. Python's sort is stable, so ties keep the
    # order written, latest first after the reverse.
    ordered = list(reversed(sessions))
    ordered.sort(key=lambda s: (s.get("started_at") is not None, s.get("started_at") or "",
                                s.get("created_at") or ""), reverse=True)
    return ordered


def _list_sessions(db, project, limit) -> Dict[str, Any]:
    sessions = [s for s in _current(db, "sessions") if _within(project, s.get("project"))]
    return {"sessions": _newest_first(sessions)[:limit]}


def _get_session(db, harness_session_id) -> Dict[str, Any]:
    rows = _current(db, "sessions", "harness_session_id = ?", (harness_session_id,))
    if not rows:
        return _error("not_found", f"there is no session {harness_session_id!r} in the audit store")
    # Capture keeps one current row for each session, the latest written.
    session = rows[-1]
    # Every row capture writes for a session carries the harness session id
    # as its session, so the events of each version of its row are found.
    events = _current(db, "events", "session = ?", (harness_session_id,))
    events.sort(key=lambda e: (e.get("ordinal") is None, e.get("ordinal") or 0))
    transcripts = _current(db, "transcripts", "session = ?", (harness_session_id,))
    return {"session": session, "events": events, "transcripts": transcripts}


def _search_events(db, text, project, limit) -> Dict[str, Any]:
    wanted = text.casefold()
    every_session = {}
    cursor = db.execute("SELECT * FROM sessions ORDER BY rowid")
    names = [d[0] for d in cursor.description]
    for values in cursor.fetchall():
        row = dict(zip(names, values))
        every_session[row["id"]] = row
    current_sessions = {}
    for row in _current(db, "sessions"):
        current_sessions[(row["harness"], row["harness_session_id"])] = row

    found = []
    for event in _current(db, "events"):
        fields = (event.get("object") or "", event.get("rationale") or "")
        if not any(wanted in field.casefold() for field in fields):
            continue
        row = every_session.get(event.get("session_row_id"))
        if row is not None:
            row = current_sessions.get((row["harness"], row["harness_session_id"]), row)
            harness_session_id, where = row["harness_session_id"], row["project"]
        else:
            harness_session_id, where = event.get("session"), None
        if not _within(project, where):
            continue
        found.append(dict(event, harness_session_id=harness_session_id, project=where))
        if len(found) == limit:
            break
    return {"events": found}
