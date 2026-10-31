"""Mechanical checks on every row being checked:
  1. the located passage appears verbatim in the retrieved copy (after _lib.norm);
     otherwise the checker paraphrased and presented it as a quote;
  2. every phrase the claim puts in quotation marks appears in the retrieved copy
     (a short one that does not is a term the source never uses);
  3. every number in the claim appears in the located passage or the retrieved copy."""
import re

import _lib


def fragments(q):
    return [f.strip(" .,;:") for f in re.split(r"\.\.\.|…|\[\.\.\.\]", q) if f.strip(" .,;:")]


def in_text(q, text_n):
    return all(_lib.norm(f) in text_n for f in fragments(q))


def num_key(n):
    return n.replace(",", "").rstrip("%")


rows = _lib.read_json("rows_access.json")
answers = {a["item_id"]: a for a in _lib.read_json("locate_passage.json")}

findings, out = [], []
for r in rows:
    row = dict(r)
    if r["status"] != "checking":
        out.append(row)
        continue
    ans = answers.get(r["id"]) or {"quote": "", "location": "", "found": False, "executor": "none"}
    text_n = _lib.norm(r["source_text"])
    quote = (ans.get("quote") or "").strip()
    found = bool(ans.get("found")) and bool(quote)
    quote_ok = found and in_text(quote, text_n)
    row.update(passage=quote, location=ans.get("location") or "", found=found, quote_ok=quote_ok,
               locate_executor=ans.get("executor", ""), locate_prompt_sha256=ans.get("prompt_sha256", ""))
    if not found:
        findings.append(_lib.finding("verify_quote", "warning", r["id"],
                                     "no passage in the retrieved copy bears on the claim", r["source_file"]))
    elif not quote_ok:
        findings.append(_lib.finding("verify_quote", "blocking", r["id"],
                                     "located passage is not verbatim in the source (a paraphrase presented as a quote)",
                                     _lib.cell(quote, 120)))
    for q in r.get("quoted", []):
        if in_text(q, text_n):
            continue
        if len(q.split()) <= 3:
            msg = "the source never uses the quoted term \"%s\"" % q
        else:
            msg = "quoted words are not in the source (a paraphrase presented as a direct quote): \"%s\"" % q
        findings.append(_lib.finding("verify_quote", "blocking", r["id"], msg, r["source_file"]))
    have = {num_key(n) for n in _lib.numbers_in(quote + " " + r["source_text"])}
    for n in r.get("numbers", []):
        if num_key(n) not in have:
            findings.append(_lib.finding("verify_quote", "blocking", r["id"],
                                         "number %s in the claim does not appear in the source" % n,
                                         r["source_file"]))
    out.append(row)

_lib.write_json("rows_quoted.json", out)
_lib.emit_findings("verify_quote", findings)
