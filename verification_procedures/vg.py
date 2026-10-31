"""Verification-graph runtime: procedural graphs for the four verification streams.

A graph (graphs/<stream>.yaml) is a procedure in the shape of Lu et al. 2026
(arXiv 2609.09153): nodes are steps; edges are (step, relation, step) triplets
carrying a condition, guidance, and pitfalls. Carried over from the Methods and
Theory Graph pilot (pg_runtime.py), not from the paper:
  contracts       contracts/<stream>.yaml: what each step reads and must produce
  implementations implementations/<stream>/<node>.py (tool steps) or
                  implementations/<stream>/<node>.prompt.md (judgment steps)
  step records    one JSON per executed step: hashed inputs, the guidance shown,
                  execution, outputs, contract checks, branches fired
  verify          replays every tool step from its saved code and compares hashes

New here:
  run             walks the whole graph: a node runs when any incoming edge fired
  judgment items  a judgment node with `foreach` asks once per item (small asks);
                  each prompt carries the pitfalls on that node's edges
  executors       recorded:<file> (fixed answers, for tests), live (the provider's model),
                  or live:<model> (another model on the same service). A live executor
                  reads the provider setting, provider.yaml in CONNECTIONS_HOME, else in
                  ~/.workflow_connections, with base_url and model, and sends the key in
                  WORKFLOW_MODEL_KEY as a bearer token when it is set. The setting may
                  also name token_limit, a whole number above 0, and token_limit_field,
                  max_tokens or max_completion_tokens. The reply's output limit is sent
                  under that field only, 4000 under max_tokens when they are absent, as
                  Table A10 records. The setting may also name request_timeout, the
                  seconds a live request waits, a whole number above 0, 300 when it is
                  absent. The manifest of a live run records the provider's base_url and
                  model, the limit and field it sent, and the request_timeout it used.
                  A live run saves each reply the service sent whole, as the bytes it
                  sent, beside the answer text, as responses/<step>/<item>.reply.json
                  (<item>.retry.reply.json for a retry), and the judgment step's record
                  lists each under replies with its sha256
  trail.jsonl     append-only event log of the run (observability)
  score           compares findings.json with a fixture's truth.yaml
  results.json    written beside the step files when a run of a graph with a schema
                  completes, one item for each item row of fields.json with the fields
                  the schema's results list names, and the scholar's decisions
  decide          records the scholar's approve or hold on one item and writes
                  report_decided.md, the report with the latest decisions near the top
  registry        registry.yaml names one procedure for each stream, with Table 1's
                  names, its graph, its triggers (events, phrases, file patterns), and
                  its quick steps; `procedures` prints each entry with its graph and
                  schema versions and its input files, and `run` takes a registered id
                  in place of a graph path
  run --quick     the light working check: `run <id> --quick` runs only the registered
                  procedure's quick steps, marks the manifest "quick": true, prints
                  "quick: <B> blocking, <W> warnings from <N> steps", and writes no
                  report and no results file

Commands:
  python3 vg.py check graphs/citations.yaml
  python3 vg.py run graphs/citations.yaml --run runs/X --inputs fixtures/citations/seeded \
      --judge live --second live:<other model>
  python3 vg.py verify --run runs/X
  python3 vg.py score --run runs/X --truth fixtures/citations/seeded/truth.yaml
  python3 vg.py decide --run runs/X --item r08 --approve --by "A. Scholar"
  python3 vg.py procedures [--check]
  python3 vg.py run citations --run runs/X --inputs fixtures/citations/seeded ...
  python3 vg.py run prose --quick --run runs/Q --inputs fixtures/prose/seeded
"""
import argparse
import copy
import datetime
import fnmatch
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections import deque

import yaml

ROOT = os.path.dirname(os.path.abspath(__file__))
RELATIONS = {"LEADS_TO", "TRIGGERS", "PROVIDES_INPUT_FOR", "CONVERGES_TO"}
EDGE_KEYS = {"from", "rel", "to", "condition", "check", "guidance", "pitfalls", "source", "invariant"}
NODE_KEYS = {"id", "kind", "does", "invariant", "foreach", "where", "role", "replay"}
SEVERITIES = ("blocking", "warning", "info")
# The provider setting (Track D choice 6). The file sits in the connections home,
# and the key, when there is one, is read from the environment and never stored.
PROVIDER_FILE = "provider.yaml"
KEY_ENV = "WORKFLOW_MODEL_KEY"
# The output limit of a live request (the ruling of 2026-10-29). The setting may
# name token_limit and token_limit_field. When it does not, the request keeps the 4000
# tokens under max_tokens that Table A10 records.
DEFAULT_TOKEN_LIMIT = 4000
TOKEN_LIMIT_FIELDS = ("max_tokens", "max_completion_tokens")
# The seconds a live request waits (Track L, step L1). The setting may name
# request_timeout. When it does not, the request keeps waiting 300 seconds.
DEFAULT_REQUEST_TIMEOUT = 300


# ---------------------------------------------------------------- graph

def load(path):
    path = os.path.abspath(path)
    with open(path) as f:
        g = yaml.safe_load(f)
    g["_path"] = path
    g["_nodes"] = {n["id"]: n for n in g["nodes"]}
    with open(os.path.join(ROOT, g["contracts"])) as f:
        g["_contracts"] = yaml.safe_load(f)
    return g


def impl_path(g, node_id):
    node = g["_nodes"][node_id]
    ext = ".prompt.md" if node["kind"] == "judgment" else ".py"
    return os.path.join(ROOT, "implementations", g["stream"], node_id + ext)


def check(g):
    """Structural problems; an empty list means the graph is valid."""
    problems = []
    ids = [n["id"] for n in g["nodes"]]
    if len(ids) != len(set(ids)):
        problems.append("duplicate node ids")
    for key in ("entry", "exit"):
        if g.get(key) not in g["_nodes"]:
            problems.append(f"{key} node missing: {g.get(key)}")
    for n in g["nodes"]:
        if n.get("kind") not in ("tool", "judgment"):
            problems.append(f"node {n['id']}: kind must be tool or judgment")
        extra = set(n) - NODE_KEYS
        if extra:
            problems.append(f"node {n['id']} has unexpected keys {sorted(extra)}")
        if n.get("kind") == "judgment" and n.get("role", "judge") not in ("judge", "second"):
            problems.append(f"node {n['id']}: role must be judge or second")
    for e in g["edges"]:
        for end in ("from", "to"):
            if e[end] not in g["_nodes"]:
                problems.append(f"edge endpoint not a node: {e[end]}")
        if e["rel"] not in RELATIONS:
            problems.append(f"unknown relation {e['rel']} on {e['from']}->{e['to']}")
        for field in ("condition", "guidance", "pitfalls", "source"):
            if field not in e:
                problems.append(f"edge {e['from']}->{e['to']} missing {field}")
        extra = set(e) - EDGE_KEYS
        if extra:
            problems.append(f"edge {e['from']}->{e['to']} has unexpected keys {sorted(extra)}")
        if "check" in e:
            try:
                _parse_check(e["check"])
            except ValueError as err:
                problems.append(str(err))
    try:
        topo_order(g)
    except ValueError as err:
        problems.append(str(err))
    reached = _reachable(g, g.get("entry"))
    for nid in ids:
        if nid not in reached:
            problems.append(f"unreachable from entry: {nid}")
    for nid in ids:
        if nid not in g["_contracts"]:
            problems.append(f"no contract for node {nid}")
        if not os.path.exists(impl_path(g, nid)):
            problems.append(f"no implementation for node {nid}: {os.path.relpath(impl_path(g, nid), ROOT)}")
    if "schema" not in g and g.get("stream") in SCHEMA_STREAMS:
        problems.append(f"a {g.get('stream')} graph must name its schema (schema: schemas/{g.get('stream')}.yaml)")
    if "schema" in g:
        try:
            schema = load_schema(g["schema"])
        except (OSError, yaml.YAMLError) as err:
            problems.append(f"schema {g['schema']} cannot be read: {err}")
        else:
            problems += check_schema(schema, g)
    return problems


# ---------------------------------------------------------------- schemas

