"""Tests for the field definitions table (Track A, Step A18).

Appendix Table A3's Shared tables row keeps each field's definition,
generation rule, and null behavior, and Figure A4 draws the field definitions
among the shared tables. Spec 0.11 has the schema document itself. The
definitions live in code, in audit_layer/fields.py, and are written to their
table when the store opens, and a test fails when a column lacks a definition
(plan choice 20). The spine is defined once, under the table name *, and a
dataset's own columns are left to its codebook.

The store is the one full_store.build_full_store makes from the test story
and Track A's fixtures, with at least one current row in every table. Nothing
here calls a model or the network, and every test runs with its home folder
inside a temporary folder. Run from the repository root with
python3 -m pytest -q audit_layer/tests.
"""
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import audit_layer.fields as fields  # noqa: E402
from audit_layer.cli import main  # noqa: E402
from audit_layer.fields import FIELDS, SPINE_TABLE, FieldDef, sync_definitions  # noqa: E402
from audit_layer.store import TABLES, current, open_store  # noqa: E402
from audit_layer.tests.full_store import build_full_store  # noqa: E402

SPINE = ["id", "created_at", "session", "origin", "method", "reason", "supersedes"]
SCHEMA = {"session": "none", "origin": "audit_layer", "method": "fields 1", "reason": "schema"}


