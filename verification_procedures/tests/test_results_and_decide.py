"""The results file, the decide command, and the decided report, on the seeded references run.

After a run completes, vg.py writes <run>/results.json, outside the run's step files. Its
items are the rows of the run's report, each marked whether it needs the scholar's
decision. `vg.py decide` records the scholar's approve or hold on one item in that file
and writes <run>/report_decided.md, the run's report with the latest decisions near the
top. The run's own report.md and step records stay as the run wrote them, so `vg.py
verify` still holds. Judgment steps use recorded answers and lookups stay offline, so
nothing here calls a model or the network.
"""
import datetime
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

ROOT = Path(__file__).resolve().parents[1]
VG = [sys.executable, str(ROOT / "vg.py")]
SEEDED = ROOT / "fixtures" / "citations" / "seeded"
GRAPH = "graphs/citations.yaml"
RUN_NAME = "seeded_run"
SCHOLAR_ROWS = ["r03", "r15"]  # the seeded run's two citations the scholar first named
# What the references report says about each citation, under its names in rows_quoted.json.
REPORTED = ["id", "citekey", "sentence", "origin", "origin_evidence", "reference", "lookup",
            "existence", "record", "reason", "reason_source", "quotes", "quote_in_source",
            "access", "source_file"]
RESULTS_FIELDS = {"schema", "schema_version", "stream", "run_id", "procedure_version",
                  "inputs", "items", "decisions"}


def vg(*args):
    env = dict(os.environ, VG_OFFLINE="1")
    return subprocess.run(VG + [str(a) for a in args], cwd=str(ROOT), capture_output=True,
                          text=True, env=env)


def run_seeded(folder, judge=True):
    args = ["run", GRAPH, "--run", folder, "--inputs", SEEDED]
    if judge:
        args += ["--judge", "recorded:" + str(SEEDED / "recorded_judge.json")]
    return vg(*args)


@pytest.fixture(scope="module")
def seeded_run(tmp_path_factory):
    rd = tmp_path_factory.mktemp("results") / RUN_NAME
    p = run_seeded(rd)
    assert p.returncode == 0, p.stdout + p.stderr
    return rd


@pytest.fixture()
def run(seeded_run, tmp_path):
    """A copy of the seeded run under the same folder name, so each test decides on its own."""
    rd = tmp_path / RUN_NAME
    shutil.copytree(str(seeded_run), str(rd))
    return rd


def results(rd):
    return json.loads((rd / "results.json").read_text(encoding="utf-8"))


def rows(rd):
    return json.loads((rd / "files" / "rows_quoted.json").read_text(encoding="utf-8"))


def decide(rd, item, choice, by="A. Author"):
    return vg("decide", "--run", rd, "--item", item, "--" + choice, "--by", by)


def checksum(path):
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def decided_parts(rd):
    """Split report_decided.md into the run's report before its first section, the
    decisions block, and the run's report from its first section on."""
    report = (rd / "files" / "report.md").read_text(encoding="utf-8")
    decided = (rd / "report_decided.md").read_text(encoding="utf-8")
    cut = report.index("\n## ") + 1
    head, tail = report[:cut], report[cut:]
    assert decided.startswith(head) and decided.endswith(tail)
    return head, decided[len(head):len(decided) - len(tail)], tail


def decided_table(block):
    """The decisions table, item id to (decision, by, at, run), in table order."""
    lines = [ln for ln in block.splitlines() if ln.startswith("| ")]
    assert lines[0] == "| Item | Decision | By | At | Run |"
    shown = {}
    for ln in lines[1:]:
        cells = [c.strip() for c in ln.strip()[1:-1].split(" | ")]
        shown[cells[0]] = tuple(cells[1:])
    return shown


def test_a_completed_run_writes_its_results_file_beside_the_step_files(run):
    data = results(run)
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    graph = yaml.safe_load((ROOT / GRAPH).read_text(encoding="utf-8"))
    assert set(data) == RESULTS_FIELDS
    assert data["schema"] == "verification-results"
    assert data["schema_version"] == 1
    assert data["stream"] == "citations"
    assert data["run_id"] == RUN_NAME
    assert data["procedure_version"] == graph["version"]
    assert data["inputs"] == manifest["inputs"]
    assert data["inputs"]["draft.md"] == checksum(SEEDED / "draft.md")
    assert data["decisions"] == []
    assert not (run / "files" / "results.json").exists()
    assert not (run / "report_decided.md").exists()


