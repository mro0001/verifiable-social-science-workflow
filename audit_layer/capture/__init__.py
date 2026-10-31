"""Capture on demand, which stores a harness's session file in the audit store.

Appendix A2.4 "Capture" sweeps each harness's session files through one event
schema with an adapter for each harness, and keeps each transcript unchanged.
Capture runs when the scholar asks, and the sweep (sweep.py) runs it over
every session a harness keeps, while a session runs, at its end, and on a
schedule.

Capture reaches a harness only through ADAPTERS, the registry of adapters by
name (plan choice 2). Each adapter module gives NAME, default_root(),
list_sessions(root), read_session(location), and parse_transcript(data), its
VERSION, and AI, true when an AI wrote the sessions the harness keeps
(reconciliation, item 7). Claude Code (claude_code.py) and ForgeCode, the
fallback harness (forgecode.py), are registered, and so are the wrappers
(wrappers.py), whose sessions are the connectors' events files, with AI false
(Track D, step D4).

capture_session reads the session and checks the folder it ran in before it
stores anything. A session whose working folder cannot be found stores
nothing, for any harness, and its summary says the working folder is unknown
(plan choice 3). A session run in an excluded folder stores nothing (A6,
A2.6, settings.py). Otherwise it stores the session row, each tool call as an
event through the mechanical tagging pass, and the transcript bytes in the
file store. A wrappers session's events are stored as the connectors wrote
them, in file order, with no mechanical pass (reconciliation, Track D). A session's project is the folder it ran in (slice plan choice 4),
and the first session stored in a folder adds the folder's row to the
projects table (projects.py, plan choice 19).
The session's tools list names each tool as the harness does, so it keeps a
tool call's harness_tool when the adapter gives one (plan choice 4). The
session row also keeps the models that answered in it and the harness's
version, as the adapter reads them, and an adapter that reads neither gives
an empty list and no version (Track P, Step P1).

Capturing a main session file also captures each subagent conversation file
in the folder named after it, <session id>/subagents/agent-<agent id>.jsonl,
as Claude Code keeps them (Step A3), or one or more folders deeper than
subagents, such as subagents/workflows/<run>/agent-<agent id>.jsonl (Step
P1). Each subagent conversation is its own
session row, with its own events and transcript (plan choice 5), and the
excluded-folder rule and the working-folder rule apply to each file on its
own. The main session's summary lists the subagents' summaries. A subagent
file that cannot be read does not stop the others. Once each is tried,
capture raises SubagentsNotCaptured, which holds the main session's summary
and names each failed subagent conversation by its id, never by its path.

Capture is safe to repeat (Figure A4). Each event's id is the harness's own id
for its tool call, and the store writes a row under a given id only once, so
capturing the same session again stores nothing new. A session that has grown
adds its new events, a new transcript row, and a session row that supersedes
the old one. Every row carries the harness's session id as its session, so a
session's events and transcripts can be found across versions of its row
(queries.py).
"""
import os
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple


class SessionRef(NamedTuple):
    """One session a harness keeps, as an adapter's list_sessions finds it, with nothing read."""

    harness_session_id: str
    # Where the adapter reads the session, such as a session file's path.
    location: str
    # The session's size in bytes.
    size: int


# The adapters import SessionRef from here, so it is defined before they load.
from audit_layer.capture import claude_code, forgecode, wrappers  # noqa: E402
from audit_layer.capture.claude_code import Session, ToolCall  # noqa: E402
from audit_layer.events import validate  # noqa: E402
from audit_layer.projects import METHOD as PROJECTS_METHOD  # noqa: E402
from audit_layer.projects import REASON as PROJECTS_REASON  # noqa: E402
from audit_layer.projects import ensure_project  # noqa: E402
from audit_layer.queries import latest_transcript  # noqa: E402
from audit_layer.settings import excluded  # noqa: E402
from audit_layer.store import Store, add_row, current, put_file, supersede  # noqa: E402
from audit_layer.tagging import mechanical  # noqa: E402
from audit_layer.tagging.mechanical import session_tags, tag  # noqa: E402

# Each harness's adapter, by the harness's name.
ADAPTERS = {claude_code.NAME: claude_code, forgecode.NAME: forgecode, wrappers.NAME: wrappers}

# The harness capture_file reads. The citation log reads its sessions.
HARNESS = claude_code.NAME

REASON = "capture"

# The session fields the model pass fills (Step A9), which capture leaves empty.
DERIVED = ("title", "gist", "summary", "keywords")

# The session fields capture gained in Step P1. A row written before them
# holds neither, and gaining them alone leaves the model pass's fields as
# they are, since the transcript has not changed.
ADDED = ("models", "harness_version")


