"""Tests for the projects table (Track A, Step A17).

Appendix Table A3's Shared tables row keeps a row for each project, and
Figure A4 draws the projects table among the shared tables. A session's
project is the folder it ran in (slice plan choice 4), and capture adds a
project row the first time a session runs in a folder, named after the
folder (plan choice 19). The proposal's Implications paragraph 1 reuses audit
records across projects, and these rows are what name them.

The sessions are the test story's synthetic Claude Code sessions and the
subagent fixture, with the folder token {{PROJECT}} replaced by a temporary
folder. A second session in another folder is the story session with its ids
changed. No real session file is read, nothing here calls a model or the
network, and every test runs with its home folder inside a temporary folder.
Run from the repository root with python3 -m pytest -q audit_layer/tests.
"""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from audit_layer.capture import capture_session  # noqa: E402
from audit_layer.cli import main  # noqa: E402
from audit_layer.projects import ensure_project, list_projects  # noqa: E402
from audit_layer.store import current, open_store  # noqa: E402

SESSIONS = ROOT / "examples" / "test_story" / "sessions" / "claude_code"
STORY_SESSION = SESSIONS / "story_session.jsonl"
EXCLUDED_SESSION = SESSIONS / "excluded_session.jsonl"
SUBAGENT = Path(__file__).parent / "fixtures" / "claude_code" / "subagent.jsonl"
TOKEN = "{{PROJECT}}"

STORY_ID = "5f3c0413-2a7d-4b9e-8c61-a0d4e7b2c913"
OTHER_ID = "0d6e2b71-8f4a-4c3e-9a15-b7e2c4d9f160"
AGENT_ID = "a7c41e2b9d0f3856"
SUBAGENT_ID = STORY_ID + "/agent-" + AGENT_ID
ENCODED = "-encoded-project-folder"

SPINE = ["id", "created_at", "session", "origin", "method", "reason", "supersedes"]


def lines_of(source, project):
    text = source.read_text(encoding="utf-8")
    text = text.replace(TOKEN, json.dumps(str(project))[1:-1])
    return [line for line in text.split("\n") if line]


