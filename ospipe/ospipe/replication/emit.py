"""Writing a research product's replication folder, `ship/<product>/` by default.

The folder holds what the product depends on (its closure), one existing build of it with
a one-row ledger, the pipeline's own package under `tools/ospipe/`, and its own Makefile,
README, and evidence files (`ship_files.py`). It is put in
place only after a copy of it, outside the project, rebuilds that build byte for byte.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, NamedTuple, Optional

from ospipe.build import read_ledger
from ospipe.build.builder import FORMATS, LEDGER_COLUMNS, LEDGER_NAME

from .closure import ReplicationError, closure
from .ship_files import name_problems, rebuild_args, write_ship_files

# The pipeline's modules, the package folders a replication folder ships. A test keeps
# this equal to the package's module folders other than the ones moved to other layers.
PIPELINE_MODULES = (
    "foundation",
    "resolve",
    "build",
    "root",
    "manifest",
    "layout",
    "evidence",
    "replication",
    "notes_templates",
)
PACKAGE_FILES = ("__init__.py", "__main__.py")
SHIP_DIR = "ship"
TOOLS_DIR = "tools"
_SEPARATOR_CELL = re.compile(r":?-{3,}:?$")


class EmitResult(NamedTuple):
    out_dir: str
    version: str
    files: List[str]


def package_dir() -> Path:
    """The folder of the ospipe package this module belongs to."""
    return Path(__file__).resolve().parents[1]


def _inside_project(path: str) -> bool:
    text = str(path)
    if Path(text).is_absolute() or text.startswith("~"):
        return False
    normal = Path(os.path.normpath(text)).as_posix()
    return not (normal == ".." or normal.startswith("../"))


def _cells(line: str):
    stripped = line.strip()
    if len(stripped) < 2 or not (stripped.startswith("|") and stripped.endswith("|")):
        return None
    return [cell.strip() for cell in stripped[1:-1].split("|")]


def _is_separator(cells) -> bool:
    return all(_SEPARATOR_CELL.match(cell) for cell in cells)


def _one_row_ledger(ledger: Path, version: str) -> str:
    """The ledger's header lines and the last row for version, as written in the file."""
    header: List[str] = []
    row_line = None
    in_header = True
    for line in ledger.read_text(encoding="utf-8").splitlines(True):
        cells = _cells(line)
        is_row = (
            cells is not None
            and cells[0].lower() != LEDGER_COLUMNS[0]
            and not _is_separator(cells)
        )
        if is_row:
            in_header = False
            if cells[0] == version:
                row_line = line
        elif in_header:
            header.append(line)
    if row_line is None:
        raise ReplicationError(["{0} has no row for {1}".format(ledger, version)])
    if not row_line.endswith("\n"):
        row_line += "\n"
    return "".join(header) + row_line


def _pick_build(project_dir: Path, product, version: Optional[str]):
    """The version to ship, its build file and its snapshot, relative to the project."""
    problems: List[str] = []
    if product.builds_dir is None:
        raise ReplicationError(["{0} has no builds dir".format(product.name)])
    if not _inside_project(product.builds_dir):
        raise ReplicationError(
            ["the builds dir {0} is not inside the project folder".format(product.builds_dir)]
        )
    if product.to not in FORMATS:
        raise ReplicationError(["{0} builds to {1}, an unknown format".format(product.name, product.to)])
    builds = project_dir / product.builds_dir
    rows = read_ledger(builds)
    if not rows:
        raise ReplicationError(
            ["{0} has no build in {1}, so there is nothing to ship".format(product.name, product.builds_dir)]
        )
    versions = [row["version"] for row in rows]
    chosen = version if version is not None else versions[-1]
    if chosen not in versions:
        raise ReplicationError(
            ["{0} has no row for {1} in {2}/{3}".format(product.name, chosen, product.builds_dir, LEDGER_NAME)]
        )
    extension = FORMATS[product.to][0]
    build_file = "{0}/{1}{2}".format(Path(product.builds_dir).as_posix(), chosen, extension)
    snapshot = "{0}/{1}.md".format(Path(product.builds_dir).as_posix(), chosen)
    for relative in (build_file, snapshot):
        if not (project_dir / relative).is_file():
            problems.append("{0} is missing".format(relative))
    if problems:
        raise ReplicationError(problems)
    return chosen, build_file, snapshot


def _copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(str(source), str(target))


def _write_folder(folder: Path, project_dir: Path, product, files, version, build_file, snapshot) -> None:
    for relative in files:
        _copy(project_dir / relative, folder / relative)
    for relative in (build_file, snapshot):
        _copy(project_dir / relative, folder / relative)
    ledger = project_dir / product.builds_dir / LEDGER_NAME
    (folder / product.builds_dir / LEDGER_NAME).write_text(
        _one_row_ledger(ledger, version), encoding="utf-8"
    )
    package = package_dir()
    tools = folder / TOOLS_DIR / "ospipe"
    tools.mkdir(parents=True)
    for name in PACKAGE_FILES:
        shutil.copyfile(str(package / name), str(tools / name))
    for module in PIPELINE_MODULES:
        shutil.copytree(
            str(package / module), str(tools / module), ignore=shutil.ignore_patterns("__pycache__")
        )


