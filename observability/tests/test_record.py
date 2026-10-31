"""Tests for the audit record reader (Track E, step E2).

Appendix A2.6 and Figure A4 have the observability layer read the audit
layer's record as it is written. The reader opens the audit home read only
and imports nothing from the audit layer. Every audit home here is synthetic,
built by audit_fixture.py in a temporary folder, and its transcripts come from
the test story. Nothing here calls a model or the network. Run from the
repository root with python3 -m pytest -q observability/tests.
"""
import hashlib
import os
import sqlite3

import pytest

from observability import record as rc
from observability.tests.audit_fixture import (
    STORY_SESSION_ID,
    AuditHome,
    story_transcript,
)


@pytest.fixture
def project(tmp_path):
    folder = tmp_path / "work" / "story_project"
    folder.mkdir(parents=True)
    return folder


@pytest.fixture
def audit(tmp_path):
    return AuditHome(tmp_path / "audit_home")


def _grown(audit, project):
    """A session captured twice, the second time after it grew."""
    first = audit.add_session(STORY_SESSION_ID, project, ended_at="2026-10-21T14:05:00.000Z")
    early = audit.add_transcript(first, story_transcript(project, lines=6))
    audit.add_event(first, 1, "read", "manuscript.md", role="read", row_id="toolu_a")
    second = audit.add_session(STORY_SESSION_ID, project, supersedes=first)
    late = audit.add_transcript(second, story_transcript(project))
    audit.add_event(second, 2, "edited", "manuscript.md", role="edited", row_id="toolu_b")
    return first, second, early, late


# Where the audit layer keeps things


def test_stored_path_is_the_file_store_under_the_checksum(tmp_path):
    checksum = "ab" * 32
    assert rc.stored_path(tmp_path, checksum) == tmp_path / "files" / checksum
    assert rc.stored_path(str(tmp_path), checksum) == tmp_path / "files" / checksum


def test_record_columns_name_each_table_and_the_fields_used():
    for table in ("sessions", "events", "transcripts"):
        for key in ("id", "created_at", "supersedes"):
            assert key in rc.RECORD_COLUMNS[table]
    assert rc.RECORD_COLUMNS["events"]["session_row"] == "session_row_id"
    assert rc.RECORD_COLUMNS["transcripts"]["session_row"] == "session_row_id"
    for key in ("harness", "harness_session_id", "project", "started_at", "ended_at"):
        assert rc.RECORD_COLUMNS["sessions"][key] == key
    for key in ("ordinal", "verb", "kind", "object", "rationale", "role"):
        assert rc.RECORD_COLUMNS["events"][key] == key
    assert rc.RECORD_COLUMNS["transcripts"]["file_sha256"] == "file_sha256"


# Opening the record read only, and refusing what is missing


def test_a_missing_database_is_refused_by_name(tmp_path):
    with pytest.raises(rc.RecordError) as error:
        rc.open_record(tmp_path / "nowhere")
    assert "audit.sqlite" in str(error.value)
    assert not (tmp_path / "nowhere").exists()


@pytest.mark.parametrize("table", ["sessions", "events", "transcripts"])
def test_a_missing_table_is_refused_by_name(tmp_path, table):
    AuditHome(tmp_path / "home", skip_table=table)
    with pytest.raises(rc.RecordError) as error:
        rc.open_record(tmp_path / "home")
    assert table in str(error.value)


@pytest.mark.parametrize("table,key", [
    (table, key) for table, columns in rc.RECORD_COLUMNS.items() for key in columns
])
def test_a_missing_column_is_named_in_the_refusal(tmp_path, table, key):
    AuditHome(tmp_path / "home", drop=(table, key))
    with pytest.raises(rc.RecordError) as error:
        rc.open_record(tmp_path / "home")
    message = str(error.value)
    assert table in message
    assert rc.RECORD_COLUMNS[table][key] in message


def test_the_record_is_opened_read_only(audit, project):
    audit.add_session(STORY_SESSION_ID, project)
    record = rc.open_record(audit.home)
    with pytest.raises(sqlite3.OperationalError):
        record.db.execute("DELETE FROM sessions")
    record.db.close()


def test_a_write_lock_is_waited_on_for_five_seconds(monkeypatch, audit):
    seen = {}
    real = sqlite3.connect

    def connect(*args, **kwargs):
        seen.update(kwargs)
        seen["address"] = args[0]
        return real(*args, **kwargs)

    monkeypatch.setattr(rc.sqlite3, "connect", connect)
    rc.open_record(audit.home).db.close()
    assert seen["timeout"] == 5
    assert seen["uri"] is True
    assert seen["address"].startswith("file:")
    assert seen["address"].endswith("?mode=ro")


# Sessions


def test_a_session_with_a_superseded_row_is_listed_once_with_both_row_ids(audit, project):
    first, second, _, _ = _grown(audit, project)
    found = rc.sessions(rc.open_record(audit.home))
    assert len(found) == 1
    session = found[0]
    assert session["row_ids"] == [first, second]
    assert session["harness"] == "claude_code"
    assert session["harness_session_id"] == STORY_SESSION_ID
    assert session["project"] == str(project)
    assert session["started_at"] == "2026-10-21T14:02:05.112Z"
    # The current row's fields, not the older row's.
    assert session["ended_at"] == "2026-10-21T14:09:41.600Z"