def adapter(name: str):
    """The adapter module registered for the harness, refusing a name none is registered for."""
    if name not in ADAPTERS:
        raise ValueError(
            f"there is no adapter for the harness {name}. The harnesses with an adapter are "
            + ", ".join(sorted(ADAPTERS))
        )
    return ADAPTERS[name]


def _origin(harness: str) -> str:
    """The origin of every row capture writes for the harness."""
    return f"{harness} adapter"


def _method(harness: str) -> str:
    """The method of every row capture writes for the harness, naming both versions.

    The wrappers' events pass through no tagging, so their method names the
    adapter's version alone.
    """
    if harness == wrappers.NAME:
        return "{} adapter version {}, events stored as written".format(
            harness, adapter(harness).VERSION
        )
    return "{} adapter version {}, mechanical tagging version {}".format(
        harness, adapter(harness).VERSION, mechanical.VERSION
    )


class Summary(NamedTuple):
    """What one capture of one session stored."""

    # Where the session was read, as given.
    path: str
    # The harness's id for the session, or None when it ran in an excluded folder.
    session_id: Optional[str]
    # True when the session ran in an excluded folder, so nothing was stored.
    excluded: bool
    # The rows written in each table. A repeated capture writes none.
    sessions: int
    events: int
    transcripts: int
    # True when the session's working folder could not be found, so nothing
    # was stored.
    folder_unknown: bool = False
    # The summary of each subagent conversation captured with a main session
    # file, in path order. A subagent's own summary lists none.
    subagents: Tuple["Summary", ...] = ()


class SubagentsNotCaptured(ValueError):
    """The main session was stored, and one or more of its subagent files could not be.

    summary is what the capture stored, the subagents it did capture among
    them. failed holds the id of each subagent conversation not captured,
    read from its file's path, since its records may not be readable.
    """

    def __init__(self, summary: Summary, failed: Tuple[str, ...], reasons: Tuple[str, ...]):
        self.summary = summary
        self.failed = failed
        # The reason each one failed, in the order of failed, naming no path.
        self.reasons = reasons
        named = "; ".join(f"{name}, {reason}" for name, reason in zip(failed, reasons))
        super().__init__(
            f"stored session {summary.session_id}, but could not capture"
            f" {len(failed)} of its subagent conversations, {named}"
        )


def capture_file(store: Store, path, settings) -> Summary:
    """Store one Claude Code session file, unless it ran in an excluded folder."""
    return capture_session(store, HARNESS, path, settings)


def capture_session(store: Store, harness: str, location, settings) -> Summary:
    """Store one session of a registered harness, unless it ran in an excluded folder.

    location is where the harness's adapter reads the session. settings are
    the ones read from the audit home's settings.yaml. Settings that do not
    list the excluded folders are refused before anything is stored, and so
    is a harness with no adapter. A main session file's subagent conversation
    files are captured after it, each on its own, and the summary lists theirs.
    A subagent file that cannot be read does not stop the others, and once
    each is tried, SubagentsNotCaptured names the ones not captured.
    """
    summary = _capture_one(store, harness, location, settings)
    found = []
    failed = []
    reasons = []
    for path in _subagent_files(location):
        try:
            found.append(_capture_one(store, harness, path, settings))
        except (OSError, ValueError) as error:
            failed.append(claude_code.subagent_id(Path(path)))
            # The reason never names the file, whose folder names spell out
            # the folder the session ran in.
            reasons.append(str(error).replace(str(path), "its file"))
    if found:
        summary = summary._replace(subagents=tuple(found))
    if failed:
        raise SubagentsNotCaptured(summary, tuple(failed), tuple(reasons))
    return summary


def _subagent_files(location) -> List[str]:
    """The subagent conversation files beside a main session file, in path order.

    They sit in the folder named after the file less .jsonl, in its subagents
    folder or any folder inside it, as agent-<agent id>.jsonl. Only those
    files are taken, so the
    agent-<agent id>.meta.json beside each is neither read nor stored. A
    location that is not a .jsonl file name gives none. No file is opened.
    """
    path = Path(str(location))
    if not path.name.endswith(".jsonl"):
        return []
    folder = path.parent / path.name[: -len(".jsonl")] / "subagents"
    if not folder.is_dir():
        return []
    return [str(found) for found in sorted(folder.rglob("agent-*.jsonl")) if found.is_file()]


