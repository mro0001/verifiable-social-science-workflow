"""Tests for the audit store (plan Step 2, appendix A2.4, Table A3, Figure A4).

Every row and file here comes from the test story's Claude Code session, whose
folder token {{PROJECT}} is replaced with a temporary folder. Nothing here calls
a model or the network. Run from the repository root with
python3 -m pytest -q audit_layer/tests.
"""
import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from audit_layer.store import (  # noqa: E402
    StoreError,
    add_row,
    current,
    open_store,
    put_file,
    supersede,
    supersede_all,
    writing,
)

STORY = ROOT / "examples" / "test_story"
STORY_SESSION = STORY / "sessions" / "claude_code" / "story_session.jsonl"
STORY_BYTES = STORY_SESSION.read_bytes()
MANUSCRIPT_BYTES = (STORY / "project" / "manuscript.md").read_bytes()
TOKEN = "{{PROJECT}}"

TABLES = ("sessions", "events", "transcripts")
PROVENANCE = ("session", "origin", "method", "reason")
EVERY_ROW = {"id", "created_at", "session", "origin", "method", "reason", "supersedes"}
COLUMNS = {
    "sessions": EVERY_ROW
    | {"harness", "harness_session_id", "project", "started_at", "ended_at", "tools"}
    | {"title", "gist", "summary", "keywords"}
    | {"models", "harness_version"},
    "events": EVERY_ROW
    | {"session_row_id", "ordinal", "verb", "kind", "object", "rationale", "role"},
    "transcripts": EVERY_ROW | {"session_row_id", "file_sha256", "byte_size"},
    # The sources store's records (Step A12).
    "sources": EVERY_ROW
    | {"citekey", "title", "authors", "year", "venue", "identifiers"}
    | {"retrieval_status", "content_fingerprint"},
    # The sources store's retrieved originals and extracted text (Step A13).
    "source_originals": EVERY_ROW
    | {"source", "file_sha256", "byte_size", "retrieval_method", "retrieved_on"},
    "source_texts": EVERY_ROW | {"source", "kind", "text", "conversion_method"},
    # The data store's catalog and codebook (Step A14). Each dataset's own
    # table, ds_<catalog row id>, appears only once a dataset is added.
    "datasets": EVERY_ROW
    | {"name", "version", "row_count", "file_sha256", "collected_on", "table_name"},
    "codebook": EVERY_ROW | {"dataset", "variable", "type", "description"},
    # The knowledge store sketch, its current entries and their history (Step A15).
    "knowledge_entries": EVERY_ROW
    | {"entry_id", "class", "title", "gist", "keywords", "content", "source_checksum"},
    "knowledge_history": EVERY_ROW
    | {"entry_id", "class", "title", "gist", "keywords", "content", "source_checksum"},
    # The working store's snapshots (Step A16).
    "snapshots": EVERY_ROW | {"project", "path", "kind", "file_sha256", "byte_size"},
    # The shared table of projects (Step A17).
    "projects": EVERY_ROW | {"folder", "name"},
    # The shared table of field definitions (Step A18).
    "field_definitions": EVERY_ROW
    | {"table_name", "field", "definition", "generation_rule", "null_behavior"},
    # The shared table of the export registry (Step A19).
    "export_registry": EVERY_ROW | {"element", "file_form", "path"},
}


def story_records():
    return [json.loads(line) for line in STORY_BYTES.decode("utf-8").splitlines()]


STORY_ID = story_records()[0]["sessionId"]

# Provenance for the rows these tests write by hand from the story session.
BY_HAND = {
    "session": STORY_ID,
    "origin": "test_store",
    "method": "written by hand from the story session",
    "reason": "test",
}
CORRECTION = dict(BY_HAND, method="corrected by hand", reason="correction")


def story_session_fields(project):
    """The story session's identity, folder, times, and the tools it used."""
    records = story_records()
    tools = []
    for record in records:
        content = (record.get("message") or {}).get("content")
        for part in content if isinstance(content, list) else []:
            if part.get("type") == "tool_use" and part["name"] not in tools:
                tools.append(part["name"])
    return {
        "harness": "claude_code",
        "harness_session_id": STORY_ID,
        "project": records[0]["cwd"].replace(TOKEN, str(project)),
        "started_at": records[0]["timestamp"],
        "ended_at": records[-1]["timestamp"],
        "tools": tools,
    }


