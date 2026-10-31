"""The export registry and the project write-out (Track A, Step A19).

Appendix A2.4 paragraph 2 and Figure A4 write a project's records out as
files for the pipeline and its replication folder, and Table A3's Shared
tables row keeps an export registry giving each element type's file form and
path. Spec 0.11 says that registry is what makes the emit contract
checkable. The registry lives here in code, as REGISTRY, and is written to
the export_registry table when the store opens, as the field definitions are
(plan choice 20). An element is a table's name, or ds_* for the dataset
tables, and a table whose rows point at kept bytes has one form for its rows
and one for its bytes. Three elements are not tables but the records the
procedures read, which Track W's writers in audit_layer/records/ write, the
citation log, the file writes, and the AI rationales, at the paths in a
project's audit/ folder that W's handoffs copy them to (reconciliation,
Track A, A19).

sync_registry(store) adds a row for each form not yet stored and supersedes
a stored row whose path differs, so a store already in step gets nothing new.

write_out_project(store, project, out_dir, citekeys, datasets, knowledge)
writes the projects, sessions, events, transcripts, and snapshots elements
for the sessions whose folder is project or a folder inside it, compared as
real paths, W's three records for the project, and the two schema elements
(plan choice 21). Sources, datasets,
and knowledge entries are written only when named, since without a links
table the store cannot say which belong to a project (Step A20). It writes
written_out.yaml last, listing every other file with its element and sha256.

- Each record keeps its fields and its provenance (session, origin, method,
  reason, and created_at). No record carries its row id or supersedes. Each
  reference to a session row is written as the session's id, to a source's
  record as its citekey, and to a dataset version's table as the path of its
  CSV file, so nothing names a database row.
- The YAML lists hold every current row. The bytes written are each
  session's latest transcript, which holds every record captured so far, and
  the latest snapshot of each working file, at its path relative to the
  project folder.
- A session id's / becomes a folder in a path, and any character other than
  letters, digits, ., -, and _ becomes _. A part made only of dots has each
  dot made _, so no path climbs out of its folder.
- The output folder must be new or empty. Every kept file is read and
  checked against its checksum before anything is written, so a stored file
  that is missing or altered leaves the folder as it was.
- W's three records are written by their own writers, byte for byte as the
  write-out commands for each write them. The citation log and the file
  writes are those of the project folder, and the rationales those of the
  project's manuscript.md, the source W's handoffs take by default. Each is
  made before anything is written, so a record that cannot be made leaves
  the folder as it was.

- citekeys names sources. Each one's current record is written, with every
  current original and text of any version of it. The latest original's
  bytes are written, its extension from its first bytes (%PDF gives .pdf,
  <html or <!DOCTYPE html gives .html, text that decodes as UTF-8 gives .txt,
  and anything else .bin), and each text as UTF-8.
- datasets names dataset versions, each a name, or a pair of a name and a
  version, which is None for the latest. Each version's catalog row is
  written, and its rows and codebook as the two CSV files write_dataset
  writes. The codebook and the rows have no YAML list, since the registry
  gives them CSV only.
- knowledge true writes every current knowledge entry and every replaced
  version in knowledge_history, each as its record and as its content
  unchanged. An entry's replaced versions are numbered from 1, oldest first.
- An unknown citekey, dataset name, or version is refused before anything is
  written.

Nothing is withheld for naming an excluded folder, since excluded folders
guard only what runs inside them (reconciliation, item 3).
"""
import hashlib
import json
import os
import posixpath
import re
import tempfile
from collections import namedtuple
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import yaml

from audit_layer.queries import session_events
from audit_layer.records.citation_log import write_citation_log
from audit_layer.records.rationales import rationales, write_rationales
from audit_layer.records.session_writes import session_writes, write_session_writes
from audit_layer.store import TABLES, Store, current, writing
from audit_layer.stores.data import DataError, dataset_files
from audit_layer.stores.knowledge import history

VERSION = 1

PROVENANCE = {
    "session": "none",
    "origin": "audit_layer",
    "method": f"writeout {VERSION}",
    "reason": "schema",
}

Form = namedtuple("Form", ["element", "file_form", "path"])

