"""report (exit): the data stream's fill function. It reads the step outputs, fills the
fields of schemas/data.yaml (copied beside this file as schema.yaml) with the wording the
report shows, and hands them to the one report builder, which writes fields.json,
findings.json, and report.md.

The report is a verification step for the scholar, and no model decides anything in it.
It lists each number in the final build with the output and the script that produce it and
whether the scripts and parameters behind it carry AI work by the record of the AI's file
edits. Each AI change to a script is shown with its text before and after, the reason the
record gives or a note that none is recorded, and whether its text is in the script now.
Each parameter the AI set is listed with its value before and after and the scripts that
read it. The Scripts table marks each script's AI changes and its documentation checks.
The Reproducibility section keeps the rerun apart, with each step, each number's match or
mismatch, the raw data's checksums, the parameter record the rerun wrote, and the model
records, since verification and the reproducible pipeline are kept distinct.

Items. A number needs the scholar's decision when it comes from AI work, when no record was
given, or when it carries a problem. Each AI change and each parameter the AI set needs a
decision, and so does every other group of problems.
"""
import csv
import io
import json

import _lib
import _report


def yn(ok):
    return "yes" if ok else "**no**"


def code_cell(text):
    """Code on one line of a block, each non-empty line as its own code span joined by a
    slash, so that no line of code can start a heading or a list item in the report. The
    item keeps the text word for word."""
    lines = [ln.strip() for ln in str(text or "").splitlines() if ln.strip()]
    return " / ".join("`%s`" % ln.replace("`", "'") for ln in lines) or "(none)"


def one_line(s):
    return " ".join(str(s).split())


def session_fields(refs, line="session_line"):
    refs = [r for r in refs if r]
    return {"sessions": list(refs), line: " and ".join(refs)} if refs else {}


def number_items(numbers, work, attached, record_given):
    """One item for each manuscript number, giving its value, the value the rerun gave (or
    (none) when the rerun gave none), and the output it comes from. A number the rerun gave
    no value for has its replayed field marked not run."""
    rows = []
    for n in numbers:
        traced = work.get(n["key"], {"script": "", "ai": False, "why": []})
        found = attached.get(n["key"], [])
        rerun = "(none)" if n.get("replayed") is None else n["replayed"]
        replayed = ({"not_run": "the rerun gave no value for this number"}
                    if n.get("replayed") is None else n["replayed"])
        if not record_given:
            ai_cell = "not known, no record"
        elif traced["ai"]:
            ai_cell = "yes, " + ", ".join(traced["why"])
        else:
            ai_cell = "no"
        rows.append({"id": n["key"], "kind": "number",
                     "summary": "%s = %s, rerun %s, from %s" % (n["key"], n["value"], rerun, n["from"]),
                     "findings": found,
                     "needs_decision": bool(traced["ai"] or not record_given or found),
                     "key": n["key"], "value": n["value"], "replayed": replayed, "from": n["from"],
                     "ok": n["ok"], "agrees": yn(n["ok"]),
                     "script": traced["script"], "from_ai": bool(traced["ai"]),
                     "script_cell": traced["script"] or "(not a pipeline output)", "ai_cell": ai_cell})
    return rows


def change_items(changes, attached):
    """One item for each AI change to a script, which needs a decision."""
    rows = []
    for c in changes:
        reason = c["rationale"]
        row = {"id": c["id"], "kind": "change",
               "summary": "AI %s to %s, %s" % (c["kind"], c["path"],
                                               "reason recorded" if reason else "no recorded reason"),
               "findings": attached.get(c["id"], []), "needs_decision": True,
               "path": c["path"], "change_kind": c["kind"], "before": c["before"], "after": c["after"],
               "reason_cell": one_line(reason) or "No reason is recorded.",
               "in_file_cell": "yes" if c["in_file"] else "no"}
        if c["kind"] == "write":
            row["before_cell"] = "(the script as it was, which a write does not record)"
            row["after_cell"] = "the whole file, %d lines" % len(c["after"].splitlines())
        else:
            row["before_cell"] = code_cell(c["before"])
            row["after_cell"] = code_cell(c["after"])
        if reason:
            row["rationale"] = reason
        row.update(session_fields([c.get("session_ref")]))
        rows.append(row)
    return rows


def param_items(ai_params, attached):
    """One item for each parameter the AI set, which needs a decision."""
    rows = []
    for p in ai_params:
        row = {"id": p["id"], "kind": "parameter",
               "summary": "%s set by the AI to %s, was %s" % (p["param"], p["after"], p["before"]),
               "findings": attached.get(p["id"], []), "needs_decision": True,
               "param": p["param"], "param_before": p["before"], "ai_value": p["after"],
               "params_now": p["now"], "read_by": ", ".join(p["read_by"]) or "no script",
               "record_id": p["record_id"],
               "reason_cell": _lib.cell(one_line(p["rationale"]), 200) or "No reason is recorded."}
        if p["rationale"]:
            row["rationale"] = p["rationale"]
        row.update(session_fields(p["sessions"], "param_session_line"))
        rows.append(row)
    return rows


def problems_about(allf, check, pred):
    return [x for x in allf if x["check"] == check and x["severity"] != "info" and pred(x["item"])]