def story_events(session_row_id, project):
    """The story's first three tool calls, a Read and the two Edits of manuscript.md."""
    manuscript = str(Path(project) / "manuscript.md")
    calls = [
        ("searched", "observation", "read"),
        ("edited", "action", "edited"),
        ("edited", "action", "edited"),
    ]
    return [
        {
            "session_row_id": session_row_id,
            "ordinal": ordinal,
            "verb": verb,
            "kind": kind,
            "object": manuscript,
            "rationale": "",
            "role": role,
        }
        for ordinal, (verb, kind, role) in enumerate(calls, start=1)
    ]


def fill(store, project):
    """Store the story session, three of its events, and its transcript."""
    session_row = add_row(store, "sessions", story_session_fields(project), BY_HAND)
    events = [add_row(store, "events", e, BY_HAND) for e in story_events(session_row, project)]
    checksum = put_file(store, STORY_BYTES)
    transcript = add_row(
        store,
        "transcripts",
        {"session_row_id": session_row, "file_sha256": checksum, "byte_size": len(STORY_BYTES)},
        BY_HAND,
    )
    return {"sessions": [session_row], "events": events, "transcripts": [transcript]}


@pytest.fixture
def filled(tmp_path):
    store = open_store(tmp_path / "home")
    ids = fill(store, tmp_path / "project")
    yield store, ids
    store.db.close()


def stored_rows(db, table, where="1", params=()):
    """Rows as the database holds them, superseded or not, in the order written."""
    cursor = db.execute(f"SELECT * FROM {table} WHERE {where} ORDER BY rowid", params)
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def stored_row(db, table, row_id):
    rows = stored_rows(db, table, "id = ?", (row_id,))
    return rows[0] if rows else None


def table_columns(db):
    names = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    return {
        name: {r[1] for r in db.execute(f"PRAGMA table_info({name})")} for name in names
    }


def with_value(provenance, field, value):
    """The provenance with one field set to value, or left out when value is None."""
    changed = dict(provenance)
    if value is None:
        del changed[field]
    else:
        changed[field] = value
    return changed


def test_a_file_put_twice_is_kept_once(tmp_path):
    store = open_store(tmp_path)
    try:
        first = put_file(store, STORY_BYTES)
        second = put_file(store, STORY_BYTES)
        assert first == second == hashlib.sha256(STORY_BYTES).hexdigest()
        assert [p.name for p in (tmp_path / "files").iterdir()] == [first]
        assert (tmp_path / "files" / first).read_bytes() == STORY_BYTES

        other = put_file(store, MANUSCRIPT_BYTES)
        assert other == hashlib.sha256(MANUSCRIPT_BYTES).hexdigest()
        assert sorted(p.name for p in (tmp_path / "files").iterdir()) == sorted([first, other])
        assert (tmp_path / "files" / first).read_bytes() == STORY_BYTES
    finally:
        store.db.close()


def test_a_put_cut_off_midway_leaves_no_partial_file_under_the_checksum(tmp_path, monkeypatch):
    store = open_store(tmp_path)
    try:
        write_bytes = Path.write_bytes

        def half_then_fail(path, data):
            write_bytes(path, data[: len(data) // 2])
            raise OSError("the disk filled up")

        monkeypatch.setattr(Path, "write_bytes", half_then_fail)
        with pytest.raises(OSError):
            put_file(store, STORY_BYTES)
        monkeypatch.undo()

        checksum = put_file(store, STORY_BYTES)
        assert (tmp_path / "files" / checksum).read_bytes() == STORY_BYTES
    finally:
        store.db.close()


@pytest.mark.parametrize("table", TABLES)
def test_rows_cannot_be_updated_or_deleted(filled, table):
    store, ids = filled
    row_id = ids[table][0]
    before = stored_rows(store.db, table)

    with pytest.raises(sqlite3.IntegrityError, match="never updated"):
        store.db.execute(f"UPDATE {table} SET origin = 'changed' WHERE id = ?", (row_id,))
    with pytest.raises(sqlite3.IntegrityError, match="never updated"):
        store.db.execute(f"UPDATE {table} SET supersedes = id")
    with pytest.raises(sqlite3.IntegrityError, match="never deleted"):
        store.db.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))
    with pytest.raises(sqlite3.IntegrityError, match="never deleted"):
        store.db.execute(f"DELETE FROM {table}")
    # A replace removes the row it collides with, so it is refused like a delete.
    with pytest.raises(sqlite3.IntegrityError, match="never deleted"):
        store.db.execute(
            f"INSERT OR REPLACE INTO {table} (id, created_at, session, origin, method, reason)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (row_id, "2026-10-28T00:00:00.000000Z", STORY_ID, "o", "m", "r"),
        )
    store.db.commit()

    assert stored_rows(store.db, table) == before


