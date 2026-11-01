"""The audit layer's command line, run as python3 -m audit_layer."""
import argparse
import os
import re
import sys
from pathlib import Path

import yaml

from audit_layer.capture import ADAPTERS, SubagentsNotCaptured, capture_session
from audit_layer.capture.check import check_captures
from audit_layer.capture.sweep import NOT_SNAPSHOTTED, sweep
from audit_layer.projects import list_projects
from audit_layer.records.citation_log import project_sessions, write_citation_log
from audit_layer.records.citation_provenance import read_references, write_citation_provenance
from audit_layer.records.rationales import rationales, write_rationales
from audit_layer.records.session_index import read_list, write_session_index
from audit_layer.records.session_writes import session_writes, write_session_writes
from audit_layer.records.file_edits import file_edits, write_file_edits
from audit_layer.settings import (
    SETTINGS,
    SettingsError,
    add_excluded,
    audit_home,
    full_path_problem,
    read_settings,
    write_settings,
)
from audit_layer.settings import excluded as is_excluded
from audit_layer.store import DATABASE, current, open_store
from audit_layer.stores.data import VERSION as DATA_VERSION
from audit_layer.stores.data import add_dataset
from audit_layer.stores.knowledge import VERSION as KNOWLEDGE_VERSION
from audit_layer.stores.knowledge import history as knowledge_history
from audit_layer.stores.knowledge import sync as knowledge_sync
from audit_layer.stores.sources import VERSION as SOURCES_VERSION
from audit_layer.stores.sources import KINDS as TEXT_KINDS
from audit_layer.stores.sources import add_from_bib, add_text, attach_original
from audit_layer.tagging.answers import open_answers
from audit_layer.tagging.model_pass import Outcome, due, tag_session
from audit_layer.tagging.review import ReviewError, review, unreviewed
from audit_layer.writeout import WRITTEN_OUT, write_out_project

HOME_HELP = "the audit home folder, else the AUDIT_HOME environment variable, else ~/.audit_layer"

