"""End to end on the test story, the session index (Track P, step P3).

The story's sessions are recorded, its citation log is written out and handed
to the project, and the references procedure checks the citations offline
with recorded answers. The scholar approves one AI-added citation. The audit
layer then writes out the project's session index with the run's results
file, and the index names each AI-added citation under the story session with
the reference id the report shows, and the session that made no contribution
with zero.

A second test (step P4) runs the references, prose, and build procedures,
writes the index with their three results files, and hands it into the
project's sessions/ folder. The reference ids there match the items whose
report names a session, each under that session.

Each layer is reached only through its command line and its files, through
the helpers in story_steps.py. Run from the repository root with python3 -m
pytest -q examples/test_story.
"""
import csv
import json
import re
from pathlib import Path

import story_steps as steps

STORY = Path(__file__).resolve().parents[1]
REFERENCES = STORY / "references"
PROSE = STORY / "prose"
TOUCH_SESSION = STORY / "sessions" / "claude_code" / "build_touch_session.jsonl"
TOUCHED = "builds/manuscript/v001.md"


def test_the_session_index_names_the_reports_ai_contributions_by_session(tmp_path):
    project = steps.workspace(tmp_path)
    steps.audit(tmp_path, "init")
    for name in ("story_session.jsonl", "build_touch_session.jsonl"):
        steps.audit(tmp_path, "capture", "--harness", "claude_code", str(tmp_path / "sessions" / name))

    out = tmp_path / "audit_out" / "citation_log.yaml"
    out.parent.mkdir()
    steps.audit(tmp_path, "write-out", "citation-log", "--project", str(project), "--out", str(out))
    steps.handoff("audit_to_project.py", "--record", "citation_log", "--from", str(out),
                  "--project", str(project))
    # The references handoff reads the final build's filled-in text.
    steps.build(project, "story v001")
    inputs = tmp_path / "inputs" / "citations"
    steps.handoff("project_to_references.py", "--project", str(project),
                  "--references", str(REFERENCES),
                  "--provenance", str(steps.provenance(tmp_path, project)), "--to", str(inputs))
    run_dir = tmp_path / "runs" / "story_citations"
    steps.run("graphs/citations.yaml", run_dir, inputs, judge=REFERENCES / "recorded_judge.json")

    # The report's blocks that name a session, by item id.
    story_ref = steps.public_id(steps.session_id("story_session.jsonl"))
    touch_ref = steps.public_id(steps.session_id("build_touch_session.jsonl"))
    shown = {}
    for block in steps.report(run_dir).split("\n### ")[1:]:
        item = block.split(":", 1)[0]
        for line in block.splitlines():
            if line.startswith("- **Session:** "):
                shown[item] = line[len("- **Session:** "):]
    assert set(shown.values()) == {story_ref}
    first = sorted(shown)[0]
    steps.decide(run_dir, first, approve=True)

    index = tmp_path / "index"
    steps.audit(tmp_path, "write-out", "session-index", "--project", str(project),
                "--out", str(index), "--results", str(run_dir / "results.json"))

    with open(str(index / "sessions.csv"), encoding="utf-8", newline="") as f:
        rows = {row["public_id"]: row for row in csv.DictReader(f)}
    assert sorted(rows) == sorted([story_ref, touch_ref])
    expected = []
    for item in sorted(shown):
        decision = "approved" if item == first else "not yet decided"
        expected.append("citations/%s (%s, run %s)" % (item, decision, run_dir.name))
    assert rows[story_ref]["references"] == "; ".join(expected)
    assert rows[story_ref]["contributions"] == str(len(shown))
    assert rows[touch_ref]["contributions"] == "0"

    # The checkbox in index.html keeps only the story session.
    page = (index / "index.html").read_text(encoding="utf-8")
    data = json.loads(re.search(
        r'<script id="session-data" type="application/json">(.*?)</script>', page, re.S).group(1))
    assert "if (onlyContributions && row.contributions === 0) { return false; }" in page
    assert [row["public_id"] for row in data if row["contributions"] != 0] == [story_ref]

    # No file of the index holds the project's full path.
    for path in index.iterdir():
        assert str(project) not in path.read_text(encoding="utf-8"), path.name


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


def shown_sessions(stream, report):
    """Each (reference id, public id) a stream's report shows, read from its lines."""
    shown = set()
    if stream == "citations":
        for block in report.split("\n### ")[1:]:
            item = block.split(":", 1)[0]
            for line in block.splitlines():
                if line.startswith("- **Session:** "):
                    shown.add(("citations/" + item, line[len("- **Session:** "):]))
        return shown
    pattern = {"prose": r"^- Change (\S+) came from session (S[0-9a-f]{12})\.$",
               "build": r"^- The AI write to (\S+) came from session (S[0-9a-f]{12})\.$"}[stream]
    for match in re.finditer(pattern, report, re.M):
        shown.add(("%s/%s" % (stream, match.group(1)), match.group(2)))
    return shown


