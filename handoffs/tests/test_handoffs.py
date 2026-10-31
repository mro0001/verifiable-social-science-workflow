"""Tests for the handoffs, the plain file copies between layers.

Each handoff is called as a command, the way a scholar or the authors would run it.
Every file here is synthetic and written in the test.

Run from the repository root with python3 -m pytest -q handoffs/tests.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HANDOFFS = ROOT / "handoffs"


def call(script, *args):
    return subprocess.run([sys.executable, str(HANDOFFS / script)] + [str(a) for a in args],
                          cwd=str(ROOT), capture_output=True, text=True)


def tree(folder):
    """Every file under a folder, as relative path to bytes."""
    folder = Path(folder)
    return {str(p.relative_to(folder)): p.read_bytes()
            for p in sorted(folder.rglob("*")) if p.is_file()}


# W1. The audit-to-project copy.

RECORDS = {
    "citation_log": "citation_log.yaml",
    "session_writes": "session_writes.jsonl",
    "rationales": "rationales.yaml",
}


def record_file(tmp_path, name, data):
    path = tmp_path / "audit_out" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def project(tmp_path):
    path = tmp_path / "project"
    path.mkdir()
    (path / "manuscript.md").write_text("A test manuscript.\n", encoding="utf-8")
    return path


@pytest.mark.parametrize("kind", sorted(RECORDS))
def test_each_record_lands_under_its_fixed_name_with_identical_bytes(tmp_path, kind):
    data = ("# written by a test\r\nkind: %s\n\xe9\x00tail" % kind).encode("latin-1")
    src = record_file(tmp_path, "any_name.out", data)
    proj = project(tmp_path)
    r = call("audit_to_project.py", "--record", kind, "--from", src, "--project", proj)
    assert r.returncode == 0, r.stderr
    dest = proj / "audit" / RECORDS[kind]
    assert dest.read_bytes() == data
    assert str(dest) in r.stdout
    assert sorted(tree(proj / "audit")) == [RECORDS[kind]]


def test_audit_folder_is_created_when_absent(tmp_path):
    src = record_file(tmp_path, "citation_log.yaml", b"citations: {}\n")
    proj = project(tmp_path)
    assert not (proj / "audit").exists()
    r = call("audit_to_project.py", "--record", "citation_log", "--from", src, "--project", proj)
    assert r.returncode == 0, r.stderr
    assert (proj / "audit").is_dir()


def test_second_copy_replaces_the_first(tmp_path):
    proj = project(tmp_path)
    first = record_file(tmp_path, "first.yaml", b"citations:\n  a: 1\n  b: 2\n  c: 3\n")
    second = record_file(tmp_path, "second.yaml", b"citations: {}\n")
    for src in (first, second):
        r = call("audit_to_project.py", "--record", "citation_log", "--from", src,
                 "--project", proj)
        assert r.returncode == 0, r.stderr
    assert (proj / "audit" / "citation_log.yaml").read_bytes() == b"citations: {}\n"


def test_copy_leaves_other_records_alone(tmp_path):
    proj = project(tmp_path)
    log = record_file(tmp_path, "log.yaml", b"citations: {}\n")
    writes = record_file(tmp_path, "writes.jsonl", b'{"path": "builds/x"}\n')
    call("audit_to_project.py", "--record", "citation_log", "--from", log, "--project", proj)
    call("audit_to_project.py", "--record", "session_writes", "--from", writes, "--project", proj)
    assert tree(proj / "audit") == {"citation_log.yaml": b"citations: {}\n",
                                    "session_writes.jsonl": b'{"path": "builds/x"}\n'}


def test_missing_record_file_exits_2_and_writes_nothing(tmp_path):
    proj = project(tmp_path)
    before = tree(proj)
    missing = tmp_path / "audit_out" / "nothing_here.yaml"
    r = call("audit_to_project.py", "--record", "citation_log", "--from", missing,
             "--project", proj)
    assert r.returncode == 2
    assert str(missing) in r.stderr
    assert tree(proj) == before
    assert not (proj / "audit").exists()


def test_missing_project_exits_2_and_writes_nothing(tmp_path):
    src = record_file(tmp_path, "log.yaml", b"citations: {}\n")
    missing = tmp_path / "no_project"
    r = call("audit_to_project.py", "--record", "citation_log", "--from", src,
             "--project", missing)
    assert r.returncode == 2
    assert str(missing) in r.stderr
    assert not missing.exists()


def test_unknown_record_kind_is_refused(tmp_path):
    src = record_file(tmp_path, "log.yaml", b"citations: {}\n")
    proj = project(tmp_path)
    before = tree(proj)
    r = call("audit_to_project.py", "--record", "transcripts", "--from", src, "--project", proj)
    assert r.returncode == 2
    assert "transcripts" in r.stderr
    assert tree(proj) == before


# W2. The project-to-references copy (Track C2, step C3).

LEDGER_HEADER = (
    "# Builds\n\n"
    "| version | date | git | sha256 | purpose | baseline | reviewed | verification | runs |\n"
    "|---|---|---|---|---|---|---|---|---|\n")


def ledger_row(version):
    return "| %s | 2026-10-31 | - | %s | test | - | no | unverified: citations | - |\n" % (
        version, "0" * 64)


PROJECT_FILES = {
    "manuscript.md": b"A test manuscript with {{num:n}} cases [@dumont2014].\n",
    "slides.md": b"# Slides\n\nA slide [@nakamura2020].\n",
    "author_draft.md": b"A test manuscript.\n",
    "audit/citation_log.yaml": b"citations:\n  dumont2014:\n    introduced_by: ai\n",
    "refs.bib": b"@article{dumont2014, title={T}}\n",
    "builds/manuscript/BUILDS.md": (LEDGER_HEADER + ledger_row("v001")
                                    + ledger_row("v002")).encode("utf-8"),
    "builds/manuscript/v001.md": b"A test manuscript with 10 cases.\n",
    "builds/manuscript/v002.md": b"A test manuscript with 12 cases [@dumont2014].\n",
    "builds/slides/BUILDS.md": (LEDGER_HEADER + ledger_row("v001")).encode("utf-8"),
    "builds/slides/v001.md": b"# Slides\n\nA built slide [@nakamura2020].\n",
}
REFERENCE_FILES = {
    "refs.yaml": b"dumont2014:\n  title: T\n",
    "metadata_cache.json": b"{}\n",
    "prior_checks.json": b"[]\n",
    "source_dumont2014.txt": b"ACCESS: fulltext\nSome text.\n",
    "source_nakamura2020.txt": b"ACCESS: abstract\nOther text.\n",
    "recorded_judge.json": b"{}\n",
    "recorded_second.json": b"{}\n",
    "expected_citation_log.yaml": b"citations: {}\n",
    "notes.txt": b"the scholar's notes\n",
}
PROVENANCE = b"works:\n  dumont2014:\n    origin: ai\n"


def write_tree(folder, files):
    for name, data in files.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return folder


def references_setup(tmp_path, drop_project=(), drop_references=(), project_files=None):
    files = dict(PROJECT_FILES, **(project_files or {}))
    proj = write_tree(tmp_path / "project",
                      {k: v for k, v in files.items() if k not in drop_project})
    refs = write_tree(tmp_path / "references",
                      {k: v for k, v in REFERENCE_FILES.items() if k not in drop_references})
    record = tmp_path / "audit_out" / "citation_provenance.yaml"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_bytes(PROVENANCE)
    return proj, refs, record


def to_references(proj, refs, record, to, *extra):
    return call("project_to_references.py", "--project", proj, "--references", refs,
                "--provenance", record, "--to", to, *extra)


def test_inputs_folder_holds_exactly_the_named_files_with_identical_bytes(tmp_path):
    proj, refs, record = references_setup(tmp_path)
    to = tmp_path / "inputs" / "citations"
    r = to_references(proj, refs, record, to)
    assert r.returncode == 0, r.stderr
    assert str(to) in r.stdout
    assert tree(to) == {
        "draft.md": PROJECT_FILES["builds/manuscript/v002.md"],
        "manuscript.md": PROJECT_FILES["manuscript.md"],
        "citation_provenance.yaml": PROVENANCE,
        "refs.yaml": REFERENCE_FILES["refs.yaml"],
        "metadata_cache.json": REFERENCE_FILES["metadata_cache.json"],
        "source_dumont2014.txt": REFERENCE_FILES["source_dumont2014.txt"],
        "source_nakamura2020.txt": REFERENCE_FILES["source_nakamura2020.txt"],
    }


def test_the_draft_is_the_latest_builds_filled_in_text(tmp_path):
    proj, refs, record = references_setup(tmp_path)
    to = tmp_path / "inputs"
    assert to_references(proj, refs, record, to).returncode == 0
    digest = hashlib.sha256((proj / "builds" / "manuscript" / "v002.md").read_bytes()).hexdigest()
    assert hashlib.sha256((to / "draft.md").read_bytes()).hexdigest() == digest


def test_the_latest_build_is_the_highest_version_in_the_ledger(tmp_path):
    # A hand-ledgered v000 row added after the builds is not the latest build.
    ledger = (LEDGER_HEADER + ledger_row("v001") + ledger_row("v002")
              + ledger_row("v000")).encode("utf-8")
    proj, refs, record = references_setup(
        tmp_path, project_files={"builds/manuscript/BUILDS.md": ledger})
    to = tmp_path / "inputs"
    r = to_references(proj, refs, record, to)
    assert r.returncode == 0, r.stderr
    assert (to / "draft.md").read_bytes() == PROJECT_FILES["builds/manuscript/v002.md"]


def test_the_source_text_is_copied_under_its_own_name_with_its_checksum(tmp_path):
    # The run lists the source text's checksum among its inputs, which is how the
    # build knows the stream's results are for the current source text.
    proj, refs, record = references_setup(tmp_path)
    to = tmp_path / "inputs"
    assert to_references(proj, refs, record, to).returncode == 0
    digest = hashlib.sha256((proj / "manuscript.md").read_bytes()).hexdigest()
    assert hashlib.sha256((to / "manuscript.md").read_bytes()).hexdigest() == digest


def test_builds_dir_and_source_options_name_another_product(tmp_path):
    proj, refs, record = references_setup(tmp_path)
    to = tmp_path / "inputs"
    r = to_references(proj, refs, record, to, "--builds-dir", "builds/slides",
                      "--source", "slides.md")
    assert r.returncode == 0, r.stderr
    assert (to / "draft.md").read_bytes() == PROJECT_FILES["builds/slides/v001.md"]
    assert (to / "slides.md").read_bytes() == PROJECT_FILES["slides.md"]
    assert not (to / "manuscript.md").exists()


def test_references_copy_leaves_every_folder_and_the_record_unchanged(tmp_path):
    proj, refs, record = references_setup(tmp_path)
    before = (tree(proj), tree(refs), record.read_bytes())
    r = to_references(proj, refs, record, tmp_path / "inputs")
    assert r.returncode == 0, r.stderr
    assert (tree(proj), tree(refs), record.read_bytes()) == before


def test_existing_inputs_folder_is_refused(tmp_path):
    proj, refs, record = references_setup(tmp_path)
    to = tmp_path / "inputs"
    to.mkdir()
    (to / "draft.md").write_bytes(b"an earlier run's draft\n")
    r = to_references(proj, refs, record, to)
    assert r.returncode == 2
    assert str(to) in r.stderr
    assert tree(to) == {"draft.md": b"an earlier run's draft\n"}


def test_a_missing_provenance_record_is_refused_with_a_message(tmp_path):
    proj, refs, record = references_setup(tmp_path)
    record.unlink()
    to = tmp_path / "inputs"
    r = to_references(proj, refs, record, to)
    assert r.returncode == 2
    assert str(record) in r.stderr
    assert "citation provenance record" in r.stderr
    assert "write-out citation-provenance" in r.stderr
    assert not to.exists()


def test_the_provenance_option_is_required(tmp_path):
    proj, refs, _ = references_setup(tmp_path)
    to = tmp_path / "inputs"
    r = call("project_to_references.py", "--project", proj, "--references", refs, "--to", to)
    assert r.returncode == 2
    assert "--provenance" in r.stderr
    assert not to.exists()


def test_a_project_with_no_build_ledger_is_refused(tmp_path):
    proj, refs, record = references_setup(
        tmp_path, drop_project=("builds/manuscript/BUILDS.md",))
    to = tmp_path / "inputs"
    r = to_references(proj, refs, record, to)
    assert r.returncode == 2
    assert str(proj / "builds" / "manuscript" / "BUILDS.md") in r.stderr
    assert not to.exists()


def test_a_ledger_with_no_build_is_refused(tmp_path):
    proj, refs, record = references_setup(
        tmp_path, project_files={"builds/manuscript/BUILDS.md": LEDGER_HEADER.encode("utf-8")})
    to = tmp_path / "inputs"
    r = to_references(proj, refs, record, to)
    assert r.returncode == 2
    assert "no build" in r.stderr
    assert not to.exists()


def test_a_missing_snapshot_of_the_latest_build_is_refused(tmp_path):
    proj, refs, record = references_setup(tmp_path, drop_project=("builds/manuscript/v002.md",))
    to = tmp_path / "inputs"
    r = to_references(proj, refs, record, to)
    assert r.returncode == 2
    assert str(proj / "builds" / "manuscript" / "v002.md") in r.stderr
    assert not to.exists()


def test_references_folder_without_refs_yaml_is_refused(tmp_path):
    proj, refs, record = references_setup(tmp_path, drop_references=("refs.yaml",))
    to = tmp_path / "inputs"
    r = to_references(proj, refs, record, to)
    assert r.returncode == 2
    assert str(refs / "refs.yaml") in r.stderr
    assert not to.exists()


def test_the_older_inputs_are_no_longer_asked_for(tmp_path):
    # The procedure reads no author draft, citation log, or prior checks.
    proj, refs, record = references_setup(
        tmp_path, drop_project=("author_draft.md", "audit/citation_log.yaml"),
        drop_references=("prior_checks.json",))
    to = tmp_path / "inputs"
    r = to_references(proj, refs, record, to)
    assert r.returncode == 0, r.stderr


def test_every_missing_file_is_named(tmp_path):
    proj, refs, record = references_setup(tmp_path, drop_project=("builds/manuscript/v002.md",),
                                          drop_references=("metadata_cache.json",))
    record.unlink()
    to = tmp_path / "inputs"
    r = to_references(proj, refs, record, to, "--source", "missing_draft.md")
    assert r.returncode == 2
    for path in (proj / "missing_draft.md", proj / "builds" / "manuscript" / "v002.md",
                 record, refs / "metadata_cache.json"):
        assert str(path) in r.stderr
    assert not to.exists()


def test_a_source_text_landing_on_another_inputs_name_is_refused(tmp_path):
    proj, refs, record = references_setup(tmp_path, project_files={"draft.md": b"a draft\n"})
    to = tmp_path / "inputs"
    r = to_references(proj, refs, record, to, "--source", "draft.md")
    assert r.returncode == 2
    assert "draft.md" in r.stderr
    assert not to.exists()


# W3. The verification-to-pipeline copy.

STREAMS = ("prose", "citations", "data", "build")


def results_run(tmp_path, stream, decisions=(), name="run1"):
    """A synthetic run folder holding a results file in the slice's form."""
    run = tmp_path / "runs" / name
    run.mkdir(parents=True, exist_ok=True)
    results = {
        "schema": "verification-results",
        "schema_version": 1,
        "stream": stream,
        "run_id": name,
        "procedure_version": "1",
        "inputs": {"draft.md": "0" * 64},
        "items": [{"id": "r01", "needs_decision": True}],
        "decisions": list(decisions),
    }
    # Indented and unsorted keys, so a copy that rewrote the file would not match.
    (run / "results.json").write_text(json.dumps(results, indent=3) + "\n", encoding="utf-8")
    return run


