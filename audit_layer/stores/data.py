"""The data store, one typed table for each dataset version.

Proposal Overview paragraph 2 gives the databases stores for research data.
Appendix Table A3's Data row gives each dataset one typed table, written
once, with a catalog row of name, version, row count, checksum, and
collection date, and one codebook row per variable, and the sentence after
Table A3 says datasets are never overwritten. Each version's table is named
ds_<catalog row id> (decision log of 2026-08-05). Types are inferred from the
values, versions count up from 1 for each name, and descriptions come from an
optional YAML file the command line reads (plan choice 16).

- add_dataset(store, name, csv_path, collected_on, descriptions, provenance)
  stores a CSV file as the name's next version and gives its catalog row.
- read_dataset(store, name, version=None) gives a version's columns and rows,
  the latest when no version is named.
- write_dataset(store, name, version, out_dir) writes the version back out as
  <name>_v<version>.csv beside <name>_v<version>_codebook.csv.
- dataset_files(store, name, version=None) gives the version's catalog row
  and the bytes of those two files, which the project write-out writes
  (Step A20).

A column is INTEGER when every value in it is a whole number, REAL when every
one is a finite decimal number, and TEXT otherwise, with an empty value
stored as null. A number may have a sign, a decimal point, and an exponent,
so 1 beside 1.5, 0.10, and 2.5e-4 are numbers, and a REAL column writes back
out as the numbers stored, 1.0, 0.1, and 0.00025. A value whose whole part
starts with a zero followed by more digits, such as 007, is a code and not a
number, so its column keeps its text. A column with no values is TEXT.
Blank lines at the end of the file are not rows.

A dataset's table has one column per variable and the spine every row of the
store carries, filled with the catalog row's provenance, and triggers refuse
an update or a delete. A column may not take a spine field's name, nor rowid,
oid, or _rowid_, the names SQLite keeps for a row's own number.
"""
import csv
import hashlib
import io
import math
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from audit_layer.store import PROVENANCE, Store, current, writing
from audit_layer.stores import is_date

VERSION = 1

# A dataset's name becomes part of a file name when it is written out.
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_INTEGER = re.compile(r"-?[0-9]+")
_REAL = re.compile(r"-?([0-9]+\.[0-9]*|\.[0-9]+|[0-9]+)([eE][-+]?[0-9]+)?")
# A whole part of a zero and more digits, as in 007, marks a code.
_LEADING_ZERO = re.compile(r"-?0[0-9]")
_SPINE = ("id", "created_at") + PROVENANCE + ("supersedes",)
_KEPT = _SPINE + ("rowid", "oid", "_rowid_")


class DataError(ValueError):
    """A dataset the data store refuses."""


