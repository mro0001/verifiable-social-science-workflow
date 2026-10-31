"""Tests for capture of the wrappers' events (Track D, step D4).

Appendix A2.4 "Capture" sweeps each harness's session files and the wrappers'
events and keeps each transcript unchanged, and Figure A4 has the wrappers
feed the sweep, which is safe to repeat. The connectors write each event as
one JSON line in <connections home>/events/<YYYY-MM-DD>_<key>.jsonl, holding
the event schema's fields plus at, cwd, and program (Track D choice 2). The
wrappers adapter reads one such file as one session of the harness wrappers,
with AI false, and capture stores its events as they are, with no mechanical
pass (reconciliation, Track D).

Every events file here is written by hand by the test, except in the end to
end test, where the connectors' own wrapper writes it. No real session file
is read, nothing here calls a model or the network, and every test runs with
HOME, AUDIT_HOME, and CONNECTIONS_HOME inside a temporary folder. Run from
the repository root with python3 -m pytest -q audit_layer/tests.
"""
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import audit_layer.capture as capture  # noqa: E402
from audit_layer.capture import ADAPTERS, capture_session, read_stored, wrappers  # noqa: E402
from audit_layer.capture.sweep import sweep  # noqa: E402
from audit_layer.cli import main  # noqa: E402
from audit_layer.queries import current_session, session_events  # noqa: E402
from audit_layer.store import current, open_store  # noqa: E402
from audit_layer.tagging.model_pass import due  # noqa: E402

TABLES = ("sessions", "events", "transcripts")
DAY = "2026-10-29"


@pytest.fixture(autouse=True)
def homes(tmp_path, monkeypatch):
    """Each test's own home, audit home, and connections home."""
    user = tmp_path / "user"
    user.mkdir()
    monkeypatch.setenv("HOME", str(user))
    monkeypatch.setenv("AUDIT_HOME", str(tmp_path / "audit_home"))
    monkeypatch.setenv("CONNECTIONS_HOME", str(tmp_path / "connections_home"))
    return tmp_path


@pytest.fixture
def project(tmp_path):
    folder = tmp_path / "project"
    folder.mkdir()
    return folder


@pytest.fixture
def settings(project):
    return {"excluded_folders": [str(project / "private")]}


@pytest.fixture
def audit(tmp_path):
    store = open_store(tmp_path / "audit_home")
    yield store
    store.db.close()


def key_of(folder):
    return hashlib.sha256(os.path.realpath(str(folder)).encode("utf-8")).hexdigest()[:12]


def session_id(folder):
    return f"{DAY}_{key_of(folder)}"


def event(folder, n, verb="ran", kind="action", obj=None, role="", program="make", **extra):
    """One line as the connectors write it, for the folder, numbered n."""
    line = {
        "harness": "wrappers",
        "harness_session_id": session_id(folder),
        "source_id": f"{n:032x}",
        "verb": verb,
        "kind": kind,
        "object": obj if obj is not None else f"make step{n}",
        "rationale": "",
        "role": role,
        "at": f"{DAY}T10:{n:02d}:00-07:00",
        "cwd": str(folder),
        "program": program,
    }
    line.update(extra)
    return line


def story_events(folder):
    """Four events, a call, the file it wrote, a git commit, and one from the events tool."""
    return [
        event(folder, 1, obj="make paper", exit_code=0, duration_s=1.5, files_scanned=4),
        event(folder, 2, verb="wrote", obj=str(folder / "paper.docx"), role="produced",
              by="make paper"),
        event(folder, 3, verb="committed", obj="git commit -m Add the paper",
              program="git", rationale="Add the paper"),
        event(folder, 4, verb="edited", obj="chapter2.docx", role="edited", program="word",
              rationale="tightened the second paragraph"),
    ]


def events_file(folder, lines, name=None):
    """Write the lines as the connectors would, one JSON line each, and give the file's path."""
    events = Path(os.environ["CONNECTIONS_HOME"]) / "events"
    events.mkdir(parents=True, exist_ok=True)
    path = events / ((name or session_id(folder)) + ".jsonl")
    path.write_bytes(lines_bytes(lines))
    return path


def lines_bytes(lines):
    return b"".join(
        (line if isinstance(line, str) else json.dumps(line, ensure_ascii=False)).encode("utf-8")
        + b"\n"
        for line in lines
    )


def stored_rows(store, table):
    cursor = store.db.execute(f"SELECT * FROM {table} ORDER BY rowid")
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def counts(store):
    return tuple(len(stored_rows(store, table)) for table in TABLES)


# The adapter.