@pytest.mark.parametrize("stream", STREAMS)
def test_results_land_under_the_streams_name_byte_for_byte(tmp_path, stream):
    run = results_run(tmp_path, stream)
    proj = project(tmp_path)
    r = call("results_to_pipeline.py", "--run", run, "--stream", stream, "--project", proj)
    assert r.returncode == 0, r.stderr
    dest = proj / "verification" / (stream + ".json")
    assert dest.read_bytes() == (run / "results.json").read_bytes()
    assert str(dest) in r.stdout
    assert sorted(tree(proj / "verification")) == [stream + ".json"]


def test_second_copy_after_a_decision_replaces_the_first(tmp_path):
    proj = project(tmp_path)
    run = results_run(tmp_path, "citations")
    assert call("results_to_pipeline.py", "--run", run, "--stream", "citations",
                "--project", proj).returncode == 0
    decision = {"item": "r01", "decision": "approved", "by": "story scholar",
                "at": "2026-10-29T10:00:00-07:00", "run_id": "run1"}
    results_run(tmp_path, "citations", decisions=[decision])
    r = call("results_to_pipeline.py", "--run", run, "--stream", "citations", "--project", proj)
    assert r.returncode == 0, r.stderr
    copied = (proj / "verification" / "citations.json").read_bytes()
    assert copied == (run / "results.json").read_bytes()
    assert b"approved" in copied


def test_results_copy_leaves_other_streams_alone(tmp_path):
    proj = project(tmp_path)
    data_run = results_run(tmp_path, "data", name="data_run")
    refs_run = results_run(tmp_path, "citations", name="refs_run")
    call("results_to_pipeline.py", "--run", data_run, "--stream", "data", "--project", proj)
    call("results_to_pipeline.py", "--run", refs_run, "--stream", "citations", "--project", proj)
    assert tree(proj / "verification") == {
        "data.json": (data_run / "results.json").read_bytes(),
        "citations.json": (refs_run / "results.json").read_bytes(),
    }


