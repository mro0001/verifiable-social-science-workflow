"""The organizer's inventory of files and the project map (step F6).

python3 -m features organize scan DIR [--home DIR]

The scan lists every file of a project with its size, checksum, and kind, so
the scholar's AI session can read the project before it proposes changes.
The map of products comes from ospipe products --json, run through the layer
runner (reconciliation, Track F), since ospipe's layout module is the one
place the build file's format lives. The rules for look-alikes and archive
lines follow ospipe's layout contract and the build procedure's map reader,
which this file reads and never imports. author_draft.md is protected and
never a look-alike, because the references and prose procedures read it.

By the reconciliation (item 3), the scan refuses and prunes no folder for
being excluded and reads no audit settings. It writes only
<DIR>/.organizer/inventory.json and changes no project file.

Step F7 adds each product's builds and the sessions that ran in the project
or changed its files, read by sessions.py. The scan reads the audit
database read only, at the audit home system.yaml records (reconciliation
item 4).
"""
import collections
import datetime
import hashlib
import json
import os
import re
import sqlite3
import sys

import yaml

from features.layers import LayerMissing, run_layer
from features.organizer.sessions import read_builds, read_sessions
from features.setup.system import DEFAULT_HOME, SetupError, features_home, load_system

SCHEMA = "organizer-inventory"
SCHEMA_VERSION = 1
COMMAND = "python3 -m features organize scan"
ORGANIZER_DIR = ".organizer"
INVENTORY_FILE = "inventory.json"
AUDIT_DATABASE = "audit.sqlite"
MAKEFILE = "Makefile"

KINDS = ("canonical", "verification", "build_input", "declared", "archived", "lookalike",
         "notes", "other")
PROTECTED_KINDS = ("canonical", "verification", "build_input", "declared")
BUILD_INPUTS = ("Makefile", "numbers.yml", "refs.bib", "pipeline.yaml", "params.yaml",
                "acquisition.yaml")
# The product fields whose files the build reads besides the source.
REFERENCED_FIELDS = ("manifest", "bib", "csl", "reference_doc")
# Skipped by name in any folder, and at the project's top only.
SKIPPED_ANYWHERE = (".git", "__pycache__")
SKIPPED_AT_TOP = (ORGANIZER_DIR, "ship")
VERIFICATION_DIR = "verification"
NOTES_DIR = "notes"
# Read by the references and prose procedures, so protected and never a look-alike.
AUTHOR_DRAFT = "author_draft.md"
ARCHIVE_MARK = "> ARCHIVE"

ProjectMap = collections.namedtuple("ProjectMap", "products referenced problems")
FileEntry = collections.namedtuple(
    "FileEntry", "path size sha256 kind claims archive_line protected")

_SPACES = re.compile(r"\s+")


# The project map.


def _relative(path):
    return os.path.normpath(str(path)).replace(os.sep, "/")


def read_map(project_dir, root=None, runner=run_layer):
    """ProjectMap(products, referenced, problems) from ospipe products --json in DIR.

    products are the mappings ospipe gives, with paths relative to DIR.
    referenced holds the files each product names after --manifest, --bib,
    --csl, and --reference-doc. A missing Makefile, a problem ospipe finds,
    and output that is not the JSON ospipe writes are each a problem.
    """
    folder = os.path.abspath(str(project_dir))
    if not os.path.isfile(os.path.join(folder, MAKEFILE)):
        return ProjectMap([], [], ["there is no build file, %s is absent" % MAKEFILE])
    done = runner("ospipe", ["products", "--json"], root=root, cwd=folder)
    try:
        found = json.loads(done.stdout)
        products = [dict(item) for item in found["products"]]
        problems = [str(problem) for problem in found["problems"]]
    except (ValueError, TypeError, KeyError):
        text = (done.stderr or done.stdout).strip()
        return ProjectMap([], [], ["ospipe products failed with exit %d. %s"
                                   % (done.returncode, text)])
    if done.returncode != 0 and not problems:
        problems.append("ospipe products exited %d" % done.returncode)
    referenced = []
    for product in products:
        for field in REFERENCED_FIELDS:
            value = product.get(field)
            if value and _relative(value) not in referenced:
                referenced.append(_relative(value))
    return ProjectMap(products, sorted(referenced), problems)


