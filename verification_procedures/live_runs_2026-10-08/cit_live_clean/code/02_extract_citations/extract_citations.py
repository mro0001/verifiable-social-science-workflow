"""One row per (citekey, sentence) from the pandoc-markdown draft.

Recognizes bracketed citations ([@a, p. 4; @b]) and bare ones (@a, @a [p. 4]).
Each row carries the sentence, its normalized hash (for matching across
drafts), the locator(s), the phrases the sentence puts in quotation marks, and
the numbers in the claim text (citations and locators removed first)."""
import hashlib
import re

import _lib

KEY = r"@([A-Za-z0-9_][A-Za-z0-9_:\-]*[A-Za-z0-9_]|[A-Za-z0-9_])"
BRACKET = re.compile(r"\[([^\[\]]*@[^\[\]]*)\]")
BARE = re.compile(r"(?<![\w@])" + KEY + r"(?:\s*\[([^\[\]@]*)\])?")
QUOTED = re.compile(r'"([^"]+)"')


def sentence_hash(s):
    return "sha256:" + hashlib.sha256(_lib.norm(s).encode("utf-8")).hexdigest()


def cites_in(sentence):
    """[(citekey, locator)] in order of appearance."""
    found = []
    for m in BRACKET.finditer(sentence):
        for part in m.group(1).split(";"):
            km = re.search(r"(?<![\w@])" + KEY, part)
            if not km:
                continue
            loc = part[km.end():].strip().lstrip(",").strip()
            found.append((m.start(), km.group(1), loc))
    rest = BRACKET.sub(lambda m: " " * len(m.group(0)), sentence)
    for m in BARE.finditer(rest):
        found.append((m.start(), m.group(1), (m.group(2) or "").strip()))
    return [(k, loc) for _, k, loc in sorted(found)]


def claim_text(sentence):
    s = BRACKET.sub(" ", sentence)
    s = BARE.sub(" ", s)
    return s


def straight_quotes(s):
    return s.replace("“", '"').replace("”", '"')


rows = []
for sent in _lib.sentences(_lib.read_text("draft.md")):
    cites = cites_in(sent)
    if not cites:
        continue
    claim = claim_text(sent)
    quoted = [q.strip() for q in QUOTED.findall(straight_quotes(claim)) if q.strip()]
    numbers = _lib.numbers_in(claim)
    seen = {}
    for key, loc in cites:
        if key in seen:
            if loc and loc not in seen[key]:
                seen[key].append(loc)
            continue
        seen[key] = [loc] if loc else []
    for key, locs in seen.items():
        rows.append({"citekey": key, "sentence": sent, "sentence_hash": sentence_hash(sent),
                     "locator": "; ".join(locs), "quoted": quoted, "numbers": numbers})

for i, r in enumerate(rows):
    r["id"] = "r%02d" % (i + 1)
_lib.write_json("rows.json", rows)
