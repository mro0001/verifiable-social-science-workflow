"""Tests for subagent conversations (Track A, Step A3).

The audit layer records every AI session transcript and tool call (proposal
Approach paragraph 5), and observability adds the work of subagents, which
must first be recorded (appendix A2.6). Claude Code keeps a subagent's
conversation in its own file, <session id>/subagents/agent-<agent id>.jsonl,
in the folder beside the main session file. Each subagent conversation is a
session of its own, with the id <parent session id>/agent-<agent id> (plan
choice 5), its own events, and its own transcript.

The main session is the test story's synthetic Claude Code session, and the
subagent conversation is fixtures/claude_code/subagent.jsonl, written from
scratch with the keys the harness uses. Their folder token {{PROJECT}} is
replaced with a temporary folder. No real session file is read, no default
root is read, nothing here calls a model or the network, and every test runs
with its home folder inside a temporary folder. Run from the repository root
with python3 -m pytest -q audit_layer/tests.
"""
import hashlib
import json
import os
import stat
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from audit_layer.capture import (  # noqa: E402
    SessionRef,
    SubagentsNotCaptured,
    Summary,
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
    subagents,
)
from audit_layer.store import add_row, current, open_store  # noqa: E402

SESSIONS = ROOT / "examples" / "test_story" / "sessions" / "claude_code"
STORY_SESSION = SESSIONS / "story_session.jsonl"
EXCLUDED_SESSION = SESSIONS / "excluded_session.jsonl"
SUBAGENT = Path(__file__).parent / "fixtures" / "claude_code" / "subagent.jsonl"
TOKEN = "{{PROJECT}}"

STORY_ID = "5f3c0413-2a7d-4b9e-8c61-a0d4e7b2c913"
EXCLUDED_ID = "9b1e0414-6c3a-4f2d-b8e5-71d2a9c4f086"
AGENT_ID = "a7c41e2b9d0f3856"
SUBAGENT_ID = STORY_ID + "/agent-" + AGENT_ID

TABLES = ("sessions", "events", "transcripts")
STORY_CALLS = [
    "toolu_story_01_read",
    "toolu_story_02_edit",
    "toolu_story_03_edit",
    "toolu_story_04_write",
    "toolu_story_05_bash",
    "toolu_story_06_bash",
]
SUBAGENT_CALLS = ["toolu_agent_01_read", "toolu_agent_02_write", "toolu_agent_03_grep"]

META = b'{"agentType": "synthetic", "description": "a meta file the adapter never reads"}'


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


class Placed:
    """The story session and its subagent conversation, laid out as Claude Code keeps them."""

    def __init__(self, root, project):
        self.root = root
        self.folder = root / "-encoded-project-folder"
        self.main = write_session(self.folder / (STORY_ID + ".jsonl"), lines_of(STORY_SESSION, project))
        self.subagents = self.folder / STORY_ID / "subagents"
        self.subagent = write_session(
            self.subagents / ("agent-" + AGENT_ID + ".jsonl"), lines_of(SUBAGENT, project)
        )
        self.meta = self.subagents / ("agent-" + AGENT_ID + ".meta.json")
        self.meta.write_bytes(META)


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
def placed(tmp_path, project):
    return Placed(tmp_path / "root", project)


@pytest.fixture
def audit(tmp_path):
    store = open_store(tmp_path / "audit_home")
    yield store
    store.db.close()


# The fixture.


def test_the_fixture_uses_the_keys_the_harness_uses(project):
    records = records_of(lines_of(SUBAGENT, project))
    assert {record["type"] for record in records} == {"user", "assistant", "attachment"}
    assert [record["type"] for record in records].count("attachment") == 1
    for record in records:
        assert record["sessionId"] == STORY_ID
        assert record["agentId"] == AGENT_ID
        assert record["isSidechain"] is True
        assert record["cwd"] == str(project)
        for key in ("timestamp", "uuid", "parentUuid"):
            assert key in record
    kinds = set()
    for record in records:
        content = (record.get("message") or {}).get("content")
        for part in content if isinstance(content, list) else []:
            kinds.add(part["type"])
    assert kinds == {"text", "tool_use", "tool_result"}


def test_a_subagent_conversation_is_started_by_an_agent_and_the_main_session_is_not(placed):
    # A subagent's user text is the prompt the AI that started it wrote.
    assert claude_code.read_session(placed.subagent).started_by_agent is True
    assert claude_code.read_session(placed.main).started_by_agent is False


