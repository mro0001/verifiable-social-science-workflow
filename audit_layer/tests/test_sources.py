"""Tests for the sources store's records (Track A, Step A12).

Appendix Table A3's Sources row gives each source its bibliographic metadata,
an identifier block with DOI, OpenAlex, and Semantic Scholar, its retrieval
status, and a content fingerprint for deduplication. Sources arrive from the
citation manager's BibTeX export (plan choice 15), and every row carries the
session and reason the command is given (plan choice 23).

The bib file is the test story's refs.bib, copied into a temporary folder.
Nothing here calls a model or the network, and
every test runs with its home folder inside a temporary folder. Run from the
repository root with python3 -m pytest -q audit_layer/tests.
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
from audit_layer.store import StoreError, add_row, current, open_store  # noqa: E402
from audit_layer.stores.bibtex import BibError, read_bib  # noqa: E402
from audit_layer.stores.sources import add_from_bib, fingerprint  # noqa: E402

REFS = ROOT / "examples" / "test_story" / "project" / "refs.bib"

GIVEN = {
    "session": "s-sources",
    "origin": "bibtex export",
    "method": "sources.add_from_bib 1; refs.bib",
    "reason": "a test of the sources store",
}

DOIS = {
    "castellanos2017": "10.5555/vss.2017.0021",
    "dumont2014": "10.5555/vss.2014.0048",
    "healy2020": "",
    "nakamura2020": "10.5555/vss.2020.0063",
}

DUMONT = """@article{dumont2014,
  author  = {Dumont, Claire},
  title   = {Fixed-term assignments and volunteer re-enlistment},
  journal = {Voluntary Sector Studies},
  year    = {2014},
  doi     = {10.5555/vss.2014.0048}
}
"""


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
def bib(tmp_path):
    copy = tmp_path / "bib" / "refs.bib"
    copy.parent.mkdir()
    shutil.copyfile(str(REFS), str(copy))
    return copy


@pytest.fixture
def home(tmp_path):
    return tmp_path / "audit_home"


@pytest.fixture
def audit(home):
    store = open_store(home)
    yield store
    store.db.close()


@pytest.fixture
def added(audit, bib):
    summary = add_from_bib(audit, bib, GIVEN)
    return audit, summary


def by_key(store):
    return {row["citekey"]: row for row in current(store, "sources")}


# The story's four records.


def test_the_story_gives_four_records_with_their_dois_and_not_retrieved(added):
    store, summary = added
    assert (summary.added, summary.unchanged, summary.superseded, summary.refused) == (4, 0, 0, [])
    rows = by_key(store)
    assert sorted(rows) == sorted(DOIS)
    for key, doi in DOIS.items():
        assert rows[key]["identifiers"] == {"doi": doi, "openalex": "", "semantic_scholar": ""}
        assert rows[key]["retrieval_status"] == "not retrieved"
    assert len(stored_rows(store.db, "sources")) == 4


def test_each_record_holds_its_bibliographic_metadata(added):
    rows = by_key(added[0])
    dumont = rows["dumont2014"]
    assert (dumont["title"], dumont["authors"], dumont["year"], dumont["venue"]) == (
        "Fixed-term assignments and volunteer re-enlistment",
        "Dumont, Claire",
        "2014",
        "Voluntary Sector Studies",
    )
    assert rows["castellanos2017"]["authors"] == "Castellanos, Rosa and Ibe, Kelechi"
    # An online entry has no journal, so its venue is empty.
    assert rows["healy2020"]["venue"] == ""


def test_each_record_carries_its_content_fingerprint(added):
    rows = by_key(added[0])
    expected = hashlib.sha256(b"fixedtermassignmentsandvolunteerreenlistment2014").hexdigest()
    assert fingerprint("Fixed-term assignments and volunteer re-enlistment", "2014") == expected
    assert rows["dumont2014"]["content_fingerprint"] == expected
    for row in rows.values():
        assert row["content_fingerprint"] == fingerprint(row["title"], row["year"])


def test_the_fingerprint_ignores_case_space_and_marks():
    assert fingerprint("The {AI} Turn: a note", "2020") == fingerprint("the ai turn, A NOTE", "2020")
    assert fingerprint("The AI turn", "2020") != fingerprint("The AI turn", "2021")


def test_a_venue_comes_from_booktitle_when_there_is_no_journal(audit, tmp_path):
    path = tmp_path / "proceedings.bib"
    path.write_text(
        "@inproceedings{ortiz2019, title = {Open methods}, booktitle = {Proceedings of a"
        " meeting}, year = {2019}}\n",
        encoding="utf-8",
    )
    add_from_bib(audit, path, GIVEN)
    assert by_key(audit)["ortiz2019"]["venue"] == "Proceedings of a meeting"


# Adding again, changes, and copies.


def test_adding_the_file_again_adds_nothing(added, bib):
    store, _ = added
    held = stored_rows(store.db, "sources")
    summary = add_from_bib(store, bib, GIVEN)
    assert (summary.added, summary.unchanged, summary.superseded, summary.refused) == (0, 4, 0, [])
    assert stored_rows(store.db, "sources") == held


def test_an_entry_whose_title_changed_supersedes_its_record(added, bib):
    store, _ = added
    before = by_key(store)["nakamura2020"]
    text = bib.read_text(encoding="utf-8").replace(
        "Recognition events and the long-serving volunteer",
        "Recognition events and long-serving volunteers",
    )
    bib.write_text(text, encoding="utf-8")
    summary = add_from_bib(store, bib, dict(GIVEN, reason="title corrected"))
    assert (summary.added, summary.superseded) == (0, 1)

    after = by_key(store)["nakamura2020"]
    assert after["supersedes"] == before["id"]
    assert after["title"] == "Recognition events and long-serving volunteers"
    assert after["content_fingerprint"] == fingerprint(after["title"], "2020")
    assert after["identifiers"] == before["identifiers"]
    assert after["retrieval_status"] == before["retrieval_status"]
    assert after["reason"] == "title corrected"
    # The earlier record stays in the table.
    assert [r["id"] for r in stored_rows(store.db, "sources")].count(before["id"]) == 1
    assert len(current(store, "sources")) == 4


def test_a_copy_under_a_new_key_is_refused_naming_the_record_it_matches(added, tmp_path):
    store, _ = added
    copy = tmp_path / "copy.bib"
    copy.write_text(DUMONT.replace("dumont2014", "dumont2014b"), encoding="utf-8")
    held = stored_rows(store.db, "sources")
    summary = add_from_bib(store, copy, GIVEN)
    assert summary.added == 0
    ((key, reason),) = summary.refused
    assert key == "dumont2014b"
    assert "dumont2014" in reason.replace("dumont2014b", "")
    assert stored_rows(store.db, "sources") == held


def test_a_new_key_with_the_same_doi_is_refused(added, tmp_path):
    store, _ = added
    copy = tmp_path / "copy.bib"
    text = DUMONT.replace("dumont2014", "other2014").replace(
        "Fixed-term assignments", "Assignments of fixed term"
    )
    copy.write_text(text.replace("10.5555/vss.2014.0048", "10.5555/VSS.2014.0048"), encoding="utf-8")
    summary = add_from_bib(store, copy, GIVEN)
    ((key, reason),) = summary.refused
    assert key == "other2014"
    assert "dumont2014" in reason and "DOI" in reason


def test_a_refused_entry_does_not_stop_the_others(added, tmp_path):
    store, _ = added
    path = tmp_path / "mixed.bib"
    path.write_text(
        DUMONT.replace("dumont2014", "dumont2014b")
        + "@book{lee2021, title = {A new book}, author = {Lee, Ana}, year = {2021}}\n",
        encoding="utf-8",
    )
    summary = add_from_bib(store, path, GIVEN)
    assert summary.added == 1
    assert [key for key, _ in summary.refused] == ["dumont2014b"]
    assert "lee2021" in by_key(store)


def test_an_entry_with_no_title_is_refused(audit, tmp_path):
    path = tmp_path / "untitled.bib"
    path.write_text("@misc{untitled, year = {2020}}\n", encoding="utf-8")
    summary = add_from_bib(audit, path, GIVEN)
    ((key, reason),) = summary.refused
    assert key == "untitled" and "title" in reason
    assert current(audit, "sources") == []


# Provenance.


def test_every_row_carries_the_given_session_and_reason(added, bib):
    store, _ = added
    for row in stored_rows(store.db, "sources"):
        assert (row["session"], row["origin"], row["method"], row["reason"]) == (
            GIVEN["session"],
            GIVEN["origin"],
            GIVEN["method"],
            GIVEN["reason"],
        )


def test_sources_rows_are_never_updated_or_deleted(added):
    store, _ = added
    with pytest.raises(sqlite3.DatabaseError):
        with store.db:
            store.db.execute("UPDATE sources SET title = 'x'")
    with pytest.raises(sqlite3.DatabaseError):
        with store.db:
            store.db.execute("DELETE FROM sources")


def test_the_identifier_block_must_be_given_as_an_object(audit):
    with pytest.raises(StoreError):
        add_row(audit, "sources", {"citekey": "x", "identifiers": "10.1/x"}, GIVEN)


# Reading the bib file.


def test_a_title_with_braces_inside_it_is_read_whole():
    (entry,) = read_bib(
        "@Article{ai2024,\n  Title = {The {AI} turn in {Public} work},\n"
        '  Note = "A {"quoted"} note, with {braces}"\n}\n'
    )
    assert (entry["type"], entry["key"]) == ("article", "ai2024")
    assert entry["fields"]["title"] == "The {AI} turn in {Public} work"
    assert entry["fields"]["note"] == 'A {"quoted"} note, with {braces}'


def test_a_value_over_several_lines_reads_as_one_line():
    (entry,) = read_bib("@book{a, title = {One\n    two   three}}")
    assert entry["fields"]["title"] == "One two three"


def test_text_outside_entries_is_passed_over():
    entries = read_bib("Exported by hand.\n\n@book{a, title = {A}}\nend\n@book{b, title={B},}\n")
    assert [e["key"] for e in entries] == ["a", "b"]


ZOTERO = """
@article{okafor2021,
\ttitle = {Records that travel},
\tvolume = {12},
\tdoi = {10.5555/rt.2021.12},
\tjournal = {Journal of Public Records},
\tauthor = {Okafor, Ada},
\tmonth = jan,
\tyear = {2021},
\tpages = {1--20},
}
"""


def test_a_bare_value_is_read_as_written():
    (entry,) = read_bib("@book{a, title = {A}, year = 2020, month = jan}")
    assert entry["fields"]["year"] == "2020"
    assert entry["fields"]["month"] == "jan"


def test_a_zotero_entry_with_a_bare_month_is_added(audit, tmp_path):
    path = tmp_path / "zotero.bib"
    path.write_text(ZOTERO, encoding="utf-8")
    summary = add_from_bib(audit, path, GIVEN)
    assert summary.added == 1
    assert summary.refused == []


@pytest.mark.parametrize(
    "text",
    [
        "@book{a, title = {Unclosed}",
        "@book{a, title = {A} # {B}}",
        "@book{a, month = jan # { 1}}",
        "@string{jan = {January}}",
        "@book{a, year = 20-20}",
        "@book{a, title {No equals}}",
        "@book{, title = {No key}}",
        "@book{a, title = {One}, title = {Two}}",
    ],
)
def test_text_not_in_the_form_read_is_refused(text):
    with pytest.raises(BibError):
        read_bib(text)


def test_an_entry_listed_twice_the_same_is_added_once(audit, bib):
    text = bib.read_text(encoding="utf-8")
    bib.write_text(text + "\n" + DUMONT, encoding="utf-8")
    summary = add_from_bib(audit, bib, GIVEN)
    assert (summary.added, summary.unchanged) == (4, 1)


def test_the_story_bib_reads_four_entries():
    entries = read_bib(REFS.read_text(encoding="utf-8"))
    assert [e["key"] for e in entries] == [
        "healy2020",
        "castellanos2017",
        "dumont2014",
        "nakamura2020",
    ]


# The command line.


def run(home, *args):
    return main(["sources", *args[:1], "--home", str(home), *args[1:]])


@pytest.fixture
def initialized(home):
    assert main(["init", "--home", str(home)]) == 0
    return home


def test_sources_add_bib_with_its_defaults(initialized, bib, capsys):
    capsys.readouterr()
    assert run(initialized, "add-bib", str(bib)) == 0
    assert capsys.readouterr().out.splitlines() == [
        "added 4 sources, 0 unchanged, 0 superseded, 0 refused"
    ]
    store = open_store(initialized)
    try:
        rows = stored_rows(store.db, "sources")
    finally:
        store.db.close()
    assert len(rows) == 4
    for row in rows:
        assert (row["session"], row["origin"], row["method"], row["reason"]) == (
            "none",
            "bibtex export",
            "sources.add_from_bib 1; refs.bib",
            "added from the citation manager's export",
        )


def test_sources_add_bib_with_a_session_and_reason(initialized, bib):
    assert run(initialized, "add-bib", str(bib), "--session", "s9", "--reason", "new refs") == 0
    store = open_store(initialized)
    try:
        rows = stored_rows(store.db, "sources")
    finally:
        store.db.close()
    assert {(row["session"], row["reason"]) for row in rows} == {("s9", "new refs")}


def test_sources_add_bib_exits_1_when_an_entry_is_refused(initialized, bib, tmp_path, capsys):
    assert run(initialized, "add-bib", str(bib)) == 0
    copy = tmp_path / "copy.bib"
    copy.write_text(DUMONT.replace("dumont2014", "dumont2014b"), encoding="utf-8")
    capsys.readouterr()
    assert run(initialized, "add-bib", str(copy)) == 1
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("refused dumont2014b, ")
    assert out[-1] == "added 0 sources, 0 unchanged, 0 superseded, 1 refused"


def test_sources_add_bib_refuses_a_file_it_cannot_read(initialized, tmp_path, capsys):
    bad = tmp_path / "bad.bib"
    bad.write_text("@book{a, title = {A} # {B}}", encoding="utf-8")
    assert run(initialized, "add-bib", str(bad)) == 1
    assert "could not add" in capsys.readouterr().err
    assert run(initialized, "add-bib", str(tmp_path / "missing.bib")) == 1


def test_sources_list_prints_each_current_record(initialized, bib, capsys):
    run(initialized, "add-bib", str(bib))
    capsys.readouterr()
    assert run(initialized, "list") == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[-1] == "4 sources"
    assert (
        "dumont2014  2014  not retrieved  Fixed-term assignments and volunteer re-enlistment"
        in lines
    )
    assert sorted(line.split()[0] for line in lines[:-1]) == sorted(DOIS)


def test_sources_commands_refuse_a_home_with_no_store(tmp_path, bib, capsys):
    empty = tmp_path / "empty_home"
    assert run(empty, "list") == 1
    assert run(empty, "add-bib", str(bib)) == 1
    assert "no audit store" in capsys.readouterr().err
    assert not empty.exists()
