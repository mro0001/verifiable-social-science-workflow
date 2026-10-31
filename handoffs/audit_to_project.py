"""Copy one record the audit layer wrote out into a project's audit folder.

    python3 handoffs/audit_to_project.py --record {citation_log,session_writes,rationales}
        --from FILE --project DIR

The file is copied byte for byte to DIR/audit/citation_log.yaml,
DIR/audit/session_writes.jsonl, or DIR/audit/rationales.yaml, replacing an older
copy. The audit layer writes the record to FILE first (its write-out command), so
the audit layer never writes into a project and this script never reads the
record's content. It is a plain copy kept in handoffs/ for a scholar to replace when
they connect the layers. No layer's code calls it. Standard library only.
"""
import argparse
import os
import shutil
import sys

RECORDS = {
    "citation_log": "citation_log.yaml",
    "session_writes": "session_writes.jsonl",
    "rationales": "rationales.yaml",
}


def refuse(message):
    print(message, file=sys.stderr)
    return 2


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="audit_to_project.py",
        description="Copy a written-out audit record into a project's audit folder.")
    parser.add_argument("--record", required=True, choices=sorted(RECORDS),
                        help="which record the file holds")
    parser.add_argument("--from", dest="source", required=True,
                        help="the file the audit layer wrote out")
    parser.add_argument("--project", required=True, help="the project folder")
    args = parser.parse_args(argv)

    if not os.path.isfile(args.source):
        return refuse("no record file at %s" % args.source)
    if not os.path.isdir(args.project):
        return refuse("no project folder at %s" % args.project)

    audit = os.path.join(args.project, "audit")
    os.makedirs(audit, exist_ok=True)
    dest = os.path.join(audit, RECORDS[args.record])
    shutil.copyfile(args.source, dest)
    print(dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
