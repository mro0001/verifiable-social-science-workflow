"""rationale_coverage: each AI change shows the reason the record gives, or that none is recorded.

Reads ai_changes.json (each AI change with the record entry exclude_author bound to it),
rationales.yaml, and revised.md. It judges no reason. It notes what a program can see.
  AI change whose entry has an empty rationale  -> blocking "AI change with no recorded reason"
  record entry bound to no change               -> warning "recorded AI change matches no
                                                   change between the two texts"
  entry's kind differs from the diff's kind     -> warning "kind mismatch"
An entry anchors a change as in exclude_author (equal to, or a 4+ word part of, the
revised or baseline sentence). A change may carry two entries (a move or a rewrite given
as a delete and an insert), their ids and kinds joined by "and", and that pair is not a
kind mismatch. An entry of kind write is
exclude_author's to note and is left alone here.
"""
import _lib


def matches(anchor, change):
    a = _lib.norm(anchor or "")
    if not a:
        return False
    sides = [_lib.norm(change["after"]), _lib.norm(change["before"])]
    if a in sides:
        return True
    return len(a.split()) >= 4 and any(a in s for s in sides if s)


ai = _lib.read_json("ai_changes.json")
record = _lib.read_yaml("rationales.yaml") or []
if isinstance(record, dict):
    record = record.get("rationales") or []
revised_sents = {_lib.norm(s) for s in _lib.sentences(_lib.read_text("revised.md"))}
bound = {rid for c in ai for rid in c["record_id"].split(" and ")}

findings = []
for n, entry in enumerate(record, 1):
    rid = str(entry.get("id") or f"r{n:02d}")
    if rid in bound or str(entry.get("kind") or "").strip().lower() == "write":
        continue
    a = _lib.norm(entry.get("anchor") or "")
    if any(matches(entry.get("anchor"), c) for c in ai):
        where = "anchor names a change another record entry already accounts for"
    elif a in revised_sents or any(len(a.split()) >= 4 and a in s for s in revised_sents):
        where = "anchor text is present unchanged in revised.md"
    else:
        where = "anchor text found in no changed sentence"
    findings.append(_lib.finding(
        "rationale_coverage", "warning", rid,
        "recorded AI change matches no change between the two texts",
        f"{where}, {_lib.cell(entry.get('anchor', ''), 100)}"))

for c in ai:
    if not c["rationale"]:
        findings.append(_lib.finding(
            "rationale_coverage", "blocking", c["id"], "AI change with no recorded reason",
            _lib.cell("record {} names it with no reason, {} -> {}".format(c["record_id"], c["before"] or "(none)",
                                                   c["after"] or "(none)"), 160)))
    claims = [k.strip().lower() for k in c["record_kind"].split(" and ")]
    pair = sorted(claims) == ["delete", "insert"]
    ok = {c["kind"]} | ({"move", "edit", "delete", "insert"} if c["kind"] == "move" or c.get("moved") or pair
                        else set())
    for rid, claimed in zip(c["record_id"].split(" and "), c["record_kind"].split(" and ")):
        claimed = claimed.strip().lower()
        if claimed not in ok:
            findings.append(_lib.finding(
                "rationale_coverage", "warning", c["id"],
                f"kind mismatch, record entry {rid} says {claimed or '(none)'} and the diff says {c['kind']}",
                _lib.cell(c["after"] or c["before"], 120)))

_lib.emit_findings("rationale_coverage", findings)
