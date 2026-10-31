"""Quick runs, the light working check (Step C12).

Each registry entry names its quick steps, the mechanical steps cheap enough to run at the
end of every turn. `vg.py run <id> --quick` starts the run as usual, with "quick": true in
the manifest, runs the quick steps in order, stops at the first contract failure, appends
run_quick_finished to the trail, and prints the blocking findings and warnings of those
steps. It writes no report and no results file. `vg.py procedures --check` checks the
quick-step rule. Nothing here calls a model or the network, and no quick step is a
judgment step, so no run here takes --judge.
"""
import copy
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
VG = [sys.executable, str(ROOT / "vg.py")]
STREAMS = ["prose", "citations", "data", "build"]
QUICK = {
    "prose": ["pin_versions", "diff_changes", "exclude_author", "content_handoff",
              "rationale_coverage"],
    "citations": ["pin_document", "extract_citations", "match_references", "read_origin"],
    "data": ["inventory", "check_raw", "check_params", "check_docs"],
    "build": ["read_map", "check_ledger", "check_hardcoding", "check_ai_touch", "check_prefs"],
}
SUMMARY = re.compile(r"^quick: (\d+) blocking, (\d+) warnings from (\d+) steps$")


def vg(*args):
    env = dict(os.environ, VG_OFFLINE="1")
    return subprocess.run(VG + [str(a) for a in args], cwd=str(ROOT), capture_output=True,
                          text=True, env=env)


