"""The data collection, cleaning, and analysis reports (Track V, step V3).

the authors specified these three reports on 2026-10-30. Each gives an outline of the phase's
steps with one- or two-word titles, then each title again with the exact code that carries
it out, then a table of the final build's descriptions of the phase with where the scripts
carry each one out, or missing. A step is a section a script marks with a comment line
`# step: <title>`, or, in a Python script with no marked section, a function the script
calls, in the order it calls them. One model step only finds the descriptions, and a
program checks each quote and each place. The three graphs share their code in
implementations/data_phases/, their contract, and their schema. The test files are a small
synthetic pipeline, and recorded answers stand in for the finding step, so nothing here
calls a model or the network.
"""
import ast
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
FX = ROOT / "fixtures" / "data_phases"
CODE = ROOT / "implementations" / "data_phases"
PHASES = ["collection", "cleaning", "analysis"]
GRAPH = {p: "graphs/data_%s.yaml" % p for p in PHASES}
NODES = ["outline_steps", "find_descriptions", "check_descriptions", "report"]
HEADINGS = ["Summary", "Problems", "Outline", "Code", "Descriptions", "Files read", "Notes"]


def vg(*args):
    env = dict(os.environ, VG_OFFLINE="1")
    return subprocess.run(VG + [str(a) for a in args], cwd=str(ROOT), capture_output=True,
                          text=True, env=env)


def run_phase(phase, inputs, rd, answers=None):
    answers = answers or (Path(inputs) / "recorded_judge.json")
    p = vg("run", GRAPH[phase], "--run", rd, "--inputs", inputs, "--judge", "recorded:%s" % answers)
    assert p.returncode == 0, p.stdout + p.stderr
    return Path(rd)


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    base = tmp_path_factory.mktemp("phases")
    out = {}
    for fixture in ("clean", "seeded"):
        for phase in PHASES:
            out[(phase, fixture)] = run_phase(phase, FX / fixture, base / ("%s_%s" % (phase, fixture)))
    return out


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def findings(rd):
    return read_json(rd / "files" / "findings.json")


def problems(rd):
    return [f for f in findings(rd) if f["severity"] in ("blocking", "warning")]


def report(rd):
    return (rd / "files" / "report.md").read_text(encoding="utf-8")


def section(text, heading):
    """The body of one ## section of a report."""
    parts = re.split(r"^## ", text, flags=re.M)
    for part in parts[1:]:
        head, _, body = part.partition("\n")
        if head.strip() == heading:
            return body.strip("\n")
    raise AssertionError("no section %s" % heading)


def table_rows(body):
    return [ln for ln in body.splitlines() if ln.startswith("| ") and not ln.startswith("| Id ")]


def copy_inputs(src, dest):
    shutil.copytree(str(src), str(dest))
    for name in ("truth.yaml",):
        if (dest / name).exists():
            (dest / name).unlink()
    return dest


def script_lines(fixture, name, start, end):
    lines = (FX / fixture / name).read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[start - 1:end])


# ---------------------------------------------------------------- the graphs

@pytest.mark.parametrize("phase", PHASES)
def test_each_phase_graph_passes_check(phase):
    p = vg("check", GRAPH[phase])
    assert p.returncode == 0, p.stdout + p.stderr
    assert p.stdout.strip() == "OK: 5 nodes, 6 edges"


def load_graph(phase):
    return yaml.safe_load((ROOT / GRAPH[phase]).read_text(encoding="utf-8"))


def test_the_three_graphs_differ_only_in_their_entry_step_title_goal_and_triggers():
    graphs = {p: load_graph(p) for p in PHASES}
    for phase, g in graphs.items():
        assert g["stream"] == "data_phases"
        assert g["version"] == 0.1
        assert g["entry"] == "phase_%s" % phase and g["exit"] == "report"
        assert g["contracts"] == "contracts/data_phases.yaml"
        assert g["schema"] == "schemas/data_phases.yaml"
        assert [n["id"] for n in g["nodes"]] == ["phase_%s" % phase] + NODES
        assert g["title"] == "Data %s report" % phase
        assert g["triggers"]
    first = graphs["collection"]
    for phase in ("cleaning", "analysis"):
        g = graphs[phase]
        assert g["nodes"][1:] == first["nodes"][1:]
        assert g["edges"][1:] == first["edges"][1:]
        entry_edge = dict(g["edges"][0], **{"from": "phase_collection"})
        assert entry_edge == first["edges"][0]