def test_stream_mismatch_is_refused_and_writes_nothing(tmp_path):
    proj = project(tmp_path)
    run = results_run(tmp_path, "data")
    r = call("results_to_pipeline.py", "--run", run, "--stream", "citations", "--project", proj)
    assert r.returncode == 2
    assert "data" in r.stderr and "citations" in r.stderr
    assert not (proj / "verification").exists()


def test_mismatch_leaves_an_older_copy_in_place(tmp_path):
    proj = project(tmp_path)
    good = results_run(tmp_path, "citations", name="good")
    call("results_to_pipeline.py", "--run", good, "--stream", "citations", "--project", proj)
    before = tree(proj)
    bad = results_run(tmp_path, "data", name="bad")
    r = call("results_to_pipeline.py", "--run", bad, "--stream", "citations", "--project", proj)
    assert r.returncode == 2
    assert tree(proj) == before


def test_run_without_results_file_is_refused(tmp_path):
    proj = project(tmp_path)
    run = tmp_path / "runs" / "stopped"
    run.mkdir(parents=True)
    (run / "manifest.json").write_text("{}\n", encoding="utf-8")
    r = call("results_to_pipeline.py", "--run", run, "--stream", "citations", "--project", proj)
    assert r.returncode == 2
    assert str(run / "results.json") in r.stderr
    assert not (proj / "verification").exists()


def test_unknown_stream_is_refused(tmp_path):
    proj = project(tmp_path)
    run = results_run(tmp_path, "selftest")
    r = call("results_to_pipeline.py", "--run", run, "--stream", "selftest", "--project", proj)
    assert r.returncode == 2
    assert "selftest" in r.stderr
    assert not (proj / "verification").exists()


def test_missing_project_is_refused_for_results(tmp_path):
    run = results_run(tmp_path, "citations")
    missing = tmp_path / "no_project"
    r = call("results_to_pipeline.py", "--run", run, "--stream", "citations", "--project", missing)
    assert r.returncode == 2
    assert str(missing) in r.stderr
    assert not missing.exists()


# Q1. Results copied back for each product.

@pytest.mark.parametrize("stream", STREAMS)
def test_results_for_a_product_land_in_its_folder_byte_for_byte(tmp_path, stream):
    run = results_run(tmp_path, stream)
    proj = project(tmp_path)
    assert not (proj / "verification").exists()
    r = call("results_to_pipeline.py", "--run", run, "--stream", stream, "--project", proj,
             "--product", "appendix")
    assert r.returncode == 0, r.stderr
    dest = proj / "verification" / "appendix" / (stream + ".json")
    assert dest.read_bytes() == (run / "results.json").read_bytes()
    assert str(dest) in r.stdout
    assert sorted(tree(proj / "verification")) == [os.path.join("appendix", stream + ".json")]


def test_two_products_keep_their_own_results(tmp_path):
    proj = project(tmp_path)
    (proj / "verification").mkdir()
    (proj / "verification" / "README.md").write_text("Results go here.\n", encoding="utf-8")
    first = results_run(tmp_path, "citations", name="proposal_run")
    second = results_run(tmp_path, "citations", name="appendix_run")
    data = results_run(tmp_path, "data", name="appendix_data")
    for run, stream, product in ((first, "citations", "proposal"),
                                 (second, "citations", "appendix"),
                                 (data, "data", "appendix")):
        r = call("results_to_pipeline.py", "--run", run, "--stream", stream, "--project", proj,
                 "--product", product)
        assert r.returncode == 0, r.stderr
    assert tree(proj / "verification") == {
        "README.md": b"Results go here.\n",
        os.path.join("proposal", "citations.json"): (first / "results.json").read_bytes(),
        os.path.join("appendix", "citations.json"): (second / "results.json").read_bytes(),
        os.path.join("appendix", "data.json"): (data / "results.json").read_bytes(),
    }


def test_product_copy_after_a_decision_replaces_the_first(tmp_path):
    proj = project(tmp_path)
    run = results_run(tmp_path, "prose")
    assert call("results_to_pipeline.py", "--run", run, "--stream", "prose",
                "--project", proj, "--product", "proposal").returncode == 0
    decision = {"item": "r01", "decision": "held", "by": "story scholar",
                "at": "2026-10-30T10:00:00-07:00", "run_id": "run1"}
    results_run(tmp_path, "prose", decisions=[decision])
    r = call("results_to_pipeline.py", "--run", run, "--stream", "prose", "--project", proj,
             "--product", "proposal")
    assert r.returncode == 0, r.stderr
    copied = (proj / "verification" / "proposal" / "prose.json").read_bytes()
    assert copied == (run / "results.json").read_bytes()
    assert b"held" in copied


@pytest.mark.parametrize("name", ["..", ".", "a/b", "../outside", "two words", ""])
def test_product_name_that_is_not_one_plain_folder_name_is_refused(tmp_path, name):
    proj = project(tmp_path)
    run = results_run(tmp_path, "citations")
    before = tree(tmp_path)
    r = call("results_to_pipeline.py", "--run", run, "--stream", "citations", "--project", proj,
             "--product", name)
    assert r.returncode == 2
    assert "product" in r.stderr
    assert tree(tmp_path) == before
    assert not (proj / "verification").exists()


def test_product_mismatch_is_refused_and_writes_nothing(tmp_path):
    proj = project(tmp_path)
    run = results_run(tmp_path, "data")
    r = call("results_to_pipeline.py", "--run", run, "--stream", "citations", "--project", proj,
             "--product", "proposal")
    assert r.returncode == 2
    assert not (proj / "verification").exists()


def test_results_file_that_is_not_json_is_refused(tmp_path):
    proj = project(tmp_path)
    run = tmp_path / "runs" / "broken"
    run.mkdir(parents=True)
    (run / "results.json").write_text("stream: citations\n", encoding="utf-8")
    r = call("results_to_pipeline.py", "--run", run, "--stream", "citations", "--project", proj)
    assert r.returncode == 2
    assert not (proj / "verification").exists()


# W9. The project-to-build copy.

BUILD_PROJECT = {
    "manuscript.md": b"# Test\n\nThis is a test manuscript.\n",
    "slides.md": b"# Slides\n\nOne slide.\n",
    "numbers.yml": b"n: {value: 3}\n",
    "Makefile": b"manuscript:\n\techo build\n",
    "audit/session_writes.jsonl": (b'{"actor": "ai", "path": "builds/manuscript/v001.md", '
                                   b'"session": "s1", "tool": "edited"}\n'),
    "audit/citation_log.yaml": b"citations: {}\n",
    "builds/manuscript/v001.md": b"This is a short test manuscript.\n",
    "builds/manuscript/BUILDS.md": b"| version |\n|---|\n| v001 |\n",
    "verification/citations.json": b"{}\n",
}


def build_project(tmp_path, drop=(), with_git=True):
    proj = tmp_path / "project"
    write_tree(proj, {k: v for k, v in BUILD_PROJECT.items() if k not in drop})
    if with_git:
        write_tree(proj / ".git", {"HEAD": b"ref: refs/heads/main\n",
                                   "objects/ab/cdef": b"\x00\x01"})
    return proj


def tar_members(path):
    import tarfile
    with tarfile.open(str(path)) as tf:
        return tf.getmembers(), {m.name: tf.extractfile(m).read() for m in tf.getmembers()
                                 if m.isfile()}


def test_packing_the_same_project_twice_gives_identical_bytes(tmp_path):
    proj = build_project(tmp_path)
    first, second = tmp_path / "inputs1", tmp_path / "inputs2"
    for to in (first, second):
        r = call("project_to_build.py", "--project", proj, "--to", to)
        assert r.returncode == 0, r.stderr
    assert (first / "project.tar").read_bytes() == (second / "project.tar").read_bytes()


def test_packing_ignores_file_times_and_modes(tmp_path):
    import os
    proj = build_project(tmp_path)
    first = tmp_path / "inputs1"
    assert call("project_to_build.py", "--project", proj, "--to", first).returncode == 0
    os.utime(str(proj / "manuscript.md"), (1700000000, 1700000000))
    os.chmod(str(proj / "slides.md"), 0o600)
    second = tmp_path / "inputs2"
    assert call("project_to_build.py", "--project", proj, "--to", second).returncode == 0
    assert (first / "project.tar").read_bytes() == (second / "project.tar").read_bytes()


def test_archive_lists_every_project_file_with_time_0_and_mode_0644_and_no_git(tmp_path):
    proj = build_project(tmp_path)
    to = tmp_path / "inputs"
    r = call("project_to_build.py", "--project", proj, "--to", to)
    assert r.returncode == 0, r.stderr
    members, data = tar_members(to / "project.tar")
    names = [m.name for m in members]
    assert names == sorted(BUILD_PROJECT)
    assert data == BUILD_PROJECT
    assert not [n for n in names if n == ".git" or n.startswith(".git/")]
    for m in members:
        assert m.isfile()
        assert m.mtime == 0
        assert m.mode == 0o644
        assert (m.uid, m.gid, m.uname, m.gname) == (0, 0, "", "")
    raw = (to / "project.tar").read_bytes()
    assert raw[257:265] == b"ustar\x0000"  # the USTAR magic and version, not GNU or PAX


