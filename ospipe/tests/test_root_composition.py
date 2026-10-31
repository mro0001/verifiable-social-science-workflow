"""Parent composition check: wire resolve through the root and assert the
root's FROZEN promise end to end, using the children's fixtures."""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ospipe.foundation import MissingKeyError, fixture  # noqa: E402
from ospipe.root import CheckResult, run_check  # noqa: E402

OSPIPE_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture()
def workspace(tmp_path):
    (tmp_path / "manuscript.md").write_text(fixture.SAMPLE_MD, encoding="utf-8")
    (tmp_path / "numbers.yml").write_text(fixture.MANIFEST_YAML, encoding="utf-8")
    tables = tmp_path / "tables"
    tables.mkdir()
    (tables / "widget_summary.md").write_text(fixture.SAMPLE_TABLE, encoding="utf-8")
    return tmp_path


def test_check_resolves_end_to_end(workspace):
    result = run_check(
        workspace / "manuscript.md",
        workspace / "numbers.yml",
        tables_dir=workspace / "tables",
        out_path=workspace / "resolved.md",
    )
    resolved = (workspace / "resolved.md").read_text(encoding="utf-8")
    assert result.wrote == str(workspace / "resolved.md")
    assert "33.5" in resolved
    assert "98.2%" in resolved
    assert "{{num:" not in resolved
    assert "{{table:" not in resolved
    assert "| widget | 33.5 |" in resolved
    assert "{{'literal': 'braces in a fence stay untouched'}}" in resolved


def test_check_fails_listing_all_missing_keys(workspace):
    (workspace / "manuscript.md").write_text(
        fixture.SAMPLE_MD + "\nAlso {{num:not_in_manifest}} and {{table:ghost_table}}.\n",
        encoding="utf-8",
    )
    with pytest.raises(MissingKeyError) as exc:
        run_check(
            workspace / "manuscript.md",
            workspace / "numbers.yml",
            tables_dir=workspace / "tables",
        )
    assert "not_in_manifest" in exc.value.keys
    assert "ghost_table" in exc.value.keys


# The foundation fixture's resolved text as the check path produced it before the
# separation, when lint still ran first. Resolving alone must give the same text.
RESOLVED_FIXTURE = (
    "# Synthetic section\n\nThe widget benchmark reached a sMAPE of 33.5 across 24 cities.\n"
    "Compliance was 98.2% overall (p = 0.050).\n\n| model | sMAPE |\n|---|---|\n"
    "| widget | 33.5 |\n\n```python\nd = {{'literal': 'braces in a fence stay untouched'}}\n```\n"
)


def test_check_result_holds_resolved_and_wrote_only(workspace):
    result = run_check(
        workspace / "manuscript.md",
        workspace / "numbers.yml",
        tables_dir=workspace / "tables",
    )
    assert CheckResult._fields == ("resolved", "wrote")
    assert result.resolved == RESOLVED_FIXTURE
    assert result.wrote is None


def test_typed_number_resolves_with_nothing_reported(workspace):
    (workspace / "manuscript.md").write_text(
        fixture.SAMPLE_MD + "\nThe raw rate was 42.7% in our sample.\n",
        encoding="utf-8",
    )
    result = run_check(
        workspace / "manuscript.md",
        workspace / "numbers.yml",
        tables_dir=workspace / "tables",
    )
    assert result.resolved == RESOLVED_FIXTURE + "\nThe raw rate was 42.7% in our sample.\n"
    cli = subprocess.run(
        [
            sys.executable,
            "-m",
            "ospipe",
            "check",
            "--manuscript",
            str(workspace / "manuscript.md"),
            "--manifest",
            str(workspace / "numbers.yml"),
            "--tables-dir",
            str(workspace / "tables"),
        ],
        capture_output=True,
        text=True,
        cwd=str(OSPIPE_DIR),
    )
    assert cli.returncode == 0
    assert cli.stderr == ""
    assert "42.7%" in cli.stdout


def test_cli_exit_codes_and_streams(workspace):
    ok = subprocess.run(
        [
            sys.executable,
            "-m",
            "ospipe",
            "check",
            "--manuscript",
            str(workspace / "manuscript.md"),
            "--manifest",
            str(workspace / "numbers.yml"),
            "--tables-dir",
            str(workspace / "tables"),
        ],
        capture_output=True,
        text=True,
        cwd=str(OSPIPE_DIR),
    )
    assert ok.returncode == 0
    assert "33.5" in ok.stdout

    (workspace / "manuscript.md").write_text("Missing {{num:nope}}.\n", encoding="utf-8")
    bad = subprocess.run(
        [
            sys.executable,
            "-m",
            "ospipe",
            "check",
            "--manuscript",
            str(workspace / "manuscript.md"),
            "--manifest",
            str(workspace / "numbers.yml"),
        ],
        capture_output=True,
        text=True,
        cwd=str(OSPIPE_DIR),
    )
    assert bad.returncode == 2
    assert "nope" in bad.stderr


def test_cli_builds_slides(workspace):
    slides = workspace / "slides.md"
    slides.write_text("---\ntitle: Widget talk\n---\n\n## Result\n\nsMAPE {{num:widget_smape_real}}.\n",
                      encoding="utf-8")
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "ospipe",
            "build",
            "--manuscript",
            str(slides),
            "--manifest",
            str(workspace / "numbers.yml"),
            "--builds-dir",
            str(workspace / "builds"),
            "--purpose",
            "slides",
            "--to",
            "revealjs",
        ],
        capture_output=True,
        text=True,
        cwd=str(OSPIPE_DIR),
    )
    assert run.returncode == 0, run.stderr
    html = (workspace / "builds" / "v001.html").read_text(encoding="utf-8")
    assert "sMAPE 33.5." in html
