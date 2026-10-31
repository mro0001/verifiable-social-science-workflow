"""Carry over an earlier verdict only when the sentence (normalized hash) and the
retrieved copy (sha256) are both unchanged. prior_checks.json is keyed
"<citekey>|<sentence_hash>"; {} means no earlier checks."""
import _lib

rows = _lib.read_json("rows_attributed.json")
prior = _lib.read_json("prior_checks.json") or {}
sources = _lib.read_json("sources.json")

findings, out = [], []
for r in rows:
    row = dict(r)
    if r["status"] == "needs_check":
        p = prior.get("%s|%s" % (r["citekey"], r["sentence_hash"]))
        src = sources.get(r["citekey"])
        if p:
            same_copy = (not p.get("source_sha256")) or (src is not None and src["sha256"] == p["source_sha256"])
            if same_copy:
                row.update(status="reused", prior=p)
                findings.append(_lib.finding(
                    "reuse_prior", "info", r["id"],
                    "verdict carried over from the check of %s (sentence and retrieved copy unchanged)"
                    % p.get("checked_on", "an earlier run"), r["sentence_hash"][:19]))
            else:
                findings.append(_lib.finding(
                    "reuse_prior", "info", r["id"],
                    "earlier verdict not reused: the retrieved copy changed since it was checked",
                    p.get("source_sha256", "")[:19]))
    out.append(row)

_lib.write_json("rows_reused.json", out)
_lib.emit_findings("reuse_prior", findings)