# Listing.


def test_listing_finds_the_main_session_and_its_subagent(placed):
    refs = sorted(claude_code.list_sessions(placed.root))
    assert refs == sorted(
        [
            SessionRef(STORY_ID, str(placed.main), placed.main.stat().st_size),
            SessionRef(SUBAGENT_ID, str(placed.subagent), placed.subagent.stat().st_size),
        ]
    )


def test_listing_opens_no_subagent_file_and_passes_over_the_meta_file(placed):
    placed.subagent.write_bytes(b"\x00 not JSON at all")
    placed.meta.chmod(0)
    try:
        refs = claude_code.list_sessions(placed.root)
    finally:
        placed.meta.chmod(stat.S_IRUSR | stat.S_IWUSR)
    assert sorted(ref.harness_session_id for ref in refs) == [STORY_ID, SUBAGENT_ID]
    assert all(not ref.location.endswith(".meta.json") for ref in refs)


def test_listing_finds_a_subagent_whose_main_file_is_not_there(placed):
    placed.main.unlink()
    refs = claude_code.list_sessions(placed.root)
    assert [ref.harness_session_id for ref in refs] == [SUBAGENT_ID]


def test_listing_passes_over_files_that_are_not_subagent_files(placed, project):
    write_session(placed.subagents / "notes.jsonl", lines_of(SUBAGENT, project))
    write_session(placed.folder / STORY_ID / "agent-x.jsonl", lines_of(SUBAGENT, project))
    refs = claude_code.list_sessions(placed.root)
    assert sorted(ref.harness_session_id for ref in refs) == [STORY_ID, SUBAGENT_ID]


# Reading a subagent conversation.


def test_a_subagent_file_reads_as_its_own_session(placed, project):
    session = claude_code.read_session(placed.subagent)
    records = records_of(lines_of(SUBAGENT, project))
    timed = [record for record in records if record["type"] != "attachment"]
    assert session.session_id == SUBAGENT_ID
    assert session.cwd == str(project)
    assert session.started_at == timed[0]["timestamp"]
    assert session.ended_at == timed[-1]["timestamp"]
    assert session.transcript == placed.subagent.read_bytes()
    assert [call.record_id for call in session.tool_calls] == SUBAGENT_CALLS
    assert [call.name for call in session.tool_calls] == ["Read", "Write", "Grep"]
    assert session.tool_calls[1].input["file_path"] == str(project / "notes" / "reading_list.md")
    assert "[@healy2020]" in session.tool_calls[1].input["content"]
    assert session.tool_calls[2].input["pattern"] == "@nakamura2020"
    assert session.messages[0] == ("user", records[0]["message"]["content"])
    assert session.messages[-1] == ("assistant", records[-1]["message"]["content"][0]["text"])
    assert all(part.result is not None for part in session.parts if part.tool_call)


def test_the_attachment_record_is_skipped_and_does_not_stop_parsing(tmp_path, project):
    records = records_of(lines_of(SUBAGENT, project))
    (attachment,) = [record for record in records if record["type"] == "attachment"]
    others = [record for record in records if record["type"] != "attachment"]
    # The attachment first, with the earliest time, and again last, with the latest.
    first = dict(attachment, timestamp="2026-10-21T13:00:00.000Z")
    last = dict(attachment, timestamp="2026-10-21T23:00:00.000Z", uuid="later")
    path = write_session(
        tmp_path / "with_attachments.jsonl", [json.dumps(r) for r in [first] + others + [last]]
    )
    session = claude_code.read_session(path)
    plain = claude_code.read_session(
        write_session(tmp_path / "plain.jsonl", [json.dumps(r) for r in others])
    )
    assert session.started_at == others[0]["timestamp"]
    assert session.ended_at == others[-1]["timestamp"]
    assert session._replace(transcript=b"") == plain._replace(transcript=b"")


def test_a_session_of_attachment_records_only_gives_no_session_id(tmp_path, project):
    records = records_of(lines_of(SUBAGENT, project))
    (attachment,) = [record for record in records if record["type"] == "attachment"]
    path = write_session(tmp_path / "attachment_only.jsonl", [json.dumps(attachment)])
    with pytest.raises(ValueError, match="session id"):
        claude_code.read_session(path)


def test_a_main_session_keeps_its_own_id(placed):
    session = claude_code.read_session(placed.main)
    assert session.session_id == STORY_ID


