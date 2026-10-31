"""Tests for capture on demand with excluded folders (plan Step 5).

Appendix A2.4 "Capture" keeps each transcript unchanged, A6 and A2.6 say
sessions run in a folder the scholar excludes are never recorded, and Figure A4
says capture is safe to repeat. The sessions are the test story's two
synthetic Claude Code session files, whose folder token {{PROJECT}} is replaced
with a temporary folder. No real session file is read, nothing here calls a
model or the network, and every test runs with its home folder inside a
temporary folder, so no test reaches the real ~/.audit_layer. Run from the
repository root with python3 -m pytest -q audit_layer/tests.
"""
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import audit_layer.capture as capture  # noqa: E402
import audit_layer.settings as settings_module  # noqa: E402
from audit_layer.capture import Summary, capture_file, claude_code  # noqa: E402
from audit_layer.cli import main  # noqa: E402
from audit_layer.settings import (  # noqa: E402
    SettingsError,
    audit_home,
    excluded,
    ignores_case,
    read_settings,
)
from audit_layer.store import current, open_store  # noqa: E402
from audit_layer.tagging import mechanical  # noqa: E402

SESSIONS = ROOT / "examples" / "test_story" / "sessions" / "claude_code"
STORY_SESSION = SESSIONS / "story_session.jsonl"
EXCLUDED_SESSION = SESSIONS / "excluded_session.jsonl"
TOKEN = "{{PROJECT}}"

STORY_ID = "5f3c0413-2a7d-4b9e-8c61-a0d4e7b2c913"
EXCLUDED_ID = "9b1e0414-6c3a-4f2d-b8e5-71d2a9c4f086"

TABLES = ("sessions", "events", "transcripts")
PROVENANCE = ("session", "origin", "method", "reason")
SESSION_FIELDS = ("harness", "harness_session_id", "project", "started_at", "ended_at", "tools")
EVENT_FIELDS = ("id", "ordinal", "verb", "kind", "object", "rationale", "role")

# The story session's two commands, as its file holds them.
STORY_CHECK = (
    "python3 -m ospipe check --manuscript manuscript.md --manifest numbers.yml"
    " --tables-dir . | tail -n 3"
)
STORY_COMMIT = (
    "git add manuscript.md source_notes.md && git commit"
    ' -m "Add two findings on volunteer exit after the sentence on fit"'
)


def expected_events(project):
    """The story's six tool calls as capture should store them, written by hand.

    Each event's id is the harness's own id for its tool call.
    """
    manuscript = str(project / "manuscript.md")
    notes = str(project / "source_notes.md")
    rows = [
        ("toolu_story_01_read", "searched", "observation", manuscript, "read"),
        ("toolu_story_02_edit", "edited", "action", manuscript, "edited"),
        ("toolu_story_03_edit", "edited", "action", manuscript, "edited"),
        ("toolu_story_04_write", "wrote", "action", notes, "produced"),
        ("toolu_story_05_bash", "verified", "observation", STORY_CHECK, ""),
        ("toolu_story_06_bash", "committed", "action", STORY_COMMIT, ""),
    ]
    return [
        {
            "id": row_id,
            "ordinal": ordinal,
            "verb": verb,
            "kind": kind,
            "object": object_,
            "rationale": "",
            "role": role,
        }
        for ordinal, (row_id, verb, kind, object_, role) in enumerate(rows, start=1)
    ]


def capture_provenance(session_id=STORY_ID):
    """The provenance every row capture writes carries (plan Step 5)."""
    return {
        "session": session_id,
        "origin": "claude_code adapter",
        "method": "claude_code adapter version {}, mechanical tagging version {}".format(
            claude_code.VERSION, mechanical.VERSION
        ),
        "reason": "capture",
    }


def lines_of(source, project):
    """The session file's records as lines of text, with the token replaced by project."""
    text = source.read_text(encoding="utf-8")
    text = text.replace(TOKEN, json.dumps(str(project))[1:-1])
    return [line for line in text.split("\n") if line]


