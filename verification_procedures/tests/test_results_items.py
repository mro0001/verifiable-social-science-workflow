"""Build, data, and prose stream items in the results file (Track W, steps W8, W11,
and W16).

Appendix A2.5 "Verification reports" asks the scholar to approve or hold each item
of a stream's results, and the product carries `unverified: <stream>` until every
item is approved. A completed build run now lists its items in <run>/results.json.
These are one row for each deliverable in the run's map, then one item for each
other group of blocking or warning findings, grouped by the finding's item. A
completed data run lists one row for each manuscript number in its
numbers_check.json, then the same problem items. A completed prose run lists one
row for each change in its changes.json, where the scholar's own change, which the
record of the AI's changes does not name, needs no decision, then the same problem items. Every item carries the slice's
`id` and `needs_decision` plus `kind`, `summary`, and `findings`. Since Step C10
the results writer takes these items from the run's fields.json, the item rows the
stream's schema fills, so the tests on made-up step outputs rerun the run's saved
report script and read the items back from results.json. Each run is made
in a temp folder. Judgment runs on recorded answers. Nothing here calls a model or
the network.
"""
import importlib.util
import inspect
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
VG = [sys.executable, str(ROOT / "vg.py")]
FIX = ROOT / "fixtures" / "build"
GRAPH = "graphs/build.yaml"
ITEM_KEYS = ["id", "kind", "summary", "findings", "needs_decision"]
FINDING_KEYS = ["check", "severity", "message", "evidence"]
SEEDED_PROBLEMS = {"builds/paper/v001.html", "builds/paper/v002.html", "builds/slides/v001.html",
                   "drafts/paper_full.md", "paper/paper.md:0.31",
                   "slides/slides.md:{{num:n_teams}}", "slides:number_sections"}


def vg(*args):
    env = dict(os.environ, VG_OFFLINE="1")
    return subprocess.run(VG + [str(a) for a in args], cwd=str(ROOT), capture_output=True,
                          text=True, env=env)


