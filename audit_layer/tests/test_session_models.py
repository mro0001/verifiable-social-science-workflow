"""Tests for the models and the harness version in the session record (Track P, Step P1).

the authors asked on 2026-10-30 for a public, searchable index of a project's AI
sessions, and each session's entry names the models that answered in it and
the harness's version (Track P plan, Step P1). Capture records the models in
the order first seen as a JSON list in the sessions field models, and the
harness's version, when the transcript gives one, as harness_version. Table
A5 lists "Recording which model and version answered each AI call" as Not
designed, and this records them for each session.

Capture by explicit file also reads a subagent conversation kept one or more
folders deeper than subagents/, such as subagents/workflows/<run>/agent-<id>.jsonl.

Every session here is synthetic, written in the test or taken from the test
story and Track A's fixtures, with the folder token {{PROJECT}} replaced with
a temporary folder. No real session file or database is read, no default
root is read, nothing here calls a model or the network, and every test runs
with its home folder inside a temporary folder. Run from the repository root
with python3 -m pytest -q audit_layer/tests.
"""
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import audit_layer.store as store_module  # noqa: E402
from audit_layer.capture import (  # noqa: E402
    SubagentsNotCaptured,
    capture_file,
    capture_session,
    claude_code,
    forgecode,
)
from audit_layer.fields import FIELDS  # noqa: E402
from audit_layer.queries import current_session  # noqa: E402
from audit_layer.store import current, open_store, supersede  # noqa: E402

_SPEC = importlib.util.spec_from_file_location(
    "forgecode_make_store_p1", Path(__file__).parent / "fixtures" / "forgecode" / "make_store.py"
)
forge_fixture = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(forge_fixture)

SESSIONS = ROOT / "examples" / "test_story" / "sessions" / "claude_code"
STORY_SESSION = SESSIONS / "story_session.jsonl"
SUBAGENT = Path(__file__).parent / "fixtures" / "claude_code" / "subagent.jsonl"
TOKEN = "{{PROJECT}}"

STORY_ID = "5f3c0413-2a7d-4b9e-8c61-a0d4e7b2c913"
AGENT_ID = "a7c41e2b9d0f3856"
SUBAGENT_ID = STORY_ID + "/agent-" + AGENT_ID

TWO_MODELS_ID = "0b7d2c55-91e4-4a6f-8d3b-5e1f0a2c7d40"


def settings_for(*folders):
    return {"excluded_folders": [str(folder) for folder in folders]}


def lines_of(source, project):
    """The session file's records as lines of text, with the token replaced by project."""
    text = source.read_text(encoding="utf-8")
    text = text.replace(TOKEN, json.dumps(str(project))[1:-1])
    return [line for line in text.split("\n") if line]


