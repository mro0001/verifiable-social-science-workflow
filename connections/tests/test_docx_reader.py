"""Tests for the Word document reader (Track D, step D18).

Appendix-only. A2.5 Prose says that for Word, programs show AI changes as
tracked changes and then read back the scholar's responses, and the A2.2
Adapters bullet names an adapter from a Word document with tracked changes to
the files the prose procedure checks. The reader reads the document's XML
with the standard library (Track D choice 13) and gives each paragraph's text
on two sides. The baseline side is the text with every tracked change
rejected, and the revised side the text with every one accepted.

Every document here is built by the test with docx_builder.py. Every test runs
with HOME, CONNECTIONS_HOME, and AUDIT_HOME inside a temporary folder. Run from
the repository root with python3 -m pytest -q connections/tests.
"""
import sys
import zipfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import docx_builder  # noqa: E402
from connections.adapters.docx_text import DocxError, read_docx, side_text  # noqa: E402

AI = "AI Reviewer"
SCHOLAR = "Scholar"


@pytest.fixture(autouse=True)
def homes(tmp_path, monkeypatch):
    user = tmp_path / "user"
    user.mkdir()
    monkeypatch.setenv("HOME", str(user))
    monkeypatch.setenv("CONNECTIONS_HOME", str(tmp_path / "connections_home"))
    monkeypatch.setenv("AUDIT_HOME", str(tmp_path / "audit_home"))
    return tmp_path


def build(tmp_path, paragraphs, comments=()):
    return read_docx(docx_builder.build(tmp_path / "doc.docx", paragraphs, comments))


def span_text(doc, side, span):
    """The text a comment's span covers on one side, across paragraphs."""
    (p0, o0), (p1, o1) = span["start"], span["end"]
    if p0 == p1:
        return doc["paragraphs"][p0][side][o0:o1]
    parts = [doc["paragraphs"][p0][side][o0:]]
    parts += [doc["paragraphs"][p][side] for p in range(p0 + 1, p1)]
    parts.append(doc["paragraphs"][p1][side][:o1])
    return "\n".join(parts)


def test_an_insertion_is_on_the_revised_side_only_with_its_author(tmp_path):
    doc = build(tmp_path, [(None, [("plain", "Volunteers stay "), ("ins", "much ", AI), ("plain", "longer.")])])
    p = doc["paragraphs"][0]
    assert p["baseline"] == "Volunteers stay longer."
    assert p["revised"] == "Volunteers stay much longer."
    assert p["changes"] == [{"author": AI, "side": "revised", "start": 16, "end": 21}]
    assert p["revised"][16:21] == "much "


def test_a_deletion_is_on_the_baseline_side_only_with_its_author(tmp_path):
    doc = build(tmp_path, [(None, [("plain", "Volunteers "), ("del", "often ", SCHOLAR), ("plain", "leave.")])])
    p = doc["paragraphs"][0]
    assert p["baseline"] == "Volunteers often leave."
    assert p["revised"] == "Volunteers leave."
    assert p["changes"] == [{"author": SCHOLAR, "side": "baseline", "start": 11, "end": 17}]
    assert p["baseline"][11:17] == "often "


def test_a_move_sits_at_its_old_place_on_the_baseline_and_its_new_place_on_the_revised_side(tmp_path):
    doc = build(tmp_path, [
        (None, [("plain", "Alpha. "), ("moveFrom", "Beta. ", AI), ("plain", "Gamma.")]),
        (None, [("plain", "Delta."), ("moveTo", " Beta.", AI)]),
    ])
    first, second = doc["paragraphs"]
    assert first["baseline"] == "Alpha. Beta. Gamma."
    assert first["revised"] == "Alpha. Gamma."
    assert second["baseline"] == "Delta."
    assert second["revised"] == "Delta. Beta."
    assert first["changes"] == [{"author": AI, "side": "baseline", "start": 7, "end": 13}]
    assert second["changes"] == [{"author": AI, "side": "revised", "start": 6, "end": 12}]


def test_a_heading_keeps_its_level(tmp_path):
    doc = build(tmp_path, [
        ("Heading 1", [("plain", "Retention")]),
        ("Heading 2", [("plain", "Results")]),
        (None, [("plain", "Most stayed.")]),
    ])
    assert [p["level"] for p in doc["paragraphs"]] == [1, 2, 0]
    assert side_text(doc, "revised") == "# Retention\n\n## Results\n\nMost stayed.\n"


def test_a_paragraph_that_is_all_deleted_is_gone_from_the_revised_side(tmp_path):
    doc = build(tmp_path, [
        (None, [("plain", "Kept.")]),
        (None, [("del", "Dropped entirely.", AI)]),
        (None, [("plain", "Also kept.")]),
    ])
    assert doc["paragraphs"][1]["revised"] == ""
    assert side_text(doc, "revised") == "Kept.\n\nAlso kept.\n"
    assert side_text(doc, "baseline") == "Kept.\n\nDropped entirely.\n\nAlso kept.\n"


