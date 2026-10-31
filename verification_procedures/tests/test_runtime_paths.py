"""The runtime's four paths that had no test (Table A5): verify reporting a failed
replay, score reporting a missed fault, the refusal to run a step after its graph
file changed, and advise. All on the self-test graph and fixture, apart from
advise, which reads the citations graph."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
VG = [sys.executable, str(ROOT / "vg.py")]
JUDGE = "recorded:fixtures/selftest/recorded_judge.json"


def run(*args):
    return subprocess.run(VG + [str(a) for a in args], cwd=ROOT, capture_output=True, text=True)


def selftest_run(rd, graph="graphs/selftest.yaml"):
    p = run("run", graph, "--run", rd, "--inputs", "fixtures/selftest", "--judge", JUDGE)
    assert p.returncode == 0, p.stdout + p.stderr
    return rd


def verdict_for(rd, node):
    data = json.loads((rd / "verify.json").read_text())
    return next(s["verdict"] for s in data["steps"] if s["node"] == node)


# ---------------------------------------------------------------- failed replay

def test_verify_reports_outputs_differ(tmp_path):
    rd = selftest_run(tmp_path / "run")
    script = rd / "code" / "01_list_items" / "list_items.py"
    text = script.read_text()
    changed = text.replace("words = _lib.read_text(\"words.txt\").split()",
                           "words = _lib.read_text(\"words.txt\").split() + [\"extra\"]")
    assert changed != text
    script.write_text(changed)
    p = run("verify", "--run", rd)
    assert p.returncode == 1, p.stdout + p.stderr
    line = next(ln for ln in p.stdout.splitlines() if "list_items" in ln)
    assert "FAIL outputs differ" in line
    assert "items.json" in line and "count.json" in line
    verdict = verdict_for(rd, "list_items")
    assert verdict.startswith("FAIL outputs differ")
    assert "items.json" in verdict and "count.json" in verdict


def test_verify_reports_changed_input(tmp_path):
    rd = selftest_run(tmp_path / "run")
    (rd / "files" / "words.txt").write_text("red green table blue purple\n")
    p = run("verify", "--run", rd)
    assert p.returncode == 1, p.stdout + p.stderr
    assert "FAIL input words.txt changed after step ran" in p.stdout
    assert verdict_for(rd, "list_items") == "FAIL input words.txt changed after step ran"


def test_verify_reports_replay_error(tmp_path):
    rd = selftest_run(tmp_path / "run")
    (rd / "code" / "01_list_items" / "list_items.py").write_text(
        "raise RuntimeError('broken on purpose')\n")
    p = run("verify", "--run", rd)
    assert p.returncode == 1, p.stdout + p.stderr
    assert "FAIL replay errored" in p.stdout
    assert verdict_for(rd, "list_items") == "FAIL replay errored"


# ---------------------------------------------------------------- missed fault

def test_score_reports_missed_fault(tmp_path):
    rd = selftest_run(tmp_path / "run")
    truth = yaml.safe_load((ROOT / "fixtures/selftest/truth.yaml").read_text())
    truth["faults"].append({"id": "F2", "check": "judge_items", "item": "w9"})
    tpath = tmp_path / "truth.yaml"
    tpath.write_text(yaml.safe_dump(truth))
    p = run("score", "--run", rd, "--truth", tpath)
    assert p.returncode == 1, p.stdout + p.stderr
    printed = json.loads(p.stdout.split(" extras=")[0])
    assert printed["missed"] == ["F2"]
    result = json.loads((rd / "score.json").read_text())
    assert result["caught"] == ["F1"]
    assert result["missed"] == ["F2"]
    assert result["recall"] < 1


def test_score_counts_a_note_of_the_same_check_and_item_as_caught(tmp_path):
    """Track C2 plan choice 7. A planted fault is caught when any finding of any severity
    names its check and item, so a report that ranks nothing is still measured. A note
    that matches no fault is not counted among the extras, as before."""
    rd = tmp_path / "made_up"
    (rd / "files").mkdir(parents=True)
    (rd / "files" / "findings.json").write_text(json.dumps([
        {"check": "verify_quote", "severity": "info", "item": "r04", "message": "a note", "evidence": ""},
        {"check": "verify_quote", "severity": "info", "item": "r09", "message": "another", "evidence": ""},
        {"check": "check_existence", "severity": "warning", "item": "x", "message": "loud", "evidence": ""},
    ]))
    tpath = tmp_path / "truth.yaml"
    tpath.write_text(yaml.safe_dump({"faults": [{"id": "F1", "check": "verify_quote", "item": "r04"}]}))
    p = run("score", "--run", rd, "--truth", tpath)
    assert p.returncode == 0, p.stdout + p.stderr
    result = json.loads((rd / "score.json").read_text())
    assert result["caught"] == ["F1"] and result["missed"] == [] and result["recall"] == 1.0
    assert [(x["check"], x["item"]) for x in result["extra_findings"]] == [("check_existence", "x")]


# ---------------------------------------------------------------- changed graph

def test_step_refused_after_graph_changed(tmp_path):
    graph = tmp_path / "selftest.yaml"
    shutil.copy2(ROOT / "graphs" / "selftest.yaml", graph)
    rd = selftest_run(tmp_path / "run", graph=graph)
    before = sorted(p.name for p in (rd / "records").iterdir())
    with open(graph, "a") as f:
        f.write("# one more comment line\n")
    p = run("step", "--run", rd, "--node", "report")
    assert p.returncode != 0
    assert "graph changed since run started; start a new run" in p.stdout + p.stderr
    assert sorted(p.name for p in (rd / "records").iterdir()) == before


# ---------------------------------------------------------------- advise

def test_advise_prints_edges_touching_the_step():
    p = run("advise", "graphs/citations.yaml", "--at", "locate_passage")
    assert p.returncode == 0, p.stdout + p.stderr
    lines = p.stdout.splitlines()
    assert "- gather_reason_and_quote -> locate_passage: Copy the passage from the source text" in p.stdout
    assert any(ln.startswith("- locate_passage -> verify_quote:") for ln in lines)
    assert "    avoid: Giving a verdict, a rating, or a fix, which the scholar alone decides." in lines
    edge_lines = [ln for ln in lines if ln.startswith("- ")]
    assert edge_lines
    for ln in edge_lines:
        ends = ln[2:].split(":", 1)[0].split(" -> ")
        assert "locate_passage" in ends, ln
    # every pitfall follows an edge line, so each avoid line belongs to a touching edge
    for ln in lines:
        assert ln.startswith("- ") or ln.startswith("    avoid: "), ln
    graph = yaml.safe_load((ROOT / "graphs" / "citations.yaml").read_text())
    touching = [e for e in graph["edges"] if "locate_passage" in (e["from"], e["to"])]
    assert len(edge_lines) == len(touching)
    for e in touching:
        for pit in e["pitfalls"]:
            assert "    avoid: " + pit in lines