def test_the_finding_step_is_the_only_model_step_and_it_asks_once_per_phase():
    for phase in PHASES:
        nodes = {n["id"]: n for n in load_graph(phase)["nodes"]}
        judged = [n for n in nodes.values() if n["kind"] == "judgment"]
        assert [n["id"] for n in judged] == ["find_descriptions"]
        assert judged[0]["foreach"] == "find_items.json"
        assert judged[0].get("role", "judge") == "judge"
    prompt = (CODE / "find_descriptions.prompt.md").read_text(encoding="utf-8")
    for placeholder in ("{{item.phase_name}}", "{{item.text}}", "{{item.code}}", "{{pitfalls}}"):
        assert placeholder in prompt, placeholder
    # it only finds, and gives no verdict, severity, or fix
    assert '"descriptions"' in prompt and '"where"' in prompt
    for word in ("verdict", "severity", "matches"):
        assert word not in json.dumps(json.loads(re.search(r"```json\n(.*?)\n```", prompt, re.S).group(1)))


def test_the_registry_does_not_name_the_phase_reports():
    reg = yaml.safe_load((ROOT / "registry.yaml").read_text(encoding="utf-8"))
    assert [e["id"] for e in reg["procedures"]] == ["prose", "citations", "data", "build"]


def test_the_schema_has_a_versions_line():
    versions = yaml.safe_load((ROOT / "schemas" / "versions.yaml").read_text(encoding="utf-8"))
    schema = yaml.safe_load((ROOT / "schemas" / "data_phases.yaml").read_text(encoding="utf-8"))
    assert schema["stream"] == "data_phases" and schema["version"] == 1
    import hashlib
    digest = hashlib.sha256((ROOT / "schemas" / "data_phases.yaml").read_bytes()).hexdigest()
    assert versions["data_phases"] == {1: "sha256:" + digest}


# ---------------------------------------------------------------- the clean test files

@pytest.mark.parametrize("phase", PHASES)
def test_the_clean_files_give_no_blocking_finding_or_warning(runs, phase):
    assert problems(runs[(phase, "clean")]) == []


@pytest.mark.parametrize("phase", PHASES)
def test_each_report_has_the_three_parts_in_order(runs, phase):
    text = report(runs[(phase, "clean")])
    assert text.startswith("# Data %s report\n" % phase)
    heads = [ln[3:] for ln in text.splitlines() if ln.startswith("## ")]
    assert heads == HEADINGS


def test_the_collection_outline_is_the_marked_sections(runs):
    body = section(report(runs[("collection", "clean")]), "Outline")
    assert body == "- `collect`, `s0_collect.py`\n  - Draw sample\n  - Write raw"


def test_the_cleaning_outline_is_the_functions_in_the_order_the_script_calls_them(runs):
    body = section(report(runs[("cleaning", "clean")]), "Outline")
    assert body == ("- `clean`, `s1_clean.py`\n  - Main\n  - Read rows\n  - Drop missing\n  - Filter age\n"
                    "  - Top code\n  - Write rows")


def test_the_analysis_outline(runs):
    body = section(report(runs[("analysis", "clean")]), "Outline")
    assert body == "- `model`, `s2_model.py`\n  - Read data\n  - Fit model\n  - Write table"


def test_main_is_a_step_and_an_uncalled_function_is_not(runs):
    rd = runs[("cleaning", "clean")]
    outline = read_json(rd / "files" / "outline.json")
    titles = [s["title"] for s in outline["steps"] if s["script"] == "s1_clean.py"]
    assert titles[0] == "Main" and "Winsorize" not in titles
    notes = [f for f in findings(rd) if f["check"] == "outline_steps" and f["severity"] == "info"]
    assert any(f["item"] == "s1_clean.py line 31" and "winsorize" in f["message"] for f in notes), notes


CODE_SECTIONS = {
    "collection": [("Draw sample", "s0_collect.py", 7, 13), ("Write raw", "s0_collect.py", 15, 19)],
    "cleaning": [("Main", "s1_clean.py", 44, 49), ("Read rows", "s1_clean.py", 8, 11), ("Drop missing", "s1_clean.py", 14, 16),
                 ("Filter age", "s1_clean.py", 19, 21), ("Top code", "s1_clean.py", 24, 28),
                 ("Write rows", "s1_clean.py", 36, 41)],
    "analysis": [("Read data", "s2_model.py", 4, 8), ("Fit model", "s2_model.py", 10, 14),
                 ("Write table", "s2_model.py", 16, 20)],
}


