"""Tests for the export registry and the project write-out (Track A, Step A19).

Appendix A2.4 paragraph 2 and Figure A4 write a project's records out as
files for the pipeline and its replication folder, and Table A3's Shared
tables row keeps an export registry giving each element type's file form and
path. The registry lives in code, in audit_layer/writeout.py, and is written
to its table when the store opens (plan choice 20). A project's sessions,
events, transcripts, and snapshots are written out by project folder (plan
choice 21). Nothing is withheld for naming an excluded folder, since excluded
folders guard only what runs inside them (reconciliation, item 3).

The store is the one full_store.build_full_store makes from the test story
and Track A's fixtures. The sessions the tests add are the story's synthetic
sessions with their ids or folders changed. No real session file is read,
nothing here calls a model or the network, and every test runs with its home
folder inside a temporary folder. Run from the repository root with
python3 -m pytest -q audit_layer/tests.
"""
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import audit_layer.writeout as writeout  # noqa: E402
from audit_layer.capture import capture_session  # noqa: E402
from audit_layer.cli import main  # noqa: E402
from audit_layer.fields import FIELDS  # noqa: E402
from audit_layer.queries import latest_transcript, session_events  # noqa: E402
from audit_layer.records.citation_log import write_citation_log  # noqa: E402
from audit_layer.records.rationales import rationales, write_rationales  # noqa: E402
from audit_layer.records.session_writes import session_writes, write_session_writes  # noqa: E402
from audit_layer.store import TABLES, add_row, current, open_store  # noqa: E402
from audit_layer.tests.full_store import (  # noqa: E402
    AGENT_ID,
    STORY,
    STORY_ID,
    SUBAGENT_ID,
    build_full_store,
)
from audit_layer.writeout import REGISTRY, Form, sync_registry, transcript_path, write_out_project  # noqa: E402

SESSIONS = STORY / "sessions" / "claude_code"
STORY_SESSION = SESSIONS / "story_session.jsonl"
EXCLUDED_SESSION = SESSIONS / "excluded_session.jsonl"
TOKEN = "{{PROJECT}}"
OTHER_ID = "0d6e2b71-8f4a-4c3e-9a15-b7e2c4d9f160"
READER_ID = "9b1e0414-6c3a-4f2d-b8e5-71d2a9c4f086"
INSIDE_ID = "3c2a9e50-71b4-4d0f-8e26-c5a1f7d3b842"

SPINE = ["id", "created_at", "session", "origin", "method", "reason", "supersedes"]
KEPT = ["created_at", "session", "origin", "method", "reason"]
REGISTRY_PROVENANCE = {
    "session": "none",
    "origin": "audit_layer",
    "method": "writeout 1",
    "reason": "schema",
}

# The files the story's project writes, as Step A19's registry names them, with
# W's three records (reconciliation, Track A, A19).
STORY_FILES = {
    "audit/projects.yaml",
    "audit/sessions.yaml",
    "audit/events.jsonl",
    "audit/transcripts.yaml",
    f"audit/transcripts/claude_code/{STORY_ID}.jsonl",
    f"audit/transcripts/claude_code/{STORY_ID}/agent-{AGENT_ID}.jsonl",
    "audit/snapshots.yaml",
    "audit/citation_log.yaml",
    "audit/session_writes.jsonl",
    "audit/rationales.yaml",
    "working/manuscript.md",
    "working/source_notes.md",
    "working/notes/reading_list.md",
    "schema/field_definitions.yaml",
    "schema/export_registry.yaml",
    "written_out.yaml",
}


