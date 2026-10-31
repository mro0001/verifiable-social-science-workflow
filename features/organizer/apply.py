"""Apply a proposal (step F9).

python3 -m features organize apply DIR PROPOSAL --by NAME [--home DIR]

The scholar applies a whole proposal by running this command, editing the
file first to drop any change (track F choice 19). Apply rescans the
project, runs the check of step F8, and applies nothing when it finds any
problem. Otherwise the changes apply in order, and each is written to the
journal as soon as it succeeds. On a failure the rest are reported as not
applied.

A move makes the target's folders and renames the file, refusing a target
that appeared after the check. An archive line is written by ospipe archive
run through the layer runner (reconciliation, Track F), dated by now, with
the file's bytes kept before and after in the content store. A mark changes
no project file. After applying, apply writes marks.yaml and a fresh
inventory.
"""
import collections
import datetime
import hashlib
import os
import subprocess
import sys

from features.layers import LayerMissing, run_layer
from features.organizer import journal
from features.organizer.inventory import (AUDIT_DATABASE, archive_line_of, build_inventory,
                                          write_inventory)
from features.organizer.proposals import (ProposalError, check_proposal, describe, load_proposal,
                                          report)
from features.setup.system import DEFAULT_HOME, SetupError, features_home, load_system

COMMAND = "python3 -m features organize apply"

ApplyResult = collections.namedtuple("ApplyResult", "problems applied not_applied inventory_path")


class ApplyError(Exception):
    """Apply cannot start, for a reason that is not a problem of the proposal."""


class ChangeFailed(Exception):
    """One change could not be applied. The message says why."""


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _relative(path):
    return os.path.normpath(str(path)).replace(os.sep, "/")


def _base_fields(by, proposal, proposal_sha256, change):
    return collections.OrderedDict([
        ("by", by),
        ("proposed_by", proposal.get("proposed_by")),
        ("proposal_sha256", proposal_sha256),
        ("change_id", change.get("id")),
        ("op", change.get("op")),
        ("reason", change.get("reason")),
    ])


def _move(folder, change):
    path = _relative(change["path"].strip())
    to = _relative(change["to"].strip())
    source = os.path.join(folder, path)
    target = os.path.join(folder, to)
    if os.path.lexists(target):
        raise ChangeFailed("%s appeared after the check, so %s was not moved" % (to, path))
    if not os.path.isfile(source):
        raise ChangeFailed("%s is no longer there" % path)
    with open(source, "rb") as handle:
        digest = _sha256(handle.read())
    os.makedirs(os.path.dirname(target), exist_ok=True)
    if os.path.lexists(target):
        raise ChangeFailed("%s appeared after the check, so %s was not moved" % (to, path))
    os.rename(source, target)
    return collections.OrderedDict([("path", path), ("to", to), ("sha256", digest)])


def _archive_line(folder, change, now, root, runner):
    path = _relative(change["path"].strip())
    superseded_by = _relative(change["superseded_by"].strip())
    full = os.path.join(folder, path)
    try:
        with open(full, "rb") as handle:
            before = handle.read()
    except OSError as error:
        raise ChangeFailed("%s cannot be read (%s)" % (path, error.strerror))
    before_sha256 = journal.keep_bytes(folder, before)
    done = runner("ospipe", ["archive", path, "--by", superseded_by, "--date",
                             now.date().isoformat()], root=root, cwd=folder)
    with open(full, "rb") as handle:
        after = handle.read()
    if done.returncode != 0:
        text = " ".join((done.stderr or done.stdout).split())
        if after != before:
            journal.keep_bytes(folder, after)
            text += ", and %s changed, its new bytes are kept in originals/" % path
        raise ChangeFailed("ospipe archive exited %d. %s" % (done.returncode, text))
    after_sha256 = journal.keep_bytes(folder, after)
    line = archive_line_of(after.decode("utf-8", "replace"))
    return collections.OrderedDict([
        ("path", path),
        ("superseded_by", superseded_by),
        ("line", line),
        ("before_sha256", before_sha256),
        ("after_sha256", after_sha256),
    ])


def _mark(change):
    item = change["item"].strip()
    if change.get("item_kind") == "file":
        item = _relative(item)
    value = change.get("value")
    return collections.OrderedDict([
        ("item_kind", change.get("item_kind")),
        ("item", item),
        ("mark", change.get("mark")),
        ("value", value),
    ])


def apply_change(folder, change, now, root=None, runner=run_layer):
    """Apply one checked change and give the fields its journal entry records."""
    op = change.get("op")
    if op == "move":
        return _move(folder, change)
    if op == "archive_line":
        return _archive_line(folder, change, now, root, runner)
    if op == "mark":
        return _mark(change)
    raise ChangeFailed("%s is not an operation the organizer has" % op)


def refresh(folder, now, root=None, runner=run_layer, audit_db=None):
    """Write marks.yaml from the journal and a fresh inventory, and give the inventory's path."""
    journal.write_marks(folder)
    record = build_inventory(folder, now, root=root, runner=runner, audit_db=audit_db)
    return write_inventory(folder, record)