@pytest.mark.parametrize("phase", PHASES)
def test_each_title_is_followed_by_the_exact_code_with_its_file_and_lines(runs, phase):
    body = section(report(runs[(phase, "clean")]), "Code")
    expected = []
    for title, script, start, end in CODE_SECTIONS[phase]:
        lines = "line %d" % start if start == end else "lines %d-%d" % (start, end)
        expected.append("### %s\n\n`%s` %s\n\n```python\n%s\n```" % (
            title, script, lines, script_lines("clean", script, start, end)))
    assert body == "\n\n".join(expected)


def test_the_descriptions_table_gives_each_quote_its_place_and_the_programs_checks(runs):
    body = section(report(runs[("cleaning", "clean")]), "Descriptions")
    assert table_rows(body) == [
        "| d01 | Rows with a missing income were dropped. | `s1_clean.py` lines 14-16 (cleaning, Drop missing) | yes | confirmed |",
        "| d02 | We kept respondents aged 18 or older. | `s1_clean.py` lines 19-21 (cleaning, Filter age) | yes | confirmed |",
        "| d03 | Incomes above 250,000 were top-coded to 250,000. | `s1_clean.py` lines 24-28 (cleaning, Top code) | yes | confirmed |",
    ]
    assert "| Id | Description in the final build's text | Where the scripts carry it out | Quote in the text | Location check |" in body


def test_a_description_carried_out_in_two_places_names_both_and_each_step(runs):
    rows = table_rows(section(report(runs[("analysis", "clean")]), "Descriptions"))
    assert rows[0] == ("| d01 | We regressed satisfaction on income in thousands by ordinary least squares. | "
                       "`s2_model.py` line 7 (analysis, Read data); `s2_model.py` lines 10-14 (analysis, Fit model) "
                       "| yes | confirmed |")


@pytest.mark.parametrize("phase", PHASES)
def test_each_description_is_an_item_for_the_scholar(runs, phase):
    rd = runs[(phase, "clean")]
    results = read_json(rd / "results.json")
    assert results["stream"] == "data_phases"
    assert results["procedure_version"] == 0.1
    items = results["items"]
    answers = read_json(FX / "clean" / "recorded_judge.json")["find_descriptions:%s" % phase]
    assert [it["id"] for it in items] == ["d%02d" % i for i in range(1, len(answers["descriptions"]) + 1)]
    for it, ans in zip(items, answers["descriptions"]):
        assert list(it) == ["id", "kind", "summary", "findings", "needs_decision"]
        assert it["kind"] == "description" and it["needs_decision"] is True
        assert it["summary"] == ans["quote"][:120]
        assert it["findings"] == []


def test_the_scholar_approves_or_holds_a_description(runs, tmp_path):
    rd = tmp_path / "decided"
    shutil.copytree(str(runs[("cleaning", "clean")]), str(rd))
    p = vg("decide", "--run", rd, "--item", "d02", "--hold", "--by", "A. Scholar")
    assert p.returncode == 0, p.stdout + p.stderr
    results = read_json(rd / "results.json")
    assert [(d["item"], d["decision"]) for d in results["decisions"]] == [("d02", "held")]
    assert (rd / "report_decided.md").is_file()


@pytest.mark.parametrize("phase", PHASES)
def test_files_read_names_each_file_by_its_name_and_checksum(runs, phase):
    rd = runs[(phase, "clean")]
    body = section(report(rd), "Files read")
    import hashlib
    for name in ("final_text.md", "pipeline.yaml", "s0_collect.py", "s1_clean.py", "s2_model.py"):
        digest = hashlib.sha256((FX / "clean" / name).read_bytes()).hexdigest()
        assert "`%s`" % name in body and "sha256:" + digest in body, name


# ---------------------------------------------------------------- the seeded test files

def test_the_seeded_cleaning_report_catches_both_planted_faults(runs):
    rd = runs[("cleaning", "seeded")]
    p = vg("score", "--run", rd, "--truth", FX / "seeded" / "truth.yaml")
    assert p.returncode == 0, p.stdout + p.stderr
    assert p.stdout.strip() == '{"faults": 2, "recall": 1.0, "missed": []} extras=0'


