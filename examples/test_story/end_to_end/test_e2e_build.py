"""End to end on the test story, build stream (appendix A2.5 "Build").

Both story sessions are recorded. The second one edits a built file, which
only the build may write. The file-writes record is written out and handed to
the project, and the manuscript built. The project is then packed for the
build procedure, which has no judgment step. The scholar holds the item for
the AI's edit to the build and approves the rest, so the next build still
flags build. Once the held item is approved the build after that no longer
flags build, and an edit to the manuscript flags it again.

The build procedure reads the stand-in build tool's files, not ospipe's (gap
G1 in the track plan), so it also reports problems that come from that
mismatch. The test asserts nothing about them. They count only as items the
scholar decides.

Each layer is reached only through its command line and its files, as a
scholar would reach it, through the helpers in story_steps.py. Run from the
repository root with python3 -m pytest -q examples/test_story.
"""
import hashlib
import json
from pathlib import Path

import story_steps as steps

STORY = Path(__file__).resolve().parents[1]
TOUCH_SESSION = STORY / "sessions" / "claude_code" / "build_touch_session.jsonl"
EXPECTED_WRITES = STORY / "build" / "expected_session_writes.jsonl"
ALL_STREAMS = {"prose", "citations", "data", "build"}
TOUCHED = "builds/manuscript/v001.md"


def touch_session():
    """The second session's id and its one edit, read from the story's file."""
    session, edits = None, []
    for line in TOUCH_SESSION.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        session = session or record.get("sessionId")
        content = (record.get("message") or {}).get("content")
        for part in content if isinstance(content, list) else []:
            if part.get("type") == "tool_use" and part.get("name") == "Edit":
                edits.append(part["input"])
    assert len(edits) == 1
    return session, edits[0]


def test_build_end_to_end(tmp_path):
    project = steps.workspace(tmp_path)
    session_id, edit = touch_session()

    # Recorded. The audit layer stores both story sessions.
    steps.audit(tmp_path, "init")
    for name in ("story_session.jsonl", "build_touch_session.jsonl"):
        steps.audit(tmp_path, "capture", "--harness", "claude_code",
                    str(tmp_path / "sessions" / name))

    # Identified. The audit layer writes out the file-writes record, and the
    # handoff copies it into the project.
    out = tmp_path / "audit_out" / "session_writes.jsonl"
    out.parent.mkdir()
    steps.audit(tmp_path, "write-out", "session-writes", "--project", str(project),
                "--out", str(out))
    assert out.read_bytes() == EXPECTED_WRITES.read_bytes()
    steps.handoff("audit_to_project.py", "--record", "session_writes", "--from", str(out),
                  "--project", str(project))

    # With no results file for any stream, v001 flags all four.
    row = steps.build(project, "story v001")
    assert row["version"] == "v001"
    assert steps.flags(row) == ALL_STREAMS

    # The second session's edit lands on the built copy, so the folder
    # matches the record.
    assert edit["file_path"] == steps.TOKEN + "/" + TOUCHED
    touched = project / TOUCHED
    text = touched.read_text(encoding="utf-8")
    assert text.count(edit["old_string"]) == 1
    touched.write_text(text.replace(edit["old_string"], edit["new_string"]), encoding="utf-8")

    # Checked and reported. The build procedure runs on the inputs the
    # handoff packs.
    inputs = tmp_path / "inputs" / "build"
    steps.handoff("project_to_build.py", "--project", str(project), "--to", str(inputs))
    run_dir = tmp_path / "runs" / "story_build"
    steps.run("graphs/build.yaml", run_dir, inputs)
    records = [json.loads(p.read_text(encoding="utf-8"))
               for p in sorted((run_dir / "records").glob("*.json"))]
    assert records
    assert [r["node"] for r in records if r["checks"]["contract"] != "pass"] == []
    assert records[-1]["node"] == "report"

    results = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    assert results["stream"] == "build"
    manuscript_sum = "sha256:" + hashlib.sha256((project / "manuscript.md").read_bytes()).hexdigest()
    assert manuscript_sum in results["inputs"].values()

    by_id = {item["id"]: item for item in results["items"]}
    assert by_id["manuscript"]["kind"] == "deliverable"
    assert by_id["slides"]["kind"] == "deliverable"
    touch = [f for f in by_id[TOUCHED]["findings"]
             if f["check"] == "check_ai_touch" and f["severity"] == "blocking"]
    assert len(touch) == 1

    # The AI's write to the build names its session by its public id, in its
    # evidence, in its item, in its results file item, and in a line of the
    # report, and the harness's own id for the session reaches none of them.
    # The deliverables name no session.
    ref = steps.public_id(session_id)
    assert touch[0]["evidence"] == "session %s, ai via edited" % ref
    assert session_id not in (run_dir / "results.json").read_text(encoding="utf-8")
    assert session_id not in steps.report(run_dir)
    fields = {item["id"]: item for item in steps.fields(run_dir)}
    assert fields[TOUCHED]["sessions"] == [ref]
    assert [i for i, item in fields.items() if "sessions" in item] == [TOUCHED]
    assert [(item["id"], item["sessions"]) for item in steps.items(run_dir)
            if "sessions" in item] == [(TOUCHED, [ref])]
    shown = [line for line in steps.report(run_dir).splitlines() if "came from session" in line]
    assert shown == ["- The AI write to %s came from session %s." % (TOUCHED, ref)]
    assert all(item["needs_decision"] for item in results["items"])

    # The results reach the project. The scholar holds the AI's edit to the
    # build and approves every other item, so v002 still flags build.
    for item in results["items"]:
        steps.decide(run_dir, item["id"], approve=item["id"] != TOUCHED)
    decided = (run_dir / "report_decided.md").read_text(encoding="utf-8")
    assert "**%d approved, 1 held, 0 undecided.**" % (len(results["items"]) - 1) in decided
    steps.handoff("results_to_pipeline.py", "--run", str(run_dir), "--stream", "build",
                  "--project", str(project))
    row = steps.build(project, "story v002")
    assert row["version"] == "v002"
    assert "build" in steps.flags(row)
    assert "build=" + run_dir.name in row["runs"]

    # Approved. The scholar approves the held item, and the results are
    # copied again.
    steps.decide(run_dir, TOUCHED, approve=True)
    decided = (run_dir / "report_decided.md").read_text(encoding="utf-8")
    assert "**%d approved, 0 held, 0 undecided.**" % len(results["items"]) in decided
    steps.handoff("results_to_pipeline.py", "--run", str(run_dir), "--stream", "build",
                  "--project", str(project))
    copied = project / "verification" / "build.json"
    assert copied.read_bytes() == (run_dir / "results.json").read_bytes()

    # Incorporated. v003 no longer flags build and names the run.
    row = steps.build(project, "story v003")
    assert row["version"] == "v003"
    assert steps.flags(row) == ALL_STREAMS - {"build"}
    assert "build=" + run_dir.name in row["runs"]

    # An edit to the manuscript makes the results stale, so v004 flags build
    # again.
    manuscript = project / "manuscript.md"
    text = manuscript.read_text(encoding="utf-8")
    assert text.count("This is a test manuscript.") == 1
    manuscript.write_text(text.replace("This is a test manuscript.",
                                       "This is a short test manuscript."), encoding="utf-8")
    row = steps.build(project, "story v004")
    assert row["version"] == "v004"
    assert steps.flags(row) == ALL_STREAMS
