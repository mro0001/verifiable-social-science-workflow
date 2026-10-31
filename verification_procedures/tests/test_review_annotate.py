import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from review.annotate import Annotation, AnnotateResult, annotate, load_annotations  # noqa: E402
from review.annotate import fixture as a_fix  # noqa: E402
from review.returns import extract  # noqa: E402


@pytest.fixture()
def source(tmp_path):
    return a_fix.build_source_docx(tmp_path / "source.docx")


def test_annotate_attaches_comments_and_reports_miss(source, tmp_path):
    out = tmp_path / "annotated.docx"
    result = annotate(source, a_fix.ANNOTATIONS, out)
    assert isinstance(result, AnnotateResult)
    assert result.count == 2
    assert result.misses == ["this text appears nowhere in the document"]
    assert Path(result.out_path).exists()


def test_round_trip_through_returns_extraction(source, tmp_path):
    out = tmp_path / "annotated.docx"
    annotate(source, a_fix.ANNOTATIONS, out, author="Claude")
    bundle = extract(out)
    texts = [c.text for c in bundle.comments]
    assert any(t.startswith("[section-job] ") for t in texts)
    assert any(t.startswith("[grounding] ") for t in texts)
    assert all(c.author == "Claude" for c in bundle.comments)
    assert bundle.deltas == []


def test_input_never_modified(source, tmp_path):
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    annotate(source, a_fix.ANNOTATIONS, tmp_path / "annotated.docx")
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before


def test_load_annotations_yaml(tmp_path):
    spec = tmp_path / "spec.yml"
    spec.write_text(
        "- anchor: alpha\n  text: first note\n  tag: grounding\n"
        "- anchor: beta\n  text: second note\n",
        encoding="utf-8",
    )
    anns = load_annotations(spec)
    assert anns[0] == Annotation("alpha", "first note", "grounding")
    assert anns[1].tag is None


def test_load_annotations_rejects_bad_shapes(tmp_path):
    bad = tmp_path / "bad.yml"
    bad.write_text("- anchor_only: x\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_annotations(bad)