def write_lines(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes("".join(line + "\n" for line in lines).encode("utf-8"))
    return path


def record(project, number, kind, content, model=None, version=None):
    """One synthetic Claude Code record of the session TWO_MODELS_ID."""
    item = {
        "parentUuid": None,
        "isSidechain": False,
        "cwd": str(project),
        "sessionId": TWO_MODELS_ID,
        "type": kind,
        "uuid": "0b7d2c55-0000-4000-8000-%012d" % number,
        "timestamp": "2026-10-29T09:%02d:00.000Z" % number,
        "message": {"role": kind, "content": content},
    }
    if model is not None:
        item["message"]["model"] = model
    if version is not None:
        item["version"] = version
    return json.dumps(item)


def two_model_lines(project):
    """A session answered by two models in turn, the first one again at the end."""
    read = {"type": "tool_use", "id": "toolu_p1_01_read", "name": "Read",
            "input": {"file_path": str(project / "manuscript.md")}}
    result = {"type": "tool_result", "tool_use_id": "toolu_p1_01_read", "content": "text"}
    return [
        record(project, 1, "user", "Read the manuscript and say what it argues.",
               version="2.0.14"),
        record(project, 2, "assistant", [{"type": "text", "text": "Reading it."}, read],
               model="synthetic-model-large", version="2.0.14"),
        record(project, 3, "user", [result], version="2.0.14"),
        record(project, 4, "assistant", [{"type": "text", "text": "A short answer."}],
               model="synthetic-model-small", version="2.0.14"),
        record(project, 5, "assistant", [{"type": "text", "text": "Done."}],
               model="synthetic-model-large", version="2.0.14"),
    ]


@pytest.fixture(autouse=True)
def home_folder(tmp_path, monkeypatch):
    """Each test's own home folder, so nothing reaches the real ~/.audit_layer or a real root."""
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
def audit(tmp_path):
    store = open_store(tmp_path / "audit_home")
    yield store
    store.db.close()


# The fields and their definitions.


def test_the_sessions_table_has_the_two_new_fields_with_definitions(audit):
    columns = [row[1] for row in audit.db.execute("PRAGMA table_info(sessions)")]
    assert "models" in columns and "harness_version" in columns
    defined = {(item.table_name, item.field): item for item in FIELDS}
    for name in ("models", "harness_version"):
        item = defined[("sessions", name)]
        assert item.definition and item.generation_rule and item.null_behavior
    stored = {
        (row["table_name"], row["field"]) for row in current(audit, "field_definitions")
    }
    assert ("sessions", "models") in stored and ("sessions", "harness_version") in stored


def test_models_is_kept_as_a_json_list(audit):
    assert "models" in store_module.LISTS["sessions"]


# Claude Code.


def test_a_claude_code_session_gives_its_models_in_the_order_first_seen_and_its_version(
    tmp_path, project
):
    path = write_lines(tmp_path / "two_models.jsonl", two_model_lines(project))
    session = claude_code.read_session(path)
    assert list(session.models) == ["synthetic-model-large", "synthetic-model-small"]
    assert session.harness_version == "2.0.14"


def test_capture_stores_the_models_and_the_version(tmp_path, audit, project):
    path = write_lines(tmp_path / "two_models.jsonl", two_model_lines(project))
    capture_file(audit, path, settings_for(project / "excluded_folder"))
    row = current_session(audit, "claude_code", TWO_MODELS_ID)
    assert row["models"] == ["synthetic-model-large", "synthetic-model-small"]
    assert row["harness_version"] == "2.0.14"
    raw = audit.db.execute(
        "SELECT models FROM sessions WHERE harness_session_id = ?", (TWO_MODELS_ID,)
    ).fetchone()[0]
    assert json.loads(raw) == ["synthetic-model-large", "synthetic-model-small"]


def test_a_session_that_names_no_model_and_no_version_stores_an_empty_list_and_no_version(
    tmp_path, audit, project
):
    path = write_lines(tmp_path / "story.jsonl", lines_of(STORY_SESSION, project))
    session = claude_code.read_session(path)
    assert list(session.models) == []
    assert session.harness_version == ""
    capture_file(audit, path, settings_for(project / "excluded_folder"))
    row = current_session(audit, "claude_code", STORY_ID)
    assert row["models"] == []
    assert row["harness_version"] is None


def test_a_record_without_a_model_text_adds_no_model(tmp_path, project):
    lines = two_model_lines(project)
    bare = json.loads(lines[3])
    bare["message"]["model"] = ""
    lines[3] = json.dumps(bare)
    session = claude_code.read_session(write_lines(tmp_path / "s.jsonl", lines))
    assert list(session.models) == ["synthetic-model-large"]


def test_a_user_record_naming_a_model_adds_no_model(tmp_path, project):
    lines = two_model_lines(project)
    lines[0] = record(project, 1, "user", "Hello.", model="not-an-answer", version="2.0.14")
    session = claude_code.read_session(write_lines(tmp_path / "s.jsonl", lines))
    assert "not-an-answer" not in session.models


def test_a_message_the_harness_made_itself_adds_no_model(tmp_path, project):
    # Claude Code names the model "<synthetic>" on assistant records it writes
    # itself, such as an API error notice, and no model answered those.
    lines = two_model_lines(project)
    lines.insert(3, record(project, 6, "assistant",
                           [{"type": "text", "text": "API Error: a synthetic notice."}],
                           model="<synthetic>", version="2.0.14"))
    session = claude_code.read_session(write_lines(tmp_path / "s.jsonl", lines))
    assert list(session.models) == ["synthetic-model-large", "synthetic-model-small"]


def test_the_version_is_the_first_one_a_record_gives(tmp_path, project):
    lines = two_model_lines(project)
    lines[0] = record(project, 1, "user", "Hello.")
    lines[4] = record(project, 5, "assistant", [{"type": "text", "text": "Done."}],
                      model="synthetic-model-large", version="2.0.15")
    session = claude_code.read_session(write_lines(tmp_path / "s.jsonl", lines))
    assert session.harness_version == "2.0.14"


def test_the_subagent_fixture_gives_its_model(audit, tmp_path, project):
    path = write_lines(tmp_path / "agent.jsonl", lines_of(SUBAGENT, project))
    capture_session(audit, "claude_code", path, settings_for(project / "excluded_folder"))
    row = current_session(audit, "claude_code", SUBAGENT_ID)
    assert row["models"] == ["claude-synthetic-1"]


# ForgeCode.


def test_a_forgecode_conversation_without_model_data_gives_an_empty_list(tmp_path, audit, project):
    messages = [
        forge_fixture.system_message(project),
        {"message": {"text": {"role": "User", "content": "Read the notes.", "tool_calls": None,
                              "model": None}}},
        {"message": {"text": {"role": "Assistant", "content": "I read them.",
                              "tool_calls": None}}},
    ]
    data = forge_fixture.context_text("c-no-model", messages).encode("utf-8")
    session = forgecode.parse_transcript(data)
    assert list(session.models) == []
    assert session.harness_version == ""

    db_path = forge_fixture.make_store(tmp_path / "forge" / ".forge.db", project)
    db = sqlite3.connect(str(db_path))
    try:
        db.execute(
            "INSERT INTO conversations (conversation_id, title, workspace_id, context,"
            " created_at, updated_at, metrics) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("c-no-model", "no model", 1, data.decode("utf-8"),
             "2026-10-29 10:00:00", "2026-10-29 10:05:00", None),
        )
        db.commit()
    finally:
        db.close()
    capture_session(audit, "forgecode", f"{db_path}#c-no-model",
                    settings_for(project / "excluded_folder"))
    row = current_session(audit, "forgecode", "c-no-model")
    assert row["models"] == []
    assert row["harness_version"] is None


