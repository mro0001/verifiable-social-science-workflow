"""End to end on the test story, publishing a verification repository
(publish design Part C).

Both story sessions are recorded, and the audit layer writes out its three
records, which are handed to the project. The four procedures run offline on
recorded answers, the scholar approves every item that needs a decision, and
the four results reach the project, so the manuscript's next build is marked
verified. python3 -m features publish build then assembles the verification
repository from the project and the runs folder, with a features home whose
system.yaml names this workflow and the test's audit home. Every number in
the README and its manifest is the one the four results files, the ledger,
and the session index give, and the README says the manuscript is marked
verified. The published results file of each stream is the project's own,
and its report is the run's decided report.

Last, the ops_publish check runs on the inputs folder the build wrote beside
the repository and finds no blocking problem. It rebuilds the manuscript only
when this machine has a make that works, chosen as publish_rebuild chooses
it, and pandoc. The repository is anonymous, the default, so the check looks
for the scholar's name in system.yaml and each of its words. The scholar
signs each decision with the story's label, "story scholar", which is none of
them, as the publishing guide says, so the decision records the results
files and reports carry give no finding. Pandoc writes its options into each
Word build's custom properties, which the check lists in one note for each
Word build and does not block, so the answers need no allow entry; the test
asserts that each Word build has that note. The build report names the
session of the AI's write to a build folder by its public id, so the check
finds no raw session id.

Each layer is reached only through its command line and its files, as a
scholar would reach it, through the helpers in story_steps.py. Run from the
repository root with python3 -m pytest -q examples/test_story.
"""
import calendar
import csv
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import yaml

import story_steps as steps

STORY = Path(__file__).resolve().parents[1]
REFERENCES = STORY / "references"
PROSE = STORY / "prose"
TOUCH_SESSION = STORY / "sessions" / "claude_code" / "build_touch_session.jsonl"
STREAMS = ("prose", "citations", "data", "build")
MAKES = (["make"], ["arch", "-arm64", "make"], ["/Library/Developer/CommandLineTools/usr/bin/make"])
REPO_URL = "https://github.com/example-scholar/story-verification"
WORKFLOW_FOLDER = "verifiable-social-science-workflow"
ACCEPTED = "Accepted by the settings."
# The note the check gives each Word build for the options pandoc writes into it.
CUSTOM_NOTE = "custom properties: bibliography, subtitle"
WORD_BUILDS = ("project/builds/manuscript/v001.docx", "project/builds/manuscript/v002.docx")
# The scholar's name in system.yaml, which no decision carries, and the terms
# an anonymous build checks for.
SCHOLAR_NAME = "Avery Quill"
NAME_TERMS = ["Avery Quill", "Avery", "Quill"]


