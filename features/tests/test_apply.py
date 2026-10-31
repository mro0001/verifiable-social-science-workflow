"""Step F9. Apply, the journal, and the content store.

The good proposal of step F8 is applied to a copy of the organizer fixture
with two builds made by ospipe build through the layer runner and a session
from make_audit_db. Archive lines are written by ospipe archive through the
runner (reconciliation, Track F).

Run from the repository root as python3 -m pytest -q features/tests.
"""
import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from features import cli
from features.layers import LayerMissing
from features.organizer import apply as organize_apply
from features.organizer import inventory, journal, proposals
from features.tests import helpers
from features.tests.test_proposals import (NOW, SESSION, checksums, db_of, good, make_home,
                                           ospipe_build, recorded, run_command, scan, session_db,
                                           write_proposal)

ROOT = helpers.ROOT
ARCHIVE_LINE = re.compile(r"^> ARCHIVE \d{4}-\d{2}-\d{2}: superseded by \S+$")
COMMON = ["schema_version", "entry", "at", "by", "proposed_by", "proposal_sha256",
          "change_id", "op", "reason"]
OP_FIELDS = {
    "move": ["path", "to", "sha256"],
    "archive_line": ["path", "superseded_by", "line", "before_sha256", "after_sha256"],
    "mark": ["item_kind", "item", "mark", "value"],
}


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


def good_file(project, tmp_path, name="proposal.yaml"):
    proposal, _ = good(project)
    return proposal, write_proposal(tmp_path, proposal, name=name)


def apply_file(project, path, by="Test Scholar", now=NOW):
    return organize_apply.apply_proposal(str(project), str(path), by, now, root=str(ROOT),
                                         audit_db=str(db_of(project)))


def organizer(project):
    return project / ".organizer"


def entries(project):
    return journal.read_journal(str(project))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def outside_organizer(project):
    return dict((path, digest) for path, digest in checksums(project).items()
                if not path.startswith(".organizer" + os.sep))


def first_line_after_front_matter(text):
    lines = text.splitlines()
    if lines and lines[0] == "---":
        end = lines.index("---", 1)
        return lines[end + 1]
    return lines[0]


# The content store.

def test_keep_bytes_keeps_content_once_under_its_checksum(project):
    data = b"some bytes\n"
    digest = journal.keep_bytes(str(project), data)
    assert digest == sha(data)
    kept = organizer(project) / "originals" / digest
    assert kept.read_bytes() == data
    stamp = kept.stat().st_mtime_ns
    assert journal.keep_bytes(str(project), data) == digest
    assert kept.stat().st_mtime_ns == stamp
    assert sorted(os.listdir(str(organizer(project) / "originals"))) == [digest]


# The journal.