def test_the_results_file_holds_every_row_with_the_right_needs_decision(run):
    items, rws = results(run)["items"], rows(run)
    assert [i["id"] for i in items] == [r["id"] for r in rws]
    for item, row in zip(items, rws):
        assert set(item) - {"sessions"} == set(REPORTED) | {"notes", "needs_decision"}, item["id"]
        assert {k: item[k] for k in REPORTED} == {k: row[k] for k in REPORTED}, item["id"]
        assert item["needs_decision"] is (row["origin"] != "scholar"), item["id"]
    assert [i["id"] for i in items if not i["needs_decision"]] == SCHOLAR_ROWS
    assert len([i for i in items if i["needs_decision"]]) == 13
    nakamura = [i for i in items if i["id"] == "r08"][0]
    assert (nakamura["citekey"], nakamura["origin"], nakamura["quote_in_source"]) == (
        "nakamura2020", "ai", "yes")


def test_approve_and_hold_are_recorded_with_who_when_and_the_run(run):
    first = results(run)
    before = datetime.datetime.now().astimezone().replace(microsecond=0)
    p = decide(run, "r08", "approve", "A. Author")
    assert p.returncode == 0, p.stdout + p.stderr
    p = decide(run, "r05", "hold", "A. Reviewer")
    assert p.returncode == 0, p.stdout + p.stderr
    after = datetime.datetime.now().astimezone()
    data = results(run)
    assert {k: v for k, v in data.items() if k != "decisions"} == {
        k: v for k, v in first.items() if k != "decisions"}
    decisions = data["decisions"]
    assert [{k: d[k] for k in ("item", "decision", "by", "run_id")} for d in decisions] == [
        {"item": "r08", "decision": "approved", "by": "A. Author", "run_id": RUN_NAME},
        {"item": "r05", "decision": "held", "by": "A. Reviewer", "run_id": RUN_NAME},
    ]
    for d in decisions:
        assert set(d) == {"item", "decision", "by", "at", "run_id"}
        at = datetime.datetime.fromisoformat(d["at"])
        assert at.tzinfo is not None
        assert before <= at <= after


def test_a_later_decision_replaces_an_earlier_one_for_that_item(run):
    assert decide(run, "r08", "hold").returncode == 0
    assert decide(run, "r08", "approve").returncode == 0
    decisions = results(run)["decisions"]
    assert [(d["item"], d["decision"]) for d in decisions] == [("r08", "held"), ("r08", "approved")]
    _, block, _ = decided_parts(run)
    assert decided_table(block)["r08"] == ("approved", "A. Author", decisions[1]["at"], RUN_NAME)
    assert "**1 approved, 0 held, 12 undecided.**" in block
    assert decide(run, "r08", "hold").returncode == 0
    _, block, _ = decided_parts(run)
    assert decided_table(block)["r08"][0] == "held"
    assert "**0 approved, 1 held, 12 undecided.**" in block


@pytest.mark.parametrize("item", ["r99", "R08", "nakamura2020"])
def test_an_unknown_item_is_refused(run, item):
    before = (run / "results.json").read_bytes()
    p = decide(run, item, "approve")
    assert p.returncode != 0
    assert "unknown item" in p.stderr and item in p.stderr
    assert (run / "results.json").read_bytes() == before
    assert not (run / "report_decided.md").exists()


@pytest.mark.parametrize("item", SCHOLAR_ROWS)
@pytest.mark.parametrize("choice", ["approve", "hold"])
def test_an_item_that_needs_no_decision_is_refused(run, item, choice):
    before = (run / "results.json").read_bytes()
    p = decide(run, item, choice)
    assert p.returncode != 0
    assert "needs no decision" in p.stderr and item in p.stderr
    assert (run / "results.json").read_bytes() == before
    assert not (run / "report_decided.md").exists()


def test_a_run_with_no_results_file_is_refused(tmp_path):
    stopped = tmp_path / "stopped"
    p = run_seeded(stopped, judge=False)  # with no judge the run stops at locate_passage
    assert p.returncode == 1, p.stdout + p.stderr
    assert not (stopped / "results.json").exists()
    for folder in (stopped, tmp_path / "no_such_run"):
        p = decide(folder, "r08", "approve")
        assert p.returncode != 0
        assert "no results file" in p.stderr
        assert not (folder / "results.json").exists()
        assert not (folder / "report_decided.md").exists()


