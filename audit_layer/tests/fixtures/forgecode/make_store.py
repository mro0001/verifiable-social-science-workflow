"""A synthetic ForgeCode database for the ForgeCode adapter's tests (Track A, Step A2).

ForgeCode keeps its conversations in one SQLite table, conversations, with
seven columns (conversation_id, title, workspace_id, context, created_at,
updated_at, metrics). The context column holds the conversation as JSON, with
its conversation_id and its messages. Each message is {"message": {"text":
{...}}} or {"message": {"tool": {...}}}, with an optional usage. A text
message has a role (System, User, or Assistant), its content, its tool calls
(each name, call_id, and arguments), and the model. A tool message has the
tool's name, the call_id, and the output (is_error and values). The system
message names the working folder between <current_working_directory> tags.

That form was learned from table and column names and from Forge's public
source only, never from a real conversation. Everything here is made up.

make_store writes three conversations.
- The story's work in Forge's form, run in the project folder. It takes the
  scholar's request, the AI's text, each tool call's input, and each result
  from the test story's Claude Code session, so both harnesses hold the same
  work. The read names manuscript.md relative to the working folder, the
  other files are named by full path, and the shell calls run the same
  commands.
- A conversation run in project/excluded_folder.
- A conversation with no System message, so its working folder is unknown.
  It has no updated_at.
"""
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
STORY_SESSION = ROOT / "examples" / "test_story" / "sessions" / "claude_code" / "story_session.jsonl"
TOKEN = "{{PROJECT}}"

STORY_ID = "7c2e9a41-5b3d-4f8a-9e16-c0b4d2a8f531"
EXCLUDED_ID = "3a8d6f20-1c4e-4b7a-8d93-e5f1a0c7b264"
NO_SYSTEM_ID = "e41b7c05-9d2a-4e6f-b358-2c7a9f0d1e83"

STORY_CREATED = "2026-10-21 14:02:05.112"
STORY_UPDATED = "2026-10-21 14:02:46.009"
EXCLUDED_CREATED = "2026-10-21 15:10:00.000"
EXCLUDED_UPDATED = "2026-10-21 15:10:30.000"
NO_SYSTEM_CREATED = "2026-10-21 16:20:00.000"

MODEL = "stand-in-model-1"

# The story's tool calls in order, as Forge names them, with the id of the
# Claude Code call each one repeats.
STORY_CALLS = [
    ("call_forge_01_read", "read", "toolu_story_01_read"),
    ("call_forge_02_patch", "patch", "toolu_story_02_edit"),
    ("call_forge_03_patch", "patch", "toolu_story_03_edit"),
    ("call_forge_04_write", "write", "toolu_story_04_write"),
    ("call_forge_05_shell", "shell", "toolu_story_05_bash"),
    ("call_forge_06_shell", "shell", "toolu_story_06_bash"),
]

TABLE = """
CREATE TABLE conversations (
    conversation_id TEXT PRIMARY KEY NOT NULL,
    title TEXT,
    workspace_id BIGINT NOT NULL,
    context TEXT,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP,
    metrics TEXT
)
"""


def system_message(folder):
    """Forge's system message, naming the folder it ran in."""
    content = (
        "You are a coding assistant.\n<system_information>\n"
        "<operating_system>stand-in</operating_system>\n"
        f"<current_working_directory>{folder}</current_working_directory>\n"
        "</system_information>"
    )
    return text_message("System", content)


def text_message(role, content, tool_calls=None, usage=None):
    text = {"role": role, "content": content, "tool_calls": tool_calls, "model": None}
    if role == "Assistant":
        text["model"] = MODEL
    message = {"message": {"text": text}}
    if usage is not None:
        message["usage"] = usage
    return message


def tool_call(name, call_id, arguments):
    return {"name": name, "call_id": call_id, "arguments": arguments}


def tool_message(name, call_id, output, is_error=False):
    return {
        "message": {
            "tool": {
                "name": name,
                "call_id": call_id,
                "output": {"is_error": is_error, "values": [{"text": output}]},
            }
        }
    }


