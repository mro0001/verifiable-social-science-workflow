"""The emit command. A temporary copy of the sample project with a build file written by
add_product and one manuscript build, emitted into ship/<product>/."""
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ospipe.build import read_ledger, verify_ledger  # noqa: E402
from ospipe.layout import add_product, read_map  # noqa: E402
from ospipe.replication import (  # noqa: E402
    PIPELINE_MODULES,
    EmitResult,
    ReplicationError,
    closure,
    emit,
)

OSPIPE_DIR = Path(__file__).resolve().parents[1]
PACKAGE_DIR = OSPIPE_DIR / "ospipe"
SAMPLE_PROJECT = OSPIPE_DIR.parent / "examples" / "sample_project"
MOVED = ("kb", "lint", "annotate", "returns", "reconcile")
# /usr/bin/make on this Mac is an xcrun shim that fails under an x86_64 python, so the
# real binary is called when it is there.
_REAL_MAKE = "/Library/Developer/CommandLineTools/usr/bin/make"
MAKE = _REAL_MAKE if os.path.exists(_REAL_MAKE) else shutil.which("make")

BUILD_ARGS = [
    "build", "--manuscript", "manuscript.md", "--manifest", "numbers.yml", "--tables-dir", ".",
    "--bib", "refs.bib", "--to", "docx", "--builds-dir", "builds/manuscript", "--purpose", "draft",
]
REBUILD_ARGS = [
    "rebuild", "--manuscript", "manuscript.md", "--manifest", "numbers.yml", "--tables-dir", ".",
    "--builds-dir", "builds/manuscript", "--bib", "refs.bib", "--to", "docx",
]


