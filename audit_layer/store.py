"""The audit store, one SQLite database and a file store beside it.

Appendix A2.4 and Table A3 give the audit store its sessions, events, and
transcripts. Figure A4 draws one database file and a file store, and every row
carries its session, origin, method, and reason. The sources store's records,
retrieved originals, and extracted text (Table A3 Sources row) are kept in the
same database, and the originals' bytes in the same file store. So are the
data store's catalog and codebook (Table A3 Data row), beside one table for
each dataset version that stores/data.py makes, and the knowledge store
sketch's entries and their history (Table A3 Knowledge row), and the working
store's snapshots (Table A3 Working row), whose bytes sit in the file store,
and the shared tables of projects, field definitions, and the export
registry (Table A3 Shared tables row). Each row also has an id and a created_at (plan choice 1). A correction is a new row whose supersedes column
names the row it replaces (plan choice 2). Rows are never updated or deleted,
and triggers in the database refuse both. The one exception is
knowledge_entries, which keeps only each entry's current row. A replaced row
may leave it once the same row is kept whole in knowledge_history, and the
trigger refuses any other delete.
"""
import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, NamedTuple, Optional, Sequence, Tuple

DATABASE = "audit.sqlite"
FILES = "files"

PROVENANCE = ("session", "origin", "method", "reason")

# The knowledge store's fields, the same in its current and its history table.
_KNOWLEDGE = (
    ("entry_id", "TEXT"),
    ("class", "TEXT"),
    ("title", "TEXT"),
    ("gist", "TEXT"),
    ("keywords", "TEXT"),
    ("content", "TEXT"),
    ("source_checksum", "TEXT"),
)