def test_record_and_default_source_are_copied_byte_for_byte_beside_the_archive(tmp_path):
    proj = build_project(tmp_path)
    to = tmp_path / "inputs"
    r = call("project_to_build.py", "--project", proj, "--to", to)
    assert r.returncode == 0, r.stderr
    assert sorted(tree(to)) == ["manuscript.md", "project.tar", "session_writes.jsonl"]
    assert (to / "session_writes.jsonl").read_bytes() == BUILD_PROJECT["audit/session_writes.jsonl"]
    assert (to / "manuscript.md").read_bytes() == BUILD_PROJECT["manuscript.md"]
    assert str(to) in r.stdout


def test_two_source_options_copy_both(tmp_path):
    proj = build_project(tmp_path)
    to = tmp_path / "inputs"
    r = call("project_to_build.py", "--project", proj, "--to", to,
             "--source", "manuscript.md", "--source", "slides.md")
    assert r.returncode == 0, r.stderr
    assert sorted(tree(to)) == ["manuscript.md", "project.tar", "session_writes.jsonl",
                                "slides.md"]
    assert (to / "slides.md").read_bytes() == BUILD_PROJECT["slides.md"]
    assert (to / "manuscript.md").read_bytes() == BUILD_PROJECT["manuscript.md"]


def test_build_copy_leaves_the_project_unchanged(tmp_path):
    proj = build_project(tmp_path)
    before = tree(proj)
    assert call("project_to_build.py", "--project", proj, "--to", tmp_path / "inputs").returncode == 0
    assert tree(proj) == before


def test_existing_build_inputs_folder_is_refused(tmp_path):
    proj = build_project(tmp_path)
    to = tmp_path / "inputs"
    to.mkdir()
    r = call("project_to_build.py", "--project", proj, "--to", to)
    assert r.returncode == 2
    assert str(to) in r.stderr
    assert list(to.iterdir()) == []


def test_missing_session_writes_record_is_refused(tmp_path):
    proj = build_project(tmp_path, drop=("audit/session_writes.jsonl",))
    to = tmp_path / "inputs"
    r = call("project_to_build.py", "--project", proj, "--to", to)
    assert r.returncode == 2
    assert str(proj / "audit" / "session_writes.jsonl") in r.stderr
    assert not to.exists()


def test_missing_source_is_refused(tmp_path):
    proj = build_project(tmp_path)
    to = tmp_path / "inputs"
    r = call("project_to_build.py", "--project", proj, "--to", to,
             "--source", "manuscript.md", "--source", "paper.md")
    assert r.returncode == 2
    assert str(proj / "paper.md") in r.stderr
    assert not to.exists()


def test_every_missing_build_input_is_named(tmp_path):
    proj = build_project(tmp_path, drop=("audit/session_writes.jsonl", "manuscript.md"))
    to = tmp_path / "inputs"
    r = call("project_to_build.py", "--project", proj, "--to", to)
    assert r.returncode == 2
    assert str(proj / "audit" / "session_writes.jsonl") in r.stderr
    assert str(proj / "manuscript.md") in r.stderr
    assert not to.exists()


def test_two_files_landing_under_one_name_are_refused(tmp_path):
    proj = build_project(tmp_path)
    write_tree(proj, {"other/manuscript.md": b"another\n"})
    to = tmp_path / "inputs"
    r = call("project_to_build.py", "--project", proj, "--to", to,
             "--source", "manuscript.md", "--source", "other/manuscript.md")
    assert r.returncode == 2
    assert "manuscript.md" in r.stderr
    assert not to.exists()


# W12. The project-to-data copy.

DATA_TOP = {
    "pipeline.yaml": b"steps:\n  - s1_results.py\n",
    "acquisition.yaml": b"sources: []\n",
    "params.yaml": b"temperature: 0.7\n",
    "numbers.yml": b'numbers:\n  n: {value: "3", from: out.json, field: n}\n',
    "s1_results.py": b"print('results')\r\n",
    "out.json": b'{"n": 3}',
    "manuscript.md": b"# Test\n\nThis is a test manuscript.\n",
}
DATA_BELOW = {
    "builds/manuscript/v001.md": b"This is a test manuscript.\n",
    "audit/session_writes.jsonl": b'{"actor": "ai"}\n',
    "verification/data.json": b"{}\n",
    "analysis/extra.py": b"print('below')\n",
}
DECLARATIONS = ("pipeline.yaml", "acquisition.yaml", "params.yaml", "numbers.yml")


def data_project(tmp_path, drop=()):
    proj = tmp_path / "project"
    write_tree(proj, {k: v for k, v in dict(DATA_TOP, **DATA_BELOW).items() if k not in drop})
    return proj


def test_top_level_files_are_copied_byte_for_byte(tmp_path):
    proj = data_project(tmp_path)
    to = tmp_path / "inputs" / "data"
    r = call("project_to_data.py", "--project", proj, "--to", to)
    assert r.returncode == 0, r.stderr
    assert tree(to) == DATA_TOP
    assert str(to) in r.stdout


def test_nothing_under_a_subfolder_is_copied(tmp_path):
    proj = data_project(tmp_path)
    to = tmp_path / "inputs"
    assert call("project_to_data.py", "--project", proj, "--to", to).returncode == 0
    assert [p for p in to.iterdir() if p.is_dir()] == []
    for name in ("builds", "audit", "verification", "analysis"):
        assert not (to / name).exists()
    assert not set(tree(to)) & {Path(k).name for k in DATA_BELOW}


def test_data_copy_leaves_the_project_unchanged(tmp_path):
    proj = data_project(tmp_path)
    before = tree(proj)
    assert call("project_to_data.py", "--project", proj, "--to", tmp_path / "inputs").returncode == 0
    assert tree(proj) == before


def test_existing_data_inputs_folder_is_refused(tmp_path):
    proj = data_project(tmp_path)
    to = tmp_path / "inputs"
    to.mkdir()
    r = call("project_to_data.py", "--project", proj, "--to", to)
    assert r.returncode == 2
    assert str(to) in r.stderr
    assert list(to.iterdir()) == []


@pytest.mark.parametrize("name", DECLARATIONS)
def test_each_missing_declaration_file_is_refused(tmp_path, name):
    proj = data_project(tmp_path, drop=(name,))
    to = tmp_path / "inputs"
    r = call("project_to_data.py", "--project", proj, "--to", to)
    assert r.returncode == 2
    assert str(proj / name) in r.stderr
    for other in DECLARATIONS:
        if other != name:
            assert str(proj / other) not in r.stderr
    assert not to.exists()


def test_every_missing_declaration_file_is_named(tmp_path):
    proj = data_project(tmp_path, drop=DECLARATIONS)
    to = tmp_path / "inputs"
    r = call("project_to_data.py", "--project", proj, "--to", to)
    assert r.returncode == 2
    for name in DECLARATIONS:
        assert str(proj / name) in r.stderr
    assert not to.exists()


def test_missing_project_is_refused_for_data(tmp_path):
    to = tmp_path / "inputs"
    r = call("project_to_data.py", "--project", tmp_path / "nowhere", "--to", to)
    assert r.returncode == 2
    assert str(tmp_path / "nowhere") in r.stderr
    assert not to.exists()


# V4. The data copy also takes the record of the AI's file edits and each script and
# helper the pipeline names at its path inside the project.

NESTED_PIPELINE = (b"helpers: [lib/params_io.py]\n"
                   b"steps:\n"
                   b"  - {id: results, phase: analysis, script: code/s1_results.py,\n"
                   b"     inputs: [raw.json], outputs: [out.json]}\n"
                   b"  - {id: table, phase: analysis, script: s2_table.py, inputs: [out.json],\n"
                   b"     outputs: [table.md]}\n")
NESTED_SCRIPTS = {
    "code/s1_results.py": b"import params_io\r\nprint('results')\n",
    "lib/params_io.py": b"VALUES = {}\n\xe9\n",
    "s2_table.py": b"print('table')\n",
}
FILE_EDITS = (b"- id: e01\n  path: code/s1_results.py\n  kind: edit\n  before: a\n  after: b\n"
              b"  rationale: ''\n  session: s\n  session_ref: S000000000000\n")


def nested_project(tmp_path, drop=()):
    files = dict(DATA_TOP, **DATA_BELOW)
    files["pipeline.yaml"] = NESTED_PIPELINE
    files.update(NESTED_SCRIPTS)
    return write_tree(tmp_path / "project", {k: v for k, v in files.items() if k not in drop})


def edits_record(tmp_path, data=FILE_EDITS):
    return record_file(tmp_path, "file_edits.yaml", data)


def test_each_script_and_helper_in_a_subfolder_is_copied_at_its_path(tmp_path):
    proj = nested_project(tmp_path)
    to = tmp_path / "inputs"
    r = call("project_to_data.py", "--project", proj, "--to", to)
    assert r.returncode == 0, r.stderr
    expected = dict(DATA_TOP)
    expected["pipeline.yaml"] = NESTED_PIPELINE
    expected.update(NESTED_SCRIPTS)
    assert tree(to) == expected
    for name in DATA_BELOW:
        assert not (to / name).exists()


