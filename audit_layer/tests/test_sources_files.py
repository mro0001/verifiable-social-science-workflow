"""Tests for the sources store's retrieved originals and extracted text (Track A, Step A13).

Appendix Table A3's Sources row keeps the retrieved original with its
retrieval method and date, and the extracted text by kind with its conversion
method. Spec 0.11 "Sources" says a source retrieved once may not be
retrievable again, and extraction can be rerun when tools improve. Every row
carries the session and reason its command is given (plan choice 23).

The original is the test story's source_nakamura2020.txt and the records come
from the story's refs.bib, both copied into a temporary folder. Nothing here
calls a model or the network, and every test runs with its home folder inside
a temporary folder. Run from the repository root with
python3 -m pytest -q audit_layer/tests.
"""
import hashlib
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from audit_layer.cli import main  # noqa: E402
from audit_layer.store import current, open_store  # noqa: E402
from audit_layer.stores.sources import (  # noqa: E402
    SourceError,
    add_from_bib,
    add_text,
    attach_original,
)

STORY = ROOT / "examples" / "test_story"
REFS = STORY / "project" / "refs.bib"
NAKAMURA = STORY / "references" / "source_nakamura2020.txt"
NAKAMURA_BYTES = NAKAMURA.read_bytes()
NAKAMURA_SHA = hashlib.sha256(NAKAMURA_BYTES).hexdigest()

GIVEN = {
    "session": "s-sources",
    "origin": "bibtex export",
    "method": "sources.add_from_bib 1; refs.bib",
    "reason": "a test of the sources store",
}

ATTACHED = {
    "session": "s-retrieve",
    "origin": "retrieval",
    "method": "sources.attach_original 1; source_nakamura2020.txt",
    "reason": "kept the retrieved original",
}

EXTRACTED = {
    "session": "s-extract",
    "origin": "text extraction",
    "method": "sources.add_text 1; source_nakamura2020.txt",
    "reason": "kept the extracted text",
}


def stored_rows(db, table):
    cursor = db.execute(f"SELECT * FROM {table} ORDER BY rowid")
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


@pytest.fixture(autouse=True)
def home_folder(tmp_path, monkeypatch):
    """Each test's own home folder, so nothing reaches the real ~/.audit_layer."""
    home = tmp_path / "home_folder"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("AUDIT_HOME", raising=False)
    return home


@pytest.fixture
def files(tmp_path):
    """The story's bib file and the Nakamura original, copied into a temporary folder."""
    folder = tmp_path / "given"
    folder.mkdir()
    shutil.copyfile(str(REFS), str(folder / "refs.bib"))
    shutil.copyfile(str(NAKAMURA), str(folder / "source_nakamura2020.txt"))
    return folder


@pytest.fixture
def store(tmp_path, files):
    audit = open_store(tmp_path / "audit_home")
    add_from_bib(audit, files / "refs.bib", GIVEN)
    yield audit
    audit.db.close()


def record(store, citekey):
    (row,) = current(store, "sources", citekey=citekey)
    return row


def kept_files(store):
    return sorted(path.name for path in store.files.iterdir())


# Retrieved originals.


def test_attaching_keeps_the_file_and_records_its_method_and_date(store, files):
    before = record(store, "nakamura2020")
    attach_original(
        store, "nakamura2020", files / "source_nakamura2020.txt", "publisher site", "2026-10-20",
        ATTACHED,
    )
    assert kept_files(store) == [NAKAMURA_SHA]
    assert (store.files / NAKAMURA_SHA).read_bytes() == NAKAMURA_BYTES

    (original,) = current(store, "source_originals")
    # The original names the record as it stands once it says retrieved.
    after = record(store, "nakamura2020")
    assert after["supersedes"] == before["id"]
    assert original["source"] == after["id"]
    assert original["file_sha256"] == NAKAMURA_SHA
    assert original["byte_size"] == len(NAKAMURA_BYTES)
    assert original["retrieval_method"] == "publisher site"
    assert original["retrieved_on"] == "2026-10-20"
    assert {k: original[k] for k in ATTACHED} == ATTACHED


