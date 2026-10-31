"""Builds synthetic Word documents for the Word reader's tests (Track D, step D18).

python-docx writes the package, the paragraphs, their styles, and the
comments. Tracked changes are raw w:ins, w:del, w:moveFrom, and w:moveTo
elements, each with a w:id, since python-docx has no call for them.

build(path, paragraphs, comments) writes path. paragraphs is a list of
(style, segments), where style is None or a paragraph style such as
"Heading 2", and segments is a list of (kind, text) or (kind, text, author).
kind is plain, link (a run inside a w:hyperlink), ins, del, moveFrom, or
moveTo. A tab or a line break in a segment's text is written as w:tab or w:br.
comments is a list of (author, text, first, last), where first and last are
(paragraph index, segment index) of the first and last segment the comment
covers, and a line break in text starts another paragraph of the comment.
"""
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.text.run import Run

DATE = "2026-10-29T00:00:00Z"

CHANGES = ("ins", "del", "moveFrom", "moveTo")


class _Ids:
    def __init__(self) -> None:
        self.next = 100

    def take(self) -> str:
        self.next += 1
        return str(self.next)


def _run(text: str, deleted: bool):
    r = OxmlElement("w:r")
    piece = []

    def flush():
        if piece:
            t = OxmlElement("w:delText" if deleted else "w:t")
            t.text = "".join(piece)
            t.set(qn("xml:space"), "preserve")
            r.append(t)
            del piece[:]

    for char in text:
        if char == "\t":
            flush()
            r.append(OxmlElement("w:tab"))
        elif char == "\n":
            flush()
            r.append(OxmlElement("w:br"))
        else:
            piece.append(char)
    flush()
    return r


def _segment(p, segment, ids: _Ids, move_names: dict):
    """Append one segment to the paragraph element p and return its w:r."""
    kind, text = segment[0], segment[1]
    author = segment[2] if len(segment) > 2 else ""
    r = _run(text, deleted=(kind == "del"))
    if kind == "plain":
        p.append(r)
        return r
    if kind == "link":
        link = OxmlElement("w:hyperlink", attrs={qn("w:anchor"): "ref"})
        link.append(r)
        p.append(link)
        return r
    if kind not in CHANGES:
        raise ValueError(f"unknown segment kind {kind}")
    attrs = {qn("w:id"): ids.take(), qn("w:author"): author, qn("w:date"): DATE}
    if kind in ("moveFrom", "moveTo"):
        name = move_names.setdefault(text.strip(), f"move{len(move_names) + 1}")
        range_id = ids.take()
        p.append(OxmlElement(f"w:{kind}RangeStart", attrs={
            qn("w:id"): range_id, qn("w:name"): name, qn("w:author"): author, qn("w:date"): DATE}))
        change = OxmlElement(f"w:{kind}", attrs=attrs)
        change.append(r)
        p.append(change)
        p.append(OxmlElement(f"w:{kind}RangeEnd", attrs={qn("w:id"): range_id}))
        return r
    change = OxmlElement(f"w:{kind}", attrs=attrs)
    change.append(r)
    p.append(change)
    return r


def build(path, paragraphs, comments=()):
    doc = Document()
    ids = _Ids()
    move_names = {}
    runs = []
    for style, segments in paragraphs:
        paragraph = doc.add_paragraph(style=style) if style else doc.add_paragraph()
        runs.append([Run(_segment(paragraph._p, s, ids, move_names), paragraph) for s in segments])
    for author, text, first, last in comments:
        lines = text.split("\n")
        comment = doc.add_comment(
            [runs[first[0]][first[1]], runs[last[0]][last[1]]], text=lines[0], author=author
        )
        for line in lines[1:]:
            comment.add_paragraph(line)
    doc.save(str(path))
    return path
