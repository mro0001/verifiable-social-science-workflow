"""The audit record reader, which reads the audit layer's record as it is written.

Appendix A2.6 and Figure A4 have the observability layer read the audit
store while records are written, and Table A7 reads the record live. This
module opens <audit_home>/audit.sqlite read only, at a path given on the
command line (plan choice 4, reconciliation item 4), and reads transcripts
from the audit home's file store. It never writes there.

The names below are copied by hand from the audit layer's store.py, and
nothing is imported from the audit layer, since only files cross a layer
edge. When the store renames a column, RECORD_COLUMNS changes with it, and
open_record names any column it cannot find.
"""
import hashlib
import os
import sqlite3
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional

DATABASE = "audit.sqlite"
FILES = "files"

# How long to wait on a write lock, in seconds.
LOCK_WAIT = 5

# Each column this reader uses, under the name it is used by here, mapped to
# its name in audit_layer/store.py. Every table has id, created_at, and
# supersedes. session_row is the column tying an event or a transcript to one
# version of its session row.
RECORD_COLUMNS = {
    "sessions": {
        "id": "id",
        "created_at": "created_at",
        "supersedes": "supersedes",
        "harness": "harness",
        "harness_session_id": "harness_session_id",
        "project": "project",
        "started_at": "started_at",
        "ended_at": "ended_at",
    },
    "events": {
        "id": "id",
        "created_at": "created_at",
        "supersedes": "supersedes",
        "session_row": "session_row_id",
        "ordinal": "ordinal",
        "verb": "verb",
        "kind": "kind",
        "object": "object",
        "rationale": "rationale",
        "role": "role",
    },
    "transcripts": {
        "id": "id",
        "created_at": "created_at",
        "supersedes": "supersedes",
        "session_row": "session_row_id",
        "file_sha256": "file_sha256",
    },
}

SESSION_FIELDS = ("harness", "harness_session_id", "project", "started_at", "ended_at")
EVENT_FIELDS = ("ordinal", "verb", "kind", "object", "rationale", "role")


class RecordError(ValueError):
    """A record the reader cannot rely on."""


class Record(NamedTuple):
    home: Path
    db: sqlite3.Connection


def stored_path(audit_home, checksum: str) -> Path:
    """Where the audit layer's put_file keeps a file, <audit_home>/files/<checksum>."""
    return Path(audit_home) / FILES / checksum


def open_record(audit_home) -> Record:
    """Open <audit_home>/audit.sqlite read only.

    A missing file, table, or column is refused by name, so a record from a
    store whose form has changed is never read as if it were empty.
    """
    home = Path(audit_home)
    path = home / DATABASE
    if not path.is_file():
        raise RecordError(f"there is no audit record at {path}")
    address = path.resolve().as_uri() + "?mode=ro"
    db = sqlite3.connect(address, uri=True, timeout=LOCK_WAIT)
    try:
        missing = _missing(db)
    except sqlite3.DatabaseError as error:
        db.close()
        raise RecordError(f"{path} cannot be read as an audit record ({error})") from error
    if missing:
        db.close()
        raise RecordError(f"{path} lacks " + "; ".join(missing))
    return Record(home=home, db=db)


def sessions(record: Record, project=None) -> List[Dict]:
    """The current session rows, one for each harness and harness session id.

    Each carries harness, harness_session_id, project, started_at, ended_at,
    and row_ids, every row of that harness session, superseded or not, in the
    order written. The fields are the current row's. With project, only
    sessions whose project is that folder or one inside it are kept,
    comparing real paths.
    """
    keys = ["id", "supersedes"] + list(SESSION_FIELDS)
    rows = _select(record, "sessions", keys)
    replaced = {row["supersedes"] for row in rows if row["supersedes"] is not None}
    groups = {}
    order = []
    for row in rows:
        group = (row["harness"], row["harness_session_id"])
        if group not in groups:
            groups[group] = {"row_ids": [], "current": None}
            order.append(group)
        groups[group]["row_ids"].append(row["id"])
        if row["id"] not in replaced:
            # The latest current row written stands for the session.
            groups[group]["current"] = row
    found = []
    for group in order:
        current = groups[group]["current"]
        if current is None:
            continue
        if project is not None and not _inside(current["project"], project):
            continue
        session = {name: current[name] for name in SESSION_FIELDS}
        session["row_ids"] = list(groups[group]["row_ids"])
        found.append(session)
    return found