REGISTRY = (
    Form("projects", "YAML list", "audit/projects.yaml"),
    Form("sessions", "YAML list", "audit/sessions.yaml"),
    Form("events", "JSON Lines", "audit/events.jsonl"),
    Form("transcripts", "YAML list", "audit/transcripts.yaml"),
    Form("transcripts", "bytes, unchanged", "audit/transcripts/<harness>/<session id>.<jsonl or json>"),
    Form("snapshots", "YAML list", "audit/snapshots.yaml"),
    Form("snapshots", "bytes, unchanged", "working/<path>"),
    Form("citation_log", "YAML mapping", "audit/citation_log.yaml"),
    Form("session_writes", "JSON Lines", "audit/session_writes.jsonl"),
    Form("rationales", "YAML list", "audit/rationales.yaml"),
    Form("sources", "YAML list", "sources/sources.yaml"),
    Form("source_originals", "YAML list", "sources/originals.yaml"),
    Form("source_originals", "bytes, unchanged", "sources/originals/<citekey>.<pdf, html, txt, or bin>"),
    Form("source_texts", "YAML list", "sources/texts.yaml"),
    Form("source_texts", "text", "sources/texts/<citekey>.<kind>.txt"),
    Form("datasets", "YAML list", "data/datasets.yaml"),
    Form("codebook", "CSV", "data/<name>_v<version>_codebook.csv"),
    Form("ds_*", "CSV", "data/<name>_v<version>.csv"),
    Form("knowledge_entries", "YAML list", "knowledge/entries.yaml"),
    Form("knowledge_entries", "markdown, unchanged", "knowledge/<entry id>.md"),
    Form("knowledge_history", "YAML list", "knowledge/history.yaml"),
    Form("knowledge_history", "markdown, unchanged", "knowledge/history/<entry id>/<n>.md"),
    Form("field_definitions", "YAML list", "schema/field_definitions.yaml"),
    Form("export_registry", "YAML list", "schema/export_registry.yaml"),
)

WRITTEN_OUT = "written_out.yaml"

# The project's source whose AI rationales are written out, relative to the
# project folder, as W's handoffs take it by default.
RATIONALES_SOURCE = "manuscript.md"

# Each file written, by its path in the output folder, its element, and its sha256.
Written = namedtuple("Written", ["path", "element", "sha256"])

# The provenance every written-out record keeps.
_KEPT = ("created_at", "session", "origin", "method", "reason")

# The fields that name another row, written as the session's id, the
# source's citekey, or the dataset version's CSV path.
_REFERENCES = {
    "events": ("session_row_id",),
    "transcripts": ("session_row_id",),
    "source_originals": ("source",),
    "source_texts": ("source",),
    "datasets": ("table_name",),
}

# The kept transcript's extension for a harness that keeps one JSON document
# per session. Every other harness keeps JSON Lines.
_JSON_HARNESSES = ("forgecode",)

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


class WriteOutError(ValueError):
    """A write-out the audit layer refuses."""


def sync_registry(store: Store) -> int:
    """Write each registry form the store lacks or holds with another path, and give the rows written.

    A form not yet stored adds a row. A stored row whose path differs is
    superseded, and the old row stays in the table. A store already in step
    gets nothing new and takes no write lock. Otherwise the reads are made
    again and the writes run in one transaction, as sync_definitions does.
    """
    if not _pending(store):
        return 0
    written = 0
    with writing(store) as write:
        for form, row in _pending(store):
            if row is None:
                write.add("export_registry", form._asdict(), PROVENANCE)
            else:
                write.supersede("export_registry", row["id"], {"path": form.path}, PROVENANCE)
            written += 1
    return written


def _pending(store: Store) -> List[Tuple[Form, Optional[Dict[str, Any]]]]:
    """Each form to write, with its current stored row, or None when none is stored."""
    held = {}  # type: Dict[Tuple[str, str], Dict[str, Any]]
    for row in current(store, "export_registry"):
        held[(row["element"], row["file_form"])] = row
    pending = []
    for form in REGISTRY:
        row = held.get((form.element, form.file_form))
        if row is None or row["path"] != form.path:
            pending.append((form, row))
    return pending


