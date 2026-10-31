"""The procedure registry (Step C11).

registry.yaml names one procedure for each of Table 1's streams, with its graph, the
events, phrases, and file patterns that start it, and its quick steps. `vg.py procedures`
prints each entry with its graph's version, its schema and that schema's version, and the
input files its contracts need, for another layer's hooks and adapters to read as data.
`vg.py procedures --check` checks the registry, and `vg.py run` takes a registered id in
place of a graph path. Judgment steps use recorded answers and lookups stay offline, so
nothing here calls a model or the network.
"""
import copy
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
VG = [sys.executable, str(ROOT / "vg.py")]
STREAMS = ["prose", "citations", "data", "build"]
EVENTS = ["ai_edit", "turn_end", "build", "commit"]
CITATION_INPUTS = ["draft.md", "citation_provenance.yaml", "refs.yaml", "metadata_cache.json"]


def vg(*args):
    env = dict(os.environ, VG_OFFLINE="1")
    return subprocess.run(VG + [str(a) for a in args], cwd=str(ROOT), capture_output=True,
                          text=True, env=env)


def load_vg():
    spec = importlib.util.spec_from_file_location("vg_for_registry", ROOT / "vg.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def registry():
    return yaml.safe_load((ROOT / "registry.yaml").read_text(encoding="utf-8"))


def listing():
    p = vg("procedures")
    assert p.returncode == 0, p.stdout + p.stderr
    return json.loads(p.stdout)


# ---------------------------------------------------------------- the real registry

def test_check_passes_on_the_real_registry():
    p = vg("procedures", "--check")
    assert p.returncode == 0, p.stdout + p.stderr
    assert p.stdout.strip() == "OK: 4 procedures"


def test_the_registry_names_table_1s_streams_and_procedures():
    reg = registry()
    assert reg["registry_version"] == 1
    entries = reg["procedures"]
    assert [e["id"] for e in entries] == STREAMS
    assert [e["stream"] for e in entries] == STREAMS
    assert [(e["name"], e["procedure"]) for e in entries] == [
        ("Prose", "Change review"), ("References", "Source support"),
        ("Data and analysis code", "Code"), ("Build", "Build integrity")]
    for e in entries:
        assert list(e) == ["id", "stream", "name", "procedure", "graph", "triggers", "quick_steps"]
        assert e["graph"] == "graphs/%s.yaml" % e["id"]
        assert list(e["triggers"]) == ["events", "phrases", "files"]
        assert e["triggers"]["events"] == EVENTS


def test_the_default_phrases_and_files():
    triggers = {e["id"]: e["triggers"] for e in registry()["procedures"]}
    assert triggers["prose"]["phrases"] == ["verify prose", "check AI edits", "change review"]
    assert triggers["prose"]["files"] == ["*.md"]
    assert triggers["citations"]["phrases"] == ["verify citations", "check references",
                                                "citation report"]
    assert triggers["citations"]["files"] == ["*.md", "*.bib", "refs.yaml"]
    assert triggers["data"]["phrases"] == ["verify data", "check the analysis", "rerun the analysis"]
    assert triggers["data"]["files"] == ["*.py", "*.R", "*.qmd", "params.yaml", "numbers.yml",
                                         "pipeline.yaml"]
    assert triggers["build"]["phrases"] == ["verify the build", "check builds"]
    assert triggers["build"]["files"] == ["Makefile", "*.md", "BUILDS.md"]


def test_the_listing_gives_each_procedures_versions_and_inputs():
    listed = listing()
    reg = registry()["procedures"]
    assert [p["id"] for p in listed] == STREAMS
    mod = load_vg()
    for entry, p in zip(reg, listed):
        g = yaml.safe_load((ROOT / entry["graph"]).read_text(encoding="utf-8"))
        schema = yaml.safe_load((ROOT / g["schema"]).read_text(encoding="utf-8"))
        assert p == dict(entry, graph_version=g["version"], schema=g["schema"],
                         schema_version=schema["version"],
                         inputs=mod.inputs_of(mod.load(str(ROOT / entry["graph"]))))
        assert p["schema_version"] == {"prose": 3, "citations": 4}.get(p["id"], 2)
        assert set(p["inputs"]) == {"required", "optional"}
    versions = {p["id"]: p["graph_version"] for p in listed}
    assert versions == {"prose": 0.3, "citations": 0.2, "data": 0.2, "build": 0.1}


def test_the_citations_inputs():
    inputs = {p["id"]: p["inputs"] for p in listing()}["citations"]
    assert inputs == {"required": CITATION_INPUTS, "optional": ["source_*.txt"]}


def test_the_other_streams_inputs():
    inputs = {p["id"]: p["inputs"] for p in listing()}
    assert inputs["prose"] == {"required": ["baseline.md", "revised.md", "versions.yaml",
                                            "rationales.yaml"],
                               "optional": []}
    assert inputs["data"] == {"required": ["pipeline.yaml", "acquisition.yaml", "params.yaml",
                                           "numbers.yml"],
                              "optional": ["*"]}
    assert inputs["build"] == {"required": ["project.tar", "session_writes.jsonl"],
                               "optional": []}


def test_inputs_leave_out_steps_json_and_the_exit_steps_findings_pattern():
    mod = load_vg()
    g = mod.load(str(ROOT / "graphs" / "selftest.yaml"))
    assert mod.inputs_of(g) == {"required": ["words.txt"], "optional": []}
    for p in listing():
        assert "steps.json" not in p["inputs"]["required"]
        assert "findings_*.json" not in p["inputs"]["optional"]


@pytest.mark.parametrize("stream", STREAMS)
def test_every_required_input_exists_in_the_seeded_fixture(stream):
    inputs = {p["id"]: p["inputs"] for p in listing()}[stream]
    seeded = ROOT / "fixtures" / stream / "seeded"
    assert inputs["required"]
    for name in inputs["required"]:
        assert (seeded / name).is_file(), name


# ---------------------------------------------------------------- synthetic registries

def synthetic():
    return copy.deepcopy(registry())


def problems_of(reg):
    return load_vg().check_registry(reg)


def test_the_real_registry_has_no_problems():
    assert problems_of(registry()) == []


def test_a_repeated_id_is_refused():
    reg = synthetic()
    reg["procedures"][1]["id"] = "prose"
    assert "procedure prose: repeated id" in problems_of(reg)


def test_a_missing_graph_is_refused():
    reg = synthetic()
    reg["procedures"][0]["graph"] = "graphs/nowhere.yaml"
    assert "procedure prose: graph graphs/nowhere.yaml does not exist" in problems_of(reg)


def test_a_graph_without_a_schema_is_refused():
    reg = synthetic()
    reg["procedures"].append(dict(reg["procedures"][0], id="selftest", stream="selftest",
                                  graph="graphs/selftest.yaml", quick_steps=[]))
    assert problems_of(reg) == ["procedure selftest: graph graphs/selftest.yaml names no schema"]


def test_a_graph_that_fails_its_check_is_refused(tmp_path):
    g = yaml.safe_load((ROOT / "graphs" / "selftest.yaml").read_text(encoding="utf-8"))
    g["nodes"][0]["kind"] = "script"
    path = tmp_path / "broken.yaml"
    path.write_text(yaml.safe_dump(g), encoding="utf-8")
    reg = synthetic()
    reg["procedures"][0]["graph"] = str(path)
    found = problems_of(reg)
    assert any(p.startswith("procedure prose: graph %s fails check: " % path) for p in found), found


def test_a_stream_that_differs_from_the_graphs_is_refused():
    reg = synthetic()
    reg["procedures"][0]["stream"] = "citations"
    assert ("procedure prose: stream citations differs from the graph's stream prose"
            in problems_of(reg))


def test_an_unknown_event_is_refused():
    reg = synthetic()
    reg["procedures"][2]["triggers"]["events"] = ["ai_edit", "lunch"]
    assert "procedure data: unknown event lunch" in problems_of(reg)


def test_empty_phrases_are_refused():
    reg = synthetic()
    reg["procedures"][3]["triggers"]["phrases"] = []
    assert "procedure build: phrases must be a non-empty list of text" in problems_of(reg)


def test_files_that_are_not_text_are_refused():
    reg = synthetic()
    reg["procedures"][3]["triggers"]["files"] = ["Makefile", 3]
    assert "procedure build: files must be a non-empty list of text" in problems_of(reg)


def test_an_unknown_or_missing_key_is_refused():
    reg = synthetic()
    del reg["procedures"][0]["procedure"]
    reg["procedures"][0]["triggers"]["hooks"] = ["Stop"]
    reg["procedures"][1]["owner"] = "C"
    found = problems_of(reg)
    assert "procedure prose: missing key procedure" in found
    assert "procedure prose: unknown trigger key hooks" in found
    assert "procedure citations: unknown key owner" in found


def test_a_registry_of_another_version_is_refused():
    reg = synthetic()
    reg["registry_version"] = 2
    assert "registry_version must be 1, not 2" in problems_of(reg)


def test_every_problem_is_named_at_once():
    reg = synthetic()
    reg["procedures"][1]["id"] = "prose"
    reg["procedures"][2]["graph"] = "graphs/nowhere.yaml"
    reg["procedures"][3]["triggers"]["events"] = ["lunch"]
    reg["procedures"][3]["triggers"]["phrases"] = []
    found = problems_of(reg)
    assert found == ["procedure prose: repeated id",
                     "procedure data: graph graphs/nowhere.yaml does not exist",
                     "procedure build: unknown event lunch",
                     "procedure build: phrases must be a non-empty list of text"]


# ---------------------------------------------------------------- running by id

def run_citations(graph, run_dir):
    seeded = ROOT / "fixtures" / "citations" / "seeded"
    return vg("run", graph, "--run", run_dir, "--inputs", seeded,
              "--judge", "recorded:%s" % (seeded / "recorded_judge.json"))


def test_running_by_id_gives_the_same_report_as_the_graph_path(tmp_path):
    by_id = tmp_path / "by_id" / "seeded_run"
    by_path = tmp_path / "by_path" / "seeded_run"
    p = run_citations("citations", by_id)
    assert p.returncode == 0, p.stdout + p.stderr
    p = run_citations("graphs/citations.yaml", by_path)
    assert p.returncode == 0, p.stdout + p.stderr
    for name in ("report.md", "findings.json", "fields.json"):
        assert (by_id / "files" / name).read_bytes() == (by_path / "files" / name).read_bytes(), name
    assert (by_id / "results.json").read_bytes() == (by_path / "results.json").read_bytes()
    m_id = json.loads((by_id / "manifest.json").read_text())
    m_path = json.loads((by_path / "manifest.json").read_text())
    assert m_id["graph"] == m_path["graph"] and m_id["graph"]["path"] == "graphs/citations.yaml"
