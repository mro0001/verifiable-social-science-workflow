"""Step F10. Undo and the log.

The good proposal of step F8 is applied to a copy of the organizer fixture,
as in step F9, and then its entries are undone one by one.

Run from the repository root as python3 -m pytest -q features/tests.
"""
import json
import os
import shutil

import pytest
import yaml

from features import cli
from features.organizer import journal, undo
from features.tests import helpers
from features.tests.test_apply import apply_file, good_file, organizer, outside_organizer
from features.tests.test_proposals import (NOW, SESSION, checksums, db_of, make_home,
                                           ospipe_build, run_command, scan, session_db)

ROOT = helpers.ROOT
# The entries the good proposal gives, in its order.
ARCHIVE_OLD, ARCHIVE_FULL, MOVE, MARK_BUILD, MARK_SESSION = (
    "j0001", "j0002", "j0003", "j0004", "j0005")


@pytest.fixture(autouse=True)
def private_home(tmp_path, monkeypatch):
    """Point HOME and both home variables at temporary folders, so nothing real is touched."""
    home = tmp_path / "user_home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("AUDIT_HOME", str(tmp_path / "env_audit_home"))
    monkeypatch.setenv("FEATURES_HOME", str(tmp_path / "env_features_home"))
    return home


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """The organizer fixture with two builds, made once for the module."""
    folder = helpers.copy_fixture("organizer_project", tmp_path_factory.mktemp("built"))
    ospipe_build(folder)
    ospipe_build(folder)
    return folder


@pytest.fixture
def project(tmp_path, built):
    """A copy of the built fixture with the audit database beside it."""
    folder = tmp_path / "organizer_project"
    shutil.copytree(str(built), str(folder), symlinks=True)
    session_db(tmp_path / "audit" / "audit.sqlite", folder)
    return folder


@pytest.fixture
def applied(project, tmp_path):
    """The project after the good proposal, with its checksums from before."""
    before = outside_organizer(project)
    _, path = good_file(project, tmp_path)
    result = apply_file(project, path)
    assert result.problems == [] and result.not_applied == []
    return project, before


def undo_one(project, entry, by="Test Scholar"):
    return undo.undo_entry(str(project), entry, by, NOW, root=str(ROOT),
                           audit_db=str(db_of(project)))


def journal_bytes(project):
    return (organizer(project) / "journal.jsonl").read_bytes()


def marks_of(project):
    return yaml.safe_load((organizer(project) / "marks.yaml").read_text(encoding="utf-8"))


# Undo returns each file.

def test_undoing_every_entry_returns_every_project_file(applied):
    project, before = applied
    assert outside_organizer(project) != before
    for entry in (MOVE, ARCHIVE_FULL, MARK_SESSION, ARCHIVE_OLD, MARK_BUILD):
        undo_one(project, entry)
    assert outside_organizer(project) == before


@pytest.mark.parametrize("entry,path", [(ARCHIVE_OLD, "drafts/manuscript_old.md"),
                                        (ARCHIVE_FULL, "drafts/retention_full.md"),
                                        (MOVE, "stray.txt")])
def test_undoing_one_file_change_returns_that_file(applied, entry, path):
    project, before = applied
    undo_one(project, entry)
    assert checksums(project)[path.replace("/", os.sep)] == before[path.replace("/", os.sep)]


def test_undoing_a_move_leaves_nothing_at_the_target(applied):
    project, _ = applied
    undo_one(project, MOVE)
    assert not os.path.lexists(str(project / "misc" / "stray.txt"))
    assert (project / "stray.txt").is_file()


def test_undoing_an_archive_line_keeps_both_versions_in_the_store(applied):
    project, _ = applied
    entry = journal.read_journal(str(project))[0]
    undo_one(project, ARCHIVE_OLD)
    store = organizer(project) / "originals"
    assert (store / entry["before_sha256"]).is_file()
    assert (store / entry["after_sha256"]).is_file()


def test_the_undo_entry_records_what_it_reversed(applied):
    project, _ = applied
    new = undo_one(project, MOVE)
    assert new == "j0006"
    entry = journal.read_journal(str(project))[-1]
    move = journal.read_journal(str(project))[2]
    assert entry["entry"] == "j0006"
    assert entry["op"] == "undo"
    assert entry["undoes"] == MOVE
    assert entry["by"] == "Test Scholar"
    assert entry["at"] == "2026-10-29T09:30:00+00:00"
    assert entry["schema_version"] == 1
    assert entry["change_id"] == move["change_id"]
    assert (entry["path"], entry["to"], entry["sha256"]) == (move["to"], move["path"],
                                                              move["sha256"])
    archive = journal.read_journal(str(project))[0]
    undo_one(project, ARCHIVE_OLD)
    reversed_archive = journal.read_journal(str(project))[-1]
    assert reversed_archive["path"] == archive["path"]
    assert reversed_archive["before_sha256"] == archive["after_sha256"]
    assert reversed_archive["after_sha256"] == archive["before_sha256"]