def test_a_forgecode_user_message_naming_a_model_adds_no_model(project):
    messages = [
        forge_fixture.system_message(project),
        {"message": {"text": {"role": "User", "content": "Read the notes.", "tool_calls": None,
                              "model": "not-an-answer"}}},
        {"message": {"text": {"role": "Assistant", "content": "I read them.",
                              "tool_calls": None, "model": "synthetic-forge-model"}}},
    ]
    data = forge_fixture.context_text("c-user-model", messages).encode("utf-8")
    session = forgecode.parse_transcript(data)
    assert list(session.models) == ["synthetic-forge-model"]


def test_a_forgecode_conversation_gives_the_models_its_assistant_messages_name(
    tmp_path, audit, project
):
    db_path = forge_fixture.make_store(tmp_path / "forge" / ".forge.db", project)
    capture_session(audit, "forgecode", f"{db_path}#{forge_fixture.STORY_ID}",
                    settings_for(project / "excluded_folder"))
    row = current_session(audit, "forgecode", forge_fixture.STORY_ID)
    assert row["models"] == [forge_fixture.MODEL]
    assert row["harness_version"] is None


# A subagent kept in a nested folder.


def place_nested(root, project, depth_parts=("workflows", "run-01")):
    folder = root / "-encoded-project-folder"
    main = write_lines(folder / (STORY_ID + ".jsonl"), lines_of(STORY_SESSION, project))
    nested = folder / STORY_ID / "subagents"
    for part in depth_parts:
        nested = nested / part
    agent = write_lines(nested / ("agent-" + AGENT_ID + ".jsonl"), lines_of(SUBAGENT, project))
    return main, agent


def test_capturing_the_main_file_captures_a_subagent_kept_in_a_nested_folder(
    tmp_path, audit, project
):
    main, agent = place_nested(tmp_path / "root", project)
    summary = capture_file(audit, main, settings_for(project / "excluded_folder"))
    assert [sub.session_id for sub in summary.subagents] == [SUBAGENT_ID]
    row = current_session(audit, "claude_code", SUBAGENT_ID)
    assert row is not None
    assert row["harness_session_id"].startswith(STORY_ID + "/")


def test_a_subagent_one_folder_deeper_is_captured_too(tmp_path, audit, project):
    main, _ = place_nested(tmp_path / "root", project, ("workflows",))
    summary = capture_file(audit, main, settings_for(project / "excluded_folder"))
    assert [sub.session_id for sub in summary.subagents] == [SUBAGENT_ID]


def test_a_nested_subagent_file_captured_on_its_own_takes_its_ids_from_its_records(
    tmp_path, audit, project
):
    _, agent = place_nested(tmp_path / "root", project)
    summary = capture_file(audit, agent, settings_for(project / "excluded_folder"))
    assert summary.session_id == SUBAGENT_ID


def test_a_broken_nested_subagent_is_named_by_its_parents_id_and_agent_id(tmp_path, audit, project):
    main, agent = place_nested(tmp_path / "root", project)
    agent.write_bytes(b"not JSON\n")
    with pytest.raises(SubagentsNotCaptured) as caught:
        capture_file(audit, main, settings_for(project / "excluded_folder"))
    assert caught.value.failed == (SUBAGENT_ID,)
    assert str(tmp_path) not in str(caught.value)


