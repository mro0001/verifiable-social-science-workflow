"""The Claude Code adapter, which reads one session file for capture.

Appendix A2.4 "Capture" sweeps each harness's session files through one event
schema with an adapter for each harness. Claude Code keeps a session as a JSON
Lines file, one record per line. A record carries the session id (sessionId),
the working folder (cwd), a time (timestamp), and its own id (uuid). An
assistant record's message holds text and tool_use parts, and a user record's
message holds the scholar's typed text or tool_result parts. Real files hold
more record types and fields than these, such as thinking parts and system
records, and the adapter passes over every one it does not use.

Like every adapter in capture's registry, it gives NAME, default_root,
list_sessions, read_session, and parse_transcript (plan choice 2), and the AI
flag, true since an AI wrote the session (reconciliation, item 7).

Claude Code keeps each subagent conversation in a file of its own,
<session id>/subagents/agent-<agent id>.jsonl, in the folder beside the main
session file. Its records carry the parent's sessionId, the subagent's
agentId, and isSidechain true. Each subagent conversation is a session of its
own, with the id <parent session id>/agent-<agent id> (plan choice 5). The
agent-<agent id>.meta.json beside it is neither read nor stored. Records of
type attachment are skipped in every file. A subagent conversation may also be
kept one or more folders deeper than subagents, such as
subagents/workflows/<run>/agent-<agent id>.jsonl, and its ids still come from
its records.

Each assistant record's message names the model that answered, and each
record may give the harness's version. The session keeps the models in the
order first seen and the first version given (Track P, Step P1). An assistant
record the harness wrote itself, such as an API error notice, names the model
<synthetic>, and since no model answered it, it adds no model.
"""
import json
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

from audit_layer.capture import SessionRef

NAME = "claude_code"

# An AI wrote the sessions this harness keeps.
AI = True

# The adapter's version, which capture names in the method of every row it
# writes. Raise it when a change alters what the adapter stores from a file.
VERSION = 3

# A subagent conversation's file, as a path below the folder that holds the
# main session file, <encoded folder>/<session id>/subagents/agent-<agent id>.jsonl.
SUBAGENT_FILES = "*/*/subagents/agent-*.jsonl"

# The model Claude Code names on an assistant record it wrote itself, which no
# model answered.
HARNESS_MADE = "<synthetic>"

# How the text the harness writes into a user record begins: a notice of a
# finished task, a local command and its output, a reminder, a system notice,
# an interruption, and the summary that continues a compacted session.
HARNESS_TEXT = (
    "<task-notification>",
    "<local-command-",
    "<command-",
    "<system-reminder>",
    "[SYSTEM NOTIFICATION",
    "[Request interrupted",
    "This session is being continued from a previous conversation",
)

# What a subagent conversation's id puts between the parent's id and the agent id.
AGENT = "/agent-"


class ToolCall(NamedTuple):
    """One tool call the session made."""

    # The harness's own id for the call, which the call's result repeats. One
    # record can hold more than one call, so the record's uuid would not tell
    # two calls apart.
    record_id: str
    name: str
    input: Dict[str, Any]
    # The time of the record that holds the call.
    time: Optional[str]
    # The harness's own name for the tool, when an adapter gives the call a
    # name the mechanical pass maps instead (the ForgeCode adapter does). It
    # stays None for Claude Code, whose names the pass already maps.
    harness_tool: Optional[str] = None


class Part(NamedTuple):
    """One part of the conversation, in the order the transcript holds them.

    A part is either text or a tool call. A tool call part carries the text of
    the call's result, or None while the transcript holds no result for it.
    """

    # user, assistant, or meta. A meta part is text in a user record that
    # the scholar did not type, such as a notice or a summary the harness
    # wrote (_typed).
    role: str
    # The text, or None for a tool call part.
    text: Optional[str]
    # The tool call, or None for a text part.
    tool_call: Optional[ToolCall]
    # The text of the tool call's result, or None.
    result: Optional[str]