# The four streams whose graphs must name a schema. The self-test graph and any other
# graph are exempt.
SCHEMA_STREAMS = ("prose", "citations", "data", "build")
SCHEMA_KEYS = {"stream", "version", "item", "id", "fields", "run", "tables", "results", "report"}
SCHEMA_REQUIRED = ("stream", "version", "item", "id", "fields", "report")
FIELD_KEYS = {"type", "values", "required", "filled_by", "not_run_text"}
FIELD_TYPES = ("str", "int", "number", "bool", "list", "dict", "enum")
TEMPLATE_TYPES = ("str", "int", "number", "enum")
TABLE_KEYS = {"id", "fields"}
REPORT_KEYS = {"title", "intro", "sections"}
SECTION_KEYS = {"heading", "parts"}
# Each part kind's keys, then the keys it must have.
PART_KEYS = {
    "text": ({"kind", "template"}, ("template",)),
    "table": ({"kind", "rows", "where", "columns", "empty"}, ("rows", "columns")),
    "list": ({"kind", "rows", "where", "line", "empty"}, ("rows", "line")),
    "blocks": ({"kind", "rows", "where", "heading", "lines", "empty"}, ("rows", "heading", "lines")),
    "groups": ({"kind", "rows", "by", "groups", "block", "empty"}, ("rows", "by", "groups", "block")),
}
BLOCK_KEYS = ({"where", "heading", "lines", "empty"}, ("heading", "lines"))  # a blocks part without rows
COLUMN_KEYS = ({"header", "value"}, ("header", "value"))
LINE_KEYS = ({"label", "value", "omit_empty"}, ("label", "value"))
GROUP_KEYS = ({"value", "title"}, ("value", "title"))
# {name} is a field of the part's rows and {run.name} a run field. Double braces, such as
# {{num:key}}, are text and never a field.
TEMPLATE_FIELD = re.compile(r"(?<!\{)\{(run\.)?([A-Za-z_]\w*)\}(?!\})")


def load_schema(path):
    """A stream schema, read relative to the folder of vg.py (an absolute path as given)."""
    with open(os.path.join(ROOT, path)) as f:
        return yaml.safe_load(f)


def _keys(where, obj, allowed, required, problems):
    """Name each unknown and each missing key of one schema object. False when obj is
    not a mapping, so the caller looks no further into it."""
    if not isinstance(obj, dict):
        problems.append(f"{where}: must be a mapping")
        return False
    for k in sorted(set(obj) - set(allowed), key=str):
        problems.append(f"{where}: unknown key {k}")
    for k in required:
        if k not in obj:
            problems.append(f"{where}: missing key {k}")
    return True


def _check_field_set(where, fields, nodes, problems):
    """Check a map of field name to {type, values, required, filled_by, not_run_text}.
    Returns the map of the fields that are mappings, for templates to look up."""
    if not isinstance(fields, dict):
        problems.append(f"{where}: must be a mapping of field names")
        return {}
    good = {}
    for name, spec in fields.items():
        at = f"{where} {name}"
        if not _keys(at, spec, FIELD_KEYS, ("type", "filled_by"), problems):
            continue
        good[name] = spec
        typ = spec.get("type")
        if "type" in spec and typ not in FIELD_TYPES:
            problems.append(f"{at}: unknown type {typ}")
        if typ == "enum" and not (isinstance(spec.get("values"), list) and spec["values"]):
            problems.append(f"{at}: an enum needs values")
        if "values" in spec and typ != "enum":
            problems.append(f"{at}: values are given for enum fields only")
        if "required" in spec and not isinstance(spec["required"], bool):
            problems.append(f"{at}: required must be true or false")
        if "not_run_text" in spec and not isinstance(spec["not_run_text"], str):
            problems.append(f"{at}: not_run_text must be text")
        if "filled_by" in spec:
            filled = spec["filled_by"]
            if not (isinstance(filled, list) and filled and all(isinstance(n, str) for n in filled)):
                problems.append(f"{at}: filled_by must be a list of node ids")
            else:
                for n in filled:
                    if n not in nodes:
                        problems.append(f"{at}: filled_by node {n} is not in the graph")
    return good


def _check_template(where, text, rows_name, row_fields, run_fields, problems):
    """Each {name} must be a field of the part's row set (row_fields None means the
    template has no rows), each {run.name} a run field, and each named field of type
    str, int, number, or enum."""
    if not isinstance(text, str):
        problems.append(f"{where}: must be text")
        return
    for m in TEMPLATE_FIELD.finditer(text):
        is_run, name = bool(m.group(1)), m.group(2)
        if is_run:
            spec = run_fields.get(name)
            if spec is None:
                problems.append(f"{where}: {m.group(0)} is not a run field")
                continue
        elif row_fields is None:
            problems.append(f"{where}: {m.group(0)} names no row set here, so write {{run.{name}}} for a run field")
            continue
        else:
            spec = row_fields.get(name)
            if spec is None:
                problems.append(f"{where}: {m.group(0)} is not a field of {rows_name}")
                continue
        typ = spec.get("type")
        if typ in FIELD_TYPES and typ not in TEMPLATE_TYPES:
            problems.append(f"{where}: {m.group(0)} names a field of type {typ}, and a template "
                            "takes only str, int, number, or enum fields")


def _check_lines(where, lines, rows_name, row_fields, run_fields, problems):
    if not isinstance(lines, list):
        problems.append(f"{where}: lines must be a list")
        return
    for j, line in enumerate(lines, 1):
        at = f"{where} line {j}"
        if _keys(at, line, *LINE_KEYS, problems):
            if "value" in line:
                _check_template(at + " value", line["value"], rows_name, row_fields, run_fields, problems)
            if "omit_empty" in line and not isinstance(line["omit_empty"], bool):
                problems.append(f"{at}: omit_empty must be true or false")


def _check_part(where, part, row_sets, run_fields, problems):
    if not isinstance(part, dict):
        problems.append(f"{where}: must be a mapping")
        return
    kind = part.get("kind")
    if kind not in PART_KEYS:
        problems.append(f"{where}: unknown kind {kind}")
        return
    where = f"{where} ({kind})"
    _keys(where, part, *PART_KEYS[kind], problems)
    if kind == "text":
        if "template" in part:
            _check_template(where + " template", part["template"], None, None, run_fields, problems)
        return
    rows = part.get("rows")
    if "rows" not in part:
        return
    if not isinstance(rows, str) or rows not in row_sets:
        problems.append(f"{where}: unknown row set {rows}")
        return
    fields = row_sets[rows]
    if kind == "table" and "columns" in part:
        if not isinstance(part["columns"], list):
            problems.append(f"{where}: columns must be a list")
        else:
            for j, col in enumerate(part["columns"], 1):
                at = f"{where} column {j}"
                if _keys(at, col, *COLUMN_KEYS, problems) and "value" in col:
                    _check_template(at + " value", col["value"], rows, fields, run_fields, problems)
    if kind == "list" and "line" in part:
        _check_template(where + " line", part["line"], rows, fields, run_fields, problems)
    if kind == "blocks":
        if "heading" in part:
            _check_template(where + " heading", part["heading"], rows, fields, run_fields, problems)
        if "lines" in part:
            _check_lines(where, part["lines"], rows, fields, run_fields, problems)
    if kind == "groups":
        by = part.get("by")
        values = None
        if "by" in part:
            spec = fields.get(by) if isinstance(by, str) else None
            if not spec or spec.get("type") != "enum":
                problems.append(f"{where}: by {by} is not an enum field of {rows}")
            else:
                values = spec.get("values") or []
        if "groups" in part:
            if not isinstance(part["groups"], list):
                problems.append(f"{where}: groups must be a list")
            else:
                for j, grp in enumerate(part["groups"], 1):
                    at = f"{where} group {j}"
                    if (_keys(at, grp, *GROUP_KEYS, problems) and values is not None
                            and "value" in grp and grp["value"] not in values):
                        problems.append(f"{at}: group value {grp['value']} is not among the values of {by}")
        if "block" in part:
            at = f"{where} block"
            block = part["block"]
            if _keys(at, block, *BLOCK_KEYS, problems):
                if "heading" in block:
                    _check_template(at + " heading", block["heading"], rows, fields, run_fields, problems)
                if "lines" in block:
                    _check_lines(at, block["lines"], rows, fields, run_fields, problems)


