"""The one report builder. A stream's exit step fills its schema's fields from the step
outputs and calls build(fields), and this module writes the stream's fields.json,
findings.json, and report.md. Copied beside the exit step's code in the run, with the
schema as schema.yaml, so a replay uses exactly what the step ran with.

fields is {"run": {name: value}, "items": [row], "tables": {table id: [row]}}. A value is
of its field's declared type or {"not_run": "<reason>"}.

steps is the content of files/steps.json, {"steps": [{"node", "status", "reason"}]}, which
the runtime writes for every node but the exit step. A node it does not list is the exit
step itself, and counts as ran.
"""
import json
import os
import re
import sys

import _lib

DEFAULT_NOT_RUN_TEXT = "not run"
# {name} is a field of the part's rows and {run.name} a run field. Double braces, such as
# {{num:key}}, are text and never a field. The same pattern vg.py checks schemas with.
TEMPLATE_FIELD = re.compile(r"(?<!\{)\{(run\.)?([A-Za-z_]\w*)\}(?!\})")


# ---------------------------------------------------------------- the field sets

def _row_sets(schema):
    """(row set name, field specs) for the items and each table."""
    sets = [("items", schema.get("fields") or {})]
    for t in schema.get("tables") or []:
        sets.append((t["id"], t.get("fields") or {}))
    return sets


def _rows(fields, name):
    if name == "items":
        return fields.get("items") or []
    return (fields.get("tables") or {}).get(name) or []


def is_not_run(value):
    return isinstance(value, dict) and set(value) == {"not_run"}


# ---------------------------------------------------------------- not run

def apply_not_run(schema, fields, steps):
    """Mark every field whose filled_by nodes all have a status other than ran as
    {"not_run": reason}, for every row and for the run, with the reason of the first
    listed node. Changes fields in place and returns [(field, nodes, reason)], the field
    named as it is for items, run.<name> for a run field, and <table>.<name> for a table's."""
    status = {s["node"]: s for s in (steps or {}).get("steps", [])}

    def skipped(nodes):
        return all(n in status and status[n].get("status") != "ran" for n in nodes)

    def reason_of(node):
        s = status[node]
        return s.get("reason") or "%s %s" % (node, s.get("status"))

    applied = []
    for label, specs in _row_sets(schema):
        for name, spec in specs.items():
            nodes = list(spec.get("filled_by") or [])
            if not nodes or not skipped(nodes):
                continue
            reason = reason_of(nodes[0])
            for r in _rows(fields, label):
                r[name] = {"not_run": reason}
            applied.append((name if label == "items" else "%s.%s" % (label, name), nodes, reason))
    for name, spec in (schema.get("run") or {}).items():
        nodes = list(spec.get("filled_by") or [])
        if not nodes or not skipped(nodes):
            continue
        reason = reason_of(nodes[0])
        fields.setdefault("run", {})[name] = {"not_run": reason}
        applied.append(("run." + name, nodes, reason))
    return applied


# ---------------------------------------------------------------- validation

def _type_ok(spec, value):
    typ = spec.get("type")
    if typ == "str":
        return isinstance(value, str)
    if typ == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if typ == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if typ == "bool":
        return isinstance(value, bool)
    if typ == "list":
        return isinstance(value, list)
    if typ == "dict":
        return isinstance(value, dict)
    if typ == "enum":
        return value in (spec.get("values") or [])
    return False


def _check_row(where, row, specs, problems):
    if not isinstance(row, dict):
        problems.append("%s: must be a mapping" % where)
        return
    for name in sorted(set(row) - set(specs)):
        problems.append("%s: undeclared field %s" % (where, name))
    for name, spec in specs.items():
        value = row.get(name)
        if value is None:
            if spec.get("required", True):
                problems.append("%s: required field %s is missing" % (where, name))
            continue
        if is_not_run(value):
            if not (isinstance(value["not_run"], str) and value["not_run"].strip()):
                problems.append("%s: %s not_run needs a reason" % (where, name))
            continue
        if not _type_ok(spec, value):
            if spec.get("type") == "enum":
                problems.append("%s: %s %s is not among its values" % (where, name, value))
            else:
                problems.append("%s: %s must be %s" % (where, name, spec.get("type")))


