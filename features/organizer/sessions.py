"""Builds and sessions for the organizer's inventory (step F7).

read_builds reads each product's ledger, BUILDS.md, by its header row, so
the seven-column ledger and the nine-column one with verification and runs
both read, and checks each ledgered file against its row. It writes nothing.

read_sessions reads the audit layer's database, opened read only, and only
its sessions and events tables. It never opens the transcripts table or the
file store. This is the one function that reads session records (track F
choice 18, reconciliation item 4), so the authors can replace it with a handoff
copy once a project's session records are written out as files.
"""
import collections
import hashlib
import json
import os
import pathlib
import re
import sqlite3

LEDGER_NAME = "BUILDS.md"
# A build file ospipe numbers, vNNN.docx or vNNN.html, with nothing after the number.
BUILD_FILE = re.compile(r"^(v\d{3,})\.(docx|html)$")
BUILD_EXTENSIONS = (".docx", ".html")
_SEPARATOR_CELL = re.compile(r"^:?-{3,}:?$")
NOT_RECORDED = "-"

# The columns read, as the slice's audit_layer/store.py names them and as
# PRAGMA table_info shows them on a store made by audit_layer init.
# session_row_id is the events column that holds the session row's id.
SESSION_COLUMNS = ("id", "harness", "harness_session_id", "project", "started_at", "ended_at",
                   "tools", "supersedes")
EVENT_COLUMNS = ("id", "session_row_id", "ordinal", "verb", "object", "role", "supersedes")
# The event roles that change a file.
CHANGING_ROLES = ("produced", "edited")


# Builds.


def _relative(path):
    return os.path.normpath(str(path)).replace(os.sep, "/")


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cells(line):
    line = line.strip()
    if len(line) < 2 or not (line.startswith("|") and line.endswith("|")):
        return None
    return [cell.strip() for cell in line[1:-1].split("|")]


