"""Step F7. Builds and sessions in the organizer's inventory.

Builds are read from each product's BUILDS.md by its header row. Sessions
are read from the audit database opened read only, from the sessions and
events tables only (track F choice 18, reconciliation item 4). Builds of the
fixture are made with ospipe build through the layer runner, and the real
audit layer runs through the runner with AUDIT_HOME in a temporary folder.

Run from the repository root as python3 -m pytest -q features/tests.
"""
import datetime
import hashlib
import io
import json
import os
import shutil
import sqlite3
from pathlib import Path

import pytest

from features import cli, layers
from features.organizer import inventory
from features.organizer import sessions as organizer_sessions
from features.setup import system
from features.tests import helpers
from features.tests.test_system_setup import fake_detector

ROOT = helpers.ROOT
STORY_PROJECT = ROOT / "examples" / "test_story" / "project"
NOW = datetime.datetime(2026, 10, 29, 9, 30, 0, tzinfo=datetime.timezone.utc)
LATER = datetime.datetime(2026, 10, 30, 14, 0, 0, tzinfo=datetime.timezone.utc)
BUILD_ARGS = ["build", "--manuscript", "manuscript.md", "--manifest", "numbers.yml",
              "--tables-dir", ".", "--bib", "refs.bib", "--builds-dir", "builds/manuscript",
              "--purpose", "draft"]
BUILD_FIELDS = ["item", "product", "version", "date", "sha256", "purpose", "verification", "runs",
                "file", "file_ok"]
SESSION_FIELDS = ["harness", "harness_session_id", "ran_here", "started_at", "ended_at", "tools",
                  "files"]


@pytest.fixture(autouse=True)
def private_home(tmp_path, monkeypatch):
    """Point HOME and both home variables at temporary folders, so nothing real is touched."""
    home = tmp_path / "user_home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("AUDIT_HOME", str(tmp_path / "env_audit_home"))
    monkeypatch.setenv("FEATURES_HOME", str(tmp_path / "env_features_home"))
    return home


def sha(path):
    return hashlib.sha256(Path(str(path)).read_bytes()).hexdigest()


def ospipe_build(project):
    done = layers.run_layer("ospipe", BUILD_ARGS, root=str(ROOT), cwd=str(project))
    assert done.returncode == 0, done.stderr
    return done


def builds_of(project):
    project_map = inventory.read_map(str(project), root=str(ROOT))
    return organizer_sessions.read_builds(str(project), project_map)


