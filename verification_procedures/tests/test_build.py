"""Build stream: graph valid, clean fixture quiet, seeded faults all caught, steps replay."""
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
VG = [sys.executable, str(ROOT / "vg.py")]
FIX = ROOT / "fixtures" / "build"


def run(*args):
    return subprocess.run(VG + list(args), cwd=ROOT, capture_output=True, text=True)


def run_fixture(tmp_path, name, inputs=None):
    rd = tmp_path / name
    p = run("run", "graphs/build.yaml", "--run", str(rd), "--inputs", str(inputs or FIX / name))
    assert p.returncode == 0, p.stdout + p.stderr
    return rd


def findings(rd):
    return json.loads((rd / "files" / "findings.json").read_text())


def test_graph_checks():
    p = run("check", "graphs/build.yaml")
    assert p.returncode == 0, p.stdout


def test_clean_is_quiet_and_replays(tmp_path):
    rd = run_fixture(tmp_path, "clean")
    loud = [f for f in findings(rd) if f["severity"] in ("blocking", "warning")]
    assert loud == [], loud
    v = run("verify", "--run", str(rd))
    assert v.returncode == 0 and "FAIL" not in v.stdout, v.stdout
    rb = json.loads((rd / "files" / "rebuild.json").read_text())
    assert rb["exercised"] and rb["rebuilt"] == 3 and rb["matched"] == 3


def test_seeded_all_caught_and_replays(tmp_path):
    rd = run_fixture(tmp_path, "seeded")
    p = run("score", "--run", str(rd), "--truth", str(FIX / "seeded" / "truth.yaml"))
    assert p.returncode == 0 and '"recall": 1.0' in p.stdout, p.stdout
    v = run("verify", "--run", str(rd))
    assert v.returncode == 0 and "FAIL" not in v.stdout, v.stdout
    assert not (rd / "files" / "truth.yaml").exists()


def test_report_sections(tmp_path):
    rd = run_fixture(tmp_path, "seeded")
    text = (rd / "files" / "report.md").read_text()
    heads = [ln.lstrip("#").strip() for ln in text.splitlines() if ln.startswith("#")]
    for h in ("Summary", "Problems", "Deliverables", "Builds", "What was checked", "Notes"):
        assert h in heads, h
    assert heads.index("Summary") < heads.index("Problems") < heads.index("Deliverables")
    assert "| Deliverable | Canonical source | Builds | Ledger ok | Rebuild matches | Prefs integrated |" in text


