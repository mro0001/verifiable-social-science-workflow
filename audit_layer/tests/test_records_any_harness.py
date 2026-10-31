"""Tests that the written-out records read any harness (Track A, Step A4).

Appendix A2.4 writes a project's records out as files, and Table A5 lists the
file writes, the citation log, and the AI rationales among the records the
procedures read. ForgeCode is the fallback harness (the ruling of
2026-10-28). So each record writer reads a stored session through
capture.read_stored, with its own harness's adapter, and a ForgeCode session
or a subagent conversation gives the same records as a Claude Code session
with the same actions. The stated reason before an edit is read from the
session's ordered parts, which every adapter gives (reconciliation, Track A).
Only sessions whose adapter has the AI flag are written out (reconciliation,
Track A and item 7).

The sessions are the test story's synthetic Claude Code session, the Forge
story conversation the ForgeCode fixture writes from it, and the synthetic
subagent conversation, each with its folder token replaced by a temporary
folder. No real session file or Forge database is read, nothing here calls a
model or the network, and every test runs with its home folder inside a
temporary folder. Run from the repository root with
python3 -m pytest -q audit_layer/tests.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from audit_layer.capture import capture_file, capture_session, claude_code, forgecode  # noqa: E402
from audit_layer.records.citation_log import citation_log  # noqa: E402
from audit_layer.records.rationales import rationales, stated_reasons  # noqa: E402
from audit_layer.records.session_index import public_id  # noqa: E402
from audit_layer.records.session_writes import session_writes  # noqa: E402
from audit_layer.store import add_row, open_store  # noqa: E402

_SPEC = importlib.util.spec_from_file_location(
    "forgecode_make_store", Path(__file__).parent / "fixtures" / "forgecode" / "make_store.py"
)
forge = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(forge)

STORY = ROOT / "examples" / "test_story"
STORY_SESSION = STORY / "sessions" / "claude_code" / "story_session.jsonl"
SUBAGENT = Path(__file__).parent / "fixtures" / "claude_code" / "subagent.jsonl"
TOKEN = "{{PROJECT}}"

STORY_ID = "5f3c0413-2a7d-4b9e-8c61-a0d4e7b2c913"
AGENT_ID = "a7c41e2b9d0f3856"
SUBAGENT_ID = STORY_ID + "/agent-" + AGENT_ID

NO_FOLDERS = {"excluded_folders": []}


def write_session(path, source, project):
    """Write the session file source at path, with the token replaced by project."""
    text = source.read_text(encoding="utf-8").replace(TOKEN, json.dumps(str(project))[1:-1])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def without_sessions(rows):
    """The rows with their session ids and public ids left out, to compare two harnesses' records."""
    return [
        {name: value for name, value in row.items() if name not in ("session", "session_ref")}
        for row in rows
    ]


@pytest.fixture(autouse=True)
def home_folder(tmp_path, monkeypatch):
    """Each test's own home folder, so nothing reaches the real ~/.audit_layer or ~/forge."""
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
def claude_store(tmp_path, project):
    """A store holding the Claude Code story session."""
    store = open_store(tmp_path / "claude_home")
    path = write_session(tmp_path / "root" / "folder" / (STORY_ID + ".jsonl"), STORY_SESSION, project)
    assert capture_file(store, path, NO_FOLDERS).events == 6
    yield store
    store.db.close()


@pytest.fixture
def forge_store(tmp_path, project):
    """A store holding the Forge story conversation."""
    store = open_store(tmp_path / "forge_home")
    db = forge.make_store(tmp_path / "forge" / ".forge.db", project)
    summary = capture_session(store, "forgecode", f"{db}#{forge.STORY_ID}", NO_FOLDERS)
    assert summary.events == 6
    yield store
    store.db.close()


@pytest.fixture
def with_subagent(tmp_path, project):
    """A store holding the story session and its subagent conversation."""
    store = open_store(tmp_path / "subagent_home")
    folder = tmp_path / "root" / "-encoded-project-folder"
    main = write_session(folder / (STORY_ID + ".jsonl"), STORY_SESSION, project)
    write_session(folder / STORY_ID / "subagents" / ("agent-" + AGENT_ID + ".jsonl"), SUBAGENT, project)
    summary = capture_session(store, "claude_code", main, NO_FOLDERS)
    assert [item.session_id for item in summary.subagents] == [SUBAGENT_ID]
    yield store
    store.db.close()


def add_editing_session(store, harness, session_id, source):
    """A made-up session row of the harness with one edited event on source and no transcript."""
    provenance = {"session": session_id, "origin": "test", "method": "by hand", "reason": "test"}
    row = add_row(
        store,
        "sessions",
        {
            "harness": harness,
            "harness_session_id": session_id,
            "project": str(Path(source).parent),
            "started_at": "2026-10-20T09:00:00.000Z",
            "ended_at": "2026-10-20T09:10:00.000Z",
            "tools": ["Edit"],
        },
        provenance,
    )
    add_row(
        store,
        "events",
        {
            "session_row_id": row,
            "ordinal": 1,
            "verb": "edited",
            "kind": "action",
            "object": str(source),
            "rationale": "",
            "role": "edited",
        },
        provenance,
    )


