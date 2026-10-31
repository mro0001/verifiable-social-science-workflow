"""The stream schema format and its checker (Step C3).

A graph may name `schema: schemas/<stream>.yaml` beside `contracts:`. The schema names
the item, each field's type and allowed values, whether it is required, which steps
fill it, and the report's layout. `vg.check_schema(schema, g)` lists its problems, and
`vg.check(g)` calls it when the graph names a schema. Every schema here is synthetic,
written in the test's temp folder and checked against the real citations graph.
"""
import copy
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import vg  # noqa: E402

GRAPH = ROOT / "graphs" / "citations.yaml"

VALID = {
    "stream": "citations",
    "version": 1,
    "item": "one citation of one reference in one sentence",
    "id": "id",
    "fields": {
        "id": {"type": "str", "filled_by": ["extract_citations"]},
        "citekey": {"type": "str", "filled_by": ["extract_citations"]},
        "line": {"type": "int", "filled_by": ["extract_citations"]},
        "origin": {"type": "enum", "values": ["yours", "ai_added"],
                   "filled_by": ["read_origin"]},
        "category": {"type": "enum", "values": ["problem", "verified", "author"],
                     "filled_by": ["gather_reason_and_quote"]},
        "score": {"type": "number", "filled_by": ["locate_passage"], "required": False},
        "moved": {"type": "bool", "filled_by": ["read_origin"]},
        "issues": {"type": "list", "filled_by": ["gather_reason_and_quote"]},
        "extra": {"type": "dict", "filled_by": ["gather_reason_and_quote"], "required": False},
        "second_verdict": {"type": "str", "filled_by": ["verify_quote"], "required": False,
                           "not_run_text": "not rechecked"},
        "needs_decision": {"type": "bool", "filled_by": ["report"]},
    },
    "run": {
        "draft_sha256": {"type": "str", "filled_by": ["pin_document"]},
        "n_rows": {"type": "int", "filled_by": ["extract_citations"]},
    },
    "tables": [
        {"id": "uncited", "fields": {"citekey": {"type": "str", "filled_by": ["match_references"]}}},
    ],
    "results": ["id", "citekey", "needs_decision"],
    "report": {
        "title": "Citation verification",
        "intro": "Checked {run.n_rows} rows of the draft {run.draft_sha256}. Numbers enter as {{num:key}}.",
        "sections": [
            {"heading": "Rows", "parts": [
                {"kind": "text", "template": "{run.n_rows} rows."},
                {"kind": "table", "rows": "items", "where": "category in [problem]",
                 "columns": [{"header": "Row", "value": "{id}"},
                             {"header": "Key", "value": "{citekey} line {line}"}],
                 "empty": "None."},
                {"kind": "list", "rows": "uncited", "line": "{citekey}", "empty": "None."},
                {"kind": "blocks", "rows": "items", "where": "category in [verified]",
                 "heading": "{id} {citekey}",
                 "lines": [{"label": "Origin", "value": "{origin}", "omit_empty": True},
                           {"label": "Second", "value": "{second_verdict}"}],
                 "empty": "None."},
                {"kind": "groups", "rows": "items", "by": "category",
                 "groups": [{"value": "problem", "title": "Problems"},
                            {"value": "verified", "title": "Verified"}],
                 "block": {"heading": "{id}", "lines": [{"label": "Key", "value": "{citekey}"}]},
                 "empty": "None."},
            ]},
        ],
    },
}


@pytest.fixture(scope="module")
def graph():
    return vg.load(str(GRAPH))


def problems_of(schema, graph):
    return vg.check_schema(schema, graph)


def changed(edit):
    s = copy.deepcopy(VALID)
    edit(s)
    return s


def has(problems, *words):
    return any(all(w in p for w in words) for p in problems)


def test_valid_schema_passes(graph):
    assert problems_of(VALID, graph) == []


def test_load_schema_reads_relative_to_vg(tmp_path):
    path = tmp_path / "s.yaml"
    path.write_text(yaml.safe_dump(VALID))
    assert vg.load_schema(str(path)) == VALID  # an absolute path is read as given
    rel = os.path.relpath(str(path), str(ROOT))
    assert vg.load_schema(rel) == VALID  # a relative path is read from vg.py's folder