class Session(NamedTuple):
    """What the adapter reads from one session file."""

    session_id: str
    cwd: str
    started_at: str
    ended_at: str
    transcript: bytes
    tool_calls: List[ToolCall]
    # The user, meta, and assistant text in order, as (role, text) pairs.
    # Tool results, thinking, and system records are left out.
    messages: List[Tuple[str, str]]
    # The text and the tool calls, each call with its result, in one list in
    # transcript order (reconciliation, Track A). So the text an assistant
    # wrote before a tool call can be read for any harness.
    parts: List[Part]
    # The models that answered, each once, in the order first seen, and the
    # harness's version, or empty text when the transcript gives none (Step
    # P1). An adapter whose harness gives neither leaves both empty.
    models: Tuple[str, ...] = ()
    harness_version: str = ""
    # True when an AI started the conversation, as with a subagent's, so the
    # text of its user messages is the prompt that AI wrote.
    started_by_agent: bool = False


def default_root() -> Path:
    """The folder Claude Code keeps its sessions in. It is named here and not read."""
    return Path.home() / ".claude" / "projects"


def list_sessions(root) -> List[SessionRef]:
    """Each session file in a folder of root, with its id and size, in path order.

    A session file is <root>/<encoded folder>/<session id>.jsonl, and its id is
    the file name less .jsonl. A subagent conversation's file is
    <root>/<encoded folder>/<session id>/subagents/agent-<agent id>.jsonl, and
    its id is <session id>/agent-<agent id>. No file is opened, so a file that
    does not hold JSON is listed like any other. A root that does not exist
    lists nothing.
    """
    root = Path(root)
    if not root.is_dir():
        return []
    refs = []
    for path in sorted(root.glob("*/*.jsonl")):
        if path.is_file():
            refs.append(SessionRef(path.name[: -len(".jsonl")], str(path), path.stat().st_size))
    for path in sorted(root.glob(SUBAGENT_FILES)):
        if path.is_file():
            refs.append(SessionRef(subagent_id(path), str(path), path.stat().st_size))
    return sorted(refs, key=lambda ref: ref.location)


def subagent_id(path: Path) -> str:
    """The id of the subagent conversation in the file at path, read from the path alone.

    The parent's id is the name of the folder that holds the subagents
    folder, however many folders deeper than subagents the file is kept.
    """
    path = Path(path)
    folder = path.parent
    while folder.name != "subagents" and folder != folder.parent:
        folder = folder.parent
    if folder.name != "subagents":
        folder = path.parent
    return folder.parent.name + "/" + path.name[: -len(".jsonl")]


def read_session(location) -> Session:
    """Read one Claude Code session file, whose path is location.

    The transcript is the file's bytes unchanged, read as parse_transcript
    reads them. A record that cannot be read is refused with the file's path
    and the record's line number.
    """
    path = Path(location)
    data = path.read_bytes()
    try:
        return parse_transcript(data)
    except ValueError as error:
        raise ValueError(f"{path} {error}") from error


def parse_transcript(data: bytes) -> Session:
    """Read a Claude Code session from the bytes of its file.

    The session id and the working folder are the first ones a record gives.
    When the record that gives the session id is a subagent's, with
    isSidechain true and an agentId, the id is <sessionId>/agent-<agentId>.
    The start and end are the first and last times a record gives. Records of
    type attachment are skipped. The transcript is the bytes unchanged. Tool
    calls come in the order the bytes hold them, and so do the parts and the
    messages. The models are each assistant record's model, each once, in the
    order first seen, leaving out <synthetic>, and the harness's version is the
    first version a record gives.
    """
    session_id = None
    cwd = None
    started_at = None
    ended_at = None
    tool_calls: List[ToolCall] = []
    parts: List[Part] = []
    # Where each tool call's part sits in parts, so its result can be added.
    calls_at: Dict[str, int] = {}
    models: List[str] = []
    harness_version = ""
    # Records end at a newline only. A line or paragraph separator inside a
    # JSON string is text, not the end of a record.
    for number, line in enumerate(data.split(b"\n"), start=1):
        if not line.strip():
            continue
        record = _record(number, line)
        if record.get("type") == "attachment":
            continue
        if session_id is None and _is_text(record.get("sessionId")):
            session_id = record["sessionId"]
            if record.get("isSidechain") is True and _is_text(record.get("agentId")):
                session_id += AGENT + record["agentId"]
        if cwd is None and _is_text(record.get("cwd")):
            cwd = record["cwd"]
        time = record.get("timestamp") if _is_text(record.get("timestamp")) else None
        if time is not None:
            started_at = started_at or time
            ended_at = time
        if not harness_version and _is_text(record.get("version")):
            harness_version = record["version"]
        if record.get("type") == "assistant":
            message = record.get("message")
            model = message.get("model") if isinstance(message, dict) else None
            if _is_text(model) and model != HARNESS_MADE and model not in models:
                models.append(model)
            for part in _assistant_parts(number, record, time):
                if part.tool_call is not None:
                    tool_calls.append(part.tool_call)
                    calls_at[part.tool_call.record_id] = len(parts)
                parts.append(part)
        elif record.get("type") == "user":
            _user_parts(record, parts, calls_at)
    if session_id is None:
        raise ValueError("has no record that gives a session id")
    if cwd is None:
        raise ValueError("has no record that gives a working folder")
    if started_at is None:
        raise ValueError("has no record that gives a time")
    return Session(
        session_id=session_id,
        cwd=cwd,
        started_at=started_at,
        ended_at=ended_at,
        transcript=data,
        tool_calls=tool_calls,
        messages=[(part.role, part.text) for part in parts if part.text is not None],
        parts=parts,
        models=tuple(models),
        harness_version=harness_version,
        started_by_agent=AGENT in session_id,
    )