def test_an_agent_id_outside_a_sidechain_does_not_rename_the_session(tmp_path, project):
    records = records_of(lines_of(STORY_SESSION, project))
    for record in records:
        record["agentId"] = AGENT_ID
    path = write_session(tmp_path / "main.jsonl", [json.dumps(r) for r in records])
    assert claude_code.read_session(path).session_id == STORY_ID


# Capture.


def test_capturing_the_main_file_stores_both_sessions(audit, placed):
    summary = capture_session(audit, "claude_code", placed.main, settings_for())
    assert summary.session_id == STORY_ID
    assert (summary.sessions, summary.events, summary.transcripts) == (1, 6, 1)
    assert summary.subagents == (
        Summary(str(placed.subagent), SUBAGENT_ID, False, 1, 3, 1),
    )

    sessions = current(audit, "sessions")
    assert [row["harness_session_id"] for row in sessions] == [STORY_ID, SUBAGENT_ID]
    story = current_session(audit, "claude_code", STORY_ID)
    agent = current_session(audit, "claude_code", SUBAGENT_ID)
    assert [event["id"] for event in session_events(audit, story)] == STORY_CALLS
    assert [event["id"] for event in session_events(audit, agent)] == SUBAGENT_CALLS
    assert latest_transcript(audit, story)[1] == placed.main.read_bytes()
    assert latest_transcript(audit, agent)[1] == placed.subagent.read_bytes()
    assert agent["tools"] == ["Read", "Write", "Grep"]
    assert agent["project"] == story["project"]
    assert agent["started_at"] == "2026-10-21T14:03:00.120Z"
    assert agent["ended_at"] == "2026-10-21T14:03:15.761Z"
    # Every row of the subagent carries its own id as its session.
    for table in TABLES:
        for row in stored_rows(audit.db, table):
            if row["session"] == SUBAGENT_ID:
                assert row["origin"] == "claude_code adapter"
    assert {row["session"] for row in stored_rows(audit.db, "events")} == {STORY_ID, SUBAGENT_ID}

    assert [row["id"] for row in subagents(audit, story)] == [agent["id"]]
    assert subagents(audit, agent) == []
    assert read_stored(audit, agent).tool_calls == claude_code.read_session(placed.subagent).tool_calls


def test_capture_file_captures_the_subagents_too(audit, placed):
    summary = capture_file(audit, placed.main, settings_for())
    assert [sub.session_id for sub in summary.subagents] == [SUBAGENT_ID]
    assert len(current(audit, "sessions")) == 2


def test_a_second_capture_adds_nothing(audit, placed):
    capture_session(audit, "claude_code", placed.main, settings_for())
    before = {table: stored_rows(audit.db, table) for table in TABLES}
    again = capture_session(audit, "claude_code", placed.main, settings_for())
    assert (again.sessions, again.events, again.transcripts) == (0, 0, 0)
    assert again.subagents == (Summary(str(placed.subagent), SUBAGENT_ID, False, 0, 0, 0),)
    assert {table: stored_rows(audit.db, table) for table in TABLES} == before


def test_a_grown_subagent_adds_only_its_new_events(audit, placed, project):
    lines = lines_of(SUBAGENT, project)
    write_session(placed.subagent, lines[:4])
    first = capture_session(audit, "claude_code", placed.main, settings_for())
    assert first.subagents[0].events == 1
    write_session(placed.subagent, lines)
    second = capture_session(audit, "claude_code", placed.main, settings_for())
    assert (second.sessions, second.events, second.transcripts) == (0, 0, 0)
    assert second.subagents[0][3:6] == (1, 2, 1)
    story = current_session(audit, "claude_code", STORY_ID)
    agent = current_session(audit, "claude_code", SUBAGENT_ID)
    assert [event["id"] for event in session_events(audit, agent)] == SUBAGENT_CALLS
    # The superseded subagent row is not named, only its current one.
    assert [row["id"] for row in subagents(audit, story)] == [agent["id"]]


