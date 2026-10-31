"""End to end on the test story, all four streams (proposal Overview para 1,
appendix A2.3 "Verification status", A2.5 "Verification reports" para 3,
Figures A3 and A6).

Both story sessions are recorded, and the audit layer writes out its three
records, the citation log, the file writes, and the AI's stated reasons. Each
is handed to the project. The project is then handed to each of the four
procedures, which run offline on recorded answers, and the four results reach
the project. A build carries `unverified:` with exactly the streams that still
have an item held or undecided. While the scholar holds one citation, the
build is marked `unverified: citations` only, and once every item is approved
the build is marked `verified` and its runs cell names all four runs. An edit
to one sentence of the manuscript flags every stream that covers the source
text, and a change to the numbers file flags data as well.

Each layer is reached only through its command line and its files, as a
scholar would reach it, through the helpers in story_steps.py. Run from the
repository root with python3 -m pytest -q examples/test_story.
"""
import json
from pathlib import Path

import yaml

import story_steps as steps

STORY = Path(__file__).resolve().parents[1]
REFERENCES = STORY / "references"
PROSE = STORY / "prose"
TOUCH_SESSION = STORY / "sessions" / "claude_code" / "build_touch_session.jsonl"
ALL_STREAMS = {"prose", "citations", "data", "build"}
HELD = "r03"
TOP_PCT_LINE = ('  none.top_pct: {value: "30.0", from: next_word_results.json, '
                'field: conditions.none.top_pct}')


def touch_edit():
    """The second session's one edit, read from the story's file."""
    edits = []
    for line in TOUCH_SESSION.read_text(encoding="utf-8").splitlines():
        content = (json.loads(line).get("message") or {}).get("content")
        for part in content if isinstance(content, list) else []:
            if part.get("type") == "tool_use" and part.get("name") == "Edit":
                edits.append(part["input"])
    assert len(edits) == 1
    return edits[0]


def write_out(tmp_path, project, kind, name, *extra):
    """Write out one audit record and hand it to the project."""
    out = tmp_path / "audit_out" / name
    out.parent.mkdir(exist_ok=True)
    steps.audit(tmp_path, "write-out", kind, "--project", str(project), *extra, "--out", str(out))
    steps.handoff("audit_to_project.py", "--record", kind.replace("-", "_"), "--from", str(out),
                  "--project", str(project))
    return out


def copy_results(run_dirs, project):
    for stream, run_dir in run_dirs.items():
        steps.handoff("results_to_pipeline.py", "--run", str(run_dir), "--stream", stream,
                      "--project", str(project))