def context_text(conversation_id, messages):
    """The context column's text for a conversation."""
    return json.dumps({"conversation_id": conversation_id, "messages": messages})


def story_messages(project):
    """The story's work in Forge's form, run in project."""
    text = STORY_SESSION.read_text(encoding="utf-8")
    text = text.replace(TOKEN, json.dumps(str(project))[1:-1])
    records = [json.loads(line) for line in text.split("\n") if line]

    request = records[0]["message"]["content"]
    texts = {}
    inputs = {}
    results = {}
    closing = None
    for record in records:
        content = (record.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        said = [part["text"] for part in content if part.get("type") == "text"]
        calls = [part for part in content if part.get("type") == "tool_use"]
        for call in calls:
            inputs[call["id"]] = call["input"]
            texts[call["id"]] = said[0]
        if record["type"] == "assistant" and not calls:
            closing = said[0]
        for part in content:
            if part.get("type") == "tool_result":
                results[part["tool_use_id"]] = part["content"]

    usage = {"prompt_tokens": 1200, "completion_tokens": 40}
    messages = [system_message(project), text_message("User", request)]
    for call_id, name, story_id in STORY_CALLS:
        given = inputs[story_id]
        if name == "read":
            arguments = {"file_path": "manuscript.md"}
        elif name == "patch":
            arguments = {
                "file_path": given["file_path"],
                "old_string": given["old_string"],
                "new_string": given["new_string"],
            }
        elif name == "write":
            arguments = {"file_path": given["file_path"], "content": given["content"]}
        else:
            arguments = {"command": given["command"], "cwd": str(project)}
        messages.append(
            text_message(
                "Assistant", texts[story_id], [tool_call(name, call_id, arguments)], usage
            )
        )
        messages.append(tool_message(name, call_id, results[story_id]))
    messages.append(text_message("Assistant", closing, None, usage))
    return messages


def excluded_messages(project):
    folder = Path(project) / "excluded_folder"
    return [
        system_message(folder),
        text_message("User", "Read the notes in this folder."),
        text_message(
            "Assistant",
            "I'll read the notes.",
            [tool_call("read", "call_forge_excluded_01_read", {"file_path": "notes.md"})],
        ),
        tool_message("read", "call_forge_excluded_01_read", "A made-up note."),
    ]


def no_system_messages():
    return [
        text_message("User", "Find where the manuscript cites dumont2014."),
        text_message(
            "Assistant",
            "I'll search for it.",
            [
                tool_call(
                    "fs_search",
                    "call_forge_nosystem_01_search",
                    {"pattern": "@dumont2014", "path": "manuscript.md"},
                )
            ],
        ),
        tool_message("fs_search", "call_forge_nosystem_01_search", "manuscript.md:22"),
    ]


def make_store(db_path, project):
    """Write a synthetic Forge database at db_path holding the three conversations.

    project is the folder the story conversation ran in. The database path is
    given back.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        (
            STORY_ID,
            "Add two findings on volunteer exit",
            1111111111,
            context_text(STORY_ID, story_messages(project)),
            STORY_CREATED,
            STORY_UPDATED,
            json.dumps({"files_changed": 2}),
        ),
        (
            EXCLUDED_ID,
            "Read the notes",
            2222222222,
            context_text(EXCLUDED_ID, excluded_messages(project)),
            EXCLUDED_CREATED,
            EXCLUDED_UPDATED,
            None,
        ),
        (
            NO_SYSTEM_ID,
            "Find a citation",
            3333333333,
            context_text(NO_SYSTEM_ID, no_system_messages()),
            NO_SYSTEM_CREATED,
            None,
            None,
        ),
    ]
    db = sqlite3.connect(str(db_path))
    try:
        db.execute(TABLE)
        db.executemany("INSERT INTO conversations VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
        db.commit()
    finally:
        db.close()
    return db_path
