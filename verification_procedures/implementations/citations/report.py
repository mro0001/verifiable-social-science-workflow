"""report: the references procedure's fill function. The step outputs fill the fields of
schemas/citations.yaml (copied beside this file as schema.yaml) with the wording the
report shows, and the one report builder writes fields.json, findings.json, and
report.md.

The report leads with counts of citations, AI citations, works not found, quotes not
found in their source, and AI citations with no recorded reason. Then it gives each
citation in the final build with its sentence and its origin with the record's
evidence, and for an AI citation whether the work was found, the AI's recorded reason,
the quote, and the quote check. The scholar's citations are listed and not checked
further. It holds no verdict and no ranking. Each AI citation, and each citation the
record never names, is an item for the scholar to approve or hold.

A blocking finding of extract_citations, on a draft whose citations the check cannot
read, is an item of its own that needs a decision, so the stream cannot read as
verified (Track L, Step L5). It is not counted among the citations."""
import _lib
import _report

# Step order as the runtime walks graphs/citations.yaml, which has no branch.
ORDER = ["pin_document", "extract_citations", "match_references", "read_origin", "fetch_metadata",
         "check_existence", "pin_sources", "gather_reason_and_quote", "locate_passage", "verify_quote",
         "report"]
seq = {node: "%02d_%s" % (i + 1, node) for i, node in enumerate(ORDER)}
NOTES = ["match_references", "read_origin", "check_existence", "gather_reason_and_quote", "verify_quote"]
ACCESS = {"fulltext": "the full text", "abstract": "the abstract only"}

rows = _lib.read_json("rows_quoted.json")
pin = _lib.read_json("doc_pin.json")
found = []
for name in NOTES:
    found.extend(_lib.read_json("findings_%s.json" % name))


def short(h):
    return h[:19] + "..." if h else ""


def notes_of(r):
    """The notes written on the row, or on its key for an AI citation."""
    return [f["message"] for f in found
            if f["item"] == r["id"] or (f["item"] == r["citekey"] and f["check"] in ("match_references",
                                                                                     "check_existence"))]


def reason_line(r):
    if r["status"] in ("not_checked", "work_not_found"):
        return ""
    if not r["reason"]:
        return "no reason recorded"
    return "\"%s\" (said by the AI %s)" % (r["reason"], r["reason_source"]) if r["reason_source"] \
        else "\"%s\"" % r["reason"]


def one_quote(q, executor):
    if q["kind"] == "section":
        shown = "a section pointer, %s" % (q["location"] or "no section named")
    elif q["kind"] == "paraphrase":
        shown = "a paraphrase, not a quote, \"%s\"" % q["text"]
    else:
        shown = "\"%s\"" % q["text"]
    if q["from"] == "record":
        return shown + " (from the record, %s)" % q["where"] if q["where"] else shown + " (from the record)"
    by = "located by %s" % (executor or "the passage step")
    return shown + " (%s%s)" % (by, ", at " + q["location"] if q["location"] and q["kind"] != "section" else "")


def quote_line(r):
    if r["status"] == "no_source":
        return "none, since there is no source text"
    if r["status"] == "to_locate" and not r["quotes"]:
        return "none located"
    return "; ".join(one_quote(q, r.get("locate_executor", "")) for q in r["quotes"])


def quote_check_line(r):
    parts = []
    for q in r["quotes"]:
        if q["kind"] != "quote":
            parts.append("not checked word for word, since it is a %s"
                         % ("section pointer" if q["kind"] == "section" else "paraphrase"))
        elif q["in_source"] == "yes":
            parts.append("found in %s%s" % (r["source_file"], ", at " + q["found_at"] if q["found_at"] else ""))
        else:
            parts.append("not found in %s" % r["source_file"])
    if any(q["kind"] == "quote" for q in r["quotes"]) and r["access"] in ACCESS:
        parts[-1] += ", which holds %s" % ACCESS[r["access"]]
    return "; ".join(parts)


def trail(r):
    parts = ["origin from citation_provenance.yaml (record %s)" % seq["read_origin"]]
    if r["origin"] == "ai":
        parts.append("lookup (records %s, %s)" % (seq["fetch_metadata"], seq["check_existence"]))
    if r["source_file"] and r["status"] in ("recorded_quote", "to_locate"):
        parts.append("source text %s %s (record %s)" % (r["source_file"], short(r["source_sha256"]),
                                                      seq["pin_sources"]))
    if r["status"] == "to_locate":
        parts.append("passage located by %s (record %s)" % (r.get("locate_executor") or "no executor",
                                                           seq["locate_passage"]))
    if r["quotes"]:
        parts.append("quote checked by a program (record %s)" % seq["verify_quote"])
    parts.append("times are each record's started_at")
    return "; ".join(parts)