def transcript_path(harness: str, session_id: str) -> str:
    """Where a session's kept transcript is written, relative to the output folder."""
    parts = [_safe_part(part) for part in str(session_id).split("/")]
    suffix = "json" if harness in _JSON_HARNESSES else "jsonl"
    return "audit/transcripts/{}/{}.{}".format(_safe_part(harness), "/".join(parts), suffix)


def write_out_project(
    store: Store,
    project,
    out_dir,
    citekeys: Sequence[str] = (),
    datasets: Sequence[Union[str, Tuple[str, Optional[int]]]] = (),
    knowledge: bool = False,
) -> List[Written]:
    """Write the project's records, and the sources, datasets, and knowledge named, into out_dir.

    It gives each file listed, as written_out.yaml lists them, in the order
    written.
    """
    out = Path(out_dir)
    _check_out(out)
    top = os.path.realpath(str(project))
    planned = []  # type: List[Tuple[str, str, bytes]]

    projects = [row for row in current(store, "projects") if _inside(row["folder"], top)]
    sessions = [row for row in current(store, "sessions") if _inside(row["project"], top)]
    names = {}  # type: Dict[str, str]
    for row in sessions:
        for row_id in _row_ids(store, row):
            names[row_id] = row["harness_session_id"]

    events = []
    for row in sessions:
        events += [_record("events", event, names) for event in session_events(store, row)]
    transcripts = [row for row in current(store, "transcripts") if row["session_row_id"] in names]
    latest = {}  # type: Dict[str, Dict[str, Any]]
    for row in transcripts:
        latest[names[row["session_row_id"]]] = row

    planned.append(("audit/projects.yaml", "projects", _yaml_list("projects", projects, names)))
    planned.append(("audit/sessions.yaml", "sessions", _yaml_list("sessions", sessions, names)))
    planned.append(("audit/events.jsonl", "events", _json_lines(events)))
    planned.append(("audit/transcripts.yaml", "transcripts", _yaml_list("transcripts", transcripts, names)))
    for row in sessions:
        transcript = latest.get(row["harness_session_id"])
        if transcript is None:
            continue
        data = _kept(store, transcript["file_sha256"], f"session {row['harness_session_id']}")
        planned.append((transcript_path(row["harness"], row["harness_session_id"]), "transcripts", data))

    snapshots = [row for row in current(store, "snapshots") if _inside(row["project"], top)]
    working = {}  # type: Dict[str, Dict[str, Any]]
    for row in snapshots:
        full = os.path.join(os.path.realpath(row["project"]), row["path"])
        working[Path(os.path.relpath(full, top)).as_posix()] = row
    planned.append(("audit/snapshots.yaml", "snapshots", _yaml_list("snapshots", snapshots, names)))
    for path in sorted(working):
        data = _kept(store, working[path]["file_sha256"], f"the snapshot of {path}")
        planned.append(("working/" + path, "snapshots", data))

    _plan_records(store, project, planned)

    _plan_sources(store, citekeys, names, planned)
    _plan_datasets(store, datasets, names, planned)
    if knowledge:
        _plan_knowledge(store, names, planned)

    planned.append(
        (
            "schema/field_definitions.yaml",
            "field_definitions",
            _yaml_list("field_definitions", current(store, "field_definitions"), names),
        )
    )
    planned.append(
        (
            "schema/export_registry.yaml",
            "export_registry",
            _yaml_list("export_registry", current(store, "export_registry"), names),
        )
    )

    _check_paths(planned)
    out.mkdir(parents=True, exist_ok=True)
    files = []
    for path, element, data in planned:
        _write_file(out / path, data)
        files.append(Written(path, element, hashlib.sha256(data).hexdigest()))
    listing = {"files": [item._asdict() for item in files]}
    _write_file(out / WRITTEN_OUT, _yaml(listing))
    return files


