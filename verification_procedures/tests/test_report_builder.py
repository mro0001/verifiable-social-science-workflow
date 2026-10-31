"""The one report builder (Step C4).

`implementations/_report.py` sits beside `_lib.py`. It marks the fields whose steps
did not run as `{"not_run": reason}`, validates the fields against the stream's
schema, warns when a required field did not run, and renders the report's
introduction and sections from the schema's five kinds of part. `build(fields)` is
what a stream's `report.py` calls at the exit step. Every schema and field set here is
synthetic, and no procedure runs.
"""
import copy
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
IMPL = ROOT / "implementations"
sys.path.insert(0, str(IMPL))
import _report  # noqa: E402

SCHEMA = {
    "stream": "citations",
    "version": 3,
    "item": "one citation",
    "id": "id",
    "fields": {
        "id": {"type": "str", "filled_by": ["extract_citations"]},
        "citekey": {"type": "str", "filled_by": ["extract_citations"]},
        "line": {"type": "int", "filled_by": ["extract_citations"]},
        "category": {"type": "enum", "values": ["problem", "verified", "author"],
                     "filled_by": ["collect_verdicts"]},
        "score": {"type": "number", "filled_by": ["judge_support"], "required": False},
        "moved": {"type": "bool", "filled_by": ["attribute_origin"]},
        "issues": {"type": "list", "filled_by": ["collect_verdicts"]},
        "extra": {"type": "dict", "filled_by": ["collect_verdicts"], "required": False},
        "note": {"type": "str", "filled_by": ["collect_verdicts"], "required": False},
        "second_verdict": {"type": "str", "filled_by": ["second_check"], "required": False,
                           "not_run_text": "not rechecked"},
        "settled": {"type": "str", "filled_by": ["settle_verdicts", "settle_unanimous"]},
        "verdict": {"type": "str", "filled_by": ["judge_support"]},
    },
    "run": {
        "n_rows": {"type": "int", "filled_by": ["extract_citations"]},
        "sha": {"type": "str", "filled_by": ["pin_document"]},
    },
    "tables": [
        {"id": "uncited", "fields": {"citekey": {"type": "str", "filled_by": ["match_references"]}}},
    ],
    "report": {
        "title": "Citation check of {run.n_rows} rows",
        "intro": "Draft {run.sha}. Numbers enter as {{num:key}}.",
        "sections": [],
    },
}


def row(i, **kw):
    r = {"id": "c%d" % i, "citekey": "key%d" % i, "line": i, "category": "verified",
         "moved": False, "issues": [], "settled": "yes", "verdict": "supports"}
    r.update(kw)
    return r


def fields_of(items=None, run=None, tables=None):
    return {"run": run if run is not None else {"n_rows": 2, "sha": "abc"},
            "items": items if items is not None else [row(1), row(2)],
            "tables": tables if tables is not None else {"uncited": [{"citekey": "lone"}]}}


def steps_of(**status):
    """steps.json content: every filling node ran unless named here as skipped."""
    nodes = ["pin_document", "extract_citations", "attribute_origin", "match_references",
             "judge_support", "collect_verdicts", "second_check", "settle_verdicts",
             "settle_unanimous"]
    out = []
    for n in nodes:
        if n in status:
            out.append({"node": n, "status": "skipped", "reason": status[n]})
        else:
            out.append({"node": n, "status": "ran", "reason": ""})
    return {"steps": out}


def with_sections(*parts, heading="Rows"):
    s = copy.deepcopy(SCHEMA)
    s["report"]["sections"] = [{"heading": heading, "parts": list(parts)}]
    return s


# ---------------------------------------------------------------- not run

def test_field_becomes_not_run_when_its_only_step_was_skipped():
    f = fields_of()
    applied = _report.apply_not_run(SCHEMA, f, steps_of(second_check="collect.json:n > 0 was false (actual 0)"))
    assert applied == [("second_verdict", ["second_check"], "collect.json:n > 0 was false (actual 0)")]
    for r in f["items"]:
        assert r["second_verdict"] == {"not_run": "collect.json:n > 0 was false (actual 0)"}
    assert f["items"][0]["verdict"] == "supports"