def session_fields(r):
    """sessions, and session_line, its text for the report, for an AI citation the record
    names in a session, else nothing."""
    if r["origin"] != "ai" or not r["sessions"]:
        return {}
    return {"sessions": list(r["sessions"]), "session_line": ", ".join(r["sessions"])}


def item(r):
    """One citation's fields, then the lines of its block in the report."""
    notes = notes_of(r)
    ai = r["origin"] == "ai"
    return dict({
        "id": r["id"], "citekey": r["citekey"], "sentence": r["sentence"], "origin": r["origin"],
        "origin_evidence": r["origin_evidence"], "reference": r["reference"], "lookup": r["lookup"],
        "existence": r["existence"],
        "record": r["record"], "reason": r["reason"], "reason_source": r["reason_source"],
        "quotes": [dict(q) for q in r["quotes"]], "quote_in_source": r["quote_in_source"],
        "access": r["access"], "source_file": r["source_file"], "source_sha256": r["source_sha256"],
        "notes": notes, "needs_decision": r["needs_decision"],
        "heading": "%s: @%s" % (r["id"], r["citekey"]),
        "reference_line": r["reference"],
        "existence_line": ("%s. The record reads %s" % (r["existence"], r["record"]) if r["record"]
                           else r["existence"]) if ai else "",
        "reason_line": reason_line(r),
        "quote_line": quote_line(r) if r["status"] in ("recorded_quote", "to_locate", "no_source") else "",
        "quote_check_line": quote_check_line(r),
        "notes_line": "; ".join(notes),
        "trail": trail(r),
        "listed_line": "%s, @%s. %s %s" % (r["id"], r["citekey"], r["sentence"], r["origin_evidence"]),
    }, **session_fields(r))


def unread_item(f):
    """The item for a blocking finding of extract_citations, with the fields every item
    carries, filled for a draft whose citations were not read."""
    message = f["message"]
    return {
        "id": f["item"], "citekey": "", "sentence": f.get("evidence", ""), "origin": "unknown",
        "origin_evidence": "No origin, since no citation key was read.",
        "reference": "", "lookup": "not_checked", "existence": "not looked up, since no citation key was read",
        "record": "", "reason": "", "reason_source": "", "quotes": [], "quote_in_source": "not_checked",
        "access": "none", "source_file": "", "source_sha256": "", "notes": [message], "needs_decision": True,
        "heading": "%s: citations not read" % f["item"],
        "reference_line": "No reference was matched, since no citation key was read.",
        "existence_line": "", "reason_line": "", "quote_line": "", "quote_check_line": "",
        "notes_line": message,
        "trail": "found by extract_citations (record %s); times are each record's started_at" % seq["extract_citations"],
        "listed_line": "",
    }


unread = [f for f in _lib.read_json("findings_extract_citations.json") if f["severity"] == "blocking"]
ai_rows = [r for r in rows if r["origin"] == "ai"]
run = {
    "draft_sha256": pin["draft_sha256"], "n_citations": len(rows), "n_ai": len(ai_rows),
    "n_scholar": sum(1 for r in rows if r["origin"] == "scholar"),
    "n_unknown": sum(1 for r in rows if r["origin"] == "unknown"),
    "n_not_found": len({r["citekey"] for r in ai_rows if r["lookup"] == "not_found"}),
    "n_not_looked_up": len({r["citekey"] for r in ai_rows if r["lookup"] == "not_looked_up"}),
    # The citations whose exact quotes, from the record or located, are none of them in the
    # source, and apart from them the record's quotes that are not in the source, most often
    # other words the AI put in double quotes, which sent the citation to the passage step.
    "n_quote_not_found": sum(1 for r in ai_rows if r["quote_in_source"] == "no"),
    "n_record_quote_not_found": sum(1 for r in ai_rows for q in r["quotes"]
                                    if q["from"] == "record" and q["in_source"] == "no"),
    "n_no_reason": sum(1 for r in ai_rows if r["lookup"] == "found" and not r["reason"]),
}

# The report ranks nothing, so it has no Summary or Problems section, unless the draft's
# citations could not be read, a blocking finding that the Problems section shows.
_report.build({"run": run, "items": [item(r) for r in rows] + [unread_item(f) for f in unread],
               "tables": {}}, ranked=bool(unread))
