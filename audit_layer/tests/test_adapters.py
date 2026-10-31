"""Tests for one adapter per harness (Track A, Step A1).

Appendix A2.4 "Capture" sweeps each harness's session files through one event
schema with an adapter for each harness. Capture reaches a harness only
through the registry of adapters by name (plan choice 2), each adapter carries
the AI flag (reconciliation, every track item 7), and a Session carries one
ordered list of parts in transcript order (reconciliation, Track A).

The sessions are the test story's synthetic Claude Code session files, whose
folder token {{PROJECT}} is replaced with a temporary folder. No real session
file is read, no default root is read, nothing here calls a model or the
network, and every test runs with its home folder inside a temporary folder.
Run from the repository root with python3 -m pytest -q audit_layer/tests.
"""
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from audit_layer.capture import (  # noqa: E402
    ADAPTERS,
    SessionRef,
    Summary,
    adapter,
    capture_file,
    capture_session,
    claude_code,
    read_stored,
)
from audit_layer.cli import main  # noqa: E402
from audit_layer.queries import (  # noqa: E402
    current_session,
    latest_transcript,
    session_events,
)
from audit_layer.store import current, open_store, supersede  # noqa: E402
from audit_layer.tagging import mechanical  # noqa: E402

SESSIONS = ROOT / "examples" / "test_story" / "sessions" / "claude_code"
STORY_SESSION = SESSIONS / "story_session.jsonl"
EXCLUDED_SESSION = SESSIONS / "excluded_session.jsonl"
TOKEN = "{{PROJECT}}"

STORY_ID = "5f3c0413-2a7d-4b9e-8c61-a0d4e7b2c913"
EXCLUDED_ID = "9b1e0414-6c3a-4f2d-b8e5-71d2a9c4f086"

TABLES = ("sessions", "events", "transcripts")
# What a row holds apart from its id, its time, and the ids of other rows.
COMPARED = {
    "sessions": ("harness", "harness_session_id", "project", "started_at", "ended_at", "tools"),
    "events": ("ordinal", "verb", "kind", "object", "rationale", "role"),
    "transcripts": ("file_sha256", "byte_size"),
}
PROVENANCE = ("session", "origin", "method", "reason")

# The story's tool calls in order, as the harness gives them.
STORY_CALLS = [
    "toolu_story_01_read",
    "toolu_story_02_edit",
    "toolu_story_03_edit",
    "toolu_story_04_write",
    "toolu_story_05_bash",
    "toolu_story_06_bash",
]

# The story's assistant text before each tool call, in order.
STORY_TEXTS = [
    "I'll read the manuscript first.",
    "I'll add the first finding after your sentence on fit.",
    "Now the second finding.",
    "Next I'll list the two sources in a notes file.",
    "Now the manuscript check.",
    "The check passes. Committing both files.",
]


def lines_of(source, project):
    """The session file's records as lines of text, with the token replaced by project."""
    text = source.read_text(encoding="utf-8")
    text = text.replace(TOKEN, json.dumps(str(project))[1:-1])
    return [line for line in text.split("\n") if line]


def write_session(path, lines):
    """Write the lines as a JSON Lines file, each ending in a newline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes("".join(line + "\n" for line in lines).encode("utf-8"))
    return path


def records_of(lines):
    return [json.loads(line) for line in lines]


def settings_for(*folders):
    return {"excluded_folders": [str(folder) for folder in folders]}


def stored_rows(db, table):
    """Rows as the database holds them, superseded or not, in the order written."""
    cursor = db.execute(f"SELECT * FROM {table} ORDER BY rowid")
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def without_ids(db):
    """Every row of every table, less its id, its time, and the ids of other rows."""
    return {
        table: [
            {name: row[name] for name in COMPARED[table] + PROVENANCE}
            for row in stored_rows(db, table)
        ]
        for table in TABLES
    }


def tool_results(lines):
    """Each tool call's result text, read here without the adapter."""
    results = {}
    for record in records_of(lines):
        content = (record.get("message") or {}).get("content")
        for part in content if isinstance(content, list) else []:
            if part.get("type") == "tool_result":
                results[part["tool_use_id"]] = part["content"]
    return results


@pytest.fixture(autouse=True)
def home_folder(tmp_path, monkeypatch):
    """Each test's own home folder, so nothing reaches the real ~/.audit_layer."""
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
def story(tmp_path, project):
    return write_session(tmp_path / "story_session.jsonl", lines_of(STORY_SESSION, project))