def write_session(path, lines):
    """Write the lines as a JSON Lines file, each ending in a newline."""
    path.write_bytes("".join(line + "\n" for line in lines).encode("utf-8"))
    return path


def settings_for(*folders):
    return {"excluded_folders": [str(folder) for folder in folders]}


def stored_rows(db, table):
    """Rows as the database holds them, superseded or not, in the order written."""
    cursor = db.execute(f"SELECT * FROM {table} ORDER BY rowid")
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def all_rows(db):
    return {table: stored_rows(db, table) for table in TABLES}


def kept_files(store):
    return sorted(p.name for p in store.files.iterdir())


def pick(row, names):
    return {name: row[name] for name in names}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


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
    """The folder the story session ran in."""
    folder = tmp_path / "project"
    folder.mkdir()
    return folder


@pytest.fixture
def story(tmp_path, project):
    """The story session file with its folder token replaced by project."""
    return write_session(tmp_path / "story_session.jsonl", lines_of(STORY_SESSION, project))


@pytest.fixture
def excluded_story(tmp_path, project):
    """The session run in project/excluded_folder."""
    return write_session(
        tmp_path / "excluded_session.jsonl", lines_of(EXCLUDED_SESSION, project)
    )


@pytest.fixture
def audit(tmp_path):
    store = open_store(tmp_path / "audit_home")
    yield store
    store.db.close()


# The story session is stored with its events, tools, start and end, and its
# transcript byte for byte.


def test_the_story_session_is_stored_with_its_events_tools_times_and_transcript(
    audit, story, project
):
    summary = capture_file(audit, story, settings_for(project / "excluded_folder"))
    assert summary == Summary(
        path=str(story), session_id=STORY_ID, excluded=False, sessions=1, events=6, transcripts=1
    )

    sessions = current(audit, "sessions")
    assert len(sessions) == 1
    session = sessions[0]
    assert pick(session, SESSION_FIELDS) == {
        "harness": "claude_code",
        "harness_session_id": STORY_ID,
        # A session's project is the folder it ran in (plan choice 4).
        "project": str(project),
        "started_at": "2026-10-21T14:02:05.112Z",
        "ended_at": "2026-10-21T14:02:46.009Z",
        "tools": ["Read", "Edit", "Write", "Bash"],
    }
    assert session["supersedes"] is None

    events = current(audit, "events")
    assert [pick(event, EVENT_FIELDS) for event in events] == expected_events(project)
    assert {event["session_row_id"] for event in events} == {session["id"]}
    assert {event["supersedes"] for event in events} == {None}

    data = story.read_bytes()
    transcripts = current(audit, "transcripts")
    assert len(transcripts) == 1
    assert pick(transcripts[0], ("session_row_id", "file_sha256", "byte_size")) == {
        "session_row_id": session["id"],
        "file_sha256": sha256(data),
        "byte_size": len(data),
    }
    assert kept_files(audit) == [sha256(data)]
    assert (audit.files / sha256(data)).read_bytes() == data

    for table, rows in all_rows(audit.db).items():
        for row in rows:
            assert pick(row, PROVENANCE) == capture_provenance(), table


def test_the_project_is_the_folder_the_session_ran_in_as_the_harness_gave_it(
    tmp_path, audit, project
):
    # The session ran in the project reached through a link, and the session
    # file gives the link. The project is kept as given, not as its real path.
    link = tmp_path / "project_link"
    link.symlink_to(project, target_is_directory=True)
    path = write_session(tmp_path / "story_session.jsonl", lines_of(STORY_SESSION, link))
    capture_file(audit, path, settings_for(project / "excluded_folder"))
    assert current(audit, "sessions")[0]["project"] == str(link)
    assert current(audit, "events")[0]["object"] == str(link / "manuscript.md")


