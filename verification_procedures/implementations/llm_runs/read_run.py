"""Read a finished run from run.tar and index what it holds.

The tar is read in memory, names lose a leading './', and only regular files
count. Without manifest.json the archive holds no run, so run_index.json says
is_run false with every other field empty, and a blocking finding says so.
Otherwise the index takes the graph's path, its version as text, the stream, and
both executors (empty when none) from the manifest, one entry for each judgment
step from its record, the number of tool steps, whether the trail finished or
names the step it stopped at, and whether verify.json and score.json exist. A
manifest from a live run holds a provider block (base_url and model), which the
index keeps as provider, an empty object when there is none. has_reference is
true when reference.json was given and the archive holds a run.

answer_book.json maps <node>:<item_id> to each answer in files/<node>.json,
without the item_id, executor, and prompt_sha256 the runtime adds, which is the
form a recorded:<file> executor reads.
"""
import json
import os
import tarfile

import _lib

CHECK = "read_run"
ADDED = ("item_id", "executor", "prompt_sha256")


def clean_name(name):
    while name.startswith("./"):
        name = name[2:]
    return name


def members():
    """Every regular file in the tar as {name: bytes}, or None when it is not a tar."""
    out = {}
    try:
        with tarfile.open(_lib.path("run.tar")) as tf:
            for info in tf.getmembers():
                if info.isfile():
                    out[clean_name(info.name)] = tf.extractfile(info).read()
    except (tarfile.TarError, OSError):
        return None
    return out


def load(files, name):
    return json.loads(files[name].decode("utf-8"))


def text(value):
    return "" if value is None else str(value)


def provider(manifest):
    block = manifest.get("provider")
    if not isinstance(block, dict):
        return {}
    return {key: text(block.get(key)) for key in ("base_url", "model")}


EMPTY = {"is_run": False, "graph": "", "graph_version": "", "stream": "", "judge": "",
         "second": "", "finished": False, "stopped_at": "", "judgment_steps": [],
         "tool_steps": 0, "has_verify": False, "has_score": False, "has_reference": False,
         "provider": {}}

files = members()
findings = []
book = {}
if files is None or "manifest.json" not in files:
    index = dict(EMPTY)
    why = ("The archive could not be read as a tar." if files is None
           else "The archive holds no manifest.json, so it is not a run folder.")
    findings.append(_lib.finding(CHECK, "blocking", "run.tar", why))
else:
    manifest = load(files, "manifest.json")
    graph = manifest.get("graph") or {}
    executors = manifest.get("executors") or {}
    records = [load(files, name) for name in sorted(files)
               if name.startswith("records/") and name.endswith(".json")]
    steps, tool_steps = [], 0
    for rec in records:
        ex = rec.get("execution") or {}
        if ex.get("type") == "script":
            tool_steps += 1
        if ex.get("type") != "judgment":
            continue
        steps.append({"seq": rec["seq"], "node": rec["node"], "role": ex.get("role", "judge"),
                      "executor": list(ex.get("executor") or []), "items": ex.get("items", 0),
                      "unjudged": list(ex.get("unjudged") or []),
                      "prompts": ex.get("prompts", ""), "responses": ex.get("responses", "")})
    events = []
    for line in files.get("trail.jsonl", b"").decode("utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    stopped = [e.get("node", "") for e in events if e.get("event") == "run_stopped"]
    index = {"is_run": True, "graph": text(graph.get("path")), "graph_version": text(graph.get("version")),
             "stream": text(manifest.get("stream")), "judge": text(executors.get("judge")),
             "second": text(executors.get("second")),
             "finished": any(e.get("event") == "run_finished" for e in events),
             "stopped_at": stopped[-1] if stopped else "", "judgment_steps": steps,
             "tool_steps": tool_steps, "has_verify": "verify.json" in files,
             "has_score": "score.json" in files,
             "has_reference": os.path.exists(_lib.path("reference.json")),
             "provider": provider(manifest)}
    for st in steps:
        name = "files/{}.json".format(st["node"])
        answers = load(files, name) if name in files else []
        for answer in answers if isinstance(answers, list) else []:
            if not isinstance(answer, dict) or "item_id" not in answer:
                continue
            key = "{}:{}".format(st["node"], answer["item_id"])
            book[key] = {k: v for k, v in answer.items() if k not in ADDED}

_lib.write_json("run_index.json", index)
_lib.write_json("answer_book.json", book)
_lib.emit_findings(CHECK, findings)
