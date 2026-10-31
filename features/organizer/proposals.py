"""Proposals and their check (step F8).

python3 -m features organize check DIR PROPOSAL [--home DIR]

A proposal is a YAML file the scholar's AI session writes after it reads
the inventory (track F choice 13). It names the inventory it was written
from and lists changes in the organizer's fixed vocabulary, which has three
operations, move, archive_line, and mark, and no way to delete (track F
choice 14, appendix A2.7 and the note to Table A8, appendix only, serving
the proposal's reversible changes). A move never touches a protected file
or a build, and never lands in a builds folder, verification/, .git/, or
.organizer/, matched in any case since folder names on macOS ignore case.
Changes apply in order, so a file is moved once, a move never lands in or
over another move's target, and an archive line never names a file an
earlier change moved away. Builds and sessions are only marked, since builds are never
edited (A2.3) and audit records are never overwritten (A2.4).

The check rescans the project in memory and refuses a proposal written
from an inventory that differs from the fresh one, since the project
changed after the AI read it (track F choice 17). It changes nothing.

By the reconciliation (item 3) the check refuses no move for its target
lying in an excluded folder and reads no audit settings.
"""
import collections
import datetime
import os
import re
import sys

import yaml

from features.layers import LayerMissing
from features.organizer.inventory import (AUDIT_DATABASE, ORGANIZER_DIR, VERIFICATION_DIR,
                                          build_inventory)
from features.setup.system import DEFAULT_HOME, SetupError, features_home, load_system

SCHEMA = "organizer-proposal"
SCHEMA_VERSION = 1
COMMAND = "python3 -m features organize check"

OPERATIONS = ("move", "archive_line", "mark")
DELETING = ("delete", "remove", "rm", "unlink", "overwrite")
NEVER_DELETES = "the organizer never deletes, so mark the item unused instead"
ITEM_KINDS = ("file", "build", "session")
MARKS = ("unused", "superseded", "belongs_to", "note")
GIT_DIR = ".git"

Problem = collections.namedtuple("Problem", "change_id rule message")

_SPACES = re.compile(r"\s+")


class ProposalError(Exception):
    """A proposal file that cannot be read as a YAML mapping."""


