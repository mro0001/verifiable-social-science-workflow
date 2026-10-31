"""Synthetic lineage and return fixtures for the reconcile contract.

Fake prose, real shapes: markdown snapshots with a ledgered baseline -> revision
pair carrying exactly four AI change regions (word swap, sentence insertion,
deletion, phrase rewrite) plus an unchanged pipe table (to exercise pandoc
table-rendering normalization), and programmatically built final-state return
docx files for each native Word gesture. The pending return reuses the returns
fixture's OOXML injection so the unresolved insertion is a genuine ``w:ins``.
"""
from pathlib import Path
from typing import Optional, Sequence, Tuple, Union

import docx

from review.returns.fixture import _wrap_run_in_ins

PathLike = Union[str, Path]

TITLE = "Synthetic Reconcile Trial"

P_COHORT = "The fabricated cohort spans twelve invented sites across four seasons."

# Region: sentence insertion (whole new paragraph in the revision).
S_INSERTED = "A wholly new synthetic sentence was inserted by the reviser."

# Region: single word swap (calibrated -> aligned).
SWAP_BASE_WORD = "calibrated"
SWAP_REV_WORD = "aligned"
MODIFIED_WORD = "recalibrated"  # neither form; used by the modified return
_P_ASSAY = "The widget assay was {0} against the archived reference batch every single morning."
P_ASSAY_BASE = _P_ASSAY.format(SWAP_BASE_WORD)
P_ASSAY_REV = _P_ASSAY.format(SWAP_REV_WORD)
P_ASSAY_MODIFIED = _P_ASSAY.format(MODIFIED_WORD)

# Region: phrase rewrite (shares the middle word "the"; must merge to one region).
REWRITE_BASE_PHRASE = "drifted upward during the second week"
REWRITE_REV_PHRASE = "held steady across the middle fortnight"
_P_PIPE = "The gadget pipeline {0} of the fabricated period."
P_PIPE_BASE = _P_PIPE.format(REWRITE_BASE_PHRASE)
P_PIPE_REV = _P_PIPE.format(REWRITE_REV_PHRASE)
# Replacement paragraph sharing no 4-gram context anchor with the revision.
P_PIPE_CONFLICT = "Unrelated replacement prose stands here without old anchor words."

TABLE = (
    ("Site", "Batch", "Yield"),
    ("North", "A", "12"),
    ("South", "B", "9"),
)

# Region: sentence deletion (first sentence of the closing paragraph).
DELETED_SENTENCE = "An obsolete disclaimer sentence sits here awaiting deletion."
CLOSING_SENTENCE = "The closing summary restates the fabricated findings plainly."
P_CLOSE_BASE = DELETED_SENTENCE + " " + CLOSING_SENTENCE
P_CLOSE_REV = CLOSING_SENTENCE

REGION_COUNT = 4

# The author's own untracked addition (outside every region).
AUTHOR_SENTENCE = "The author appended this untracked remark at the very end."

PENDING_AUTHOR = "Claude"
PENDING_DATE = "2026-07-23T00:00:00Z"

COMMENT_AUTHOR = "Margin Author"
COMMENT_TEXT = "A synthetic margin remark about the fabricated cohort."

BASELINE_VERSION = "v001"
REVISION_VERSION = "v002"

_PIPE_TABLE_MD = "\n".join(
    ["| " + " | ".join(TABLE[0]) + " |", "|---|---|---|"]
    + ["| " + " | ".join(row) + " |" for row in TABLE[1:]]
)

BASELINE_MD = "\n\n".join(
    [
        "# " + TITLE,
        P_COHORT,
        P_ASSAY_BASE,
        P_PIPE_BASE,
        _PIPE_TABLE_MD,
        P_CLOSE_BASE,
    ]
) + "\n"

REVISION_MD = "\n\n".join(
    [
        "# " + TITLE,
        P_COHORT,
        S_INSERTED,
        P_ASSAY_REV,
        P_PIPE_REV,
        _PIPE_TABLE_MD,
        P_CLOSE_REV,
    ]
) + "\n"