def test_the_description_with_no_code_reads_missing(runs):
    rd = runs[("cleaning", "seeded")]
    rows = table_rows(section(report(rd), "Descriptions"))
    assert rows[3] == "| d04 | Responses were weighted to the regional population shares. | missing | yes | missing |"
    item = [it for it in read_json(rd / "results.json")["items"] if it["id"] == "d04"][0]
    assert [f["check"] for f in item["findings"]] == ["check_descriptions"]
    assert item["needs_decision"] is True


def test_a_quote_not_in_the_text_is_shown_as_not_found(runs):
    rd = runs[("cleaning", "seeded")]
    rows = table_rows(section(report(rd), "Descriptions"))
    assert rows[1] == ("| d02 | We kept only respondents aged 18 or older. | `s1_clean.py` lines 19-21 "
                       "(cleaning, Filter age) | no | confirmed |")
    found = [f for f in problems(rd) if f["item"] == "d02"]
    assert [(f["check"], f["severity"]) for f in found] == [("check_descriptions", "warning")]
    assert found[0]["message"] == "The quote is not in the final build's text."


@pytest.mark.parametrize("phase", ["collection", "analysis"])
def test_the_seeded_collection_and_analysis_reports_have_no_planted_fault(runs, phase):
    assert problems(runs[(phase, "seeded")]) == []


def test_the_counts_lead_the_report(runs):
    text = report(runs[("cleaning", "seeded")])
    assert ("Pipeline steps in this phase 1, outline steps 6. Descriptions found 4 (missing from "
            "the scripts 1, quotes not in the text 1, places not in the scripts 0).") in text


# ---------------------------------------------------------------- other cases, in tmp_path

def edit_pipeline(inputs, change):
    path = inputs / "pipeline.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def test_a_phase_with_no_step_declared_says_so(tmp_path):
    inputs = copy_inputs(FX / "clean", tmp_path / "inputs")
    edit_pipeline(inputs, lambda d: d["steps"].pop())
    rd = run_phase("analysis", inputs, tmp_path / "run")
    text = report(rd)
    assert section(text, "Outline") == ("No step of the pipeline declares the phase analysis "
                                        "(`phase: analysis` in `pipeline.yaml`).")
    assert section(text, "Code") == "None."
    # the scripts the pipeline no longer names hold no place the program can confirm
    rows = table_rows(section(text, "Descriptions"))
    assert all(r.endswith("| yes | not found |") for r in rows), rows
    notes = [f for f in findings(rd) if f["check"] == "outline_steps" and f["item"] == "analysis"]
    assert [f["severity"] for f in notes] == ["info"]


def test_a_step_with_no_phase_or_an_unknown_phase_is_named_in_every_report(tmp_path):
    inputs = copy_inputs(FX / "clean", tmp_path / "inputs")

    def change(d):
        del d["steps"][0]["phase"]
        d["steps"][2]["phase"] = "modelling"
    edit_pipeline(inputs, change)
    rd = run_phase("cleaning", inputs, tmp_path / "run")
    found = {f["item"]: f for f in problems(rd) if f["check"] == "outline_steps"}
    assert sorted(found) == ["collect", "model"]
    assert found["collect"]["message"] == ("The step declares no phase, so no phase report shows it.")
    assert found["model"]["message"] == ("The step declares the phase modelling, which is not "
                                         "collection, cleaning, or analysis.")
    items = read_json(rd / "results.json")["items"]
    assert [(it["id"], it["kind"]) for it in items if it["kind"] == "finding"] == [
        ("collect", "finding"), ("model", "finding")]


def test_a_place_outside_the_scripts_lines_is_not_found(tmp_path):
    inputs = copy_inputs(FX / "clean", tmp_path / "inputs")
    book = read_json(FX / "clean" / "recorded_judge.json")
    book["find_descriptions:cleaning"]["descriptions"][0]["where"] = [
        {"file": "s1_clean.py", "start": 48, "end": 60}]
    book["find_descriptions:cleaning"]["descriptions"][1]["where"] = [
        {"file": "s9_none.py", "start": 1, "end": 2}]
    answers = tmp_path / "recorded_judge.json"
    answers.write_text(json.dumps(book), encoding="utf-8")
    rd = run_phase("cleaning", inputs, tmp_path / "run", answers)
    rows = table_rows(section(report(rd), "Descriptions"))
    assert rows[0] == ("| d01 | Rows with a missing income were dropped. | `s1_clean.py` lines 48-60 "
                       "(no such lines, the script has 53) | yes | not found |")
    assert rows[1] == ("| d02 | We kept respondents aged 18 or older. | `s9_none.py` lines 1-2 "
                       "(not a script of the pipeline) | yes | not found |")
    found = {f["item"]: f["message"] for f in problems(rd)}
    assert found["d01"] == "The place s1_clean.py lines 48-60 is not in the scripts."
    assert found["d02"] == "The place s9_none.py lines 1-2 is not in the scripts."


