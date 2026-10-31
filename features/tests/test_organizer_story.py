"""Step F11. The organizer's guide and the story run.

On a temporary copy of the test story's project, system setup (fake
detection, temporary homes), project setup with the manuscript product, and
capture of the story session through the runner come first. Then the
organizer's commands run as a scholar would run them. By the reconciliation
(Track F), author_draft.md is protected and never a look-alike, and the
recorded proposal marks it with a note instead of archiving it. So the undo
here undoes that mark, and the draft stays byte for byte as the story has it.

The guide's tests read every organizer command line in
features/organizer/GUIDE.md and its one example proposal.

Run from the repository root as python3 -m pytest -q features/tests.
"""
import json
import os
import re
import shlex
import shutil
from pathlib import Path

import pytest
import yaml

from features import cli, layers
from features.organizer import inventory, journal, proposals
from features.setup import project as setup_project
from features.setup import system
from features.tests import helpers
from features.tests.test_proposals import NOW, checksums, run_command
from features.tests.test_system_setup import fake_detector

ROOT = helpers.ROOT
STORY = ROOT / "examples" / "test_story" / "project"
GUIDE = ROOT / "features" / "organizer" / "GUIDE.md"
STORY_PROPOSAL = helpers.FIXTURES / "story_proposal.yaml"
SESSION = helpers.STORY_SESSION_ID

PROPOSAL_KEYS = ("schema", "schema_version", "proposed_by", "inventory_id", "changes")
CHANGE_KEYS = ("id", "op", "reason")
OP_KEYS = {"move": ("path", "to"),
           "archive_line": ("path", "superseded_by"),
           "mark": ("item_kind", "item", "mark", "value")}
ORGANIZE_COMMANDS = ("scan", "check", "apply", "undo", "log")


@pytest.fixture(autouse=True)
def private_home(tmp_path, monkeypatch):
    """Point HOME and both home variables at temporary folders, so nothing real is touched."""
    home = tmp_path / "user_home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("AUDIT_HOME", str(tmp_path / "env_audit_home"))
    monkeypatch.setenv("FEATURES_HOME", str(tmp_path / "env_features_home"))
    monkeypatch.setattr(setup_project, "_interactive", lambda: False)
    return home


def story_files():
    """The story project's own files, as relative paths with their bytes."""
    found = {}
    for here, folders, files in os.walk(str(STORY)):
        folders[:] = [name for name in folders if name != "__pycache__"]
        for name in files:
            path = os.path.join(here, name)
            found[os.path.relpath(path, str(STORY))] = Path(path).read_bytes()
    return found


def outside_organizer(folder):
    return dict((path, digest) for path, digest in checksums(folder).items()
                if not path.startswith(journal.ORGANIZER_DIR + os.sep))


@pytest.fixture
def story(tmp_path):
    """The story project set up and its session captured, with the features home."""
    folder = tmp_path / "story"
    shutil.copytree(str(STORY), str(folder), ignore=shutil.ignore_patterns("__pycache__"))
    home = tmp_path / "features_home"
    audit_home = tmp_path / "audit_home"
    given = {"scholar_name": "Test Scholar", "excluded_folders": [], "citation_export": ""}
    result = system.run_system_setup(str(home), str(audit_home), given, str(ROOT), NOW,
                                     detector=fake_detector())
    assert result.ready
    code, out, err = run_command(["setup", "project", str(folder), "--home", str(home),
                                  "--product", "manuscript:manuscript.md:docx"])
    assert code == 0, out + err
    session = helpers.story_session(folder, tmp_path / "sessions" / "story_session.jsonl")
    captured = layers.run_layer("audit_layer", ["capture", "--harness", "claude_code", str(session)],
                                root=str(ROOT), env={"AUDIT_HOME": str(audit_home)})
    assert captured.returncode == 0, captured.stderr
    return folder, home


def organize(*args):
    return run_command(["organize"] + [str(arg) for arg in args])


def story_proposal(folder, tmp_path):
    """The recorded story proposal with the inventory id of the scan just written."""
    record = json.loads((folder / ".organizer" / "inventory.json").read_text(encoding="utf-8"))
    text = STORY_PROPOSAL.read_text(encoding="utf-8").replace("{{INVENTORY_ID}}",
                                                              record["inventory_id"])
    path = folder / ".organizer" / "proposals" / "2026-10-29_1.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# Setup keeps the story.

def test_project_setup_keeps_every_story_file(story):
    folder, _ = story
    for path, data in story_files().items():
        assert (folder / path).read_bytes() == data, path


# The scan.

def test_the_scan_lists_the_story_session_and_protects_the_authors_draft(story):
    folder, home = story
    code, out, err = organize("scan", folder, "--home", home)
    assert code == 0, out + err
    record = json.loads((folder / ".organizer" / "inventory.json").read_text(encoding="utf-8"))
    sessions = dict((item["harness_session_id"], item) for item in record["sessions"])
    assert SESSION in sessions and sessions[SESSION]["ran_here"]
    assert SESSION in out
    files = dict((entry["path"], entry) for entry in record["files"])
    assert files["manuscript.md"]["kind"] == "canonical"
    assert SESSION in files["manuscript.md"]["sessions"]
    draft = files["author_draft.md"]
    assert draft["protected"] is True
    assert draft["kind"] != "lookalike"
    assert draft["archive_line"] is None


def test_the_authors_draft_reads_as_the_manuscript_by_its_title(story):
    """The draft would be a look-alike by its title, which is why it gets a note."""
    folder, _ = story
    draft = (folder / "author_draft.md").read_text(encoding="utf-8")
    manuscript = (folder / "manuscript.md").read_text(encoding="utf-8")
    assert inventory.title_of(draft) == inventory.title_of(manuscript)


