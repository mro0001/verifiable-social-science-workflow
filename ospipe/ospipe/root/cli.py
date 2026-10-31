"""Composition root. The one place ospipe modules wire together."""
import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, NamedTuple, Optional

from ospipe.build import BuildError, build as run_build, rebuild as run_rebuild
from ospipe.build.verification import status_text, stream_status
from ospipe.evidence import (
    EvidenceError,
    citation_evidence,
    count_line,
    entry_line,
    evidence_yaml,
    markdown_list,
    unverified_claims,
)
from ospipe.foundation import ManifestError, MissingKeyError, load_manifest
from ospipe.layout import AddProductError, ArchiveError, add_product, archive, look_alikes, read_map
from ospipe.manifest import ManifestEmitError, emit_manifest
from ospipe.notes_templates import NotesTemplatesError, install_notes
from ospipe.replication import ReplicationError, emit as run_emit
from ospipe.resolve import ResolveError, resolve


class CheckResult(NamedTuple):
    resolved: str
    wrote: Optional[str]


def _load_tables(tables_dir) -> Dict[str, str]:
    tables: Dict[str, str] = {}
    if tables_dir is None:
        return tables
    for path in sorted(Path(tables_dir).glob("*.md")):
        tables[path.stem] = path.read_text(encoding="utf-8")
    return tables


def run_check(
    manuscript_path,
    manifest_path,
    overlay_path=None,
    tables_dir=None,
    out_path=None,
) -> CheckResult:
    text = Path(manuscript_path).read_text(encoding="utf-8")
    manifest = load_manifest(manifest_path, overlay_path)
    resolved = resolve(text, manifest, _load_tables(tables_dir))
    wrote = None
    if out_path is not None:
        Path(out_path).write_text(resolved, encoding="utf-8")
        wrote = str(out_path)
    return CheckResult(resolved=resolved, wrote=wrote)