def add_dataset(
    store: Store,
    name: str,
    csv_path,
    collected_on: str,
    descriptions: Optional[Dict[str, str]],
    provenance: Dict[str, str],
) -> Dict[str, Any]:
    """Store the CSV file at csv_path as the next version of name and give its catalog row.

    The file's first row names the variables, and blank lines at its end
    are not rows. The version is one more than the name's latest, from 1,
    and its catalog row supersedes the latest's, whose table stays.
    descriptions maps variables to their codebook descriptions, and a
    variable it leaves out has an empty one. A ragged row, a blank line
    between rows, a repeated column name, a column with no name or a name
    the store keeps, a description of a variable the file lacks, a name that
    cannot name a file, or a date not written YYYY-MM-DD is refused, and then
    nothing is stored.
    """
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise DataError(
            f"the dataset name {name!r} cannot name a file. Use letters, digits, '.', '-', and"
            " '_', starting with a letter or digit"
        )
    if not is_date(collected_on):
        raise DataError(f"the collection date {collected_on!r} is not a date written YYYY-MM-DD")
    data = Path(csv_path).read_bytes()
    columns, rows = _read_csv(data.decode("utf-8-sig"))
    descriptions = dict(descriptions or {})
    unknown = [variable for variable in descriptions if variable not in columns]
    if unknown:
        raise DataError(
            "the codebook describes "
            + ", ".join(str(variable) for variable in unknown)
            + ", which the file does not have"
        )
    types = [_type([row[index] for row in rows]) for index in range(len(columns))]
    catalog_id = uuid.uuid4().hex
    table = "ds_" + catalog_id
    fields = {
        "name": name,
        "row_count": len(rows),
        "file_sha256": hashlib.sha256(data).hexdigest(),
        "collected_on": collected_on,
        "table_name": table,
    }
    with writing(store) as write:
        latest = store.db.execute(
            "SELECT max(version) FROM datasets WHERE name = ?", (name,)
        ).fetchone()[0]
        fields["version"] = (latest or 0) + 1
        previous = current(store, "datasets", name=name)
        if previous:
            write.supersede("datasets", previous[-1]["id"], fields, provenance, row_id=catalog_id)
        else:
            write.add("datasets", fields, provenance, row_id=catalog_id)
        (catalog,) = current(store, "datasets", id=catalog_id)
        _make_table(store, table, columns, types)
        spine = [catalog["created_at"]] + [provenance[field] for field in PROVENANCE] + [None]
        names = ["id"] + columns + list(_SPINE[1:])
        store.db.executemany(
            f"INSERT INTO {_quote(table)} ({', '.join(_quote(n) for n in names)})"
            f" VALUES ({', '.join('?' for _ in names)})",
            [
                [uuid.uuid4().hex] + [_value(value, kind) for value, kind in zip(row, types)] + spine
                for row in rows
            ],
        )
        for variable, kind in zip(columns, types):
            write.add(
                "codebook",
                {
                    "dataset": catalog_id,
                    "variable": variable,
                    "type": kind,
                    "description": str(descriptions.get(variable) or ""),
                },
                provenance,
            )
    return catalog


def read_dataset(store: Store, name: str, version: Optional[int] = None) -> Tuple[List[str], List[tuple]]:
    """The columns and rows of name's version, the latest when version is None.

    Rows come in the order the file gave them, with each value of its
    column's type and an empty value as None.
    """
    catalog = _catalog(store, name, version)
    columns = [entry["variable"] for entry in _codebook(store, catalog)]
    cursor = store.db.execute(
        f"SELECT {', '.join(_quote(c) for c in columns)} FROM {_quote(catalog['table_name'])}"
        " ORDER BY rowid"
    )
    return columns, [tuple(row) for row in cursor.fetchall()]


def write_dataset(store: Store, name: str, version: int, out_dir) -> List[Path]:
    """Write name's version out as <name>_v<version>.csv and its codebook, and give both paths.

    The codebook file has the columns variable, type, and description. An
    unknown name or version is refused before anything is written.
    """
    catalog, data, codebook = dataset_files(store, name, version)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = f"{name}_v{catalog['version']}"
    data_path = out / f"{stem}.csv"
    codebook_path = out / f"{stem}_codebook.csv"
    data_path.write_bytes(data)
    codebook_path.write_bytes(codebook)
    return [data_path, codebook_path]


def dataset_files(
    store: Store, name: str, version: Optional[int] = None
) -> Tuple[Dict[str, Any], bytes, bytes]:
    """The catalog row of name's version and the bytes of its CSV file and its codebook file.

    The version is the latest when version is None. The files are the ones
    write_dataset writes, UTF-8 with a newline ending each line. An unknown
    name or version is refused.
    """
    catalog = _catalog(store, name, version)
    entries = _codebook(store, catalog)
    columns, rows = read_dataset(store, name, catalog["version"])
    data = _csv_bytes(columns, [[_text(value) for value in row] for row in rows])
    codebook = _csv_bytes(
        ["variable", "type", "description"],
        [[e["variable"], e["type"], e["description"] or ""] for e in entries],
    )
    return catalog, data, codebook


