"""Minimal build tool for the synthetic test project (stands in for ospipe build).

python3 tools/build.py --source S --manifest M --builds-dir D --ext html --purpose P -- <pandoc argv>

1. Resolve {{num:key}} in S from M; a missing key fails the build, listing every missing key.
2. Refuse to build over a corrupted archive (any ledgered file whose sha256 no longer matches).
3. Write the next D/vNNN.md (the resolved snapshot, byte-exact), render D/vNNN.<ext> with
   `<pandoc argv> D/vNNN.md -o D/vNNN.<ext>`, and append a row to D/BUILDS.md.
The ledger date comes from SOURCE_DATE_EPOCH when set.
"""
import argparse
import datetime
import hashlib
import os
import re
import subprocess
import sys

import yaml

PLACEHOLDER = re.compile(r"\{\{num:([A-Za-z0-9_.\-]+)\}\}")
COLUMNS = ["version", "date", "git", "file", "sha256", "snapshot_sha256", "source", "source_sha256",
           "numbers_sha256", "command_sha256", "pandoc", "purpose"]


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def ledger_rows(ledger):
    if not os.path.exists(ledger):
        return []
    rows = []
    with open(ledger, encoding="utf-8") as f:
        lines = [ln.strip() for ln in f if ln.strip().startswith("|")]
    if not lines:
        return []
    head = [c.strip() for c in lines[0].strip("|").split("|")]
    for ln in lines[2:]:
        rows.append(dict(zip(head, [c.strip() for c in ln.strip("|").split("|")])))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--builds-dir", required=True)
    ap.add_argument("--ext", required=True)
    ap.add_argument("--purpose", default="draft")
    ap.add_argument("pandoc", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    cmd = a.pandoc[1:] if a.pandoc and a.pandoc[0] == "--" else a.pandoc

    with open(a.source, encoding="utf-8") as f:
        text = f.read()
    with open(a.manifest, encoding="utf-8") as f:
        manifest = {str(k): str(v) for k, v in (yaml.safe_load(f) or {}).items()}
    missing = sorted({k for k in PLACEHOLDER.findall(text) if k not in manifest})
    if missing:
        sys.exit("build refused: missing manifest keys: " + ", ".join(missing))
    resolved = PLACEHOLDER.sub(lambda m: manifest[m.group(1)], text)

    os.makedirs(a.builds_dir, exist_ok=True)
    ledger = os.path.join(a.builds_dir, "BUILDS.md")
    rows = ledger_rows(ledger)
    bad = [r["file"] for r in rows
           if not os.path.exists(os.path.join(a.builds_dir, r["file"]))
           or sha(os.path.join(a.builds_dir, r["file"])) != r["sha256"]]
    if bad:
        sys.exit("build refused: ledgered builds changed or missing: " + ", ".join(bad))
    n = max([int(r["version"][1:]) for r in rows] or [0]) + 1
    version = "v%03d" % n
    snap = os.path.join(a.builds_dir, version + ".md")
    out = os.path.join(a.builds_dir, version + "." + a.ext)
    with open(snap, "w", encoding="utf-8") as f:
        f.write(resolved)
    proc = subprocess.run(cmd + [snap, "-o", out])
    if proc.returncode:
        os.remove(snap)
        if os.path.exists(out):
            os.remove(out)
        sys.exit("pandoc failed")
    ver = subprocess.run([cmd[0], "--version"], capture_output=True, text=True).stdout.split()[1]
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    when = datetime.datetime.utcfromtimestamp(int(epoch)) if epoch else datetime.datetime.utcnow()
    row = {"version": version, "date": when.strftime("%Y-%m-%d"), "git": "-",
           "file": os.path.basename(out), "sha256": sha(out), "snapshot_sha256": sha(snap),
           "source": a.source, "source_sha256": sha(a.source), "numbers_sha256": sha(a.manifest),
           "command_sha256": hashlib.sha256(" ".join(cmd[1:]).encode()).hexdigest(),
           "pandoc": ver, "purpose": a.purpose.replace("|", "/")}
    new = not os.path.exists(ledger)
    with open(ledger, "a", encoding="utf-8") as f:
        if new:
            f.write("# Builds ledger\n\nOne row per build. Builds are never edited; the sha256 says so.\n\n")
            f.write("| " + " | ".join(COLUMNS) + " |\n")
            f.write("|" + "---|" * len(COLUMNS) + "\n")
        f.write("| " + " | ".join(row[c] for c in COLUMNS) + " |\n")
    print(version, out)


if __name__ == "__main__":
    main()