def test_attaching_turns_the_records_status_to_retrieved(store, files):
    before = record(store, "nakamura2020")
    assert before["retrieval_status"] == "not retrieved"
    attach_original(
        store, "nakamura2020", files / "source_nakamura2020.txt", "publisher site", "2026-10-20",
        ATTACHED,
    )
    after = record(store, "nakamura2020")
    assert after["retrieval_status"] == "retrieved"
    assert after["supersedes"] == before["id"]
    assert {k: after[k] for k in ("title", "authors", "year", "venue", "identifiers")} == {
        k: before[k] for k in ("title", "authors", "year", "venue", "identifiers")
    }
    assert {k: after[k] for k in ATTACHED} == ATTACHED
    # The other records are untouched, and the earlier record stays in the table.
    assert record(store, "dumont2014")["retrieval_status"] == "not retrieved"
    assert before["id"] in [row["id"] for row in stored_rows(store.db, "sources")]


def test_attaching_the_same_bytes_again_adds_a_row_and_no_second_file(store, files, tmp_path):
    attach_original(
        store, "nakamura2020", files / "source_nakamura2020.txt", "publisher site", "2026-10-20",
        ATTACHED,
    )
    status_rows = len(stored_rows(store.db, "sources"))
    again = tmp_path / "again.txt"
    again.write_bytes(NAKAMURA_BYTES)
    attach_original(store, "nakamura2020", again, "library copy", "2026-10-22", ATTACHED)

    assert kept_files(store) == [NAKAMURA_SHA]
    originals = current(store, "source_originals")
    assert [row["retrieval_method"] for row in originals] == ["publisher site", "library copy"]
    assert {row["file_sha256"] for row in originals} == {NAKAMURA_SHA}
    # The record already says retrieved, so it is not superseded again, and
    # both originals name the current record.
    assert len(stored_rows(store.db, "sources")) == status_rows
    assert {row["source"] for row in originals} == {record(store, "nakamura2020")["id"]}


def test_a_record_changed_in_the_bib_file_keeps_its_retrieved_status(store, files):
    attach_original(
        store, "nakamura2020", files / "source_nakamura2020.txt", "publisher site", "2026-10-20",
        ATTACHED,
    )
    bib = files / "refs.bib"
    bib.write_text(
        bib.read_text(encoding="utf-8").replace(
            "Recognition events and the long-serving volunteer",
            "Recognition events and long-serving volunteers",
        ),
        encoding="utf-8",
    )
    add_from_bib(store, bib, GIVEN)
    assert record(store, "nakamura2020")["retrieval_status"] == "retrieved"


def test_an_unknown_citekey_is_refused_and_nothing_is_kept(store, files):
    held = stored_rows(store.db, "sources")
    with pytest.raises(SourceError, match="nobody2020"):
        attach_original(
            store, "nobody2020", files / "source_nakamura2020.txt", "publisher site",
            "2026-10-20", ATTACHED,
        )
    assert kept_files(store) == []
    assert stored_rows(store.db, "source_originals") == []
    assert stored_rows(store.db, "sources") == held


@pytest.mark.parametrize("date", ["20 October 2026", "2026-10-2", "2026/10/20", "2026-02-30", ""])
def test_a_date_not_in_year_month_day_form_is_refused(store, files, date):
    with pytest.raises(SourceError, match="YYYY-MM-DD"):
        attach_original(
            store, "nakamura2020", files / "source_nakamura2020.txt", "publisher site", date,
            ATTACHED,
        )
    assert kept_files(store) == []
    assert stored_rows(store.db, "source_originals") == []
    assert record(store, "nakamura2020")["retrieval_status"] == "not retrieved"


def test_a_blank_retrieval_method_is_refused(store, files):
    with pytest.raises(SourceError, match="method"):
        attach_original(
            store, "nakamura2020", files / "source_nakamura2020.txt", "  ", "2026-10-20", ATTACHED
        )
    assert stored_rows(store.db, "source_originals") == []


def test_a_missing_original_is_refused_and_nothing_is_kept(store, files):
    with pytest.raises(OSError):
        attach_original(
            store, "nakamura2020", files / "missing.pdf", "publisher site", "2026-10-20", ATTACHED
        )
    assert stored_rows(store.db, "source_originals") == []
    assert record(store, "nakamura2020")["retrieval_status"] == "not retrieved"


