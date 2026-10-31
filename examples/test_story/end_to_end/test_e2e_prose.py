"""End to end on the test story, prose stream (appendix A2.5 "Prose", A2.3
"Verification status").

The story's session is recorded, and the audit layer writes out the AI's
stated reason for each sentence it added to the manuscript. The record is
handed to the project and the manuscript built. The author's draft, the
manuscript, the record, and the pin the scholar keeps are handed to the prose
procedure, which lines up the changes between the two drafts and shows each of
the AI's changes with the reason the record gives, with no model asked (prose
0.3, Track V). The scholar approves both of the AI's additions, so the next
build no longer flags prose. An edit to the manuscript flags prose again.

The build already reads verification/prose.json against the source text, so
prose has no pipeline step. Each layer is reached only through its command
line and its files, as a scholar would reach it, through the helpers in
story_steps.py. Run from the repository root with python3 -m pytest -q
examples/test_story.
"""
import hashlib
import json
from pathlib import Path

import yaml

import story_steps as steps

STORY = Path(__file__).resolve().parents[1]
PROSE = STORY / "prose"
ALL_STREAMS = {"prose", "citations", "data", "build"}


def test_prose_end_to_end(tmp_path):
    project = steps.workspace(tmp_path)

    # Recorded. The audit layer stores the story session.
    steps.audit(tmp_path, "init")
    steps.audit(tmp_path, "capture", "--harness", "claude_code",
                str(tmp_path / "sessions" / "story_session.jsonl"))

    # Identified. The audit layer writes out the AI's stated reasons for its
    # edits to the manuscript, and the handoff copies them into the project.
    out = tmp_path / "audit_out" / "rationales.yaml"
    out.parent.mkdir()
    steps.audit(tmp_path, "write-out", "rationales", "--project", str(project),
                "--source", "manuscript.md", "--out", str(out))
    expected = PROSE / "expected_rationales.yaml"
    assert yaml.safe_load(out.read_text(encoding="utf-8")) == yaml.safe_load(
        expected.read_text(encoding="utf-8"))
    steps.handoff("audit_to_project.py", "--record", "rationales", "--from", str(out),
                  "--project", str(project))

    # With no results file for any stream, v001 flags all four.
    row = steps.build(project, "story v001")
    assert row["version"] == "v001"
    assert steps.flags(row) == ALL_STREAMS

    # Checked and reported. The prose procedure runs on the inputs the handoff
    # gathers, and no step asks a model.
    inputs = tmp_path / "inputs" / "prose"
    steps.handoff("project_to_prose.py", "--project", str(project), "--prose", str(PROSE),
                  "--to", str(inputs))
    assert sorted(p.name for p in inputs.iterdir()) == [
        "baseline.md", "rationales.yaml", "revised.md", "versions.yaml"]
    run_dir = tmp_path / "runs" / "story_prose"
    steps.run("graphs/prose.yaml", run_dir, inputs)
    records = [json.loads(p.read_text(encoding="utf-8"))
               for p in sorted((run_dir / "records").glob("*.json"))]
    assert records
    assert [r["node"] for r in records if r["checks"]["contract"] != "pass"] == []

    results = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    assert results["stream"] == "prose"
    manuscript_sum = "sha256:" + hashlib.sha256((project / "manuscript.md").read_bytes()).hexdigest()
    assert manuscript_sum in results["inputs"].values()

    # The items are the AI's two added sentences, each handed to citations.
    items = results["items"]
    assert [(item["id"], item["kind"]) for item in items] == [("c01", "change"), ("c02", "change")]
    for item in items:
        assert item["needs_decision"] is True
        assert [(f["check"], f["severity"]) for f in item["findings"]] == [
            ("content_handoff", "warning")], item["id"]
        assert "citations" in item["findings"][0]["message"]

    # Each change names the session whose stated reason it carries by its
    # public id, in its item, in its results file item, and in a line of the
    # report.
    ref = steps.public_id(steps.session_id("story_session.jsonl"))
    assert [(item["id"], item["sessions"]) for item in steps.fields(run_dir)] == [
        ("c01", [ref]), ("c02", [ref])]
    assert [(item["id"], item["sessions"]) for item in steps.items(run_dir)] == [
        ("c01", [ref]), ("c02", [ref])]
    shown = [line for line in steps.report(run_dir).splitlines() if "came from session" in line]
    assert shown == ["- Change c01 came from session %s." % ref,
                     "- Change c02 came from session %s." % ref]

    # The report shows each of the AI's edits with the sentence it added and the
    # reason the session gave for it, word for word.
    report = steps.report(run_dir)
    for item, entry in zip(items, yaml.safe_load(expected.read_text(encoding="utf-8"))):
        block = report.split("### %s (insert)" % item["id"], 1)[1].split("###", 1)[0]
        assert "- **Before:** (none)" in block
        assert "- **After:** %s" % entry["anchor"] in block
        assert "- **Stated reason:** %s" % entry["rationale"] in block

    # The results reach the project, then the scholar approves both changes
    # and the results are copied again.
    steps.handoff("results_to_pipeline.py", "--run", str(run_dir), "--stream", "prose",
                  "--project", str(project))
    for item in items:
        steps.decide(run_dir, item["id"], approve=True)
    decided = (run_dir / "report_decided.md").read_text(encoding="utf-8")
    assert "**2 approved, 0 held, 0 undecided.**" in decided
    steps.handoff("results_to_pipeline.py", "--run", str(run_dir), "--stream", "prose",
                  "--project", str(project))
    copied = project / "verification" / "prose.json"
    assert copied.read_bytes() == (run_dir / "results.json").read_bytes()

    # Incorporated. v002 no longer flags prose and names the run.
    row = steps.build(project, "story v002")
    assert row["version"] == "v002"
    assert steps.flags(row) == ALL_STREAMS - {"prose"}
    assert "prose=" + run_dir.name in row["runs"]

    # An edit to the manuscript makes the results stale, so v003 flags prose
    # again.
    manuscript = project / "manuscript.md"
    text = manuscript.read_text(encoding="utf-8")
    assert text.count("This is a test manuscript.") == 1
    manuscript.write_text(text.replace("This is a test manuscript.",
                                       "This is a short test manuscript."), encoding="utf-8")
    row = steps.build(project, "story v003")
    assert row["version"] == "v003"
    assert steps.flags(row) == ALL_STREAMS
