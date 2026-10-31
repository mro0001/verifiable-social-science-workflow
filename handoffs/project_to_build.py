"""Pack a project into one archive and copy its file-writes record and source texts
into one inputs folder for a run of the build procedure.

    python3 handoffs/project_to_build.py --project DIR --to DIR [--source FILE ...]

It writes project.tar, holding every regular file under the project except the
.git folder, packed in sorted order with times 0, mode 0644, owner 0, and the
USTAR format, the way the build fixtures pack their projects. The same project
then always packs to the same bytes. Beside the archive it copies
audit/session_writes.jsonl as session_writes.jsonl and each source text under its
own name. --source is a path inside the project, may be given more than once, and
defaults to manuscript.md. The source copy puts the text's checksum among the
run's inputs, which is how the build tells that a build-stream result is current.

It refuses when the --to folder already exists, since a run's inputs are fixed,
and when the record or a source is missing, naming each one. A refusal exits 2
and writes nothing. Ignored files are packed too, unlike git archive. It is a
plain copy kept in handoffs/ for a scholar to replace when they connect the layers.
No layer's code calls it. Standard library only.
"""
import argparse
import io
import os
import shutil
import sys
import tarfile

ARCHIVE = "project.tar"
RECORD = "session_writes.jsonl"


def project_files(project):
    """Every regular file under the project, as sorted paths relative to it with
    forward slashes, leaving out the .git folder and links."""
    names = []
    for root, dirs, files in os.walk(project):
        if os.path.samefile(root, project):
            dirs[:] = [d for d in dirs if d != ".git"]
            files = [f for f in files if f != ".git"]
        for name in files:
            path = os.path.join(root, name)
            if os.path.isfile(path) and not os.path.islink(path):
                names.append(os.path.relpath(path, project).replace(os.sep, "/"))
    return sorted(names)


def pack(project):
    """The project's archive as bytes, the same bytes for the same files."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tf:
        for name in project_files(project):
            with open(os.path.join(project, name), "rb") as f:
                data = f.read()
            info = tarfile.TarInfo(name)
            info.size, info.mtime, info.mode = len(data), 0, 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="project_to_build.py",
        description="Pack a project into the build procedure's inputs folder.")
    parser.add_argument("--project", required=True, help="the project folder")
    parser.add_argument("--to", required=True, help="the inputs folder to create")
    parser.add_argument("--source", action="append",
                        help="a source text in the project, repeatable (default manuscript.md)")
    args = parser.parse_args(argv)
    sources = args.source or ["manuscript.md"]

    if os.path.exists(args.to):
        print("the inputs folder %s already exists, and a run's inputs are fixed" % args.to,
              file=sys.stderr)
        return 2
    if not os.path.isdir(args.project):
        print("missing project folder %s" % args.project, file=sys.stderr)
        return 2

    copies = [(os.path.join(args.project, "audit", RECORD), RECORD)]
    copies += [(os.path.join(args.project, source), os.path.basename(source)) for source in sources]
    missing = [src for src, _ in copies if not os.path.isfile(src)]
    if missing:
        for src in missing:
            print("missing %s" % src, file=sys.stderr)
        return 2
    names = [ARCHIVE] + [name for _, name in copies]
    clashes = sorted(set(name for name in names if names.count(name) > 1))
    if clashes:
        print("two files would land under one name in the inputs folder: %s"
              % ", ".join(clashes), file=sys.stderr)
        return 2

    archive = pack(args.project)
    os.makedirs(args.to)
    with open(os.path.join(args.to, ARCHIVE), "wb") as f:
        f.write(archive)
    for src, name in copies:
        shutil.copyfile(src, os.path.join(args.to, name))
    print(args.to)
    return 0


if __name__ == "__main__":
    sys.exit(main())