def write_session(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes("".join(line + "\n" for line in lines).encode("utf-8"))
    return path


def stored_rows(db, table):
    cursor = db.execute(f"SELECT * FROM {table} ORDER BY rowid")
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


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
    folder = tmp_path / "volunteer_study"
    folder.mkdir()
    return folder


@pytest.fixture
def other(tmp_path):
    folder = tmp_path / "second_study"
    folder.mkdir()
    return folder


@pytest.fixture
def settings(project):
    return {"excluded_folders": [str(project / "excluded_folder")]}


@pytest.fixture
def audit_home(tmp_path):
    return tmp_path / "audit_home"


@pytest.fixture
def audit(audit_home):
    store = open_store(audit_home)
    yield store
    store.db.close()


@pytest.fixture
def story(tmp_path, project):
    """The story session file, with its subagent conversation beside it."""
    folder = tmp_path / "root" / ENCODED
    path = write_session(folder / (STORY_ID + ".jsonl"), lines_of(STORY_SESSION, project))
    write_session(
        folder / STORY_ID / "subagents" / ("agent-" + AGENT_ID + ".jsonl"),
        lines_of(SUBAGENT, project),
    )
    return path


@pytest.fixture
def story_alone(tmp_path, project):
    """The story session file with no subagent conversation beside it."""
    return write_session(tmp_path / "alone" / (STORY_ID + ".jsonl"), lines_of(STORY_SESSION, project))


@pytest.fixture
def other_session(tmp_path, other):
    """A session of its own, run in another folder, with its own session and tool call ids."""
    lines = [
        line.replace(STORY_ID, OTHER_ID).replace("toolu_story", "toolu_other")
        for line in lines_of(STORY_SESSION, other)
    ]
    return write_session(tmp_path / "root" / "-encoded-other-folder" / (OTHER_ID + ".jsonl"), lines)


@pytest.fixture
def excluded_session(tmp_path, project):
    (project / "excluded_folder").mkdir()
    return write_session(tmp_path / "excluded_session.jsonl", lines_of(EXCLUDED_SESSION, project))


def test_capturing_the_story_adds_one_project_row_named_after_its_folder(
    audit, story_alone, project, settings
):
    capture_session(audit, "claude_code", story_alone, settings)

    (row,) = stored_rows(audit.db, "projects")
    assert row["folder"] == str(project)
    assert row["name"] == "volunteer_study"
    assert row["session"] == STORY_ID
    assert row["origin"] == "claude_code adapter"
    assert row["method"] == "projects 1"
    assert row["reason"] == "first session in folder"
    assert row["supersedes"] is None


def test_the_story_s_subagent_adds_no_project_row(audit, story, project, settings):
    summary = capture_session(audit, "claude_code", story, settings)
    assert len(summary.subagents) == 1

    (row,) = stored_rows(audit.db, "projects")
    assert row["folder"] == str(project)
    assert row["session"] == STORY_ID


def test_a_repeated_capture_adds_no_project_row(audit, story, settings):
    capture_session(audit, "claude_code", story, settings)
    before = stored_rows(audit.db, "projects")
    capture_session(audit, "claude_code", story, settings)
    assert stored_rows(audit.db, "projects") == before


def test_a_session_in_another_folder_adds_a_second_row(
    audit, story, other_session, project, other, settings
):
    capture_session(audit, "claude_code", story, settings)
    capture_session(audit, "claude_code", other_session, settings)

    rows = stored_rows(audit.db, "projects")
    assert [(row["folder"], row["name"]) for row in rows] == [
        (str(project), "volunteer_study"),
        (str(other), "second_study"),
    ]
    assert rows[1]["session"] == OTHER_ID


def test_the_excluded_session_adds_no_project_row(audit, excluded_session, settings):
    summary = capture_session(audit, "claude_code", excluded_session, settings)
    assert summary.excluded
    assert stored_rows(audit.db, "projects") == []


def test_ensure_project_gives_the_existing_row_s_id_for_a_folder_it_holds(audit, project):
    given = {
        "session": "s-projects",
        "origin": "a test",
        "method": "projects 1",
        "reason": "first session in folder",
    }
    first = ensure_project(audit, str(project), given)
    again = ensure_project(audit, str(project), dict(given, session="s-later"))
    assert again == first
    (row,) = current(audit, "projects")
    assert row["id"] == first
    assert row["session"] == "s-projects"


def test_list_projects_counts_each_project_s_current_sessions(
    audit, story, other_session, project, other, settings
):
    capture_session(audit, "claude_code", story, settings)
    capture_session(audit, "claude_code", other_session, settings)

    listed = list_projects(audit)
    # The story's subagent conversation is a session of its own (plan choice 5).
    assert [(item.project["folder"], item.sessions) for item in listed] == [
        (str(project), 2),
        (str(other), 1),
    ]


def test_a_grown_session_is_counted_once(audit, story_alone, project, settings):
    capture_session(audit, "claude_code", story_alone, settings)
    lines = lines_of(STORY_SESSION, project)
    write_session(story_alone, lines[:-1])
    capture_session(audit, "claude_code", story_alone, settings)
    write_session(story_alone, lines)
    capture_session(audit, "claude_code", story_alone, settings)
    assert len(stored_rows(audit.db, "sessions")) > 1

    (item,) = list_projects(audit)
    assert item.sessions == 1


def test_the_projects_table_has_its_fields_and_refuses_update_and_delete(
    audit, story_alone, settings
):
    names = [r[1] for r in audit.db.execute("PRAGMA table_info(projects)")]
    assert names == ["id", "folder", "name"] + SPINE[1:]
    capture_session(audit, "claude_code", story_alone, settings)
    with pytest.raises(sqlite3.DatabaseError, match="never updated"):
        audit.db.execute("UPDATE projects SET name = 'renamed'")
    with pytest.raises(sqlite3.DatabaseError, match="never deleted"):
        audit.db.execute("DELETE FROM projects")


def test_the_projects_command_prints_both_with_their_session_counts(
    tmp_path, story, other_session, project, other, capsys
):
    home = tmp_path / "cli_home"
    assert main(["init", "--home", str(home)]) == 0
    assert main(["capture", "--home", str(home), "--harness", "claude_code", str(story)]) == 0
    assert main(["capture", "--home", str(home), "--harness", "claude_code", str(other_session)]) == 0
    capsys.readouterr()

    assert main(["projects", "--home", str(home)]) == 0
    assert capsys.readouterr().out.splitlines() == [
        f"{project}  volunteer_study  2 sessions",
        f"{other}  second_study  1 session",
        "2 projects",
    ]


def test_the_projects_command_refuses_a_home_with_no_store(tmp_path, capsys):
    home = tmp_path / "no_home"
    assert main(["projects", "--home", str(home)]) == 1
    assert "no audit store" in capsys.readouterr().err
    assert not home.exists()