def test_the_wrappers_adapter_is_registered_without_the_ai_flag():
    assert ADAPTERS["wrappers"] is wrappers
    assert wrappers.NAME == "wrappers"
    assert wrappers.AI is False
    for function in ("default_root", "list_sessions", "read_session", "parse_transcript"):
        assert callable(getattr(wrappers, function))


def test_the_default_root_is_the_events_folder_of_the_connections_home(homes, monkeypatch):
    assert wrappers.default_root() == homes / "connections_home" / "events"
    monkeypatch.delenv("CONNECTIONS_HOME")
    assert wrappers.default_root() == homes / "user" / ".workflow_connections" / "events"
    monkeypatch.setenv("CONNECTIONS_HOME", "")
    assert wrappers.default_root() == homes / "user" / ".workflow_connections" / "events"
    # The root is named, not made.
    assert not (homes / "user" / ".workflow_connections").exists()


def test_list_sessions_lists_each_events_file_with_its_id_and_size(project, tmp_path):
    first = events_file(project, story_events(project))
    other = tmp_path / "other"
    other.mkdir()
    second = events_file(other, [event(other, 1)])
    (first.parent / "notes.txt").write_text("not an events file")
    refs = wrappers.list_sessions(first.parent)
    assert sorted(refs, key=lambda r: r.location) == sorted(
        [
            capture.SessionRef(session_id(project), str(first), first.stat().st_size),
            capture.SessionRef(session_id(other), str(second), second.stat().st_size),
        ],
        key=lambda r: r.location,
    )
    assert wrappers.list_sessions(tmp_path / "missing") == []


def test_read_session_gives_the_file_as_one_session(project):
    path = events_file(project, story_events(project))
    session = wrappers.read_session(path)
    assert session.session_id == session_id(project)
    assert session.cwd == str(project)
    assert session.started_at == f"{DAY}T10:01:00-07:00"
    assert session.ended_at == f"{DAY}T10:04:00-07:00"
    assert session.transcript == path.read_bytes()
    assert session.tools == ["make", "git", "word"]
    assert [e["source_id"] for e in session.events] == [f"{n:032x}" for n in (1, 2, 3, 4)]
    # Each event holds the schema's fields only, as the file gives them.
    assert session.events[1] == {
        "harness": "wrappers",
        "harness_session_id": session_id(project),
        "source_id": f"{2:032x}",
        "verb": "wrote",
        "kind": "action",
        "object": str(project / "paper.docx"),
        "rationale": "",
        "role": "produced",
    }
    assert session.tool_calls == []


def test_parse_transcript_reads_the_stored_bytes_the_same_way(project):
    path = events_file(project, story_events(project))
    assert wrappers.parse_transcript(path.read_bytes()) == wrappers.read_session(path)


# Capture.


def test_a_file_is_stored_as_one_session_with_its_events_as_written(audit, project, settings):
    path = events_file(project, story_events(project))
    summary = capture_session(audit, "wrappers", path, settings)
    assert (summary.session_id, summary.excluded) == (session_id(project), False)
    assert (summary.sessions, summary.events, summary.transcripts) == (1, 4, 1)

    (row,) = stored_rows(audit, "sessions")
    assert row["harness"] == "wrappers"
    assert row["harness_session_id"] == session_id(project)
    assert row["project"] == str(project)
    assert row["started_at"] == f"{DAY}T10:01:00-07:00"
    assert row["ended_at"] == f"{DAY}T10:04:00-07:00"
    assert json.loads(row["tools"]) == ["make", "git", "word"]
    assert row["origin"] == "wrappers adapter"
    assert row["reason"] == "capture"
    assert row["session"] == session_id(project)
    assert "wrappers adapter version" in row["method"]
    assert "mechanical" not in row["method"]

    events = stored_rows(audit, "events")
    got = [(e["id"], e["ordinal"], e["verb"], e["kind"], e["object"], e["rationale"], e["role"])
           for e in events]
    assert got == [
        (f"{1:032x}", 1, "ran", "action", "make paper", "", ""),
        (f"{2:032x}", 2, "wrote", "action", str(project / "paper.docx"), "", "produced"),
        (f"{3:032x}", 3, "committed", "action", "git commit -m Add the paper",
         "Add the paper", ""),
        (f"{4:032x}", 4, "edited", "action", "chapter2.docx",
         "tightened the second paragraph", "edited"),
    ]
    assert {e["origin"] for e in events} == {"wrappers adapter"}

    (transcript,) = stored_rows(audit, "transcripts")
    data = path.read_bytes()
    assert transcript["file_sha256"] == hashlib.sha256(data).hexdigest()
    assert transcript["byte_size"] == len(data)
    assert (audit.files / transcript["file_sha256"]).read_bytes() == data


