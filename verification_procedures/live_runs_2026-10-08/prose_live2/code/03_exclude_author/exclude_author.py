"""exclude_author: changes the author claims are listed, not judged.

Reads changes.json and author_edits.yaml (a list of {anchor, note}; write []
when the author made no edits). An anchor matches a change when it equals the
change's revised or baseline sentence (normalized), or is contained in one of
them (anchors of four words or more). Writes ai_changes.json and
author_changes.json.
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


changes = _lib.read_json("changes.json")
claims = _lib.read_yaml("author_edits.yaml") or []
if isinstance(claims, dict):
    claims = claims.get("author_edits") or []

author_ids, findings = {}, []
for n, claim in enumerate(claims, 1):
    cid = str(claim.get("id") or f"a{n:02d}")
    hit = next((c for c in changes if c["id"] not in author_ids and matches(claim.get("anchor"), c)), None)
    if hit is None:
        findings.append(_lib.finding(
            "exclude_author", "warning", cid,
            "listed author edit matches no change between the pinned versions",
            _lib.cell(claim.get("anchor", ""), 120)))
        continue
    author_ids[hit["id"]] = cid
    findings.append(_lib.finding(
        "exclude_author", "info", hit["id"],
        f"author edit ({cid}), listed not judged" + (f": {claim['note']}" if claim.get("note") else ""),
        _lib.cell(hit["after"] or hit["before"], 120)))

ai = [c for c in changes if c["id"] not in author_ids]
author = [dict(c, author_claim=author_ids[c["id"]]) for c in changes if c["id"] in author_ids]
_lib.write_json("ai_changes.json", ai)
_lib.write_json("author_changes.json", author)
_lib.emit_findings("exclude_author", findings)
