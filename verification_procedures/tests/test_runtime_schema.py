"""Runtime support for schemas (Step C5): the manifest pins the schema, the runtime writes
files/steps.json before the exit step, the exit step's code folder holds _report.py and
schema.yaml, and verify replays each step's own script, picked by its node name."""
import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
VG = [sys.executable, str(ROOT / "vg.py")]
sys.path.insert(0, str(ROOT))
import vg  # noqa: E402

SCHEMA = {
    "stream": "selftest",
    "version": 3,
    "item": "one word",
    "id": "id",
    "fields": {
        "id": {"type": "str", "filled_by": ["list_items"]},
        "word": {"type": "str", "filled_by": ["list_items"]},
        "is_color": {"type": "bool", "filled_by": ["judge_items"]},
        "big": {"type": "str", "required": False, "filled_by": ["skipped_branch"]},
    },
    "report": {
        "title": "Self-test",
        "intro": "Words.",
        "sections": [{"heading": "Words", "parts": [
            {"kind": "table", "rows": "items",
             "columns": [{"header": "Word", "value": "{word}"}]}]}],
    },
}


def run(*args):
    return subprocess.run(VG + list(args), cwd=ROOT, capture_output=True, text=True)


def schema_graph(tmp_path):
    """A copy of the self-test graph that names a synthetic schema by its absolute path."""
    schema = tmp_path / "selftest_schema.yaml"
    schema.write_text(yaml.safe_dump(SCHEMA, sort_keys=False))
    g = yaml.safe_load((ROOT / "graphs" / "selftest.yaml").read_text())
    g["schema"] = str(schema)
    graph = tmp_path / "selftest_with_schema.yaml"
    graph.write_text(yaml.safe_dump(g, sort_keys=False))
    return graph, schema


def run_selftest(tmp_path, graph):
    rd = tmp_path / "run"
    p = run("run", str(graph), "--run", str(rd), "--inputs", "fixtures/selftest",
            "--judge", "recorded:fixtures/selftest/recorded_judge.json")
    assert p.returncode == 0, p.stdout + p.stderr
    return rd


def test_the_synthetic_schema_checks_against_the_selftest_graph(tmp_path):
    graph, _ = schema_graph(tmp_path)
    p = run("check", str(graph))
    assert p.returncode == 0, p.stdout


def test_manifest_pins_the_schema(tmp_path):
    graph, schema = schema_graph(tmp_path)
    rd = run_selftest(tmp_path, graph)
    m = json.loads((rd / "manifest.json").read_text())
    assert m["schema"] == {"path": str(schema), "version": 3, "sha256": vg.sha(str(schema))}


def test_steps_json_lists_what_ran_and_why_a_step_was_skipped(tmp_path):
    graph, _ = schema_graph(tmp_path)
    rd = run_selftest(tmp_path, graph)
    steps = json.loads((rd / "files" / "steps.json").read_text())
    assert steps == {"steps": [
        {"node": "list_items", "status": "ran", "reason": ""},
        {"node": "judge_items", "status": "ran", "reason": ""},
        {"node": "skipped_branch", "status": "skipped",
         "reason": "count.json:n > 100 was false (actual 4)"},
    ]}


def test_the_exit_steps_code_folder_holds_the_builder_and_the_schema(tmp_path):
    graph, schema = schema_graph(tmp_path)
    rd = run_selftest(tmp_path, graph)
    code = rd / "code" / "03_report"
    assert sorted(p.name for p in code.iterdir()) == ["_lib.py", "_report.py", "report.py", "schema.yaml"]
    assert (code / "_report.py").read_bytes() == (ROOT / "implementations" / "_report.py").read_bytes()
    assert (code / "schema.yaml").read_bytes() == schema.read_bytes()
    rec = json.loads((rd / "records" / "03_report.json").read_text())
    assert set(rec["execution"]["code_files"]) == {
        "code/03_report/_lib.py", "code/03_report/_report.py",
        "code/03_report/report.py", "code/03_report/schema.yaml"}
    # the other tool steps' code folders are as before
    assert sorted(p.name for p in (rd / "code" / "01_list_items").iterdir()) == ["_lib.py", "list_items.py"]


def test_verify_replays_each_steps_own_script(tmp_path, monkeypatch, capsys):
    graph, _ = schema_graph(tmp_path)
    rd = run_selftest(tmp_path, graph)
    ran = []
    real = vg.subprocess.run

    def spy(cmd, *a, **kw):
        ran.append(Path(cmd[1]).name)
        return real(cmd, *a, **kw)

    monkeypatch.setattr(vg.subprocess, "run", spy)
    assert vg.verify(str(rd)) == 0
    assert ran == ["list_items.py", "report.py"]
    assert "FAIL" not in capsys.readouterr().out


def test_the_unchanged_selftest_graph_writes_no_steps_json_and_copies_nothing_more(tmp_path):
    rd = run_selftest(tmp_path, ROOT / "graphs" / "selftest.yaml")
    assert not (rd / "files" / "steps.json").exists()
    assert "schema" not in json.loads((rd / "manifest.json").read_text())
    assert sorted(p.name for p in (rd / "code" / "03_report").iterdir()) == ["_lib.py", "report.py"]
    assert run("verify", "--run", str(rd)).returncode == 0


def test_a_skipped_step_with_no_unfired_check_says_no_incoming_edge_fired(tmp_path):
    """A node whose only incoming edges come from steps that did not run has no check to
    name, so its reason says no incoming edge fired."""
    g = vg.load(str(ROOT / "graphs" / "selftest.yaml"))
    g["nodes"].insert(3, {"id": "after_skip", "kind": "tool", "does": "x"})
    g["_nodes"]["after_skip"] = g["nodes"][3]
    g["edges"].append({"from": "skipped_branch", "rel": "LEADS_TO", "to": "after_skip",
                       "condition": "Always.", "guidance": "x", "pitfalls": [], "source": "test"})
    g["edges"].append({"from": "after_skip", "rel": "CONVERGES_TO", "to": "report",
                       "condition": "Always.", "guidance": "x", "pitfalls": [], "source": "test"})
    rd = run_selftest(tmp_path, ROOT / "graphs" / "selftest.yaml")
    vg.write_steps(str(rd), g)
    steps = json.loads((rd / "files" / "steps.json").read_text())["steps"]
    assert steps[-1] == {"node": "after_skip", "status": "skipped", "reason": "no incoming edge fired"}
