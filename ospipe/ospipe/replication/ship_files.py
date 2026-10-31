"""The replication folder's own files, its Makefile, README, and evidence files.

`emit` calls `write_ship_files` on the new folder before its rebuild check, so the folder
that is checked is the folder that ships. The README is written last, since it lists
every other file in the folder with its checksum.
"""
import hashlib
import platform
import shlex
import subprocess
from pathlib import Path
from typing import List, Optional

import yaml

from ospipe.build import read_ledger
from ospipe.build.builder import FORMATS
from ospipe.build.verification import status_text, stream_status
from ospipe.evidence import EvidenceError, citation_evidence, entry_line, evidence_yaml, markdown_list, unverified_claims

from .closure import AUDIT_RECORDS, PIPELINE, ReplicationError

MAKEFILE = "Makefile"
README = "README.md"
EVIDENCE_FILE = "citation_evidence.yaml"
UNVERIFIED_FILE = "unverified_claims.md"
SHIP_FILES = (MAKEFILE, README, EVIDENCE_FILE, UNVERIFIED_FILE)
OSPIPE_LINE = "PYTHONPATH=tools python3 -m ospipe"
CITATION_LOG = AUDIT_RECORDS[0][0]
CITATIONS_RESULTS = "citations.json"


def rebuild_args(product, version: str) -> List[str]:
    """The rebuild command's words for a product, every path relative to the folder."""
    words = ["rebuild", "--manuscript", product.source, "--manifest", product.manifest]
    for flag, value in (("--overlay", product.overlay), ("--tables-dir", product.tables_dir)):
        if value is not None:
            words.extend([flag, value])
    words.extend(["--builds-dir", product.builds_dir, "--version", version])
    for flag, value in (
        ("--bib", product.bib),
        ("--csl", product.csl),
        ("--reference-doc", product.reference_doc),
    ):
        if value is not None:
            words.extend([flag, value])
    words.extend(["--to", product.to])
    return words


def name_problems(files) -> List[str]:
    """A closure file at the path of one of the folder's own files would be written over."""
    return [
        "{0} is a file the product needs and also a file the replication folder writes".format(name)
        for name in SHIP_FILES
        if name in files
    ]


def check_command(product, version: str) -> str:
    """The check rule's command line, for use without Make."""
    return OSPIPE_LINE + " " + " ".join(shlex.quote(word) for word in rebuild_args(product, version))


def _make_word(word: str) -> str:
    return shlex.quote(word).replace("$", "$$")


def _steps(folder: Path) -> List[str]:
    """Each pipeline step as `<runner> <script>`, in the file's order."""
    data = yaml.safe_load((folder / PIPELINE).read_text(encoding="utf-8")) or {}
    problems = []
    commands = []
    for number, step in enumerate(data.get("steps") or [], start=1):
        label = "{0} step {1}".format(PIPELINE, step.get("id", number))
        runner, script = step.get("runner"), step.get("script")
        if not isinstance(runner, str) or not runner.strip():
            problems.append("{0} has no runner, so make results cannot run it".format(label))
        if not isinstance(script, str) or not script.strip():
            problems.append("{0} has no one script, so make results cannot run it".format(label))
        if not problems:
            commands.append("{0} {1}".format(runner.strip().replace("$", "$$"), _make_word(script)))
    if problems:
        raise ReplicationError(problems)
    return commands


def makefile_text(project_name: str, product, version: str, steps: Optional[List[str]]) -> str:
    """The folder's Makefile. `check` first, so it is the default, and `results` when the
    folder holds the analysis. Nothing in it is newer than GNU Make 3.81."""
    lines = [
        "# The replication folder's build file, written by ospipe emit from the build file of",
        "# the project {0} for its product {1}, build {2}.".format(project_name, product.name, version),
        "# Never edit it by hand. Fix the project and emit again.",
        "",
        "OSPIPE := " + OSPIPE_LINE,
        "",
        "check:",
        "\t$(OSPIPE) " + " ".join(_make_word(word) for word in rebuild_args(product, version)),
    ]
    phony = ["check"]
    if steps is not None:
        lines.extend(["", "results:"])
        lines.extend("\t" + command for command in steps)
        lines.append("\t$(OSPIPE) emit-manifest --manifest " + _make_word(product.manifest))
        phony.append("results")
    lines.extend(["", ".PHONY: " + " ".join(phony)])
    return "\n".join(lines) + "\n"