def _check_rebuild(folder: Path, product, version: str) -> None:
    """Copy the folder outside the project and rebuild there. Refuse unless it matches."""
    work = Path(tempfile.mkdtemp(prefix="ospipe-emit-check-"))
    try:
        copy = work / folder.name
        shutil.copytree(str(folder), str(copy))
        env = dict(os.environ)
        env["PYTHONPATH"] = TOOLS_DIR
        run = subprocess.run(
            [sys.executable, "-m", "ospipe"] + rebuild_args(product, version),
            capture_output=True,
            text=True,
            cwd=str(copy),
            env=env,
        )
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    if run.returncode != 0 or not run.stdout.startswith("match {0} ".format(version)):
        output = [line for line in (run.stdout + run.stderr).splitlines() if line.strip()]
        raise ReplicationError(
            ["the shipped folder does not rebuild {0}, so nothing was written".format(version)] + output
        )


def _is_or_holds(folder: Path, path: Path) -> bool:
    return path == folder or folder in path.parents


def _out_problems(out: Path, project_dir: Path, project_map, files) -> List[str]:
    """Why out cannot be the replication folder. Replacing it would remove the project, a
    file the product needs, or a product's builds."""
    project = Path(os.path.realpath(str(project_dir)))
    if _is_or_holds(out, project):
        return ["the out dir {0} is or holds the project folder".format(out)]
    problems = []
    named = [
        (p.builds_dir, "the builds dir of {0}".format(p.name))
        for p in project_map.products
        if p.builds_dir is not None
    ]
    named += [(f, "a file the product needs") for f in files]
    for relative, what in named:
        if _is_or_holds(out, Path(os.path.realpath(str(project / relative)))):
            problems.append(
                "the out dir {0} is or holds {1}, {2}".format(out, Path(relative).as_posix(), what)
            )
    return problems


def _is_replication_folder(folder: Path) -> bool:
    """Whether folder looks like one emit wrote, its package under tools/ and a ledger."""
    if not (folder / TOOLS_DIR / "ospipe" / "__init__.py").is_file():
        return False
    tools = folder / TOOLS_DIR
    return any(
        p.is_file() and tools not in p.parents for p in folder.rglob(LEDGER_NAME)
    )


def _existing_problems(out: Path, replace: bool) -> List[str]:
    """Why an existing out cannot be written over. replace removes it, so only a folder
    emit wrote may be replaced."""
    if not out.exists():
        return []
    if not out.is_dir():
        return ["the out dir {0} exists and is not a folder".format(out)]
    if not replace:
        return ["{0} already exists, so give replace to write over it".format(out)]
    if not _is_replication_folder(out):
        return [
            "the out dir {0} is not a replication folder emit wrote, so replace will not "
            "remove it".format(out)
        ]
    return []


def _first_missing(path: Path) -> Optional[Path]:
    """The highest folder on the way to path that does not exist yet, or None."""
    missing = None
    current = path
    while not current.exists():
        missing = current
        if current.parent == current:
            break
        current = current.parent
    return missing


def _listing(folder: Path) -> List[str]:
    return sorted(
        p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()
    )


def emit(project_map, product_name, out_dir=None, version=None, replace=False) -> EmitResult:
    """Write the product's replication folder and return where, which build, and its files.
    Raises ReplicationError, with nothing written, for every refusal."""
    project_dir = Path(project_map.project_dir)
    found = closure(project_map, product_name)
    problems = name_problems(found.files)
    if problems:
        raise ReplicationError(problems)
    product = [p for p in project_map.products if p.name == product_name][-1]
    chosen, build_file, snapshot = _pick_build(project_dir, product, version)

    if out_dir is None:
        out = project_dir / SHIP_DIR / product.name
    else:
        out = Path(out_dir)
    out = Path(os.path.realpath(os.path.abspath(str(out))))
    problems = _out_problems(out, project_dir, project_map, found.files)
    problems = problems or _existing_problems(out, replace)
    if problems:
        raise ReplicationError(problems)

    created = _first_missing(out.parent)
    out.parent.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="." + out.name + ".emit-", dir=str(out.parent)))
    aside = None
    try:
        _write_folder(folder, project_dir, product, found.files, chosen, build_file, snapshot)
        write_ship_files(folder, project_dir, product, chosen, found)
        _check_rebuild(folder, product, chosen)
        if out.exists():
            problems = _existing_problems(out, replace)
            if problems:
                raise ReplicationError(problems)
            aside = Path(tempfile.mkdtemp(prefix="." + out.name + ".old-", dir=str(out.parent)))
            os.rmdir(str(aside))
            os.rename(str(out), str(aside))
        try:
            os.rename(str(folder), str(out))
        except OSError:
            if aside is not None:
                os.rename(str(aside), str(out))
                aside = None
            raise
    except BaseException:
        shutil.rmtree(str(folder), ignore_errors=True)
        if created is not None:
            shutil.rmtree(str(created), ignore_errors=True)
        raise
    if aside is not None:
        shutil.rmtree(str(aside), ignore_errors=True)
    return EmitResult(out_dir=str(out), version=chosen, files=_listing(out))
