"""A synthetic audit home for the observability tests (Track E, step E2).

The home is built with sqlite3 from the reader's own RECORD_COLUMNS, and each
transcript file is written where stored_path says the audit layer keeps it.
Nothing here imports the audit layer's code. Transcript text comes from the
test story's Claude Code session, with {{PROJECT}} replaced by a temporary
folder, so no fixture holds a real folder name or machine path.
"""
import hashlib
import sqlite3
import uuid
from pathlib import Path

from observability.record import DATABASE, RECORD_COLUMNS, stored_path

STORY_SESSION = (
    Path(__file__).resolve().parents[2]
    / "examples" / "test_story" / "sessions" / "claude_code" / "story_session.jsonl"
)
STORY_SESSION_ID = "5f3c0413-2a7d-4b9e-8c61-a0d4e7b2c913"


def story_transcript(project, lines=None):
    """The test story's session as bytes, its first lines only when lines is given."""
    text = STORY_SESSION.read_text(encoding="utf-8").replace("{{PROJECT}}", str(project))
    if lines is not None:
        text = "".join(text.splitlines(True)[:lines])
    return text.encode("utf-8")


class AuditHome:
    """An audit home with the three tables the reader uses and its file store.

    drop names a (table, key) pair of RECORD_COLUMNS to leave out of the
    database, and skip_table a table to leave out, so a refusal can be tested.
    """

    def __init__(self, home, drop=None, skip_table=None):
        self.home = Path(home)
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / "files").mkdir(exist_ok=True)
        self.path = self.home / DATABASE
        self._clock = 0
        db = sqlite3.connect(str(self.path))
        for table, columns in RECORD_COLUMNS.items():
            if table == skip_table:
                continue
            names = [
                name for key, name in columns.items()
                if (table, key) != drop
            ]
            db.execute("CREATE TABLE {} ({})".format(table, ", ".join(names)))
        db.commit()
        db.close()

    def _now(self):
        self._clock += 1
        return "2026-10-21T15:00:{:02d}.{:06d}Z".format(self._clock // 1000000, self._clock % 1000000)

    def _insert(self, table, values):
        columns = RECORD_COLUMNS[table]
        values = dict(values)
        values.setdefault("id", uuid.uuid4().hex)
        values.setdefault("created_at", self._now())
        values.setdefault("supersedes", None)
        names = [columns[key] for key in values]
        db = sqlite3.connect(str(self.path))
        db.execute(
            "INSERT INTO {} ({}) VALUES ({})".format(
                table, ", ".join(names), ", ".join("?" for _ in names)),
            list(values.values()),
        )
        db.commit()
        db.close()
        return values["id"]

    def add_session(self, harness_session_id, project, harness="claude_code",
                    started_at="2026-10-21T14:02:05.112Z",
                    ended_at="2026-10-21T14:09:41.600Z", supersedes=None):
        return self._insert("sessions", {
            "harness": harness,
            "harness_session_id": harness_session_id,
            "project": str(project),
            "started_at": started_at,
            "ended_at": ended_at,
            "supersedes": supersedes,
        })

    def add_event(self, session_row, ordinal, verb, obj, kind="action",
                  rationale="", role="", supersedes=None, row_id=None):
        values = {
            "session_row": session_row,
            "ordinal": ordinal,
            "verb": verb,
            "kind": kind,
            "object": obj,
            "rationale": rationale,
            "role": role,
            "supersedes": supersedes,
        }
        if row_id is not None:
            values["id"] = row_id
        return self._insert("events", values)

    def add_transcript(self, session_row, data, write_file=True):
        """Keep data as a transcript of session_row and return its checksum."""
        checksum = hashlib.sha256(data).hexdigest()
        if write_file:
            stored_path(self.home, checksum).write_bytes(data)
        self._insert("transcripts", {
            "session_row": session_row,
            "file_sha256": checksum,
        })
        return checksum

    def digest(self):
        """The sha256 of the database file's bytes."""
        return hashlib.sha256(self.path.read_bytes()).hexdigest()