def test_a_subagent_run_in_an_excluded_folder_stores_nothing_while_its_parent_is_stored(
    audit, placed, project
):
    lines = [
        line.replace(json.dumps(str(project))[1:-1], json.dumps(str(project / "excluded_folder"))[1:-1])
        for line in lines_of(SUBAGENT, project)
    ]
    write_session(placed.subagent, lines)
    summary = capture_session(
        audit, "claude_code", placed.main, settings_for(project / "excluded_folder")
    )
    assert (summary.sessions, summary.events, summary.transcripts) == (1, 6, 1)
    assert summary.subagents == (Summary(str(placed.subagent), None, True, 0, 0, 0),)
    assert [row["harness_session_id"] for row in current(audit, "sessions")] == [STORY_ID]
    assert {row["session"] for table in TABLES for row in stored_rows(audit.db, table)} == {STORY_ID}
    story = current_session(audit, "claude_code", STORY_ID)
    assert subagents(audit, story) == []


def test_a_parent_and_subagent_both_run_in_an_excluded_folder_store_nothing(tmp_path, audit, project):
    excluded = project / "excluded_folder"
    folder = tmp_path / "root" / "-encoded-excluded-folder"
    main_file = write_session(folder / (EXCLUDED_ID + ".jsonl"), lines_of(EXCLUDED_SESSION, project))
    lines = [
        line.replace(json.dumps(str(project))[1:-1], json.dumps(str(excluded))[1:-1])
        for line in lines_of(SUBAGENT, project)
    ]
    write_session(folder / EXCLUDED_ID / "subagents" / ("agent-" + AGENT_ID + ".jsonl"), lines)
    summary = capture_session(audit, "claude_code", main_file, settings_for(excluded))
    assert summary.excluded and summary.subagents[0].excluded
    assert all(stored_rows(audit.db, table) == [] for table in TABLES)


def test_the_meta_file_is_neither_read_nor_stored(audit, placed):
    placed.meta.chmod(0)
    try:
        capture_session(audit, "claude_code", placed.main, settings_for())
    finally:
        placed.meta.chmod(stat.S_IRUSR | stat.S_IWUSR)
    held = sorted(os.listdir(str(audit.files)))
    assert hashlib.sha256(META).hexdigest() not in held
    assert held == sorted(
        [
            hashlib.sha256(placed.main.read_bytes()).hexdigest(),
            hashlib.sha256(placed.subagent.read_bytes()).hexdigest(),
        ]
    )


def test_a_main_file_with_no_subagent_folder_captures_alone(tmp_path, audit, project):
    path = write_session(tmp_path / (STORY_ID + ".jsonl"), lines_of(STORY_SESSION, project))
    summary = capture_session(audit, "claude_code", path, settings_for())
    assert summary == Summary(str(path), STORY_ID, False, 1, 6, 1)
    assert summary.subagents == ()


def test_a_subagent_file_can_be_captured_on_its_own(audit, placed):
    summary = capture_session(audit, "claude_code", placed.subagent, settings_for())
    assert summary == Summary(str(placed.subagent), SUBAGENT_ID, False, 1, 3, 1)
    assert [row["harness_session_id"] for row in current(audit, "sessions")] == [SUBAGENT_ID]


# The subagents query.


def test_subagents_names_only_the_parents_own_agents(audit, placed):
    capture_session(audit, "claude_code", placed.main, settings_for())
    provenance = {"session": "test", "origin": "test", "method": "test", "reason": "test"}
    for harness, session_id in [
        ("claude_code", STORY_ID + "/agent-"),
        ("claude_code", STORY_ID + "x/agent-" + AGENT_ID),
        ("claude_code", STORY_ID + "/agent-" + AGENT_ID + "/agent-b2"),
        ("claude_code", STORY_ID + "/other-" + AGENT_ID),
        ("forgecode", SUBAGENT_ID),
    ]:
        add_row(
            audit,
            "sessions",
            {"harness": harness, "harness_session_id": session_id, "tools": []},
            provenance,
        )
    second = STORY_ID + "/agent-b2c3d4"
    add_row(
        audit,
        "sessions",
        {"harness": "claude_code", "harness_session_id": second, "tools": []},
        provenance,
    )
    story = current_session(audit, "claude_code", STORY_ID)
    assert [row["harness_session_id"] for row in subagents(audit, story)] == [SUBAGENT_ID, second]


# A subagent file that cannot be read.

BROKEN_ID = STORY_ID + "/agent-0000broken"


def place_broken(placed):
    """A subagent file that cannot be read, sorting before the good one."""
    path = placed.subagents / "agent-0000broken.jsonl"
    path.write_bytes(b"this line is not JSON\n")
    return path


