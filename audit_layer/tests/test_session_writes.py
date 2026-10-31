"""Tests for the written-out record of file writes (Track W, step W6).

Table A5 lists the file writes among the records the procedures read, which
nothing wrote before, and A2.4 writes a project's records out as files. The
build procedure's check_ai_touch reads one line per write, with the session,
the actor, the tool, and the path. The sessions are the test story's two
synthetic Claude Code session files, whose folder token {{PROJECT}} is
replaced with a temporary folder, and short sessions made up here in the same
format. Each is captured into an audit store in a temporary folder. No real
session file is read, and nothing here calls a model or the network. Run from
the repository root with python3 -m pytest -q audit_layer/tests.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from audit_layer.capture import capture_file  # noqa: E402
from audit_layer.cli import main  # noqa: E402
from audit_layer.records.session_writes import (  # noqa: E402
    session_writes,
    write_session_writes,
)
from audit_layer.records.session_index import public_id  # noqa: E402
from audit_layer.store import current, open_store  # noqa: E402

STORY = ROOT / "examples" / "test_story"
SESSIONS = STORY / "sessions" / "claude_code"
STORY_SESSION = SESSIONS / "story_session.jsonl"
TOUCH_SESSION = SESSIONS / "build_touch_session.jsonl"
EXPECTED = STORY / "build" / "expected_session_writes.jsonl"
TOKEN = "{{PROJECT}}"

STORY_ID = "5f3c0413-2a7d-4b9e-8c61-a0d4e7b2c913"
TOUCH_ID = "8b21d6e4-9c3a-4f57-a2e0-3d6c1f84b705"
MADE_UP_ID = "3e7b0417-9f2a-4b4c-b6d8-d0f3e5a7c246"

NO_FOLDERS = {"excluded_folders": []}


def lines_of(source, folder):
    """A story session's records as lines of text, run in folder."""
    text = source.read_text(encoding="utf-8").replace(TOKEN, json.dumps(str(folder))[1:-1])
    return [line for line in text.split("\n") if line]


def made_up_lines(folder, calls, session_id=MADE_UP_ID, day="2026-10-23"):
    """A short session in the Claude Code format, run in folder.

    Each call is a tool name and its input, and each has its result.
    """
    records = []

    def add(kind, content):
        number = len(records) + 1
        records.append(
            {
                "parentUuid": records[-1]["uuid"] if records else None,
                "isSidechain": False,
                "cwd": str(folder),
                "sessionId": session_id,
                "type": kind,
                "message": {"role": kind, "content": content},
                "uuid": "{}-0000-4000-8000-{:012d}".format(session_id[:8], number),
                "timestamp": "{}T09:00:{:02d}.000Z".format(day, number),
            }
        )

    add("user", "Write the notes.")
    for number, (name, given) in enumerate(calls, start=1):
        call_id = "toolu_{}_{:02d}".format(session_id[:8], number)
        add("assistant", [{"type": "tool_use", "id": call_id, "name": name, "input": given}])
        add("user", [{"type": "tool_result", "tool_use_id": call_id, "content": "Done."}])
    return [json.dumps(record) for record in records]


def capture(store, path, lines):
    """Write the lines as a session file at path and capture it."""
    path.write_bytes("".join(line + "\n" for line in lines).encode("utf-8"))
    summary = capture_file(store, path, NO_FOLDERS)
    assert not summary.excluded
    return summary


def capture_story(store, tmp_path, project):
    # The later session goes in first, so the order comes from the start times.
    capture(store, tmp_path / "build_touch_session.jsonl", lines_of(TOUCH_SESSION, project))
    capture(store, tmp_path / "story_session.jsonl", lines_of(STORY_SESSION, project))


def write(store, project, out):
    write_session_writes(session_writes(store, project), out)
    return out.read_bytes()


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
    """The folder the story sessions ran in."""
    folder = tmp_path / "project"
    folder.mkdir()
    return folder