BUILDS_MD = """# Builds

| version | date | git | sha256 | purpose | baseline | reviewed |
|---|---|---|---|---|---|---|
| v001 | 2026-07-23 | 0000000 | 00ff00ff | synthetic baseline | - | no |
| v002 | 2026-07-23 | 1111111 | 11ee11ee | synthetic revision (four AI regions) | v001 | no |
"""


def build_builds_dir(dirpath):
    # type: (PathLike) -> Path
    """Write BUILDS.md plus the v001/v002 snapshots into *dirpath*; return it."""
    dirpath = Path(dirpath)
    dirpath.mkdir(parents=True, exist_ok=True)
    (dirpath / (BASELINE_VERSION + ".md")).write_text(BASELINE_MD, encoding="utf-8")
    (dirpath / (REVISION_VERSION + ".md")).write_text(REVISION_MD, encoding="utf-8")
    (dirpath / "BUILDS.md").write_text(BUILDS_MD, encoding="utf-8")
    return dirpath


# --- return docx builders (final state; no tracked changes unless stated) -----


def _build_return(
    path,  # type: PathLike
    paragraphs,  # type: Sequence[str]
    pending_insertion=None,  # type: Optional[str]
    comment=None,  # type: Optional[Tuple[str, str]]
):
    # type: (...) -> Path
    """Assemble a return docx: heading, body paragraphs with the table sitting
    before the last one (mirroring the snapshots), optional pending ``w:ins``
    paragraph (the one whose text equals *pending_insertion*), optional margin
    comment anchored to the first body paragraph."""
    path = Path(path)
    doc = docx.Document()
    doc.add_heading(TITLE, level=1)
    body = list(paragraphs)
    for text in body[:-1]:
        if text == pending_insertion:
            paragraph = doc.add_paragraph()
            run = paragraph.add_run(text)
            _wrap_run_in_ins(run, PENDING_AUTHOR, PENDING_DATE, 901)
        else:
            doc.add_paragraph(text)
    table = doc.add_table(rows=0, cols=len(TABLE[0]))
    for row in TABLE:
        cells = table.add_row().cells
        for cell, value in zip(cells, row):
            cell.text = value
    doc.add_paragraph(body[-1])
    if comment is not None:
        author, text = comment
        target = doc.paragraphs[1].runs[0]
        doc.add_comment(target, text=text, author=author, initials="MA")
    doc.save(str(path))
    return path


def build_return_all_accepted(path):
    # type: (PathLike) -> Path
    """Every AI change accepted; no author work."""
    return _build_return(path, [P_COHORT, S_INSERTED, P_ASSAY_REV, P_PIPE_REV, P_CLOSE_REV])


def build_return_one_rejected(path):
    # type: (PathLike) -> Path
    """The phrase rewrite rejected (baseline text restored); the rest accepted."""
    return _build_return(path, [P_COHORT, S_INSERTED, P_ASSAY_REV, P_PIPE_BASE, P_CLOSE_REV])


def build_return_one_modified(path):
    # type: (PathLike) -> Path
    """The word swap rewritten to a third form; the rest accepted."""
    return _build_return(path, [P_COHORT, S_INSERTED, P_ASSAY_MODIFIED, P_PIPE_REV, P_CLOSE_REV])


def build_return_author_edit(path):
    # type: (PathLike) -> Path
    """Everything accepted plus an untracked author sentence outside all regions,
    and one margin comment."""
    return _build_return(
        path,
        [P_COHORT, S_INSERTED, P_ASSAY_REV, P_PIPE_REV, P_CLOSE_REV + " " + AUTHOR_SENTENCE],
        comment=(COMMENT_AUTHOR, COMMENT_TEXT),
    )


def build_return_pending(path):
    # type: (PathLike) -> Path
    """Everything accepted except the inserted sentence, which remains a genuine
    unresolved ``w:ins`` tracked change authored by the AI."""
    return _build_return(
        path,
        [P_COHORT, S_INSERTED, P_ASSAY_REV, P_PIPE_REV, P_CLOSE_REV],
        pending_insertion=S_INSERTED,
    )


def build_return_conflict(path):
    # type: (PathLike) -> Path
    """The rewrite paragraph replaced wholesale, destroying its context anchors."""
    return _build_return(path, [P_COHORT, S_INSERTED, P_ASSAY_REV, P_PIPE_CONFLICT, P_CLOSE_REV])
