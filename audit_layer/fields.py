"""The field definitions, one for every column of every table (Track A, Step A18).

Appendix Table A3's Shared tables row keeps each field's definition,
generation rule, and null behavior, Figure A4 draws the field definitions
among the shared tables, and spec 0.11 has the schema document itself. The
definitions live here in code and are written to the field_definitions table
when the store opens (plan choice 20), so the table stays in step with the
code.

FIELDS holds one FieldDef for every column of every table in store.TABLES.
The spine every row carries (id, created_at, session, origin, method, reason,
and supersedes) is defined once, under the table name *. The data columns of
a dataset's own table, ds_<catalog row id>, are left to that dataset's
codebook rows, and its spine is the spine defined under *. A generation rule
is a short plain phrase naming what writes the field, and the null behavior
says when the field may be empty.

sync_definitions(store) adds a row for each definition not yet stored and
supersedes a stored row whose text differs, and a store already in step gets
nothing new. A table or column added later gets its definition here in the
same step.
"""
from collections import namedtuple
from typing import Any, Dict, List, Optional, Tuple

from audit_layer.store import Store, current, writing

VERSION = 1

# The table name the spine is defined under.
SPINE_TABLE = "*"

PROVENANCE = {
    "session": "none",
    "origin": "audit_layer",
    "method": f"fields {VERSION}",
    "reason": "schema",
}

FieldDef = namedtuple(
    "FieldDef", ["table_name", "field", "definition", "generation_rule", "null_behavior"]
)

_NEVER = "never empty"
_CAPTURE = "capture, from the harness's session file"
_MECHANICAL = "mechanical pass"
_MODEL = "model pass, then a person, by review"
_STORE = "set by the store"
_BIB = "sources add-bib, from the citation manager's BibTeX export"
_ATTACH = "sources attach, from the retrieved file"
_TEXT = "sources text, from the extracted text file"
_DATA = "data add, from the CSV file"
_KNOWLEDGE = "knowledge sync, from the entry file"
_SNAPSHOT = "sweep, from the working file"
_UNTAGGED = (
    "empty until the model pass runs, and empty again when the transcript grows and capture"
    " writes a new row"
)


def _defs(table: str, rows) -> Tuple[FieldDef, ...]:
    return tuple(FieldDef(table, *row) for row in rows)


_KNOWLEDGE_FIELDS = (
    ("entry_id", "The entry's identifier, the id key of its file's heading.", _KNOWLEDGE, _NEVER),
    ("class", "The entry's class, the group key of its file's heading.", _KNOWLEDGE,
     "empty when the heading gives no group"),
    ("title", "The entry's title, the title key of its file's heading.", _KNOWLEDGE, _NEVER),
    ("gist", "The first sentence of the first paragraph after the entry's title line.",
     _KNOWLEDGE, "empty when the entry has no paragraph after its title"),
    ("keywords", "The entry's keywords, a JSON list.", _KNOWLEDGE,
     "never empty, and an empty list, since no route fills it yet"),
    ("content", "The whole entry file, as text.", _KNOWLEDGE, _NEVER),
    ("source_checksum", "The version of the source material, the source_commit key of the"
     " heading.", _KNOWLEDGE, "empty when the heading gives no source_commit"),
)