@pytest.fixture
def audit(tmp_path):
    store = open_store(tmp_path / "audit_home")
    yield store
    store.db.close()


def test_the_two_story_sessions_give_the_expected_file_byte_for_byte(tmp_path, audit, project):
    capture_story(audit, tmp_path, project)
    out = tmp_path / "session_writes.jsonl"
    assert write(audit, project, out) == EXPECTED.read_bytes()


def test_the_rows_name_each_write_with_its_session_and_verb(tmp_path, audit, project):
    capture_story(audit, tmp_path, project)
    assert session_writes(audit, project) == [
        {"actor": "ai", "path": "manuscript.md", "session": STORY_ID, "session_ref": public_id(STORY_ID), "tool": "edited"},
        {"actor": "ai", "path": "manuscript.md", "session": STORY_ID, "session_ref": public_id(STORY_ID), "tool": "edited"},
        {"actor": "ai", "path": "source_notes.md", "session": STORY_ID, "session_ref": public_id(STORY_ID), "tool": "wrote"},
        {"actor": "ai", "path": "builds/manuscript/v001.md", "session": TOUCH_ID, "session_ref": public_id(TOUCH_ID), "tool": "edited"},
    ]


def test_the_read_the_check_and_the_commit_give_no_line(tmp_path, audit, project):
    capture(audit, tmp_path / "story_session.jsonl", lines_of(STORY_SESSION, project))
    verbs = sorted({event["verb"] for event in current(audit, "events")})
    assert verbs == ["committed", "edited", "searched", "verified", "wrote"]
    assert [row["tool"] for row in session_writes(audit, project)] == ["edited", "edited", "wrote"]


def test_capturing_a_session_again_adds_no_line(tmp_path, audit, project):
    capture_story(audit, tmp_path, project)
    first = write(audit, project, tmp_path / "first.jsonl")
    again = capture(audit, tmp_path / "story_session.jsonl", lines_of(STORY_SESSION, project))
    assert again.events == 0
    assert write(audit, project, tmp_path / "again.jsonl") == first


def test_a_grown_session_adds_only_its_new_writes(tmp_path, audit, project):
    lines = lines_of(STORY_SESSION, project)
    # The session up to the result of its first edit, then the whole file.
    capture(audit, tmp_path / "story_session.jsonl", lines[:5])
    assert len(session_writes(audit, project)) == 1
    grown = capture(audit, tmp_path / "story_session.jsonl", lines)
    assert grown.sessions == 1
    capture(audit, tmp_path / "build_touch_session.jsonl", lines_of(TOUCH_SESSION, project))
    assert write(audit, project, tmp_path / "out.jsonl") == EXPECTED.read_bytes()


def test_a_session_run_elsewhere_counts_only_its_writes_inside_the_project(
    tmp_path, audit, project
):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    calls = [
        ("Write", {"file_path": str(project / "notes" / "plan.md"), "content": "A plan.\n"}),
        ("Write", {"file_path": str(elsewhere / "other.md"), "content": "Not the project.\n"}),
        ("Edit", {"file_path": "../project/manuscript.md", "old_string": "a", "new_string": "b"}),
        ("Write", {"file_path": str(tmp_path / "project_two" / "x.md"), "content": "x\n"}),
    ]
    capture(audit, tmp_path / "made_up.jsonl", made_up_lines(elsewhere, calls))
    assert session_writes(audit, project) == [
        {"actor": "ai", "path": "notes/plan.md", "session": MADE_UP_ID, "session_ref": public_id(MADE_UP_ID), "tool": "wrote"},
        {"actor": "ai", "path": "manuscript.md", "session": MADE_UP_ID, "session_ref": public_id(MADE_UP_ID), "tool": "edited"},
    ]


