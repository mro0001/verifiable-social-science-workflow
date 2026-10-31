"""Acceptance tests for the schemas and builder, the results file, and the registry (Step C13).

One run of each fixture is shared through module fixtures. The nine runs are the golden
copies' nine (the four streams on their clean and seeded fixtures, and the data procedure
on the sample project), each started by its registered id into a folder named
<stream>_<fixture>, and one more build run on a project with an empty ledger. The four
quick runs are shared the same way. Judgment steps use recorded answers and lookups stay
offline (VG_OFFLINE=1), so nothing here calls a model or the network.
"""
import copy
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
VG = [sys.executable, str(ROOT / "vg.py")]
STREAMS = ["prose", "citations", "data", "build"]
RUNS = [("prose", "clean"), ("prose", "seeded"), ("citations", "clean"), ("citations", "seeded"),
        ("data", "clean"), ("data", "seeded"), ("build", "clean"), ("build", "seeded"),
        ("data", "sample")]
NAMES = ["%s_%s" % r for r in RUNS]
SEEDED = ["%s_seeded" % s for s in STREAMS]
CLEAN = ["prose_clean", "citations_clean", "data_clean", "build_clean", "data_sample"]
RESULTS_KEYS = ["schema", "schema_version", "stream", "run_id", "procedure_version", "inputs",
                "items", "decisions"]
NOT_RUN_EMPTY = {"str": "", "list": [], "dict": {}}
SAMPLE = ROOT.parent / "examples" / "sample_project"


def vg(*args):
    env = dict(os.environ, VG_OFFLINE="1")
    return subprocess.run(VG + [str(a) for a in args], cwd=str(ROOT), capture_output=True,
                          text=True, env=env)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def flat_copy(project, folder):
    """Copy the project's top-level regular files into folder, as the data handoff copies
    a flat project, so a sample project built in place keeps its builds/ out of the run."""
    folder.mkdir(parents=True)
    for path in sorted(Path(project).iterdir()):
        if path.is_file() and not path.is_symlink():
            shutil.copyfile(str(path), str(folder / path.name))
    return folder


def inputs_of(stream, fixture, staging=None):
    if (stream, fixture) == ("data", "sample"):
        return flat_copy(SAMPLE, staging)
    return ROOT / "fixtures" / stream / fixture


def run_by_id(stream, inputs, run_dir):
    """A full run of the registered procedure with the fixture's recorded answers."""
    args = ["run", stream, "--run", run_dir, "--inputs", inputs]
    if stream != "build":
        args += ["--judge", "recorded:%s" % (Path(inputs) / "recorded_judge.json")]
    return vg(*args)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def schema_of(stream):
    return yaml.safe_load((ROOT / "schemas" / ("%s.yaml" % stream)).read_text(encoding="utf-8"))


def graph_of(stream):
    return yaml.safe_load((ROOT / "graphs" / ("%s.yaml" % stream)).read_text(encoding="utf-8"))


def stream_of(name):
    return name.split("_", 1)[0]


def checksum(path):
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def headings(text):
    return [ln for ln in text.splitlines() if ln.startswith("#")]


def table_rows(text):
    return [ln for ln in text.splitlines() if ln.startswith("|")]


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    base = tmp_path_factory.mktemp("acceptance")
    out = {}
    for stream, fixture in RUNS:
        rd = base / ("%s_%s" % (stream, fixture))
        p = run_by_id(stream, inputs_of(stream, fixture, base / (rd.name + "_inputs")), rd)
        assert p.returncode == 0, p.stdout + p.stderr
        out[rd.name] = rd
    # a build project with a map but no ledgered builds, so the rebuild branch is not taken
    empty = base / "empty_inputs"
    empty.mkdir()
    maker = load_module("make_build_fixtures", ROOT / "fixtures" / "build" / "make_fixtures.py")
    maker.pack(str(ROOT / "fixtures" / "build" / "source"), str(empty / "project.tar"))
    shutil.copy(str(ROOT / "fixtures" / "build" / "clean" / "session_writes.jsonl"),
                str(empty / "session_writes.jsonl"))
    rd = base / "build_empty"
    p = run_by_id("build", empty, rd)
    assert p.returncode == 0, p.stdout + p.stderr
    out[rd.name] = rd
    return out


@pytest.fixture(scope="module")
def quick_runs(tmp_path_factory):
    base = tmp_path_factory.mktemp("acceptance_quick")
    out = {}
    for stream in STREAMS:
        rd = base / ("%s_quick" % stream)
        p = vg("run", stream, "--quick", "--run", rd, "--inputs",
               ROOT / "fixtures" / stream / "seeded")
        assert p.returncode == 0, p.stdout + p.stderr
        out[stream] = rd
    return out