def validate_fields(schema, fields):
    """Problems with a filled field set; an empty list means it is valid. A value is
    {"not_run": <non-empty text>} or of its declared type. An undeclared field, a missing
    or None required value, and a repeated item id are each a problem."""
    problems = []
    id_field = schema.get("id")
    seen = set()
    for i, r in enumerate(fields.get("items") or [], 1):
        rid = r.get(id_field) if isinstance(r, dict) else None
        where = "item %s" % (rid if isinstance(rid, str) and rid else i)
        if rid is not None and not is_not_run(rid):
            if rid in seen:
                problems.append("%s: repeated id" % where)
            seen.add(rid)
        _check_row(where, r, schema.get("fields") or {}, problems)
    _check_row("run", fields.get("run") or {}, schema.get("run") or {}, problems)
    declared = {t["id"]: t.get("fields") or {} for t in schema.get("tables") or []}
    tables = fields.get("tables") or {}
    for tid in sorted(set(tables) - set(declared)):
        problems.append("undeclared table %s" % tid)
    for tid, specs in declared.items():
        for i, r in enumerate(tables.get(tid) or [], 1):
            _check_row("table %s row %d" % (tid, i), r, specs, problems)
    return problems


# ---------------------------------------------------------------- completeness

def _spec_of(schema, field):
    if field.startswith("run."):
        return (schema.get("run") or {}).get(field[4:]), None
    if "." in field:
        tid, name = field.split(".", 1)
        for t in schema.get("tables") or []:
            if t["id"] == tid:
                return (t.get("fields") or {}).get(name), (tid, name)
        return None, None
    return (schema.get("fields") or {}).get(field), ("items", field)


def completeness(schema, applied, fields):
    """One warning per required field the builder marked not run. A field marked not run
    for one item by the stream's fill function gives none."""
    out = []
    for field, nodes, reason in applied:
        spec, where = _spec_of(schema, field)
        if not spec or not spec.get("required", True):
            continue
        if where is None:
            rows = [fields.get("run") or {}]
            name = field[4:]
        else:
            rows = _rows(fields, where[0])
            name = where[1]
        n = sum(1 for r in rows if is_not_run(r.get(name)))
        out.append(_lib.finding("completeness", "warning", field,
                                "required field not run for %d of %d rows: %s" % (n, len(rows), reason),
                                ", ".join(nodes)))
    return out


# ---------------------------------------------------------------- rendering

def _text(value, spec):
    if is_not_run(value):
        return (spec or {}).get("not_run_text", DEFAULT_NOT_RUN_TEXT)
    if value is None:
        return ""
    return str(value)


def fill(template, row, row_specs, run, run_specs):
    """Replace {name} with the row's value and {run.name} with the run's, as text, and a
    not run value with its field's not_run_text. Nothing else changes."""
    def sub(m):
        if m.group(1):
            name = m.group(2)
            return _text(run.get(name), run_specs.get(name))
        name = m.group(2)
        return _text((row or {}).get(name), row_specs.get(name))
    return TEMPLATE_FIELD.sub(sub, template)


def _where(row, expr):
    """<field> in [<values>], or <field> alone for the rows whose field has a value; no
    expression keeps every row."""
    if not expr:
        return True
    if " in " not in expr:
        return bool(row.get(expr.strip()))
    import yaml
    name, _, allowed = expr.partition(" in ")
    return row.get(name.strip()) in (yaml.safe_load(allowed) or [])


def _block(part, row, specs, run, run_specs):
    lines = ["### " + fill(part["heading"], row, specs, run, run_specs), ""]
    for ln in part["lines"]:
        value = fill(ln["value"], row, specs, run, run_specs)
        if ln.get("omit_empty") and not value.strip():
            continue
        lines.append("- **%s:** %s" % (ln["label"], value))
    return "\n".join(lines)


