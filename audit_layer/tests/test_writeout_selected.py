"""Tests for the write-out of selected sources, datasets, and knowledge entries (Track A, Step A20).

Appendix Table A3 gives the sources, data, and knowledge stores their rows,
and its export registry gives each element's file form and path. A2.3's
replication folder holds the source text, data, and code a research product
needs. Without a links table the store cannot say which sources or datasets
belong to a project, so they are written out only when named (plan choice
21). A table is written back out as a delimited file with its codebook
beside it (spec 0.11 "Data").

The store is the one full_store.build_full_store makes from the test story
and Track A's fixtures. Every file these tests add is synthetic. No real
session file is read, nothing here calls a model or the network, and every
test runs with its home folder inside a temporary folder. Run from the
repository root with python3 -m pytest -q audit_layer/tests.
"""
import hashlib
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from audit_layer.cli import main  # noqa: E402
from audit_layer.store import current  # noqa: E402
from audit_layer.stores.data import add_dataset, write_dataset  # noqa: E402
from audit_layer.stores.knowledge import sync  # noqa: E402
from audit_layer.stores.sources import attach_original  # noqa: E402
from audit_layer.tests.full_store import (  # noqa: E402
    AGENT_ID,
    DATA,
    DATASET,
    ENTRY,
    ENTRY_ID,
    GIVEN,
    NAKAMURA,
    STORY_ID,
    build_full_store,
)
from audit_layer.writeout import write_out_project  # noqa: E402

# The files a write-out of the story's project with nothing named holds (Step A19,
# with W's three records from Track A late).
STORY_FILES = {
    "audit/projects.yaml",
    "audit/sessions.yaml",
    "audit/events.jsonl",
    "audit/transcripts.yaml",
    f"audit/transcripts/claude_code/{STORY_ID}.jsonl",
    f"audit/transcripts/claude_code/{STORY_ID}/agent-{AGENT_ID}.jsonl",
    "audit/snapshots.yaml",
    "audit/citation_log.yaml",
    "audit/session_writes.jsonl",
    "audit/rationales.yaml",
    "working/manuscript.md",
    "working/source_notes.md",
    "working/notes/reading_list.md",
    "schema/field_definitions.yaml",
    "schema/export_registry.yaml",
    "written_out.yaml",
}

NAKAMURA_FILES = {
    "sources/sources.yaml",
    "sources/originals.yaml",
    "sources/originals/nakamura2020.txt",
    "sources/texts.yaml",
    "sources/texts/nakamura2020.fulltext.txt",
}
DATA_FILES = {
    "data/datasets.yaml",
    f"data/{DATASET}_v1.csv",
    f"data/{DATASET}_v1_codebook.csv",
}
KNOWLEDGE_FILES = {
    "knowledge/entries.yaml",
    f"knowledge/{ENTRY_ID}.md",
    "knowledge/history.yaml",
    f"knowledge/history/{ENTRY_ID}/1.md",
}


def files_in(folder):
    return {p.relative_to(folder).as_posix() for p in Path(folder).rglob("*") if p.is_file()}


def load_yaml(path):
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def attach(full, tmp_path, citekey, name, data):
    """Keep data as citekey's retrieved original, from a file of its own."""
    path = tmp_path / "originals" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    attach_original(full.store, citekey, path, "a test original", "2026-10-23", GIVEN)


def add_second_version(full, tmp_path):
    """Add the dataset again with one more row, as its version 2."""
    path = tmp_path / "second" / DATA.name
    path.parent.mkdir(parents=True)
    path.write_bytes(DATA.read_bytes() + b"both,Posting and definition,60,9,35.5\n")
    return add_dataset(full.store, DATASET, path, "2026-10-24", {}, GIVEN)


@pytest.fixture(autouse=True)
def home_folder(tmp_path, monkeypatch):
    """Each test's own home folder, so nothing reaches the real ~/.audit_layer or a real root."""
    home = tmp_path / "home_folder"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("AUDIT_HOME", raising=False)
    return home


@pytest.fixture
def full(tmp_path):
    built = build_full_store(tmp_path / "full")
    yield built
    built.store.db.close()


@pytest.fixture
def out(tmp_path):
    return tmp_path / "written"