def _pandoc_version() -> str:
    try:
        run = subprocess.run(["pandoc", "--version"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return "pandoc not found"
    lines = run.stdout.splitlines()
    return lines[0].strip() if run.returncode == 0 and lines else "pandoc not found"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _listing(folder: Path) -> List[str]:
    return sorted(
        p.relative_to(folder).as_posix()
        for p in folder.rglob("*")
        if p.is_file() and p.relative_to(folder).as_posix() != README
    )


def _write_evidence(folder: Path, product, files) -> Optional[str]:
    """Write citation_evidence.yaml when the folder holds the product's citations results.
    Returns the README's line about it, or None when there is no citations results file."""
    relative = (Path(product.verification_dir) / CITATIONS_RESULTS).as_posix()
    if relative not in files:
        return None
    log = folder / CITATION_LOG if CITATION_LOG in files else None
    try:
        evidence = citation_evidence(folder / product.verification_dir, citation_log=log)
    except EvidenceError as err:
        return "No citation evidence file was written, since {0}".format(
            str(err).replace(str(folder) + "/", "")
        )
    # The path as the citation-evidence command run in this folder writes it.
    evidence["results_file"] = str(Path(product.verification_dir) / CITATIONS_RESULTS)
    (folder / EVIDENCE_FILE).write_text(evidence_yaml(evidence), encoding="utf-8")
    return "The citation evidence file is `{0}`, with {1} citations.".format(EVIDENCE_FILE, len(evidence["items"]))


def _readme_text(folder, project_name, product, version, row, notes, flags, entries, evidence_line, has_pipeline):
    build_file = "{0}/{1}{2}".format(Path(product.builds_dir).as_posix(), version, FORMATS[product.to][0])
    out = [
        "# Replication folder for {0}".format(product.name),
        "",
        "This folder rebuilds one build of the research product {0} from the project {1}, "
        "with the project out of reach. `ospipe emit` wrote it from the project's build file. "
        "Never edit it by hand. Fix the project and emit again.".format(product.name, project_name),
        "",
        "## Rebuild the product",
        "",
        "Run `make` in this folder. It rebuilds {0} from the copy of its text in `{1}` in a "
        "temporary folder and compares checksums, and it prints `match {0}` when the rebuild "
        "is byte for byte the shipped build. Without Make, run this command line in this "
        "folder.".format(version, "{0}/{1}.md".format(Path(product.builds_dir).as_posix(), version)),
        "",
        "    " + check_command(product, version),
        "",
        "## Rerun the analysis",
        "",
    ]
    if has_pipeline:
        out.append(
            "Run `make results` to rerun each step of `{0}` in its order and then fill the numbers "
            "file `{1}` from the outputs, then run `make` to check the build again.".format(PIPELINE, product.manifest)
        )
    else:
        out.append(
            "The project declares no analysis, so this folder ships its computed results only."
        )
    out.extend(
        [
            "",
            "## The shipped build",
            "",
            "- File `{0}`".format(build_file),
            "- Version {0}".format(version),
            "- Ledger date {0}".format(row["date"]),
            "- sha256 {0}".format(row["sha256"]),
            "",
            "## Tools at emit",
            "",
            "- Python {0}".format(platform.python_version()),
            "- PyYAML {0}".format(yaml.__version__),
            "- {0}".format(_pandoc_version()),
            "",
            "A different Pandoc can change the bytes of a build, so a rebuild with another version may not match.",
            "",
            "## Verification",
            "",
            "The verification status at emit is `{0}`.".format(status_text(flags)),
            "",
        ]
    )
    if evidence_line is not None:
        out.extend([evidence_line, ""])
    out.extend(["## Unverified claims", ""])
    if entries:
        out.extend("- " + entry_line(entry) for entry in entries)
        out.extend(["", "The same list is in `{0}`.".format(UNVERIFIED_FILE)])
    else:
        out.append("None")
    out.extend(["", "## Not shipped", ""])
    if notes:
        out.extend("- " + note for note in notes)
    else:
        out.append("Nothing the closure looks for is absent.")
    out.extend(
        [
            "",
            "## Before sharing",
            "",
            "Review this folder before it is shared. It may hold results files and the audit "
            "layer's records, which name AI sessions.",
            "",
            "## Files",
            "",
            "| file | sha256 |",
            "|---|---|",
        ]
    )
    for relative in _listing(folder):
        out.append("| `{0}` | {1} |".format(relative.replace("|", "\\|"), _sha256(folder / relative)))
    return "\n".join(out) + "\n"


def write_ship_files(folder, project_dir, product, version: str, found) -> List[str]:
    """Write the folder's Makefile, unverified_claims.md, citation_evidence.yaml when the
    folder holds the product's citations results, and last README.md. Returns the names
    written. Raises ReplicationError when the pipeline's steps cannot become make results."""
    folder = Path(folder)
    project_name = Path(project_dir).resolve().name
    has_pipeline = PIPELINE in found.files
    steps = _steps(folder) if has_pipeline else None
    written = []

    (folder / MAKEFILE).write_text(makefile_text(project_name, product, version, steps), encoding="utf-8")
    written.append(MAKEFILE)

    verification_dir = folder / product.verification_dir
    source = folder / product.source
    manifest = folder / product.manifest
    entries = unverified_claims(verification_dir, source, manifest)
    (folder / UNVERIFIED_FILE).write_text(markdown_list(entries), encoding="utf-8")
    written.append(UNVERIFIED_FILE)

    evidence_line = _write_evidence(folder, product, found.files)
    if (folder / EVIDENCE_FILE).is_file():
        written.append(EVIDENCE_FILE)

    flags, _ = stream_status(verification_dir, source, manifest)
    rows = [r for r in read_ledger(folder / product.builds_dir) if r["version"] == version]
    readme = _readme_text(
        folder, project_name, product, version, rows[-1], found.notes, flags, entries, evidence_line, has_pipeline
    )
    (folder / README).write_text(readme, encoding="utf-8")
    written.append(README)
    return written