def test_an_answer_entry_that_cannot_be_read_is_named_and_kept_out_of_the_table(tmp_path):
    inputs = copy_inputs(FX / "clean", tmp_path / "inputs")
    book = read_json(FX / "clean" / "recorded_judge.json")
    book["find_descriptions:cleaning"]["descriptions"].insert(0, {"where": []})
    book["find_descriptions:cleaning"]["descriptions"].append(
        {"quote": "Rows with a missing income were dropped.", "where": [{"file": "s1_clean.py", "start": "x"}]})
    answers = tmp_path / "recorded_judge.json"
    answers.write_text(json.dumps(book), encoding="utf-8")
    rd = run_phase("cleaning", inputs, tmp_path / "run", answers)
    rows = table_rows(section(report(rd), "Descriptions"))
    assert [r.split(" | ")[0] for r in rows] == ["| d01", "| d02", "| d03", "| d04"]
    found = {f["item"]: f["message"] for f in problems(rd)}
    assert found["answer entry 1"] == "The finding step's entry gives no quote, so it is not listed."
    assert found["d04"] == "The finding step gave a place that cannot be read, so it is not checked."
    assert rows[3].endswith("| yes | not found |")


def test_a_phase_the_finding_step_did_not_answer_is_a_warning_and_the_run_completes(tmp_path):
    inputs = copy_inputs(FX / "clean", tmp_path / "inputs")
    book = read_json(FX / "clean" / "recorded_judge.json")
    del book["find_descriptions:analysis"]
    answers = tmp_path / "recorded_judge.json"
    answers.write_text(json.dumps(book), encoding="utf-8")
    rd = run_phase("analysis", inputs, tmp_path / "run", answers)
    found = [f for f in problems(rd) if f["check"] == "find_descriptions"]
    assert [(f["item"], f["severity"]) for f in found] == [("analysis", "warning")]
    assert section(report(rd), "Descriptions").endswith("None.")


def test_a_script_that_is_not_python_is_read_by_its_marks_only(tmp_path):
    inputs = copy_inputs(FX / "clean", tmp_path / "inputs")
    (inputs / "s3_plot.R").write_text("library(utils)\n# step: Read table\nt <- read.csv('table_model.csv')\n\n"
                                      "# step: Draw plot\nplot(t$estimate)\n", encoding="utf-8")
    (inputs / "s4_note.R").write_text("x <- 1\n", encoding="utf-8")

    def change(d):
        d["steps"].append({"id": "plot", "phase": "analysis", "runner": "Rscript", "script": "s3_plot.R",
                           "inputs": ["table_model.csv"], "outputs": ["plot.pdf"]})
        d["steps"].append({"id": "note", "phase": "analysis", "runner": "Rscript", "script": "s4_note.R",
                           "inputs": [], "outputs": []})
    edit_pipeline(inputs, change)
    rd = run_phase("analysis", inputs, tmp_path / "run")
    outline = section(report(rd), "Outline")
    assert outline.endswith("- `plot`, `s3_plot.R`\n  - Read table\n  - Draw plot\n"
                            "- `note`, `s4_note.R`\n  - No step could be read from this script.")
    code = section(report(rd), "Code")
    assert "### Read table\n\n`s3_plot.R` lines 2-3\n\n```r\n# step: Read table\nt <- read.csv('table_model.csv')\n```" in code
    found = {f["item"]: f["message"] for f in problems(rd)}
    assert found["s4_note.R"] == ("The script marks no step, and only a Python script's functions "
                                  "can be read in place of marks.")


