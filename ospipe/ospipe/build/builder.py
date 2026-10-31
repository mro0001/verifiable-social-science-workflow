"""Numbered immutable builds, a Word document, reveal.js slides, or a web page, plus the BUILDS.md ledger.

FROZEN surface documented in CONTRACT.md: the build() signature, BuildResult
shape, ledger column set and order, and the verify-before-build refusal.
Builds are never edited in place; the vNNN.md snapshot is the resolved text
byte-exact; citations render only here (citeproc at build time, nowhere else).
Given a verification folder, the build reads each stream's results file
(verification.py) and records the status in the row. The status never stops a build.
Every build is fixed-date (SOURCE_DATE_EPOCH at midnight UTC of the row's date), so
rebuild() can rebuild any version from its snapshot and its row.
"""
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple, Union

from .verification import runs_text, status_text, stream_status

PathLike = Union[str, Path]

LEDGER_NAME = "BUILDS.md"
LEDGER_COLUMNS = (
    "version", "date", "git", "sha256", "purpose", "baseline", "reviewed", "verification", "runs",
)
# Ledgers written before the verification columns have only the first seven.
# Their rows still parse and verify, and new rows are appended to them in full.
OLD_LEDGER_COLUMNS = LEDGER_COLUMNS[:7]
LEDGER_HEADER = (
    "# Builds\n"
    "\n"
    "| " + " | ".join(LEDGER_COLUMNS) + " |\n"
    "|" + "|".join("---" for _ in LEDGER_COLUMNS) + "|\n"
)

# Output formats: the pandoc writer named by build(to=...) -> (file extension, extra pandoc args).
FORMATS = {
    "docx": (".docx", ()),
    "revealjs": (".html", ("--standalone",)),
    "html": (".html", ("--standalone",)),
}

_VERSION = re.compile(r"v(\d{3,})$")
# Stray-file discovery: vNNN plus an optional ./_/- suffix (e.g. v000_submitted.docx)
# counts for version numbering so a hand-dropped file cannot cause a collision.
_BUILD_NAME = re.compile(r"v(\d{3,})(?:[._-].*)?\.(?:docx|html)$")
_SHA256_HEX = re.compile(r"[0-9a-f]{64}$")
_SEPARATOR_CELL = re.compile(r":?-{3,}:?$")


class BuildError(RuntimeError):
    pass


class BuildResult(NamedTuple):
    version: str
    docx_path: str
    snapshot_path: str
    sha256: str


class RebuildResult(NamedTuple):
    match: bool
    ledger_sha256: str
    rebuilt_sha256: str
    text_matches: Optional[bool]


_EPOCH_DAY = date(1970, 1, 1)


def _build_date() -> date:
    """The build's date. Today's, or the UTC date of SOURCE_DATE_EPOCH when it is set."""
    value = os.environ.get("SOURCE_DATE_EPOCH")
    if value is None or not value.strip():
        return date.today()
    try:
        seconds = int(value.strip())
    except ValueError:
        raise BuildError(
            "SOURCE_DATE_EPOCH {0!r} is not a whole number of seconds".format(value)
        )
    return datetime.fromtimestamp(seconds, tz=timezone.utc).date()


def _pandoc_env(day: date) -> Dict[str, str]:
    """The environment as it is, with SOURCE_DATE_EPOCH at midnight UTC of day."""
    env = dict(os.environ)
    env["SOURCE_DATE_EPOCH"] = str((day - _EPOCH_DAY).days * 86400)
    return env


def _check_format(to: str, reference_docx) -> Tuple[str, Tuple[str, ...]]:
    if to not in FORMATS:
        raise BuildError(
            "unknown output format {0!r}, expected one of: {1}".format(to, ", ".join(FORMATS))
        )
    if reference_docx is not None and to != "docx":
        raise BuildError("a reference docx applies only to docx builds")
    return FORMATS[to]