@pytest.fixture
def audit(tmp_path):
    store = open_store(tmp_path / "audit_home")
    yield store
    store.db.close()


# The registry of adapters.


def test_the_registry_holds_the_claude_code_adapter():
    assert ADAPTERS["claude_code"] is claude_code
    assert adapter("claude_code") is claude_code


def test_an_unknown_harness_is_refused_and_the_message_names_the_known_ones():
    with pytest.raises(ValueError) as refused:
        adapter("forgecode_v0")
    assert "forgecode_v0" in str(refused.value)
    assert "claude_code" in str(refused.value)


def test_each_adapter_gives_the_same_five_things_and_the_ai_flag():
    for name, module in ADAPTERS.items():
        assert module.NAME == name
        for function in ("default_root", "list_sessions", "read_session", "parse_transcript"):
            assert callable(getattr(module, function)), (name, function)
        assert isinstance(module.AI, bool), name
    assert claude_code.AI is True


def test_the_claude_code_default_root_is_its_projects_folder(home_folder):
    # The root is named, not read.
    assert claude_code.default_root() == home_folder / ".claude" / "projects"
    assert not (home_folder / ".claude").exists()


# Listing a harness's sessions.


def test_list_sessions_lists_every_session_file_with_its_size(tmp_path, project):
    root = tmp_path / "root"
    first = write_session(
        root / "-folder-one" / (STORY_ID + ".jsonl"), lines_of(STORY_SESSION, project)
    )
    second = write_session(
        root / "-folder-two" / (EXCLUDED_ID + ".jsonl"), lines_of(EXCLUDED_SESSION, project)
    )
    refs = sorted(claude_code.list_sessions(root))
    assert refs == sorted(
        [
            SessionRef(STORY_ID, str(first), first.stat().st_size),
            SessionRef(EXCLUDED_ID, str(second), second.stat().st_size),
        ]
    )


def test_list_sessions_opens_no_file(tmp_path):
    root = tmp_path / "root"
    write_session(root / "-folder-one" / "not-json.jsonl", ["this is not JSON", "{"])
    (root / "-folder-two").mkdir(parents=True)
    (root / "-folder-two" / "also-not-json.jsonl").write_bytes(b"\x00\xff plain bytes")
    refs = sorted(claude_code.list_sessions(root))
    assert [(ref.harness_session_id, ref.size) for ref in refs] == [
        ("also-not-json", 14),
        ("not-json", len("this is not JSON\n{\n")),
    ]


def test_list_sessions_of_a_missing_root_is_empty(tmp_path):
    assert claude_code.list_sessions(tmp_path / "no_root") == []


# Reading a session.


def test_parse_transcript_reads_the_bytes_as_read_session_reads_the_file(story):
    assert claude_code.parse_transcript(story.read_bytes()) == claude_code.read_session(story)
    assert claude_code.read_session(str(story)) == claude_code.read_session(story)


def test_a_broken_record_read_from_a_file_names_the_file_and_the_line(tmp_path, project):
    lines = lines_of(STORY_SESSION, project)
    path = write_session(tmp_path / "broken.jsonl", lines[:-1] + [lines[-1][:40]])
    with pytest.raises(ValueError, match=r"line 15\b") as refused:
        claude_code.parse_transcript(path.read_bytes())
    assert str(path) not in str(refused.value)
    with pytest.raises(ValueError, match=r"line 15\b") as refused:
        claude_code.read_session(path)
    assert str(path) in str(refused.value)


def test_the_story_messages_run_from_the_request_to_the_closing_text(story, project):
    session = claude_code.read_session(story)
    records = records_of(lines_of(STORY_SESSION, project))
    request = records[0]["message"]["content"]
    closing = records[-1]["message"]["content"][0]["text"]
    assert session.messages[0] == ("user", request)
    assert session.messages[-1] == ("assistant", closing)
    assert session.messages[1:-1] == [("assistant", text) for text in STORY_TEXTS]
    results = tool_results(lines_of(STORY_SESSION, project))
    assert results
    for role, text in session.messages:
        assert role in ("user", "assistant")
        assert text not in results.values()