def test_the_projects_sessions_folder_names_each_reports_ai_contributions_by_session(tmp_path):
    project = steps.workspace(tmp_path)
    steps.audit(tmp_path, "init")
    for name in ("story_session.jsonl", "build_touch_session.jsonl"):
        steps.audit(tmp_path, "capture", "--harness", "claude_code", str(tmp_path / "sessions" / name))

    # The three records reach the project, and the first build makes the copy
    # the second session edits.
    out = tmp_path / "audit_out"
    out.mkdir()
    for kind, name, extra in (("citation-log", "citation_log.yaml", []),
                              ("session-writes", "session_writes.jsonl", []),
                              ("rationales", "rationales.yaml", ["--source", "manuscript.md"])):
        steps.audit(tmp_path, "write-out", kind, "--project", str(project), *extra,
                    "--out", str(out / name))
        steps.handoff("audit_to_project.py", "--record", kind.replace("-", "_"),
                      "--from", str(out / name), "--project", str(project))
    steps.build(project, "story v001")
    edit = touch_edit()
    touched = project / TOUCHED
    text = touched.read_text(encoding="utf-8")
    touched.write_text(text.replace(edit["old_string"], edit["new_string"]), encoding="utf-8")

    # The three procedures whose items can name a session.
    inputs = tmp_path / "inputs"
    runs = {stream: tmp_path / "runs" / ("story_" + stream)
            for stream in ("citations", "prose", "build")}
    steps.handoff("project_to_references.py", "--project", str(project),
                  "--references", str(REFERENCES),
                  "--provenance", str(steps.provenance(tmp_path, project)),
                  "--to", str(inputs / "citations"))
    steps.run("graphs/citations.yaml", runs["citations"], inputs / "citations",
              judge=REFERENCES / "recorded_judge.json")
    steps.handoff("project_to_prose.py", "--project", str(project), "--prose", str(PROSE),
                  "--to", str(inputs / "prose"))
    steps.run("graphs/prose.yaml", runs["prose"], inputs / "prose")
    steps.handoff("project_to_build.py", "--project", str(project), "--to", str(inputs / "build"))
    steps.run("graphs/build.yaml", runs["build"], inputs / "build")

    story_ref = steps.public_id(steps.session_id("story_session.jsonl"))
    touch_ref = steps.public_id(steps.session_id("build_touch_session.jsonl"))
    shown = set()
    for stream, run_dir in runs.items():
        found = shown_sessions(stream, steps.report(run_dir))
        assert found, stream
        shown |= found
    assert {ref for _, ref in shown} == {story_ref, touch_ref}
    assert ("build/" + TOUCHED, touch_ref) in shown

    # The scholar approves the prose changes and holds the AI's build write.
    for item in steps.items(runs["prose"]):
        steps.decide(runs["prose"], item["id"], approve=True)
    steps.decide(runs["build"], TOUCHED, approve=False)

    index = tmp_path / "index"
    steps.audit(tmp_path, "write-out", "session-index", "--project", str(project),
                "--out", str(index), *["--results=%s" % (run_dir / "results.json")
                                       for run_dir in runs.values()])
    steps.handoff("session_index_to_project.py", "--from", str(index), "--project", str(project))
    sessions = project / "sessions"
    assert sorted(p.name for p in sessions.iterdir()) == sorted(p.name for p in index.iterdir())

    # The sessions/ folder's reference ids are the items the reports name,
    # each under the session the report shows, with the scholar's decision.
    with open(str(sessions / "sessions.csv"), encoding="utf-8", newline="") as f:
        rows = {row["public_id"]: row for row in csv.DictReader(f)}
    assert sorted(rows) == sorted([story_ref, touch_ref])
    listed = set()
    decisions = {}
    for ref, row in rows.items():
        entries = [entry for entry in row["references"].split("; ") if entry]
        assert row["contributions"] == str(len(entries))
        for entry in entries:
            reference, rest = entry.rsplit(" (", 1)
            listed.add((reference, ref))
            decisions[reference] = rest.split(",", 1)[0]
    assert listed == shown
    assert decisions["build/" + TOUCHED] == "held"
    assert {d for r, d in decisions.items() if r.startswith("prose/")} == {"approved"}
    assert {d for r, d in decisions.items() if r.startswith("citations/")} == {"not yet decided"}

    # Each session's page in the project lists its own reference ids.
    for reference, ref in shown:
        assert "| %s |" % reference in (sessions / (ref + ".md")).read_text(encoding="utf-8")
