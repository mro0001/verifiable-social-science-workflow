"""From source files to replication folder, running `python3 -m ospipe` as a scholar would.

In a temporary copy of the sample project it installs the notes, adds three products,
reruns the analysis and the manifest emitter, builds each product, marks an older draft,
lists what is unverified, and emits two replication folders, each of which rebuilds with
a match once it is moved out of the project.
"""
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ospipe.evidence import fixture as evidence_fixture  # noqa: E402

OSPIPE_DIR = Path(__file__).resolve().parents[1]
REPO = OSPIPE_DIR.parent
SAMPLE_PROJECT = REPO / "examples" / "sample_project"
NOTES_TEMPLATES = REPO / "templates" / "notes"
# /usr/bin/make on this Mac is an xcrun shim that fails under an x86_64 python, so the
# real binary is called when it is there.
_REAL_MAKE = "/Library/Developer/CommandLineTools/usr/bin/make"
MAKE = _REAL_MAKE if os.path.exists(_REAL_MAKE) else shutil.which("make")
COMMAND_START = "PYTHONPATH=tools python3 -m ospipe rebuild "

SITE_MD = """\
---
title: The Next Word, Online
---

# The next word

Asked with no context, {{num:model}} gave its most common word in {{num:none.top_pct}} percent of its answers.
"""

# name -> (add-product options, build options beyond the source and manifest, extension)
PRODUCTS = {
    "manuscript": (["--source", "manuscript.md", "--bib", "refs.bib", "--tables-dir", "."],
                   ["--tables-dir", ".", "--bib", "refs.bib", "--to", "docx"], ".docx"),
    "slides": (["--source", "slides.md", "--to", "revealjs", "--tables-dir", "."],
               ["--tables-dir", ".", "--to", "revealjs"], ".html"),
    "site": (["--source", "site.md", "--to", "html"], ["--to", "html"], ".html"),
}
SOURCES = {"manuscript": "manuscript.md", "slides": "slides.md", "site": "site.md"}


