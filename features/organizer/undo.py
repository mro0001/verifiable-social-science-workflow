"""Undo and the log (step F10).

python3 -m features organize undo DIR ENTRY --by NAME [--home DIR]
python3 -m features organize log DIR

Undo reverses one journal entry when the project is still as that entry
left it. A moved file goes back when the file at its new path still has the
recorded checksum and its old path is free. An archived file gets its
original bytes back from the content store when it still has the bytes the
archive line gave it. A mark needs no file change. In any other state undo
refuses and says what changed, and the bytes of both versions stay in the
content store. Each undo is itself a journal entry, with op undo, the entry
it undoes, and the reversed fields, so nothing is lost (track F choice 16).
There is no redo, since the scholar applies the proposal again after a
fresh scan.

The log prints the journal as a table and then the current marks.
"""
import collections
import datetime
import hashlib
import os
import sys

from features.layers import LayerMissing, run_layer
from features.organizer import journal
from features.organizer.apply import refresh
from features.organizer.inventory import AUDIT_DATABASE, INVENTORY_FILE
from features.setup.system import DEFAULT_HOME, SetupError, features_home, load_system

COMMANDS = ("python3 -m features organize undo", "python3 -m features organize log")
NONE = "-"
LOG_COLUMNS = ("entry", "at", "by", "proposed by", "op", "item", "reason", "undone by")


class UndoError(Exception):
    """An entry that cannot be undone. The message says why, and nothing was changed."""