def working_make():
    """The first make whose version line names GNU Make, as publish_rebuild chooses it,
    or None."""
    for command in MAKES:
        try:
            done = subprocess.run(command + ["--version"], stdin=subprocess.DEVNULL,
                                  capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            continue
        if done.returncode == 0 and "GNU Make" in done.stdout:
            return command
    return None


def can_rebuild():
    return working_make() is not None and shutil.which("pandoc") is not None


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


def features_home(tmp_path):
    """A features home whose system.yaml has every field system setup writes, naming this
    workflow and the test's audit home."""
    home = tmp_path / "features_home"
    home.mkdir()
    record = {
        "schema": "features-system",
        "schema_version": 1,
        "written_at": "2026-10-31T00:00:00Z",
        "workflow_root": str(steps.ROOT),
        "python": "%d.%d" % sys.version_info[:2],
        "scholar_name": SCHOLAR_NAME,
        "harness": "claude_code",
        "audit_home": str(tmp_path / "audit_home"),
        "citation_export": "",
        "excluded_folders": [],
        "layers": {},
        "ready": True,
        "software": [],
    }
    (home / "system.yaml").write_text(yaml.safe_dump(record, sort_keys=False), encoding="utf-8")
    return home


def publish_build(project, out, answers, runs, home):
    done = subprocess.run(
        [sys.executable, "-m", "features", "publish", "build", str(project), "--out", str(out),
         "--answers", str(answers), "--runs", str(runs), "--home", str(home)],
        cwd=str(steps.ROOT), capture_output=True, text=True)
    assert done.returncode == 0, "publish build exit %d\n%s%s" % (
        done.returncode, done.stdout, done.stderr)
    return done.stdout


def check(inputs, run_dir):
    """Run the ops_publish check offline and give its findings."""
    steps.run("graphs/ops_publish.yaml", run_dir, inputs)
    return json.loads((Path(run_dir) / "files" / "findings.json").read_text(encoding="utf-8"))


def _findings(item):
    return item.get("findings") or []


def expected_counts(run_dirs):
    """The README's numbers, worked out here from the four results files."""
    prose = steps.items(run_dirs["prose"])
    citations = steps.items(run_dirs["citations"])
    data = steps.items(run_dirs["data"])
    changes = [item for item in prose if item.get("kind") == "change"]
    rows = [item for item in citations if item.get("citekey")]
    numbers = [item for item in data if item.get("kind") == "number"]
    return {
        "prose.changes": len(changes),
        "prose.ai": sum(1 for item in changes if item["needs_decision"]),
        "citations.rows": len(rows),
        "citations.ai": sum(1 for item in rows if item.get("origin") == "ai"),
        "data.numbers": len(numbers),
        "data.reproduce": sum(1 for item in numbers if not any(
            finding.get("check") == "check_numbers" for finding in _findings(item))),
        "decisions.approved": sum(1 for run_dir in run_dirs.values()
                                  for item in steps.items(run_dir) if item["needs_decision"]),
        "decisions.held": 0,
        "decisions.undecided": 0,
        "sessions.indexed": 2,
    }


def test_publish_builds_a_repository_that_passes_its_check(tmp_path):
    project = steps.workspace(tmp_path)

    # Recorded and identified. Both sessions are stored, and the three records
    # reach the project. The second session's edit lands on the first build.
    steps.audit(tmp_path, "init")
    for name in ("story_session.jsonl", "build_touch_session.jsonl"):
        steps.audit(tmp_path, "capture", "--harness", "claude_code",
                    str(tmp_path / "sessions" / name))
    write_out(tmp_path, project, "citation-log", "citation_log.yaml")
    write_out(tmp_path, project, "session-writes", "session_writes.jsonl")
    write_out(tmp_path, project, "rationales", "rationales.yaml", "--source", "manuscript.md")
    assert steps.build(project, "story v001")["version"] == "v001"
    edit = touch_edit()
    touched = project / edit["file_path"].replace(steps.TOKEN + "/", "", 1)
    text = touched.read_text(encoding="utf-8")
    assert text.count(edit["old_string"]) == 1
    touched.write_text(text.replace(edit["old_string"], edit["new_string"]), encoding="utf-8")

    # Checked and reported. The four procedures run on recorded answers.
    inputs = tmp_path / "inputs"
    runs = tmp_path / "runs"
    run_dirs = dict((stream, runs / ("story_" + stream)) for stream in STREAMS)
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

    # Approved. The scholar approves every item, the results reach the
    # project, and the next build is marked verified.
    for run_dir in run_dirs.values():
        for item in steps.items(run_dir):
            if item["needs_decision"]:
                steps.decide(run_dir, item["id"], approve=True)
    copy_results(run_dirs, project)
    row = steps.build(project, "story v002")
    assert row["version"] == "v002"
    assert row["verification"] == "verified"

    # Published. The answers need no allow entry.
    rebuild = can_rebuild()
    answers = tmp_path / "publish_answers.yaml"
    answers.write_text(yaml.safe_dump({
        "title": "Verification reports for the test story",
        "repo_url": REPO_URL,
        "check": {"rebuild": rebuild},
    }, sort_keys=False), encoding="utf-8")
    out = tmp_path / "published" / "story-verification"
    printed = publish_build(project, out, answers, runs, features_home(tmp_path))
    check_inputs = out.parent / (out.name + ".check")
    assert printed.splitlines()[0] == "Wrote %s" % out
    assert "--inputs %s" % check_inputs in printed
    assert sorted(path.name for path in check_inputs.iterdir()) == [
        "left_out.json", "publish_check.yaml", "repo.tar"]
    assert not (out.parent / (out.name + ".github")).exists()
    settings = yaml.safe_load((check_inputs / "publish_check.yaml").read_text(encoding="utf-8"))
    assert settings["terms"] == NAME_TERMS
    assert (out / ".gitignore").read_text(encoding="utf-8") == ".DS_Store\n"

    # Every number comes from the results files, the ledger, and the index.
    expected = expected_counts(run_dirs)
    manifest = json.loads((out / "docs" / "publish_manifest.json").read_text(encoding="utf-8"))
    assert manifest["anonymous"] is True
    counts = manifest["counts"]
    for key, value in expected.items():
        assert counts[key] == value, key
    assert counts["builds.total"] == 2
    assert counts["builds.manuscript.latest"] == "v002"
    assert counts["builds.manuscript.state"] == "verified"
    assert "builds.slides.latest" not in counts
    states = dict((product["name"], product["state"]) for product in manifest["products"])
    assert states == {"manuscript": "verified", "slides": "no numbered build yet"}
    assert counts["missing"] == ""
    with open(str(out / "project" / "sessions" / "sessions.csv"), encoding="utf-8",
              newline="") as handle:
        indexed = sorted(row["public_id"] for row in csv.DictReader(handle))
    assert indexed == sorted([steps.public_id(steps.session_id(name)) for name in
                              ("story_session.jsonl", "build_touch_session.jsonl")])

    readme = (out / "README.md").read_text(encoding="utf-8")
    assert readme.startswith("# Verification reports for the test story\n")
    assert "Every item is approved, and `manuscript` is marked verified." in readme
    assert "all %d approved" % expected["decisions.approved"] in readme
    assert "%d of %d changes were made by an AI." % (
        expected["prose.ai"], expected["prose.changes"]) in readme
    assert "%d of %d citations were first named by an AI." % (
        expected["citations.ai"], expected["citations.rows"]) in readme
    assert expected["data.reproduce"] == expected["data.numbers"]
    assert "All %d numbers reproduce from the raw data." % expected["data.numbers"] in readme
    assert "No AI session wrote or changed the analysis script." in readme
    assert "one row for each of the %d AI sessions" % expected["sessions.indexed"] in readme
    epoch = calendar.timegm(time.strptime(row["date"], "%Y-%m-%d"))
    assert counts["builds.manuscript.epoch"] == epoch
    assert ("SOURCE_DATE_EPOCH=%d PYTHONPATH=../../%s/ospipe make manuscript"
            % (epoch, WORKFLOW_FOLDER)) in readme
    assert "`slides` has no numbered build yet." in readme
    assert "git clone %s\n" % REPO_URL in readme
    for stream in STREAMS:
        assert "](project/verification/%s/report.md)" % stream in readme
    figure = (out / "docs" / "results.svg").read_text(encoding="utf-8")
    assert ">verified</text>" in figure
    assert ">no build yet</text>" in figure

    # Each stream's results file is the project's own, and its report is the
    # run's decided report.
    for stream, run_dir in run_dirs.items():
        folder = out / "project" / "verification" / stream
        assert (folder / "results.json").read_bytes() == (
            project / "verification" / (stream + ".json")).read_bytes()
        assert (folder / "report.md").read_bytes() == (run_dir / "report_decided.md").read_bytes()
    assert not (out / "project" / "audit").exists()

    # Checked before it goes public. Nothing blocks, nothing warns, nothing
    # needed accepting, and each Word build has the note on pandoc's options.
    findings = check(check_inputs, tmp_path / "check_run")
    blocking = [finding for finding in findings if finding["severity"] == "blocking"]
    assert blocking == []
    warnings = [finding for finding in findings if finding["severity"] == "warning"]
    assert warnings == []
    assert not [finding for finding in findings if finding["message"].startswith(ACCEPTED)]
    for path in WORD_BUILDS:
        assert any(finding["item"] == path and finding["severity"] == "info"
                   and finding["evidence"] == CUSTOM_NOTE for finding in findings), path
    # With make and pandoc here, the manuscript rebuilds byte for byte, and
    # slides, which has no numbered build, is skipped.
    rebuilt = tmp_path / "check_run" / "files" / "rebuild.json"
    if rebuild:
        products = json.loads(rebuilt.read_text(encoding="utf-8"))["products"]
        assert dict((product["name"], product["result"]) for product in products) == {
            "manuscript": "same bytes", "slides": "skipped"}
    else:
        assert not rebuilt.exists()