def test_the_parts_follow_the_transcript_with_each_call_and_its_result(story, project):
    lines = lines_of(STORY_SESSION, project)
    session = claude_code.read_session(story)
    results = tool_results(lines)

    expected = [("user", records_of(lines)[0]["message"]["content"], None, None)]
    for text, call_id in zip(STORY_TEXTS, STORY_CALLS):
        expected.append(("assistant", text, None, None))
        expected.append(("assistant", None, call_id, results[call_id]))
    expected.append(("assistant", records_of(lines)[-1]["message"]["content"][0]["text"], None, None))

    got = [
        (
            part.role,
            part.text,
            None if part.tool_call is None else part.tool_call.record_id,
            part.result,
        )
        for part in session.parts
    ]
    assert got == expected
    # The tool call parts are the session's tool calls, in the same order.
    assert [part.tool_call for part in session.parts if part.tool_call] == session.tool_calls


def test_thinking_system_records_and_a_call_with_no_result_yet_leave_no_text(tmp_path, project):
    records = records_of(lines_of(STORY_SESSION, project))
    # A thinking part before the first text, written here for the test.
    records[1]["message"]["content"].insert(
        0, {"type": "thinking", "thinking": "The scholar wants two findings.", "signature": "x"}
    )
    # The session so far ends with the first call, before its result.
    path = write_session(tmp_path / "running.jsonl", [json.dumps(r) for r in records[:2]])
    session = claude_code.read_session(path)
    assert [(part.role, part.text) for part in session.parts] == [
        ("user", records[0]["message"]["content"]),
        ("assistant", STORY_TEXTS[0]),
        ("assistant", None),
    ]
    assert session.parts[-1].tool_call.record_id == STORY_CALLS[0]
    assert session.parts[-1].result is None
    assert [text for _, text in session.messages] == [
        records[0]["message"]["content"],
        STORY_TEXTS[0],
    ]


def test_a_result_given_as_text_parts_is_read_as_their_text(tmp_path, project):
    records = records_of(lines_of(STORY_SESSION, project))
    records[2]["message"]["content"][0]["content"] = [
        {"type": "text", "text": "first line"},
        {"type": "text", "text": "second line"},
    ]
    path = write_session(tmp_path / "parts.jsonl", [json.dumps(r) for r in records])
    session = claude_code.read_session(path)
    first_call = [part for part in session.parts if part.tool_call][0]
    assert first_call.result == "first line\nsecond line"


def test_a_typed_prompt_given_as_text_parts_is_a_user_message(tmp_path, project):
    records = records_of(lines_of(STORY_SESSION, project))
    request = records[0]["message"]["content"]
    records[0]["message"]["content"] = [{"type": "text", "text": request}]
    path = write_session(tmp_path / "prompt_parts.jsonl", [json.dumps(r) for r in records])
    session = claude_code.read_session(path)
    assert session.messages[0] == ("user", request)
    assert session.parts[0].role == "user" and session.parts[0].text == request


# Text in a user record that the scholar did not type is a meta part. Claude
# Code writes notices, summaries, skill bodies, and command output as user
# records, and marks them as the tests below do.


def test_a_prompt_whose_origin_is_human_is_a_user_message(tmp_path, project):
    records = records_of(lines_of(STORY_SESSION, project))
    records[0]["origin"] = {"kind": "human"}
    records[0]["promptSource"] = "typed"
    path = write_session(tmp_path / "human.jsonl", [json.dumps(r) for r in records])
    session = claude_code.read_session(path)
    assert session.parts[0].role == "user"
    assert session.messages[0] == ("user", records[0]["message"]["content"])


NOT_TYPED = {
    "a task notice": ({"origin": {"kind": "task-notification"}}, "<task-notification>\nA report.</task-notification>"),
    "an origin other than a person": ({"origin": {"kind": "coordinator"}}, "Carry on with step two."),
    "a meta record": ({"isMeta": True}, "Base directory for this skill: a skill's own text."),
    "a compaction summary": ({"isCompactSummary": True}, "This session is being continued from a previous conversation."),
    "a notice with no origin": ({}, "<task-notification>\nA report.</task-notification>"),
    "a summary with no flag": ({}, "This session is being continued from a previous conversation that ran out of context."),
    "command output": ({}, "<local-command-stdout>Set model</local-command-stdout>"),
    "a command": ({}, "<command-name>/clear</command-name>"),
    "a reminder": ({}, "<system-reminder>A note.</system-reminder>"),
    "a system notice": ({}, "[SYSTEM NOTIFICATION - NOT USER INPUT] A task ended."),
    "an interruption": ({}, "[Request interrupted by user]"),
}


