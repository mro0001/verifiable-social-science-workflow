"""pin_versions: hash both drafts; the baseline must be a ledgered (pinned) version.

Reads baseline.md, revised.md, versions.yaml (the stand-in for BUILDS.md:
{versions: [{version, file, sha256}]}). Writes pins.json and findings.
"""
import hashlib

import _lib


def digest(name):
    with open(_lib.path(name), "rb") as f:
        return "sha256:" + hashlib.sha256(f.read()).hexdigest()


def bare(h):
    h = str(h or "").strip().lower()
    return h if h.startswith("sha256:") else "sha256:" + h


ledger = (_lib.read_yaml("versions.yaml") or {}).get("versions") or []
by_sha = {}
for row in ledger:
    by_sha.setdefault(bare(row.get("sha256")), str(row.get("version")))

base_sha, rev_sha = digest("baseline.md"), digest("revised.md")
base_ver, rev_ver = by_sha.get(base_sha), by_sha.get(rev_sha)
findings = []
if base_ver is None:
    findings.append(_lib.finding(
        "pin_versions", "blocking", "baseline.md",
        "baseline not a pinned version, the diff is unanchored",
        f"{base_sha} matches no row of versions.yaml ({len(ledger)} rows)"))
else:
    findings.append(_lib.finding(
        "pin_versions", "info", "baseline.md", f"baseline is pinned version {base_ver}", base_sha))
findings.append(_lib.finding(
    "pin_versions", "info", "revised.md",
    f"revised hashed for the record ({'ledgered as ' + rev_ver if rev_ver else 'not yet ledgered'})",
    rev_sha))
if base_sha == rev_sha:
    findings.append(_lib.finding(
        "pin_versions", "warning", "revised.md", "revised is byte-identical to baseline; nothing to verify",
        rev_sha))

_lib.write_json("pins.json", {
    "pinned": base_ver is not None,
    "baseline": {"file": "baseline.md", "sha256": base_sha, "version": base_ver},
    "revised": {"file": "revised.md", "sha256": rev_sha, "version": rev_ver},
})
_lib.emit_findings("pin_versions", findings)