def test_the_record_of_the_ais_file_edits_lands_as_file_edits_yaml_byte_for_byte(tmp_path):
    proj = data_project(tmp_path)
    record = edits_record(tmp_path)
    to = tmp_path / "inputs"
    r = call("project_to_data.py", "--project", proj, "--to", to, "--file-edits", record)
    assert r.returncode == 0, r.stderr
    assert tree(to) == dict(DATA_TOP, **{"file_edits.yaml": FILE_EDITS})


def test_without_the_record_no_file_edits_yaml_is_written(tmp_path):
    proj = data_project(tmp_path)
    to = tmp_path / "inputs"
    assert call("project_to_data.py", "--project", proj, "--to", to).returncode == 0
    assert not (to / "file_edits.yaml").exists()


def test_a_missing_record_of_the_ais_file_edits_is_refused_with_the_command_that_writes_it(tmp_path):
    proj = data_project(tmp_path)
    to = tmp_path / "inputs"
    missing = tmp_path / "audit_out" / "file_edits.yaml"
    r = call("project_to_data.py", "--project", proj, "--to", to, "--file-edits", missing)
    assert r.returncode == 2
    assert str(missing) in r.stderr
    assert "write-out file-edits" in r.stderr
    assert not to.exists()


def test_a_project_file_named_like_the_record_is_refused_beside_the_record(tmp_path):
    proj = data_project(tmp_path)
    (proj / "file_edits.yaml").write_bytes(b"[]\n")
    to = tmp_path / "inputs"
    r = call("project_to_data.py", "--project", proj, "--to", to,
             "--file-edits", edits_record(tmp_path))
    assert r.returncode == 2
    assert "file_edits.yaml" in r.stderr
    assert not to.exists()


@pytest.mark.parametrize("name", sorted(NESTED_SCRIPTS))
def test_each_missing_script_or_helper_is_refused(tmp_path, name):
    proj = nested_project(tmp_path, drop=(name,))
    to = tmp_path / "inputs"
    r = call("project_to_data.py", "--project", proj, "--to", to)
    assert r.returncode == 2
    assert str(proj / name) in r.stderr
    for other in NESTED_SCRIPTS:
        if other != name:
            assert str(proj / other) not in r.stderr
    assert not to.exists()


def test_every_missing_data_input_is_named(tmp_path):
    proj = nested_project(tmp_path, drop=tuple(NESTED_SCRIPTS) + ("numbers.yml",))
    to = tmp_path / "inputs"
    missing = tmp_path / "nowhere" / "file_edits.yaml"
    r = call("project_to_data.py", "--project", proj, "--to", to, "--file-edits", missing)
    assert r.returncode == 2
    for path in [proj / name for name in NESTED_SCRIPTS] + [proj / "numbers.yml", missing]:
        assert str(path) in r.stderr
    assert not to.exists()


@pytest.mark.parametrize("script", ["../outside.py", "/tmp/outside.py", "code/../../outside.py"])
def test_a_script_outside_the_project_is_refused(tmp_path, script):
    proj = data_project(tmp_path)
    (proj / "pipeline.yaml").write_text("steps:\n  - {id: s, script: %s}\n" % script, encoding="utf-8")
    (tmp_path / "outside.py").write_bytes(b"print('outside')\n")
    to = tmp_path / "inputs"
    r = call("project_to_data.py", "--project", proj, "--to", to)
    assert r.returncode == 2
    assert script in r.stderr
    assert not to.exists()


def test_a_pipeline_file_that_is_not_yaml_is_refused(tmp_path):
    proj = data_project(tmp_path)
    (proj / "pipeline.yaml").write_bytes(b"steps: [unclosed\n")
    to = tmp_path / "inputs"
    r = call("project_to_data.py", "--project", proj, "--to", to)
    assert r.returncode == 2
    assert str(proj / "pipeline.yaml") in r.stderr
    assert not to.exists()


def test_the_nested_data_copy_leaves_the_project_and_the_record_unchanged(tmp_path):
    proj = nested_project(tmp_path)
    record = edits_record(tmp_path)
    before = (tree(proj), record.read_bytes())
    assert call("project_to_data.py", "--project", proj, "--to", tmp_path / "inputs",
                "--file-edits", record).returncode == 0
    assert (tree(proj), record.read_bytes()) == before


# V4. The project-to-data-phases copy.

PHASE_TEXT = b"# Test\n\nWe kept respondents aged 18 or older.\r\n"
SLIDES_TEXT = b"# Slides\n\nWe fit one model."
LEDGER = (b"| version | date | purpose |\n|---|---|---|\n"
          b"| v001 | 2026-10-01 | first |\n| v010 | 2026-10-03 | tenth |\n| v002 | 2026-10-02 | second |\n")
PHASE_PROJECT = dict(NESTED_SCRIPTS, **{
    "pipeline.yaml": NESTED_PIPELINE,
    "manuscript.md": b"# Test\n\n{{num:min_age}}\n",
    "numbers.yml": b"numbers: {}\n",
    "raw.json": b"{}\n",
    "builds/manuscript/BUILDS.md": LEDGER,
    "builds/manuscript/v001.md": b"the first build\n",
    "builds/manuscript/v002.md": b"the second build\n",
    "builds/manuscript/v010.md": PHASE_TEXT,
    "builds/manuscript/v011.md": b"a text no ledger row names\n",
    "builds/slides/BUILDS.md": b"| version | date |\n|---|---|\n| v003 | 2026-10-04 |\n",
    "builds/slides/v003.md": SLIDES_TEXT,
    "audit/rationales.yaml": b"[]\n",
    "analysis/extra.py": b"print('below')\n",
})


def phase_project(tmp_path, drop=()):
    return write_tree(tmp_path / "project", {k: v for k, v in PHASE_PROJECT.items() if k not in drop})


def phase_expected(text=PHASE_TEXT):
    expected = dict(NESTED_SCRIPTS)
    expected["pipeline.yaml"] = NESTED_PIPELINE
    expected["final_text.md"] = text
    return expected


def test_the_pipeline_its_scripts_and_the_latest_builds_text_are_copied_byte_for_byte(tmp_path):
    proj = phase_project(tmp_path)
    to = tmp_path / "inputs" / "phases"
    r = call("project_to_data_phases.py", "--project", proj, "--to", to)
    assert r.returncode == 0, r.stderr
    assert str(to) in r.stdout
    assert tree(to) == phase_expected()


def test_the_builds_dir_option_names_the_products_builds_folder(tmp_path):
    proj = phase_project(tmp_path)
    to = tmp_path / "inputs"
    r = call("project_to_data_phases.py", "--project", proj, "--to", to,
             "--builds-dir", "builds/slides")
    assert r.returncode == 0, r.stderr
    assert tree(to) == phase_expected(SLIDES_TEXT)


def test_two_builds_dirs_join_their_latest_texts_in_the_order_given(tmp_path):
    proj = phase_project(tmp_path)
    to = tmp_path / "inputs"
    r = call("project_to_data_phases.py", "--project", proj, "--to", to,
             "--builds-dir", "builds/manuscript", "--builds-dir", "builds/slides")
    assert r.returncode == 0, r.stderr
    assert (to / "final_text.md").read_bytes() == PHASE_TEXT + b"\n" + SLIDES_TEXT
    r = call("project_to_data_phases.py", "--project", proj, "--to", tmp_path / "other",
             "--builds-dir", "builds/slides", "--builds-dir", "builds/manuscript")
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "other" / "final_text.md").read_bytes() == SLIDES_TEXT + b"\n\n" + PHASE_TEXT


def test_the_phases_copy_leaves_the_project_unchanged(tmp_path):
    proj = phase_project(tmp_path)
    before = tree(proj)
    assert call("project_to_data_phases.py", "--project", proj,
                "--to", tmp_path / "inputs").returncode == 0
    assert tree(proj) == before


def test_an_existing_phases_inputs_folder_is_refused(tmp_path):
    proj = phase_project(tmp_path)
    to = tmp_path / "inputs"
    to.mkdir()
    r = call("project_to_data_phases.py", "--project", proj, "--to", to)
    assert r.returncode == 2
    assert str(to) in r.stderr
    assert list(to.iterdir()) == []


def test_a_missing_ledger_is_refused(tmp_path):
    proj = phase_project(tmp_path, drop=("builds/manuscript/BUILDS.md",))
    to = tmp_path / "inputs"
    r = call("project_to_data_phases.py", "--project", proj, "--to", to)
    assert r.returncode == 2
    assert str(proj / "builds" / "manuscript" / "BUILDS.md") in r.stderr
    assert not to.exists()


