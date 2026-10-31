"""Data stream, the final-numbers report (Track V, step V2): graph check, clean fixture
silent, seeded fixture fully caught, tool steps replay, and the report lists each number
with the output and the script that produce it, marks the AI's scripts and parameters by
the record of the AI's file edits, and keeps the rerun in its own section. No step asks a
model."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
VG = [sys.executable, str(ROOT / "vg.py")]
FX = ROOT / "fixtures" / "data"

GRAPH_NODES = ["inventory", "check_raw", "check_params", "check_docs", "attribute_ai",
               "replay_pipeline", "check_records", "check_numbers"]
# The order the runtime runs them, the graph's topological order.
RUN_ORDER = ["inventory", "check_raw", "check_params", "replay_pipeline", "check_docs",
             "attribute_ai", "check_records", "check_numbers"]
NUMBER_FIELDS = {"key", "value", "replayed", "from", "ok", "agrees"}
NUMBERS = ["alpha", "mean_income_k_north", "n_analytic", "p_income_k", "slope_income_k"]
SECTIONS = ["Summary", "Problems", "Numbers", "AI changes to scripts", "Parameters the AI set",
            "Scripts", "Reproducibility"]


def vg(*args):
    return subprocess.run(VG + [str(a) for a in args], cwd=ROOT, capture_output=True, text=True)


def run_inputs(rd, inputs):
    p = vg("run", "graphs/data.yaml", "--run", rd, "--inputs", inputs)
    assert p.returncode == 0, p.stdout + p.stderr
    return rd


def run_fixture(tmp_path, name):
    return run_inputs(tmp_path / name, FX / name)


@pytest.fixture(scope="module")
def clean_run(tmp_path_factory):
    return run_fixture(tmp_path_factory.mktemp("data"), "clean")


@pytest.fixture(scope="module")
def seeded_run(tmp_path_factory):
    return run_fixture(tmp_path_factory.mktemp("data"), "seeded")


def copy_of(tmp_path, name="clean"):
    inputs = tmp_path / "inputs"
    shutil.copytree(str(FX / name), str(inputs))
    return inputs


def record_of(inputs):
    return yaml.safe_load((inputs / "file_edits.yaml").read_text(encoding="utf-8"))


def write_record(inputs, entries):
    (inputs / "file_edits.yaml").write_text(yaml.safe_dump(entries, sort_keys=False), encoding="utf-8")


def findings(rd):
    return json.loads((rd / "files" / "findings.json").read_text())


def fields_of(rd):
    return json.loads((rd / "files" / "fields.json").read_text())


def items_of(rd):
    return {it["id"]: it for it in fields_of(rd)["items"]}


def report_of(rd):
    return (rd / "files" / "report.md").read_text(encoding="utf-8")


def loud(rd):
    return [f for f in findings(rd) if f["severity"] in ("blocking", "warning")]


# ---------------------------------------------------------------- the graph

def test_graph_check():
    p = vg("check", "graphs/data.yaml")
    assert p.returncode == 0, p.stdout


def test_the_graph_is_version_0_2_with_no_judgment_step():
    g = yaml.safe_load((ROOT / "graphs" / "data.yaml").read_text())
    assert g["version"] == 0.2
    assert g["schema"] == "schemas/data.yaml"
    assert [n["id"] for n in g["nodes"]] == GRAPH_NODES + ["report"]
    assert all(n["kind"] == "tool" for n in g["nodes"])
    schema = yaml.safe_load((ROOT / "schemas" / "data.yaml").read_text())
    assert schema["stream"] == "data" and schema["version"] == 2
    assert not (ROOT / "implementations" / "data" / "judge_method_docs.prompt.md").exists()


# ---------------------------------------------------------------- the clean and seeded files

def test_clean_has_no_blocking_or_warning(clean_run):
    assert loud(clean_run) == []
    replay = json.loads((clean_run / "files" / "replay.json").read_text())
    assert replay["all_reproduce"] and replay["crashed"] == 0


def test_seeded_full_recall(seeded_run):
    p = vg("score", "--run", seeded_run, "--truth", FX / "seeded" / "truth.yaml")
    assert p.returncode == 0 and '"recall": 1.0' in p.stdout, p.stdout


def test_seeded_catches_each_fault_the_plan_names(seeded_run):
    found = {(f["check"], f["item"], f["severity"]) for f in findings(seeded_run)}
    # an AI-edited script with no reason, a parameter the AI changed, a number that
    # does not reproduce, and a raw file changed after collection
    assert ("attribute_ai", "e02", "blocking") in found
    assert ("attribute_ai", "params.yaml:fig_width", "warning") in found
    assert ("check_numbers", "slope_income_k", "blocking") in found
    assert ("check_raw", "raw_survey.csv", "blocking") in found


def test_the_truth_file_names_the_planted_faults():
    truth = yaml.safe_load((FX / "seeded" / "truth.yaml").read_text())
    pairs = {(t["check"], t["item"]) for t in truth["faults"]}
    assert ("attribute_ai", "e02") in pairs and ("attribute_ai", "params.yaml:fig_width") in pairs
    assert not any(t["check"] == "judge_method_docs" for t in truth["faults"])


def test_tool_steps_replay(clean_run, seeded_run):
    for rd in (clean_run, seeded_run):
        p = vg("verify", "--run", rd)
        assert p.returncode == 0, p.stdout
        assert "FAIL" not in p.stdout


def test_truth_stays_out_of_the_run_and_no_recorded_answers_remain(seeded_run):
    files = {p.name for p in (seeded_run / "files").iterdir()}
    assert "truth.yaml" not in files
    for name in ("clean", "seeded"):
        assert not (FX / name / "recorded_judge.json").exists()


def test_steps_json_lists_every_step_as_ran(clean_run):
    steps = json.loads((clean_run / "files" / "steps.json").read_text())["steps"]
    assert [s["node"] for s in steps] == RUN_ORDER
    assert all(s["status"] == "ran" for s in steps)


def test_verify_replays_every_step_the_report_included(seeded_run):
    assert vg("verify", "--run", seeded_run).returncode == 0
    steps = json.loads((seeded_run / "verify.json").read_text())["steps"]
    assert steps[-1]["node"] == "report"
    assert len(steps) == 9
    assert all(s["verdict"] == "replay matches" for s in steps), steps


# ---------------------------------------------------------------- the report

def test_report_sections_in_order(seeded_run):
    heads = [ln.lstrip("#").strip() for ln in report_of(seeded_run).splitlines() if ln.startswith("## ")]
    assert [h for h in heads if h in SECTIONS] == SECTIONS


def test_each_number_shows_its_output_its_script_and_whether_it_comes_from_ai_work(clean_run, seeded_run):
    text = report_of(clean_run)
    assert "| mean_income_k_north | 59.311 | table_descriptives.csv | s2_describe.py | yes, e01 in s2_describe.py |" in text
    assert "| slope_income_k | 0.011 | table_model.csv | s3_model.py | no |" in text
    text = report_of(seeded_run)
    assert "| slope_income_k | 0.015 | table_model.csv | s3_model.py | yes, e02 in s1_clean.py |" in text
    assert ("| mean_income_k_north | 63.487 | table_descriptives.csv | s2_describe.py | "
            "yes, e01 in s2_describe.py, e02 in s1_clean.py, parameter fig_width |") in text


def test_the_reproducibility_section_gives_each_numbers_match_or_mismatch(clean_run, seeded_run):
    clean = report_of(clean_run).split("## Reproducibility", 1)[1]
    assert "| slope_income_k | 0.011 | 0.011 | yes |" in clean
    seeded = report_of(seeded_run).split("## Reproducibility", 1)[1]
    assert "| slope_income_k | 0.015 | 0.011 | **no** |" in seeded
    assert "| clean | s1_clean.py | yes | yes | clean |" in seeded
    assert "| raw_survey.csv |" in seeded and "| **no** |" in seeded
    assert "| fig_width | 520 | 520 | yes | describe | s2_describe.py |" in seeded


def test_the_raw_checksums_are_shown_against_the_acquisition_record(clean_run, seeded_run):
    acq = yaml.safe_load((FX / "clean" / "acquisition.yaml").read_text())
    want = acq["raw"][0]["sha256"]
    row = "| raw_survey.csv | %s | %s | yes |" % (want, want)
    assert row in report_of(clean_run)
    raw = fields_of(seeded_run)["tables"]["raw"]
    assert raw[0]["file"] == "raw_survey.csv" and raw[0]["agrees"] == "**no**"
    assert raw[0]["recorded"] != raw[0]["now"]


def test_an_ai_change_to_a_script_shows_the_change_and_the_stated_reason(seeded_run):
    text = report_of(seeded_run)
    record = record_of(FX / "seeded")
    first = text.split("### e01 (s2_describe.py, edit)", 1)[1].split("###", 1)[0]
    assert "- **Stated reason:** %s" % record[0]["rationale"] in first
    assert "- **In the script now:** yes" in first
    second = text.split("### e02 (s1_clean.py, edit)", 1)[1].split("##", 1)[0]
    assert '- **Before:** `return [r for r in rows if r["income"].strip() != ""]`' in second
    assert '- **After:** `return [r for r in rows if r["age"].strip() != ""]`' in second
    assert "- **Stated reason:** No reason is recorded." in second


def test_each_parameter_the_ai_set_is_listed(seeded_run):
    text = report_of(seeded_run).split("## Parameters the AI set", 1)[1].split("\n## ", 1)[0]
    assert "| fig_width | 480 | 520 | 520 | s2_describe.py | e03 |" in text
    assert "Parameter fig_width came from session S7f3e2d1c0b9a." in text


def test_the_scripts_table_marks_the_ais_scripts(seeded_run):
    text = report_of(seeded_run).split("## Scripts", 1)[1].split("\n## ", 1)[0]
    assert "| s1_clean.py | clean | e02 | **no** |" in text
    assert "| s2_describe.py | describe | e01 | **no** |" in text
    assert "| s3_model.py | model | none | yes |" in text
    assert "| params_io.py | helper | none | yes |" in text


def test_no_report_names_an_absolute_path_or_a_harness_session_id(seeded_run):
    text = report_of(seeded_run)
    assert str(ROOT) not in text and "/Users/" not in text and "/tmp/" not in text
    for entry in record_of(FX / "seeded"):
        if entry.get("session"):
            assert entry["session"] not in text
    assert "Change e02 came from session S5a0c91e7d2b4." in text
    assert "Change params.yaml" not in text


# ---------------------------------------------------------------- the items

def test_items_are_numbers_then_ai_changes_then_parameters_then_problems(seeded_run):
    items = fields_of(seeded_run)["items"]
    assert [it["id"] for it in items[:8]] == NUMBERS + ["e01", "e02", "params.yaml:fig_width"]
    assert [it["kind"] for it in items[:8]] == ["number"] * 5 + ["change", "change", "parameter"]
    assert all(it["kind"] == "finding" for it in items[8:])
    assert all(it["needs_decision"] for it in items)


def test_a_number_from_ai_work_waits_for_the_scholar_and_one_from_the_scholars_code_does_not(clean_run):
    items = items_of(clean_run)
    assert items["mean_income_k_north"]["needs_decision"] is True
    assert items["mean_income_k_north"]["from_ai"] is True
    for key in ("alpha", "n_analytic", "p_income_k", "slope_income_k"):
        assert items[key]["needs_decision"] is False and items[key]["from_ai"] is False
    assert items["e01"]["needs_decision"] is True


def test_a_number_item_carries_what_check_numbers_found(seeded_run):
    items = items_of(seeded_run)
    slope = items["slope_income_k"]
    assert slope["kind"] == "number"
    assert {k: slope[k] for k in NUMBER_FIELDS} == {
        "key": "slope_income_k", "value": "0.015", "replayed": "0.011", "from": "table_model.csv",
        "ok": False, "agrees": "**no**"}
    assert slope["script"] == "s3_model.py"
    assert [f["check"] for f in slope["findings"]] == ["check_numbers"]
    other = [it for it in items.values() if it["kind"] == "finding"]
    assert other and all(not (NUMBER_FIELDS & set(it)) for it in other)


def test_an_ai_change_item_keeps_the_code_and_the_reason_word_for_word(seeded_run):
    items = items_of(seeded_run)
    record = {e["id"]: e for e in record_of(FX / "seeded")}
    for cid in ("e01", "e02"):
        it = items[cid]
        assert it["before"] == record[cid]["before"] and it["after"] == record[cid]["after"]
        assert it["path"] == record[cid]["path"] and it["change_kind"] == "edit"
    assert items["e01"]["rationale"] == record["e01"]["rationale"]
    assert "rationale" not in items["e02"]
    assert [f["check"] for f in items["e02"]["findings"]] == ["attribute_ai"]


def test_a_parameter_item_names_its_values_and_its_record(seeded_run):
    it = items_of(seeded_run)["params.yaml:fig_width"]
    assert (it["param"], it["param_before"], it["ai_value"], it["params_now"], it["record_id"]) == (
        "fig_width", "480", "520", "520", "e03")
    assert it["read_by"] == "s2_describe.py"
    assert [f["severity"] for f in it["findings"]] == ["warning"]


def test_report_is_written_by_the_one_builder(clean_run, seeded_run):
    for rd in (clean_run, seeded_run):
        code = next((rd / "code").glob("*_report"))
        assert sorted(p.name for p in code.iterdir()) == ["_lib.py", "_report.py", "report.py", "schema.yaml"]
        fields = fields_of(rd)
        assert fields["schema"] == {"stream": "data", "version": 2}
        assert set(fields["tables"]) == {"scripts", "steps", "raw", "params", "models"}
        inv = json.loads((rd / "files" / "inventory.json").read_text())
        assert [r["step"] for r in fields["tables"]["steps"]] == [s["id"] for s in inv["steps"]]
        assert json.loads((rd / "files" / "findings_completeness.json").read_text()) == []
        results = json.loads((rd / "results.json").read_text())
        keep = ("id", "kind", "summary", "findings", "needs_decision")
        assert [{k: it[k] for k in keep} for it in fields["items"]] == results["items"]


# ---------------------------------------------------------------- cases built from the clean files

def test_with_no_record_every_number_waits_and_the_report_says_so(tmp_path):
    inputs = copy_of(tmp_path)
    (inputs / "file_edits.yaml").unlink()
    rd = run_inputs(tmp_path / "run", inputs)
    assert loud(rd) == []
    notes = [f for f in findings(rd) if f["check"] == "attribute_ai"]
    assert [(f["severity"], f["item"]) for f in notes] == [("info", "file_edits.yaml")]
    items = items_of(rd)
    assert all(items[k]["needs_decision"] for k in NUMBERS)
    text = report_of(rd)
    assert "No record of the AI's file edits was given" in text
    assert "| slope_income_k | 0.011 | table_model.csv | s3_model.py | not known, no record |" in text


def test_an_empty_record_marks_nothing_as_the_ais(tmp_path):
    inputs = copy_of(tmp_path)
    write_record(inputs, [])
    rd = run_inputs(tmp_path / "run", inputs)
    assert loud(rd) == []
    items = items_of(rd)
    assert not any(items[k]["needs_decision"] for k in NUMBERS)
    text = report_of(rd)
    assert "no AI contributions to the scripts or the parameters were found in it." in text


def test_an_ai_change_whose_text_is_no_longer_in_the_script_is_a_warning(tmp_path):
    inputs = copy_of(tmp_path)
    record = record_of(inputs)
    record[0]["after"] = "        # A line the scholar later removed."
    write_record(inputs, record)
    rd = run_inputs(tmp_path / "run", inputs)
    assert [(f["check"], f["item"], f["severity"]) for f in loud(rd)] == [("attribute_ai", "e01", "warning")]
    assert "- **In the script now:** no" in report_of(rd)


def test_an_ai_change_to_the_helper_marks_every_number(tmp_path):
    inputs = copy_of(tmp_path)
    helper = (inputs / "params_io.py").read_text(encoding="utf-8")
    line = next(ln for ln in helper.splitlines() if "def file_sha256" in ln)
    write_record(inputs, [{"id": "e01", "path": "params_io.py", "kind": "edit", "before": "def f(name):",
                           "after": line, "rationale": "Name it for what it returns."}])
    rd = run_inputs(tmp_path / "run", inputs)
    assert loud(rd) == []
    items = items_of(rd)
    assert all(items[k]["needs_decision"] and items[k]["from_ai"] for k in NUMBERS)
    assert "| params_io.py | helper | e01 | yes |" in report_of(rd)


def test_a_write_of_params_yaml_lists_every_parameter_it_set(tmp_path):
    inputs = copy_of(tmp_path)
    text = (inputs / "params.yaml").read_text(encoding="utf-8")
    write_record(inputs, [{"id": "e01", "path": "params.yaml", "kind": "write", "before": "",
                           "after": text, "rationale": "Set the analysis choices."}])
    rd = run_inputs(tmp_path / "run", inputs)
    params = sorted(it["param"] for it in fields_of(rd)["items"] if it["kind"] == "parameter")
    assert params == ["alpha", "fig_height", "fig_width", "income_cap", "min_age", "model_formula",
                      "round_digits"]
    alpha = items_of(rd)["params.yaml:alpha"]
    assert alpha["param_before"] == "(not recorded)" and alpha["ai_value"] == "0.05"
    assert all(items_of(rd)[k]["needs_decision"] for k in NUMBERS)


def test_an_ai_set_parameter_with_no_reason_is_blocking(tmp_path):
    inputs = copy_of(tmp_path)
    write_record(inputs, [{"id": "e01", "path": "params.yaml", "kind": "edit",
                           "before": "alpha: 0.10", "after": "alpha: 0.05", "rationale": ""}])
    rd = run_inputs(tmp_path / "run", inputs)
    found = sorted((f["severity"], f["item"]) for f in loud(rd))
    assert found == [("blocking", "params.yaml:alpha"), ("warning", "params.yaml:alpha")]
    assert items_of(rd)["alpha"]["needs_decision"] is True


MODEL_NUMBERS = ["alpha", "n_analytic", "p_income_k", "slope_income_k"]


def test_an_edit_of_a_parameters_value_alone_is_found_on_its_line_in_params_yaml(tmp_path):
    """An Edit that replaces only the value names no parameter. The parameter is the one on
    the line of params.yaml that holds the edit's text after, and its value before is that
    line with the edit undone."""
    inputs = copy_of(tmp_path)
    write_record(inputs, [{"id": "e01", "path": "params.yaml", "kind": "edit", "before": "0.10 ",
                           "after": "0.05 ", "rationale": "Use the usual threshold."}])
    rd = run_inputs(tmp_path / "run", inputs)
    assert [(f["severity"], f["item"]) for f in loud(rd)] == [("warning", "params.yaml:alpha")]
    items = items_of(rd)
    alpha = items["params.yaml:alpha"]
    assert (alpha["param_before"], alpha["ai_value"], alpha["record_id"]) == ("0.1", "0.05", "e01")
    assert "e01" not in items
    for key in MODEL_NUMBERS:
        assert items[key]["needs_decision"] is True and items[key]["from_ai"] is True
    assert items["mean_income_k_north"]["needs_decision"] is False


def test_an_edit_of_params_yaml_whose_text_is_not_found_touches_every_parameter(tmp_path):
    """When no parameter can be named, the change is shown and every number whose scripts
    read a parameter comes from AI work."""
    inputs = copy_of(tmp_path)
    write_record(inputs, [{"id": "e01", "path": "params.yaml", "kind": "edit", "before": "0.10 ",
                           "after": "0.07 ", "rationale": "Try a looser threshold."}])
    rd = run_inputs(tmp_path / "run", inputs)
    assert [(f["severity"], f["item"]) for f in loud(rd)] == [("warning", "e01")]
    items = items_of(rd)
    assert items["e01"]["kind"] == "change" and items["e01"]["path"] == "params.yaml"
    assert not any(it["kind"] == "parameter" for it in items.values())
    for key in NUMBERS:
        assert items[key]["needs_decision"] is True and items[key]["from_ai"] is True
        assert items[key]["ai_cell"] == "yes, e01 in params.yaml"


def test_an_edit_of_a_comment_in_params_yaml_sets_no_parameter(tmp_path):
    inputs = copy_of(tmp_path)
    write_record(inputs, [{"id": "e01", "path": "params.yaml", "kind": "edit",
                           "before": "# model: threshold",
                           "after": "# model: threshold for the significant column",
                           "rationale": "Say what the threshold is for."}])
    rd = run_inputs(tmp_path / "run", inputs)
    assert loud(rd) == []
    items = items_of(rd)
    assert items["e01"]["kind"] == "change"
    assert not any(it["kind"] == "parameter" for it in items.values())
    assert not any(items[k]["needs_decision"] for k in NUMBERS)


@pytest.mark.parametrize("name", ["numbers.yml", "pipeline.yaml", "acquisition.yaml"])
def test_an_ai_edit_to_a_declaration_no_check_traces_is_noted_for_the_scholar(tmp_path, name):
    inputs = copy_of(tmp_path)
    write_record(inputs, [{"id": "e01", "path": name, "kind": "edit", "before": "a", "after": "b",
                           "rationale": "A change."}])
    rd = run_inputs(tmp_path / "run", inputs)
    assert loud(rd) == []
    notes = [f for f in findings(rd) if f["check"] == "attribute_ai"]
    assert [(f["severity"], f["item"]) for f in notes] == [("info", "e01")]
    assert name in notes[0]["message"]
    assert "e01" not in items_of(rd)


def test_a_write_of_a_script_is_shown_as_the_whole_file(tmp_path):
    inputs = copy_of(tmp_path)
    script = (inputs / "s3_model.py").read_text(encoding="utf-8")
    write_record(inputs, [{"id": "e01", "path": "s3_model.py", "kind": "write", "before": "",
                           "after": script, "rationale": "Write the model step.", "session_ref": "S0a1b2c3d4e5f"}])
    rd = run_inputs(tmp_path / "run", inputs)
    assert loud(rd) == []
    text = report_of(rd)
    assert "### e01 (s3_model.py, write)" in text
    assert "- **After:** the whole file, %d lines" % len(script.splitlines()) in text
    assert "Change e01 came from session S0a1b2c3d4e5f." in text
    assert items_of(rd)["slope_income_k"]["needs_decision"] is True


def test_a_record_entry_on_a_file_outside_the_pipeline_is_left_out(tmp_path):
    inputs = copy_of(tmp_path)
    write_record(inputs, [{"id": "e01", "path": "manuscript.md", "kind": "edit", "before": "a",
                           "after": "b", "rationale": "Prose, for the prose stream."}])
    rd = run_inputs(tmp_path / "run", inputs)
    assert loud(rd) == []
    assert "e01" not in items_of(rd)
    assert not any(items_of(rd)[k]["needs_decision"] for k in NUMBERS)


def test_a_number_the_rerun_did_not_give_still_shows_none(tmp_path):
    """A number whose source is not a pipeline output has no rerun value. Its rerun cell
    reads None, and fields.json marks the value not run for that number."""
    inputs = copy_of(tmp_path)
    nums = inputs / "numbers.yml"
    nums.write_text(nums.read_text().replace(
        "alpha: {value: \"0.05\", from: params_record_model.csv",
        "alpha: {value: \"0.05\", from: notes.csv"))
    rd = run_inputs(tmp_path / "run", inputs)
    text = report_of(rd)
    assert "| alpha | 0.05 | None | **no** |" in text
    assert "| alpha | 0.05 | notes.csv | (not a pipeline output) | no |" in text
    alpha = items_of(rd)["alpha"]
    assert alpha["replayed"] == {"not_run": "the rerun gave no value for this number"}
    assert alpha["summary"] == "alpha = 0.05, rerun (none), from notes.csv"
    # a number that does not come from the process is a problem the scholar sees
    assert alpha["needs_decision"] is True
    assert json.loads((rd / "files" / "findings_completeness.json").read_text()) == []


# ---------------------------------------------------------------- a script in a subfolder (V4)

SUB_SCRIPT = '''"""Count the rows of the raw file.

