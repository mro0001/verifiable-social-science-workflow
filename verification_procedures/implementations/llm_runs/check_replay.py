"""Read the replay and the score the run saved in its archive, and rerun nothing.

Each step of the archived verify.json whose verdict starts with FAIL is blocking,
with the item <seq>_<node> and the verdict as evidence. A missing verify.json is
a warning, since a run never replayed shows nothing about its tool steps. The
archived score.json gives an info note of its recall and a warning for each
fault it missed, and a missing score.json gives an info note.
"""
import json
import tarfile

import _lib

CHECK = "check_replay"


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


index = _lib.read_json("run_index.json")
files = members() if index["is_run"] else {}
findings = []

if "verify.json" in files:
    verified = json.loads(files["verify.json"].decode("utf-8"))
    for st in verified.get("steps") or []:
        verdict = str(st.get("verdict", ""))
        if verdict.startswith("FAIL"):
            findings.append(_lib.finding(
                CHECK, "blocking", "{:02d}_{}".format(int(st.get("seq", 0)), st.get("node", "")),
                "The step did not replay to the same outputs when the run was verified.", verdict))
else:
    findings.append(_lib.finding(
        CHECK, "warning", "verify.json",
        "The archive holds no verify.json, so the run was never replayed and its tool steps are not shown to reproduce."))

if "score.json" in files:
    scored = json.loads(files["score.json"].decode("utf-8"))
    faults = scored.get("faults") or 0
    caught = scored.get("caught") or []
    if faults:
        message = "The run's score caught {} of {} planted faults, a recall of {}.".format(
            len(caught), faults, scored.get("recall"))
    else:
        message = "The run's score had no planted faults to catch."
    findings.append(_lib.finding(CHECK, "info", "score.json", message))
    for fault in scored.get("missed") or []:
        findings.append(_lib.finding(CHECK, "warning", fault,
                                     "The run missed a planted fault its truth file names.", "score.json"))
else:
    findings.append(_lib.finding(CHECK, "info", "score.json",
                                 "The archive holds no score.json, so the run was not scored against planted faults."))

_lib.emit_findings(CHECK, findings)
