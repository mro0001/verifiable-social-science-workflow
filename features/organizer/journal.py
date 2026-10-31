"""The organizer's journal, its content store, and its marks (step F9).

Every applied change and every undo goes to an append-only journal,
<DIR>/.organizer/journal.jsonl, one JSON object per line, and a line once
written is never changed. The bytes of every file a change rewrites are
kept before and after in the content store, <DIR>/.organizer/originals/,
named by their sha256, kept once and never removed (track F choice 16,
modelled on the audit layer's file store that keeps each file once, A2.4).
Marks on files, builds, and sessions live in <DIR>/.organizer/marks.yaml,
written from the journal, since builds are never edited (A2.3) and audit
records are never overwritten (A2.4).
"""
import collections
import hashlib
import json
import os

import yaml

ORGANIZER_DIR = ".organizer"
JOURNAL_FILE = "journal.jsonl"
ORIGINALS_DIR = "originals"
MARKS_FILE = "marks.yaml"
SCHEMA_VERSION = 1
MARKS_SCHEMA = "organizer-marks"
MARKS_SCHEMA_VERSION = 1
UNDO = "undo"
MARK = "mark"


class JournalError(Exception):
    """A journal that cannot be read line by line as JSON objects."""


def _organizer(project_dir):
    return os.path.join(os.path.abspath(str(project_dir)), ORGANIZER_DIR)


def journal_path(project_dir):
    return os.path.join(_organizer(project_dir), JOURNAL_FILE)


def originals_dir(project_dir):
    return os.path.join(_organizer(project_dir), ORIGINALS_DIR)


def marks_path(project_dir):
    return os.path.join(_organizer(project_dir), MARKS_FILE)


# The content store.


def keep_bytes(project_dir, data):
    """Keep data once in <DIR>/.organizer/originals/<sha256> and give the sha256.

    Content already kept is left as it is. Nothing is ever removed.
    """
    digest = hashlib.sha256(data).hexdigest()
    folder = originals_dir(project_dir)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, digest)
    if os.path.exists(path):
        return digest
    try:
        with open(path, "xb") as handle:
            handle.write(data)
    except FileExistsError:
        pass
    return digest


def kept_bytes(project_dir, digest):
    """The bytes kept under digest, or None when the store lacks them or they do not match it."""
    path = os.path.join(originals_dir(project_dir), str(digest))
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as handle:
        data = handle.read()
    if hashlib.sha256(data).hexdigest() != digest:
        return None
    return data


# The journal.


def read_journal(project_dir):
    """Every journal entry in order, as dicts. A missing journal reads as empty.

    Raises JournalError naming the line when a line is not a JSON object,
    and when the journal does not end with a line break, since its last
    line was then cut short. Apply and undo read the journal before they
    change any file, so such a journal stops them before any change.
    """
    path = journal_path(project_dir)
    if not os.path.isfile(path):
        return []
    if os.path.getsize(path):
        with open(path, "rb") as handle:
            handle.seek(-1, os.SEEK_END)
            if handle.read(1) != b"\n":
                raise JournalError("the journal %s does not end with a line break, so it was"
                                   " cut short" % path)
    found = []
    with open(path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                entry = json.loads(line, object_pairs_hook=collections.OrderedDict)
            except ValueError as error:
                raise JournalError("the journal %s cannot be read at line %d (%s)"
                                   % (path, number, error))
            if not isinstance(entry, dict) or not isinstance(entry.get("entry"), str):
                raise JournalError("the journal %s line %d is not a journal entry"
                                   % (path, number))
            found.append(entry)
    return found


def next_entry_id(entries):
    return "j%04d" % (len(entries) + 1)


def append_entry(project_dir, fields, now):
    """Append one entry to the journal and give its id, j0001, j0002, and so on.

    The entry holds schema_version, entry, and at, then the fields in the
    order given, and undoes (null unless given) last. Earlier lines are
    never touched.
    """
    entries = read_journal(project_dir)
    entry_id = next_entry_id(entries)
    record = collections.OrderedDict([
        ("schema_version", SCHEMA_VERSION),
        ("entry", entry_id),
        ("at", now.isoformat(timespec="seconds")),
    ])
    for name, value in fields.items():
        if name not in ("schema_version", "entry", "at", "undoes"):
            record[name] = value
    record["undoes"] = fields.get("undoes")
    os.makedirs(_organizer(project_dir), exist_ok=True)
    path = journal_path(project_dir)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return entry_id


def undone_by(entries):
    """A mapping of each undone entry's id to the id of the entry that undid it."""
    found = {}
    for entry in entries:
        if entry.get("op") == UNDO and entry.get("undoes"):
            found[entry["undoes"]] = entry["entry"]
    return found


# The marks.


def current_marks(entries):
    """Each mark the journal holds that no later entry undid, in journal order."""
    undone = undone_by(entries)
    marks = []
    for entry in entries:
        if entry.get("op") != MARK or entry["entry"] in undone:
            continue
        marks.append(collections.OrderedDict([
            ("item_kind", entry.get("item_kind")),
            ("item", entry.get("item")),
            ("mark", entry.get("mark")),
            ("value", entry.get("value")),
            ("reason", entry.get("reason")),
            ("entry", entry["entry"]),
            ("by", entry.get("by")),
            ("proposed_by", entry.get("proposed_by")),
        ]))
    return marks


def write_marks(project_dir):
    """Write <DIR>/.organizer/marks.yaml from the journal and give its path."""
    marks = [dict(mark) for mark in current_marks(read_journal(project_dir))]
    record = {"schema": MARKS_SCHEMA, "schema_version": MARKS_SCHEMA_VERSION, "marks": marks}
    os.makedirs(_organizer(project_dir), exist_ok=True)
    path = marks_path(project_dir)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("# The organizer's marks, written from journal.jsonl. Do not edit.\n")
        handle.write(yaml.safe_dump(record, sort_keys=False, allow_unicode=True))
    return path