@pytest.fixture(scope="module")
def report_lib():
    """The one report builder, for its validate_fields."""
    sys.path.insert(0, str(ROOT / "implementations"))
    try:
        return load_module("report_builder_for_acceptance", ROOT / "implementations" / "_report.py")
    finally:
        sys.path.remove(str(ROOT / "implementations"))


# ---------------------------------------------------------------- schemas and builder

@pytest.mark.parametrize("stream", STREAMS)
def test_each_stream_graph_checks_with_its_schema(stream):
    g = graph_of(stream)
    assert g["schema"] == "schemas/%s.yaml" % stream
    assert schema_of(stream)["stream"] == stream
    p = vg("check", "graphs/%s.yaml" % stream)
    assert p.returncode == 0 and p.stdout.startswith("OK: "), p.stdout + p.stderr


@pytest.mark.parametrize("stream", STREAMS)
def test_every_seeded_fixture_scores_full_recall(runs, stream):
    rd = runs["%s_seeded" % stream]
    p = vg("score", "--run", rd, "--truth", ROOT / "fixtures" / stream / "seeded" / "truth.yaml")
    assert p.returncode == 0, p.stdout + p.stderr
    assert read_json(rd / "score.json")["recall"] == 1.0


@pytest.mark.parametrize("name", CLEAN)
def test_every_clean_fixture_gives_no_blocking_finding_or_warning(runs, name):
    found = read_json(runs[name] / "files" / "findings.json")
    loud = [f for f in found if f["severity"] in ("blocking", "warning")]
    assert loud == [], loud


@pytest.mark.parametrize("name", NAMES + ["build_empty"])
def test_each_runs_fields_validate_against_its_schema(runs, report_lib, name):
    fields = read_json(runs[name] / "files" / "fields.json")
    schema = schema_of(stream_of(name))
    assert fields["schema"] == {"stream": schema["stream"], "version": schema["version"]}
    assert report_lib.validate_fields(schema, fields) == []


@pytest.mark.parametrize("name", NAMES + ["build_empty"])
def test_every_item_id_appears_in_its_report(runs, name):
    fields = read_json(runs[name] / "files" / "fields.json")
    id_field = schema_of(stream_of(name))["id"]
    text = (runs[name] / "files" / "report.md").read_text(encoding="utf-8")
    assert fields["items"]
    missing = [it[id_field] for it in fields["items"] if str(it[id_field]) not in text]
    assert missing == []


def test_the_clean_citations_run_asks_the_passage_step_only_where_no_quote_is_recorded(runs):
    """The references procedure 0.2 has no branch (Track C2). Its one model step asks only
    for the AI citations whose work was found and whose record holds no quote."""
    rd = runs["citations_clean"]
    rows = read_json(rd / "files" / "rows_reasons.json")
    to_locate = [r["id"] for r in rows if r["status"] == "to_locate"]
    asked = sorted(p.stem for p in (rd / "prompts").glob("*_locate_passage/*.txt"))
    assert asked == to_locate == ["r04", "r06"]
    fields = read_json(rd / "files" / "fields.json")
    assert [it["id"] for it in fields["items"]] == [r["id"] for r in rows]
    assert read_json(rd / "files" / "findings_completeness.json") == []


def test_a_branch_not_taken_leaves_the_empty_ledger_pandoc_field_not_run(runs):
    rd = runs["build_empty"]
    nodes = [read_json(p)["node"] for p in sorted((rd / "records").iterdir())]
    assert "no_rebuild" in nodes and "rebuild" not in nodes
    fields = read_json(rd / "files" / "fields.json")
    reason = "ledger.json:rows > 0 was false (actual 0)"
    assert fields["run"]["pandoc"] == {"not_run": reason}
    deliverables = fields["tables"]["deliverables"]
    assert deliverables and all(r["rebuild"] == {"not_run": reason} for r in deliverables)
    text = (rd / "files" / "report.md").read_text(encoding="utf-8")
    assert all(r["name"] in text for r in deliverables)
    assert read_json(rd / "files" / "findings_completeness.json") == []


