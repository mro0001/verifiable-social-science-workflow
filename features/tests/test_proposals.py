"""Step F8. Proposals and their check.

The recorded proposals in features/tests/fixtures/proposals/ stand in for
the AI's answers. The test fills in the inventory id, the session id, and
the project folder. The organizer fixture gets two builds made with ospipe
build through the layer runner, and a session from make_audit_db.

Run from the repository root as python3 -m pytest -q features/tests.
"""
import copy
import datetime
import hashlib
import io
import os
import shutil
from pathlib import Path

import pytest
import yaml

from features import cli, layers
from features.organizer import inventory, proposals
from features.setup import system
from features.tests import helpers
from features.tests.test_system_setup import fake_detector

ROOT = helpers.ROOT
PROPOSALS = helpers.FIXTURES / "proposals"
NOW = datetime.datetime(2026, 10, 29, 9, 30, 0, tzinfo=datetime.timezone.utc)
SESSION = "6a1d2c0e-0000-4000-8000-00000000f008"
BUILD_ARGS = ["build", "--manuscript", "manuscript.md", "--manifest", "numbers.yml",
              "--tables-dir", ".", "--bib", "refs.bib", "--builds-dir", "builds/manuscript",
              "--purpose", "draft"]


@pytest.fixture(autouse=True)
def private_home(tmp_path, monkeypatch):
    """Point HOME and both home variables at temporary folders, so nothing real is touched."""
    home = tmp_path / "user_home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("AUDIT_HOME", str(tmp_path / "env_audit_home"))
    monkeypatch.setenv("FEATURES_HOME", str(tmp_path / "env_features_home"))
    return home


def ospipe_build(project):
    done = layers.run_layer("ospipe", BUILD_ARGS, root=str(ROOT), cwd=str(project))
    assert done.returncode == 0, done.stderr


def session_db(path, project):
    """A database holding one session that ran in the project and edited the manuscript."""
    real = os.path.realpath(str(project))
    sessions = [{"id": "s1", "harness": "claude_code", "harness_session_id": SESSION,
                 "project": real, "started_at": "2026-10-28T10:00:00Z",
                 "ended_at": "2026-10-28T11:00:00Z", "tools": '["Edit"]'}]
    events = [{"id": "e1", "session_row_id": "s1", "ordinal": 1, "verb": "edited",
               "kind": "action", "object": os.path.join(real, "manuscript.md"),
               "role": "edited"}]
    return helpers.make_audit_db(path, sessions, events)


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


def db_of(project):
    return project.parent / "audit" / "audit.sqlite"


def scan(project):
    return inventory.build_inventory(str(project), NOW, root=str(ROOT), audit_db=str(db_of(project)))


def recorded(name, project, record):
    """A recorded proposal with its placeholders filled for this project and inventory."""
    text = (PROPOSALS / name).read_text(encoding="utf-8")
    text = text.replace("{{INVENTORY_ID}}", record["inventory_id"])
    text = text.replace("{{SESSION}}", SESSION)
    text = text.replace("{{PROJECT}}", os.path.realpath(str(project)))
    return yaml.safe_load(text)


def check(project, proposal, record=None):
    record = record or scan(project)
    return proposals.check_proposal(str(project), proposal, record)


def good(project):
    record = scan(project)
    return recorded("good.yaml", project, record), record


def with_change(project, change):
    """The good proposal's header with one change in place of its changes."""
    proposal, record = good(project)
    proposal["changes"] = [dict({"id": "x1", "reason": "A test change."}, **change)]
    return proposal, record


def rules(problems):
    return [problem.rule for problem in problems]


def checksums(folder):
    found = {}
    for here, _, files in os.walk(str(folder)):
        for name in files:
            path = os.path.join(here, name)
            found[os.path.relpath(path, str(folder))] = hashlib.sha256(
                Path(path).read_bytes()).hexdigest()
    return found


