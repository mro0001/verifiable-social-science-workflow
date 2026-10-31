"""Tests for the knowledge store sketch (Track A, Step A15).

Appendix Table A3's Knowledge row is a sketch only, with an entry class,
title, gist, keywords, content, and a checksum of the source material, and a
history table that keeps every prior version. A2.4 "Knowledge base" gives each
entry a markdown file whose heading fixes its identifier, title, source,
source version, date, and group. The reconciliation's Track A section loads
the tables knowledge_entries and knowledge_history from entry files with
python3 -m audit_layer knowledge sync --corpus DIR. The class is the entry's
group, the gist is the first sentence of the first paragraph after the title,
keywords stay empty, the content is the whole file, and the checksum is
source_commit (plan choice 17). There is no search.

The tests write their own synthetic entry files, since Track G moves the
knowledge base's corpus at the same time. Nothing here calls a model or the
network, and every test runs with its home folder inside a temporary folder.
Run from the repository root with python3 -m pytest -q audit_layer/tests.
"""
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from audit_layer.cli import main  # noqa: E402
from audit_layer.store import current, open_store  # noqa: E402
from audit_layer.stores.knowledge import history, parse_entry, sync  # noqa: E402

STANDARD = """\
---
id: standards-numbers-from-files
title: Every number comes from a file
source: standards/numbers.md
source_commit: 3f2a9c1
updated: 2026-10-20
group: STANDARDS
---

# Every number comes from a file

A number in the manuscript is read from a results file, never typed by hand. The
build fails when the two differ.

1. The build reads numbers.yml.

## Consult also

- standards-citations-checked
"""

GUIDELINE = """\
---
id: guidelines-plain-words
title: "Plain words in every document"
source: guidelines/plain.md
source_commit: "sha256:0a1b2c3d4e5f"
updated: 2026-10-21
group: GUIDELINES
---

# Plain words in every document

Write short sentences! A reader should never need a glossary.

1. No dashes.
"""

PROCEDURE = """\
---
id: procedures-references
title: The references procedure
source: verification_procedures/graphs/references.yaml
source_commit: sha256:9e8d7c6b5a41
updated: 2026-10-22
group: PROCEDURES
---

# The references procedure

Checks that each citation in the manuscript names a source, and that the quoted
text appears in it? The procedural graph system runs it with the command below.

1. python3 verification_procedures/vg.py run references
"""

NO_ID = """\
---
title: An entry with no identifier
source: standards/none.md
source_commit: 1234567
updated: 2026-10-23
group: STANDARDS
---

# An entry with no identifier

This entry cannot be stored.
"""

GIVEN = {
    "session": "s-knowledge",
    "origin": "entry files",
    "method": "knowledge.sync 1; corpus",
    "reason": "a test of the knowledge store",
}
LATER = {
    "session": "s-knowledge-later",
    "origin": "entry files",
    "method": "knowledge.sync 1; corpus",
    "reason": "the entry changed",
}
FIELDS = ["entry_id", "class", "title", "gist", "keywords", "content", "source_checksum"]
SPINE = ["id", "created_at", "session", "origin", "method", "reason", "supersedes"]


def stored_rows(db, table):
    cursor = db.execute(f"SELECT * FROM {table} ORDER BY rowid")
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def write_corpus(folder, with_bad=False):
    """The three synthetic entries in group folders, and the malformed one when asked."""
    files = {
        "standards/standards-numbers-from-files.md": STANDARD,
        "guidelines/guidelines-plain-words.md": GUIDELINE,
        "procedures/procedures-references.md": PROCEDURE,
    }
    if with_bad:
        files["standards/standards-no-id.md"] = NO_ID
    for rel, text in files.items():
        path = folder / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return folder


@pytest.fixture(autouse=True)
def home_folder(tmp_path, monkeypatch):
    """Each test's own home folder, so nothing reaches the real ~/.audit_layer."""
    home = tmp_path / "home_folder"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("AUDIT_HOME", raising=False)
    return home


@pytest.fixture
def store(tmp_path):
    opened = open_store(tmp_path / "audit")
    yield opened
    opened.db.close()


@pytest.fixture
def corpus(tmp_path):
    return write_corpus(tmp_path / "corpus")


def by_id(rows):
    return {row["entry_id"]: row for row in rows}


# parse_entry