def _source_git_hash(manuscript_path) -> Optional[str]:
    try:
        out = subprocess.run(
            ["git", "-C", str(Path(manuscript_path).resolve().parent), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return None
    return out.stdout.strip() or None if out.returncode == 0 else None


def _emit_manifest(manifest_path, outputs_dir) -> int:
    try:
        result = emit_manifest(manifest_path, outputs_dir)
    except ManifestEmitError as err:
        print(str(err), file=sys.stderr)
        return 2
    for key, old, new in result.changed:
        print("{0}: {1} -> {2}".format(key, "(no value)" if old is None else old, new))
    if not result.changed:
        print("{0} unchanged".format(manifest_path))
    return 0


def _products(map_path, as_json) -> int:
    try:
        project_map = read_map(map_path)
    except FileNotFoundError:
        print("no build file {0}".format(map_path), file=sys.stderr)
        return 2
    if as_json:
        data = {
            "project_dir": project_map.project_dir,
            "products": [product._asdict() for product in project_map.products],
            "problems": list(project_map.problems),
        }
        print(json.dumps(data, indent=2))
    else:
        for product in project_map.products:
            print(
                "{0}: {1} -> {2} ({3})".format(
                    product.name,
                    "(none)" if product.source is None else product.source,
                    "(none)" if product.builds_dir is None else product.builds_dir,
                    product.to,
                )
            )
        for problem in project_map.problems:
            print(problem)
        for item in look_alikes(project_map):
            if not item.archived:
                print("not archived: {0} reads as {1} ({2})".format(item.path, item.claims, item.reason))
    return 2 if project_map.problems else 0


def _archive(args) -> int:
    try:
        project_map = read_map(args.map)
    except FileNotFoundError:
        print("no build file {0}".format(args.map), file=sys.stderr)
        return 2
    try:
        line = archive(args.draft, args.by, project_map, on=args.date)
    except ArchiveError as err:
        print(str(err), file=sys.stderr)
        return 2
    print("archived {0}, {1}".format(args.draft, line))
    return 0


def _add_product(args) -> int:
    try:
        product = add_product(
            args.map,
            args.name,
            args.source,
            to=args.to,
            builds_dir=args.builds_dir,
            bib=args.bib,
            csl=args.csl,
            reference_doc=args.reference_doc,
            tables_dir=args.tables_dir,
        )
    except AddProductError as err:
        print(str(err), file=sys.stderr)
        return 2
    print(
        "added {0} to {1}, {2} -> {3} ({4})".format(
            product.name, args.map, product.source, product.builds_dir, product.to
        )
    )
    return 0


def _install_notes(args) -> int:
    try:
        result = install_notes(args.project, templates_dir=args.templates)
    except NotesTemplatesError as err:
        print(str(err), file=sys.stderr)
        return 2
    for path in result.written:
        print("wrote {0}".format(path))
    for path in result.skipped:
        print("skipped {0}, already there".format(path))
    return 0


def _unverified(args) -> int:
    verification_dir = args.verification_dir
    if verification_dir is None:
        verification_dir = str(Path(args.source).parent / "verification")
    entries = unverified_claims(verification_dir, args.source, args.manifest)
    for entry in entries:
        print(entry_line(entry))
    print(count_line(entries))
    if args.out is not None:
        Path(args.out).write_text(markdown_list(entries), encoding="utf-8")
    return 0


DEFAULT_CITATION_LOG = Path("audit") / "citation_log.yaml"


def _citation_evidence(args) -> int:
    citation_log = args.citation_log
    if citation_log is None and DEFAULT_CITATION_LOG.is_file():
        citation_log = str(DEFAULT_CITATION_LOG)
    try:
        evidence = citation_evidence(args.verification_dir, citation_log=citation_log)
    except EvidenceError as err:
        print(str(err), file=sys.stderr)
        return 2
    Path(args.out).write_text(evidence_yaml(evidence), encoding="utf-8")
    print("wrote {0}, {1} citations".format(args.out, len(evidence["items"])))
    return 0


def _emit(args) -> int:
    try:
        project_map = read_map(args.map)
    except FileNotFoundError:
        print("no build file {0}".format(args.map), file=sys.stderr)
        return 2
    try:
        result = run_emit(
            project_map, args.product, out_dir=args.out, version=args.version, replace=args.replace
        )
    except ReplicationError as err:
        print(str(err), file=sys.stderr)
        return 2
    print(
        "emitted {0} {1} to {2}, {3} files".format(
            args.product, result.version, result.out_dir, len(result.files)
        )
    )
    return 0


def _rebuild(args, resolved) -> int:
    try:
        result = run_rebuild(
            args.builds_dir,
            args.version,
            bibliography=args.bib,
            csl=args.csl,
            reference_docx=args.reference_doc,
            to=args.to,
            resolved_md=resolved,
        )
    except BuildError as err:
        print("rebuild failed: {0}".format(err), file=sys.stderr)
        return 3
    if result.text_matches is False:
        print("text differs from {0}".format(args.version))
        return 1
    if not result.match:
        print(
            "mismatch {0} ledger sha256 {1} rebuilt sha256 {2}".format(
                args.version, result.ledger_sha256, result.rebuilt_sha256
            )
        )
        return 1
    print("match {0} sha256 {1}".format(args.version, result.rebuilt_sha256[:12]))
    return 0


def _add_check_args(p):
    p.add_argument("--manuscript", required=True)
    p.add_argument("--manifest", required=True)
    p.add_argument("--overlay", default=None)
    p.add_argument("--tables-dir", default=None)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="ospipe")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="resolve a canonical markdown file")
    _add_check_args(check)
    check.add_argument("--out", default=None)

    bld = sub.add_parser(
        "build", help="check, then produce a numbered immutable build (docx, reveal.js slides, or a web page)"
    )
    _add_check_args(bld)
    bld.add_argument("--builds-dir", required=True)
    bld.add_argument("--purpose", required=True)
    bld.add_argument("--baseline", default=None)
    bld.add_argument("--bib", default=None)
    bld.add_argument("--csl", default=None)
    bld.add_argument("--reference-doc", default=None)
    bld.add_argument("--to", choices=("docx", "revealjs", "html"), default="docx")
    bld.add_argument(
        "--verification-dir",
        default=None,
        help="the folder of each stream's results file, by default verification beside the manuscript",
    )

    reb = sub.add_parser(
        "rebuild", help="rebuild a ledgered version from its snapshot and compare checksums"
    )
    _add_check_args(reb)
    reb.add_argument("--builds-dir", required=True)
    reb.add_argument("--version", required=True, help="the ledgered version, vNNN")
    reb.add_argument("--bib", default=None)
    reb.add_argument("--csl", default=None)
    reb.add_argument("--reference-doc", default=None)
    reb.add_argument("--to", choices=("docx", "revealjs", "html"), default="docx")

    emm = sub.add_parser(
        "emit-manifest", help="fill each value in the numbers file from the analysis outputs"
    )
    emm.add_argument("--manifest", required=True)
    emm.add_argument(
        "--outputs-dir",
        default=None,
        help="the folder each entry's from names a file in, by default the manifest's folder",
    )

    prods = sub.add_parser("products", help="list the research products the build file names")
    prods.add_argument("--map", default="Makefile", help="the build file, by default Makefile here")
    prods.add_argument("--json", action="store_true", help="print the whole map as JSON")

    add = sub.add_parser("add-product", help="add a research product's rule to the build file")
    add.add_argument("--name", required=True)
    add.add_argument("--source", required=True, help="the product's one source file, relative to the project")
    add.add_argument("--to", choices=("docx", "revealjs", "html"), default="docx")
    add.add_argument("--builds-dir", default=None, help="by default builds/<name>")
    add.add_argument("--bib", default=None)
    add.add_argument("--csl", default=None)
    add.add_argument("--reference-doc", default=None)
    add.add_argument("--tables-dir", default=None)
    add.add_argument("--map", default="Makefile", help="the build file, by default Makefile here")

    arc = sub.add_parser("archive", help="mark an older draft as archived, superseded by another file")
    arc.add_argument("draft", help="the older draft, relative to the project")
    arc.add_argument("--by", required=True, help="the file that supersedes it, relative to the project")
    arc.add_argument("--date", default=None, help="YYYY-MM-DD, by default today")
    arc.add_argument("--map", default="Makefile", help="the build file, by default Makefile here")

    notes = sub.add_parser("install-notes", help="copy the notes templates into a project's notes folder")
    notes.add_argument("--project", required=True, help="the project folder")
    notes.add_argument(
        "--templates", default=None, help="the templates folder, by default the repository's templates/notes"
    )

    unv = sub.add_parser("unverified", help="list the streams and items not yet verified for a source file")
    unv.add_argument("--source", required=True, help="the product's source file")
    unv.add_argument("--manifest", required=True, help="the numbers file")
    unv.add_argument(
        "--verification-dir",
        default=None,
        help="the folder of each stream's results file, by default verification beside the source",
    )
    unv.add_argument("--out", default=None, help="also write the list as markdown to this file")

    cev = sub.add_parser("citation-evidence", help="write the citation evidence file from the citations results file")
    cev.add_argument(
        "--verification-dir", default="verification", help="the folder of the results files, by default verification here"
    )
    cev.add_argument(
        "--citation-log",
        default=None,
        help="the citation log, by default audit/citation_log.yaml here when it exists",
    )
    cev.add_argument("--out", required=True, help="the YAML file to write")

    shp = sub.add_parser(
        "emit", help="write a product's replication folder, by default ship/<product>, that rebuilds its build"
    )
    shp.add_argument("--product", required=True, help="the product's name in the build file")
    shp.add_argument("--map", default="Makefile", help="the build file, by default Makefile here")
    shp.add_argument("--out", default=None, help="the folder to write, by default ship/<product> in the project")
    shp.add_argument("--version", default=None, help="the build to ship, vNNN, by default the ledger's last row")
    shp.add_argument("--replace", action="store_true", help="put a new folder in place of an existing one")

    args = parser.parse_args(argv)

    if args.command == "emit-manifest":
        return _emit_manifest(args.manifest, args.outputs_dir)
    if args.command == "emit":
        return _emit(args)
    if args.command == "products":
        return _products(args.map, args.json)
    if args.command == "add-product":
        return _add_product(args)
    if args.command == "archive":
        return _archive(args)
    if args.command == "install-notes":
        return _install_notes(args)
    if args.command == "unverified":
        return _unverified(args)
    if args.command == "citation-evidence":
        return _citation_evidence(args)

    try:
        result = run_check(
            args.manuscript,
            args.manifest,
            overlay_path=args.overlay,
            tables_dir=args.tables_dir,
            out_path=args.out if args.command == "check" else None,
        )
    except MissingKeyError as err:
        print(f"resolve failed, missing manifest keys: {', '.join(err.keys)}", file=sys.stderr)
        return 2
    except (ResolveError, ManifestError) as err:
        print(f"resolve failed: {err}", file=sys.stderr)
        return 2

    if args.command == "check":
        if result.wrote is None:
            sys.stdout.write(result.resolved)
        return 0

    if args.command == "rebuild":
        return _rebuild(args, result.resolved)

    verification_dir = args.verification_dir
    if verification_dir is None:
        verification_dir = str(Path(args.manuscript).parent / "verification")
    try:
        built = run_build(
            result.resolved,
            args.builds_dir,
            purpose=args.purpose,
            baseline=args.baseline,
            bibliography=args.bib,
            csl=args.csl,
            reference_docx=args.reference_doc,
            source_git_hash=_source_git_hash(args.manuscript),
            to=args.to,
            verification_dir=verification_dir,
            source_path=args.manuscript,
            numbers_path=args.manifest,
        )
    except BuildError as err:
        print(f"build failed: {err}", file=sys.stderr)
        return 3
    print(f"{built.version} -> {built.docx_path} (sha256 {built.sha256[:12]})")
    flags, _ = stream_status(verification_dir, args.manuscript, args.manifest)
    print(status_text(flags))
    return 0