def test_a_relative_path_is_tagged_against_the_folder_the_session_ran_in(
    tmp_path, audit, project
):
    records = [json.loads(line) for line in lines_of(STORY_SESSION, project)]
    read = records[1]["message"]["content"][1]
    assert read["name"] == "Read"
    read["input"]["file_path"] = "./author_draft.md"
    path = write_session(
        tmp_path / "story_session.jsonl", [json.dumps(record) for record in records]
    )
    capture_file(audit, path, settings_for(project / "excluded_folder"))
    assert current(audit, "events")[0]["object"] == str(project / "author_draft.md")


def test_the_method_names_the_adapter_and_tagging_versions(audit, story, project):
    capture_file(audit, story, settings_for(project / "excluded_folder"))
    method = current(audit, "sessions")[0]["method"]
    assert f"claude_code adapter version {claude_code.VERSION}" in method
    assert f"mechanical tagging version {mechanical.VERSION}" in method


def test_a_transcript_with_other_line_ends_is_kept_byte_for_byte(tmp_path, audit, project):
    # Carriage returns before each newline and no newline at the end.
    lines = lines_of(STORY_SESSION, project)
    path = tmp_path / "story_session.jsonl"
    path.write_bytes("\r\n".join(lines).encode("utf-8"))
    data = path.read_bytes()

    capture_file(audit, path, settings_for(project / "excluded_folder"))
    transcript = current(audit, "transcripts")[0]
    assert transcript["file_sha256"] == sha256(data)
    assert transcript["byte_size"] == len(data)
    assert (audit.files / sha256(data)).read_bytes() == data


# A second capture adds nothing.


def test_a_second_capture_adds_nothing(audit, story, project):
    settings = settings_for(project / "excluded_folder")
    capture_file(audit, story, settings)
    before = all_rows(audit.db)
    files = kept_files(audit)

    nothing = Summary(
        path=str(story), session_id=STORY_ID, excluded=False, sessions=0, events=0, transcripts=0
    )
    assert capture_file(audit, story, settings) == nothing
    assert all_rows(audit.db) == before
    assert kept_files(audit) == files

    # The same holds for a store opened again.
    audit.db.close()
    again = open_store(audit.home)
    try:
        assert capture_file(again, story, settings) == nothing
        assert all_rows(again.db) == before
        assert kept_files(again) == files
    finally:
        again.db.close()


# A grown file adds only the new parts and supersedes the session row.