# Each table's own fields. Every row also has id, created_at, the four
# provenance fields, and supersedes. Ids are text, so capture can give each
# event the harness's own id for its tool call (plan Step 5).
TABLES = {
    "sessions": (
        ("harness", "TEXT"),
        ("harness_session_id", "TEXT"),
        ("project", "TEXT"),
        ("started_at", "TEXT"),
        ("ended_at", "TEXT"),
        ("tools", "TEXT"),
        # The model pass's four fields (Table A4, Step A9), empty until it
        # fills them. keywords is a JSON list.
        ("title", "TEXT"),
        ("gist", "TEXT"),
        ("summary", "TEXT"),
        ("keywords", "TEXT"),
        # The models that answered in the session, a JSON list, and the
        # harness's version, both from the transcript (Track P, Step P1). A
        # store made before them gains both, empty on its old rows.
        ("models", "TEXT"),
        ("harness_version", "TEXT"),
    ),
    "events": (
        ("session_row_id", "TEXT"),
        ("ordinal", "INTEGER"),
        ("verb", "TEXT"),
        ("kind", "TEXT"),
        ("object", "TEXT"),
        ("rationale", "TEXT"),
        ("role", "TEXT"),
    ),
    "transcripts": (
        ("session_row_id", "TEXT"),
        ("file_sha256", "TEXT"),
        ("byte_size", "INTEGER"),
    ),
    # The sources store's records (Table A3 Sources row, Step A12).
    # identifiers is a JSON object with doi, openalex, and semantic_scholar,
    # and retrieval_status is not retrieved or retrieved.
    "sources": (
        ("citekey", "TEXT"),
        ("title", "TEXT"),
        ("authors", "TEXT"),
        ("year", "TEXT"),
        ("venue", "TEXT"),
        ("identifiers", "TEXT"),
        ("retrieval_status", "TEXT"),
        ("content_fingerprint", "TEXT"),
    ),
    # The sources store's retrieved originals and extracted text (Table A3
    # Sources row, Step A13). source is a sources row's id. An original's
    # bytes sit in the file store under file_sha256, and kind is abstract,
    # body, fulltext, or references.
    "source_originals": (
        ("source", "TEXT"),
        ("file_sha256", "TEXT"),
        ("byte_size", "INTEGER"),
        ("retrieval_method", "TEXT"),
        ("retrieved_on", "TEXT"),
    ),
    "source_texts": (
        ("source", "TEXT"),
        ("kind", "TEXT"),
        ("text", "TEXT"),
        ("conversion_method", "TEXT"),
    ),
    # The data store's catalog and codebook (Table A3 Data row, Step A14).
    # Each dataset version's rows sit in its own table, table_name, which is
    # ds_<catalog row id> (stores/data.py). file_sha256 is the CSV file's as
    # given, and dataset is a catalog row's id.
    "datasets": (
        ("name", "TEXT"),
        ("version", "INTEGER"),
        ("row_count", "INTEGER"),
        ("file_sha256", "TEXT"),
        ("collected_on", "TEXT"),
        ("table_name", "TEXT"),
    ),
    "codebook": (
        ("dataset", "TEXT"),
        ("variable", "TEXT"),
        ("type", "TEXT"),
        ("description", "TEXT"),
    ),
    # The knowledge store sketch (Table A3 Knowledge row, Step A15), loaded
    # from the knowledge base's entry files (stores/knowledge.py). keywords is
    # a JSON list. knowledge_entries holds one current row per entry, and
    # each replaced row moves whole into knowledge_history.
    "knowledge_entries": _KNOWLEDGE,
    "knowledge_history": _KNOWLEDGE,
    # The working store's snapshots (Table A3 Working row, Step A16). project
    # is the session's project folder, path is relative to it, kind is note,
    # script, or draft, and the bytes sit in the file store under file_sha256.
    "snapshots": (
        ("project", "TEXT"),
        ("path", "TEXT"),
        ("kind", "TEXT"),
        ("file_sha256", "TEXT"),
        ("byte_size", "INTEGER"),
    ),
    # The shared tables' projects (Table A3 Shared tables row, Step A17). A
    # project is the folder its sessions ran in (slice plan choice 4), and
    # name is the folder's last part (plan choice 19).
    "projects": (
        ("folder", "TEXT"),
        ("name", "TEXT"),
    ),
    # The shared tables' field definitions (Table A3 Shared tables row, Step
    # A18), written from fields.py when the store opens. table_name is * for
    # the spine every row carries.
    "field_definitions": (
        ("table_name", "TEXT"),
        ("field", "TEXT"),
        ("definition", "TEXT"),
        ("generation_rule", "TEXT"),
        ("null_behavior", "TEXT"),
    ),
    # The shared tables' export registry (Table A3 Shared tables row, Step
    # A19), written from writeout.py when the store opens. element is a table
    # name, or ds_* for the dataset tables, and a table whose rows point at
    # kept bytes has one row for its rows and one for its bytes.
    "export_registry": (
        ("element", "TEXT"),
        ("file_form", "TEXT"),
        ("path", "TEXT"),
    ),
}

# The one table whose rows may leave it, each only once the same row, whole,
# is kept in the table named here (plan rules, "every table is append-only
# except knowledge_entries").
MOVES_TO = {"knowledge_entries": "knowledge_history"}

# Fields stored as a JSON list and handed back as a list.
LISTS = {
    "sessions": ("tools", "keywords", "models"),
    "knowledge_entries": ("keywords",),
    "knowledge_history": ("keywords",),
}

# Fields stored as a JSON object and handed back as a dict.
OBJECTS = {"sources": ("identifiers",)}


class StoreError(ValueError):
    """A write or read the store refuses."""


class Store(NamedTuple):
    home: Path
    db: sqlite3.Connection
    files: Path


def _fields(table: str) -> List[str]:
    return [name for name, _ in TABLES[table]]


def _columns(table: str) -> List[str]:
    return ["id"] + _fields(table) + ["created_at"] + list(PROVENANCE) + ["supersedes"]


