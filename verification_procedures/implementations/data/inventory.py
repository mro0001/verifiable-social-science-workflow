"""inventory: parse pipeline.yaml and bundle every declared project file.

Reads pipeline.yaml, acquisition.yaml, params.yaml, numbers.yml and every file
they name (raw data, scripts, helpers, committed outputs), and the record of the AI's
file edits (file_edits.yaml) when it is given. Writes project.json,
the bundle later steps read (so the binding to concrete file names lives in one
place), inventory.json (steps, scripts, raw, outputs), and findings.

Checks: every declared file is present; each step input is raw (acquired) or an
output of an EARLIER step; no output is declared twice; every runner is known.
"""
import base64
import hashlib
import os

import _lib

CHECK = "inventory"
DECLARATIONS = ["pipeline.yaml", "acquisition.yaml", "params.yaml", "numbers.yml"]
# The record of the AI's file edits, bundled when given; attribute_ai says when it is not.
RECORD = "file_edits.yaml"
RUNNERS = {"python3"}


def load_file(name):
    with open(_lib.path(name), "rb") as f:
        data = f.read()
    entry = {"sha256": "sha256:" + hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    try:
        entry["text"] = data.decode("utf-8")
    except UnicodeDecodeError:
        entry["base64"] = base64.b64encode(data).decode("ascii")
    return entry


def plain(obj):
    """YAML dates and other scalars to JSON-safe values."""
    if isinstance(obj, dict):
        return {str(k): plain(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [plain(v) for v in obj]
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    return str(obj)


findings = []
pipe = _lib.read_yaml("pipeline.yaml") or {}
acq = _lib.read_yaml("acquisition.yaml") or {}
numbers = (_lib.read_yaml("numbers.yml") or {}).get("numbers") or {}
steps = pipe.get("steps") or []
helpers = pipe.get("helpers") or []
raw = [r["file"] for r in (acq.get("raw") or [])]

produced_by, seen_outputs = {}, set()
for s in steps:
    sid = s.get("id", "?")
    for o in s.get("outputs") or []:
        if o in produced_by:
            findings.append(_lib.finding(CHECK, "blocking", o, "output declared by two steps",
                                         f"{produced_by[o]} and {sid}"))
        produced_by.setdefault(o, sid)

order = {s.get("id"): i for i, s in enumerate(steps)}
for i, s in enumerate(steps):
    sid = s.get("id", f"step{i + 1}")
    for key in ("id", "script", "inputs", "outputs"):
        if key not in s:
            findings.append(_lib.finding(CHECK, "blocking", sid, f"step lacks {key}", "pipeline.yaml"))
    runner = s.get("runner", "python3")
    if runner not in RUNNERS:
        findings.append(_lib.finding(CHECK, "blocking", sid, f"runner {runner!r} cannot be replayed here",
                                     "replay supports: " + ", ".join(sorted(RUNNERS))))
    for inp in s.get("inputs") or []:
        if inp in raw:
            continue
        src = produced_by.get(inp)
        if src is None:
            findings.append(_lib.finding(CHECK, "blocking", inp,
                                         "input is neither acquired raw data nor a pipeline output",
                                         f"step {sid}"))
        elif order[src] >= i:
            findings.append(_lib.finding(CHECK, "blocking", inp,
                                         f"input is produced by a later step ({src})", f"step {sid}"))

declared = set(DECLARATIONS) | set(helpers) | set(raw)
for s in steps:
    declared.add(s.get("script"))
    declared.update(s.get("inputs") or [])
    declared.update(s.get("outputs") or [])
declared.update(v.get("from") for v in numbers.values() if isinstance(v, dict) and v.get("from"))
declared.discard(None)

files = {}
if os.path.exists(_lib.path(RECORD)):
    files[RECORD] = load_file(RECORD)
for name in sorted(declared):
    if os.path.exists(_lib.path(name)):
        files[name] = load_file(name)
    else:
        findings.append(_lib.finding(CHECK, "blocking", name, "declared file is missing", "pipeline.yaml"))

for name in raw:
    if not any(name in (s.get("inputs") or []) for s in steps):
        findings.append(_lib.finding(CHECK, "info", name, "acquired raw file is not read by any step",
                                     "acquisition.yaml"))

_lib.write_json("project.json", {"files": files, "pipeline": plain(pipe), "numbers": plain(numbers),
                                 "acquisition": plain(acq), "params": plain(_lib.read_yaml("params.yaml") or {})})
_lib.write_json("inventory.json", {
    "steps": [{"id": s.get("id"), "kind": s.get("kind", ""), "runner": s.get("runner", "python3"),
               "script": s.get("script"), "inputs": s.get("inputs") or [],
               "outputs": s.get("outputs") or []} for s in steps],
    "helpers": helpers,
    "scripts": [s.get("script") for s in steps],
    "raw": raw,
    "outputs": sorted(produced_by),
    "n_steps": len(steps),
    "n_numbers": len(numbers),
})
_lib.emit_findings(CHECK, findings)