def check_schema(schema, g):
    """Problems with a stream schema, checked against its graph; an empty list means it
    is valid. The schema names the stream, a positive integer version, what one item
    is, the item field that names each item, the item fields, the run fields, other
    row sets (tables), the item fields the results file carries, and the report's
    layout of sections built from text, table, list, blocks, and groups parts."""
    problems = []
    if not _keys("schema", schema, SCHEMA_KEYS, SCHEMA_REQUIRED, problems):
        return problems
    nodes = set(g["_nodes"])
    if "stream" in schema and schema["stream"] != g.get("stream"):
        problems.append(f"schema stream {schema['stream']} differs from the graph's stream {g.get('stream')}")
    version = schema.get("version")
    if "version" in schema and not (isinstance(version, int) and not isinstance(version, bool) and version > 0):
        problems.append(f"version must be a positive integer, not {version!r}")
    if "item" in schema and not isinstance(schema["item"], str):
        problems.append("item must be text saying what one item is")
    items = _check_field_set("field", schema.get("fields", {}), nodes, problems)
    run_fields = _check_field_set("run field", schema.get("run", {}), nodes, problems)
    row_sets = {"items": items}
    tables = schema.get("tables", [])
    if not isinstance(tables, list):
        problems.append("tables must be a list")
        tables = []
    for i, table in enumerate(tables, 1):
        if not _keys(f"table {i}", table, TABLE_KEYS, ("id", "fields"), problems):
            continue
        tid = table.get("id")
        if not isinstance(tid, str):
            problems.append(f"table {i}: id must be text")
            continue
        if "fields" in table:
            row_sets[tid] = _check_field_set(f"table {tid} field", table["fields"], nodes, problems)
    if "id" in schema and schema["id"] not in items:
        problems.append(f"id {schema['id']} is not an item field")
    results = schema.get("results", [])
    if not isinstance(results, list):
        problems.append("results must be a list of item fields")
        results = []
    for name in results:
        if name not in items:
            problems.append(f"results entry {name} is not an item field")
    report = schema.get("report")
    if "report" in schema and _keys("report", report, REPORT_KEYS, ("title", "intro", "sections"), problems):
        for key in ("title", "intro"):
            if key in report:
                _check_template(f"report {key}", report[key], None, None, run_fields, problems)
        sections = report.get("sections", [])
        if not isinstance(sections, list):
            problems.append("report sections must be a list")
            sections = []
        for i, sec in enumerate(sections, 1):
            where = f"section {i}"
            if not _keys(where, sec, SECTION_KEYS, ("heading", "parts"), problems):
                continue
            where = f"section {i} ({sec.get('heading')})"
            parts = sec.get("parts", [])
            if not isinstance(parts, list):
                problems.append(f"{where}: parts must be a list")
                continue
            for j, part in enumerate(parts, 1):
                _check_part(f"{where} part {j}", part, row_sets, run_fields, problems)
    return problems


def _reachable(g, start):
    seen, queue = {start}, deque([start])
    while queue:
        cur = queue.popleft()
        for e in g["edges"]:
            if e["from"] == cur and e["to"] not in seen:
                seen.add(e["to"])
                queue.append(e["to"])
    return seen


def topo_order(g):
    indeg = {n["id"]: 0 for n in g["nodes"]}
    for e in g["edges"]:
        indeg[e["to"]] += 1
    ready = [n["id"] for n in g["nodes"] if indeg[n["id"]] == 0]
    order = []
    while ready:
        cur = ready.pop(0)
        order.append(cur)
        for e in g["edges"]:
            if e["from"] == cur:
                indeg[e["to"]] -= 1
                if indeg[e["to"]] == 0:
                    ready.append(e["to"])
    if len(order) != len(g["nodes"]):
        raise ValueError("graph has a cycle; verification graphs must be acyclic")
    return order


def _parse_check(expr):
    m = re.match(r"^\s*([\w.\-]+):([\w.]+)\s*(==|!=|>=|<=|>|<)\s*(.+?)\s*$", expr)
    if not m:
        raise ValueError(f"check must look like 'file.json:field OP value': {expr}")
    fname, field, op, rhs = m.groups()
    return fname, field, op, yaml.safe_load(rhs)


def eval_check(files_dir, expr):
    fname, field, op, value = _parse_check(expr)
    with open(os.path.join(files_dir, fname)) as f:
        actual = json.load(f)
    for part in field.split("."):
        actual = actual.get(part) if isinstance(actual, dict) else None
    ops = {"==": lambda a, b: a == b, "!=": lambda a, b: a != b,
           ">": lambda a, b: a is not None and a > b, ">=": lambda a, b: a is not None and a >= b,
           "<": lambda a, b: a is not None and a < b, "<=": lambda a, b: a is not None and a <= b}
    return ops[op](actual, value), actual


def node_pitfalls(g, node_id):
    """Guidance and pitfalls from every edge touching the node: what the step's
    executor should know at the moment it acts."""
    lines = []
    for e in g["edges"]:
        if node_id in (e["from"], e["to"]):
            lines.append(f"- {e['from']} -> {e['to']}: {e['guidance']}")
            for p in e["pitfalls"]:
                lines.append(f"    avoid: {p}")
    return "\n".join(lines)


# ---------------------------------------------------------------- contracts

def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


TYPES = {"int": int, "number": (int, float), "bool": bool, "str": str, "list": list, "dict": dict}


def _check_fields(where, data, spec, problems):
    for field, typ in spec.items():
        if field not in data:
            problems.append(f"{where}: missing field {field}")
        elif isinstance(typ, list):
            if data[field] not in typ:
                problems.append(f"{where}: {field}={data[field]!r} not in {typ}")
        else:
            ok = isinstance(data[field], TYPES[typ])
            if typ in ("int", "number") and isinstance(data[field], bool):
                ok = False
            if not ok:
                problems.append(f"{where}: {field} is not {typ}")


def validate(files_dir, produces):
    """Check produced files against the node contract. A .json spec may be a
    field map (object) or {items: field map} (a list of objects)."""
    problems = []
    for fname, spec in (produces or {}).items():
        path = os.path.join(files_dir, fname)
        if not os.path.exists(path):
            problems.append(f"{fname}: missing")
            continue
        if fname.endswith(".json") and spec:
            with open(path) as f:
                data = json.load(f)
            if "items" in spec:
                if not isinstance(data, list):
                    problems.append(f"{fname}: expected a list")
                    continue
                for i, item in enumerate(data):
                    _check_fields(f"{fname}[{i}]", item, spec["items"], problems)
            else:
                _check_fields(fname, data, spec, problems)
        elif fname.endswith(".md") and spec and "headings" in spec:
            with open(path) as f:
                heads = [ln.lstrip("#").strip() for ln in f if ln.startswith("#")]
            missing = [h for h in spec["headings"] if h not in heads]
            if missing:
                problems.append(f"{fname}: missing headings {missing}")
    return problems


# ---------------------------------------------------------------- executors

def _extract_json(text):
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    m = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, flags=re.S)
    if m:
        return json.loads(m.group(1))
    start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=-1)
    if start < 0:
        raise ValueError("no JSON in response")
    end = max(text.rfind("}"), text.rfind("]"))
    return json.loads(text[start:end + 1])


def provider_path():
    """provider.yaml in CONNECTIONS_HOME when it is set, else in ~/.workflow_connections."""
    home = os.environ.get("CONNECTIONS_HOME") or os.path.join(os.path.expanduser("~"), ".workflow_connections")
    return os.path.join(home, PROVIDER_FILE)