def _checksums(folder):
    folder = Path(folder)
    return {
        p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(folder.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    }


def _run(args, cwd, pythonpath=None):
    env = dict(os.environ)
    env.pop("SOURCE_DATE_EPOCH", None)
    if pythonpath is not None:
        env["PYTHONPATH"] = pythonpath
    return subprocess.run(list(args), capture_output=True, text=True, cwd=str(cwd), env=env)


def _ospipe(args, cwd, pythonpath=None):
    run = _run([sys.executable, "-m", "ospipe"] + list(args), cwd, str(OSPIPE_DIR) if pythonpath is None else pythonpath)
    return run


def _ok(run):
    assert run.returncode == 0, run.stdout + run.stderr
    return run.stdout.splitlines()


def _build(project, name):
    if MAKE is not None:
        return _ok(_run([MAKE, name], project))
    _, options, _ = PRODUCTS[name]
    args = ["build", "--manuscript", SOURCES[name], "--manifest", "numbers.yml"] + options
    args += ["--builds-dir", "builds/" + name, "--purpose", "draft"]
    return _ok(_ospipe(args, project))


def _check_shipped(folder):
    """make in the moved folder, or the check rule's command line when make is not on the path."""
    if MAKE is not None:
        return _run([MAKE], folder)
    readme = (folder / "README.md").read_text(encoding="utf-8")
    lines = [line.strip() for line in readme.splitlines() if line.strip().startswith(COMMAND_START)]
    assert len(lines) == 1, lines
    return _run(["sh", "-c", lines[0]], folder)


def test_from_source_files_to_replication_folder(tmp_path):
    sample_before = _checksums(SAMPLE_PROJECT)
    notes_before = _checksums(NOTES_TEMPLATES)
    project = tmp_path / "project"
    shutil.copytree(
        str(SAMPLE_PROJECT), str(project), ignore=shutil.ignore_patterns("__pycache__", "builds", "ship")
    )

    # The notes templates.
    lines = _ok(_ospipe(["install-notes", "--project", "."], project))
    templates = sorted(p.name for p in NOTES_TEMPLATES.glob("*.md"))
    assert lines == ["wrote notes/{0}".format(name) for name in templates]

    # Three products, one source file each.
    (project / "site.md").write_text(SITE_MD, encoding="utf-8")
    for name, (options, _, _) in PRODUCTS.items():
        lines = _ok(_ospipe(["add-product", "--name", name] + options, project))
        to = options[options.index("--to") + 1] if "--to" in options else "docx"
        assert lines == ["added {0} to Makefile, {1} -> builds/{0} ({2})".format(name, SOURCES[name], to)]

    # The analysis, then the manifest emitter, which finds nothing to change.
    _ok(_run(["python3", "s1_results.py"], project))
    numbers_before = (project / "numbers.yml").read_bytes()
    assert _ok(_ospipe(["emit-manifest", "--manifest", "numbers.yml"], project)) == ["numbers.yml unchanged"]
    assert (project / "numbers.yml").read_bytes() == numbers_before

    # Each product builds as v001.
    for name, (_, _, extension) in PRODUCTS.items():
        lines = _build(project, name)
        wanted = "v001 -> builds/{0}/v001{1} (sha256 ".format(name, extension)
        assert any(line.startswith(wanted) for line in lines), lines
        assert (project / "builds" / name / ("v001" + extension)).is_file()

    # An older draft reads as the manuscript until it carries an archive line.
    shutil.copyfile(str(project / "manuscript.md"), str(project / "manuscript_2026-09.md"))
    lines = _ok(_ospipe(["products"], project))
    assert lines[:3] == [
        "manuscript: manuscript.md -> builds/manuscript (docx)",
        "slides: slides.md -> builds/slides (revealjs)",
        "site: site.md -> builds/site (html)",
    ]
    advice = [line for line in lines if line.startswith("not archived: ")]
    assert len(advice) == 1 and advice[0].startswith("not archived: manuscript_2026-09.md reads as manuscript.md ")
    lines = _ok(_ospipe(["archive", "manuscript_2026-09.md", "--by", "manuscript.md", "--date", "2026-10-28"], project))
    assert lines[0].startswith("archived manuscript_2026-09.md")
    assert not [line for line in _ok(_ospipe(["products"], project)) if line.startswith("not archived: ")]

    # A current citations results file with one held item.
    source_text = (project / "manuscript.md").read_text(encoding="utf-8")
    results = evidence_fixture.citations_results(
        source_text=source_text,
        decisions=[
            evidence_fixture.decision("r01"),
            evidence_fixture.decision("r02", "held"),
            evidence_fixture.decision("r03"),
        ],
    )
    evidence_fixture.write_results(project / "verification", "citations", results)
    lines = _ok(_ospipe(["unverified", "--source", "manuscript.md", "--manifest", "numbers.yml"], project))
    assert lines == [
        "prose - missing",
        "citations r02 held, The rise was steady.",
        "data - missing",
        "build - missing",
        "4 unverified",
    ]

    # The manuscript's and the website's replication folders.
    away = tmp_path / "away"
    away.mkdir()
    for name in ("manuscript", "site"):
        lines = _ok(_ospipe(["emit", "--product", name], project))
        assert lines[0].startswith("emitted {0} v001 to ".format(name)), lines
        shutil.move(str(project / "ship" / name), str(away / name))
    project.rename(tmp_path / "project_out_of_reach")

    for name in ("manuscript", "site"):
        run = _check_shipped(away / name)
        assert run.returncode == 0, run.stdout + run.stderr
        assert "match v001 sha256 " in run.stdout
    readme = (away / "manuscript" / "README.md").read_text(encoding="utf-8")
    assert "citations r02 held" in readme
    assert (away / "manuscript" / "citation_evidence.yaml").is_file()

    assert _checksums(SAMPLE_PROJECT) == sample_before
    assert _checksums(NOTES_TEMPLATES) == notes_before