def test_field_with_two_filling_steps_stays_filled_when_one_ran():
    f = fields_of()
    applied = _report.apply_not_run(SCHEMA, f, steps_of(settle_verdicts="no incoming edge fired"))
    assert applied == []
    assert all(r["settled"] == "yes" for r in f["items"])


def test_reason_is_the_first_listed_nodes_when_all_skipped():
    f = fields_of()
    applied = _report.apply_not_run(SCHEMA, f, steps_of(settle_verdicts="first reason",
                                                         settle_unanimous="second reason"))
    assert applied == [("settled", ["settle_verdicts", "settle_unanimous"], "first reason")]
    assert f["items"][1]["settled"] == {"not_run": "first reason"}


def test_run_and_table_fields_become_not_run():
    f = fields_of()
    applied = _report.apply_not_run(SCHEMA, f, steps_of(pin_document="no incoming edge fired",
                                                         match_references="no incoming edge fired"))
    assert ("run.sha", ["pin_document"], "no incoming edge fired") in applied
    assert ("uncited.citekey", ["match_references"], "no incoming edge fired") in applied
    assert f["run"]["sha"] == {"not_run": "no incoming edge fired"}
    assert f["tables"]["uncited"][0]["citekey"] == {"not_run": "no incoming edge fired"}


def test_a_step_missing_from_steps_json_counts_as_ran():
    # steps.json lists every node but the exit step, which is the one running.
    s = copy.deepcopy(SCHEMA)
    s["fields"]["verdict"]["filled_by"] = ["report"]
    f = fields_of()
    assert _report.apply_not_run(s, f, steps_of()) == []
    assert f["items"][0]["verdict"] == "supports"


# ---------------------------------------------------------------- completeness

def test_required_field_not_run_gives_one_completeness_warning():
    f = fields_of()
    applied = _report.apply_not_run(SCHEMA, f, steps_of(judge_support="no incoming edge fired"))
    found = _report.completeness(SCHEMA, applied, f)
    assert found == [{
        "check": "completeness", "severity": "warning", "item": "verdict",
        "message": "required field not run for 2 of 2 rows: no incoming edge fired",
        "evidence": "judge_support"}]


def test_optional_field_not_run_gives_no_warning():
    f = fields_of()
    applied = _report.apply_not_run(SCHEMA, f, steps_of(second_check="no incoming edge fired"))
    assert applied
    assert _report.completeness(SCHEMA, applied, f) == []


def test_item_marked_not_run_by_the_fill_function_gives_no_warning():
    f = fields_of(items=[row(1), row(2, verdict={"not_run": "the author's own citation"})])
    applied = _report.apply_not_run(SCHEMA, f, steps_of())
    assert applied == []
    assert _report.completeness(SCHEMA, applied, f) == []
    assert _report.validate_fields(SCHEMA, f) == []


# ---------------------------------------------------------------- validation

def test_valid_fields_have_no_problems():
    f = fields_of(items=[row(1, score=0.5, extra={"a": 1}, note="x"), row(2, score=1)])
    assert _report.validate_fields(SCHEMA, f) == []


