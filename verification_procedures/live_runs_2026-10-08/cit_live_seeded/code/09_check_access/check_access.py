"""Per row: what the check can read. fulltext, abstract (warning: verdict limited
to the abstract), or none (row not checked, warning)."""
import _lib


def initial(given):
    g = "".join(ch for ch in (given or "") if ch.isalpha())
    return g[:1].upper()


def ref_string(ref):
    if not ref or not ref.get("in_refs"):
        return "(no reference entry)"
    names = ", ".join(a["family"] + (", " + initial(a["given"]) + "." if a["given"] else "")
                      for a in ref.get("authors", []))
    s = "%s (%s). %s." % (names, ref.get("year"), ref.get("title", ""))
    if ref.get("container"):
        s += " %s." % ref["container"]
    if ref.get("doi"):
        s += " doi:%s" % ref["doi"]
    return s


rows = _lib.read_json("rows_reused.json")
sources = _lib.read_json("sources.json")
refs = {r["id"]: r for r in _lib.read_json("refs_index.json")}

findings, out = [], []
for r in rows:
    row = dict(r, reference=ref_string(refs.get(r["citekey"])))
    src = sources.get(r["citekey"])
    row.update(source_file=src["file"] if src else "", source_sha256=src["sha256"] if src else "")
    if r["status"] == "author":
        row.update(access="fulltext" if src and src["access"] == "fulltext" else
                   ("abstract" if src and src["access"] == "abstract" else "none"))
    elif r["status"] == "reused":
        row.update(access=r["prior"].get("access", "fulltext"))
    elif src is None or src["access"] not in ("fulltext", "abstract"):
        row.update(status="not_checked", access="none")
        findings.append(_lib.finding(
            "check_access", "warning", r["id"],
            "not checked: no usable retrieved copy of @%s" % r["citekey"],
            src["file"] if src else "no source_%s.txt" % r["citekey"]))
    else:
        row.update(status="checking", access=src["access"], source_text=src["text"])
        if src["access"] == "abstract":
            findings.append(_lib.finding(
                "check_access", "warning", r["id"],
                "abstract only: the verdict covers the abstract, not the full text", src["file"]))
    out.append(row)

_lib.write_json("rows_access.json", out)
_lib.emit_findings("check_access", findings)