def _sources(project_map):
    found = []
    for product in project_map.products:
        source = product.get("source")
        if source and _relative(source) not in found:
            found.append(_relative(source))
    return found


def _builds_dirs(project_map):
    found = []
    for product in project_map.products:
        builds = product.get("builds_dir")
        if builds:
            found.append(_relative(builds).rstrip("/"))
    return found


# The files a pipeline, the acquisition record, and the numbers file declare.


def _load_yaml(path, messages):
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as error:
        messages.append("%s cannot be read, so the files it declares are not known (%s)"
                        % (os.path.basename(path), str(error).splitlines()[0]))
        return None


def _names(value):
    """The file names in a list, or a single name, as relative paths."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [_relative(item) for item in value if isinstance(item, str) and item.strip()]


def _declared(project_dir, messages):
    folder = os.path.abspath(str(project_dir))
    declared = set()
    pipeline = _load_yaml(os.path.join(folder, "pipeline.yaml"), messages)
    if isinstance(pipeline, dict):
        declared.update(_names(pipeline.get("helpers")))
        steps = pipeline.get("steps")
        for step in steps if isinstance(steps, list) else []:
            if isinstance(step, dict):
                declared.update(_names(step.get("script")))
                declared.update(_names(step.get("inputs")))
                declared.update(_names(step.get("outputs")))
    acquisition = _load_yaml(os.path.join(folder, "acquisition.yaml"), messages)
    if isinstance(acquisition, dict):
        raw = acquisition.get("raw")
        for item in raw if isinstance(raw, list) else []:
            if isinstance(item, dict):
                declared.update(_names(item.get("file")))
    numbers = _load_yaml(os.path.join(folder, "numbers.yml"), messages)
    if isinstance(numbers, dict):
        entries = numbers.get("numbers") if isinstance(numbers.get("numbers"), dict) else numbers
        for entry in entries.values():
            if isinstance(entry, dict):
                declared.update(_names(entry.get("from")))
    return declared


def read_declared(project_dir):
    """The files pipeline.yaml, acquisition.yaml, and numbers.yml name, as relative paths."""
    return _declared(project_dir, [])


# Titles and archive lines, by the rules of ospipe's layout contract.


def _front_matter_end(text):
    lines = text.splitlines(True)
    if not lines or lines[0].rstrip("\r\n").rstrip() != "---":
        return None
    offset = len(lines[0])
    for line in lines[1:]:
        offset += len(line)
        if line.rstrip("\r\n").rstrip() in ("---", "..."):
            return offset
    return None


def _split(text):
    end = _front_matter_end(text)
    if end is None:
        return "", text
    return text[:end], text[end:]


def _normal(title):
    return _SPACES.sub(" ", title).strip().lower()


def title_of(text):
    """The front matter's title, else the first '# ' heading, in lower case with spaces collapsed."""
    front, body = _split(text)
    if front:
        try:
            data = yaml.safe_load("\n".join(front.splitlines()[1:-1]))
        except yaml.YAMLError:
            data = None
        if isinstance(data, dict) and isinstance(data.get("title"), str) and data["title"].strip():
            return _normal(data["title"])
    for line in body.splitlines():
        if line.startswith("# "):
            return _normal(line[2:])
    return ""


def archive_line_of(text):
    """The first non-empty line after any front matter when it starts with '> ARCHIVE', else None."""
    _, body = _split(text)
    for line in body.splitlines():
        if line.strip():
            return line.strip() if line.strip().startswith(ARCHIVE_MARK) else None
    return None


# The files.


def _inside(relative, folder):
    return relative == folder or relative.startswith(folder + "/")


def _walk(folder, skipped_dirs):
    """Each file's path relative to folder, in order, leaving out the skipped folders."""
    found = []
    for here, dirs, files in os.walk(folder):
        top = os.path.relpath(here, folder)
        kept = []
        for name in sorted(dirs):
            relative = name if top == "." else _relative(os.path.join(top, name))
            if name in SKIPPED_ANYWHERE or (top == "." and name in SKIPPED_AT_TOP):
                continue
            if any(_inside(relative, builds) for builds in skipped_dirs):
                continue
            kept.append(name)
        dirs[:] = kept
        for name in files:
            found.append(name if top == "." else _relative(os.path.join(top, name)))
    return sorted(found)