# The reason the sources add-bib command gives its rows unless told another
# (plan choice 23).
SOURCES_REASON = "added from the citation manager's export"
ATTACH_REASON = "kept the retrieved original"
TEXT_REASON = "kept the extracted text"
DATA_REASON = "added a collected dataset"
KNOWLEDGE_REASON = "synced from the knowledge base's entry files"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="audit_layer")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="create the audit home, its database, and its settings file")
    init.add_argument("--home", help=HOME_HELP)

    excluded = sub.add_parser(
        "excluded", help="add to or list the folders whose AI sessions are never recorded"
    )
    excluded_actions = excluded.add_subparsers(dest="action", required=True, metavar="add|list")
    excluded_add = excluded_actions.add_parser(
        "add",
        help="add folders to excluded_folders in the settings file, creating the audit home"
        " when it has none, and never removing a folder",
    )
    excluded_add.add_argument("--home", help=HOME_HELP)
    excluded_add.add_argument(
        "folders", nargs="+", metavar="PATH", help="a folder, as a full path starting with / or ~"
    )
    excluded_list = excluded_actions.add_parser(
        "list", help="print the folders listed under excluded_folders"
    )
    excluded_list.add_argument("--home", help=HOME_HELP)

    capture = sub.add_parser("capture", help="store AI sessions in the audit store")
    capture.add_argument("--home", help=HOME_HELP)
    capture.add_argument(
        "--harness",
        required=True,
        choices=sorted(ADAPTERS),
        metavar="NAME",
        help="the harness that kept the sessions, one of " + ", ".join(sorted(ADAPTERS)),
    )
    capture.add_argument(
        "paths", nargs="+", metavar="LOCATION", help="where the harness keeps a session"
    )

    swept = sub.add_parser(
        "sweep", help="capture every session the harnesses keep that the store does not hold whole"
    )
    swept.add_argument("--home", help=HOME_HELP)
    swept.add_argument(
        "--harness",
        action="append",
        choices=sorted(ADAPTERS),
        metavar="NAME",
        help="a harness to sweep, one of " + ", ".join(sorted(ADAPTERS)) + ", else every one",
    )
    swept.add_argument(
        "--root",
        action="append",
        type=_root,
        default=[],
        metavar="HARNESS=PATH",
        help="where a harness keeps its sessions, in place of its usual place",
    )
    swept.add_argument(
        "--file",
        action="append",
        metavar="LOCATION",
        help="a session to sweep in place of the listing, with one --harness",
    )

    checked = sub.add_parser(
        "check-captures",
        help="list sessions missed or interrupted in capture, and stored files gone or altered",
    )
    checked.add_argument("--home", help=HOME_HELP)
    checked.add_argument(
        "--harness",
        action="append",
        choices=sorted(ADAPTERS),
        metavar="NAME",
        help="a harness to check, one of " + ", ".join(sorted(ADAPTERS)) + ", else every one",
    )
    checked.add_argument(
        "--root",
        action="append",
        type=_root,
        default=[],
        metavar="HARNESS=PATH",
        help="where a harness keeps its sessions, in place of its usual place",
    )

    tagged = sub.add_parser(
        "tag", help="fill each due session's title, gist, summary, keywords, and decisions"
    )
    tagged.add_argument("--home", help=HOME_HELP)
    tagged.add_argument(
        "--answers",
        required=True,
        metavar="SPEC",
        help="where the answers come from, such as recorded:<file>",
    )
    tagged.add_argument(
        "--session",
        action="append",
        metavar="ID",
        help="a session to tag, by its id, in place of the sessions due",
    )
    tagged.add_argument(
        "--limit", type=_limit, metavar="N", help="tag at most this many sessions"
    )

    reviewed = sub.add_parser(
        "review", help="list the model pass's fields awaiting review, or record a person's review"
    )
    reviewed.add_argument("--home", help=HOME_HELP)
    which = reviewed.add_mutually_exclusive_group(required=True)
    which.add_argument(
        "--list", action="store_true", help="list each session whose model-pass fields await review"
    )
    which.add_argument("--session", metavar="ID", help="the session to review, by its id")
    reviewed.add_argument("--by", metavar="NAME", help="the name of the person who reviewed")
    reviewed.add_argument(
        "--set",
        action="append",
        type=_field_value,
        default=[],
        metavar="FIELD=VALUE",
        help="a new value for title, gist, summary, or keywords (terms split at commas)",
    )
    reviewed.add_argument(
        "--rationale",
        action="append",
        type=_rationale,
        default=[],
        metavar="ORDINAL=TEXT",
        help="a new rationale for the decision at this ordinal",
    )

    sources = sub.add_parser("sources", help="add to the sources store or list its records")
    source_commands = sources.add_subparsers(dest="action", required=True)
    add_bib = source_commands.add_parser(
        "add-bib", help="add a record for each entry of the citation manager's BibTeX export"
    )
    add_bib.add_argument("--home", help=HOME_HELP)
    add_bib.add_argument("file", metavar="FILE", help="the BibTeX file")
    add_bib.add_argument(
        "--session", default="none", metavar="ID", help="the session the records come from"
    )
    add_bib.add_argument(
        "--reason", default=SOURCES_REASON, metavar="TEXT", help="why the records are added"
    )
    listed = source_commands.add_parser("list", help="list the current source records")
    listed.add_argument("--home", help=HOME_HELP)
    attached = source_commands.add_parser(
        "attach", help="keep a source's retrieved original, with its retrieval method and date"
    )
    attached.add_argument("--home", help=HOME_HELP)
    attached.add_argument("citekey", metavar="CITEKEY", help="the source's citekey")
    attached.add_argument("--original", required=True, metavar="FILE", help="the retrieved file")
    attached.add_argument(
        "--method", required=True, metavar="TEXT", help="how the original was retrieved"
    )
    attached.add_argument(
        "--date", required=True, metavar="YYYY-MM-DD", help="the day it was retrieved"
    )
    attached.add_argument(
        "--session", default="none", metavar="ID", help="the session the original comes from"
    )
    attached.add_argument(
        "--reason", default=ATTACH_REASON, metavar="TEXT", help="why the original is kept"
    )
    texted = source_commands.add_parser(
        "text", help="keep text extracted from a source, by kind, with its conversion method"
    )
    texted.add_argument("--home", help=HOME_HELP)
    texted.add_argument("citekey", metavar="CITEKEY", help="the source's citekey")
    texted.add_argument(
        "--kind", required=True, metavar="KIND", help="one of " + ", ".join(TEXT_KINDS)
    )
    texted.add_argument("--file", required=True, metavar="FILE", help="the extracted text")
    texted.add_argument(
        "--conversion", required=True, metavar="TEXT", help="how the text was extracted"
    )
    texted.add_argument(
        "--session", default="none", metavar="ID", help="the session the text comes from"
    )
    texted.add_argument(
        "--reason", default=TEXT_REASON, metavar="TEXT", help="why the text is kept"
    )

    data = sub.add_parser("data", help="add a dataset to the data store or list its datasets")
    data_commands = data.add_subparsers(dest="action", required=True)
    data_add = data_commands.add_parser(
        "add", help="store a CSV file as the next version of a dataset, with its codebook"
    )
    data_add.add_argument("--home", help=HOME_HELP)
    data_add.add_argument("--name", required=True, metavar="NAME", help="the dataset's name")
    data_add.add_argument("--csv", required=True, metavar="FILE", help="the CSV file")
    data_add.add_argument(
        "--collected", required=True, metavar="YYYY-MM-DD", help="the day the data were collected"
    )
    data_add.add_argument(
        "--codebook", metavar="FILE", help="a YAML file mapping each variable to its description"
    )
    data_add.add_argument(
        "--session", default="none", metavar="ID", help="the session the dataset comes from"
    )
    data_add.add_argument(
        "--reason", default=DATA_REASON, metavar="TEXT", help="why the dataset is added"
    )
    data_list = data_commands.add_parser("list", help="list the current version of each dataset")
    data_list.add_argument("--home", help=HOME_HELP)

    knowledge = sub.add_parser(
        "knowledge", help="load the knowledge base's entry files or list an entry's versions"
    )
    knowledge_commands = knowledge.add_subparsers(dest="action", required=True)
    synced = knowledge_commands.add_parser(
        "sync", help="load each entry file of a corpus folder into the knowledge store"
    )
    synced.add_argument("--home", help=HOME_HELP)
    synced.add_argument(
        "--corpus", required=True, metavar="DIR", help="the folder holding the entry files"
    )
    synced.add_argument(
        "--session", default="none", metavar="ID", help="the session the entries come from"
    )
    synced.add_argument(
        "--reason", default=KNOWLEDGE_REASON, metavar="TEXT", help="why the entries are synced"
    )
    versions = knowledge_commands.add_parser(
        "history", help="list every version of an entry, oldest first"
    )
    versions.add_argument("--home", help=HOME_HELP)
    versions.add_argument("entry_id", metavar="ENTRY_ID", help="the entry's id")

    listed_projects = sub.add_parser(
        "projects", help="list each project's folder, name, and number of sessions"
    )
    listed_projects.add_argument("--home", help=HOME_HELP)

    defined = sub.add_parser(
        "fields", help="print each field's definition, generation rule, and null behavior"
    )
    defined.add_argument("--home", help=HOME_HELP)
    defined.add_argument(
        "table", nargs="?", metavar="TABLE", help="the table whose fields to print, * for the spine"
    )

    write_out = sub.add_parser("write-out", help="write a project's records out as files")
    records = write_out.add_subparsers(dest="record", required=True)
    log = records.add_parser(
        "citation-log", help="write out the citations AI sessions introduced in a project"
    )
    log.add_argument("--home", help=HOME_HELP)
    log.add_argument("--project", required=True, metavar="DIR", help="the project folder")
    log.add_argument("--out", required=True, metavar="FILE", help="the YAML file to write")
    provenance = records.add_parser(
        "citation-provenance",
        help="write out where the record first names each work in a reference list, an AI or the scholar",
    )
    provenance.add_argument("--home", help=HOME_HELP)
    provenance.add_argument("--project", required=True, metavar="DIR", help="the project folder")
    provenance.add_argument(
        "--references",
        required=True,
        metavar="FILE",
        help="the reference list, refs.yaml or a BibTeX file ending in .bib",
    )
    provenance.add_argument("--out", required=True, metavar="FILE", help="the YAML file to write")
    provenance.add_argument(
        "--artifacts",
        nargs="+",
        action="extend",
        default=[],
        metavar="PATH",
        help="a working folder of AI output, each of whose files is an AI-written artifact, or one such file",
    )
    provenance.add_argument(
        "--fetched",
        nargs="+",
        action="extend",
        default=[],
        metavar="PATH",
        help="a folder or file of sources an AI fetched, AI output that is not the AI's own words",
    )
    writes = records.add_parser(
        "session-writes", help="write out the files AI sessions wrote or edited in a project"
    )
    writes.add_argument("--home", help=HOME_HELP)
    writes.add_argument("--project", required=True, metavar="DIR", help="the project folder")
    writes.add_argument("--out", required=True, metavar="FILE", help="the JSON Lines file to write")
    reasons = records.add_parser(
        "rationales", help="write out the stated reason for each AI edit to a project's source file"
    )
    reasons.add_argument("--home", help=HOME_HELP)
    reasons.add_argument("--project", required=True, metavar="DIR", help="the project folder")
    reasons.add_argument(
        "--source", required=True, metavar="FILE", help="the source file, relative to the project"
    )
    reasons.add_argument("--out", required=True, metavar="FILE", help="the YAML file to write")
    edits = records.add_parser(
        "file-edits",
        help=(
            "write out each edit AI sessions made to a file in a project, with its text before"
            " and after and the stated reason"
        ),
    )
    edits.add_argument("--home", help=HOME_HELP)
    edits.add_argument("--project", required=True, metavar="DIR", help="the project folder")
    edits.add_argument("--out", required=True, metavar="FILE", help="the YAML file to write")
    project_out = records.add_parser(
        "project",
        help=(
            "write out a project's sessions, events, transcripts, snapshots, and the schema,"
            " and the sources, datasets, and knowledge entries named"
        ),
    )
    project_out.add_argument("--home", help=HOME_HELP)
    project_out.add_argument("--project", required=True, metavar="DIR", help="the project folder")
    project_out.add_argument(
        "--out", required=True, metavar="DIR", help="the new or empty folder to write into"
    )
    project_out.add_argument(
        "--sources", metavar="KEY,...", help="the citekeys of the sources to write out"
    )
    project_out.add_argument(
        "--datasets",
        metavar="NAME[:VERSION],...",
        help="the datasets to write out, each at its latest version unless one is given",
    )
    project_out.add_argument(
        "--knowledge", action="store_true", help="write out every knowledge entry and its history"
    )
    index_out = records.add_parser(
        "session-index",
        help=(
            "write out a public, searchable index of the AI sessions that touched a project,"
            " with their AI contributions in the final reports"
        ),
        description=(
            "Write out a public, searchable index of the AI sessions that touched a project,"
            " with their AI contributions in the final reports. To put the index in the"
            " project's sessions/ folder, replacing an older copy, run"
            " python3 handoffs/session_index_to_project.py --from DIR --project DIR"
            " with the --out folder as --from."
        ),
    )
    index_out.add_argument("--home", help=HOME_HELP)
    index_out.add_argument("--project", required=True, metavar="DIR", help="the project folder")
    index_out.add_argument(
        "--out", required=True, metavar="DIR", help="the new or empty folder to write into"
    )
    index_out.add_argument(
        "--results",
        nargs="+",
        action="extend",
        default=[],
        metavar="FILE",
        help=(
            "a stream's results file, or PRODUCT=FILE for one product's, the last one given"
            " for a product's stream counting"
        ),
    )
    index_out.add_argument(
        "--also-folder",
        nargs="+",
        action="extend",
        default=[],
        metavar="DIR",
        help="a folder the project's work was done in before it moved, which counts as the project's",
    )
    index_out.add_argument(
        "--no-summaries",
        action="store_true",
        help="leave out the model-written title, gist, summary, and keywords of every session",
    )
    index_out.add_argument(
        "--withhold",
        metavar="FILE",
        help="a file listing public ids, one to a line, whose model-written fields are left out",
    )
    index_out.add_argument(
        "--scrub",
        metavar="FILE",
        help=(
            "a file listing terms, one to a line, each written as [withheld], in any case,"
            " in the model-written fields and in the file names the index lists"
        ),
    )

    args = parser.parse_args(argv)
    home = audit_home(args.home)

    if args.command == "init":
        return _init(home)
    if args.command == "excluded" and args.action == "add":
        return _excluded_add(home, args.folders)
    if args.command == "excluded" and args.action == "list":
        return _excluded_list(home)
    if args.command == "capture":
        return _capture(home, args.harness, args.paths)
    if args.command == "sweep":
        return _sweep(home, args.harness, dict(args.root), args.file)
    if args.command == "check-captures":
        return _check_captures(home, args.harness, dict(args.root))
    if args.command == "tag":
        return _tag(home, args.answers, args.session, args.limit)
    if args.command == "review":
        return _review(home, args.list, args.session, args.by, args.set, args.rationale)
    if args.command == "sources" and args.action == "add-bib":
        return _sources_add_bib(home, args.file, args.session, args.reason)
    if args.command == "sources" and args.action == "list":
        return _sources_list(home)
    if args.command == "sources" and args.action == "attach":
        return _sources_attach(
            home, args.citekey, args.original, args.method, args.date, args.session, args.reason
        )
    if args.command == "sources" and args.action == "text":
        return _sources_text(
            home, args.citekey, args.kind, args.file, args.conversion, args.session, args.reason
        )
    if args.command == "data" and args.action == "add":
        return _data_add(
            home, args.name, args.csv, args.collected, args.codebook, args.session, args.reason
        )
    if args.command == "data" and args.action == "list":
        return _data_list(home)
    if args.command == "knowledge" and args.action == "sync":
        return _knowledge_sync(home, args.corpus, args.session, args.reason)
    if args.command == "knowledge" and args.action == "history":
        return _knowledge_history(home, args.entry_id)
    if args.command == "projects":
        return _projects(home)
    if args.command == "fields":
        return _fields(home, args.table)
    if args.command == "write-out" and args.record == "citation-log":
        return _write_out_citation_log(home, args.project, args.out)
    if args.command == "write-out" and args.record == "citation-provenance":
        return _write_out_citation_provenance(
            home, args.project, args.references, args.artifacts, args.out, args.fetched
        )
    if args.command == "write-out" and args.record == "session-writes":
        return _write_out_session_writes(home, args.project, args.out)
    if args.command == "write-out" and args.record == "rationales":
        return _write_out_rationales(home, args.project, args.source, args.out)
    if args.command == "write-out" and args.record == "file-edits":
        return _write_out_file_edits(home, args.project, args.out)
    if args.command == "write-out" and args.record == "project":
        return _write_out_project(
            home, args.project, args.out, args.sources, args.datasets, args.knowledge
        )
    if args.command == "write-out" and args.record == "session-index":
        return _write_out_session_index(
            home, args.project, args.out, args.results, args.no_summaries, args.withhold, args.scrub,
            args.also_folder,
        )
    return 2


