"""The Word document reader, which gives a document's text on two sides (Track D, step D18).

Appendix-only. A2.5 Prose says that for Word, programs show AI changes as
tracked changes and then read back the scholar's responses, and the A2.2
Adapters bullet names an adapter from a Word document with tracked changes to
the files the prose procedure checks. The Word adapter (step D19) builds on
this reader. It reads the package's XML with zipfile and xml.etree from the
standard library (Track D choice 13).

read_docx(path) reads word/document.xml, word/comments.xml, and
word/styles.xml and returns a mapping with two lists.

- paragraphs. Each has level (N for a style named heading N, else 0),
  baseline and revised (its text on each side), and changes. The revised side
  keeps plain runs, w:ins, and w:moveTo. The baseline side keeps plain runs,
  w:del (its w:delText), and w:moveFrom. So the baseline is the text with
  every tracked change rejected and the revised side the text with every one
  accepted. Runs inside hyperlinks count, w:tab is a tab, and w:br is a line
  break. Each tracked change in changes has its author, its side, and its
  character span there, start and end.
- comments. Each has id, author, text (its paragraphs joined by a line
  break), and span, which gives for each side the start and end of the text
  between its w:commentRangeStart and w:commentRangeEnd, each as
  [paragraph index, character offset]. span is None when the document marks
  no range for the comment. Comments come in the order comments.xml lists
  them.

side_text(doc, side) joins the paragraphs that are not empty on that side
with a blank line, writes a heading as # repeated to its level and a space
before its text, and ends with one line break.
"""
import re
import zipfile
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

SIDES = ("baseline", "revised")
BOTH = frozenset(SIDES)

# A tracked change keeps its text on one side only.
CHANGE_SIDE = {
    W + "ins": "revised",
    W + "moveTo": "revised",
    W + "del": "baseline",
    W + "moveFrom": "baseline",
}

# Elements inside a paragraph whose runs count as if they stood in the paragraph.
INLINE = {W + "hyperlink", W + "smartTag", W + "customXml", W + "fldSimple", W + "sdt", W + "sdtContent"}

# Elements holding paragraphs, walked for the paragraphs inside them.
BLOCK = {W + "tbl", W + "tr", W + "tc", W + "sdt", W + "sdtContent", W + "customXml"}

HEADING = re.compile(r"heading\s+(\d+)", re.IGNORECASE)


class DocxError(ValueError):
    """A file could not be read as a Word document. The message names the file and the part."""


class _Paragraph:
    """The text of one paragraph as it is read, on both sides, with its changes and comment marks."""

    def __init__(self, index: int) -> None:
        self.index = index
        self.parts = {side: [] for side in SIDES}  # type: Dict[str, List[str]]
        self.length = {side: 0 for side in SIDES}
        self.changes = []  # type: List[dict]

    def add(self, text: str, sides) -> None:
        for side in sides:
            self.parts[side].append(text)
            self.length[side] += len(text)

    def place(self) -> Dict[str, List[int]]:
        return {side: [self.index, self.length[side]] for side in SIDES}

    def text(self, side: str) -> str:
        return "".join(self.parts[side])


def _run(r, sides, para: _Paragraph) -> None:
    for child in r:
        tag = child.tag
        if tag == W + "t":
            para.add(child.text or "", sides)
        elif tag == W + "delText":
            if "revised" not in sides:
                para.add(child.text or "", sides)
        elif tag == W + "tab":
            para.add("\t", sides)
        elif tag == W + "br":
            para.add("\n", sides)