def _scan(project_dir, project_map, declared, messages):
    folder = os.path.abspath(str(project_dir))
    sources = _sources(project_map)
    referenced = set(project_map.referenced)
    titles, stems = [], []
    for source in sources:
        path = os.path.join(folder, source)
        if os.path.isfile(path):
            with open(path, "rb") as handle:
                title = title_of(handle.read().decode("utf-8", "replace"))
            if title:
                titles.append((title, source))
        stem = os.path.splitext(os.path.basename(source))[0].lower()
        if stem:
            stems.append((stem, source))

    entries = []
    for relative in _walk(folder, _builds_dirs(project_map)):
        path = os.path.join(folder, relative)
        if os.path.islink(path) and not os.path.exists(path):
            messages.append("%s was skipped, it is a link to nothing" % relative)
            continue
        try:
            with open(path, "rb") as handle:
                data = handle.read()
        except OSError as error:
            messages.append("%s was skipped, it cannot be read (%s)" % (relative, error.strerror))
            continue
        name = os.path.basename(relative)
        markdown = name.lower().endswith(".md")
        line, claims = None, None
        if markdown:
            text = data.decode("utf-8", "replace")
            line = archive_line_of(text)
            if relative not in sources and name != AUTHOR_DRAFT:
                title = title_of(text)
                for source_title, source in titles:
                    if title and title == source_title:
                        claims = source
                        break
                if claims is None:
                    for stem, source in stems:
                        if stem in name.lower():
                            claims = source
                            break
        if relative in sources:
            kind = "canonical"
        elif _inside(relative, VERIFICATION_DIR):
            kind = "verification"
        elif relative in BUILD_INPUTS or relative in referenced:
            kind = "build_input"
        elif relative in declared:
            kind = "declared"
        elif line is not None:
            kind = "archived"
        elif claims is not None:
            kind = "lookalike"
        elif _inside(relative, NOTES_DIR):
            kind = "notes"
        else:
            kind = "other"
        if kind not in ("archived", "lookalike"):
            claims = None
        protected = kind in PROTECTED_KINDS or name == AUTHOR_DRAFT
        entries.append(FileEntry(relative, len(data), hashlib.sha256(data).hexdigest(), kind,
                                 claims, line, protected))
    return entries


def scan_files(project_dir, project_map, declared):
    """A FileEntry for each file of the project, in path order.

    The walk leaves out .git/ and __pycache__/ in any folder, .organizer/ and
    ship/ at the top, and each product's builds folder. A link that leads to
    nothing is left out.
    """
    return _scan(project_dir, project_map, declared, [])


# The inventory.