def test_undo_rewrites_the_inventory(applied):
    project, _ = applied
    undo_one(project, MOVE)
    written = json.loads((organizer(project) / "inventory.json").read_text(encoding="utf-8"))
    assert written["inventory_id"] == scan(project)["inventory_id"]
    assert "stray.txt" in [entry["path"] for entry in written["files"]]


# Refusals.

def test_a_second_undo_is_refused(applied):
    project, _ = applied
    undo_one(project, MOVE)
    saved = journal_bytes(project)
    with pytest.raises(undo.UndoError) as raised:
        undo_one(project, MOVE)
    assert "j0006" in str(raised.value)
    assert journal_bytes(project) == saved


def test_an_undo_of_an_undo_is_refused(applied):
    project, _ = applied
    new = undo_one(project, MARK_BUILD)
    saved = journal_bytes(project)
    with pytest.raises(undo.UndoError):
        undo_one(project, new)
    assert journal_bytes(project) == saved


def test_an_unknown_entry_is_refused(applied):
    project, _ = applied
    saved = journal_bytes(project)
    for entry in ("j0099", "x1", ""):
        with pytest.raises(undo.UndoError):
            undo_one(project, entry)
    assert journal_bytes(project) == saved


def test_undo_needs_a_name(applied):
    project, _ = applied
    with pytest.raises(undo.UndoError):
        undo_one(project, MOVE, by=" ")


def test_undo_with_no_journal_is_refused(project):
    with pytest.raises(undo.UndoError):
        undo_one(project, "j0001")
    assert not organizer(project).exists()


@pytest.mark.parametrize("entry", [ARCHIVE_OLD, MOVE, MARK_BUILD])
def test_a_journal_cut_short_stops_undo_before_any_change(applied, entry):
    project, _ = applied
    path = organizer(project) / "journal.jsonl"
    path.write_bytes(path.read_bytes().rstrip(b"\n"))
    saved = path.read_bytes()
    files = checksums(project)
    with pytest.raises(journal.JournalError):
        undo_one(project, entry)
    assert path.read_bytes() == saved
    assert checksums(project) == files


def test_undoing_a_move_after_the_file_was_edited_is_refused_and_changes_nothing(applied):
    project, _ = applied
    (project / "misc" / "stray.txt").write_text("edited after the move\n", encoding="utf-8")
    saved = journal_bytes(project)
    files = checksums(project)
    with pytest.raises(undo.UndoError) as raised:
        undo_one(project, MOVE)
    assert "misc/stray.txt" in str(raised.value)
    assert journal_bytes(project) == saved
    assert checksums(project) == files


def test_undoing_a_move_when_the_old_path_is_taken_is_refused(applied):
    project, _ = applied
    (project / "stray.txt").write_text("a new file\n", encoding="utf-8")
    saved = journal_bytes(project)
    files = checksums(project)
    with pytest.raises(undo.UndoError) as raised:
        undo_one(project, MOVE)
    assert "stray.txt" in str(raised.value)
    assert journal_bytes(project) == saved
    assert checksums(project) == files


def test_undoing_a_move_whose_file_is_gone_is_refused(applied):
    project, _ = applied
    os.rename(str(project / "misc" / "stray.txt"), str(project / "elsewhere.txt"))
    files = checksums(project)
    with pytest.raises(undo.UndoError):
        undo_one(project, MOVE)
    assert checksums(project) == files


def test_undoing_an_archive_line_after_the_file_was_edited_is_refused_and_changes_nothing(
        applied):
    project, _ = applied
    draft = project / "drafts" / "manuscript_old.md"
    draft.write_text(draft.read_text(encoding="utf-8") + "A new paragraph.\n", encoding="utf-8")
    saved = journal_bytes(project)
    files = checksums(project)
    with pytest.raises(undo.UndoError) as raised:
        undo_one(project, ARCHIVE_OLD)
    assert "drafts/manuscript_old.md" in str(raised.value)
    assert journal_bytes(project) == saved
    assert checksums(project) == files


