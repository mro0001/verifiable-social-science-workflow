"""The ForgeCode adapter, which reads Forge's conversations for capture.

ForgeCode is the fallback harness (the ruling of 2026-10-28), and
appendix A2.4 "Capture" gives each harness an adapter into the one event
schema. Forge keeps its conversations in one SQLite database, by default
~/forge/.forge.db, in one table, conversations, with the columns
conversation_id, title, workspace_id, context, created_at, updated_at, and
metrics. The context column holds the conversation as JSON, with its
conversation_id and its messages. Each message is {"message": {"text": {...}}}
or {"message": {"tool": {...}}}, with an optional usage. A text message has a
role (System, User, or Assistant), its content, its tool calls (each name,
call_id, and arguments), and the model. A tool message has the tool's name,
the call_id, and the output, whose values hold the result.

That form was learned from table and column names and from Forge's public
source only, never from a real conversation. Before live use, check the key
names of one real conversation (key names only).

The database is opened read only and never written. A session is one
conversation, read from the database at a location <database path>#<id>.

workspace_id is a hash of the working folder, not the folder, so the folder
comes from the <current_working_directory> line of the first System message
that has one (plan choice 3). A real conversation's first System message names
no folder and its second does. A conversation with no such line has an empty
working folder, and capture stores nothing of it.

Forge's tool names are translated to the names the mechanical pass already
maps, and each tool call keeps Forge's own name as harness_tool, which the
session's tools list uses (plan choice 4).

Like every adapter in capture's registry, it gives NAME, default_root,
list_sessions, read_session, and parse_transcript (plan choice 2), and the AI
flag, true since an AI wrote the conversations (reconciliation, item 7).
Forge's sub-conversations are not followed, so each conversation is its own
session.

The models are the model each Assistant message names, each once, in the
order first seen, and none when no message names one. A conversation whose
context gives initiator agent was begun by an agent that handed Forge a task,
so its user text is the prompt that agent wrote (started_by_agent). Forge's store gives no
version of the harness, so the version is left empty (Track P, Step P1).
"""
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from audit_layer.capture import SessionRef
from audit_layer.capture.claude_code import Part, Session, ToolCall

NAME = "forgecode"

# An AI wrote the conversations this harness keeps.
AI = True

# The adapter's version, which capture names in the method of every row it
# writes. Raise it when a change alters what the adapter stores from a
# conversation.
VERSION = 3

# Forge's tool names that the mechanical pass maps under another name.
_NAMES = {
    "read": "Read",
    "write": "Write",
    "patch": "Edit",
    "multi_patch": "Edit",
    "fs_search": "Grep",
    "sem_search": "Grep",
    "shell": "Bash",
    "fetch": "WebFetch",
}

_FOLDER_START = "<current_working_directory>"
_FOLDER_END = "</current_working_directory>"


def default_root() -> Path:
    """The database Forge keeps its conversations in. It is named here and not read."""
    return Path.home() / "forge" / ".forge.db"


def list_sessions(root) -> List[SessionRef]:
    """Each conversation in the database at root that holds a context, in the order begun.

    The session id is the conversation_id, the location is <root>#<id>, and
    the size is the byte length of the context. No context is read. A database
    that does not exist lists nothing.
    """
    path = Path(root)
    if not path.is_file():
        return []
    rows = _query(
        path,
        "SELECT conversation_id, length(CAST(context AS BLOB)) FROM conversations"
        " WHERE context IS NOT NULL ORDER BY created_at, conversation_id",
        (),
    )
    return [SessionRef(row[0], f"{root}#{row[0]}", row[1]) for row in rows]


def read_session(location) -> Session:
    """Read one conversation, whose location is <database path>#<conversation id>.

    The start is the row's created_at and the end its updated_at, else its
    created_at. The transcript is the context text as stored, as bytes.
    """
    path, mark, conversation_id = str(location).rpartition("#")
    if not mark or not path or not conversation_id:
        raise ValueError(
            f"{location} does not name a conversation, which is given as <database path>#<id>"
        )
    rows = _query(
        Path(path),
        "SELECT context, created_at, updated_at FROM conversations WHERE conversation_id = ?",
        (conversation_id,),
    )
    if not rows or rows[0][0] is None:
        raise ValueError(f"{path} holds no conversation {conversation_id} with a context")
    context, created_at, updated_at = rows[0]
    data = context if isinstance(context, bytes) else str(context).encode("utf-8")
    try:
        session = parse_transcript(data)
    except ValueError as error:
        raise ValueError(f"conversation {conversation_id} {error}") from error
    started_at = "" if created_at is None else str(created_at)
    ended_at = started_at if updated_at is None else str(updated_at)
    return session._replace(started_at=started_at, ended_at=ended_at)