@pytest.mark.parametrize("change, expect", [
    (lambda f: f["items"][0].update(line="3"), "item c1: line must be int"),
    (lambda f: f["items"][0].update(line=True), "item c1: line must be int"),
    (lambda f: f["items"][0].update(score="high"), "item c1: score must be number"),
    (lambda f: f["items"][0].update(moved="no"), "item c1: moved must be bool"),
    (lambda f: f["items"][0].update(issues="x"), "item c1: issues must be list"),
    (lambda f: f["items"][0].update(extra=[1]), "item c1: extra must be dict"),
    (lambda f: f["items"][0].update(citekey=4), "item c1: citekey must be str"),
    (lambda f: f["items"][0].update(category="maybe"), "item c1: category maybe is not among its values"),
    (lambda f: f["items"][0].update(color="red"), "item c1: undeclared field color"),
    (lambda f: f["items"][0].pop("verdict"), "item c1: required field verdict is missing"),
    (lambda f: f["items"][0].update(verdict=None), "item c1: required field verdict is missing"),
    (lambda f: f["items"][1].update(id="c1"), "item c1: repeated id"),
    (lambda f: f["items"][0].update(verdict={"not_run": ""}), "item c1: verdict not_run needs a reason"),
    (lambda f: f["items"][0].update(verdict={"not_run": "x", "also": 1}), "item c1: verdict must be str"),
    (lambda f: f["run"].update(n_rows="two"), "run: n_rows must be int"),
    (lambda f: f["run"].update(extra=1), "run: undeclared field extra"),
    (lambda f: f["run"].pop("sha"), "run: required field sha is missing"),
    (lambda f: f["tables"]["uncited"][0].update(citekey=1), "table uncited row 1: citekey must be str"),
    (lambda f: f["tables"]["uncited"][0].update(page=1), "table uncited row 1: undeclared field page"),
    (lambda f: f["tables"].update(other=[]), "undeclared table other"),
])
def test_each_validation_problem_is_named(change, expect):
    f = fields_of()
    change(f)
    problems = _report.validate_fields(SCHEMA, f)
    assert expect in problems, problems


def test_optional_field_may_be_missing_or_none():
    f = fields_of(items=[row(1, note=None), row(2)])
    assert _report.validate_fields(SCHEMA, f) == []


def test_not_run_value_passes_for_any_type():
    f = fields_of(items=[row(1, line={"not_run": "r"}, category={"not_run": "r"},
                            issues={"not_run": "r"})])
    assert _report.validate_fields(SCHEMA, f) == []


# ---------------------------------------------------------------- rendering

def test_text_part_renders_run_values_once():
    s = with_sections({"kind": "text", "template": "{run.n_rows} rows of {run.sha}, {{num:n}} kept."})
    intro, sections = _report.render(s, fields_of())
    assert intro == "Draft abc. Numbers enter as {{num:key}}."
    assert sections == [("Rows", "2 rows of abc, {{num:n}} kept.")]


def test_table_part_with_where_and_empty():
    table = {"kind": "table", "rows": "items", "where": "category in [problem, verified]",
             "columns": [{"header": "Row", "value": "{id}"},
                         {"header": "Key", "value": "{citekey} line {line}"}],
             "empty": "No rows."}
    items = [row(1, category="problem"), row(2, category="author"), row(3)]
    _, sections = _report.render(with_sections(table), fields_of(items=items))
    assert sections[0][1] == ("| Row | Key |\n|---|---|\n"
                              "| c1 | key1 line 1 |\n| c3 | key3 line 3 |")
    _, sections = _report.render(with_sections(table), fields_of(items=[row(2, category="author")]))
    assert sections[0][1] == "No rows."


def test_list_part_where_a_field_alone_keeps_the_rows_that_give_it():
    part = {"kind": "list", "rows": "items", "where": "session_line", "line": "{id} {session_line}"}
    items = [row(1, session_line="Sabc"), row(2), row(3, session_line="")]
    _, sections = _report.render(with_sections(part), fields_of(items=items))
    assert sections[0][1] == "- c1 Sabc"


def test_table_part_writes_an_empty_cell_as_one_space():
    """Spacing adjusted in Step C7 so the data report's Parameter record row for a
    parameter no step read keeps its old form, `| n/a | | |`."""
    table = {"kind": "table", "rows": "items",
             "columns": [{"header": "Row", "value": "{id}"},
                         {"header": "Note", "value": "{note}"},
                         {"header": "Key", "value": "{citekey}"}]}
    _, sections = _report.render(with_sections(table), fields_of(items=[row(1, note="")]))
    assert sections[0][1] == "| Row | Note | Key |\n|---|---|---|\n| c1 | | key1 |"