def _pandoc_command(pandoc, to, extra_args, output, snapshot, bibliography, csl, reference_docx):
    cmd = [pandoc, "--from", "markdown", "--to", to, *extra_args, "--output", str(output)]
    if bibliography is not None:
        cmd += ["--citeproc", "--bibliography", str(bibliography)]
        if csl is not None:
            cmd += ["--csl", str(csl)]
    if reference_docx is not None:
        cmd += ["--reference-doc", str(reference_docx)]
    cmd.append(str(snapshot))
    return cmd


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_ledger(builds_dir: Path) -> Tuple[List[Dict[str, str]], List[str]]:
    """Parse BUILDS.md into rows. Returns (rows, problems); tolerant of its
    own output round-trip, strict about anything else pipe-shaped."""
    rows: List[Dict[str, str]] = []
    problems: List[str] = []
    ledger = builds_dir / LEDGER_NAME
    if not ledger.exists():
        return rows, problems
    for lineno, raw in enumerate(ledger.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if len(line) < 2 or not (line.startswith("|") and line.endswith("|")):
            continue
        cells = [cell.strip() for cell in line[1:-1].split("|")]
        if cells[0].lower() == LEDGER_COLUMNS[0]:
            continue  # header row
        if all(_SEPARATOR_CELL.match(cell) for cell in cells):
            continue  # separator row
        if len(cells) not in (len(LEDGER_COLUMNS), len(OLD_LEDGER_COLUMNS)):
            problems.append(
                "{0} line {1}: expected {2} columns ({3} in an older ledger), got {4}: {5!r}".format(
                    LEDGER_NAME, lineno, len(LEDGER_COLUMNS), len(OLD_LEDGER_COLUMNS), len(cells), line
                )
            )
            continue
        rows.append(dict(zip(LEDGER_COLUMNS, cells)))
    return rows, problems


def read_ledger(builds_dir: PathLike) -> List[Dict[str, str]]:
    """The ledger's rows as the build's own parser reads them, older seven-column rows
    and nine-column rows alike, each a mapping from column name to cell. A row of
    another width is left out, and verify_ledger reports it."""
    rows, _ = _parse_ledger(Path(builds_dir))
    return rows


def verify_ledger(builds_dir: PathLike) -> None:
    """Re-hash every ledgered build file (vNNN.docx, or vNNN.html for slides or a page).
    Raises BuildError listing ALL problems (every mismatch, missing file, and
    malformed row) in one go."""
    builds = Path(builds_dir)
    rows, problems = _parse_ledger(builds)
    seen = set()
    for row in rows:
        version = row["version"]
        if not _VERSION.match(version):
            problems.append(
                "{0}: bad version {1!r} (expected vNNN)".format(LEDGER_NAME, version)
            )
            continue
        if version in seen:
            problems.append("{0}: duplicate row for {1}".format(LEDGER_NAME, version))
            continue
        seen.add(version)
        # Each distinct extension is looked for once, since slides and pages share .html.
        extensions = sorted(set(ext for ext, _ in FORMATS.values()))
        present = [builds / (version + ext) for ext in extensions]
        present = [path for path in present if path.exists()]
        if not present:
            problems.append(
                "{0}: ledgered file {0}.docx or {0}.html is missing from {1}".format(
                    version, builds
                )
            )
            continue
        if len(present) > 1:
            problems.append(
                "{0}: both {1} exist, so the ledger cannot say which one was built".format(
                    version, " and ".join(path.name for path in present)
                )
            )
            continue
        docx = present[0]
        if not _SHA256_HEX.match(row["sha256"]):
            problems.append(
                "{0}: ledger sha256 {1!r} is not a sha256 hex digest".format(
                    version, row["sha256"]
                )
            )
            continue
        actual = _sha256_of(docx)
        if actual != row["sha256"]:
            problems.append(
                "{0}: sha256 mismatch; ledger {1} vs on-disk {2} ({3} was modified "
                "after build)".format(version, row["sha256"], actual, docx.name)
            )
    if problems:
        raise BuildError(
            "ledger verification failed:\n" + "\n".join("- " + p for p in problems)
        )


def _next_version(builds: Path) -> str:
    """Highest of ledgered versions and stray vNNN*.docx or vNNN*.html files on disk, +1.
    v000 is reserved for externally archived documents and never auto-assigned;
    an empty archive yields v001."""
    highest = 0
    rows, _ = _parse_ledger(builds)
    for row in rows:
        match = _VERSION.match(row["version"])
        if match:
            highest = max(highest, int(match.group(1)))
    if builds.exists():
        for entry in builds.iterdir():
            match = _BUILD_NAME.match(entry.name)
            if match:
                highest = max(highest, int(match.group(1)))
    return "v{0:03d}".format(highest + 1)


def _cell(value: Optional[str]) -> str:
    """One-line, pipe-free ledger cell; None/empty becomes '-'."""
    if value is None:
        return "-"
    text = " ".join(str(value).split()).replace("|", "/")
    return text if text else "-"


def _append_row(
    builds: Path,
    version: str,
    sha256: str,
    purpose: str,
    baseline: Optional[str],
    source_git_hash: Optional[str],
    verification: str,
    runs: str,
    day: date,
) -> None:
    ledger = builds / LEDGER_NAME
    if ledger.exists():
        text = ledger.read_text(encoding="utf-8")
        if text and not text.endswith("\n"):
            text += "\n"
    else:
        text = LEDGER_HEADER
    row = "| {0} | {1} | {2} | {3} | {4} | {5} | no | {6} | {7} |\n".format(
        version,
        day.isoformat(),
        _cell(source_git_hash),
        sha256,
        _cell(purpose),
        _cell(baseline),
        _cell(verification),
        _cell(runs),
    )
    ledger.write_text(text + row, encoding="utf-8")


def build(
    resolved_md: str,
    builds_dir: PathLike,
    *,
    purpose: str,
    baseline: Optional[str] = None,
    bibliography: Optional[PathLike] = None,
    csl: Optional[PathLike] = None,
    reference_docx: Optional[PathLike] = None,
    source_git_hash: Optional[str] = None,
    pandoc: str = "pandoc",
    to: str = "docx",
    verification_dir: Optional[PathLike] = None,
    source_path: Optional[PathLike] = None,
    numbers_path: Optional[PathLike] = None,
) -> BuildResult:
    extension, extra_args = _check_format(to, reference_docx)
    day = _build_date()

    builds = Path(builds_dir)
    builds.mkdir(parents=True, exist_ok=True)

    verify_ledger(builds)  # no new build over a corrupted archive

    # Read, never checked here, and never a reason to stop the build.
    verification, runs = "-", "-"
    if verification_dir is not None:
        flags, run_ids = stream_status(verification_dir, source_path, numbers_path)
        verification, runs = status_text(flags), runs_text(run_ids)

    version = _next_version(builds)
    snapshot = builds / (version + ".md")
    docx = builds / (version + extension)  # the built file, whatever its format

    snapshot.write_bytes(resolved_md.encode("utf-8"))  # byte-exact

    cmd = _pandoc_command(
        pandoc, to, extra_args, docx, snapshot, bibliography, csl, reference_docx
    )
    proc = subprocess.run(cmd, capture_output=True, text=True, env=_pandoc_env(day))
    if proc.returncode != 0:
        for leftover in (docx, snapshot):
            try:
                leftover.unlink()
            except OSError:
                pass
        raise BuildError(
            "pandoc failed for {0} (exit {1}):\n{2}".format(
                version, proc.returncode, proc.stderr.strip()
            )
        )

    sha256 = _sha256_of(docx)
    _append_row(
        builds, version, sha256, purpose, baseline, source_git_hash, verification, runs, day
    )
    return BuildResult(
        version=version,
        docx_path=str(docx),
        snapshot_path=str(snapshot),
        sha256=sha256,
    )


def rebuild(
    builds_dir: PathLike,
    version: str,
    *,
    bibliography: Optional[PathLike] = None,
    csl: Optional[PathLike] = None,
    reference_docx: Optional[PathLike] = None,
    pandoc: str = "pandoc",
    to: str = "docx",
    resolved_md: Optional[str] = None,
) -> RebuildResult:
    """Rebuild a ledgered version from its snapshot in a new temporary folder, under the
    epoch of its row's date, and compare the checksum with the row's. Nothing is
    written in builds_dir."""
    extension, extra_args = _check_format(to, reference_docx)
    builds = Path(builds_dir)
    found = [row for row in read_ledger(builds) if row["version"] == version]
    if not found:
        raise BuildError("{0}: no row for {1}".format(builds / LEDGER_NAME, version))
    row = found[-1]
    try:
        day = date.fromisoformat(row["date"])
    except ValueError:
        raise BuildError(
            "{0}: ledger date {1!r} is not YYYY-MM-DD".format(version, row["date"])
        )
    snapshot = builds / (version + ".md")
    if not snapshot.is_file():
        raise BuildError("{0}: the snapshot {1} is missing".format(version, snapshot))
    text = snapshot.read_bytes()
    text_matches = None
    if resolved_md is not None:
        text_matches = resolved_md.encode("utf-8") == text

    work = Path(tempfile.mkdtemp(prefix="ospipe-rebuild-"))
    try:
        copy = work / snapshot.name
        copy.write_bytes(text)
        output = work / (version + extension)
        cmd = _pandoc_command(
            pandoc, to, extra_args, output, copy, bibliography, csl, reference_docx
        )
        proc = subprocess.run(cmd, capture_output=True, text=True, env=_pandoc_env(day))
        if proc.returncode != 0 or not output.is_file():
            raise BuildError(
                "pandoc failed rebuilding {0} (exit {1}):\n{2}".format(
                    version, proc.returncode, proc.stderr.strip()
                )
            )
        rebuilt = _sha256_of(output)
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    return RebuildResult(
        match=rebuilt == row["sha256"],
        ledger_sha256=row["sha256"],
        rebuilt_sha256=rebuilt,
        text_matches=text_matches,
    )