def load_proposal(path):
    """The proposal in the YAML file at path, as a dict. Raises ProposalError naming the file."""
    path = os.path.abspath(os.path.expanduser(str(path)))
    try:
        with open(path, encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except OSError as error:
        raise ProposalError("the proposal %s cannot be read (%s)" % (path, error.strerror))
    except (UnicodeDecodeError, yaml.YAMLError) as error:
        raise ProposalError("the proposal %s is not readable YAML (%s)"
                            % (path, str(error).splitlines()[0]))
    if not isinstance(data, dict):
        raise ProposalError("the proposal %s is not a mapping of fields" % path)
    return data


# Small readers.


def _text(value):
    """value as a stripped string, or '' when it is not a non-empty string."""
    if isinstance(value, str):
        return value.strip()
    return ""


def _relative(path):
    return os.path.normpath(path).replace(os.sep, "/")


def _inside(relative, folder):
    """Whether relative is folder or lies under it, ignoring case.

    Folder names on macOS ignore case, so Builds/ and builds/ are one folder
    there, and a kept-out folder is matched in any case.
    """
    relative = relative.casefold()
    folder = folder.casefold()
    return relative == folder or relative.startswith(folder + "/")


def _canonicals(record):
    found = []
    for product in record["map"]["products"]:
        source = product.get("source")
        if isinstance(source, str) and source:
            found.append(_relative(source))
    return found


def _kept_out(record):
    """The folders a move never lands in, relative to the project, with their names."""
    folders = [(ORGANIZER_DIR, ORGANIZER_DIR + "/"), (VERIFICATION_DIR, VERIFICATION_DIR + "/")]
    for product in record["map"]["products"]:
        for field, label in (("builds_dir", "the builds folder %s"),
                             ("verification_dir", "the verification folder %s")):
            value = product.get(field)
            if isinstance(value, str) and value.strip():
                folder = _relative(value).rstrip("/")
                folders.append((folder, label % (folder + "/")))
    return folders


# The check of each operation.


def _check_move(change, folder, record, files, targets, moved, problems):
    change_id = change.get("id")
    path = _text(change.get("path"))
    to = _text(change.get("to"))
    if not path:
        problems.append(Problem(change_id, "move", "a move needs the path of the file to move"))
    else:
        entry = files.get(_relative(path))
        if entry is None:
            problems.append(Problem(change_id, "move",
                                    "%s is not a file in the inventory" % path))
        elif entry["protected"]:
            problems.append(Problem(change_id, "move",
                                    "%s is protected as %s and is never moved"
                                    % (path, entry["kind"])))
        elif entry["path"] in moved:
            problems.append(Problem(change_id, "move", "%s is already moved by change %s"
                                    % (path, moved[entry["path"]])))
        else:
            moved[entry["path"]] = change_id
    if not to:
        problems.append(Problem(change_id, "move", "a move needs the path to move the file to"))
        return
    real_folder = os.path.realpath(folder)
    given = to if os.path.isabs(to) else os.path.join(folder, to)
    target = os.path.realpath(os.path.normpath(given))
    if not target.startswith(real_folder + os.sep):
        problems.append(Problem(change_id, "move", "%s lies outside the project" % to))
        return
    relative = _relative(os.path.relpath(target, real_folder))
    for kept, name in _kept_out(record):
        if _inside(relative, kept):
            problems.append(Problem(change_id, "move",
                                    "%s lies in %s, where the organizer moves nothing"
                                    % (to, name)))
            return
    if GIT_DIR in relative.casefold().split("/"):
        problems.append(Problem(change_id, "move",
                                "%s lies in a %s/ folder, where the organizer moves nothing"
                                % (to, GIT_DIR)))
        return
    if os.path.lexists(os.path.normpath(given)) or os.path.lexists(target):
        problems.append(Problem(change_id, "move", "%s exists already" % to))
        return
    parent = os.path.dirname(target)
    while parent.startswith(real_folder + os.sep):
        if os.path.lexists(parent) and not os.path.isdir(parent):
            problems.append(Problem(change_id, "move",
                                    "%s cannot be made, %s is a file"
                                    % (to, _relative(os.path.relpath(parent, real_folder)))))
            return
        parent = os.path.dirname(parent)
    for earlier, earlier_id in targets.items():
        if relative.casefold() == earlier.casefold():
            message = "%s is already the target of change %s" % (to, earlier_id)
        elif _inside(relative, earlier):
            message = "%s lies under %s, the file change %s moves there" % (to, earlier, earlier_id)
        elif _inside(earlier, relative):
            message = ("%s would be a file above %s, where change %s moves a file"
                       % (to, earlier, earlier_id))
        else:
            continue
        problems.append(Problem(change_id, "move", message))
        return
    targets[relative] = change_id


def _check_archive_line(change, record, files, moved, problems):
    change_id = change.get("id")
    path = _text(change.get("path"))
    superseded_by = _text(change.get("superseded_by"))
    if not path:
        problems.append(Problem(change_id, "archive_line",
                                "an archive line needs the path of the draft to mark"))
    else:
        entry = files.get(_relative(path))
        if entry is None:
            problems.append(Problem(change_id, "archive_line",
                                    "%s is not a file in the inventory" % path))
        elif entry["kind"] != "lookalike" or not entry["path"].lower().endswith(".md"):
            problems.append(Problem(change_id, "archive_line",
                                    "%s is %s, and only a markdown look-alike gets an archive line"
                                    % (path, entry["kind"])))
        elif entry["path"] in moved:
            problems.append(Problem(change_id, "archive_line",
                                    "%s is moved away by the earlier change %s"
                                    % (path, moved[entry["path"]])))
    canonicals = _canonicals(record)
    if not superseded_by:
        problems.append(Problem(change_id, "archive_line",
                                "an archive line needs superseded_by, the canonical source"))
    elif _relative(superseded_by) not in canonicals:
        problems.append(Problem(change_id, "archive_line",
                                "%s is not a canonical source the build file names (%s)"
                                % (superseded_by, ", ".join(canonicals) or "none")))


def _check_mark(change, record, files, problems):
    change_id = change.get("id")
    item_kind = change.get("item_kind")
    item = _text(change.get("item"))
    mark = change.get("mark")
    if item_kind not in ITEM_KINDS:
        problems.append(Problem(change_id, "mark", "item_kind %r is not one of %s"
                                % (item_kind, ", ".join(ITEM_KINDS))))
    elif not item:
        problems.append(Problem(change_id, "mark", "a mark needs the item it marks"))
    else:
        if item_kind == "file":
            known = item in files or _relative(item) in files
        elif item_kind == "build":
            known = item in [build["item"] for build in record["builds"]]
        else:
            known = item in [session["harness_session_id"] for session in record["sessions"]]
        if not known:
            problems.append(Problem(change_id, "mark",
                                    "%s %s is not in the inventory" % (item_kind, item)))
    if mark not in MARKS:
        problems.append(Problem(change_id, "mark", "mark %r is not one of %s"
                                % (mark, ", ".join(MARKS))))
    elif mark != "unused" and not _text(change.get("value")):
        problems.append(Problem(change_id, "mark", "a %s mark needs a value" % mark))


def check_proposal(project_dir, proposal, inventory):
    """The problems of a proposal against a fresh inventory, as a list of Problem.

    inventory is the record build_inventory gives for the project now. An
    empty list means every change can be applied. The check changes nothing.
    """
    if not isinstance(proposal, dict):
        return [Problem(None, "proposal", "the proposal is not a mapping of fields")]
    folder = os.path.abspath(str(project_dir))
    problems = []
    if proposal.get("schema") != SCHEMA:
        problems.append(Problem(None, "schema", "schema is %r, not %s"
                                % (proposal.get("schema"), SCHEMA)))
    if proposal.get("schema_version") != SCHEMA_VERSION:
        problems.append(Problem(None, "schema_version", "schema_version is %r, not %d"
                                % (proposal.get("schema_version"), SCHEMA_VERSION)))
    if not _text(proposal.get("proposed_by")):
        problems.append(Problem(None, "proposed_by",
                                "proposed_by is missing, so the proposal names no author"))
    changes = proposal.get("changes")
    if not isinstance(changes, list):
        problems.append(Problem(None, "changes", "changes is not a list"))
    if proposal.get("inventory_id") != inventory["inventory_id"]:
        problems.append(Problem(None, "inventory_id",
                                "the project changed after the inventory this proposal was"
                                " written from (%s, now %s), so scan it again and write a new"
                                " proposal" % (proposal.get("inventory_id"),
                                               inventory["inventory_id"])))
        return problems
    if not isinstance(changes, list):
        return problems

    files = dict((entry["path"], entry) for entry in inventory["files"])
    seen = set()
    targets = {}
    moved = {}
    for number, change in enumerate(changes, start=1):
        if not isinstance(change, dict):
            problems.append(Problem(None, "change", "change %d is not a mapping" % number))
            continue
        change_id = change.get("id")
        if change_id is not None and not isinstance(change_id, str):
            problems.append(Problem(None, "id", "change %d has the id %s, which is not text,"
                                    " so quote it" % (number, _one_line(change_id))))
        elif not _text(change_id):
            problems.append(Problem(None, "id", "change %d has no id" % number))
        elif change_id in seen:
            problems.append(Problem(change_id, "id", "the id %s is used by an earlier change"
                                    % change_id))
        else:
            seen.add(change_id)
        if not _text(change.get("reason")):
            problems.append(Problem(change_id, "reason", "change %s gives no reason"
                                    % (change_id or number)))
        op = change.get("op")
        if op == "move":
            _check_move(change, folder, inventory, files, targets, moved, problems)
        elif op == "archive_line":
            _check_archive_line(change, inventory, files, moved, problems)
        elif op == "mark":
            _check_mark(change, inventory, files, problems)
        elif isinstance(op, str) and op.strip().lower() in DELETING:
            problems.append(Problem(change_id, "op", NEVER_DELETES))
        elif not _text(op):
            problems.append(Problem(change_id, "op", "the change names no op, one of %s"
                                    % ", ".join(OPERATIONS)))
        else:
            problems.append(Problem(change_id, "op", "%s is not an operation the organizer has,"
                                    " which are %s" % (op, ", ".join(OPERATIONS))))
    return problems


def _one_line(value):
    if value is None:
        return "?"
    return _SPACES.sub(" ", str(value)).strip() or "?"


def describe(change):
    """One plain line saying what a change does and why."""
    get = lambda name: _one_line(change.get(name))  # noqa: E731
    op = change.get("op")
    if op == "move":
        what = "move %s to %s" % (get("path"), get("to"))
    elif op == "archive_line":
        what = "archive_line %s, superseded by %s" % (get("path"), get("superseded_by"))
    elif op == "mark":
        what = "mark %s %s %s" % (get("item_kind"), get("item"), get("mark"))
        if change.get("value") is not None:
            what += ", value %s" % get("value")
    else:
        what = "%s %s, an operation the organizer does not have" % (get("op"), get("path"))
    return "%s %s, because %s" % (get("id"), what, get("reason"))


# The command.


def add_command(commands):
    parser = commands.add_parser(
        "check", help="check a proposal against a fresh scan, changing nothing",
        description="Rescan a project in memory, print each change a proposal makes and then"
        " each problem, and exit 1 on any problem. Nothing is changed.")
    parser.add_argument("dir", metavar="DIR", help="the project folder")
    parser.add_argument("proposal", metavar="PROPOSAL", help="the proposal file, YAML")
    parser.add_argument("--home", help="the features home, else FEATURES_HOME, else " + DEFAULT_HOME)
    parser.set_defaults(run=command)


def report(proposal, problems, out):
    """Print each change's line and then each problem."""
    changes = proposal.get("changes") if isinstance(proposal, dict) else None
    changes = changes if isinstance(changes, list) else []
    out.write("Changes %d\n" % len(changes))
    for number, change in enumerate(changes, start=1):
        if isinstance(change, dict):
            out.write("  %s\n" % describe(change))
        else:
            out.write("  change %d is not a mapping\n" % number)
    if not problems:
        out.write("No problems\n")
        return
    out.write("Problems %d\n" % len(problems))
    for problem in problems:
        out.write("  %s %s\n" % (problem.change_id or "proposal", problem.message))


def command(options, out=None, err=None, now=None):
    out = out or sys.stdout
    err = err or sys.stderr
    now = now or datetime.datetime.now(datetime.timezone.utc)
    folder = os.path.abspath(os.path.expanduser(options.dir))
    try:
        proposal = load_proposal(options.proposal)
        system = load_system(features_home(options.home))
        if not os.path.isdir(folder):
            raise SetupError("%s is not a folder" % folder)
        record = build_inventory(folder, now, root=system["workflow_root"],
                                 audit_db=os.path.join(system["audit_home"], AUDIT_DATABASE))
    except (ProposalError, SetupError, LayerMissing) as error:
        err.write("organize check stopped, %s\n" % error)
        return 1
    problems = check_proposal(folder, proposal, record)
    out.write("Proposal %s for %s\n" % (os.path.abspath(options.proposal), record["project"]))
    report(proposal, problems, out)
    out.write("Nothing was changed\n")
    return 1 if problems else 0
