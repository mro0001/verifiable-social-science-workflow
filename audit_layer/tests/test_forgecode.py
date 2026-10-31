"""Tests for the ForgeCode adapter (Track A, Step A2).

ForgeCode is the fallback harness (the ruling of 2026-10-28), and
appendix A2.4 "Capture" gives each harness an adapter into the one event
schema. Forge keeps its conversations in one SQLite table, and the adapter
reads that database read only. The working folder comes from the system
message's <current_working_directory> line (plan choice 3), and Forge's tool
names are translated to the names the mechanical pass maps while the
session's tools list keeps Forge's own (plan choice 4).

Every database here is the synthetic one fixtures/forgecode/make_store.py
writes into a temporary folder, and the Claude Code session is the test
story's, with its folder token replaced. No real session or database is read,
no default root is read, nothing here calls a model or the network, and every
test runs with its home folder inside a temporary folder. Run from the
repository root with python3 -m pytest -q audit_layer/tests.
"""
import hashlib
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from audit_layer.capture import (  # noqa: E402
    ADAPTERS,
    SessionRef,
    Summary,
    capture_file,
    capture_session,
    claude_code,
    forgecode,
    read_stored,
)
from audit_layer.cli import main  # noqa: E402
from audit_layer.queries import current_session, latest_transcript, session_events  # noqa: E402
from audit_layer.store import current, open_store  # noqa: E402
from audit_layer.tagging import mechanical  # noqa: E402

_SPEC = importlib.util.spec_from_file_location(
    "forgecode_make_store", Path(__file__).parent / "fixtures" / "forgecode" / "make_store.py"
)
fixture = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(fixture)

SESSIONS = ROOT / "examples" / "test_story" / "sessions" / "claude_code"
STORY_SESSION = SESSIONS / "story_session.jsonl"
TOKEN = "{{PROJECT}}"

TABLES = ("sessions", "events", "transcripts")

STORY_CALL_IDS = [call_id for call_id, _, _ in fixture.STORY_CALLS]
FORGE_NAMES = [name for _, name, _ in fixture.STORY_CALLS]
TRANSLATED = ["Read", "Edit", "Edit", "Write", "Bash", "Bash"]


def settings_for(*folders):
    return {"excluded_folders": [str(folder) for folder in folders]}


def stored_rows(db, table):
    cursor = db.execute(f"SELECT * FROM {table} ORDER BY rowid")
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def context_of(db_path, conversation_id):
    db = sqlite3.connect(str(db_path))
    try:
        (text,) = db.execute(
            "SELECT context FROM conversations WHERE conversation_id = ?", (conversation_id,)
        ).fetchone()
    finally:
        db.close()
    return text


def set_context(db_path, conversation_id, text):
    db = sqlite3.connect(str(db_path))
    try:
        db.execute(
            "UPDATE conversations SET context = ? WHERE conversation_id = ?",
            (text, conversation_id),
        )
        db.commit()
    finally:
        db.close()


def location(db_path, conversation_id):
    return f"{db_path}#{conversation_id}"


def context_bytes(messages, conversation_id="c-test"):
    return fixture.context_text(conversation_id, messages).encode("utf-8")


@pytest.fixture(autouse=True)
def home_folder(tmp_path, monkeypatch):
    """Each test's own home folder, so nothing reaches the real ~/forge or ~/.audit_layer."""
    home = tmp_path / "home_folder"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("AUDIT_HOME", raising=False)
    return home


@pytest.fixture
def project(tmp_path):
    folder = tmp_path / "project"
    folder.mkdir()
    return folder


@pytest.fixture
def forge_db(tmp_path, project):
    return fixture.make_store(tmp_path / "forge" / ".forge.db", project)


@pytest.fixture
def audit(tmp_path):
    store = open_store(tmp_path / "audit_home")
    yield store
    store.db.close()


@pytest.fixture
def settings(project):
    return settings_for(project / "excluded_folder")


# The adapter in the registry.


def test_the_registry_holds_the_forgecode_adapter():
    assert ADAPTERS["forgecode"] is forgecode
    assert forgecode.NAME == "forgecode"
    assert forgecode.AI is True
    for function in ("default_root", "list_sessions", "read_session", "parse_transcript"):
        assert callable(getattr(forgecode, function))


def test_the_default_root_is_forges_database_and_is_not_read(home_folder):
    assert forgecode.default_root() == home_folder / "forge" / ".forge.db"
    assert not (home_folder / "forge").exists()


# Listing the conversations.