def test_a_missing_or_broken_script_is_named(tmp_path):
    inputs = copy_inputs(FX / "clean", tmp_path / "inputs")
    (inputs / "s0_collect.py").unlink()
    (inputs / "s1_clean.py").write_text("def broken(:\n", encoding="utf-8")
    rd = run_phase("collection", inputs, tmp_path / "collection")
    found = {f["item"]: f["message"] for f in problems(rd) if f["check"] == "outline_steps"}
    assert found == {"s0_collect.py": "The pipeline names this script, and it is not among the inputs."}
    assert section(report(rd), "Outline") == ("- `collect`, `s0_collect.py`\n"
                                              "  - No step could be read from this script.")
    rd = run_phase("cleaning", inputs, tmp_path / "cleaning")
    found = {f["item"]: f["message"] for f in problems(rd) if f["check"] == "outline_steps"}
    assert found == {"s1_clean.py": "The script cannot be read as Python at line 1, so its steps "
                                    "are not listed."}
    # a script of another phase is named only in its own phase's report
    assert "s0_collect.py" not in found


HELPER_STEPS = (
    "import csv\n\n\n"
    "def _blank(cell):\n"
    "    return cell.strip() == \"\"\n\n\n"
    "def read_rows(name):\n"
    "    with open(name, newline=\"\") as f:\n"
    "        return list(csv.DictReader(f))\n\n\n"
    "def drop_missing(rows):\n"
    "    return [r for r in rows if not _blank(r[\"income\"])]\n\n\n"
    "def write_rows(name, rows):\n"
    "    with open(name, \"w\", newline=\"\") as f:\n"
    "        csv.DictWriter(f, fieldnames=list(rows[0])).writerows(rows)\n\n\n"
)


def test_a_step_that_calls_a_helper_keeps_both_steps_in_call_order(tmp_path):
    # module code that calls the steps itself
    inputs = copy_inputs(FX / "clean", tmp_path / "inputs")
    (inputs / "s1_clean.py").write_text(HELPER_STEPS + (
        "rows = read_rows(\"raw_survey.csv\")\n"
        "rows = drop_missing(rows)\n"
        "write_rows(\"clean_survey.csv\", rows)\n"), encoding="utf-8")
    rd = run_phase("cleaning", inputs, tmp_path / "flat")
    assert section(report(rd), "Outline") == (
        "- `clean`, `s1_clean.py`\n  - Read rows\n  - Drop missing\n  - Blank\n  - Write rows")
    code = section(report(rd), "Code")
    assert "### Drop missing\n\n`s1_clean.py` lines 13-14\n\n" in code
    # the same steps called from main: main is a step too, and comes first
    inputs = copy_inputs(FX / "clean", tmp_path / "inputs_main")
    (inputs / "s1_clean.py").write_text(HELPER_STEPS + (
        "def main():\n"
        "    rows = read_rows(\"raw_survey.csv\")\n"
        "    write_rows(\"clean_survey.csv\", drop_missing(rows))\n\n\n"
        "main()\n"), encoding="utf-8")
    rd = run_phase("cleaning", inputs, tmp_path / "main")
    assert section(report(rd), "Outline") == (
        "- `clean`, `s1_clean.py`\n  - Main\n  - Read rows\n  - Drop missing\n  - Blank\n  - Write rows")


def test_a_one_step_script_with_a_helper_shows_both_and_leaves_no_code_out(tmp_path):
    inputs = copy_inputs(FX / "clean", tmp_path / "inputs")
    (inputs / "s2_model.py").write_text(
        "def _fmt(x):\n"
        "    return \"%.3f\" % x\n\n\n"
        "def fit_model(d):\n"
        "    slope = sum(d) / len(d)\n"
        "    return _fmt(slope)\n\n\n"
        "print(fit_model([1, 2]))\n", encoding="utf-8")
    book = read_json(FX / "clean" / "recorded_judge.json")
    book["find_descriptions:analysis"]["descriptions"] = [
        {"quote": "We regressed satisfaction on income in thousands by ordinary least squares.",
         "where": [{"file": "s2_model.py", "start": 6, "end": 7}]}]
    answers = tmp_path / "recorded_judge.json"
    answers.write_text(json.dumps(book), encoding="utf-8")
    rd = run_phase("analysis", inputs, tmp_path / "run", answers)
    assert section(report(rd), "Outline") == "- `model`, `s2_model.py`\n  - Fit model\n  - Fmt"
    assert "### Fit model\n\n`s2_model.py` lines 5-7\n\n" in section(report(rd), "Code")
    rows = table_rows(section(report(rd), "Descriptions"))
    assert "`s2_model.py` lines 6-7 (analysis, Fit model)" in rows[0]