def ledger(project, rows, header):
    folder = project / "builds" / "manuscript"
    folder.mkdir(parents=True, exist_ok=True)
    lines = ["# Builds", "", "| " + " | ".join(header) + " |",
             "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    (folder / "BUILDS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return folder


def run_command(argv):
    out = io.StringIO()
    err = io.StringIO()
    parser, _ = cli._parser()
    options = parser.parse_args(argv)
    code = options.run(options, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def audit(args, audit_home):
    done = layers.run_layer("audit_layer", args, root=str(ROOT),
                            env={"AUDIT_HOME": str(audit_home)})
    assert done.returncode == 0, done.stderr
    return done


def story_project(tmp_path):
    target = tmp_path / "story"
    shutil.copytree(str(STORY_PROJECT), str(target),
                    ignore=shutil.ignore_patterns("__pycache__", "builds", ".organizer"))
    return target


def captured_story(tmp_path, audit_home=None):
    """A copy of the story project and an audit home holding the story session."""
    project = story_project(tmp_path)
    audit_home = audit_home or (tmp_path / "audit")
    if not (Path(str(audit_home)) / "settings.yaml").is_file():
        audit(["init"], audit_home)
    session_file = helpers.story_session(project, tmp_path / "sessions" / "story_session.jsonl")
    audit(["capture", "--harness", "claude_code", str(session_file)], audit_home)
    return project, Path(str(audit_home)) / "audit.sqlite"


# The helpers.

def test_copy_fixture_copies_the_named_fixture(tmp_path):
    project = helpers.copy_fixture("organizer_project", tmp_path)
    assert project == tmp_path / "organizer_project"
    assert (project / "manuscript.md").is_file()
    assert (project / "Makefile").is_file()


def test_make_audit_db_has_the_slices_columns(tmp_path):
    path = helpers.make_audit_db(tmp_path / "a.sqlite", [{"harness": "claude_code"}],
                                 [{"session_row_id": "sessions-0001", "ordinal": 1}])
    db = sqlite3.connect(str(path))
    try:
        assert [row[1] for row in db.execute("PRAGMA table_info(sessions)")] == list(
            helpers.SESSION_TABLE)
        assert [row[1] for row in db.execute("PRAGMA table_info(events)")] == list(
            helpers.EVENT_TABLE)
        assert db.execute("SELECT id, harness FROM sessions").fetchall() == [
            ("sessions-0001", "claude_code")]
    finally:
        db.close()


def test_make_audit_db_matches_a_store_made_by_audit_layer_init(tmp_path):
    audit(["init"], tmp_path / "audit")
    db = sqlite3.connect(str(tmp_path / "audit" / "audit.sqlite"))
    try:
        for table, columns in (("sessions", helpers.SESSION_TABLE),
                               ("events", helpers.EVENT_TABLE),
                               ("transcripts", helpers.TRANSCRIPT_TABLE)):
            assert tuple(row[1] for row in db.execute("PRAGMA table_info(%s)" % table)) == columns
    finally:
        db.close()


def test_the_reader_names_only_columns_the_store_has(tmp_path):
    assert set(organizer_sessions.SESSION_COLUMNS) <= set(helpers.SESSION_TABLE)
    assert set(organizer_sessions.EVENT_COLUMNS) <= set(helpers.EVENT_TABLE)
    assert "session_row_id" in organizer_sessions.EVENT_COLUMNS
    assert "supersedes" in organizer_sessions.SESSION_COLUMNS


def test_story_session_sets_the_project_path(tmp_path):
    project = story_project(tmp_path)
    out = helpers.story_session(project, tmp_path / "out" / "s.jsonl")
    text = out.read_text(encoding="utf-8")
    assert helpers.PLACEHOLDER not in text
    assert os.path.realpath(str(project)) + "/manuscript.md" in text
    assert helpers.STORY_SESSION_ID in text


# Builds.

def test_two_builds_give_two_rows_with_their_files_matching(tmp_path):
    project = helpers.copy_fixture("organizer_project", tmp_path)
    ospipe_build(project)
    ospipe_build(project)
    builds, problems = builds_of(project)
    assert problems == []
    assert [build["item"] for build in builds] == ["manuscript/v001", "manuscript/v002"]
    for build, version in zip(builds, ("v001", "v002")):
        assert list(build) == BUILD_FIELDS
        assert build["product"] == "manuscript"
        assert build["version"] == version
        assert build["file"] == "builds/manuscript/%s.docx" % version
        assert build["sha256"] == sha(project / build["file"])
        assert build["file_ok"] is True
        assert build["purpose"] == "draft"
        assert build["verification"].startswith("unverified")
        assert build["runs"] == "-"
        assert len(build["date"]) == 10


def test_a_changed_byte_in_a_build_gives_file_ok_false_and_a_problem(tmp_path):
    project = helpers.copy_fixture("organizer_project", tmp_path)
    ospipe_build(project)
    ospipe_build(project)
    docx = project / "builds" / "manuscript" / "v001.docx"
    data = bytearray(docx.read_bytes())
    data[-1] = (data[-1] + 1) % 256
    docx.write_bytes(bytes(data))
    builds, problems = builds_of(project)
    assert [build["file_ok"] for build in builds] == [False, True]
    assert len(problems) == 1
    assert "manuscript/v001" in problems[0]


def test_a_ledgered_file_that_is_missing_is_a_problem(tmp_path):
    project = helpers.copy_fixture("organizer_project", tmp_path)
    ospipe_build(project)
    (project / "builds" / "manuscript" / "v001.docx").unlink()
    builds, problems = builds_of(project)
    assert builds[0]["file_ok"] is False
    assert builds[0]["file"] is None
    assert len(problems) == 1
    assert "manuscript/v001" in problems[0] and "missing" in problems[0]


def test_a_build_file_with_no_row_is_a_problem(tmp_path):
    project = helpers.copy_fixture("organizer_project", tmp_path)
    ospipe_build(project)
    shutil.copy(str(project / "builds" / "manuscript" / "v001.docx"),
                str(project / "builds" / "manuscript" / "v002.html"))
    builds, problems = builds_of(project)
    assert [build["item"] for build in builds] == ["manuscript/v001"]
    assert len(problems) == 1
    assert "v002.html" in problems[0] and "no row" in problems[0]


def test_a_hand_written_seven_column_ledger_parses(tmp_path):
    project = helpers.copy_fixture("organizer_project", tmp_path)
    folder = ledger(project, [], ["version"])
    (folder / "v001.docx").write_bytes(b"first build")
    ledger(project, [["v001", "2026-10-01", "-", sha(folder / "v001.docx"), "draft one", "-",
                      "no"]],
           ["version", "date", "git", "sha256", "purpose", "baseline", "reviewed"])
    builds, problems = builds_of(project)
    assert problems == []
    assert builds == [{
        "item": "manuscript/v001", "product": "manuscript", "version": "v001",
        "date": "2026-10-01", "sha256": sha(folder / "v001.docx"), "purpose": "draft one",
        "verification": "-", "runs": "-", "file": "builds/manuscript/v001.docx",
        "file_ok": True}]


def test_a_nine_column_rows_verification_and_runs_are_read(tmp_path):
    project = helpers.copy_fixture("organizer_project", tmp_path)
    folder = ledger(project, [], ["version"])
    (folder / "v001.html").write_bytes(b"<html>slides</html>")
    ledger(project, [["v001", "2026-10-02", "-", sha(folder / "v001.html"), "talk", "-", "no",
                      "verified", "citations=run-7"]],
           ["version", "date", "git", "sha256", "purpose", "baseline", "reviewed",
            "verification", "runs"])
    builds, problems = builds_of(project)
    assert problems == []
    assert builds[0]["verification"] == "verified"
    assert builds[0]["runs"] == "citations=run-7"
    assert builds[0]["file"] == "builds/manuscript/v001.html"
    assert builds[0]["file_ok"] is True


def test_a_project_with_no_builds_has_no_rows_and_no_problems(tmp_path):
    project = helpers.copy_fixture("organizer_project", tmp_path)
    assert builds_of(project) == ([], [])


def test_reading_builds_writes_nothing(tmp_path):
    project = helpers.copy_fixture("organizer_project", tmp_path)
    ospipe_build(project)
    before = dict((path, sha(path)) for path in (project / "builds").rglob("*") if path.is_file())
    builds_of(project)
    after = dict((path, sha(path)) for path in (project / "builds").rglob("*") if path.is_file())
    assert after == before


# Sessions, from a database made by hand.

def sample_db(tmp_path):
    """A database holding sessions in the project, a sibling, and the parent folder.

    A ran in a sibling at first and in the project at last, and its first
    row's event edited the manuscript. B ran in the project at first and in
    the sibling at last, with no events. C ran in the sibling and edited a
    file there. D ran in the parent and edited a project file, and also read
    one. E ran in the parent and only read a project file.
    """
    work = tmp_path / "work"
    project = helpers.copy_fixture("organizer_project", work)
    os.rename(str(project), str(work / "project"))
    project = work / "project"
    sibling = work / "project2"
    sibling.mkdir()
    real = os.path.realpath(str(project))
    sibling_real = os.path.realpath(str(sibling))
    parent = os.path.realpath(str(work))

    def row(row_id, hsid, folder, supersedes=None, tools=("Edit",)):
        return {"id": row_id, "harness": "claude_code", "harness_session_id": hsid,
                "project": folder, "started_at": "2026-10-20T10:00:00Z",
                "ended_at": "2026-10-20T11:00:00Z", "tools": json.dumps(list(tools)),
                "supersedes": supersedes}

    def event(event_id, row_id, ordinal, verb, path, role):
        return {"id": event_id, "session_row_id": row_id, "ordinal": ordinal, "verb": verb,
                "kind": "action", "object": path, "role": role}

    sessions = [
        row("a1", "A", sibling_real),
        row("b1", "B", real),
        row("c1", "C", sibling_real),
        row("d1", "D", parent, tools=("Read", "Edit")),
        row("e1", "E", parent, tools=("Read",)),
        row("a2", "A", real, supersedes="a1", tools=("Edit", "Write")),
        row("b2", "B", sibling_real, supersedes="b1"),
    ]
    events = [
        event("ea1", "a1", 1, "edited", os.path.join(real, "manuscript.md"), "edited"),
        event("ec1", "c1", 1, "edited", os.path.join(sibling_real, "x.md"), "edited"),
        event("ed1", "d1", 1, "searched", os.path.join(real, "raw.csv"), "read"),
        event("ed2", "d1", 2, "edited", os.path.join(real, "stray.txt"), "edited"),
        event("ed3", "d1", 3, "wrote", os.path.join(real, "gone.md"), "produced"),
        event("ee1", "e1", 1, "searched", os.path.join(real, "manuscript.md"), "read"),
    ]
    db = helpers.make_audit_db(tmp_path / "audit" / "audit.sqlite", sessions, events)
    return project, db


def test_a_superseded_session_row_is_ignored_while_its_events_still_count(tmp_path):
    project, db = sample_db(tmp_path)
    found = dict((item["harness_session_id"], item)
                 for item in organizer_sessions.read_sessions(str(db), str(project)))
    assert "B" not in found
    assert list(found["A"]) == SESSION_FIELDS
    assert found["A"]["ran_here"] is True
    assert found["A"]["tools"] == ["Edit", "Write"]
    assert found["A"]["files"] == [
        {"path": "manuscript.md", "role": "edited", "verb": "edited", "present": True}]


def test_a_session_in_a_sibling_folder_is_left_out(tmp_path):
    project, db = sample_db(tmp_path)
    found = [item["harness_session_id"]
             for item in organizer_sessions.read_sessions(str(db), str(project))]
    assert "C" not in found


def test_a_session_in_the_parent_that_edited_a_project_file_is_listed(tmp_path):
    project, db = sample_db(tmp_path)
    found = dict((item["harness_session_id"], item)
                 for item in organizer_sessions.read_sessions(str(db), str(project)))
    assert sorted(found) == ["A", "D"]
    assert found["D"]["ran_here"] is False
    assert found["D"]["harness"] == "claude_code"
    assert found["D"]["started_at"] == "2026-10-20T10:00:00Z"
    assert found["D"]["ended_at"] == "2026-10-20T11:00:00Z"
    assert found["D"]["files"] == [
        {"path": "gone.md", "role": "produced", "verb": "wrote", "present": False},
        {"path": "stray.txt", "role": "edited", "verb": "edited", "present": True}]


def test_paths_are_compared_as_real_paths(tmp_path):
    project, db = sample_db(tmp_path)
    link = tmp_path / "link_to_project"
    os.symlink(str(project), str(link))
    found = [item["harness_session_id"]
             for item in organizer_sessions.read_sessions(str(db), str(link))]
    assert sorted(found) == ["A", "D"]


def test_a_missing_database_gives_no_sessions_and_a_message(tmp_path):
    project = helpers.copy_fixture("organizer_project", tmp_path)
    absent = tmp_path / "audit" / "audit.sqlite"
    assert organizer_sessions.read_sessions(str(absent), str(project)) == []
    assert not absent.exists()
    found = inventory.build_inventory(str(project), NOW, root=str(ROOT), audit_db=str(absent))
    assert found["sessions"] == []
    assert any(str(absent) in message for message in found["messages"])


def test_the_reader_reads_only_the_sessions_and_events_tables(tmp_path, monkeypatch):
    project, db = sample_db(tmp_path)
    tables = set()
    calls = []
    real_connect = sqlite3.connect

    def watched(*args, **kwargs):
        calls.append((args, kwargs))
        connection = real_connect(*args, **kwargs)

        def authorizer(action, first, second, database, source):
            if action == sqlite3.SQLITE_READ:
                tables.add(first)
            return sqlite3.SQLITE_OK

        connection.set_authorizer(authorizer)
        return connection

    monkeypatch.setattr(organizer_sessions.sqlite3, "connect", watched)
    assert organizer_sessions.read_sessions(str(db), str(project))
    assert tables == {"sessions", "events"}
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[0].startswith("file:") and args[0].endswith("?mode=ro")
    assert kwargs.get("uri") is True


def test_read_sessions_opens_through_the_read_only_connection(tmp_path, monkeypatch):
    project, db = sample_db(tmp_path)
    opened = []
    real_open = organizer_sessions.connect_read_only

    def watched(path):
        opened.append(path)
        return real_open(path)

    monkeypatch.setattr(organizer_sessions, "connect_read_only", watched)
    assert organizer_sessions.read_sessions(str(db), str(project))
    assert opened == [os.path.abspath(str(db))]


@pytest.mark.parametrize("name", ["Project #2", "q?mark", "100% done", "with space",
                                  "all #? % of it"])
def test_an_audit_home_with_uri_characters_in_its_name_is_read_and_left_alone(tmp_path, name):
    project, db = sample_db(tmp_path)
    parent = tmp_path / "homes"
    parent.mkdir()
    audit_home = parent / name
    audit_home.mkdir()
    moved = audit_home / "audit.sqlite"
    shutil.move(str(db), str(moved))
    listed = sorted(os.listdir(str(parent)))
    inside = sorted(os.listdir(str(audit_home)))
    before = sha(moved)
    found = [item["harness_session_id"]
             for item in organizer_sessions.read_sessions(str(moved), str(project))]
    assert sorted(found) == ["A", "D"]
    assert sorted(os.listdir(str(parent))) == listed
    assert sorted(os.listdir(str(audit_home))) == inside
    assert sha(moved) == before
    connection = organizer_sessions.connect_read_only(str(moved))
    try:
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("INSERT INTO sessions (id) VALUES ('new')")
    finally:
        connection.close()
    assert sorted(os.listdir(str(parent))) == listed


def test_a_relative_event_path_joins_the_project_of_its_own_session_row(tmp_path):
    """F ran in the project and produced notes.md by a relative path, then a
    correction moved F's project to the sibling. The event still names the
    project's notes.md. G ran in the sibling and wrote x.md by a relative
    path, then a correction moved G to the project, so x.md is the sibling's.
    """
    work = tmp_path / "work"
    project = work / "project"
    sibling = work / "project2"
    project.mkdir(parents=True)
    sibling.mkdir()
    (project / "notes.md").write_text("notes\n", encoding="utf-8")
    real = os.path.realpath(str(project))
    sibling_real = os.path.realpath(str(sibling))

    def row(row_id, hsid, folder, supersedes=None):
        return {"id": row_id, "harness": "claude_code", "harness_session_id": hsid,
                "project": folder, "started_at": "2026-10-20T10:00:00Z",
                "ended_at": "2026-10-20T11:00:00Z", "tools": json.dumps(["Write"]),
                "supersedes": supersedes}

    sessions = [row("f1", "F", real), row("g1", "G", sibling_real),
                row("f2", "F", sibling_real, supersedes="f1"),
                row("g2", "G", real, supersedes="g1")]
    events = [
        {"id": "ef1", "session_row_id": "f1", "ordinal": 1, "verb": "wrote", "kind": "action",
         "object": "notes.md", "role": "produced"},
        {"id": "eg1", "session_row_id": "g1", "ordinal": 1, "verb": "wrote", "kind": "action",
         "object": "x.md", "role": "produced"},
    ]
    db = helpers.make_audit_db(tmp_path / "audit" / "audit.sqlite", sessions, events)
    found = dict((item["harness_session_id"], item)
                 for item in organizer_sessions.read_sessions(str(db), str(project)))
    assert found["F"]["ran_here"] is False
    assert found["F"]["files"] == [
        {"path": "notes.md", "role": "produced", "verb": "wrote", "present": True}]
    assert found["G"]["ran_here"] is True
    assert found["G"]["files"] == []


def test_the_reader_opens_the_database_read_only(tmp_path):
    project, db = sample_db(tmp_path)
    connection = organizer_sessions.connect_read_only(str(db))
    try:
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("INSERT INTO sessions (id) VALUES ('new')")
    finally:
        connection.close()


# The inventory with builds and sessions.

def test_the_inventory_gains_builds_problems_and_sessions(tmp_path):
    project, db = sample_db(tmp_path)
    ospipe_build(project)
    found = inventory.build_inventory(str(project), NOW, root=str(ROOT), audit_db=str(db))
    assert list(found) == ["schema", "schema_version", "inventory_id", "project", "scanned_at",
                           "map", "files", "builds", "build_problems", "sessions", "messages"]
    assert [build["item"] for build in found["builds"]] == ["manuscript/v001"]
    assert found["build_problems"] == []
    assert [item["harness_session_id"] for item in found["sessions"]] == ["A", "D"]
    files = dict((entry["path"], entry) for entry in found["files"])
    assert files["manuscript.md"]["sessions"] == ["A"]
    assert files["stray.txt"]["sessions"] == ["D"]
    assert files["raw.csv"]["sessions"] == []
    assert found["messages"] == []


def test_the_inventory_id_covers_build_rows(tmp_path):
    project = helpers.copy_fixture("organizer_project", tmp_path)
    ospipe_build(project)
    first = inventory.build_inventory(str(project), NOW, root=str(ROOT))
    second = inventory.build_inventory(str(project), LATER, root=str(ROOT))
    assert second["inventory_id"] == first["inventory_id"]
    ospipe_build(project)
    third = inventory.build_inventory(str(project), NOW, root=str(ROOT))
    assert third["inventory_id"] != first["inventory_id"]


def test_the_inventory_id_covers_session_ids(tmp_path):
    project, db = sample_db(tmp_path)
    with_sessions = inventory.build_inventory(str(project), NOW, root=str(ROOT), audit_db=str(db))
    again = inventory.build_inventory(str(project), LATER, root=str(ROOT), audit_db=str(db))
    without = inventory.build_inventory(str(project), NOW, root=str(ROOT))
    assert again["inventory_id"] == with_sessions["inventory_id"]
    assert without["inventory_id"] != with_sessions["inventory_id"]


# The real audit layer on the story session.

def test_the_story_session_is_listed_with_its_files(tmp_path):
    project, db = captured_story(tmp_path)
    before = sha(db)
    found = inventory.build_inventory(str(project), NOW, root=str(ROOT), audit_db=str(db))
    assert sha(db) == before
    story = [item for item in found["sessions"]
             if item["harness_session_id"] == helpers.STORY_SESSION_ID]
    assert len(story) == 1
    story = story[0]
    assert story["harness"] == "claude_code"
    assert story["ran_here"] is True
    files = dict((item["path"], item) for item in story["files"])
    assert files["manuscript.md"]["role"] == "edited"
    assert files["source_notes.md"]["role"] == "produced"
    assert files["source_notes.md"]["present"] == (project / "source_notes.md").exists()
    assert files["manuscript.md"]["present"] is True
    entries = dict((entry["path"], entry) for entry in found["files"])
    assert helpers.STORY_SESSION_ID in entries["manuscript.md"]["sessions"]


def test_present_follows_whether_the_story_project_holds_the_file(tmp_path):
    project, db = captured_story(tmp_path)
    assert not (project / "source_notes.md").exists()
    found = organizer_sessions.read_sessions(str(db), str(project))
    files = dict((item["path"], item) for item in found[0]["files"])
    assert files["source_notes.md"]["present"] is False
    (project / "source_notes.md").write_text("# Source notes\n", encoding="utf-8")
    found = organizer_sessions.read_sessions(str(db), str(project))
    files = dict((item["path"], item) for item in found[0]["files"])
    assert files["source_notes.md"]["present"] is True


def test_a_write_through_the_readers_connection_fails_on_a_real_store(tmp_path):
    project, db = captured_story(tmp_path)
    before = sha(db)
    connection = organizer_sessions.connect_read_only(str(db))
    try:
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("DELETE FROM sessions")
    finally:
        connection.close()
    assert sha(db) == before


# The command.

def make_home(tmp_path):
    home = tmp_path / "features_home"
    given = {"scholar_name": "Test Scholar", "excluded_folders": [], "citation_export": ""}
    result = system.run_system_setup(str(home), str(tmp_path / "audit_home"), given,
                                     str(ROOT), NOW, detector=fake_detector())
    assert result.ready
    return home


def test_scan_reads_the_audit_home_from_system_yaml(tmp_path):
    home = make_home(tmp_path)
    project, db = captured_story(tmp_path, audit_home=tmp_path / "audit_home")
    before = sha(db)
    code, out, err = run_command(["organize", "scan", str(project), "--home", str(home)])
    assert code == 0, err
    assert sha(db) == before
    written = json.loads((project / ".organizer" / "inventory.json").read_text(encoding="utf-8"))
    assert [item["harness_session_id"] for item in written["sessions"]] == [
        helpers.STORY_SESSION_ID]
    assert "Sessions 1" in out


def test_scan_prints_the_builds_and_their_problems(tmp_path):
    home = make_home(tmp_path)
    project = helpers.copy_fixture("organizer_project", tmp_path)
    ospipe_build(project)
    ospipe_build(project)
    (project / "builds" / "manuscript" / "v002.docx").write_bytes(b"changed")
    code, out, err = run_command(["organize", "scan", str(project), "--home", str(home)])
    assert code == 0, err
    assert "Builds 2" in out
    assert "manuscript/v002" in out


def test_scan_with_no_audit_database_lists_no_sessions_and_says_so(tmp_path):
    home = make_home(tmp_path)
    (tmp_path / "audit_home" / "audit.sqlite").unlink()
    project = helpers.copy_fixture("organizer_project", tmp_path)
    code, out, err = run_command(["organize", "scan", str(project), "--home", str(home)])
    assert code == 0, err
    written = json.loads((project / ".organizer" / "inventory.json").read_text(encoding="utf-8"))
    assert written["sessions"] == []
    assert "audit.sqlite" in out
    assert not (tmp_path / "audit_home" / "audit.sqlite").exists()