def test_parse_entry_maps_the_six_key_heading():
    fields, problems = parse_entry(STANDARD)
    assert problems == []
    assert fields == {
        "entry_id": "standards-numbers-from-files",
        "class": "STANDARDS",
        "title": "Every number comes from a file",
        "gist": "A number in the manuscript is read from a results file, never typed by hand.",
        "keywords": [],
        "content": STANDARD,
        "source_checksum": "3f2a9c1",
    }


def test_parse_entry_strips_quotes_and_ends_the_gist_at_any_sentence_mark():
    fields, problems = parse_entry(GUIDELINE)
    assert problems == []
    assert fields["title"] == "Plain words in every document"
    assert fields["source_checksum"] == "sha256:0a1b2c3d4e5f"
    assert fields["gist"] == "Write short sentences!"
    fields, _ = parse_entry(PROCEDURE)
    assert fields["gist"] == (
        "Checks that each citation in the manuscript names a source, and that the quoted"
        " text appears in it?"
    )


def test_a_paragraph_with_no_sentence_mark_is_the_whole_gist():
    text = STANDARD.replace(
        "A number in the manuscript is read from a results file, never typed by hand. The\n"
        "build fails when the two differ.",
        "Numbers come from files\nand nowhere else",
    )
    fields, problems = parse_entry(text)
    assert problems == []
    assert fields["gist"] == "Numbers come from files and nowhere else"


def test_a_heading_without_id_or_title_is_a_problem():
    _, problems = parse_entry(NO_ID)
    assert problems == ["the heading has no id"]
    _, problems = parse_entry(STANDARD.replace("title: Every number comes from a file\n", ""))
    assert problems == ["the heading has no title"]


def test_a_file_with_no_heading_block_is_a_problem():
    _, problems = parse_entry("# A title\n\nA point.\n")
    assert problems == ["the file has no heading block between --- lines"]
    _, problems = parse_entry("---\nid: x\ntitle: y\n\n# y\n")
    assert problems == ["the file has no heading block between --- lines"]


# sync


def test_sync_stores_each_entry_with_its_mapped_fields(store, corpus):
    summary = sync(store, [corpus], GIVEN)
    assert (summary.added, summary.unchanged, summary.replaced) == (3, 0, 0)
    assert summary.problems == ()
    rows = by_id(current(store, "knowledge_entries"))
    assert sorted(rows) == [
        "guidelines-plain-words",
        "procedures-references",
        "standards-numbers-from-files",
    ]
    standard = rows["standards-numbers-from-files"]
    assert standard["class"] == "STANDARDS"
    assert standard["title"] == "Every number comes from a file"
    assert standard["gist"].startswith("A number in the manuscript")
    assert standard["keywords"] == []
    assert standard["content"] == STANDARD
    assert standard["source_checksum"] == "3f2a9c1"
    assert rows["procedures-references"]["class"] == "PROCEDURES"
    for row in rows.values():
        assert {name: row[name] for name in ("session", "origin", "method", "reason")} == GIVEN
        assert row["supersedes"] is None
    assert stored_rows(store.db, "knowledge_history") == []


def test_sync_takes_single_files_as_well_as_folders(store, corpus):
    summary = sync(store, [corpus / "guidelines" / "guidelines-plain-words.md"], GIVEN)
    assert summary.added == 1
    assert [row["entry_id"] for row in current(store, "knowledge_entries")] == [
        "guidelines-plain-words"
    ]


def test_syncing_again_adds_nothing(store, corpus):
    sync(store, [corpus], GIVEN)
    before = stored_rows(store.db, "knowledge_entries")
    summary = sync(store, [corpus], LATER)
    assert (summary.added, summary.unchanged, summary.replaced) == (0, 3, 0)
    assert stored_rows(store.db, "knowledge_entries") == before
    assert stored_rows(store.db, "knowledge_history") == []


