"""The citation evidence file.

Each citation in the citations results file, with the scholar's decision on the file's
run and, from the citation log, who introduced it and in which session. The results
files and the citation log are synthetic (`ospipe/evidence/fixture.py`). Nothing here
calls a model or the network.
"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ospipe.evidence import CITEKEY_FIELD, EvidenceError, citation_evidence  # noqa: E402
from ospipe.evidence import fixture  # noqa: E402

OSPIPE_DIR = Path(__file__).resolve().parents[1]
TOP_KEYS = ["schema", "schema_version", "results_file", "results_sha256", "run_id", "procedure_version", "items"]
ITEM_KEYS = ["id", "needs_decision", "decision", "by", "at", "introduced_by", "session", "item"]


@pytest.fixture()
def folder(tmp_path):
    fixture.write_results(tmp_path / "verification", "citations", fixture.evidence_results())
    return tmp_path / "verification"


@pytest.fixture()
def log(tmp_path):
    path = tmp_path / "audit" / "citation_log.yaml"
    path.parent.mkdir()
    path.write_text(fixture.CITATION_LOG_YAML, encoding="utf-8")
    return path


def by_id(evidence):
    return {item["id"]: item for item in evidence["items"]}


class TestCitationEvidence:
    def test_the_citekey_field_is_the_one_a_references_run_writes(self):
        assert CITEKEY_FIELD == "citekey"

    def test_the_top_keys_in_order(self, folder):
        evidence = citation_evidence(folder)
        assert list(evidence) == TOP_KEYS
        assert evidence["schema"] == "citation-evidence"
        assert evidence["schema_version"] == 1
        path = folder / "citations.json"
        assert evidence["results_file"] == str(path)
        assert evidence["results_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert evidence["run_id"] == fixture.RUN_ID
        assert evidence["procedure_version"] == 0.1

    def test_each_item_in_the_results_order_with_its_keys(self, folder):
        evidence = citation_evidence(folder)
        assert [item["id"] for item in evidence["items"]] == ["r01", "r02", "r03", "r04", "r05"]
        for item in evidence["items"]:
            assert list(item) == ITEM_KEYS

    def test_the_results_item_is_copied_unchanged(self, folder):
        results = json.loads((folder / "citations.json").read_text(encoding="utf-8"))
        evidence = citation_evidence(folder)
        assert [item["item"] for item in evidence["items"]] == results["items"]

    def test_an_approved_item(self, folder):
        item = by_id(citation_evidence(folder))["r01"]
        assert (item["needs_decision"], item["decision"], item["by"], item["at"]) == (
            True,
            "approved",
            "scholar",
            fixture.AT,
        )

    def test_a_held_item(self, folder):
        item = by_id(citation_evidence(folder))["r02"]
        assert (item["decision"], item["by"], item["at"]) == ("held", fixture.HELD_BY, fixture.HELD_AT)

    def test_an_undecided_item(self, folder):
        item = by_id(citation_evidence(folder))["r03"]
        assert (item["decision"], item["by"], item["at"]) == ("undecided", "", "")

    def test_an_authors_warrant_item_needs_no_decision(self, folder):
        item = by_id(citation_evidence(folder))["r04"]
        assert (item["needs_decision"], item["decision"], item["by"], item["at"]) == (
            False,
            "not needed",
            "",
            "",
        )

    def test_an_approval_on_an_older_run_does_not_count(self, folder):
        item = by_id(citation_evidence(folder))["r05"]
        assert (item["decision"], item["by"], item["at"]) == ("undecided", "", "")

    def test_the_citation_log_joins_on_the_citekey(self, folder, log):
        items = by_id(citation_evidence(folder, citation_log=log))
        for row_id in ("r02", "r03"):
            assert (items[row_id]["introduced_by"], items[row_id]["session"]) == ("ai", fixture.SESSION)
        for row_id in ("r01", "r04", "r05"):
            assert (items[row_id]["introduced_by"], items[row_id]["session"]) == ("", "")

    def test_without_a_citation_log_both_are_empty(self, folder):
        for item in citation_evidence(folder)["items"]:
            assert (item["introduced_by"], item["session"]) == ("", "")


def damage_results(folder, damage):
    path = folder / "citations.json"
    folder.mkdir(parents=True, exist_ok=True)
    data = fixture.evidence_results()
    if damage == "missing":
        return
    if damage == "bad_json":
        path.write_text("{not json", encoding="utf-8")
        return
    if damage == "wrong_schema":
        data["schema"] = "verification-report"
    elif damage == "schema_version_2":
        data["schema_version"] = 2
    elif damage == "schema_version_true":
        data["schema_version"] = True
    elif damage == "item_without_id":
        del data["items"][0]["id"]
    path.write_text(json.dumps(data), encoding="utf-8")


DAMAGES = ["missing", "bad_json", "wrong_schema", "schema_version_2", "schema_version_true", "item_without_id"]


class TestRefusals:
    @pytest.mark.parametrize("damage", DAMAGES)
    def test_a_results_file_it_cannot_read_is_refused(self, tmp_path, damage):
        folder = tmp_path / "verification"
        damage_results(folder, damage)
        with pytest.raises(EvidenceError):
            citation_evidence(folder)

    @pytest.mark.parametrize("text", ["citations: [not, a, mapping]\n", "{broken: [\n", "- a list\n"])
    def test_a_citation_log_it_cannot_read_is_refused(self, folder, tmp_path, text):
        bad = tmp_path / "bad_log.yaml"
        bad.write_text(text, encoding="utf-8")
        with pytest.raises(EvidenceError):
            citation_evidence(folder, citation_log=bad)

    def test_a_named_citation_log_that_is_missing_is_refused(self, folder, tmp_path):
        with pytest.raises(EvidenceError):
            citation_evidence(folder, citation_log=tmp_path / "no_such.yaml")


def run_cli(cwd, *args):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(OSPIPE_DIR)
    return subprocess.run(
        [sys.executable, "-m", "ospipe", "citation-evidence"] + [str(a) for a in args],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=env,
    )


class TestCommandLine:
    def test_writes_yaml_that_loads_and_matches_the_function(self, folder, log, tmp_path):
        out = tmp_path / "citation_evidence.yaml"
        run = run_cli(
            tmp_path, "--verification-dir", folder, "--citation-log", log, "--out", out
        )
        assert run.returncode == 0, run.stderr
        loaded = yaml.safe_load(out.read_text(encoding="utf-8"))
        assert loaded == citation_evidence(folder, citation_log=log)
        assert list(loaded) == TOP_KEYS

    def test_the_same_inputs_give_byte_identical_output(self, folder, log, tmp_path):
        first, second = tmp_path / "first.yaml", tmp_path / "second.yaml"
        for out in (first, second):
            run = run_cli(tmp_path, "--verification-dir", folder, "--citation-log", log, "--out", out)
            assert run.returncode == 0, run.stderr
        assert first.read_bytes() == second.read_bytes()

    def test_the_defaults_are_the_projects_verification_and_audit_folders(self, folder, log, tmp_path):
        # tmp_path holds verification/citations.json and audit/citation_log.yaml
        run = run_cli(tmp_path, "--out", "evidence.yaml")
        assert run.returncode == 0, run.stderr
        loaded = yaml.safe_load((tmp_path / "evidence.yaml").read_text(encoding="utf-8"))
        assert loaded["results_file"] == str(Path("verification") / "citations.json")
        assert by_id(loaded)["r02"]["session"] == fixture.SESSION

    def test_without_the_default_citation_log_the_join_is_empty(self, folder, tmp_path):
        run = run_cli(tmp_path, "--out", "evidence.yaml")
        assert run.returncode == 0, run.stderr
        loaded = yaml.safe_load((tmp_path / "evidence.yaml").read_text(encoding="utf-8"))
        assert all(item["session"] == "" for item in loaded["items"])

    @pytest.mark.parametrize("damage", DAMAGES)
    def test_each_refusal_exits_2_and_writes_nothing(self, tmp_path, damage):
        damage_results(tmp_path / "verification", damage)
        out = tmp_path / "evidence.yaml"
        run = run_cli(tmp_path, "--out", out)
        assert run.returncode == 2
        assert run.stderr.strip()
        assert not out.exists()

    def test_a_named_citation_log_that_is_missing_exits_2(self, folder, tmp_path):
        out = tmp_path / "evidence.yaml"
        run = run_cli(tmp_path, "--citation-log", tmp_path / "no_such.yaml", "--out", out)
        assert run.returncode == 2
        assert not out.exists()

    def test_out_is_required(self, folder, tmp_path):
        run = run_cli(tmp_path)
        assert run.returncode == 2
        assert "--out" in run.stderr