def inventory_id(files, builds=(), sessions=()):
    """The sha256 of the files' paths, sizes, checksums, and kinds, the build rows, and the session ids.

    It holds no times or absolute paths, so an unchanged project gives the
    same id wherever it lies.
    """
    rows = {
        "files": [[entry["path"], entry["size"], entry["sha256"], entry["kind"]]
                  for entry in files],
        "builds": [[build[name] for name in ("item", "date", "sha256", "purpose", "verification",
                                             "runs", "file", "file_ok")] for build in builds],
        "sessions": sorted([item["harness"], item["harness_session_id"]] for item in sessions),
    }
    text = json.dumps(rows, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sessions_of(audit_db, folder, messages):
    if audit_db is None:
        return []
    path = os.path.abspath(os.path.expanduser(str(audit_db)))
    if not os.path.isfile(path):
        messages.append("no sessions are listed, the audit database %s does not exist" % path)
        return []
    try:
        return read_sessions(path, folder)
    except sqlite3.Error as error:
        messages.append("no sessions are listed, the audit database %s cannot be read (%s)"
                        % (path, error))
        return []


def build_inventory(project_dir, now, root=None, runner=run_layer, audit_db=None):
    """The inventory record of one project, as a dict in the order the record keeps.

    audit_db is the audit layer's database file, read only. When it is None
    no sessions are read.
    """
    folder = os.path.realpath(os.path.abspath(str(project_dir)))
    messages = []
    project_map = read_map(folder, root=root, runner=runner)
    declared = _declared(folder, messages)
    files = [dict(entry._asdict()) for entry in _scan(folder, project_map, declared, messages)]
    builds, build_problems = read_builds(folder, project_map)
    sessions = _sessions_of(audit_db, folder, messages)
    for entry in files:
        entry["sessions"] = [item["harness_session_id"] for item in sessions
                             if any(changed["path"] == entry["path"] for changed in item["files"])]
    record = collections.OrderedDict([
        ("schema", SCHEMA),
        ("schema_version", SCHEMA_VERSION),
        ("inventory_id", inventory_id(files, builds, sessions)),
        ("project", folder),
        ("scanned_at", now.isoformat(timespec="seconds")),
        ("map", collections.OrderedDict([
            ("products", project_map.products),
            ("referenced", project_map.referenced),
            ("problems", project_map.problems),
        ])),
        ("files", files),
        ("builds", builds),
        ("build_problems", build_problems),
        ("sessions", sessions),
        ("messages", messages),
    ])
    return json.loads(json.dumps(record))


def write_inventory(project_dir, record):
    """Write the record to <DIR>/.organizer/inventory.json and give its path."""
    folder = os.path.join(os.path.abspath(str(project_dir)), ORGANIZER_DIR)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, INVENTORY_FILE)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    return path


# The command.


def add_command(commands):
    parser = commands.add_parser(
        "scan", help="list a project's files with their kinds",
        description="Write the organizer's inventory of a project's files to"
        " <DIR>/.organizer/inventory.json, changing no project file.")
    parser.add_argument("dir", metavar="DIR", help="the project folder")
    parser.add_argument("--home", help="the features home, else FEATURES_HOME, else " + DEFAULT_HOME)
    parser.set_defaults(run=command)


def _report(record, path, out):
    out.write("Inventory of %s\n" % record["project"])
    counts = collections.Counter(entry["kind"] for entry in record["files"])
    out.write("Files by kind\n")
    for kind in KINDS:
        out.write("  %s %d\n" % (kind, counts.get(kind, 0)))
    lookalikes = [entry for entry in record["files"] if entry["kind"] == "lookalike"]
    out.write("Look-alikes with no archive line\n")
    for entry in lookalikes:
        out.write("  %s reads as %s\n" % (entry["path"], entry["claims"]))
    if not lookalikes:
        out.write("  none\n")
    if record["map"]["problems"]:
        out.write("Problems in the build file\n")
        for problem in record["map"]["problems"]:
            out.write("  %s\n" % problem)
    out.write("Builds %d\n" % len(record["builds"]))
    if record["build_problems"]:
        out.write("Problems in the builds\n")
        for problem in record["build_problems"]:
            out.write("  %s\n" % problem)
    out.write("Sessions %d\n" % len(record["sessions"]))
    for item in record["sessions"]:
        out.write("  %s %s, %s\n" % (item["harness"], item["harness_session_id"],
                                     "ran here" if item["ran_here"] else "ran elsewhere"))
    for message in record["messages"]:
        out.write(message[:1].upper() + message[1:] + "\n")
    out.write("Wrote %s, inventory %s\n" % (path, record["inventory_id"]))


def command(options, out=None, err=None):
    out = out or sys.stdout
    err = err or sys.stderr
    folder = os.path.abspath(os.path.expanduser(options.dir))
    try:
        system = load_system(features_home(options.home))
        if not os.path.isdir(folder):
            raise SetupError("%s is not a folder" % folder)
        record = build_inventory(folder, datetime.datetime.now(datetime.timezone.utc),
                                 root=system["workflow_root"],
                                 audit_db=os.path.join(system["audit_home"], AUDIT_DATABASE))
    except (SetupError, LayerMissing) as error:
        err.write("organize scan stopped, %s\n" % error)
        return 1
    path = write_inventory(folder, record)
    _report(record, path, out)
    return 0
