"""Copy the folder the audit layer wrote out for a project into a folder of the
project.

    python3 handoffs/writeout_to_project.py --from DIR --to DIR

The --from folder is the one python3 -m audit_layer write-out project --out DIR
wrote. It is copied whole, byte for byte, into a new or empty folder the scholar
names inside the project, such as <project>/records. A new folder is used so the
copy never overwrites or mixes with the project's own files. The pipeline reads
only the three records in audit/ that audit_to_project.py copies, so this copy is
for the scholar and the project's own record.

It refuses when the --from folder lacks the write-out's own list file,
written_out.yaml, and when the --to folder holds anything or is a file. A refusal
exits 2 and writes nothing. It is a plain copy kept in handoffs/ for a scholar to
replace when they connect the layers. No layer's code calls it. Standard library
only.
"""
import argparse
import os
import shutil
import sys

LIST_FILE = "written_out.yaml"


def refuse(message):
    print(message, file=sys.stderr)
    return 2


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="writeout_to_project.py",
        description="Copy a project's written-out records into a folder of the project.")
    parser.add_argument("--from", dest="source", required=True,
                        help="the folder write-out project wrote")
    parser.add_argument("--to", required=True, help="the new or empty folder to copy into")
    args = parser.parse_args(argv)

    if not os.path.isdir(args.source):
        return refuse("missing written-out folder %s" % args.source)
    if not os.path.isfile(os.path.join(args.source, LIST_FILE)):
        return refuse("missing %s, so %s is not a written-out folder"
                      % (os.path.join(args.source, LIST_FILE), args.source))
    if os.path.exists(args.to):
        if not os.path.isdir(args.to):
            return refuse("%s is a file, not a folder" % args.to)
        if os.listdir(args.to):
            return refuse("the folder %s is not empty" % args.to)

    shutil.copytree(args.source, args.to, dirs_exist_ok=True)
    print(args.to)
    return 0


if __name__ == "__main__":
    sys.exit(main())
