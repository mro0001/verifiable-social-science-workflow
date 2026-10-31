"""Take the reason and any recorded quote for each AI citation whose work was found
(the authors' steps 3b and 4, Track C2 plan choices 4 and 5).

The reason is the AI's own words around the work's first AI appearance, as the
provenance record gives it, with where it came from. When the record holds none the row
says so, and that is a note. The recorded quotes are the record's quotations of the
source near the work's mention. Each row gets a status.

  not_checked      the citation is the scholar's or of unknown origin, so step 3 leaves it out
  work_not_found   an AI citation whose work was not found or not looked up
  no_source        an AI citation whose work was found, with no source text, so no quote
                   is located or checked (a note)
  recorded_quote   the record holds a quote that is in the source text, which verify_quote
                   checks again and places
  to_locate        the record holds no quote that is in the source text, so the passage
                   step locates one, and verify_quote checks it beside any record quote

A record quote is often other words the AI put in double quotes, so one that is not in
the source does not stand as the citation's quote. It is kept, shown, and checked, and
the passage step is asked as well. Each row also carries its reference, the lookup's
result, and the source text it is checked against, with its access level and checksum."""
import re

import _lib


def in_source(quote, source):
    """Whether the quote is in the source text, each part around an ellipsis after _lib.norm,
    as verify_quote looks for it."""
    parts = [_lib.norm(f.strip(" .,;:")) for f in re.split(r"\.\.\.|…|\[\.\.\.\]", quote) if f.strip(" .,;:")]
    whole = _lib.norm(source)
    return bool(parts) and all(p in whole for p in parts)


def text(value):
    return value if isinstance(value, str) else ("" if value is None else str(value))


def where(part):
    """Where a piece of the record came from, as one line of text."""
    bits = []
    if text(part.get("time")):
        bits.append("at %s" % text(part["time"]))
    if text(part.get("session_ref")):
        bits.append("in session %s" % text(part["session_ref"]))
    if text(part.get("artifact")):
        bits.append("in %s" % text(part["artifact"]))
    return " ".join(bits)


rows = _lib.read_json("rows_origin.json")
refs = {r["id"]: r for r in _lib.read_json("refs_index.json")}
verified = {r["id"]: r for r in _lib.read_json("refs_verified.json")}
sources = _lib.read_json("sources.json")
prov = _lib.read_yaml("citation_provenance.yaml") or {}
works = prov.get("works") if isinstance(prov, dict) else None
works = works if isinstance(works, dict) else {}

findings, out = [], []
for r in rows:
    key = r["citekey"]
    ref = refs.get(key) or {}
    lk = verified.get(key) or {}
    src = sources.get(key)
    usable = src is not None and src["access"] in ("fulltext", "abstract")
    row = dict(r, reference=ref.get("reference", "(no entry in the reference list)"),
               lookup=lk.get("lookup", "not_checked"), existence=lk.get("existence", ""),
               record=lk.get("record", ""), reason="", reason_source="", recorded_quotes=[],
               source_file=src["file"] if usable else "", source_sha256=src["sha256"] if usable else "",
               access=src["access"] if usable else "none")
    if r["origin"] != "ai":
        row.update(status="not_checked", existence="not looked up, since the citation is not an AI's")
    elif row["lookup"] != "found":
        row["status"] = "work_not_found"
    else:
        work = works.get(key) if isinstance(works.get(key), dict) else {}
        reason = work.get("reason")
        if isinstance(reason, dict) and text(reason.get("text")).strip():
            row.update(reason=text(reason["text"]).strip(), reason_source=where(reason))
        else:
            findings.append(_lib.finding(
                "gather_reason_and_quote", "info", r["id"],
                "no reason is recorded for @%s, since the record holds no AI words around its first AI appearance" % key,
                "citation_provenance.yaml"))
        quotes = []
        for q in work.get("quotes") or []:
            if isinstance(q, dict) and text(q.get("text")).strip() and \
                    text(q["text"]).strip() not in [x["text"] for x in quotes]:
                quotes.append({"text": text(q["text"]).strip(), "where": where(q)})
        row["recorded_quotes"] = quotes
        if not usable:
            row["status"] = "no_source"
            findings.append(_lib.finding(
                "gather_reason_and_quote", "info", r["id"],
                "there is no source text for @%s, so no quote was located or checked" % key,
                "no source_%s.txt" % key))
        else:
            found = any(in_source(q["text"], src["text"]) for q in quotes)
            row.update(status="recorded_quote" if found else "to_locate", source_text=src["text"])
    out.append(row)

_lib.write_json("rows_reasons.json", out)
_lib.emit_findings("gather_reason_and_quote", findings)
