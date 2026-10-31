"""Search the entries by the outside server's rules, so the two give the same answers.

The query is split into lowercase word tokens. Each entry (in the group, when
one is given) scores, per token, 5 for the token in its title, 4 in its id, 2 in
its point, and 1 in its body. Entries scoring above 0 are sorted by score from
high to low and then by id, and cut to the limit (10 unless the call gives one).
The snippet is 140 characters of the body starting 40 before the first token
found, whitespace collapsed, else the entry's description.
"""
import re

import _lib

WIDTH = 140
BEFORE = 40


def snippet(entry, tokens):
    body = entry["body"]
    low = body.lower()
    for token in tokens:
        at = low.find(token)
        if at >= 0:
            start = max(0, at - BEFORE)
            return re.sub(r"\s+", " ", body[start:start + WIDTH]).strip()
    return entry["description"]


def score(entry, tokens):
    title, point, body = entry["title"].lower(), entry["point"].lower(), entry["body"].lower()
    total = 0
    for token in tokens:
        if token in title:
            total += 5
        if token in entry["id"]:
            total += 4
        if token in point:
            total += 2
        if token in body:
            total += 1
    return total


call = _lib.read_json("request_ok.json")
arguments = call["arguments"]
group = arguments.get("group")
limit = arguments.get("limit", 10)
tokens = [t for t in re.split(r"\W+", arguments["query"].lower()) if t]
scored = []
for entry in _lib.read_json("kb_index.json")["entries"]:
    if group is not None and entry["group"] != group:
        continue
    points = score(entry, tokens)
    if points > 0:
        scored.append((points, entry))
scored.sort(key=lambda pair: (-pair[0], pair[1]["id"]))
results = [{"id": e["id"], "title": e["title"], "group": e["group"], "score": s,
            "snippet": snippet(e, tokens)} for s, e in scored[:limit]]
_lib.write_json("answer.json", {"tool": call["tool"], "result": {"results": results},
                                "returned": [r["id"] for r in results]})