def test_listing_gives_the_three_conversations_with_their_sizes(forge_db):
    refs = forgecode.list_sessions(forge_db)
    expected = [
        SessionRef(
            conversation_id,
            location(forge_db, conversation_id),
            len(context_of(forge_db, conversation_id).encode("utf-8")),
        )
        for conversation_id in (fixture.STORY_ID, fixture.EXCLUDED_ID, fixture.NO_SYSTEM_ID)
    ]
    assert sorted(refs) == sorted(expected)


def test_a_conversation_with_no_context_is_not_listed(forge_db):
    db = sqlite3.connect(str(forge_db))
    try:
        db.execute(
            "INSERT INTO conversations VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("empty-conversation", "Nothing yet", 4, None, "2026-10-21 17:00:00.000", None, None),
        )
        db.commit()
    finally:
        db.close()
    ids = [ref.harness_session_id for ref in forgecode.list_sessions(forge_db)]
    assert len(ids) == 3
    assert "empty-conversation" not in ids


def test_listing_a_missing_database_gives_nothing(tmp_path):
    assert forgecode.list_sessions(tmp_path / "no_forge" / ".forge.db") == []
    assert not (tmp_path / "no_forge").exists()


def test_listing_a_file_that_is_not_a_database_is_refused(tmp_path):
    path = tmp_path / "not_a_database.db"
    path.write_bytes(b"this is not a database at all, just plain text" * 4)
    with pytest.raises(ValueError):
        forgecode.list_sessions(path)


# Reading a conversation.


def test_the_story_conversation_reads_back_with_its_id_folder_times_and_tools(
    forge_db, project
):
    session = forgecode.read_session(location(forge_db, fixture.STORY_ID))
    assert session.session_id == fixture.STORY_ID
    assert session.cwd == str(project)
    assert session.started_at == fixture.STORY_CREATED
    assert session.ended_at == fixture.STORY_UPDATED
    assert [call.record_id for call in session.tool_calls] == STORY_CALL_IDS
    assert [call.name for call in session.tool_calls] == TRANSLATED
    assert [call.harness_tool for call in session.tool_calls] == FORGE_NAMES
    # Forge keeps no time for each message.
    assert [call.time for call in session.tool_calls] == [None] * 6
    assert session.transcript == context_of(forge_db, fixture.STORY_ID).encode("utf-8")


def test_a_conversation_with_no_updated_time_ends_when_it_started(forge_db):
    session = forgecode.read_session(location(forge_db, fixture.NO_SYSTEM_ID))
    assert session.started_at == fixture.NO_SYSTEM_CREATED
    assert session.ended_at == fixture.NO_SYSTEM_CREATED
    # It has no System message, so its working folder is empty.
    assert session.cwd == ""


def test_parse_transcript_reads_the_context_as_read_session_does_less_the_times(forge_db):
    from_db = forgecode.read_session(location(forge_db, fixture.STORY_ID))
    parsed = forgecode.parse_transcript(from_db.transcript)
    # The times are columns of the row, not part of the context.
    assert parsed == from_db._replace(started_at="", ended_at="")


def test_the_translated_inputs_are_those_the_mechanical_pass_reads(forge_db, project):
    session = forgecode.read_session(location(forge_db, fixture.STORY_ID))
    read, first, second, write, check, commit = session.tool_calls
    assert read.input == {"file_path": "manuscript.md"}
    assert set(first.input) == {"file_path", "old_string", "new_string"}
    assert "[@dumont2014]" in first.input["new_string"]
    assert "[@nakamura2020]" in second.input["new_string"]
    assert write.input["file_path"] == str(project / "source_notes.md")
    assert "ospipe check" in check.input["command"]
    assert "git commit" in commit.input["command"]


def test_the_messages_are_the_user_and_assistant_text_in_order(forge_db, project):
    session = forgecode.read_session(location(forge_db, fixture.STORY_ID))
    story = claude_code.parse_transcript(
        STORY_SESSION.read_text(encoding="utf-8")
        .replace(TOKEN, json.dumps(str(project))[1:-1])
        .encode("utf-8")
    )
    # The same request, the same text before each call, and the same close.
    assert session.messages == story.messages
    for _, text in session.messages:
        assert "<current_working_directory>" not in text