def _checksums(folder):
    folder = Path(folder)
    if not folder.exists():
        return {}
    return {
        p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(folder.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    }


def _ospipe(args, cwd, pythonpath=None):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(OSPIPE_DIR) if pythonpath is None else pythonpath
    return subprocess.run(
        [sys.executable, "-m", "ospipe"] + list(args),
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=env,
    )


def _build(project):
    run = _ospipe(BUILD_ARGS, project)
    assert run.returncode == 0, run.stdout + run.stderr
    return run


@pytest.fixture(scope="module")
def sample_before():
    return _checksums(SAMPLE_PROJECT)


@pytest.fixture(scope="module")
def template(tmp_path_factory, sample_before):
    folder = tmp_path_factory.mktemp("template") / "project"
    shutil.copytree(
        str(SAMPLE_PROJECT), str(folder), ignore=shutil.ignore_patterns("__pycache__", "builds", "ship")
    )
    add_product(folder / "Makefile", "manuscript", "manuscript.md", bib="refs.bib", tables_dir=".")
    _build(folder)
    yield folder
    assert _checksums(SAMPLE_PROJECT) == sample_before


@pytest.fixture()
def project(tmp_path, template):
    folder = tmp_path / "project"
    shutil.copytree(str(template), str(folder))
    return folder


def _map(project):
    return read_map(project / "Makefile")


def _shipped(project):
    return project / "ship" / "manuscript"


class TestFolder:
    def test_every_closure_file_is_shipped_byte_identical(self, project):
        result = emit(_map(project), "manuscript")
        assert isinstance(result, EmitResult)
        out = Path(result.out_dir)
        assert out == (project / "ship" / "manuscript").resolve()
        files = closure(_map(project), "manuscript").files
        assert files
        for relative in files:
            assert (out / relative).read_bytes() == (project / relative).read_bytes(), relative

    def test_the_shipped_build_has_a_one_row_ledger(self, project):
        result = emit(_map(project), "manuscript")
        assert result.version == "v001"
        builds = Path(result.out_dir) / "builds" / "manuscript"
        source_builds = project / "builds" / "manuscript"
        for name in ("v001.docx", "v001.md"):
            assert (builds / name).read_bytes() == (source_builds / name).read_bytes()
        assert sorted(p.name for p in builds.iterdir()) == ["BUILDS.md", "v001.docx", "v001.md"]
        rows = read_ledger(builds)
        assert rows == read_ledger(source_builds)
        assert len(rows) == 1
        verify_ledger(builds)

    def test_the_ledger_keeps_the_header_lines_and_the_chosen_row_only(self, project):
        _build(project)
        emit(_map(project), "manuscript", version="v001")
        lines = (project / "builds" / "manuscript" / "BUILDS.md").read_text(encoding="utf-8").splitlines(True)
        shipped = (_shipped(project) / "builds" / "manuscript" / "BUILDS.md").read_text(encoding="utf-8")
        assert lines[4].startswith("| v001 |") and lines[5].startswith("| v002 |")
        assert shipped == "".join(lines[:5])

    def test_the_pipeline_package_is_shipped_under_tools(self, project):
        result = emit(_map(project), "manuscript")
        tools = Path(result.out_dir) / "tools" / "ospipe"
        top = sorted(p.name for p in tools.iterdir())
        assert top == sorted(["__init__.py", "__main__.py"] + list(PIPELINE_MODULES))
        assert not any("__pycache__" in p.parts for p in tools.rglob("*"))
        for name in ("__init__.py", "__main__.py"):
            assert (tools / name).read_bytes() == (PACKAGE_DIR / name).read_bytes()
        for module in PIPELINE_MODULES:
            assert _checksums(tools / module) == _checksums(PACKAGE_DIR / module), module

    def test_the_result_lists_every_file_in_the_folder(self, project):
        result = emit(_map(project), "manuscript")
        assert result.files == sorted(_checksums(result.out_dir))

    def test_nothing_is_left_beside_the_folder(self, project):
        emit(_map(project), "manuscript")
        assert sorted(p.name for p in (project / "ship").iterdir()) == ["manuscript"]


def test_pipeline_modules_are_the_package_module_folders():
    folders = sorted(
        child.name
        for child in PACKAGE_DIR.iterdir()
        if child.is_dir() and child.name not in MOVED and (child / "__init__.py").is_file()
    )
    assert sorted(PIPELINE_MODULES) == folders
    assert len(set(PIPELINE_MODULES)) == len(PIPELINE_MODULES)


def test_the_folder_rebuilds_with_the_project_out_of_reach(project, tmp_path):
    emit(_map(project), "manuscript")
    moved = tmp_path / "moved_away"
    project.rename(moved)
    assert not project.exists()
    run = _ospipe(REBUILD_ARGS + ["--version", "v001"], moved / "ship" / "manuscript", pythonpath="tools")
    assert run.returncode == 0, run.stdout + run.stderr
    assert run.stdout.startswith("match v001 sha256 ")


class TestRefusals:
    def test_a_project_with_no_build_is_refused(self, project):
        shutil.rmtree(str(project / "builds"))
        before = _checksums(project)
        with pytest.raises(ReplicationError) as caught:
            emit(_map(project), "manuscript")
        assert any("no build" in p for p in caught.value.problems), caught.value.problems
        assert _checksums(project) == before
        assert not (project / "ship").exists()

    def test_an_unknown_version_is_refused(self, project):
        before = _checksums(project)
        with pytest.raises(ReplicationError) as caught:
            emit(_map(project), "manuscript", version="v009")
        assert any("v009" in p for p in caught.value.problems), caught.value.problems
        assert _checksums(project) == before

    def test_an_existing_folder_is_refused_without_replace(self, project):
        emit(_map(project), "manuscript")
        before = _checksums(project)
        with pytest.raises(ReplicationError) as caught:
            emit(_map(project), "manuscript")
        assert any("replace" in p for p in caught.value.problems), caught.value.problems
        assert _checksums(project) == before
        assert sorted(p.name for p in (project / "ship").iterdir()) == ["manuscript"]

    def test_a_closure_problem_is_refused(self, project):
        (project / "params_io.py").unlink()
        before = _checksums(project)
        with pytest.raises(ReplicationError) as caught:
            emit(_map(project), "manuscript")
        assert any("params_io.py" in p for p in caught.value.problems)
        assert _checksums(project) == before
        assert not (project / "ship").exists()

    def test_a_rewritten_ledger_date_fails_the_rebuild(self, project):
        ledger = project / "builds" / "manuscript" / "BUILDS.md"
        row = read_ledger(ledger.parent)[0]
        text = ledger.read_text(encoding="utf-8")
        old = "| v001 | {0} |".format(row["date"])
        assert old in text
        ledger.write_text(text.replace(old, "| v001 | 2020-01-01 |"), encoding="utf-8")
        before = _checksums(project)
        with pytest.raises(ReplicationError) as caught:
            emit(_map(project), "manuscript")
        assert any("mismatch v001" in p for p in caught.value.problems), caught.value.problems
        assert _checksums(project) == before
        assert not (project / "ship").exists()


class TestOutDirRefusals:
    """With replace, an out_dir that is or holds the project, a closure file, or the
    builds dir would be removed, so each is refused before anything is written."""

    def _refused(self, project, out_dir, words):
        before = _checksums(project)
        with pytest.raises(ReplicationError) as caught:
            emit(_map(project), "manuscript", out_dir=out_dir, replace=True)
        assert any(all(w in p for w in words) for p in caught.value.problems), caught.value.problems
        assert _checksums(project) == before
        assert not (project / "ship").exists()

    def test_the_project_folder_is_refused(self, project):
        self._refused(project, project, ["project folder"])

    def test_a_folder_holding_the_project_is_refused(self, project):
        self._refused(project, project.parent, ["project folder"])

    def test_the_builds_dir_is_refused(self, project):
        self._refused(project, project / "builds" / "manuscript", ["builds/manuscript"])

    def test_a_folder_holding_the_builds_dir_is_refused(self, project):
        self._refused(project, project / "builds", ["builds/manuscript"])

    def test_a_closure_file_is_refused(self, project):
        self._refused(project, project / "manuscript.md", ["manuscript.md"])

    def test_a_folder_holding_a_closure_file_is_refused(self, project):
        (project / "data").mkdir()
        shutil.move(str(project / "refs.bib"), str(project / "data" / "refs.bib"))
        makefile = project / "Makefile"
        text = makefile.read_text(encoding="utf-8")
        assert "--bib refs.bib" in text
        makefile.write_text(text.replace("--bib refs.bib", "--bib data/refs.bib"), encoding="utf-8")
        assert "data/refs.bib" in closure(_map(project), "manuscript").files
        self._refused(project, project / "data", ["data/refs.bib"])

    def test_a_relative_out_is_read_from_the_current_folder(self, project, monkeypatch):
        monkeypatch.chdir(str(project))
        self._refused(project, ".", ["project folder"])
        self._refused(project, "builds", ["builds/manuscript"])


class TestReplaceRefusals:
    """With replace, an existing out_dir is removed, so one that is not a replication
    folder emit wrote, or that holds any product's builds, is refused and left as it was."""

    def _refused(self, project, out_dir, words):
        before = _checksums(project)
        with pytest.raises(ReplicationError) as caught:
            emit(_map(project), "manuscript", out_dir=out_dir, replace=True)
        assert any(all(w in p for w in words) for p in caught.value.problems), caught.value.problems
        assert _checksums(project) == before
        assert not (project / "ship").exists()

    def test_another_product_s_builds_dir_is_refused(self, project):
        add_product(project / "Makefile", "slides", "slides.md", to="html")
        builds = project / "builds" / "slides"
        builds.mkdir(parents=True)
        for name in ("BUILDS.md", "v001.html", "v001.md"):
            (builds / name).write_text("made by hand\n", encoding="utf-8")
        self._refused(project, builds, ["builds/slides"])
        assert sorted(p.name for p in builds.iterdir()) == ["BUILDS.md", "v001.html", "v001.md"]

    def test_a_folder_emit_did_not_write_is_refused(self, project):
        notes = project / "notes"
        notes.mkdir()
        (notes / "decisions.md").write_text("a record\n", encoding="utf-8")
        self._refused(project, notes, ["not a replication folder"])
        assert (notes / "decisions.md").read_text(encoding="utf-8") == "a record\n"

    def test_a_folder_outside_the_project_emit_did_not_write_is_refused(self, project, tmp_path):
        other = tmp_path / "other"
        other.mkdir()
        (other / "keep.txt").write_text("keep\n", encoding="utf-8")
        self._refused(project, other, ["not a replication folder"])
        assert sorted(p.name for p in tmp_path.iterdir()) == ["other", "project"]
        assert (other / "keep.txt").read_text(encoding="utf-8") == "keep\n"

    def test_an_existing_file_is_refused(self, project, tmp_path):
        other = tmp_path / "other.txt"
        other.write_text("keep\n", encoding="utf-8")
        self._refused(project, other, ["not a folder"])
        assert sorted(p.name for p in tmp_path.iterdir()) == ["other.txt", "project"]
        assert other.read_text(encoding="utf-8") == "keep\n"

    def test_the_command_with_another_product_s_builds_exits_2(self, project):
        add_product(project / "Makefile", "slides", "slides.md", to="html")
        builds = project / "builds" / "slides"
        builds.mkdir(parents=True)
        (builds / "BUILDS.md").write_text("made by hand\n", encoding="utf-8")
        before = _checksums(project)
        for out in ("builds/slides", "notes"):
            if out == "notes":
                (project / "notes").mkdir()
                (project / "notes" / "decisions.md").write_text("a record\n", encoding="utf-8")
                before = _checksums(project)
            run = _ospipe(["emit", "--product", "manuscript", "--out", out, "--replace"], project)
            assert run.returncode == 2, run.stdout + run.stderr
            assert _checksums(project) == before
        assert not (project / "ship").exists()


def test_replace_puts_the_new_folder_in_the_old_one_s_place(project):
    first = emit(_map(project), "manuscript")
    (Path(first.out_dir) / "left_by_hand.txt").write_text("old\n", encoding="utf-8")
    _build(project)
    second = emit(_map(project), "manuscript", replace=True)
    assert second.out_dir == first.out_dir
    assert second.version == "v002"
    out = Path(second.out_dir)
    assert not (out / "left_by_hand.txt").exists()
    names = sorted(p.name for p in (out / "builds" / "manuscript").iterdir())
    assert names == ["BUILDS.md", "v002.docx", "v002.md"]
    assert sorted(p.name for p in (project / "ship").iterdir()) == ["manuscript"]


def test_a_named_out_dir_is_used(project, tmp_path):
    out = tmp_path / "elsewhere" / "paper"
    result = emit(_map(project), "manuscript", out_dir=out)
    assert Path(result.out_dir) == out.resolve()
    assert (out / "manuscript.md").is_file()
    assert not (project / "ship").exists()


class TestCommand:
    def test_emit_writes_the_folder_and_exits_0(self, project):
        run = _ospipe(["emit", "--product", "manuscript"], project)
        assert run.returncode == 0, run.stdout + run.stderr
        assert run.stdout.startswith("emitted manuscript v001 to ")
        assert (_shipped(project) / "builds" / "manuscript" / "v001.docx").is_file()

    def test_every_option_reaches_emit(self, project, tmp_path):
        _build(project)
        out = tmp_path / "out"
        run = _ospipe(
            ["emit", "--map", str(project / "Makefile"), "--product", "manuscript", "--out", str(out),
             "--version", "v001"],
            tmp_path,
        )
        assert run.returncode == 0, run.stdout + run.stderr
        assert (out / "builds" / "manuscript" / "v001.docx").is_file()
        run = _ospipe(["emit", "--map", str(project / "Makefile"), "--product", "manuscript", "--out",
                       str(out), "--replace"], tmp_path)
        assert run.returncode == 0, run.stdout + run.stderr
        assert (out / "builds" / "manuscript" / "v002.docx").is_file()

    def test_a_refusal_exits_2(self, project):
        before = _checksums(project)
        run = _ospipe(["emit", "--product", "poster"], project)
        assert run.returncode == 2
        assert "poster" in run.stderr
        assert _checksums(project) == before

    def test_out_dot_or_builds_with_replace_exits_2_and_keeps_the_project(self, project):
        before = _checksums(project)
        for out in (".", "builds"):
            run = _ospipe(["emit", "--product", "manuscript", "--out", out, "--replace"], project)
            assert run.returncode == 2, run.stdout + run.stderr
            assert _checksums(project) == before
        assert not (project / "ship").exists()

    def test_a_missing_build_file_exits_2(self, tmp_path):
        run = _ospipe(["emit", "--product", "manuscript"], tmp_path)
        assert run.returncode == 2
        assert "no build file" in run.stderr


@pytest.mark.skipif(MAKE is None, reason="make is not on the path")
def test_make_emit_writes_the_folder(project):
    run = subprocess.run([MAKE, "emit", "PRODUCT=manuscript"], capture_output=True, text=True, cwd=str(project))
    assert run.returncode == 0, run.stdout + run.stderr
    assert (_shipped(project) / "builds" / "manuscript" / "v001.docx").is_file()
    assert (_shipped(project) / "tools" / "ospipe" / "__main__.py").is_file()
