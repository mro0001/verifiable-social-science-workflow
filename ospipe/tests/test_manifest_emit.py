"""Manifest emitter contract tests: synthetic outputs from the fixture, and a
temporary copy of the sample project for the end-to-end case."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ospipe.foundation import load_manifest  # noqa: E402
from ospipe.manifest import EmitResult, ManifestEmitError, emit_manifest  # noqa: E402
from ospipe.manifest import fixture  # noqa: E402

OSPIPE_DIR = Path(__file__).resolve().parents[1]
SAMPLE_PROJECT = OSPIPE_DIR.parent / "examples" / "sample_project"


def _write_outputs(folder, outputs=None, csv_text=None):
    folder.mkdir(parents=True, exist_ok=True)
    data = fixture.OUTPUTS if outputs is None else outputs
    (folder / fixture.OUTPUTS_JSON_NAME).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    (folder / fixture.OUTPUTS_CSV_NAME).write_text(
        fixture.OUTPUTS_CSV if csv_text is None else csv_text, encoding="utf-8"
    )


def _changed_outputs():
    data = json.loads(fixture.OUTPUTS_JSON)
    data["run"]["cities"] = 25
    data["summary"]["smape"] = 34.25
    data["cities"][0]["smape"] = 11.5
    return data


@pytest.fixture()
def project(tmp_path):
    _write_outputs(tmp_path)
    manifest = tmp_path / "numbers.yml"
    manifest.write_text(fixture.MANIFEST_YAML, encoding="utf-8")
    return manifest


def _run_cli(args, cwd=None, env=None):
    return subprocess.run(
        [sys.executable, "-m", "ospipe", "emit-manifest"] + args,
        capture_output=True,
        text=True,
        cwd=str(cwd or OSPIPE_DIR),
        env=env,
    )


class TestLookups:
    def test_current_values_leave_the_file_byte_for_byte(self, project):
        before = project.read_bytes()
        result = emit_manifest(project)
        assert isinstance(result, EmitResult)
        assert result.changed == []
        assert list(result.unchanged) == list(fixture.MANIFEST_KEYS)
        assert project.read_bytes() == before

    def test_dotted_path_list_position_csv_row_whole_and_decimal(self, project):
        csv_text = fixture.OUTPUTS_CSV.replace("Alpha,2021,13.0", "Alpha,2021,14.5")
        _write_outputs(project.parent, _changed_outputs(), csv_text)
        result = emit_manifest(project)
        assert result.changed == [
            ("run.cities", "24", "25"),  # a whole number through str()
            ("summary.smape", "33.5", "34.25"),  # a decimal number through str()
            ("alpha.smape", "12.25", "11.5"),  # a list position
            ("alpha_2021.smape", "13.0", "14.5"),  # a CSV row chosen by where, text as it is
        ]
        assert result.unchanged == ["run.label", "summary.compliance"]
        values = load_manifest(project)
        assert values["run.cities"] == "25"
        assert values["summary.smape"] == "34.25"
        assert values["alpha.smape"] == "11.5"
        assert values["alpha_2021.smape"] == "14.5"
        assert values["summary.compliance"] == "98.2"  # a text value as it is

    def test_outputs_dir_defaults_to_the_manifest_folder_and_can_be_named(self, tmp_path):
        outputs = tmp_path / "outputs"
        _write_outputs(outputs, _changed_outputs())
        manifest = tmp_path / "config" / "numbers.yml"
        manifest.parent.mkdir()
        manifest.write_text(fixture.MANIFEST_YAML, encoding="utf-8")
        with pytest.raises(ManifestEmitError):
            emit_manifest(manifest)  # nothing beside the manifest
        result = emit_manifest(manifest, outputs_dir=outputs)
        assert ("run.cities", "24", "25") in result.changed

    def test_entry_with_no_value_is_filled(self, project):
        text = fixture.MANIFEST_YAML.replace(
            '  run.cities: {value: "24", from: widget_results.json, field: run.cities}',
            "  run.cities: {from: widget_results.json, field: run.cities}",
        )
        project.write_text(text, encoding="utf-8")
        result = emit_manifest(project)
        assert result.changed == [("run.cities", None, "24")]
        assert load_manifest(project)["run.cities"] == "24"


class TestProblems:
    def test_every_problem_is_reported_in_one_error_and_the_file_is_untouched(self, tmp_path):
        _write_outputs(tmp_path)
        manifest = tmp_path / "numbers.yml"
        manifest.write_text(fixture.PROBLEM_MANIFEST_YAML, encoding="utf-8")
        before = manifest.read_bytes()
        with pytest.raises(ManifestEmitError) as exc:
            emit_manifest(manifest)
        problems = exc.value.problems
        assert len(problems) == len(fixture.PROBLEM_KEYS)
        for key, problem in zip(fixture.PROBLEM_KEYS, problems):
            assert key in problem
        message = str(exc.value)
        for key in fixture.PROBLEM_KEYS:
            assert key in message
        assert manifest.read_bytes() == before

    def test_problem_wording_names_each_kind(self, tmp_path):
        _write_outputs(tmp_path)
        manifest = tmp_path / "numbers.yml"
        manifest.write_text(fixture.PROBLEM_MANIFEST_YAML, encoding="utf-8")
        with pytest.raises(ManifestEmitError) as exc:
            emit_manifest(manifest)
        by_key = dict(zip(fixture.PROBLEM_KEYS, exc.value.problems))
        assert "from" in by_key["no_from"]
        assert "field" in by_key["no_field"]
        assert "absent.json" in by_key["missing_file"]
        assert "run.nothing" in by_key["missing_json_field"]
        assert "cities.5.smape" in by_key["list_past_end"]
        assert "nothing" in by_key["missing_column"]
        assert "0 rows" in by_key["zero_rows"]
        assert "2 rows" in by_key["several_rows"]
        for key in ("refused_true", "refused_null", "refused_list", "refused_object"):
            assert "refused" in by_key[key]

    def test_a_good_entry_beside_a_problem_is_not_written(self, project):
        text = fixture.MANIFEST_YAML + "  ghost: {value: \"1\", from: absent.csv, field: smape}\n"
        project.write_text(text, encoding="utf-8")
        _write_outputs(project.parent, _changed_outputs())
        before = project.read_bytes()
        with pytest.raises(ManifestEmitError) as exc:
            emit_manifest(project)
        assert exc.value.problems == [p for p in exc.value.problems if "ghost" in p]
        assert project.read_bytes() == before

    @pytest.mark.parametrize(
        "text",
        [
            "widget_smape: \"33.5\"\n",  # the flat form
            "numbers:\n  a: {value: \"1\", from: x.json, field: a}\nother: 1\n",
            "numbers: [1, 2]\n",
            "- just a list\n",
        ],
    )
    def test_not_the_numbers_shape_is_refused(self, tmp_path, text):
        manifest = tmp_path / "numbers.yml"
        manifest.write_text(text, encoding="utf-8")
        with pytest.raises(ManifestEmitError, match="numbers:"):
            emit_manifest(manifest)
        assert manifest.read_text(encoding="utf-8") == text


class TestRewrite:
    def test_rewrite_keeps_leading_comments_order_and_other_fields(self, project):
        text = fixture.MANIFEST_YAML + (
            '  "2020": {value: "9.75", from: widget_table.csv, field: smape,'
            " where: {city: Beta, year: 2020, smape: 9.75}, note: kept as it is}\n"
        )
        project.write_text(text, encoding="utf-8")
        _write_outputs(project.parent, _changed_outputs())
        emit_manifest(project)
        written = project.read_text(encoding="utf-8")
        leading = fixture.MANIFEST_YAML.split("numbers:\n")[0]
        assert written.startswith(leading + "numbers:\n")
        body = written[len(leading) + len("numbers:\n"):].splitlines()
        assert body[0] == '  run.cities: {value: "25", from: "widget_results.json", field: "run.cities"}'
        assert body[5] == (
            '  alpha_2021.smape: {value: "13.0", from: "widget_table.csv", field: "smape",'
            ' where: {"city": "Alpha", "year": 2021}}'
        )
        loaded = yaml.safe_load(written)["numbers"]
        assert list(loaded) == list(fixture.MANIFEST_KEYS) + ["2020"]  # the key loads back as text
        assert loaded["2020"]["where"] == {"city": "Beta", "year": 2020, "smape": 9.75}
        assert loaded["2020"]["note"] == "kept as it is"
        assert list(loaded["2020"]) == ["value", "from", "field", "where", "note"]
        values = load_manifest(project)
        assert values["run.cities"] == "25"
        assert values["2020"] == "9.75"

    def test_every_value_loads_back_as_the_same_text(self, tmp_path):
        tricky = {
            "quote": 'a "quoted" word',
            "slash": "back\\slash and a: colon",
            "accent": "café   line and \U0001F600",
            "hash": "# not a comment",
            "number_like": "0.050",
        }
        (tmp_path / "t.json").write_text(json.dumps(tricky), encoding="utf-8")
        lines = ["numbers:"]
        for key in tricky:
            lines.append("  {0}: {{from: t.json, field: {0}}}".format(key))
        manifest = tmp_path / "numbers.yml"
        manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = emit_manifest(manifest)
        assert [c[0] for c in result.changed] == list(tricky)
        assert load_manifest(manifest) == tricky
        # a second pass finds nothing to change and leaves the file alone
        before = manifest.read_bytes()
        assert emit_manifest(manifest).changed == []
        assert manifest.read_bytes() == before


class TestCommand:
    def test_cli_prints_changes_or_unchanged(self, project):
        same = _run_cli(["--manifest", str(project)])
        assert same.returncode == 0, same.stderr
        assert same.stdout == "{0} unchanged\n".format(project)
        _write_outputs(project.parent, _changed_outputs())
        moved = _run_cli(["--manifest", str(project), "--outputs-dir", str(project.parent)])
        assert moved.returncode == 0, moved.stderr
        assert moved.stdout.splitlines() == [
            "run.cities: 24 -> 25",
            "summary.smape: 33.5 -> 34.25",
            "alpha.smape: 12.25 -> 11.5",
        ]

    def test_cli_exits_2_listing_every_problem(self, tmp_path):
        _write_outputs(tmp_path)
        manifest = tmp_path / "numbers.yml"
        manifest.write_text(fixture.PROBLEM_MANIFEST_YAML, encoding="utf-8")
        run = _run_cli(["--manifest", str(manifest)])
        assert run.returncode == 2
        for key in fixture.PROBLEM_KEYS:
            assert key in run.stderr
        assert manifest.read_text(encoding="utf-8") == fixture.PROBLEM_MANIFEST_YAML


def _checksums(folder):
    sums = {}
    for path in sorted(Path(folder).rglob("*")):
        if path.is_file():
            sums[str(path.relative_to(folder))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return sums


def _docx_to_plain(docx_path):
    proc = subprocess.run(
        ["pandoc", "--from", "docx", "--to", "plain", str(docx_path)], capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


class TestSampleProject:
    def test_rerun_then_emit_carries_a_changed_count_into_the_build(self, tmp_path):
        original = _checksums(SAMPLE_PROJECT)
        copy = tmp_path / "sample_project"
        shutil.copytree(str(SAMPLE_PROJECT), str(copy), ignore=shutil.ignore_patterns("__pycache__", "builds"))
        env = dict(os.environ, PYTHONPATH=str(OSPIPE_DIR))
        numbers_before = (copy / "numbers.yml").read_bytes()

        script = subprocess.run([sys.executable, "s1_results.py"], cwd=str(copy), capture_output=True, text=True)
        assert script.returncode == 0, script.stderr
        same = _run_cli(["--manifest", "numbers.yml"], cwd=copy, env=env)
        assert same.returncode == 0, same.stderr
        assert same.stdout == "numbers.yml unchanged\n"
        assert (copy / "numbers.yml").read_bytes() == numbers_before

        counts_path = copy / "next_word_counts.json"
        counts = json.loads(counts_path.read_text(encoding="utf-8"))
        none = [c for c in counts["conditions"] if c["key"] == "none"][0]
        assert none["top"][0]["count"] == 18
        none["top"][0]["count"] = 21
        counts_path.write_text(json.dumps(counts, indent=2) + "\n", encoding="utf-8")
        script = subprocess.run([sys.executable, "s1_results.py"], cwd=str(copy), capture_output=True, text=True)
        assert script.returncode == 0, script.stderr

        moved = _run_cli(["--manifest", "numbers.yml"], cwd=copy, env=env)
        assert moved.returncode == 0, moved.stderr
        assert moved.stdout.splitlines() == ["none.top_pct: 30.0 -> 35.0"]
        assert load_manifest(copy / "numbers.yml")["none.top_pct"] == "35.0"

        built = subprocess.run(
            [
                sys.executable, "-m", "ospipe", "build",
                "--manuscript", "manuscript.md", "--manifest", "numbers.yml", "--tables-dir", ".",
                "--bib", "refs.bib", "--builds-dir", "builds/manuscript", "--purpose", "after the rerun",
            ],
            cwd=str(copy), capture_output=True, text=True, env=env,
        )
        assert built.returncode == 0, built.stderr
        assert "35.0" in (copy / "builds" / "manuscript" / "v001.md").read_text(encoding="utf-8")
        assert "35.0" in _docx_to_plain(copy / "builds" / "manuscript" / "v001.docx")

        assert _checksums(SAMPLE_PROJECT) == original
