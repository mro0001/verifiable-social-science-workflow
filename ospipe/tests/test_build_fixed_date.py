"""Fixed-date builds and the rebuild command. Real pandoc runs on the build fixture's
synthetic text, with SOURCE_DATE_EPOCH set by the test."""
import hashlib
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ospipe.build import (  # noqa: E402
    BuildError,
    RebuildResult,
    build,
    read_ledger,
    rebuild,
    verify_ledger,
)
from ospipe.build import fixture  # noqa: E402
from ospipe.foundation import fixture as root_fixture  # noqa: E402

OSPIPE_DIR = Path(__file__).resolve().parents[1]
NEW_YEAR = "1767225600"  # 2026-01-01T00:00:00Z
NEW_YEAR_AFTERNOON = "1767276000"  # 2026-01-01T14:00:00Z
SPRING = "1772323200"  # 2026-03-01T00:00:00Z


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _row(builds_dir, version):
    return [r for r in read_ledger(builds_dir) if r["version"] == version][0]


def _snapshot(folder):
    """The listing and checksum of every file under folder."""
    return {
        p.relative_to(folder).as_posix(): _sha(p)
        for p in sorted(Path(folder).rglob("*"))
        if p.is_file()
    }


def _fake_pandoc(tmp_path):
    """A stand-in pandoc that writes the environment it was given to its --output file."""
    script = tmp_path / "fake_pandoc"
    script.write_text(
        "#!{0}\n"
        "import json, os, sys\n"
        "out = sys.argv[sys.argv.index('--output') + 1]\n"
        "open(out, 'w').write(json.dumps(dict(os.environ), sort_keys=True))\n".format(sys.executable),
        encoding="utf-8",
    )
    script.chmod(0o755)
    return str(script)