def _part(part, schema, fields):
    run = fields.get("run") or {}
    run_specs = schema.get("run") or {}
    kind = part["kind"]
    if kind == "text":
        return fill(part["template"], None, {}, run, run_specs)
    specs = dict(_row_sets(schema)).get(part["rows"], {})
    rows = [r for r in _rows(fields, part["rows"]) if _where(r, part.get("where"))]
    if not rows and "empty" in part:
        return part["empty"]
    if kind == "table":
        cols = part["columns"]
        lines = ["| " + " | ".join(c["header"] for c in cols) + " |",
                 "|" + "|".join("---" for _ in cols) + "|"]
        for r in rows:
            cells = [fill(c["value"], r, specs, run, run_specs) for c in cols]
            # An empty cell is written as one space between its bars.
            lines.append("|" + "|".join(" %s " % v if v else " " for v in cells) + "|")
        return "\n".join(lines)
    if kind == "list":
        return "\n".join("- " + fill(part["line"], r, specs, run, run_specs) for r in rows)
    if kind == "blocks":
        return "\n\n".join(_block(part, r, specs, run, run_specs) for r in rows)
    if kind == "groups":
        block = part["block"]
        out = []
        for grp in part["groups"]:
            sel = [r for r in rows if r.get(part["by"]) == grp["value"] and _where(r, block.get("where"))]
            chunk = ["**%s (%d)**" % (grp["title"], len(sel))]
            if sel:
                chunk += [_block(block, r, specs, run, run_specs) for r in sel]
            elif "empty" in block:
                chunk.append(block["empty"])
            out.append("\n\n".join(chunk))
        return "\n\n".join(out)
    raise ValueError("unknown part kind %s" % kind)


def render(schema, fields):
    """The report's introduction and its sections [(heading, markdown body)], built from
    the schema's layout. Parts of a section are joined by one blank line, and a part that
    renders to nothing is left out."""
    run = fields.get("run") or {}
    run_specs = schema.get("run") or {}
    report = schema["report"]
    intro = fill(report["intro"], None, {}, run, run_specs)
    sections = []
    for sec in report.get("sections") or []:
        bodies = [_part(p, schema, fields) for p in sec.get("parts") or []]
        sections.append((sec["heading"], "\n\n".join(b for b in bodies if b)))
    return intro, sections


# ---------------------------------------------------------------- the exit step

def build(fields, ranked=True):
    """Write fields.json, findings.json, and report.md for the stream, from the schema
    beside this file and the run's steps.json. Any validation problem is printed and the
    step exits 1, so it fails its contract. A stream whose report ranks nothing passes
    ranked=False, and its report leaves out the Summary and Problems sections."""
    import yaml
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.yaml"), encoding="utf-8") as f:
        schema = yaml.safe_load(f)
    try:
        steps = _lib.read_json("steps.json")
    except FileNotFoundError:
        print("steps.json is missing from the run's files")
        sys.exit(1)
    fields.setdefault("run", {})
    fields.setdefault("items", [])
    fields.setdefault("tables", {})
    applied = apply_not_run(schema, fields, steps)
    problems = validate_fields(schema, fields)
    if problems:
        for p in problems:
            print(p)
        sys.exit(1)
    _lib.emit_findings("completeness", completeness(schema, applied, fields))
    # fields.json keeps the order the fill function gave, which is as fixed as a sorted
    # order, so the results file can carry each item's values, and the findings inside
    # them, in the order the slice's results file has them.
    with open(_lib.path("fields.json"), "w", encoding="utf-8") as f:
        json.dump({"schema": {"stream": schema["stream"], "version": schema["version"]},
                   "run": fields["run"], "items": fields["items"], "tables": fields["tables"]},
                  f, indent=2, ensure_ascii=False)
        f.write("\n")
    findings = _lib.collect_findings()
    _lib.write_json("findings.json", findings)
    run = fields["run"]
    title = fill(schema["report"]["title"], None, {}, run, schema.get("run") or {})
    intro, sections = render(schema, fields)
    _lib.write_text("report.md", _lib.report(title, intro, findings, sections, ranked=ranked))