def load_vg():
    spec = importlib.util.spec_from_file_location("vg_for_quick", ROOT / "vg.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def registry():
    return yaml.safe_load((ROOT / "registry.yaml").read_text(encoding="utf-8"))


def quick_run(stream, run_dir, inputs=None):
    inputs = inputs or ROOT / "fixtures" / stream / "seeded"
    return vg("run", stream, "--quick", "--run", run_dir, "--inputs", inputs)


def nodes_of(rd):
    return [json.loads(p.read_text())["node"] for p in sorted((rd / "records").iterdir())]


def trail_events(rd):
    lines = (rd / "trail.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line)["event"] for line in lines]


def loud_counts(rd):
    """Blocking findings and warnings in the findings files the run's steps produced."""
    blocking = warnings = 0
    for p in sorted((rd / "records").iterdir()):
        rec = json.loads(p.read_text())
        for name in rec["outputs"]:
            if name.startswith("findings_"):
                for f in json.loads((rd / "files" / name).read_text()):
                    blocking += f["severity"] == "blocking"
                    warnings += f["severity"] == "warning"
    return blocking, warnings


@pytest.fixture(scope="module")
def quick_runs(tmp_path_factory):
    base = tmp_path_factory.mktemp("quick")
    out = {}
    for stream in STREAMS:
        rd = base / ("%s_seeded" % stream)
        p = quick_run(stream, rd)
        out[stream] = (rd, p)
    return out


# ---------------------------------------------------------------- the registry's quick steps

def test_the_registry_names_each_streams_quick_steps():
    assert {e["id"]: e["quick_steps"] for e in registry()["procedures"]} == QUICK


# ---------------------------------------------------------------- quick runs on the seeded fixtures

@pytest.mark.parametrize("stream", STREAMS)
def test_a_quick_run_runs_exactly_its_quick_steps(quick_runs, stream):
    rd, p = quick_runs[stream]
    assert p.returncode == 0, p.stdout + p.stderr
    assert nodes_of(rd) == QUICK[stream]
    manifest = json.loads((rd / "manifest.json").read_text())
    assert manifest["quick"] is True
    assert manifest["executors"] == {"judge": None, "second": None}
    assert manifest["graph"]["path"] == "graphs/%s.yaml" % stream


@pytest.mark.parametrize("stream", STREAMS)
def test_a_quick_run_writes_no_report_and_no_results_file(quick_runs, stream):
    rd, _ = quick_runs[stream]
    assert not (rd / "files" / "report.md").exists()
    assert not (rd / "files" / "fields.json").exists()
    assert not (rd / "files" / "steps.json").exists()
    assert not (rd / "results.json").exists()


@pytest.mark.parametrize("stream", STREAMS)
def test_a_quick_run_prints_its_findings_and_ends_its_trail(quick_runs, stream):
    rd, p = quick_runs[stream]
    last = p.stdout.strip().splitlines()[-1]
    m = SUMMARY.match(last)
    assert m, p.stdout
    assert (int(m.group(1)), int(m.group(2))) == loud_counts(rd)
    assert int(m.group(3)) == len(QUICK[stream])
    events = trail_events(rd)
    assert events[0] == "run_initialized"
    assert events[-1] == "run_quick_finished"
    assert "run_finished" not in events


@pytest.mark.parametrize("stream", STREAMS)
def test_verify_replays_every_step_a_quick_run_ran(quick_runs, stream):
    rd, _ = quick_runs[stream]
    v = vg("verify", "--run", rd)
    assert v.returncode == 0, v.stdout + v.stderr
    lines = v.stdout.strip().splitlines()
    assert len(lines) == len(QUICK[stream])
    assert all(line.endswith("replay matches") for line in lines), v.stdout


def test_the_prose_quick_run_reports_the_silent_change_as_blocking(quick_runs):
    rd, p = quick_runs["prose"]
    found = json.loads((rd / "files" / "findings_rationale_coverage.json").read_text())
    assert any(f["item"] == "c05" and f["severity"] == "blocking" for f in found), found
    assert int(SUMMARY.match(p.stdout.strip().splitlines()[-1]).group(1)) >= 1


def test_a_full_run_is_not_marked_quick(tmp_path):
    rd = tmp_path / "full"
    p = vg("run", "build", "--run", rd, "--inputs", ROOT / "fixtures" / "build" / "seeded")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "quick" not in json.loads((rd / "manifest.json").read_text())
    assert (rd / "results.json").is_file()


def test_a_quick_run_stops_at_the_first_contract_failure(tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "project.tar").write_bytes(b"this is not a tar file\n")
    (inputs / "session_writes.jsonl").write_text("", encoding="utf-8")
    rd = tmp_path / "broken"
    p = quick_run("build", rd, inputs)
    assert p.returncode == 1, p.stdout + p.stderr
    assert nodes_of(rd) == ["read_map"]
    events = trail_events(rd)
    assert "run_stopped" in events and events[-1] == "run_quick_finished"
    assert p.stdout.strip().splitlines()[-1] == "quick: 0 blocking, 0 warnings from 1 steps"
    assert not (rd / "results.json").exists()


def test_a_quick_run_takes_a_registered_id(tmp_path):
    rd = tmp_path / "by_path"
    p = vg("run", "graphs/build.yaml", "--quick", "--run", rd,
           "--inputs", ROOT / "fixtures" / "build" / "seeded")
    assert p.returncode != 0
    assert "registered procedure id" in p.stderr
    assert not rd.exists()


# ---------------------------------------------------------------- the quick-step rule

def problems_of(reg):
    return load_vg().check_registry(reg)


def synthetic():
    return copy.deepcopy(registry())


def entry(reg, pid):
    return next(e for e in reg["procedures"] if e["id"] == pid)


def test_the_real_quick_steps_follow_the_rule():
    assert problems_of(registry()) == []


def test_quick_steps_that_leave_out_a_needed_step_are_refused():
    reg = synthetic()
    entry(reg, "prose")["quick_steps"] = ["pin_versions", "diff_changes", "content_handoff"]
    found = problems_of(reg)
    assert ("procedure prose: quick step content_handoff has no unconditional edge from an "
            "earlier quick step") in found
    assert ("procedure prose: quick step content_handoff reads ai_changes.json, which is "
            "neither a procedure input nor made by an earlier quick step") in found


def test_quick_steps_holding_a_judgment_step_are_refused():
    # The prose and data procedures have no judgment step since Track V (steps V1 and V2), so
    # the references procedure's one judgment step, locate_passage, stands in, with the steps
    # before it in the graph's order.
    reg = synthetic()
    entry(reg, "citations")["quick_steps"] = QUICK["citations"] + ["fetch_metadata", "check_existence", "pin_sources", "gather_reason_and_quote", "locate_passage"]
    assert "procedure citations: quick step locate_passage is a judgment step" in problems_of(reg)


def test_quick_steps_holding_the_exit_are_refused():
    reg = synthetic()
    entry(reg, "build")["quick_steps"] = QUICK["build"] + ["report"]
    assert "procedure build: quick step report is the exit step" in problems_of(reg)


def test_quick_steps_out_of_the_graphs_order_are_refused():
    reg = synthetic()
    entry(reg, "data")["quick_steps"] = ["inventory", "check_params", "check_raw", "check_docs"]
    assert ("procedure data: quick step check_raw is listed out of the graph's order"
            in problems_of(reg))


def test_a_quick_step_that_is_not_a_step_of_the_graph_is_refused():
    reg = synthetic()
    entry(reg, "citations")["quick_steps"] = ["pin_document", "lunch"]
    assert ("procedure citations: quick step lunch is not a step of graphs/citations.yaml"
            in problems_of(reg))


def test_quick_steps_that_do_not_start_at_the_entry_are_refused():
    reg = synthetic()
    entry(reg, "citations")["quick_steps"] = ["extract_citations", "match_references"]
    assert ("procedure citations: quick step extract_citations has no unconditional edge from "
            "an earlier quick step") in problems_of(reg)


def test_a_quick_step_reached_only_by_a_conditional_edge_is_refused():
    reg = synthetic()
    entry(reg, "build")["quick_steps"] = ["read_map", "check_ledger", "rebuild"]
    assert ("procedure build: quick step rebuild has no unconditional edge from an earlier "
            "quick step") in problems_of(reg)


def test_procedures_check_names_quick_step_problems(tmp_path, capsys):
    reg = synthetic()
    entry(reg, "citations")["quick_steps"] = QUICK["citations"] + ["fetch_metadata", "check_existence", "pin_sources", "gather_reason_and_quote", "locate_passage"]
    path = tmp_path / "registry.yaml"
    path.write_text(yaml.safe_dump(reg, sort_keys=False), encoding="utf-8")
    mod = load_vg()
    mod.REGISTRY = str(path)
    assert mod.main(["procedures", "--check"]) == 1
    assert "procedure citations: quick step locate_passage is a judgment step" in capsys.readouterr().out