@pytest.mark.parametrize("fields, text", list(NOT_TYPED.values()), ids=list(NOT_TYPED))
def test_text_the_scholar_did_not_type_is_a_meta_part(tmp_path, project, fields, text):
    records = records_of(lines_of(STORY_SESSION, project))
    records[0].update(fields)
    records[0]["message"]["content"] = text
    path = write_session(tmp_path / "meta.jsonl", [json.dumps(r) for r in records])
    session = claude_code.read_session(path)
    assert (session.parts[0].role, session.parts[0].text) == ("meta", text)
    assert session.messages[0] == ("meta", text)
    # Only the record's text changes role. Its tool results still go to their calls.
    assert [part.role for part in session.parts[1:]] == [
        part.role for part in claude_code.read_session(write_session(tmp_path / "plain.jsonl", lines_of(STORY_SESSION, project))).parts[1:]
    ]


def test_a_meta_record_given_as_text_parts_is_a_meta_part(tmp_path, project):
    records = records_of(lines_of(STORY_SESSION, project))
    records[0]["isMeta"] = True
    records[0]["message"]["content"] = [{"type": "text", "text": "[Image: original 2540x1080]"}]
    path = write_session(tmp_path / "meta_parts.jsonl", [json.dumps(r) for r in records])
    session = claude_code.read_session(path)
    assert (session.parts[0].role, session.parts[0].text) == ("meta", "[Image: original 2540x1080]")


# Capture for any registered harness.


def test_capture_session_stores_the_same_rows_as_capture_file(tmp_path, story, project):
    settings = settings_for(project / "excluded_folder")
    by_file = open_store(tmp_path / "by_file")
    by_session = open_store(tmp_path / "by_session")
    try:
        first = capture_file(by_file, story, settings)
        second = capture_session(by_session, "claude_code", str(story), settings)
        assert first == second == Summary(str(story), STORY_ID, False, 1, 6, 1)
        assert without_ids(by_file.db) == without_ids(by_session.db)
        rows = without_ids(by_session.db)
        assert [row["origin"] for table in TABLES for row in rows[table]] == [
            "claude_code adapter"
        ] * 8
        assert {row["method"] for table in TABLES for row in rows[table]} == {
            "claude_code adapter version {}, mechanical tagging version {}".format(
                claude_code.VERSION, mechanical.VERSION
            )
        }
    finally:
        by_file.db.close()
        by_session.db.close()


def stand_in_adapter(name):
    """A second harness for the test, which reads Claude Code's form under another name."""
    module = types.ModuleType(name)
    module.NAME = name
    module.AI = True
    module.VERSION = 7
    module.default_root = lambda: Path("/nowhere")
    module.list_sessions = lambda root: []
    module.parse_transcript = claude_code.parse_transcript
    module.read_session = claude_code.read_session
    return module


def test_capture_session_names_the_harness_in_every_row(audit, story, project, monkeypatch):
    monkeypatch.setitem(ADAPTERS, "stand_in", stand_in_adapter("stand_in"))
    summary = capture_session(audit, "stand_in", story, settings_for())
    assert summary.events == 6
    for table in TABLES:
        for row in stored_rows(audit.db, table):
            assert row["origin"] == "stand_in adapter"
            assert row["method"] == "stand_in adapter version 7, mechanical tagging version {}".format(
                mechanical.VERSION
            )
    (session,) = current(audit, "sessions")
    assert session["harness"] == "stand_in"
    assert current_session(audit, "stand_in", STORY_ID)["id"] == session["id"]
    assert current_session(audit, "claude_code", STORY_ID) is None
    # The stored session reads back through its own harness's adapter.
    assert read_stored(audit, session).tool_calls == claude_code.read_session(story).tool_calls


def test_capture_session_refuses_an_unknown_harness(audit, story):
    with pytest.raises(ValueError, match="claude_code"):
        capture_session(audit, "forgecode_v0", story, settings_for())
    assert all(stored_rows(audit.db, table) == [] for table in TABLES)


def test_capture_session_skips_a_session_run_in_an_excluded_folder(tmp_path, audit, project):
    path = write_session(tmp_path / "excluded.jsonl", lines_of(EXCLUDED_SESSION, project))
    summary = capture_session(audit, "claude_code", path, settings_for(project / "excluded_folder"))
    assert summary == Summary(str(path), None, True, 0, 0, 0)
    assert all(stored_rows(audit.db, table) == [] for table in TABLES)


# Reading what the store holds.


