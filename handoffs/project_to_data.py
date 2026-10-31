"""Copy a project's top-level files, each script and helper its pipeline names, and the
record of the AI's file edits into one inputs folder for a run of the data procedure.

    python3 handoffs/project_to_data.py --project DIR --to DIR [--file-edits FILE]

It copies every regular file at the top level of the project, byte for byte. From the
project's subfolders it copies only each step's script and each helper that
pipeline.yaml names, at its path inside the project, so a script in a subfolder such
as code/s1_results.py is found (Track V, step V4). Nothing else below the top is
copied, so builds/, audit/, and verification/ stay out of the run. The numbers file is
among the copies, which puts its checksum among the run's inputs, and that is how the
build tells that a data result is current.

With --file-edits it copies the record of the AI's file edits, the file python3 -m
audit_layer write-out file-edits wrote, as file_edits.yaml. The data procedure reads it
to mark which scripts and parameters an AI wrote or changed. Without it the procedure
says no record was given.

It refuses when the --to folder already exists, since a run's inputs are fixed, when
the project lacks any of pipeline.yaml, acquisition.yaml, params.yaml, and numbers.yml,
when pipeline.yaml cannot be read as YAML, when a script or helper it names is missing
or lies outside the project, when the record named is missing, and when the project
holds a file_edits.yaml of its own beside the record, naming each problem. A refusal
exits 2 and writes nothing. It is a plain copy kept in handoffs/ for a scholar to
replace when they connect the layers. No layer's code calls it. Standard library and
PyYAML.
"""
import argparse
import os
import shutil
import sys

import yaml

DECLARATIONS = ("pipeline.yaml", "acquisition.yaml", "params.yaml", "numbers.yml")
RECORD = "file_edits.yaml"


def top_level_files(project):
    """The names of the regular files at the top of the project, sorted, leaving out
    links and folders."""
    names = []
    for name in sorted(os.listdir(project)):
        path = os.path.join(project, name)
        if os.path.isfile(path) and not os.path.islink(path):
            names.append(name)
    return names


def pipeline_files(project):
    """(names, problems). names are the scripts and helpers pipeline.yaml names, each
    once, in the order it names them, as paths inside the project with forward slashes.
    problems are messages for a pipeline file that cannot be read and for each name that
    is missing or lies outside the project."""
    path = os.path.join(project, "pipeline.yaml")
    try:
        with open(path, encoding="utf-8") as f:
            pipeline = yaml.safe_load(f)
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as error:
        return [], ["%s cannot be read as YAML, so its scripts are not known (%s)"
                    % (path, type(error).__name__)]
    pipeline = pipeline if isinstance(pipeline, dict) else {}
    helpers = pipeline.get("helpers") if isinstance(pipeline.get("helpers"), list) else []
    steps = pipeline.get("steps") if isinstance(pipeline.get("steps"), list) else []
    given = [h for h in helpers if isinstance(h, str)]
    given += [s.get("script") for s in steps if isinstance(s, dict) and isinstance(s.get("script"), str)]
    top = os.path.realpath(project)
    names, problems = [], []
    for name in given:
        name = name.strip()
        if not name or name in names:
            continue
        real = os.path.realpath(os.path.join(project, name))
        if os.path.isabs(name) or not real.startswith(top + os.sep):
            problems.append("pipeline.yaml names the script %s, which is outside the project %s"
                            % (name, project))
            continue
        full = os.path.join(project, name)
        if not os.path.isfile(full) or os.path.islink(full):
            problems.append("missing %s" % full)
            continue
        names.append(os.path.relpath(real, top).replace(os.sep, "/"))
    return names, problems


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="project_to_data.py",
        description="Copy a project's top-level files, its pipeline's scripts and helpers, "
                    "and the record of the AI's file edits into the data procedure's inputs folder.")
    parser.add_argument("--project", required=True, help="the project folder")
    parser.add_argument("--to", required=True, help="the inputs folder to create")
    parser.add_argument("--file-edits", dest="file_edits", metavar="FILE",
                        help="the record of the AI's file edits, the file python3 -m audit_layer "
                             "write-out file-edits wrote")
    args = parser.parse_args(argv)

    if os.path.exists(args.to):
        print("the inputs folder %s already exists, and a run's inputs are fixed" % args.to,
              file=sys.stderr)
        return 2
    if not os.path.isdir(args.project):
        print("missing project folder %s" % args.project, file=sys.stderr)
        return 2

    problems = ["missing %s" % os.path.join(args.project, name) for name in DECLARATIONS
                if not os.path.isfile(os.path.join(args.project, name))]
    scripts = []
    if os.path.isfile(os.path.join(args.project, "pipeline.yaml")):
        scripts, found = pipeline_files(args.project)
        problems += found
    names = top_level_files(args.project)
    if args.file_edits is not None:
        if not os.path.isfile(args.file_edits):
            problems.append("missing the record of the AI's file edits %s. Write it with python3 -m "
                            "audit_layer write-out file-edits" % args.file_edits)
        if RECORD in names:
            problems.append("the project holds a %s of its own, where the record of the AI's file "
                            "edits would land" % os.path.join(args.project, RECORD))
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        return 2

    copies = [(os.path.join(args.project, name), name) for name in names]
    copies += [(os.path.join(args.project, name), name) for name in scripts if "/" in name]
    if args.file_edits is not None:
        copies.append((args.file_edits, RECORD))
    os.makedirs(args.to)
    for src, name in copies:
        dest = os.path.join(args.to, name)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(src, dest)
    print(args.to)
    return 0


if __name__ == "__main__":
    sys.exit(main())