def provider_setting():
    """The provider setting's base_url and model, with token_limit, token_limit_field, and
    request_timeout when the file names them. Raises RuntimeError naming the file when it
    is missing, cannot be read, lacks base_url or model, or names a limit or a timeout that
    is not a whole number above 0 or a field other than max_tokens or max_completion_tokens."""
    path = provider_path()
    try:
        with open(path) as f:
            setting = yaml.safe_load(f)
    except FileNotFoundError:
        raise RuntimeError(f"there is no provider setting at {path}. Write base_url and model there")
    except (OSError, yaml.YAMLError) as err:
        raise RuntimeError(f"the provider setting {path} cannot be read ({err})")
    if not isinstance(setting, dict):
        raise RuntimeError(f"the provider setting {path} must hold base_url and model")
    for key in ("base_url", "model"):
        value = setting.get(key)
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError(f"the provider setting {path} lacks {key}")
    found = {"base_url": setting["base_url"], "model": setting["model"]}
    if "token_limit" in setting:
        limit = setting["token_limit"]
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise RuntimeError(f"the provider setting {path} has a wrong token_limit, "
                               "which must be a whole number above 0")
        found["token_limit"] = limit
    if "token_limit_field" in setting:
        field = setting["token_limit_field"]
        if not isinstance(field, str) or field not in TOKEN_LIMIT_FIELDS:
            raise RuntimeError(f"the provider setting {path} has a wrong token_limit_field, "
                               "which must be " + " or ".join(TOKEN_LIMIT_FIELDS))
        found["token_limit_field"] = field
    if "request_timeout" in setting:
        wait = setting["request_timeout"]
        if isinstance(wait, bool) or not isinstance(wait, int) or wait <= 0:
            raise RuntimeError(f"the provider setting {path} has a wrong request_timeout, "
                               "which must be a whole number of seconds above 0")
        found["request_timeout"] = wait
    return found


def token_limit(provider):
    """(limit, field) for a live request, from a provider setting or a manifest's provider
    block. A key the provider does not hold keeps the request Table A10 records."""
    return (provider.get("token_limit", DEFAULT_TOKEN_LIMIT),
            provider.get("token_limit_field", TOKEN_LIMIT_FIELDS[0]))


def is_live(spec):
    return spec == "live" or (spec.startswith("live:") and bool(spec[len("live:"):].strip()))


def executor_kind_ok(spec):
    """An executor is recorded:<file>, live, or live:<model>."""
    return is_live(spec) or (spec.startswith("recorded:") and bool(spec[len("recorded:"):].strip()))


def call_executor(spec, prompt, item_key, provider=None):
    """Returns (raw_text, executor_id, reply). spec is recorded:<path>, live, or live:<model>.
    A live call posts to <base_url>/chat/completions with the provider's model, or the
    one named, waits the provider's request_timeout (300 seconds when it names none), and
    returns the executor id live:<model the service reports> and the whole reply as the
    bytes the service sent. A recorded executor gives no reply."""
    kind, _, arg = spec.partition(":")
    if kind == "recorded":
        with open(arg) as f:
            book = json.load(f)
        if item_key not in book:
            raise KeyError(f"recorded executor has no answer for {item_key}")
        ans = book[item_key]
        return (ans if isinstance(ans, str) else json.dumps(ans)), f"recorded:{os.path.basename(arg)}", None
    if is_live(spec):
        if provider is None:
            provider = provider_setting()
        model = arg.strip() or provider["model"]
        url = provider["base_url"].rstrip("/") + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        key = os.environ.get(KEY_ENV)
        if key:
            headers["Authorization"] = f"Bearer {key}"
        limit, field = token_limit(provider)
        wait = provider.get("request_timeout", DEFAULT_REQUEST_TIMEOUT)
        body = {"model": model, "temperature": 0, field: limit,
                "messages": [{"role": "user", "content": prompt}]}
        last = None
        for attempt in range(4):
            try:
                req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
                with urllib.request.urlopen(req, timeout=wait) as r:
                    sent = r.read()
                data = json.loads(sent)
                return (data["choices"][0]["message"]["content"] or "",
                        f"live:{data.get('model') or model}", sent)
            except Exception as err:  # retry transient failures (429, timeouts)
                last = err
                time.sleep(5 * (attempt + 1))
        raise RuntimeError(f"live call to {url} failed: {last}")
    raise ValueError(f"unknown executor {spec}")


RETRY_NOTE = ("\n\nYour previous reply could not be parsed. Reply with only the single JSON "
              "object asked for: no prose, no code fence, and escape any quotation marks inside strings.")


def finding_dict(check, severity, item, message, evidence=""):
    return {"check": check, "severity": severity, "item": str(item), "message": message, "evidence": evidence}


def _render(template, item, g, node_id):
    out = template.replace("{{pitfalls}}", node_pitfalls(g, node_id))
    out = out.replace("{{goal}}", g["goal"].strip())
    out = out.replace("{{item}}", json.dumps(item, indent=2, ensure_ascii=False))
    for k, v in item.items():
        out = out.replace("{{item." + k + "}}", v if isinstance(v, str) else json.dumps(v, ensure_ascii=False))
    return out


def _where(item, expr):
    if not expr:
        return True
    field, _, allowed = expr.partition(" in ")
    return item.get(field.strip()) in yaml.safe_load(allowed)


# ---------------------------------------------------------------- runs

def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def write_json(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write("\n")


def trail(run_dir, **event):
    with open(os.path.join(run_dir, "trail.jsonl"), "a") as f:
        f.write(json.dumps(dict(at=now(), **event), ensure_ascii=False) + "\n")


def same_model(a, b, provider=None):
    """Two recorded executors are the same model when they name the same file (by
    real path). Any other two are the same model when the part after the first
    colon is the same, ignoring case and surrounding spaces. A bare live executor
    is read as live:<the provider's model> (reconciliation, Track D, D15)."""
    if provider is not None:
        a = "live:" + provider["model"] if a.strip() == "live" else a
        b = "live:" + provider["model"] if b.strip() == "live" else b
    kind_a, _, arg_a = a.partition(":")
    kind_b, _, arg_b = b.partition(":")
    if kind_a.strip() == "recorded" and kind_b.strip() == "recorded":
        return os.path.realpath(arg_a.strip()) == os.path.realpath(arg_b.strip())
    return arg_a.strip().lower() == arg_b.strip().lower()


def reads_every_input(g):
    """Whether a step of the graph may read any input file, its contract's reads_optional
    naming "*", as the data procedure's inventory and the data phase reports' outline_steps
    do. Such a run also carries the inputs folder's subfolders (Track V, step V4)."""
    return any("*" in ((g["_contracts"].get(n["id"]) or {}).get("reads_optional") or [])
               for n in g["nodes"])


def subfolder_files(folder):
    """The regular files inside the folder's subfolders, as paths inside it with forward
    slashes, sorted. Hidden files and folders, byte-code caches, links, the hidden truth,
    and recorded answers are left out, so a script at code/s1.py enters a run and a
    copy kept under __pycache__ or .git does not."""
    out = []
    for top, dirs, names in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d != "__pycache__")
        if os.path.samefile(top, folder):
            continue
        for name in sorted(names):
            path = os.path.join(top, name)
            if (name.startswith(".") or name == "truth.yaml" or name.startswith("recorded_")
                    or os.path.islink(path) or not os.path.isfile(path)):
                continue
            out.append(os.path.relpath(path, folder).replace(os.sep, "/"))
    return sorted(out)