def test_read_stored_gives_back_the_tool_calls_read_from_the_file(audit, story, project):
    capture_session(audit, "claude_code", story, settings_for())
    row = current_session(audit, "claude_code", STORY_ID)
    stored = read_stored(audit, row)
    from_file = claude_code.read_session(story)
    assert stored.tool_calls == from_file.tool_calls
    assert [call.record_id for call in stored.tool_calls] == STORY_CALLS
    assert stored == from_file


def test_a_grown_session_gives_every_event_in_ordinal_order(tmp_path, audit, project):
    lines = lines_of(STORY_SESSION, project)
    path = tmp_path / "story_session.jsonl"
    settings = settings_for()
    for count in (4, 8, 14, len(lines)):
        write_session(path, lines[:count])
        capture_session(audit, "claude_code", path, settings)
    # The session row was superseded as the file grew.
    assert len(stored_rows(audit.db, "sessions")) == 4
    row = current_session(audit, "claude_code", STORY_ID)
    assert row["supersedes"] is not None

    events = session_events(audit, row)
    assert [event["id"] for event in events] == STORY_CALLS
    assert [event["ordinal"] for event in events] == [1, 2, 3, 4, 5, 6]
    # The events were written under three of the session's four rows.
    assert len({event["session_row_id"] for event in events}) == 3

    transcript, data = latest_transcript(audit, row)
    assert data == path.read_bytes()
    assert transcript["byte_size"] == len(data)
    assert read_stored(audit, row).tool_calls == claude_code.read_session(path).tool_calls


def test_session_events_gives_the_current_version_of_an_event(audit, story):
    capture_session(audit, "claude_code", story, settings_for())
    row = current_session(audit, "claude_code", STORY_ID)
    edit = current(audit, "events", id=STORY_CALLS[1])[0]
    provenance = {"session": STORY_ID, "origin": "test", "method": "test", "reason": "test"}
    newer = supersede(audit, "events", edit["id"], {"kind": "decision"}, provenance)
    events = session_events(audit, row)
    assert [event["id"] for event in events] == [STORY_CALLS[0], newer] + STORY_CALLS[2:]
    assert events[1]["kind"] == "decision"


def test_session_events_keeps_to_its_own_session(tmp_path, audit, story, project):
    other = write_session(tmp_path / "other.jsonl", lines_of(EXCLUDED_SESSION, project))
    capture_session(audit, "claude_code", story, settings_for())
    capture_session(audit, "claude_code", other, settings_for())
    story_row = current_session(audit, "claude_code", STORY_ID)
    other_row = current_session(audit, "claude_code", EXCLUDED_ID)
    assert [event["id"] for event in session_events(audit, story_row)] == STORY_CALLS
    assert [event["id"] for event in session_events(audit, other_row)] == [
        "toolu_excluded_01_read"
    ]
    assert latest_transcript(audit, other_row)[1] == other.read_bytes()


def test_a_session_with_no_stored_transcript_is_named(audit):
    provenance = {"session": STORY_ID, "origin": "test", "method": "test", "reason": "test"}
    from audit_layer.store import add_row

    add_row(
        audit,
        "sessions",
        {"harness": "claude_code", "harness_session_id": STORY_ID, "tools": []},
        provenance,
    )
    row = current_session(audit, "claude_code", STORY_ID)
    with pytest.raises(ValueError, match=STORY_ID):
        latest_transcript(audit, row)


# The capture command.


def test_the_capture_command_takes_any_registered_harness(
    tmp_path, story, project, capsys, monkeypatch
):
    home = tmp_path / "audit_home"
    assert main(["init", "--home", str(home)]) == 0
    monkeypatch.setitem(ADAPTERS, "stand_in", stand_in_adapter("stand_in"))
    capsys.readouterr()
    assert main(["capture", "--home", str(home), "--harness", "stand_in", str(story)]) == 0
    assert "6 events" in capsys.readouterr().out
    store = open_store(home)
    try:
        assert [row["harness"] for row in current(store, "sessions")] == ["stand_in"]
    finally:
        store.db.close()


def test_the_capture_command_refuses_an_unknown_harness_and_names_the_known_ones(
    tmp_path, story, capsys
):
    home = tmp_path / "audit_home"
    assert main(["init", "--home", str(home)]) == 0
    capsys.readouterr()
    with pytest.raises(SystemExit) as stop:
        main(["capture", "--home", str(home), "--harness", "forgecode_v0", str(story)])
    assert stop.value.code == 2
    assert "claude_code" in capsys.readouterr().err