def _schema() -> str:
    parts = []
    for table, fields in TABLES.items():
        lines = ["id TEXT PRIMARY KEY NOT NULL"]
        lines += [f"{name} {kind}" for name, kind in fields]
        lines.append("created_at TEXT NOT NULL")
        lines += [f"{name} TEXT NOT NULL CHECK (length(trim({name})) > 0)" for name in PROVENANCE]
        lines.append("supersedes TEXT")
        parts.append(f"CREATE TABLE IF NOT EXISTS {table} (\n  " + ",\n  ".join(lines) + "\n);")
        parts.append(
            f"CREATE TRIGGER IF NOT EXISTS {table}_never_updated BEFORE UPDATE ON {table}\n"
            f"BEGIN SELECT RAISE(ABORT, '{table} rows are never updated'); END;"
        )
        if table in MOVES_TO:
            kept = MOVES_TO[table]
            same = " AND ".join(f"kept.{name} IS OLD.{name}" for name in _columns(table))
            parts.append(
                f"CREATE TRIGGER IF NOT EXISTS {table}_moved_only BEFORE DELETE ON {table}\n"
                f"WHEN NOT EXISTS (SELECT 1 FROM {kept} AS kept WHERE {same})\n"
                f"BEGIN SELECT RAISE(ABORT, '{table} rows leave the table only once kept in"
                f" {kept}'); END;"
            )
        else:
            parts.append(
                f"CREATE TRIGGER IF NOT EXISTS {table}_never_deleted BEFORE DELETE ON {table}\n"
                f"BEGIN SELECT RAISE(ABORT, '{table} rows are never deleted'); END;"
            )
    return "\n".join(parts) + "\n"


def open_store(home) -> Store:
    """Open the store at home, making the folder, database, and file store when missing.

    Opening writes each field definition (fields.py) and each export
    registry form (writeout.py) the store lacks or holds with other text, so
    a store already in step gets nothing new.
    """
    home = Path(home)
    files = home / FILES
    files.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(home / DATABASE))
    # A replace removes the row it collides with. With recursive triggers on,
    # that removal meets the trigger that refuses a delete.
    db.execute("PRAGMA recursive_triggers = ON")
    db.executescript(_schema())
    _add_missing_columns(db)
    store = Store(home=home, db=db, files=files)
    # The schema documents itself (Step A18), and says each element's file
    # form (Step A19). Imported here, since both write through this module.
    from audit_layer.fields import sync_definitions
    from audit_layer.writeout import sync_registry

    sync_definitions(store)
    sync_registry(store)
    return store


def _add_missing_columns(db: sqlite3.Connection) -> None:
    """Add each field a table made by an older version of the store lacks.

    A store made before the model pass's four fields existed gains them here,
    empty on every row it already holds (Step A9), and so does a store made
    before the sessions' models and harness_version (Step P1).
    """
    for table, fields in TABLES.items():
        have = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
        for name, kind in fields:
            if name not in have:
                with db:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")


def put_file(store: Store, data: bytes) -> str:
    """Keep data once in the file store under its sha256 and return the checksum."""
    checksum = hashlib.sha256(data).hexdigest()
    path = store.files / checksum
    if not path.exists():
        # Written whole under another name first, so a stored file is never partial.
        partial = store.files / (checksum + ".partial")
        partial.write_bytes(data)
        os.replace(str(partial), str(path))
    return checksum


def add_row(
    store: Store,
    table: str,
    fields: Dict[str, Any],
    provenance: Dict[str, str],
    row_id: Optional[str] = None,
) -> Optional[str]:
    """Write a new row and return its id.

    The store makes the id unless row_id gives one, as capture does with the
    harness's own id for each tool call. A given id the table already holds,
    on a current or a superseded row, writes nothing and gives None, so a
    repeated capture stores nothing new (plan Step 5).
    """
    _check_table(table)
    _check_fields(table, fields)
    _check_provenance(provenance)
    if row_id is not None:
        if not isinstance(row_id, str) or not row_id.strip():
            raise StoreError("a row id given to the store must be text that is not blank")
        if _row(store, table, row_id) is not None:
            return None
    return _insert(store, table, fields, provenance, None, row_id)