def make_home(tmp_path, project):
    home = tmp_path / "features_home"
    given = {"scholar_name": "Test Scholar", "excluded_folders": [], "citation_export": ""}
    # Setup runs audit_layer init in the audit home. Put the hand-made
    # session database in place of the store it makes.
    db_of(project).unlink()
    result = system.run_system_setup(str(home), str(tmp_path / "audit"), given, str(ROOT), NOW,
                                     detector=fake_detector())
    assert result.ready
    db_of(project).unlink()
    session_db(db_of(project), project)
    return home


def run_command(argv):
    out = io.StringIO()
    err = io.StringIO()
    parser, _ = cli._parser()
    options = parser.parse_args(argv)
    code = options.run(options, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def write_proposal(tmp_path, proposal, name="proposal.yaml"):
    path = tmp_path / name
    path.write_text(yaml.safe_dump(proposal, sort_keys=False), encoding="utf-8")
    return path


# The fixture holds what the good proposal names.

def test_the_fixture_inventory_holds_the_builds_and_the_session(project):
    record = scan(project)
    assert [build["item"] for build in record["builds"]] == ["manuscript/v001", "manuscript/v002"]
    assert [item["harness_session_id"] for item in record["sessions"]] == [SESSION]


# A good proposal.

def test_the_good_proposal_has_no_problems(project):
    proposal, record = good(project)
    assert [change["op"] for change in proposal["changes"]] == [
        "archive_line", "archive_line", "move", "mark", "mark"]
    assert check(project, proposal, record) == []


def test_a_problem_names_its_change_rule_and_message(project):
    proposal, record = with_change(project, {"op": "tidy", "path": "stray.txt"})
    problems = check(project, proposal, record)
    assert len(problems) == 1
    assert problems[0]._fields == ("change_id", "rule", "message")
    assert problems[0].change_id == "x1"


# The organizer never deletes, and knows only its three operations.

def test_a_delete_gets_the_never_deletes_message(project):
    record = scan(project)
    problems = check(project, recorded("delete.yaml", project, record), record)
    assert len(problems) == 1
    assert problems[0].message == "the organizer never deletes, so mark the item unused instead"


@pytest.mark.parametrize("op", ["delete", "remove", "rm", "unlink", "overwrite"])
def test_each_deleting_op_gets_the_never_deletes_message(project, op):
    proposal, record = with_change(project, {"op": op, "path": "stray.txt"})
    messages = [problem.message for problem in check(project, proposal, record)]
    assert messages == ["the organizer never deletes, so mark the item unused instead"]


def test_an_unknown_op_is_refused(project):
    record = scan(project)
    problems = check(project, recorded("unknown_op.yaml", project, record), record)
    assert len(problems) == 1
    assert problems[0].change_id == "c1"
    assert "tidy" in problems[0].message
    assert "never deletes" not in problems[0].message


def test_a_missing_op_is_refused(project):
    proposal, record = with_change(project, {"path": "stray.txt"})
    assert len(check(project, proposal, record)) == 1


# The proposal's header.

def test_a_wrong_schema_is_refused(project):
    proposal, record = good(project)
    proposal["schema"] = "organizer-inventory"
    assert "schema" in rules(check(project, proposal, record))


def test_a_wrong_schema_version_is_refused(project):
    proposal, record = good(project)
    proposal["schema_version"] = 2
    assert "schema_version" in rules(check(project, proposal, record))


@pytest.mark.parametrize("value", [None, "", "  "])
def test_a_missing_proposed_by_is_refused(project, value):
    proposal, record = good(project)
    if value is None:
        del proposal["proposed_by"]
    else:
        proposal["proposed_by"] = value
    assert rules(check(project, proposal, record)) == ["proposed_by"]


def test_changes_that_are_not_a_list_are_refused(project):
    proposal, record = good(project)
    proposal["changes"] = {"id": "c1"}
    assert rules(check(project, proposal, record)) == ["changes"]


def test_a_proposal_that_is_not_a_mapping_is_refused(project):
    record = scan(project)
    problems = proposals.check_proposal(str(project), ["changes"], record)
    assert len(problems) == 1


@pytest.mark.parametrize("value", [None, "", "   "])
def test_a_change_with_no_reason_is_refused(project, value):
    proposal, record = good(project)
    if value is None:
        del proposal["changes"][2]["reason"]
    else:
        proposal["changes"][2]["reason"] = value
    problems = check(project, proposal, record)
    assert [(problem.change_id, problem.rule) for problem in problems] == [("c3", "reason")]


def test_a_repeated_id_is_refused(project):
    proposal, record = good(project)
    proposal["changes"][4]["id"] = "c1"
    problems = check(project, proposal, record)
    assert [(problem.change_id, problem.rule) for problem in problems] == [("c1", "id")]


def test_a_change_with_no_id_is_refused(project):
    proposal, record = good(project)
    del proposal["changes"][2]["id"]
    assert rules(check(project, proposal, record)) == ["id"]


@pytest.mark.parametrize("value", [1, 2.5, True, ["c1"]])
def test_an_id_that_is_not_text_is_refused_as_not_text(project, value):
    proposal, record = good(project)
    proposal["changes"][2]["id"] = value
    problems = check(project, proposal, record)
    assert rules(problems) == ["id"]
    assert "not text" in problems[0].message
    assert "no id" not in problems[0].message


# A stale inventory id refuses the whole proposal.

def test_a_stale_inventory_id_is_refused(project):
    proposal, record = good(project)
    (project / "stray.txt").write_bytes((project / "stray.txt").read_bytes() + b"x")
    problems = check(project, proposal, scan(project))
    assert rules(problems) == ["inventory_id"]
    assert problems[0].change_id is None
    assert "changed" in problems[0].message


@pytest.mark.parametrize("value", [None, "", "0" * 64])
def test_a_missing_or_wrong_inventory_id_is_refused(project, value):
    proposal, record = good(project)
    if value is None:
        del proposal["inventory_id"]
    else:
        proposal["inventory_id"] = value
    assert rules(check(project, proposal, record)) == ["inventory_id"]


# Moves.

@pytest.mark.parametrize("path", ["manuscript.md", "raw.csv", "numbers.yml", "Makefile",
                                  "verification/README.md", "s1.py"])
def test_moving_a_protected_file_is_refused(project, path):
    proposal, record = with_change(project, {"op": "move", "path": path, "to": "misc/x"})
    assert rules(check(project, proposal, record)) == ["move"]


def test_moving_a_file_under_builds_is_refused(project):
    assert (project / "builds" / "manuscript" / "v001.docx").is_file()
    proposal, record = with_change(project, {"op": "move", "path": "builds/manuscript/v001.docx",
                                             "to": "misc/v001.docx"})
    assert rules(check(project, proposal, record)) == ["move"]


def test_moving_a_file_not_in_the_inventory_is_refused(project):
    proposal, record = with_change(project, {"op": "move", "path": "nothing.txt",
                                             "to": "misc/nothing.txt"})
    assert rules(check(project, proposal, record)) == ["move"]


def test_moving_onto_an_existing_file_is_refused(project):
    proposal, record = with_change(project, {"op": "move", "path": "stray.txt",
                                             "to": "notes/writing.md"})
    assert rules(check(project, proposal, record)) == ["move"]


def test_moving_onto_an_existing_folder_is_refused(project):
    proposal, record = with_change(project, {"op": "move", "path": "stray.txt", "to": "drafts"})
    assert rules(check(project, proposal, record)) == ["move"]


@pytest.mark.parametrize("to", ["../stray.txt", "misc/../../stray.txt", "/tmp/stray.txt"])
def test_moving_outside_the_project_is_refused(project, to):
    proposal, record = with_change(project, {"op": "move", "path": "stray.txt", "to": to})
    assert rules(check(project, proposal, record)) == ["move"]


def test_moving_through_a_link_that_leads_outside_the_project_is_refused(project, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(str(outside), str(project / "away"))
    proposal, record = with_change(project, {"op": "move", "path": "stray.txt",
                                             "to": "away/stray.txt"})
    assert rules(check(project, proposal, record)) == ["move"]


@pytest.mark.parametrize("to", [".organizer/stray.txt", "builds/manuscript/stray.txt",
                                "builds/manuscript", "verification/stray.txt",
                                ".git/stray.txt", "drafts/.git/stray.txt"])
def test_moving_into_a_folder_the_organizer_keeps_out_of_is_refused(project, to):
    proposal, record = with_change(project, {"op": "move", "path": "stray.txt", "to": to})
    assert rules(check(project, proposal, record)) == ["move"]


@pytest.mark.parametrize("to", ["Builds/manuscript/stray.txt", "Builds/Manuscript",
                                "Verification/stray.txt", ".Organizer/stray.txt",
                                ".ORGANIZER/journal.jsonl", ".GIT/stray.txt",
                                "drafts/.Git/stray.txt"])
def test_a_kept_out_folder_is_refused_in_any_case(project, to):
    """Folder names on macOS ignore case, so a kept-out folder is matched in any case."""
    proposal, record = with_change(project, {"op": "move", "path": "stray.txt", "to": to})
    assert rules(check(project, proposal, record)) == ["move"]


def test_moving_under_a_file_is_refused(project):
    proposal, record = with_change(project, {"op": "move", "path": "stray.txt",
                                             "to": "refs.bib/stray.txt"})
    assert rules(check(project, proposal, record)) == ["move"]


def test_two_moves_to_one_target_are_refused(project):
    proposal, record = good(project)
    proposal["changes"].append({"id": "c6", "op": "move", "reason": "Another loose file.",
                                "path": "notes/writing.md", "to": "misc/stray.txt"})
    problems = check(project, proposal, record)
    assert [(problem.change_id, problem.rule) for problem in problems] == [("c6", "move")]


def test_two_moves_of_one_file_are_refused(project):
    proposal, record = good(project)
    proposal["changes"].append({"id": "c6", "op": "move", "reason": "Moved twice.",
                                "path": "stray.txt", "to": "other/stray.txt"})
    problems = check(project, proposal, record)
    assert [(problem.change_id, problem.rule) for problem in problems] == [("c6", "move")]
    assert "c3" in problems[0].message


@pytest.mark.parametrize("first, second", [("misc/m", "misc/m/stray.txt"),
                                           ("misc/m/stray.txt", "misc/m"),
                                           ("misc/m", "MISC/M/stray.txt")])
def test_a_move_into_or_over_another_moves_target_is_refused(project, first, second):
    proposal, record = good(project)
    proposal["changes"] = [
        {"id": "m1", "op": "move", "reason": "A loose file.", "path": "stray.txt", "to": first},
        {"id": "m2", "op": "move", "reason": "Another loose file.", "path": "notes/writing.md",
         "to": second}]
    problems = check(project, proposal, record)
    assert [(problem.change_id, problem.rule) for problem in problems] == [("m2", "move")]
    assert "m1" in problems[0].message


def test_an_archive_line_on_a_file_an_earlier_change_moved_is_refused(project):
    proposal, record = good(project)
    proposal["changes"] = [
        {"id": "m1", "op": "move", "reason": "An old draft.", "path": "drafts/manuscript_old.md",
         "to": "old/manuscript_old.md"},
        {"id": "a1", "op": "archive_line", "reason": "An old draft.",
         "path": "drafts/manuscript_old.md", "superseded_by": "manuscript.md"}]
    problems = check(project, proposal, record)
    assert [(problem.change_id, problem.rule) for problem in problems] == [("a1", "archive_line")]
    assert "m1" in problems[0].message


def test_an_archive_line_before_a_move_of_the_same_file_is_allowed(project):
    proposal, record = good(project)
    proposal["changes"] = [
        {"id": "a1", "op": "archive_line", "reason": "An old draft.",
         "path": "drafts/manuscript_old.md", "superseded_by": "manuscript.md"},
        {"id": "m1", "op": "move", "reason": "An old draft.", "path": "drafts/manuscript_old.md",
         "to": "old/manuscript_old.md"}]
    assert check(project, proposal, record) == []


@pytest.mark.parametrize("missing", ["path", "to"])
def test_a_move_missing_a_field_is_refused(project, missing):
    change = {"op": "move", "path": "stray.txt", "to": "misc/stray.txt"}
    del change[missing]
    proposal, record = with_change(project, change)
    assert rules(check(project, proposal, record)) == ["move"]


# Archive lines.

@pytest.mark.parametrize("path", ["manuscript.md", "drafts/early.md", "notes/writing.md",
                                  "stray.txt", "drafts/missing.md"])
def test_archiving_anything_but_a_lookalike_is_refused(project, path):
    proposal, record = with_change(project, {"op": "archive_line", "path": path,
                                             "superseded_by": "manuscript.md"})
    assert rules(check(project, proposal, record)) == ["archive_line"]


@pytest.mark.parametrize("superseded_by", ["drafts/retention_full.md", "stray.txt", "nothing.md",
                                           "", None])
def test_a_superseded_by_that_is_not_canonical_is_refused(project, superseded_by):
    change = {"op": "archive_line", "path": "drafts/manuscript_old.md"}
    if superseded_by is not None:
        change["superseded_by"] = superseded_by
    proposal, record = with_change(project, change)
    assert rules(check(project, proposal, record)) == ["archive_line"]


# Marks.

def test_a_mark_on_an_unknown_session_is_refused(project):
    proposal, record = with_change(project, {"op": "mark", "item_kind": "session",
                                             "item": "no-such-session", "mark": "unused"})
    assert rules(check(project, proposal, record)) == ["mark"]


@pytest.mark.parametrize("item", ["manuscript/v003", "slides/v001", "v001"])
def test_a_mark_on_an_unknown_build_is_refused(project, item):
    proposal, record = with_change(project, {"op": "mark", "item_kind": "build", "item": item,
                                             "mark": "unused"})
    assert rules(check(project, proposal, record)) == ["mark"]


def test_a_mark_on_an_unknown_file_is_refused(project):
    proposal, record = with_change(project, {"op": "mark", "item_kind": "file",
                                             "item": "nothing.txt", "mark": "unused"})
    assert rules(check(project, proposal, record)) == ["mark"]


def test_a_mark_on_any_listed_file_is_allowed_with_unused_and_no_value(project):
    proposal, record = with_change(project, {"op": "mark", "item_kind": "file",
                                             "item": "manuscript.md", "mark": "unused"})
    assert check(project, proposal, record) == []


def test_an_unknown_item_kind_is_refused(project):
    proposal, record = with_change(project, {"op": "mark", "item_kind": "folder",
                                             "item": "drafts", "mark": "unused"})
    assert rules(check(project, proposal, record)) == ["mark"]


def test_an_unknown_mark_is_refused(project):
    proposal, record = with_change(project, {"op": "mark", "item_kind": "file",
                                             "item": "stray.txt", "mark": "deleted"})
    assert rules(check(project, proposal, record)) == ["mark"]


@pytest.mark.parametrize("mark", ["superseded", "belongs_to", "note"])
@pytest.mark.parametrize("value", [None, "", "  "])
def test_every_mark_but_unused_needs_a_value(project, mark, value):
    change = {"op": "mark", "item_kind": "file", "item": "stray.txt", "mark": mark}
    if value is not None:
        change["value"] = value
    proposal, record = with_change(project, change)
    assert rules(check(project, proposal, record)) == ["mark"]


# The description of each change.

def test_describe_gives_one_plain_line_per_change(project):
    proposal, _ = good(project)
    lines = [proposals.describe(change) for change in proposal["changes"]]
    assert lines[0] == ("c1 archive_line drafts/manuscript_old.md, superseded by manuscript.md,"
                        " because An older draft whose file name holds the manuscript's name.")
    assert lines[2] == ("c3 move stray.txt to misc/stray.txt,"
                        " because A loose file at the top of the project.")
    assert lines[3] == ("c4 mark build manuscript/v001 superseded, value manuscript/v002,"
                        " because The second build replaces the first.")
    for line in lines:
        assert "\n" not in line
        assert "\u2014" not in line


def test_describe_names_an_unknown_op(project):
    line = proposals.describe({"id": "x", "op": "tidy", "reason": "r"})
    assert "tidy" in line
    assert "\n" not in line


# The command.

def test_check_prints_each_change_and_exits_0_on_a_good_proposal(project, tmp_path):
    home = make_home(tmp_path, project)
    proposal, _ = good(project)
    path = write_proposal(tmp_path, proposal)
    code, out, err = run_command(["organize", "check", str(project), str(path),
                                  "--home", str(home)])
    assert code == 0, err + out
    for change in proposal["changes"]:
        assert proposals.describe(change) in out
    assert "No problems" in out


def test_check_prints_the_problems_after_the_changes_and_exits_1(project, tmp_path):
    home = make_home(tmp_path, project)
    proposal = recorded("delete.yaml", project, scan(project))
    path = write_proposal(tmp_path, proposal)
    code, out, err = run_command(["organize", "check", str(project), str(path),
                                  "--home", str(home)])
    assert code == 1
    change_line = out.index(proposals.describe(proposal["changes"][0]))
    problem_line = out.index("the organizer never deletes, so mark the item unused instead")
    assert change_line < problem_line


def test_check_refuses_a_stale_proposal_from_the_command(project, tmp_path):
    home = make_home(tmp_path, project)
    proposal, _ = good(project)
    path = write_proposal(tmp_path, proposal)
    (project / "notes" / "writing.md").write_text("changed\n", encoding="utf-8")
    code, out, err = run_command(["organize", "check", str(project), str(path),
                                  "--home", str(home)])
    assert code == 1
    assert "changed" in out


def test_check_changes_nothing_in_the_project(project, tmp_path):
    home = make_home(tmp_path, project)
    proposal, _ = good(project)
    path = write_proposal(tmp_path, proposal)
    bad = copy.deepcopy(proposal)
    bad["changes"][0]["op"] = "delete"
    bad_path = write_proposal(tmp_path, bad, name="bad.yaml")
    before = checksums(project)
    db_before = checksums(db_of(project).parent)
    for given in (path, bad_path):
        run_command(["organize", "check", str(project), str(given), "--home", str(home)])
    assert checksums(project) == before
    assert not (project / ".organizer").exists()
    assert checksums(db_of(project).parent) == db_before


def test_check_refuses_an_unreadable_proposal_file(project, tmp_path):
    home = make_home(tmp_path, project)
    path = tmp_path / "broken.yaml"
    path.write_text("schema: [unclosed\n", encoding="utf-8")
    code, out, err = run_command(["organize", "check", str(project), str(path),
                                  "--home", str(home)])
    assert code == 1
    assert "broken.yaml" in err
    missing = tmp_path / "absent.yaml"
    code, out, err = run_command(["organize", "check", str(project), str(missing),
                                  "--home", str(home)])
    assert code == 1
    assert "absent.yaml" in err


def test_check_refuses_without_system_yaml(project, tmp_path):
    proposal, _ = good(project)
    path = write_proposal(tmp_path, proposal)
    code, out, err = run_command(["organize", "check", str(project), str(path),
                                  "--home", str(tmp_path / "no_home")])
    assert code == 1
    assert "python3 -m features setup system" in err


def test_check_is_listed_in_the_organize_group():
    parser, helps = cli._parser()
    assert "check" in helps["organize"].format_help()
