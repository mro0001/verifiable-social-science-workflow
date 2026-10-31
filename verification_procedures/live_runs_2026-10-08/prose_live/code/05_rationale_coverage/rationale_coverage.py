"""rationale_coverage: every AI change carries a rationale, every rationale a change.

Reads ai_changes.json, author_changes.json, content_tokens.json,
rationales.yaml ([{id, anchor, kind, rationale}]) and revised.md. An anchor
matches a change as in exclude_author (equal to, or a 4+ word part of, the
revised or baseline sentence). Each rationale binds to at most one change and
each change to at most one rationale, in rationale order.
  AI change with no rationale              -> blocking "silent change"
  rationale matching no change             -> warning "claimed change not made"
  rationale on a change the author claims  -> info (listed, not judged)
  rationale kind differs from diff kind    -> warning "kind mismatch"
Writes judge_items.json: the rationalized AI changes, one item per ask.
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
author = _lib.read_json("author_changes.json")
tokens = {t["id"]: t for t in _lib.read_json("content_tokens.json")}
rats = _lib.read_yaml("rationales.yaml") or []
if isinstance(rats, dict):
    rats = rats.get("rationales") or []
revised_sents = {_lib.norm(s) for s in _lib.sentences(_lib.read_text("revised.md"))}

bound, findings = {}, []
for n, r in enumerate(rats, 1):
    rid = str(r.get("id") or f"r{n:02d}")
    hit = next((c for c in ai if c["id"] not in bound and matches(r.get("anchor"), c)), None)
    if hit is None:
        own = next((c for c in author if matches(r.get("anchor"), c)), None)
        if own is not None:
            findings.append(_lib.finding(
                "rationale_coverage", "info", own["id"],
                f"rationale {rid} anchors a change the author claims; listed, not judged",
                _lib.cell(r.get("rationale", ""), 120)))
            continue
        a = _lib.norm(r.get("anchor") or "")
        where = ("anchor text is present unchanged in revised.md" if a in revised_sents
                 or any(len(a.split()) >= 4 and a in s for s in revised_sents)
                 else "anchor text found in no changed sentence")
        findings.append(_lib.finding(
            "rationale_coverage", "warning", rid, "claimed change not made",
            f"{where}: {_lib.cell(r.get('anchor', ''), 100)}"))
        continue
    bound[hit["id"]] = dict(r, id=rid)
    claimed = str(r.get("kind") or "").strip().lower()
    ok = {hit["kind"]} | ({"move", "edit"} if hit.get("moved") else set())
    if claimed not in ok:
        findings.append(_lib.finding(
            "rationale_coverage", "warning", hit["id"],
            f"kind mismatch: rationale {rid} says {claimed or '(none)'}, diff says {hit['kind']}",
            _lib.cell(hit["after"] or hit["before"], 120)))

items = []
for c in ai:
    r = bound.get(c["id"])
    if r is None:
        findings.append(_lib.finding(
            "rationale_coverage", "blocking", c["id"],
            f"silent change: AI {c['kind']} has no rationale",
            _lib.cell("{} -> {}".format(c["before"] or "(none)", c["after"] or "(none)"), 160)))
        continue
    items.append({"id": c["id"], "kind": c["kind"], "moved": bool(c.get("moved")),
                  "before": c["before"], "after": c["after"],
                  "rationale_id": r["id"], "rationale_kind": str(r.get("kind") or ""),
                  "rationale": str(r.get("rationale") or ""),
                  "mechanical_token_diff": tokens.get(c["id"], {}).get("summary") or "none"})

_lib.write_json("judge_items.json", items)
_lib.emit_findings("rationale_coverage", findings)