def test_a_broken_subagent_file_does_not_stop_the_good_one(audit, placed):
    broken = place_broken(placed)
    with pytest.raises(SubagentsNotCaptured) as caught:
        capture_session(audit, "claude_code", placed.main, settings_for())
    error = caught.value
    assert error.failed == (BROKEN_ID,)
    assert error.summary.session_id == STORY_ID
    assert (error.summary.sessions, error.summary.events, error.summary.transcripts) == (1, 6, 1)
    assert error.summary.subagents == (
        Summary(str(placed.subagent), SUBAGENT_ID, False, 1, 3, 1),
    )
    sessions = current(audit, "sessions")
    assert [row["harness_session_id"] for row in sessions] == [STORY_ID, SUBAGENT_ID]
    message = str(error)
    assert STORY_ID in message and "stored" in message and BROKEN_ID in message
    assert str(broken) not in message and str(placed.folder) not in message


def test_a_broken_subagent_file_is_still_a_value_error(audit, placed):
    place_broken(placed)
    with pytest.raises(ValueError):
        capture_session(audit, "claude_code", placed.main, settings_for())


def test_a_capture_after_the_broken_file_is_mended_stores_it(audit, placed, project):
    broken = place_broken(placed)
    with pytest.raises(SubagentsNotCaptured):
        capture_session(audit, "claude_code", placed.main, settings_for())
    lines = [
        line.replace(AGENT_ID, "0000broken") for line in lines_of(SUBAGENT, project)
    ]
    write_session(broken, [line.replace("toolu_agent_", "toolu_mended_") for line in lines])
    summary = capture_session(audit, "claude_code", placed.main, settings_for())
    assert [found.session_id for found in summary.subagents] == [BROKEN_ID, SUBAGENT_ID]
    assert [(found.sessions, found.events) for found in summary.subagents] == [(1, 3), (0, 0)]


# The capture command.


def test_the_capture_command_names_each_subagent_by_its_id(tmp_path, placed, capsys):
    home = tmp_path / "audit_home"
    assert main(["init", "--home", str(home)]) == 0
    capsys.readouterr()
    assert main(["capture", "--home", str(home), "--harness", "claude_code", str(placed.main)]) == 0
    out = capsys.readouterr().out
    lines = out.strip().split("\n")
    assert len(lines) == 2
    assert "6 events" in lines[0]
    assert SUBAGENT_ID in lines[1] and "3 events" in lines[1]
    assert str(placed.subagent) not in out
    assert main(["capture", "--home", str(home), "--harness", "claude_code", str(placed.main)]) == 0
    again = capsys.readouterr().out.strip().split("\n")
    assert SUBAGENT_ID in again[1] and "nothing new" in again[1]


def test_the_capture_command_says_when_a_subagent_ran_in_an_excluded_folder(
    tmp_path, placed, project, capsys
):
    home = tmp_path / "audit_home"
    assert main(["init", "--home", str(home)]) == 0
    excluded = project / "excluded_folder"
    (home / "settings.yaml").write_text(
        "excluded_folders:\n  - " + json.dumps(str(excluded)) + "\n", encoding="utf-8"
    )
    lines = [
        line.replace(json.dumps(str(project))[1:-1], json.dumps(str(excluded))[1:-1])
        for line in lines_of(SUBAGENT, project)
    ]
    write_session(placed.subagent, lines)
    capsys.readouterr()
    assert main(["capture", "--home", str(home), "--harness", "claude_code", str(placed.main)]) == 0
    out = capsys.readouterr().out.strip().split("\n")
    assert len(out) == 2
    assert "excluded folder" in out[1] and "nothing was stored" in out[1]
    assert str(placed.subagent) not in out[1]


def test_the_capture_command_reports_the_stored_sessions_and_names_a_broken_subagent_by_its_id(
    tmp_path, placed, capsys
):
    home = tmp_path / "audit_home"
    assert main(["init", "--home", str(home)]) == 0
    broken = place_broken(placed)
    capsys.readouterr()
    assert main(["capture", "--home", str(home), "--harness", "claude_code", str(placed.main)]) == 1
    captured = capsys.readouterr()
    out = captured.out.strip().split("\n")
    assert len(out) == 2
    assert STORY_ID in out[0] and "6 events" in out[0]
    assert SUBAGENT_ID in out[1] and "3 events" in out[1]
    assert "could not capture " + str(placed.main) not in captured.err
    assert BROKEN_ID in captured.err and "stored" in captured.err
    assert str(broken) not in captured.err and str(placed.folder) not in captured.err
