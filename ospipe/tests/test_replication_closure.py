"""What a research product depends on. A temporary copy of the sample project with a
build file written by add_product."""
import hashlib
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ospipe.layout import add_product, read_map  # noqa: E402
from ospipe.replication import Closure, ReplicationError, closure  # noqa: E402
from ospipe.replication import fixture  # noqa: E402

OSPIPE_DIR = Path(__file__).resolve().parents[1]
SAMPLE_PROJECT = OSPIPE_DIR.parent / "examples" / "sample_project"


def _checksums(folder):
    return {
        p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(Path(folder).rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    }


@pytest.fixture(scope="module")
def sample_before():
    return _checksums(SAMPLE_PROJECT)


@pytest.fixture()
def project(tmp_path, sample_before):
    folder = tmp_path / "project"
    shutil.copytree(str(SAMPLE_PROJECT), str(folder))
    makefile = folder / "Makefile"
    add_product(makefile, "manuscript", "manuscript.md", bib="refs.bib", tables_dir=".")
    add_product(makefile, "slides", "slides.md", to="revealjs", tables_dir=".")
    yield folder
    assert _checksums(SAMPLE_PROJECT) == sample_before


def _map(project):
    return read_map(project / "Makefile")


def test_manuscript_closure_is_exactly_the_sample_files(project):
    result = closure(_map(project), "manuscript")
    assert isinstance(result, Closure)
    assert result.files == list(fixture.MANUSCRIPT_CLOSURE)


def test_slides_closure_swaps_the_source_and_drops_the_bibliography(project):
    result = closure(_map(project), "slides")
    assert result.files == list(fixture.SLIDES_CLOSURE)
    assert "refs.bib" not in result.files
    assert "manuscript.md" not in result.files


def test_files_are_sorted_relative_and_unique(project):
    files = closure(_map(project), "manuscript").files
    assert files == sorted(set(files))
    assert all(not Path(f).is_absolute() and not f.startswith("..") for f in files)


def test_notes_name_the_absent_results_files_and_records(project):
    notes = closure(_map(project), "manuscript").notes
    for stream in ("prose", "citations", "data", "build"):
        assert any("verification/{0}.json".format(stream) in note for note in notes)
    for record in fixture.AUDIT_RECORDS:
        assert any(record in note for note in notes)
    assert not any("pipeline.yaml" in note for note in notes)


def test_verification_folder_and_citation_log_add_their_files(project):
    verification = project / "verification"
    verification.mkdir()
    for stream in ("citations", "data"):
        (verification / (stream + ".json")).write_text(fixture.RESULTS_STUB, encoding="utf-8")
    audit = project / "audit"
    audit.mkdir()
    for record in fixture.AUDIT_RECORDS:
        (project / record).write_text(fixture.RECORD_STUB, encoding="utf-8")
    result = closure(_map(project), "manuscript")
    expected = sorted(
        list(fixture.MANUSCRIPT_CLOSURE)
        + ["verification/citations.json", "verification/data.json"]
        + list(fixture.AUDIT_RECORDS)
    )
    assert result.files == expected
    assert any("verification/prose.json" in note for note in result.notes)
    assert not any("verification/citations.json" in note for note in result.notes)
    assert not any("audit/" in note for note in result.notes)


def test_named_verification_folder_is_the_one_read(project):
    makefile = project / "Makefile"
    text = makefile.read_text(encoding="utf-8")
    makefile.write_text(
        text.replace("--builds-dir builds/manuscript", "--verification-dir checks --builds-dir builds/manuscript"),
        encoding="utf-8",
    )
    (project / "checks").mkdir()
    (project / "checks" / "prose.json").write_text(fixture.RESULTS_STUB, encoding="utf-8")
    result = closure(_map(project), "manuscript")
    assert "checks/prose.json" in result.files


def test_local_images_are_shipped_and_remote_ones_are_not(project):
    (project / "figs").mkdir()
    (project / "figs" / "plot.png").write_bytes(b"fake png")
    source = project / "manuscript.md"
    source.write_text(source.read_text(encoding="utf-8") + fixture.IMAGE_LINES, encoding="utf-8")
    files = closure(_map(project), "manuscript").files
    assert "figs/plot.png" in files
    assert not any("example.org" in f for f in files)
    assert not any("fenced.png" in f for f in files)


def test_every_problem_is_reported_together(project, tmp_path):
    (tmp_path / "outside.png").write_bytes(b"fake png outside the project")
    source = project / "manuscript.md"
    source.write_text(source.read_text(encoding="utf-8") + fixture.BAD_LINES, encoding="utf-8")
    with pytest.raises(ReplicationError) as caught:
        closure(_map(project), "manuscript")
    problems = caught.value.problems
    assert len(problems) == 3, problems
    assert any("ghost_table.md" in p for p in problems)
    assert any("../outside.png" in p and "leaves the project folder" in p for p in problems)
    assert any("/Users/someone/plot.png" in p and "absolute" in p for p in problems)


def test_missing_pipeline_file_is_reported(project):
    (project / "params_io.py").unlink()
    (project / "next_word_results.json").unlink()
    with pytest.raises(ReplicationError) as caught:
        closure(_map(project), "manuscript")
    problems = caught.value.problems
    assert any("params_io.py" in p for p in problems)
    assert any("next_word_results.json" in p for p in problems)


def test_a_script_holding_an_absolute_path_is_shipped(project):
    script = project / "s1_results.py"
    script.write_text(
        script.read_text(encoding="utf-8") + '\nELSEWHERE = "/Users/someone/data.csv"\n', encoding="utf-8"
    )
    assert "s1_results.py" in closure(_map(project), "manuscript").files


def test_without_pipeline_the_notes_say_the_analysis_is_not_shipped(project):
    (project / "pipeline.yaml").unlink()
    result = closure(_map(project), "manuscript")
    assert "no pipeline.yaml, so the analysis is not shipped" in result.notes
    assert result.files == ["manuscript.md", "numbers.yml", "refs.bib", "top_words.md"]


def test_without_params_and_acquisition_the_notes_say_so(project):
    (project / "params.yaml").unlink()
    (project / "acquisition.yaml").unlink()
    result = closure(_map(project), "manuscript")
    assert "params.yaml" not in result.files
    assert "acquisition.yaml" not in result.files
    assert any(note.startswith("no params.yaml") for note in result.notes)
    assert any(note.startswith("no acquisition.yaml") for note in result.notes)
    assert "next_word_counts.json" in result.files  # still a step input


def test_overlay_and_style_files_named_by_the_rule_are_shipped(project):
    (project / "overlay.yml").write_text("extra: 1\n", encoding="utf-8")
    (project / "style").mkdir()
    (project / "style" / "apa.csl").write_text("<style/>\n", encoding="utf-8")
    (project / "style" / "ref.docx").write_bytes(b"fake reference doc")
    makefile = project / "Makefile"
    makefile.write_text(
        makefile.read_text(encoding="utf-8").replace(
            "--bib refs.bib",
            "--overlay overlay.yml --bib refs.bib --csl style/apa.csl --reference-doc style/ref.docx",
        ),
        encoding="utf-8",
    )
    files = closure(_map(project), "manuscript").files
    for name in ("overlay.yml", "style/apa.csl", "style/ref.docx"):
        assert name in files


def test_unknown_product_is_refused(project):
    with pytest.raises(ReplicationError) as caught:
        closure(_map(project), "poster")
    assert any("poster" in p for p in caught.value.problems)


def test_table_without_a_tables_dir_is_refused(project):
    makefile = project / "Makefile"
    makefile.write_text(
        makefile.read_text(encoding="utf-8").replace("--tables-dir . --to revealjs", "--to revealjs"),
        encoding="utf-8",
    )
    with pytest.raises(ReplicationError) as caught:
        closure(_map(project), "slides")
    assert any("top_words" in p and "--tables-dir" in p for p in caught.value.problems)
