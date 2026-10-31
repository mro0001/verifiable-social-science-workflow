"""Portability on the test story, across two harnesses and two models
(proposal Approach, appendix A2.2, A2.4 "Capture", A4, and A5).

Two harnesses. Claude Code is the first harness and ForgeCode the fallback,
and each has its own capture adapter. The story's AI-added citations run end
to end twice, once from the Claude Code story session and once from the
synthetic ForgeCode conversation the audit layer's ForgeCode tests use, which
holds the same work in Forge's form. Each run records the session, writes
out the citation log, hands it to the project, writes out the citation
provenance record, which the references handoff gathers with the final
build's filled-in text, runs the procedure
with recorded answers, approves each item with vg.py decide, copies the
results back, and builds. Both runs give the same citation log keys, the
same items, and the same build marks before and after approval. The one
difference is where in the record each item says its citation appears, the
public id worked out from its own harness's session id and the time its own
harness recorded.

Two models. The references procedure runs on the story with its one model
step, which locates a passage, answered by two different recorded models in
turn, and both give the same items. Each run's manifest names the executor it
used. Since the references procedure 0.2 (Track C2) asks no second model, a
second checker named on its command line is never asked.

Each layer is reached only through its command line and its files, through
the helpers in story_steps.py. The Forge conversation comes from the audit
layer's test fixture file, which uses the standard library only and imports
no layer's code. Nothing here reads a real session file or Forge database,
calls a model, or uses the network. Run from the repository root with
python3 -m pytest -q examples/test_story.
"""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

import story_steps as steps

STORY = Path(__file__).resolve().parents[1]
REFERENCES = STORY / "references"
FORGE_FIXTURE = (steps.ROOT / "audit_layer" / "tests" / "fixtures" / "forgecode"
                 / "make_store.py")
ALL_STREAMS = {"prose", "citations", "data", "build"}
CLAUDE_STORY_ID = "5f3c0413-2a7d-4b9e-8c61-a0d4e7b2c913"


def forge_fixture():
    spec = importlib.util.spec_from_file_location("forgecode_make_store", str(FORGE_FIXTURE))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


forge = forge_fixture()


# The item fields that say where in the record a citation appears, which name the
# session's public id and the time its own harness recorded.
WHERE_IN_THE_RECORD = ("sessions", "origin_evidence", "reason_source")


def without_sessions(items):
    """The items with the public ids of their sessions, and where in the record each
    citation appears, left out."""
    return [{k: v for k, v in item.items() if k not in WHERE_IN_THE_RECORD} for item in items]


def sessions_by_key(items):
    return {item["citekey"]: item.get("sessions") for item in items}


def session_location(tmp_path, project, harness):
    """Where the harness keeps the story's work, written inside tmp_path."""
    if harness == "claude_code":
        return str(tmp_path / "sessions" / "story_session.jsonl")
    db = forge.make_store(tmp_path / "forge" / ".forge.db", project)
    return "%s#%s" % (db, forge.STORY_ID)


def recorded_story(tmp_path, harness):
    """The story project with the session recorded from the harness and its
    citation log written out and handed to the project. Gives the project and
    the citation log as written out."""
    project = steps.workspace(tmp_path)
    steps.audit(tmp_path, "init")
    steps.audit(tmp_path, "capture", "--harness", harness,
                session_location(tmp_path, project, harness))
    out = tmp_path / "audit_out" / "citation_log.yaml"
    out.parent.mkdir()
    steps.audit(tmp_path, "write-out", "citation-log", "--project", str(project), "--out", str(out))
    steps.handoff("audit_to_project.py", "--record", "citation_log", "--from", str(out),
                  "--project", str(project))
    return project, yaml.safe_load(out.read_text(encoding="utf-8"))


def references_inputs(tmp_path, project):
    """The references procedure's inputs, which the handoff gathers from the
    project's latest build, so the project must have been built."""
    inputs = tmp_path / "inputs" / "citations"
    steps.handoff("project_to_references.py", "--project", str(project),
                  "--references", str(REFERENCES),
                  "--provenance", str(steps.provenance(tmp_path, project)), "--to", str(inputs))
    return inputs


def citation_round(tmp_path, harness):
    """The story's citations end to end from one harness. Gives the citation
    log, the run's items before and after approval, the decisions, and the
    build marks."""
    project, log = recorded_story(tmp_path, harness)
    marks = [steps.build(project, "story v001")["verification"]]

    inputs = references_inputs(tmp_path, project)
    run_dir = tmp_path / "runs" / "story_citations"
    steps.run("graphs/citations.yaml", run_dir, inputs, judge=REFERENCES / "recorded_judge.json")
    before = steps.items(run_dir)
    steps.handoff("results_to_pipeline.py", "--run", str(run_dir), "--stream", "citations",
                  "--project", str(project))
    marks.append(steps.build(project, "story v002")["verification"])

    for item in before:
        if item["needs_decision"]:
            steps.decide(run_dir, item["id"], approve=True)
    after = steps.items(run_dir)
    results = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    decisions = [(entry["item"], entry["decision"]) for entry in results["decisions"]]
    steps.handoff("results_to_pipeline.py", "--run", str(run_dir), "--stream", "citations",
                  "--project", str(project))
    marks.append(steps.build(project, "story v003")["verification"])
    return {"log": log, "before": before, "after": after, "decisions": decisions,
            "marks": marks}