class TestFixedDate:
    def test_same_text_in_two_folders_gives_one_word_checksum(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SOURCE_DATE_EPOCH", NEW_YEAR)
        first = build(fixture.RESOLVED_MD, tmp_path / "a", purpose="one")
        second = build(fixture.RESOLVED_MD, tmp_path / "b", purpose="two")
        assert first.sha256 == second.sha256

    def test_row_date_is_the_epoch_date(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SOURCE_DATE_EPOCH", NEW_YEAR)
        build(fixture.RESOLVED_MD, tmp_path, purpose="new year")
        assert _row(tmp_path, "v001")["date"] == "2026-01-01"

    def test_epoch_within_a_day_builds_at_that_day_midnight(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SOURCE_DATE_EPOCH", NEW_YEAR)
        midnight = build(fixture.RESOLVED_MD, tmp_path / "a", purpose="midnight")
        monkeypatch.setenv("SOURCE_DATE_EPOCH", NEW_YEAR_AFTERNOON)
        afternoon = build(fixture.RESOLVED_MD, tmp_path / "b", purpose="afternoon")
        assert afternoon.sha256 == midnight.sha256
        assert _row(tmp_path / "b", "v001")["date"] == "2026-01-01"

    def test_pandoc_gets_the_midnight_epoch_and_the_rest_of_the_environment(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("SOURCE_DATE_EPOCH", NEW_YEAR_AFTERNOON)
        monkeypatch.setenv("OSPIPE_TEST_MARK", "passed through")
        result = build(
            fixture.RESOLVED_MD, tmp_path / "builds", purpose="env", pandoc=_fake_pandoc(tmp_path)
        )
        seen = json.loads(Path(result.docx_path).read_text(encoding="utf-8"))
        assert seen["SOURCE_DATE_EPOCH"] == NEW_YEAR
        assert seen["OSPIPE_TEST_MARK"] == "passed through"
        assert os.environ["SOURCE_DATE_EPOCH"] == NEW_YEAR_AFTERNOON

    def test_without_an_epoch_the_date_is_today(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SOURCE_DATE_EPOCH", raising=False)
        before = date.today().isoformat()
        result = build(
            fixture.RESOLVED_MD, tmp_path / "builds", purpose="today", pandoc=_fake_pandoc(tmp_path)
        )
        after = date.today().isoformat()
        row_date = _row(tmp_path / "builds", "v001")["date"]
        assert row_date in (before, after)
        seen = json.loads(Path(result.docx_path).read_text(encoding="utf-8"))
        expected = (date.fromisoformat(row_date) - date(1970, 1, 1)).days * 86400
        assert seen["SOURCE_DATE_EPOCH"] == str(expected)

    def test_an_epoch_that_is_not_a_number_is_refused_before_writing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SOURCE_DATE_EPOCH", "next tuesday")
        with pytest.raises(BuildError, match="SOURCE_DATE_EPOCH"):
            build(fixture.RESOLVED_MD, tmp_path, purpose="bad epoch")
        assert list(tmp_path.iterdir()) == []


class TestReadLedger:
    def test_reads_old_and_new_rows_alike(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SOURCE_DATE_EPOCH", NEW_YEAR)
        (tmp_path / "v000.docx").write_bytes(b"external archive")
        (tmp_path / "BUILDS.md").write_text(
            "# Builds\n\n"
            "| version | date | git | sha256 | purpose | baseline | reviewed |\n"
            "|---|---|---|---|---|---|---|\n"
            + fixture.external_row("v000", _sha(tmp_path / "v000.docx")),
            encoding="utf-8",
        )
        result = build(fixture.RESOLVED_MD, tmp_path, purpose="after the old row")
        rows = read_ledger(tmp_path)
        assert [r["version"] for r in rows] == ["v000", "v001"]
        assert rows[0]["date"] == "2026-01-01"
        assert rows[0]["purpose"] == "externally archived submitted docx"
        assert "verification" not in rows[0]
        assert rows[1]["sha256"] == result.sha256
        assert rows[1]["verification"] == "-"
        assert rows[1]["reviewed"] == "no"

    def test_no_ledger_gives_no_rows(self, tmp_path):
        assert read_ledger(tmp_path) == []


class TestRebuild:
    def test_word_build_rebuilds_to_a_match(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SOURCE_DATE_EPOCH", NEW_YEAR)
        bib = tmp_path / "refs.bib"
        bib.write_text(fixture.BIB, encoding="utf-8")
        builds = tmp_path / "builds"
        built = build(fixture.CITED_MD, builds, purpose="cited", bibliography=bib)
        result = rebuild(builds, "v001", bibliography=bib)
        assert isinstance(result, RebuildResult)
        assert result.match is True
        assert result.ledger_sha256 == built.sha256
        assert result.rebuilt_sha256 == built.sha256
        assert result.text_matches is None

    def test_rebuild_uses_the_row_date_not_the_environment(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SOURCE_DATE_EPOCH", NEW_YEAR)
        build(fixture.RESOLVED_MD, tmp_path, purpose="new year")
        monkeypatch.setenv("SOURCE_DATE_EPOCH", SPRING)
        assert rebuild(tmp_path, "v001").match is True
        monkeypatch.delenv("SOURCE_DATE_EPOCH")
        assert rebuild(tmp_path, "v001").match is True

    def test_slides_build_rebuilds_to_a_match(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SOURCE_DATE_EPOCH", NEW_YEAR)
        build(fixture.SLIDES_MD, tmp_path, purpose="slides", to="revealjs")
        result = rebuild(tmp_path, "v001", to="revealjs")
        assert result.match is True

    def test_page_build_rebuilds_to_a_match(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SOURCE_DATE_EPOCH", NEW_YEAR)
        untitled = "Text with no title block, so the page takes the file name as its title.\n"
        build(untitled, tmp_path, purpose="page", to="html")
        assert "<title>v001</title>" in (tmp_path / "v001.html").read_text(encoding="utf-8")
        result = rebuild(tmp_path, "v001", to="html")
        assert result.match is True

    def test_hand_changed_checksum_is_a_mismatch(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SOURCE_DATE_EPOCH", NEW_YEAR)
        built = build(fixture.RESOLVED_MD, tmp_path, purpose="to be edited")
        ledger = tmp_path / "BUILDS.md"
        ledger.write_text(
            ledger.read_text(encoding="utf-8").replace(built.sha256, fixture.FAKE_SHA256),
            encoding="utf-8",
        )
        result = rebuild(tmp_path, "v001")
        assert result.match is False
        assert result.ledger_sha256 == fixture.FAKE_SHA256
        assert result.rebuilt_sha256 == built.sha256

    def test_changed_source_text_differs(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SOURCE_DATE_EPOCH", NEW_YEAR)
        build(fixture.RESOLVED_MD, tmp_path, purpose="first")
        same = rebuild(tmp_path, "v001", resolved_md=fixture.RESOLVED_MD)
        assert same.text_matches is True and same.match is True
        changed = rebuild(tmp_path, "v001", resolved_md=fixture.RESOLVED_MD_NEXT)
        assert changed.text_matches is False
        assert changed.match is True

    def test_unknown_version_raises(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SOURCE_DATE_EPOCH", NEW_YEAR)
        build(fixture.RESOLVED_MD, tmp_path, purpose="only one")
        with pytest.raises(BuildError, match="v009"):
            rebuild(tmp_path, "v009")

    def test_builds_dir_is_left_as_it_was(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SOURCE_DATE_EPOCH", NEW_YEAR)
        build(fixture.RESOLVED_MD, tmp_path / "builds", purpose="first")
        build(fixture.SLIDES_MD, tmp_path / "slides", purpose="first", to="revealjs")
        before = (_snapshot(tmp_path / "builds"), _snapshot(tmp_path / "slides"))
        rebuild(tmp_path / "builds", "v001")
        rebuild(tmp_path / "builds", "v001", resolved_md=fixture.RESOLVED_MD_NEXT)
        rebuild(tmp_path / "slides", "v001", to="revealjs")
        with pytest.raises(BuildError):
            rebuild(tmp_path / "builds", "v002")
        after = (_snapshot(tmp_path / "builds"), _snapshot(tmp_path / "slides"))
        assert after == before
        assert verify_ledger(tmp_path / "builds") is None

    def test_unknown_format_and_reference_doc_with_slides_refused(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SOURCE_DATE_EPOCH", NEW_YEAR)
        build(fixture.SLIDES_MD, tmp_path, purpose="slides", to="revealjs")
        with pytest.raises(BuildError, match="unknown output format"):
            rebuild(tmp_path, "v001", to="pdf")
        with pytest.raises(BuildError, match="only to docx"):
            rebuild(tmp_path, "v001", to="revealjs", reference_docx=tmp_path / "ref.docx")


@pytest.fixture()
def workspace(tmp_path):
    (tmp_path / "manuscript.md").write_text(root_fixture.SAMPLE_MD, encoding="utf-8")
    (tmp_path / "numbers.yml").write_text(root_fixture.MANIFEST_YAML, encoding="utf-8")
    tables = tmp_path / "tables"
    tables.mkdir()
    (tables / "widget_summary.md").write_text(root_fixture.SAMPLE_TABLE, encoding="utf-8")
    return tmp_path


def _ospipe(args, epoch=NEW_YEAR):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(OSPIPE_DIR)
    if epoch is None:
        env.pop("SOURCE_DATE_EPOCH", None)
    else:
        env["SOURCE_DATE_EPOCH"] = epoch
    return subprocess.run(
        [sys.executable, "-m", "ospipe"] + list(args),
        capture_output=True,
        text=True,
        cwd=str(OSPIPE_DIR),
        env=env,
    )


def _source_args(ws):
    return [
        "--manuscript", str(ws / "manuscript.md"),
        "--manifest", str(ws / "numbers.yml"),
        "--tables-dir", str(ws / "tables"),
    ]


class TestRebuildCommand:
    def _build(self, ws, to="docx"):
        run = _ospipe(
            ["build"] + _source_args(ws)
            + ["--builds-dir", str(ws / "builds"), "--purpose", "first", "--to", to]
        )
        assert run.returncode == 0, run.stderr
        return _row(ws / "builds", "v001")["sha256"]

    def test_match_prints_the_version_and_checksum(self, workspace):
        sha = self._build(workspace)
        run = _ospipe(
            ["rebuild"] + _source_args(workspace)
            + ["--builds-dir", str(workspace / "builds"), "--version", "v001"],
            epoch=SPRING,
        )
        assert run.returncode == 0, run.stderr
        assert run.stdout.strip() == "match v001 sha256 {0}".format(sha[:12])

    def test_slides_match(self, workspace):
        sha = self._build(workspace, to="revealjs")
        run = _ospipe(
            ["rebuild"] + _source_args(workspace)
            + ["--builds-dir", str(workspace / "builds"), "--version", "v001", "--to", "revealjs"],
            epoch=None,
        )
        assert run.returncode == 0, run.stderr
        assert run.stdout.strip() == "match v001 sha256 {0}".format(sha[:12])

    def test_changed_source_prints_text_differs(self, workspace):
        self._build(workspace)
        source = workspace / "manuscript.md"
        source.write_text(source.read_text(encoding="utf-8") + "\nA new closing line.\n", encoding="utf-8")
        run = _ospipe(
            ["rebuild"] + _source_args(workspace)
            + ["--builds-dir", str(workspace / "builds"), "--version", "v001"]
        )
        assert run.returncode == 1
        assert run.stdout.strip() == "text differs from v001"

    def test_changed_checksum_prints_mismatch_with_both(self, workspace):
        sha = self._build(workspace)
        ledger = workspace / "builds" / "BUILDS.md"
        ledger.write_text(
            ledger.read_text(encoding="utf-8").replace(sha, fixture.FAKE_SHA256), encoding="utf-8"
        )
        run = _ospipe(
            ["rebuild"] + _source_args(workspace)
            + ["--builds-dir", str(workspace / "builds"), "--version", "v001"]
        )
        assert run.returncode == 1
        line = run.stdout.strip()
        assert line.startswith("mismatch v001")
        assert fixture.FAKE_SHA256 in line and sha in line

    def test_unknown_version_exits_3(self, workspace):
        self._build(workspace)
        run = _ospipe(
            ["rebuild"] + _source_args(workspace)
            + ["--builds-dir", str(workspace / "builds"), "--version", "v004"]
        )
        assert run.returncode == 3
        assert "v004" in run.stderr

    def test_unresolved_source_exits_2(self, workspace):
        self._build(workspace)
        source = workspace / "manuscript.md"
        source.write_text(source.read_text(encoding="utf-8") + "\n{{num:ghost}}\n", encoding="utf-8")
        run = _ospipe(
            ["rebuild"] + _source_args(workspace)
            + ["--builds-dir", str(workspace / "builds"), "--version", "v001"]
        )
        assert run.returncode == 2
        assert "ghost" in run.stderr