@pytest.mark.parametrize("field", PROVENANCE)
def test_every_provenance_field_is_required(filled, field):
    store, ids = filled
    counts = {t: len(stored_rows(store.db, t)) for t in TABLES}

    for table in TABLES:
        for value in (None, "", "   "):
            provenance = with_value(BY_HAND, field, value)
            with pytest.raises(StoreError, match=field):
                add_row(store, table, {}, provenance)
            with pytest.raises(StoreError, match=field):
                supersede(store, table, ids[table][0], {}, provenance)
            # The database refuses the row too, whatever writes it.
            row = dict(BY_HAND, id="r-" + field, created_at="2026-10-28T00:00:00.000000Z")
            row[field] = value
            names = list(row)
            with pytest.raises(sqlite3.IntegrityError):
                store.db.execute(
                    f"INSERT INTO {table} ({', '.join(names)})"
                    f" VALUES ({', '.join('?' for _ in names)})",
                    [row[n] for n in names],
                )
    store.db.commit()

    assert {t: len(stored_rows(store.db, t)) for t in TABLES} == counts
    with pytest.raises(StoreError, match="extra"):
        add_row(store, "sessions", {}, dict(BY_HAND, extra="x"))


@pytest.mark.parametrize("table", TABLES)
def test_a_supersede_hides_the_old_row_from_current_and_keeps_it(filled, table):
    store, ids = filled
    old_id = ids[table][0]
    old = stored_row(store.db, table, old_id)
    old_current = [r for r in current(store, table) if r["id"] == old_id][0]
    count = len(stored_rows(store.db, table))
    if table == "sessions":
        changes = {
            "ended_at": "2026-10-21T14:05:00.000Z",
            "tools": ["Read", "Edit", "Write", "Bash", "Grep"],
        }
    elif table == "events":
        changes = {"rationale": "The scholar asked for two findings after the sentence on fit."}
    else:
        grown = STORY_BYTES + b"\n"
        changes = {"file_sha256": put_file(store, grown), "byte_size": len(grown)}

    new_id = supersede(store, table, old_id, changes, CORRECTION)

    assert new_id != old_id
    rows = current(store, table)
    assert old_id not in [r["id"] for r in rows]
    new = [r for r in rows if r["id"] == new_id][0]
    assert new["supersedes"] == old_id
    assert {k: new[k] for k in PROVENANCE} == CORRECTION
    assert new["created_at"] >= old["created_at"]
    for name in COLUMNS[table] - EVERY_ROW:
        assert new[name] == changes.get(name, old_current[name]), name
    # The old row stays in the table exactly as it was written.
    assert stored_row(store.db, table, old_id) == old
    assert len(stored_rows(store.db, table)) == count + 1

    with pytest.raises(StoreError, match="already superseded"):
        supersede(store, table, old_id, {}, CORRECTION)
    with pytest.raises(StoreError, match="no row"):
        supersede(store, table, "no-such-row", {}, CORRECTION)
    newer = supersede(store, table, new_id, {}, CORRECTION)
    ids_now = [r["id"] for r in current(store, table)]
    assert newer in ids_now and new_id not in ids_now and old_id not in ids_now


def test_supersede_all_writes_every_correction_in_one_transaction_or_none(filled):
    store, ids = filled
    session_row, event_row = ids["sessions"][0], ids["events"][0]
    counts = {t: len(stored_rows(store.db, t)) for t in TABLES}

    # A refused correction anywhere in the list writes none of them.
    stale = supersede(store, "events", ids["events"][1], {}, CORRECTION)
    counts["events"] += 1
    for writes, match in (
        (
            [
                ("sessions", session_row, {"title": "A title"}, CORRECTION),
                ("events", ids["events"][1], {"kind": "decision"}, CORRECTION),
            ],
            "already superseded",
        ),
        (
            [
                ("sessions", session_row, {"title": "A title"}, CORRECTION),
                ("events", "no-such-row", {"kind": "decision"}, CORRECTION),
            ],
            "no row",
        ),
        (
            [
                ("events", event_row, {"kind": "decision"}, CORRECTION),
                ("events", event_row, {"rationale": "Twice."}, CORRECTION),
            ],
            "named twice",
        ),
        (
            [
                ("sessions", session_row, {"title": "A title"}, CORRECTION),
                ("events", event_row, {"parent": "x"}, CORRECTION),
            ],
            "parent",
        ),
    ):
        with pytest.raises(StoreError, match=match):
            supersede_all(store, writes)
        assert {t: len(stored_rows(store.db, t)) for t in TABLES} == counts
        assert not store.db.in_transaction

    new_ids = supersede_all(
        store,
        [
            ("sessions", session_row, {"title": "A title"}, CORRECTION),
            ("events", event_row, {"kind": "decision"}, CORRECTION),
            ("events", stale, {"rationale": "It was asked for."}, CORRECTION),
        ],
    )
    assert len(new_ids) == 3
    assert {t: len(stored_rows(store.db, t)) for t in TABLES} == dict(
        counts, sessions=counts["sessions"] + 1, events=counts["events"] + 2
    )
    for new_id, old_id, table in zip(
        new_ids, (session_row, event_row, stale), ("sessions", "events", "events")
    ):
        assert stored_row(store.db, table, new_id)["supersedes"] == old_id
    assert supersede_all(store, []) == []


