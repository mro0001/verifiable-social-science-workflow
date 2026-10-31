"""Installing the notes templates. Temporary projects, and the repository's own
`templates/notes/`, read only."""
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ospipe.notes_templates import InstallResult, NotesTemplatesError, install_notes  # noqa: E402

OSPIPE_DIR = Path(__file__).resolve().parents[1]
TEMPLATES = OSPIPE_DIR.parent / "templates" / "notes"


def _checksums(folder):
    return {
        path.relative_to(folder).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(Path(folder).rglob("*"))
        if path.is_file()
    }


def _template_names():
    return sorted(path.name for path in TEMPLATES.glob("*.md"))


@pytest.fixture(scope="module", autouse=True)
def templates_unchanged():
    before = _checksums(TEMPLATES)
    yield
    assert _checksums(TEMPLATES) == before


@pytest.fixture()
def project(tmp_path):
    folder = tmp_path / "project"
    folder.mkdir()
    (folder / "manuscript.md").write_text("# Fake paper\n", encoding="utf-8")
    return folder


def _cli(args, cwd, pythonpath=OSPIPE_DIR):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(pythonpath)
    return subprocess.run(
        [sys.executable, "-m", "ospipe", "install-notes"] + list(args),
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=env,
    )


def test_the_templates_folder_holds_templates():
    assert _template_names()


def test_a_new_project_gets_every_template_byte_for_byte(project):
    result = install_notes(project)
    assert isinstance(result, InstallResult)
    names = _template_names()
    assert sorted(Path(p).name for p in result.written) == names
    assert result.skipped == []
    notes = project / "notes"
    assert sorted(path.name for path in notes.iterdir()) == names
    for name in names:
        assert (notes / name).read_bytes() == (TEMPLATES / name).read_bytes()


def test_a_second_run_writes_nothing_and_skips_them_all(project):
    install_notes(project)
    before = _checksums(project / "notes")
    result = install_notes(project)
    assert result.written == []
    assert sorted(Path(p).name for p in result.skipped) == _template_names()
    assert _checksums(project / "notes") == before


def test_an_edited_note_is_left_as_it_was(project):
    notes = project / "notes"
    notes.mkdir()
    edited = "# Writing\n\n2026-10-28. A note the scholar wrote.\n"
    (notes / "writing.md").write_text(edited, encoding="utf-8")
    result = install_notes(project)
    assert (notes / "writing.md").read_text(encoding="utf-8") == edited
    assert [Path(p).name for p in result.skipped] == ["writing.md"]
    assert sorted(Path(p).name for p in result.written) == [n for n in _template_names() if n != "writing.md"]


def test_another_templates_folder_can_be_named(project, tmp_path):
    other = tmp_path / "other_templates"
    other.mkdir()
    (other / "area.md").write_text("# Area\n", encoding="utf-8")
    (other / "skip.txt").write_text("not a template\n", encoding="utf-8")
    result = install_notes(project, templates_dir=other)
    assert [Path(p).name for p in result.written] == ["area.md"]
    assert sorted(p.name for p in (project / "notes").iterdir()) == ["area.md"]


def test_a_missing_templates_folder_refuses(project, tmp_path):
    with pytest.raises(NotesTemplatesError):
        install_notes(project, templates_dir=tmp_path / "nowhere")
    assert not (project / "notes").exists()


class TestCommand:
    def test_install_prints_what_it_wrote_and_skipped(self, project):
        first = _cli(["--project", str(project)], project)
        assert first.returncode == 0, first.stderr
        assert sum(1 for line in first.stdout.splitlines() if line.startswith("wrote ")) == len(
            _template_names()
        )
        second = _cli(["--project", str(project)], project)
        assert second.returncode == 0, second.stderr
        lines = second.stdout.splitlines()
        assert not any(line.startswith("wrote ") for line in lines)
        assert sum(1 for line in lines if line.startswith("skipped ")) == len(_template_names())

    def test_a_missing_templates_folder_exits_2(self, project, tmp_path):
        run = _cli(["--project", str(project), "--templates", str(tmp_path / "nowhere")], project)
        assert run.returncode == 2
        assert not (project / "notes").exists()

    def test_a_copy_without_the_repository_templates_asks_for_them(self, project, tmp_path):
        copy = tmp_path / "replication" / "ospipe"
        shutil.copytree(
            str(OSPIPE_DIR / "ospipe"),
            str(copy / "ospipe"),
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        run = _cli(["--project", str(project)], project, pythonpath=copy)
        assert run.returncode == 2
        assert "--templates" in run.stderr
        assert not (project / "notes").exists()
        named = _cli(["--project", str(project), "--templates", str(TEMPLATES)], project, pythonpath=copy)
        assert named.returncode == 0, named.stderr
        assert sorted(p.name for p in (project / "notes").iterdir()) == _template_names()
