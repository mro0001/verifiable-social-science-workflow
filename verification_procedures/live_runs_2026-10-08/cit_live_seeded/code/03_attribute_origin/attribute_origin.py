"""Label each row by who contributed it (the scope rule of 2026-10-08).

  yours                     author introduced the source AND the sentence is
                            unchanged from the author's last draft -> not checked
  ai_added                  AI introduced the source -> checked
  ai_reworded               author's source, sentence changed since the author's
                            draft -> checked
  ai_sourced_author_worded  AI introduced the source, the sentence is as the author
                            last wrote it (reworded or moved by the author) -> checked
  unknown                   no log entry -> treated as AI, checked, flagged

Sentences are matched by normalized text, never by position, so a sentence
that only moved keeps its label. `moved` notes a sentence whose text is
unchanged but whose neighbors on both sides differ from the author's draft."""
import _lib

rows = _lib.read_json("rows.json")
now_sents = [_lib.norm(x) for x in _lib.sentences(_lib.read_text("draft.md"))]
author_sents = [_lib.norm(x) for x in _lib.sentences(_lib.read_text("author_draft.md"))]
log = _lib.read_yaml("citation_log.yaml") or {}
log = log.get("citations", log)
author_set = set(author_sents)


def neighbors(seq, s):
    i = seq.index(s)
    return (seq[i - 1] if i > 0 else None, seq[i + 1] if i + 1 < len(seq) else None)


def was_moved(s):
    """Moved = text unchanged but both neighbors differ from the author's draft."""
    if s not in author_set or s not in now_sents:
        return False
    (p0, n0), (p1, n1) = neighbors(author_sents, s), neighbors(now_sents, s)
    return p0 != p1 and n0 != n1


findings, out = [], []
for r in rows:
    n = _lib.norm(r["sentence"])
    in_author = n in author_set
    moved = was_moved(n)
    entry = log.get(r["citekey"]) or {}
    by = entry.get("introduced_by")
    if by == "author":
        origin = "yours" if in_author else "ai_reworded"
    elif by == "ai":
        origin = "ai_sourced_author_worded" if in_author else "ai_added"
    else:
        origin = "unknown"
    status = "author" if origin == "yours" else "needs_check"
    row = dict(r, origin=origin, moved=moved, status=status,
               introduced_in=str(entry.get("draft", "")), introduced_session=str(entry.get("session", "")))
    out.append(row)
    if origin == "unknown":
        findings.append(_lib.finding(
            "attribute_origin", "warning", r["id"],
            "origin unknown (no citation-log entry for @%s); checked as if AI-contributed" % r["citekey"],
            r["citekey"]))
    elif origin == "yours":
        findings.append(_lib.finding(
            "attribute_origin", "info", r["id"],
            "not checked, author's warrant" + (" (sentence moved, text unchanged)" if moved else ""),
            r["citekey"]))

_lib.write_json("rows_attributed.json", out)
_lib.emit_findings("attribute_origin", findings)
