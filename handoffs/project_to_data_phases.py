"""Copy a project's pipeline, each script and helper it names, and the final build's
text into one inputs folder for a run of the data collection, cleaning, and analysis
reports.

    python3 handoffs/project_to_data_phases.py --project DIR --to DIR
        [--builds-dir DIR ...]

It copies pipeline.yaml, and each step's script and each helper pipeline.yaml names at
its path inside the project, so a script in a subfolder is found. The final build is
the latest build in the product's ledger, the highest version listed in BUILDS.md in the
builds folder (DIR inside the project, builds/manuscript by default). Its filled-in text,
vNNN.md beside the ledger, is copied as final_text.md, the text the reports quote (Track
V, plan choice 1). When a project has several products, such as a manuscript and an
appendix built apart, --builds-dir is given once for each, and the latest build's text of
each is joined in the order given, with one blank line between them. Nothing else is
copied, so recorded answers and the builds themselves stay out of the run.

It reads the ledger only to find the latest version. It refuses when the --to folder
already exists, since a run's inputs are fixed, when pipeline.yaml is missing or cannot be
read as YAML, when a script or helper it names is missing or lies outside the project, and
when a ledger is missing, lists no build, or its latest build's text is missing, naming
each problem. A refusal exits 2 and writes nothing. It is a plain copy kept in handoffs/
for a scholar to replace when they connect the layers. No layer's code calls it.
Standard library and PyYAML.
"""
import argparse
import os
import re
import shutil
import sys

from project_to_data import pipeline_files

LEDGER = "BUILDS.md"
TEXT = "final_text.md"
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


def latest_text(project, builds_dir):
    """(path, problem). path is the latest build's text in the builds folder, and problem
    a message when the ledger or that text cannot be had."""
    builds = os.path.join(project, builds_dir)
    ledger = os.path.join(builds, LEDGER)
    if not os.path.isfile(ledger):
        return None, "missing %s, the ledger that names the final build" % ledger
    version = latest_version(ledger)
    if version is None:
        return None, "the ledger %s lists no build, so there is no final build to read" % ledger
    path = os.path.join(builds, version + ".md")
    if not os.path.isfile(path):
        return None, "missing %s, the filled-in text of the latest build %s" % (path, version)
    return path, None


def joined(paths):
    """The texts at paths, in order, with one blank line between each two."""
    parts = []
    for path in paths:
        with open(path, "rb") as f:
            parts.append(f.read())
    out = b""
    for n, data in enumerate(parts):
        if n:
            out += b"\n" if out.endswith(b"\n") else b"\n\n"
        out += data
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="project_to_data_phases.py",
        description="Copy a project's pipeline, its scripts and helpers, and the final build's "
                    "text into the inputs folder of the data phase reports.")
    parser.add_argument("--project", required=True, help="the project folder")
    parser.add_argument("--to", required=True, help="the inputs folder to create")
    parser.add_argument("--builds-dir", dest="builds_dirs", action="append", metavar="DIR",
                        help="a product's builds folder in the project, which holds its ledger "
                             "BUILDS.md (default builds/manuscript). Give it once for each product "
                             "whose text the reports read, in the order the texts are joined")
    args = parser.parse_args(argv)

    if os.path.exists(args.to):
        print("the inputs folder %s already exists, and a run's inputs are fixed" % args.to,
              file=sys.stderr)
        return 2
    if not os.path.isdir(args.project):
        print("missing project folder %s" % args.project, file=sys.stderr)
        return 2

    problems, scripts = [], []
    if os.path.isfile(os.path.join(args.project, "pipeline.yaml")):
        scripts, problems = pipeline_files(args.project)
    else:
        problems.append("missing %s" % os.path.join(args.project, "pipeline.yaml"))
    texts = []
    for builds_dir in args.builds_dirs or [os.path.join("builds", "manuscript")]:
        path, problem = latest_text(args.project, builds_dir)
        if problem:
            problems.append(problem)
        else:
            texts.append(path)
    if TEXT in scripts:
        problems.append("pipeline.yaml names a script %s, where the final build's text lands" % TEXT)
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        return 2

    text = joined(texts)
    os.makedirs(args.to)
    shutil.copyfile(os.path.join(args.project, "pipeline.yaml"), os.path.join(args.to, "pipeline.yaml"))
    for name in scripts:
        dest = os.path.join(args.to, name)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(os.path.join(args.project, name), dest)
    with open(os.path.join(args.to, TEXT), "wb") as f:
        f.write(text)
    print(args.to)
    return 0


if __name__ == "__main__":
    sys.exit(main())
