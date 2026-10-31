"""attribute_ai: the record says which scripts and parameters an AI wrote or changed.

Reads the record of the AI's file edits from project.json, where inventory bundled it, as
the audit layer writes it out ([{id, path, kind, before, after, rationale, session,
session_ref}]), with params_usage.json for the parameters each script reads. A change, a
script, or a parameter is the AI's when the record shows an AI tool call made it (Track V,
choice 2), and a stated reason is the one the record gives, word for word (choice 3). No
model judges anything here. Every other change is not in the record, which includes
changes the AI made through shell commands.

An entry on a step script or a helper is an AI change to a script. A program checks that
its text after is still in the script as it stands (for a write, that the script is that
text), and a change whose text is gone is a warning. A change with no recorded reason is
blocking. An entry on params.yaml gives the parameters the AI set, the keys whose value
it changed or added (every key, for a write). When its text names no key, as when an Edit
replaces a value alone, the keys are those on the lines of params.yaml as it stands that
hold its text after. Each is a warning for the scholar to check, and blocking when no
reason is recorded. An entry on params.yaml that sets no parameter is shown as a change,
and when neither its text nor params.yaml as it stands names a key, it is taken to touch
every parameter. An entry on another file the data procedure reads, such as numbers.yml,
pipeline.yaml, or acquisition.yaml, is a note for the scholar, since no step traces it.
An entry on any other file is left to the stream that covers it.

Each manuscript number is traced from the output it names to the step that writes it,
then through the steps whose outputs that step reads, to their scripts, every helper, and
the parameters those scripts read. A number comes from AI work when any of them carries an
AI change, a parameter the AI set, or, when its scripts read any parameter, a change on
params.yaml taken to touch every parameter. With no record given nothing can be marked,
and a note says so.

Writes ai_work.json, {record_given, changes, params, scripts, numbers}.
"""
import re

import _lib
import yaml

CHECK = "attribute_ai"
RECORD = "file_edits.yaml"
PARAMS = "params.yaml"
KEY_LINE = re.compile(r"^([A-Za-z_][\w.-]*)\s*:(.*)$")

proj = _lib.read_json("project.json")
inv = _lib.read_json("inventory.json")
usage = _lib.read_json("params_usage.json")
files = proj["files"]
params = proj["params"]
findings = []

step_of = {s["script"]: s["id"] for s in inv["steps"]}
for h in inv["helpers"]:
    step_of.setdefault(h, "helper")


def one_line(s):
    return " ".join(str(s).split())


def value_text(v):
    return "(not set)" if v is None else str(v)


def parse_value(text):
    """The value after `name:` on one line of params.yaml, its comment left out."""
    text = re.sub(r"\s+#.*$", "", text).strip()
    try:
        return yaml.safe_load(text) if text else None
    except yaml.YAMLError:
        return text


def key_values(text):
    """The name: value lines at the left margin of a piece of params.yaml, in order."""
    out = {}
    for line in str(text or "").splitlines():
        m = KEY_LINE.match(line)
        if m:
            out[m.group(1)] = parse_value(m.group(2))
    return out


def found_on_lines(entry):
    """{param: (value before, value after)} for the parameters on the lines of params.yaml as
    it stands that hold the edit's text after, the value before read from params.yaml with
    the edit undone at that place. None when the text after is not in params.yaml now."""
    text = (files.get(PARAMS) or {}).get("text")
    after = entry["after"]
    if text is None or not after.strip() or after not in text:
        return None
    now, lines, out = key_values(text), text.splitlines(), {}
    start = text.find(after)
    while start >= 0:
        first = text.count("\n", 0, start)
        last = text.count("\n", 0, start + len(after.rstrip("\n")))
        was = key_values(text[:start] + entry["before"] + text[start + len(after):])
        for line in lines[first:last + 1]:
            m = KEY_LINE.match(line)
            if m:
                out.setdefault(m.group(1), (was.get(m.group(1)), now.get(m.group(1))))
        start = text.find(after, start + 1)
    return out


def set_params(entry):
    """(named, [(param, before, after)]) for an entry on params.yaml. The list holds the
    parameters the entry set, before "(not recorded)" when the record cannot say. named is
    false when the record and params.yaml as it stands cannot say which parameters the
    entry touched."""
    if entry["kind"] == "write":
        try:
            loaded = yaml.safe_load(entry["after"] or "")
        except yaml.YAMLError:
            loaded = None
        loaded = loaded if isinstance(loaded, dict) else key_values(entry["after"])
        return bool(loaded), [(str(k), "(not recorded)", v) for k, v in loaded.items()]
    old, new = key_values(entry["before"]), key_values(entry["after"])
    if not old and not new:
        lines = found_on_lines(entry)
        if lines is None:
            return False, []
        return True, [(k, value_text(b), a) for k, (b, a) in lines.items() if b != a]
    out = [(k, value_text(old.get(k)), v) for k, v in new.items() if k not in old or old[k] != v]
    out += [(k, value_text(v), "(removed)") for k, v in old.items() if k not in new]
    return True, out


def in_file_now(entry):
    text = (files.get(entry["path"]) or {}).get("text")
    if text is None:
        return False
    if entry["kind"] == "write":
        return entry["after"] == text
    if entry["after"].strip():
        return entry["after"] in text
    return not entry["before"].strip() or entry["before"] not in text