FIELDS = (
    _defs(SPINE_TABLE, (
        ("id", "The row's own id, unique in its table.",
         "set by the store, or the harness's own id for a tool call", _NEVER),
        ("created_at", "When the row was written, in UTC, as YYYY-MM-DDTHH:MM:SS.ffffffZ.",
         _STORE, _NEVER),
        ("session", "The id of the session the row comes from, or none for a command run"
         " outside a recorded session.", "the program that writes the row", _NEVER),
        ("origin", "What wrote the row, such as an adapter, the model pass, or a person.",
         "the program that writes the row", _NEVER),
        ("method", "How the row was made, with the version of the program that made it.",
         "the program that writes the row", _NEVER),
        ("reason", "Why the row was written.", "the program that writes the row", _NEVER),
        ("supersedes", "The id of the row in the same table that this row corrects or"
         " replaces.", _STORE, "empty on a row that replaces none"),
    ))
    + _defs("sessions", (
        ("harness", "The harness that kept the session, such as claude_code or forgecode.",
         _CAPTURE, _NEVER),
        ("harness_session_id", "The harness's own id for the session. A subagent"
         " conversation's is its parent's id followed by /agent- and its agent id.",
         _CAPTURE, _NEVER),
        ("project", "The folder the session ran in, which names its project.", _CAPTURE,
         _NEVER),
        ("started_at", "The time of the session's first record, as the harness wrote it.",
         _CAPTURE, "empty only when the harness gives no time"),
        ("ended_at", "The time of the session's last record, as the harness wrote it.",
         _CAPTURE, "empty only when the harness gives no time"),
        ("tools", "The tools the session used, each once, in the order first used, as a"
         " JSON list.", _CAPTURE, "never empty, and an empty list when the session used no tool"),
        ("title", "A title of at most 80 characters for the session.", _MODEL, _UNTAGGED),
        ("gist", "One line of at most 200 characters saying what the session did.", _MODEL,
         _UNTAGGED),
        ("summary", "One paragraph of at most 1,200 characters on the session.", _MODEL,
         _UNTAGGED),
        ("keywords", "Three to ten terms for the session, as a JSON list.", _MODEL, _UNTAGGED),
        ("models", "The models that answered in the session, each once, in the order first"
         " seen, as a JSON list.", _CAPTURE,
         "an empty list when the transcript names no model, and empty on a row written before"
         " the field existed until capture writes the session again"),
        ("harness_version", "The harness's version, the first one the transcript gives.",
         _CAPTURE,
         "empty when the transcript gives no version, and on a row written before the field"
         " existed until capture writes the session again"),
    ))
    + _defs("events", (
        ("session_row_id", "The id of the session row current when the event was captured.",
         _CAPTURE, _NEVER),
        ("ordinal", "The tool call's place among the session's tool calls, counted from 1.",
         _CAPTURE, _NEVER),
        ("verb", "What the tool call did, such as searched, edited, wrote, verified,"
         " committed, or ran.", _MECHANICAL, _NEVER),
        ("kind", "The event's kind, action or observation, or decision once the model pass"
         " names it one.", "mechanical pass, then the model pass for a decision", _NEVER),
        ("object", "What the tool call acted on, a file's full path, a pattern, an address, or"
         " a command.", _MECHANICAL, _NEVER),
        ("rationale", "One sentence on why the decision was made.", _MODEL,
         "empty until the model pass names the event a decision"),
        ("role", "What the tool call did to a file, read, edited, or produced.", _MECHANICAL,
         "empty when the tool call names no file"),
    ))
    + _defs("transcripts", (
        ("session_row_id", "The id of the session row current when the transcript was kept.",
         _CAPTURE, _NEVER),
        ("file_sha256", "The sha256 of the session's bytes, kept under it in the file store.",
         _CAPTURE, _NEVER),
        ("byte_size", "The number of bytes kept.", _CAPTURE, _NEVER),
    ))
    + _defs("sources", (
        ("citekey", "The source's citekey in the citation manager.", _BIB, _NEVER),
        ("title", "The source's title.", _BIB, _NEVER),
        ("authors", "The source's authors, as the export writes them.", _BIB,
         "empty when the entry names no author"),
        ("year", "The source's year.", _BIB, "empty when the entry gives no year"),
        ("venue", "The journal or book the source appeared in.", _BIB,
         "empty when the entry names neither"),
        ("identifiers", "The source's ids, a JSON object with doi, openalex, and"
         " semantic_scholar.", _BIB,
         "never empty, and each id is empty text until some route fills it"),
        ("retrieval_status", "Whether the original is kept, not retrieved or retrieved.",
         "sources add-bib, then sources attach", _NEVER),
        ("content_fingerprint", "The sha256 of the title, lower case, letters and digits only,"
         " followed by the year, used to find duplicates.", _BIB, _NEVER),
    ))
    + _defs("source_originals", (
        ("source", "The id of the source record the original belongs to.", _ATTACH, _NEVER),
        ("file_sha256", "The sha256 of the original's bytes, kept under it in the file store.",
         _ATTACH, _NEVER),
        ("byte_size", "The number of bytes kept.", _ATTACH, _NEVER),
        ("retrieval_method", "How the original was retrieved.", _ATTACH, _NEVER),
        ("retrieved_on", "The day the original was retrieved, as YYYY-MM-DD.", _ATTACH, _NEVER),
    ))
    + _defs("source_texts", (
        ("source", "The id of the source record the text was extracted from.", _TEXT, _NEVER),
        ("kind", "The kind of text, abstract, body, fulltext, or references.", _TEXT, _NEVER),
        ("text", "The extracted text.", _TEXT, "empty when the extracted file is empty"),
        ("conversion_method", "How the text was extracted.", _TEXT, _NEVER),
    ))
    + _defs("datasets", (
        ("name", "The dataset's name.", _DATA, _NEVER),
        ("version", "The version of the dataset, counted from 1 for each name.", _DATA, _NEVER),
        ("row_count", "The number of rows the version holds.", _DATA, _NEVER),
        ("file_sha256", "The sha256 of the CSV file as given.", _DATA, _NEVER),
        ("collected_on", "The day the data were collected, as YYYY-MM-DD.", _DATA, _NEVER),
        ("table_name", "The table holding the version's rows, ds_ and the catalog row's id.",
         _DATA, _NEVER),
    ))
    + _defs("codebook", (
        ("dataset", "The id of the catalog row of the dataset version.", _DATA, _NEVER),
        ("variable", "The variable's name, a column of the dataset's table.", _DATA, _NEVER),
        ("type", "The variable's type, INTEGER, REAL, or TEXT, inferred from its values.",
         _DATA, _NEVER),
        ("description", "What the variable holds.",
         "data add, from the codebook file", "empty when the codebook file gives none"),
    ))
    + _defs("knowledge_entries", _KNOWLEDGE_FIELDS)
    + _defs("knowledge_history", _KNOWLEDGE_FIELDS)
    + _defs("snapshots", (
        ("project", "The project folder the snapshot was taken in.", _SNAPSHOT, _NEVER),
        ("path", "The file's path relative to the project folder.", _SNAPSHOT, _NEVER),
        ("kind", "The file's kind, note, script, or draft.", _SNAPSHOT, _NEVER),
        ("file_sha256", "The sha256 of the file's bytes, kept under it in the file store.",
         _SNAPSHOT, _NEVER),
        ("byte_size", "The number of bytes kept.", _SNAPSHOT, _NEVER),
    ))
    + _defs("projects", (
        ("folder", "The folder the project's sessions ran in.",
         "capture, from the first session run in the folder", _NEVER),
        ("name", "The project's name, the folder's last part.",
         "capture, from the first session run in the folder", _NEVER),
    ))
    + _defs("field_definitions", (
        ("table_name", "The table the field belongs to, or * for the spine every row carries.",
         "audit_layer, from fields.py", _NEVER),
        ("field", "The field's name.", "audit_layer, from fields.py", _NEVER),
        ("definition", "What the field holds.", "audit_layer, from fields.py", _NEVER),
        ("generation_rule", "What writes the field.", "audit_layer, from fields.py", _NEVER),
        ("null_behavior", "When the field may be empty.", "audit_layer, from fields.py",
         _NEVER),
    ))
    + _defs("export_registry", (
        ("element", "The element written out, a table's name, or ds_* for the dataset tables.",
         "audit_layer, from writeout.py", _NEVER),
        ("file_form", "The form of the element's file, such as YAML list, JSON Lines, CSV, or"
         " bytes, unchanged.", "audit_layer, from writeout.py", _NEVER),
        ("path", "The file's path in the written-out folder, with each part that varies in"
         " angle brackets.", "audit_layer, from writeout.py", _NEVER),
    ))
)

