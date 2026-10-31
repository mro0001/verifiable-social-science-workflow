"""Copy the knowledge base's export to the file the knowledge base server reads.

    python3 handoffs/kb_export_to_server.py --export FILE --to FILE

The export is the file python3 -m audit_layer.kb export --out FILE wrote. The --to
file is the one the server's required --index option names, as in
python3 -m connections serve kb --index FILE. The file is copied byte for byte,
replacing an older copy, and this script never reads its content.

It refuses when the export file is missing, when the --to file's folder does not
exist, and when --to names a folder. A refusal exits 2 and writes nothing. It is a
plain copy kept in handoffs/ for a scholar to replace when they connect the layers. No
layer's code calls it. Standard library only.
"""
import argparse
import os
import shutil
import sys


def refuse(message):
    print(message, file=sys.stderr)
    return 2


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="kb_export_to_server.py",
        description="Copy the knowledge base's export to the server's index file.")
    parser.add_argument("--export", required=True,
                        help="the file python3 -m audit_layer.kb export wrote")
    parser.add_argument("--to", required=True,
                        help="the file the server's --index option names")
    args = parser.parse_args(argv)

    if not os.path.isfile(args.export):
        return refuse("no export file at %s" % args.export)
    folder = os.path.dirname(os.path.abspath(args.to))
    if not os.path.isdir(folder):
        return refuse("no folder %s for the index file" % folder)
    if os.path.isdir(args.to):
        return refuse("%s is a folder, not the index file" % args.to)

    shutil.copyfile(args.export, args.to)
    print(args.to)
    return 0


if __name__ == "__main__":
    sys.exit(main())