def test_writing_keeps_every_write_of_its_block_or_none(filled):
    store, ids = filled
    session_row, event_row = ids["sessions"][0], ids["events"][0]
    counts = {t: len(stored_rows(store.db, t)) for t in TABLES}

    # A block that raises keeps nothing it wrote, its own statements included.
    with pytest.raises(StoreError, match="no row"):
        with writing(store) as write:
            write.add("events", {"verb": "read"}, BY_HAND)
            write.supersede("sessions", session_row, {"title": "A title"}, CORRECTION)
            store.db.execute("CREATE TABLE scratch (x TEXT)")
            write.supersede("events", "no-such-row", {}, CORRECTION)
    assert {t: len(stored_rows(store.db, t)) for t in TABLES} == counts
    assert "scratch" not in table_columns(store.db)
    assert not store.db.in_transaction

    with pytest.raises(StoreError, match="already holds"):
        with writing(store) as write:
            write.add("events", {"verb": "read"}, BY_HAND, row_id=event_row)
    with pytest.raises(StoreError, match="parent"):
        with writing(store) as write:
            write.add("events", {"parent": "x"}, BY_HAND)
    assert {t: len(stored_rows(store.db, t)) for t in TABLES} == counts

    with writing(store) as write:
        added = write.add("events", {"verb": "read"}, BY_HAND, row_id="given-id")
        newer = write.supersede("sessions", session_row, {"title": "A title"}, CORRECTION)
    assert added == "given-id"
    assert stored_row(store.db, "sessions", newer)["supersedes"] == session_row
    assert {t: len(stored_rows(store.db, t)) for t in TABLES} == dict(
        counts, sessions=counts["sessions"] + 1, events=counts["events"] + 1
    )


def test_writing_is_refused_while_another_write_is_under_way(filled):
    store, ids = filled
    store.db.execute("BEGIN")
    try:
        with pytest.raises(StoreError, match="under way"):
            with writing(store):
                pass
        # The write under way is left open, as it was.
        assert store.db.in_transaction
    finally:
        store.db.rollback()


def test_current_returns_matching_rows_in_the_order_written(filled):
    store, ids = filled
    session_row = ids["sessions"][0]

    events = current(store, "events")
    assert [r["id"] for r in events] == ids["events"]
    assert [r["ordinal"] for r in events] == [1, 2, 3]
    assert [r["ordinal"] for r in current(store, "events", verb="edited")] == [2, 3]
    read = current(store, "events", session_row_id=session_row, role="read")
    assert [r["ordinal"] for r in read] == [1]
    assert current(store, "events", verb="committed") == []
    assert [r["id"] for r in current(store, "sessions", harness_session_id=STORY_ID)] == [
        session_row
    ]
    with pytest.raises(StoreError, match="parent"):
        current(store, "sessions", parent="the story session")


def test_the_store_refuses_unknown_tables_and_fields(filled):
    store, ids = filled
    session_row = ids["sessions"][0]
    counts = {t: len(stored_rows(store.db, t)) for t in TABLES}

    for call in (
        lambda: add_row(store, "links", {}, BY_HAND),
        lambda: current(store, "links"),
        lambda: supersede(store, "links", session_row, {}, BY_HAND),
    ):
        with pytest.raises(StoreError, match="no table links"):
            call()
    for name in ("id", "created_at", "supersedes", "origin", "parent"):
        with pytest.raises(StoreError, match=name):
            add_row(store, "sessions", {name: "x"}, BY_HAND)
        with pytest.raises(StoreError, match=name):
            supersede(store, "sessions", session_row, {name: "x"}, BY_HAND)
    with pytest.raises(StoreError, match="tools"):
        add_row(store, "sessions", {"tools": "Read"}, BY_HAND)

    assert {t: len(stored_rows(store.db, t)) for t in TABLES} == counts