def test_the_parts_hold_each_call_with_its_result_in_order(forge_db, project):
    session = forgecode.read_session(location(forge_db, fixture.STORY_ID))
    calls = [part for part in session.parts if part.tool_call is not None]
    assert [part.tool_call for part in calls] == session.tool_calls
    assert calls[-1].result.startswith("[main bea0f61]")
    assert calls[0].result is not None and "manuscript" in calls[0].result.lower()
    assert session.parts[0].role == "user" and session.parts[0].text == session.messages[0][1]
    assert session.parts[-1].role == "assistant" and session.parts[-1].tool_call is None


def test_multi_patch_becomes_one_edit_with_its_strings_joined_by_a_newline():
    arguments = {
        "file_path": "/work/manuscript.md",
        "edits": [
            {"old_string": "first old", "new_string": "first new"},
            {"old_string": "second old", "new_string": "second new"},
        ],
    }
    messages = [
        fixture.system_message("/work"),
        fixture.text_message(
            "Assistant", "Two edits.", [fixture.tool_call("multi_patch", "call_multi", arguments)]
        ),
    ]
    (call,) = forgecode.parse_transcript(context_bytes(messages)).tool_calls
    assert call.name == "Edit"
    assert call.harness_tool == "multi_patch"
    assert call.input == {
        "file_path": "/work/manuscript.md",
        "old_string": "first old\nsecond old",
        "new_string": "first new\nsecond new",
    }
    assert mechanical.tag(call, "/work") == {
        "verb": "edited",
        "kind": "action",
        "object": "/work/manuscript.md",
        "role": "edited",
    }


def test_the_search_and_fetch_names_are_translated_and_others_stay():
    calls = [
        fixture.tool_call("fs_search", "c1", {"pattern": "@dumont2014", "path": "."}),
        fixture.tool_call("sem_search", "c2", {"pattern": "volunteer exit"}),
        fixture.tool_call("fetch", "c3", {"url": "https://example.org/paper"}),
        fixture.tool_call("todo_write", "c4", {"todos": []}),
        fixture.tool_call("remove", "c5", {"path": "old.md"}),
    ]
    messages = [
        fixture.system_message("/work"),
        fixture.text_message("Assistant", "Looking.", calls),
    ]
    session = forgecode.parse_transcript(context_bytes(messages))
    assert [call.name for call in session.tool_calls] == [
        "Grep",
        "Grep",
        "WebFetch",
        "todo_write",
        "remove",
    ]
    assert [call.harness_tool for call in session.tool_calls] == [
        "fs_search",
        "sem_search",
        "fetch",
        "todo_write",
        "remove",
    ]
    tags = [mechanical.tag(call, "/work") for call in session.tool_calls]
    assert [(tag["verb"], tag["object"]) for tag in tags] == [
        ("searched", "@dumont2014"),
        ("searched", "volunteer exit"),
        ("searched", "https://example.org/paper"),
        ("ran", "todo_write"),
        ("ran", "remove"),
    ]


def test_arguments_given_as_json_text_are_read_as_their_object():
    call = fixture.tool_call("shell", "c1", json.dumps({"command": "git status"}))
    messages = [
        fixture.system_message("/work"),
        fixture.text_message("Assistant", "Status.", [call]),
    ]
    (read,) = forgecode.parse_transcript(context_bytes(messages)).tool_calls
    assert read.name == "Bash"
    assert read.input == {"command": "git status"}


def test_a_call_with_no_call_id_takes_the_conversation_message_and_call_index():
    calls = [
        {"name": "read", "arguments": {"file_path": "a.md"}},
        {"name": "read", "call_id": None, "arguments": {"file_path": "b.md"}},
    ]
    messages = [
        fixture.system_message("/work"),
        fixture.text_message("User", "Read both."),
        fixture.text_message("Assistant", "Reading.", calls),
    ]
    session = forgecode.parse_transcript(context_bytes(messages, "c-noid"))
    assert [call.record_id for call in session.tool_calls] == ["c-noid:2:0", "c-noid:2:1"]


def test_the_first_system_message_that_names_a_folder_gives_the_working_folder():
    # A real conversation names its folder in its second System message, after
    # one that names none.
    messages = [
        fixture.text_message("System", "You are a coding assistant, with no folder named."),
        fixture.system_message("/later"),
        fixture.text_message("User", "Hello."),
    ]
    assert forgecode.parse_transcript(context_bytes(messages)).cwd == "/later"


@pytest.mark.parametrize("initiator, by_agent", [("agent", True), ("user", False), (None, False)])
def test_a_conversation_an_agent_began_is_started_by_an_agent(initiator, by_agent):
    # An agent that hands Forge a task writes the conversation's user text.
    context = {"conversation_id": "c-test", "messages": [fixture.system_message("/work")]}
    if initiator is not None:
        context["initiator"] = initiator
    session = forgecode.parse_transcript(json.dumps(context).encode("utf-8"))
    assert session.started_by_agent is by_agent