record_given = RECORD in files
record = []
if record_given:
    try:
        loaded = yaml.safe_load(files[RECORD].get("text", "")) or []
    except yaml.YAMLError as err:
        loaded = []
        findings.append(_lib.finding(CHECK, "blocking", RECORD, "the record of the AI's file edits is not YAML",
                                     one_line(err)[:200]))
    for n, e in enumerate(loaded if isinstance(loaded, list) else [], 1):
        if not isinstance(e, dict):
            continue
        record.append({"id": str(e.get("id") or "e%02d" % n), "path": str(e.get("path") or ""),
                       "kind": "write" if str(e.get("kind") or "").strip().lower() == "write" else "edit",
                       "before": e.get("before") if isinstance(e.get("before"), str) else "",
                       "after": e.get("after") if isinstance(e.get("after"), str) else "",
                       "rationale": str(e.get("rationale") or "").strip(),
                       "session_ref": str(e.get("session_ref") or "").strip()})
else:
    findings.append(_lib.finding(
        CHECK, "info", RECORD,
        "no record of the AI's file edits was given, so no script or parameter is marked as the AI's "
        "and every number waits for the scholar", "inputs"))

changes, by_param, every_param = [], {}, set()
for e in record:
    if e["path"] == PARAMS:
        named, found = set_params(e)
        if not named:
            every_param.add(e["id"])
        if found:
            for k, before, after in found:
                p = by_param.setdefault(k, {"param": k, "before": before, "records": [], "reasons": [],
                                            "sessions": []})
                p["after"] = value_text(after)
                p["records"].append(e["id"])
                if e["rationale"] and e["rationale"] not in p["reasons"]:
                    p["reasons"].append(e["rationale"])
                if e["session_ref"] and e["session_ref"] not in p["sessions"]:
                    p["sessions"].append(e["session_ref"])
                p.setdefault("no_reason", False)
                p["no_reason"] = p["no_reason"] or not e["rationale"]
            continue
    elif e["path"] not in step_of:
        if e["path"] in files and e["path"] != RECORD:
            findings.append(_lib.finding(
                CHECK, "info", e["id"],
                "an AI %s to %s, which no step of this report traces, for the scholar to look at"
                % (e["kind"], e["path"]), _lib.cell(one_line(e["after"]) or "(text removed)", 120)))
        continue
    row = dict(e, step=step_of.get(e["path"], "settings"), in_file=in_file_now(e))
    changes.append(row)
    if not e["rationale"]:
        findings.append(_lib.finding(CHECK, "blocking", e["id"],
                                     "an AI change to %s with no recorded reason" % e["path"],
                                     _lib.cell(one_line(e["after"]) or "(text removed)", 120)))
    if not row["in_file"]:
        findings.append(_lib.finding(CHECK, "warning", e["id"],
                                     "the AI's text from this change is not in %s as it stands" % e["path"],
                                     _lib.cell(one_line(e["after"]) or "(text removed)", 120)))

ai_params = []
for k, p in by_param.items():
    now = value_text(params.get(k)) if k in params else "(not in params.yaml)"
    read_by = sorted(s for s, u in usage.items() if k in u.get("reads", []))
    item = "%s:%s" % (PARAMS, k)
    ai_params.append({"id": item, "param": k, "before": p["before"], "after": p["after"], "now": now,
                      "read_by": read_by, "record_id": " and ".join(p["records"]),
                      "rationale": " ".join(p["reasons"]), "sessions": p["sessions"]})
    findings.append(_lib.finding(CHECK, "warning", item, "a parameter the AI set, for the scholar to check",
                                 "%s %s -> %s (record %s), params.yaml now %s"
                                 % (k, p["before"], p["after"], " and ".join(p["records"]), now)))
    if p["no_reason"]:
        findings.append(_lib.finding(CHECK, "blocking", item,
                                     "the AI set this parameter with no recorded reason",
                                     "record " + " and ".join(p["records"])))

scripts = {}
for c in changes:
    scripts.setdefault(c["path"], []).append(c["id"])

producer = {}
for s in inv["steps"]:
    for o in s["outputs"]:
        producer.setdefault(o, s)


def chain(step):
    """The step and every earlier step whose outputs it is computed from, in pipeline order."""
    seen, todo = set(), [step["id"]]
    by_id = {s["id"]: s for s in inv["steps"]}
    while todo:
        sid = todo.pop()
        if sid in seen:
            continue
        seen.add(sid)
        for i in by_id[sid]["inputs"]:
            if i in producer:
                todo.append(producer[i]["id"])
    return [s for s in inv["steps"] if s["id"] in seen]


numbers = {}
for key in sorted(proj["numbers"]):
    spec = proj["numbers"][key] if isinstance(proj["numbers"][key], dict) else {}
    src = spec.get("from")
    step = producer.get(src)
    if step is None:
        numbers[key] = {"script": "", "ai": False, "why": []}
        continue
    steps = chain(step)
    used = [s["script"] for s in steps] + list(inv["helpers"])
    why = [c["id"] + " in " + c["path"] for c in changes if c["path"] in used]
    read = set()
    for sc in used:
        read.update(usage.get(sc, {}).get("reads", []))
    why += ["parameter " + p["param"] for p in ai_params if p["param"] in read]
    if read:
        why += [c["id"] + " in " + PARAMS for c in changes if c["id"] in every_param]
    numbers[key] = {"script": step["script"], "ai": bool(why), "why": why}

_lib.write_json("ai_work.json", {"record_given": record_given, "changes": changes, "params": ai_params,
                                 "scripts": scripts, "numbers": numbers})
_lib.emit_findings(CHECK, findings)