def test_a_ledger_that_lists_no_build_is_refused(tmp_path):
    proj = phase_project(tmp_path)
    (proj / "builds" / "manuscript" / "BUILDS.md").write_bytes(b"| version | date |\n|---|---|\n")
    to = tmp_path / "inputs"
    r = call("project_to_data_phases.py", "--project", proj, "--to", to)
    assert r.returncode == 2
    assert "lists no build" in r.stderr
    assert not to.exists()


def test_a_missing_text_of_the_latest_build_is_refused(tmp_path):
    proj = phase_project(tmp_path, drop=("builds/manuscript/v010.md",))
    to = tmp_path / "inputs"
    r = call("project_to_data_phases.py", "--project", proj, "--to", to)
    assert r.returncode == 2
    assert str(proj / "builds" / "manuscript" / "v010.md") in r.stderr
    assert not to.exists()


@pytest.mark.parametrize("name", ["pipeline.yaml"] + sorted(NESTED_SCRIPTS))
def test_each_missing_phases_input_is_refused(tmp_path, name):
    proj = phase_project(tmp_path, drop=(name,))
    to = tmp_path / "inputs"
    r = call("project_to_data_phases.py", "--project", proj, "--to", to)
    assert r.returncode == 2
    assert str(proj / name) in r.stderr
    assert not to.exists()


def test_every_missing_phases_input_is_named(tmp_path):
    proj = phase_project(tmp_path, drop=tuple(NESTED_SCRIPTS) + ("builds/slides/v003.md",))
    to = tmp_path / "inputs"
    r = call("project_to_data_phases.py", "--project", proj, "--to", to,
             "--builds-dir", "builds/manuscript", "--builds-dir", "builds/slides")
    assert r.returncode == 2
    for path in [proj / name for name in NESTED_SCRIPTS] + [proj / "builds" / "slides" / "v003.md"]:
        assert str(path) in r.stderr
    assert not to.exists()


def test_a_missing_project_is_refused_for_the_phases(tmp_path):
    to = tmp_path / "inputs"
    r = call("project_to_data_phases.py", "--project", tmp_path / "nowhere", "--to", to)
    assert r.returncode == 2
    assert str(tmp_path / "nowhere") in r.stderr
    assert not to.exists()


# W17. The project-to-prose copy.

PROSE_PROJECT = {
    "manuscript.md": b"# Test\n\nThis is a test manuscript.\nAn added sentence.\n",
    "slides.md": b"# Slides\n\nA slide sentence.\n",
    "author_draft.md": b"# Test\n\nThis is a test manuscript.\n",
    "audit/rationales.yaml": b"- id: r01\n  anchor: \"An added sentence.\"\n  kind: insert\n",
    "audit/citation_log.yaml": b"citations: {}\n",
    "numbers.yml": b"numbers: {}\n",
}
PROSE_FOLDER = {
    "versions.yaml": b"versions:\n  - {version: author_draft, file: author_draft.md}\n",
    "author_edits.yaml": b"[]\n",
    "recorded_judge.json": b"{}\n",
    "expected_rationales.yaml": b"[]\n",
}
PROSE_COPIES = {
    "baseline.md": "author_draft.md",
    "revised.md": "manuscript.md",
    "rationales.yaml": "audit/rationales.yaml",
}


def prose_setup(tmp_path, drop_project=(), drop_prose=()):
    proj = write_tree(tmp_path / "project",
                      {k: v for k, v in PROSE_PROJECT.items() if k not in drop_project})
    prose = write_tree(tmp_path / "prose",
                       {k: v for k, v in PROSE_FOLDER.items() if k not in drop_prose})
    return proj, prose


def test_each_prose_input_lands_under_its_name_with_identical_bytes(tmp_path):
    proj, prose = prose_setup(tmp_path)
    to = tmp_path / "inputs" / "prose"
    r = call("project_to_prose.py", "--project", proj, "--prose", prose, "--to", to)
    assert r.returncode == 0, r.stderr
    assert str(to) in r.stdout
    expected = {name: PROSE_PROJECT[src] for name, src in PROSE_COPIES.items()}
    expected["versions.yaml"] = PROSE_FOLDER["versions.yaml"]
    assert tree(to) == expected


def test_revised_carries_the_source_texts_checksum(tmp_path):
    proj, prose = prose_setup(tmp_path)
    to = tmp_path / "inputs"
    assert call("project_to_prose.py", "--project", proj, "--prose", prose,
                "--to", to).returncode == 0
    digest = hashlib.sha256((proj / "manuscript.md").read_bytes()).hexdigest()
    assert hashlib.sha256((to / "revised.md").read_bytes()).hexdigest() == digest


def test_source_option_names_the_revised_text(tmp_path):
    proj, prose = prose_setup(tmp_path)
    to = tmp_path / "inputs"
    r = call("project_to_prose.py", "--project", proj, "--prose", prose, "--to", to,
             "--source", "slides.md")
    assert r.returncode == 0, r.stderr
    assert (to / "revised.md").read_bytes() == PROSE_PROJECT["slides.md"]


def test_prose_copy_leaves_both_folders_unchanged(tmp_path):
    proj, prose = prose_setup(tmp_path)
    before = (tree(proj), tree(prose))
    assert call("project_to_prose.py", "--project", proj, "--prose", prose,
                "--to", tmp_path / "inputs").returncode == 0
    assert (tree(proj), tree(prose)) == before


def test_existing_prose_inputs_folder_is_refused(tmp_path):
    proj, prose = prose_setup(tmp_path)
    to = tmp_path / "inputs"
    to.mkdir()
    (to / "revised.md").write_bytes(b"an earlier run's text\n")
    r = call("project_to_prose.py", "--project", proj, "--prose", prose, "--to", to)
    assert r.returncode == 2
    assert str(to) in r.stderr
    assert tree(to) == {"revised.md": b"an earlier run's text\n"}


@pytest.mark.parametrize("name", ["manuscript.md", "author_draft.md", "audit/rationales.yaml"])
def test_each_missing_project_file_is_refused(tmp_path, name):
    proj, prose = prose_setup(tmp_path, drop_project=(name,))
    to = tmp_path / "inputs"
    r = call("project_to_prose.py", "--project", proj, "--prose", prose, "--to", to)
    assert r.returncode == 2
    assert str(proj / name) in r.stderr
    assert not to.exists()


def test_a_list_of_the_authors_edits_in_the_prose_folder_is_not_copied(tmp_path):
    """The prose procedure 0.3 reads no list of the author's edits (Track V, step V4)."""
    proj, prose = prose_setup(tmp_path)
    to = tmp_path / "inputs"
    assert call("project_to_prose.py", "--project", proj, "--prose", prose, "--to", to).returncode == 0
    assert not (to / "author_edits.yaml").exists()
    proj, prose = prose_setup(tmp_path / "without", drop_prose=("author_edits.yaml",))
    r = call("project_to_prose.py", "--project", proj, "--prose", prose, "--to", tmp_path / "inputs2")
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("name", ["versions.yaml"])
def test_each_missing_prose_file_is_refused(tmp_path, name):
    proj, prose = prose_setup(tmp_path, drop_prose=(name,))
    to = tmp_path / "inputs"
    r = call("project_to_prose.py", "--project", proj, "--prose", prose, "--to", to)
    assert r.returncode == 2
    assert str(prose / name) in r.stderr
    assert not to.exists()


def test_every_missing_prose_input_is_named(tmp_path):
    proj, prose = prose_setup(tmp_path, drop_project=("author_draft.md", "audit/rationales.yaml"),
                              drop_prose=("versions.yaml",))
    to = tmp_path / "inputs"
    r = call("project_to_prose.py", "--project", proj, "--prose", prose, "--to", to,
             "--source", "missing.md")
    assert r.returncode == 2
    for path in (proj / "missing.md", proj / "author_draft.md", proj / "audit" / "rationales.yaml",
                 prose / "versions.yaml"):
        assert str(path) in r.stderr
    assert not to.exists()


# M2. The graphs-to-knowledge-base copy.

PROCEDURE_FILES = {
    "graphs/citations.yaml": b"graph: citations\ncontracts: contracts/citations.yaml\n",
    "graphs/prose.yaml": b"graph: prose\r\ncontracts: contracts/prose.yaml\n",
    "contracts/citations.yaml": b"steps: {}\n",
    "contracts/prose.yaml": b"steps: {}\n\xe9\n",
    "registry.yaml": b"registry_version: 1\nprocedures: []\n",
}
PROCEDURE_EXTRAS = {
    "vg.py": b"print('not copied')\n",
    "README.md": b"# Procedures\n",
    "implementations/citations/check.py": b"pass\n",
    "fixtures/citations/seeded/draft.md": b"A draft.\n",
}
PROCEDURE_PARTS = ("graphs", "contracts", "registry.yaml")


def procedures_setup(tmp_path, drop=()):
    files = dict(PROCEDURE_FILES)
    files.update(PROCEDURE_EXTRAS)
    kept = {k: v for k, v in files.items()
            if k.split("/", 1)[0] not in drop and k not in drop}
    folder = tmp_path / "verification_procedures"
    folder.mkdir()
    return write_tree(folder, kept)