def stored_rows(db, table):
    cursor = db.execute(f'SELECT * FROM "{table}" ORDER BY rowid')
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def store_tables(db):
    return sorted(r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'"))


def every_row(db):
    return {table: stored_rows(db, table) for table in store_tables(db)}


def files_in(folder):
    return {p.relative_to(folder).as_posix() for p in Path(folder).rglob("*") if p.is_file()}


def load_yaml(path):
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def load_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def lines_of(source, project, cwd=None):
    """A story session's lines, run in project, or in cwd when given."""
    text = source.read_text(encoding="utf-8")
    if cwd is not None:
        text = text.replace(f'"cwd":"{TOKEN}/excluded_folder"', '"cwd":' + json.dumps(str(cwd)))
        text = text.replace(f'"cwd":"{TOKEN}"', '"cwd":' + json.dumps(str(cwd)))
    text = text.replace(TOKEN, json.dumps(str(project))[1:-1])
    return [line for line in text.split("\n") if line]


def write_session(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes("".join(line + "\n" for line in lines).encode("utf-8"))
    return path


def renamed(lines, old_id, new_id, tool_prefix):
    return [line.replace(old_id, new_id).replace(tool_prefix, tool_prefix + "_b") for line in lines]


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


@pytest.fixture
def out(tmp_path):
    return tmp_path / "written"


@pytest.fixture
def written(full, out):
    files = write_out_project(full.store, full.project, out)
    return files


def capture_other(full, tmp_path):
    """A session of its own run in another folder, captured into the full store."""
    other = tmp_path / "second_study"
    other.mkdir()
    lines = renamed(lines_of(STORY_SESSION, other), STORY_ID, OTHER_ID, "toolu_story")
    path = write_session(tmp_path / "other_root" / (OTHER_ID + ".jsonl"), lines)
    capture_session(full.store, "claude_code", path, full.settings)
    return other


def capture_reader(full, tmp_path):
    """A session run in the project that reads a file inside the excluded folder."""
    (full.project / "excluded_folder").mkdir(exist_ok=True)
    lines = lines_of(EXCLUDED_SESSION, full.project, cwd=full.project)
    path = write_session(tmp_path / "reader_root" / (READER_ID + ".jsonl"), lines)
    summary = capture_session(full.store, "claude_code", path, full.settings)
    assert not summary.excluded
    return path


def capture_inside(full, tmp_path):
    """A session run in a folder inside the project."""
    inside = full.project / "analysis"
    inside.mkdir()
    lines = renamed(lines_of(STORY_SESSION, full.project, cwd=inside), STORY_ID, INSIDE_ID, "toolu_story")
    path = write_session(tmp_path / "inside_root" / (INSIDE_ID + ".jsonl"), lines)
    capture_session(full.store, "claude_code", path, full.settings)
    return inside


# The export registry.


def test_the_registry_names_each_element_s_file_form_and_path():
    assert [tuple(form) for form in REGISTRY] == [
        ("projects", "YAML list", "audit/projects.yaml"),
        ("sessions", "YAML list", "audit/sessions.yaml"),
        ("events", "JSON Lines", "audit/events.jsonl"),
        ("transcripts", "YAML list", "audit/transcripts.yaml"),
        ("transcripts", "bytes, unchanged", "audit/transcripts/<harness>/<session id>.<jsonl or json>"),
        ("snapshots", "YAML list", "audit/snapshots.yaml"),
        ("snapshots", "bytes, unchanged", "working/<path>"),
        ("citation_log", "YAML mapping", "audit/citation_log.yaml"),
        ("session_writes", "JSON Lines", "audit/session_writes.jsonl"),
        ("rationales", "YAML list", "audit/rationales.yaml"),
        ("sources", "YAML list", "sources/sources.yaml"),
        ("source_originals", "YAML list", "sources/originals.yaml"),
        ("source_originals", "bytes, unchanged", "sources/originals/<citekey>.<pdf, html, txt, or bin>"),
        ("source_texts", "YAML list", "sources/texts.yaml"),
        ("source_texts", "text", "sources/texts/<citekey>.<kind>.txt"),
        ("datasets", "YAML list", "data/datasets.yaml"),
        ("codebook", "CSV", "data/<name>_v<version>_codebook.csv"),
        ("ds_*", "CSV", "data/<name>_v<version>.csv"),
        ("knowledge_entries", "YAML list", "knowledge/entries.yaml"),
        ("knowledge_entries", "markdown, unchanged", "knowledge/<entry id>.md"),
        ("knowledge_history", "YAML list", "knowledge/history.yaml"),
        ("knowledge_history", "markdown, unchanged", "knowledge/history/<entry id>/<n>.md"),
        ("field_definitions", "YAML list", "schema/field_definitions.yaml"),
        ("export_registry", "YAML list", "schema/export_registry.yaml"),
    ]
    assert all(isinstance(form, Form) for form in REGISTRY)


def test_every_table_in_the_store_has_a_registry_row(full):
    elements = {row["element"] for row in current(full.store, "export_registry")}
    tables = store_tables(full.store.db)
    assert any(name.startswith("ds_") for name in tables)
    for table in tables:
        assert ("ds_*" if table.startswith("ds_") else table) in elements, table
    assert set(TABLES) <= elements
    assert elements - set(TABLES) == {"ds_*", "citation_log", "session_writes", "rationales"}


def test_a_new_store_holds_one_current_row_for_each_registry_form(tmp_path):
    store = open_store(tmp_path / "audit_home")
    try:
        rows = current(store, "export_registry")
        assert [Form(r["element"], r["file_form"], r["path"]) for r in rows] == list(REGISTRY)
        for row in rows:
            assert {name: row[name] for name in REGISTRY_PROVENANCE} == REGISTRY_PROVENANCE
            assert row["supersedes"] is None
    finally:
        store.db.close()


def test_opening_the_store_again_writes_no_registry_row(full):
    before = every_row(full.store.db)
    store = open_store(full.home)
    try:
        assert sync_registry(store) == 0
        assert every_row(store.db) == before
    finally:
        store.db.close()


def test_a_changed_path_supersedes_the_registry_row_and_keeps_the_old_one(full, monkeypatch):
    (old,) = [row for row in current(full.store, "export_registry") if row["element"] == "events"]
    changed = tuple(
        form._replace(path="audit/actions.jsonl") if form.element == "events" else form
        for form in REGISTRY
    )
    monkeypatch.setattr(writeout, "REGISTRY", changed)
    count = len(stored_rows(full.store.db, "export_registry"))

    assert sync_registry(full.store) == 1
    rows = stored_rows(full.store.db, "export_registry")
    assert len(rows) == count + 1
    assert old in rows
    (new,) = [row for row in current(full.store, "export_registry") if row["element"] == "events"]
    assert new["supersedes"] == old["id"]
    assert new["path"] == "audit/actions.jsonl"
    assert sync_registry(full.store) == 0


def test_the_export_registry_table_has_its_fields_and_refuses_update_and_delete(tmp_path):
    store = open_store(tmp_path / "audit_home")
    try:
        names = [r[1] for r in store.db.execute("PRAGMA table_info(export_registry)")]
        assert names == ["id", "element", "file_form", "path"] + SPINE[1:]
        with pytest.raises(sqlite3.DatabaseError, match="never updated"):
            store.db.execute("UPDATE export_registry SET path = 'changed'")
        with pytest.raises(sqlite3.DatabaseError, match="never deleted"):
            store.db.execute("DELETE FROM export_registry")
    finally:
        store.db.close()


def test_the_export_registry_s_fields_have_definitions(full):
    held = {(r["table_name"], r["field"]) for r in current(full.store, "field_definitions")}
    for field in ("element", "file_form", "path"):
        assert ("export_registry", field) in held
    assert {item.field for item in FIELDS if item.table_name == "export_registry"} == {
        "element",
        "file_form",
        "path",
    }


# The project write-out.


def test_the_story_s_project_writes_every_audit_working_and_schema_file(full, out, written):
    assert files_in(out) == STORY_FILES


def test_sessions_yaml_lists_the_story_session_and_its_subagent_with_tags_and_provenance(
    full, out, written
):
    records = load_yaml(out / "audit" / "sessions.yaml")
    assert isinstance(records, list)
    by_id = {record["harness_session_id"]: record for record in records}
    assert set(by_id) == {STORY_ID, SUBAGENT_ID}

    story = by_id[STORY_ID]
    assert story["title"] == "Two findings on volunteer exit"
    assert story["origin"] == "person A. Reviewer"
    assert story["method"] == "review"
    assert story["keywords"] and isinstance(story["keywords"], list)
    assert story["gist"] and story["summary"]

    subagent = by_id[SUBAGENT_ID]
    assert subagent["origin"] == "model pass"
    assert subagent["title"] == "Start a reading list and check a citation"
    assert subagent["tools"] == ["Read", "Write", "Grep"]

    for row in current(full.store, "sessions"):
        record = by_id[row["harness_session_id"]]
        assert record == {name: value for name, value in row.items() if name not in ("id", "supersedes")}
        for name in KEPT:
            assert record[name]


def test_no_record_has_an_id_or_supersedes_and_references_are_session_ids(full, out, written):
    lists = {
        "projects": load_yaml(out / "audit" / "projects.yaml"),
        "sessions": load_yaml(out / "audit" / "sessions.yaml"),
        "events": load_jsonl(out / "audit" / "events.jsonl"),
        "transcripts": load_yaml(out / "audit" / "transcripts.yaml"),
        "snapshots": load_yaml(out / "audit" / "snapshots.yaml"),
        "field_definitions": load_yaml(out / "schema" / "field_definitions.yaml"),
        "export_registry": load_yaml(out / "schema" / "export_registry.yaml"),
    }
    for element, records in lists.items():
        assert records, element
        for record in records:
            assert "id" not in record and "supersedes" not in record, element
            for name in KEPT:
                assert record[name], (element, name)

    ids = {STORY_ID, SUBAGENT_ID}
    assert {record["session_row_id"] for record in lists["events"]} == ids
    assert {record["session_row_id"] for record in lists["transcripts"]} == ids
    row_ids = {row["id"] for row in stored_rows(full.store.db, "sessions")}
    assert not row_ids & {record["session_row_id"] for record in lists["events"]}


def test_events_jsonl_holds_each_session_s_current_events_in_ordinal_order(full, out, written):
    records = load_jsonl(out / "audit" / "events.jsonl")
    expected = []
    for row in current(full.store, "sessions"):
        for event in session_events(full.store, row):
            kept = {name: value for name, value in event.items() if name not in ("id", "supersedes")}
            kept["session_row_id"] = row["harness_session_id"]
            expected.append(kept)
    assert sorted(records, key=json.dumps) == sorted(expected, key=json.dumps)
    for session_id in (STORY_ID, SUBAGENT_ID):
        ordinals = [r["ordinal"] for r in records if r["session_row_id"] == session_id]
        assert ordinals == sorted(ordinals) and ordinals
    assert any(record["kind"] == "decision" and record["rationale"] for record in records)


def test_each_transcript_file_equals_the_stored_bytes(full, out, written):
    for row in current(full.store, "sessions"):
        transcript, data = latest_transcript(full.store, row)
        path = out / transcript_path(row["harness"], row["harness_session_id"])
        assert path.read_bytes() == data
        assert sha256(path) == transcript["file_sha256"]
    records = load_yaml(out / "audit" / "transcripts.yaml")
    assert len(records) == len(current(full.store, "transcripts"))


def test_working_manuscript_equals_the_snapshot(full, out, written):
    (snapshot,) = [r for r in current(full.store, "snapshots") if r["path"] == "manuscript.md"]
    kept = (full.store.files / snapshot["file_sha256"]).read_bytes()
    assert (out / "working" / "manuscript.md").read_bytes() == kept
    assert kept == (full.project / "manuscript.md").read_bytes()
    records = load_yaml(out / "audit" / "snapshots.yaml")
    assert {(r["path"], r["kind"]) for r in records} == {
        ("manuscript.md", "draft"),
        ("source_notes.md", "draft"),
        ("notes/reading_list.md", "note"),
    }


def test_the_checksums_in_written_out_yaml_match_the_files(full, out, written):
    listed = load_yaml(out / "written_out.yaml")
    assert set(listed) == {"files"}
    paths = [item["path"] for item in listed["files"]]
    assert set(paths) == STORY_FILES - {"written_out.yaml"}
    assert len(paths) == len(set(paths))
    for item in listed["files"]:
        assert item["sha256"] == sha256(out / item["path"]), item["path"]
    elements = {item["path"]: item["element"] for item in listed["files"]}
    assert elements["audit/events.jsonl"] == "events"
    assert elements[f"audit/transcripts/claude_code/{STORY_ID}.jsonl"] == "transcripts"
    assert elements["working/manuscript.md"] == "snapshots"
    assert elements["schema/export_registry.yaml"] == "export_registry"
    assert [tuple(item) for item in written] == [
        (item["path"], item["element"], item["sha256"]) for item in listed["files"]
    ]


def test_written_out_yaml_is_written_last(full, out, monkeypatch):
    order = []
    real = writeout._write_file

    def recording(path, data):
        order.append(Path(path).relative_to(out).as_posix())
        real(path, data)

    monkeypatch.setattr(writeout, "_write_file", recording)
    write_out_project(full.store, full.project, out)
    assert order[-1] == "written_out.yaml"
    assert set(order) == STORY_FILES


def test_the_schema_files_hold_the_current_definitions_and_registry(full, out, written):
    definitions = load_yaml(out / "schema" / "field_definitions.yaml")
    assert len(definitions) == len(current(full.store, "field_definitions"))
    registry = load_yaml(out / "schema" / "export_registry.yaml")
    assert [(r["element"], r["file_form"], r["path"]) for r in registry] == [
        tuple(form) for form in REGISTRY
    ]


def test_a_session_in_another_project_is_left_out(full, tmp_path, out):
    other = capture_other(full, tmp_path)
    assert current(full.store, "sessions", harness_session_id=OTHER_ID)

    write_out_project(full.store, full.project, out)
    assert files_in(out) == STORY_FILES
    sessions = load_yaml(out / "audit" / "sessions.yaml")
    assert OTHER_ID not in {r["harness_session_id"] for r in sessions}
    assert OTHER_ID not in {r["session_row_id"] for r in load_jsonl(out / "audit" / "events.jsonl")}
    assert OTHER_ID not in {r["session_row_id"] for r in load_yaml(out / "audit" / "transcripts.yaml")}
    assert [r["folder"] for r in load_yaml(out / "audit" / "projects.yaml")] == [str(full.project)]
    assert str(other) not in (out / "audit" / "projects.yaml").read_text(encoding="utf-8")


def test_a_session_in_the_project_that_reads_inside_the_excluded_folder_is_written_out(
    full, tmp_path, out
):
    capture_reader(full, tmp_path)
    write_out_project(full.store, full.project, out)

    sessions = load_yaml(out / "audit" / "sessions.yaml")
    assert READER_ID in {r["harness_session_id"] for r in sessions}
    assert (out / transcript_path("claude_code", READER_ID)).is_file()
    assert set(load_yaml(out / "written_out.yaml")) == {"files"}


def test_a_session_in_a_folder_inside_the_project_is_written_out(full, tmp_path, out):
    inside = capture_inside(full, tmp_path)
    write_out_project(full.store, full.project, out)

    sessions = load_yaml(out / "audit" / "sessions.yaml")
    assert INSIDE_ID in {r["harness_session_id"] for r in sessions}
    folders = [r["folder"] for r in load_yaml(out / "audit" / "projects.yaml")]
    assert folders == [str(full.project), str(inside)]


def test_a_non_empty_output_folder_is_refused_and_nothing_is_written(full, out):
    out.mkdir()
    (out / "kept.txt").write_text("already here\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not empty"):
        write_out_project(full.store, full.project, out)
    assert files_in(out) == {"kept.txt"}


def test_an_output_path_that_is_a_file_is_refused(full, out):
    out.write_text("a file\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not a folder"):
        write_out_project(full.store, full.project, out)
    assert out.read_text(encoding="utf-8") == "a file\n"


def test_an_empty_output_folder_is_written_into(full, out):
    out.mkdir()
    write_out_project(full.store, full.project, out)
    assert files_in(out) == STORY_FILES


def test_an_altered_stored_file_is_refused_and_nothing_is_written(full, out):
    (snapshot,) = [r for r in current(full.store, "snapshots") if r["path"] == "manuscript.md"]
    (full.store.files / snapshot["file_sha256"]).write_bytes(b"altered\n")
    with pytest.raises(ValueError, match="altered"):
        write_out_project(full.store, full.project, out)
    assert not out.exists() or files_in(out) == set()


def test_a_session_id_s_slash_becomes_a_folder_and_other_characters_become_underscores():
    assert transcript_path("claude_code", "a1/agent-b2") == "audit/transcripts/claude_code/a1/agent-b2.jsonl"
    assert transcript_path("claude_code", "a b:c.d_e-f") == "audit/transcripts/claude_code/a_b_c.d_e-f.jsonl"
    assert transcript_path("forgecode", "conv-1") == "audit/transcripts/forgecode/conv-1.json"
    # A part made only of dots never climbs out of its folder.
    assert transcript_path("claude_code", "../x") == "audit/transcripts/claude_code/__/x.jsonl"


# W's three records, the records the procedures read (reconciliation, Track A, A19).


def written_by(writer, *arguments):
    """The bytes a record writer writes to a file of its own."""
    folder = Path(arguments[-1])
    writer(*arguments)
    return folder.read_bytes()


def test_the_registry_gives_w_s_three_records_the_paths_the_handoffs_copy_to():
    forms = {form.element: form for form in REGISTRY}
    assert forms["citation_log"] == Form("citation_log", "YAML mapping", "audit/citation_log.yaml")
    assert forms["session_writes"] == Form("session_writes", "JSON Lines", "audit/session_writes.jsonl")
    assert forms["rationales"] == Form("rationales", "YAML list", "audit/rationales.yaml")


def test_the_written_out_citation_log_is_what_write_citation_log_writes(full, out, written, tmp_path):
    expected = written_by(write_citation_log, full.store, full.project, tmp_path / "citation_log.yaml")
    assert (out / "audit" / "citation_log.yaml").read_bytes() == expected
    log = load_yaml(out / "audit" / "citation_log.yaml")["citations"]
    assert sorted(log) == ["dumont2014", "healy2020", "nakamura2020"]
    assert log["dumont2014"]["session"] == STORY_ID
    assert log["healy2020"]["session"] == SUBAGENT_ID


def test_the_written_out_file_writes_are_what_write_session_writes_writes(full, out, written, tmp_path):
    rows = session_writes(full.store, full.project)
    expected = written_by(write_session_writes, rows, tmp_path / "session_writes.jsonl")
    assert (out / "audit" / "session_writes.jsonl").read_bytes() == expected
    assert {row["path"] for row in load_jsonl(out / "audit" / "session_writes.jsonl")} == {
        "manuscript.md",
        "source_notes.md",
        "notes/reading_list.md",
    }


def test_the_written_out_rationales_are_those_of_the_project_s_manuscript(full, out, written, tmp_path):
    entries = rationales(full.store, full.project / "manuscript.md")
    expected = written_by(write_rationales, entries, tmp_path / "rationales.yaml")
    assert (out / "audit" / "rationales.yaml").read_bytes() == expected
    loaded = load_yaml(out / "audit" / "rationales.yaml")
    assert loaded == yaml.safe_load((STORY / "prose" / "expected_rationales.yaml").read_text(encoding="utf-8"))


def test_written_out_yaml_lists_the_three_records_under_their_elements(full, out, written):
    listed = {item["path"]: item for item in load_yaml(out / "written_out.yaml")["files"]}
    for path, element in (
        ("audit/citation_log.yaml", "citation_log"),
        ("audit/session_writes.jsonl", "session_writes"),
        ("audit/rationales.yaml", "rationales"),
    ):
        assert listed[path]["element"] == element
        assert listed[path]["sha256"] == sha256(out / path)


def test_a_project_with_no_ai_session_writes_the_three_records_empty(tmp_path, out):
    folder = tmp_path / "quiet_project"
    folder.mkdir()
    store = open_store(tmp_path / "quiet_home")
    try:
        write_out_project(store, folder, out)
    finally:
        store.db.close()
    assert load_yaml(out / "audit" / "citation_log.yaml") == {"citations": {}}
    assert (out / "audit" / "session_writes.jsonl").read_bytes() == b""
    assert load_yaml(out / "audit" / "rationales.yaml") == []


def test_a_record_that_cannot_be_written_is_refused_and_nothing_is_written(full, tmp_path, out):
    # A session run elsewhere that edited the project's manuscript, with no
    # transcript stored, so its stated reasons cannot be read. The citation
    # log skips it and names it, since it ran outside the project (Track L,
    # Step L7), and the rationales record is refused.
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    provenance = {"session": "lost-1", "origin": "test", "method": "by hand", "reason": "test"}
    row = add_row(
        full.store,
        "sessions",
        {
            "harness": "claude_code",
            "harness_session_id": "lost-1",
            "project": str(elsewhere),
            "started_at": "2026-10-20T09:00:00.000Z",
            "ended_at": "2026-10-20T09:10:00.000Z",
            "tools": ["Edit"],
        },
        provenance,
    )
    add_row(
        full.store,
        "events",
        {
            "session_row_id": row,
            "ordinal": 1,
            "verb": "edited",
            "kind": "action",
            "object": str(full.project / "manuscript.md"),
            "rationale": "",
            "role": "edited",
        },
        provenance,
    )
    with pytest.raises(writeout.WriteOutError, match="rationales record.*no stored transcript.*nothing was written"):
        write_out_project(full.store, full.project, out)
    assert not out.exists() or files_in(out) == set()


# The write-out project command.


def test_the_write_out_project_command_writes_the_folder(full, out, capsys):
    code = main(
        ["write-out", "project", "--home", str(full.home), "--project", str(full.project), "--out", str(out)]
    )
    assert code == 0
    assert files_in(out) == STORY_FILES
    printed = capsys.readouterr().out
    assert printed.splitlines() == [
        f"wrote {out}, 15 files listed in written_out.yaml"
    ]


def test_the_write_out_project_command_refuses_a_non_empty_folder(full, out, capsys):
    out.mkdir()
    (out / "kept.txt").write_text("already here\n", encoding="utf-8")
    code = main(
        ["write-out", "project", "--home", str(full.home), "--project", str(full.project), "--out", str(out)]
    )
    assert code == 1
    assert "not empty" in capsys.readouterr().err
    assert files_in(out) == {"kept.txt"}


def test_the_write_out_project_command_refuses_a_home_with_no_store(tmp_path, capsys):
    home = tmp_path / "no_home"
    code = main(
        ["write-out", "project", "--home", str(home), "--project", str(tmp_path), "--out", str(tmp_path / "o")]
    )
    assert code == 1
    assert "no audit store" in capsys.readouterr().err
    assert not home.exists()
    assert not (tmp_path / "o").exists()