def test_both_harnesses_give_the_same_citations_items_and_build_marks(tmp_path):
    claude = citation_round(tmp_path / "claude_code", "claude_code")
    forge_run = citation_round(tmp_path / "forgecode", "forgecode")

    # The same citation log keys, each from its own harness's session.
    assert sorted(claude["log"]["citations"]) == ["dumont2014", "nakamura2020"]
    assert sorted(forge_run["log"]["citations"]) == sorted(claude["log"]["citations"])
    for key, entry in claude["log"]["citations"].items():
        other = forge_run["log"]["citations"][key]
        assert entry["introduced_by"] == other["introduced_by"] == "ai"
        assert entry["draft"] == other["draft"]
        assert entry["session"] == CLAUDE_STORY_ID
        assert other["session"] == forge.STORY_ID

    # The same items, before and after approval.
    assert [item["id"] for item in claude["before"] if item["needs_decision"]] == [
        "r01", "r02", "r03"]
    assert without_sessions(forge_run["before"]) == without_sessions(claude["before"])
    assert claude["after"] == claude["before"]
    assert forge_run["after"] == forge_run["before"]
    for run, session in ((claude, CLAUDE_STORY_ID), (forge_run, forge.STORY_ID)):
        ref = [steps.public_id(session)]
        assert sessions_by_key(run["before"]) == {
            "castellanos2017": None, "dumont2014": ref, "nakamura2020": ref}
    assert claude["decisions"] == [("r01", "approved"), ("r02", "approved"), ("r03", "approved")]
    assert forge_run["decisions"] == claude["decisions"]

    # The same build marks. v001 has no results, v002 has undecided items,
    # and v003 comes after every item is approved.
    assert forge_run["marks"] == claude["marks"]
    flags = [steps.flags({"verification": mark}) for mark in claude["marks"]]
    assert flags[0] == ALL_STREAMS
    assert "citations" in flags[1]
    assert flags[2] == ALL_STREAMS - {"citations"}


def model_answers(folder, name):
    """A recorded model that answers the one model step of the story's references run."""
    answers = json.loads((REFERENCES / "recorded_judge.json").read_text(encoding="utf-8"))
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(json.dumps(answers, indent=2), encoding="utf-8")
    return path


def executors_used(run_dir):
    """Each judgment step's role and the executors its record names."""
    used = {}
    for record in sorted((Path(run_dir) / "records").glob("*.json")):
        execution = json.loads(record.read_text(encoding="utf-8")).get("execution") or {}
        if execution.get("type") == "judgment":
            used.setdefault(execution["role"], set()).update(execution["executor"])
    return used


def test_the_references_procedure_runs_with_either_of_two_models(tmp_path):
    project, _ = recorded_story(tmp_path, "claude_code")
    steps.build(project, "story v001")
    inputs = references_inputs(tmp_path, project)
    model_a = model_answers(tmp_path / "models", "model_a.json")
    model_b = model_answers(tmp_path / "models", "model_b.json")

    runs = {}
    for name, judge in (("a_judges", model_a), ("b_judges", model_b)):
        run_dir = tmp_path / "runs" / name
        steps.run("graphs/citations.yaml", run_dir, inputs, judge=judge)
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["executors"] == {"judge": "recorded:%s" % judge, "second": None}
        assert executors_used(run_dir) == {"judge": {"recorded:" + judge.name}}
        runs[name] = steps.items(run_dir)

    # Both models give the same answers, so the items are the same with either.
    assert [item["id"] for item in runs["a_judges"] if item["needs_decision"]] == [
        "r01", "r02", "r03"]
    assert runs["b_judges"] == runs["a_judges"]


def test_a_second_checker_named_for_the_references_procedure_is_never_asked(tmp_path):
    project, _ = recorded_story(tmp_path, "claude_code")
    steps.build(project, "story v001")
    inputs = references_inputs(tmp_path, project)
    model_a = model_answers(tmp_path / "models", "model_a.json")
    run_dir = tmp_path / "runs" / "a_twice"
    done = subprocess.run(
        [sys.executable, "vg.py", "run", "graphs/citations.yaml", "--run", str(run_dir),
         "--inputs", str(inputs), "--judge", "recorded:%s" % model_a,
         "--second", "recorded:%s" % model_a],
        cwd=str(steps.VERIFICATION), env=dict(os.environ, VG_OFFLINE="1"),
        capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr
    assert executors_used(run_dir) == {"judge": {"recorded:" + model_a.name}}