def current(store: Store, table: str, **match: Any) -> List[Dict[str, Any]]:
    """The rows no later row supersedes, in the order written.

    Keyword arguments keep only the rows whose field holds the given value.
    """
    _check_table(table)
    unknown = sorted(set(match) - set(_columns(table)))
    if unknown:
        raise StoreError(f"{table} has no field {', '.join(unknown)}")
    names = sorted(match)
    sql = (
        f"SELECT * FROM {table} WHERE id NOT IN "
        f"(SELECT supersedes FROM {table} WHERE supersedes IS NOT NULL)"
    )
    sql += "".join(f" AND {name} IS ?" for name in names)
    cursor = store.db.execute(sql + " ORDER BY rowid", [match[name] for name in names])
    return [_decode(table, cursor, row) for row in cursor.fetchall()]


def supersede(
    store: Store,
    table: str,
    old_id: str,
    changes: Dict[str, Any],
    provenance: Dict[str, str],
) -> str:
    """Write the corrected row, which supersedes old_id, and return its id.

    The new row keeps the old row's fields except those in changes, and carries
    the correction's own provenance. The old row stays in the table.
    """
    return supersede_all(store, [(table, old_id, changes, provenance)])[0]


def supersede_all(
    store: Store,
    writes: Sequence[Tuple[str, str, Dict[str, Any], Dict[str, str]]],
) -> List[str]:
    """Write several corrections in one transaction and return their ids, in order.

    Each write is (table, old_id, changes, provenance), checked as supersede
    checks it, and no row may be named twice. The checks on the old rows and
    the writes run in one transaction that holds the database's write lock,
    so when any correction is refused, or another writer has superseded a row
    since it was read, none of them is written (Step A10).
    """
    for table, _, changes, provenance in writes:
        _check_table(table)
        _check_fields(table, changes)
        _check_provenance(provenance)
    ids = []
    with store.db:
        if not store.db.in_transaction:
            store.db.execute("BEGIN IMMEDIATE")
        named = set()
        for table, old_id, changes, provenance in writes:
            if (table, old_id) in named:
                raise StoreError(f"row {old_id} in {table} is named twice in one write")
            named.add((table, old_id))
            ids.append(_supersede_one(store, table, old_id, changes, provenance))
    return ids


class Writer(NamedTuple):
    """Writes made inside one transaction that writing(store) holds."""

    store: Store

    def add(
        self,
        table: str,
        fields: Dict[str, Any],
        provenance: Dict[str, str],
        row_id: Optional[str] = None,
    ) -> str:
        """Write a new row, checked as add_row checks it, and return its id.

        A given row_id the table already holds is refused, since nothing in
        the transaction may be half written.
        """
        _check_table(table)
        _check_fields(table, fields)
        _check_provenance(provenance)
        if row_id is not None and _row(self.store, table, row_id) is not None:
            raise StoreError(f"{table} already holds a row {row_id}")
        return _write(self.store, table, fields, provenance, None, row_id)

    def supersede(
        self,
        table: str,
        old_id: str,
        changes: Dict[str, Any],
        provenance: Dict[str, str],
        row_id: Optional[str] = None,
    ) -> str:
        """Write the corrected row, checked as supersede checks it, and return its id."""
        _check_table(table)
        _check_fields(table, changes)
        _check_provenance(provenance)
        if row_id is not None and _row(self.store, table, row_id) is not None:
            raise StoreError(f"{table} already holds a row {row_id}")
        return _supersede_one(self.store, table, old_id, changes, provenance, row_id)


@contextmanager
def writing(store: Store) -> Iterator[Writer]:
    """Hold the database's write lock for several writes, kept together or not at all.

    The block's own statements on store.db run in the same transaction, as
    the data store's table for a dataset does (Step A14). When the block
    raises, nothing it wrote is kept.
    """
    # Checked before the block opens, so a refusal leaves the write under way alone.
    if store.db.in_transaction:
        raise StoreError("a write to the store is already under way on this connection")
    with store.db:
        store.db.execute("BEGIN IMMEDIATE")
        yield Writer(store)


