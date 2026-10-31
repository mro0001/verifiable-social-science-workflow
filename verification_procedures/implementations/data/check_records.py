"""check_records: the parameter and model records were produced by THIS run.

Convention: a step that reads parameters writes params_record_<step>.csv
(param, value, step, script); a step of kind `model` also writes
model_record_<step>.json (model, spec, params, params_sha256, n, outputs).
  - a missing record -> blocking
  - a record value that differs from params.yaml -> blocking
  - a parameter the script reads that its record omits -> blocking (record is stale)
  - a committed record that differs from the replayed one -> blocking
  - a model record whose params_sha256 is not the current params.yaml -> blocking "stale model"
  - a model record whose n differs from the replayed n -> blocking
"""
import csv
import io
import json

import _lib

CHECK = "check_records"
proj = _lib.read_json("project.json")
inv = _lib.read_json("inventory.json")
replay = _lib.read_json("replay.json")
usage = _lib.read_json("params_usage.json")
files, params = proj["files"], proj["params"]
current = files["params.yaml"]["sha256"] if "params.yaml" in files else None
findings, status = [], []


def canon(v):
    return str(v)


def rows_of(text):
    return list(csv.DictReader(io.StringIO(text)))


for s in inv["steps"]:
    sid, script = s["id"], s["script"]
    reads = usage.get(script, {}).get("reads", [])
    precord, mrecord = f"params_record_{sid}.csv", f"model_record_{sid}.json"
    ok = True
    if reads or precord in s["outputs"]:
        if precord not in s["outputs"] or precord not in files:
            findings.append(_lib.finding(CHECK, "blocking", precord,
                                         "step reads parameters but has no parameter record",
                                         f"{script} reads {', '.join(reads)}"))
            ok = False
        else:
            text = files[precord].get("text", "")
            rows = rows_of(text)
            if text.splitlines()[:1] != ["param,value,step,script"]:
                findings.append(_lib.finding(CHECK, "blocking", precord,
                                             "parameter record header is not param,value,step,script",
                                             text.splitlines()[0] if text else "empty"))
                ok = False
            recorded = {}
            for r in rows:
                k = r.get("param")
                recorded[k] = r.get("value")
                if k not in params:
                    findings.append(_lib.finding(CHECK, "blocking", precord,
                                                 f"records {k}, which params.yaml does not define", str(r)))
                    ok = False
                elif r.get("value") != canon(params[k]):
                    findings.append(_lib.finding(CHECK, "blocking", precord,
                                                 f"records {k} = {r.get('value')}, params.yaml says {canon(params[k])}",
                                                 "record was not produced from the current params.yaml"))
                    ok = False
                if r.get("step") != sid or r.get("script") != script:
                    findings.append(_lib.finding(CHECK, "warning", precord,
                                                 f"row for {k} names step/script {r.get('step')}/{r.get('script')}",
                                                 f"expected {sid}/{script}"))
            for k in reads:
                if k not in recorded:
                    findings.append(_lib.finding(CHECK, "blocking", precord,
                                                 f"script reads {k} but the record omits it: record is stale",
                                                 script))
                    ok = False
            again = replay["replayed"].get(precord)
            if again is not None and again != text:
                findings.append(_lib.finding(CHECK, "blocking", precord,
                                             "committed parameter record differs from the replayed one",
                                             "the record was typed or kept from an older run"))
                ok = False
    if s["kind"] == "model":
        if mrecord not in s["outputs"] or mrecord not in files:
            findings.append(_lib.finding(CHECK, "blocking", mrecord, "model step has no model record", script))
            ok = False
        else:
            try:
                rec = json.loads(files[mrecord].get("text", ""))
            except ValueError as err:
                rec = None
                findings.append(_lib.finding(CHECK, "blocking", mrecord, "model record is not JSON", str(err)))
                ok = False
            if rec is not None:
                lacking = [k for k in ("model", "spec", "params", "params_sha256", "n", "outputs") if k not in rec]
                if lacking:
                    findings.append(_lib.finding(CHECK, "blocking", mrecord,
                                                 "model record lacks " + ", ".join(lacking), script))
                    ok = False
                if rec.get("params_sha256") and rec["params_sha256"] != current:
                    findings.append(_lib.finding(CHECK, "blocking", mrecord,
                                                 "stale model: record was made under a different params.yaml",
                                                 f"record {rec['params_sha256'][:19]}..., current {str(current)[:19]}..."))
                    ok = False
                for k, v in sorted((rec.get("params") or {}).items()):
                    if k not in params or canon(v) != canon(params[k]):
                        findings.append(_lib.finding(CHECK, "blocking", mrecord,
                                                     f"model record has {k} = {v!r}, params.yaml says {params.get(k)!r}",
                                                     "stale model"))
                        ok = False
                again = replay["replayed"].get(mrecord)
                if again:
                    n2 = json.loads(again).get("n")
                    if rec.get("n") != n2:
                        findings.append(_lib.finding(CHECK, "blocking", mrecord,
                                                     f"model record n = {rec.get('n')}, replay gives n = {n2}",
                                                     "the model was fit on different data"))
                        ok = False
                for o in rec.get("outputs") or []:
                    if o not in s["outputs"]:
                        findings.append(_lib.finding(CHECK, "warning", mrecord,
                                                     f"model record lists output {o} that pipeline.yaml does not declare",
                                                     script))
    status.append({"step": sid, "records_ok": ok})

_lib.write_json("records_status.json", status)
_lib.emit_findings(CHECK, findings)
