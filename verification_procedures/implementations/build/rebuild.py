"""rebuild: re-derive every ledgered build and compare with the ledger's sha256.

In a scratch copy of the project, run the map's pandoc command on each build's frozen
snapshot exactly as the build tool does (`pandoc <args> <builds>/vNNN.md -o out`).
The result must equal the ledger's sha256 (check_ledger separately compares the file
with the ledger; the two together catch a build edited with its ledger hash forged).
When the canonical and the manifest are unchanged since the build, the snapshot is
also re-resolved from the canonical, so the snapshot itself is witnessed.

Pandoc runs with SOURCE_DATE_EPOCH at midnight UTC of the ledger row's date, the date
rule a fixed-date build uses, so a format that stamps the time (docx) rebuilds to the
same bytes. A row whose ledger records no build command (ospipe's ledger) is not
re-rendered, and a row that records no source or numbers checksum is not witnessed.
The report marks each such check not run.
"""
import calendar
import datetime
import difflib
import hashlib
import os
import posixpath
import re
import shutil
import subprocess
import tarfile
import tempfile

import yaml

import _lib

NODE = "rebuild"
PLACEHOLDER = re.compile(r"\{\{num:([A-Za-z0-9_.\-]+)\}\}")


def project_files():
    out = {}
    with tarfile.open(_lib.path("project.tar")) as tf:
        for m in tf.getmembers():
            if m.isfile() and not m.name.startswith("/") and ".." not in m.name.split("/"):
                out[posixpath.normpath(m.name)] = tf.extractfile(m).read()
    return out


def h(data):
    return hashlib.sha256(data).hexdigest()


def find_pandoc():
    for p in (shutil.which("pandoc"), "/opt/homebrew/bin/pandoc", "/usr/local/bin/pandoc"):
        if p and os.path.exists(p):
            return p
    return None


def source_date_epoch(day):
    """SOURCE_DATE_EPOCH for midnight UTC of a YYYY-MM-DD ledger date, or None."""
    try:
        when = datetime.datetime.strptime(day or "", "%Y-%m-%d")
    except ValueError:
        return None
    return str(calendar.timegm(when.timetuple()))


def resolve(text, manifest):
    missing = sorted({k for k in PLACEHOLDER.findall(text) if k not in manifest})
    if missing:
        return None, missing
    return PLACEHOLDER.sub(lambda m: manifest[m.group(1)], text), []


def first_difference(built, rebuilt):
    """The lines the build has and the rebuild does not (what the build did not produce)."""
    a = built.decode("utf-8", errors="replace").splitlines()
    b = rebuilt.decode("utf-8", errors="replace").splitlines()
    extra = [ln[1:].strip() for ln in difflib.unified_diff(b, a, lineterm="", n=0)
             if ln.startswith("+") and not ln.startswith("+++") and ln[1:].strip()]
    gone = [ln[1:].strip() for ln in difflib.unified_diff(b, a, lineterm="", n=0)
            if ln.startswith("-") and not ln.startswith("---") and ln[1:].strip()]
    refs_only = False
    for txt in (a, b):
        if not any('id="refs"' in ln for ln in txt):
            break
    else:
        cut_a = next(i for i, ln in enumerate(a) if 'id="refs"' in ln)
        cut_b = next(i for i, ln in enumerate(b) if 'id="refs"' in ln)
        refs_only = a[:cut_a] == b[:cut_b]
    if extra:
        return "build has, rebuild lacks: " + extra[0][:140], refs_only
    if gone:
        return "rebuild has, build lacks: " + gone[0][:140], refs_only
    return "bytes differ (whitespace or encoding)", refs_only


