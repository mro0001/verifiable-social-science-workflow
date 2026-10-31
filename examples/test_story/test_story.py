"""Checks on the test story, the one synthetic story every layer's tests come from.

The story follows Figure A6. Before the session the scholar wrote a sentence
citing castellanos2017. A Claude Code session then added two cited sentences,
one citing dumont2014, whose source supports it, and one citing nakamura2020,
whose source does not. Session files write the project folder as the token
{{PROJECT}}, which tests replace with a temporary folder.

Run from the repository root with python3 -m pytest examples/test_story.
Nothing here calls a model or the network. The references procedure runs
offline with recorded answers and the story's citation provenance record.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

STORY = Path(__file__).resolve().parent
ROOT = STORY.parents[1]
VERIFICATION = ROOT / "verification_procedures"
PROJECT = STORY / "project"
SESSIONS = STORY / "sessions" / "claude_code"
REFERENCES = STORY / "references"
STORY_SESSION = SESSIONS / "story_session.jsonl"
SESSION_FILES = ["story_session.jsonl", "excluded_session.jsonl"]
TOKEN = "{{PROJECT}}"

# A pandoc citation key after "[", ";", a space, or a line start.
CITE = re.compile(r"(?<![\w@])@([A-Za-z0-9_][A-Za-z0-9_:\-]*[A-Za-z0-9_])")


def records(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def parts(record):
    content = (record.get("message") or {}).get("content")
    return content if isinstance(content, list) else []


def tool_uses(recs):
    return [p for r in recs for p in parts(r) if p.get("type") == "tool_use"]


@pytest.mark.parametrize("name", SESSION_FILES)
def test_session_file_parses_as_json_lines(name):
    lines = (SESSIONS / name).read_text(encoding="utf-8").splitlines()
    assert lines and all(line.strip() for line in lines)
    recs = [json.loads(line) for line in lines]
    assert all(isinstance(r, dict) for r in recs)
    assert len({r["sessionId"] for r in recs}) == 1
    types = {r["type"] for r in recs}
    assert {"user", "assistant"} <= types <= {"user", "assistant", "system"}
    if name == "story_session.jsonl":
        assert "system" in types
    for r in recs:
        for field in ("sessionId", "cwd", "timestamp", "uuid", "parentUuid", "isSidechain"):
            assert field in r, (field, r["uuid"])
        assert r["cwd"].startswith(TOKEN)
        assert r["isSidechain"] is False
        if r["type"] != "system":
            assert r["message"]["role"] == r["type"]
    assert recs[0]["parentUuid"] is None
    for before, after in zip(recs, recs[1:]):
        assert after["parentUuid"] == before["uuid"]
    stamps = [r["timestamp"] for r in recs]
    assert stamps == sorted(stamps)
    for use in tool_uses(recs):
        path = use["input"].get("file_path")
        assert path is None or path.startswith(TOKEN + "/")


@pytest.mark.parametrize("name", SESSION_FILES)
def test_every_tool_use_has_a_matching_tool_result(name):
    used, answered = {}, {}
    for i, r in enumerate(records(SESSIONS / name)):
        for p in parts(r):
            if p.get("type") == "tool_use":
                assert r["type"] == "assistant"
                assert p["id"] not in used
                assert {"id", "name", "input"} <= set(p)
                used[p["id"]] = i
            elif p.get("type") == "tool_result":
                assert r["type"] == "user"
                assert p["tool_use_id"] not in answered
                answered[p["tool_use_id"]] = i
    assert used
    assert set(used) == set(answered)
    for tool_id, at in used.items():
        assert answered[tool_id] > at


def test_manuscript_has_exactly_three_citations():
    keys = CITE.findall((PROJECT / "manuscript.md").read_text(encoding="utf-8"))
    assert sorted(keys) == ["castellanos2017", "dumont2014", "nakamura2020"]
    before = CITE.findall((PROJECT / "author_draft.md").read_text(encoding="utf-8"))
    assert before == ["castellanos2017"]
    bib = (PROJECT / "refs.bib").read_text(encoding="utf-8")
    for key in keys:
        assert re.search(r"@\w+\{%s," % key, bib), key


def test_the_session_edits_turn_the_author_draft_into_the_manuscript():
    text = (PROJECT / "author_draft.md").read_text(encoding="utf-8")
    edits = [u["input"] for u in tool_uses(records(STORY_SESSION)) if u["name"] == "Edit"]
    assert len(edits) == 2
    for edit in edits:
        assert edit["file_path"] == TOKEN + "/manuscript.md"
        assert text.count(edit["old_string"]) == 1
        text = text.replace(edit["old_string"], edit["new_string"])
    assert text == (PROJECT / "manuscript.md").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def story_run(tmp_path_factory):
    """Run the references procedure on the story, offline, with recorded answers and the
    story's citation provenance record."""
    tmp = tmp_path_factory.mktemp("story_references")
    inputs = tmp / "inputs"
    inputs.mkdir()
    shutil.copyfile(str(PROJECT / "manuscript.md"), str(inputs / "draft.md"))
    shutil.copyfile(str(REFERENCES / "expected_citation_provenance.yaml"),
                    str(inputs / "citation_provenance.yaml"))
    for src in sorted(REFERENCES.iterdir()):
        if not src.name.startswith("expected_"):
            shutil.copyfile(str(src), str(inputs / src.name))
    run = tmp / "run"
    proc = subprocess.run(
        [sys.executable, "vg.py", "run", "graphs/citations.yaml", "--run", str(run),
         "--inputs", str(inputs), "--judge", "recorded:" + str(inputs / "recorded_judge.json")],
        cwd=str(VERIFICATION), capture_output=True, text=True,
        env=dict(os.environ, VG_OFFLINE="1"))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    files = run / "files"
    rows = json.loads((files / "rows_quoted.json").read_text(encoding="utf-8"))
    findings = json.loads((files / "findings.json").read_text(encoding="utf-8"))
    # The recorded answers cover every ask, so no passage goes unlocated.
    assert [f for f in findings if f["message"].startswith("not judged")] == []
    return {r["citekey"]: r for r in rows}, findings


def test_the_references_procedure_gives_nakamura2020_its_reason_quote_and_check(story_run):
    rows, findings = story_run
    row = rows["nakamura2020"]
    assert row["origin"] == "ai" and row["lookup"] == "found"
    assert "Nakamura 2020, recognition events" in row["reason"]
    assert [(q["text"], q["in_source"]) for q in row["quotes"]] == [
        ("Recognition events had no measurable effect on exit among long-serving volunteers.", "yes")]
    assert all(f["severity"] == "info" for f in findings)


def test_the_references_procedure_gives_dumont2014_its_quote_found_in_the_source(story_run):
    rows, _ = story_run
    row = rows["dumont2014"]
    assert row["origin"] == "ai" and row["quote_in_source"] == "yes"
    assert row["quotes"][0]["found_at"] == "p. 11"


def test_the_references_procedure_lists_the_scholars_citation_as_never_named(story_run):
    rows, findings = story_run
    row = rows["castellanos2017"]
    assert row["origin"] == "unknown" and row["lookup"] == "not_checked"
    assert any(f["check"] == "read_origin" and f["item"] == row["id"]
               and "never names" in f["message"] for f in findings)
