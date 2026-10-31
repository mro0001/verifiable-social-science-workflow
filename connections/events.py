"""The event writer every connector uses.

Appendix A2.2 says wrappers turn what happens in the scholar's software into
events in a schema that fits the audit layer's databases, and Figure A4 has
the wrappers feed capture. A connector's event holds the one event schema's
fields, with harness wrappers and the harness session id <YYYY-MM-DD>_<key>,
where key is the first 12 hex characters of the sha256 of the working
folder's real path. It also holds at, cwd, and program, since the schema has
no time or folder and capture needs both (Track D choice 2, reconciliation
item 7).

Every event is one JSON line in <connections home>/events/<session id>.jsonl,
one file per day and working folder, so capture can store each file as one
session with the file kept unchanged as its transcript. Nothing is written in
an excluded folder or while the audit settings file is missing (choice 3),
and a failure to write never reaches the caller.
"""
import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Mapping

from connections.home import connections_home, folder_key, recording_allowed

HARNESS = "wrappers"

# The fixed lists of Table A4, copied from the slice's audit_layer/events.py
# and never imported, since connections imports no audit layer code. A change
# there is copied here by hand.
VERBS = ("wrote", "edited", "ran", "searched", "verified", "committed")
KINDS = ("action", "decision", "observation", "blocker")
ROLES = ("produced", "edited", "read", "cited")

EVENTS_FOLDER = "events"


def make_event(cwd, verb, kind, obj, rationale="", role="", program="", extra=None, now=None):
    """The event for one thing done in the folder cwd.

    The verb, kind, and role must be in their lists (the role may be empty)
    and the object must not be empty, else ValueError names the field. The
    rationale and program must be text and extra a mapping, else ValueError
    names it. extra adds more fields to the event and may not replace one. now fixes the
    clock, and a time without a time zone is taken as local time.
    """
    if verb not in VERBS:
        raise ValueError(f"verb {verb!r} is not one of {', '.join(VERBS)}")
    if kind not in KINDS:
        raise ValueError(f"kind {kind!r} is not one of {', '.join(KINDS)}")
    if role != "" and role not in ROLES:
        raise ValueError(f"role {role!r} is not one of {', '.join(ROLES)}, or empty")
    if not isinstance(obj, str) or not obj.strip():
        raise ValueError("object is empty")
    if not isinstance(rationale, str):
        raise ValueError("rationale must be text")
    if not isinstance(program, str):
        raise ValueError("program must be text")
    if extra is not None and not isinstance(extra, Mapping):
        raise ValueError("extra must be a mapping from field names to values")
    moment = (now or datetime.now()).astimezone().replace(microsecond=0)
    event = {
        "harness": HARNESS,
        "harness_session_id": f"{moment.strftime('%Y-%m-%d')}_{folder_key(cwd)}",
        "source_id": uuid.uuid4().hex,
        "verb": verb,
        "kind": kind,
        "object": obj,
        "rationale": rationale,
        "role": role,
        "at": moment.isoformat(),
        "cwd": os.path.abspath(str(cwd)),
        "program": program,
    }
    for name, value in (extra or {}).items():
        if name in event:
            raise ValueError(f"{name} is a field of the event and cannot be given as an extra")
        event[name] = value
    return event


def event_path(event) -> Path:
    """<connections home>/events/<harness_session_id>.jsonl."""
    return connections_home() / EVENTS_FOLDER / f"{event['harness_session_id']}.jsonl"


def append_event(event) -> bool:
    """Append the event as one UTF-8 JSON line, if recording is allowed in its folder.

    Gives True when the line was written. Gives False, and never raises, when
    the folder is excluded, the audit settings file is missing or unclear, or
    anything else fails.
    """
    try:
        if not recording_allowed(event["cwd"]):
            return False
        name = event["harness_session_id"]
        if not isinstance(name, str) or not name or name in (".", "..") or os.sep in name:
            return False
        line = (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8")
        path = event_path(event)
        path.parent.mkdir(parents=True, exist_ok=True)
        # One write to a file opened for appending, so lines from connectors
        # writing at the same time do not mix.
        handle = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            while line:
                line = line[os.write(handle, line) :]
        finally:
            os.close(handle)
        return True
    except Exception:
        return False