def test_graphs_contracts_and_registry_are_copied_byte_for_byte_and_nothing_else(tmp_path):
    procedures = procedures_setup(tmp_path)
    to = tmp_path / "kb_procedures"
    r = call("graphs_to_kb.py", "--procedures", procedures, "--to", to)
    assert r.returncode == 0, r.stderr
    assert str(to) in r.stdout
    assert tree(to) == PROCEDURE_FILES


def test_graphs_copy_leaves_the_procedures_folder_unchanged(tmp_path):
    procedures = procedures_setup(tmp_path)
    before = tree(procedures)
    assert call("graphs_to_kb.py", "--procedures", procedures,
                "--to", tmp_path / "kb_procedures").returncode == 0
    assert tree(procedures) == before


def test_existing_graphs_copy_folder_is_refused(tmp_path):
    procedures = procedures_setup(tmp_path)
    to = tmp_path / "kb_procedures"
    to.mkdir()
    r = call("graphs_to_kb.py", "--procedures", procedures, "--to", to)
    assert r.returncode == 2
    assert str(to) in r.stderr
    assert tree(to) == {}
    assert list(to.iterdir()) == []


@pytest.mark.parametrize("part", PROCEDURE_PARTS)
def test_each_missing_procedures_part_is_refused(tmp_path, part):
    procedures = procedures_setup(tmp_path, drop=(part,))
    to = tmp_path / "kb_procedures"
    r = call("graphs_to_kb.py", "--procedures", procedures, "--to", to)
    assert r.returncode == 2
    assert str(procedures / part) in r.stderr
    assert not to.exists()


def test_every_missing_procedures_part_is_named(tmp_path):
    procedures = procedures_setup(tmp_path, drop=PROCEDURE_PARTS)
    to = tmp_path / "kb_procedures"
    r = call("graphs_to_kb.py", "--procedures", procedures, "--to", to)
    assert r.returncode == 2
    for part in PROCEDURE_PARTS:
        assert str(procedures / part) in r.stderr
    assert not to.exists()


def test_missing_procedures_folder_is_refused(tmp_path):
    to = tmp_path / "kb_procedures"
    r = call("graphs_to_kb.py", "--procedures", tmp_path / "nowhere", "--to", to)
    assert r.returncode == 2
    assert str(tmp_path / "nowhere") in r.stderr
    assert not to.exists()


def test_the_real_procedures_folder_copies_its_three_parts_whole(tmp_path):
    procedures = ROOT / "verification_procedures"
    to = tmp_path / "kb_procedures"
    r = call("graphs_to_kb.py", "--procedures", procedures, "--to", to)
    assert r.returncode == 0, r.stderr
    expected = {name: data for name, data in tree(procedures).items()
                if name == "registry.yaml" or name.split("/", 1)[0] in ("graphs", "contracts")}
    assert expected and tree(to) == expected


# M2. The knowledge base export to the server's index file.

def test_export_lands_at_the_servers_index_file_byte_for_byte(tmp_path):
    export = record_file(tmp_path, "kb_export.json", b'{"schema": "kb-index"}\r\n\xe9')
    home = tmp_path / "connections_home"
    home.mkdir()
    dest = home / "kb_index.json"
    r = call("kb_export_to_server.py", "--export", export, "--to", dest)
    assert r.returncode == 0, r.stderr
    assert str(dest) in r.stdout
    assert dest.read_bytes() == export.read_bytes()
    assert sorted(tree(home)) == ["kb_index.json"]


def test_a_second_export_replaces_the_older_copy(tmp_path):
    first = record_file(tmp_path, "first.json", b'{"entries": [1, 2, 3]}\n')
    second = record_file(tmp_path, "second.json", b'{"entries": []}\n')
    dest = tmp_path / "kb_index.json"
    for export in (first, second):
        r = call("kb_export_to_server.py", "--export", export, "--to", dest)
        assert r.returncode == 0, r.stderr
    assert dest.read_bytes() == b'{"entries": []}\n'


def test_a_real_kb_export_is_copied_unchanged(tmp_path):
    export = tmp_path / "export.json"
    made = subprocess.run([sys.executable, "-m", "audit_layer.kb", "export", "--out", str(export)],
                          cwd=str(ROOT), capture_output=True, text=True)
    assert made.returncode == 0, made.stderr
    dest = tmp_path / "server" / "kb_index.json"
    dest.parent.mkdir()
    r = call("kb_export_to_server.py", "--export", export, "--to", dest)
    assert r.returncode == 0, r.stderr
    assert dest.read_bytes() == export.read_bytes()


def test_missing_export_file_is_refused_and_writes_nothing(tmp_path):
    dest = tmp_path / "kb_index.json"
    missing = tmp_path / "no_export.json"
    r = call("kb_export_to_server.py", "--export", missing, "--to", dest)
    assert r.returncode == 2
    assert str(missing) in r.stderr
    assert not dest.exists()


def test_missing_export_leaves_an_older_copy_in_place(tmp_path):
    dest = tmp_path / "kb_index.json"
    dest.write_bytes(b'{"older": true}\n')
    r = call("kb_export_to_server.py", "--export", tmp_path / "no_export.json", "--to", dest)
    assert r.returncode == 2
    assert dest.read_bytes() == b'{"older": true}\n'


def test_index_file_in_a_missing_folder_is_refused(tmp_path):
    export = record_file(tmp_path, "kb_export.json", b"{}\n")
    folder = tmp_path / "no_home"
    r = call("kb_export_to_server.py", "--export", export, "--to", folder / "kb_index.json")
    assert r.returncode == 2
    assert str(folder) in r.stderr
    assert not folder.exists()


def test_index_path_that_is_a_folder_is_refused(tmp_path):
    export = record_file(tmp_path, "kb_export.json", b"{}\n")
    folder = tmp_path / "kb_index.json"
    folder.mkdir()
    r = call("kb_export_to_server.py", "--export", export, "--to", folder)
    assert r.returncode == 2
    assert str(folder) in r.stderr
    assert list(folder.iterdir()) == []


# M2. The written-out project's folder into the project.

STORY = ROOT / "examples" / "test_story"
WRITTEN = {
    "written_out.yaml": b"files:\n  - path: audit/sessions.yaml\n",
    "audit/sessions.yaml": b"- id: s1\r\n",
    "audit/transcripts/claude_code/s1.jsonl": b'{"type": "user"}\n\xe9',
    "schema/field_definitions.yaml": b"fields: []\n",
}


def written_folder(tmp_path, drop=()):
    folder = tmp_path / "written"
    folder.mkdir()
    return write_tree(folder, {k: v for k, v in WRITTEN.items() if k not in drop})


