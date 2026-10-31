"""Copy the final build's text, the citation provenance record, and the scholar's
references folder into one inputs folder for a run of the references procedure.

    python3 handoffs/project_to_references.py --project DIR --references DIR
        --provenance FILE --to DIR [--builds-dir DIR] [--source FILE]

The final build is the latest build in the product's ledger, the highest version
listed in BUILDS.md in the builds folder (DIR inside the project,
builds/manuscript by default). Its filled-in text, vNNN.md beside the ledger, is
copied as draft.md, so a citation removed before that build is not read (Track
C2, plan choice 1). The source text (FILE inside the project, manuscript.md by
default) is copied under its own name, so the run lists its checksum among its
inputs and the build can tell the results are for the current source text. The
citation provenance record, the file python3 -m audit_layer write-out
citation-provenance wrote, is copied as citation_provenance.yaml. From the
references folder it copies refs.yaml, metadata_cache.json, and every
source_*.txt. Nothing else is copied, so recorded answers and expected files
kept beside the references stay out of the run. These are the files the
procedure's pin_document and pin_sources steps read.

It reads the ledger only to find the latest version. It refuses when the --to
folder already exists, since a run's inputs are fixed, when the ledger is missing
or lists no build, when any of the files above is missing, naming each one, and
when the source text's name is the name of another input. A refusal exits 2 and
writes nothing. It is a plain copy kept in handoffs/ for a scholar to replace
when they connect the layers. No layer's code calls it. Standard library only.
"""
import argparse
import glob
import os
import re
import shutil
import sys

REFERENCE_FILES = ("refs.yaml", "metadata_cache.json")
LEDGER = "BUILDS.md"
VERSION = re.compile(r"v(\d{3,})$")


def latest_version(ledger):
    """The highest vNNN version the ledger's rows list, or None when it lists none."""
    best = None
    with open(ledger, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not (line.startswith("|") and line.endswith("|")):
                continue
            first = line[1:-1].split("|")[0].strip()
            match = VERSION.match(first)
            if match and (best is None or int(match.group(1)) > int(best[1:])):
                best = first
    return best


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="project_to_references.py",
        description="Copy a project's final build text and records into the references "
                    "procedure's inputs folder.")
    parser.add_argument("--project", required=True, help="the project folder")
    parser.add_argument("--references", required=True,
                        help="the references folder the scholar keeps")
    parser.add_argument("--provenance", required=True,
                        help="the citation provenance record, the file python3 -m audit_layer "
                             "write-out citation-provenance wrote")
    parser.add_argument("--to", required=True, help="the inputs folder to create")
    parser.add_argument("--builds-dir", default=os.path.join("builds", "manuscript"),
                        help="the product's builds folder in the project, which holds its "
                             "ledger BUILDS.md (default builds/manuscript)")
    parser.add_argument("--source", default="manuscript.md",
                        help="the source text in the project (default manuscript.md)")
    args = parser.parse_args(argv)

    if os.path.exists(args.to):
        print("the inputs folder %s already exists, and a run's inputs are fixed" % args.to,
              file=sys.stderr)
        return 2

    builds = os.path.join(args.project, args.builds_dir)
    ledger = os.path.join(builds, LEDGER)
    if not os.path.isfile(ledger):
        print("missing %s, the ledger that names the final build" % ledger, file=sys.stderr)
        return 2
    version = latest_version(ledger)
    if version is None:
        print("the ledger %s lists no build, so there is no final build to read" % ledger,
              file=sys.stderr)
        return 2

    source_name = os.path.basename(args.source)
    copies = [
        (os.path.join(builds, version + ".md"), "draft.md"),
        (os.path.join(args.project, args.source), source_name),
        (args.provenance, "citation_provenance.yaml"),
    ]
    copies += [(os.path.join(args.references, name), name) for name in REFERENCE_FILES]
    for src in sorted(glob.glob(os.path.join(glob.escape(args.references), "source_*.txt"))):
        if os.path.isfile(src):
            copies.append((src, os.path.basename(src)))

    names = [name for _, name in copies]
    if names.count(source_name) > 1:
        print("the source text %s would land on the inputs name %s, which another input "
              "holds" % (args.source, source_name), file=sys.stderr)
        return 2
    missing = [src for src, _ in copies if not os.path.isfile(src)]
    if missing:
        for src in missing:
            if src == args.provenance:
                print("missing the citation provenance record %s. Write it with python3 -m "
                      "audit_layer write-out citation-provenance" % src, file=sys.stderr)
            else:
                print("missing %s" % src, file=sys.stderr)
        return 2

    os.makedirs(args.to)
    for src, name in copies:
        shutil.copyfile(src, os.path.join(args.to, name))
    print(args.to)
    return 0


if __name__ == "__main__":
    sys.exit(main())