def test_capture_runs_no_mechanical_pass_on_the_events(audit, project, settings, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("the mechanical pass was run on wrapper events")

    monkeypatch.setattr(capture, "tag", refuse)
    path = events_file(project, story_events(project))
    assert capture_session(audit, "wrappers", path, settings).events == 4


def test_a_second_capture_adds_nothing(audit, project, settings):
    path = events_file(project, story_events(project))
    capture_session(audit, "wrappers", path, settings)
    before = counts(audit)
    summary = capture_session(audit, "wrappers", path, settings)
    assert (summary.sessions, summary.events, summary.transcripts) == (0, 0, 0)
    assert counts(audit) == before


def test_one_more_line_adds_one_event_and_a_superseding_session_row(audit, project, settings):
    lines = story_events(project)
    path = events_file(project, lines)
    capture_session(audit, "wrappers", path, settings)
    first = current(audit, "sessions")[0]
    events_file(project, lines + [event(project, 5, obj="make check", program="make")])
    summary = capture_session(audit, "wrappers", path, settings)
    assert (summary.sessions, summary.events, summary.transcripts) == (1, 1, 1)
    (latest,) = current(audit, "sessions")
    assert latest["supersedes"] == first["id"]
    assert latest["ended_at"] == f"{DAY}T10:05:00-07:00"
    events = session_events(audit, latest)
    assert [e["object"] for e in events][-1] == "make check"
    assert len(events) == 5


def test_a_file_from_an_excluded_folder_stores_nothing(audit, project, settings):
    private = project / "private" / "records"
    private.mkdir(parents=True)
    path = events_file(private, [event(private, 1), event(private, 2)])
    summary = capture_session(audit, "wrappers", path, settings)
    assert summary.excluded is True
    assert counts(audit) == (0, 0, 0)
    assert list(audit.files.iterdir()) == []


def test_a_bad_middle_line_refuses_the_file_and_names_the_line(audit, project, settings):
    lines = story_events(project)
    path = events_file(project, lines[:2] + ["{not json"] + lines[2:])
    with pytest.raises(ValueError) as refused:
        capture_session(audit, "wrappers", path, settings)
    assert "line 3" in str(refused.value)
    assert counts(audit) == (0, 0, 0)


def test_a_verb_outside_the_list_is_refused(audit, project, settings):
    lines = story_events(project)
    lines[1]["verb"] = "deleted"
    path = events_file(project, lines)
    with pytest.raises(ValueError) as refused:
        capture_session(audit, "wrappers", path, settings)
    assert "line 2" in str(refused.value)
    assert "verb" in str(refused.value)
    assert counts(audit) == (0, 0, 0)


@pytest.mark.parametrize("field", ["source_id", "object", "at", "cwd"])
def test_a_line_missing_a_field_is_refused(audit, project, settings, field):
    lines = story_events(project)
    del lines[2][field]
    path = events_file(project, lines)
    with pytest.raises(ValueError) as refused:
        capture_session(audit, "wrappers", path, settings)
    assert "line 3" in str(refused.value)
    assert field in str(refused.value)


def test_a_line_that_names_another_session_is_refused(audit, project, settings, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    lines = story_events(project)
    lines[2]["harness_session_id"] = session_id(other)
    path = events_file(project, lines)
    with pytest.raises(ValueError) as refused:
        capture_session(audit, "wrappers", path, settings)
    assert "line 3" in str(refused.value)
    assert counts(audit) == (0, 0, 0)


def test_a_line_that_names_another_folder_is_refused(audit, project, settings, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    lines = story_events(project)
    lines[3]["cwd"] = str(other)
    path = events_file(project, lines)
    with pytest.raises(ValueError) as refused:
        capture_session(audit, "wrappers", path, settings)
    assert "line 4" in str(refused.value)
    assert counts(audit) == (0, 0, 0)


def test_a_line_from_another_harness_is_refused(audit, project, settings):
    lines = story_events(project)
    lines[0]["harness"] = "claude_code"
    path = events_file(project, lines)
    with pytest.raises(ValueError) as refused:
        capture_session(audit, "wrappers", path, settings)
    assert "line 1" in str(refused.value)


def test_a_file_whose_name_is_not_its_session_is_refused(audit, project, settings):
    path = events_file(project, story_events(project), name=f"{DAY}_000000000000")
    with pytest.raises(ValueError) as refused:
        capture_session(audit, "wrappers", path, settings)
    assert "line 1" in str(refused.value)
    assert counts(audit) == (0, 0, 0)


def test_an_unfinished_last_line_waits_for_the_next_capture(audit, project, settings):
    lines = story_events(project)
    whole = lines_bytes(lines)
    finished = lines_bytes(lines[:3])
    path = events_file(project, lines[:3])
    # The fourth line is being written, so it has no line break yet.
    path.write_bytes(whole[:-1])
    summary = capture_session(audit, "wrappers", path, settings)
    assert summary.events == 3
    (transcript,) = stored_rows(audit, "transcripts")
    assert (audit.files / transcript["file_sha256"]).read_bytes() == finished

    path.write_bytes(whole)
    summary = capture_session(audit, "wrappers", path, settings)
    assert summary.events == 1
    assert len(stored_rows(audit, "events")) == 4
    latest = stored_rows(audit, "transcripts")[-1]
    assert (audit.files / latest["file_sha256"]).read_bytes() == whole


def test_an_unfinished_last_line_that_is_not_yet_json_is_not_refused(audit, project, settings):
    lines = story_events(project)
    path = events_file(project, lines[:2])
    path.write_bytes(path.read_bytes() + b'{"harness": "wrap')
    assert capture_session(audit, "wrappers", path, settings).events == 2


def test_the_stored_transcript_reads_back_through_the_adapter(audit, project, settings):
    path = events_file(project, story_events(project))
    capture_session(audit, "wrappers", path, settings)
    row = current_session(audit, "wrappers", session_id(project))
    assert read_stored(audit, row) == wrappers.read_session(path)


def test_wrapper_sessions_are_not_due_for_the_model_pass(audit, project, settings):
    path = events_file(project, story_events(project))
    capture_session(audit, "wrappers", path, settings)
    assert due(audit) == []


# The sweep and the command line.


def test_the_sweep_finds_the_events_files_in_the_connections_home(audit, project, settings, tmp_path):
    events_file(project, story_events(project))
    summary = sweep(audit, settings, tmp_path / "audit_home", harnesses=["wrappers"])
    assert (summary.captured, summary.failed) == (1, ())
    # The wrappers' sessions take no snapshot of working files.
    assert current(audit, "snapshots") == []
    again = sweep(audit, settings, tmp_path / "audit_home", harnesses=["wrappers"])
    assert (again.captured, again.unchanged) == (0, 1)


def test_the_sweep_of_every_harness_includes_the_wrappers(audit, project, settings, tmp_path):
    events_file(project, story_events(project))
    summary = sweep(audit, settings, tmp_path / "audit_home")
    assert summary.captured == 1
    assert current(audit, "sessions")[0]["harness"] == "wrappers"


def run_audit_layer(*args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "audit_layer"] + list(args),
        cwd=str(cwd or ROOT), env=dict(os.environ), capture_output=True, text=True,
    )


def test_capture_harness_wrappers_on_the_command_line(project, capsys):
    assert main(["init"]) == 0
    path = events_file(project, story_events(project))
    capsys.readouterr()
    assert main(["capture", "--harness", "wrappers", str(path)]) == 0
    db = sqlite3.connect(str(Path(os.environ["AUDIT_HOME"]) / "audit.sqlite"))
    try:
        assert db.execute("SELECT count(*) FROM events").fetchone() == (4,)
    finally:
        db.close()


def test_end_to_end_a_wrapped_call_is_captured_through_commands_only(project):
    done = run_audit_layer("init")
    assert done.returncode == 0, done.stderr
    wrapped = subprocess.run(
        [sys.executable, "-m", "connections", "wrap", "--",
         sys.executable, "-c", "open('o.txt', 'w')"],
        cwd=str(project), env=dict(os.environ, PYTHONPATH=str(ROOT)),
        capture_output=True, text=True,
    )
    assert wrapped.returncode == 0, wrapped.stderr
    (path,) = sorted((Path(os.environ["CONNECTIONS_HOME"]) / "events").glob("*.jsonl"))
    done = run_audit_layer("capture", "--harness", "wrappers", str(path))
    assert done.returncode == 0, done.stderr
    db = sqlite3.connect(str(Path(os.environ["AUDIT_HOME"]) / "audit.sqlite"))
    try:
        rows = db.execute("SELECT verb, kind, object, role FROM events ORDER BY ordinal").fetchall()
        (harness,) = db.execute("SELECT harness FROM sessions").fetchone()
    finally:
        db.close()
    assert harness == "wrappers"
    assert [row[0] for row in rows] == ["ran", "wrote"]
    assert rows[0][1] == "action"
    assert rows[0][2].endswith("-c open('o.txt', 'w')")
    assert rows[1][1:] == ("action", os.path.realpath(str(project / "o.txt")), "produced")
