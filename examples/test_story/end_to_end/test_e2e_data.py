"""End to end on the test story, data stream (appendix A2.5 "Data and analysis
code", A2.3 "Verification status").

The story's session is recorded, and the audit layer writes out the record of
the AI's file edits. Its edits are to the manuscript and a notes file, and none
is to the pipeline's script or parameters. The build already reads
verification/data.json against the numbers file, so the stream has no
pipeline step. The manuscript is built, and the project's top-level files and
the record are handed to the data procedure, which reruns the analysis and
checks every number against the rerun. No number comes from code an AI wrote
or changed, so none waits for the scholar, and the next build no longer flags
data (decision 21). An edit to the manuscript leaves data unflagged, since the
data stream covers the numbers file. A change to the numbers file that keeps
every value flags data again, since any change to that file asks for a new
check.

The pipeline's one step declares its phase, analysis, and its script marks its
steps. The phase handoff gives the three data phase reports the pipeline, its
script, and the latest build's text, and each report runs with recorded
answers standing in for its finding step (Track V, step V4).

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
PHASE_ANSWERS = STORY / "data" / "recorded_phases.json"
STEP_TITLES = ["Parameters", "Shares", "Summary", "Table", "Outputs"]

ALL_STREAMS = {"prose", "citations", "data", "build"}
NUMBER_KEYS = ["definition.distinct", "definition.top_pct", "definition.top_word", "model",
               "n_per_condition", "none.distinct", "none.top_pct", "none.top_word", "question",
               "temperature"]
TOP_PCT_LINE = ('  none.top_pct: {value: "30.0", from: next_word_results.json, '
                'field: conditions.none.top_pct}')


def checksum(path):
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def test_data_end_to_end(tmp_path):
    project = steps.workspace(tmp_path)

    # Recorded. The audit layer stores the story session and writes out the
    # record of the AI's file edits, which names the two edits to the
    # manuscript and the notes file the session wrote, and no script.
    steps.audit(tmp_path, "init")
    steps.audit(tmp_path, "capture", "--harness", "claude_code",
                str(tmp_path / "sessions" / "story_session.jsonl"))
    record = tmp_path / "audit_out" / "file_edits.yaml"
    record.parent.mkdir()
    steps.audit(tmp_path, "write-out", "file-edits", "--project", str(project), "--out", str(record))
    entries = yaml.safe_load(record.read_text(encoding="utf-8"))
    assert [(e["id"], e["path"], e["kind"]) for e in entries] == [
        ("e01", "manuscript.md", "edit"), ("e02", "manuscript.md", "edit"),
        ("e03", "source_notes.md", "write")]

    # With no results file for any stream, v001 flags all four.
    row = steps.build(project, "story v001")
    assert row["version"] == "v001"
    assert steps.flags(row) == ALL_STREAMS

    # Checked and reported. The handoff copies the project's top-level files
    # and the record, and the data procedure runs on them with no model asked.
    inputs = tmp_path / "inputs" / "data"
    steps.handoff("project_to_data.py", "--project", str(project), "--to", str(inputs),
                  "--file-edits", str(record))
    assert not [p for p in inputs.iterdir() if p.is_dir()]
    assert (inputs / "file_edits.yaml").read_bytes() == record.read_bytes()
    run_dir = tmp_path / "runs" / "story_data"
    steps.run("graphs/data.yaml", run_dir, inputs)
    records = [json.loads(p.read_text(encoding="utf-8"))
               for p in sorted((run_dir / "records").glob("*.json"))]
    assert records
    assert [r["node"] for r in records if r["checks"]["contract"] != "pass"] == []

    findings = json.loads((run_dir / "files" / "findings.json").read_text(encoding="utf-8"))
    assert [f for f in findings if f["severity"] in ("blocking", "warning")] == []

    results = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    assert results["stream"] == "data"
    assert checksum(project / "numbers.yml") in results["inputs"].values()
    assert checksum(record) in results["inputs"].values()
    assert [item["id"] for item in results["items"]] == NUMBER_KEYS
    assert all(item["kind"] == "number" and item["findings"] == [] and not item["needs_decision"]
               for item in results["items"])
    assert ("The record of the AI's file edits was given, and no AI contributions to the "
            "scripts or the parameters were found in it.") in steps.report(run_dir)

    # The data phase reports. The handoff copies the pipeline, its script, and
    # the text of the latest build, v001, and each report runs on them.
    phases = tmp_path / "inputs" / "data_phases"
    steps.handoff("project_to_data_phases.py", "--project", str(project), "--to", str(phases))
    assert sorted(p.name for p in phases.iterdir()) == ["final_text.md", "params_io.py",
                                                       "pipeline.yaml", "s1_results.py"]
    built = project / "builds" / "manuscript" / "v001.md"
    assert (phases / "final_text.md").read_bytes() == built.read_bytes()
    script = (project / "s1_results.py").read_text(encoding="utf-8").splitlines()
    reports = {}
    for phase in ("collection", "cleaning", "analysis"):
        phase_run = tmp_path / "runs" / ("story_data_" + phase)
        steps.run("graphs/data_%s.yaml" % phase, phase_run, phases, judge=PHASE_ANSWERS)
        reports[phase] = steps.report(phase_run)
        phase_records = [json.loads(p.read_text(encoding="utf-8"))
                         for p in sorted((phase_run / "records").glob("*.json"))]
        assert [r["node"] for r in phase_records if r["checks"]["contract"] != "pass"] == []

    # The analysis report lists the script's five marked steps, then each with
    # its exact code, file, and lines, and the one description the finding
    # step gave, whose quote and places the program confirmed.
    analysis = reports["analysis"]
    outline = analysis.split("## Outline", 1)[1].split("## Code", 1)[0]
    assert "- `results`, `s1_results.py`" in outline
    assert [line.strip()[2:] for line in outline.splitlines() if line.startswith("  - ")] == STEP_TITLES
    code = analysis.split("## Code", 1)[1].split("## Descriptions", 1)[0]
    marks = [n for n, line in enumerate(script, 1) if line.startswith("# step: ")]
    assert [script[n - 1][len("# step: "):] for n in marks] == STEP_TITLES
    table_start = marks[STEP_TITLES.index("Table")]
    table_end = marks[STEP_TITLES.index("Outputs")] - 3
    assert "### Table\n\n`s1_results.py` lines %d-%d" % (table_start, table_end) in code
    assert "\n".join(script[table_start - 1:table_end]) in code
    assert ("| d01 | The table lists the three most common words in each condition. |"
            in analysis)
    assert analysis.count("| yes | confirmed |") == 1
    assert "- Warnings: 0" in analysis

    # The pipeline declares no collection or cleaning step, and each of those
    # reports says so. The collection report lists the description of the
    # sampling, which no script carries out, as missing.
    for phase in ("collection", "cleaning"):
        assert ("No step of the pipeline declares the phase %s" % phase) in reports[phase]
    assert ("| d01 | It answered 60 times in each of three conditions, at temperature 1.0. "
            "| missing | yes | missing |") in reports["collection"]

    # The results reach the project. No number needs the scholar's decision,
    # so there is nothing to approve.
    steps.handoff("results_to_pipeline.py", "--run", str(run_dir), "--stream", "data",
                  "--project", str(project))
    copied = project / "verification" / "data.json"
    assert copied.read_bytes() == (run_dir / "results.json").read_bytes()

    # Incorporated. v002 no longer flags data and names the run.
    row = steps.build(project, "story v002")
    assert row["version"] == "v002"
    assert steps.flags(row) == ALL_STREAMS - {"data"}
    assert "data=" + run_dir.name in row["runs"]

    # An edit to the manuscript leaves the numbers file as it was, so v003
    # still does not flag data.
    manuscript = project / "manuscript.md"
    text = manuscript.read_text(encoding="utf-8")
    assert text.count("This is a test manuscript.") == 1
    manuscript.write_text(text.replace("This is a test manuscript.",
                                       "This is a short test manuscript."), encoding="utf-8")
    row = steps.build(project, "story v003")
    assert row["version"] == "v003"
    assert steps.flags(row) == ALL_STREAMS - {"data"}

    # The same number written differently changes the numbers file, so v004
    # flags data again.
    numbers = project / "numbers.yml"
    text = numbers.read_text(encoding="utf-8")
    assert text.count(TOP_PCT_LINE) == 1
    numbers.write_text(text.replace(TOP_PCT_LINE, TOP_PCT_LINE.replace('"30.0"', '"30.00"')),
                       encoding="utf-8")
    row = steps.build(project, "story v004")
    assert row["version"] == "v004"
    assert steps.flags(row) == ALL_STREAMS
