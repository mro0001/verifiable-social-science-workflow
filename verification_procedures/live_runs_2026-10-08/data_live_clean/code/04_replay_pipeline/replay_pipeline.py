"""replay_pipeline: rerun the whole pipeline from raw data and compare every output.

Copies only raw data, scripts, helpers, and params.yaml into an empty temporary
folder (never a committed output or cached intermediate), runs each step in
pipeline order, and compares each declared output byte for byte with the
committed one.
  - committed output differs -> blocking "output does not reproduce"
  - a step exits nonzero -> blocking (later steps still run, and fail visibly)
  - a step writes anything to stderr while exiting 0 -> warning (read warnings,
    not just pass/fail)
  - a step writes a file pipeline.yaml does not declare -> warning
Writes replay.json: per step results plus the replayed text of every output,
which check_records and check_numbers read. Temporary paths are scrubbed from
stderr so the step itself replays byte-identically.
"""
import base64
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile

import _lib

CHECK = "replay_pipeline"
proj = _lib.read_json("project.json")
inv = _lib.read_json("inventory.json")
files = proj["files"]
findings = []


def put(folder, name):
    entry = files[name]
    data = entry["text"].encode("utf-8") if "text" in entry else base64.b64decode(entry["base64"])
    with open(os.path.join(folder, name), "wb") as f:
        f.write(data)


def digest(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def first_difference(a, b):
    la, lb = a.splitlines(), b.splitlines()
    for i in range(max(len(la), len(lb))):
        x = la[i] if i < len(la) else "<no line>"
        y = lb[i] if i < len(lb) else "<no line>"
        if x != y:
            return f"line {i + 1}: committed {x[:70]!r} / replayed {y[:70]!r}"
    return "bytes differ (line endings or trailing newline)"


tmp = tempfile.mkdtemp(prefix="vg_replay_")
real = os.path.realpath(tmp)
try:
    seeds = set(inv["raw"]) | set(inv["helpers"]) | {s["script"] for s in inv["steps"]} | {"params.yaml"}
    for name in sorted(seeds):
        if name in files:
            put(tmp, name)
    steps, replayed, crashed = [], {}, 0
    declared = set(seeds) | set(inv["outputs"])
    for s in inv["steps"]:
        before = set(os.listdir(tmp))
        if s["runner"] != "python3":
            steps.append({"id": s["id"], "script": s["script"], "exit_code": None, "stderr": "",
                          "outputs": [], "note": "runner not replayable here"})
            continue
        proc = subprocess.run([sys.executable, s["script"]], cwd=tmp, capture_output=True, text=True,
                              env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONHASHSEED="0"))
        err = proc.stderr.replace(real, "<replay>").replace(tmp, "<replay>")
        if proc.returncode:
            crashed += 1
            tail = err.strip().splitlines()[-1] if err.strip() else "no stderr"
            findings.append(_lib.finding(CHECK, "blocking", s["script"],
                                         f"step crashed (exit {proc.returncode}); the pipeline does not run from raw",
                                         tail))
        elif err.strip():
            findings.append(_lib.finding(CHECK, "warning", s["script"],
                                         "step wrote warnings to stderr while exiting 0",
                                         " ".join(err.strip().splitlines())[:300]))
        for extra in sorted(set(os.listdir(tmp)) - before - declared):
            findings.append(_lib.finding(CHECK, "warning", extra, "step wrote a file pipeline.yaml does not declare",
                                         f"step {s['id']}"))
        outs = []
        for o in s["outputs"]:
            p = os.path.join(tmp, o)
            new = None
            if os.path.exists(p):
                with open(p, "rb") as f:
                    new = f.read()
                try:
                    replayed[o] = new.decode("utf-8")
                except UnicodeDecodeError:
                    replayed[o] = None
            old = files.get(o)
            rec = {"file": o, "committed_sha256": old["sha256"] if old else None,
                   "replayed_sha256": digest(new) if new is not None else None}
            rec["reproduces"] = bool(old and new is not None and rec["committed_sha256"] == rec["replayed_sha256"])
            outs.append(rec)
            if new is None:
                findings.append(_lib.finding(CHECK, "blocking", o, "declared output was not produced by the replay",
                                             f"step {s['id']}"))
            elif old is None:
                findings.append(_lib.finding(CHECK, "blocking", o, "output has no committed copy to compare",
                                             f"step {s['id']}"))
            elif not rec["reproduces"]:
                ev = first_difference(old.get("text", ""), replayed.get(o) or "") if "text" in old else "binary differs"
                findings.append(_lib.finding(CHECK, "blocking", o,
                                             "output does not reproduce: hand-edited or stale", ev))
        steps.append({"id": s["id"], "script": s["script"], "exit_code": proc.returncode,
                      "stderr": err, "outputs": outs})
finally:
    shutil.rmtree(tmp, ignore_errors=True)

all_ok = all(o["reproduces"] for s in steps for o in s["outputs"]) and crashed == 0
_lib.write_json("replay.json", {"steps": steps, "replayed": replayed, "crashed": crashed,
                                "all_reproduce": all_ok, "python": sys.version.split()[0]})
_lib.emit_findings(CHECK, findings)