def test_a_session_whose_only_row_is_superseded_is_not_listed(audit, project):
    wrong = audit.add_session("s-wrong-id", project)
    right = audit.add_session("s-right-id", project, supersedes=wrong)
    found = rc.sessions(rc.open_record(audit.home))
    assert [s["harness_session_id"] for s in found] == ["s-right-id"]
    assert found[0]["row_ids"] == [right]


def test_sessions_of_other_harnesses_and_ids_are_kept_apart(audit, project):
    one = audit.add_session("same-id", project, harness="claude_code")
    two = audit.add_session("same-id", project, harness="forgecode")
    three = audit.add_session("other-id", project, harness="claude_code")
    found = rc.sessions(rc.open_record(audit.home))
    assert [s["row_ids"] for s in found] == [[one], [two], [three]]
    assert [s["harness"] for s in found] == ["claude_code", "forgecode", "claude_code"]


def test_the_project_filter_keeps_a_subfolder_and_drops_a_sibling_sharing_a_prefix(
        audit, project, tmp_path):
    inside = project / "analysis"
    inside.mkdir()
    sibling = tmp_path / "work" / "story_project_old"
    sibling.mkdir()
    at_top = audit.add_session("s-top", project)
    in_sub = audit.add_session("s-sub", inside)
    audit.add_session("s-sibling", sibling)
    record = rc.open_record(audit.home)
    kept = rc.sessions(record, project=project)
    assert [s["row_ids"] for s in kept] == [[at_top], [in_sub]]
    assert len(rc.sessions(record)) == 3


def test_the_project_filter_compares_real_paths(audit, project, tmp_path):
    link = tmp_path / "link_to_project"
    os.symlink(str(project), str(link))
    through_link = audit.add_session("s-link", link / "analysis")
    direct = audit.add_session("s-direct", project)
    kept = rc.sessions(rc.open_record(audit.home), project=link)
    assert [s["row_ids"] for s in kept] == [[through_link], [direct]]


# Transcripts


def test_a_grown_session_returns_both_transcript_versions_oldest_first(audit, project):
    _grown(audit, project)
    record = rc.open_record(audit.home)
    session = rc.sessions(record)[0]
    found = rc.transcripts(record, session)
    assert found == [story_transcript(project, lines=6), story_transcript(project)]


def test_transcripts_of_another_session_are_left_out(audit, project):
    mine = audit.add_session("s-mine", project)
    other = audit.add_session("s-other", project)
    audit.add_transcript(mine, b"mine\n")
    audit.add_transcript(other, b"other\n")
    record = rc.open_record(audit.home)
    session = [s for s in rc.sessions(record) if s["harness_session_id"] == "s-mine"][0]
    assert rc.transcripts(record, session) == [b"mine\n"]


def test_a_missing_transcript_file_raises_naming_the_checksum(audit, project):
    row = audit.add_session(STORY_SESSION_ID, project)
    checksum = audit.add_transcript(row, story_transcript(project), write_file=False)
    record = rc.open_record(audit.home)
    with pytest.raises(rc.RecordError) as error:
        rc.transcripts(record, rc.sessions(record)[0])
    assert checksum in str(error.value)


def test_an_altered_transcript_file_raises_naming_the_checksum(audit, project):
    row = audit.add_session(STORY_SESSION_ID, project)
    checksum = audit.add_transcript(row, story_transcript(project))
    rc.stored_path(audit.home, checksum).write_bytes(b"altered\n")
    record = rc.open_record(audit.home)
    with pytest.raises(rc.RecordError) as error:
        rc.transcripts(record, rc.sessions(record)[0])
    assert checksum in str(error.value)


# Events


def test_events_are_the_current_rows_of_every_session_row_by_ordinal(audit, project):
    first = audit.add_session(STORY_SESSION_ID, project)
    third = audit.add_event(first, 3, "ran", "python3 check.py", kind="observation")
    audit.add_event(first, 1, "read", "manuscript.md", role="read")
    second = audit.add_session(STORY_SESSION_ID, project, supersedes=first)
    audit.add_event(second, 2, "edited", "manuscript.md", role="edited",
                    rationale="add two findings")
    audit.add_event(first, 3, "ran", "python3 check.py", kind="blocker",
                    rationale="exit 1", supersedes=third)
    other = audit.add_session("s-other", project)
    audit.add_event(other, 1, "read", "elsewhere.md")
    record = rc.open_record(audit.home)
    session = [s for s in rc.sessions(record) if s["harness_session_id"] == STORY_SESSION_ID][0]
    found = rc.events(record, session)
    assert found == [
        {"ordinal": 1, "verb": "read", "kind": "action", "object": "manuscript.md",
         "rationale": "", "role": "read"},
        {"ordinal": 2, "verb": "edited", "kind": "action", "object": "manuscript.md",
         "rationale": "add two findings", "role": "edited"},
        {"ordinal": 3, "verb": "ran", "kind": "blocker", "object": "python3 check.py",
         "rationale": "exit 1", "role": ""},
    ]


# Reading changes nothing


def test_the_database_bytes_are_the_same_after_every_read(audit, project):
    _grown(audit, project)
    before = audit.digest()
    listing = sorted(os.listdir(str(audit.home)))
    record = rc.open_record(audit.home)
    assert audit.digest() == before
    for session in rc.sessions(record, project=project):
        assert audit.digest() == before
        rc.transcripts(record, session)
        assert audit.digest() == before
        rc.events(record, session)
        assert audit.digest() == before
    record.db.close()
    assert audit.digest() == before
    assert sorted(os.listdir(str(audit.home))) == listing
    assert hashlib.sha256(audit.path.read_bytes()).hexdigest() == before
