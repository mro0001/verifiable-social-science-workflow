"""check_ledger: every file in a builds dir is the file its BUILDS.md row recorded.

For each deliverable in map.json: each build (vNNN.<ext>) and snapshot (vNNN.md)
must have a ledger row and match its sha256; each row's files must exist. Files in
returns/ (the author's saved Word reviews) are the review channel and not builds.

The ledger is read by its header names. ospipe's ledger (its nine columns, or the
first seven in an older ledger) records no file name, snapshot checksum, or build
command. Its build file is vNNN.<ext>, with the extension the map gives, and a
check its columns cannot support is left to the report, which marks it not run.
"""
import hashlib
import posixpath
import re
import tarfile

import _lib

NODE = "check_ledger"
NEEDED = ["version", "file", "sha256", "snapshot_sha256", "source", "source_sha256",
          "numbers_sha256", "command_sha256", "pandoc"]
OSPIPE_COLUMNS = ["version", "date", "git", "sha256", "purpose", "baseline", "reviewed",
                  "verification", "runs"]


def ospipe_form(head):
    """True for ospipe's ledger, its nine columns or the first seven of an older one."""
    return head in (OSPIPE_COLUMNS, OSPIPE_COLUMNS[:7])


def project_files():
    out = {}
    with tarfile.open(_lib.path("project.tar")) as tf:
        for m in tf.getmembers():
            if m.isfile() and not m.name.startswith("/") and ".." not in m.name.split("/"):
                out[posixpath.normpath(m.name)] = tf.extractfile(m).read()
    return out


def h(data):
    return hashlib.sha256(data).hexdigest()


def parse_ledger(text):
    lines = [ln.strip() for ln in text.splitlines() if ln.strip().startswith("|")]
    if len(lines) < 2:
        return [], []
    head = [c.strip() for c in lines[0].strip("|").split("|")]
    rows = [dict(zip(head, [c.strip() for c in ln.strip("|").split("|")])) for ln in lines[2:]]
    return head, rows


def main():
    files = project_files()
    m = _lib.read_json("map.json")
    findings, builds, latest = [], [], {}
    for d in m["deliverables"]:
        bdir = d["builds_dir"]
        ledger_path = bdir + "/BUILDS.md"
        on_disk = sorted(p for p in files if posixpath.dirname(p) == bdir and p != ledger_path)
        if ledger_path not in files:
            for p in on_disk:
                findings.append(_lib.finding(NODE, "blocking", p,
                                             "File in the builds dir with no ledger at all: not a build.", bdir))
            if not on_disk:
                findings.append(_lib.finding(NODE, "info", d["name"], "No builds yet.", bdir))
            continue
        head, rows = parse_ledger(files[ledger_path].decode("utf-8"))
        ospipe = ospipe_form(head)
        missing_cols = [c for c in NEEDED if c not in head]
        if missing_cols and not ospipe:
            findings.append(_lib.finding(NODE, "warning", ledger_path,
                                         "The ledger lacks columns the rebuild needs.", ", ".join(missing_cols)))
        covered, versions = set(), set()
        for r in rows:
            v = r.get("version", "?")
            if v in versions:
                findings.append(_lib.finding(NODE, "blocking", "%s/%s" % (bdir, v),
                                             "Two ledger rows share one version.", v))
            versions.add(v)
            fname = "%s.%s" % (v, d["ext"]) if ospipe else r.get("file", "")
            fpath = "%s/%s" % (bdir, fname)
            snap = "%s/%s.md" % (bdir, v)
            covered.update([fpath, snap])
            file_ok = fpath in files and h(files[fpath]) == r.get("sha256")
            if fpath not in files:
                findings.append(_lib.finding(NODE, "blocking", fpath,
                                             "The ledger row's build is missing from the builds dir.", v))
            elif not file_ok:
                findings.append(_lib.finding(NODE, "blocking", fpath,
                                             "Deliverable edited after build: its sha256 no longer matches the ledger.",
                                             "ledger %s..., file %s..." % (r.get("sha256", "")[:12], h(files[fpath])[:12])))
            snap_ok = snap in files and h(files[snap]) == r.get("snapshot_sha256")
            if snap not in files:
                findings.append(_lib.finding(NODE, "blocking", snap,
                                             "The resolved snapshot for this build is missing.", v))
            elif "snapshot_sha256" not in head:
                snap_ok = None  # the ledger records no snapshot checksum to compare
            elif not snap_ok:
                findings.append(_lib.finding(NODE, "blocking", snap,
                                             "Snapshot edited after build: its sha256 no longer matches the ledger.",
                                             "ledger %s..., file %s..." % (r.get("snapshot_sha256", "")[:12], h(files[snap])[:12])))
            row = {"deliverable": d["name"], "version": v, "path": fpath, "snapshot": snap,
                   "file_ok": file_ok, "snapshot_ok": snap_ok}
            for c in ("date", "sha256", "snapshot_sha256", "source", "source_sha256", "numbers_sha256",
                      "command_sha256", "pandoc", "purpose"):
                row[c] = r.get(c, "")
            builds.append(row)
            if re.match(r"^v\d+$", v):
                if d["name"] not in latest or int(v[1:]) > int(latest[d["name"]]["version"][1:]):
                    latest[d["name"]] = {"version": v, "path": fpath, "snapshot": snap}
        for p in on_disk:
            if p not in covered:
                findings.append(_lib.finding(NODE, "blocking", p,
                                             "File in the builds dir that no ledgered build produced.", ledger_path))
    _lib.write_json("ledger.json", {"rows": len(builds), "builds": builds, "latest": latest})
    _lib.emit_findings(NODE, findings)


if __name__ == "__main__":
    main()