def test_a_script_two_steps_of_one_phase_run_shows_its_code_and_notes_once(tmp_path):
    inputs = copy_inputs(FX / "clean", tmp_path / "inputs")
    text = (inputs / "s2_model.py").read_text(encoding="utf-8")
    (inputs / "s2_model.py").write_text(text.replace("# step: Fit model", "# step: Fit the linear model"),
                                        encoding="utf-8")

    def change(d):
        d["steps"].append({"id": "model_again", "phase": "analysis", "script": "s2_model.py"})
    edit_pipeline(inputs, change)
    rd = run_phase("analysis", inputs, tmp_path / "run")
    body = section(report(rd), "Outline")
    assert body.count("  - Fit the linear model") == 2
    code = section(report(rd), "Code")
    assert code.count("### Read data\n") == 1 and code.count("### Fit the linear model\n") == 1
    notes = [f for f in findings(rd) if f["item"] == "s2_model.py line 10"]
    assert len(notes) == 1, notes


def test_a_script_two_phases_share_is_read_and_noted_in_each_report(tmp_path):
    inputs = copy_inputs(FX / "clean", tmp_path / "inputs")
    (inputs / "shared.py").write_text("def fetch():\n    return 1\n\n\ndef unused():\n    return 0\n\n\n"
                                      "fetch()\n", encoding="utf-8")
    (inputs / "note.R").write_text("x <- 1\n", encoding="utf-8")

    def change(d):
        d["steps"].insert(0, {"id": "fetch", "phase": "collection", "script": "shared.py"})
        d["steps"].insert(1, {"id": "note_a", "phase": "collection", "script": "note.R"})
        d["steps"].append({"id": "tidy", "phase": "cleaning", "script": "shared.py"})
        d["steps"].append({"id": "note_b", "phase": "cleaning", "script": "note.R"})
        d["steps"].append({"id": "note_c", "phase": "cleaning", "script": "note.R"})
    edit_pipeline(inputs, change)
    book = read_json(FX / "clean" / "recorded_judge.json")
    book["find_descriptions:cleaning"]["descriptions"][0]["where"] = [
        {"file": "shared.py", "start": 1, "end": 2}]
    answers = tmp_path / "recorded_judge.json"
    answers.write_text(json.dumps(book), encoding="utf-8")
    for phase in ("collection", "cleaning"):
        rd = run_phase(phase, inputs, tmp_path / phase, answers)
        warned = [f for f in problems(rd) if f["item"] == "note.R"]
        assert [f["message"] for f in warned] == [
            "The script marks no step, and only a Python script's functions can be read in place of marks."]
        notes = [f for f in findings(rd) if f["check"] == "outline_steps" and f["item"] == "shared.py line 5"]
        assert len(notes) == 1 and "unused" in notes[0]["message"], phase
        outline = read_json(rd / "files" / "outline.json")
        shared = [s for s in outline["scripts"] if s["file"] == "shared.py"]
        assert [(s["pipeline_steps"], s["phases"]) for s in shared] == [
            (["fetch", "tidy"], ["collection", "cleaning"])]
    body = section(report(rd), "Outline")
    assert "- `tidy`, `shared.py`\n  - Fetch\n" in body
    assert "- `note_b`, `note.R`\n  - No step could be read from this script.\n" in body
    rows = table_rows(section(report(rd), "Descriptions"))
    assert rows[0] == ("| d01 | Rows with a missing income were dropped. | `shared.py` lines 1-2 "
                       "(collection and cleaning, Fetch) | yes | confirmed |")


def test_code_holding_a_fence_is_shown_inside_a_longer_fence(tmp_path):
    inputs = copy_inputs(FX / "clean", tmp_path / "inputs")
    (inputs / "s2_model.py").write_text('# step: Write note\nNOTE = """\n```\nnot a fence\n```\n"""\n',
                                        encoding="utf-8")
    rd = run_phase("analysis", inputs, tmp_path / "run")
    assert "````python\n# step: Write note\n" in section(report(rd), "Code")


def test_a_title_of_more_than_two_words_is_kept_and_noted(tmp_path):
    inputs = copy_inputs(FX / "clean", tmp_path / "inputs")
    text = (inputs / "s2_model.py").read_text(encoding="utf-8")
    (inputs / "s2_model.py").write_text(text.replace("# step: Fit model", "# step: Fit the linear model"),
                                        encoding="utf-8")
    rd = run_phase("analysis", inputs, tmp_path / "run")
    assert "  - Fit the linear model" in section(report(rd), "Outline")
    notes = [f for f in findings(rd) if f["item"] == "s2_model.py line 10"]
    assert [(f["severity"], f["message"]) for f in notes] == [
        ("info", "The title has 4 words, and the outline asks for one or two.")]