def _plan_records(store: Store, project, planned) -> None:
    """Plan W's three records for the project, each made by its own writer."""
    source = Path(str(project)) / RATIONALES_SOURCE
    with tempfile.TemporaryDirectory() as scratch:
        folder = Path(scratch)
        for element, path, write in (
            ("citation_log", "audit/citation_log.yaml", lambda out: write_citation_log(store, project, out)),
            (
                "session_writes",
                "audit/session_writes.jsonl",
                lambda out: write_session_writes(session_writes(store, project), out),
            ),
            (
                "rationales",
                "audit/rationales.yaml",
                lambda out: write_rationales(rationales(store, source), out),
            ),
        ):
            out = folder / posixpath.basename(path)
            try:
                write(out)
            except (OSError, ValueError) as error:
                raise WriteOutError(f"could not make the {element} record, {error}, so nothing was written")
            planned.append((path, element, out.read_bytes()))


def _plan_sources(store: Store, citekeys: Sequence[str], names: Dict[str, str], planned) -> None:
    """Plan the sources elements for the citekeys named, refusing one the store lacks."""
    keys = _unique(citekeys)
    if not keys:
        return
    records = []
    originals = []
    texts = []
    files = []  # type: List[Tuple[str, str, bytes]]
    for key in keys:
        rows = current(store, "sources", citekey=key)
        if not rows:
            raise WriteOutError(f"there is no source {key} in the sources store, so nothing was written")
        records += rows
        cursor = store.db.execute("SELECT id FROM sources WHERE citekey = ? ORDER BY rowid", (key,))
        versions = [row[0] for row in cursor.fetchall()]
        for row_id in versions:
            names[row_id] = key
        own = [row for row in current(store, "source_originals") if row["source"] in versions]
        originals += own
        if own:
            data = _kept(store, own[-1]["file_sha256"], f"the original of {key}")
            path = "sources/originals/{}.{}".format(_safe_part(key), _original_suffix(data))
            files.append((path, "source_originals", data))
        own_texts = [row for row in current(store, "source_texts") if row["source"] in versions]
        texts += own_texts
        for row in own_texts:
            path = "sources/texts/{}.{}.txt".format(_safe_part(key), _safe_part(row["kind"]))
            files.append((path, "source_texts", row["text"].encode("utf-8")))
    planned.append(("sources/sources.yaml", "sources", _yaml_list("sources", records, names)))
    planned.append(
        ("sources/originals.yaml", "source_originals", _yaml_list("source_originals", originals, names))
    )
    planned += [item for item in files if item[1] == "source_originals"]
    planned.append(("sources/texts.yaml", "source_texts", _yaml_list("source_texts", texts, names)))
    planned += [item for item in files if item[1] == "source_texts"]


def _plan_datasets(store: Store, datasets, names: Dict[str, str], planned) -> None:
    """Plan the data elements for the dataset versions named, refusing one the store lacks."""
    if not datasets:
        return
    found = []
    seen = set()
    for item in datasets:
        name, version = (item, None) if isinstance(item, str) else item
        try:
            catalog, data, codebook = dataset_files(store, name, version)
        except DataError as error:
            raise WriteOutError(f"{error}, so nothing was written")
        if catalog["id"] in seen:
            continue
        seen.add(catalog["id"])
        stem = "data/{}_v{}".format(_safe_part(catalog["name"]), catalog["version"])
        names[catalog["table_name"]] = stem + ".csv"
        found.append((catalog, stem, data, codebook))
    catalogs = [catalog for catalog, _, _, _ in found]
    planned.append(("data/datasets.yaml", "datasets", _yaml_list("datasets", catalogs, names)))
    for _, stem, data, codebook in found:
        planned.append((stem + ".csv", "ds_*", data))
        planned.append((stem + "_codebook.csv", "codebook", codebook))


def _plan_knowledge(store: Store, names: Dict[str, str], planned) -> None:
    """Plan the knowledge elements, every current entry and every replaced version."""
    entries = current(store, "knowledge_entries")
    held = {row["id"] for row in entries}
    replaced = []
    files = []  # type: List[Tuple[str, str, bytes]]
    for entry in entries:
        part = _safe_part(entry["entry_id"])
        files.append(("knowledge/{}.md".format(part), "knowledge_entries", _content(entry)))
        versions = [row for row in history(store, entry["entry_id"]) if row["id"] not in held]
        for number, row in enumerate(versions, start=1):
            path = "knowledge/history/{}/{}.md".format(part, number)
            files.append((path, "knowledge_history", _content(row)))
        replaced += versions
    planned.append(
        ("knowledge/entries.yaml", "knowledge_entries", _yaml_list("knowledge_entries", entries, names))
    )
    planned += [item for item in files if item[1] == "knowledge_entries"]
    planned.append(
        ("knowledge/history.yaml", "knowledge_history", _yaml_list("knowledge_history", replaced, names))
    )
    planned += [item for item in files if item[1] == "knowledge_history"]


