"""Check every exact quote against the source text (the authors' step 3b, Track C2 plan
choice 5).

A row whose status is recorded_quote has the record's quotes. A row whose status is
to_locate has any record quotes, none of them in the source, then the passage step's
answer, a quote, a section pointer, a paraphrase, or none. Each exact quote is looked for in the source text after _lib.norm, with an
ellipsis splitting it into parts that must each be there, and is found or not. Where it
was found is the nearest page marker ([p. 7]) or heading before it, when the quote lies
within one block of the source text. A section pointer and a paraphrase are shown as
they are and not checked word for word.

Each quote is {text, from (record or located), kind (quote, section, or paraphrase),
location (as the passage step gave it, empty for a recorded quote), where (who recorded
it, for a recorded quote), in_source (yes, no, or not_checked), found_at}. A row's
quote_in_source is yes when an exact quote is in the source, no when there are exact
quotes and none is, and not_checked when there is none. A quote not in its source, a section pointer, a
paraphrase, and a passage step that found nothing or gave no answer are each a note."""
import re

import _lib

MARKER = re.compile(r"^\[(.+)\]$")
HEADING = re.compile(r"^#+\s*(.+?)\s*$")


def fragments(q):
    return [f.strip(" .,;:") for f in re.split(r"\.\.\.|…|\[\.\.\.\]", q) if f.strip(" .,;:")]


def blocks(text):
    """(location, normalized block) for each block of the text between blank lines, where
    the location is the page marker or heading last seen before it."""
    out, here = [], ""
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if not block:
            continue
        first = block.splitlines()[0].strip()
        m = MARKER.match(first) or HEADING.match(first)
        if m:
            here = m.group(1).strip()
            rest = block[len(block.splitlines()[0]):].strip()
            if not rest:
                continue
            block = rest
        out.append((here, _lib.norm(block)))
    return out


def find(quote, text):
    """(found, where) for an exact quote in the source text."""
    parts = [_lib.norm(f) for f in fragments(quote)]
    if not parts:
        return False, ""
    for here, block in blocks(text):
        if all(p in block for p in parts):
            return True, here
    whole = _lib.norm(text)
    return all(p in whole for p in parts), ""


rows = _lib.read_json("rows_reasons.json")
answers = {a["item_id"]: a for a in _lib.read_json("locate_passage.json")}

findings, out = [], []
for r in rows:
    row = dict(r, quotes=[], quote_in_source="not_checked", locate_executor="")
    key = r["citekey"]
    quotes = []
    if r["status"] == "recorded_quote":
        quotes = [{"text": q["text"], "from": "record", "kind": "quote", "location": "", "where": q["where"]}
                  for q in r["recorded_quotes"]]
    elif r["status"] == "to_locate":
        quotes = [{"text": q["text"], "from": "record", "kind": "quote", "location": "", "where": q["where"]}
                  for q in r.get("recorded_quotes") or []]
        ans = answers.get(r["id"])
        if ans is None:
            findings.append(_lib.finding("verify_quote", "info", r["id"],
                                         "no passage was located for @%s, since the passage step gave no answer" % key,
                                         "locate_passage"))
        else:
            row["locate_executor"] = ans.get("executor", "")
            kind = ans.get("kind")
            said = (ans.get("text") or "").strip()
            location = (ans.get("location") or "").strip()
            if kind == "quote" and said:
                quotes.append({"text": said, "from": "located", "kind": "quote", "location": location, "where": ""})
            elif kind in ("section", "paraphrase"):
                quotes.append({"text": said, "from": "located", "kind": kind, "location": location, "where": ""})
                findings.append(_lib.finding(
                    "verify_quote", "info", r["id"],
                    "no exact quote was given for @%s, since the passage step gave a %s, which is not checked word for word"
                    % (key, "section pointer" if kind == "section" else "paraphrase"),
                    _lib.cell(location or said, 120)))
            else:
                findings.append(_lib.finding(
                    "verify_quote", "info", r["id"],
                    "the passage step found no passage in the source text of @%s that bears on the sentence" % key,
                    r["source_file"]))
    checked = []
    for q in quotes:
        if q["kind"] != "quote":
            q.update(in_source="not_checked", found_at="")
            continue
        found, at = find(q["text"], r["source_text"])
        q.update(in_source="yes" if found else "no", found_at=at)
        checked.append(found)
        if not found:
            findings.append(_lib.finding(
                "verify_quote", "info", r["id"],
                "the quote given for @%s is not in its source text %s" % (key, r["source_file"]),
                _lib.cell(q["text"], 120)))
    if checked:
        row["quote_in_source"] = "yes" if any(checked) else "no"
    row["quotes"] = quotes
    row.pop("source_text", None)
    out.append(row)

_lib.write_json("rows_quoted.json", out)
_lib.emit_findings("verify_quote", findings)
