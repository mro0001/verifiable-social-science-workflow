"""check_descriptions: check what the finding step found, and never correct it.

Each entry of the finding step's answer with a quote becomes one description, numbered
d01, d02, and so on in the answer's order. The program looks for its quote in the final
build's text, ignoring only differences of spacing, quote marks, dashes, and case
(_lib.norm). It checks that each place is a script the pipeline declares and lines inside
that script, and names the outline steps each place falls in, with the phases of the
pipeline steps that run the script. A
description with no place reads missing. The quote check and the place check are shown
for the scholar to judge, and each problem is a warning on the description.
"""
import _lib

CHECK = "check_descriptions"

phase = _lib.read_json("phase.json")["phase"]
outline = _lib.read_json("outline.json")
text = _lib.norm(_lib.read_text("final_text.md"))
answers = [a for a in _lib.read_json("find_descriptions.json") if a.get("item_id") == phase]
lengths = {s["file"]: s["lines"] for s in outline["scripts"]}
phases_of = {s["file"]: s["phases"] for s in outline["scripts"]}
findings = []


def lines_text(start, end):
    return "line %d" % start if start == end else "lines %d-%d" % (start, end)


def joined(words):
    if len(words) < 2:
        return "".join(words)
    return ", ".join(words[:-1]) + " and " + words[-1]


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def read_place(place):
    """(file, start, end) or None when the place cannot be read."""
    if not isinstance(place, dict) or not isinstance(place.get("file"), str) or not place["file"]:
        return None
    start, end = place.get("start"), place.get("end", place.get("start"))
    if not (is_int(start) and is_int(end)):
        return None
    return place["file"], start, end


def check_place(file, start, end):
    """The place's record, with its status and its cell in the report."""
    at = "`%s` %s" % (file, lines_text(start, end))
    if file not in lengths:
        return {"file": file, "start": start, "end": end, "status": "not found", "steps": [],
                "cell": at + " (not a script of the pipeline)"}
    n = lengths[file]
    if not (1 <= start <= end <= n):
        return {"file": file, "start": start, "end": end, "status": "not found", "steps": [],
                "cell": at + " (no such lines, the script has %d)" % n}
    inside = []
    for s in outline["steps"]:
        if s["script"] == file and s["start"] <= end and start <= s["end"] and s["title"] not in inside:
            inside.append(s["title"])
    where = joined([p or "no phase declared" for p in phases_of.get(file, [])]) or "no phase declared"
    return {"file": file, "start": start, "end": end, "status": "confirmed", "steps": inside,
            "cell": "%s (%s, %s)" % (at, where, ", ".join(inside) if inside else "in no step")}


rows = []
for answer in answers:
    entries = answer.get("descriptions")
    if not isinstance(entries, list):
        findings.append(_lib.finding(CHECK, "warning", phase,
                                     "The finding step's answer holds no list of descriptions."))
        continue
    for n, entry in enumerate(entries, 1):
        quote = entry.get("quote") if isinstance(entry, dict) else None
        if not isinstance(quote, str) or not quote.strip():
            findings.append(_lib.finding(CHECK, "warning", "answer entry %d" % n,
                                         "The finding step's entry gives no quote, so it is not listed."))
            continue
        did = "d%02d" % (len(rows) + 1)
        found = _lib.norm(quote) in text
        if not found:
            findings.append(_lib.finding(CHECK, "warning", did, "The quote is not in the final build's text.",
                                         _lib.cell(quote, 120)))
        given = entry.get("where")
        given = [] if given is None else given
        places, unreadable = [], False
        if not isinstance(given, list):
            unreadable = True
        else:
            for place in given:
                read = read_place(place)
                if read is None:
                    unreadable = True
                    continue
                places.append(check_place(*read))
        if unreadable:
            findings.append(_lib.finding(CHECK, "warning", did, "The finding step gave a place that cannot "
                                                               "be read, so it is not checked."))
        for p in places:
            if p["status"] != "confirmed":
                findings.append(_lib.finding(CHECK, "warning", did, "The place %s %s is not in the scripts." % (
                    p["file"], lines_text(p["start"], p["end"]))))
        cells = [p["cell"] for p in places] + (["(a place that cannot be read)"] if unreadable else [])
        if not cells:
            status = "missing"
            findings.append(_lib.finding(CHECK, "warning", did, "The finding step gave no place in the scripts "
                                                               "that carries out this description."))
        elif unreadable or any(p["status"] != "confirmed" for p in places):
            status = "not found"
        else:
            status = "confirmed"
        rows.append({"id": did, "quote": quote, "quote_found": found,
                     "where": [{k: p[k] for k in ("file", "start", "end", "status", "steps")} for p in places],
                     "where_cell": "; ".join(cells) or "missing", "location_status": status})

_lib.write_json("descriptions.json", rows)
_lib.emit_findings(CHECK, findings)