def _read_csv(text: str) -> Tuple[List[str], List[List[str]]]:
    """The header and the rows of a CSV file's text, refusing what cannot be one table."""
    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        header = next(reader, None)
        if not header:
            raise DataError("the file has no header row naming its variables")
        seen = {}
        for index, column in enumerate(header):
            if not column.strip():
                raise DataError(f"column {index + 1} of the header has no name")
            if column.lower() in _KEPT:
                raise DataError(
                    f"the column {column} has a name the store keeps for itself. The names "
                    + ", ".join(_KEPT)
                    + " cannot name a variable"
                )
            # SQLite does not tell names apart by case.
            if column.lower() in seen:
                raise DataError(
                    f"the column {column} repeats the name {seen[column.lower()]}, so it"
                    " cannot be stored"
                )
            seen[column.lower()] = column
        rows = []
        blank = None
        for row in reader:
            if not row:
                # A blank line counts only when a row follows it.
                blank = blank or reader.line_num
                continue
            if blank:
                raise DataError(
                    f"line {blank} is empty, between rows of the file, so the file is not stored"
                )
            if len(row) != len(header):
                raise DataError(
                    f"line {reader.line_num} has {len(row)} values where the header names"
                    f" {len(header)}, so the file is not stored"
                )
            rows.append(row)
    except csv.Error as error:
        raise DataError(f"the file cannot be read as CSV, {error}")
    return header, rows


def _type(values: List[str]) -> str:
    """INTEGER, REAL, or TEXT, as every non-empty value is a whole number, a number, or not."""
    given = [value for value in values if value != ""]
    if not given:
        return "TEXT"
    if all(_is_integer(value) for value in given):
        return "INTEGER"
    if all(_is_real(value) for value in given):
        return "REAL"
    return "TEXT"


def _is_integer(value: str) -> bool:
    if not _INTEGER.fullmatch(value):
        return False
    number = int(value)
    return str(number) == value and -(2 ** 63) <= number < 2 ** 63


def _is_real(value: str) -> bool:
    if not _REAL.fullmatch(value) or _LEADING_ZERO.match(value):
        return False
    return math.isfinite(float(value))


def _value(value: str, kind: str) -> Any:
    if value == "":
        return None
    if kind == "INTEGER":
        return int(value)
    if kind == "REAL":
        return float(value)
    return value


def _text(value: Any) -> str:
    """A stored value as the text it was given."""
    if value is None:
        return ""
    if isinstance(value, float):
        return repr(value)
    return str(value)


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _make_table(store: Store, table: str, columns: List[str], types: List[str]) -> None:
    """Make the dataset's table and the triggers that refuse an update or a delete."""
    lines = ["id TEXT PRIMARY KEY NOT NULL"]
    lines += [f"{_quote(column)} {kind}" for column, kind in zip(columns, types)]
    lines.append("created_at TEXT NOT NULL")
    lines += [f"{field} TEXT NOT NULL CHECK (length(trim({field})) > 0)" for field in PROVENANCE]
    lines.append("supersedes TEXT")
    store.db.execute(f"CREATE TABLE {_quote(table)} (\n  " + ",\n  ".join(lines) + "\n)")
    for verb, event in (("updated", "UPDATE"), ("deleted", "DELETE")):
        store.db.execute(
            f"CREATE TRIGGER {_quote(table + '_never_' + verb)} BEFORE {event} ON {_quote(table)}"
            f" BEGIN SELECT RAISE(ABORT, 'dataset rows are never {verb}'); END"
        )


def _catalog(store: Store, name: str, version: Optional[int]) -> Dict[str, Any]:
    """The catalog row of name's version, the current one when version is None."""
    if version is None:
        rows = current(store, "datasets", name=name)
        if not rows:
            raise DataError(f"there is no dataset {name} in the data store")
        return rows[-1]
    # A version's catalog row stays whole in the table once a later one supersedes it.
    cursor = store.db.execute(
        "SELECT * FROM datasets WHERE name = ? AND version = ?", (name, version)
    )
    found = cursor.fetchone()
    if found is None:
        if not store.db.execute("SELECT 1 FROM datasets WHERE name = ?", (name,)).fetchone():
            raise DataError(f"there is no dataset {name} in the data store")
        raise DataError(f"the dataset {name} has no version {version}")
    return dict(zip([d[0] for d in cursor.description], found))


def _codebook(store: Store, catalog: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The catalog row's codebook entries, in the order of its columns."""
    return current(store, "codebook", dataset=catalog["id"])


def _csv_bytes(header: List[str], rows: List[List[str]]) -> bytes:
    handle = io.StringIO(newline="")
    writer = csv.writer(handle, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return handle.getvalue().encode("utf-8")