def test_all_four_streams_end_to_end(tmp_path):
    project = steps.workspace(tmp_path)

    # Recorded. The audit layer stores both story sessions.
    steps.audit(tmp_path, "init")
    for name in ("story_session.jsonl", "build_touch_session.jsonl"):
        steps.audit(tmp_path, "capture", "--harness", "claude_code",
                    str(tmp_path / "sessions" / name))

    # Identified. The three records are written out and handed to the project.
    log = write_out(tmp_path, project, "citation-log", "citation_log.yaml")
    writes = write_out(tmp_path, project, "session-writes", "session_writes.jsonl")
    reasons = write_out(tmp_path, project, "rationales", "rationales.yaml",
                        "--source", "manuscript.md")
    assert yaml.safe_load(log.read_text(encoding="utf-8")) == yaml.safe_load(
        (REFERENCES / "expected_citation_log.yaml").read_text(encoding="utf-8"))
    assert writes.read_bytes() == (STORY / "build" / "expected_session_writes.jsonl").read_bytes()
    assert yaml.safe_load(reasons.read_text(encoding="utf-8")) == yaml.safe_load(
        (PROSE / "expected_rationales.yaml").read_text(encoding="utf-8"))

    # With no results file for any stream, v001 flags all four.
    row = steps.build(project, "story v001")
    assert row["version"] == "v001"
    assert steps.flags(row) == ALL_STREAMS

    # The second session's edit lands on the built copy, so the folder
    # matches the file-writes record.
    edit = touch_edit()
    touched = project / edit["file_path"].replace(steps.TOKEN + "/", "", 1)
    text = touched.read_text(encoding="utf-8")
    assert text.count(edit["old_string"]) == 1
    touched.write_text(text.replace(edit["old_string"], edit["new_string"]), encoding="utf-8")

    # Checked, judged, and reported. Each procedure runs on the inputs its
    # handoff gathers, with recorded answers where it has a judgment step.
    inputs = tmp_path / "inputs"
    runs = tmp_path / "runs"
    run_dirs = {stream: runs / ("story_" + stream) for stream in
                ("prose", "citations", "data", "build")}
    steps.handoff("project_to_prose.py", "--project", str(project), "--prose", str(PROSE),
                  "--to", str(inputs / "prose"))
    steps.run("graphs/prose.yaml", run_dirs["prose"], inputs / "prose")
    steps.handoff("project_to_references.py", "--project", str(project),
                  "--references", str(REFERENCES),
                  "--provenance", str(steps.provenance(tmp_path, project)),
                  "--to", str(inputs / "citations"))
    steps.run("graphs/citations.yaml", run_dirs["citations"], inputs / "citations",
              judge=REFERENCES / "recorded_judge.json")
    steps.handoff("project_to_data.py", "--project", str(project), "--to", str(inputs / "data"))
    steps.run("graphs/data.yaml", run_dirs["data"], inputs / "data")
    steps.handoff("project_to_build.py", "--project", str(project), "--to", str(inputs / "build"))
    steps.run("graphs/build.yaml", run_dirs["build"], inputs / "build")
    for stream, run_dir in run_dirs.items():
        results = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
        assert results["stream"] == stream
        assert any(item["needs_decision"] for item in results["items"]), stream

    # The four results reach the project, but no item is decided, so v002
    # still flags all four.
    copy_results(run_dirs, project)
    row = steps.build(project, "story v002")
    assert row["version"] == "v002"
    assert steps.flags(row) == ALL_STREAMS

    # The scholar holds one citation and approves every other item that needs
    # a decision in all four streams, so v003 carries citations only.
    citation_items = {item["id"]: item for item in steps.items(run_dirs["citations"])}
    assert citation_items[HELD]["citekey"] == "nakamura2020"
    for stream, run_dir in run_dirs.items():
        for item in steps.items(run_dir):
            if item["needs_decision"]:
                steps.decide(run_dir, item["id"], approve=item["id"] != HELD)
    copy_results(run_dirs, project)
    row = steps.build(project, "story v003")
    assert row["version"] == "v003"
    assert steps.flags(row) == {"citations"}
    assert row["verification"] == "unverified: citations"

    # Approved. Once the held citation is approved, v004 is verified and its
    # runs cell names all four runs.
    steps.decide(run_dirs["citations"], HELD, approve=True)
    copy_results(run_dirs, project)
    row = steps.build(project, "story v004")
    assert row["version"] == "v004"
    assert steps.flags(row) == set()
    assert row["verification"] == "verified"
    for stream, run_dir in run_dirs.items():
        assert "%s=%s" % (stream, run_dir.name) in row["runs"]

    # One changed sentence of the manuscript flags every stream that covers
    # the source text, and leaves data verified.
    manuscript = project / "manuscript.md"
    text = manuscript.read_text(encoding="utf-8")
    assert text.count("This is a test manuscript.") == 1
    manuscript.write_text(text.replace("This is a test manuscript.",
                                       "This is a short test manuscript."), encoding="utf-8")
    row = steps.build(project, "story v005")
    assert row["version"] == "v005"
    assert steps.flags(row) == {"prose", "citations", "build"}

    # One changed value in the numbers file flags data as well.
    numbers = project / "numbers.yml"
    text = numbers.read_text(encoding="utf-8")
    assert text.count(TOP_PCT_LINE) == 1
    numbers.write_text(text.replace(TOP_PCT_LINE, TOP_PCT_LINE.replace('"30.0"', '"31.0"')),
                       encoding="utf-8")
    row = steps.build(project, "story v006")
    assert row["version"] == "v006"
    assert steps.flags(row) == ALL_STREAMS
