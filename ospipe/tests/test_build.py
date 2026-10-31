"""Build contract tests: real pandoc runs on tiny synthetic markdown."""
import hashlib
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ospipe.build import BuildError, BuildResult, build, verify_ledger  # noqa: E402
from ospipe.build import fixture  # noqa: E402


def _docx_to_plain(docx_path) -> str:
    proc = subprocess.run(
        ["pandoc", "--from", "docx", "--to", "plain", str(docx_path)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


class TestFirstBuild:
    def test_v001_snapshot_ledger_and_result_shape(self, tmp_path):
        result = build(fixture.RESOLVED_MD, tmp_path, purpose="first synthetic draft")

        assert isinstance(result, BuildResult)
        assert result.version == "v001"
        assert re.fullmatch(r"[0-9a-f]{64}", result.sha256)

        # snapshot is the resolved text byte-exact
        snapshot = Path(result.snapshot_path)
        assert snapshot == tmp_path / "v001.md"
        assert snapshot.read_bytes() == fixture.RESOLVED_MD.encode("utf-8")

        # docx exists and the recorded hash is the on-disk hash
        docx = Path(result.docx_path)
        assert docx == tmp_path / "v001.docx"
        assert hashlib.sha256(docx.read_bytes()).hexdigest() == result.sha256

        # ledger row, contract column order, reviewed starts no, git is '-',
        # and no verification status read when no verification folder is given
        ledger = (tmp_path / "BUILDS.md").read_text(encoding="utf-8")
        assert (
            "| version | date | git | sha256 | purpose | baseline | reviewed | verification | runs |"
            in ledger
        )
        row = [ln for ln in ledger.splitlines() if ln.startswith("| v001 ")][0]
        cells = [c.strip() for c in row.strip()[1:-1].split("|")]
        assert len(cells) == 9
        assert cells[0] == "v001"
        assert cells[2] == "-"
        assert cells[3] == result.sha256
        assert cells[4] == "first synthetic draft"
        assert cells[5] == "-"
        assert cells[6] == "no"
        assert cells[7] == "-"
        assert cells[8] == "-"

        # docx really carries the content
        plain = _docx_to_plain(docx)
        assert "Synthetic Widget Study" in plain
        assert "33.5" in plain

    def test_round_trip_and_sequential_versions(self, tmp_path):
        build(fixture.RESOLVED_MD, tmp_path, purpose="round one")
        # a written row re-reads and re-verifies cleanly
        assert verify_ledger(tmp_path) is None

        second = build(
            fixture.RESOLVED_MD_NEXT,
            tmp_path,
            purpose="round two",
            baseline="v001",
            source_git_hash="abc1234",
        )
        assert second.version == "v002"
        assert verify_ledger(tmp_path) is None
        ledger = (tmp_path / "BUILDS.md").read_text(encoding="utf-8")
        row = [ln for ln in ledger.splitlines() if ln.startswith("| v002 ")][0]
        assert "abc1234" in row
        assert "| v001 |" in row  # baseline column


class TestVersionDiscovery:
    def test_stray_docx_counts_for_numbering_not_verification(self, tmp_path):
        (tmp_path / "v000_submitted.docx").write_bytes(b"hand-dropped external file")
        first = build(fixture.RESOLVED_MD, tmp_path, purpose="after external drop")
        assert first.version == "v001"  # no collision with the v000-style file

        (tmp_path / "v005.docx").write_bytes(b"another stray")
        nxt = build(fixture.RESOLVED_MD_NEXT, tmp_path, purpose="after stray v005")
        assert nxt.version == "v006"

        # unledgered strays are ignored by verification
        assert verify_ledger(tmp_path) is None

    def test_ledgered_v000_external_archive_is_verified_and_tolerated(self, tmp_path):
        payload = b"external submitted artifact"
        (tmp_path / "v000.docx").write_bytes(payload)
        sha = hashlib.sha256(payload).hexdigest()
        header = "| version | date | git | sha256 | purpose | baseline | reviewed |\n"
        sep = "|---|---|---|---|---|---|---|\n"
        (tmp_path / "BUILDS.md").write_text(
            "# Builds\n\n" + header + sep + fixture.external_row("v000", sha),
            encoding="utf-8",
        )
        assert verify_ledger(tmp_path) is None
        result = build(fixture.RESOLVED_MD, tmp_path, purpose="first real build")
        assert result.version == "v001"


class TestVerifyRefusal:
    def test_tampered_docx_refuses_next_build(self, tmp_path):
        first = build(fixture.RESOLVED_MD, tmp_path, purpose="to be tampered")
        with open(first.docx_path, "ab") as fh:
            fh.write(fixture.TAMPER_BYTES)

        with pytest.raises(BuildError, match="v001"):
            verify_ledger(tmp_path)
        with pytest.raises(BuildError, match="sha256 mismatch"):
            build(fixture.RESOLVED_MD_NEXT, tmp_path, purpose="must refuse")
        # the refused build left nothing behind
        assert not (tmp_path / "v002.md").exists()
        assert not (tmp_path / "v002.docx").exists()

    def test_all_problems_reported_in_one_error(self, tmp_path):
        first = build(fixture.RESOLVED_MD, tmp_path, purpose="one")
        second = build(fixture.RESOLVED_MD, tmp_path, purpose="two", baseline="v001")
        build(fixture.RESOLVED_MD, tmp_path, purpose="three", baseline="v002")

        with open(first.docx_path, "ab") as fh:
            fh.write(fixture.TAMPER_BYTES)
        Path(second.docx_path).unlink()

        with pytest.raises(BuildError) as exc:
            verify_ledger(tmp_path)
        message = str(exc.value)
        assert "v001" in message and "mismatch" in message
        assert "v002" in message and "missing" in message
        assert "v003" not in message

    def test_ledgered_row_with_missing_file_blocks_build(self, tmp_path):
        (tmp_path / "BUILDS.md").write_text(fixture.GHOST_LEDGER, encoding="utf-8")
        with pytest.raises(BuildError, match="v007"):
            verify_ledger(tmp_path)
        with pytest.raises(BuildError, match="v007"):
            build(fixture.RESOLVED_MD, tmp_path, purpose="must not build")
        assert not (tmp_path / "v008.docx").exists()


class TestPandoc:
    def test_pandoc_failure_surfaces_stderr_and_burns_nothing(self, tmp_path):
        with pytest.raises(BuildError) as exc:
            build(
                fixture.CITED_MD,
                tmp_path,
                purpose="doomed cited build",
                bibliography=tmp_path / "missing.bib",
            )
        assert "missing.bib" in str(exc.value)
        # no ledger row, no snapshot, no docx, version not burned
        assert not (tmp_path / "BUILDS.md").exists()
        assert not (tmp_path / "v001.md").exists()
        assert not (tmp_path / "v001.docx").exists()
        retry = build(fixture.RESOLVED_MD, tmp_path, purpose="recovery build")
        assert retry.version == "v001"

    def test_citeproc_renders_bibliography(self, tmp_path):
        bib = tmp_path / "refs.bib"
        bib.write_text(fixture.BIB, encoding="utf-8")
        result = build(
            fixture.CITED_MD,
            tmp_path / "builds",
            purpose="cited build",
            bibliography=bib,
        )
        plain = _docx_to_plain(result.docx_path)
        assert "Doe" in plain and "2020" in plain  # in-text citation
        assert "A Fake Study of Widget Counting" in plain  # reference list entry
        assert "Gadget Baselines Reconsidered" in plain


class TestSlides:
    def test_revealjs_build_writes_html_snapshot_and_ledger_row(self, tmp_path):
        result = build(fixture.SLIDES_MD, tmp_path, purpose="first slides", to="revealjs")
        html = Path(result.docx_path)  # the field holds the built file, whatever its format
        assert html == tmp_path / "v001.html"
        assert not (tmp_path / "v001.docx").exists()
        assert hashlib.sha256(html.read_bytes()).hexdigest() == result.sha256
        assert Path(result.snapshot_path).read_bytes() == fixture.SLIDES_MD.encode("utf-8")
        text = html.read_text(encoding="utf-8")
        assert "reveal" in text
        assert "Counting widgets" in text and "33.5" in text
        ledger = (tmp_path / "BUILDS.md").read_text(encoding="utf-8")
        assert "| v001 |" in ledger and result.sha256 in ledger
        assert verify_ledger(tmp_path) is None

    def test_same_text_gives_identical_slides(self, tmp_path):
        first = build(fixture.SLIDES_MD, tmp_path / "a", purpose="one", to="revealjs")
        second = build(fixture.SLIDES_MD, tmp_path / "b", purpose="two", to="revealjs")
        assert first.sha256 == second.sha256

    def test_tampered_html_refuses_next_build(self, tmp_path):
        first = build(fixture.SLIDES_MD, tmp_path, purpose="to be tampered", to="revealjs")
        with open(first.docx_path, "ab") as fh:
            fh.write(fixture.TAMPER_BYTES)
        with pytest.raises(BuildError, match="sha256 mismatch"):
            build(fixture.SLIDES_MD, tmp_path, purpose="must refuse", to="revealjs")
        assert not (tmp_path / "v002.md").exists()
        assert not (tmp_path / "v002.html").exists()

    def test_stray_html_counts_for_numbering(self, tmp_path):
        (tmp_path / "v004.html").write_bytes(b"hand-dropped slides")
        result = build(fixture.SLIDES_MD, tmp_path, purpose="after stray", to="revealjs")
        assert result.version == "v005"
        assert verify_ledger(tmp_path) is None

    def test_unknown_format_and_reference_doc_with_slides_refused(self, tmp_path):
        with pytest.raises(BuildError, match="unknown output format"):
            build(fixture.SLIDES_MD, tmp_path, purpose="bad format", to="pdf")
        with pytest.raises(BuildError, match="only to docx"):
            build(
                fixture.SLIDES_MD,
                tmp_path,
                purpose="bad option",
                to="revealjs",
                reference_docx=tmp_path / "ref.docx",
            )
        assert list(tmp_path.iterdir()) == []


class TestPage:
    def test_html_build_writes_page_snapshot_and_ledger_row(self, tmp_path):
        result = build(fixture.PAGE_MD, tmp_path, purpose="first page", to="html")
        page = Path(result.docx_path)  # the field holds the built file, whatever its format
        assert page == tmp_path / "v001.html"
        assert not (tmp_path / "v001.docx").exists()
        assert hashlib.sha256(page.read_bytes()).hexdigest() == result.sha256
        assert Path(result.snapshot_path) == tmp_path / "v001.md"
        assert Path(result.snapshot_path).read_bytes() == fixture.PAGE_MD.encode("utf-8")
        text = page.read_text(encoding="utf-8")
        assert "<title>Synthetic Widget Page</title>" in text
        assert "Counting widgets" in text and "33.5" in text
        assert "What changed" in text and "98.2%" in text
        assert "Reveal.initialize" not in text  # a plain web page, not slides
        ledger = (tmp_path / "BUILDS.md").read_text(encoding="utf-8")
        row = [ln for ln in ledger.splitlines() if ln.startswith("| v001 ")][0]
        assert result.sha256 in row and "first page" in row

    def test_same_text_gives_identical_pages(self, tmp_path):
        first = build(fixture.PAGE_MD, tmp_path / "a", purpose="one", to="html")
        second = build(fixture.PAGE_MD, tmp_path / "b", purpose="two", to="html")
        assert first.sha256 == second.sha256

    def test_tampered_page_refuses_next_build(self, tmp_path):
        first = build(fixture.PAGE_MD, tmp_path, purpose="to be tampered", to="html")
        with open(first.docx_path, "ab") as fh:
            fh.write(fixture.TAMPER_BYTES)
        with pytest.raises(BuildError, match="sha256 mismatch"):
            build(fixture.PAGE_MD, tmp_path, purpose="must refuse", to="html")
        assert not (tmp_path / "v002.md").exists()
        assert not (tmp_path / "v002.html").exists()

    def test_reference_doc_with_page_refused_before_writing(self, tmp_path):
        with pytest.raises(BuildError, match="only to docx"):
            build(
                fixture.PAGE_MD,
                tmp_path,
                purpose="bad option",
                to="html",
                reference_docx=tmp_path / "ref.docx",
            )
        assert list(tmp_path.iterdir()) == []

    def test_ledgered_page_verifies_once_for_the_shared_extension(self, tmp_path):
        build(fixture.PAGE_MD, tmp_path, purpose="page", to="html")
        assert verify_ledger(tmp_path) is None
        second = build(fixture.PAGE_MD, tmp_path, purpose="page again", to="html")
        assert second.version == "v002"
        assert verify_ledger(tmp_path) is None

    def test_page_beside_docx_for_one_version_still_refused(self, tmp_path):
        build(fixture.PAGE_MD, tmp_path, purpose="page", to="html")
        (tmp_path / "v001.docx").write_bytes(b"hand-dropped word file")
        with pytest.raises(BuildError) as exc:
            verify_ledger(tmp_path)
        message = str(exc.value)
        assert "v001.docx and v001.html" in message
        assert message.count("v001.html") == 1

    def test_cli_builds_a_page_from_the_root_fixture(self, tmp_path):
        from ospipe.foundation import fixture as root_fixture

        (tmp_path / "manuscript.md").write_text(root_fixture.SAMPLE_MD, encoding="utf-8")
        (tmp_path / "numbers.yml").write_text(root_fixture.MANIFEST_YAML, encoding="utf-8")
        tables = tmp_path / "tables"
        tables.mkdir()
        (tables / "widget_summary.md").write_text(root_fixture.SAMPLE_TABLE, encoding="utf-8")
        run = subprocess.run(
            [
                sys.executable,
                "-m",
                "ospipe",
                "build",
                "--manuscript",
                str(tmp_path / "manuscript.md"),
                "--manifest",
                str(tmp_path / "numbers.yml"),
                "--tables-dir",
                str(tables),
                "--builds-dir",
                str(tmp_path / "builds"),
                "--purpose",
                "page",
                "--to",
                "html",
            ],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).resolve().parents[1]),
        )
        assert run.returncode == 0, run.stderr
        page = (tmp_path / "builds" / "v001.html").read_text(encoding="utf-8")
        assert "33.5" in page
        assert "Reveal.initialize" not in page
