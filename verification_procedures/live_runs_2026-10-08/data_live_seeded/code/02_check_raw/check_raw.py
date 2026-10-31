"""check_raw: raw data is immutable; each raw file must match its acquisition hash.

A mismatch is blocking even when every output still reproduces: replay starts
from the raw file as it is now, so only the acquisition hash can show the edit.
Raw inputs read by a step but absent from acquisition.yaml are blocking too.
"""
import _lib

CHECK = "check_raw"
proj = _lib.read_json("project.json")
inv = _lib.read_json("inventory.json")
files = proj["files"]
entries = proj["acquisition"].get("raw") or []
findings = []

acquired = set()
for e in entries:
    name = e.get("file", "?")
    acquired.add(name)
    for field in ("sha256", "source", "collected"):
        if not e.get(field):
            sev = "blocking" if field == "sha256" else "warning"
            findings.append(_lib.finding(CHECK, sev, name, f"acquisition record lacks {field}", "acquisition.yaml"))
    if name not in files:
        continue  # inventory already reports the missing file
    have, want = files[name]["sha256"], e.get("sha256")
    if want and have != want:
        findings.append(_lib.finding(CHECK, "blocking", name, "raw data changed after acquisition",
                                     f"recorded {want[:19]}..., now {have[:19]}..."))

for s in inv["steps"]:
    for inp in s["inputs"]:
        if inp not in inv["outputs"] and inp not in acquired:
            findings.append(_lib.finding(CHECK, "blocking", inp, "raw input has no acquisition record",
                                         f"read by step {s['id']}"))

_lib.emit_findings(CHECK, findings)
