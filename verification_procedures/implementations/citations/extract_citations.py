"""One row per (citekey, sentence) from the pandoc-markdown draft.

Recognizes bracketed citations ([@a, p. 4; @b]) and bare ones (@a, @a [p. 4]).
Each row carries the sentence, its normalized hash (for matching across
drafts), the locator(s), the phrases the sentence puts in quotation marks, and
the numbers in the claim text (citations and locators removed first).

An @ that pandoc prints as text is not a citation (Track L, Step L3). That is
an @ a backslash escapes, as in \\@key and [\\@key], and any @ inside inline
code or a fenced code block. The sentences keep their text as written.

A draft that cites only by author and year in parentheses gives no row, so the
step then writes one blocking finding on draft.md, saying its citations are in
a form this check cannot read and must be written as keys first, with a count
of the author-year citations seen (Track L, Step L5). The finding is written to
findings_extract_citations.json, which is otherwise an empty list.
"""
import hashlib
import re
import string

import _lib

KEY = r"@([A-Za-z0-9_][A-Za-z0-9_:\-]*[A-Za-z0-9_]|[A-Za-z0-9_])"
BRACKET = re.compile(r"\[([^\[\]]*@[^\[\]]*)\]")
BARE = re.compile(r"(?<![\w@])" + KEY + r"(?:\s*\[([^\[\]@]*)\])?")
QUOTED = re.compile(r'"([^"]+)"')


def sentence_hash(s):
    return "sha256:" + hashlib.sha256(_lib.norm(s).encode("utf-8")).hexdigest()


# A fence that opens a code block, three or more backticks or tildes after at
# most three spaces. A backtick fence's info text holds no backtick.
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
BLANK_LINE = re.compile(r"\n[ \t]*\n")
# The character that stands in for an @ pandoc prints as text, in the copy of the
# draft the citations are read from. It is not a word character, a space, or any
# character the sentence splitter looks at, so both copies split alike.
HIDDEN = "\x00"


def _fences(text):
    """The (start, end) of each fenced code block, fences included. A fence closes at
    the next line of the same character, at least as long, with nothing after it but
    spaces. A fence that never closes opens no block, as in pandoc."""
    lines = text.splitlines(True)
    starts, at = [], 0
    for line in lines:
        starts.append(at)
        at += len(line)
    blocks, i = [], 0
    while i < len(lines):
        m = FENCE.match(lines[i].rstrip("\r\n"))
        if m and not (m.group(1)[0] == "`" and "`" in m.group(2)):
            mark = m.group(1)
            close = re.compile(r"^ {0,3}%s{%d,}[ \t]*$" % (re.escape(mark[0]), len(mark)))
            j = next((j for j in range(i + 1, len(lines)) if close.match(lines[j].rstrip("\r\n"))), None)
            if j is not None:
                blocks.append((starts[i], starts[j] + len(lines[j])))
                i = j + 1
                continue
        i += 1
    return blocks


def _inline(text, start, end):
    """The (start, end) of each inline code span between start and end, and the
    position of each @ a backslash escapes outside them. A run of backticks opens a
    span that the next run of the same length closes within the paragraph. A run
    with no such close is text, and a backslash before any ASCII punctuation makes it
    text."""
    spans, escaped, k = [], [], start
    while k < end:
        ch = text[k]
        if ch == "\\" and k + 1 < end and text[k + 1] in string.punctuation:
            if text[k + 1] == "@":
                escaped.append(k + 1)
            k += 2
            continue
        if ch == "`":
            n = len(text[k:end]) - len(text[k:end].lstrip("`"))
            blank = BLANK_LINE.search(text, k, end)
            stop = blank.start() if blank else end
            close = re.compile(r"(?<!`)`{%d}(?!`)" % n).search(text, k + n, stop)
            if close:
                spans.append((k, close.end()))
                k = close.end()
            else:
                k += n
            continue
        k += 1
    return spans, escaped


def code_and_escapes(text):
    """The (start, end) of everything pandoc reads as code, fenced blocks and inline
    code, and the position of each @ a backslash escapes outside code."""
    code, escaped, at = [], [], 0
    for start, end in _fences(text) + [(len(text), len(text))]:
        spans, marks = _inline(text, at, start)
        code += spans + ([(start, end)] if end > start else [])
        escaped += marks
        at = end
    return code, escaped