def _original_suffix(data: bytes) -> str:
    """The extension a retrieved original is written with, from its first bytes."""
    if data.startswith(b"%PDF"):
        return "pdf"
    start = data[:15].lower()
    if start.startswith(b"<html") or start.startswith(b"<!doctype html"):
        return "html"
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return "bin"
    return "txt"


def _content(row: Dict[str, Any]) -> bytes:
    return (row["content"] or "").encode("utf-8")


def _unique(items: Sequence[str]) -> List[str]:
    """The items in the order given, each once."""
    seen = []  # type: List[str]
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen


def _check_out(out: Path) -> None:
    """Refuse an output that is not a new or empty folder."""
    if out.exists() and not out.is_dir():
        raise WriteOutError(f"the output {out} is not a folder")
    if out.is_dir() and any(out.iterdir()):
        raise WriteOutError(f"the output folder {out} is not empty, so give a new or empty folder")


def _check_paths(planned: List[Tuple[str, str, bytes]]) -> None:
    """Refuse a path that leaves the output folder or that two files would share."""
    seen = set()
    for path, _, _ in planned:
        normal = posixpath.normpath(path)
        if normal != path or normal.startswith("../") or posixpath.isabs(normal) or normal == WRITTEN_OUT:
            raise WriteOutError(f"the path {path} would not be written inside the output folder")
        if path in seen:
            raise WriteOutError(f"two files would be written at {path}")
        seen.add(path)


def _safe_part(part: str) -> str:
    """A part of a path with every character outside letters, digits, ., -, and _ made _."""
    safe = _UNSAFE.sub("_", part)
    if not safe.strip("."):
        safe = "_" * max(len(safe), 1)
    return safe


def _inside(path: Optional[str], top: str) -> bool:
    """Whether path is the folder top or inside it, compared as real paths. top is a real path."""
    if not path:
        return False
    real = os.path.realpath(path)
    return real == top or real.startswith(top.rstrip(os.sep) + os.sep)


def _row_ids(store: Store, session_row: Dict[str, Any]) -> List[str]:
    """The ids of every row the session has had, current or superseded."""
    cursor = store.db.execute(
        "SELECT id FROM sessions WHERE harness IS ? AND harness_session_id IS ? ORDER BY rowid",
        (session_row["harness"], session_row["harness_session_id"]),
    )
    return [row[0] for row in cursor.fetchall()]


def _record(table: str, row: Dict[str, Any], names: Dict[str, str]) -> Dict[str, Any]:
    """The row as a written-out record, its fields then its provenance, with no row id."""
    record = {name: row[name] for name, _ in TABLES[table]}
    for name in _REFERENCES.get(table, ()):
        if record[name] not in names:
            raise WriteOutError(f"a {table} row names a row not written out")
        record[name] = names[record[name]]
    for name in _KEPT:
        record[name] = row[name]
    return record


def _kept(store: Store, checksum: str, what: str) -> bytes:
    """The bytes the file store keeps under checksum, refused when missing or altered."""
    path = store.files / checksum
    if not path.is_file():
        raise WriteOutError(f"the stored file of {what} is missing, so nothing was written")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != checksum:
        raise WriteOutError(f"the stored file of {what} is altered, so nothing was written")
    return data


def _yaml(value: Any) -> bytes:
    text = yaml.safe_dump(
        value, sort_keys=False, allow_unicode=True, default_flow_style=False, width=4096
    )
    return text.encode("utf-8")


def _yaml_list(table: str, rows: List[Dict[str, Any]], names: Dict[str, str]) -> bytes:
    return _yaml([_record(table, row, names) for row in rows])


def _json_lines(records: List[Dict[str, Any]]) -> bytes:
    text = "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records)
    return text.encode("utf-8")


def _write_file(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