def test_undoing_an_archive_line_whose_original_bytes_are_gone_is_refused(applied):
    project, _ = applied
    entry = journal.read_journal(str(project))[0]
    store = organizer(project) / "originals"
    os.rename(str(store / entry["before_sha256"]), str(project.parent / "kept_aside"))
    files = checksums(project)
    with pytest.raises(undo.UndoError) as raised:
        undo_one(project, ARCHIVE_OLD)
    assert "originals" in str(raised.value)
    assert checksums(project) == files


# Marks.

def test_an_undone_mark_leaves_marks_yaml_and_the_journal_keeps_both(applied):
    project, _ = applied
    assert [mark["entry"] for mark in marks_of(project)["marks"]] == [MARK_BUILD, MARK_SESSION]
    new = undo_one(project, MARK_BUILD)
    assert [mark["entry"] for mark in marks_of(project)["marks"]] == [MARK_SESSION]
    entries = journal.read_journal(str(project))
    assert [entry["entry"] for entry in entries] == [ARCHIVE_OLD, ARCHIVE_FULL, MOVE, MARK_BUILD,
                                                     MARK_SESSION, new]
    assert entries[-1]["undoes"] == MARK_BUILD
    assert (entries[-1]["item_kind"], entries[-1]["item"]) == ("build", "manuscript/v001")
    assert marks_of(project)["marks"][0]["item"] == SESSION


def test_undoing_a_mark_changes_no_project_file(applied):
    project, _ = applied
    files = outside_organizer(project)
    undo_one(project, MARK_SESSION)
    assert outside_organizer(project) == files


# The log.

def test_log_shows_every_entry_and_which_entry_undid_which(applied):
    project, _ = applied
    undo_one(project, MOVE)
    undo_one(project, MARK_BUILD)
    text = undo.log_text(str(project))
    lines = text.splitlines()
    header = lines[0].split()
    assert header[:2] == ["entry", "at"]
    rows = dict((line.split()[0], line) for line in lines[1:] if line[:1] == "j")
    assert sorted(rows) == ["j0001", "j0002", "j0003", "j0004", "j0005", "j0006", "j0007"]
    assert rows[MOVE].rstrip().endswith("j0006")
    assert rows[MARK_BUILD].rstrip().endswith("j0007")
    assert "undoes j0003" in rows["j0006"]
    assert "undoes j0004" in rows["j0007"]
    assert "Test Scholar" in rows[ARCHIVE_OLD]
    assert "ai:claude_code:" + SESSION in rows[ARCHIVE_OLD]
    assert "archive_line" in rows[ARCHIVE_OLD]
    assert "drafts/manuscript_old.md" in rows[ARCHIVE_OLD]
    assert "An older draft whose file name holds the manuscript's name." in rows[ARCHIVE_OLD]
    assert "stray.txt" in rows[MOVE]
    marks_at = lines.index("Marks")
    marks = lines[marks_at + 1:]
    assert len(marks) == 1
    assert SESSION in marks[0] and "belongs_to" in marks[0] and MARK_SESSION in marks[0]


def test_log_of_a_project_with_no_journal(project):
    text = undo.log_text(str(project))
    assert "no journal" in text.lower()
    assert not organizer(project).exists()


# The commands.

def test_the_undo_command_prints_the_new_entry(applied, tmp_path):
    project, before = applied
    home = make_home(tmp_path, project)
    code, out, err = run_command(["organize", "undo", str(project), MOVE,
                                  "--by", "Test Scholar", "--home", str(home)])
    assert code == 0, err
    assert "j0006" in out and MOVE in out
    assert checksums(project)["stray.txt"] == before["stray.txt"]


def test_the_undo_command_refuses_and_exits_1(applied, tmp_path):
    project, _ = applied
    home = make_home(tmp_path, project)
    code, out, err = run_command(["organize", "undo", str(project), "j0099",
                                  "--by", "Test Scholar", "--home", str(home)])
    assert code == 1
    assert "j0099" in err


def test_the_undo_command_needs_by():
    parser, _ = cli._parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["organize", "undo", "somewhere", "j0001"])


def test_the_log_command_prints_the_log(applied):
    project, _ = applied
    code, out, err = run_command(["organize", "log", str(project)])
    assert code == 0, err
    assert out == undo.log_text(str(project))


def test_undo_and_log_are_listed_in_the_organize_group():
    parser, helps = cli._parser()
    text = helps["organize"].format_help()
    assert "undo" in text and "log" in text
