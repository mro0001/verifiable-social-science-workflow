"""The replication folder's Makefile, README, and evidence files. A temporary copy of the
sample project with a build file written by add_product and one manuscript build, emitted
into ship/<product>/."""
import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ospipe.build import read_ledger  # noqa: E402
from ospipe.evidence import fixture as evidence_fixture  # noqa: E402
from ospipe.layout import add_product, read_map  # noqa: E402
from ospipe.replication import ReplicationError, emit  # noqa: E402

OSPIPE_DIR = Path(__file__).resolve().parents[1]
SAMPLE_PROJECT = OSPIPE_DIR.parent / "examples" / "sample_project"
# /usr/bin/make on this Mac is an xcrun shim that fails under an x86_64 python, so the
# real binary is called when it is there.
_REAL_MAKE = "/Library/Developer/CommandLineTools/usr/bin/make"
MAKE = _REAL_MAKE if os.path.exists(_REAL_MAKE) else shutil.which("make")
needs_make = pytest.mark.skipif(MAKE is None, reason="make is not on the path")

BUILD_ARGS = [
    "build", "--manuscript", "manuscript.md", "--manifest", "numbers.yml", "--tables-dir", ".",
    "--bib", "refs.bib", "--to", "docx", "--builds-dir", "builds/manuscript", "--purpose", "draft",
]
COMMAND_START = "PYTHONPATH=tools python3 -m ospipe rebuild "
_ROW = re.compile(r"^\| `([^`]+)` \| ([0-9a-f]{64}) \|$")


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _checksums(folder):
    folder = Path(folder)
    return {
        p.relative_to(folder).as_posix(): _sha256(p)
        for p in sorted(folder.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    }


def _ospipe(args, cwd, pythonpath=None):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(OSPIPE_DIR) if pythonpath is None else pythonpath
    return subprocess.run(
        [sys.executable, "-m", "ospipe"] + list(args), capture_output=True, text=True, cwd=str(cwd), env=env
    )


def _make(args, cwd):
    return subprocess.run([MAKE] + list(args), capture_output=True, text=True, cwd=str(cwd))


def _build(project):
    run = _ospipe(BUILD_ARGS, project)
    assert run.returncode == 0, run.stdout + run.stderr


def _held_citations(project):
    """A current citations results file for the manuscript with r02 held and the rest
    approved, and a citation log naming two of the citekeys."""
    source_text = (project / "manuscript.md").read_text(encoding="utf-8")
    data = evidence_fixture.citations_results(
        source_text=source_text,
        decisions=[
            evidence_fixture.decision("r01"),
            evidence_fixture.decision("r02", "held", by="a scholar"),
            evidence_fixture.decision("r03"),
        ],
    )
    evidence_fixture.write_results(project / "verification", "citations", data)
    (project / "audit").mkdir()
    (project / "audit" / "citation_log.yaml").write_text(evidence_fixture.CITATION_LOG_YAML, encoding="utf-8")


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


def _emit(project, **kwargs):
    return Path(emit(read_map(project / "Makefile"), "manuscript", **kwargs).out_dir)


def _moved(project, tmp_path):
    """Emit, then move the folder out of the project and rename the project away."""
    out = _emit(project)
    away = tmp_path / "away" / "manuscript"
    away.parent.mkdir()
    shutil.move(str(out), str(away))
    project.rename(tmp_path / "project_out_of_reach")
    return away


def _readme(folder):
    return (folder / "README.md").read_text(encoding="utf-8")


def _command_line(folder):
    lines = [line.strip() for line in _readme(folder).splitlines() if line.strip().startswith(COMMAND_START)]
    assert len(lines) == 1, lines
    return lines[0]


def _check(folder):
    """make in the folder, or the check rule's command line when make is not on the path."""
    if MAKE is not None:
        return _make([], folder)
    return subprocess.run(["sh", "-c", _command_line(folder)], capture_output=True, text=True, cwd=str(folder))


class TestReadme:
    def test_it_lists_every_other_file_with_its_checksum(self, project):
        out = _emit(project)
        rows = {}
        for line in _readme(out).splitlines():
            found = _ROW.match(line)
            if found:
                rows[found.group(1)] = found.group(2)
        expected = _checksums(out)
        del expected["README.md"]
        assert rows == expected
        for name in ("Makefile", "unverified_claims.md", "manuscript.md", "tools/ospipe/__main__.py"):
            assert name in rows

    def test_it_names_the_pandoc_version(self, project):
        out = _emit(project)
        first = subprocess.run(["pandoc", "--version"], capture_output=True, text=True).stdout.splitlines()[0]
        text = _readme(out)
        assert first.strip() in text
        assert "different Pandoc" in text

    def test_it_names_the_project_product_build_and_tools(self, project):
        out = _emit(project)
        text = _readme(out)
        row = read_ledger(project / "builds" / "manuscript")[0]
        for piece in ("manuscript", "project", "v001", row["date"], row["sha256"], "builds/manuscript/v001.docx"):
            assert piece in text, piece
        python = "{0}.{1}.{2}".format(*sys.version_info[:3])
        assert "Python " + python in text
        assert "PyYAML " + yaml.__version__ in text
        assert "`make`" in text and "`make results`" in text
        assert "review" in text.lower() and "shared" in text

    def test_it_gives_the_check_rule_s_command_line(self, project):
        out = _emit(project)
        line = _command_line(out)
        for word in ("--manuscript manuscript.md", "--manifest numbers.yml", "--tables-dir .",
                     "--builds-dir builds/manuscript", "--version v001", "--bib refs.bib", "--to docx"):
            assert word in line, word

    def test_it_gives_the_verification_status_and_the_closure_notes(self, project):
        out = _emit(project)
        text = _readme(out)
        assert "unverified: prose, citations, data, build" in text
        assert "citations - missing" in text
        assert "no verification/citations.json, so the citations results are not shipped" in text
        assert not (out / "citation_evidence.yaml").exists()


class TestMakefile:
    def test_check_is_the_default_rule_and_results_follows_the_pipeline(self, project):
        out = _emit(project)
        text = (out / "Makefile").read_text(encoding="utf-8")
        lines = text.splitlines()
        assert lines[0].startswith("#")
        header = " ".join(line for line in lines if line.startswith("#"))
        assert "ospipe emit" in header and "by hand" in header and "emit again" in header
        assert "OSPIPE := PYTHONPATH=tools python3 -m ospipe" in lines
        rules = [line.split(":")[0] for line in lines if re.match(r"^[A-Za-z][A-Za-z0-9_-]*:", line)]
        assert rules == ["check", "results"]
        check = lines[lines.index("check:") + 1]
        assert check.startswith("\t$(OSPIPE) rebuild ") and "--version v001" in check
        assert lines[lines.index("results:") + 1 : lines.index("results:") + 3] == [
            "\tpython3 s1_results.py",
            "\t$(OSPIPE) emit-manifest --manifest numbers.yml",
        ]

    def test_without_pipeline_yaml_there_is_no_results_rule(self, project):
        (project / "pipeline.yaml").unlink()
        out = _emit(project)
        text = (out / "Makefile").read_text(encoding="utf-8")
        assert "results:" not in text
        readme = _readme(out)
        assert "computed results only" in readme
        assert "make results" not in readme


def test_the_moved_folder_matches(project, tmp_path):
    away = _moved(project, tmp_path)
    run = _check(away)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "match v001 sha256 " in run.stdout


def test_the_command_line_matches_without_make(project, tmp_path):
    away = _moved(project, tmp_path)
    run = subprocess.run(["sh", "-c", _command_line(away)], capture_output=True, text=True, cwd=str(away))
    assert run.returncode == 0, run.stdout + run.stderr
    assert run.stdout.startswith("match v001 sha256 ")


@needs_make
def test_make_results_reruns_the_analysis_and_make_still_matches(project, tmp_path):
    away = _moved(project, tmp_path)
    before = _checksums(away)
    for name in ("next_word_results.json", "top_words.md", "params_record_results.csv"):
        (away / name).unlink()
    run = _make(["results"], away)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "python3 s1_results.py" in run.stdout
    assert "numbers.yml unchanged" in run.stdout
    after = _checksums(away)
    for name in ("next_word_results.json", "top_words.md", "params_record_results.csv", "numbers.yml"):
        assert after[name] == before[name], name
    run = _make([], away)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "match v001" in run.stdout


def test_editing_the_shipped_source_prints_text_differs(project, tmp_path):
    away = _moved(project, tmp_path)
    source = away / "manuscript.md"
    source.write_text(source.read_text(encoding="utf-8") + "\nOne more sentence.\n", encoding="utf-8")
    run = _check(away)
    assert run.returncode != 0
    assert "text differs from v001" in run.stdout


class TestHeldCitation:
    def test_a_held_item_appears_in_the_readme_and_the_list(self, project):
        _held_citations(project)
        out = _emit(project)
        listed = (out / "unverified_claims.md").read_text(encoding="utf-8")
        assert "- citations r02 held" in listed
        assert listed.rstrip().endswith("4 unverified")
        text = _readme(out)
        assert "citations r02 held" in text
        assert "unverified: prose, citations, data, build" in text
        assert "citation_evidence.yaml" in text

    def test_the_evidence_file_equals_what_the_command_writes(self, project, tmp_path):
        _held_citations(project)
        out = _emit(project)
        target = tmp_path / "evidence.yaml"
        run = _ospipe(["citation-evidence", "--verification-dir", "verification", "--out", str(target)], out,
                      pythonpath="tools")
        assert run.returncode == 0, run.stdout + run.stderr
        shipped = (out / "citation_evidence.yaml").read_bytes()
        assert shipped == target.read_bytes()
        data = yaml.safe_load(shipped.decode("utf-8"))
        assert [item["decision"] for item in data["items"]] == ["approved", "held", "approved"]
        assert data["items"][1]["session"] == evidence_fixture.SESSION

    def test_the_list_equals_what_the_unverified_command_writes(self, project, tmp_path):
        _held_citations(project)
        out = _emit(project)
        target = tmp_path / "unverified.md"
        run = _ospipe(["unverified", "--source", "manuscript.md", "--manifest", "numbers.yml", "--out",
                       str(target)], out, pythonpath="tools")
        assert run.returncode == 0, run.stdout + run.stderr
        assert (out / "unverified_claims.md").read_bytes() == target.read_bytes()


def test_four_verified_streams_say_none(project):
    source_text = (project / "manuscript.md").read_text(encoding="utf-8")
    numbers_text = (project / "numbers.yml").read_text(encoding="utf-8")
    folder = project / "verification"
    evidence_fixture.write_results(folder, "citations", evidence_fixture.citations_results(source_text=source_text))
    evidence_fixture.write_results(folder, "prose", evidence_fixture.stream_results("prose", source_text))
    evidence_fixture.write_results(folder, "data", evidence_fixture.stream_results("data", numbers_text))
    evidence_fixture.write_results(folder, "build", evidence_fixture.stream_results("build", source_text))
    out = _emit(project)
    text = _readme(out)
    assert "The verification status at emit is `verified`." in text
    # The build had no results, so its ledger row still reads unverified. The README's
    # status is the one at emit and never says the ledger records it.
    assert "ledger records" not in text
    row = read_ledger(out / "builds" / "manuscript")[0]
    assert row["verification"].startswith("unverified")
    section = text.split("## Unverified claims", 1)[1].split("\n## ", 1)[0]
    assert section.strip() == "None"
    assert (out / "unverified_claims.md").read_text(encoding="utf-8") == "0 unverified\n"


def test_a_closure_file_with_a_shipped_file_s_name_is_refused(project):
    (project / "README.md").write_text((project / "manuscript.md").read_text(encoding="utf-8"), encoding="utf-8")
    add_product(project / "Makefile", "readme", "README.md", tables_dir=".")
    run = _ospipe(["build", "--manuscript", "README.md", "--manifest", "numbers.yml", "--tables-dir", ".",
                   "--to", "docx", "--builds-dir", "builds/readme", "--purpose", "draft"], project)
    assert run.returncode == 0, run.stdout + run.stderr
    before = _checksums(project)
    with pytest.raises(ReplicationError) as caught:
        emit(read_map(project / "Makefile"), "readme")
    assert any("README.md" in p for p in caught.value.problems), caught.value.problems
    assert _checksums(project) == before
    assert not (project / "ship").exists()


def test_a_pipeline_step_without_a_runner_is_refused(project):
    pipeline = project / "pipeline.yaml"
    pipeline.write_text(pipeline.read_text(encoding="utf-8").replace("    runner: python3\n", ""), encoding="utf-8")
    before = _checksums(project)
    with pytest.raises(ReplicationError) as caught:
        _emit(project)
    assert any("has no runner" in p for p in caught.value.problems), caught.value.problems
    assert _checksums(project) == before
    assert not (project / "ship").exists()


def test_an_unreadable_citations_results_file_ships_no_evidence_file_and_says_why(project):
    (project / "verification").mkdir(exist_ok=True)
    (project / "verification" / "citations.json").write_text("{not json", encoding="utf-8")
    out = _emit(project)
    assert (out / "verification" / "citations.json").is_file()
    assert not (out / "citation_evidence.yaml").exists()
    assert "No citation evidence file was written, since" in _readme(out)


def test_the_emit_check_still_refuses_a_rewritten_ledger_date(project):
    ledger = project / "builds" / "manuscript" / "BUILDS.md"
    row = read_ledger(ledger.parent)[0]
    text = ledger.read_text(encoding="utf-8")
    ledger.write_text(text.replace("| v001 | {0} |".format(row["date"]), "| v001 | 2020-01-01 |"), encoding="utf-8")
    with pytest.raises(ReplicationError):
        _emit(project)
    assert not (project / "ship").exists()
