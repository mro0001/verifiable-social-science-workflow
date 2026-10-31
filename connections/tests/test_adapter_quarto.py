"""Tests for the Quarto adapter (Track D, step D13).

The proposal names an adapter for Quarto as designed but not built (Status
paragraph 2), and Table A6 lists it as specified. The data procedure's
conventions put Quarto parameters in the YAML header and give a Quarto step
runner quarto render. The Quarto adapter reads each document's header block
from the comment lines that open its first code chunk, writes pipeline.yaml,
and writes the front matter's params to params.yaml (Track D choice 17).
Quarto is never run.

Every document here is synthetic .qmd text the test writes. Every test runs
with HOME, CONNECTIONS_HOME, and AUDIT_HOME inside a temporary folder. Run
from the repository root with python3 -m pytest -q connections/tests.
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

from connections.adapters import ADAPTERS, quarto  # noqa: E402
from connections.cli import main  # noqa: E402

CLEAN = """---
title: Clean the survey
params:
  min_age: 18
  income_cap: 250000
---

Some prose before the code.

```{r}
#| label: clean
#| echo: false
# Purpose:
#     Drop rows with no income and keep adults only.
# Inputs:
#     raw_survey.csv - one row per respondent as collected.
# Outputs:
#     clean_survey.csv - the analytic rows.
# Parameters:
#     min_age - respondents younger than this are excluded.
# Assumptions:
#     A blank cell means missing.
library(yaml)
```

```{r}
# Outputs:
#     second_chunk.csv - only the first chunk is read.
```
"""

MODEL = """---
title: Fit the model
params:
  income_cap: 250000
  alpha: 0.05
---

```{python}
#| label: fit
# Kind: model
# Purpose:
#     Regress satisfaction on income.
# Inputs:
#     clean_survey.csv - the analytic rows.
# Outputs:
#     table_model.csv - the coefficients.
x = 1
```
"""

PLAIN = """# A document with no front matter

```{r}
x <- 1
```
"""

NESTED = """---
params:
  bands:
    low: 1
    high: 2
---
"""

CONFLICT = """---
params:
  min_age: 21