def write_named(full, out, **named):
    return write_out_project(full.store, full.project, out, **named)


# What is named is written, at its registry path, and nothing else.


def test_named_sources_datasets_and_knowledge_are_written_at_their_registry_paths(full, out):
    files = write_named(
        full, out, citekeys=["nakamura2020"], datasets=[(DATASET, None)], knowledge=True
    )
    expected = STORY_FILES | NAKAMURA_FILES | DATA_FILES | KNOWLEDGE_FILES
    assert files_in(out) == expected

    listed = load_yaml(out / "written_out.yaml")["files"]
    assert {item["path"] for item in listed} == expected - {"written_out.yaml"}
    for item in listed:
        assert item["sha256"] == sha256(out / item["path"]), item["path"]
    elements = {item["path"]: item["element"] for item in listed}
    assert elements["sources/sources.yaml"] == "sources"
    assert elements["sources/originals/nakamura2020.txt"] == "source_originals"
    assert elements["sources/texts/nakamura2020.fulltext.txt"] == "source_texts"
    assert elements["data/datasets.yaml"] == "datasets"
    assert elements[f"data/{DATASET}_v1_codebook.csv"] == "codebook"
    assert elements[f"data/{DATASET}_v1.csv"] == "ds_*"
    assert elements[f"knowledge/{ENTRY_ID}.md"] == "knowledge_entries"
    assert elements[f"knowledge/history/{ENTRY_ID}/1.md"] == "knowledge_history"
    assert [tuple(item) for item in files] == [
        (item["path"], item["element"], item["sha256"]) for item in listed
    ]


def test_with_nothing_named_no_source_data_or_knowledge_file_is_written(full, out):
    write_named(full, out)
    assert files_in(out) == STORY_FILES


def test_a_source_not_named_is_absent(full, tmp_path, out):
    attach(full, tmp_path, "dumont2014", "dumont.txt", b"Dumont's synthetic text.\n")
    write_named(full, out, citekeys=["nakamura2020"])
    assert files_in(out) == STORY_FILES | NAKAMURA_FILES
    assert [r["citekey"] for r in load_yaml(out / "sources" / "sources.yaml")] == ["nakamura2020"]
    assert {r["source"] for r in load_yaml(out / "sources" / "originals.yaml")} == {"nakamura2020"}


def test_a_named_source_with_no_original_or_text_writes_empty_lists(full, out):
    write_named(full, out, citekeys=["dumont2014"])
    assert files_in(out) == STORY_FILES | {
        "sources/sources.yaml",
        "sources/originals.yaml",
        "sources/texts.yaml",
    }
    assert load_yaml(out / "sources" / "originals.yaml") == []
    assert load_yaml(out / "sources" / "texts.yaml") == []


# Sources.


def test_the_nakamura_original_comes_out_as_txt_byte_for_byte(full, out):
    write_named(full, out, citekeys=["nakamura2020"])
    assert (out / "sources" / "originals" / "nakamura2020.txt").read_bytes() == NAKAMURA.read_bytes()