def parse_transcript(data: bytes) -> Session:
    """Read a Forge conversation from the bytes of its context.

    The context holds no times, so the start and end are empty here and
    read_session fills them from the row. The working folder is empty when no
    System message names one.
    """
    try:
        context = json.loads(data.decode("utf-8"))
    except ValueError as error:
        raise ValueError("has a context that is not JSON") from error
    if not isinstance(context, dict):
        raise ValueError("has a context that is not a JSON object")
    conversation_id = context.get("conversation_id")
    if not _is_text(conversation_id):
        raise ValueError("has a context that gives no conversation_id")
    messages = context.get("messages")
    if not isinstance(messages, list):
        messages = []

    cwd = None
    tool_calls: List[ToolCall] = []
    parts: List[Part] = []
    # Where each tool call's part sits in parts, so its result can be added.
    calls_at: Dict[str, int] = {}
    models: List[str] = []
    for index, entry in enumerate(messages):
        message = entry.get("message") if isinstance(entry, dict) else None
        if not isinstance(message, dict):
            continue
        text = message.get("text")
        tool = message.get("tool")
        if isinstance(text, dict):
            role = text.get("role")
            content = text.get("content")
            if role == "System":
                if not cwd:
                    cwd = _folder(content)
            elif role in ("User", "Assistant"):
                if _is_text(content):
                    parts.append(Part(role.lower(), content, None, None))
                if role == "Assistant":
                    model = text.get("model")
                    if _is_text(model) and model not in models:
                        models.append(model)
                    calls = text.get("tool_calls")
                    for number, call in enumerate(calls if isinstance(calls, list) else []):
                        tool_call = _tool_call(conversation_id, index, number, call)
                        if tool_call is None:
                            continue
                        tool_calls.append(tool_call)
                        calls_at[tool_call.record_id] = len(parts)
                        parts.append(Part("assistant", None, tool_call, None))
        elif isinstance(tool, dict) and tool.get("call_id") in calls_at:
            at = calls_at[tool["call_id"]]
            parts[at] = parts[at]._replace(result=_result_text(tool.get("output")))

    return Session(
        session_id=conversation_id,
        cwd=cwd or "",
        started_at="",
        ended_at="",
        transcript=data,
        tool_calls=tool_calls,
        messages=[(part.role, part.text) for part in parts if part.text is not None],
        parts=parts,
        models=tuple(models),
        started_by_agent=context.get("initiator") == "agent",
    )


def _query(path: Path, sql: str, values) -> List[Any]:
    """The rows the query gives, from the database opened read only."""
    try:
        db = sqlite3.connect(Path(path).absolute().as_uri() + "?mode=ro", uri=True)
    except sqlite3.Error as error:
        raise ValueError(f"{path} could not be opened as a Forge database ({error})") from error
    try:
        return db.execute(sql, values).fetchall()
    except sqlite3.Error as error:
        raise ValueError(f"{path} could not be read as a Forge database ({error})") from error
    finally:
        db.close()


def _folder(content: Any) -> str:
    """The text between the working folder tags, or empty when there are none."""
    if not isinstance(content, str):
        return ""
    start = content.find(_FOLDER_START)
    if start < 0:
        return ""
    start += len(_FOLDER_START)
    end = content.find(_FOLDER_END, start)
    if end < 0:
        return ""
    return content[start:end].strip()


def _tool_call(conversation_id: str, index: int, number: int, call: Any) -> Optional[ToolCall]:
    """One of an Assistant message's tool calls, translated for the mechanical pass.

    The record id is the call_id, else <conversation id>:<message index>:<call
    index>, both counted from 0. A call with no name is passed over.
    """
    if not isinstance(call, dict) or not _is_text(call.get("name")):
        return None
    name = call["name"]
    call_id = call.get("call_id")
    if not _is_text(call_id):
        call_id = f"{conversation_id}:{index}:{number}"
    return ToolCall(
        record_id=call_id,
        name=_NAMES.get(name, name),
        input=_input(name, _arguments(call.get("arguments"))),
        # Forge keeps no time for each message.
        time=None,
        harness_tool=name,
    )


def _arguments(arguments: Any) -> Dict[str, Any]:
    """A call's arguments as an object. Arguments given as JSON text are read as the object it holds."""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except ValueError:
            return {}
    return arguments if isinstance(arguments, dict) else {}


def _input(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """The input the mechanical pass reads.

    A multi_patch is one Edit, whose old strings and new strings are its
    edits' strings, each joined by a newline. Every other call keeps its
    arguments as given.
    """
    if name != "multi_patch":
        return arguments
    edits = arguments.get("edits")
    edits = [edit for edit in edits if isinstance(edit, dict)] if isinstance(edits, list) else []
    given = {key: value for key, value in arguments.items() if key != "edits"}
    given["old_string"] = "\n".join(str(edit.get("old_string", "")) for edit in edits)
    given["new_string"] = "\n".join(str(edit.get("new_string", "")) for edit in edits)
    return given


def _result_text(output: Any) -> str:
    """A tool's result as text, its values' text one to a line."""
    values = output.get("values") if isinstance(output, dict) else None
    texts = []
    for value in values if isinstance(values, list) else []:
        if isinstance(value, str):
            texts.append(value)
        elif isinstance(value, dict) and isinstance(value.get("text"), str):
            texts.append(value["text"])
    return "\n".join(texts)


def _is_text(value: Any) -> bool:
    return isinstance(value, str) and value != ""