def test_a_row_given_its_id_is_written_once(filled, tmp_path):
    # Capture gives each event the harness's own id for its tool call (plan Step 5).
    store, ids = filled
    event = story_events(ids["sessions"][0], tmp_path / "project")[0]
    given = "toolu_story_01_read"

    assert add_row(store, "events", event, BY_HAND, row_id=given) == given
    row = stored_row(store.db, "events", given)
    assert {k: row[k] for k in event} == event
    assert {k: row[k] for k in PROVENANCE} == BY_HAND
    count = len(stored_rows(store.db, "events"))

    # The same id again writes nothing, whatever the fields, and returns None.
    assert add_row(store, "events", dict(event, verb="ran"), CORRECTION, row_id=given) is None
    assert stored_row(store.db, "events", given) == row
    assert len(stored_rows(store.db, "events")) == count

    # A superseded row still holds its id.
    supersede(store, "events", given, {"rationale": "Asked for by the scholar."}, CORRECTION)
    assert add_row(store, "events", event, BY_HAND, row_id=given) is None
    assert stored_row(store.db, "events", given) == row
    assert len(stored_rows(store.db, "events")) == count + 1


@pytest.mark.parametrize("row_id", ["", "   ", 3])
def test_a_given_id_must_be_text(filled, row_id):
    store, ids = filled
    counts = {t: len(stored_rows(store.db, t)) for t in TABLES}
    for table in TABLES:
        with pytest.raises(StoreError, match="id"):
            add_row(store, table, {}, BY_HAND, row_id=row_id)
    assert {t: len(stored_rows(store.db, t)) for t in TABLES} == counts


def test_a_new_store_works_in_an_empty_temp_folder(tmp_path):
    assert list(tmp_path.iterdir()) == []
    store = open_store(tmp_path)
    try:
        assert (tmp_path / "audit.sqlite").is_file()
        assert (tmp_path / "files").is_dir()
        assert table_columns(store.db) == COLUMNS
        assert all(current(store, t) == [] for t in TABLES)

        fields = story_session_fields(tmp_path / "project")
        row_id = add_row(store, "sessions", fields, BY_HAND)
        row = current(store, "sessions")[0]
        assert row["id"] == row_id
        assert {k: row[k] for k in fields} == fields
        assert {k: row[k] for k in PROVENANCE} == BY_HAND
        assert row["supersedes"] is None
        assert row["created_at"]
        assert fields["tools"] == ["Read", "Edit", "Write", "Bash"]
        assert stored_row(store.db, "sessions", row_id)["tools"] == json.dumps(fields["tools"])
    finally:
        store.db.close()


def test_reopening_an_existing_store_works(tmp_path):
    home = tmp_path / "home"
    store = open_store(home)
    ids = fill(store, tmp_path / "project")
    written = {t: current(store, t) for t in TABLES}
    store.db.close()

    store = open_store(home)
    try:
        assert {t: current(store, t) for t in TABLES} == written
        assert table_columns(store.db) == COLUMNS
        transcript = written["transcripts"][0]
        kept = home / "files" / transcript["file_sha256"]
        assert kept.read_bytes() == STORY_BYTES
        assert transcript["byte_size"] == len(STORY_BYTES)
        assert put_file(store, STORY_BYTES) == transcript["file_sha256"]
        assert [p.name for p in (home / "files").iterdir()] == [transcript["file_sha256"]]

        event = story_events(ids["sessions"][0], tmp_path / "project")[0]
        more = add_row(store, "events", event, BY_HAND)
        assert [r["id"] for r in current(store, "events")] == ids["events"] + [more]
        with pytest.raises(sqlite3.IntegrityError, match="never deleted"):
            store.db.execute("DELETE FROM events WHERE id = ?", (more,))
    finally:
        store.db.close()


def test_init_creates_the_audit_home_and_the_database(tmp_path):
    home = tmp_path / "audit_home"
    for _ in range(2):
        proc = subprocess.run(
            [sys.executable, "-m", "audit_layer", "init", "--home", str(home)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, proc.stderr
        assert str(home) in proc.stdout
    assert (home / "audit.sqlite").is_file()
    assert (home / "files").is_dir()
    db = sqlite3.connect(str(home / "audit.sqlite"))
    try:
        assert table_columns(db) == COLUMNS
        assert all(stored_rows(db, t) == [] for t in TABLES)
    finally:
        db.close()
