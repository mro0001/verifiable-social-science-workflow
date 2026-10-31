"""Copy a project's session index into the project's sessions/ folder.

    python3 handoffs/session_index_to_project.py --from DIR --project DIR

The --from folder is the one python3 -m audit_layer write-out session-index
--project DIR --out DIR wrote. It is copied whole, byte for byte, into
<project>/sessions/, replacing an older copy, so the folder a public repository
shows always holds the latest index and no page of an older one. This script
never reads the index's content.

It refuses when the --from folder is missing, is empty, or lacks the index's own
table, sessions.csv, when the project folder is missing, when <project>/sessions
is a file, or holds files but no sessions.csv, so it is not an older copy, and
when --from is <project>/sessions itself or a folder inside it. A refusal exits 2
and writes nothing. It is a plain copy kept in handoffs/ for a scholar to replace
when they connect the layers. No layer's code calls it. Standard library only.
"""
import argparse
import os
import shutil
import sys

TABLE = "sessions.csv"
FOLDER = "sessions"


def refuse(message):
    print(message, file=sys.stderr)
    return 2


def holds_files(folder):
    for _, _, files in os.walk(folder):
        if files:
            return True
    return False


def inside(path, folder):
    path, folder = os.path.realpath(path), os.path.realpath(folder)
    return path == folder or path.startswith(folder + os.sep)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="session_index_to_project.py",
        description="Copy a project's session index into the project's sessions/ folder.")
    parser.add_argument("--from", dest="source", required=True,
                        help="the folder write-out session-index wrote")
    parser.add_argument("--project", required=True, help="the project folder")
    args = parser.parse_args(argv)

    if not os.path.isdir(args.source):
        return refuse("missing session index folder %s" % args.source)
    if not holds_files(args.source):
        return refuse("the session index folder %s is empty" % args.source)
    if not os.path.isfile(os.path.join(args.source, TABLE)):
        return refuse("missing %s, so %s is not a session index"
                      % (os.path.join(args.source, TABLE), args.source))
    if not os.path.isdir(args.project):
        return refuse("no project folder at %s" % args.project)
    dest = os.path.join(args.project, FOLDER)
    if os.path.lexists(dest) and not os.path.isdir(dest):
        return refuse("%s is a file, not a folder" % dest)
    if inside(args.source, dest):
        return refuse("the session index %s is the project's own copy in %s"
                      % (args.source, dest))
    if os.path.isdir(dest) and holds_files(dest) and not os.path.isfile(
            os.path.join(dest, TABLE)):
        return refuse("%s holds files but no %s, so it is not an older copy of the index"
                      % (dest, TABLE))

    # The new copy is made beside the older one and then put in its place, so
    # a copy that fails partway leaves the older copy as it was.
    staging = os.path.join(args.project, ".%s.new-%d" % (FOLDER, os.getpid()))
    try:
        shutil.copytree(args.source, staging)
    except OSError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    os.rename(staging, dest)
    print(dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