def test_a_grown_file_adds_only_the_new_parts_and_supersedes_the_session_row(
    tmp_path, audit, project
):
    settings = settings_for(project / "excluded_folder")
    lines = lines_of(STORY_SESSION, project)
    path = tmp_path / "story_session.jsonl"
    expected = expected_events(project)

    def capture_now(lines_so_far):
        write_session(path, lines_so_far)
        return capture_file(audit, path, settings)

    def counts(sessions, events, transcripts):
        return Summary(
            path=str(path),
            session_id=STORY_ID,
            excluded=False,
            sessions=sessions,
            events=events,
            transcripts=transcripts,
        )

    # The session so far holds the Read and both Edits.
    assert capture_now(lines[:8]) == counts(1, 3, 1)
    first = current(audit, "sessions")[0]
    assert first["ended_at"] == "2026-10-21T14:02:22.719Z"
    assert first["tools"] == ["Read", "Edit"]
    first_rows = all_rows(audit.db)
    first_bytes = path.read_bytes()

    # The file grows by the Write, both commands, and their results.
    assert capture_now(lines[:14]) == counts(1, 3, 1)
    second = current(audit, "sessions")
    assert len(second) == 1
    second = second[0]
    assert second["supersedes"] == first["id"]
    assert pick(second, SESSION_FIELDS) == dict(
        pick(first, SESSION_FIELDS),
        ended_at="2026-10-21T14:02:41.610Z",
        tools=["Read", "Edit", "Write", "Bash"],
    )
    rows = all_rows(audit.db)
    # The old session row stays in the table as it was written.
    assert rows["sessions"][0] == first_rows["sessions"][0]
    assert len(rows["sessions"]) == 2
    # Only the three new calls are added, after the first three, which are unchanged.
    assert rows["events"][:3] == first_rows["events"]
    assert [pick(event, EVENT_FIELDS) for event in rows["events"]] == expected
    assert [event["session_row_id"] for event in rows["events"]] == [first["id"]] * 3 + [
        second["id"]
    ] * 3
    # A new transcript row holds the grown file, and the first one stays.
    assert rows["transcripts"][0] == first_rows["transcripts"][0]
    assert len(rows["transcripts"]) == 2
    grown = path.read_bytes()
    assert pick(rows["transcripts"][1], ("session_row_id", "file_sha256", "byte_size")) == {
        "session_row_id": second["id"],
        "file_sha256": sha256(grown),
        "byte_size": len(grown),
    }
    assert kept_files(audit) == sorted([sha256(first_bytes), sha256(grown)])

    # The last record holds no tool call, so the file grows by no event.
    assert capture_now(lines) == counts(1, 0, 1)
    third = current(audit, "sessions")
    assert len(third) == 1
    third = third[0]
    assert third["supersedes"] == second["id"]
    assert pick(third, SESSION_FIELDS) == dict(
        pick(second, SESSION_FIELDS), ended_at="2026-10-21T14:02:46.009Z"
    )
    rows = all_rows(audit.db)
    assert len(rows["sessions"]) == 3
    assert [pick(event, EVENT_FIELDS) for event in rows["events"]] == expected
    assert len(rows["transcripts"]) == 3
    whole = path.read_bytes()
    assert whole == story_bytes(project)
    assert rows["transcripts"][2]["file_sha256"] == sha256(whole)
    assert rows["transcripts"][2]["session_row_id"] == third["id"]
    assert (audit.files / sha256(whole)).read_bytes() == whole
    for table, stored in rows.items():
        for row in stored:
            assert pick(row, PROVENANCE) == capture_provenance(), table

    # And capturing the whole file again adds nothing.
    assert capture_now(lines) == counts(0, 0, 0)
    assert all_rows(audit.db) == rows


def story_bytes(project):
    return "".join(line + "\n" for line in lines_of(STORY_SESSION, project)).encode("utf-8")


# The session in an excluded folder stores nothing.


def the_folder_itself(tmp_path, project, monkeypatch):
    folder = project / "excluded_folder"
    folder.mkdir()
    return [str(folder)]


def a_folder_that_holds_it(tmp_path, project, monkeypatch):
    (project / "excluded_folder").mkdir()
    return [str(project)]


def a_link_into_a_listed_folder(tmp_path, project, monkeypatch):
    # The session's folder is a link to the listed folder.
    records = tmp_path / "student_records"
    records.mkdir()
    (project / "excluded_folder").symlink_to(records, target_is_directory=True)
    return [str(records)]


def a_listed_link(tmp_path, project, monkeypatch):
    # The listed folder is a link to the session's folder.
    folder = project / "excluded_folder"
    folder.mkdir()
    link = tmp_path / "records_link"
    link.symlink_to(folder, target_is_directory=True)
    return [str(link)]