def test_unknown_keys_are_named(graph):
    cases = [
        (lambda s: s.update(colour="red"), ("unknown key", "colour")),
        (lambda s: s["fields"]["id"].update(shape="x"), ("unknown key", "shape")),
        (lambda s: s["report"].update(footer="x"), ("unknown key", "footer")),
        (lambda s: s["report"]["sections"][0].update(note="x"), ("unknown key", "note")),
        (lambda s: s["report"]["sections"][0]["parts"][1].update(width=3), ("unknown key", "width")),
        (lambda s: s["tables"][0].update(order="x"), ("unknown key", "order")),
    ]
    for edit, words in cases:
        assert has(problems_of(changed(edit), graph), *words), words


def test_unknown_type_is_named(graph):
    p = problems_of(changed(lambda s: s["fields"]["line"].update(type="float")), graph)
    assert has(p, "line", "unknown type", "float")


def test_enum_without_values_is_named(graph):
    p = problems_of(changed(lambda s: s["fields"]["origin"].pop("values")), graph)
    assert has(p, "origin", "enum", "values")


def test_values_on_a_field_that_is_not_an_enum_is_named(graph):
    p = problems_of(changed(lambda s: s["fields"]["citekey"].update(values=["a"])), graph)
    assert has(p, "citekey", "values")


def test_filled_by_node_not_in_graph_is_named(graph):
    p = problems_of(changed(lambda s: s["fields"]["citekey"].update(filled_by=["no_such_step"])), graph)
    assert has(p, "citekey", "no_such_step", "not in the graph")
    p = problems_of(changed(lambda s: s["run"]["n_rows"].update(filled_by=["ghost"])), graph)
    assert has(p, "n_rows", "ghost")
    p = problems_of(changed(lambda s: s["tables"][0]["fields"]["citekey"].update(filled_by=["ghost"])), graph)
    assert has(p, "uncited", "ghost")


def test_stream_differing_from_graph_is_named(graph):
    p = problems_of(changed(lambda s: s.update(stream="prose")), graph)
    assert has(p, "stream", "prose", "citations")


def test_id_not_an_item_field_is_named(graph):
    p = problems_of(changed(lambda s: s.update(id="row_id")), graph)
    assert has(p, "id", "row_id", "not an item field")


def test_results_entry_not_an_item_field_is_named(graph):
    p = problems_of(changed(lambda s: s["results"].append("draft_sha256")), graph)
    assert has(p, "results", "draft_sha256", "not an item field")


@pytest.mark.parametrize("version", [0, -1, 1.5, "1", True, None])
def test_version_not_a_positive_integer_is_named(graph, version):
    p = problems_of(changed(lambda s: s.update(version=version)), graph)
    assert has(p, "version", "positive integer")


def test_part_with_unknown_kind_is_named(graph):
    p = problems_of(changed(lambda s: s["report"]["sections"][0]["parts"][0].update(kind="chart")), graph)
    assert has(p, "unknown kind", "chart")


def test_part_with_unknown_row_set_is_named(graph):
    p = problems_of(changed(lambda s: s["report"]["sections"][0]["parts"][2].update(rows="missing")), graph)
    assert has(p, "row set", "missing")


def test_template_field_not_in_row_set_is_named(graph):
    def edit(s):
        s["report"]["sections"][0]["parts"][1]["columns"][0]["value"] = "{nope}"
    p = problems_of(changed(edit), graph)
    assert has(p, "{nope}", "not a field of items")

    def edit_list(s):
        s["report"]["sections"][0]["parts"][2]["line"] = "{id}"  # id is not a field of uncited
    p = problems_of(changed(edit_list), graph)
    assert has(p, "{id}", "not a field of uncited")

    def edit_text(s):
        s["report"]["sections"][0]["parts"][0]["template"] = "{n_rows} rows."
    p = problems_of(changed(edit_text), graph)
    assert has(p, "{n_rows}")


def test_template_run_field_not_a_run_field_is_named(graph):
    p = problems_of(changed(lambda s: s["report"].update(intro="Checked {run.n_pages}.")), graph)
    assert has(p, "{run.n_pages}", "not a run field")
    def edit(s):
        s["report"]["sections"][0]["parts"][3]["heading"] = "{id} {run.missing}"
    assert has(problems_of(changed(edit), graph), "{run.missing}", "not a run field")


