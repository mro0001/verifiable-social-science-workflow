"""diff_changes: sentence-level alignment of baseline.md -> revised.md.

Pairing (each sentence is used once):
  1. Sentences with identical normalized text pair first.
  2. Remaining sentences pair as EDITS by word similarity >= 0.5 (best, then nearest).
  3. The longest run of pairs in the same relative order is the spine; a pair
     outside it MOVED. An identical moved pair is a MOVE (never an insert plus a
     delete); a changed moved pair is an edit with moved=true.
  4. A gap between spine pairs holding one unpaired sentence per side is an
     in-place rewrite and pairs as an edit at similarity >= 0.25.
  5. What is left is INSERT (revised only) or DELETE (baseline only).
Ids c01.. follow revised order; a deletion sits after the revised position of
the last matched baseline sentence before it. Deterministic.
"""
import difflib
import re

import _lib

EDIT_SIM, REWRITE = 0.5, 0.25

CLOSE_QUOTE_END = re.compile(r'(?<=[.!?]["\u201d\'\u2019])\s+(?=[A-Z"\u201c(\[])')


def sentences(text):
    """_lib.sentences, plus a split after a sentence that ends inside a closing quote."""
    return [p for s in _lib.sentences(text) for p in CLOSE_QUOTE_END.split(s) if p.strip()]


base = sentences(_lib.read_text("baseline.md"))
rev = sentences(_lib.read_text("revised.md"))
nb, nr = [_lib.norm(s) for s in base], [_lib.norm(s) for s in rev]


def sim(i, j):
    return difflib.SequenceMatcher(None, nb[i].split(), nr[j].split(), autojunk=False).ratio()


pair = {}  # baseline index -> revised index


def free(side):
    used = set(pair) if side == "b" else set(pair.values())
    return [k for k in range(len(base) if side == "b" else len(rev)) if k not in used]


# 1. identical normalized text pairs first (in order, so repeated sentences pair in sequence)
for i in range(len(base)):
    j = next((j for j in free("r") if nr[j] == nb[i]), None)
    if j is not None:
        pair[i] = j

# 2. remaining sentences pair as edits by similarity (best first, then nearest)
cands = sorted(((sim(i, j), abs(i - j), i, j) for i in free("b") for j in free("r")),
               key=lambda t: (-t[0], t[1], t[2], t[3]))
for r, _, i, j in cands:
    if r < EDIT_SIM:
        break
    if i not in pair and j not in pair.values():
        pair[i] = j


def in_order(pairs):
    """Longest run of pairs whose revised order follows baseline order (LIS);
    deterministic. Pairs outside it are the ones that moved."""
    seq = sorted(pairs)
    best = [1] * len(seq)
    prev = [-1] * len(seq)
    for a in range(len(seq)):
        for b in range(a):
            if seq[b][1] < seq[a][1] and best[b] + 1 > best[a]:
                best[a], prev[a] = best[b] + 1, b
    if not seq:
        return set()
    k = max(range(len(seq)), key=lambda x: (best[x], -x))
    keep = set()
    while k >= 0:
        keep.add(seq[k])
        k = prev[k]
    return keep


spine = in_order(pair.items())

# 3. an in-place rewrite: a gap between spine pairs holding exactly one unpaired
#    sentence on each side pairs as an edit at a lower similarity
anchors = sorted(spine) + [(len(base), len(rev))]
lo_b, lo_r = -1, -1
for hb, hr in anchors:
    gb = [i for i in free("b") if lo_b < i < hb]
    gr = [j for j in free("r") if lo_r < j < hr]
    if len(gb) == 1 and len(gr) == 1 and sim(gb[0], gr[0]) >= REWRITE:
        pair[gb[0]] = gr[0]
        spine.add((gb[0], gr[0]))
    lo_b, lo_r = hb, hr

changes = []
for i, j in sorted(pair.items()):
    moved = (i, j) not in spine
    if nb[i] == nr[j]:
        if moved:
            changes.append({"kind": "move", "b_index": i, "r_index": j, "moved": True,
                            "before": base[i], "after": rev[j]})
        continue
    changes.append({"kind": "edit", "b_index": i, "r_index": j, "moved": moved,
                    "before": base[i], "after": rev[j]})
for i in free("b"):
    changes.append({"kind": "delete", "b_index": i, "r_index": None, "moved": False,
                    "before": base[i], "after": ""})
for j in free("r"):
    changes.append({"kind": "insert", "b_index": None, "r_index": j, "moved": False,
                    "before": "", "after": rev[j]})
b2r = dict(pair)


def position(c):
    if c["r_index"] is not None:
        return (c["r_index"], 0, -1)
    prev = [b2r[k] for k in range(c["b_index"]) if b2r.get(k) is not None]
    return ((max(prev) if prev else -1) + 0.5, 1, c["b_index"])


changes.sort(key=position)
for n, c in enumerate(changes, 1):
    c["id"] = f"c{n:02d}"
_lib.write_json("changes.json", changes)
