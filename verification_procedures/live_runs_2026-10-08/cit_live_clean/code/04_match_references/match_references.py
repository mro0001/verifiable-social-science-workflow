"""Every key cited in a row that needs checking must have a reference entry."""
import _lib


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
    return int(str(iss)[:4])


rows = _lib.read_json("rows_attributed.json")
refs = load_refs()
checked_keys = sorted({r["citekey"] for r in rows if r["status"] == "needs_check"})
cited_keys = sorted({r["citekey"] for r in rows})

findings, index = [], []
for key in sorted(set(cited_keys) | set(refs)):
    ref = refs.get(key)
    in_checked = key in checked_keys
    entry = {"id": key, "in_refs": ref is not None, "cited": key in cited_keys,
             "cited_in_checked": in_checked}
    if ref is not None:
        entry.update({
            "doi": str(ref.get("DOI") or ref.get("doi") or ""),
            "authors": [{"family": str(a.get("family", "")), "given": str(a.get("given", ""))}
                        for a in ref.get("author", [])],
            "year": year_of(ref),
            "title": str(ref.get("title", "")),
            "container": str(ref.get("container-title", "")),
            "type": str(ref.get("type", "")),
        })
    index.append(entry)
    if ref is None and in_checked:
        findings.append(_lib.finding("match_references", "blocking", key,
                                     "cited key @%s has no entry in the reference list" % key, "refs.yaml"))
    elif ref is None:
        findings.append(_lib.finding("match_references", "info", key,
                                     "@%s has no reference entry; cited only in the author's own sentences, not checked" % key,
                                     "refs.yaml"))
    elif key not in cited_keys:
        findings.append(_lib.finding("match_references", "info", key,
                                     "in the reference list but not cited in the draft", "refs.yaml"))
    elif not in_checked:
        findings.append(_lib.finding("match_references", "info", key,
                                     "cited only in the author's own sentences; reference not checked", "refs.yaml"))

_lib.write_json("refs_index.json", index)
_lib.emit_findings("match_references", findings)