def stored_rows(db, table):
    cursor = db.execute(f'SELECT * FROM "{table}" ORDER BY rowid')
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def store_tables(db):
    return sorted(r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'"))


def columns_of(db, table):
    return [r[1] for r in db.execute(f'PRAGMA table_info("{table}")')]


def every_row(db):
    return {table: stored_rows(db, table) for table in store_tables(db)}


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


def defined(store):
    """The current definitions, by table name and field."""
    return {(row["table_name"], row["field"]): row for row in current(store, "field_definitions")}


# The full store.


def test_the_full_store_has_a_current_row_in_every_table(full):
    tables = store_tables(full.store.db)
    assert set(TABLES) <= set(tables)
    assert any(name.startswith("ds_") for name in tables)
    for table in tables:
        if table.startswith("ds_"):
            assert stored_rows(full.store.db, table), table
        else:
            assert current(full.store, table), table
    assert len(current(full.store, "knowledge_history")) == 1
    assert {row["origin"] for row in current(full.store, "sessions")} == {
        "model pass",
        "person A. Reviewer",
    }


# Every column has its definition.


def test_every_column_has_a_current_definition_under_its_table_or_under_the_spine(full):
    held = defined(full.store)
    for table in store_tables(full.store.db):
        if table.startswith("ds_"):
            continue
        for column in columns_of(full.store.db, table):
            if column in SPINE:
                assert (SPINE_TABLE, column) in held, column
                assert (table, column) not in held, (table, column)
            else:
                assert (table, column) in held, (table, column)


def test_each_dataset_table_s_own_columns_are_covered_by_its_codebook(full):
    held = defined(full.store)
    tables = [name for name in store_tables(full.store.db) if name.startswith("ds_")]
    assert tables
    for table in tables:
        (catalog,) = [row for row in current(full.store, "datasets") if row["table_name"] == table]
        variables = [row["variable"] for row in current(full.store, "codebook", dataset=catalog["id"])]
        own = [column for column in columns_of(full.store.db, table) if column not in SPINE]
        assert own == variables
        assert all((SPINE_TABLE, column) in held for column in SPINE)
        assert not any(key[0] == table for key in held)


def test_every_definition_names_a_column_the_store_has_and_says_all_three_things():
    store_columns = {table: [name for name, _ in spec] for table, spec in TABLES.items()}
    seen = set()
    for item in FIELDS:
        assert isinstance(item, FieldDef)
        assert (item.table_name, item.field) not in seen
        seen.add((item.table_name, item.field))
        if item.table_name == SPINE_TABLE:
            assert item.field in SPINE
        else:
            assert item.field in store_columns[item.table_name], item
        for text in (item.definition, item.generation_rule, item.null_behavior):
            assert isinstance(text, str) and text.strip(), item
            assert "\u2014" not in text
    assert {item.field for item in FIELDS if item.table_name == SPINE_TABLE} == set(SPINE)
    for table, names in store_columns.items():
        assert {item.field for item in FIELDS if item.table_name == table} == set(names), table


# Writing the definitions.


def test_a_new_store_holds_one_current_row_for_each_definition(tmp_path):
    store = open_store(tmp_path / "audit_home")
    try:
        rows = current(store, "field_definitions")
        assert [
            FieldDef(r["table_name"], r["field"], r["definition"], r["generation_rule"], r["null_behavior"])
            for r in rows
        ] == list(FIELDS)
        for row in rows:
            assert {name: row[name] for name in SCHEMA} == SCHEMA
            assert row["supersedes"] is None
    finally:
        store.db.close()


def test_opening_the_store_again_writes_nothing(full):
    before = every_row(full.store.db)
    store = open_store(full.home)
    try:
        assert every_row(store.db) == before
        assert sync_definitions(store) == 0
        assert every_row(store.db) == before
    finally:
        store.db.close()


def test_a_changed_definition_supersedes_the_stored_row_and_keeps_the_old_one(full, monkeypatch):
    (old,) = [
        row
        for row in current(full.store, "field_definitions")
        if (row["table_name"], row["field"]) == ("sessions", "title")
    ]
    changed = [
        item._replace(definition="A title for the session, written for a reader.")
        if (item.table_name, item.field) == ("sessions", "title")
        else item
        for item in FIELDS
    ]
    monkeypatch.setattr(fields, "FIELDS", tuple(changed))
    count = len(stored_rows(full.store.db, "field_definitions"))

    store = open_store(full.home)
    try:
        rows = stored_rows(store.db, "field_definitions")
        assert len(rows) == count + 1
        assert old in rows
        (new,) = [row for row in current(store, "field_definitions") if row["field"] == "title"
                  and row["table_name"] == "sessions"]
        assert new["supersedes"] == old["id"]
        assert new["definition"] == "A title for the session, written for a reader."
        assert new["generation_rule"] == old["generation_rule"]
        assert {name: new[name] for name in SCHEMA} == SCHEMA
        assert len(current(store, "field_definitions")) == len(FIELDS)
    finally:
        store.db.close()


def test_a_new_definition_is_added_once(full, monkeypatch):
    extra = FieldDef("projects", "folder_note", "A note.", "set by a test", "never empty")
    monkeypatch.setattr(fields, "FIELDS", tuple(FIELDS) + (extra,))
    assert sync_definitions(full.store) == 1
    assert sync_definitions(full.store) == 0
    assert ("projects", "folder_note") in defined(full.store)


def test_the_field_definitions_table_has_its_fields_and_refuses_update_and_delete(tmp_path):
    store = open_store(tmp_path / "audit_home")
    try:
        names = columns_of(store.db, "field_definitions")
        assert names == [
            "id",
            "table_name",
            "field",
            "definition",
            "generation_rule",
            "null_behavior",
        ] + SPINE[1:]
        with pytest.raises(sqlite3.DatabaseError, match="never updated"):
            store.db.execute("UPDATE field_definitions SET definition = 'changed'")
        with pytest.raises(sqlite3.DatabaseError, match="never deleted"):
            store.db.execute("DELETE FROM field_definitions")
    finally:
        store.db.close()


# The fields command.


def test_fields_sessions_prints_the_session_fields_with_their_rules(full, capsys):
    assert main(["fields", "sessions", "--home", str(full.home)]) == 0
    expected = []
    own = [item for item in FIELDS if item.table_name == "sessions"]
    for item in own:
        expected += [
            f"sessions.{item.field}",
            f"  {item.definition}",
            f"  generated by {item.generation_rule}",
            f"  {item.null_behavior}",
        ]
    expected.append(f"{len(own)} fields")
    assert capsys.readouterr().out.splitlines() == expected
    assert "title" in [item.field for item in own]


def test_fields_with_no_table_prints_every_definition(full, capsys):
    assert main(["fields", "--home", str(full.home)]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[-1] == f"{len(FIELDS)} fields"
    assert "*.session" in out
    assert "projects.folder" in out


def test_fields_refuses_a_table_with_no_definitions(full, capsys):
    assert main(["fields", "no_such_table", "--home", str(full.home)]) == 1
    assert "no_such_table" in capsys.readouterr().err


def test_fields_refuses_a_home_with_no_store(tmp_path, capsys):
    home = tmp_path / "no_home"
    assert main(["fields", "--home", str(home)]) == 1
    assert "no audit store" in capsys.readouterr().err
    assert not home.exists()