Purpose:
    Count the respondents in the raw file.
Inputs:
    raw.csv - one row per respondent.
Outputs:
    out.json - the count of rows, as n.
Parameters:
    none.
Assumptions:
    The first line names the columns.
"""
import json


def count(name):
    """Return the number of rows after the header line of the file name."""
    with open(name, encoding="utf-8") as f:
        return len(f.read().splitlines()) - 1


with open("out.json", "w", encoding="utf-8") as f:
    f.write(json.dumps({"n": count("raw.csv")}) + "\\n")
'''
SUB_RAW = "id,age\n1,30\n2,41\n3,52\n"


def nested_project(folder):
    """A small project whose one step's script is code/s1_count.py, as the data handoff
    copies it at its path inside the project (Track V, step V4)."""
    import hashlib
    folder.mkdir(parents=True)
    (folder / "code").mkdir()
    (folder / "code" / "s1_count.py").write_text(SUB_SCRIPT, encoding="utf-8")
    (folder / "raw.csv").write_text(SUB_RAW, encoding="utf-8")
    (folder / "out.json").write_text('{"n": 3}\n', encoding="utf-8")
    (folder / "pipeline.yaml").write_text(
        "steps:\n  - {id: count, kind: table, runner: python3, script: code/s1_count.py,\n"
        "     inputs: [raw.csv], outputs: [out.json]}\n", encoding="utf-8")
    digest = hashlib.sha256(SUB_RAW.encode("utf-8")).hexdigest()
    (folder / "acquisition.yaml").write_text(
        "raw:\n  - {file: raw.csv, sha256: \"sha256:%s\", source: synthetic, collected: 2026-10-31}\n"
        % digest, encoding="utf-8")
    (folder / "params.yaml").write_text("{}\n", encoding="utf-8")
    (folder / "numbers.yml").write_text(
        'numbers:\n  n: {value: "3", from: out.json, field: n}\n', encoding="utf-8")
    return folder


def test_a_script_in_a_subfolder_is_read_rerun_and_replayed(tmp_path):
    inputs = nested_project(tmp_path / "inputs")
    rd = run_inputs(tmp_path / "run", inputs)
    assert (rd / "files" / "code" / "s1_count.py").read_text(encoding="utf-8") == SUB_SCRIPT
    assert [f for f in findings(rd) if f["severity"] == "blocking"] == []
    assert not [f for f in loud(rd) if "missing" in f["message"]]
    assert items_of(rd)["n"]["agrees"] == "yes"
    assert "code/s1_count.py" in report_of(rd)
    manifest = json.loads((rd / "manifest.json").read_text())
    assert "code/s1_count.py" in manifest["inputs"]
    p = vg("verify", "--run", rd)
    assert p.returncode == 0, p.stdout + p.stderr


def test_an_ai_change_to_a_script_in_a_subfolder_is_shown(tmp_path):
    inputs = nested_project(tmp_path / "inputs")
    write_record(inputs, [{
        "id": "e01", "path": "code/s1_count.py", "kind": "edit",
        "before": "return len(f.read().splitlines())",
        "after": "return len(f.read().splitlines()) - 1",
        "rationale": "The header line is not a respondent.",
        "session": "sess-1", "session_ref": "S000000000001"}])
    rd = run_inputs(tmp_path / "run", inputs)
    change = items_of(rd)["e01"]
    assert change["path"] == "code/s1_count.py"
    assert change["rationale"] == "The header line is not a respondent."
    assert change["in_file_cell"] == "yes"
    assert items_of(rd)["n"]["ai_cell"] == "yes, e01 in code/s1_count.py"
    assert items_of(rd)["n"]["needs_decision"] is True


def test_hidden_folders_and_byte_code_stay_out_of_a_data_run(tmp_path):
    inputs = nested_project(tmp_path / "inputs")
    for rel in (".git/HEAD", "code/__pycache__/s1_count.cpython-39.pyc", "code/.notes"):
        path = inputs.joinpath(*rel.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"not an input\n")
    rd = run_inputs(tmp_path / "run", inputs)
    manifest = json.loads((rd / "manifest.json").read_text())
    assert [name for name in manifest["inputs"] if "/" in name] == ["code/s1_count.py"]
    assert not (rd / "files" / ".git").exists()
    assert not (rd / "files" / "code" / "__pycache__").exists()


def test_a_run_whose_steps_read_no_every_input_carries_no_subfolder(tmp_path):
    """Only a graph with a step that may read any input file, as the data procedure's
    inventory does, carries the inputs folder's subfolders into the run."""
    inputs = tmp_path / "inputs"
    shutil.copytree(str(ROOT / "fixtures" / "prose" / "clean"), str(inputs))
    (inputs / "sub").mkdir()
    (inputs / "sub" / "extra.md").write_text("not read\n", encoding="utf-8")
    rd = tmp_path / "run"
    p = vg("run", "graphs/prose.yaml", "--run", rd, "--inputs", inputs)
    assert p.returncode == 0, p.stdout + p.stderr
    manifest = json.loads((rd / "manifest.json").read_text())
    assert not [name for name in manifest["inputs"] if "/" in name]
    assert not (rd / "files" / "sub").exists()


def test_the_sample_projects_golden_copy_holds_after_the_sample_is_built(tmp_path, monkeypatch):
    """A4's second block builds the sample project in place, which leaves builds/ in it.
    The golden run reads the project's top-level files, as the data handoff copies them
    from a flat project, so the built files never enter the data run."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("make_golden",
                                                  str(ROOT / "tests" / "golden" / "make_golden.py"))
    maker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(maker)
    built = tmp_path / "sample_project"
    shutil.copytree(str(maker.SAMPLE), str(built))
    for rel in ("builds/manuscript/BUILDS.md", "builds/manuscript/v001.md", "__pycache__/params_io.pyc"):
        path = built.joinpath(*rel.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("built\n", encoding="utf-8")
    monkeypatch.setattr(maker, "SAMPLE", built)
    rd = tmp_path / "data_sample"
    proc = maker.run_procedure("data", "sample", rd)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    manifest = json.loads((rd / "manifest.json").read_text())
    assert not [name for name in manifest["inputs"] if "/" in name]
    for fname, path in sorted(maker.outputs(rd).items()):
        assert path.read_bytes() == (ROOT / "tests" / "golden" / "data_sample" / fname).read_bytes(), fname
