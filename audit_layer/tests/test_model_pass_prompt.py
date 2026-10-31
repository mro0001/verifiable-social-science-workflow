"""Tests for the model pass's fields and its prompt (Track A, Step A9).

Proposal Approach paragraph 5 has the audit layer tag every AI session
transcript and tool call, and Figure 1 puts the metadata in the audit layer.
Appendix Table A4 gives the model pass one AI model call per session, which
fills each session's title, gist, summary, and keywords and a rationale for
each decision, and Table A3 stamps each with the pass that produced it.
Tagging fills the schema's fields and adds none, and the derived layer is
regenerable from the kept transcript (spec 0.11), so a session row that
supersedes another because its transcript grew starts with the four fields
empty (plan choice 13). The prompt sends the action log and the user and
assistant text, cut to 60,000 characters (plan choice 9). The reconciliation
drops the excluded-folder guard (item 3), and due skips sessions whose
adapter lacks the AI flag.

The sessions are the test story's synthetic Claude Code session and the
synthetic subagent conversation in fixtures/claude_code. Their folder token
{{PROJECT}} is replaced with a temporary folder. No real session file is
read, nothing here calls a model or the network, and every test runs with its
home folder inside a temporary folder. Run from the repository root with
python3 -m pytest -q audit_layer/tests.
"""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import audit_layer.capture as capture  # noqa: E402
from audit_layer.capture import capture_session, read_stored  # noqa: E402
from audit_layer.queries import current_session, session_events  # noqa: E402
from audit_layer.store import StoreError, add_row, current, open_store, supersede  # noqa: E402
from audit_layer.tagging import model_pass  # noqa: E402
from audit_layer.tagging.model_pass import due, render_prompt  # noqa: E402

SESSIONS = ROOT / "examples" / "test_story" / "sessions" / "claude_code"
STORY_SESSION = SESSIONS / "story_session.jsonl"
SUBAGENT = Path(__file__).parent / "fixtures" / "claude_code" / "subagent.jsonl"
TEMPLATE = ROOT / "audit_layer" / "tagging" / "model_pass.prompt.md"
TOKEN = "{{PROJECT}}"

STORY_ID = "5f3c0413-2a7d-4b9e-8c61-a0d4e7b2c913"
AGENT_ID = "a7c41e2b9d0f3856"
SUBAGENT_ID = STORY_ID + "/agent-" + AGENT_ID

DERIVED = ("title", "gist", "summary", "keywords")

STORY_REQUEST = (
    "In manuscript.md, after my sentence on fit in the Results section, add two findings"
    " from the volunteer retention literature with their citations. Then list the sources"
    " you added in a short notes file, run the manuscript check, and commit."
)
STORY_CLOSING = (
    "I added two findings after your sentence on fit, Dumont (2014) on clear end dates and"
    " Nakamura (2020) on recognition events. Both are listed in source_notes.md, the"
    " manuscript check passes, and both files are committed."
)
# Text that appears only in the story's tool results.
TOOL_RESULT_TEXT = (
    "File created successfully at",
    "[main bea0f61]",
    "has been updated. Here's the result",
    "2 files changed, 9 insertions",
)
STORY_CHECK = (
    "python3 -m ospipe check --manuscript manuscript.md --manifest numbers.yml"
    " --tables-dir . | tail -n 3"
)
STORY_COMMIT = (
    "git add manuscript.md source_notes.md && git commit"
    ' -m "Add two findings on volunteer exit after the sentence on fit"'
)

MODEL_PASS = {
    "session": STORY_ID,
    "origin": "model pass",
    "method": "model_pass 1; model recorded:test.json",
    "reason": "tagging",
}
FILLED = {
    "title": "Add two findings on volunteer exit",
    "gist": "The scholar asked for two findings and the AI added them.",
    "summary": "A made-up summary of the story session.",
    "keywords": ["volunteer exit", "findings", "citations"],
}


