"""Tests for the R adapter and the header reader (Track D, step D12).

The proposal names an adapter for R as designed but not built (Status
paragraph 2), and Table A6 lists it as specified. The data procedure's
conventions say R binds the same contract with runner Rscript, and that each
script opens with the sections Purpose, Inputs, Outputs, Parameters, and
Assumptions. The R adapter reads those sections from the comment lines at the
top of each script, and an optional Kind line, and writes pipeline.yaml
(Track D choice 17). Scripts are read, never run.

Every R script here is synthetic text the test writes. Every test runs with
HOME, CONNECTIONS_HOME, and AUDIT_HOME inside a temporary folder. Run from the
repository root with python3 -m pytest -q connections/tests.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from connections.adapters import ADAPTERS, headers, r  # noqa: E402
from connections.adapters.headers import file_names, header_lines, kind_of, sections  # noqa: E402
from connections.cli import main  # noqa: E402

CLEAN = """#!/usr/bin/env Rscript
#' Clean the raw survey into the analytic file.
#'
#' Purpose:
#'     Drop rows with no income and keep adults only.
#' Inputs:
#'     raw_survey.csv - one row per respondent as collected.
#'     never edited by any step.
#' Outputs:
#'     clean_survey.csv - the analytic rows.
#'     params_record_clean.csv - the parameters this run read.
#' Parameters:
#'     min_age - respondents younger than this are excluded.
#' Assumptions:
#'     A blank cell means missing.
library(yaml)
# Outputs:
#     not_a_header.csv - a comment after the code starts is not read.
"""

MODEL = """# Fit the satisfaction model.
#
# Kind: model
# Purpose:
#     Regress satisfaction on income.
# Inputs:
#     clean_survey.csv - the analytic rows.
# Outputs:
#     table_model.csv - the coefficients.
#     model_record_model.json - the model record, written by the run.
# Parameters:
#     none
# Assumptions:
#     Income enters in thousands.
p <- yaml::read_yaml("params.yaml")
"""

BARE = """library(yaml)
x <- 1
"""


@pytest.fixture(autouse=True)
def homes(tmp_path, monkeypatch):
    user = tmp_path / "user"
    user.mkdir()
    monkeypatch.setenv("HOME", str(user))
    monkeypatch.setenv("CONNECTIONS_HOME", str(tmp_path / "connections_home"))
    monkeypatch.setenv("AUDIT_HOME", str(tmp_path / "audit_home"))
    return tmp_path


@pytest.fixture
def project(tmp_path, monkeypatch):
    folder = tmp_path / "project"
    folder.mkdir()
    (folder / "s1_clean.R").write_text(CLEAN, encoding="utf-8")
    (folder / "s3_model.R").write_text(MODEL, encoding="utf-8")
    (folder / "bare.R").write_text(BARE, encoding="utf-8")
    (folder / "params_io.R").write_text("# Purpose:\n#     Read params.yaml.\n", encoding="utf-8")
    monkeypatch.chdir(folder)
    return folder


def pipeline(out):
    return yaml.safe_load((out / "pipeline.yaml").read_text(encoding="utf-8"))


# The header reader.


def test_header_lines_drop_the_mark_and_one_space_and_skip_the_first_bang_line():
    lines = header_lines(CLEAN, ("#'", "#"))
    assert lines[0] == "Clean the raw survey into the analytic file."
    assert lines[1] == ""
    assert lines[2] == "Purpose:"
    assert lines[3] == "    Drop rows with no income and keep adults only."
    assert lines[-1] == "    A blank cell means missing."


def test_header_lines_stop_at_the_first_line_that_is_not_a_comment():
    lines = header_lines(CLEAN, ("#'", "#"))
    assert not any("not_a_header" in line for line in lines)


def test_header_lines_skip_lines_starting_with_bar():
    text = "#| label: setup\n#| echo: false\n# Purpose:\n#     Set up.\nx <- 1\n"
    assert header_lines(text, ("#",)) == ["Purpose:", "    Set up."]


def test_a_bang_line_after_the_first_line_ends_nothing_and_is_kept_as_a_comment():
    text = "# Purpose:\n#!     kept\n"
    assert header_lines(text, ("#",)) == ["Purpose:", "!     kept"]


def test_header_lines_of_a_text_with_no_header_are_empty():
    assert header_lines(BARE, ("#'", "#")) == []
    assert header_lines("", ("#",)) == []


def test_sections_split_at_the_five_names_at_the_left_margin():
    found = sections(header_lines(CLEAN, ("#'", "#")))
    assert sorted(found) == ["Assumptions", "Inputs", "Outputs", "Parameters", "Purpose"]
    assert found["Inputs"] == [
        "    raw_survey.csv - one row per respondent as collected.",
        "    never edited by any step.",
    ]


def test_sections_ignore_other_names_and_indented_names():
    lines = ["Purpose:", "    Do it.", "Notes:", "    kept under Purpose.", "  Inputs:", "    a.csv"]
    found = sections(lines)
    assert sorted(found) == ["Purpose"]
    assert found["Purpose"] == ["    Do it.", "Notes:", "    kept under Purpose.", "  Inputs:", "    a.csv"]


def test_kind_of_reads_the_kind_line():
    assert kind_of(header_lines(MODEL, ("#'", "#"))) == "model"
    assert kind_of(header_lines(CLEAN, ("#'", "#"))) is None


def test_file_names_take_the_first_word_when_it_ends_in_a_dot_and_an_extension():
    section = [
        "    clean_survey.csv - the analytic rows.",
        "    written once per run, see table.csv",
        "    0.5 is the cutoff, not a file.",
        "",
        "    model_record_model.json - the model record.",
    ]
    assert file_names(section) == ["clean_survey.csv", "model_record_model.json"]


# The R adapter.


def test_the_r_adapter_is_registered_for_the_data_stream():
    adapter = ADAPTERS["r"]
    assert adapter.stream == "data"
    assert tuple(adapter.fills) == ("pipeline.yaml",)


def test_two_documented_scripts_give_two_steps_in_order(project, tmp_path):
    out = tmp_path / "out"
    code = main(["adapt", "r", "--out", str(out), "--scripts", "s1_clean.R", "s3_model.R"])
    assert code == 0
    steps = pipeline(out)["steps"]
    assert [s["id"] for s in steps] == ["s1_clean", "s3_model"]
    assert steps[0]["script"] == "s1_clean.R"
    assert steps[0]["inputs"] == ["raw_survey.csv"]
    assert steps[0]["outputs"] == ["clean_survey.csv", "params_record_clean.csv"]
    assert steps[1]["inputs"] == ["clean_survey.csv"]
    assert steps[1]["outputs"] == ["table_model.csv", "model_record_model.json"]
    assert all(s["runner"] == "Rscript" for s in steps)


def test_the_kind_line_is_kept_and_step_is_the_default(project, tmp_path):
    out = tmp_path / "out"
    main(["adapt", "r", "--out", str(out), "--scripts", "s1_clean.R", "s3_model.R"])
    steps = pipeline(out)["steps"]
    assert steps[0]["kind"] == "step"
    assert steps[1]["kind"] == "model"


def test_a_script_with_no_header_gives_empty_inputs_and_outputs(project, tmp_path):
    out = tmp_path / "out"
    main(["adapt", "r", "--out", str(out), "--scripts", "bare.R"])
    assert pipeline(out)["steps"] == [
        {"id": "bare", "kind": "step", "runner": "Rscript", "script": "bare.R", "inputs": [], "outputs": []}
    ]


def test_helpers_are_listed_and_default_to_none(project, tmp_path):
    one, two = tmp_path / "one", tmp_path / "two"
    main(["adapt", "r", "--out", str(one), "--scripts", "s1_clean.R", "--helpers", "params_io.R"])
    main(["adapt", "r", "--out", str(two), "--scripts", "s1_clean.R"])
    assert pipeline(one)["helpers"] == ["params_io.R"]
    assert pipeline(two)["helpers"] == []


def test_every_step_has_the_keys_the_data_inventory_reads(project, tmp_path):
    out = tmp_path / "out"
    main(["adapt", "r", "--out", str(out), "--scripts", "s1_clean.R", "s3_model.R", "bare.R"])
    loaded = pipeline(out)
    assert sorted(loaded) == ["helpers", "steps"]
    for step in loaded["steps"]:
        assert list(step) == ["id", "kind", "runner", "script", "inputs", "outputs"]
        assert isinstance(step["inputs"], list) and isinstance(step["outputs"], list)


def test_the_record_names_every_script_and_helper_read(project, tmp_path):
    out = tmp_path / "out"
    main(["adapt", "r", "--out", str(out), "--scripts", "s1_clean.R", "--helpers", "params_io.R"])
    record = json.loads((out / "adapter_record.json").read_text(encoding="utf-8"))
    assert record["adapter"] == "r"
    assert record["stream"] == "data"
    assert sorted(record["read"]) == ["params_io.R", "s1_clean.R"]
    assert sorted(record["wrote"]) == ["pipeline.yaml"]


def test_the_same_scripts_give_the_same_bytes(project, tmp_path):
    one, two = tmp_path / "one", tmp_path / "two"
    for out in (one, two):
        main(["adapt", "r", "--out", str(out), "--scripts", "s1_clean.R", "s3_model.R"])
    for name in ("pipeline.yaml", "adapter_record.json"):
        assert (one / name).read_bytes() == (two / name).read_bytes()


def test_a_missing_script_is_refused_and_nothing_is_written(project, tmp_path, capsys):
    out = tmp_path / "out"
    assert main(["adapt", "r", "--out", str(out), "--scripts", "s1_clean.R", "gone.R"]) == 1
    assert "gone.R" in capsys.readouterr().err
    assert not out.exists()


def test_scripts_are_required(project, tmp_path):
    with pytest.raises(SystemExit) as stop:
        main(["adapt", "r", "--out", str(tmp_path / "out")])
    assert stop.value.code == 2


def test_the_adapter_runs_with_rscript_off_the_path(project, tmp_path):
    empty = tmp_path / "no_programs"
    empty.mkdir()
    env = dict(os.environ)
    env["PATH"] = str(empty)
    env["PYTHONPATH"] = str(ROOT)
    out = tmp_path / "out"
    done = subprocess.run(
        [sys.executable, "-m", "connections", "adapt", "r", "--out", str(out),
         "--scripts", "s1_clean.R", "s3_model.R"],
        cwd=str(project),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 0, done.stderr
    assert [s["id"] for s in pipeline(out)["steps"]] == ["s1_clean", "s3_model"]


def test_the_modules_import_no_other_layer():
    for module in (headers, r):
        source = Path(module.__file__).read_text(encoding="utf-8")
        for layer in ("audit_layer", "ospipe", "verification_procedures", "observability", "features"):
            assert "import " + layer not in source and "from " + layer not in source
        for name in ("subprocess", "os.system"):
            assert name not in source