def test_a_step_removed_from_a_run_gives_a_not_run_field_and_a_completeness_warning(runs, tmp_path):
    done = runs["data_seeded"]
    dest = tmp_path / "data_seeded"
    shutil.copytree(str(done), str(dest))
    fdir = dest / "files"
    before = (fdir / "report.md").read_text(encoding="utf-8")
    steps = read_json(fdir / "steps.json")
    # The data procedure has no judgment step since version 0.2 (Track V, step V2), so a tool
    # step that alone fills one required field stands in.
    reason = "check_records was removed from this run"
    for s in steps["steps"]:
        if s["node"] == "check_records":
            s["status"], s["reason"] = "skipped", reason
    (fdir / "steps.json").write_text(json.dumps(steps, indent=2), encoding="utf-8")
    for name in ("fields.json", "findings.json", "report.md", "findings_completeness.json"):
        (fdir / name).unlink()
    script = sorted(dest.glob("code/*_report/report.py"))[-1]
    p = subprocess.run([sys.executable, str(script), str(fdir)], capture_output=True, text=True,
                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    assert p.returncode == 0, p.stdout + p.stderr
    fields = read_json(fdir / "fields.json")
    assert all(r["records_ok"] == {"not_run": reason} for r in fields["tables"]["steps"])
    warnings = read_json(fdir / "findings_completeness.json")
    assert any(w["item"] == "steps.records_ok" and w["severity"] == "warning" and reason in w["message"]
               for w in warnings), warnings
    assert any(f["check"] == "completeness" and f["item"] == "steps.records_ok"
               for f in read_json(fdir / "findings.json"))
    after = (fdir / "report.md").read_text(encoding="utf-8")
    assert headings(after) == headings(before)
    # every row stays, the findings table gains the one completeness warning, and each row of
    # the rerun's step table shows its records check not run
    added = [ln for ln in table_rows(after) if "| completeness | steps.records_ok |" in ln]
    assert len(added) == 1
    changed = [ln for ln in table_rows(after) if ln not in added and ln not in table_rows(before)]
    assert len(changed) == len(fields["tables"]["steps"])
    assert all("| not run |" in ln for ln in changed)
    assert len(table_rows(after)) == len(table_rows(before)) + 1


@pytest.mark.parametrize("name", NAMES + ["build_empty"])
def test_every_tool_step_of_every_run_replays_the_report_included(runs, name):
    rd = runs[name]
    p = vg("verify", "--run", rd)
    assert p.returncode == 0 and "FAIL" not in p.stdout, p.stdout + p.stderr
    tools = [read_json(r) for r in sorted((rd / "records").iterdir())]
    tools = [r for r in tools if r["kind"] == "tool"]
    verdicts = {s["node"]: s["verdict"] for s in read_json(rd / "verify.json")["steps"]}
    for r in tools:
        assert verdicts[r["node"]] in ("replay matches", "network step: outputs hashed, not replayed"), r["node"]
    assert verdicts["report"] == "replay matches"


def test_versions_yaml_records_each_schemas_versions():
    """Track P raised prose, citations, and build to version 2 for the sessions field, and
    Track C2 raised citations to version 3 for the references procedure 0.2, and to 4 for
    the two quote counts, and Track V raised prose to version 3 and data to version 2 for
    the reports built for the scholar's verification."""
    versions = yaml.safe_load((ROOT / "schemas" / "versions.yaml").read_text(encoding="utf-8"))
    # Track V, step V3, added the schema of the three data phase reports, tested in test_data_phases.py.
    assert sorted(versions) == sorted(STREAMS + ["data_phases"])
    for stream in STREAMS:
        assert list(versions[stream]) == {"data": [1, 2], "prose": [1, 2, 3], "citations": [1, 2, 3, 4]}.get(stream, [1, 2])


@pytest.mark.parametrize("stream", STREAMS)
def test_each_schemas_checksum_matches_its_versions_line(stream):
    """A schema changed without a new version fails here. Raise the schema's version and
    add its new line to schemas/versions.yaml."""
    versions = yaml.safe_load((ROOT / "schemas" / "versions.yaml").read_text(encoding="utf-8"))
    schema = schema_of(stream)
    assert schema["version"] in versions[stream], (
        "schemas/%s.yaml version %s has no line in versions.yaml" % (stream, schema["version"]))
    assert versions[stream][schema["version"]] == checksum(ROOT / "schemas" / ("%s.yaml" % stream)), (
        "schemas/%s.yaml changed without a new version" % stream)


@pytest.mark.parametrize("name", NAMES)
def test_each_run_pins_the_recorded_schema(runs, name):
    versions = yaml.safe_load((ROOT / "schemas" / "versions.yaml").read_text(encoding="utf-8"))
    pinned = read_json(runs[name] / "manifest.json")["schema"]
    assert pinned["sha256"] == versions[stream_of(name)][pinned["version"]]


# ---------------------------------------------------------------- the results file

def schema_item_rows(stream, fields):
    """The schema's item rows as the results file carries them, the results fields of each
    item row in order, a not run value written as the empty value of its type, and a field
    marked required false left out when the row does not give it."""
    schema = schema_of(stream)
    out = []
    for row in fields["items"]:
        item = {}
        for name in schema["results"]:
            if name not in row and schema["fields"][name].get("required") is False:
                continue
            value = row.get(name)
            if isinstance(value, dict) and set(value) == {"not_run"}:
                value = copy.deepcopy(NOT_RUN_EMPTY.get(schema["fields"][name]["type"]))
            item[name] = value
        out.append(item)
    return out


@pytest.mark.parametrize("name", NAMES)
def test_each_results_file_has_the_slices_keys_and_the_schemas_items(runs, name):
    rd = runs[name]
    results = read_json(rd / "results.json")
    manifest = read_json(rd / "manifest.json")
    assert list(results) == RESULTS_KEYS
    assert results["schema"] == "verification-results"
    assert results["schema_version"] == 1
    assert results["stream"] == manifest["stream"] == stream_of(name)
    assert results["inputs"] == manifest["inputs"]
    assert results["run_id"] == name
    assert results["procedure_version"] == graph_of(stream_of(name))["version"]
    assert results["items"] == schema_item_rows(stream_of(name), read_json(rd / "files" / "fields.json"))
    assert results["decisions"] == []


def records_and_report(rd):
    out = {p.name: checksum(p) for p in sorted((rd / "records").iterdir())}
    out["report.md"] = checksum(rd / "files" / "report.md")
    return out


@pytest.mark.parametrize("name", SEEDED)
def test_decide_approves_one_item_and_holds_another_on_each_seeded_run(runs, tmp_path, name):
    rd = tmp_path / name
    shutil.copytree(str(runs[name]), str(rd))
    before = records_and_report(rd)
    items = read_json(rd / "results.json")["items"]
    open_items = [it["id"] for it in items if it["needs_decision"]]
    assert len(open_items) >= 2, open_items
    first, second = open_items[0], open_items[1]
    p = vg("decide", "--run", rd, "--item", first, "--approve", "--by", "A. Scholar")
    assert p.returncode == 0, p.stdout + p.stderr
    p = vg("decide", "--run", rd, "--item", second, "--hold", "--by", "A. Scholar")
    assert p.returncode == 0, p.stdout + p.stderr
    decided = (rd / "report_decided.md").read_text(encoding="utf-8")
    assert "**1 approved, 1 held, %d undecided.**" % (len(open_items) - 2) in decided
    assert "| %s | approved | A. Scholar |" % first in decided
    assert "| %s | held | A. Scholar |" % second in decided
    no_decision = [it["id"] for it in items if not it["needs_decision"]]
    if no_decision:
        p = vg("decide", "--run", rd, "--item", no_decision[0], "--approve", "--by", "A. Scholar")
        assert p.returncode != 0 and "needs no decision" in p.stderr
    results = read_json(rd / "results.json")
    assert [(d["item"], d["decision"]) for d in results["decisions"]] == [
        (first, "approved"), (second, "held")]
    assert records_and_report(rd) == before
    v = vg("verify", "--run", rd)
    assert v.returncode == 0 and "FAIL" not in v.stdout, v.stdout


def test_at_least_one_stream_has_an_item_that_needs_no_decision(runs):
    found = [name for name in SEEDED
             if any(not it["needs_decision"] for it in read_json(runs[name] / "results.json")["items"])]
    assert found


@pytest.mark.parametrize("stream", STREAMS)
def test_a_quick_run_has_no_results_file(quick_runs, stream):
    rd = quick_runs[stream]
    assert not (rd / "results.json").exists()
    assert not (rd / "files" / "report.md").exists()


# ---------------------------------------------------------------- the registry

def test_procedures_check_passes():
    p = vg("procedures", "--check")
    assert p.returncode == 0 and p.stdout.strip() == "OK: 4 procedures", p.stdout + p.stderr


@pytest.mark.parametrize("stream", STREAMS)
def test_each_registered_procedure_runs_by_id_and_scores_full_recall(runs, stream):
    reg = yaml.safe_load((ROOT / "registry.yaml").read_text(encoding="utf-8"))
    entry = next(e for e in reg["procedures"] if e["id"] == stream)
    rd = runs["%s_seeded" % stream]
    manifest = read_json(rd / "manifest.json")
    assert manifest["graph"]["path"] == entry["graph"]
    assert "quick" not in manifest
    if stream != "build":
        assert manifest["executors"]["judge"].startswith("recorded:")
    p = vg("score", "--run", rd, "--truth", ROOT / "fixtures" / stream / "seeded" / "truth.yaml")
    assert p.returncode == 0 and '"recall": 1.0' in p.stdout, p.stdout


@pytest.mark.parametrize("stream", STREAMS)
def test_each_procedures_quick_run_runs_its_quick_steps_only(quick_runs, stream):
    reg = yaml.safe_load((ROOT / "registry.yaml").read_text(encoding="utf-8"))
    entry = next(e for e in reg["procedures"] if e["id"] == stream)
    rd = quick_runs[stream]
    nodes = [read_json(p)["node"] for p in sorted((rd / "records").iterdir())]
    assert nodes == entry["quick_steps"]
    assert read_json(rd / "manifest.json")["quick"] is True