# ---------------------------------------------------------------- the run record

@pytest.mark.parametrize("phase", PHASES)
def test_every_tool_step_replays(runs, phase):
    for fixture in ("clean", "seeded"):
        rd = runs[(phase, fixture)]
        p = vg("verify", "--run", rd)
        assert p.returncode == 0 and "FAIL" not in p.stdout, p.stdout + p.stderr


@pytest.mark.parametrize("phase", PHASES)
def test_no_report_names_an_absolute_path(runs, phase):
    for fixture in ("clean", "seeded"):
        rd = runs[(phase, fixture)]
        for name in ("files/report.md", "files/findings.json", "results.json", "files/fields.json"):
            text = (rd / name).read_text(encoding="utf-8")
            assert str(rd) not in text and str(FX) not in text and str(Path.home()) not in text, name


def test_the_text_a_scholar_reads_has_no_em_dash(runs):
    for rd in runs.values():
        assert "—" not in report(rd)


def test_the_code_imports_nothing_from_another_layer():
    allowed = {"_lib", "_report", "ast", "hashlib", "json", "os", "re", "sys", "yaml"}
    files = sorted(CODE.glob("*.py"))
    assert [f.name for f in files] == ["check_descriptions.py", "outline_steps.py", "phase_analysis.py",
                                       "phase_cleaning.py", "phase_collection.py", "report.py"]
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [(node.module or "").split(".")[0]]
            else:
                continue
            assert set(names) <= allowed, (path.name, names)


# ---------------------------------------------------------------- golden copies

spec_golden = None


def golden_maker():
    import importlib.util
    spec = importlib.util.spec_from_file_location("make_golden_phases",
                                                  str(ROOT / "tests" / "golden" / "make_golden_phases.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("phase,fixture", [(p, f) for f in ("clean", "seeded") for p in PHASES])
def test_each_run_reproduces_its_golden_copy(tmp_path, phase, fixture):
    maker = golden_maker()
    name = maker.folder_name(phase, fixture)
    rd = tmp_path / name
    proc = maker.run_phase(phase, fixture, rd)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    for fname, path in sorted(maker.outputs(rd).items()):
        want = ROOT / "tests" / "golden" / name / fname
        assert want.is_file(), "no golden copy %s/%s" % (name, fname)
        assert path.read_bytes() == want.read_bytes(), "%s/%s differs" % (name, fname)
    assert sorted(maker.outputs(rd)) == ["findings.json", "report.md", "results.json"]


# ---------------------------------------------------------------- a script in a subfolder (V4)

def test_a_script_in_a_subfolder_is_outlined_and_its_places_confirmed(tmp_path):
    """The data phase handoff copies each script at its path inside the project, and the
    run carries the subfolder, so the analysis report finds code/s2_model.py."""
    inputs = tmp_path / "inputs"
    shutil.copytree(str(FX / "clean"), str(inputs))
    (inputs / "code").mkdir()
    shutil.move(str(inputs / "s2_model.py"), str(inputs / "code" / "s2_model.py"))
    pipe = inputs / "pipeline.yaml"
    pipe.write_text(pipe.read_text(encoding="utf-8").replace("script: s2_model.py",
                                                             "script: code/s2_model.py"),
                    encoding="utf-8")
    answers = tmp_path / "recorded_judge.json"
    answers.write_text((inputs / "recorded_judge.json").read_text(encoding="utf-8").replace(
        '"s2_model.py"', '"code/s2_model.py"'), encoding="utf-8")
    rd = run_phase("analysis", inputs, tmp_path / "run", answers)
    outline = read_json(rd / "files" / "outline.json")
    assert [(s["script"], s["title"]) for s in outline["steps"] if s["phase"] == "analysis"] == [
        ("code/s2_model.py", "Read data"), ("code/s2_model.py", "Fit model"),
        ("code/s2_model.py", "Write table")]
    descriptions = read_json(rd / "files" / "descriptions.json")
    assert [d["location_status"] for d in descriptions] == ["confirmed", "confirmed"]
    assert problems(rd) == []
    assert "code/s2_model.py" in report(rd)
    p = vg("verify", "--run", rd)
    assert p.returncode == 0, p.stdout + p.stderr
