"""Check what the run kept for each judgment step against its own record.

For each answer in files/<node>.json, the saved prompt <prompts>/<item_id>.txt must
exist with a sha256 equal to the answer's prompt_sha256 (blocking otherwise), and
the saved response <responses>/<item_id>.txt must exist (a warning otherwise).
Each item the step did not judge is a warning, retries are the count of
*.retry.txt files in the step's responses folder, and an info note gives the
answered of asked for each step. A finding's item is <node>:<item_id>, the key of
the answer book, or the step's node for the note.
"""
import hashlib
import json
import tarfile

import _lib

CHECK = "check_record"


def clean_name(name):
    while name.startswith("./"):
        name = name[2:]
    return name


def members():
    out = {}
    with tarfile.open(_lib.path("run.tar")) as tf:
        for info in tf.getmembers():
            if info.isfile():
                out[clean_name(info.name)] = tf.extractfile(info).read()
    return out


def answers_of(files, node):
    name = "files/{}.json".format(node)
    if name not in files:
        return []
    answers = json.loads(files[name].decode("utf-8"))
    if not isinstance(answers, list):
        return []
    return [a for a in answers if isinstance(a, dict) and "item_id" in a]


index = _lib.read_json("run_index.json")
files = members()
rows, findings = [], []
for st in index["judgment_steps"]:
    node = st["node"]
    answers = answers_of(files, node)
    mismatches = missing = 0
    for answer in answers:
        key = "{}:{}".format(node, answer["item_id"])
        prompt = "{}/{}.txt".format(st["prompts"], answer["item_id"])
        if prompt not in files:
            mismatches += 1
            findings.append(_lib.finding(CHECK, "blocking", key,
                                         "The answer's saved prompt is missing from the run.", prompt))
        else:
            digest = "sha256:" + hashlib.sha256(files[prompt]).hexdigest()
            if digest != answer.get("prompt_sha256"):
                mismatches += 1
                findings.append(_lib.finding(
                    CHECK, "blocking", key,
                    "The saved prompt does not match the checksum recorded with the answer.",
                    "{} is {}, the answer records {}".format(prompt, digest, answer.get("prompt_sha256"))))
        response = "{}/{}.txt".format(st["responses"], answer["item_id"])
        if response not in files:
            missing += 1
            findings.append(_lib.finding(CHECK, "warning", key,
                                         "The answer's saved response is missing from the run.", response))
    for item in st["unjudged"]:
        findings.append(_lib.finding(CHECK, "warning", "{}:{}".format(node, item),
                                     "The item was not judged, so no answer stands behind it.",
                                     st["responses"]))
    prefix = st["responses"] + "/"
    retries = sum(1 for name in files if name.startswith(prefix) and name.endswith(".retry.txt"))
    findings.append(_lib.finding(CHECK, "info", node, "{} of {} items answered.".format(
        len(answers), st["items"])))
    rows.append({"node": node, "items": st["items"], "answered": len(answers),
                 "unjudged": len(st["unjudged"]), "retries": retries,
                 "prompt_mismatches": mismatches, "missing_responses": missing})

_lib.write_json("record_check.json", rows)
_lib.emit_findings(CHECK, findings)
