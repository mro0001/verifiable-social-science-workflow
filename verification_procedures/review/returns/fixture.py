"""Synthetic reviewed-docx fixture for the returns contract. Fake prose, real revision-mark shapes.

Builds, programmatically, a docx containing genuine OOXML tracked changes:

- one ``w:ins`` insertion (numeric edit -- text contains digits),
- one ``w:del`` deletion whose child run uses ``w:delText`` (prose edit -- no digits),
- one margin comment (python-docx 1.2 ``Document.add_comment`` API).

Hard-won shape note: pandoc's docx reader SILENTLY DROPS ``w:ins``/``w:del``
elements that lack a ``w:id`` attribute -- the wrapped text vanishes from both
the tracked and the accepted output. ``w:id`` is required by the OOXML schema
and every real reviewer docx carries it, so the fixture sets it too.

Second shape note: pandoc normalizes a trailing space inside a tracked span to
sit outside the span, so the deletion's ``w:delText`` carries a trailing space
(for natural accepted prose) while the expected extracted span text
(``DELETION_TEXT``) does not.
"""
from pathlib import Path
from typing import Union

import docx
from docx.oxml.ns import qn
from docx.oxml.parser import OxmlElement

PathLike = Union[str, Path]

INSERTION_AUTHOR = "Synthetic Reviewer"
DELETION_AUTHOR = "Second Reviewer"
REVISION_DATE = "2026-07-23T00:00:00Z"

# Numeric edit: touches_number must come out True.
INSERTION_TEXT = "48.6% in the final pass"
# Prose edit: touches_number must come out False. Expected span text (no trailing space).
DELETION_TEXT = "entirely redundant and"
_DELETION_DOCX_TEXT = DELETION_TEXT + " "

COMMENT_AUTHOR = "Margin Annotator"
COMMENT_TEXT = "Please cite the synthetic archive here."


def _wrap_run_in_ins(run, author, date, rev_id):
    """Wrap an existing python-docx run in <w:ins author date id>."""
    r = run._r
    ins = OxmlElement("w:ins")
    ins.set(qn("w:id"), str(rev_id))
    ins.set(qn("w:author"), author)
    ins.set(qn("w:date"), date)
    r.addprevious(ins)
    ins.append(r)


def _append_del(paragraph, text, author, date, rev_id):
    """Append <w:del><w:r><w:delText>text</w:delText></w:r></w:del> to a paragraph."""
    delel = OxmlElement("w:del")
    delel.set(qn("w:id"), str(rev_id))
    delel.set(qn("w:author"), author)
    delel.set(qn("w:date"), date)
    del_r = OxmlElement("w:r")
    del_t = OxmlElement("w:delText")
    del_t.set(qn("xml:space"), "preserve")
    del_t.text = text
    del_r.append(del_t)
    delel.append(del_r)
    paragraph._p.append(delel)


def build_reviewed_docx(path):
    # type: (PathLike) -> Path
    """Build the reviewed fixture docx at *path* and return the path."""
    path = Path(path)
    doc = docx.Document()

    doc.add_paragraph("The synthetic cohort was assembled from twelve fabricated sites.")

    # Insertion (numeric edit).
    p_ins = doc.add_paragraph()
    p_ins.add_run("The widget rate rose to ")
    ins_run = p_ins.add_run(INSERTION_TEXT)
    p_ins.add_run(" during review.")
    _wrap_run_in_ins(ins_run, INSERTION_AUTHOR, REVISION_DATE, 101)

    # Deletion (prose edit).
    p_del = doc.add_paragraph()
    p_del.add_run("The gadget protocol was ")
    _append_del(p_del, _DELETION_DOCX_TEXT, DELETION_AUTHOR, REVISION_DATE, 102)
    p_del.add_run("kept for audit.")

    # Margin comment via the python-docx 1.2 API (fall back loudly if absent).
    p_c = doc.add_paragraph()
    c_run = p_c.add_run("The archive column needs a synthetic source note.")
    if not hasattr(doc, "add_comment"):
        raise RuntimeError(
            "python-docx has no Document.add_comment; fixture requires python-docx >= 1.2"
        )
    doc.add_comment(c_run, text=COMMENT_TEXT, author=COMMENT_AUTHOR, initials="MA")

    doc.save(str(path))
    return path


def build_clean_docx(path):
    # type: (PathLike) -> Path
    """Build a docx with NO revisions and NO comments at *path* and return the path."""
    path = Path(path)
    doc = docx.Document()
    doc.add_paragraph("The synthetic cohort was assembled from twelve fabricated sites.")
    doc.add_paragraph("No reviewer has touched this fabricated draft.")
    doc.save(str(path))
    return path
