"""Match each key cited in the final build's text to the reference list (the authors' step 1).

refs_index.json has one entry for each key that is cited or listed, with in_refs, cited,
and, for a listed key, its DOI (a doi.org or dx.doi.org link read as the DOI alone),
authors, year, title, container, type, and the reference as one line of text. Two cases
are notes for the scholar, a cited key with no entry in the reference list, and an entry
the final build does not cite, which is not checked. Nothing here is a verdict."""
import re

import _lib

DOI_LINK = re.compile(r"^\s*https?://(?:dx\.)?doi\.org/", re.I)


def load_refs():
    data = _lib.read_yaml("refs.yaml") or []
    if isinstance(data, dict):
        data = data.get("references", [])
    return {str(r["id"]): r for r in data}


def year_of(ref):
    iss = ref.get("issued")
    if isinstance(iss, dict) and "date-parts" in iss:
        return int(iss["date-parts"][0][0])
    if isinstance(iss, list) and iss and isinstance(iss[0], dict):
        return int(iss[0].get("year"))
    if iss is None:
        return None
    found = re.match(r"\d{4}", str(iss))
    return int(found.group(0)) if found else None


def initial(given):
    g = "".join(ch for ch in (given or "") if ch.isalpha())
    return g[:1].upper()


def ref_string(entry):
    names = ", ".join(a["family"] + (", " + initial(a["given"]) + "." if a["given"] else "")
                      for a in entry["authors"])
    s = "%s (%s). %s." % (names, entry["year"], entry["title"])
    if entry["container"]:
        s += " %s." % entry["container"]
    if entry["doi"]:
        s += " doi:%s" % entry["doi"]
    return s


rows = _lib.read_json("rows.json")
refs = load_refs()
cited = sorted({r["citekey"] for r in rows})

findings, index = [], []
for key in sorted(set(cited) | set(refs)):
    ref = refs.get(key)
    entry = {"id": key, "in_refs": ref is not None, "cited": key in cited,
             "reference": "(no entry in the reference list)"}
    if ref is not None:
        entry.update({
            "doi": DOI_LINK.sub("", str(ref.get("DOI") or ref.get("doi") or "")).strip(),
            "authors": [{"family": str(a.get("family") or a.get("literal") or ""), "given": str(a.get("given", ""))}
                        for a in ref.get("author", [])],
            "year": year_of(ref),
            "title": str(ref.get("title", "")),
            "container": str(ref.get("container-title", "")),
            "type": str(ref.get("type", "")),
        })
        entry["reference"] = ref_string(entry)
    index.append(entry)
    if ref is None:
        findings.append(_lib.finding(
            "match_references", "info", key,
            "@%s is cited in the final build and has no entry in the reference list" % key, "refs.yaml"))
    elif key not in cited:
        findings.append(_lib.finding(
            "match_references", "info", key,
            "@%s is in the reference list and not cited in the final build, so it is not checked" % key,
            "refs.yaml"))

_lib.write_json("refs_index.json", index)
_lib.emit_findings("match_references", findings)