def test_append_entry_numbers_entries_and_stamps_each_line(project):
    first = journal.append_entry(str(project), {"by": "A", "op": "mark"}, NOW)
    second = journal.append_entry(str(project), {"by": "B", "op": "mark"}, NOW)
    assert (first, second) == ("j0001", "j0002")
    lines = (organizer(project) / "journal.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    record = json.loads(lines[0])
    assert record["schema_version"] == 1
    assert record["entry"] == "j0001"
    assert record["at"] == "2026-10-29T09:30:00+00:00"
    assert record["by"] == "A"
    assert record["undoes"] is None
    assert [item["entry"] for item in entries(project)] == ["j0001", "j0002"]


def test_a_journal_line_that_is_not_json_is_an_error(project):
    organizer(project).mkdir()
    (organizer(project) / "journal.jsonl").write_text("{not json\n", encoding="utf-8")
    with pytest.raises(journal.JournalError) as raised:
        journal.read_journal(str(project))
    assert "line 1" in str(raised.value)


def test_a_missing_journal_reads_as_empty(project):
    assert journal.read_journal(str(project)) == []


def cut_short(project):
    """Leave a one-entry journal whose last line has no line break."""
    journal.append_entry(str(project), {"by": "A", "op": "mark"}, NOW)
    path = organizer(project) / "journal.jsonl"
    path.write_bytes(path.read_bytes().rstrip(b"\n"))
    return path


def test_a_journal_that_does_not_end_with_a_line_break_is_an_error(project):
    cut_short(project)
    with pytest.raises(journal.JournalError) as raised:
        journal.read_journal(str(project))
    assert "line break" in str(raised.value)


def test_an_empty_journal_file_reads_as_empty(project):
    organizer(project).mkdir()
    (organizer(project) / "journal.jsonl").write_bytes(b"")
    assert journal.read_journal(str(project)) == []


# The good proposal.

def test_the_good_proposal_applies_every_change(project, tmp_path):
    _, path = good_file(project, tmp_path)
    result = apply_file(project, path)
    assert result.problems == []
    assert [entry for _, entry in result.applied] == ["j0001", "j0002", "j0003", "j0004",
                                                     "j0005"]
    assert result.not_applied == []


def test_the_move_keeps_the_checksum_and_leaves_nothing_at_the_old_path(project, tmp_path):
    before = sha((project / "stray.txt").read_bytes())
    _, path = good_file(project, tmp_path)
    apply_file(project, path)
    assert not os.path.lexists(str(project / "stray.txt"))
    assert sha((project / "misc" / "stray.txt").read_bytes()) == before


def test_the_archive_line_follows_the_front_matter_and_the_file_scans_as_archived(
        project, tmp_path):
    _, path = good_file(project, tmp_path)
    apply_file(project, path)
    text = (project / "drafts" / "manuscript_old.md").read_text(encoding="utf-8")
    assert text.startswith("---\n")
    line = first_line_after_front_matter(text)
    assert ARCHIVE_LINE.match(line)
    assert line == "> ARCHIVE 2026-10-29: superseded by manuscript.md"
    files = dict((entry["path"], entry) for entry in scan(project)["files"])
    assert files["drafts/manuscript_old.md"]["kind"] == "archived"
    assert files["drafts/manuscript_old.md"]["archive_line"] == line


def test_with_no_front_matter_the_archive_line_is_at_the_top_and_the_title_still_reads(
        project, tmp_path):
    _, path = good_file(project, tmp_path)
    apply_file(project, path)
    text = (project / "drafts" / "retention_full.md").read_text(encoding="utf-8")
    first = text.splitlines()[0]
    assert ARCHIVE_LINE.match(first)
    assert text.splitlines()[1] == ""
    assert inventory.title_of(text) == "retention in small agencies"
    files = dict((entry["path"], entry) for entry in scan(project)["files"])
    assert files["drafts/retention_full.md"]["kind"] == "archived"
    assert files["drafts/retention_full.md"]["claims"] == "manuscript.md"


def test_the_original_and_new_bytes_sit_in_the_content_store(project, tmp_path):
    original = (project / "drafts" / "manuscript_old.md").read_bytes()
    _, path = good_file(project, tmp_path)
    apply_file(project, path)
    entry = entries(project)[0]
    assert entry["op"] == "archive_line"
    store = organizer(project) / "originals"
    assert entry["before_sha256"] == sha(original)
    assert (store / entry["before_sha256"]).read_bytes() == original
    after = (project / "drafts" / "manuscript_old.md").read_bytes()
    assert entry["after_sha256"] == sha(after)
    assert (store / entry["after_sha256"]).read_bytes() == after


def test_marks_yaml_lists_the_build_and_session_marks(project, tmp_path):
    _, path = good_file(project, tmp_path)
    apply_file(project, path)
    marks = yaml.safe_load((organizer(project) / "marks.yaml").read_text(encoding="utf-8"))
    assert marks["schema"] == "organizer-marks"
    assert marks["schema_version"] == 1
    found = [(mark["item_kind"], mark["item"], mark["mark"], mark["value"])
             for mark in marks["marks"]]
    assert found == [("build", "manuscript/v001", "superseded", "manuscript/v002"),
                     ("session", SESSION, "belongs_to", os.path.realpath(str(project)))]
    for mark in marks["marks"]:
        assert sorted(mark) == sorted(["item_kind", "item", "mark", "value", "reason", "entry",
                                       "by", "proposed_by"])
        assert mark["by"] == "Test Scholar"
        assert mark["proposed_by"] == "ai:claude_code:" + SESSION
    assert [mark["entry"] for mark in marks["marks"]] == ["j0004", "j0005"]


def test_the_journal_has_five_entries_with_every_field(project, tmp_path):
    proposal, path = good_file(project, tmp_path)
    proposal_sha = sha(path.read_bytes())
    apply_file(project, path)
    found = entries(project)
    assert len(found) == 5
    for entry, change in zip(found, proposal["changes"]):
        assert list(entry) == COMMON + OP_FIELDS[change["op"]] + ["undoes"]
        assert entry["schema_version"] == 1
        assert entry["at"] == "2026-10-29T09:30:00+00:00"
        assert entry["by"] == "Test Scholar"
        assert entry["proposed_by"] == proposal["proposed_by"]
        assert entry["proposal_sha256"] == proposal_sha
        assert entry["change_id"] == change["id"]
        assert entry["op"] == change["op"]
        assert entry["reason"] == change["reason"]
        assert entry["undoes"] is None
    move = found[2]
    assert (move["path"], move["to"]) == ("stray.txt", "misc/stray.txt")
    assert move["sha256"] == sha((project / "misc" / "stray.txt").read_bytes())
    assert found[0]["line"] == "> ARCHIVE 2026-10-29: superseded by manuscript.md"
    assert found[0]["superseded_by"] == "manuscript.md"


def test_nothing_is_lost(project, tmp_path):
    before = set(checksums(project).values())
    _, path = good_file(project, tmp_path)
    apply_file(project, path)
    after = set(checksums(project).values())
    store = organizer(project) / "originals"
    kept = set(sha((store / name).read_bytes()) for name in os.listdir(str(store)))
    assert before - after - kept == set()


def test_apply_writes_a_fresh_inventory(project, tmp_path):
    _, path = good_file(project, tmp_path)
    result = apply_file(project, path)
    written = json.loads((organizer(project) / "inventory.json").read_text(encoding="utf-8"))
    assert written["inventory_id"] == scan(project)["inventory_id"]
    assert result.inventory_path == str(organizer(project) / "inventory.json")
    assert "misc/stray.txt" in [entry["path"] for entry in written["files"]]


# Refusals.

def test_a_proposal_with_one_problem_applies_nothing(project, tmp_path):
    proposal, _ = good(project)
    proposal["changes"].append({"id": "c6", "op": "delete", "reason": "Old.",
                                "path": "notes/writing.md"})
    path = write_proposal(tmp_path, proposal)
    before = checksums(project)
    result = apply_file(project, path)
    assert [problem.change_id for problem in result.problems] == ["c6"]
    assert result.applied == []
    assert checksums(project) == before
    assert not organizer(project).exists()


def test_a_proposal_with_a_problem_leaves_an_earlier_journal_unchanged(project, tmp_path):
    _, path = good_file(project, tmp_path)
    apply_file(project, path)
    journal_bytes = (organizer(project) / "journal.jsonl").read_bytes()
    record = scan(project)
    bad = recorded("delete.yaml", project, record)
    bad_path = write_proposal(tmp_path, bad, name="bad.yaml")
    before = outside_organizer(project)
    result = apply_file(project, bad_path)
    assert result.problems
    assert result.applied == []
    assert (organizer(project) / "journal.jsonl").read_bytes() == journal_bytes
    assert outside_organizer(project) == before


def test_the_same_proposal_applied_again_is_refused_as_stale(project, tmp_path):
    _, path = good_file(project, tmp_path)
    apply_file(project, path)
    journal_bytes = (organizer(project) / "journal.jsonl").read_bytes()
    result = apply_file(project, path)
    assert [problem.rule for problem in result.problems] == ["inventory_id"]
    assert result.applied == []
    assert (organizer(project) / "journal.jsonl").read_bytes() == journal_bytes


def test_earlier_journal_lines_are_unchanged_after_a_later_apply(project, tmp_path):
    _, path = good_file(project, tmp_path)
    apply_file(project, path)
    journal_bytes = (organizer(project) / "journal.jsonl").read_bytes()
    record = scan(project)
    later = {"schema": "organizer-proposal", "schema_version": 1,
             "proposed_by": "scholar:Test Scholar", "inventory_id": record["inventory_id"],
             "changes": [{"id": "d1", "op": "mark", "reason": "Not used any more.",
                          "item_kind": "file", "item": "notes/writing.md", "mark": "unused"}]}
    later_path = write_proposal(tmp_path, later, name="later.yaml")
    result = apply_file(project, later_path)
    assert [entry for _, entry in result.applied] == ["j0006"]
    now_bytes = (organizer(project) / "journal.jsonl").read_bytes()
    assert now_bytes.startswith(journal_bytes)
    assert len(now_bytes.splitlines()) == 6
    marks = yaml.safe_load((organizer(project) / "marks.yaml").read_text(encoding="utf-8"))
    assert [mark["entry"] for mark in marks["marks"]] == ["j0004", "j0005", "j0006"]
    assert marks["marks"][2]["value"] is None


def test_a_move_whose_target_appears_after_the_check_stops_there(project, tmp_path,
                                                                 monkeypatch):
    _, path = good_file(project, tmp_path)
    real_check = proposals.check_proposal

    def check_then_make_target(project_dir, proposal, record):
        problems = real_check(project_dir, proposal, record)
        (project / "misc").mkdir()
        (project / "misc" / "stray.txt").write_text("came later\n", encoding="utf-8")
        return problems

    monkeypatch.setattr(organize_apply, "check_proposal", check_then_make_target)
    result = apply_file(project, path)
    assert [entry for _, entry in result.applied] == ["j0001", "j0002"]
    assert [change["id"] for change, _ in result.not_applied] == ["c3", "c4", "c5"]
    assert "misc/stray.txt" in result.not_applied[0][1]
    assert (project / "stray.txt").exists()
    assert (project / "misc" / "stray.txt").read_text(encoding="utf-8") == "came later\n"
    assert len(entries(project)) == 2
    marks = yaml.safe_load((organizer(project) / "marks.yaml").read_text(encoding="utf-8"))
    assert marks["marks"] == []


def test_a_failed_archive_stops_there_and_journals_only_what_succeeded(project, tmp_path):
    _, path = good_file(project, tmp_path)
    calls = []

    def runner(layer, args, root=None, cwd=None, env=None, timeout=600):
        if layer == "ospipe" and args and args[0] == "archive":
            calls.append(args)
            if len(calls) == 2:
                return helpers_result(args, 2, "", "cannot archive the draft\n")
        return organize_apply.run_layer(layer, args, root=root, cwd=cwd, env=env,
                                        timeout=timeout)

    original = (project / "drafts" / "retention_full.md").read_bytes()
    result = organize_apply.apply_proposal(str(project), str(path), "Test Scholar", NOW,
                                           root=str(ROOT), runner=runner,
                                           audit_db=str(db_of(project)))
    assert [entry for _, entry in result.applied] == ["j0001"]
    assert [change["id"] for change, _ in result.not_applied] == ["c2", "c3", "c4", "c5"]
    assert "cannot archive the draft" in result.not_applied[0][1]
    assert (project / "drafts" / "retention_full.md").read_bytes() == original
    assert (project / "stray.txt").exists()
    assert len(entries(project)) == 1



@pytest.mark.parametrize("raised,said", [
    (subprocess.TimeoutExpired(["python", "-m", "ospipe", "archive"], 600), "timed out"),
    (LayerMissing("the ospipe layer is missing"), "the ospipe layer is missing"),
])
def test_a_runner_error_during_an_archive_stops_there_and_still_refreshes(project, tmp_path,
                                                                          raised, said):
    _, path = good_file(project, tmp_path)
    calls = []

    def runner(layer, args, root=None, cwd=None, env=None, timeout=600):
        if layer == "ospipe" and args and args[0] == "archive":
            calls.append(args)
            if len(calls) == 2:
                raise raised
        return organize_apply.run_layer(layer, args, root=root, cwd=cwd, env=env,
                                        timeout=timeout)

    original = (project / "drafts" / "retention_full.md").read_bytes()
    result = organize_apply.apply_proposal(str(project), str(path), "Test Scholar", NOW,
                                           root=str(ROOT), runner=runner,
                                           audit_db=str(db_of(project)))
    assert [entry for _, entry in result.applied] == ["j0001"]
    assert [change["id"] for change, _ in result.not_applied] == ["c2", "c3", "c4", "c5"]
    assert said in result.not_applied[0][1]
    assert (project / "drafts" / "retention_full.md").read_bytes() == original
    assert len(entries(project)) == 1
    assert result.inventory_path is not None and os.path.isfile(result.inventory_path)
    marks = yaml.safe_load((organizer(project) / "marks.yaml").read_text(encoding="utf-8"))
    assert marks["marks"] == []

def helpers_result(args, code, out, err):
    from features.layers import LayerResult
    return LayerResult(["python", "-m", "ospipe"] + list(args), code, out, err)


def test_apply_runs_ospipe_archive_for_each_archive_line(project, tmp_path):
    _, path = good_file(project, tmp_path)
    seen = []

    def runner(layer, args, root=None, cwd=None, env=None, timeout=600):
        seen.append((layer, list(args), cwd))
        return organize_apply.run_layer(layer, args, root=root, cwd=cwd, env=env,
                                        timeout=timeout)

    organize_apply.apply_proposal(str(project), str(path), "Test Scholar", NOW, root=str(ROOT),
                                  runner=runner, audit_db=str(db_of(project)))
    archives = [(args, cwd) for layer, args, cwd in seen if layer == "ospipe"
                and args[0] == "archive"]
    real = os.path.realpath(str(project))
    assert archives == [
        (["archive", "drafts/manuscript_old.md", "--by", "manuscript.md", "--date",
          "2026-10-29"], real),
        (["archive", "drafts/retention_full.md", "--by", "manuscript.md", "--date",
          "2026-10-29"], real),
    ]


def test_apply_needs_a_name(project, tmp_path):
    _, path = good_file(project, tmp_path)
    with pytest.raises(organize_apply.ApplyError):
        apply_file(project, path, by="  ")
    assert not organizer(project).exists()


def test_a_broken_journal_stops_apply_before_any_change(project, tmp_path):
    _, path = good_file(project, tmp_path)
    organizer(project).mkdir()
    (organizer(project) / "journal.jsonl").write_text("{broken\n", encoding="utf-8")
    before = outside_organizer(project)
    with pytest.raises(journal.JournalError):
        apply_file(project, path)
    assert outside_organizer(project) == before



def test_a_journal_cut_short_stops_apply_before_any_change(project, tmp_path):
    _, path = good_file(project, tmp_path)
    journal_file = cut_short(project)
    saved = journal_file.read_bytes()
    before = outside_organizer(project)
    with pytest.raises(journal.JournalError):
        apply_file(project, path)
    assert outside_organizer(project) == before
    assert journal_file.read_bytes() == saved

# The command.

def test_apply_prints_each_applied_change_with_its_entry(project, tmp_path):
    home = make_home(tmp_path, project)
    proposal, path = good_file(project, tmp_path)
    code, out, err = run_command(["organize", "apply", str(project), str(path),
                                  "--by", "Test Scholar", "--home", str(home)])
    assert code == 0, err
    for number, change in enumerate(proposal["changes"], start=1):
        assert "j%04d %s" % (number, proposals.describe(change)) in out
    assert "marks.yaml" in out
    assert "inventory.json" in out


def test_apply_prints_the_problems_and_exits_1(project, tmp_path):
    home = make_home(tmp_path, project)
    bad = recorded("delete.yaml", project, scan(project))
    path = write_proposal(tmp_path, bad)
    code, out, err = run_command(["organize", "apply", str(project), str(path),
                                  "--by", "Test Scholar", "--home", str(home)])
    assert code == 1
    assert "the organizer never deletes, so mark the item unused instead" in out
    assert "Nothing was applied" in out
    assert not organizer(project).exists()


def test_apply_needs_by_on_the_command_line(project, tmp_path):
    _, path = good_file(project, tmp_path)
    parser, _ = cli._parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["organize", "apply", str(project), str(path)])


def test_apply_refuses_without_system_yaml(project, tmp_path):
    _, path = good_file(project, tmp_path)
    code, out, err = run_command(["organize", "apply", str(project), str(path),
                                  "--by", "Test Scholar", "--home", str(tmp_path / "no_home")])
    assert code == 1
    assert "python3 -m features setup system" in err
    assert not organizer(project).exists()


def test_apply_is_listed_in_the_organize_group():
    parser, helps = cli._parser()
    assert "apply" in helps["organize"].format_help()