def test_a_folder_named_by_a_later_system_message_does_not_replace_the_first():
    messages = [
        fixture.system_message("/first"),
        fixture.system_message("/second"),
        fixture.text_message("User", "Hello."),
    ]
    assert forgecode.parse_transcript(context_bytes(messages)).cwd == "/first"


def test_a_context_that_is_not_json_is_refused():
    with pytest.raises(ValueError):
        forgecode.parse_transcript(b"not JSON at all")
    with pytest.raises(ValueError):
        forgecode.parse_transcript(json.dumps({"messages": []}).encode("utf-8"))


def test_a_location_without_a_conversation_or_an_unknown_one_is_refused(forge_db):
    with pytest.raises(ValueError):
        forgecode.read_session(str(forge_db))
    with pytest.raises(ValueError, match="no-such-conversation"):
        forgecode.read_session(location(forge_db, "no-such-conversation"))


# Capturing a conversation.


def events_of(store, harness, session_id):
    row = current_session(store, harness, session_id)
    return [
        (event["verb"], event["kind"], event["object"], event["role"])
        for event in session_events(store, row)
    ]


def test_the_story_conversation_captures_as_the_claude_code_story_does(
    tmp_path, forge_db, project, settings
):
    story = tmp_path / "story_session.jsonl"
    story.write_bytes(
        STORY_SESSION.read_text(encoding="utf-8")
        .replace(TOKEN, json.dumps(str(project))[1:-1])
        .encode("utf-8")
    )
    by_claude = open_store(tmp_path / "claude_home")
    by_forge = open_store(tmp_path / "forge_home")
    try:
        capture_file(by_claude, story, settings)
        where = location(forge_db, fixture.STORY_ID)
        summary = capture_session(by_forge, "forgecode", where, settings)
        assert summary == Summary(where, fixture.STORY_ID, False, 1, 6, 1)

        story_id = claude_code.read_session(story).session_id
        assert events_of(by_forge, "forgecode", fixture.STORY_ID) == events_of(
            by_claude, "claude_code", story_id
        )

        row = current_session(by_forge, "forgecode", fixture.STORY_ID)
        assert row["tools"] == ["read", "patch", "write", "shell"]
        assert row["project"] == str(project)
        assert row["started_at"] == fixture.STORY_CREATED
        assert row["ended_at"] == fixture.STORY_UPDATED
        assert [event["id"] for event in session_events(by_forge, row)] == STORY_CALL_IDS

        _, data = latest_transcript(by_forge, row)
        assert data == context_of(forge_db, fixture.STORY_ID).encode("utf-8")

        for table in TABLES:
            for stored in stored_rows(by_forge.db, table):
                assert stored["origin"] == "forgecode adapter"
                assert stored["session"] == fixture.STORY_ID
                assert stored["method"] == (
                    "forgecode adapter version {}, mechanical tagging version {}".format(
                        forgecode.VERSION, mechanical.VERSION
                    )
                )
    finally:
        by_claude.db.close()
        by_forge.db.close()


def test_the_excluded_conversation_stores_nothing(audit, forge_db, settings):
    where = location(forge_db, fixture.EXCLUDED_ID)
    summary = capture_session(audit, "forgecode", where, settings)
    assert summary.excluded is True
    assert (summary.sessions, summary.events, summary.transcripts) == (0, 0, 0)
    assert all(stored_rows(audit.db, table) == [] for table in TABLES)


def test_a_conversation_with_no_system_message_stores_nothing_and_says_so(
    audit, forge_db, settings
):
    where = location(forge_db, fixture.NO_SYSTEM_ID)
    summary = capture_session(audit, "forgecode", where, settings)
    assert summary == Summary(where, fixture.NO_SYSTEM_ID, False, 0, 0, 0, True)
    assert summary.folder_unknown is True
    assert all(stored_rows(audit.db, table) == [] for table in TABLES)


def test_settings_that_list_no_excluded_folders_are_refused_for_an_unplaced_session_too(
    audit, forge_db
):
    from audit_layer.settings import SettingsError

    with pytest.raises(SettingsError):
        capture_session(audit, "forgecode", location(forge_db, fixture.NO_SYSTEM_ID), {})
    assert all(stored_rows(audit.db, table) == [] for table in TABLES)


