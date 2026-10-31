"""Extract tracked edits and margin comments from a reviewed docx. FROZEN surface in CONTRACT.md.

Read-only: extract never writes any file and never modifies the input docx.
Porting the deltas into canonical markdown is a human-in-the-loop act upstream.
"""
import re
import subprocess
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, NamedTuple, Union

PathLike = Union[str, Path]

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


class Delta(NamedTuple):
    kind: str  # "insertion" | "deletion"
    text: str
    author: str
    date: str
    touches_number: bool


class Comment(NamedTuple):
    author: str
    text: str


class ReturnBundle(NamedTuple):
    deltas: List[Delta]
    comments: List[Comment]
    tracked_markdown: str
    accepted_markdown: str


# Pandoc bracketed span: [text]{attrs}. Pandoc escapes literal brackets inside
# span text, so an unescaped ] reliably closes the span (per contract; do not
# over-engineer).
_SPAN = re.compile(r"\[((?:[^\[\]\\]|\\.)*)\]\{([^{}]*)\}")
# Class tokens must stand alone in the attribute block (start or whitespace
# before the dot) so dots inside attribute values never read as classes.
_INSERTION_CLASS = re.compile(r"(?:^|\s)\.insertion(?=\s|$|\})")
_DELETION_CLASS = re.compile(r"(?:^|\s)\.deletion(?=\s|$|\})")
_UNESCAPE = re.compile(r"\\([^A-Za-z0-9\s])")


def _attr(attrs, name):
    # type: (str, str) -> str
    """Pull name="value" out of a pandoc attribute block, any attribute order."""
    m = re.search(r'\b%s="([^"]*)"' % re.escape(name), attrs)
    return m.group(1) if m else ""


def _unescape(text):
    # type: (str) -> str
    """Undo pandoc's backslash-escaping of markdown punctuation in span text."""
    return _UNESCAPE.sub(r"\1", text)


def _run_pandoc(pandoc, docx_path, mode):
    # type: (str, Path, str) -> str
    cmd = [
        pandoc,
        "-f",
        "docx",
        "-t",
        "markdown",
        "--track-changes=%s" % mode,
        "--wrap=none",
        str(docx_path),
    ]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "pandoc failed (%s) on %s: %s"
            % (mode, docx_path, proc.stderr.decode("utf-8", "replace").strip())
        )
    return proc.stdout.decode("utf-8")


def _parse_deltas(tracked_markdown):
    # type: (str) -> List[Delta]
    deltas = []
    for m in _SPAN.finditer(tracked_markdown):
        raw_text, attrs = m.group(1), m.group(2)
        if _INSERTION_CLASS.search(attrs):
            kind = "insertion"
        elif _DELETION_CLASS.search(attrs):
            kind = "deletion"
        else:
            continue  # comment-start / comment-end / unrelated spans
        text = _unescape(raw_text)
        deltas.append(
            Delta(
                kind=kind,
                text=text,
                author=_attr(attrs, "author"),
                date=_attr(attrs, "date"),
                touches_number=any(ch.isdigit() for ch in text),
            )
        )
    return deltas


def _comments_via_api(docx_path):
    # type: (Path) -> List[Comment]
    import docx as _docx

    doc = _docx.Document(str(docx_path))
    comments_obj = getattr(doc, "comments", None)
    if comments_obj is None:
        raise AttributeError("python-docx Document has no .comments")
    return [Comment(author=c.author or "", text=c.text or "") for c in comments_obj]


def _comments_via_xml(docx_path):
    # type: (Path) -> List[Comment]
    """Fallback: read word/comments.xml straight out of the package."""
    out = []
    with zipfile.ZipFile(str(docx_path)) as zf:
        if "word/comments.xml" not in zf.namelist():
            return out
        root = ET.fromstring(zf.read("word/comments.xml"))
    for node in root.findall("{%s}comment" % _W_NS):
        author = node.get("{%s}author" % _W_NS, "")
        texts = [t.text or "" for t in node.iter("{%s}t" % _W_NS)]
        out.append(Comment(author=author, text="".join(texts)))
    return out


def _read_comments(docx_path):
    # type: (Path) -> List[Comment]
    try:
        return _comments_via_api(docx_path)
    except Exception:
        return _comments_via_xml(docx_path)


def extract(reviewed_docx, *, pandoc="pandoc"):
    # type: (PathLike, str) -> ReturnBundle
    """Extract tracked edits and margin comments from *reviewed_docx*. Read-only."""
    docx_path = Path(reviewed_docx)
    if not docx_path.is_file():
        raise FileNotFoundError(str(docx_path))
    tracked_markdown = _run_pandoc(pandoc, docx_path, "all")
    accepted_markdown = _run_pandoc(pandoc, docx_path, "accept")
    return ReturnBundle(
        deltas=_parse_deltas(tracked_markdown),
        comments=_read_comments(docx_path),
        tracked_markdown=tracked_markdown,
        accepted_markdown=accepted_markdown,
    )
