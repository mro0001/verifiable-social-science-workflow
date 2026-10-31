"""Checks on the story's data for the prose stream (Track W, step W14).

Appendix A2.5 "Prose" asks that each AI edit come with a stated reason and
that a program line up the changes between two drafts. Since version 0.3
(Track V, step V1) the prose procedure asks no model. It reads a pin of the
earlier draft and the record of the AI's changes, neither of which the project
holds. The folder prose/ holds them for the story. The pin is kept by the
scholar, and the expected rationales say what the audit layer should write out
for the story session. Since step V4 the folder keeps no list of the scholar's
edits and no recorded judge answers, since the procedure reads neither.

Run from the repository root with python3 -m pytest examples/test_story.
Nothing here calls a model or the network.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

STORY = Path(__file__).resolve().parent
ROOT = STORY.parents[1]
VERIFICATION = ROOT / "verification_procedures"
PROJECT = STORY / "project"
PROSE = STORY / "prose"
STORY_SESSION = STORY / "sessions" / "claude_code" / "story_session.jsonl"
SOURCE = "{{PROJECT}}/manuscript.md"
FIELDS = ["id", "anchor", "kind", "rationale", "session", "session_ref"]


def records(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def parts(record):
    content = (record.get("message") or {}).get("content")
    return content if isinstance(content, list) else []


def load(name):
    return yaml.safe_load((PROSE / name).read_text(encoding="utf-8"))


def sentences(text):
    """A plain sentence split for these checks. It drops the front matter,
    skips headings, joins each paragraph's lines, and ends a sentence at a
    full stop, a question mark, or an exclamation mark before a space."""
    if text.startswith("---\n"):
        text = text.split("\n---\n", 1)[1]
    out = []
    for para in re.split(r"\n\s*\n", text):
        para = " ".join(para.split())
        if not para or para.startswith("#"):
            continue
        out += [s for s in re.split(r"(?<=[.!?])\s+", para) if s]
    return out


def stated_texts():
    """The assistant text before each Edit on the manuscript, in call order.
    A typed prompt from the scholar and each tool call clear what came before."""
    pending, out = [], []
    for r in records(STORY_SESSION):
        content = (r.get("message") or {}).get("content")
        if r["type"] == "user" and isinstance(content, str):
            pending = []
            continue
        if r["type"] != "assistant":
            continue
        for p in parts(r):
            if p.get("type") == "text":
                pending.append(p["text"])
            elif p.get("type") == "tool_use":
                if p["name"] == "Edit" and p["input"].get("file_path") == SOURCE:
                    out.append((" ".join(pending).strip(), p["input"]))
                pending = []
    return out


def test_the_pin_names_the_author_draft_by_its_checksum():
    pins = load("versions.yaml")
    assert list(pins) == ["versions"]
    assert pins["versions"] == [{
        "version": "author_draft", "file": "author_draft.md",
        "sha256": "sha256:" + hashlib.sha256((PROJECT / "author_draft.md").read_bytes()).hexdigest()}]
    text = (PROSE / "versions.yaml").read_text(encoding="utf-8")
    assert text.startswith("#") and "ledger" in text.split("versions:")[0]


def test_the_prose_folder_keeps_only_what_the_procedure_reads_and_what_the_tests_expect():
    assert sorted(p.name for p in PROSE.iterdir()) == ["expected_rationales.yaml", "versions.yaml"]


def test_the_expected_rationales_have_their_fields_in_order():
    entries = load("expected_rationales.yaml")
    assert [e["id"] for e in entries] == ["r01", "r02"]
    session = records(STORY_SESSION)[0]["sessionId"]
    for e in entries:
        assert list(e) == FIELDS
        assert e["kind"] == "insert"
        assert e["session"] == session
        # The session's public id, S and the first 12 hex characters of the sha256 of its id.
        assert e["session_ref"] == "S" + hashlib.sha256(session.encode("utf-8")).hexdigest()[:12]


def test_each_expected_anchor_is_a_sentence_of_the_manuscript_and_not_of_the_draft():
    revised = sentences((PROJECT / "manuscript.md").read_text(encoding="utf-8"))
    draft = sentences((PROJECT / "author_draft.md").read_text(encoding="utf-8"))
    for e in load("expected_rationales.yaml"):
        assert revised.count(e["anchor"]) == 1, e["anchor"]
        assert e["anchor"] not in draft, e["anchor"]


def test_each_expected_rationale_is_the_assistant_text_before_its_edit():
    stated = stated_texts()
    entries = load("expected_rationales.yaml")
    assert len(stated) == len(entries) == 2
    for e, (text, edit) in zip(entries, stated):
        assert e["rationale"] == text
        assert e["anchor"] in edit["new_string"]
        assert e["anchor"] not in edit["old_string"]


@pytest.fixture(scope="module")
def prose_run(tmp_path_factory):
    """Run the prose procedure on the story, offline. The author draft is the
    baseline, the manuscript the revised draft, and the expected rationales
    stand in for the record the audit layer writes out."""
    tmp = tmp_path_factory.mktemp("story_prose")
    inputs = tmp / "inputs"
    inputs.mkdir()
    shutil.copyfile(str(PROJECT / "author_draft.md"), str(inputs / "baseline.md"))
    shutil.copyfile(str(PROJECT / "manuscript.md"), str(inputs / "revised.md"))
    shutil.copyfile(str(PROSE / "versions.yaml"), str(inputs / "versions.yaml"))
    shutil.copyfile(str(PROSE / "expected_rationales.yaml"), str(inputs / "rationales.yaml"))
    run = tmp / "run"
    proc = subprocess.run(
        [sys.executable, "vg.py", "run", "graphs/prose.yaml", "--run", str(run),
         "--inputs", str(inputs)],
        cwd=str(VERIFICATION), capture_output=True, text=True,
        env=dict(os.environ, VG_OFFLINE="1"))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    steps = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((run / "records").glob("*.json"))]
    assert steps and [s["node"] for s in steps if s["checks"]["contract"] != "pass"] == []
    files = run / "files"

    def read(name):
        return json.loads((files / name).read_text(encoding="utf-8"))

    return {name: read(name) for name in (
        "pins.json", "changes.json", "ai_changes.json", "author_changes.json",
        "findings.json")}


def test_the_prose_procedure_finds_the_pinned_baseline(prose_run):
    assert prose_run["pins.json"]["pinned"] is True
    assert prose_run["pins.json"]["baseline"]["version"] == "author_draft"


def test_the_prose_procedure_finds_two_ai_inserts(prose_run):
    anchors = [e["anchor"] for e in load("expected_rationales.yaml")]
    changes = prose_run["changes.json"]
    assert [(c["id"], c["kind"], c["after"]) for c in changes] == [
        ("c01", "insert", anchors[0]), ("c02", "insert", anchors[1])]
    assert [c["id"] for c in prose_run["ai_changes.json"]] == ["c01", "c02"]


def test_both_inserts_are_ai_changes_with_their_stated_reasons(prose_run):
    entries = load("expected_rationales.yaml")
    assert [(c["id"], c["record_id"], c["rationale"]) for c in prose_run["ai_changes.json"]] == [
        ("c01", "r01", entries[0]["rationale"]), ("c02", "r02", entries[1]["rationale"])]
    assert prose_run["author_changes.json"] == []


def test_each_insert_is_handed_to_citations_and_nothing_blocks(prose_run):
    findings = prose_run["findings.json"]
    assert [f for f in findings if f["severity"] == "blocking"] == []
    assert [f for f in findings if f["check"] == "rationale_coverage"] == []
    for cid in ("c01", "c02"):
        handoffs = [f for f in findings if f["check"] == "content_handoff" and f["item"] == cid]
        assert len(handoffs) == 1, cid
        assert handoffs[0]["severity"] == "warning"
        assert "citations" in handoffs[0]["message"]
    warnings = [f for f in findings if f["severity"] == "warning"]
    assert sorted((f["check"], f["item"]) for f in warnings) == [
        ("content_handoff", "c01"), ("content_handoff", "c02")]