def test_originals_and_text_rows_are_never_updated_or_deleted(store, files):
    attach_original(
        store, "nakamura2020", files / "source_nakamura2020.txt", "publisher site", "2026-10-20",
        ATTACHED,
    )
    add_text(
        store, "nakamura2020", "fulltext", files / "source_nakamura2020.txt", "copied", EXTRACTED
    )
    for table in ("source_originals", "source_texts"):
        with pytest.raises(sqlite3.DatabaseError):
            with store.db:
                store.db.execute(f"UPDATE {table} SET source = 'x'")
        with pytest.raises(sqlite3.DatabaseError):
            with store.db:
                store.db.execute(f"DELETE FROM {table}")


# Extracted text.


def test_a_text_row_holds_the_text_and_its_conversion_method(store, files):
    source = record(store, "nakamura2020")
    add_text(
        store, "nakamura2020", "fulltext", files / "source_nakamura2020.txt", "copied as plain text",
        EXTRACTED,
    )
    (text,) = current(store, "source_texts")
    assert text["source"] == source["id"]
    assert text["kind"] == "fulltext"
    assert text["text"] == NAKAMURA_BYTES.decode("utf-8")
    assert text["conversion_method"] == "copied as plain text"
    assert {k: text[k] for k in EXTRACTED} == EXTRACTED
    # Adding text leaves the record and its status as they were.
    assert record(store, "nakamura2020") == source


def test_the_newest_text_of_a_kind_counts(store, files, tmp_path):
    add_text(
        store, "nakamura2020", "fulltext", files / "source_nakamura2020.txt", "first tool",
        EXTRACTED,
    )
    abstract = tmp_path / "abstract.txt"
    abstract.write_text("Recognition events had no measurable effect.\n", encoding="utf-8")
    add_text(store, "nakamura2020", "abstract", abstract, "by hand", EXTRACTED)
    better = tmp_path / "better.txt"
    better.write_text("A cleaner extraction.\n", encoding="utf-8")
    add_text(store, "nakamura2020", "fulltext", better, "second tool", EXTRACTED)

    rows = {row["kind"]: row for row in current(store, "source_texts")}
    assert sorted(rows) == ["abstract", "fulltext"]
    assert rows["fulltext"]["text"] == "A cleaner extraction.\n"
    assert rows["fulltext"]["conversion_method"] == "second tool"
    # The earlier extraction stays in the table, superseded by the newer one.
    every = stored_rows(store.db, "source_texts")
    assert len(every) == 3
    assert rows["fulltext"]["supersedes"] == every[0]["id"]


@pytest.mark.parametrize("kind", ["summary", "Fulltext", ""])
def test_an_unknown_kind_is_refused(store, files, kind):
    with pytest.raises(SourceError, match="kind"):
        add_text(
            store, "nakamura2020", kind, files / "source_nakamura2020.txt", "copied", EXTRACTED
        )
    assert stored_rows(store.db, "source_texts") == []


def test_text_for_an_unknown_citekey_is_refused(store, files):
    with pytest.raises(SourceError, match="nobody2020"):
        add_text(store, "nobody2020", "fulltext", files / "source_nakamura2020.txt", "copied", EXTRACTED)
    assert stored_rows(store.db, "source_texts") == []


def test_a_blank_conversion_method_is_refused(store, files):
    with pytest.raises(SourceError, match="conversion"):
        add_text(store, "nakamura2020", "fulltext", files / "source_nakamura2020.txt", "", EXTRACTED)
    assert stored_rows(store.db, "source_texts") == []


def test_text_that_is_not_utf8_is_refused(store, tmp_path):
    bad = tmp_path / "bad.txt"
    bad.write_bytes(b"\xff\xfe not text")
    with pytest.raises(ValueError):
        add_text(store, "nakamura2020", "fulltext", bad, "copied", EXTRACTED)
    assert stored_rows(store.db, "source_texts") == []


# The command line.


@pytest.fixture
def initialized(tmp_path, files):
    home = tmp_path / "cli_home"
    assert main(["init", "--home", str(home)]) == 0
    assert main(["sources", "add-bib", "--home", str(home), str(files / "refs.bib")]) == 0
    return home


def cli_rows(home, table):
    audit = open_store(home)
    try:
        return stored_rows(audit.db, table)
    finally:
        audit.db.close()


def attach(home, *extra):
    return main(["sources", "attach", "--home", str(home), *extra])


def text(home, *extra):
    return main(["sources", "text", "--home", str(home), *extra])