@pytest.mark.parametrize("field", ["moved", "issues", "extra"])
def test_template_naming_a_field_of_another_type_is_named(graph, field):
    def edit(s):
        s["report"]["sections"][0]["parts"][3]["lines"][0]["value"] = "{%s}" % field
    p = problems_of(changed(edit), graph)
    assert has(p, "{%s}" % field, "type")


def test_groups_by_not_an_enum_field_is_named(graph):
    p = problems_of(changed(lambda s: s["report"]["sections"][0]["parts"][4].update(by="citekey")), graph)
    assert has(p, "by", "citekey", "enum")


def test_groups_value_not_among_values_is_named(graph):
    def edit(s):
        s["report"]["sections"][0]["parts"][4]["groups"].append({"value": "lost", "title": "Lost"})
    p = problems_of(changed(edit), graph)
    assert has(p, "lost", "category")


def test_templates_in_a_groups_block_are_checked_against_its_rows(graph):
    def edit(s):
        s["report"]["sections"][0]["parts"][4]["block"]["heading"] = "{nope}"
    assert has(problems_of(changed(edit), graph), "{nope}", "not a field of items")


def test_double_braces_are_not_fields(graph):
    def edit(s):
        s["report"]["sections"][0]["parts"][0]["template"] = "Write {{num:key}} or {{table:t1}}."
    assert problems_of(changed(edit), graph) == []


def test_graph_without_schema_checks_as_before():
    # the self-test graph names no schema and is exempt from the schema rule (Step C9)
    g = vg.load(str(ROOT / "graphs" / "selftest.yaml"))
    assert "schema" not in g
    assert vg.check(g) == []


@pytest.mark.parametrize("stream", ["prose", "citations", "data", "build"])
def test_a_stream_graph_without_schema_fails_check(tmp_path, stream):
    g = yaml.safe_load((ROOT / "graphs" / ("%s.yaml" % stream)).read_text())
    g.pop("schema", None)
    gpath = tmp_path / ("%s.yaml" % stream)
    gpath.write_text(yaml.safe_dump(g, sort_keys=False))
    problems = vg.check(vg.load(str(gpath)))
    assert has(problems, "schema", stream), problems
    proc = subprocess.run([sys.executable, str(ROOT / "vg.py"), "check", str(gpath)],
                          cwd=str(ROOT), capture_output=True, text=True)
    assert proc.returncode == 1


@pytest.mark.parametrize("stream", ["prose", "citations", "data", "build"])
def test_each_stream_graph_names_its_schema_and_checks(stream):
    g = vg.load(str(ROOT / "graphs" / ("%s.yaml" % stream)))
    assert g["schema"] == "schemas/%s.yaml" % stream
    assert vg.check(g) == []


def write_graph_copy(tmp_path, schema):
    spath = tmp_path / "citations_schema.yaml"
    spath.write_text(yaml.safe_dump(schema, sort_keys=False))
    g = yaml.safe_load(GRAPH.read_text())
    g["schema"] = str(spath)
    gpath = tmp_path / "citations.yaml"
    gpath.write_text(yaml.safe_dump(g, sort_keys=False))
    return gpath


def test_check_calls_check_schema_when_graph_names_one(tmp_path):
    good = write_graph_copy(tmp_path, VALID)
    assert vg.check(vg.load(str(good))) == []
    bad = write_graph_copy(tmp_path, changed(lambda s: s.update(stream="data")))
    problems = vg.check(vg.load(str(bad)))
    assert has(problems, "stream", "data")


def test_check_command_names_schema_problems(tmp_path):
    bad = write_graph_copy(tmp_path, changed(lambda s: s["fields"]["line"].update(type="float")))
    proc = subprocess.run([sys.executable, str(ROOT / "vg.py"), "check", str(bad)],
                          cwd=str(ROOT), capture_output=True, text=True)
    assert proc.returncode == 1
    assert "float" in proc.stdout


def test_missing_schema_file_is_a_problem(tmp_path):
    g = yaml.safe_load(GRAPH.read_text())
    g["schema"] = str(tmp_path / "absent.yaml")
    gpath = tmp_path / "citations.yaml"
    gpath.write_text(yaml.safe_dump(g, sort_keys=False))
    assert has(vg.check(vg.load(str(gpath))), "schema", "absent.yaml")