def test_a_comments_span_lands_on_its_words_on_both_sides(tmp_path):
    doc = build(
        tmp_path,
        [(None, [("plain", "Retention "), ("del", "fell", AI), ("ins", "rose", AI), ("plain", " after training.")])],
        [(AI, "[edit] The source reports a rise.", (0, 1), (0, 2))],
    )
    comment = doc["comments"][0]
    assert comment["author"] == AI
    assert comment["text"] == "[edit] The source reports a rise."
    assert comment["span"]["baseline"] == {"start": [0, 10], "end": [0, 14]}
    assert comment["span"]["revised"] == {"start": [0, 10], "end": [0, 14]}
    assert span_text(doc, "baseline", comment["span"]["baseline"]) == "fell"
    assert span_text(doc, "revised", comment["span"]["revised"]) == "rose"


def test_a_comment_on_plain_words_covers_the_same_words_on_both_sides(tmp_path):
    doc = build(
        tmp_path,
        [(None, [("plain", "Most volunteers "), ("plain", "stayed a year"), ("ins", " or more", AI), ("plain", ".")])],
        [(SCHOLAR, "Check the year.", (0, 1), (0, 1))],
    )
    span = doc["comments"][0]["span"]
    assert span_text(doc, "baseline", span["baseline"]) == "stayed a year"
    assert span_text(doc, "revised", span["revised"]) == "stayed a year"


def test_a_comment_on_deleted_text_only_covers_nothing_on_the_revised_side(tmp_path):
    doc = build(
        tmp_path,
        [(None, [("plain", "Volunteers "), ("del", "often ", AI), ("plain", "leave.")])],
        [(AI, "[delete] Not in the source.", (0, 1), (0, 1))],
    )
    span = doc["comments"][0]["span"]
    assert span_text(doc, "baseline", span["baseline"]) == "often "
    assert span["revised"]["start"] == span["revised"]["end"]


def test_a_comment_across_two_paragraphs_and_with_two_paragraphs_of_text(tmp_path):
    doc = build(
        tmp_path,
        [(None, [("plain", "One. "), ("plain", "Two.")]), (None, [("plain", "Three."), ("plain", " Four.")])],
        [(AI, "[move] First line.\nSecond line.", (0, 1), (1, 0))],
    )
    comment = doc["comments"][0]
    assert comment["text"] == "[move] First line.\nSecond line."
    assert comment["span"]["revised"] == {"start": [0, 5], "end": [1, 6]}
    assert span_text(doc, "revised", comment["span"]["revised"]) == "Two.\nThree."


def test_a_document_without_tracked_changes_gives_the_same_text_on_both_sides(tmp_path):
    doc = build(tmp_path, [
        ("Heading 1", [("plain", "Introduction")]),
        (None, [("plain", "Volunteers stay when they own their work.")]),
        (None, [("plain", "Coordinators matter too.")]),
    ])
    assert len(doc["paragraphs"]) == 3
    for p in doc["paragraphs"]:
        assert p["baseline"] == p["revised"]
        assert p["changes"] == []
    expected = "# Introduction\n\nVolunteers stay when they own their work.\n\nCoordinators matter too.\n"
    assert side_text(doc, "baseline") == side_text(doc, "revised") == expected
    assert doc["comments"] == []


def test_runs_inside_hyperlinks_count_and_tabs_and_breaks_are_kept(tmp_path):
    doc = build(tmp_path, [(None, [("plain", "See\t"), ("link", "the table"), ("plain", " below.\nNext line.")])])
    p = doc["paragraphs"][0]
    assert p["baseline"] == p["revised"] == "See\tthe table below.\nNext line."


def test_side_text_skips_empty_paragraphs_and_ends_with_one_line_break(tmp_path):
    doc = build(tmp_path, [
        (None, [("plain", "First.")]),
        (None, []),
        (None, [("ins", "Added.", AI)]),
    ])
    assert side_text(doc, "baseline") == "First.\n"
    assert side_text(doc, "revised") == "First.\n\nAdded.\n"


def test_a_file_that_is_not_a_word_document_is_refused_by_name(tmp_path):
    bad = tmp_path / "notes.docx"
    bad.write_text("not a zip", encoding="utf-8")
    with pytest.raises(DocxError) as raised:
        read_docx(bad)
    assert "notes.docx" in str(raised.value)
    empty = tmp_path / "empty.docx"
    with zipfile.ZipFile(str(empty), "w") as package:
        package.writestr("other.xml", "<a/>")
    with pytest.raises(DocxError) as raised:
        read_docx(empty)
    assert "word/document.xml" in str(raised.value)


def test_the_reader_uses_only_the_standard_library():
    text = (ROOT / "connections" / "adapters" / "docx_text.py").read_text(encoding="utf-8")
    assert "import docx" not in text and "from docx" not in text
    assert "subprocess" not in text