def _init(home) -> int:
    store = open_store(home)
    store.db.close()
    print(f"audit home ready at {home}")
    settings = home / SETTINGS
    if write_settings(home):
        print(
            f"wrote {settings}. List in it every folder that holds student records,"
            " so capture never records the sessions run there"
        )
    else:
        print(f"kept {settings} as it is")
    return 0


def _print_excluded(home, folders) -> None:
    print(f"excluded folders in {home / SETTINGS}")
    for folder in folders:
        print(f"  {folder}")
    if not folders:
        print("  none")


def _excluded_add(home, folders) -> int:
    # Every folder is checked before anything is written, so a refused one
    # leaves the audit home as it was.
    for folder in folders:
        problem = full_path_problem(folder)
        if problem:
            print(f"excluded add refused, {problem}", file=sys.stderr)
            return 1
    if not (home / SETTINGS).exists():
        store = open_store(home)
        store.db.close()
        write_settings(home)
        print(f"audit home ready at {home}")
    try:
        listed = add_excluded(home, folders)
    except SettingsError as error:
        print(f"excluded add refused, {error}", file=sys.stderr)
        return 1
    _print_excluded(home, listed)
    return 0


def _excluded_list(home) -> int:
    try:
        settings = read_settings(home)
    except SettingsError as error:
        print(f"excluded list refused, {error}", file=sys.stderr)
        return 1
    _print_excluded(home, settings["excluded_folders"])
    return 0