def lines_of(source, project):
    text = source.read_text(encoding="utf-8")
    text = text.replace(TOKEN, json.dumps(str(project))[1:-1])
    return [line for line in text.split("\n") if line]


def write_session(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes("".join(line + "\n" for line in lines).encode("utf-8"))
    return path


def settings_for(*folders):
    return {"excluded_folders": [str(folder) for folder in folders]}


def stored_rows(db, table):
    cursor = db.execute(f"SELECT * FROM {table} ORDER BY rowid")
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def table_columns(db, table):
    return [row[1] for row in db.execute(f"PRAGMA table_info({table})")]


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
def settings(project):
    return settings_for(project / "excluded_folder")


@pytest.fixture
def audit(tmp_path):
    store = open_store(tmp_path / "audit_home")
    yield store
    store.db.close()


@pytest.fixture
def placed(tmp_path, project):
    """The story session and its subagent conversation, as Claude Code keeps them."""
    folder = tmp_path / "root" / "-encoded-project-folder"
    main = write_session(folder / (STORY_ID + ".jsonl"), lines_of(STORY_SESSION, project))
    write_session(
        folder / STORY_ID / "subagents" / ("agent-" + AGENT_ID + ".jsonl"),
        lines_of(SUBAGENT, project),
    )
    return main


@pytest.fixture
def captured(audit, placed, settings):
    """The store once the story and its subagent conversation are captured."""
    capture_session(audit, "claude_code", placed, settings)
    return audit


def story_prompt(store):
    row = current_session(store, "claude_code", STORY_ID)
    events = session_events(store, row)
    messages = read_stored(store, row).messages
    return render_prompt(row, events, messages)


# The four fields in the store.


def test_a_new_store_has_the_four_fields_on_sessions(audit):
    columns = table_columns(audit.db, "sessions")
    for name in DERIVED:
        assert name in columns


def old_sessions_schema():
    """The sessions table as a store made before this step wrote it."""
    return (
        "CREATE TABLE sessions (id TEXT PRIMARY KEY NOT NULL, harness TEXT,"
        " harness_session_id TEXT, project TEXT, started_at TEXT, ended_at TEXT, tools TEXT,"
        " created_at TEXT NOT NULL, session TEXT NOT NULL, origin TEXT NOT NULL,"
        " method TEXT NOT NULL, reason TEXT NOT NULL, supersedes TEXT)"
    )


def test_a_store_made_without_the_four_fields_has_them_once_opened(tmp_path):
    home = tmp_path / "old_home"
    home.mkdir()
    db = sqlite3.connect(str(home / "audit.sqlite"))
    db.execute(old_sessions_schema())
    db.execute(
        "INSERT INTO sessions (id, harness, harness_session_id, project, started_at, ended_at,"
        " tools, created_at, session, origin, method, reason, supersedes) VALUES"
        " ('old-row', 'claude_code', ?, '/p', 't0', 't1', '[\"Read\"]', 't2', ?, 'o', 'm',"
        " 'r', NULL)",
        (STORY_ID, STORY_ID),
    )
    db.commit()
    db.close()

    store = open_store(home)
    try:
        columns = table_columns(store.db, "sessions")
        for name in DERIVED:
            assert name in columns
        (row,) = current(store, "sessions")
        assert row["id"] == "old-row"
        assert row["tools"] == ["Read"]
        assert [row[name] for name in DERIVED] == [None, None, None, None]
        # The table takes the four fields from now on.
        new_id = supersede(store, "sessions", "old-row", FILLED, MODEL_PASS)
        (new,) = current(store, "sessions")
        assert new["id"] == new_id
        assert {name: new[name] for name in DERIVED} == FILLED
    finally:
        store.db.close()

    # Opening it again adds nothing more.
    again = open_store(home)
    try:
        assert table_columns(again.db, "sessions").count("title") == 1
    finally:
        again.db.close()


def test_keywords_are_kept_as_a_json_list(audit):
    provenance = dict(MODEL_PASS, origin="test", method="by hand", reason="test")
    row_id = add_row(audit, "sessions", {"keywords": ["a", "b", "c"]}, provenance)
    (row,) = current(audit, "sessions", id=row_id)
    assert row["keywords"] == ["a", "b", "c"]
    (stored,) = stored_rows(audit.db, "sessions")
    assert json.loads(stored["keywords"]) == ["a", "b", "c"]
    with pytest.raises(StoreError, match="keywords"):
        add_row(audit, "sessions", {"keywords": "a, b, c"}, provenance)


def test_a_first_capture_leaves_the_four_fields_empty(captured):
    row = current_session(captured, "claude_code", STORY_ID)
    assert [row[name] for name in DERIVED] == [None, None, None, None]


# A grown capture leaves the new session row's four fields empty.


def test_a_grown_capture_leaves_the_new_session_rows_four_fields_empty(
    tmp_path, audit, project, settings
):
    lines = lines_of(STORY_SESSION, project)
    path = tmp_path / "story_session.jsonl"
    write_session(path, lines[:8])
    capture_session(audit, "claude_code", path, settings)
    first = current_session(audit, "claude_code", STORY_ID)
    tagged_id = supersede(audit, "sessions", first["id"], FILLED, MODEL_PASS)

    # Capturing the same file again keeps the tagged row current.
    capture_session(audit, "claude_code", path, settings)
    assert current_session(audit, "claude_code", STORY_ID)["id"] == tagged_id

    write_session(path, lines)
    capture_session(audit, "claude_code", path, settings)
    grown = current_session(audit, "claude_code", STORY_ID)
    assert grown["supersedes"] == tagged_id
    assert [grown[name] for name in DERIVED] == [None, None, None, None]
    assert grown["ended_at"] == "2026-10-21T14:02:46.009Z"
    # The tagged row stays in the table as it was written.
    tagged = [row for row in stored_rows(audit.db, "sessions") if row["id"] == tagged_id]
    assert tagged[0]["title"] == FILLED["title"]


# The prompt.


def test_the_template_has_its_two_slots_and_names_the_five_keys():
    text = TEMPLATE.read_text(encoding="utf-8")
    assert text.count("{{ACTION_LOG}}") == 1
    assert text.count("{{CONVERSATION}}") == 1
    for key in ("title", "gist", "summary", "keywords", "decisions", "ordinal", "rationale"):
        assert f"`{key}`" in text
    # The limits of plan choice 9.
    for limit in ("80", "200", "1,200", "3 to 10"):
        assert limit in text


def test_the_story_prompt_holds_every_event_line_in_order(captured, project):
    prompt = story_prompt(captured)
    manuscript = str(project / "manuscript.md")
    notes = str(project / "source_notes.md")
    expected = [
        f"1 searched observation {manuscript}",
        f"2 edited action {manuscript}",
        f"3 edited action {manuscript}",
        f"4 wrote action {notes}",
        f"5 verified observation {STORY_CHECK}",
        f"6 committed action {STORY_COMMIT}",
    ]
    lines = prompt.split("\n")
    at = [lines.index(line) for line in expected]
    assert at == sorted(at)
    assert at == list(range(at[0], at[0] + len(expected)))


def test_the_story_prompt_holds_the_request_and_the_closing_text_and_no_tool_result(captured):
    prompt = story_prompt(captured)
    assert "user: " + STORY_REQUEST in prompt
    assert "assistant: " + STORY_CLOSING in prompt
    assert prompt.index(STORY_REQUEST) < prompt.index(STORY_CLOSING)
    for text in TOOL_RESULT_TEXT:
        assert text not in prompt
    assert "{{ACTION_LOG}}" not in prompt
    assert "{{CONVERSATION}}" not in prompt


def test_the_slots_are_filled_once_so_text_that_looks_like_a_slot_stays_as_it_is():
    row = {"harness": "claude_code", "harness_session_id": "s"}
    events = [{"ordinal": 1, "verb": "ran", "kind": "action", "object": "echo {{CONVERSATION}}"}]
    messages = [("user", "say {{ACTION_LOG}} please")]
    prompt = render_prompt(row, events, messages)
    assert "1 ran action echo {{CONVERSATION}}" in prompt
    assert "user: say {{ACTION_LOG}} please" in prompt


def test_an_event_object_on_more_than_one_line_stays_on_one_line():
    row = {"harness": "claude_code", "harness_session_id": "s"}
    events = [{"ordinal": 1, "verb": "ran", "kind": "action", "object": "echo a\necho b"}]
    prompt = render_prompt(row, events, [])
    assert "1 ran action echo a echo b" in prompt.split("\n")


def test_a_long_conversation_is_cut_to_the_limit_keeping_its_start_and_end():
    row = {"harness": "claude_code", "harness_session_id": "s"}
    start = "START OF THE CONVERSATION"
    end = "END OF THE CONVERSATION"
    middle = "THE MIDDLE OF THE CONVERSATION"
    filler = "x" * 20000
    messages = [("user", start + filler), ("assistant", filler), ("user", middle)]
    messages += [("assistant", filler + filler), ("user", filler + end)]
    whole = "\n\n".join(f"{role}: {text}" for role, text in messages)
    assert len(whole) > model_pass.LIMIT

    prompt = render_prompt(row, [], messages)
    kept_start = whole[: model_pass.LIMIT // 2]
    kept_end = whole[-(model_pass.LIMIT // 2):]
    assert kept_start + "\n" + model_pass.MIDDLE + "\n" + kept_end in prompt
    assert model_pass.MIDDLE == "[... middle of the conversation left out ...]"
    assert model_pass.LIMIT == 60000
    assert start in prompt and end in prompt
    assert middle not in prompt


def test_a_conversation_within_the_limit_is_sent_whole():
    row = {"harness": "claude_code", "harness_session_id": "s"}
    messages = [("user", "a" * 29000), ("assistant", "b" * 30000)]
    prompt = render_prompt(row, [], messages)
    assert "user: " + "a" * 29000 + "\n\nassistant: " + "b" * 30000 in prompt
    assert model_pass.MIDDLE not in prompt


# Which sessions are due.


def test_the_story_and_its_subagent_are_due_once_captured(captured):
    names = [row["harness_session_id"] for row in due(captured)]
    assert names == [STORY_ID, SUBAGENT_ID]


def test_nothing_is_due_in_an_empty_store(audit):
    assert due(audit) == []


def test_a_session_with_a_title_is_not_due(captured):
    row = current_session(captured, "claude_code", STORY_ID)
    supersede(captured, "sessions", row["id"], FILLED, MODEL_PASS)
    assert [row["harness_session_id"] for row in due(captured)] == [SUBAGENT_ID]


def test_a_session_whose_current_version_a_person_wrote_is_not_due(captured):
    row = current_session(captured, "claude_code", STORY_ID)
    by_person = dict(MODEL_PASS, origin="person scholar", method="review", reason="reviewed")
    supersede(captured, "sessions", row["id"], {"title": ""}, by_person)
    assert [row["harness_session_id"] for row in due(captured)] == [SUBAGENT_ID]


def test_a_session_whose_adapter_lacks_the_ai_flag_is_not_due(captured, monkeypatch):
    class NotAI:
        NAME = "not_ai"
        AI = False

    monkeypatch.setitem(capture.ADAPTERS, "not_ai", NotAI)
    provenance = dict(MODEL_PASS, origin="not_ai adapter", method="by hand", reason="capture")
    add_row(captured, "sessions", {"harness": "not_ai", "harness_session_id": "w1"}, provenance)
    # A harness with no adapter at all is not due either.
    add_row(captured, "sessions", {"harness": "gone", "harness_session_id": "g1"}, provenance)
    assert [row["harness_session_id"] for row in due(captured)] == [STORY_ID, SUBAGENT_ID]
