"""ospipe holds only the pipeline's modules.

The command line has only the pipeline's commands, and the package runs its check and
build with the modules that moved to other layers taken out.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ospipe.foundation import fixture  # noqa: E402

OSPIPE_DIR = Path(__file__).resolve().parents[1]
PACKAGE_DIR = OSPIPE_DIR / "ospipe"
MOVED = ("kb", "lint", "annotate", "returns", "reconcile")


@pytest.fixture()
def workspace(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "manuscript.md").write_text(fixture.SAMPLE_MD, encoding="utf-8")
    (work / "numbers.yml").write_text(fixture.MANIFEST_YAML, encoding="utf-8")
    tables = work / "tables"
    tables.mkdir()
    (tables / "widget_summary.md").write_text(fixture.SAMPLE_TABLE, encoding="utf-8")
    (work / "slides.md").write_text(
        "---\ntitle: Widget talk\n---\n\n## Result\n\nsMAPE {{num:widget_smape_real}}.\n",
        encoding="utf-8",
    )
    return work


def _ospipe(args, cwd, env=None):
    return subprocess.run(
        [sys.executable, "-m", "ospipe"] + list(args),
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=env,
    )


def test_returns_is_no_longer_a_command(tmp_path):
    run = _ospipe(["returns", str(tmp_path / "x.docx")], OSPIPE_DIR)
    assert run.returncode == 2
    assert "usage: ospipe" in run.stderr
    assert "invalid choice: 'returns'" in run.stderr


def test_allowlist_is_no_longer_an_option(workspace):
    (workspace / "a.txt").write_text("42.7\n", encoding="utf-8")
    run = _ospipe(
        [
            "check",
            "--manuscript",
            str(workspace / "manuscript.md"),
            "--manifest",
            str(workspace / "numbers.yml"),
            "--allowlist",
            str(workspace / "a.txt"),
        ],
        OSPIPE_DIR,
    )
    assert run.returncode == 2
    assert "usage: ospipe" in run.stderr
    assert "unrecognized arguments: --allowlist" in run.stderr


def test_package_runs_without_the_moved_modules(tmp_path, workspace):
    holder = tmp_path / "holder"
    holder.mkdir()
    copy = holder / "ospipe"
    shutil.copytree(
        str(PACKAGE_DIR),
        str(copy),
        ignore=shutil.ignore_patterns("__pycache__", *MOVED),
    )
    for name in MOVED:
        assert not (copy / name).exists()

    env = dict(os.environ)
    env["PYTHONPATH"] = str(holder)

    check = _ospipe(
        [
            "check",
            "--manuscript",
            str(workspace / "manuscript.md"),
            "--manifest",
            str(workspace / "numbers.yml"),
            "--tables-dir",
            str(workspace / "tables"),
        ],
        holder,
        env,
    )
    assert check.returncode == 0, check.stderr
    assert "33.5" in check.stdout

    build = _ospipe(
        [
            "build",
            "--manuscript",
            str(workspace / "slides.md"),
            "--manifest",
            str(workspace / "numbers.yml"),
            "--builds-dir",
            str(workspace / "builds"),
            "--purpose",
            "slides",
            "--to",
            "revealjs",
        ],
        holder,
        env,
    )
    assert build.returncode == 0, build.stderr
    assert (workspace / "builds" / "v001.html").is_file()
    html = (workspace / "builds" / "v001.html").read_text(encoding="utf-8")
    assert "sMAPE 33.5." in html