def test_an_original_s_extension_comes_from_its_first_bytes(full, tmp_path, out):
    attach(full, tmp_path, "dumont2014", "dumont.pdf", b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    attach(full, tmp_path, "castellanos2017", "castellanos", b"<!DOCTYPE html>\n<html></html>\n")
    attach(full, tmp_path, "healy2020", "healy", b"\xff\xfe\x00\x01 not text")
    write_named(full, out, citekeys=["dumont2014", "castellanos2017", "healy2020"])
    originals = {p for p in files_in(out) if p.startswith("sources/originals/")}
    assert originals == {
        "sources/originals/dumont2014.pdf",
        "sources/originals/castellanos2017.html",
        "sources/originals/healy2020.bin",
    }


def test_an_original_starting_with_an_html_tag_is_html(full, tmp_path, out):
    attach(full, tmp_path, "dumont2014", "dumont", b"<html><body>synthetic</body></html>\n")
    write_named(full, out, citekeys=["dumont2014"])
    assert (out / "sources" / "originals" / "dumont2014.html").is_file()


def test_the_latest_original_of_a_source_is_the_one_written(full, tmp_path, out):
    attach(full, tmp_path, "nakamura2020", "second.txt", b"A later retrieval, synthetic.\n")
    write_named(full, out, citekeys=["nakamura2020"])
    assert (out / "sources" / "originals" / "nakamura2020.txt").read_bytes() == (
        b"A later retrieval, synthetic.\n"
    )
    assert len(load_yaml(out / "sources" / "originals.yaml")) == 2


def test_the_source_records_keep_their_fields_and_name_the_source_by_citekey(full, out):
    write_named(full, out, citekeys=["nakamura2020"])
    (record,) = load_yaml(out / "sources" / "sources.yaml")
    (row,) = current(full.store, "sources", citekey="nakamura2020")
    assert record == {k: v for k, v in row.items() if k not in ("id", "supersedes")}
    assert record["retrieval_status"] == "retrieved"
    assert isinstance(record["identifiers"], dict)

    (original,) = load_yaml(out / "sources" / "originals.yaml")
    assert original["source"] == "nakamura2020"
    assert original["file_sha256"] == sha256(out / "sources" / "originals" / "nakamura2020.txt")
    (text,) = load_yaml(out / "sources" / "texts.yaml")
    assert text["source"] == "nakamura2020"
    assert text["kind"] == "fulltext"
    assert (out / "sources" / "texts" / "nakamura2020.fulltext.txt").read_bytes() == text[
        "text"
    ].encode("utf-8")
    for item in (record, original, text):
        assert "id" not in item and "supersedes" not in item
        for name in ("created_at", "session", "origin", "method", "reason"):
            assert item[name]


# Datasets.


def test_a_dataset_s_csv_and_codebook_equal_what_write_dataset_writes(full, tmp_path, out):
    write_named(full, out, datasets=[(DATASET, None)])
    by_hand = tmp_path / "by_hand"
    paths = write_dataset(full.store, DATASET, 1, by_hand)
    for path in paths:
        assert (out / "data" / path.name).read_bytes() == path.read_bytes(), path.name


def test_a_dataset_named_without_a_version_gives_its_latest(full, tmp_path, out):
    add_second_version(full, tmp_path)
    write_named(full, out, datasets=[(DATASET, None)])
    data = {p for p in files_in(out) if p.startswith("data/")}
    assert data == {
        "data/datasets.yaml",
        f"data/{DATASET}_v2.csv",
        f"data/{DATASET}_v2_codebook.csv",
    }
    (record,) = load_yaml(out / "data" / "datasets.yaml")
    assert record["version"] == 2
    assert record["row_count"] == 4


def test_a_dataset_named_with_a_version_gives_that_version(full, tmp_path, out):
    add_second_version(full, tmp_path)
    write_named(full, out, datasets=[(DATASET, 1), (DATASET, 2)])
    data = {p for p in files_in(out) if p.startswith("data/")}
    assert data == {
        "data/datasets.yaml",
        f"data/{DATASET}_v1.csv",
        f"data/{DATASET}_v1_codebook.csv",
        f"data/{DATASET}_v2.csv",
        f"data/{DATASET}_v2_codebook.csv",
    }
    by_hand = tmp_path / "by_hand"
    for version in (1, 2):
        for path in write_dataset(full.store, DATASET, version, by_hand / str(version)):
            assert (out / "data" / path.name).read_bytes() == path.read_bytes(), path.name


def test_the_catalog_record_names_its_table_by_the_csv_path(full, out):
    write_named(full, out, datasets=[(DATASET, None)])
    (record,) = load_yaml(out / "data" / "datasets.yaml")
    (row,) = current(full.store, "datasets", name=DATASET)
    assert record["table_name"] == f"data/{DATASET}_v1.csv"
    assert row["table_name"] not in (out / "data" / "datasets.yaml").read_text(encoding="utf-8")
    kept = {k: v for k, v in row.items() if k not in ("id", "supersedes", "table_name")}
    assert {k: v for k, v in record.items() if k != "table_name"} == kept


# Knowledge entries.


def test_each_knowledge_file_equals_its_entry_file_and_its_replaced_version_sits_at_1(full, out):
    write_named(full, out, knowledge=True)
    entry_file = full.project.parent / "corpus" / "numbers.md"
    assert (out / "knowledge" / f"{ENTRY_ID}.md").read_bytes() == entry_file.read_bytes()
    earlier = ENTRY.format(commit="3f2a9c1", more="").encode("utf-8")
    assert (out / "knowledge" / "history" / ENTRY_ID / "1.md").read_bytes() == earlier

    (entry,) = load_yaml(out / "knowledge" / "entries.yaml")
    assert entry["entry_id"] == ENTRY_ID and entry["source_checksum"] == "7b4e0d2"
    (replaced,) = load_yaml(out / "knowledge" / "history.yaml")
    assert replaced["entry_id"] == ENTRY_ID and replaced["source_checksum"] == "3f2a9c1"
    for item in (entry, replaced):
        assert "id" not in item and "supersedes" not in item


def test_history_versions_are_numbered_from_1_oldest_first(full, out):
    entry_file = full.project.parent / "corpus" / "numbers.md"
    entry_file.write_bytes(ENTRY.format(commit="9d1c3e8", more="Third version.").encode("utf-8"))
    assert sync(full.store, [entry_file], GIVEN).replaced == 1
    write_named(full, out, knowledge=True)
    folder = out / "knowledge" / "history" / ENTRY_ID
    assert sorted(p.name for p in folder.iterdir()) == ["1.md", "2.md"]
    assert b"3f2a9c1" in (folder / "1.md").read_bytes()
    assert b"7b4e0d2" in (folder / "2.md").read_bytes()
    history = load_yaml(out / "knowledge" / "history.yaml")
    assert [r["source_checksum"] for r in history] == ["3f2a9c1", "7b4e0d2"]


# Refusals.


@pytest.mark.parametrize(
    "named, why",
    [
        ({"citekeys": ["nakamura2020", "nobody1999"]}, "no source nobody1999"),
        ({"datasets": [("no_such_data", None)]}, "no dataset no_such_data"),
        ({"datasets": [(DATASET, 7)]}, "no version 7"),
    ],
)
def test_an_unknown_citekey_dataset_or_version_is_refused_and_nothing_is_written(
    full, out, named, why
):
    with pytest.raises(ValueError, match=why):
        write_named(full, out, **named)
    assert not out.exists()


# The write-out project command.


def run(full, out, *more):
    return main(
        ["write-out", "project", "--home", str(full.home), "--project", str(full.project), "--out", str(out)]
        + list(more)
    )


def test_the_command_writes_what_its_options_name(full, tmp_path, out, capsys):
    add_second_version(full, tmp_path)
    code = run(
        full, out, "--sources", "nakamura2020", "--datasets", f"{DATASET}:1,{DATASET}", "--knowledge"
    )
    assert code == 0
    expected = (
        STORY_FILES
        | NAKAMURA_FILES
        | DATA_FILES
        | {f"data/{DATASET}_v2.csv", f"data/{DATASET}_v2_codebook.csv"}
        | KNOWLEDGE_FILES
    )
    assert files_in(out) == expected
    assert capsys.readouterr().out.splitlines() == [
        f"wrote {out}, {len(expected) - 1} files listed in written_out.yaml"
    ]


def test_the_command_with_no_options_writes_the_project_only(full, out):
    assert run(full, out) == 0
    assert files_in(out) == STORY_FILES


@pytest.mark.parametrize(
    "more, why",
    [
        (["--sources", "nobody1999"], "no source nobody1999"),
        (["--datasets", "no_such_data"], "no dataset no_such_data"),
        (["--datasets", f"{DATASET}:7"], "no version 7"),
        (["--datasets", f"{DATASET}:one"], "not a version"),
        (["--datasets", f"{DATASET}:0"], "not a version"),
    ],
)
def test_the_command_refuses_an_unknown_name_or_version_and_writes_nothing(
    full, out, capsys, more, why
):
    assert run(full, out, *more) == 1
    assert why in capsys.readouterr().err
    assert not out.exists()


def test_the_store_is_unchanged_by_a_write_out(full, out):
    def every_row(db):
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        return {t: db.execute(f'SELECT * FROM "{t}" ORDER BY rowid').fetchall() for t in tables}

    before = every_row(full.store.db)
    write_named(full, out, citekeys=["nakamura2020"], datasets=[(DATASET, None)], knowledge=True)
    assert every_row(full.store.db) == before
