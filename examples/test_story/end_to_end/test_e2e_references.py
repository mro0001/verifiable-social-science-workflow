"""End to end on the test story, references stream (Figure A6).

The story's session is recorded, its citation log written out and handed to
the project, and the manuscript built. The citation provenance record is
written out, and the handoff gathers it with the final build's filled-in text.
The references procedure then lays out the citations offline with recorded
answers, giving the AI-added citation its reason, quote, and quote check, the
scholar approves each item,
and the results reach the project, so the next build no longer flags
citations. An edit to the manuscript flags citations again.

Each layer is reached only through its command line and its files, as a
scholar would reach it, through the helpers in story_steps.py. Run from the
repository root with python3 -m pytest -q examples/test_story.
"""
import hashlib
import json
from pathlib import Path

import yaml

import story_steps as steps

STORY = Path(__file__).resolve().parents[1]
REFERENCES = STORY / "references"
ALL_STREAMS = {"prose", "citations", "data", "build"}


def test_references_end_to_end(tmp_path):
    project = steps.workspace(tmp_path)

    # Recorded. The audit layer stores the story session.
    steps.audit(tmp_path, "init")
    steps.audit(tmp_path, "capture", "--harness", "claude_code",
                str(tmp_path / "sessions" / "story_session.jsonl"))

    # Identified. The audit layer writes out the citation log, and the
    # handoff copies it into the project.
    out = tmp_path / "audit_out" / "citation_log.yaml"
    out.parent.mkdir()
    steps.audit(tmp_path, "write-out", "citation-log", "--project", str(project), "--out", str(out))
    expected = REFERENCES / "expected_citation_log.yaml"
    assert yaml.safe_load(out.read_text(encoding="utf-8")) == yaml.safe_load(
        expected.read_text(encoding="utf-8"))
    steps.handoff("audit_to_project.py", "--record", "citation_log", "--from", str(out),
                  "--project", str(project))

    # With no results file for any stream, v001 flags all four.
    row = steps.build(project, "story v001")
    assert row["version"] == "v001"
    assert steps.flags(row) == ALL_STREAMS

    # Checked and reported. The audit layer writes out the citation provenance
    # record, which names the two citations the story session added, and the
    # handoff gathers it with the final build's filled-in text, v001.md, as
    # the draft the procedure reads.
    record = steps.provenance(tmp_path, project)
    assert yaml.safe_load(record.read_text(encoding="utf-8")) == yaml.safe_load(
        (REFERENCES / "expected_citation_provenance.yaml").read_text(encoding="utf-8"))
    inputs = tmp_path / "inputs" / "citations"
    steps.handoff("project_to_references.py", "--project", str(project),
                  "--references", str(REFERENCES), "--provenance", str(record),
                  "--to", str(inputs))
    assert (inputs / "draft.md").read_bytes() == (project / "builds" / "manuscript"
                                                  / "v001.md").read_bytes()
    assert (inputs / "citation_provenance.yaml").read_bytes() == record.read_bytes()
    run_dir = tmp_path / "runs" / "story_citations"
    steps.run("graphs/citations.yaml", run_dir, inputs, judge=REFERENCES / "recorded_judge.json")
    manuscript_sum = "sha256:" + hashlib.sha256((project / "manuscript.md").read_bytes()).hexdigest()
    results = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    assert results["stream"] == "citations"
    assert manuscript_sum in results["inputs"].values()

    # Each AI-added citation names the session that added it by its public
    # id, in its item, in its results file item, and in its block of the
    # report. The scholar's citation names none.
    ref = steps.public_id(steps.session_id("story_session.jsonl"))
    by_key = {item["citekey"]: item for item in steps.fields(run_dir)}
    assert by_key["dumont2014"]["sessions"] == [ref]
    assert by_key["nakamura2020"]["sessions"] == [ref]
    assert "sessions" not in by_key["castellanos2017"]
    in_results = {item["citekey"]: item for item in steps.items(run_dir)}
    assert in_results["dumont2014"]["sessions"] == [ref]
    assert in_results["nakamura2020"]["sessions"] == [ref]
    assert "sessions" not in in_results["castellanos2017"]
    blocks = steps.report(run_dir).split("\n### ")[1:]
    for key, item in by_key.items():
        block = next(b for b in blocks if b.startswith(item["id"] + ":"))
        lines = [line for line in block.splitlines() if line.startswith("- **Session:**")]
        assert lines == (["- **Session:** " + ref] if key != "castellanos2017" else []), key

    # The story's AI-added citation nakamura2020 comes with the reason the AI
    # gave in its notes file, the quote the passage step located in the
    # source, and the program's check that the quote is in the source, in its
    # results file item and in its block of the report.
    added = in_results["nakamura2020"]
    assert added["origin"] == "ai" and added["lookup"] == "found"
    assert "Nakamura 2020, recognition events" in added["reason"]
    assert "source_notes.md" in added["reason_source"]
    quote = "Recognition events had no measurable effect on exit among long-serving volunteers."
    assert [(q["text"], q["in_source"]) for q in added["quotes"]] == [(quote, "yes")]
    assert added["quote_in_source"] == "yes"
    block = next(b for b in blocks if b.startswith(added["id"] + ":"))
    assert any(line.startswith("- **Reason:**") and "Nakamura 2020, recognition events" in line
               for line in block.splitlines())
    assert any(line.startswith("- **Quote:**") and quote in line for line in block.splitlines())
    assert any(line.startswith("- **Quote check:**") and "found in source_nakamura2020.txt" in line
               for line in block.splitlines())

    # The results reach the project, but no item is decided, so v002 still
    # flags citations.
    steps.handoff("results_to_pipeline.py", "--run", str(run_dir), "--stream", "citations",
                  "--project", str(project))
    row = steps.build(project, "story v002")
    assert row["version"] == "v002"
    assert "citations" in steps.flags(row)

    # Approved. The scholar approves each item that needs a decision, and the
    # results are copied again.
    needing = [item["id"] for item in steps.items(run_dir) if item["needs_decision"]]
    assert needing == ["r01", "r02", "r03"]
    for item in needing:
        steps.decide(run_dir, item, approve=True)
    decided = (run_dir / "report_decided.md").read_text(encoding="utf-8")
    assert "**3 approved, 0 held, 0 undecided.**" in decided
    steps.handoff("results_to_pipeline.py", "--run", str(run_dir), "--stream", "citations",
                  "--project", str(project))
    copied = project / "verification" / "citations.json"
    assert copied.read_bytes() == (run_dir / "results.json").read_bytes()

    # Incorporated. v003 no longer flags citations and names the run.
    row = steps.build(project, "story v003")
    assert row["version"] == "v003"
    assert steps.flags(row) == ALL_STREAMS - {"citations"}
    assert "citations=" + run_dir.name in row["runs"]

    # An edit to the manuscript makes the results stale, so v004 flags
    # citations again.
    manuscript = project / "manuscript.md"
    text = manuscript.read_text(encoding="utf-8")
    assert text.count("This is a test manuscript.") == 1
    manuscript.write_text(text.replace("This is a test manuscript.",
                                       "This is a short test manuscript."), encoding="utf-8")
    row = steps.build(project, "story v004")
    assert row["version"] == "v004"
    assert steps.flags(row) == ALL_STREAMS