def test_sources_attach_with_its_defaults(initialized, files, capsys):
    capsys.readouterr()
    original = str(files / "source_nakamura2020.txt")
    code = attach(
        initialized, "nakamura2020", "--original", original, "--method", "publisher site",
        "--date", "2026-10-20",
    )
    assert code == 0
    assert capsys.readouterr().out.splitlines() == [
        f"attached source_nakamura2020.txt to nakamura2020, kept as {NAKAMURA_SHA[:12]},"
        " status retrieved"
    ]
    (row,) = cli_rows(initialized, "source_originals")
    assert (row["session"], row["origin"], row["method"], row["reason"]) == (
        "none",
        "retrieval",
        "sources.attach_original 1; source_nakamura2020.txt",
        "kept the retrieved original",
    )
    assert (row["retrieval_method"], row["retrieved_on"]) == ("publisher site", "2026-10-20")
    status = [r for r in cli_rows(initialized, "sources") if r["retrieval_status"] == "retrieved"]
    assert [(r["citekey"], r["reason"]) for r in status] == [
        ("nakamura2020", "kept the retrieved original")
    ]


def test_sources_attach_with_a_session_and_reason(initialized, files):
    code = attach(
        initialized, "nakamura2020", "--original", str(files / "source_nakamura2020.txt"),
        "--method", "publisher site", "--date", "2026-10-20", "--session", "s7",
        "--reason", "paywalled, kept now",
    )
    assert code == 0
    (row,) = cli_rows(initialized, "source_originals")
    assert (row["session"], row["reason"]) == ("s7", "paywalled, kept now")


@pytest.mark.parametrize(
    "citekey, date, said",
    [("nobody2020", "2026-10-20", "nobody2020"), ("nakamura2020", "20/10/2026", "YYYY-MM-DD")],
)
def test_sources_attach_refuses_and_exits_1(initialized, files, capsys, citekey, date, said):
    capsys.readouterr()
    code = attach(
        initialized, citekey, "--original", str(files / "source_nakamura2020.txt"),
        "--method", "publisher site", "--date", date,
    )
    assert code == 1
    err = capsys.readouterr().err
    assert err.startswith("sources attach refused, ") and said in err
    assert cli_rows(initialized, "source_originals") == []


def test_sources_text_with_its_defaults(initialized, files, capsys):
    capsys.readouterr()
    code = text(
        initialized, "nakamura2020", "--kind", "fulltext", "--file",
        str(files / "source_nakamura2020.txt"), "--conversion", "copied as plain text",
    )
    assert code == 0
    assert capsys.readouterr().out.splitlines() == ["added the fulltext text of nakamura2020"]
    (row,) = cli_rows(initialized, "source_texts")
    assert (row["session"], row["origin"], row["method"], row["reason"]) == (
        "none",
        "text extraction",
        "sources.add_text 1; source_nakamura2020.txt",
        "kept the extracted text",
    )
    assert (row["kind"], row["conversion_method"]) == ("fulltext", "copied as plain text")


def test_sources_text_with_a_session_and_reason(initialized, files):
    code = text(
        initialized, "nakamura2020", "--kind", "abstract", "--file",
        str(files / "source_nakamura2020.txt"), "--conversion", "by hand", "--session", "s8",
        "--reason", "first pass",
    )
    assert code == 0
    (row,) = cli_rows(initialized, "source_texts")
    assert (row["session"], row["reason"]) == ("s8", "first pass")


def test_sources_text_refuses_an_unknown_kind(initialized, files, capsys):
    capsys.readouterr()
    code = text(
        initialized, "nakamura2020", "--kind", "summary", "--file",
        str(files / "source_nakamura2020.txt"), "--conversion", "copied",
    )
    assert code == 1
    assert capsys.readouterr().err.startswith("sources text refused, ")
    assert cli_rows(initialized, "source_texts") == []


def test_sources_attach_and_text_refuse_a_home_with_no_store(tmp_path, files, capsys):
    empty = tmp_path / "empty_home"
    original = str(files / "source_nakamura2020.txt")
    assert attach(empty, "nakamura2020", "--original", original, "--method", "m", "--date",
                  "2026-10-20") == 1
    assert text(empty, "nakamura2020", "--kind", "fulltext", "--file", original,
                "--conversion", "c") == 1
    assert "no audit store" in capsys.readouterr().err
    assert not empty.exists()