def test_a_nested_meta_file_and_other_files_are_not_read(tmp_path, audit, project):
    main, agent = place_nested(tmp_path / "root", project)
    (agent.parent / ("agent-" + AGENT_ID + ".meta.json")).write_bytes(b"not JSON")
    write_lines(agent.parent / "notes.jsonl", ["not JSON"])
    summary = capture_file(audit, main, settings_for(project / "excluded_folder"))
    assert [sub.session_id for sub in summary.subagents] == [SUBAGENT_ID]


# Rows written before the fields existed.


def old_sessions_fields():
    return tuple(
        (name, kind) for name, kind in store_module.TABLES["sessions"]
        if name not in ("models", "harness_version")
    )


def old_schema():
    """The store's schema as it was before the two fields, read with the sessions table cut back."""
    kept = store_module.TABLES
    store_module.TABLES = dict(kept, sessions=old_sessions_fields())
    try:
        return store_module._schema()
    finally:
        store_module.TABLES = kept


def test_an_old_store_gains_the_fields_empty_on_its_old_rows(tmp_path, project):
    home = tmp_path / "old_home"
    home.mkdir()
    db = sqlite3.connect(str(home / store_module.DATABASE))
    db.executescript(old_schema())
    columns = [row[1] for row in db.execute("PRAGMA table_info(sessions)")]
    assert "models" not in columns and "harness_version" not in columns
    db.execute(
        "INSERT INTO sessions (id, harness, harness_session_id, project, started_at, ended_at,"
        " tools, title, gist, summary, keywords, created_at, session, origin, method, reason,"
        " supersedes) VALUES ('old-row', 'claude_code', ?, ?, '2026-10-29T09:01:00.000Z',"
        " '2026-10-29T09:05:00.000Z', '[\"Read\"]', 'A title', 'A gist', 'A summary',"
        " '[\"a\", \"b\", \"c\"]', '2026-10-29T10:00:00.000000Z', ?, 'claude_code adapter',"
        " 'an older version', 'capture', NULL)",
        (TWO_MODELS_ID, str(project), TWO_MODELS_ID),
    )
    db.commit()
    db.close()

    store = open_store(home)
    try:
        columns = [row[1] for row in store.db.execute("PRAGMA table_info(sessions)")]
        assert "models" in columns and "harness_version" in columns
        row = current_session(store, "claude_code", TWO_MODELS_ID)
        assert row["id"] == "old-row"
        assert row["models"] is None
        assert row["harness_version"] is None
        assert row["title"] == "A title"
    finally:
        store.db.close()


def test_capturing_an_unchanged_session_again_fills_the_new_fields_and_keeps_the_model_pass_fields(
    tmp_path, audit, project
):
    path = write_lines(tmp_path / "two_models.jsonl", two_model_lines(project))
    settings = settings_for(project / "excluded_folder")
    capture_file(audit, path, settings)
    row = current_session(audit, "claude_code", TWO_MODELS_ID)
    tagged = {"title": "A title", "gist": "A gist", "summary": "A summary",
              "keywords": ["a", "b", "c"]}
    provenance = {"session": TWO_MODELS_ID, "origin": "test", "method": "by hand",
                  "reason": "test"}
    row_id = supersede(audit, "sessions", row["id"], tagged, provenance)
    # The row as a store made before the fields existed would hold it.
    old_id = supersede(audit, "sessions", row_id, {"models": None, "harness_version": None},
                       provenance)

    summary = capture_file(audit, path, settings)
    assert summary.sessions == 1
    new = current_session(audit, "claude_code", TWO_MODELS_ID)
    assert new["supersedes"] == old_id
    assert new["models"] == ["synthetic-model-large", "synthetic-model-small"]
    assert new["harness_version"] == "2.0.14"
    assert {name: new[name] for name in tagged} == tagged

    again = capture_file(audit, path, settings)
    assert again.sessions == 0


def test_a_grown_session_still_empties_the_model_pass_fields(tmp_path, audit, project):
    lines = two_model_lines(project)
    path = write_lines(tmp_path / "two_models.jsonl", lines[:3])
    settings = settings_for(project / "excluded_folder")
    capture_file(audit, path, settings)
    row = current_session(audit, "claude_code", TWO_MODELS_ID)
    supersede(audit, "sessions", row["id"], {"title": "A title"},
              {"session": TWO_MODELS_ID, "origin": "test", "method": "by hand", "reason": "test"})
    write_lines(path, lines)
    capture_file(audit, path, settings)
    new = current_session(audit, "claude_code", TWO_MODELS_ID)
    assert new["title"] is None
    assert new["models"] == ["synthetic-model-large", "synthetic-model-small"]
