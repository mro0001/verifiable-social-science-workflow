"""Copy a project's drafts and its AI rationales record, with the pin the scholar
keeps, into one inputs folder for a run of the prose procedure.

    python3 handoffs/project_to_prose.py --project DIR --prose DIR --to DIR
        [--source FILE]

From the project it copies author_draft.md as baseline.md, the source text (FILE,
manuscript.md by default) as revised.md, and audit/rationales.yaml as
rationales.yaml. From the prose folder it copies versions.yaml. Nothing else is
copied, so expected files kept beside it stay out of the run. Since version 0.3 the
procedure reads no list of the author's own edits, since a change the record does not
name is the scholar's (Track V, step V4). These are the files the procedure's
pin_versions, exclude_author, and rationale_coverage steps read. The source text
lands as revised.md byte for byte, which puts its checksum among the run's inputs,
and that is how the build tells that a prose result is current.

It refuses when the --to folder already exists, since a run's inputs are fixed,
and when any of the files above is missing, naming each one. A refusal exits 2 and
writes nothing. It is a plain copy kept in handoffs/ for a scholar to replace when they
connect the layers. No layer's code calls it. Standard library only.
"""
import argparse
import os
import shutil
import sys

PROSE_FILES = ("versions.yaml",)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="project_to_prose.py",
        description="Copy a project's drafts and rationales into the prose procedure's inputs folder.")
    parser.add_argument("--project", required=True, help="the project folder")
    parser.add_argument("--prose", required=True,
                        help="the folder holding the pin the scholar keeps")
    parser.add_argument("--to", required=True, help="the inputs folder to create")
    parser.add_argument("--source", default="manuscript.md",
                        help="the source text in the project (default manuscript.md)")
    args = parser.parse_args(argv)

    if os.path.exists(args.to):
        print("the inputs folder %s already exists, and a run's inputs are fixed" % args.to,
              file=sys.stderr)
        return 2

    copies = [
        (os.path.join(args.project, "author_draft.md"), "baseline.md"),
        (os.path.join(args.project, args.source), "revised.md"),
        (os.path.join(args.project, "audit", "rationales.yaml"), "rationales.yaml"),
    ]
    copies += [(os.path.join(args.prose, name), name) for name in PROSE_FILES]
    missing = [src for src, _ in copies if not os.path.isfile(src)]
    if missing:
        for src in missing:
            print("missing %s" % src, file=sys.stderr)
        return 2

    os.makedirs(args.to)
    for src, name in copies:
        shutil.copyfile(src, os.path.join(args.to, name))
    print(args.to)
    return 0


if __name__ == "__main__":
    sys.exit(main())
