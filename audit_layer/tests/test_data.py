"""Tests for the data store (Track A, Step A14).

Appendix Table A3's Data row gives each dataset one typed table, written once,
with a catalog row of name, version, row count, checksum, and collection
date, and one codebook row per variable. The sentence after Table A3 says
datasets are never overwritten, and the decision log of 2026-08-05 names each
dataset's table ds_<id>. Types are inferred from the values, versions count up
from 1 for each name, and descriptions come from an optional YAML file (plan
choice 16). Every row carries the session and reason its command is given
(plan choice 23).

The dataset is the test story's word-count conditions, kept as a table in
fixtures/data/. Nothing here calls a model or the network, and every test runs
with its home folder inside a temporary folder. Run from the repository root
with python3 -m pytest -q audit_layer/tests.
"""
import csv
import hashlib
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from audit_layer.cli import main  # noqa: E402
from audit_layer.store import current, open_store  # noqa: E402
from audit_layer.stores.data import (  # noqa: E402
    DataError,
    add_dataset,
    read_dataset,
    write_dataset,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "data"
CONDITIONS = FIXTURES / "next_word_conditions.csv"
CONDITIONS_BYTES = CONDITIONS.read_bytes()
CODEBOOK = FIXTURES / "next_word_conditions_codebook.yaml"
DESCRIPTIONS = yaml.safe_load(CODEBOOK.read_text(encoding="utf-8"))

COLUMNS = ["key", "label", "n", "distinct", "top_share"]
TYPES = {"key": "TEXT", "label": "TEXT", "n": "INTEGER", "distinct": "INTEGER", "top_share": "REAL"}
ROWS = [
    ("none", "Question only", 60, 16, 30.0),
    ("context", "Plus the posting", 60, 15, 25.0),
    ("definition", "Plus a definition", 60, 10, 30.0),
]
SPINE = ["id", "created_at", "session", "origin", "method", "reason", "supersedes"]

GIVEN = {
    "session": "s-data",
    "origin": "data file",
    "method": "data.add_dataset 1; next_word_conditions.csv",
    "reason": "a test of the data store",
}


def stored_rows(db, table):
    cursor = db.execute(f'SELECT * FROM "{table}" ORDER BY rowid')
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def table_names(db):
    return sorted(r[0] for r in db.execute("SELECT name FROM sqlite_master"))


def declared(db, table):
    return {r[1]: r[2] for r in db.execute(f'PRAGMA table_info("{table}")')}


@pytest.fixture(autouse=True)
def home_folder(tmp_path, monkeypatch):
    """Each test's own home folder, so nothing reaches the real ~/.audit_layer."""
    home = tmp_path / "home_folder"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("AUDIT_HOME", raising=False)
    return home


@pytest.fixture
def given(tmp_path):
    """The fixture dataset and its codebook, copied into a temporary folder."""
    folder = tmp_path / "given"
    folder.mkdir()
    shutil.copyfile(str(CONDITIONS), str(folder / CONDITIONS.name))
    shutil.copyfile(str(CODEBOOK), str(folder / CODEBOOK.name))
    return folder


@pytest.fixture
def store(tmp_path):
    audit = open_store(tmp_path / "audit_home")
    yield audit
    audit.db.close()


@pytest.fixture
def added(store, given):
    row = add_dataset(
        store, "next_word_conditions", given / CONDITIONS.name, "2026-10-21", DESCRIPTIONS, GIVEN
    )
    return store, row


def write_csv(path, text):
    path.write_text(text, encoding="utf-8")
    return path


# The typed table, the catalog row, and the codebook.


def test_the_dataset_gets_a_table_with_the_inferred_types(added):
    store, row = added
    assert row["table_name"] == "ds_" + row["id"]
    columns = declared(store.db, row["table_name"])
    assert {name: columns[name] for name in COLUMNS} == TYPES
    assert sorted(columns) == sorted(COLUMNS + SPINE)
    values = store.db.execute(
        f'SELECT key, label, n, "distinct", top_share FROM "{row["table_name"]}" ORDER BY rowid'
    ).fetchall()
    assert values == ROWS
    kinds = store.db.execute(
        f'SELECT typeof(key), typeof(n), typeof("distinct"), typeof(top_share)'
        f' FROM "{row["table_name"]}"'
    ).fetchall()
    assert set(kinds) == {("text", "integer", "integer", "real")}


def test_the_catalog_row_has_the_row_count_checksum_and_date(added):
    store, row = added
    (catalog,) = current(store, "datasets")
    assert catalog == row
    assert (catalog["name"], catalog["version"], catalog["row_count"]) == (
        "next_word_conditions",
        1,
        3,
    )
    assert catalog["file_sha256"] == hashlib.sha256(CONDITIONS_BYTES).hexdigest()
    assert catalog["collected_on"] == "2026-10-21"
    assert catalog["supersedes"] is None
    assert {k: catalog[k] for k in GIVEN} == GIVEN


def test_the_codebook_has_each_variable_with_its_type_and_description(added):
    store, row = added
    entries = current(store, "codebook")
    assert [e["variable"] for e in entries] == COLUMNS
    for entry in entries:
        assert entry["dataset"] == row["id"]
        assert entry["type"] == TYPES[entry["variable"]]
        assert entry["description"] == DESCRIPTIONS[entry["variable"]]
        assert {k: entry[k] for k in GIVEN} == GIVEN


def test_without_descriptions_the_codebook_descriptions_are_empty(store, given):
    row = add_dataset(store, "plain", given / CONDITIONS.name, "2026-10-21", None, GIVEN)
    assert {e["description"] for e in current(store, "codebook", dataset=row["id"])} == {""}


def test_the_dataset_rows_carry_the_spine_with_the_catalog_rows_provenance(added):
    store, row = added
    rows = stored_rows(store.db, row["table_name"])
    assert len(rows) == 3
    assert len({r["id"] for r in rows}) == 3
    for stored in rows:
        assert {k: stored[k] for k in GIVEN} == GIVEN
        assert stored["created_at"] == row["created_at"]
        assert stored["supersedes"] is None


def test_updating_or_deleting_a_row_of_the_dataset_table_is_refused(added):
    store, row = added
    table = row["table_name"]
    with pytest.raises(sqlite3.DatabaseError, match="never updated"):
        with store.db:
            store.db.execute(f'UPDATE "{table}" SET n = 61')
    with pytest.raises(sqlite3.DatabaseError, match="never deleted"):
        with store.db:
            store.db.execute(f'DELETE FROM "{table}"')
    assert read_dataset(store, "next_word_conditions") == (COLUMNS, ROWS)
    for name in ("datasets", "codebook"):
        with pytest.raises(sqlite3.DatabaseError):
            with store.db:
                store.db.execute(f"DELETE FROM {name}")


# Versions.


def test_adding_the_name_again_makes_version_2_and_keeps_version_1(added, given, tmp_path):
    store, first = added
    more = write_csv(
        tmp_path / "more.csv",
        "key,label,n,distinct,top_share\nnone,Question only,120,22,28.5\n",
    )
    second = add_dataset(store, "next_word_conditions", more, "2026-10-28", None, GIVEN)
    assert second["version"] == 2
    assert second["supersedes"] == first["id"]
    assert second["row_count"] == 1
    assert second["table_name"] == "ds_" + second["id"] != first["table_name"]
    assert [r["id"] for r in current(store, "datasets")] == [second["id"]]

    # Version 1's table and catalog row stay in the store.
    assert first["table_name"] in table_names(store.db)
    assert first["id"] in [r["id"] for r in stored_rows(store.db, "datasets")]
    assert read_dataset(store, "next_word_conditions", 1) == (COLUMNS, ROWS)
    assert read_dataset(store, "next_word_conditions") == (
        COLUMNS,
        [("none", "Question only", 120, 22, 28.5)],
    )
    assert read_dataset(store, "next_word_conditions", 2) == read_dataset(
        store, "next_word_conditions"
    )


def test_another_name_starts_at_version_1(added, given):
    store, _ = added
    other = add_dataset(store, "conditions_copy", given / CONDITIONS.name, "2026-10-21", None, GIVEN)
    assert other["version"] == 1
    assert len(current(store, "datasets")) == 2


def test_reading_an_unknown_name_or_version_is_refused(added):
    store, _ = added
    with pytest.raises(DataError, match="nothing_here"):
        read_dataset(store, "nothing_here")
    with pytest.raises(DataError, match="version 3"):
        read_dataset(store, "next_word_conditions", 3)


# Written out and read back.


def test_rows_written_out_and_read_back_equal_the_stored_rows(added, tmp_path):
    store, _ = added
    out = tmp_path / "out"
    paths = write_dataset(store, "next_word_conditions", 1, out)
    data = out / "next_word_conditions_v1.csv"
    codebook = out / "next_word_conditions_v1_codebook.csv"
    assert sorted(paths) == sorted([data, codebook])
    # The table the store holds writes out as the file it was given.
    assert data.read_bytes() == CONDITIONS_BYTES

    back = add_dataset(store, "read_back", data, "2026-10-21", None, GIVEN)
    assert read_dataset(store, "read_back") == read_dataset(store, "next_word_conditions")
    assert {e["variable"]: e["type"] for e in current(store, "codebook", dataset=back["id"])} == TYPES

    with codebook.open(newline="", encoding="utf-8") as handle:
        written = list(csv.DictReader(handle))
    assert [dict(r) for r in written] == [
        {"variable": name, "type": TYPES[name], "description": DESCRIPTIONS[name]}
        for name in COLUMNS
    ]


def test_writing_an_unknown_version_is_refused_and_writes_nothing(added, tmp_path):
    store, _ = added
    with pytest.raises(DataError):
        write_dataset(store, "next_word_conditions", 2, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_a_column_named_with_a_space_is_stored_and_written_out_under_that_name(store, tmp_path):
    given = write_csv(tmp_path / "spaced.csv", "key,top share\nnone,30.0\ncontext,25.0\n")
    row = add_dataset(store, "spaced", given, "2026-10-21", {"top share": "The top share"}, GIVEN)
    assert declared(store.db, row["table_name"])["top share"] == "REAL"
    assert read_dataset(store, "spaced") == (["key", "top share"], [("none", 30.0), ("context", 25.0)])
    write_dataset(store, "spaced", 1, tmp_path / "out")
    assert (tmp_path / "out" / "spaced_v1.csv").read_bytes() == given.read_bytes()
    codebook = (tmp_path / "out" / "spaced_v1_codebook.csv").read_text(encoding="utf-8")
    assert "top share,REAL,The top share" in codebook.splitlines()


def test_a_column_named_with_a_word_sql_keeps_is_stored(store, tmp_path):
    given = write_csv(tmp_path / "words.csv", 'select,"a ""quoted"" name"\n1,x\n')
    add_dataset(store, "words", given, "2026-10-21", None, GIVEN)
    assert read_dataset(store, "words") == (["select", 'a "quoted" name'], [(1, "x")])


def test_an_empty_value_is_stored_as_null_and_written_back_empty(store, tmp_path):
    given = write_csv(tmp_path / "gaps.csv", "a,b,c\n1,,x\n,2.5,\n3,1.5,y\n")
    row = add_dataset(store, "gaps", given, "2026-10-21", None, GIVEN)
    assert read_dataset(store, "gaps") == (["a", "b", "c"], [(1, None, "x"), (None, 2.5, None), (3, 1.5, "y")])
    assert {e["variable"]: e["type"] for e in current(store, "codebook", dataset=row["id"])} == {
        "a": "INTEGER",
        "b": "REAL",
        "c": "TEXT",
    }
    write_dataset(store, "gaps", 1, tmp_path / "out")
    assert (tmp_path / "out" / "gaps_v1.csv").read_bytes() == given.read_bytes()


def test_a_column_of_decimal_numbers_is_real_however_they_are_written(store, tmp_path):
    # Whole numbers beside decimals, a trailing zero, and exponents are all
    # numbers, so their columns are REAL, and each writes back as the number
    # stored.
    given = write_csv(
        tmp_path / "numbers.csv",
        "mixed,trailing,exponent\n1,0.10,1e3\n1.5,2.50,2.5e-4\n2,-0.5,\n",
    )
    row = add_dataset(store, "numbers", given, "2026-10-21", None, GIVEN)
    assert {e["variable"]: e["type"] for e in current(store, "codebook", dataset=row["id"])} == {
        "mixed": "REAL",
        "trailing": "REAL",
        "exponent": "REAL",
    }
    assert read_dataset(store, "numbers") == (
        ["mixed", "trailing", "exponent"],
        [(1.0, 0.1, 1000.0), (1.5, 2.5, 0.00025), (2.0, -0.5, None)],
    )
    write_dataset(store, "numbers", 1, tmp_path / "out")
    written = tmp_path / "out" / "numbers_v1.csv"
    assert written.read_text(encoding="utf-8") == (
        "mixed,trailing,exponent\n1.0,0.1,1000.0\n1.5,2.5,0.00025\n2.0,-0.5,\n"
    )
    # What is written out reads back as the rows stored.
    add_dataset(store, "numbers_back", written, "2026-10-21", None, GIVEN)
    assert read_dataset(store, "numbers_back") == read_dataset(store, "numbers")


def test_a_code_with_a_leading_zero_an_overflow_or_no_values_keeps_its_column_text(store, tmp_path):
    # 007 is a code whose zeros a number would drop, 1e999 is no finite
    # number, and a column with no values is text too.
    given = write_csv(
        tmp_path / "codes.csv", "zip,code,huge,blank\n007,01.5,1e999,\n83843,2.5,1,\n"
    )
    row = add_dataset(store, "codes", given, "2026-10-21", None, GIVEN)
    assert {e["variable"]: e["type"] for e in current(store, "codebook", dataset=row["id"])} == {
        "zip": "TEXT",
        "code": "TEXT",
        "huge": "TEXT",
        "blank": "TEXT",
    }
    write_dataset(store, "codes", 1, tmp_path / "out")
    assert (tmp_path / "out" / "codes_v1.csv").read_bytes() == given.read_bytes()


def test_blank_lines_at_the_end_of_the_file_are_not_rows(store, tmp_path):
    given = write_csv(tmp_path / "trailing.csv", "a,b\n1,2\n3,4\n\n\n")
    row = add_dataset(store, "trailing", given, "2026-10-21", None, GIVEN)
    assert row["row_count"] == 2
    assert read_dataset(store, "trailing") == (["a", "b"], [(1, 2), (3, 4)])


# What is refused, with nothing stored.


def nothing_stored(store, before):
    assert table_names(store.db) == before
    assert stored_rows(store.db, "datasets") == []
    assert stored_rows(store.db, "codebook") == []


@pytest.mark.parametrize(
    "text, said",
    [
        ("a,b\n1,2\n3\n", "line 3"),
        ("a,b\n1,2,3\n", "line 2"),
        ("a,b\n1,2\n\n4,5\n", "line 3 is empty"),
        ("a,b,a\n1,2,3\n", "a"),
        ("Key,key\n1,2\n", "key"),
        ("a,,c\n1,2,3\n", "no name"),
        ("", "header"),
        ("id,value\n1,2\n", "id"),
        ("value,Session\n1,2\n", "Session"),
        ("rowid,value\n1,2\n", "rowid"),
    ],
)
def test_a_file_the_store_cannot_hold_as_a_table_stores_nothing(store, tmp_path, text, said):
    before = table_names(store.db)
    path = write_csv(tmp_path / "bad.csv", text)
    with pytest.raises(DataError, match=said):
        add_dataset(store, "bad", path, "2026-10-21", None, GIVEN)
    nothing_stored(store, before)


@pytest.mark.parametrize("date", ["21 October 2026", "2026-10-32", "2026/10/21", ""])
def test_a_collection_date_not_in_year_month_day_form_is_refused(store, given, date):
    before = table_names(store.db)
    with pytest.raises(DataError, match="YYYY-MM-DD"):
        add_dataset(store, "next_word_conditions", given / CONDITIONS.name, date, None, GIVEN)
    nothing_stored(store, before)


@pytest.mark.parametrize("name", ["", "../up", "two words", ".hidden", "a/b"])
def test_a_name_that_cannot_name_a_file_is_refused(store, given, name):
    before = table_names(store.db)
    with pytest.raises(DataError, match="name"):
        add_dataset(store, name, given / CONDITIONS.name, "2026-10-21", None, GIVEN)
    nothing_stored(store, before)


def test_a_description_of_a_variable_the_file_lacks_is_refused(store, given):
    before = table_names(store.db)
    with pytest.raises(DataError, match="top_word"):
        add_dataset(
            store, "next_word_conditions", given / CONDITIONS.name, "2026-10-21",
            dict(DESCRIPTIONS, top_word="The most common word"), GIVEN,
        )
    nothing_stored(store, before)


def test_a_file_that_is_not_utf8_text_stores_nothing(store, tmp_path):
    before = table_names(store.db)
    path = tmp_path / "bad.csv"
    path.write_bytes(b"a,b\n\xff,2\n")
    with pytest.raises(ValueError):
        add_dataset(store, "bad", path, "2026-10-21", None, GIVEN)
    nothing_stored(store, before)


# The command line.


@pytest.fixture
def initialized(tmp_path):
    home = tmp_path / "cli_home"
    assert main(["init", "--home", str(home)]) == 0
    return home


def data(home, action, *extra):
    return main(["data", action, "--home", str(home), *extra])


def cli_rows(home, table):
    audit = open_store(home)
    try:
        return stored_rows(audit.db, table)
    finally:
        audit.db.close()


def test_data_add_with_its_defaults(initialized, given, capsys):
    capsys.readouterr()
    code = data(
        initialized, "add", "--name", "next_word_conditions", "--csv",
        str(given / CONDITIONS.name), "--collected", "2026-10-21",
    )
    assert code == 0
    assert capsys.readouterr().out.splitlines() == [
        "added next_word_conditions version 1, 3 rows, 5 variables"
    ]
    (catalog,) = cli_rows(initialized, "datasets")
    assert (catalog["session"], catalog["origin"], catalog["method"], catalog["reason"]) == (
        "none",
        "data file",
        "data.add_dataset 1; next_word_conditions.csv",
        "added a collected dataset",
    )
    assert {e["description"] for e in cli_rows(initialized, "codebook")} == {""}


def test_data_add_with_a_codebook_session_and_reason(initialized, given):
    code = data(
        initialized, "add", "--name", "next_word_conditions", "--csv",
        str(given / CONDITIONS.name), "--collected", "2026-10-21", "--codebook",
        str(given / CODEBOOK.name), "--session", "s5", "--reason", "the talk's counts",
    )
    assert code == 0
    entries = cli_rows(initialized, "codebook")
    assert {e["variable"]: e["description"] for e in entries} == DESCRIPTIONS
    for table in ("datasets", "codebook"):
        assert {(r["session"], r["reason"]) for r in cli_rows(initialized, table)} == {
            ("s5", "the talk's counts")
        }


@pytest.mark.parametrize(
    "text",
    [
        "- a list\n- of terms\n",
        "key: [not, text]\n",
        "true: a key that is not text\n",
        "key: [unclosed\n",
    ],
)
def test_data_add_refuses_a_codebook_that_is_not_a_map_of_text(initialized, given, tmp_path, capsys, text):
    bad = write_csv(tmp_path / "bad.yaml", text)
    capsys.readouterr()
    code = data(
        initialized, "add", "--name", "next_word_conditions", "--csv",
        str(given / CONDITIONS.name), "--collected", "2026-10-21", "--codebook", str(bad),
    )
    assert code == 1
    assert capsys.readouterr().err.startswith("data add refused, ")
    assert cli_rows(initialized, "datasets") == []


def test_data_add_refuses_a_ragged_file(initialized, tmp_path, capsys):
    bad = write_csv(tmp_path / "bad.csv", "a,b\n1\n")
    capsys.readouterr()
    assert data(initialized, "add", "--name", "bad", "--csv", str(bad), "--collected", "2026-10-21") == 1
    assert "line 2" in capsys.readouterr().err
    assert cli_rows(initialized, "datasets") == []


def test_data_list_prints_each_current_dataset(initialized, given, capsys):
    csv_path = str(given / CONDITIONS.name)
    for _ in range(2):
        data(initialized, "add", "--name", "next_word_conditions", "--csv", csv_path, "--collected", "2026-10-21")
    data(initialized, "add", "--name", "copy", "--csv", csv_path, "--collected", "2026-10-22")
    capsys.readouterr()
    assert data(initialized, "list") == 0
    assert capsys.readouterr().out.splitlines() == [
        "next_word_conditions  version 2  3 rows  collected 2026-10-21",
        "copy  version 1  3 rows  collected 2026-10-22",
        "2 datasets",
    ]


def test_data_commands_refuse_a_home_with_no_store(tmp_path, given, capsys):
    empty = tmp_path / "empty_home"
    assert data(empty, "list") == 1
    assert data(
        empty, "add", "--name", "x", "--csv", str(given / CONDITIONS.name), "--collected", "2026-10-21"
    ) == 1
    assert "no audit store" in capsys.readouterr().err
    assert not empty.exists()