def main():
    files = project_files()
    m = _lib.read_json("map.json")
    ledger = _lib.read_json("ledger.json")
    by_name = {d["name"]: d for d in m["deliverables"]}
    pandoc = find_pandoc()
    findings, results = [], []
    version = None
    if pandoc:
        version = subprocess.run([pandoc, "--version"], capture_output=True, text=True).stdout.split()[1]
    with tempfile.TemporaryDirectory() as tmp:
        for p, data in files.items():
            dest = os.path.join(tmp, p)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as f:
                f.write(data)
        for b in sorted(ledger["builds"], key=lambda r: r["path"]):
            d = by_name[b["deliverable"]]
            res = {"path": b["path"], "ledger_sha256": b["sha256"], "rebuilt_sha256": None,
                   "matches": False, "snapshot_witnessed": None}
            results.append(res)
            # 1. witness the snapshot from the canonical, when the inputs have not moved on
            src, man = d["source"], d["manifest"]
            if not b["source_sha256"] or not b["numbers_sha256"]:
                pass  # the ledger records no source or numbers checksum to witness against
            elif src in files and man in files and h(files[src]) == b["source_sha256"] \
                    and h(files[man]) == b["numbers_sha256"]:
                manifest = {str(k): str(v) for k, v in (yaml.safe_load(files[man].decode("utf-8")) or {}).items()}
                resolved, missing = resolve(files[src].decode("utf-8"), manifest)
                if resolved is None:
                    findings.append(_lib.finding(NODE, "blocking", b["snapshot"],
                                                 "The recorded canonical no longer resolves, yet a build exists.",
                                                 "missing: " + ", ".join(missing)))
                    res["snapshot_witnessed"] = False
                elif b["snapshot"] in files and resolved.encode("utf-8") == files[b["snapshot"]]:
                    res["snapshot_witnessed"] = True
                else:
                    res["snapshot_witnessed"] = False
                    findings.append(_lib.finding(NODE, "blocking", b["snapshot"],
                                                 "The snapshot is not the resolved canonical it claims to come from.",
                                                 "canonical %s at sha %s..." % (src, b["source_sha256"][:12])))
            else:
                findings.append(_lib.finding(NODE, "info", b["path"],
                                             "Canonical or numbers changed since this build; the rebuild starts from the frozen snapshot.",
                                             "recorded source %s..." % b["source_sha256"][:12]))
            # 2. re-render the snapshot with the map's command
            if not b["command_sha256"]:
                continue  # the ledger records no build command to compare with
            if not pandoc:
                findings.append(_lib.finding(NODE, "blocking", b["path"], "pandoc not found; cannot rebuild.", ""))
                continue
            if b["snapshot"] not in files:
                findings.append(_lib.finding(NODE, "blocking", b["path"],
                                             "Cannot rebuild: the snapshot is missing.", b["snapshot"]))
                continue
            out = os.path.join(tmp, ".vg_rebuild", b["path"])
            os.makedirs(os.path.dirname(out), exist_ok=True)
            env = dict(os.environ)
            epoch = source_date_epoch(b.get("date"))
            if epoch:
                env["SOURCE_DATE_EPOCH"] = epoch
            proc = subprocess.run([pandoc] + d["pandoc_args"] + [b["snapshot"], "-o", out],
                                  cwd=tmp, capture_output=True, text=True, env=env)
            if proc.returncode or not os.path.exists(out):
                findings.append(_lib.finding(NODE, "blocking", b["path"],
                                             "The map's command does not run on this build's snapshot.",
                                             proc.stderr.strip()[:160]))
                continue
            with open(out, "rb") as f:
                rebuilt = f.read()
            res["rebuilt_sha256"] = h(rebuilt)
            res["matches"] = res["rebuilt_sha256"] == b["sha256"]
            if res["matches"]:
                continue
            built = files.get(b["path"], b"")
            diff, refs_only = first_difference(built, rebuilt)
            if d["command_sha256"] != b["command_sha256"]:
                findings.append(_lib.finding(NODE, "warning", b["path"],
                                             "The map's command changed since this build, so the rebuild cannot confirm it.",
                                             diff))
            elif b["pandoc"] != version:
                findings.append(_lib.finding(NODE, "warning", b["path"],
                                             "pandoc changed since this build (%s then, %s now), so the rebuild cannot confirm it." % (b["pandoc"], version),
                                             diff))
            elif refs_only:
                findings.append(_lib.finding(NODE, "warning", b["path"],
                                             "The rebuild differs only in References; expected only if refs.bib or the CSL changed since the build.",
                                             diff))
            else:
                findings.append(_lib.finding(NODE, "blocking", b["path"],
                                             "Deliverable not derived from the build: same snapshot, same command, same pandoc, different bytes (direct edit).",
                                             diff))
    _lib.write_json("rebuild.json", {"exercised": True, "pandoc": version, "rebuilt": len(results),
                                     "matched": sum(1 for r in results if r["matches"]), "builds": results})
    _lib.emit_findings(NODE, findings)


if __name__ == "__main__":
    main()
