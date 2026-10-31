"""Tests for the session's public id in the three records (Track P, step P2).

A session's public id is S followed by the first 12 hex characters of the
sha256 of the harness's id for it (Track P choice 1). The audit layer holds
the rule, and the citation log, the rationales record, and the file-writes
record carry it as session_ref beside the harness's id, so the reports can
copy it. The sessions are the test story's two synthetic Claude Code session
files, whose folder token {{PROJECT}} is replaced with a temporary folder,
captured into an audit store in a temporary folder. No real session file is
read, and nothing here calls a model or the network. Run from the repository
root with python3 -m pytest -q audit_layer/tests.
"""
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from audit_layer.capture import capture_file  # noqa: E402
from audit_layer.records.citation_log import citation_log, write_citation_log  # noqa: E402
from audit_layer.records.rationales import FIELDS, rationales, write_rationales  # noqa: E402
from audit_layer.records.session_index import public_id  # noqa: E402
from audit_layer.records.session_writes import session_writes  # noqa: E402
from audit_layer.store import open_store  # noqa: E402

STORY = ROOT / "examples" / "test_story"
SESSIONS = STORY / "sessions" / "claude_code"
TOKEN = "{{PROJECT}}"

STORY_ID = "5f3c0413-2a7d-4b9e-8c61-a0d4e7b2c913"
TOUCH_ID = "8b21d6e4-9c3a-4f57-a2e0-3d6c1f84b705"
# The public ids of the two story sessions, worked out once by hand from the
# sha256 of each id.
STORY_REF = "S55ac19fb97b9"
TOUCH_REF = "Sadbdcaecef34"

NO_FOLDERS = {"excluded_folders": []}


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
    folder = tmp_path / "project"
    folder.mkdir()
    return folder


@pytest.fixture
def audit(tmp_path, project):
    """An audit store holding both story sessions, run in the project folder."""
    store = open_store(tmp_path / "audit_home")
    for name in ("story_session.jsonl", "build_touch_session.jsonl"):
        text = (SESSIONS / name).read_text(encoding="utf-8")
        path = tmp_path / name
        path.write_text(text.replace(TOKEN, json.dumps(str(project))[1:-1]), encoding="utf-8")
        summary = capture_file(store, path, NO_FOLDERS)
        assert not summary.excluded
    yield store
    store.db.close()


# ------------------------------------------------------------------ the rule


def test_the_public_id_is_s_and_the_first_12_hex_characters_of_the_sha256():
    # The sha256 of abc is ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad.
    assert public_id("abc") == "Sba7816bf8f01"


def test_the_story_sessions_give_their_public_ids():
    assert public_id(STORY_ID) == STORY_REF
    assert public_id(TOUCH_ID) == TOUCH_REF


def test_the_public_id_is_the_same_each_time_and_differs_between_sessions():
    assert public_id(STORY_ID) == public_id(STORY_ID)
    assert public_id(STORY_ID) != public_id(TOUCH_ID)
    # A subagent's id holds its parent's, and its public id is its own.
    assert public_id(STORY_ID + "/agent-a1") != public_id(STORY_ID)


@pytest.mark.parametrize("given", ["", "   ", None, 7])
def test_the_public_id_needs_the_harness_id_as_text(given):
    with pytest.raises(ValueError):
        public_id(given)


# ------------------------------------------------------------------ the records


def test_each_citation_log_entry_carries_its_sessions_public_id(audit, project):
    log = citation_log(audit, project)
    assert sorted(log["citations"]) == ["dumont2014", "nakamura2020"]
    for entry in log["citations"].values():
        assert list(entry) == ["introduced_by", "draft", "session", "session_ref"]
        assert entry["session"] == STORY_ID
        assert entry["session_ref"] == STORY_REF


def test_the_written_citation_log_keeps_the_public_id(tmp_path, audit, project):
    out = tmp_path / "citation_log.yaml"
    write_citation_log(audit, project, out)
    loaded = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert {e["session_ref"] for e in loaded["citations"].values()} == {STORY_REF}


def test_each_rationale_carries_its_sessions_public_id_after_the_session(tmp_path, audit, project):
    assert FIELDS == ("id", "anchor", "kind", "rationale", "session", "session_ref")
    entries = rationales(audit, project / "manuscript.md")
    assert len(entries) == 2
    assert {(e["session"], e["session_ref"]) for e in entries} == {(STORY_ID, STORY_REF)}
    out = tmp_path / "rationales.yaml"
    write_rationales(entries, out)
    loaded = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert [list(e) for e in loaded] == [list(FIELDS)] * 2


def test_each_file_write_carries_its_sessions_public_id(audit, project):
    rows = session_writes(audit, project)
    assert [(r["path"], r["session"], r["session_ref"]) for r in rows] == [
        ("manuscript.md", STORY_ID, STORY_REF),
        ("manuscript.md", STORY_ID, STORY_REF),
        ("source_notes.md", STORY_ID, STORY_REF),
        ("builds/manuscript/v001.md", TOUCH_ID, TOUCH_REF),
    ]


def test_the_story_expected_records_hold_the_public_ids():
    log = yaml.safe_load((STORY / "references" / "expected_citation_log.yaml").read_text(encoding="utf-8"))
    assert {e["session_ref"] for e in log["citations"].values()} == {STORY_REF}
    entries = yaml.safe_load((STORY / "prose" / "expected_rationales.yaml").read_text(encoding="utf-8"))
    assert {e["session_ref"] for e in entries} == {STORY_REF}
    lines = (STORY / "build" / "expected_session_writes.jsonl").read_text(encoding="utf-8").splitlines()
    rows = [json.loads(line) for line in lines]
    assert [r["session_ref"] for r in rows] == [STORY_REF, STORY_REF, STORY_REF, TOUCH_REF]