def test_list_part_over_a_table_with_empty():
    part = {"kind": "list", "rows": "uncited", "line": "@{citekey}", "empty": "None."}
    _, sections = _report.render(with_sections(part), fields_of(
        tables={"uncited": [{"citekey": "a"}, {"citekey": "b"}]}))
    assert sections[0][1] == "- @a\n- @b"
    _, sections = _report.render(with_sections(part), fields_of(tables={"uncited": []}))
    assert sections[0][1] == "None."


def test_blocks_part_with_omit_empty():
    part = {"kind": "blocks", "rows": "items", "where": "category in [verified]",
            "heading": "{id}: @{citekey}",
            "lines": [{"label": "Note", "value": "{note}", "omit_empty": True},
                      {"label": "Line", "value": "{line}"},
                      {"label": "Empty kept", "value": "{note}"}],
            "empty": "None."}
    items = [row(1, note="checked twice"), row(2), row(3, category="problem")]
    _, sections = _report.render(with_sections(part), fields_of(items=items))
    assert sections[0][1] == (
        "### c1: @key1\n\n- **Note:** checked twice\n- **Line:** 1\n- **Empty kept:** checked twice\n\n"
        "### c2: @key2\n\n- **Line:** 2\n- **Empty kept:** ")
    _, sections = _report.render(with_sections(part), fields_of(items=[row(3, category="problem")]))
    assert sections[0][1] == "None."


def test_groups_part_shows_counts_and_empty_groups():
    part = {"kind": "groups", "rows": "items", "by": "category",
            "groups": [{"value": "problem", "title": "Problems"},
                       {"value": "verified", "title": "Verified"}],
            "block": {"heading": "{id}", "lines": [{"label": "Key", "value": "{citekey}"}],
                      "empty": "None."},
            "empty": "No citations."}
    items = [row(1), row(2, category="author"), row(3)]
    _, sections = _report.render(with_sections(part), fields_of(items=items))
    assert sections[0][1] == (
        "**Problems (0)**\n\nNone.\n\n"
        "**Verified (2)**\n\n### c1\n\n- **Key:** key1\n\n### c3\n\n- **Key:** key3")
    _, sections = _report.render(with_sections(part), fields_of(items=[]))
    assert sections[0][1] == "No citations."


def test_parts_of_a_section_are_joined_by_one_blank_line():
    s = with_sections({"kind": "text", "template": "First."}, {"kind": "text", "template": "Second."})
    s["report"]["sections"].append({"heading": "More", "parts": [{"kind": "text", "template": "Third."}]})
    _, sections = _report.render(s, fields_of())
    assert sections == [("Rows", "First.\n\nSecond."), ("More", "Third.")]


def test_not_run_text_shows_in_place_of_a_value_that_did_not_run():
    part = {"kind": "list", "rows": "items",
            "line": "{id} second {second_verdict}, verdict {verdict}, sha {run.sha}"}
    f = fields_of(items=[row(1, verdict={"not_run": "skipped"}, second_verdict={"not_run": "skipped"})],
                  run={"n_rows": 1, "sha": {"not_run": "skipped"}})
    _, sections = _report.render(with_sections(part), f)
    assert sections[0][1] == "- c1 second not rechecked, verdict not run, sha not run"


def test_template_leaves_everything_else_unchanged():
    part = {"kind": "list", "rows": "items", "line": "| {id} | {{num:x}} | {nope | *{citekey}* |"}
    _, sections = _report.render(with_sections(part), fields_of(items=[row(1)]))
    assert sections[0][1] == "- | c1 | {{num:x}} | {nope | *key1* |"


# ---------------------------------------------------------------- build

REPORT_PY = "import json, sys\nimport _report\n_report.build(json.load(open(sys.argv[2])))\n"