def init_run(graph_path, run_dir, inputs_dir, judge=None, second=None, quick=False):
    if os.path.exists(run_dir):
        sys.exit(f"run dir exists: {run_dir}")
    g = load(graph_path)
    problems = check(g)
    if problems:
        sys.exit("graph fails check:\n" + "\n".join(problems))
    for spec in (judge, second):
        if spec and not executor_kind_ok(spec):
            sys.exit(f"unknown executor {spec}. An executor is recorded:<file>, live, or live:<model>")
    provider = None
    if any(spec and is_live(spec) for spec in (judge, second)):
        try:
            provider = provider_setting()
        except RuntimeError as err:
            sys.exit(f"a live executor needs the provider setting, and {err}")
    has_second = any(n.get("kind") == "judgment" and n.get("role") == "second" for n in g["nodes"])
    if has_second and judge and second and same_model(judge, second, provider):
        sys.exit(f"the second checker must be a different model from the judge ({second})")
    for sub in ("files", "records", "code", "prompts", "responses", "logs"):
        os.makedirs(os.path.join(run_dir, sub))
    inputs = {}
    for name in sorted(os.listdir(inputs_dir)):
        src = os.path.join(inputs_dir, name)
        if name in ("truth.yaml",) or name.startswith("recorded_") or not os.path.isfile(src):
            continue  # hidden truth and recorded answers never enter the run
        shutil.copy2(src, os.path.join(run_dir, "files", name))
        inputs[name] = sha(src)
    if reads_every_input(g):
        for rel in subfolder_files(inputs_dir):
            dest = os.path.join(run_dir, "files", *rel.split("/"))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(os.path.join(inputs_dir, *rel.split("/")), dest)
            inputs[rel] = sha(dest)
    manifest = {
        "created_at": now(),
        "stream": g["stream"],
        "graph": {"path": os.path.relpath(g["_path"], ROOT), "version": g["version"], "sha256": sha(g["_path"])},
        "contracts": {"path": g["contracts"], "sha256": sha(os.path.join(ROOT, g["contracts"]))},
        "inputs_from": os.path.abspath(inputs_dir),
        "inputs": inputs,
        "executors": {"judge": judge, "second": second},
        "python": sys.version.split()[0],
    }
    if provider is not None:
        limit, field = token_limit(provider)
        manifest["provider"] = {"base_url": provider["base_url"], "model": provider["model"],
                                "token_limit": limit, "token_limit_field": field,
                                "request_timeout": provider.get("request_timeout", DEFAULT_REQUEST_TIMEOUT)}
    if "schema" in g:
        schema_path = os.path.join(ROOT, g["schema"])
        manifest["schema"] = {"path": g["schema"], "version": load_schema(g["schema"])["version"],
                              "sha256": sha(schema_path)}
    if quick:
        manifest["quick"] = True
    write_json(os.path.join(run_dir, "manifest.json"), manifest)
    trail(run_dir, event="run_initialized", stream=g["stream"], graph_version=g["version"])
    return g


def _manifest(run_dir):
    with open(os.path.join(run_dir, "manifest.json")) as f:
        return json.load(f)


def records(run_dir):
    rdir = os.path.join(run_dir, "records")
    out = []
    for name in sorted(os.listdir(rdir)):
        with open(os.path.join(rdir, name)) as f:
            out.append(json.load(f))
    return out


def _actual_text(value):
    return json.dumps(value, ensure_ascii=False)


def write_steps(run_dir, g):
    """Write files/steps.json, {"steps": [{"node", "status", "reason"}]}, for every node but
    the exit, in topological order. A node with a record ran. Any other node was skipped,
    and its reason names each check on an edge into it that did not fire, as
    "<check> was false (actual <value>)", or says no incoming edge fired. It holds no time,
    so a replay of the exit step sees the same file."""
    recs = records(run_dir)
    ran = {r["node"] for r in recs}
    steps = []
    for nid in topo_order(g):
        if nid == g["exit"]:
            continue
        if nid in ran:
            steps.append({"node": nid, "status": "ran", "reason": ""})
            continue
        unfired = []
        for r in recs:
            for b in r.get("branches", []):
                if b["to"] == nid and not b["fired"] and b.get("check"):
                    unfired.append("%s was false (actual %s)" % (b["check"], _actual_text(b.get("actual"))))
        steps.append({"node": nid, "status": "skipped",
                      "reason": "; ".join(unfired) or "no incoming edge fired"})
    write_json(os.path.join(run_dir, "files", "steps.json"), {"steps": steps})