def _why(error):
    """Why a change failed, in words, for a failure the loop of apply_proposal catches."""
    if isinstance(error, (ChangeFailed, LayerMissing)):
        return str(error)
    if isinstance(error, subprocess.TimeoutExpired):
        return "ospipe archive timed out after %s seconds" % error.timeout
    return "%s (%s)" % (error.strerror or error, getattr(error, "filename", "") or "")


def apply_proposal(project_dir, proposal_path, by, now, root=None, runner=run_layer,
                   audit_db=None):
    """Check a proposal against a fresh scan and, with no problem, apply every change in order.

    Gives ApplyResult(problems, applied, not_applied, inventory_path).
    applied lists (change, entry id) for each change journaled, and
    not_applied lists (change, why) for the change that failed and each one
    after it. A change fails when it is refused, on an OSError, and when the
    runner raises LayerMissing or times out. With any problem nothing is applied, nothing is written, and
    inventory_path is None. Raises ProposalError when the file cannot be
    read, JournalError when the journal cannot be read, and ApplyError when
    by names no one.
    """
    if not isinstance(by, str) or not by.strip():
        raise ApplyError("--by needs the name of the scholar who applies the proposal")
    by = by.strip()
    folder = os.path.realpath(os.path.abspath(str(project_dir)))
    path = os.path.abspath(os.path.expanduser(str(proposal_path)))
    proposal = load_proposal(path)
    with open(path, "rb") as handle:
        proposal_sha256 = _sha256(handle.read())
    journal.read_journal(folder)
    record = build_inventory(folder, now, root=root, runner=runner, audit_db=audit_db)
    problems = check_proposal(folder, proposal, record)
    if problems:
        return ApplyResult(problems, [], [], None)

    applied, not_applied = [], []
    changes = proposal["changes"]
    for number, change in enumerate(changes):
        try:
            fields = apply_change(folder, change, now, root=root, runner=runner)
        except (ChangeFailed, OSError, LayerMissing, subprocess.TimeoutExpired) as error:
            why = _why(error)
            not_applied.append((change, why))
            for later in changes[number + 1:]:
                not_applied.append((later, "not applied, since change %s failed"
                                    % change.get("id")))
            break
        entry = _base_fields(by, proposal, proposal_sha256, change)
        entry.update(fields)
        applied.append((change, journal.append_entry(folder, entry, now)))
    inventory_path = refresh(folder, now, root=root, runner=runner, audit_db=audit_db)
    return ApplyResult([], applied, not_applied, inventory_path)


# The command.


def add_command(commands):
    parser = commands.add_parser(
        "apply", help="apply a checked proposal, journaling every change",
        description="Rescan a project, check a proposal, and with no problem apply its changes"
        " in order. Each change is written to <DIR>/.organizer/journal.jsonl, and the bytes of"
        " each file an archive line changes are kept in <DIR>/.organizer/originals/.")
    parser.add_argument("dir", metavar="DIR", help="the project folder")
    parser.add_argument("proposal", metavar="PROPOSAL", help="the proposal file, YAML")
    parser.add_argument("--by", required=True, metavar="NAME",
                        help="the name of the scholar who applies the proposal")
    parser.add_argument("--home", help="the features home, else FEATURES_HOME, else " + DEFAULT_HOME)
    parser.set_defaults(run=command)


def command(options, out=None, err=None, now=None):
    out = out or sys.stdout
    err = err or sys.stderr
    now = now or datetime.datetime.now(datetime.timezone.utc)
    folder = os.path.abspath(os.path.expanduser(options.dir))
    try:
        system = load_system(features_home(options.home))
        if not os.path.isdir(folder):
            raise SetupError("%s is not a folder" % folder)
        result = apply_proposal(folder, options.proposal, options.by, now,
                                root=system["workflow_root"],
                                audit_db=os.path.join(system["audit_home"], AUDIT_DATABASE))
    except (ApplyError, ProposalError, journal.JournalError, SetupError, LayerMissing) as error:
        err.write("organize apply stopped, %s\n" % error)
        return 1
    out.write("Proposal %s for %s\n" % (os.path.abspath(options.proposal),
                                         os.path.realpath(folder)))
    if result.problems:
        report(load_proposal(options.proposal), result.problems, out)
        out.write("Nothing was applied\n")
        return 1
    out.write("Applied %d of %d\n" % (len(result.applied),
                                      len(result.applied) + len(result.not_applied)))
    for change, entry in result.applied:
        out.write("  %s %s\n" % (entry, describe(change)))
    if result.not_applied:
        out.write("Not applied %d\n" % len(result.not_applied))
        for change, why in result.not_applied:
            out.write("  %s, %s\n" % (describe(change), why))
    out.write("Wrote %s\n" % journal.marks_path(os.path.realpath(folder)))
    out.write("Wrote %s\n" % result.inventory_path)
    return 1 if result.not_applied else 0