def _capture_one(store: Store, harness: str, location, settings) -> Summary:
    """Store one session, as capture_session does, with no subagent files."""
    reader = adapter(harness)
    session = reader.read_session(location)
    # The settings are checked for every session, one with no working folder
    # too, so settings that cannot be read are always refused.
    in_excluded_folder = excluded(session.cwd or os.sep, settings)
    if not session.cwd:
        return Summary(str(location), session.session_id, False, 0, 0, 0, True)
    if in_excluded_folder:
        return Summary(str(location), None, True, 0, 0, 0)

    if harness == wrappers.NAME:
        # The connectors wrote each event in the schema already, so it is
        # stored as it is, in file order.
        events = [dict(event) for event in session.events]
    else:
        events = [_event(harness, session, tool_call) for tool_call in session.tool_calls]
    for event in events:
        problems = validate(event)
        if problems:
            raise ValueError(
                f"{location} gives tool call {event['source_id']} an event the schema refuses, "
                + "; ".join(problems)
            )
    provenance = {
        "session": session.session_id,
        "origin": _origin(harness),
        "method": _method(harness),
        "reason": REASON,
    }

    # The transcript goes into the file store first, so no row names a file
    # the store does not hold.
    checksum = put_file(store, session.transcript)
    session_row, sessions = _session_row(store, harness, session, provenance)

    added = 0
    for ordinal, event in enumerate(events, start=1):
        fields = {
            "session_row_id": session_row,
            "ordinal": ordinal,
            "verb": event["verb"],
            "kind": event["kind"],
            "object": event["object"],
            "rationale": event["rationale"],
            "role": event["role"],
        }
        if add_row(store, "events", fields, provenance, row_id=event["source_id"]) is not None:
            added += 1

    transcripts = 0
    held = current(
        store,
        "transcripts",
        session=session.session_id,
        origin=provenance["origin"],
        file_sha256=checksum,
    )
    if not held:
        fields = {
            "session_row_id": session_row,
            "file_sha256": checksum,
            "byte_size": len(session.transcript),
        }
        add_row(store, "transcripts", fields, provenance)
        transcripts = 1

    # The first session run in a folder adds its project's row (plan choice 19).
    ensure_project(
        store,
        session.cwd,
        {
            "session": session.session_id,
            "origin": provenance["origin"],
            "method": PROJECTS_METHOD,
            "reason": PROJECTS_REASON,
        },
    )

    return Summary(str(location), session.session_id, False, sessions, added, transcripts)


def read_stored(store: Store, session_row) -> Session:
    """The stored session, parsed from its latest transcript by its own harness's adapter."""
    _, data = latest_transcript(store, session_row)
    return adapter(session_row["harness"]).parse_transcript(data)


def _event(harness: str, session: Session, tool_call: ToolCall) -> Dict[str, str]:
    """The tool call as an event in the one schema (events.py).

    The mechanical pass gives the verb, kind, object, and role. The rationale
    stays empty, since Table A4 gives decisions theirs in the model pass.
    """
    event = {
        "harness": harness,
        "harness_session_id": session.session_id,
        "source_id": tool_call.record_id,
        "rationale": "",
    }
    event.update(tag(tool_call, session.cwd))
    return event


def _session_row(
    store: Store, harness: str, session: Session, provenance: Dict[str, str]
) -> Tuple[str, int]:
    """The id of the session's current row, and the number of session rows written.

    A first capture writes the row. A later capture that finds the session
    changed, such as a later end or more tools, writes a row that supersedes
    the current one, with the model pass's four fields empty, so the pass
    runs again on the grown transcript (plan choice 13). Otherwise the current
    row stands, and so do any fields the model pass filled. Only the fields
    capture writes are compared. A row written before the models and the
    harness version existed, which differs only in holding neither, is
    superseded by a row that gains them and keeps the model pass's fields
    (Step P1).
    """
    fields = {
        "harness": harness,
        "harness_session_id": session.session_id,
        "project": session.cwd,
        "started_at": session.started_at,
        "ended_at": session.ended_at,
        "tools": list(session.tools)
        if harness == wrappers.NAME
        else session_tags(
            call._replace(name=call.harness_tool) if call.harness_tool else call
            for call in session.tool_calls
        ),
        "models": list(getattr(session, "models", ())),
        "harness_version": getattr(session, "harness_version", "") or None,
    }
    rows = current(store, "sessions", harness=harness, harness_session_id=session.session_id)
    if not rows:
        return add_row(store, "sessions", fields, provenance), 1
    # Capture keeps one current row for each session, the latest written.
    latest = rows[-1]
    changed = [name for name, value in fields.items() if latest[name] != value]
    if not changed:
        return latest["id"], 0
    if all(name in ADDED and latest[name] is None for name in changed):
        return supersede(store, "sessions", latest["id"], fields, provenance), 1
    fields.update({name: None for name in DERIVED})
    return supersede(store, "sessions", latest["id"], fields, provenance), 1
