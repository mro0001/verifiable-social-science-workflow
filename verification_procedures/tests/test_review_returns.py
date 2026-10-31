import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from review.returns import Comment, Delta, ReturnBundle, extract  # noqa: E402
from review.returns import fixture  # noqa: E402


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def reviewed_docx(tmp_path_factory):
    return fixture.build_reviewed_docx(tmp_path_factory.mktemp("returns") / "reviewed.docx")


@pytest.fixture(scope="module")
def clean_docx(tmp_path_factory):
    return fixture.build_clean_docx(tmp_path_factory.mktemp("returns_clean") / "clean.docx")


@pytest.fixture(scope="module")
def bundle(reviewed_docx):
    return extract(reviewed_docx)


class TestFixtureExtraction:
    def test_exactly_the_planted_deltas(self, bundle):
        assert isinstance(bundle, ReturnBundle)
        assert len(bundle.deltas) == 2
        assert all(isinstance(d, Delta) for d in bundle.deltas)
        assert sorted(d.kind for d in bundle.deltas) == ["deletion", "insertion"]

    def test_insertion_text_author_date(self, bundle):
        (ins,) = [d for d in bundle.deltas if d.kind == "insertion"]
        assert ins.text == fixture.INSERTION_TEXT
        assert ins.author == fixture.INSERTION_AUTHOR
        assert ins.date == fixture.REVISION_DATE

    def test_deletion_text_author_date(self, bundle):
        (dele,) = [d for d in bundle.deltas if d.kind == "deletion"]
        assert dele.text == fixture.DELETION_TEXT
        assert dele.author == fixture.DELETION_AUTHOR
        assert dele.date == fixture.REVISION_DATE

    def test_touches_number_true_for_numeric_edit(self, bundle):
        (ins,) = [d for d in bundle.deltas if d.kind == "insertion"]
        assert ins.touches_number is True

    def test_touches_number_false_for_prose_edit(self, bundle):
        (dele,) = [d for d in bundle.deltas if d.kind == "deletion"]
        assert dele.touches_number is False

    def test_margin_comment(self, bundle):
        assert bundle.comments == [
            Comment(author=fixture.COMMENT_AUTHOR, text=fixture.COMMENT_TEXT)
        ]


class TestMarkdownOutputs:
    def test_tracked_markdown_carries_revision_spans(self, bundle):
        assert "{.insertion" in bundle.tracked_markdown.replace("{ .insertion", "{.insertion")
        assert ".deletion" in bundle.tracked_markdown
        assert fixture.INSERTION_TEXT in bundle.tracked_markdown

    def test_accepted_markdown_applies_the_edits(self, bundle):
        assert fixture.INSERTION_TEXT in bundle.accepted_markdown
        assert fixture.DELETION_TEXT not in bundle.accepted_markdown
        assert ".insertion" not in bundle.accepted_markdown
        assert ".deletion" not in bundle.accepted_markdown


class TestReadOnly:
    def test_extract_never_modifies_the_input(self, reviewed_docx):
        before = _sha256(reviewed_docx)
        extract(reviewed_docx)
        assert _sha256(reviewed_docx) == before

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            extract(tmp_path / "nope.docx")

    def test_pandoc_is_keyword_only(self, reviewed_docx):
        with pytest.raises(TypeError):
            extract(reviewed_docx, "pandoc")  # type: ignore[misc]


class TestNoRevisions:
    def test_clean_docx_yields_empty_deltas(self, clean_docx):
        bundle = extract(clean_docx)
        assert bundle.deltas == []
        assert bundle.comments == []
        assert bundle.tracked_markdown == bundle.accepted_markdown