def _ledger_rows(path, where, problems):
    """The ledger's rows as mappings from header name to cell, in file order."""
    with open(path, encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    header = None
    rows = []
    for number, line in enumerate(lines, start=1):
        cells = _cells(line)
        if cells is None:
            continue
        if header is None:
            header = [cell.lower() for cell in cells]
            continue
        if all(_SEPARATOR_CELL.match(cell) for cell in cells):
            continue
        if len(cells) != len(header):
            problems.append("%s line %d has %d cells where its header has %d"
                            % (where, number, len(cells), len(header)))
            continue
        rows.append(dict(zip(header, cells)))
    return rows


def _product_folders(project_map):
    found = []
    for product in project_map.products:
        name = product.get("name")
        builds = product.get("builds_dir")
        if name and builds:
            pair = (str(name), _relative(builds).rstrip("/"))
            if pair not in found:
                found.append(pair)
    return found


def read_builds(project_dir, project_map):
    """(builds, problems) for every product's builds folder in the map.

    Each build is a mapping with item (<product>/<version>), product,
    version, date, sha256, purpose, verification and runs (or - when the
    ledger has no such column), file (the build file's path relative to DIR,
    or None when there is none), and file_ok (the file's checksum matches its
    row). A ledgered file that is missing or changed, and a vNNN.docx or
    vNNN.html file with no row, are problems.
    """
    folder = os.path.abspath(str(project_dir))
    builds, problems = [], []
    for product, relative in _product_folders(project_map):
        builds_dir = os.path.join(folder, relative)
        if not os.path.isdir(builds_dir):
            continue
        ledger = os.path.join(builds_dir, LEDGER_NAME)
        where = "%s/%s" % (relative, LEDGER_NAME)
        rows = []
        if os.path.isfile(ledger):
            try:
                rows = _ledger_rows(ledger, where, problems)
            except (OSError, UnicodeDecodeError) as error:
                problems.append("%s cannot be read (%s)" % (where, error))
        ledgered = set()
        for row in rows:
            version = row.get("version", "")
            item = "%s/%s" % (product, version)
            ledgered.add(version)
            present = [version + extension for extension in BUILD_EXTENSIONS
                       if version and os.path.isfile(os.path.join(builds_dir, version + extension))]
            file_name, file_ok = None, False
            if not present:
                problems.append("%s is ledgered but its file %s.docx or %s.html is missing"
                                % (item, version, version))
            elif len(present) > 1:
                problems.append("%s has both %s, so the ledger cannot say which was built"
                                % (item, " and ".join(present)))
            else:
                file_name = "%s/%s" % (relative, present[0])
                file_ok = _sha256(os.path.join(builds_dir, present[0])) == row.get("sha256")
                if not file_ok:
                    problems.append("%s changed after it was built, %s no longer matches its row"
                                    % (item, file_name))
            builds.append(collections.OrderedDict([
                ("item", item),
                ("product", product),
                ("version", version),
                ("date", row.get("date", NOT_RECORDED)),
                ("sha256", row.get("sha256", NOT_RECORDED)),
                ("purpose", row.get("purpose", NOT_RECORDED)),
                ("verification", row.get("verification", NOT_RECORDED)),
                ("runs", row.get("runs", NOT_RECORDED)),
                ("file", file_name),
                ("file_ok", file_ok),
            ]))
        for name in sorted(os.listdir(builds_dir)):
            match = BUILD_FILE.match(name)
            if match and match.group(1) not in ledgered:
                problems.append("%s/%s has no row in %s" % (relative, name, where))
    return [dict(build) for build in builds], problems


# Sessions.


def connect_read_only(audit_db):
    """A connection to the audit database that can only read.

    The path is written into the URI escaped, so a '#', '?', '%', or space in
    the audit home's name cannot drop mode=ro or open another file.
    """
    path = os.path.abspath(str(audit_db))
    return sqlite3.connect(pathlib.Path(path).as_uri() + "?mode=ro", uri=True)


def _real(path):
    return os.path.realpath(os.path.abspath(str(path)))


def _inside(path, folder):
    return path == folder or path.startswith(folder.rstrip(os.sep) + os.sep)


def _tools(value):
    try:
        tools = json.loads(value) if value else []
    except ValueError:
        return []
    return [str(tool) for tool in tools] if isinstance(tools, list) else []


def _rows(connection, table, columns):
    cursor = connection.execute("SELECT %s FROM %s ORDER BY rowid" % (", ".join(columns), table))
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _current(rows):
    replaced = set(row["supersedes"] for row in rows if row["supersedes"])
    return [row for row in rows if row["id"] not in replaced]


def read_sessions(audit_db, project_dir):
    """The sessions that ran in DIR or produced or edited a file inside it.

    A session's current row (one no later row supersedes) gives its project.
    A session whose project is DIR or inside it has ran_here true. A session
    elsewhere is listed when an event of any of its rows produced or edited a
    file inside DIR. Each is a mapping with harness, harness_session_id,
    ran_here, started_at, ended_at, tools, and files, each file a mapping of
    path (relative to DIR), role, verb, and present. Paths are compared as
    real paths. A missing database gives an empty list.
    """
    path = os.path.abspath(str(audit_db))
    if not os.path.isfile(path):
        return []
    project = _real(project_dir)
    connection = connect_read_only(path)
    try:
        session_rows = _rows(connection, "sessions", SESSION_COLUMNS)
        event_rows = _current(_rows(connection, "events", EVENT_COLUMNS))
    finally:
        connection.close()

    keys = collections.OrderedDict()
    row_key = {}
    for row in session_rows:
        key = (row["harness"], row["harness_session_id"])
        keys.setdefault(key, [])
        keys[key].append(row)
        row_key[row["id"]] = key
    events = collections.defaultdict(list)
    for event in event_rows:
        key = row_key.get(event["session_row_id"])
        if key is not None:
            events[key].append(event)

    found = []
    for key, rows in keys.items():
        current = _current(rows)
        if not current:
            continue
        latest = current[-1]
        ran_here = bool(latest["project"]) and _inside(_real(latest["project"]), project)
        files = collections.OrderedDict()
        position = dict((row["id"], number) for number, row in enumerate(rows))
        row_project = dict((row["id"], row["project"]) for row in rows)
        ordered = sorted(events.get(key, []), key=lambda event: (
            position[event["session_row_id"]], event["ordinal"] or 0))
        for event in ordered:
            if event["role"] not in CHANGING_ROLES or not event["object"]:
                continue
            target = event["object"]
            if not os.path.isabs(target):
                # A relative path is relative to the project of the event's own session row.
                base = row_project.get(event["session_row_id"])
                if not base:
                    continue
                target = os.path.join(base, target)
            real = _real(target)
            if real == project or not _inside(real, project):
                continue
            relative = _relative(os.path.relpath(real, project))
            if relative not in files:
                files[relative] = collections.OrderedDict([
                    ("path", relative),
                    ("role", event["role"]),
                    ("verb", event["verb"]),
                    ("present", os.path.isfile(real)),
                ])
        if not ran_here and not files:
            continue
        found.append(collections.OrderedDict([
            ("harness", key[0]),
            ("harness_session_id", key[1]),
            ("ran_here", ran_here),
            ("started_at", latest["started_at"]),
            ("ended_at", latest["ended_at"]),
            ("tools", _tools(latest["tools"])),
            ("files", [dict(files[name]) for name in sorted(files)]),
        ]))
    return [dict(item) for item in found]