# The citation log.


def test_both_harnesses_give_the_same_citation_log_each_with_its_own_session(
    claude_store, forge_store, project
):
    from_claude = citation_log(claude_store, project)["citations"]
    from_forge = citation_log(forge_store, project)["citations"]
    assert sorted(from_claude) == ["dumont2014", "nakamura2020"]
    assert sorted(from_forge) == sorted(from_claude)
    for key in from_claude:
        assert from_forge[key]["introduced_by"] == from_claude[key]["introduced_by"] == "ai"
        assert from_forge[key]["draft"] == from_claude[key]["draft"]
        assert from_claude[key]["session"] == STORY_ID
        assert from_forge[key]["session"] == forge.STORY_ID


def test_a_subagent_s_citation_is_logged_under_the_subagent_s_session(with_subagent, project):
    log = citation_log(with_subagent, project)["citations"]
    assert log["healy2020"] == {
        "introduced_by": "ai",
        "draft": "",
        "session": SUBAGENT_ID,
        "session_ref": public_id(SUBAGENT_ID),
    }
    assert log["dumont2014"]["session"] == STORY_ID
    assert log["nakamura2020"]["session"] == STORY_ID


def test_the_citation_log_reads_the_forge_session_through_its_own_adapter(
    forge_store, project, monkeypatch
):
    def refuse(data):
        raise AssertionError("the Claude Code reader was asked to parse a Forge transcript")

    monkeypatch.setattr(claude_code, "parse_transcript", refuse)
    monkeypatch.setattr(claude_code, "read_session", refuse)
    assert sorted(citation_log(forge_store, project)["citations"]) == ["dumont2014", "nakamura2020"]


def test_the_citation_log_leaves_out_a_harness_without_the_ai_flag(forge_store, project, monkeypatch):
    monkeypatch.setattr(forgecode, "AI", False)
    assert citation_log(forge_store, project) == {"citations": {}}


# The file writes.


def test_both_harnesses_give_the_same_file_writes_each_with_its_own_session(
    claude_store, forge_store, project
):
    from_claude = session_writes(claude_store, project)
    from_forge = session_writes(forge_store, project)
    assert [row["path"] for row in from_claude] == ["manuscript.md", "manuscript.md", "source_notes.md"]
    assert without_sessions(from_forge) == without_sessions(from_claude)
    assert {row["session"] for row in from_claude} == {STORY_ID}
    assert {row["session"] for row in from_forge} == {forge.STORY_ID}


def test_a_subagent_s_writes_are_listed_under_the_subagent_s_session(with_subagent, project):
    rows = session_writes(with_subagent, project)
    assert {
        "actor": "ai",
        "path": "notes/reading_list.md",
        "session": SUBAGENT_ID,
        "session_ref": public_id(SUBAGENT_ID),
        "tool": "wrote",
    } in rows


def test_the_file_writes_leave_out_a_harness_without_the_ai_flag(
    claude_store, forge_store, project, monkeypatch
):
    monkeypatch.setattr(forgecode, "AI", False)
    assert session_writes(forge_store, project) == []
    assert len(session_writes(claude_store, project)) == 3


def test_the_file_writes_leave_out_a_harness_with_no_adapter(claude_store, project):
    add_editing_session(claude_store, "wrappers", "2026-10-20_0123456789ab", project / "manuscript.md")
    rows = session_writes(claude_store, project)
    assert {row["session"] for row in rows} == {STORY_ID}


# The AI rationales.


def test_both_harnesses_give_the_same_rationales_each_with_its_own_session(
    claude_store, forge_store, project
):
    from_claude = rationales(claude_store, project / "manuscript.md")
    from_forge = rationales(forge_store, project / "manuscript.md")
    assert [entry["id"] for entry in from_claude] == ["r01", "r02"]
    assert without_sessions(from_forge) == without_sessions(from_claude)
    assert {entry["session"] for entry in from_claude} == {STORY_ID}
    assert {entry["session"] for entry in from_forge} == {forge.STORY_ID}
    assert [entry["rationale"] for entry in from_forge] == [
        "I'll add the first finding after your sentence on fit.",
        "Now the second finding.",
    ]


def test_stated_reasons_read_the_ordered_parts_of_either_harness(tmp_path, project):
    claude = claude_code.read_session(
        write_session(tmp_path / "story.jsonl", STORY_SESSION, project)
    )
    db = forge.make_store(tmp_path / "forge" / ".forge.db", project)
    forge_session = forgecode.read_session(f"{db}#{forge.STORY_ID}")
    from_claude = stated_reasons(claude.parts)
    from_forge = stated_reasons(forge_session.parts)
    assert len(from_claude) == len(from_forge) == 6
    assert list(from_forge.values()) == list(from_claude.values())
    assert from_forge["call_forge_02_patch"] == "I'll add the first finding after your sentence on fit."


def test_the_rationales_skip_and_name_a_harness_without_the_ai_flag(
    forge_store, project, monkeypatch, capsys
):
    monkeypatch.setattr(forgecode, "AI", False)
    assert rationales(forge_store, project / "manuscript.md") == []
    error = capsys.readouterr().err
    assert forge.STORY_ID in error and "forgecode" in error