def _load_maker():
    spec = importlib.util.spec_from_file_location("make_fixtures", FIX / "make_fixtures.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_tar_matches_readable_tree():
    for name in ("clean", "seeded"):
        tree = FIX / name / "project"
        on_disk = {str(p.relative_to(tree)): p.read_bytes() for p in tree.rglob("*") if p.is_file()}
        with tarfile.open(FIX / name / "project.tar") as tf:
            packed = {m.name: tf.extractfile(m).read() for m in tf.getmembers() if m.isfile()}
        assert packed == on_disk, name


def test_empty_ledger_takes_no_rebuild_branch(tmp_path):
    """A project with a map but no builds yet: rebuild is skipped and the report says so."""
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    _load_maker().pack(str(FIX / "source"), str(inputs / "project.tar"))
    shutil.copy(FIX / "clean" / "session_writes.jsonl", inputs / "session_writes.jsonl")
    rd = run_fixture(tmp_path, "empty", inputs)
    nodes = [json.loads(p.read_text())["node"] for p in sorted((rd / "records").iterdir())]
    assert "no_rebuild" in nodes and "rebuild" not in nodes
    text = (rd / "files" / "report.md").read_text()
    assert "not exercised" in text
    assert "Rebuilt with pandoc not run." in text
    fields = json.loads((rd / "files" / "fields.json").read_text())
    assert fields["run"]["pandoc"] == {"not_run": "ledger.json:rows > 0 was false (actual 0)"}
    assert all(r["rebuild"] == {"not_run": "ledger.json:rows > 0 was false (actual 0)"}
               for r in fields["tables"]["deliverables"])
    assert fields["tables"]["builds"] == []
    assert "No ledgered builds." in text
    # fields of a step a branch can skip are not required, so no completeness warning
    assert json.loads((rd / "files" / "findings_completeness.json").read_text()) == []
    assert run("verify", "--run", str(rd)).returncode == 0


# ---------------------------------------------------------------- the schema and the one builder

def test_graph_names_its_schema_and_the_schema_checks():
    g = yaml.safe_load((ROOT / "graphs" / "build.yaml").read_text())
    assert g["schema"] == "schemas/build.yaml"
    assert g["version"] == 0.1
    schema = yaml.safe_load((ROOT / "schemas" / "build.yaml").read_text())
    assert schema["stream"] == "build" and schema["version"] == 2
    assert run("check", "graphs/build.yaml").returncode == 0


@pytest.mark.parametrize("name", ["clean", "seeded"])
def test_report_is_written_by_the_one_builder(tmp_path, name):
    rd = run_fixture(tmp_path, name)
    code = next((rd / "code").glob("*_report"))
    assert sorted(p.name for p in code.iterdir()) == ["_lib.py", "_report.py", "report.py", "schema.yaml"]
    fields = json.loads((rd / "files" / "fields.json").read_text())
    assert fields["schema"] == {"stream": "build", "version": 2}
    assert set(fields) == {"schema", "run", "items", "tables"}
    assert set(fields["tables"]) == {"deliverables", "builds"}
    assert fields["run"]["pandoc"].startswith("pandoc ")
    assert json.loads((rd / "files" / "findings_completeness.json").read_text()) == []
    # the items are the ones the results file lists for the build stream
    results = json.loads((rd / "results.json").read_text())
    assert fields["items"] == results["items"]
    ledger = json.loads((rd / "files" / "ledger.json").read_text())
    assert [b["path"] for b in fields["tables"]["builds"]] == [b["path"] for b in ledger["builds"]]


@pytest.mark.parametrize("name", ["clean", "seeded"])
def test_verify_replays_every_tool_step_the_report_included(tmp_path, name):
    rd = run_fixture(tmp_path, name)
    assert run("verify", "--run", str(rd)).returncode == 0
    steps = json.loads((rd / "verify.json").read_text())["steps"]
    assert [s["node"] for s in steps][-1] == "report"
    assert all(s["verdict"] == "replay matches" for s in steps), steps


def test_steps_json_names_the_skipped_branch(tmp_path):
    rd = run_fixture(tmp_path, "clean")
    steps = json.loads((rd / "files" / "steps.json").read_text())["steps"]
    assert {"node": "no_rebuild", "status": "skipped",
            "reason": "ledger.json:rows == 0 was false (actual 3)"} in steps
    assert "report" not in [s["node"] for s in steps]


# ---------------------------------------------------------------- ospipe's forms (Step C9b)

# A synthetic project in ospipe's forms. The Makefile's rules run ospipe's build with
# --manuscript, the ledger has ospipe's nine columns, and numbers.yml nests each value
# under `numbers:`. Nothing here runs ospipe; the built files are written by the test.
OSPIPE_MAKEFILE = (
    "OSPIPE ?= python3 -m ospipe\n"
    "PURPOSE ?= draft\n"
    "\n"
    ".PHONY: manuscript slides\n"
    "\n"
    "manuscript: manuscript.md numbers.yml refs.bib\n"
    "\t$(OSPIPE) build --manuscript manuscript.md --manifest numbers.yml --tables-dir . "
    "--bib refs.bib --builds-dir builds/manuscript --purpose \"$(PURPOSE)\"\n"
    "\n"
    "slides: slides.md numbers.yml\n"
    "\t$(OSPIPE) build --manuscript slides.md --manifest numbers.yml --tables-dir . "
    "--to revealjs --builds-dir builds/slides --purpose \"$(PURPOSE)\"\n"
)
OSPIPE_NUMBERS = (
    "numbers:\n"
    "  n_programs: {value: \"48\", from: results.json, field: n}\n"
    "  share: {value: \"31%\", from: results.json, field: share}\n"
)
OSPIPE_COLUMNS = ["version", "date", "git", "sha256", "purpose", "baseline", "reviewed",
                  "verification", "runs"]
NO_COMMAND = "the ledger records no build command"
NO_SNAPSHOT_SUM = "the ledger records no snapshot checksum"
NO_SOURCE_SUMS = "the ledger records no source or numbers checksum"


def _sha(data):
    import hashlib
    return hashlib.sha256(data).hexdigest()


def _ospipe_ledger(rows):
    head = "| " + " | ".join(OSPIPE_COLUMNS) + " |\n|" + "|".join("---" for _ in OSPIPE_COLUMNS) + "|\n"
    return "# Builds\n\n" + head + "".join(
        "| " + " | ".join(r[c] for c in OSPIPE_COLUMNS) + " |\n" for r in rows)


def ospipe_project(tmp_path, manuscript=None, tamper=False):
    """Write the synthetic ospipe project, pack it, and give the inputs folder."""
    proj = tmp_path / "ospipe_project"
    (proj / "builds" / "manuscript").mkdir(parents=True)
    (proj / "builds" / "slides").mkdir(parents=True)
    (proj / "Makefile").write_text(OSPIPE_MAKEFILE)
    (proj / "numbers.yml").write_text(OSPIPE_NUMBERS)
    (proj / "refs.bib").write_text("")
    text = manuscript or "# A test\n\nIn {{num:n_programs}} programs, {{num:share}} left early.\n"
    (proj / "manuscript.md").write_text(text)
    (proj / "slides.md").write_text("# A test\n\n{{num:n_programs}} programs.\n")
    built = {"manuscript": ("v001.docx", b"PK synthetic docx bytes"),
             "slides": ("v001.html", b"<html>synthetic slides</html>")}
    for name, (fname, data) in built.items():
        bdir = proj / "builds" / name
        (bdir / "v001.md").write_text("# A test\n\nIn 48 programs.\n")
        (bdir / fname).write_bytes(data)
        row = {"version": "v001", "date": "2026-10-29", "git": "-", "sha256": _sha(data),
               "purpose": "story v001", "baseline": "-", "reviewed": "no",
               "verification": "unverified: prose, citations, data, build", "runs": "-"}
        (bdir / "BUILDS.md").write_text(_ospipe_ledger([row]))
    if tamper:
        (proj / "builds" / "manuscript" / "v001.docx").write_bytes(b"PK edited after the build")
    (proj / "build_prefs.yaml").write_text("all: {}\n")
    inputs = tmp_path / "ospipe_inputs"
    inputs.mkdir()
    _load_maker().pack(str(proj), str(inputs / "project.tar"))
    (inputs / "session_writes.jsonl").write_text("")
    return inputs


def files_json(rd, name):
    return json.loads((rd / "files" / name).read_text())


def test_read_map_accepts_ospipes_build_rule(tmp_path):
    rd = run_fixture(tmp_path, "ospipe", ospipe_project(tmp_path))
    m = {d["name"]: d for d in files_json(rd, "map.json")["deliverables"]}
    assert m["manuscript"]["source"] == "manuscript.md"
    assert m["manuscript"]["builds_dir"] == "builds/manuscript"
    assert m["manuscript"]["manifest"] == "numbers.yml"
    assert m["manuscript"]["ext"] == "docx"
    assert m["manuscript"]["pandoc_args"] == ["--from", "markdown", "--to", "docx",
                                              "--citeproc", "--bibliography", "refs.bib"]
    assert m["slides"]["source"] == "slides.md" and m["slides"]["ext"] == "html"
    assert m["slides"]["pandoc_args"] == ["--from", "markdown", "--to", "revealjs", "--standalone"]
    assert [f for f in files_json(rd, "findings_read_map.json") if f["severity"] != "info"] == []


def test_check_ledger_reads_ospipes_nine_columns(tmp_path):
    rd = run_fixture(tmp_path, "ospipe", ospipe_project(tmp_path))
    assert [f for f in files_json(rd, "findings_check_ledger.json") if f["severity"] != "info"] == []
    builds = {b["path"]: b for b in files_json(rd, "ledger.json")["builds"]}
    assert sorted(builds) == ["builds/manuscript/v001.docx", "builds/slides/v001.html"]
    b = builds["builds/manuscript/v001.docx"]
    assert b["file_ok"] is True and b["snapshot_ok"] is None
    assert (b["date"], b["purpose"]) == ("2026-10-29", "story v001")
    rows = {r["path"]: r for r in files_json(rd, "fields.json")["tables"]["builds"]}
    assert rows["builds/manuscript/v001.docx"]["file_ok"] is True
    assert rows["builds/manuscript/v001.docx"]["snapshot_ok"] == {"not_run": NO_SNAPSHOT_SUM}


def test_an_edited_ospipe_build_is_still_caught(tmp_path):
    rd = run_fixture(tmp_path, "ospipe", ospipe_project(tmp_path, tamper=True))
    hits = [f for f in files_json(rd, "findings_check_ledger.json") if f["severity"] == "blocking"]
    assert [(f["item"], f["message"].split(":")[0]) for f in hits] == [
        ("builds/manuscript/v001.docx", "Deliverable edited after build")]


def test_rebuild_is_not_run_when_the_ledger_records_no_command(tmp_path):
    rd = run_fixture(tmp_path, "ospipe", ospipe_project(tmp_path))
    assert [f for f in files_json(rd, "findings_rebuild.json") if f["severity"] != "info"] == []
    rows = files_json(rd, "fields.json")["tables"]["builds"]
    assert rows and all(r["rebuild_matches"] == {"not_run": NO_COMMAND} for r in rows)
    assert all(r["snapshot_witnessed"] == {"not_run": NO_SOURCE_SUMS} for r in rows)
    assert all((r["rebuild_cell"], r["witnessed_cell"], r["snapshot_cell"]) == ("not run",) * 3 for r in rows)
    assert all(r["rebuild"] == "not run" and r["ledger_ok"] == "1/1"
               for r in files_json(rd, "fields.json")["tables"]["deliverables"])
    assert files_json(rd, "findings_completeness.json") == []
    loud = [f for f in findings(rd) if f["severity"] in ("blocking", "warning")]
    assert loud == [], loud
    v = run("verify", "--run", str(rd))
    assert v.returncode == 0 and "FAIL" not in v.stdout, v.stdout


def test_check_hardcoding_reads_the_nested_numbers_form(tmp_path):
    text = "# A test\n\nIn {{num:n_programs}} programs, 31% left early.\n"
    rd = run_fixture(tmp_path, "ospipe", ospipe_project(tmp_path, manuscript=text))
    hits = [f for f in files_json(rd, "findings_check_hardcoding.json") if f["severity"] != "info"]
    assert [(f["severity"], f["item"]) for f in hits] == [("blocking", "manuscript.md:31%")]
    assert "key 'share'" in hits[0]["message"]


def test_rebuild_uses_the_ledger_dates_midnight(tmp_path):
    """A docx build made with SOURCE_DATE_EPOCH at midnight UTC of its ledger date rebuilds
    to the same bytes (B11's date rule)."""
    proj = tmp_path / "standin"
    proj.mkdir()
    shutil.copytree(str(FIX / "source" / "tools"), str(proj / "tools"))
    (proj / "Makefile").write_text(
        "paper: paper.md numbers.yml\n"
        "\tpython3 tools/build.py --source paper.md --manifest numbers.yml --builds-dir builds/paper "
        "--ext docx --purpose draft -- pandoc --to docx\n")
    (proj / "numbers.yml").write_text("n: \"48\"\n")
    (proj / "paper.md").write_text("# Paper\n\nWe studied {{num:n}} programs.\n")
    env = dict(os.environ, SOURCE_DATE_EPOCH="1789948800")  # 2026-09-21 00:00 UTC
    p = subprocess.run([sys.executable, "tools/build.py", "--source", "paper.md", "--manifest", "numbers.yml",
                        "--builds-dir", "builds/paper", "--ext", "docx", "--purpose", "draft", "--",
                        "pandoc", "--to", "docx"], cwd=str(proj), env=env, capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "| 2026-09-21 |" in (proj / "builds" / "paper" / "BUILDS.md").read_text()
    inputs = tmp_path / "standin_inputs"
    inputs.mkdir()
    _load_maker().pack(str(proj), str(inputs / "project.tar"))
    (inputs / "session_writes.jsonl").write_text("")
    rd = run_fixture(tmp_path, "standin_run", inputs)
    rb = files_json(rd, "rebuild.json")
    assert (rb["rebuilt"], rb["matched"]) == (1, 1), rb
    assert [f for f in files_json(rd, "findings_rebuild.json") if f["severity"] != "info"] == []