def _walk(element, sides, para: _Paragraph, starts: dict, ends: dict) -> None:
    for child in element:
        tag = child.tag
        if tag == W + "r":
            _run(child, sides, para)
        elif tag in CHANGE_SIDE:
            narrowed = sides & {CHANGE_SIDE[tag]}
            if not narrowed:
                _walk(child, narrowed, para, starts, ends)
                continue
            side = CHANGE_SIDE[tag]
            start = para.length[side]
            _walk(child, narrowed, para, starts, ends)
            end = para.length[side]
            if end > start:
                para.changes.append(
                    {"author": child.get(W + "author", ""), "side": side, "start": start, "end": end}
                )
        elif tag in INLINE:
            _walk(child, sides, para, starts, ends)
        elif tag == W + "commentRangeStart":
            starts.setdefault(child.get(W + "id", ""), para.place())
        elif tag == W + "commentRangeEnd":
            ends.setdefault(child.get(W + "id", ""), para.place())


def _paragraph_elements(element):
    for child in element:
        if child.tag == W + "p":
            yield child
        elif child.tag in BLOCK:
            for inner in _paragraph_elements(child):
                yield inner


def _style_names(root) -> Dict[str, str]:
    names = {}
    if root is None:
        return names
    for style in root.iter(W + "style"):
        name = style.find(W + "name")
        if name is not None:
            names[style.get(W + "styleId", "")] = name.get(W + "val", "")
    return names


def _level(p, styles: Dict[str, str]) -> int:
    style = p.find(W + "pPr/" + W + "pStyle")
    if style is None:
        return 0
    found = HEADING.fullmatch(styles.get(style.get(W + "val", ""), "").strip())
    return int(found.group(1)) if found else 0


def _plain_text(p) -> str:
    para = _Paragraph(0)
    _walk(p, BOTH, para, {}, {})
    return para.text("revised")


def _part(package, path: str, name: str, required: bool):
    try:
        data = package.read(name)
    except KeyError:
        if required:
            raise DocxError(f"{path} is not a Word document, it has no {name}")
        return None
    try:
        return ET.fromstring(data)
    except ET.ParseError as error:
        raise DocxError(f"{path} has a {name} that is not XML, {error}")


def read_docx(path) -> dict:
    """The paragraphs and comments of the Word document at path, as the module docstring describes."""
    try:
        package = zipfile.ZipFile(str(path))
    except (OSError, zipfile.BadZipFile) as error:
        raise DocxError(f"{path} cannot be read as a Word document, {error}")
    with package:
        document = _part(package, str(path), "word/document.xml", True)
        comments_root = _part(package, str(path), "word/comments.xml", False)
        styles = _style_names(_part(package, str(path), "word/styles.xml", False))

    body = document.find(W + "body")
    starts, ends = {}, {}  # type: Dict[str, dict], Dict[str, dict]
    paragraphs = []
    for index, p in enumerate(_paragraph_elements(body if body is not None else [])):
        para = _Paragraph(index)
        _walk(p, BOTH, para, starts, ends)
        paragraphs.append({
            "level": _level(p, styles),
            "baseline": para.text("baseline"),
            "revised": para.text("revised"),
            "changes": para.changes,
        })

    comments = []
    if comments_root is not None:
        for comment in comments_root.iter(W + "comment"):
            cid = comment.get(W + "id", "")
            span = None  # type: Optional[dict]
            if cid in starts and cid in ends:
                span = {side: {"start": starts[cid][side], "end": ends[cid][side]} for side in SIDES}
            comments.append({
                "id": cid,
                "author": comment.get(W + "author", ""),
                "text": "\n".join(_plain_text(p) for p in _paragraph_elements(comment)),
                "span": span,
            })
    return {"paragraphs": paragraphs, "comments": comments}


def side_text(doc: dict, side: str) -> str:
    """The document's text on one side, paragraphs that are not empty joined by a blank line."""
    if side not in SIDES:
        raise ValueError(f"side is baseline or revised, not {side}")
    parts = []
    for paragraph in doc["paragraphs"]:
        text = paragraph[side]
        if not text.strip():
            continue
        if paragraph["level"]:
            text = "#" * paragraph["level"] + " " + text
        parts.append(text)
    return "\n\n".join(parts) + "\n" if parts else ""
