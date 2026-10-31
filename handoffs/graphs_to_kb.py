"""Copy the verification layer's graphs, contracts, and registry into a new folder
the knowledge base reads.

    python3 handoffs/graphs_to_kb.py --procedures DIR --to DIR

It copies graphs/, contracts/, and registry.yaml from the procedures folder
(normally verification_procedures), byte for byte and nothing else, into a new
folder. These are the three things the knowledge base's graph-entries command
reads, so the next step is

    python3 -m audit_layer.kb graph-entries --procedures <the --to folder>

It refuses when the --to folder already exists, and when the procedures folder
lacks any of the three, naming each one. A refusal exits 2 and writes nothing. It
is a plain copy kept in handoffs/ for a scholar to replace when they connect the
layers. No layer's code calls it. Standard library only.
"""
import argparse
import os
import shutil
import sys

FOLDERS = ("graphs", "contracts")
REGISTRY = "registry.yaml"


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="graphs_to_kb.py",
        description="Copy the procedures' graphs, contracts, and registry for the knowledge base.")
    parser.add_argument("--procedures", required=True,
                        help="the verification layer's folder, normally verification_procedures")
    parser.add_argument("--to", required=True, help="the new folder to create")
    args = parser.parse_args(argv)

    if os.path.exists(args.to):
        print("the folder %s already exists" % args.to, file=sys.stderr)
        return 2
    if not os.path.isdir(args.procedures):
        print("missing procedures folder %s" % args.procedures, file=sys.stderr)
        return 2

    missing = [os.path.join(args.procedures, name) for name in FOLDERS
               if not os.path.isdir(os.path.join(args.procedures, name))]
    if not os.path.isfile(os.path.join(args.procedures, REGISTRY)):
        missing.append(os.path.join(args.procedures, REGISTRY))
    if missing:
        for path in missing:
            print("missing %s" % path, file=sys.stderr)
        return 2

    os.makedirs(args.to)
    for name in FOLDERS:
        shutil.copytree(os.path.join(args.procedures, name), os.path.join(args.to, name))
    shutil.copyfile(os.path.join(args.procedures, REGISTRY), os.path.join(args.to, REGISTRY))
    print(args.to)
    return 0


if __name__ == "__main__":
    sys.exit(main())