def _capture(home, harness, paths) -> int:
    # The settings are read before the store is opened, so a refused capture
    # leaves the audit home as it was.
    try:
        settings = read_settings(home)
    except SettingsError as error:
        print(f"capture refused, {error}", file=sys.stderr)
        return 1
    store = open_store(home)
    failed = 0
    try:
        for path in paths:
            try:
                summary = capture_session(store, harness, path, settings)
            except SubagentsNotCaptured as error:
                # The main session was stored, so its lines are printed, then
                # the subagent conversations not captured, by their ids and
                # never by a path.
                _print_summary(error.summary)
                print(f"capture incomplete, {error}", file=sys.stderr)
                failed += 1
                continue
            except (OSError, ValueError) as error:
                # One file that cannot be read does not stop the others.
                print(f"could not capture {path}, {error}", file=sys.stderr)
                failed += 1
                continue
            _print_summary(summary)
    finally:
        store.db.close()
    return 1 if failed else 0


def _root(given: str):
    """A --root value, HARNESS=PATH, as the harness and the path."""
    harness, mark, path = given.partition("=")
    if not mark or not path:
        raise argparse.ArgumentTypeError(f"{given} is not given as HARNESS=PATH")
    if harness not in ADAPTERS:
        raise argparse.ArgumentTypeError(
            f"there is no adapter for the harness {harness}. The harnesses with an adapter are "
            + ", ".join(sorted(ADAPTERS))
        )
    return harness, path


def _sweep(home, harnesses, roots, files) -> int:
    # The settings are read before the store is opened, so a refused sweep
    # leaves the audit home as it was.
    try:
        settings = read_settings(home)
    except SettingsError as error:
        print(f"sweep refused, {error}", file=sys.stderr)
        return 1
    if files and (not harnesses or len(harnesses) != 1):
        print("sweep refused, name one harness with --harness to sweep a --file", file=sys.stderr)
        return 1
    store = open_store(home)
    try:
        summary = sweep(store, settings, home, harnesses=harnesses, roots=roots, locations=files)
    finally:
        store.db.close()
    if summary.refused:
        print(f"sweep not run, {summary.refused}", file=sys.stderr)
        return 1
    # The summary names sessions by id and never by a path. A captured session
    # whose working files could not be snapshotted is counted once, as
    # captured, and is printed on a line of its own.
    not_captured = [
        (name, reason) for name, reason in summary.failed if not reason.startswith(NOT_SNAPSHOTTED)
    ]
    not_snapshotted = [
        (name, reason[len(NOT_SNAPSHOTTED):].lstrip(", "))
        for name, reason in summary.failed
        if reason.startswith(NOT_SNAPSHOTTED)
    ]
    print(
        "swept {}, {} captured, {} unchanged, {} excluded, {} working folder unknown,"
        " {} failed".format(
            _count(
                summary.captured
                + summary.unchanged
                + summary.excluded
                + summary.folder_unknown
                + len(not_captured),
                "session",
            ),
            summary.captured,
            summary.unchanged,
            summary.excluded,
            summary.folder_unknown,
            len(not_captured),
        )
    )
    for name, reason in not_captured:
        print(f"could not capture {name}, {reason}")
    for name, reason in not_snapshotted:
        print(f"could not snapshot {name}, {reason}")
    return 1 if summary.failed else 0


