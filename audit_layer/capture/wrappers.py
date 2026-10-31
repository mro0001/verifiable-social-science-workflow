"""The wrappers adapter, which reads one file of the connectors' events for capture.

Appendix A2.4 "Capture" sweeps each harness's session files and the wrappers'
events, keeps each transcript unchanged, and is safe to repeat (Figure A4).
The connectors (wrappers around the scholar's software, the events tool for
outside software) write each event as one JSON line in
<connections home>/events/<YYYY-MM-DD>_<key>.jsonl, one file per day and
working folder, where key is the first 12 hex characters of the sha256 of the
folder's real path. A line holds the one event schema's fields (events.py),
with harness wrappers and harness_session_id the file name less .jsonl, plus
at (the time), cwd (the working folder), and program, and may hold more
fields of the connector's own, such as exit_code (Track D choice 2,
reconciliation item 7).

The connections home is CONNECTIONS_HOME if set, else ~/.workflow_connections.
It is read from the environment here, since the audit layer imports no
connections code and only the file crosses the layer edge.

One file is one session of the harness wrappers. Its id is the file name less
.jsonl, its working folder is the lines' cwd, its start and end are the first
and last at, its tools are the distinct program values in the order first
given, and its transcript is the file's bytes unchanged. In place of tool
calls it gives the events in file order, each checked against the schema, and
capture stores them as they are, with no mechanical pass (reconciliation,
Track D). A last line without its line break is still being written, so it
and its bytes are left for the next capture. Any other line that does not
parse or validate, or that names another session, folder, or harness, makes
the adapter refuse the whole file and name the line.

The adapter's AI flag is false, since no AI wrote these sessions, so they
never reach the model pass, the working-file snapshots, or the written-out
records that read AI sessions (reconciliation, item 7 and Track D).
"""
import json
import os
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

from audit_layer.capture import SessionRef
from audit_layer.events import FIELDS, validate

NAME = "wrappers"

# No AI wrote the sessions this harness keeps.
AI = False

# The adapter's version, which capture names in the method of every row it
# writes. Raise it when a change alters what the adapter stores from a file.
VERSION = 1

# Where the connectors keep their settings and events, as the connections
# layer names it (Track D choice 1).
HOME_VARIABLE = "CONNECTIONS_HOME"
DEFAULT_HOME = "~/.workflow_connections"
EVENTS_FOLDER = "events"

# The fields a line carries beside the event schema's, which the session needs.
_LINE_FIELDS = ("at", "cwd")


class Session(NamedTuple):
    """What the adapter reads from one events file.

    It has the fields of the Claude Code adapter's session that capture and
    the other readers use, with tool_calls, messages, and parts empty, since a
    wrapper session holds no conversation, plus tools and events.
    """

    session_id: str
    cwd: str
    started_at: str
    ended_at: str
    # The bytes through the last line break, unchanged.
    transcript: bytes
    # The distinct program values, in the order first given.
    tools: List[str]
    # The events in file order, each holding the schema's fields only.
    events: List[Dict[str, str]]
    tool_calls: List[Any]
    messages: List[Tuple[str, str]]
    parts: List[Any]


def default_root() -> Path:
    """The events folder of the connections home. It is named here and not read."""
    chosen = os.environ.get(HOME_VARIABLE) or DEFAULT_HOME
    return Path(os.path.expanduser(chosen)) / EVENTS_FOLDER


def list_sessions(root) -> List[SessionRef]:
    """Each events file in root, <root>/<session id>.jsonl, with its id and size, in path order.

    No file is opened. A root that does not exist lists nothing.
    """
    root = Path(root)
    if not root.is_dir():
        return []
    refs = []
    for path in sorted(root.glob("*.jsonl")):
        if path.is_file():
            refs.append(SessionRef(path.name[: -len(".jsonl")], str(path), path.stat().st_size))
    return refs


def read_session(location) -> Session:
    """Read one events file, whose path is location, as one session.

    The session id is the file name less .jsonl, and every line must name it.
    A line that cannot be read is refused with the file's path and its line
    number.
    """
    path = Path(location)
    name = path.name[: -len(".jsonl")] if path.name.endswith(".jsonl") else path.name
    data = path.read_bytes()
    try:
        return _parse(data, name)
    except ValueError as error:
        raise ValueError(f"{path} {error}") from error


def parse_transcript(data: bytes) -> Session:
    """Read a wrapper session from the bytes of its file, as stored.

    The session id is the one the first line names.
    """
    return _parse(data, None)


def _parse(data: bytes, session_id: Optional[str]) -> Session:
    end = data.rfind(b"\n")
    finished = data[: end + 1] if end >= 0 else b""
    cwd = None
    folder = None
    started_at = ""
    ended_at = ""
    tools: List[str] = []
    events: List[Dict[str, str]] = []
    for number, line in enumerate(finished.split(b"\n"), start=1):
        if not line.strip():
            continue
        record = _record(number, line)
        missing = [name for name in _LINE_FIELDS if not _is_text(record.get(name))]
        if missing:
            raise ValueError(f"line {number} has no {' or '.join(missing)} as text")
        event = {name: record[name] for name in FIELDS if name in record}
        problems = validate(event)
        if problems:
            raise ValueError(f"line {number} is not an event the schema takes, " + "; ".join(problems))
        if event["harness"] != NAME:
            raise ValueError(f"line {number} names the harness {event['harness']}, not {NAME}")
        if session_id is None:
            session_id = event["harness_session_id"]
        if event["harness_session_id"] != session_id:
            raise ValueError(
                f"line {number} names the session {event['harness_session_id']}, not {session_id}"
            )
        if cwd is None:
            cwd = record["cwd"]
            folder = os.path.realpath(cwd)
        elif record["cwd"] != cwd and os.path.realpath(record["cwd"]) != folder:
            raise ValueError(f"line {number} names another working folder than line 1")
        started_at = started_at or record["at"]
        ended_at = record["at"]
        program = record.get("program")
        if _is_text(program) and program not in tools:
            tools.append(program)
        events.append(event)
    return Session(
        session_id=session_id or "",
        cwd=cwd or "",
        started_at=started_at,
        ended_at=ended_at,
        transcript=finished,
        tools=tools,
        events=events,
        tool_calls=[],
        messages=[],
        parts=[],
    )


def _record(number: int, line: bytes) -> Dict[str, Any]:
    try:
        record = json.loads(line.decode("utf-8"))
    except ValueError as error:
        raise ValueError(f"line {number} is not a JSON object") from error
    if not isinstance(record, dict):
        raise ValueError(f"line {number} is not a JSON object")
    return record


def _is_text(value: Any) -> bool:
    return isinstance(value, str) and value != ""