def story_written_out(tmp_path):
    """Write the story project out as the audit layer does, through its command line."""
    shutil.copytree(str(STORY / "project"), str(tmp_path / "project"))
    proj = Path(os.path.realpath(str(tmp_path / "project")))
    session = tmp_path / "story_session.jsonl"
    text = (STORY / "sessions" / "claude_code" / "story_session.jsonl").read_text(encoding="utf-8")
    session.write_text(text.replace("{{PROJECT}}", str(proj)), encoding="utf-8")
    env = dict(os.environ, AUDIT_HOME=str(tmp_path / "audit_home"))
    out = tmp_path / "written"
    for args in (["init"], ["capture", "--harness", "claude_code", str(session)],
                 ["write-out", "project", "--project", str(proj), "--out", str(out)]):
        done = subprocess.run([sys.executable, "-m", "audit_layer"] + args, cwd=str(ROOT),
                              env=env, capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
    return proj, out


def test_a_written_out_story_project_is_copied_whole_with_the_same_bytes(tmp_path):
    proj, written = story_written_out(tmp_path)
    to = proj / "records"
    r = call("writeout_to_project.py", "--from", written, "--to", to)
    assert r.returncode == 0, r.stderr
    assert str(to) in r.stdout
    assert "written_out.yaml" in tree(written)
    assert any(name.startswith("audit/transcripts/") for name in tree(written))
    assert tree(to) == tree(written)


def test_written_out_folder_lands_in_a_new_folder(tmp_path):
    written = written_folder(tmp_path)
    to = tmp_path / "project" / "records"
    (tmp_path / "project").mkdir()
    r = call("writeout_to_project.py", "--from", written, "--to", to)
    assert r.returncode == 0, r.stderr
    assert tree(to) == WRITTEN


def test_written_out_folder_lands_in_an_empty_folder(tmp_path):
    written = written_folder(tmp_path)
    to = tmp_path / "records"
    to.mkdir()
    r = call("writeout_to_project.py", "--from", written, "--to", to)
    assert r.returncode == 0, r.stderr
    assert tree(to) == WRITTEN


def test_writeout_copy_leaves_the_written_out_folder_unchanged(tmp_path):
    written = written_folder(tmp_path)
    assert call("writeout_to_project.py", "--from", written,
                "--to", tmp_path / "records").returncode == 0
    assert tree(written) == WRITTEN


def test_folder_without_the_write_outs_list_is_refused(tmp_path):
    written = written_folder(tmp_path, drop=("written_out.yaml",))
    to = tmp_path / "records"
    r = call("writeout_to_project.py", "--from", written, "--to", to)
    assert r.returncode == 2
    assert str(written / "written_out.yaml") in r.stderr
    assert not to.exists()


def test_missing_written_out_folder_is_refused(tmp_path):
    to = tmp_path / "records"
    r = call("writeout_to_project.py", "--from", tmp_path / "nowhere", "--to", to)
    assert r.returncode == 2
    assert str(tmp_path / "nowhere") in r.stderr
    assert not to.exists()


def test_a_target_folder_holding_anything_is_refused(tmp_path):
    written = written_folder(tmp_path)
    to = tmp_path / "records"
    (to / "audit").mkdir(parents=True)
    (to / "raw.csv").write_bytes(b"the project's raw data\n")
    r = call("writeout_to_project.py", "--from", written, "--to", to)
    assert r.returncode == 2
    assert str(to) in r.stderr
    assert tree(to) == {"raw.csv": b"the project's raw data\n"}
    assert sorted(p.name for p in to.iterdir()) == ["audit", "raw.csv"]


def test_a_target_folder_holding_only_an_empty_folder_is_refused(tmp_path):
    written = written_folder(tmp_path)
    to = tmp_path / "records"
    (to / "audit").mkdir(parents=True)
    r = call("writeout_to_project.py", "--from", written, "--to", to)
    assert r.returncode == 2
    assert str(to) in r.stderr
    assert tree(to) == {}


def test_a_target_that_is_a_file_is_refused(tmp_path):
    written = written_folder(tmp_path)
    to = tmp_path / "records"
    to.write_bytes(b"a file\n")
    r = call("writeout_to_project.py", "--from", written, "--to", to)
    assert r.returncode == 2
    assert str(to) in r.stderr
    assert to.read_bytes() == b"a file\n"


# P4. The session index into the project's sessions/ folder.

INDEX = {
    "sessions.csv": b"public_id,contributions\r\nS0123456789ab,1\r\n",
    "README.md": b"# Sessions\n\n| [S0123456789ab](S0123456789ab.md) |\n",
    "S0123456789ab.md": b"# Session S0123456789ab\n\xc3\xa9\n",
    "index.html": b"<!doctype html>\n<script id=\"session-data\">[]</script>\n",
}
OLDER = {
    "sessions.csv": b"public_id,contributions\r\nSffffffffffff,0\r\n",
    "README.md": b"# Sessions, an older copy\n",
    "Sffffffffffff.md": b"# Session Sffffffffffff\n",
    "index.html": b"<!doctype html>\n",
}


def index_folder(tmp_path, files=None):
    folder = tmp_path / "index"
    folder.mkdir()
    return write_tree(folder, INDEX if files is None else files)


def story_session_index(tmp_path):
    """Write the story project's session index as the audit layer does, through
    its command line."""
    shutil.copytree(str(STORY / "project"), str(tmp_path / "project"))
    proj = Path(os.path.realpath(str(tmp_path / "project")))
    env = dict(os.environ, AUDIT_HOME=str(tmp_path / "audit_home"))
    out = tmp_path / "index"
    commands = [["init"]]
    for name in ("story_session.jsonl", "build_touch_session.jsonl"):
        session = tmp_path / name
        text = (STORY / "sessions" / "claude_code" / name).read_text(encoding="utf-8")
        session.write_text(text.replace("{{PROJECT}}", str(proj)), encoding="utf-8")
        commands.append(["capture", "--harness", "claude_code", str(session)])
    commands.append(["write-out", "session-index", "--project", str(proj), "--out", str(out)])
    for args in commands:
        done = subprocess.run([sys.executable, "-m", "audit_layer"] + args, cwd=str(ROOT),
                              env=env, capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
    return proj, out


def test_a_story_session_index_lands_in_the_projects_sessions_folder_byte_for_byte(tmp_path):
    proj, index = story_session_index(tmp_path)
    r = call("session_index_to_project.py", "--from", index, "--project", proj)
    assert r.returncode == 0, r.stderr
    assert str(proj / "sessions") in r.stdout
    names = tree(index)
    assert {"sessions.csv", "README.md", "index.html"} <= set(names)
    assert len([name for name in names if name.startswith("S") and name.endswith(".md")]) == 2
    assert tree(proj / "sessions") == names


def test_the_index_lands_in_a_new_sessions_folder(tmp_path):
    index = index_folder(tmp_path)
    proj = project(tmp_path)
    r = call("session_index_to_project.py", "--from", index, "--project", proj)
    assert r.returncode == 0, r.stderr
    assert tree(proj / "sessions") == INDEX
    assert tree(proj) == dict({"manuscript.md": b"A test manuscript.\n"},
                              **{"sessions/" + k: v for k, v in INDEX.items()})


def test_a_new_copy_replaces_an_older_one_whole(tmp_path):
    index = index_folder(tmp_path)
    proj = project(tmp_path)
    write_tree(proj / "sessions", OLDER)
    r = call("session_index_to_project.py", "--from", index, "--project", proj)
    assert r.returncode == 0, r.stderr
    assert tree(proj / "sessions") == INDEX
    assert not (proj / "sessions" / "Sffffffffffff.md").exists()


def test_the_copy_leaves_the_index_folder_unchanged(tmp_path):
    index = index_folder(tmp_path)
    proj = project(tmp_path)
    assert call("session_index_to_project.py", "--from", index,
                "--project", proj).returncode == 0
    assert tree(index) == INDEX


def test_a_missing_index_is_refused_and_writes_nothing(tmp_path):
    proj = project(tmp_path)
    r = call("session_index_to_project.py", "--from", tmp_path / "nowhere", "--project", proj)
    assert r.returncode == 2
    assert str(tmp_path / "nowhere") in r.stderr
    assert not (proj / "sessions").exists()


def test_an_empty_index_is_refused_and_writes_nothing(tmp_path):
    index = tmp_path / "index"
    index.mkdir()
    proj = project(tmp_path)
    r = call("session_index_to_project.py", "--from", index, "--project", proj)
    assert r.returncode == 2
    assert str(index) in r.stderr
    assert "empty" in r.stderr
    assert not (proj / "sessions").exists()


def test_a_folder_without_the_index_table_is_refused(tmp_path):
    index = index_folder(tmp_path, {k: v for k, v in INDEX.items() if k != "sessions.csv"})
    proj = project(tmp_path)
    r = call("session_index_to_project.py", "--from", index, "--project", proj)
    assert r.returncode == 2
    assert str(index / "sessions.csv") in r.stderr
    assert not (proj / "sessions").exists()


def test_an_index_that_is_a_file_is_refused(tmp_path):
    index = tmp_path / "index"
    index.write_bytes(b"a file\n")
    proj = project(tmp_path)
    r = call("session_index_to_project.py", "--from", index, "--project", proj)
    assert r.returncode == 2
    assert str(index) in r.stderr
    assert not (proj / "sessions").exists()


def test_a_refusal_leaves_an_older_copy_in_place(tmp_path):
    index = tmp_path / "index"
    index.mkdir()
    proj = project(tmp_path)
    write_tree(proj / "sessions", OLDER)
    r = call("session_index_to_project.py", "--from", index, "--project", proj)
    assert r.returncode == 2
    assert "empty" in r.stderr
    assert tree(proj / "sessions") == OLDER


def test_a_missing_project_is_refused_for_the_index(tmp_path):
    index = index_folder(tmp_path)
    r = call("session_index_to_project.py", "--from", index, "--project", tmp_path / "nowhere")
    assert r.returncode == 2
    assert str(tmp_path / "nowhere") in r.stderr
    assert not (tmp_path / "nowhere").exists()


def test_a_sessions_folder_holding_no_index_is_refused(tmp_path):
    index = index_folder(tmp_path)
    proj = project(tmp_path)
    write_tree(proj / "sessions", {"notes.txt": b"the scholar's own notes\n"})
    r = call("session_index_to_project.py", "--from", index, "--project", proj)
    assert r.returncode == 2
    assert str(proj / "sessions") in r.stderr
    assert tree(proj / "sessions") == {"notes.txt": b"the scholar's own notes\n"}


def test_a_sessions_path_that_is_a_file_is_refused(tmp_path):
    index = index_folder(tmp_path)
    proj = project(tmp_path)
    (proj / "sessions").write_bytes(b"a file\n")
    r = call("session_index_to_project.py", "--from", index, "--project", proj)
    assert r.returncode == 2
    assert str(proj / "sessions") in r.stderr
    assert (proj / "sessions").read_bytes() == b"a file\n"


def test_the_projects_own_copy_given_as_the_index_is_refused(tmp_path):
    proj = project(tmp_path)
    write_tree(proj / "sessions", INDEX)
    r = call("session_index_to_project.py", "--from", proj / "sessions", "--project", proj)
    assert r.returncode == 2
    assert str(proj / "sessions") in r.stderr
    assert tree(proj / "sessions") == INDEX