# The check's four lists, in the order printed, and whether the sweep is
# their remedy (plan choice 8).
_CHECK_LISTS = (
    ("not captured", "not_captured", True),
    ("working folder unknown", "working_folder_unknown", True),
    ("changed since capture", "changed_since_capture", True),
    ("stored file missing or altered", "stored_file_missing_or_altered", False),
)


def _check_captures(home, harnesses, roots) -> int:
    # The check only reads, so a home with no settings file or no store is
    # refused rather than made.
    try:
        settings = read_settings(home)
    except SettingsError as error:
        print(f"check refused, {error}", file=sys.stderr)
        return 1
    if not (home / DATABASE).is_file():
        print(
            f"check refused, there is no audit store at {home}. Run python3 -m audit_layer"
            " init, then capture or sweep the sessions",
            file=sys.stderr,
        )
        return 1
    store = open_store(home)
    try:
        report = check_captures(store, settings, harnesses=harnesses, roots=roots)
    except ValueError as error:
        print(f"check not finished, {error}", file=sys.stderr)
        return 1
    finally:
        store.db.close()
    # Each list names sessions by id and never by a path.
    for heading, field, swept in _CHECK_LISTS:
        names = getattr(report, field)
        line = f"{heading}, {_count(len(names), 'session')}"
        if names and swept:
            line += ", run python3 -m audit_layer sweep"
        print(line)
        for name in names:
            print(f"  {name}")
    return 1 if any(report) else 0


def _limit(given: str) -> int:
    """A --limit value, a whole number of at least 1."""
    try:
        number = int(given)
    except ValueError:
        number = 0
    if number < 1:
        raise argparse.ArgumentTypeError(f"{given} is not a whole number of at least 1")
    return number


def _tag(home, spec, names, limit) -> int:
    # Tagging adds to a store capture made, so a home with no store is
    # refused rather than made.
    if not (home / DATABASE).is_file():
        print(
            f"tag refused, there is no audit store at {home}. Run python3 -m audit_layer"
            " init, then capture or sweep the sessions",
            file=sys.stderr,
        )
        return 1
    try:
        answers = open_answers(spec)
    except ValueError as error:
        print(f"tag refused, {error}", file=sys.stderr)
        return 1
    store = open_store(home)
    outcomes = []
    try:
        # Each chosen session is its row and why it cannot be tagged, if so,
        # in the order named, else in the order due.
        if names:
            # A session named twice is tagged once, where first named.
            names = list(dict.fromkeys(names))
            chosen = [(name,) + _named_session(store, name) for name in names]
        else:
            chosen = [(row["harness_session_id"], row, None) for row in due(store)]
        if limit is not None:
            chosen = chosen[:limit]
        for name, row, problem in chosen:
            if problem:
                outcomes.append(Outcome(name, "failed", (problem,)))
            else:
                outcomes.append(tag_session(store, row, answers))
    finally:
        store.db.close()
    # Each line names a session by its id and never by a path.
    for outcome in outcomes:
        print(f"{outcome.status} {outcome.session_id}")
        for problem in outcome.problems:
            print(f"  {problem}")
    failed = sum(1 for outcome in outcomes if outcome.status == "failed")
    print(f"tagged {_count(len(outcomes) - failed, 'session')}, {failed} failed")
    return 1 if failed else 0


def _named_session(store, name):
    """The current row of the session named on the command line, or why it cannot be tagged."""
    rows = current(store, "sessions", harness_session_id=name)
    if not rows:
        return None, f"there is no session {name} in the audit store"
    if len({row["harness"] for row in rows}) > 1:
        return None, f"two harnesses have a session {name}, so it cannot be told apart"
    reader = ADAPTERS.get(rows[-1]["harness"])
    if reader is None or getattr(reader, "AI", False) is not True:
        return None, f"session {name} was not kept by an AI harness, so the pass does not tag it"
    return rows[-1], None


def _field_value(given: str):
    """A --set value, FIELD=VALUE, as the field and its value.

    The value is kept whole after the first =, and keywords are split at
    commas into terms, each without space at its ends.
    """
    field, mark, value = given.partition("=")
    if not mark or not field:
        raise argparse.ArgumentTypeError(f"{given} is not given as FIELD=VALUE")
    if field == "keywords":
        return field, [term.strip() for term in value.split(",") if term.strip()]
    return field, value


def _rationale(given: str):
    """A --rationale value, ORDINAL=TEXT, as the ordinal and the text."""
    ordinal, mark, text = given.partition("=")
    if not mark:
        raise argparse.ArgumentTypeError(f"{given} is not given as ORDINAL=TEXT")
    try:
        return int(ordinal), text
    except ValueError:
        raise argparse.ArgumentTypeError(f"{ordinal} in {given} is not a whole number")


def _review(home, listing, name, by, sets, rationales) -> int:
    # A review adds to a store the model pass tagged, so a home with no store
    # is refused rather than made.
    if not (home / DATABASE).is_file():
        print(
            f"review refused, there is no audit store at {home}. Run python3 -m audit_layer"
            " init, then capture and tag the sessions",
            file=sys.stderr,
        )
        return 1
    if listing and (by is not None or sets or rationales):
        print("review refused, --list takes no --by, --set, or --rationale", file=sys.stderr)
        return 1
    if not listing and by is None:
        print("review refused, name the person who reviewed with --by", file=sys.stderr)
        return 1
    store = open_store(home)
    try:
        if listing:
            pending = unreviewed(store)
        else:
            outcome = review(store, name, by, dict(sets), dict(rationales))
    except ReviewError as error:
        print(f"review refused, {error}", file=sys.stderr)
        return 1
    finally:
        store.db.close()
    if not listing:
        if outcome.changed:
            print(f"reviewed {outcome.session_id}, changed {', '.join(outcome.changed)}")
        else:
            print(f"reviewed {outcome.session_id}, every value kept")
        return 0
    # Each session is named by its id and never by a path.
    for item in pending:
        row = item.session
        print(row["harness_session_id"])
        print(f"  title {row['title'] or ''}")
        print(f"  gist {row['gist'] or ''}")
        print(f"  keywords {', '.join(row['keywords'] or [])}")
        for event in item.decisions:
            print(f"  decision {event['ordinal']} {event['rationale']}")
    verb = "awaits" if len(pending) == 1 else "await"
    print(f"{_count(len(pending), 'session')} {verb} review")
    return 0