def load_vg():
    spec = importlib.util.spec_from_file_location("vg_for_items", ROOT / "vg.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_build(folder, fixture):
    p = vg("run", GRAPH, "--run", folder, "--inputs", FIX / fixture)
    assert p.returncode == 0, p.stdout + p.stderr
    return folder


@pytest.fixture(scope="module")
def seeded_build(tmp_path_factory):
    return run_build(tmp_path_factory.mktemp("items") / "seeded_build", "seeded")


@pytest.fixture(scope="module")
def clean_build(tmp_path_factory):
    return run_build(tmp_path_factory.mktemp("items") / "clean_build", "clean")


@pytest.fixture()
def run(seeded_build, tmp_path):
    """A copy of the seeded build run under the same name, so each test decides on its own."""
    rd = tmp_path / seeded_build.name
    shutil.copytree(str(seeded_build), str(rd))
    return rd


def results(rd):
    return json.loads((rd / "results.json").read_text(encoding="utf-8"))


def run_findings(rd):
    return json.loads((rd / "files" / "findings.json").read_text(encoding="utf-8"))


def problems_of(findings):
    return [f for f in findings if f["severity"] in ("blocking", "warning")]


def as_tuple(f):
    return tuple(f[k] for k in FINDING_KEYS)


# ---------------------------------------------------------------- seeded build fixture

def test_the_seeded_build_lists_its_deliverables_then_one_item_for_each_problem(seeded_build):
    data = results(seeded_build)
    assert data["stream"] == "build" and data["decisions"] == []
    items = data["items"]
    assert [it["id"] for it in items[:2]] == ["paper", "slides"]
    assert [it["kind"] for it in items[:2]] == ["deliverable", "deliverable"]
    rest = items[2:]
    assert {it["id"] for it in rest} == SEEDED_PROBLEMS
    assert len(rest) == len(SEEDED_PROBLEMS)
    assert all(it["kind"] == "finding" for it in rest)
    assert all(it["needs_decision"] is True for it in items)
    for it in items:
        assert list(it) == ITEM_KEYS, it["id"]
        for f in it["findings"]:
            assert list(f) == FINDING_KEYS, it["id"]


def test_every_blocking_or_warning_finding_sits_in_exactly_one_item(seeded_build):
    problems = problems_of(run_findings(seeded_build))
    assert problems
    carried = Counter()
    for it in results(seeded_build)["items"]:
        carried.update(as_tuple(f) for f in it["findings"])
    assert carried == Counter(as_tuple(f) for f in problems)
    # Each problem item holds exactly the problems found on its own item.
    for it in results(seeded_build)["items"][2:]:
        assert [as_tuple(f) for f in it["findings"]] == [
            as_tuple(f) for f in problems if f["item"] == it["id"]]


def test_info_findings_make_no_item(seeded_build):
    infos = [f for f in run_findings(seeded_build) if f["severity"] == "info"]
    assert infos
    ids = {it["id"] for it in results(seeded_build)["items"]}
    carried = {as_tuple(f) for it in results(seeded_build)["items"] for f in it["findings"]}
    for f in infos:
        assert as_tuple(f) not in carried
    assert "canonical sources" not in ids and "drafts/paper_2026-09.md" not in ids


def test_a_deliverable_summary_gives_its_source_builds_folder_and_ledgered_versions(seeded_build):
    items = {it["id"]: it for it in results(seeded_build)["items"]}
    assert items["paper"]["summary"] == (
        "source paper/paper.md, builds folder builds/paper, ledgered versions v001, v002")
    assert items["slides"]["summary"] == (
        "source slides/slides.md, builds folder builds/slides, ledgered versions v001")
    # No problem in the seeded fixture is found on a deliverable's own name.
    assert items["paper"]["findings"] == [] and items["slides"]["findings"] == []


def test_a_problem_summary_gives_the_count_and_the_first_message_cut_to_120(seeded_build):
    # The seeded messages all fit in 120 characters. The cut is shown on made-up findings below.
    problems = problems_of(run_findings(seeded_build))
    for it in results(seeded_build)["items"][2:]:
        first = [f for f in problems if f["item"] == it["id"]][0]["message"]
        assert it["summary"] == "1 problem. " + first[:120]


def test_the_seeded_build_score_holds_and_the_run_still_replays(run):
    assert vg("decide", "--run", run, "--item", "paper", "--approve",
              "--by", "story scholar").returncode == 0
    p = vg("score", "--run", run, "--truth", FIX / "seeded" / "truth.yaml")
    assert p.returncode == 0, p.stdout + p.stderr
    score = json.loads((run / "score.json").read_text(encoding="utf-8"))
    assert score["faults"] == 7 and len(score["caught"]) == 7 and score["missed"] == []
    assert score["extra_findings"] == []
    v = vg("verify", "--run", run)
    assert v.returncode == 0 and "FAIL" not in v.stdout, v.stdout
    assert "replay matches" in v.stdout


# ---------------------------------------------------------------- clean build fixture

def test_the_clean_build_lists_only_its_two_deliverables_with_no_findings(clean_build):
    items = results(clean_build)["items"]
    assert [(it["id"], it["kind"]) for it in items] == [("paper", "deliverable"),
                                                         ("slides", "deliverable")]
    assert all(it["findings"] == [] and it["needs_decision"] is True for it in items)
    assert items[0]["summary"] == (
        "source paper/paper.md, builds folder builds/paper, ledgered versions v001, v002")


# ---------------------------------------------------------------- made-up findings, through results.json

def finding(check, severity, item, message, evidence=""):
    return {"check": check, "severity": severity, "item": item, "message": message,
            "evidence": evidence}


def rerun_report(done, dest, files, findings):
    """A copy of a completed run with some step outputs replaced by made-up ones and every
    findings_*.json replaced by the made-up findings, one file per check. The run's own
    saved report script runs again on those files, then the results writer writes
    results.json again from the new fields.json. Returns that file's items."""
    shutil.copytree(str(done), str(dest))
    fdir = dest / "files"
    for p in list(fdir.glob("findings_*.json")):
        p.unlink()
    for name in ("findings.json", "fields.json", "report.md"):
        (fdir / name).unlink()
    (dest / "results.json").unlink()
    for name, obj in files.items():
        (fdir / name).write_text(json.dumps(obj), encoding="utf-8")
    by_check = {}
    for f in findings:
        by_check.setdefault(f["check"], []).append(f)
    for check, found in by_check.items():
        (fdir / ("findings_%s.json" % check)).write_text(json.dumps(found), encoding="utf-8")
    script = sorted(dest.glob("code/*_report/report.py"))[-1]
    p = subprocess.run([sys.executable, str(script), str(fdir)], capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
    load_vg().write_results(str(dest))
    return results(dest)["items"]


def build_items(clean_build, tmp_path, names, findings):
    """The build items of the clean build run redone with a map of the named deliverables,
    an empty ledger, and the made-up findings."""
    deliverables = [{"name": n, "source": "%s/%s.md" % (n, n), "builds_dir": "builds/" + n}
                    for n in names]
    return rerun_report(clean_build, tmp_path / clean_build.name, {
        "map.json": {"deliverables": deliverables, "look_alikes": []},
        "ledger.json": {"rows": 0, "builds": [], "latest": {}}}, findings)


def deliverable(name, found=()):
    return {"id": name, "kind": "deliverable",
            "summary": "source %s/%s.md, builds folder builds/%s, ledgered versions none" % (
                name, name, name),
            "findings": list(found), "needs_decision": True}


def test_info_findings_on_their_own_make_no_item(clean_build, tmp_path):
    items = build_items(clean_build, tmp_path, ["paper"],
                        [finding("read_map", "info", "drafts/a.md", "Archived look-alike.")])
    assert items == [deliverable("paper")]


def test_two_findings_on_the_same_path_make_one_item(clean_build, tmp_path):
    found = [finding("check_ledger", "blocking", "builds/paper/v001.html", "Edited after build.", "e1"),
             finding("read_map", "info", "builds/paper/v001.html", "Only a note."),
             finding("rebuild", "warning", "builds/paper/v001.html", "Not derived from the build.", "e2")]
    items = build_items(clean_build, tmp_path, ["paper", "slides"], found)
    assert items == [deliverable("paper"), deliverable("slides"), {
        "id": "builds/paper/v001.html",
        "kind": "finding",
        "summary": "2 problems. Edited after build.",
        "findings": [
            {"check": "check_ledger", "severity": "blocking", "message": "Edited after build.",
             "evidence": "e1"},
            {"check": "rebuild", "severity": "warning", "message": "Not derived from the build.",
             "evidence": "e2"}],
        "needs_decision": True,
    }]


def test_a_finding_on_a_row_id_is_carried_by_that_row(clean_build, tmp_path):
    found = [finding("check_ledger", "warning", "slides", "No ledger columns.", "cols"),
             finding("check_prefs", "blocking", "slides:number_sections", "Preference missing.")]
    items = build_items(clean_build, tmp_path, ["paper", "slides"], found)
    assert items[:2] == [deliverable("paper"), deliverable("slides", [
        {"check": "check_ledger", "severity": "warning", "message": "No ledger columns.",
         "evidence": "cols"}])]
    assert [it["id"] for it in items[2:]] == ["slides:number_sections"]


def test_a_long_first_message_is_cut_to_120_characters(clean_build, tmp_path):
    long_message = "x" * 200
    items = build_items(clean_build, tmp_path, [],
                        [finding("read_map", "blocking", "Makefile", long_message)])
    assert [it["id"] for it in items] == ["Makefile"]
    assert items[0]["summary"] == "1 problem. " + "x" * 120


def test_a_finding_on_a_deliverable_name_is_carried_by_that_deliverable(clean_build, tmp_path):
    """A build run's findings with a problem on a deliverable's own name, as check_ledger
    writes for a deliverable with no builds, move onto that row."""
    items = rerun_report(clean_build, tmp_path / clean_build.name, {
        "map.json": {"deliverables": [{"name": "paper", "source": None, "builds_dir": "builds/paper"}],
                     "look_alikes": []},
        "ledger.json": {"rows": 0, "builds": [], "latest": {}}},
        [finding("read_map", "blocking", "paper", "No source for this deliverable.", "rule paper")])
    assert items == [{
        "id": "paper",
        "kind": "deliverable",
        "summary": "source (none), builds folder builds/paper, ledgered versions none",
        "findings": [{"check": "read_map", "severity": "blocking",
                      "message": "No source for this deliverable.", "evidence": "rule paper"}],
        "needs_decision": True,
    }]


# ---------------------------------------------------------------- deciding a build item

def test_decide_approves_and_holds_a_build_item_and_refuses_an_unknown_one(run):
    before = (run / "files" / "report.md").read_bytes()
    p = vg("decide", "--run", run, "--item", "paper", "--approve", "--by", "story scholar")
    assert p.returncode == 0, p.stdout + p.stderr
    p = vg("decide", "--run", run, "--item", "slides/slides.md:{{num:n_teams}}", "--hold",
           "--by", "story scholar")
    assert p.returncode == 0, p.stdout + p.stderr
    data = results(run)
    assert [(d["item"], d["decision"]) for d in data["decisions"]] == [
        ("paper", "approved"), ("slides/slides.md:{{num:n_teams}}", "held")]
    assert all(d["by"] == "story scholar" and d["run_id"] == run.name for d in data["decisions"])
    decided = (run / "report_decided.md").read_text(encoding="utf-8")
    total = len(data["items"])
    assert "**1 approved, 1 held, %d undecided.**" % (total - 2) in decided
    p = vg("decide", "--run", run, "--item", "builds/paper/v009.html", "--approve",
           "--by", "story scholar")
    assert p.returncode != 0 and "unknown item" in p.stderr
    assert len(results(run)["decisions"]) == 2
    assert (run / "files" / "report.md").read_bytes() == before


# ---------------------------------------------------------------- data stream (W11)

DATA_FIX = ROOT / "fixtures" / "data"
SAMPLE = ROOT.parent / "examples" / "sample_project"
DATA_GRAPH = "graphs/data.yaml"
DATA_NUMBERS = ["alpha", "mean_income_k_north", "n_analytic", "p_income_k", "slope_income_k"]
# The AI's changes and the parameter the AI set, which the record of the AI's file edits
# names in the seeded files (Track V, step V2).
SEEDED_DATA_AI = [("e01", "change"), ("e02", "change"), ("params.yaml:fig_width", "parameter")]
SEEDED_DATA_PROBLEMS = {"model_record_model.json", "raw_survey.csv", "s1_clean.py",
                        "s1_clean.py:L42", "s2_describe.py", "s3_model.py",
                        "table_descriptives.csv"}
# The empty record of the AI's work, for a report rerun on made-up step outputs.
NO_AI_WORK = {"record_given": True, "changes": [], "params": [], "scripts": {}, "numbers": {}}
SAMPLE_NUMBERS = ["definition.distinct", "definition.top_pct", "definition.top_word", "model",
                  "n_per_condition", "none.distinct", "none.top_pct", "none.top_word",
                  "question", "temperature"]


def run_data(folder, inputs):
    p = vg("run", DATA_GRAPH, "--run", folder, "--inputs", inputs)
    assert p.returncode == 0, p.stdout + p.stderr
    return folder


@pytest.fixture(scope="module")
def seeded_data(tmp_path_factory):
    return run_data(tmp_path_factory.mktemp("items") / "seeded_data", DATA_FIX / "seeded")


@pytest.fixture(scope="module")
def clean_data(tmp_path_factory):
    return run_data(tmp_path_factory.mktemp("items") / "clean_data", DATA_FIX / "clean")


@pytest.fixture(scope="module")
def sample_data(tmp_path_factory):
    """The A4 data command, run on the sample project in a temp run folder. Its top-level
    files are copied as the data handoff copies a flat project, so a sample built in
    place keeps its builds/ folder out of the run."""
    base = tmp_path_factory.mktemp("items")
    inputs = base / "sample_inputs"
    inputs.mkdir()
    for path in sorted(SAMPLE.iterdir()):
        if path.is_file() and not path.is_symlink():
            shutil.copyfile(str(path), str(inputs / path.name))
    return run_data(base / "demo_sample", inputs)


def numbers_check(rd):
    return json.loads((rd / "files" / "numbers_check.json").read_text(encoding="utf-8"))


def test_the_seeded_data_run_lists_its_numbers_then_one_item_for_each_problem(seeded_data):
    data = results(seeded_data)
    assert data["stream"] == "data" and data["decisions"] == []
    items = data["items"]
    assert [it["id"] for it in items[:5]] == DATA_NUMBERS
    assert all(it["kind"] == "number" for it in items[:5])
    assert [(it["id"], it["kind"]) for it in items[5:8]] == SEEDED_DATA_AI
    rest = items[8:]
    assert {it["id"] for it in rest} == SEEDED_DATA_PROBLEMS
    assert len(rest) == len(SEEDED_DATA_PROBLEMS)
    assert all(it["kind"] == "finding" for it in rest)
    assert all(it["needs_decision"] is True for it in items)
    for it in items:
        assert list(it) == ITEM_KEYS, it["id"]
        for f in it["findings"]:
            assert list(f) == FINDING_KEYS, it["id"]


def test_the_seeded_slope_carries_its_blocking_check_numbers_finding(seeded_data):
    items = {it["id"]: it for it in results(seeded_data)["items"]}
    slope = items["slope_income_k"]
    assert [(f["check"], f["severity"]) for f in slope["findings"]] == [
        ("check_numbers", "blocking")]
    assert slope["findings"][0]["message"] == "manuscript number does not come from the process"
    for key in DATA_NUMBERS[:4]:
        assert items[key]["findings"] == [], key


def test_every_blocking_or_warning_data_finding_sits_in_exactly_one_item(seeded_data):
    problems = problems_of(run_findings(seeded_data))
    assert problems
    carried = Counter()
    for it in results(seeded_data)["items"]:
        carried.update(as_tuple(f) for f in it["findings"])
    assert carried == Counter(as_tuple(f) for f in problems)
    infos = {as_tuple(f) for f in run_findings(seeded_data) if f["severity"] == "info"}
    assert not infos & set(carried)


def test_a_number_summary_gives_its_value_the_rerun_and_its_source(seeded_data):
    items = {it["id"]: it for it in results(seeded_data)["items"]}
    for row in numbers_check(seeded_data):
        assert items[row["key"]]["summary"] == "%s = %s, rerun %s, from %s" % (
            row["key"], row["value"], row["replayed"], row["from"])
    assert items["alpha"]["summary"] == "alpha = 0.05, rerun 0.05, from params_record_model.csv"


def test_the_seeded_data_score_holds_and_the_run_still_replays(seeded_data, tmp_path):
    rd = tmp_path / seeded_data.name
    shutil.copytree(str(seeded_data), str(rd))
    p = vg("score", "--run", rd, "--truth", DATA_FIX / "seeded" / "truth.yaml")
    assert p.returncode == 0, p.stdout + p.stderr
    score = json.loads((rd / "score.json").read_text(encoding="utf-8"))
    assert score["faults"] == 9 and len(score["caught"]) == 9 and score["missed"] == []
    assert len(score["extra_findings"]) == 2
    v = vg("verify", "--run", rd)
    assert v.returncode == 0 and "FAIL" not in v.stdout, v.stdout


def test_the_clean_data_run_lists_its_five_numbers_and_its_ai_change_with_no_findings(clean_data):
    items = results(clean_data)["items"]
    assert [(it["id"], it["kind"]) for it in items] == (
        [(k, "number") for k in DATA_NUMBERS] + [("e01", "change")])
    assert all(it["findings"] == [] for it in items)
    # only the number from the AI's change and the change itself wait for the scholar
    assert [it["id"] for it in items if it["needs_decision"]] == ["mean_income_k_north", "e01"]


def test_the_sample_project_lists_its_ten_numbers_and_nothing_else(sample_data):
    items = results(sample_data)["items"]
    assert [(it["id"], it["kind"]) for it in items] == [(k, "number") for k in SAMPLE_NUMBERS]
    assert all(it["findings"] == [] and it["needs_decision"] is True for it in items)
    assert problems_of(run_findings(sample_data)) == []


def test_a_number_the_rerun_did_not_give_shows_none(clean_data, tmp_path):
    """A number whose source the replay did not produce has no rerun value. Its row
    says so, and the finding on its key moves onto the row."""
    items = rerun_report(clean_data, tmp_path / clean_data.name, {
        "numbers_check.json": [
            {"key": "n", "value": "12", "from": "out.csv", "replayed": None, "ok": False}],
        "ai_work.json": NO_AI_WORK}, [
        finding("check_numbers", "blocking", "n", "source output was not produced by the replay",
                "from: out.csv"),
        finding("check_raw", "info", "raw.csv", "Only a note.")])
    assert items == [{
        "id": "n",
        "kind": "number",
        "summary": "n = 12, rerun (none), from out.csv",
        "findings": [{"check": "check_numbers", "severity": "blocking",
                      "message": "source output was not produced by the replay",
                      "evidence": "from: out.csv"}],
        "needs_decision": True,
    }]


# ---------------------------------------------------------------- prose stream (W16)

PROSE_FIX = ROOT / "fixtures" / "prose"
PROSE_GRAPH = "graphs/prose.yaml"
SEEDED_CHANGES = ["c%02d" % n for n in range(1, 10)]
CLEAN_CHANGES = ["c%02d" % n for n in range(1, 6)]


def run_prose(folder, inputs):
    # The prose procedure asks no model since version 0.3 (Track V, step V1).
    p = vg("run", PROSE_GRAPH, "--run", folder, "--inputs", inputs)
    assert p.returncode == 0, p.stdout + p.stderr
    return folder


@pytest.fixture(scope="module")
def seeded_prose(tmp_path_factory):
    return run_prose(tmp_path_factory.mktemp("items") / "seeded_prose", PROSE_FIX / "seeded")


@pytest.fixture(scope="module")
def clean_prose(tmp_path_factory):
    return run_prose(tmp_path_factory.mktemp("items") / "clean_prose", PROSE_FIX / "clean")


def changes(rd):
    return json.loads((rd / "files" / "changes.json").read_text(encoding="utf-8"))


def test_the_seeded_prose_run_lists_its_changes_then_one_item_for_each_problem(seeded_prose):
    data = results(seeded_prose)
    assert data["stream"] == "prose" and data["decisions"] == []
    items = data["items"]
    assert [it["id"] for it in items[:9]] == SEEDED_CHANGES
    assert all(it["kind"] == "change" for it in items[:9])
    assert [(it["id"], it["kind"]) for it in items[9:]] == [("r08", "finding")]
    for it in items:
        assert list(it) == ITEM_KEYS, it["id"]
        for f in it["findings"]:
            assert list(f) == FINDING_KEYS, it["id"]


def test_only_the_authors_own_edit_needs_no_decision(seeded_prose):
    needs = {it["id"]: it["needs_decision"] for it in results(seeded_prose)["items"]}
    assert [k for k, v in needs.items() if v is False] == ["c07"]
    assert all(v is True for k, v in needs.items() if k != "c07")


def test_every_blocking_or_warning_prose_finding_sits_in_exactly_one_item(seeded_prose):
    problems = problems_of(run_findings(seeded_prose))
    assert problems
    carried = Counter()
    for it in results(seeded_prose)["items"]:
        carried.update(as_tuple(f) for f in it["findings"])
    assert carried == Counter(as_tuple(f) for f in problems)
    infos = {as_tuple(f) for f in run_findings(seeded_prose) if f["severity"] == "info"}
    assert not infos & set(carried)
    # Each change carries exactly the problems found on its own id.
    for it in results(seeded_prose)["items"]:
        assert [as_tuple(f) for f in it["findings"]] == [
            as_tuple(f) for f in problems if f["item"] == it["id"]], it["id"]


def test_the_seeded_changes_carry_their_planted_problems(seeded_prose):
    items = {it["id"]: it for it in results(seeded_prose)["items"]}
    checks = {k: sorted(f["check"] for f in it["findings"]) for k, it in items.items()}
    assert checks["c05"] == ["rationale_coverage"]
    for cid in ("c03", "c04", "c06", "c08"):
        assert checks[cid] == ["content_handoff"], cid
    assert checks["c09"] == ["rationale_coverage"]
    assert checks["r08"] == ["rationale_coverage"]
    # The move and the scholar's own change carry no problem.
    assert checks["c01"] == [] and checks["c07"] == []


def test_a_change_summary_gives_its_kind_and_its_sentence_cut_to_120(seeded_prose, clean_prose):
    for rd in (seeded_prose, clean_prose):
        items = {it["id"]: it for it in results(rd)["items"]}
        for c in changes(rd):
            text = c["before"] if c["kind"] == "delete" else c["after"]
            assert items[c["id"]]["summary"] == "%s: %s" % (c["kind"], text[:120]), c["id"]
    clean = {it["id"]: it for it in results(clean_prose)["items"]}
    assert clean["c04"]["summary"] == ("delete: Agencies that adopted the format did so for a "
                                       "variety of different reasons, and those reasons varied "
                                       "a great deal.")
    assert clean["c05"]["summary"] == "insert: The next section turns to the interview protocol itself."


def test_decide_refuses_the_authors_own_edit(seeded_prose, tmp_path):
    rd = tmp_path / seeded_prose.name
    shutil.copytree(str(seeded_prose), str(rd))
    p = vg("decide", "--run", rd, "--item", "c07", "--approve", "--by", "story scholar")
    assert p.returncode != 0 and "needs no decision" in p.stderr
    assert results(rd)["decisions"] == []
    p = vg("decide", "--run", rd, "--item", "c05", "--hold", "--by", "story scholar")
    assert p.returncode == 0, p.stdout + p.stderr
    assert [(d["item"], d["decision"]) for d in results(rd)["decisions"]] == [("c05", "held")]


def test_the_seeded_prose_score_holds_and_the_run_still_replays(seeded_prose, tmp_path):
    rd = tmp_path / seeded_prose.name
    shutil.copytree(str(seeded_prose), str(rd))
    p = vg("score", "--run", rd, "--truth", PROSE_FIX / "seeded" / "truth.yaml")
    assert p.returncode == 0, p.stdout + p.stderr
    score = json.loads((rd / "score.json").read_text(encoding="utf-8"))
    assert score["faults"] == 7 and len(score["caught"]) == 7 and score["missed"] == []
    assert score["extra_findings"] == []
    v = vg("verify", "--run", rd)
    assert v.returncode == 0 and "FAIL" not in v.stdout, v.stdout


def test_the_clean_prose_run_lists_only_its_five_changes_with_no_findings(clean_prose):
    items = results(clean_prose)["items"]
    assert [(it["id"], it["kind"]) for it in items] == [(k, "change") for k in CLEAN_CHANGES]
    assert all(it["findings"] == [] and it["needs_decision"] is True for it in items)


def test_a_long_changed_sentence_is_cut_to_120_characters(clean_prose, tmp_path):
    """A made-up prose run with a long inserted sentence, a deleted one, and a problem
    on the inserted change's id, which moves onto that change's row."""
    long_sentence = "Word " * 40
    items = rerun_report(clean_prose, tmp_path / clean_prose.name, {
        "changes.json": [
            {"id": "c01", "kind": "insert", "before": "", "after": long_sentence, "moved": False},
            {"id": "c02", "kind": "delete", "before": "Gone now.", "after": "", "moved": False}],
        "ai_changes.json": [
            {"id": "c01", "kind": "insert", "before": "", "after": long_sentence, "moved": False,
             "record_id": "r01", "record_kind": "insert", "rationale": ""}],
        "author_changes.json": [{"id": "c02", "kind": "delete", "before": "Gone now.", "after": "",
                                 "moved": False}],
        "handoff.json": []}, [
        finding("rationale_coverage", "blocking", "c01", "AI change with no recorded reason"),
        finding("exclude_author", "info", "c02", "the scholar's own change, listed not checked")])
    assert items == [
        {"id": "c01", "kind": "change", "summary": "insert: " + long_sentence[:120],
         "findings": [{"check": "rationale_coverage", "severity": "blocking",
                       "message": "AI change with no recorded reason", "evidence": ""}],
         "needs_decision": True},
        {"id": "c02", "kind": "change", "summary": "delete: Gone now.", "findings": [],
         "needs_decision": False},
    ]


# ---------------------------------------------------------------- items from the schema (Step C10)

STREAMS = ("prose", "citations", "data", "build")
# The keys of the citations items since the references procedure 0.2 (Track C2), and the
# keys W gave the other three streams' items.
CITATION_RESULTS = ["id", "citekey", "sentence", "origin", "origin_evidence", "reference", "lookup",
                    "existence", "record", "reason", "reason_source", "quotes", "quote_in_source",
                    "access", "source_file", "notes", "needs_decision"]
# Track P added sessions to the prose, citations, and build items, left out of an item
# with no session.
RESULTS_KEYS = {"citations": CITATION_RESULTS + ["sessions"], "build": ITEM_KEYS + ["sessions"],
                "data": ITEM_KEYS, "prose": ITEM_KEYS + ["sessions"]}
SELFTEST = ROOT / "fixtures" / "selftest"


def stream_schema(stream):
    return yaml.safe_load((ROOT / "schemas" / ("%s.yaml" % stream)).read_text(encoding="utf-8"))


@pytest.mark.parametrize("stream", STREAMS)
def test_each_schema_lists_the_fields_its_results_items_carry(stream):
    assert stream_schema(stream)["results"] == RESULTS_KEYS[stream]
    assert vg("check", "graphs/%s.yaml" % stream).returncode == 0


@pytest.mark.parametrize("which", ["seeded_build", "clean_build", "seeded_data", "sample_data",
                                   "seeded_prose", "clean_prose"])
def test_the_items_are_the_schemas_item_rows_in_order(which, request):
    rd = request.getfixturevalue(which)
    fields = json.loads((rd / "files" / "fields.json").read_text(encoding="utf-8"))
    keys = stream_schema(results(rd)["stream"])["results"]
    assert results(rd)["items"] == [{k: row[k] for k in keys if k in row} for row in fields["items"]]


def test_the_results_writer_names_no_stream():
    mod = load_vg()
    for gone in ("items_citations", "items_build", "items_data", "items_prose", "STREAM_ITEMS",
                 "CITATION_ITEM_FIELDS", "problem_items"):
        assert not hasattr(mod, gone), gone
    source = inspect.getsource(mod.write_results) + inspect.getsource(mod.result_items)
    for stream in STREAMS:
        assert '"%s"' % stream not in source and "'%s'" % stream not in source, stream


def test_a_selftest_run_writes_no_results_file(tmp_path):
    rd = tmp_path / "selftest_run"
    p = vg("run", "graphs/selftest.yaml", "--run", rd, "--inputs", SELFTEST,
           "--judge", "recorded:%s" % (SELFTEST / "recorded_judge.json"))
    assert p.returncode == 0, p.stdout + p.stderr
    assert (rd / "files" / "report.md").is_file()
    assert not (rd / "files" / "fields.json").exists()
    assert not (rd / "results.json").exists()


def made_up_run(tmp_path, items, schema_fields, results_list):
    """A run folder holding only a manifest, a fields.json, and a pinned schema copy in its
    exit step's code folder."""
    rd = tmp_path / "made_up"
    (rd / "files").mkdir(parents=True)
    (rd / "code" / "03_report").mkdir(parents=True)
    (rd / "manifest.json").write_text(json.dumps({
        "stream": "made_up", "graph": {"path": "graphs/made_up.yaml", "version": 0.3},
        "inputs": {"a.txt": "sha256:00"}}), encoding="utf-8")
    (rd / "files" / "fields.json").write_text(json.dumps({
        "schema": {"stream": "made_up", "version": 1}, "run": {}, "items": items, "tables": {}}),
        encoding="utf-8")
    (rd / "code" / "03_report" / "schema.yaml").write_text(yaml.safe_dump({
        "stream": "made_up", "version": 1, "item": "a row", "id": "id",
        "fields": schema_fields, "results": results_list}), encoding="utf-8")
    return rd


def test_results_fields_are_taken_in_the_schemas_order_and_a_not_run_value_is_left_empty(tmp_path):
    schema_fields = {"id": {"type": "str"}, "note": {"type": "str"}, "tags": {"type": "list"},
                     "ok": {"type": "bool"}, "needs_decision": {"type": "bool"},
                     "cell": {"type": "str"}}
    skipped = {"not_run": "a step was skipped"}
    rd = made_up_run(tmp_path, [
        {"id": "a1", "note": skipped, "tags": skipped, "ok": skipped, "needs_decision": True,
         "cell": "shown"},
        {"id": "a2", "note": "seen", "tags": ["x"], "ok": True, "needs_decision": False,
         "cell": "shown"}], schema_fields, ["id", "ok", "note", "tags", "needs_decision"])
    written = load_vg().write_results(str(rd))
    assert written == results(rd)
    assert list(written) == ["schema", "schema_version", "stream", "run_id", "procedure_version",
                             "inputs", "items", "decisions"]
    assert written["schema"] == "verification-results" and written["schema_version"] == 1
    assert written["run_id"] == "made_up" and written["procedure_version"] == 0.3
    assert written["items"] == [
        {"id": "a1", "ok": None, "note": "", "tags": [], "needs_decision": True},
        {"id": "a2", "ok": True, "note": "seen", "tags": ["x"], "needs_decision": False}]
    assert [list(it) for it in written["items"]] == [["id", "ok", "note", "tags", "needs_decision"]] * 2


def test_a_run_without_fields_json_gets_no_results_file(tmp_path):
    rd = made_up_run(tmp_path, [], {"id": {"type": "str"}}, ["id"])
    (rd / "files" / "fields.json").unlink()
    assert load_vg().write_results(str(rd)) is None
    assert not (rd / "results.json").exists()
