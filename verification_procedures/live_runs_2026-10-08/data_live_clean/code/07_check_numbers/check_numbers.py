"""check_numbers: every manuscript number comes from the process.

numbers.yml maps each key the prose cites as {{num:<key>}} to
{value, from: <pipeline output>, field: <column or dotted JSON path>, where: {col: val}}.
The value must equal the REPLAYED output, not the committed copy.
  - `from` is not a pipeline output -> blocking
  - the field or row cannot be found in the replayed output -> blocking
  - the value differs -> blocking "manuscript number does not come from the process"
Numeric strings are compared as numbers ("0.050" == "0.05"); others exactly.
"""
import csv
import io
import json

import _lib

CHECK = "check_numbers"
proj = _lib.read_json("project.json")
inv = _lib.read_json("inventory.json")
replay = _lib.read_json("replay.json")
findings, table = [], []


def equal(a, b):
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return str(a) == str(b)


def lookup(text, name, field, where):
    if name.endswith(".json"):
        cur = json.loads(text)
        for part in str(field).split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
                cur = cur[int(part)]
            else:
                raise KeyError(f"no {field} in {name}")
        return cur
    rows = [r for r in csv.DictReader(io.StringIO(text))
            if all(str(r.get(k)) == str(v) for k, v in (where or {}).items())]
    if len(rows) != 1:
        raise KeyError(f"{len(rows)} rows of {name} match {where or 'no where'}")
    if field not in rows[0]:
        raise KeyError(f"no column {field} in {name}")
    return rows[0][field]


for key in sorted(proj["numbers"]):
    spec = proj["numbers"][key]
    if not isinstance(spec, dict) or "value" not in spec or "from" not in spec or "field" not in spec:
        findings.append(_lib.finding(CHECK, "blocking", key, "entry lacks value, from, or field", str(spec)))
        continue
    src, typed = spec["from"], spec["value"]
    row = {"key": key, "value": str(typed), "from": src, "replayed": None, "ok": False}
    if src not in inv["outputs"]:
        findings.append(_lib.finding(CHECK, "blocking", key,
                                     "manuscript number does not come from the process: source is not a pipeline output",
                                     f"from: {src}"))
    elif replay["replayed"].get(src) is None:
        findings.append(_lib.finding(CHECK, "blocking", key, "source output was not produced by the replay",
                                     f"from: {src}"))
    else:
        try:
            got = lookup(replay["replayed"][src], src, spec["field"], spec.get("where"))
            row["replayed"] = str(got)
            if equal(typed, got):
                row["ok"] = True
            else:
                findings.append(_lib.finding(CHECK, "blocking", key,
                                             "manuscript number does not come from the process",
                                             f"numbers.yml {typed!r}; replayed {src} {spec['field']} = {got!r}"))
        except (KeyError, ValueError) as err:
            findings.append(_lib.finding(CHECK, "blocking", key, "number cannot be resolved in the replayed output",
                                         str(err)))
    table.append(row)

_lib.write_json("numbers_check.json", table)
_lib.emit_findings(CHECK, findings)