def build_run(tmp_path, schema, fields, steps, extra_findings=None):
    code = tmp_path / "code"
    files = tmp_path / "files"
    code.mkdir()
    files.mkdir()
    shutil.copy(IMPL / "_lib.py", code / "_lib.py")
    shutil.copy(IMPL / "_report.py", code / "_report.py")
    (code / "schema.yaml").write_text(yaml.safe_dump(schema, sort_keys=False))
    (code / "report.py").write_text(REPORT_PY)
    (files / "steps.json").write_text(json.dumps(steps))
    if extra_findings is not None:
        (files / "findings_check_existence.json").write_text(json.dumps(extra_findings))
    fpath = tmp_path / "fields_in.json"
    fpath.write_text(json.dumps(fields))
    return subprocess.run([sys.executable, str(code / "report.py"), str(files), str(fpath)],
                          capture_output=True, text=True), files


def test_build_writes_fields_findings_and_report(tmp_path):
    s = with_sections({"kind": "table", "rows": "items",
                       "columns": [{"header": "Row", "value": "{id}"},
                                   {"header": "Verdict", "value": "{verdict}"}]})
    note = {"check": "check_existence", "severity": "info", "item": "c2",
            "message": "found", "evidence": ""}
    proc, files = build_run(tmp_path, s, fields_of(), steps_of(judge_support="no incoming edge fired"),
                            extra_findings=[note])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    comp = json.loads((files / "findings_completeness.json").read_text())
    assert [x["item"] for x in comp] == ["verdict"]
    saved = json.loads((files / "fields.json").read_text())
    assert saved["schema"] == {"stream": "citations", "version": 3}
    assert saved["run"] == {"n_rows": 2, "sha": "abc"}
    assert saved["items"][0]["verdict"] == {"not_run": "no incoming edge fired"}
    assert saved["tables"] == {"uncited": [{"citekey": "lone"}]}
    findings = json.loads((files / "findings.json").read_text())
    assert [(x["check"], x["severity"]) for x in findings] == [("completeness", "warning"),
                                                              ("check_existence", "info")]
    report = (files / "report.md").read_text()
    heads = [ln for ln in report.splitlines() if ln.startswith("#")]
    assert heads[:3] == ["# Citation check of 2 rows", "## Summary", "## Problems"]
    assert report.index("Draft abc.") < report.index("## Summary")
    assert report.startswith("# Citation check of 2 rows\n\nDraft abc. Numbers enter as {{num:key}}.\n\n## Summary\n")
    assert "| warning | completeness | verdict | required field not run for 2 of 2 rows" in report
    assert "## Rows\n\n| Row | Verdict |\n|---|---|\n| c1 | not run |\n| c2 | not run |\n" in report
    assert report.index("## Problems") < report.index("## Rows") < report.index("## Notes")


def test_fields_json_keeps_the_order_the_fill_function_gave(tmp_path):
    """The results file carries item fields as fields.json holds them (Step C10), so a
    finding inside an item keeps the finding format's order of keys."""
    s = dict(SCHEMA, fields=dict(SCHEMA["fields"], findings={"type": "list", "required": False}))
    found = [{"check": "check_existence", "severity": "warning", "message": "m", "evidence": "e"}]
    proc, files = build_run(tmp_path, s, fields_of(items=[row(1, findings=found), row(2)]), steps_of())
    assert proc.returncode == 0, proc.stdout + proc.stderr
    saved = json.loads((files / "fields.json").read_text())
    assert list(saved) == ["schema", "run", "items", "tables"]
    assert list(saved["items"][0]["findings"][0]) == ["check", "severity", "message", "evidence"]
    assert list(saved["items"][1]) == list(row(2))


def test_build_fails_the_step_on_a_validation_problem(tmp_path):
    f = fields_of(items=[row(1, category="maybe")])
    proc, files = build_run(tmp_path, SCHEMA, f, steps_of())
    assert proc.returncode == 1
    assert "item c1: category maybe is not among its values" in proc.stdout
    assert not (files / "report.md").exists()
    assert not (files / "fields.json").exists()


def test_build_writes_an_empty_completeness_file_when_all_ran(tmp_path):
    proc, files = build_run(tmp_path, SCHEMA, fields_of(), steps_of())
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads((files / "findings_completeness.json").read_text()) == []
    assert "## Problems\n\nNone.\n" in (files / "report.md").read_text()