def test_the_project_is_compared_as_a_real_path(tmp_path, audit, project):
    link = tmp_path / "link_to_project"
    link.symlink_to(project, target_is_directory=True)
    # The sessions ran through the link, and the record is asked for by the folder itself.
    capture(audit, tmp_path / "story_session.jsonl", lines_of(STORY_SESSION, link))
    capture(audit, tmp_path / "build_touch_session.jsonl", lines_of(TOUCH_SESSION, link))
    assert write(audit, project, tmp_path / "a.jsonl") == EXPECTED.read_bytes()
    # And the other way round.
    assert write(audit, link, tmp_path / "b.jsonl") == EXPECTED.read_bytes()


def test_a_project_with_no_writes_gives_an_empty_file(tmp_path, audit, project):
    capture_story(audit, tmp_path, project)
    other = tmp_path / "other_project"
    other.mkdir()
    out = tmp_path / "session_writes.jsonl"
    assert session_writes(audit, other) == []
    assert write(audit, other, out) == b""


def test_no_line_names_an_absolute_path(tmp_path, audit, project):
    capture_story(audit, tmp_path, project)
    text = write(audit, project, tmp_path / "out.jsonl").decode("utf-8")
    assert str(tmp_path) not in text and os.path.realpath(str(tmp_path)) not in text
    for line in text.splitlines():
        path = json.loads(line)["path"]
        assert not os.path.isabs(path) and "\\" not in path
        assert ".." not in path.split("/")


def test_the_write_out_command_writes_the_record(tmp_path, project, capsys):
    home = tmp_path / "audit_home"
    assert main(["init", "--home", str(home)]) == 0
    for source in (STORY_SESSION, TOUCH_SESSION):
        path = tmp_path / source.name
        path.write_bytes("".join(line + "\n" for line in lines_of(source, project)).encode("utf-8"))
        assert main(["capture", "--home", str(home), "--harness", "claude_code", str(path)]) == 0
    capsys.readouterr()
    out = tmp_path / "session_writes.jsonl"
    argv = ["write-out", "session-writes", "--home", str(home), "--project", str(project)]
    assert main(argv + ["--out", str(out)]) == 0
    assert out.read_bytes() == EXPECTED.read_bytes()
    printed = capsys.readouterr().out
    assert str(out) in printed and "4 file writes" in printed


def test_write_out_runs_as_a_module_with_the_audit_home_from_the_environment(tmp_path, project):
    home = tmp_path / "audit_home"
    store = open_store(home)
    try:
        capture_story(store, tmp_path, project)
    finally:
        store.db.close()
    done = subprocess.run(
        [sys.executable, "-m", "audit_layer", "write-out", "session-writes",
         "--project", "project", "--out", "out.jsonl"],
        cwd=str(tmp_path), capture_output=True, text=True,
        env=dict(os.environ, AUDIT_HOME=str(home), PYTHONPATH=str(ROOT)))
    assert done.returncode == 0, done.stderr
    assert (tmp_path / "out.jsonl").read_bytes() == EXPECTED.read_bytes()


def test_write_out_refuses_without_an_audit_store(tmp_path, project, capsys):
    home = tmp_path / "no_home"
    out = tmp_path / "out.jsonl"
    argv = ["write-out", "session-writes", "--home", str(home), "--project", str(project)]
    assert main(argv + ["--out", str(out)]) == 1
    assert "there is no audit store" in capsys.readouterr().err
    assert not out.exists() and not home.exists()


def test_write_out_names_an_out_file_it_cannot_write(tmp_path, project, capsys):
    home = tmp_path / "audit_home"
    assert main(["init", "--home", str(home)]) == 0
    out = tmp_path / "missing_folder" / "out.jsonl"
    argv = ["write-out", "session-writes", "--home", str(home), "--project", str(project)]
    assert main(argv + ["--out", str(out)]) == 1
    assert "could not write out the file writes" in capsys.readouterr().err


@pytest.mark.parametrize(
    "arguments",
    [["--out", "x.jsonl"], ["--project", "p"]],
    ids=["no project", "no out file"],
)
def test_write_out_needs_a_project_and_an_out_file(arguments):
    with pytest.raises(SystemExit) as raised:
        main(["write-out", "session-writes"] + arguments)
    assert raised.value.code == 2