# The recorded proposal, checked, applied, logged, and one entry undone.

def test_the_story_proposal_passes_the_check_and_changes_nothing(story, tmp_path):
    folder, home = story
    assert organize("scan", folder, "--home", home)[0] == 0
    path = story_proposal(folder, tmp_path)
    before = outside_organizer(folder)
    code, out, err = organize("check", folder, path, "--home", home)
    assert code == 0, out + err
    assert "No problems" in out
    assert outside_organizer(folder) == before


def test_the_story_run_applies_logs_and_undoes(story, tmp_path):
    folder, home = story
    draft = (STORY / "author_draft.md").read_bytes()
    assert organize("scan", folder, "--home", home)[0] == 0
    path = story_proposal(folder, tmp_path)
    before = outside_organizer(folder)

    code, out, err = organize("apply", folder, path, "--by", "Test Scholar", "--home", home)
    assert code == 0, out + err
    assert "Applied 3 of 3" in out
    entries = journal.read_journal(str(folder))
    assert [entry["entry"] for entry in entries] == ["j0001", "j0002", "j0003"]
    assert all(entry["by"] == "Test Scholar" for entry in entries)
    assert all(entry["proposed_by"] == "ai:claude_code:" + SESSION for entry in entries)
    assert outside_organizer(folder) == before
    marks = yaml.safe_load((folder / ".organizer" / "marks.yaml").read_text(encoding="utf-8"))
    assert [(mark["item_kind"], mark["item"]) for mark in marks["marks"]] == [
        ("file", "author_draft.md"), ("session", SESSION), ("file", "README.md")]

    code, out, err = organize("log", folder)
    assert code == 0, out + err
    for entry in ("j0001", "j0002", "j0003"):
        assert entry in out
    assert "j0004" not in out

    code, out, err = organize("undo", folder, "j0001", "--by", "Test Scholar", "--home", home)
    assert code == 0, out + err
    assert (folder / "author_draft.md").read_bytes() == draft
    assert outside_organizer(folder) == before
    marks = yaml.safe_load((folder / ".organizer" / "marks.yaml").read_text(encoding="utf-8"))
    assert [(mark["item_kind"], mark["item"]) for mark in marks["marks"]] == [
        ("session", SESSION), ("file", "README.md")]
    code, out, err = organize("log", folder)
    assert code == 0, out + err
    assert "j0004" in out
    assert [entry["undoes"] for entry in journal.read_journal(str(folder))] == [
        None, None, None, "j0001"]


def test_the_story_proposal_names_the_session_and_only_the_organizers_operations():
    proposal = yaml.safe_load(STORY_PROPOSAL.read_text(encoding="utf-8"))
    assert proposal["proposed_by"] == "ai:claude_code:" + SESSION
    ops = [change["op"] for change in proposal["changes"]]
    assert ops == ["mark", "mark", "mark"]
    assert "archive_line" not in ops


# The guide.

def guide_text():
    return GUIDE.read_text(encoding="utf-8")


def guide_commands():
    return re.findall(r"python3 -m features (organize [^`\n]*)", guide_text())


def guide_proposals():
    return re.findall(r"```yaml\n(.*?)```", guide_text(), re.DOTALL)


def test_every_organizer_line_in_the_guide_parses_with_the_command():
    commands = guide_commands()
    parser, _ = cli._parser()
    seen = set()
    for line in commands:
        options = parser.parse_args(shlex.split(line))
        assert options.group == "organize", line
        assert options.command in ORGANIZE_COMMANDS, line
        seen.add(options.command)
    assert seen == set(ORGANIZE_COMMANDS)


def test_the_guide_holds_one_example_proposal_with_known_fields_and_operations():
    blocks = guide_proposals()
    assert len(blocks) == 1
    proposal = yaml.safe_load(blocks[0])
    assert set(proposal) == set(PROPOSAL_KEYS)
    assert proposal["schema"] == proposals.SCHEMA
    assert proposal["schema_version"] == proposals.SCHEMA_VERSION
    ops = set()
    for change in proposal["changes"]:
        assert change["op"] in proposals.OPERATIONS
        assert set(change) <= set(CHANGE_KEYS + OP_KEYS[change["op"]]), change
        assert set(CHANGE_KEYS) <= set(change), change
        assert change["reason"].strip()
        if change["op"] == "mark":
            assert change["item_kind"] in proposals.ITEM_KINDS
            assert change["mark"] in proposals.MARKS
        ops.add(change["op"])
    assert ops == set(proposals.OPERATIONS)


def test_the_guides_example_passes_the_check_on_the_organizer_fixture(tmp_path):
    folder = helpers.copy_fixture("organizer_project", tmp_path)
    record = inventory.build_inventory(str(folder), NOW, root=str(ROOT))
    proposal = yaml.safe_load(guide_proposals()[0])
    proposal["inventory_id"] = record["inventory_id"]
    assert proposals.check_proposal(str(folder), proposal, record) == []


def test_the_guide_says_what_the_organizer_never_does_and_where_proposals_go():
    text = guide_text()
    for words in (".organizer/inventory.json", ".organizer/proposals/<YYYY-MM-DD>_<n>.yaml",
                  "`inventory_id`", "`proposed_by`", "`unused`", "never delete",
                  "`author_draft.md`", "scholar's word", "PYTHONPATH"):
        assert words in text, words
    for op in proposals.OPERATIONS:
        assert "`%s`" % op in text, op
    assert "\u2014" not in text
