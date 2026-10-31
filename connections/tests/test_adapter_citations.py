"""Tests for the citation manager export adapter (Track D, step D17).

The proposal's Table 1 names the citation manager as the references
stream's tool, and Table A6 lists an adapter for a citation manager's export
as specified (appendix-only). The adapter reads CSL JSON directly, converts
BibTeX with pandoc -f bibtex -t csljson, and keeps the seven fields the
references procedure reads (Track D choice 16), writing refs.yaml.

The CSL JSON exports here are written by the test from the seeded references
fixture's refs.yaml, and the BibTeX file is synthetic text. The references
procedure is run offline through vg.py's command line with the fixture's
recorded answers, so no model or network is called. Every test runs with
HOME, CONNECTIONS_HOME, and AUDIT_HOME inside a temporary folder. Run from
the repository root with python3 -m pytest -q connections/tests.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from connections.adapters import ADAPTERS  # noqa: E402
from connections.cli import main  # noqa: E402

VP = ROOT / "verification_procedures"
SEEDED = VP / "fixtures" / "citations" / "seeded"
GRAPH = "graphs/citations.yaml"

BIB = """@article{okafor2018,
  author = {Okafor, Adaeze},
  title = {Written role descriptions and volunteer tenure},
  journal = {Public Service Quarterly},
  year = {2018},
  doi = {10.5555/psq.2019.0044}
}