def transcripts(record: Record, session: Dict) -> List[bytes]:
    """The bytes of every transcript row tied to any of the session's row_ids, oldest first.

    Each file is checked against its file_sha256, and a missing or altered
    file raises RecordError naming the checksum.
    """
    found = []
    for row in _tied(record, "transcripts", ["file_sha256"], session, current_only=False):
        checksum = row["file_sha256"]
        path = stored_path(record.home, checksum)
        try:
            data = path.read_bytes()
        except OSError as error:
            raise RecordError(
                f"the transcript {checksum} is missing from the file store ({error})") from error
        if hashlib.sha256(data).hexdigest() != checksum:
            raise RecordError(
                f"the transcript {checksum} in the file store does not match its checksum")
        found.append(data)
    return found


def events(record: Record, session: Dict) -> List[Dict]:
    """The current event rows tied to any of the session's row_ids, by ordinal.

    Each carries ordinal, verb, kind, object, rationale, and role.
    """
    rows = _tied(record, "events", list(EVENT_FIELDS), session, current_only=True)
    rows.sort(key=lambda row: (row["ordinal"] is None, row["ordinal"] or 0, row["_order"]))
    return [{name: row[name] for name in EVENT_FIELDS} for row in rows]


def _missing(db: sqlite3.Connection) -> List[str]:
    """What the record lacks, as table and column names."""
    missing = []
    for table, columns in RECORD_COLUMNS.items():
        held = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
        if not held:
            missing.append(f"the table {table}")
            continue
        absent = [name for name in columns.values() if name not in held]
        if absent:
            missing.append(f"the column {', '.join(absent)} in the table {table}")
    return missing


def _select(record: Record, table: str, keys: List[str], where: str = "",
            values: Optional[list] = None) -> List[Dict]:
    """Rows of table under the reader's own keys, in the order written."""
    columns = RECORD_COLUMNS[table]
    names = ", ".join(columns[key] for key in keys)
    sql = f"SELECT rowid, {names} FROM {table}"
    if where:
        sql += " WHERE " + where
    sql += f" ORDER BY {columns['created_at']}, rowid"
    rows = []
    for position, row in enumerate(record.db.execute(sql, values or [])):
        decoded = dict(zip(keys, row[1:]))
        decoded["_order"] = position
        rows.append(decoded)
    return rows


def _tied(record: Record, table: str, keys: List[str], session: Dict,
          current_only: bool) -> List[Dict]:
    """The rows of table tied to any of the session's row_ids, in the order written."""
    columns = RECORD_COLUMNS[table]
    row_ids = list(session["row_ids"])
    if not row_ids:
        return []
    where = "{} IN ({})".format(columns["session_row"], ", ".join("?" for _ in row_ids))
    rows = _select(record, table, ["id", "supersedes"] + keys, where, row_ids)
    if current_only:
        replaced = _replaced(record, table)
        rows = [row for row in rows if row["id"] not in replaced]
    return rows


def _replaced(record: Record, table: str) -> set:
    """The ids of every row in table that a later row supersedes."""
    column = RECORD_COLUMNS[table]["supersedes"]
    sql = f"SELECT {column} FROM {table} WHERE {column} IS NOT NULL"
    return {row[0] for row in record.db.execute(sql)}


def _inside(path, folder) -> bool:
    """Whether path is folder or a folder inside it, as real paths."""
    if path is None:
        return False
    real = os.path.realpath(str(path))
    top = os.path.realpath(str(folder))
    return real == top or real.startswith(top.rstrip(os.sep) + os.sep)