def _sha256(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def _find(entries, entry_id):
    for entry in entries:
        if entry.get("entry") == entry_id:
            return entry
    return None


def _undo_move(folder, entry):
    path, to, digest = entry.get("path"), entry.get("to"), entry.get("sha256")
    path_full = os.path.join(folder, path)
    to_full = os.path.join(folder, to)
    if not os.path.isfile(to_full):
        raise UndoError("%s is not there any more, so %s cannot be moved back to %s"
                        % (to, entry["entry"], path))
    now_sha = _sha256(to_full)
    if now_sha != digest:
        raise UndoError("%s changed after %s moved it (checksum %s, recorded %s), so it is"
                        " not moved back" % (to, entry["entry"], now_sha, digest))
    if os.path.lexists(path_full):
        raise UndoError("%s exists again, so %s cannot be moved back there" % (path, to))
    os.makedirs(os.path.dirname(path_full), exist_ok=True)
    os.rename(to_full, path_full)
    return collections.OrderedDict([("path", to), ("to", path), ("sha256", digest)])


def _undo_archive_line(folder, entry):
    path = entry.get("path")
    full = os.path.join(folder, path)
    if not os.path.isfile(full):
        raise UndoError("%s is not there any more, so its archive line from %s cannot be"
                        " taken out" % (path, entry["entry"]))
    now_sha = _sha256(full)
    if now_sha != entry.get("after_sha256"):
        raise UndoError("%s changed after %s gave it an archive line (checksum %s, recorded %s),"
                        " so it is left as it is. Both versions stay in .organizer/%s/"
                        % (path, entry["entry"], now_sha, entry.get("after_sha256"),
                           journal.ORIGINALS_DIR))
    original = journal.kept_bytes(folder, entry.get("before_sha256"))
    if original is None:
        raise UndoError("the original bytes of %s (%s) are missing from .organizer/%s/, so"
                        " %s cannot be undone" % (path, entry.get("before_sha256"),
                                                   journal.ORIGINALS_DIR, entry["entry"]))
    with open(full, "wb") as handle:
        handle.write(original)
    return collections.OrderedDict([
        ("path", path),
        ("superseded_by", entry.get("superseded_by")),
        ("line", entry.get("line")),
        ("before_sha256", entry.get("after_sha256")),
        ("after_sha256", entry.get("before_sha256")),
    ])


def _undo_mark(entry):
    return collections.OrderedDict(
        (name, entry.get(name)) for name in ("item_kind", "item", "mark", "value"))


def undo_entry(project_dir, entry_id, by, now, root=None, runner=run_layer, audit_db=None):
    """Undo one journal entry and give the id of the undo entry it appends.

    Refuses, raising UndoError and changing nothing, an unknown entry, an
    entry already undone, an undo entry, and a file not in the state the
    entry left it in. Then rewrites marks.yaml and the inventory.
    """
    if not isinstance(by, str) or not by.strip():
        raise UndoError("--by needs the name of the scholar who undoes the entry")
    by = by.strip()
    folder = os.path.realpath(os.path.abspath(str(project_dir)))
    entries = journal.read_journal(folder)
    if not entries:
        raise UndoError("%s has no journal, so there is nothing to undo"
                        % os.path.join(folder, journal.ORGANIZER_DIR, journal.JOURNAL_FILE))
    entry = _find(entries, entry_id)
    if entry is None:
        raise UndoError("%s is not an entry in the journal, which runs %s to %s"
                        % (entry_id or "an empty name", entries[0]["entry"],
                           entries[-1]["entry"]))
    op = entry.get("op")
    if op == journal.UNDO:
        raise UndoError("%s is itself an undo of %s, and an undo is not undone. Apply the"
                        " proposal again after a fresh scan instead" % (entry_id,
                                                                       entry.get("undoes")))
    undone = journal.undone_by(entries)
    if entry_id in undone:
        raise UndoError("%s is already undone by %s" % (entry_id, undone[entry_id]))
    if op == "move":
        fields = _undo_move(folder, entry)
    elif op == "archive_line":
        fields = _undo_archive_line(folder, entry)
    elif op == "mark":
        fields = _undo_mark(entry)
    else:
        raise UndoError("%s has the op %s, which the organizer cannot undo" % (entry_id, op))
    record = collections.OrderedDict([
        ("by", by),
        ("proposed_by", None),
        ("proposal_sha256", None),
        ("change_id", entry.get("change_id")),
        ("op", journal.UNDO),
        ("reason", "undo of %s" % entry_id),
    ])
    record.update(fields)
    record["undoes"] = entry_id
    new_id = journal.append_entry(folder, record, now)
    refresh(folder, now, root=root, runner=runner, audit_db=audit_db)
    return new_id


# The log.


def _shown(value):
    if value is None or value == "":
        return NONE
    return " ".join(str(value).split())


def item_of(entry):
    """What an entry changed, in a few words."""
    if "to" in entry:
        what = "%s to %s" % (_shown(entry.get("path")), _shown(entry.get("to")))
    elif "before_sha256" in entry:
        what = _shown(entry.get("path"))
    elif "item_kind" in entry:
        what = "%s %s %s" % (_shown(entry.get("item_kind")), _shown(entry.get("item")),
                             _shown(entry.get("mark")))
    else:
        what = NONE
    if entry.get("op") == journal.UNDO:
        return "undoes %s, %s" % (_shown(entry.get("undoes")), what)
    return what


def _mark_line(mark):
    text = "%s %s %s" % (mark["item_kind"], mark["item"], mark["mark"])
    if mark.get("value") is not None:
        text += " %s" % _shown(mark["value"])
    return "%s, entry %s, by %s" % (text, mark["entry"], _shown(mark.get("by")))


def log_text(project_dir):
    """The journal as a table, then the current marks, as text ending in a line break."""
    folder = os.path.realpath(os.path.abspath(str(project_dir)))
    entries = journal.read_journal(folder)
    if not entries:
        return "No journal in %s, so nothing has been applied\n" % os.path.join(
            folder, journal.ORGANIZER_DIR)
    undone = journal.undone_by(entries)
    rows = [list(LOG_COLUMNS)]
    for entry in entries:
        rows.append([_shown(entry.get("entry")), _shown(entry.get("at")), _shown(entry.get("by")),
                     _shown(entry.get("proposed_by")), _shown(entry.get("op")), item_of(entry),
                     _shown(entry.get("reason")), undone.get(entry.get("entry"), NONE)])
    widths = [max(len(row[column]) for row in rows) for column in range(len(LOG_COLUMNS))]
    lines = ["  ".join(cell.ljust(width) for cell, width in zip(row, widths)).rstrip()
             for row in rows]
    lines.append("Marks")
    marks = journal.current_marks(entries)
    for mark in marks:
        lines.append("  " + _mark_line(mark))
    if not marks:
        lines.append("  none")
    return "\n".join(lines) + "\n"


# The commands.


def add_commands(commands):
    parser = commands.add_parser(
        "undo", help="undo one journal entry",
        description="Undo one entry of <DIR>/.organizer/journal.jsonl when the project is still"
        " as that entry left it, and journal the undo.")
    parser.add_argument("dir", metavar="DIR", help="the project folder")
    parser.add_argument("entry", metavar="ENTRY", help="the journal entry, such as j0003")
    parser.add_argument("--by", required=True, metavar="NAME",
                        help="the name of the scholar who undoes the entry")
    parser.add_argument("--home", help="the features home, else FEATURES_HOME, else " + DEFAULT_HOME)
    parser.set_defaults(run=undo_command)
    parser = commands.add_parser(
        "log", help="print the journal and the current marks",
        description="Print <DIR>/.organizer/journal.jsonl as a table, with who ran and who"
        " proposed each change and which entry undid it, then the current marks.")
    parser.add_argument("dir", metavar="DIR", help="the project folder")
    parser.set_defaults(run=log_command)


def undo_command(options, out=None, err=None, now=None):
    out = out or sys.stdout
    err = err or sys.stderr
    now = now or datetime.datetime.now(datetime.timezone.utc)
    folder = os.path.abspath(os.path.expanduser(options.dir))
    try:
        system = load_system(features_home(options.home))
        if not os.path.isdir(folder):
            raise SetupError("%s is not a folder" % folder)
        new_id = undo_entry(folder, options.entry, options.by, now,
                            root=system["workflow_root"],
                            audit_db=os.path.join(system["audit_home"], AUDIT_DATABASE))
    except (UndoError, journal.JournalError, SetupError, LayerMissing) as error:
        err.write("organize undo stopped, %s\n" % error)
        return 1
    entry = journal.read_journal(folder)[-1]
    real = os.path.realpath(folder)
    out.write("%s %s\n" % (new_id, item_of(entry)))
    out.write("Wrote %s\n" % journal.marks_path(real))
    out.write("Wrote %s\n" % os.path.join(real, journal.ORGANIZER_DIR, INVENTORY_FILE))
    return 0


def log_command(options, out=None, err=None):
    out = out or sys.stdout
    err = err or sys.stderr
    folder = os.path.abspath(os.path.expanduser(options.dir))
    if not os.path.isdir(folder):
        err.write("organize log stopped, %s is not a folder\n" % folder)
        return 1
    try:
        out.write(log_text(folder))
    except journal.JournalError as error:
        err.write("organize log stopped, %s\n" % error)
        return 1
    return 0