def _no_store(home, what) -> bool:
    """Whether the home has no store, which is then said, for a command that adds to one."""
    if (home / DATABASE).is_file():
        return False
    print(
        f"{what} refused, there is no audit store at {home}. Run python3 -m audit_layer init",
        file=sys.stderr,
    )
    return True


def _sources_add_bib(home, path, session, reason) -> int:
    if _no_store(home, "sources add-bib"):
        return 1
    provenance = {
        "session": session,
        "origin": "bibtex export",
        "method": f"sources.add_from_bib {SOURCES_VERSION}; {Path(path).name}",
        "reason": reason,
    }
    store = open_store(home)
    try:
        summary = add_from_bib(store, path, provenance)
    except (OSError, ValueError) as error:
        # A BibError is a ValueError, as is a file that is not UTF-8 text.
        print(f"could not add the sources in {path}, {error}", file=sys.stderr)
        return 1
    finally:
        store.db.close()
    for key, why in summary.refused:
        print(f"refused {key}, {why}")
    print(
        f"added {_count(summary.added, 'source')}, {summary.unchanged} unchanged,"
        f" {summary.superseded} superseded, {len(summary.refused)} refused"
    )
    return 1 if summary.refused else 0


def _sources_list(home) -> int:
    if _no_store(home, "sources list"):
        return 1
    store = open_store(home)
    try:
        rows = current(store, "sources")
    finally:
        store.db.close()
    for row in rows:
        print(f"{row['citekey']}  {row['year']}  {row['retrieval_status']}  {row['title']}")
    print(_count(len(rows), "source"))
    return 0


def _sources_attach(home, citekey, path, method, date, session, reason) -> int:
    if _no_store(home, "sources attach"):
        return 1
    provenance = {
        "session": session,
        "origin": "retrieval",
        "method": f"sources.attach_original {SOURCES_VERSION}; {Path(path).name}",
        "reason": reason,
    }
    store = open_store(home)
    try:
        row_id = attach_original(store, citekey, path, method, date, provenance)
        (row,) = [r for r in current(store, "source_originals") if r["id"] == row_id]
    except (OSError, ValueError) as error:
        # A SourceError or a StoreError is a ValueError.
        print(f"sources attach refused, {error}", file=sys.stderr)
        return 1
    finally:
        store.db.close()
    print(
        f"attached {Path(path).name} to {citekey}, kept as {row['file_sha256'][:12]},"
        " status retrieved"
    )
    return 0


def _sources_text(home, citekey, kind, path, conversion, session, reason) -> int:
    if _no_store(home, "sources text"):
        return 1
    provenance = {
        "session": session,
        "origin": "text extraction",
        "method": f"sources.add_text {SOURCES_VERSION}; {Path(path).name}",
        "reason": reason,
    }
    store = open_store(home)
    try:
        add_text(store, citekey, kind, path, conversion, provenance)
    except (OSError, ValueError) as error:
        # A file that is not UTF-8 text is a ValueError, as a SourceError is.
        print(f"sources text refused, {error}", file=sys.stderr)
        return 1
    finally:
        store.db.close()
    print(f"added the {kind} text of {citekey}")
    return 0


def _codebook_file(path):
    """The descriptions a codebook YAML file maps each variable to."""
    loaded = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError(f"the codebook {Path(path).name} does not map variables to descriptions")
    for variable, description in loaded.items():
        if not isinstance(variable, str):
            raise ValueError(
                f"the codebook names the variable {variable!r}, which YAML did not read as"
                " text. Put the name in quotes"
            )
        if description is not None and not isinstance(description, str):
            raise ValueError(f"the codebook's description of {variable} is not text")
    return {variable: description or "" for variable, description in loaded.items()}


def _data_add(home, name, path, collected, codebook, session, reason) -> int:
    if _no_store(home, "data add"):
        return 1
    provenance = {
        "session": session,
        "origin": "data file",
        "method": f"data.add_dataset {DATA_VERSION}; {Path(path).name}",
        "reason": reason,
    }
    try:
        descriptions = _codebook_file(codebook) if codebook else None
    except (OSError, ValueError) as error:
        print(f"data add refused, {error}", file=sys.stderr)
        return 1
    except yaml.YAMLError as error:
        print(f"data add refused, the codebook cannot be read as YAML, {error}", file=sys.stderr)
        return 1
    store = open_store(home)
    try:
        catalog = add_dataset(store, name, path, collected, descriptions, provenance)
        variables = len(current(store, "codebook", dataset=catalog["id"]))
    except (OSError, ValueError) as error:
        # A DataError is a ValueError, as is a file that is not UTF-8 text.
        print(f"data add refused, {error}", file=sys.stderr)
        return 1
    finally:
        store.db.close()
    print(
        f"added {name} version {catalog['version']}, {_count(catalog['row_count'], 'row')},"
        f" {_count(variables, 'variable')}"
    )
    return 0


def _data_list(home) -> int:
    if _no_store(home, "data list"):
        return 1
    store = open_store(home)
    try:
        rows = current(store, "datasets")
    finally:
        store.db.close()
    for row in rows:
        print(
            f"{row['name']}  version {row['version']}  {_count(row['row_count'], 'row')}"
            f"  collected {row['collected_on']}"
        )
    print(_count(len(rows), "dataset"))
    return 0