---
"""

BROKEN = """---
params: [unclosed
---
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
    for name, text in (
        ("s1_clean.qmd", CLEAN),
        ("s3_model.qmd", MODEL),
        ("plain.qmd", PLAIN),
        ("nested.qmd", NESTED),
        ("conflict.qmd", CONFLICT),
        ("broken.qmd", BROKEN),
    ):
        (folder / name).write_text(text, encoding="utf-8")
    monkeypatch.chdir(folder)
    return folder


def load(out, name):
    return yaml.safe_load((out / name).read_text(encoding="utf-8"))


def test_the_quarto_adapter_is_registered_for_the_data_stream():
    adapter = ADAPTERS["quarto"]
    assert adapter.stream == "data"
    assert tuple(adapter.fills) == ("pipeline.yaml", "params.yaml")


def test_front_matter_params_become_params_yaml_in_order(project, tmp_path):
    out = tmp_path / "out"
    assert main(["adapt", "quarto", "--out", str(out), "--docs", "s1_clean.qmd", "s3_model.qmd"]) == 0
    params = load(out, "params.yaml")
    assert params == {"min_age": 18, "income_cap": 250000, "alpha": 0.05}
    assert list(params) == ["min_age", "income_cap", "alpha"]


def test_the_first_chunk_gives_the_steps_inputs_and_outputs(project, tmp_path):
    out = tmp_path / "out"
    main(["adapt", "quarto", "--out", str(out), "--docs", "s1_clean.qmd", "s3_model.qmd"])
    steps = load(out, "pipeline.yaml")["steps"]
    assert steps == [
        {"id": "s1_clean", "kind": "step", "runner": "quarto render", "script": "s1_clean.qmd",
         "inputs": ["raw_survey.csv"], "outputs": ["clean_survey.csv"]},
        {"id": "s3_model", "kind": "model", "runner": "quarto render", "script": "s3_model.qmd",
         "inputs": ["clean_survey.csv"], "outputs": ["table_model.csv"]},
    ]
    assert load(out, "pipeline.yaml")["helpers"] == []


def test_chunk_options_are_skipped_and_later_chunks_are_not_read(project, tmp_path):
    out = tmp_path / "out"
    main(["adapt", "quarto", "--out", str(out), "--docs", "s1_clean.qmd"])
    text = (out / "pipeline.yaml").read_text(encoding="utf-8")
    assert "label" not in text and "echo" not in text
    assert "second_chunk.csv" not in text


def test_a_nested_parameter_is_refused_with_its_name_and_nothing_written(project, tmp_path, capsys):
    out = tmp_path / "out"
    assert main(["adapt", "quarto", "--out", str(out), "--docs", "s1_clean.qmd", "nested.qmd"]) == 1
    err = capsys.readouterr().err
    assert "bands" in err and "nested.qmd" in err
    assert not out.exists()


def test_one_name_with_two_values_is_refused_with_its_name_and_nothing_written(project, tmp_path, capsys):
    out = tmp_path / "out"
    assert main(["adapt", "quarto", "--out", str(out), "--docs", "s1_clean.qmd", "conflict.qmd"]) == 1
    err = capsys.readouterr().err
    assert "min_age" in err
    assert not out.exists()


def test_one_name_with_the_same_value_twice_is_kept_once(project, tmp_path):
    out = tmp_path / "out"
    main(["adapt", "quarto", "--out", str(out), "--docs", "s1_clean.qmd", "s3_model.qmd"])
    assert (out / "params.yaml").read_text(encoding="utf-8").count("income_cap") == 1


def test_a_document_without_front_matter_gives_empty_params(project, tmp_path):
    out = tmp_path / "out"
    assert main(["adapt", "quarto", "--out", str(out), "--docs", "plain.qmd"]) == 0
    assert (out / "params.yaml").read_text(encoding="utf-8") == "{}\n"
    assert load(out, "pipeline.yaml")["steps"] == [
        {"id": "plain", "kind": "step", "runner": "quarto render", "script": "plain.qmd",
         "inputs": [], "outputs": []}
    ]


def test_front_matter_that_is_not_yaml_is_refused(project, tmp_path, capsys):
    out = tmp_path / "out"
    assert main(["adapt", "quarto", "--out", str(out), "--docs", "broken.qmd"]) == 1
    assert "broken.qmd" in capsys.readouterr().err
    assert not out.exists()


def test_the_record_names_each_document_and_both_files(project, tmp_path):
    out = tmp_path / "out"
    main(["adapt", "quarto", "--out", str(out), "--docs", "s1_clean.qmd", "s3_model.qmd"])
    record = json.loads((out / "adapter_record.json").read_text(encoding="utf-8"))
    assert record["adapter"] == "quarto"
    assert record["stream"] == "data"
    assert sorted(record["read"]) == ["s1_clean.qmd", "s3_model.qmd"]
    assert sorted(record["wrote"]) == ["params.yaml", "pipeline.yaml"]


def test_the_same_documents_give_the_same_bytes(project, tmp_path):
    one, two = tmp_path / "one", tmp_path / "two"
    for out in (one, two):
        main(["adapt", "quarto", "--out", str(out), "--docs", "s1_clean.qmd", "s3_model.qmd"])
    for name in ("pipeline.yaml", "params.yaml", "adapter_record.json"):
        assert (one / name).read_bytes() == (two / name).read_bytes()


def test_docs_are_required(project, tmp_path):
    with pytest.raises(SystemExit) as stop:
        main(["adapt", "quarto", "--out", str(tmp_path / "out")])
    assert stop.value.code == 2


def test_quarto_is_never_run(project, tmp_path):
    empty = tmp_path / "no_programs"
    empty.mkdir()
    env = dict(os.environ)
    env["PATH"] = str(empty)
    env["PYTHONPATH"] = str(ROOT)
    out = tmp_path / "out"
    done = subprocess.run(
        [sys.executable, "-m", "connections", "adapt", "quarto", "--out", str(out),
         "--docs", "s1_clean.qmd", "s3_model.qmd"],
        cwd=str(project),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 0, done.stderr
    assert [s["id"] for s in load(out, "pipeline.yaml")["steps"]] == ["s1_clean", "s3_model"]
    source = Path(quarto.__file__).read_text(encoding="utf-8")
    for name in ("subprocess", "os.system"):
        assert name not in source


def test_the_module_imports_no_other_layer():
    source = Path(quarto.__file__).read_text(encoding="utf-8")
    for layer in ("audit_layer", "ospipe", "verification_procedures", "observability", "features"):
        assert "import " + layer not in source and "from " + layer not in source