def a_folder_listed_from_the_home_folder(tmp_path, project, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (project / "excluded_folder").mkdir()
    return ["~/project/excluded_folder"]


def a_folder_not_yet_made(tmp_path, project, monkeypatch):
    return [str(project / "excluded_folder")]


def one_of_several(tmp_path, project, monkeypatch):
    (project / "excluded_folder").mkdir()
    return [str(tmp_path / "other_records"), str(project / "excluded_folder") + "/"]


LISTINGS = [
    the_folder_itself,
    a_folder_that_holds_it,
    a_link_into_a_listed_folder,
    a_listed_link,
    a_folder_listed_from_the_home_folder,
    a_folder_not_yet_made,
    one_of_several,
]


@pytest.mark.parametrize("listing", LISTINGS, ids=[f.__name__ for f in LISTINGS])
def test_the_session_in_an_excluded_folder_stores_nothing(
    tmp_path, audit, project, excluded_story, listing, monkeypatch
):
    settings = {"excluded_folders": listing(tmp_path, project, monkeypatch)}
    summary = capture_file(audit, excluded_story, settings)
    assert summary == Summary(
        path=str(excluded_story),
        session_id=None,
        excluded=True,
        sessions=0,
        events=0,
        transcripts=0,
    )
    assert all_rows(audit.db) == {table: [] for table in TABLES}
    assert kept_files(audit) == []


def test_only_the_session_in_the_excluded_folder_is_left_out(
    audit, project, story, excluded_story
):
    (project / "excluded_folder").mkdir()
    settings = settings_for(project / "excluded_folder")

    assert capture_file(audit, excluded_story, settings).excluded
    assert not capture_file(audit, story, settings).excluded
    assert capture_file(audit, excluded_story, settings).excluded

    rows = all_rows(audit.db)
    assert [row["harness_session_id"] for row in rows["sessions"]] == [STORY_ID]
    assert len(rows["events"]) == 6
    assert len(rows["transcripts"]) == 1
    assert kept_files(audit) == [sha256(story.read_bytes())]
    # Nothing from the excluded session is anywhere in the database.
    text = json.dumps(rows)
    for trace in (EXCLUDED_ID, "toolu_excluded", "excluded_folder", "README.txt"):
        assert trace not in text


def test_a_session_beside_or_above_an_excluded_folder_is_captured(
    tmp_path, audit, project, story
):
    # The story ran in the folder that holds the excluded one, and a folder
    # whose name only starts with the story's folder name is listed too.
    (project / "excluded_folder").mkdir()
    settings = settings_for(project / "excluded_folder", str(project) + "_old")
    summary = capture_file(audit, story, settings)
    assert not summary.excluded
    assert summary.events == 6


# The rule capture uses for an excluded folder.


@pytest.mark.parametrize(
    "where, expected",
    [
        ("records", True),
        ("records/course", True),
        ("records/course/week_1", True),
        ("records/../records/course", True),
        (".", False),
        ("records_old", False),
        ("recordsx/course", False),
        ("other/records", False),
    ],
)
def test_excluded_compares_real_paths_at_folder_edges(project, where, expected):
    settings = settings_for(project / "records")
    assert excluded(os.path.join(str(project), where), settings) is expected


def test_excluded_follows_links_on_both_sides(tmp_path, project):
    records = tmp_path / "student_records"
    (records / "course").mkdir(parents=True)
    into = project / "linked_records"
    into.symlink_to(records, target_is_directory=True)
    listed = tmp_path / "listed_link"
    listed.symlink_to(records, target_is_directory=True)

    # A link into an excluded folder still counts.
    assert excluded(str(into / "course"), settings_for(records))
    # A listed link stands for the folder it points to.
    assert excluded(str(records / "course"), settings_for(listed))
    assert excluded(str(into), settings_for(listed))
    # The folder that holds the link is not inside the excluded folder.
    assert not excluded(str(project), settings_for(records))


def test_no_folder_is_excluded_when_none_is_listed(project):
    assert not excluded(str(project), {"excluded_folders": []})


# Letter case in a listed folder (Track L, Step L4, decision 51). Whether the
# disk ignores case is found by checking the disk, and a stand-in for that
# check plays each kind of disk here.


def disk(monkeypatch, ignores):
    """Stand in for the disk check, and keep the folders it was asked about."""
    asked = []

    def check(path):
        asked.append(str(path))
        return ignores

    monkeypatch.setattr(settings_module, "ignores_case", check)
    return asked


@pytest.mark.parametrize("ignores, expected", [(True, True), (False, False)])
@pytest.mark.parametrize(
    "listed, where",
    [
        ("Records", "records"),
        ("records", "RECORDS"),
        ("Records", "rEcOrDs/course/week_1"),
    ],
)
def test_a_folder_listed_in_another_case_counts_only_on_a_disk_that_ignores_case(
    project, monkeypatch, listed, where, ignores, expected
):
    (project / "records" / "course" / "week_1").mkdir(parents=True)
    disk(monkeypatch, ignores)
    settings = settings_for(project / listed)
    assert excluded(os.path.join(str(project), where), settings) is expected


@pytest.mark.parametrize("ignores", [True, False])
def test_the_same_case_counts_on_either_disk(project, monkeypatch, ignores):
    (project / "records" / "course").mkdir(parents=True)
    disk(monkeypatch, ignores)
    assert excluded(str(project / "records" / "course"), settings_for(project / "records"))


@pytest.mark.parametrize("where", ["RECORDS_old", "Recordsx/course", "Other/records", "."])
def test_ignoring_case_still_compares_whole_folders(project, monkeypatch, where):
    disk(monkeypatch, True)
    settings = settings_for(project / "Records")
    assert not excluded(os.path.join(str(project), where), settings)


def test_the_disk_checked_is_the_listed_folders_own(project, monkeypatch):
    asked = disk(monkeypatch, True)
    excluded(str(project / "elsewhere"), settings_for(project / "Records"))
    assert asked == [os.path.realpath(str(project / "Records"))]


@pytest.mark.parametrize("ignores, stored", [(True, False), (False, True)])
def test_a_session_run_in_a_listed_folder_written_in_another_case(
    audit, project, excluded_story, monkeypatch, ignores, stored
):
    # The session ran in project/excluded_folder, and the scholar listed it as
    # project/Excluded_Folder.
    (project / "excluded_folder").mkdir()
    disk(monkeypatch, ignores)
    summary = capture_file(audit, excluded_story, settings_for(project / "Excluded_Folder"))
    assert summary.excluded is not stored
    assert bool(kept_files(audit)) is stored


def test_the_disk_check_agrees_with_the_disk(tmp_path):
    # The check runs on this machine's own disk, compared with what the disk
    # does with a name written in another case.
    probe = tmp_path / "Probe"
    probe.mkdir()
    expected = (tmp_path / "pROBE").exists()
    assert ignores_case(probe) is expected
    # A folder not yet made is judged by the nearest folder above it.
    assert ignores_case(probe / "not" / "made") is expected
    # A name with no letter is passed over for one above it.
    (probe / "2026").mkdir()
    assert ignores_case(probe / "2026") is expected


# The settings file and the audit home.


def test_init_writes_a_settings_file_with_no_excluded_folders(tmp_path):
    home = tmp_path / "audit_home"
    assert main(["init", "--home", str(home)]) == 0
    text = (home / "settings.yaml").read_text(encoding="utf-8")
    assert yaml.safe_load(text) == {"excluded_folders": []}
    comment = " ".join(line for line in text.splitlines() if line.startswith("#"))
    assert "student records" in comment
    assert read_settings(home) == {"excluded_folders": []}
    assert (home / "audit.sqlite").is_file()


def test_init_run_again_keeps_the_folders_the_scholar_listed(tmp_path, project):
    home = tmp_path / "audit_home"
    assert main(["init", "--home", str(home)]) == 0
    settings = home / "settings.yaml"
    listed = str(project / "excluded_folder")
    edited = settings.read_text(encoding="utf-8").replace(
        "excluded_folders: []", "excluded_folders:\n  - " + json.dumps(listed)
    )
    settings.write_text(edited, encoding="utf-8")

    assert main(["init", "--home", str(home)]) == 0
    assert settings.read_text(encoding="utf-8") == edited
    assert read_settings(home) == {"excluded_folders": [listed]}


def test_the_audit_home_is_the_option_else_the_variable_else_the_default(
    tmp_path, home_folder, monkeypatch
):
    assert audit_home(None) == home_folder / ".audit_layer"
    monkeypatch.setenv("AUDIT_HOME", str(tmp_path / "from_variable"))
    assert audit_home(None) == tmp_path / "from_variable"
    assert audit_home(str(tmp_path / "from_option")) == tmp_path / "from_option"
    # A variable set to nothing counts as not set.
    monkeypatch.setenv("AUDIT_HOME", "")
    assert audit_home(None) == home_folder / ".audit_layer"


@pytest.mark.parametrize("how", ["option", "variable", "default"])
def test_init_and_capture_find_the_audit_home_the_same_way(
    tmp_path, home_folder, project, story, how
):
    env = dict(os.environ)
    given = []
    if how == "option":
        home = tmp_path / "from_option"
        given = ["--home", str(home)]
        env["AUDIT_HOME"] = str(tmp_path / "not_used")
    elif how == "variable":
        home = tmp_path / "from_variable"
        env["AUDIT_HOME"] = str(home)
    else:
        home = home_folder / ".audit_layer"

    def run(*args):
        return subprocess.run(
            [sys.executable, "-m", "audit_layer", *args],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
        )

    made = run("init", *given)
    assert made.returncode == 0, made.stderr
    assert str(home) in made.stdout
    assert (home / "settings.yaml").is_file()
    stored = run("capture", *given, "--harness", "claude_code", str(story))
    assert stored.returncode == 0, stored.stderr
    assert STORY_ID in stored.stdout

    db = sqlite3.connect(str(home / "audit.sqlite"))
    try:
        assert [row["harness_session_id"] for row in stored_rows(db, "sessions")] == [STORY_ID]
    finally:
        db.close()
    assert not (tmp_path / "not_used").exists()


@pytest.mark.parametrize(
    "text, problem",
    [
        ("excluded_folders: /Users/you/Documents/Courses\n", "list"),
        ("excluded_folders:\n", "list"),
        ("excluded_folders:\n  - Documents/Courses\n", "full path"),
        ("excluded_folders:\n  - ''\n", "not a folder"),
        ("excluded_folders:\n  - 3\n", "not a folder"),
        (
            "exclude_folders:\n  - /Users/you/Documents/Courses\nexcluded_folders: []\n",
            "exclude_folders",
        ),
        ("- /Users/you/Documents/Courses\n", "mapping"),
        ("", "mapping"),
        ("excluded_folders: [\n", "YAML"),
    ],
    ids=[
        "one folder not in a list",
        "no list",
        "a relative folder",
        "an empty folder",
        "a number",
        "a misspelled setting",
        "a list alone",
        "an empty file",
        "broken YAML",
    ],
)
def test_a_settings_file_that_does_not_clearly_list_folders_is_refused(tmp_path, text, problem):
    home = tmp_path / "audit_home"
    home.mkdir()
    (home / "settings.yaml").write_text(text, encoding="utf-8")
    with pytest.raises(SettingsError, match=problem):
        read_settings(home)


# Capture without settings refuses.


def no_home(home):
    pass


def a_store_with_no_settings_file(home):
    # As the init command left a home before this step.
    open_store(home).db.close()


def a_settings_file_that_lists_no_folders(home):
    open_store(home).db.close()
    (home / "settings.yaml").write_text("excluded_folders:\n", encoding="utf-8")


HOMES = [no_home, a_store_with_no_settings_file, a_settings_file_that_lists_no_folders]


@pytest.mark.parametrize("make_home", HOMES, ids=[f.__name__ for f in HOMES])
def test_capture_without_settings_refuses(tmp_path, story, capsys, make_home):
    home = tmp_path / "audit_home"
    make_home(home)
    before = sorted(p.name for p in home.iterdir()) if home.exists() else None

    code = main(["capture", "--home", str(home), "--harness", "claude_code", str(story)])
    assert code == 1
    out, err = capsys.readouterr()
    assert "settings" in err
    assert "init" in err or "excluded_folders" in err
    assert STORY_ID not in out

    if before is None:
        assert not home.exists()
    else:
        assert sorted(p.name for p in home.iterdir()) == before
        db = sqlite3.connect(str(home / "audit.sqlite"))
        try:
            assert {table: stored_rows(db, table) for table in TABLES} == {
                table: [] for table in TABLES
            }
        finally:
            db.close()
        assert list((home / "files").iterdir()) == []


@pytest.mark.parametrize(
    "settings", [None, {}, {"excluded_folders": "/x"}], ids=["none", "empty", "not a list"]
)
def test_capture_file_refuses_settings_that_do_not_list_folders(audit, story, settings):
    with pytest.raises(SettingsError):
        capture_file(audit, story, settings)
    assert all_rows(audit.db) == {table: [] for table in TABLES}
    assert kept_files(audit) == []


# The capture command.


def test_the_capture_command_stores_sessions_and_skips_excluded_ones(
    tmp_path, project, story, excluded_story, capsys
):
    home = tmp_path / "audit_home"
    (project / "excluded_folder").mkdir()
    assert main(["init", "--home", str(home)]) == 0
    (home / "settings.yaml").write_text(
        "excluded_folders:\n  - " + json.dumps(str(project / "excluded_folder")) + "\n",
        encoding="utf-8",
    )
    capsys.readouterr()

    command = ["capture", "--home", str(home), "--harness", "claude_code"]
    assert main(command + [str(story), str(excluded_story)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2
    assert str(story) in lines[0] and STORY_ID in lines[0] and "6 events" in lines[0]
    assert str(excluded_story) in lines[1] and "excluded folder" in lines[1]
    assert EXCLUDED_ID not in lines[1]

    store = open_store(home)
    try:
        first = all_rows(store.db)
        assert [row["harness_session_id"] for row in first["sessions"]] == [STORY_ID]
        assert len(first["events"]) == 6
        assert len(first["transcripts"]) == 1
    finally:
        store.db.close()

    assert main(command + [str(story), str(excluded_story)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert "nothing new" in lines[0]
    assert "excluded folder" in lines[1]
    store = open_store(home)
    try:
        assert all_rows(store.db) == first
    finally:
        store.db.close()


def test_a_file_capture_cannot_read_is_named_and_the_rest_are_captured(
    tmp_path, project, story, capsys
):
    home = tmp_path / "audit_home"
    assert main(["init", "--home", str(home)]) == 0
    capsys.readouterr()
    lines = lines_of(STORY_SESSION, project)
    broken = write_session(tmp_path / "broken.jsonl", lines[:-1] + [lines[-1][:40]])
    missing = tmp_path / "missing.jsonl"

    command = ["capture", "--home", str(home), "--harness", "claude_code"]
    assert main(command + [str(broken), str(missing), str(story)]) == 1
    out, err = capsys.readouterr()
    assert str(broken) in err and "line 15" in err
    assert str(missing) in err
    assert str(story) in out and "6 events" in out

    store = open_store(home)
    try:
        transcripts = current(store, "transcripts")
        assert [row["file_sha256"] for row in transcripts] == [sha256(story.read_bytes())]
    finally:
        store.db.close()


@pytest.mark.parametrize(
    "harness", [["--harness", "no_such_harness"], []], ids=["another harness", "no harness"]
)
def test_capture_takes_only_the_harness_it_has_an_adapter_for(tmp_path, story, harness):
    home = tmp_path / "audit_home"
    assert main(["init", "--home", str(home)]) == 0
    with pytest.raises(SystemExit) as stop:
        main(["capture", "--home", str(home)] + harness + [str(story)])
    assert stop.value.code == 2


def test_an_event_the_schema_refuses_stores_nothing(audit, story, project, monkeypatch):
    tag = capture.tag

    def wrong_verb(tool_call, cwd):
        fields = tag(tool_call, cwd)
        return dict(fields, verb="deleted") if tool_call.name == "Bash" else fields

    monkeypatch.setattr(capture, "tag", wrong_verb)
    with pytest.raises(ValueError, match="verb"):
        capture_file(audit, story, settings_for(project / "excluded_folder"))
    assert all_rows(audit.db) == {table: [] for table in TABLES}
    assert kept_files(audit) == []