def test_an_edited_entry_moves_its_old_version_with_its_provenance_to_history(store, corpus):
    sync(store, [corpus], GIVEN)
    (old,) = [
        row
        for row in stored_rows(store.db, "knowledge_entries")
        if row["entry_id"] == "standards-numbers-from-files"
    ]
    edited = STANDARD.replace("source_commit: 3f2a9c1", "source_commit: 4b5c6d7").replace(
        "never typed by hand.", "never typed by hand or copied."
    )
    (corpus / "standards" / "standards-numbers-from-files.md").write_text(edited, encoding="utf-8")

    summary = sync(store, [corpus], LATER)
    assert (summary.added, summary.unchanged, summary.replaced) == (0, 2, 1)

    (moved,) = stored_rows(store.db, "knowledge_history")
    assert moved == old
    assert moved["session"] == "s-knowledge"
    assert moved["reason"] == "a test of the knowledge store"

    rows = [
        row
        for row in stored_rows(store.db, "knowledge_entries")
        if row["entry_id"] == "standards-numbers-from-files"
    ]
    assert len(rows) == 1
    (new,) = rows
    assert new["content"] == edited
    assert new["source_checksum"] == "4b5c6d7"
    assert new["gist"].endswith("never typed by hand or copied.")
    assert new["supersedes"] == old["id"]
    assert new["session"] == "s-knowledge-later"
    assert new["reason"] == "the entry changed"
    assert len(current(store, "knowledge_entries")) == 3


def test_history_lists_an_entrys_versions_oldest_first(store, corpus):
    path = corpus / "standards" / "standards-numbers-from-files.md"
    sync(store, [corpus], GIVEN)
    path.write_text(STANDARD.replace("3f2a9c1", "4b5c6d7"), encoding="utf-8")
    sync(store, [corpus], LATER)
    path.write_text(STANDARD.replace("3f2a9c1", "5c6d7e8"), encoding="utf-8")
    sync(store, [corpus], LATER)
    versions = history(store, "standards-numbers-from-files")
    assert [v["source_checksum"] for v in versions] == ["3f2a9c1", "4b5c6d7", "5c6d7e8"]
    assert [v["supersedes"] for v in versions[1:]] == [versions[0]["id"], versions[1]["id"]]
    assert history(store, "guidelines-plain-words")[0]["title"] == "Plain words in every document"
    assert history(store, "no-such-entry") == []


def test_the_malformed_file_is_reported_and_the_others_are_stored(store, tmp_path):
    corpus = write_corpus(tmp_path / "corpus", with_bad=True)
    summary = sync(store, [corpus], GIVEN)
    assert summary.added == 3
    assert summary.problems == (("standards/standards-no-id.md", "the heading has no id"),)
    assert len(current(store, "knowledge_entries")) == 3


def test_a_file_that_is_not_utf8_is_reported_and_the_others_are_stored(store, corpus):
    (corpus / "guidelines" / "aa-latin1.md").write_bytes("---\nid: caf\xe9\n---\n".encode("latin-1"))
    summary = sync(store, [corpus], GIVEN)
    assert summary.added == 3
    assert summary.problems == (("guidelines/aa-latin1.md", "the file is not UTF-8 text"),)
    assert len(current(store, "knowledge_entries")) == 3


def test_two_files_with_one_id_store_neither_second(store, corpus):
    copy = corpus / "standards" / "copy.md"
    copy.write_text(STANDARD.replace("Every number", "Each number"), encoding="utf-8")
    summary = sync(store, [corpus], GIVEN)
    assert summary.added == 3
    assert summary.problems == (
        (
            "standards/standards-numbers-from-files.md",
            "repeats the id standards-numbers-from-files of standards/copy.md",
        ),
    )
    (row,) = current(store, "knowledge_entries", entry_id="standards-numbers-from-files")
    assert row["title"] == "Each number comes from a file"


def test_a_path_that_is_not_there_is_refused_before_anything_is_stored(store, corpus, tmp_path):
    with pytest.raises(ValueError, match="no file or folder"):
        sync(store, [corpus, tmp_path / "missing"], GIVEN)
    assert stored_rows(store.db, "knowledge_entries") == []


def test_knowledge_history_refuses_update_and_delete(store, corpus):
    path = corpus / "standards" / "standards-numbers-from-files.md"
    sync(store, [corpus], GIVEN)
    path.write_text(STANDARD.replace("3f2a9c1", "4b5c6d7"), encoding="utf-8")
    sync(store, [corpus], LATER)
    with pytest.raises(sqlite3.DatabaseError, match="never updated"):
        store.db.execute("UPDATE knowledge_history SET title = 'x'")
    with pytest.raises(sqlite3.DatabaseError, match="never deleted"):
        store.db.execute("DELETE FROM knowledge_history")
    assert len(stored_rows(store.db, "knowledge_history")) == 1