_TEXTS = ("definition", "generation_rule", "null_behavior")


def sync_definitions(store: Store) -> int:
    """Write each definition the store lacks or holds with other text, and give the rows written.

    A definition not yet stored adds a row. A stored row whose definition,
    generation rule, or null behavior differs is superseded, and the old row
    stays in the table. A store already in step gets nothing new and takes
    no write lock. Otherwise the reads are made again and the writes run in
    one transaction, so two programs opening the store at once write each
    definition once.
    """
    if not _pending(store):
        return 0
    written = 0
    with writing(store) as write:
        for item, row in _pending(store):
            fields = item._asdict()
            if row is None:
                write.add("field_definitions", fields, PROVENANCE)
            else:
                changes = {name: fields[name] for name in _TEXTS}
                write.supersede("field_definitions", row["id"], changes, PROVENANCE)
            written += 1
    return written


def _pending(store: Store) -> List[Tuple[FieldDef, Optional[Dict[str, Any]]]]:
    """Each definition to write, with its current stored row, or None when none is stored."""
    held = {}  # type: Dict[Tuple[str, str], Dict[str, Any]]
    for row in current(store, "field_definitions"):
        held[(row["table_name"], row["field"])] = row
    pending = []
    for item in FIELDS:
        row = held.get((item.table_name, item.field))
        if row is None or any(row[name] != getattr(item, name) for name in _TEXTS):
            pending.append((item, row))
    return pending