def _knowledge_sync(home, corpus, session, reason) -> int:
    if _no_store(home, "knowledge sync"):
        return 1
    provenance = {
        "session": session,
        "origin": "entry files",
        "method": f"knowledge.sync {KNOWLEDGE_VERSION}; {Path(corpus).name}",
        "reason": reason,
    }
    store = open_store(home)
    try:
        summary = knowledge_sync(store, [corpus], provenance)
    except (OSError, ValueError) as error:
        # A KnowledgeError is a ValueError. A file that is not UTF-8 text is
        # among the problems and does not stop the sync.
        print(f"knowledge sync refused, {error}", file=sys.stderr)
        return 1
    finally:
        store.db.close()
    for name, problem in summary.problems:
        print(f"not synced {name}, {problem}")
    entries = "entry" if summary.added == 1 else "entries"
    line = f"added {summary.added} {entries}, {summary.unchanged} unchanged, {summary.replaced} replaced"
    if summary.problems:
        line += f", {len(summary.problems)} not synced"
    print(line)
    return 1 if summary.problems else 0


def _knowledge_history(home, entry_id) -> int:
    if _no_store(home, "knowledge history"):
        return 1
    store = open_store(home)
    try:
        versions = knowledge_history(store, entry_id)
    finally:
        store.db.close()
    if not versions:
        print(f"knowledge history refused, the store holds no entry {entry_id}", file=sys.stderr)
        return 1
    for number, version in enumerate(versions, start=1):
        mark = "  current" if number == len(versions) else ""
        print(
            f"{version['created_at']}  {version['source_checksum']}  {version['title']}{mark}"
        )
    print(_count(len(versions), "version"))
    return 0


def _projects(home) -> int:
    if _no_store(home, "projects"):
        return 1
    store = open_store(home)
    try:
        listed = list_projects(store)
    finally:
        store.db.close()
    for item in listed:
        row = item.project
        print(f"{row['folder']}  {row['name']}  {_count(item.sessions, 'session')}")
    print(_count(len(listed), "project"))
    return 0


def _fields(home, table) -> int:
    if _no_store(home, "fields"):
        return 1
    store = open_store(home)
    try:
        rows = current(store, "field_definitions")
    finally:
        store.db.close()
    if table is not None:
        rows = [row for row in rows if row["table_name"] == table]
        if not rows:
            print(f"fields refused, the store defines no table {table}", file=sys.stderr)
            return 1
    for row in rows:
        print(f"{row['table_name']}.{row['field']}")
        print(f"  {row['definition']}")
        print(f"  generated by {row['generation_rule']}")
        print(f"  {row['null_behavior']}")
    print(_count(len(rows), "field"))
    return 0


def _print_summary(summary) -> None:
    """Print a line for the session, then one for each subagent captured with it."""
    print(_describe(summary))
    for subagent in summary.subagents:
        print(_describe_subagent(subagent))


def _write_out_citation_log(home, project, out) -> int:
    # Writing out only reads the store, so a home with no store is refused
    # rather than made.
    if not (home / DATABASE).is_file():
        print(
            f"write-out refused, there is no audit store at {home}. Run python3 -m audit_layer"
            " init, then capture the project's sessions",
            file=sys.stderr,
        )
        return 1
    store = open_store(home)
    try:
        sessions = project_sessions(store, project)
        log = write_citation_log(store, project, out)
    except (OSError, ValueError) as error:
        print(f"could not write out the citation log, {error}", file=sys.stderr)
        return 1
    finally:
        store.db.close()
    citations = _count(len(log["citations"]), "citation")
    print(
        f"wrote {out}, {citations} from {_count(len(sessions), 'session')}"
        f" recorded in {os.path.realpath(project)}"
    )
    return 0


def _write_out_citation_provenance(home, project, references, artifacts, out, fetched=()) -> int:
    # As for the citation log, a home with no store is refused rather than made.
    if not (home / DATABASE).is_file():
        print(
            f"write-out refused, there is no audit store at {home}. Run python3 -m audit_layer"
            " init, then capture the project's sessions",
            file=sys.stderr,
        )
        return 1
    named = list(artifacts) + list(fetched)
    missing = [path for path in named if not (os.path.isdir(path) or os.path.isfile(path))]
    if missing:
        print(f"write-out refused, {missing[0]} is not a folder or a file", file=sys.stderr)
        return 1
    # An excluded folder is never read, so an artifacts folder or file inside one is
    # refused. Capture needs the settings file, so a home whose store holds sessions has one.
    if (home / SETTINGS).is_file():
        try:
            settings = read_settings(home)
        except SettingsError as error:
            print(f"write-out refused, {error}", file=sys.stderr)
            return 1
        inside = [path for path in named if is_excluded(path, settings)]
        if inside:
            print(
                f"write-out refused, {inside[0]} is inside an excluded folder, which is never read",
                file=sys.stderr,
            )
            return 1
    store = open_store(home)
    try:
        works = read_references(references)
        record = write_citation_provenance(store, project, works, artifacts, out, fetched)
    except (OSError, ValueError) as error:
        print(f"could not write out the citation provenance, {error}", file=sys.stderr)
        return 1
    finally:
        store.db.close()
    origins = [entry["origin"] for entry in record["works"].values()]
    print(
        f"wrote {out}, {_count(len(origins), 'work')}, {origins.count('ai')} first named by an AI,"
        f" {origins.count('scholar')} first named by the scholar,"
        f" {origins.count('unknown')} never named in the record"
    )
    return 0


def _write_out_session_writes(home, project, out) -> int:
    # As for the citation log, a home with no store is refused rather than made.
    if not (home / DATABASE).is_file():
        print(
            f"write-out refused, there is no audit store at {home}. Run python3 -m audit_layer"
            " init, then capture the project's sessions",
            file=sys.stderr,
        )
        return 1
    store = open_store(home)
    try:
        rows = session_writes(store, project)
        write_session_writes(rows, out)
    except (OSError, ValueError) as error:
        print(f"could not write out the file writes, {error}", file=sys.stderr)
        return 1
    finally:
        store.db.close()
    print(f"wrote {out}, {_count(len(rows), 'file write')} recorded in {os.path.realpath(project)}")
    return 0