def _supersede_one(
    store: Store,
    table: str,
    old_id: str,
    changes: Dict[str, Any],
    provenance: Dict[str, str],
    row_id: Optional[str] = None,
) -> str:
    """Write the row superseding old_id inside the transaction the caller holds."""
    old = _row(store, table, old_id)
    if old is None:
        raise StoreError(f"there is no row {old_id} in {table}")
    later = store.db.execute(f"SELECT id FROM {table} WHERE supersedes = ?", (old_id,)).fetchone()
    if later is not None:
        raise StoreError(f"row {old_id} in {table} is already superseded by row {later[0]}")
    fields = {name: old[name] for name in _fields(table)}
    fields.update(changes)
    return _write(store, table, fields, provenance, old_id, row_id)


def _check_table(table: str) -> None:
    if table not in TABLES:
        raise StoreError(f"the audit store has no table {table}")


def _check_fields(table: str, fields: Dict[str, Any]) -> None:
    unknown = sorted(set(fields) - set(_fields(table)))
    if unknown:
        raise StoreError(
            f"{table} has no field {', '.join(unknown)} to write. Provenance goes in its own"
            " argument, and the store sets id, created_at, and supersedes"
        )
    for name in LISTS.get(table, ()):
        value = fields.get(name)
        if value is not None and not isinstance(value, (list, tuple)):
            raise StoreError(f"{table} keeps {name} as a JSON list, so give it as a list")
    for name in OBJECTS.get(table, ()):
        value = fields.get(name)
        if value is not None and not isinstance(value, dict):
            raise StoreError(f"{table} keeps {name} as a JSON object, so give it as a dict")


def _check_provenance(provenance: Dict[str, str]) -> None:
    unknown = sorted(set(provenance) - set(PROVENANCE))
    if unknown:
        raise StoreError(f"provenance has no field {', '.join(unknown)}")
    for name in PROVENANCE:
        value = provenance.get(name)
        if not isinstance(value, str) or not value.strip():
            raise StoreError(f"every row needs a {name} in its provenance")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _insert(
    store: Store,
    table: str,
    fields: Dict[str, Any],
    provenance: Dict[str, str],
    supersedes: Optional[str],
    row_id: Optional[str] = None,
) -> str:
    with store.db:
        return _write(store, table, fields, provenance, supersedes, row_id)


def _write(
    store: Store,
    table: str,
    fields: Dict[str, Any],
    provenance: Dict[str, str],
    supersedes: Optional[str],
    row_id: Optional[str] = None,
) -> str:
    """Insert the row inside the transaction the caller holds and return its id."""
    row = {name: fields.get(name) for name in _fields(table)}
    for name in LISTS.get(table, ()):
        if row[name] is not None:
            row[name] = json.dumps(list(row[name]))
    for name in OBJECTS.get(table, ()):
        if row[name] is not None:
            row[name] = json.dumps(dict(row[name]), sort_keys=True)
    row["id"] = uuid.uuid4().hex if row_id is None else row_id
    row["created_at"] = _now()
    for name in PROVENANCE:
        row[name] = provenance[name]
    row["supersedes"] = supersedes
    names = list(row)
    store.db.execute(
        f"INSERT INTO {table} ({', '.join(names)}) VALUES ({', '.join('?' for _ in names)})",
        [row[name] for name in names],
    )
    return row["id"]


def _row(store: Store, table: str, row_id: str) -> Optional[Dict[str, Any]]:
    cursor = store.db.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,))
    row = cursor.fetchone()
    return None if row is None else _decode(table, cursor, row)


def _decode(table: str, cursor: sqlite3.Cursor, row: tuple) -> Dict[str, Any]:
    names = [d[0] for d in cursor.description]
    decoded = dict(zip(names, row))
    for name in LISTS.get(table, ()) + OBJECTS.get(table, ()):
        if decoded.get(name) is not None:
            decoded[name] = json.loads(decoded[name])
    return decoded