def _record(number: int, line: bytes) -> Dict[str, Any]:
    try:
        record = json.loads(line.decode("utf-8"))
    except ValueError as error:
        raise ValueError(f"line {number} is not a JSON object") from error
    if not isinstance(record, dict):
        raise ValueError(f"line {number} is not a JSON object")
    return record


def _content(record: Dict[str, Any]) -> Any:
    message = record.get("message")
    return message.get("content") if isinstance(message, dict) else None


def _assistant_parts(number: int, record: Dict[str, Any], time: Optional[str]) -> List[Part]:
    """An assistant record's text and tool call parts, in order. Thinking is left out."""
    content = _content(record)
    if _is_text(content):
        return [Part("assistant", content, None, None)]
    parts = []
    for part in content if isinstance(content, list) else []:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text" and _is_text(part.get("text")):
            parts.append(Part("assistant", part["text"], None, None))
        elif part.get("type") == "tool_use":
            if not _is_text(part.get("id")) or not _is_text(part.get("name")):
                raise ValueError(f"line {number} has a tool call without an id or a name")
            call = ToolCall(
                record_id=part["id"],
                name=part["name"],
                input=part.get("input", {}),
                time=time,
            )
            parts.append(Part("assistant", None, call, None))
    return parts


def _user_parts(record: Dict[str, Any], parts: List[Part], calls_at: Dict[str, int]) -> None:
    """Add a user record's text to parts, and its tool results to their calls.

    The text is a user part when the scholar typed it and a meta part when the
    harness wrote it (_typed).
    """
    content = _content(record)
    if _is_text(content):
        parts.append(Part("user" if _typed(record, content) else "meta", content, None, None))
        return
    for part in content if isinstance(content, list) else []:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text" and _is_text(part.get("text")):
            role = "user" if _typed(record, part["text"]) else "meta"
            parts.append(Part(role, part["text"], None, None))
        elif part.get("type") == "tool_result" and part.get("tool_use_id") in calls_at:
            at = calls_at[part["tool_use_id"]]
            parts[at] = parts[at]._replace(result=_result_text(part.get("content")))


def _typed(record: Dict[str, Any], text: str) -> bool:
    """True when the text of a user record is what the scholar typed.

    Claude Code marks text of its own in a user record, such as a skill's body,
    a pasted image, or a local command's caveat, with isMeta, and the summary
    that continues a compacted session with isCompactSummary. Newer versions
    give each prompt an origin, of kind human for what the scholar typed and of
    another kind, such as task-notification, for a notice the harness sent. A
    record with no origin, from an older version, is the scholar's unless its
    text begins as the harness's own text does (HARNESS_TEXT).
    """
    if record.get("isMeta") is True or record.get("isCompactSummary") is True:
        return False
    origin = record.get("origin")
    if isinstance(origin, dict) and origin.get("kind") is not None:
        return origin.get("kind") == "human"
    return not text.lstrip().startswith(HARNESS_TEXT)


def _result_text(content: Any) -> str:
    """A tool result's text. A result given as parts is their text, one part to a line."""
    if isinstance(content, str):
        return content
    texts = []
    for part in content if isinstance(content, list) else []:
        if isinstance(part, dict) and isinstance(part.get("text"), str):
            texts.append(part["text"])
    return "\n".join(texts)


def _is_text(value: Any) -> bool:
    return isinstance(value, str) and value != ""
