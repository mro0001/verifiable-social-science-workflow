"""The knowledge base's command line, run as python3 -m audit_layer.kb."""
import argparse
import datetime

from audit_layer.kb import CORPUS
from audit_layer.kb.check import check_corpus
from audit_layer.kb.entries import entry_files
from audit_layer.kb.graph_entries import sync
from audit_layer.kb.index import write_export, write_llms
from audit_layer.kb.sources import STATUSES, counts, source_status

CORPUS_HELP = "the corpus folder, else the knowledge base's own corpus"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="audit_layer.kb")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="check every entry and the index against the entry rules")
    check.add_argument("--corpus", default=str(CORPUS), metavar="DIR", help=CORPUS_HELP)

    llms = sub.add_parser("llms", help="rewrite the index llms.txt from the corpus")
    llms.add_argument("--corpus", default=str(CORPUS), metavar="DIR", help=CORPUS_HELP)

    export = sub.add_parser("export", help="write every entry to one JSON file, kb-index version 1")
    export.add_argument("--out", required=True, metavar="FILE", help="the JSON file to write")
    export.add_argument("--corpus", default=str(CORPUS), metavar="DIR", help=CORPUS_HELP)

    graphs = sub.add_parser(
        "graph-entries", help="bring the PROCEDURES group in step with the procedural graphs"
    )
    graphs.add_argument(
        "--procedures", required=True, metavar="DIR",
        help="a folder holding graphs/, contracts/, and any registry.yaml",
    )
    graphs.add_argument("--corpus", default=str(CORPUS), metavar="DIR", help=CORPUS_HELP)
    graphs.add_argument("--date", metavar="YYYY-MM-DD", help="the date a written entry carries, else today")
    graphs.add_argument("--check", action="store_true", help="write nothing and exit 1 when an entry is stale")

    sources = sub.add_parser(
        "source-check", help="compare each entry's recorded source checksum with the file under a root"
    )
    sources.add_argument(
        "--root", required=True, metavar="DIR", help="the folder each entry's source is read under"
    )
    sources.add_argument("--corpus", default=str(CORPUS), metavar="DIR", help=CORPUS_HELP)

    args = parser.parse_args(argv)
    if args.command == "check":
        return _check(args.corpus)
    if args.command == "llms":
        print("rewrote" if write_llms(args.corpus) else "unchanged")
        return 0
    if args.command == "export":
        write_export(args.corpus, args.out)
        return 0
    if args.command == "graph-entries":
        return _graph_entries(args)
    if args.command == "source-check":
        return _source_check(args.corpus, args.root)
    return 2


def _source_check(corpus, root) -> int:
    rows = source_status(corpus, root)
    for row in rows:
        print("{} {} {}".format(row["status"], row["id"], row["source"]))
    found = counts(rows)
    print("{} entries, {}".format(len(rows), ", ".join("{} {}".format(found[s], s) for s in STATUSES)))
    return 1 if found["changed"] else 0


def _graph_entries(args) -> int:
    date = args.date or datetime.date.today().isoformat()
    try:
        result = sync(args.procedures, args.corpus, date, check_only=args.check)
    except (OSError, ValueError) as error:
        print("FAIL {}".format(error))
        return 1
    for kind in ("added", "changed", "removed"):
        for ident in result[kind]:
            print("{} {}".format(kind, ident))
    if args.check and (result["added"] or result["changed"] or result["removed"]):
        return 1
    return 0


def _check(corpus) -> int:
    problems = check_corpus(corpus)
    if not problems:
        print("OK: {} entries".format(len(entry_files(corpus))))
        return 0
    print("FAIL ({})".format(len(problems)))
    for problem in problems:
        print(problem)
    return 1