def readable(text):
    """The text with every @ pandoc prints as text replaced by HIDDEN, the same length
    and otherwise the same, so citations are read from it and nothing else changes."""
    code, escaped = code_and_escapes(text)
    hidden = set(escaped)
    for start, end in code:
        hidden.update(i for i in range(start, end) if text[i] == "@")
    return "".join(HIDDEN if i in hidden else ch for i, ch in enumerate(text))


def cites_in(sentence, read=None):
    """[(citekey, locator)] in order of appearance. The citations are found in read,
    the sentence as readable() gives it, and the locators are taken from the sentence."""
    read = sentence if read is None else read
    found = []
    for m in BRACKET.finditer(read):
        at = m.start(1)
        for part in m.group(1).split(";"):
            km = re.search(r"(?<![\w@])" + KEY, part)
            if km:
                loc = sentence[at + km.end():at + len(part)].strip().lstrip(",").strip()
                found.append((m.start(), km.group(1), loc))
            at += len(part) + 1
    rest = BRACKET.sub(lambda m: " " * len(m.group(0)), read)
    for m in BARE.finditer(rest):
        loc = sentence[m.start(2):m.end(2)] if m.group(2) is not None else ""
        found.append((m.start(), m.group(1), loc.strip()))
    return [(k, loc) for _, k, loc in sorted(found)]


def _cut(pattern, text, read):
    """text and read with each match of pattern in read replaced by one space."""
    out_text, out_read, last = [], [], 0
    for m in pattern.finditer(read):
        out_text += [text[last:m.start()], " "]
        out_read += [read[last:m.start()], " "]
        last = m.end()
    return "".join(out_text) + text[last:], "".join(out_read) + read[last:]


def claim_text(sentence, read=None):
    read = sentence if read is None else read
    s, r = _cut(BRACKET, sentence, read)
    s, r = _cut(BARE, s, r)
    return s


# An author-year citation inside parentheses, as in (Smith, 2020), (Lee & Park
# 2019), or (Chan et al., 2021, p. 4). A month and year, as in (March 2020), is
# not one.
PARENS = re.compile(r"\(([^()]*)\)")
NAME = r"[A-Z\u00C0-\u00DE][\w'\u2019\-]*"
MONTH = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\b"
AUTHOR_YEAR = re.compile(r"(?<![\w\-])(?!" + MONTH + ")" + NAME + r"(?:(?:,| and| &|, and|, &)? " + NAME
                         + r")*(?: et al\.)?,? (?:1[6-9]|20)\d{2}[a-z]?(?!\w)")


def without_code(text):
    """The text with everything pandoc reads as code blanked, line breaks kept."""
    chars = list(text)
    for start, end in code_and_escapes(text)[0]:
        for i in range(start, end):
            if chars[i] != "\n":
                chars[i] = " "
    return "".join(chars)


def author_year(text):
    """(count, first sentence) of the author-year citations inside parentheses in the
    text outside code, each part of a parenthesis split at semicolons counted once."""
    count, first = 0, ""
    for sent in _lib.sentences(without_code(text)):
        for m in PARENS.finditer(sent):
            for part in m.group(1).split(";"):
                if AUTHOR_YEAR.search(part):
                    count += 1
                    first = first or sent
    return count, first


def straight_quotes(s):
    return s.replace("“", '"').replace("”", '"')


text = _lib.read_text("draft.md")
sentences = _lib.sentences(text)
reads = _lib.sentences(readable(text))
assert len(reads) == len(sentences), "the readable copy split into other sentences"
rows = []
for sent, read in zip(sentences, reads):
    cites = cites_in(sent, read)
    if not cites:
        continue
    claim = claim_text(sent, read)
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

findings = []
if not rows:
    n_author_year, first = author_year(text)
    if n_author_year:
        findings.append(_lib.finding(
            "extract_citations", "blocking", "draft.md",
            "%d author-year %s written in a form this check cannot read and must be written as "
            "citation keys first" % (n_author_year, "citation is" if n_author_year == 1 else "citations are"),
            _lib.cell(first)))
_lib.emit_findings("extract_citations", findings)
