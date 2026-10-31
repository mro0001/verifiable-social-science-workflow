"""content_handoff: an AI change that touches content is not style.

For each AI change, compare the token inventories of before and after:
numbers, citation keys, quoted passages, negations, hedges, boosters. Any
difference is a warning naming the stream that owns the content:
  numbers -> data; citation keys and quoted passages -> citations;
  negation or claim strength -> the stream that carries the sentence's support
  (citations if it cites, data if it has numbers, author if neither).
A move with identical text carries no token difference. Writes handoff.json
(one row per handed-off change) and content_tokens.json (every AI change's
token diff, for the judge).
"""
import re
from collections import Counter

import _lib

CITEKEY = re.compile(r"@([A-Za-z0-9_][\w:.#$%&\-+?<>~/]*[A-Za-z0-9_])")
# author-year only inside parentheses "(Kim, 2018; Park and Lee 2020)" or narrative "Kim (2018)",
# so a bare "In 2019" stays a number
_NAME_YEAR = r"[A-Z][A-Za-z\-]+(?:\s(?:and|&)\s[A-Z][A-Za-z\-]+)?,?\s(?:19|20)\d{2}[a-z]?"
PAREN = re.compile(r"\(([^()]*)\)")
NAME_YEAR = re.compile(_NAME_YEAR)
NARRATIVE = re.compile(r"[A-Z][A-Za-z\-]+\s\((?:19|20)\d{2}[a-z]?\)")
QUOTE = re.compile(r'"([^"]{3,})"')
NEGATION = {"not", "no", "never", "none", "nor", "neither", "cannot", "without", "nothing", "nobody"}
HEDGES = {"may", "might", "could", "suggest", "suggests", "suggested", "appear", "appears", "appeared",
          "likely", "possibly", "perhaps", "potentially", "tentative", "tentatively", "indicate",
          "indicates", "somewhat", "partly", "plausibly", "seem", "seems"}
BOOSTERS = {"does", "show", "shows", "showed", "shown", "prove", "proves", "proved", "proven",
            "demonstrate", "demonstrates", "demonstrated", "establish", "establishes", "established",
            "confirm", "confirms", "confirmed", "clearly", "certainly", "definitively", "undoubtedly",
            "always", "must", "conclusively"}


def straight(s):
    return (s or "").replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")


def inventory(s):
    s = straight(s)
    keys = CITEKEY.findall(s) + NARRATIVE.findall(s)
    for inner in PAREN.findall(s):
        keys += NAME_YEAR.findall(inner)
    quotes = [_lib.norm(q) for q in QUOTE.findall(s)]
    bare = NARRATIVE.sub(" ", CITEKEY.sub(" ", s))
    bare = PAREN.sub(lambda m: "(" + NAME_YEAR.sub(" ", m.group(1)) + ")", bare)
    words = re.findall(r"[a-z']+", s.lower())
    words += ["not" for w in words if w.endswith("n't")]
    return {
        "numbers": Counter(_lib.numbers_in(bare)),
        "citations": Counter(keys),
        "quotes": Counter(quotes),
        "negation": Counter(w for w in words if w in NEGATION),
        "strength": Counter([w for w in words if w in HEDGES] + [w for w in words if w in BOOSTERS]),
    }


def diff(before, after):
    b, a = inventory(before), inventory(after)
    out = {}
    for k in b:
        removed, added = sorted((b[k] - a[k]).elements()), sorted((a[k] - b[k]).elements())
        if removed or added:
            out[k] = {"removed": removed, "added": added}
    return out


def describe(d):
    parts = []
    for k in ("numbers", "citations", "quotes", "negation", "strength"):
        if k in d:
            parts.append("{}: {} -> {}".format(k, ", ".join(d[k]["removed"]) or "(none)",
                                               ", ".join(d[k]["added"]) or "(none)"))
    return "; ".join(parts)


changes = _lib.read_json("ai_changes.json")
tokens, handoff, findings = [], [], []
for c in changes:
    d = diff(c["before"], c["after"])
    tokens.append({"id": c["id"], "token_diff": d, "summary": describe(d)})
    if not d:
        continue
    text = c["after"] or c["before"]
    inv = inventory(text)
    streams = set()
    if "numbers" in d:
        streams.add("data")
    if "citations" in d or "quotes" in d:
        streams.add("citations")
    if "negation" in d or "strength" in d:
        if inv["citations"]:
            streams.add("citations")
        if inv["numbers"]:
            streams.add("data")
        if not inv["citations"] and not inv["numbers"]:
            streams.add("author")
    streams = sorted(streams)
    handoff.append({"change_id": c["id"], "kind": c["kind"], "streams": streams, "token_diff": d,
                    "before": c["before"], "after": c["after"]})
    findings.append(_lib.finding(
        "content_handoff", "warning", c["id"],
        "content change: hand off to {} stream".format("|".join(streams)),
        describe(d)))

_lib.write_json("content_tokens.json", tokens)
_lib.write_json("handoff.json", handoff)
_lib.emit_findings("content_handoff", findings)