def _write_out_rationales(home, project, source, out) -> int:
    # As for the citation log, a home with no store is refused rather than made.
    if not (home / DATABASE).is_file():
        print(
            f"write-out refused, there is no audit store at {home}. Run python3 -m audit_layer"
            " init, then capture the project's sessions",
            file=sys.stderr,
        )
        return 1
    path = os.path.join(project, source)
    store = open_store(home)
    try:
        entries = rationales(store, path)
        write_rationales(entries, out)
    except (OSError, ValueError) as error:
        print(f"could not write out the rationales, {error}", file=sys.stderr)
        return 1
    finally:
        store.db.close()
    print(f"wrote {out}, {_count(len(entries), 'rationale')} for {os.path.realpath(path)}")
    return 0


def _write_out_file_edits(home, project, out) -> int:
    # As for the citation log, a home with no store is refused rather than made.
    if not (home / DATABASE).is_file():
        print(
            f"write-out refused, there is no audit store at {home}. Run python3 -m audit_layer"
            " init, then capture the project's sessions",
            file=sys.stderr,
        )
        return 1
    store = open_store(home)
    try:
        entries = file_edits(store, project)
        write_file_edits(entries, out)
    except (OSError, ValueError) as error:
        print(f"could not write out the file edits, {error}", file=sys.stderr)
        return 1
    finally:
        store.db.close()
    print(f"wrote {out}, {_count(len(entries), 'file edit')} recorded in {os.path.realpath(project)}")
    return 0


def _named(given):
    """The comma-separated names given to an option, each once, blanks dropped."""
    return [part.strip() for part in (given or "").split(",") if part.strip()]


def _dataset_versions(given):
    """Each NAME[:VERSION] given as a name and a version, None for the latest.

    A version that is not a whole number from 1 raises ValueError.
    """
    versions = []
    for part in _named(given):
        name, mark, version = part.rpartition(":")
        if not mark:
            versions.append((part, None))
            continue
        if not re.fullmatch(r"[0-9]+", version) or int(version) < 1:
            raise ValueError(f"{version!r} in {part} is not a version, which is a whole number from 1")
        versions.append((name, int(version)))
    return versions


def _write_out_project(home, project, out, sources=None, datasets=None, knowledge=False) -> int:
    try:
        versions = _dataset_versions(datasets)
    except ValueError as error:
        print(f"write-out refused, {error}", file=sys.stderr)
        return 1
    # Writing out only reads the store, so a home with no store is refused
    # rather than made.
    if not (home / DATABASE).is_file():
        print(
            f"write-out refused, there is no audit store at {home}. Run python3 -m audit_layer"
            " init, then capture the project's sessions",
            file=sys.stderr,
        )
        return 1
    store = open_store(home)
    try:
        files = write_out_project(store, project, out, _named(sources), versions, knowledge)
    except (OSError, ValueError) as error:
        # A WriteOutError is a ValueError.
        print(f"write-out refused, {error}", file=sys.stderr)
        return 1
    finally:
        store.db.close()
    print(f"wrote {out}, {_count(len(files), 'file')} listed in {WRITTEN_OUT}")
    return 0


def _write_out_session_index(home, project, out, results, no_summaries, withhold, scrub, also=()) -> int:
    # As for the citation log, a home with no store is refused rather than made.
    if not (home / DATABASE).is_file():
        print(
            f"write-out refused, there is no audit store at {home}. Run python3 -m audit_layer"
            " init, then capture the project's sessions",
            file=sys.stderr,
        )
        return 1
    store = open_store(home)
    try:
        withheld = read_list(withhold, "withhold list") if withhold else []
        terms = read_list(scrub, "scrub list") if scrub else []
        index = write_session_index(
            store, project, out, results, not no_summaries, withheld, terms, also=also
        )
    except (OSError, ValueError) as error:
        # A SessionIndexError is a ValueError.
        print(f"write-out refused, {error}", file=sys.stderr)
        return 1
    finally:
        store.db.close()
    for path in index.set_aside:
        print(f"set aside {path}, since a later results file of its stream was given")
    for ref in index.unlisted:
        print(f"the results files name session {ref}, which the index does not list")
    contributing = sum(1 for row in index.rows if row["contributions"])
    print(
        f"wrote {out}, {_count(len(index.rows), 'session')},"
        f" {contributing} with an AI contribution in the final reports"
    )
    return 0


def _describe(summary) -> str:
    if summary.excluded:
        return f"skipped {summary.path}, its session ran in an excluded folder, and nothing was stored"
    if summary.folder_unknown:
        return (
            f"skipped {summary.path}, session {summary.session_id},"
            " working folder unknown, and nothing was stored"
        )
    return f"captured {summary.path}, session {summary.session_id}, {_added(summary)}"


def _describe_subagent(summary) -> str:
    """A line for a subagent conversation captured with its main session file.

    It names the subagent conversation by its id, and never by its file's
    path, whose folder names spell out the folder the session ran in.
    """
    if summary.excluded:
        return (
            "skipped a subagent conversation, it ran in an excluded folder,"
            " and nothing was stored"
        )
    if summary.folder_unknown:
        return (
            f"skipped subagent session {summary.session_id},"
            " working folder unknown, and nothing was stored"
        )
    return f"captured subagent session {summary.session_id}, {_added(summary)}"


def _added(summary) -> str:
    """What one capture stored, as the rows it added, else nothing new."""
    if summary.sessions or summary.events or summary.transcripts:
        added = ", ".join(
            [
                _count(summary.sessions, "session row"),
                _count(summary.events, "event"),
                _count(summary.transcripts, "transcript"),
            ]
        )
        return f"added {added}"
    return "nothing new"


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"