def step(run_dir, node_id):
    m = _manifest(run_dir)
    g = load(os.path.join(ROOT, m["graph"]["path"]))
    if sha(g["_path"]) != m["graph"]["sha256"]:
        sys.exit("graph changed since run started; start a new run")
    node, contract = g["_nodes"][node_id], g["_contracts"][node_id]
    files = os.path.join(run_dir, "files")
    schema_exit = node_id == g["exit"] and "schema" in g
    if schema_exit:
        write_steps(run_dir, g)
    seq = len(records(run_dir)) + 1
    tag = f"{seq:02d}_{node_id}"
    missing = [r for r in contract.get("reads", []) if not os.path.exists(os.path.join(files, r))]
    if missing:
        sys.exit(f"{node_id}: required inputs not present: {missing}")
    inputs = {r: sha(os.path.join(files, r)) for r in contract.get("reads", [])}
    for pat in contract.get("reads_optional", []):
        for fn in sorted(glob.glob(os.path.join(files, pat))):
            if os.path.isfile(fn):
                inputs.setdefault(os.path.basename(fn), sha(fn))
        for rel in subfolder_files(files):
            if fnmatch.fnmatchcase(rel, pat):
                inputs.setdefault(rel, sha(os.path.join(files, *rel.split("/"))))
    trail(run_dir, event="step_started", node=node_id, seq=seq, kind=node["kind"])
    started, t0 = now(), time.time()
    before = {fn: sha(os.path.join(files, fn)) for fn in os.listdir(files)
              if os.path.isfile(os.path.join(files, fn))}

    if node["kind"] == "tool":
        code_dir = os.path.join(run_dir, "code", tag)
        os.makedirs(code_dir)
        src = impl_path(g, node_id)
        shutil.copy2(src, code_dir)
        lib = os.path.join(ROOT, "implementations", "_lib.py")
        shutil.copy2(lib, code_dir)
        if schema_exit:
            # the one report builder and the stream's schema, pinned by the record's checksums
            shutil.copy2(os.path.join(ROOT, "implementations", "_report.py"), code_dir)
            shutil.copy2(os.path.join(ROOT, g["schema"]), os.path.join(code_dir, "schema.yaml"))
        proc = subprocess.run([sys.executable, os.path.join(code_dir, os.path.basename(src)), files],
                              capture_output=True, text=True,
                              env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        for stream, text in (("stdout", proc.stdout), ("stderr", proc.stderr)):
            with open(os.path.join(run_dir, "logs", f"{tag}.{stream}"), "w") as f:
                f.write(text)
        execution = {"type": "script", "executor": "python3",
                     "code_files": {os.path.relpath(os.path.join(code_dir, n), run_dir): sha(os.path.join(code_dir, n))
                                    for n in sorted(os.listdir(code_dir))},
                     "exit_code": proc.returncode, "logs": [f"logs/{tag}.stdout", f"logs/{tag}.stderr"],
                     "replay": node.get("replay", "exact")}
        problems = validate(files, contract.get("produces")) if proc.returncode == 0 else [
            f"script exited {proc.returncode}; see logs/{tag}.stderr"]
    else:
        execution, problems = _judgment(run_dir, g, node, contract, tag, m)

    overwritten = [fn for fn, h in before.items()
                   if os.path.exists(os.path.join(files, fn)) and sha(os.path.join(files, fn)) != h]
    if overwritten:
        problems.append(f"step overwrote existing files {overwritten}; steps only add files")
    outputs = {fn: sha(os.path.join(files, fn)) for fn in (contract.get("produces") or {})
               if os.path.exists(os.path.join(files, fn))}
    branches = []
    if not problems:
        for e in g["edges"]:
            if e["from"] != node_id:
                continue
            if "check" in e:
                fired, actual = eval_check(files, e["check"])
                branches.append({"to": e["to"], "rel": e["rel"], "check": e["check"], "actual": actual, "fired": fired})
            else:
                branches.append({"to": e["to"], "rel": e["rel"], "check": None, "fired": True})
    record = {
        "record_version": 1, "seq": seq, "node": node_id, "kind": node["kind"],
        "graph_version": g["version"], "started_at": started, "duration_s": round(time.time() - t0, 2),
        "inputs": inputs, "execution": execution, "outputs": outputs,
        "checks": {"contract": "fail" if problems else "pass", "problems": problems},
        "branches": branches,
    }
    write_json(os.path.join(run_dir, "records", f"{tag}.json"), record)
    trail(run_dir, event="step_finished", node=node_id, seq=seq, contract=record["checks"]["contract"],
          fired=[b["to"] for b in branches if b["fired"]])
    return record


def _judgment(run_dir, g, node, contract, tag, m):
    """One prompt per item (or one prompt if no foreach). Output: <node>.json, a
    list of the parsed answers, each carrying item_id, executor, and prompt hash.
    Each answer's text goes to responses/<tag>/<item>.txt, and a live executor's whole
    reply, the bytes the service sent, beside it to <item>.reply.json (.retry.txt and
    .retry.reply.json for a retry). The record lists each reply file with its sha256."""
    files = os.path.join(run_dir, "files")
    with open(impl_path(g, node["id"])) as f:
        template = f.read()
    role = node.get("role", "judge")
    spec = m["executors"].get(role)
    if not spec:
        return {"type": "judgment", "role": role, "executor": None}, [f"no executor configured for role {role}"]
    if node.get("foreach"):
        with open(os.path.join(files, node["foreach"])) as f:
            items = [it for it in json.load(f) if _where(it, node.get("where"))]
    else:
        items = [{"id": "all"}]
    answers, problems, used, unjudged, replies = [], [], set(), [], []
    pdir = os.path.join(run_dir, "prompts", tag)
    rdir = os.path.join(run_dir, "responses", tag)
    os.makedirs(pdir)
    os.makedirs(rdir)
    for it in items:
        item_id = str(it.get("id"))
        prompt = _render(template, it, g, node["id"])
        with open(os.path.join(pdir, f"{item_id}.txt"), "w") as f:
            f.write(prompt)
        ans, why = None, ""
        for attempt in (1, 2):
            ask = prompt if attempt == 1 else prompt + RETRY_NOTE
            try:
                raw, exe, reply = call_executor(spec, ask, f"{node['id']}:{item_id}", m.get("provider"))
            except Exception as err:
                why = f"executor failed: {err}"
                break
            used.add(exe)
            stem = item_id if attempt == 1 else f"{item_id}.retry"
            with open(os.path.join(rdir, f"{stem}.txt"), "w") as f:
                f.write(raw)
            if reply is not None:
                saved = os.path.join(rdir, f"{stem}.reply.json")
                with open(saved, "wb") as f:
                    f.write(reply)
                replies.append({"path": os.path.relpath(saved, run_dir), "sha256": sha(saved)})
            try:
                ans = _extract_json(raw)
            except Exception as err:
                ans, why = None, f"unparseable response ({err})"
                continue
            if not isinstance(ans, dict):
                ans, why = None, "response is not a JSON object"
                continue
            break
        if ans is None:
            unjudged.append(finding_dict(node["id"], "warning", item_id,
                                         "not judged: " + why[:200], spec))
            trail(run_dir, event="judgment_unjudged", node=node["id"], item=item_id, reason=why[:200])
            continue
        ans.update(item_id=item_id, executor=exe, prompt_sha256="sha256:" + hashlib.sha256(prompt.encode()).hexdigest())
        answers.append(ans)
        trail(run_dir, event="judgment_item", node=node["id"], item=item_id, executor=exe)
    out_name = f"{node['id']}.json"
    write_json(os.path.join(files, out_name), answers)
    # always written, so a report that reads findings_*.json replays identically
    write_json(os.path.join(files, f"findings_unjudged_{node['id']}.json"), unjudged)
    problems += validate(files, contract.get("produces"))
    execution = {"type": "judgment", "role": role, "executor": sorted(used) or [spec],
                 "items": len(items), "unjudged": [u["item"] for u in unjudged],
                 "prompts": os.path.relpath(pdir, run_dir), "responses": os.path.relpath(rdir, run_dir)}
    if replies:
        execution["replies"] = replies
    return execution, problems


def run_all(run_dir):
    """Walk the graph: a node runs when the entry or any incoming fired edge
    activates it; nodes run in topological order. A failed contract stops the run."""
    m = _manifest(run_dir)
    g = load(os.path.join(ROOT, m["graph"]["path"]))
    active = {g["entry"]}
    for nid in topo_order(g):
        if nid not in active:
            trail(run_dir, event="step_skipped", node=nid, reason="no incoming edge fired")
            continue
        rec = step(run_dir, nid)
        status = rec["checks"]["contract"]
        print(f"{rec['seq']:02d} {nid:28s} {rec['kind']:9s} {status}"
              + (f"  {rec['checks']['problems'][:3]}" if rec["checks"]["problems"] else ""))
        if status == "fail":
            trail(run_dir, event="run_stopped", node=nid)
            return 1
        active |= {b["to"] for b in rec["branches"] if b["fired"]}
    trail(run_dir, event="run_finished")
    write_results(run_dir)
    return 0


def run_quick(pid, run_dir, inputs_dir, judge=None, second=None):
    """The light working check. Start a run of the registered procedure pid as usual, with
    "quick": true in the manifest, then run its quick steps in order through step(),
    stopping at the first contract failure. Append run_quick_finished to the trail and
    print the blocking findings and warnings in those steps' findings files. No report and
    no results file are written. Returns 1 when a step failed, otherwise 0."""
    entry = registered(pid)
    if entry is None:
        sys.exit(f"--quick takes a registered procedure id, and {pid} is not one")
    problems = check_registry({"registry_version": REGISTRY_VERSION, "procedures": [entry]})
    if problems:
        sys.exit("the registry entry fails its check:\n" + "\n".join(problems))
    init_run(os.path.join(ROOT, entry["graph"]), run_dir, inputs_dir, judge, second, quick=True)
    files = os.path.join(run_dir, "files")
    failed, ran, blocking, warnings = False, 0, 0, 0
    for nid in entry["quick_steps"]:
        rec = step(run_dir, nid)
        ran += 1
        status = rec["checks"]["contract"]
        print(f"{rec['seq']:02d} {nid:28s} {rec['kind']:9s} {status}"
              + (f"  {rec['checks']['problems'][:3]}" if rec["checks"]["problems"] else ""))
        for name in sorted(rec["outputs"]):
            if not name.startswith("findings_"):
                continue
            try:
                with open(os.path.join(files, name)) as f:
                    found = json.load(f)
            except (OSError, ValueError):
                continue
            for x in found if isinstance(found, list) else []:
                severity = x.get("severity") if isinstance(x, dict) else None
                blocking += severity == "blocking"
                warnings += severity == "warning"
        if status == "fail":
            trail(run_dir, event="run_stopped", node=nid)
            failed = True
            break
    trail(run_dir, event="run_quick_finished")
    print(f"quick: {blocking} blocking, {warnings} warnings from {ran} steps")
    return 1 if failed else 0


def verify(run_dir):
    """Replay each tool step from its saved code on copies of its recorded
    inputs and compare .json outputs by hash. Judgment steps are listed."""
    files = os.path.join(run_dir, "files")
    results = []
    for r in records(run_dir):
        ex = r["execution"]
        if ex["type"] != "script":
            results.append((r["seq"], r["node"], "judgment: recorded answers kept; review, not replay"))
            continue
        if ex.get("replay") == "network":
            results.append((r["seq"], r["node"], "network step: outputs hashed, not replayed"))
            continue
        with tempfile.TemporaryDirectory() as tmp:
            for fn, h in r["inputs"].items():
                if sha(os.path.join(files, fn)) != h:
                    # input was overwritten later in the run; replay is still valid
                    # only if the recorded hash can be matched, so report it
                    results.append((r["seq"], r["node"], f"FAIL input {fn} changed after step ran"))
                    break
                os.makedirs(os.path.dirname(os.path.join(tmp, fn)), exist_ok=True)
                shutil.copy2(os.path.join(files, fn), os.path.join(tmp, fn))
            else:
                # the step's own script, by its node name; a folder saved without one
                # falls back to the first saved file that is not a helper
                own = [p for p in ex["code_files"] if os.path.basename(p) == r["node"] + ".py"]
                script = (own or [p for p in ex["code_files"] if not p.endswith("_lib.py")])[0]
                proc = subprocess.run([sys.executable, os.path.join(run_dir, script), tmp],
                                      capture_output=True, text=True,
                              env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
                if proc.returncode:
                    results.append((r["seq"], r["node"], "FAIL replay errored"))
                    continue
                diffs = [fn for fn, h in r["outputs"].items()
                         if os.path.exists(os.path.join(tmp, fn)) and sha(os.path.join(tmp, fn)) != h]
                results.append((r["seq"], r["node"], "FAIL outputs differ: " + ", ".join(diffs) if diffs
                                else "replay matches"))
    for seq, node, verdict in results:
        print(f"{seq:02d} {node:28s} {verdict}")
    write_json(os.path.join(run_dir, "verify.json"),
               {"verified_at": now(), "steps": [{"seq": s, "node": n, "verdict": v} for s, n, v in results]})
    trail(run_dir, event="verified", failures=sum(v.startswith("FAIL") for _, _, v in results))
    return 1 if any(v.startswith("FAIL") for _, _, v in results) else 0


def score(run_dir, truth_path):
    """Seeded-fault scoring. truth.yaml: {faults: [{id, check, item}], clean_items: [...]}.
    A fault is caught when a finding of any severity has the same check and an item
    containing the truth item (Track C2 plan choice 7), so a report that ranks nothing is
    still measured. Blocking and warning findings matching no fault are extras."""
    with open(os.path.join(run_dir, "files", "findings.json")) as f:
        findings = json.load(f)
    with open(truth_path) as f:
        truth = yaml.safe_load(f) or {}
    faults = truth.get("faults") or []
    caught, missed, used = [], [], set()
    for t in faults:
        hit = [i for i, x in enumerate(findings)
               if x["check"] == t["check"] and str(t["item"]) in str(x["item"])]
        (caught if hit else missed).append(t["id"])
        used.update(hit)
    extras = [findings[i] for i in range(len(findings))
              if i not in used and findings[i]["severity"] in ("blocking", "warning")]
    result = {"faults": len(faults), "caught": caught, "missed": missed,
              "recall": round(len(caught) / len(faults), 3) if faults else None,
              "extra_findings": [{"check": x["check"], "item": x["item"], "message": x["message"]} for x in extras]}
    write_json(os.path.join(run_dir, "score.json"), result)
    print(json.dumps({k: result[k] for k in ("faults", "recall", "missed")}),
          f"extras={len(extras)}")
    return result


# ---------------------------------------------------------------- results and decisions

RESULTS_SCHEMA = "verification-results"
RESULTS_SCHEMA_VERSION = 1
# The value a results field takes when the builder marked it not run, by the field's type, so
# the results file keeps each field's type and its readers stay as the slice made them. The
# reason stays in fields.json.
NOT_RUN_EMPTY = {"str": "", "list": [], "dict": {}}


def _pinned_schema(run_dir):
    """The schema the run's exit step ran with, the copy in its code folder, or None."""
    copies = sorted(glob.glob(os.path.join(run_dir, "code", "*", "schema.yaml")))
    if not copies:
        return None
    with open(copies[-1], encoding="utf-8") as f:
        return yaml.safe_load(f)


def result_items(run_dir):
    """The run's items for its results file, one for each item row of files/fields.json in
    row order, holding the fields the schema's results list names, in that order. A value
    the builder marked not run is written as the empty value of its field's type (None for
    a type with no empty value). A field the schema marks required false is left out of an
    item whose row does not give it. None when the run has no fields.json or no pinned
    schema, as for a graph with no schema."""
    path = os.path.join(run_dir, "files", "fields.json")
    schema = _pinned_schema(run_dir)
    if not os.path.isfile(path) or schema is None:
        return None
    with open(path, encoding="utf-8") as f:
        rows = json.load(f).get("items") or []
    specs = schema.get("fields") or {}
    items = []
    for row in rows:
        item = {}
        for name in schema.get("results") or []:
            if name not in row and (specs.get(name) or {}).get("required") is False:
                continue
            value = row.get(name)
            if isinstance(value, dict) and set(value) == {"not_run"}:
                value = copy.deepcopy(NOT_RUN_EMPTY.get((specs.get(name) or {}).get("type")))
            item[name] = value
        items.append(item)
    return items


def write_results(run_dir):
    """Write <run>/results.json for a run that completed, with its items taken from the
    run's fields.json. The file sits beside the step files, not among them, so a replay
    never sees it. It starts with no decisions. A run without fields.json (a graph with no
    schema) gets no results file, and None is returned."""
    items = result_items(run_dir)
    if items is None:
        return None
    m = _manifest(run_dir)
    results = {
        "schema": RESULTS_SCHEMA,
        "schema_version": RESULTS_SCHEMA_VERSION,
        "stream": m["stream"],
        "run_id": os.path.basename(run_dir),
        "procedure_version": m["graph"]["version"],
        "inputs": m["inputs"],
        "items": items,
        "decisions": [],
    }
    write_json(os.path.join(run_dir, "results.json"), results)
    return results


def decide(run_dir, item_id, decision, by):
    """Add the scholar's decision on one item to the run's results file, then write
    <run>/report_decided.md. Decisions are kept in the order they are made, and the latest
    one for an item is the one that counts. The run's report.md and step records are left
    as the run wrote them."""
    path = os.path.join(run_dir, "results.json")
    if not os.path.isfile(path):
        sys.exit(f"no results file in {run_dir}, since only a run that completed has one")
    with open(path) as f:
        results = json.load(f)
    item = next((it for it in results["items"] if it["id"] == item_id), None)
    if item is None:
        sys.exit(f"unknown item {item_id} in run {results['run_id']}")
    if not item["needs_decision"]:
        sys.exit(f"item {item_id} needs no decision")
    results["decisions"].append({"item": item_id, "decision": decision, "by": by,
                                 "at": now(), "run_id": results["run_id"]})
    write_json(path, results)
    write_decided_report(run_dir, results)
    print(f"{item_id} {decision} by {by} on run {results['run_id']}, report_decided.md written")
    return 0


def _cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def write_decided_report(run_dir, results):
    """<run>/report_decided.md is the run's report with the decisions placed before its
    first section. They are a count of approved, held, and undecided items and a short
    table of each item's latest decision. Items that need no decision are not listed."""
    latest = {}
    for entry in results["decisions"]:
        latest[entry["item"]] = entry
    counts = {"approved": 0, "held": 0, "undecided": 0}
    table = ["| Item | Decision | By | At | Run |", "|---|---|---|---|---|"]
    for item in results["items"]:
        if not item["needs_decision"]:
            continue
        entry = latest.get(item["id"])
        word = entry["decision"] if entry else "undecided"
        counts[word] += 1
        cells = [item["id"], word] + ([entry["by"], entry["at"], entry["run_id"]] if entry
                                      else ["-", "-", "-"])
        table.append("| " + " | ".join(_cell(c) for c in cells) + " |")
    block = (["## Decisions", "",
              "**%d approved, %d held, %d undecided.**" % (
                  counts["approved"], counts["held"], counts["undecided"]), ""]
             + table + [""])
    with open(os.path.join(run_dir, "files", "report.md"), encoding="utf-8") as f:
        lines = f.read().split("\n")
    first = next((i for i, line in enumerate(lines) if line.startswith("## ")), len(lines))
    with open(os.path.join(run_dir, "report_decided.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines[:first] + block + lines[first:]))


# ---------------------------------------------------------------- the procedure registry

REGISTRY = "registry.yaml"
REGISTRY_VERSION = 1
REGISTRY_KEYS = ("id", "stream", "name", "procedure", "graph", "triggers", "quick_steps")
TRIGGER_KEYS = ("events", "phrases", "files")
EVENTS = ("ai_edit", "turn_end", "build", "commit")


def load_registry(path=None):
    """The procedure registry, registry.yaml in the folder of vg.py unless a path is given."""
    with open(path or os.path.join(ROOT, REGISTRY), encoding="utf-8") as f:
        return yaml.safe_load(f)


def _texts(value):
    return isinstance(value, list) and bool(value) and all(isinstance(v, str) and v for v in value)


def check_registry(reg):
    """Problems with a registry; an empty list means it is valid. Ids are unique, each graph
    exists, passes check, and names a schema, the entry's stream is the graph's, the
    trigger keys and events are the known ones, phrases and files are non-empty lists of
    text, and quick_steps is a list of step names that follows the quick-step rule."""
    if not isinstance(reg, dict):
        return ["the registry must be a mapping"]
    problems = []
    if reg.get("registry_version") != REGISTRY_VERSION:
        problems.append(f"registry_version must be {REGISTRY_VERSION}, not {reg.get('registry_version')}")
    entries = reg.get("procedures")
    if not isinstance(entries, list):
        return problems + ["procedures must be a list"]
    seen = set()
    for i, e in enumerate(entries, 1):
        if not isinstance(e, dict):
            problems.append(f"procedure {i}: must be a mapping")
            continue
        pid = e.get("id")
        at = f"procedure {pid if isinstance(pid, str) and pid else i}"
        if pid in seen:
            problems.append(f"{at}: repeated id")
        seen.add(pid)
        for key in REGISTRY_KEYS:
            if key not in e:
                problems.append(f"{at}: missing key {key}")
        for key in sorted(set(e) - set(REGISTRY_KEYS)):
            problems.append(f"{at}: unknown key {key}")
        for key in ("id", "stream", "name", "procedure", "graph"):
            if key in e and not (isinstance(e[key], str) and e[key]):
                problems.append(f"{at}: {key} must be text")
        graph = e.get("graph")
        checked = None  # the graph, when it exists and passes its check
        if isinstance(graph, str) and graph:
            path = os.path.join(ROOT, graph)
            if not os.path.isfile(path):
                problems.append(f"{at}: graph {graph} does not exist")
            else:
                g = load(path)
                graph_problems = check(g)
                for p in graph_problems:
                    problems.append(f"{at}: graph {graph} fails check: {p}")
                if not graph_problems:
                    checked = g
                if "schema" not in g:
                    problems.append(f"{at}: graph {graph} names no schema")
                if "stream" in e and e["stream"] != g.get("stream"):
                    problems.append(f"{at}: stream {e['stream']} differs from the graph's stream {g.get('stream')}")
        triggers = e.get("triggers")
        if "triggers" in e and not isinstance(triggers, dict):
            problems.append(f"{at}: triggers must be a mapping")
        elif isinstance(triggers, dict):
            for key in TRIGGER_KEYS:
                if key not in triggers:
                    problems.append(f"{at}: missing trigger key {key}")
            for key in sorted(set(triggers) - set(TRIGGER_KEYS)):
                problems.append(f"{at}: unknown trigger key {key}")
            events = triggers.get("events")
            if "events" in triggers:
                if not _texts(events):
                    problems.append(f"{at}: events must be a non-empty list of text")
                else:
                    for ev in events:
                        if ev not in EVENTS:
                            problems.append(f"{at}: unknown event {ev}")
            for key in ("phrases", "files"):
                if key in triggers and not _texts(triggers[key]):
                    problems.append(f"{at}: {key} must be a non-empty list of text")
        quick = e.get("quick_steps")
        if "quick_steps" in e and not (isinstance(quick, list)
                                       and all(isinstance(q, str) and q for q in quick)):
            problems.append(f"{at}: quick_steps must be a list of step names")
        elif isinstance(quick, list) and checked is not None:
            problems += [f"{at}: {p}" for p in check_quick_steps(checked, quick, graph)]
    return problems


def check_quick_steps(g, quick, graph):
    """The quick-step rule. Each quick step is a tool step of the graph and not the exit,
    the steps are listed in the graph's topological order, each one other than the entry
    has an unconditional edge from an earlier quick step, and each one's contract reads
    are procedure inputs or files an earlier quick step produces."""
    problems = []
    order = topo_order(g)
    inputs = set(inputs_of(g)["required"])
    earlier, produced, last = [], set(), -1
    for q in quick:
        if q not in g["_nodes"]:
            problems.append(f"quick step {q} is not a step of {graph}")
            continue
        if g["_nodes"][q]["kind"] != "tool":
            problems.append(f"quick step {q} is a judgment step")
        if q == g["exit"]:
            problems.append(f"quick step {q} is the exit step")
        at = order.index(q)
        if at <= last:
            problems.append(f"quick step {q} is listed out of the graph's order")
        last = max(last, at)
        if q != g["entry"] and not any(e["to"] == q and e["from"] in earlier and "check" not in e
                                       for e in g["edges"]):
            problems.append(f"quick step {q} has no unconditional edge from an earlier quick step")
        contract = g["_contracts"].get(q) or {}
        for name in contract.get("reads") or []:
            if name not in inputs and name not in produced:
                problems.append(f"quick step {q} reads {name}, which is neither a procedure input "
                                "nor made by an earlier quick step")
        earlier.append(q)
        produced.update(contract.get("produces") or {})
    return problems


def inputs_of(g):
    """The files a run of the graph needs in its inputs folder. Required are the files a
    step's contract reads that no step produces, apart from steps.json, which the runtime
    writes, in the order the graph first reads them. Optional are the reads_optional
    patterns of every step but the exit, whose findings_*.json pattern names produced
    files."""
    order = topo_order(g)
    produced = set()
    for nid in order:
        produced.update((g["_contracts"].get(nid) or {}).get("produces") or {})
    required, optional = [], []
    for nid in order:
        contract = g["_contracts"].get(nid) or {}
        for name in contract.get("reads") or []:
            if name not in produced and name != "steps.json" and name not in required:
                required.append(name)
        if nid != g["exit"]:
            for pat in contract.get("reads_optional") or []:
                if pat not in optional:
                    optional.append(pat)
    return {"required": required, "optional": optional}


def procedures(reg):
    """Each registry entry with its graph's version, its schema and that schema's version,
    and its input files."""
    out = []
    for e in reg["procedures"]:
        g = load(os.path.join(ROOT, e["graph"]))
        out.append(dict(e, graph_version=g["version"], schema=g["schema"],
                        schema_version=load_schema(g["schema"])["version"], inputs=inputs_of(g)))
    return out


def registered(pid):
    """The registry entry whose id is pid, or None."""
    path = os.path.join(ROOT, REGISTRY)
    if os.path.isfile(path):
        for e in load_registry(path).get("procedures") or []:
            if isinstance(e, dict) and e.get("id") == pid and isinstance(e.get("graph"), str):
                return e
    return None


def graph_of(name):
    """The graph a registered procedure id names, or the name itself as a graph path."""
    e = registered(name)
    return os.path.join(ROOT, e["graph"]) if e else name


# ---------------------------------------------------------------- CLI

def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check"); c.add_argument("graph")
    r = sub.add_parser("run"); r.add_argument("graph"); r.add_argument("--run", required=True)
    r.add_argument("--inputs", required=True); r.add_argument("--judge"); r.add_argument("--second")
    r.add_argument("--quick", action="store_true")
    s = sub.add_parser("step"); s.add_argument("--run", required=True); s.add_argument("--node", required=True)
    v = sub.add_parser("verify"); v.add_argument("--run", required=True)
    sc = sub.add_parser("score"); sc.add_argument("--run", required=True); sc.add_argument("--truth", required=True)
    a = sub.add_parser("advise"); a.add_argument("graph"); a.add_argument("--at", required=True)
    d = sub.add_parser("decide"); d.add_argument("--run", required=True); d.add_argument("--item", required=True)
    choice = d.add_mutually_exclusive_group(required=True)
    choice.add_argument("--approve", action="store_true"); choice.add_argument("--hold", action="store_true")
    d.add_argument("--by", required=True)
    pr = sub.add_parser("procedures"); pr.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "check":
        g = load(args.graph)
        problems = check(g)
        print("\n".join(problems) or f"OK: {len(g['nodes'])} nodes, {len(g['edges'])} edges")
        return 1 if problems else 0
    if args.cmd == "run":
        run_dir = os.path.abspath(args.run)
        if args.quick:
            return run_quick(args.graph, run_dir, args.inputs, args.judge, args.second)
        init_run(graph_of(args.graph), run_dir, args.inputs, args.judge, args.second)
        return run_all(run_dir)
    if args.cmd == "step":
        rec = step(os.path.abspath(args.run), args.node)
        return 0 if rec["checks"]["contract"] == "pass" else 1
    if args.cmd == "verify":
        return verify(os.path.abspath(args.run))
    if args.cmd == "score":
        res = score(os.path.abspath(args.run), args.truth)
        return 0 if not res["missed"] else 1
    if args.cmd == "advise":
        print(node_pitfalls(load(args.graph), args.at))
        return 0
    if args.cmd == "decide":
        return decide(os.path.abspath(args.run), args.item, "approved" if args.approve else "held", args.by)
    if args.cmd == "procedures":
        reg = load_registry()
        problems = check_registry(reg)
        if args.check:
            print("\n".join(problems) or f"OK: {len(reg['procedures'])} procedures")
            return 1 if problems else 0
        if problems:
            sys.exit("the registry fails its check:\n" + "\n".join(problems))
        print(json.dumps(procedures(reg), indent=2, ensure_ascii=False))
        return 0


if __name__ == "__main__":
    sys.exit(main())