def test_a_session_of_any_harness_with_no_working_folder_stores_nothing(
    audit, tmp_path, project, monkeypatch, settings
):
    story = tmp_path / "story_session.jsonl"
    story.write_bytes(
        STORY_SESSION.read_text(encoding="utf-8")
        .replace(TOKEN, json.dumps(str(project))[1:-1])
        .encode("utf-8")
    )

    read = claude_code.read_session

    def no_folder(location):
        return read(location)._replace(cwd="")

    monkeypatch.setattr(claude_code, "read_session", no_folder)
    summary = capture_session(audit, "claude_code", story, settings)
    assert summary.folder_unknown is True
    assert summary.excluded is False
    assert all(stored_rows(audit.db, table) == [] for table in TABLES)


def test_capture_never_changes_the_forge_database(audit, forge_db, settings):
    before = sha256(forge_db)
    for ref in forgecode.list_sessions(forge_db):
        capture_session(audit, "forgecode", ref.location, settings)
    assert sha256(forge_db) == before
    assert sorted(path.name for path in forge_db.parent.iterdir()) == [".forge.db"]


def test_a_grown_conversation_adds_only_the_new_event_and_a_new_transcript(
    audit, forge_db, project, settings
):
    where = location(forge_db, fixture.STORY_ID)
    capture_session(audit, "forgecode", where, settings)
    assert capture_session(audit, "forgecode", where, settings) == Summary(
        where, fixture.STORY_ID, False, 0, 0, 0
    )

    context = json.loads(context_of(forge_db, fixture.STORY_ID))
    arguments = {
        "file_path": str(project / "source_notes.md"),
        "old_string": "# Sources added in this session",
        "new_string": "# Sources added in this session, both checked",
    }
    context["messages"].append(
        fixture.text_message(
            "Assistant",
            "One more change to the notes.",
            [fixture.tool_call("patch", "call_forge_07_patch", arguments)],
        )
    )
    context["messages"].append(fixture.tool_message("patch", "call_forge_07_patch", "patched"))
    set_context(forge_db, fixture.STORY_ID, json.dumps(context))

    before = {table: len(stored_rows(audit.db, table)) for table in TABLES}
    summary = capture_session(audit, "forgecode", where, settings)
    assert summary == Summary(where, fixture.STORY_ID, False, 0, 1, 1)
    after = {table: len(stored_rows(audit.db, table)) for table in TABLES}
    assert after == {
        "sessions": before["sessions"],
        "events": before["events"] + 1,
        "transcripts": before["transcripts"] + 1,
    }
    row = current_session(audit, "forgecode", fixture.STORY_ID)
    events = session_events(audit, row)
    assert [event["id"] for event in events] == STORY_CALL_IDS + ["call_forge_07_patch"]
    assert (events[-1]["verb"], events[-1]["object"]) == (
        "edited",
        str(project / "source_notes.md"),
    )
    assert latest_transcript(audit, row)[1] == json.dumps(context).encode("utf-8")


def test_read_stored_parses_a_forge_session_with_the_forgecode_adapter(
    audit, forge_db, settings
):
    where = location(forge_db, fixture.STORY_ID)
    capture_session(audit, "forgecode", where, settings)
    row = current_session(audit, "forgecode", fixture.STORY_ID)
    stored = read_stored(audit, row)
    from_db = forgecode.read_session(where)
    assert stored.tool_calls == from_db.tool_calls
    assert [call.harness_tool for call in stored.tool_calls] == FORGE_NAMES
    assert stored.messages == from_db.messages
    assert stored.cwd == from_db.cwd


# The capture command.


def test_the_capture_command_takes_forge_locations_and_reports_an_unknown_folder(
    tmp_path, forge_db, capsys
):
    home = tmp_path / "audit_home"
    assert main(["init", "--home", str(home)]) == 0
    capsys.readouterr()
    story = location(forge_db, fixture.STORY_ID)
    unplaced = location(forge_db, fixture.NO_SYSTEM_ID)
    assert main(["capture", "--home", str(home), "--harness", "forgecode", story, unplaced]) == 0
    lines = capsys.readouterr().out.strip().split("\n")
    assert len(lines) == 2
    assert fixture.STORY_ID in lines[0] and "6 events" in lines[0]
    assert fixture.NO_SYSTEM_ID in lines[1] and "working folder unknown" in lines[1]
    store = open_store(home)
    try:
        assert [row["harness_session_id"] for row in current(store, "sessions")] == [
            fixture.STORY_ID
        ]
    finally:
        store.db.close()
