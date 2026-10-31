"""Say for each AI citation's work whether it can be found (the authors' step 3a).

lookup is found, not_found, or not_looked_up. existence says it in words, and record is
the record that was found, written as a reference, for the scholar to read beside the
reference entry. What cannot be found, and what was not looked up, is a note for the
scholar, never a blocking finding, since the scholar decides whether there is an issue.
No field of the record is compared here."""
import _lib

FOUND = {"cache": "found in the metadata cache", "crossref": "found in Crossref",
         "datacite": "found in DataCite"}


def initial(given):
    g = "".join(ch for ch in (given or "") if ch.isalpha())
    return g[:1].upper()


def record_line(rec):
    names = ", ".join(str(a.get("family", "")) + (", " + initial(a.get("given")) + "." if a.get("given") else "")
                      for a in rec.get("author") or [])
    s = "%s (%s). %s." % (names, rec.get("issued"), rec.get("title", ""))
    if rec.get("container-title"):
        s += " %s." % rec["container-title"]
    if rec.get("type"):
        s += " Type %s." % rec["type"]
    return s


findings, out = [], []
for lk in _lib.read_json("lookups.json"):
    key, doi, via = lk["id"], lk["doi"], lk["via"]
    entry = {"id": key, "lookup": "found", "existence": "", "record": ""}
    if lk["found"]:
        entry.update(existence="%s (DOI %s)" % (FOUND.get(via, "found"), doi), record=record_line(lk["record"]))
    else:
        if via == "no_doi":
            entry.update(lookup="not_looked_up", existence="no DOI, not looked up")
        elif via in ("crossref_error", "datacite_error"):
            entry.update(lookup="not_looked_up",
                         existence="not looked up, since the lookup of DOI %s failed" % doi)
        elif via == "cache_miss_offline":
            entry.update(lookup="not_found",
                         existence="not found, since DOI %s is not in the metadata cache and live lookup was off" % doi)
        else:
            entry.update(lookup="not_found", existence="not found, since neither Crossref nor DataCite holds DOI %s" % doi)
        message = ("@%s has no DOI, so it was not looked up" % key if via == "no_doi"
                   else "@%s was %s" % (key, entry["existence"]))
        findings.append(_lib.finding("check_existence", "info", key, message, doi or "refs.yaml"))
    out.append(entry)

_lib.write_json("refs_verified.json", out)
_lib.emit_findings("check_existence", findings)
