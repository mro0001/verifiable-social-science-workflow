"""Compare each checked reference entry with its looked-up record."""
import re

import _lib


def words(s):
    return set(re.findall(r"[a-z0-9]+", _lib.norm(s)))


def initial(given):
    g = re.sub(r"[^A-Za-z]", "", given or "")
    return g[:1].upper()


def cite_form(authors):
    return ", ".join(a["family"] + (" " + initial(a["given"]) + "." if a["given"] else "") for a in authors)


PUBLISHED = {"article-journal", "journal-article", "chapter", "book-chapter", "book", "paper-conference",
             "proceedings-article"}
PREPRINT = {"posted-content", "article", "preprint", "report"}

index = {r["id"]: r for r in _lib.read_json("refs_index.json")}
findings, out = [], []
for lk in _lib.read_json("lookups.json"):
    key = lk["id"]
    ref = index[key]
    notes = []

    def flag(sev, msg, ev):
        notes.append(msg)
        findings.append(_lib.finding("check_existence", sev, key, msg, ev))

    if not lk["found"]:
        if lk["via"] == "no_doi":
            flag("warning", "no DOI in the reference entry; existence must be confirmed by hand", "refs.yaml")
        elif lk["via"] == "crossref_error":
            flag("warning", "DOI lookup failed (network error); existence must be confirmed by hand", lk["doi"])
        else:
            where = {"crossref_404": "Crossref has no record of it",
                     "cache_miss_offline": "not in the metadata cache, and live lookup was off"}.get(lk["via"], lk["via"])
            flag("blocking", "citation may not exist: no record for DOI %s (%s)" % (lk["doi"], where), lk["doi"])
        out.append({"id": key, "exists": False, "metadata_ok": False,
                    "status": "; ".join(notes), "record": None})
        continue

    rec = lk["record"]
    rec_auth = [{"family": a.get("family", ""), "given": a.get("given", "")} for a in rec.get("author", [])]
    ref_fam = [_lib.norm(a["family"]) for a in ref["authors"]]
    rec_fam = [_lib.norm(a["family"]) for a in rec_auth]
    if ref_fam != rec_fam:
        flag("blocking", "author mismatch: reference lists %s; record lists %s"
             % (cite_form(ref["authors"]) or "none", cite_form(rec_auth) or "none"), lk["doi"])
    else:
        bad = ["%s (%s. vs %s.)" % (a["family"], initial(a["given"]), initial(b["given"]))
               for a, b in zip(ref["authors"], rec_auth)
               if initial(a["given"]) and initial(b["given"]) and initial(a["given"]) != initial(b["given"])]
        if bad:
            flag("warning", "author initials differ: " + ", ".join(bad), lk["doi"])
    rec_year = rec.get("issued")
    if rec_year is not None and ref.get("year") != int(rec_year):
        flag("blocking", "year mismatch: reference says %s; record says %s" % (ref.get("year"), rec_year), lk["doi"])
    a, b = words(ref.get("title", "")), words(rec.get("title", ""))
    if a != b:
        overlap = len(a & b) / float(len(a | b) or 1)
        if overlap < 0.6:
            flag("blocking", "title mismatch: reference title is not the record's title", rec.get("title", ""))
        else:
            flag("warning", "title differs in wording from the record", rec.get("title", ""))
    if ref.get("container") and rec.get("container-title") and \
            words(ref["container"]) != words(rec["container-title"]):
        flag("warning", "venue differs: reference says %s; record says %s"
             % (ref["container"], rec["container-title"]), lk["doi"])
    if ref.get("type") in PUBLISHED and rec.get("type") in PREPRINT:
        flag("warning", "stage mismatch: reference describes a published %s; the DOI resolves to a %s"
             % (ref["type"], rec.get("type")), lk["doi"])
    out.append({"id": key, "exists": True, "metadata_ok": not notes,
                "status": "; ".join(notes) if notes else "exists; metadata matches",
                "record": rec})

_lib.write_json("refs_verified.json", out)
_lib.emit_findings("check_existence", findings)