@book{brennan2016,
  author = {Brennan, Siobhan},
  title = {The work is theirs},
  publisher = {Civic Press},
  date = {2016-03}
}
"""


@pytest.fixture(autouse=True)
def homes(tmp_path, monkeypatch):
    user = tmp_path / "user"
    user.mkdir()
    monkeypatch.setenv("HOME", str(user))
    monkeypatch.setenv("CONNECTIONS_HOME", str(tmp_path / "connections_home"))
    monkeypatch.setenv("AUDIT_HOME", str(tmp_path / "audit_home"))
    return tmp_path


def fixture_references():
    return yaml.safe_load((SEEDED / "refs.yaml").read_text(encoding="utf-8"))["references"]


def csl_item(ref):
    """One CSL JSON item for a fixture reference, the year written as date-parts."""
    item = dict(ref)
    item["issued"] = {"date-parts": [[ref["issued"]]]}
    return item


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def references(out):
    return yaml.safe_load((out / "refs.yaml").read_text(encoding="utf-8"))["references"]


def adapt(export, out):
    return main(["adapt", "citations", "--out", str(out), "--export", str(export)])


def vg(*args):
    env = dict(os.environ, VG_OFFLINE="1")
    return subprocess.run(
        [sys.executable, str(VP / "vg.py")] + list(args),
        cwd=str(VP),
        capture_output=True,
        text=True,
        env=env,
    )


def run_references(inputs, run):
    done = vg(
        "run", GRAPH, "--run", str(run), "--inputs", str(inputs),
        "--judge", "recorded:" + str(SEEDED / "recorded_judge.json"),
    )
    assert done.returncode == 0, done.stdout + done.stderr
    return run


def finding_keys(run):
    findings = json.loads((run / "files" / "findings.json").read_text(encoding="utf-8"))
    return sorted((f["check"], f["severity"], str(f["item"])) for f in findings)


def test_the_citations_adapter_is_registered_for_the_citations_stream():
    adapter = ADAPTERS["citations"]
    assert adapter.stream == "citations"
    assert tuple(adapter.fills) == ("refs.yaml",)


def test_a_csl_json_export_of_the_fixture_gives_the_fixtures_references(tmp_path):
    export = write_json(tmp_path / "library.json", [csl_item(r) for r in fixture_references()])
    out = tmp_path / "out"
    assert adapt(export, out) == 0
    expected = sorted(fixture_references(), key=lambda r: r["id"])
    assert references(out) == expected
    assert [r["id"] for r in references(out)] == sorted(r["id"] for r in fixture_references())


def test_the_seven_fields_are_written_in_their_order(tmp_path):
    export = write_json(tmp_path / "library.json", [csl_item(r) for r in fixture_references()])
    out = tmp_path / "out"
    adapt(export, out)
    for ref in references(out):
        assert list(ref) == ["id", "type", "author", "issued", "title", "container-title", "DOI"]
    assert (out / "refs.yaml").read_text(encoding="utf-8").startswith("references:\n")


def test_a_mapping_holding_items_is_read_like_a_list(tmp_path):
    items = [csl_item(r) for r in fixture_references()]
    out_list, out_map = tmp_path / "a", tmp_path / "b"
    adapt(write_json(tmp_path / "list.json", items), out_list)
    adapt(write_json(tmp_path / "map.json", {"items": items}), out_map)
    assert (out_list / "refs.yaml").read_bytes() == (out_map / "refs.yaml").read_bytes()


def test_the_references_procedure_finds_the_same_faults_from_the_adapters_refs(tmp_path):
    export = write_json(tmp_path / "library.json", [csl_item(r) for r in fixture_references()])
    out = tmp_path / "out"
    assert adapt(export, out) == 0
    inputs = tmp_path / "inputs"
    shutil.copytree(str(SEEDED), str(inputs))
    shutil.copyfile(str(out / "refs.yaml"), str(inputs / "refs.yaml"))

    adapted = run_references(inputs, tmp_path / "run_adapted")
    original = run_references(SEEDED, tmp_path / "run_fixture")

    scored = vg("score", "--run", str(adapted), "--truth", str(SEEDED / "truth.yaml"))
    assert scored.returncode == 0, scored.stdout + scored.stderr
    score = json.loads((adapted / "score.json").read_text(encoding="utf-8"))
    assert score["faults"] == 13
    assert len(score["caught"]) == 13
    assert score["recall"] == 1.0
    assert finding_keys(adapted) == finding_keys(original)


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="Pandoc is not on the path")
def test_a_bibtex_file_goes_through_pandoc_to_two_references(tmp_path):
    bib = tmp_path / "library.bib"
    bib.write_text(BIB, encoding="utf-8")
    out = tmp_path / "out"
    assert adapt(bib, out) == 0
    assert references(out) == [
        {"id": "brennan2016", "type": "book", "author": [{"family": "Brennan", "given": "Siobhan"}],
         "issued": 2016, "title": "The work is theirs"},
        {"id": "okafor2018", "type": "article-journal", "author": [{"family": "Okafor", "given": "Adaeze"}],
         "issued": 2018, "title": "Written role descriptions and volunteer tenure",
         "container-title": "Public Service Quarterly", "DOI": "10.5555/psq.2019.0044"},
    ]
    record = json.loads((out / "adapter_record.json").read_text(encoding="utf-8"))
    assert list(record["read"]) == [str(bib)]


def test_a_bibtex_file_without_pandoc_is_refused(tmp_path, monkeypatch, capsys):
    bib = tmp_path / "library.bib"
    bib.write_text(BIB, encoding="utf-8")
    empty = tmp_path / "empty_path"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    out = tmp_path / "out"
    assert adapt(bib, out) == 1
    assert "pandoc" in capsys.readouterr().err
    assert not out.exists()


def test_an_institution_author_is_kept_as_family(tmp_path):
    item = {"id": "council2020", "type": "report", "author": [{"literal": "Civic Research Council"}],
            "issued": {"date-parts": [[2020, 5]]}, "title": "Volunteer counts"}
    out = tmp_path / "out"
    assert adapt(write_json(tmp_path / "one.json", [item]), out) == 0
    assert references(out) == [
        {"id": "council2020", "type": "report", "author": [{"family": "Civic Research Council"}],
         "issued": 2020, "title": "Volunteer counts"},
    ]


def test_the_year_comes_from_raw_or_literal_and_doi_from_either_case(tmp_path):
    items = [
        {"id": "b", "issued": {"raw": "Spring 2018"}, "doi": "10.1/b"},
        {"id": "a", "issued": {"literal": "c. 1999-2000"}, "DOI": "10.1/a"},
        {"id": "c", "issued": {"literal": "forthcoming"}},
    ]
    out = tmp_path / "out"
    assert adapt(write_json(tmp_path / "years.json", items), out) == 0
    assert references(out) == [
        {"id": "a", "issued": 1999, "DOI": "10.1/a"},
        {"id": "b", "issued": 2018, "DOI": "10.1/b"},
        {"id": "c"},
    ]


def test_an_item_with_no_id_is_refused_and_nothing_written(tmp_path, capsys):
    items = [csl_item(r) for r in fixture_references()]
    del items[3]["id"]
    out = tmp_path / "out"
    assert adapt(write_json(tmp_path / "library.json", items), out) == 1
    assert "id" in capsys.readouterr().err
    assert not out.exists()


def test_two_items_with_one_id_are_refused_with_the_id(tmp_path, capsys):
    items = [csl_item(r) for r in fixture_references()]
    items.append(dict(items[0]))
    out = tmp_path / "out"
    assert adapt(write_json(tmp_path / "library.json", items), out) == 1
    assert items[0]["id"] in capsys.readouterr().err
    assert not out.exists()


def test_another_extension_is_refused(tmp_path, capsys):
    ris = tmp_path / "library.ris"
    ris.write_text("TY  - JOUR\nER  -\n", encoding="utf-8")
    out = tmp_path / "out"
    assert adapt(ris, out) == 1
    assert "library.ris" in capsys.readouterr().err
    assert not out.exists()


def test_an_export_that_is_not_a_list_of_items_is_refused(tmp_path, capsys):
    out = tmp_path / "out"
    assert adapt(write_json(tmp_path / "odd.json", {"references": []}), out) == 1
    assert "odd.json" in capsys.readouterr().err
    assert not out.exists()


def test_two_runs_on_one_export_give_the_same_bytes(tmp_path):
    export = write_json(tmp_path / "library.json", [csl_item(r) for r in fixture_references()])
    adapt(export, tmp_path / "a")
    adapt(export, tmp_path / "b")
    for name in ("refs.yaml", "adapter_record.json"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()


def test_the_module_runs_no_program_but_pandoc():
    text = (ROOT / "connections" / "adapters" / "citations.py").read_text(encoding="utf-8")
    assert "verification_procedures" not in text and "audit_layer" not in text
    assert text.count("subprocess.run(") == 1