def test_decide_takes_one_of_approve_or_hold_and_a_name(run):
    before = (run / "results.json").read_bytes()
    for extra in (["--approve", "--hold", "--by", "A. Author"], ["--by", "A. Author"], ["--approve"]):
        p = vg("decide", "--run", run, "--item", "r08", *extra)
        assert p.returncode == 2, extra
    assert (run / "results.json").read_bytes() == before
    assert not (run / "report_decided.md").exists()


def test_the_decided_report_shows_each_decision(run):
    for item, choice, by in (("r08", "approve", "A. Author"), ("r05", "hold", "A. Author"),
                             ("r01", "approve", "A. Reviewer")):
        assert decide(run, item, choice, by).returncode == 0
    head, block, tail = decided_parts(run)
    assert head.startswith("# References report\n")
    # The references report ranks nothing, so its first section is Citations.
    assert tail.startswith("## Citations\n")
    assert block.startswith("## Decisions\n")
    assert "**2 approved, 1 held, 10 undecided.**" in block
    at = {d["item"]: d["at"] for d in results(run)["decisions"]}
    shown = decided_table(block)
    needing = [i["id"] for i in results(run)["items"] if i["needs_decision"]]
    assert list(shown) == needing
    for item in SCHOLAR_ROWS:
        assert item not in shown
    assert shown["r08"] == ("approved", "A. Author", at["r08"], RUN_NAME)
    assert shown["r05"] == ("held", "A. Author", at["r05"], RUN_NAME)
    assert shown["r01"] == ("approved", "A. Reviewer", at["r01"], RUN_NAME)
    for item in needing:
        if item not in ("r01", "r05", "r08"):
            assert shown[item] == ("undecided", "-", "-", "-"), item


def test_report_and_step_records_are_unchanged_and_verify_still_replays(run):
    def snapshot():
        return {str(p.relative_to(run)): checksum(p) for p in sorted(run.rglob("*"))
                if p.is_file() and p.name not in ("results.json", "report_decided.md")}

    before = snapshot()
    assert "files/report.md" in before
    assert len([k for k in before if k.startswith("records/")]) == 11
    for item, choice in (("r08", "hold"), ("r08", "approve"), ("r05", "hold"), ("r01", "approve")):
        assert decide(run, item, choice).returncode == 0
    assert snapshot() == before
    p = vg("verify", "--run", run)
    assert p.returncode == 0, p.stdout + p.stderr
    for s in json.loads((run / "verify.json").read_text(encoding="utf-8"))["steps"]:
        if s["node"] == "fetch_metadata":
            assert s["verdict"].startswith("network step")
        elif s["verdict"].startswith("judgment"):
            continue
        else:
            assert s["verdict"] == "replay matches", s


def test_the_seeded_scores_hold_after_decisions(run):
    for item, choice in (("r08", "approve"), ("r05", "hold")):
        assert decide(run, item, choice).returncode == 0
    p = vg("score", "--run", run, "--truth", SEEDED / "truth.yaml")
    assert p.returncode == 0, p.stdout + p.stderr
    score = json.loads((run / "score.json").read_text(encoding="utf-8"))
    assert score["faults"] == 13 and score["recall"] == 1.0 and score["missed"] == []
    assert score["extra_findings"] == []


def test_a_seeded_prose_run_lists_its_changes_and_decide_refuses_an_unknown_item(tmp_path):
    # Replaces the slice's test of an empty item list, by the ruling of 2026-10-29 in the
    # clean build's reconciliation file, now that the prose stream is widened (Track W, W16).
    fx = ROOT / "fixtures" / "prose" / "seeded"
    rd = tmp_path / "prose_run"
    p = vg("run", "graphs/prose.yaml", "--run", rd, "--inputs", fx)
    assert p.returncode == 0, p.stdout + p.stderr
    data = results(rd)
    manifest = json.loads((rd / "manifest.json").read_text(encoding="utf-8"))
    graph = yaml.safe_load((ROOT / "graphs" / "prose.yaml").read_text(encoding="utf-8"))
    assert set(data) == RESULTS_FIELDS
    assert (data["stream"], data["run_id"]) == ("prose", "prose_run")
    assert data["procedure_version"] == graph["version"]
    assert data["inputs"] == manifest["inputs"]
    assert data["decisions"] == []
    changes = json.loads((rd / "files" / "changes.json").read_text(encoding="utf-8"))
    assert changes
    change_items = [it["id"] for it in data["items"] if it["kind"] == "change"]
    assert change_items == [c["id"] for c in changes]
    p = decide(rd, "c99", "approve")
    assert p.returncode != 0 and "unknown item" in p.stderr
    assert not (rd / "report_decided.md").exists()
