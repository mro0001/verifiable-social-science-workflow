"""report (exit): turn judgments into findings, then write findings.json and report.md.

The report opens with the summary and the problems, then three tables
assembled from the run itself, never typed: the Pipeline (does each step
reproduce, are its records sound, is its documentation sound), the Parameter
record (every value each step read, from the replayed records, against
params.yaml), and the Manuscript numbers (typed value against replayed value).
"""
import csv
import io
import json

import _lib

proj = _lib.read_json("project.json")
inv = _lib.read_json("inventory.json")
replay = _lib.read_json("replay.json")
records_status = {r["step"]: r["records_ok"] for r in _lib.read_json("records_status.json")}
numbers = _lib.read_json("numbers_check.json")
answers = _lib.read_json("judge_method_docs.json")
items = {i["id"]: i for i in _lib.read_json("method_items.json")}
params = proj["params"]

judged = []
for a in answers:
    if a.get("matches") is False:
        mm = a.get("mismatches") or []
        ev = "; ".join(f"says {m.get('claim', '')!r}, code {m.get('code', '')!r}" for m in mm if isinstance(m, dict))
        judged.append(_lib.finding("judge_method_docs", "warning", a["item_id"],
                                   "documentation does not describe what the code does (judgment: confirm)",
                                   (ev or a.get("reason", "")) + f" [{a['executor']}]"))
answered = {a["item_id"] for a in answers}
for iid in sorted(set(items) - answered):
    judged.append(_lib.finding("judge_method_docs", "warning", iid, "no usable judgment for this item",
                               "executor failed or answer unparseable; check by hand"))
_lib.emit_findings("judge_method_docs", judged)
allf = _lib.collect_findings()
_lib.write_json("findings.json", allf)


def problems_about(check, pred):
    return [x for x in allf if x["check"] == check and x["severity"] != "info" and pred(x["item"])]


def yn(ok):
    return "yes" if ok else "**no**"


rows = ["| Step | Script | Reproduces | Records ok | Docs ok | Stderr |", "|---|---|---|---|---|---|"]
by_step = {s["id"]: s for s in replay["steps"]}
for s in inv["steps"]:
    r = by_step.get(s["id"], {})
    outs = r.get("outputs", [])
    repro = bool(outs) and all(o["reproduces"] for o in outs) and r.get("exit_code") == 0
    stem = s["script"].rsplit(".", 1)[0]
    docs = not problems_about("check_docs", lambda i, sc=s["script"]: i == sc or i.startswith(sc + ":")) \
        and not problems_about("judge_method_docs", lambda i, st=stem: i == st or i.startswith(st + ".")) \
        and not problems_about("check_params", lambda i, sc=s["script"]: i.startswith(sc + ":"))
    bad = [o["file"] for o in outs if not o["reproduces"]]
    rows.append("| {} | {} | {} | {} | {} | {} |".format(
        s["id"], s["script"], yn(repro) + (f" ({', '.join(bad)})" if bad else ""),
        yn(records_status.get(s["id"], True)), yn(docs),
        "warning" if (r.get("stderr") or "").strip() else "clean"))
pipeline_md = "\n".join(rows) + "\n\nDocs ok covers the docstring sections, the parameter scan of the script, and the per-function judgment."

prow = ["| Param | Value recorded | params.yaml | Agrees | Step | Script |", "|---|---|---|---|---|---|"]
recorded = set()
for s in inv["steps"]:
    name = f"params_record_{s['id']}.csv"
    text = replay["replayed"].get(name)
    if not text:
        continue
    for r in csv.DictReader(io.StringIO(text)):
        recorded.add(r["param"])
        want = params.get(r["param"])
        prow.append("| {} | {} | {} | {} | {} | {} |".format(
            r["param"], _lib.cell(r["value"]), _lib.cell(want), yn(str(want) == r["value"]), r["step"], r["script"]))
for k in sorted(set(params) - recorded):
    prow.append(f"| {k} | (not read by any step) | {_lib.cell(params[k])} | n/a | | |")
param_md = ("Assembled from the parameter records the replay wrote, not from the committed copies.\n\n"
            + "\n".join(prow))

mrows = ["| Record | Model | Spec | n | Made under current params.yaml | Reproduces |", "|---|---|---|---|---|---|"]
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
    mrows.append("| {} | {} | {} | {} | {} | {} |".format(
        name, rec.get("model"), _lib.cell(rec.get("spec")), rec.get("n"),
        yn(rec.get("params_sha256") == current), yn(rep)))
model_md = "\n".join(mrows)

nrows = ["| Key | numbers.yml | Replayed | From | Agrees |", "|---|---|---|---|---|"]
for n in numbers:
    nrows.append(f"| {n['key']} | {n['value']} | {n['replayed']} | {n['from']} | {yn(n['ok'])} |")
numbers_md = "\n".join(nrows)

judge_md = ("{} method items judged ({} step, {} function); {} judged not to match the code.".format(
    len(items), sum(1 for i in items.values() if i["kind"] == "step"),
    sum(1 for i in items.values() if i["kind"] == "function"),
    sum(1 for a in answers if a.get("matches") is False)))

intro = ("Data stream verification: the pipeline replayed from raw data in an empty folder; parameters "
         "checked for being set once in params.yaml; parameter and model records checked against params.yaml "
         "and the replay; manuscript numbers checked against the replayed outputs; method documentation "
         "checked for structure (tool) and truth (judgment). "
         f"{inv['n_steps']} steps, {len(inv['raw'])} raw file(s), {inv['n_numbers']} manuscript numbers.")
_lib.write_text("report.md", _lib.report("Data verification report", intro, allf, sections=[
    ("Pipeline", pipeline_md),
    ("Parameter record", param_md),
    ("Model records", model_md),
    ("Manuscript numbers", numbers_md),
    ("Method documentation judgments", judge_md),
]))