def script_rows(inv, scripts, allf):
    rows = []
    listed = [(s["script"], s["id"]) for s in inv["steps"]] + [(h, "helper") for h in inv["helpers"]]
    for script, step in listed:
        docs = not problems_about(allf, "check_docs", lambda i, sc=script: i == sc or i.startswith(sc + ":")) \
            and not problems_about(allf, "check_params", lambda i, sc=script: i.startswith(sc + ":"))
        rows.append({"script": "{}".format(script), "step": "{}".format(step),
                     "ai_changes": ", ".join(scripts.get(script, [])) or "none", "docs_ok": yn(docs)})
    return rows


def step_rows(inv, replay, records_status):
    by_step = {s["id"]: s for s in replay["steps"]}
    rows = []
    for s in inv["steps"]:
        r = by_step.get(s["id"], {})
        outs = r.get("outputs", [])
        repro = bool(outs) and all(o["reproduces"] for o in outs) and r.get("exit_code") == 0
        bad = [o["file"] for o in outs if not o["reproduces"]]
        rows.append({"step": "{}".format(s["id"]), "script": "{}".format(s["script"]),
                     "reproduces": yn(repro) + (f" ({', '.join(bad)})" if bad else ""),
                     "records_ok": yn(records_status.get(s["id"], True)),
                     "stderr": "warning" if (r.get("stderr") or "").strip() else "clean"})
    return rows


def raw_rows(proj):
    rows = []
    for e in proj["acquisition"].get("raw") or []:
        name = str(e.get("file", "?"))
        want = str(e.get("sha256") or "(none)")
        have = (proj["files"].get(name) or {}).get("sha256") or "(missing)"
        rows.append({"file": name, "recorded": want, "now": have, "agrees": yn(want == have)})
    return rows


def param_rows(inv, replay, params):
    rows = []
    recorded = set()
    for s in inv["steps"]:
        text = replay["replayed"].get(f"params_record_{s['id']}.csv")
        if not text:
            continue
        for r in csv.DictReader(io.StringIO(text)):
            recorded.add(r["param"])
            want = params.get(r["param"])
            rows.append({"param": "{}".format(r["param"]), "recorded": _lib.cell(r["value"]),
                         "params_yaml": _lib.cell(want), "agrees": yn(str(want) == r["value"]),
                         "step": "{}".format(r["step"]), "script": "{}".format(r["script"])})
    for k in sorted(set(params) - recorded):
        rows.append({"param": "{}".format(k), "recorded": "(not read by any step)",
                     "params_yaml": _lib.cell(params[k]), "agrees": "n/a", "step": "", "script": ""})
    return rows


def model_rows(inv, replay, proj):
    rows = []
    current = proj["files"].get("params.yaml", {}).get("sha256")
    for s in inv["steps"]:
        name = f"model_record_{s['id']}.json"
        if name not in proj["files"]:
            continue
        try:
            rec = json.loads(proj["files"][name]["text"])
        except (KeyError, ValueError):
            continue
        rep = next((o["reproduces"] for st in replay["steps"] for o in st["outputs"] if o["file"] == name), False)
        rows.append({"record": name, "model": "{}".format(rec.get("model")), "spec": _lib.cell(rec.get("spec")),
                     "n": "{}".format(rec.get("n")), "current": yn(rec.get("params_sha256") == current),
                     "reproduces": yn(rep)})
    return rows


def main():
    proj = _lib.read_json("project.json")
    inv = _lib.read_json("inventory.json")
    replay = _lib.read_json("replay.json")
    records_status = {r["step"]: r["records_ok"] for r in _lib.read_json("records_status.json")}
    numbers = _lib.read_json("numbers_check.json")
    work = _lib.read_json("ai_work.json")

    allf = _lib.collect_findings()
    own = [n["key"] for n in numbers] + [c["id"] for c in work["changes"]] + [p["id"] for p in work["params"]]
    attached, problems = _lib.problem_items(allf, own)
    numbered = number_items(numbers, work["numbers"], attached, work["record_given"])
    if not work["record_given"]:
        record_line = ("No record of the AI's file edits was given, so nothing is marked as the AI's "
                       "and every number waits for the scholar.")
    elif work["changes"] or work["params"]:
        record_line = "The record of the AI's file edits was given."
    else:
        record_line = ("The record of the AI's file edits was given, and no AI contributions to the "
                       "scripts or the parameters were found in it.")
    run = {"n_steps": inv["n_steps"], "n_raw": len(inv["raw"]), "n_numbers": inv["n_numbers"],
           "record_line": record_line,
           "n_numbers_ai": sum(1 for n in numbered if n["from_ai"]),
           "n_changes": len(work["changes"]),
           "n_no_reason": sum(1 for c in work["changes"] if not c["rationale"]),
           "n_ai_params": len(work["params"])}
    _report.build({
        "run": run,
        "items": numbered + change_items(work["changes"], attached) + param_items(work["params"], attached)
        + problems,
        "tables": {"scripts": script_rows(inv, work["scripts"], allf),
                   "steps": step_rows(inv, replay, records_status),
                   "raw": raw_rows(proj),
                   "params": param_rows(inv, replay, proj["params"]),
                   "models": model_rows(inv, replay, proj)},
    })


if __name__ == "__main__":
    main()