def test_a_current_entry_is_never_updated_and_leaves_only_into_history(store, corpus):
    sync(store, [corpus], GIVEN)
    with pytest.raises(sqlite3.DatabaseError, match="never updated"):
        store.db.execute("UPDATE knowledge_entries SET title = 'x'")
    with pytest.raises(sqlite3.DatabaseError, match="only once kept in knowledge_history"):
        store.db.execute("DELETE FROM knowledge_entries")
    assert len(stored_rows(store.db, "knowledge_entries")) == 3


def test_the_tables_have_the_sketchs_fields_and_the_spine(store):
    for table in ("knowledge_entries", "knowledge_history"):
        names = [r[1] for r in store.db.execute(f"PRAGMA table_info({table})")]
        assert names == ["id"] + FIELDS + SPINE[1:]


# The command line


@pytest.fixture
def initialized(tmp_path):
    home = tmp_path / "audit"
    assert main(["init", "--home", str(home)]) == 0
    return home


def test_knowledge_sync_with_its_defaults(initialized, corpus, capsys):
    capsys.readouterr()
    assert main(["knowledge", "sync", "--home", str(initialized), "--corpus", str(corpus)]) == 0
    out = capsys.readouterr().out
    assert "added 3 entries, 0 unchanged, 0 replaced" in out
    db = sqlite3.connect(str(initialized / "audit.sqlite"))
    rows = stored_rows(db, "knowledge_entries")
    db.close()
    assert len(rows) == 3
    for row in rows:
        assert row["session"] == "none"
        assert row["origin"] == "entry files"
        assert row["method"] == "knowledge.sync 1; corpus"
        assert row["reason"] == "synced from the knowledge base's entry files"


def test_knowledge_sync_with_a_session_and_reason(initialized, corpus):
    assert (
        main(
            [
                "knowledge",
                "sync",
                "--home",
                str(initialized),
                "--corpus",
                str(corpus),
                "--session",
                "s-7",
                "--reason",
                "after the entries were moved",
            ]
        )
        == 0
    )
    db = sqlite3.connect(str(initialized / "audit.sqlite"))
    rows = stored_rows(db, "knowledge_entries")
    db.close()
    assert {(row["session"], row["reason"]) for row in rows} == {
        ("s-7", "after the entries were moved")
    }


def test_knowledge_sync_reports_a_malformed_file_and_exits_1(initialized, tmp_path, capsys):
    corpus = write_corpus(tmp_path / "corpus", with_bad=True)
    capsys.readouterr()
    assert main(["knowledge", "sync", "--home", str(initialized), "--corpus", str(corpus)]) == 1
    out = capsys.readouterr().out
    assert "not synced standards/standards-no-id.md, the heading has no id" in out
    assert "added 3 entries, 0 unchanged, 0 replaced, 1 not synced" in out


def test_knowledge_sync_refuses_a_corpus_that_is_not_there(initialized, tmp_path, capsys):
    capsys.readouterr()
    missing = tmp_path / "missing"
    assert main(["knowledge", "sync", "--home", str(initialized), "--corpus", str(missing)]) == 1
    assert "knowledge sync refused" in capsys.readouterr().err


def test_knowledge_history_prints_each_version(initialized, corpus, capsys):
    path = corpus / "standards" / "standards-numbers-from-files.md"
    main(["knowledge", "sync", "--home", str(initialized), "--corpus", str(corpus)])
    path.write_text(STANDARD.replace("3f2a9c1", "4b5c6d7"), encoding="utf-8")
    main(["knowledge", "sync", "--home", str(initialized), "--corpus", str(corpus)])
    capsys.readouterr()
    assert (
        main(["knowledge", "history", "--home", str(initialized), "standards-numbers-from-files"])
        == 0
    )
    lines = capsys.readouterr().out.strip().split("\n")
    assert len(lines) == 3
    assert "3f2a9c1" in lines[0] and "Every number comes from a file" in lines[0]
    assert "4b5c6d7" in lines[1] and "current" in lines[1]
    assert lines[2] == "2 versions"


def test_knowledge_history_of_an_unknown_entry_exits_1(initialized, capsys):
    capsys.readouterr()
    assert main(["knowledge", "history", "--home", str(initialized), "nothing-here"]) == 1
    assert "no entry nothing-here" in capsys.readouterr().err


def test_knowledge_commands_refuse_a_home_with_no_store(tmp_path, corpus, capsys):
    home = tmp_path / "empty"
    assert main(["knowledge", "sync", "--home", str(home), "--corpus", str(corpus)]) == 1
    assert main(["knowledge", "history", "--home", str(home), "x"]) == 1
    assert not (home / "audit.sqlite").exists()
