"""Module contracts and the layer boundary.

Each check is a function over a package folder, the folder that holds `MODULES.md` and
the `ospipe/` package, so the tests run it on the package and on broken copies of it.
Each returns a list of problems, empty when the package keeps the rule.
"""
import ast
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

OSPIPE_DIR = Path(__file__).resolve().parents[1]
MOVED = ("kb", "lint", "annotate", "returns", "reconcile")


HEADINGS = ("## Produces", "## Frozen", "## Soft", "## Consumers", "## Fixture", "## Status")
OTHER_LAYERS = (
    "verification_procedures",
    "vg",
    "audit_layer",
    "observability",
    "connections",
    "features",
)
NETWORK = ("socket", "ssl", "urllib", "http", "requests")
FORBIDDEN = tuple("ospipe." + name for name in MOVED) + OTHER_LAYERS + NETWORK


def module_folders(pkg):
    """Every folder of the package that holds an `__init__.py`, other than the moved ones."""
    package = Path(pkg) / "ospipe"
    found = []
    for child in sorted(package.iterdir()):
        if child.is_dir() and child.name not in MOVED and (child / "__init__.py").is_file():
            found.append(child)
    return found


def contract_problems(pkg):
    """Each module folder has a CONTRACT.md with the six headings and a row in MODULES.md."""
    problems = []
    modules_md = Path(pkg) / "MODULES.md"
    rows = modules_md.read_text(encoding="utf-8") if modules_md.is_file() else ""
    for folder in module_folders(pkg):
        contract = folder / "CONTRACT.md"
        if not contract.is_file():
            problems.append("{}: no CONTRACT.md".format(folder.name))
        else:
            text = contract.read_text(encoding="utf-8")
            for heading in HEADINGS:
                if not re.search("^" + re.escape(heading) + r"[ \t]*$", text, re.MULTILINE):
                    problems.append("{}: CONTRACT.md lacks {}".format(folder.name, heading))
        if not re.search(r"^\|\s*" + re.escape(folder.name) + r"\s*\|", rows, re.MULTILINE):
            problems.append("{}: no row in MODULES.md".format(folder.name))
    return problems


def listed_commands(pkg):
    """The commands `python3 -m ospipe --help` lists, run on this package folder."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(pkg)
    run = subprocess.run(
        [sys.executable, "-m", "ospipe", "--help"],
        capture_output=True,
        text=True,
        cwd=str(pkg),
        env=env,
    )
    if run.returncode != 0:
        return None, run.stderr
    match = re.search(r"\{([A-Za-z0-9_,-]+)\}", run.stdout)
    if match is None:
        return None, run.stdout
    return match.group(1).split(","), ""


def command_problems(pkg):
    """Every command the help lists is named in root/CONTRACT.md."""
    commands, error = listed_commands(pkg)
    if commands is None:
        return ["help did not list the commands: {}".format(error.strip())]
    contract = Path(pkg) / "ospipe" / "root" / "CONTRACT.md"
    text = contract.read_text(encoding="utf-8") if contract.is_file() else ""
    problems = []
    for command in commands:
        if not re.search(r"python3 -m ospipe " + re.escape(command) + r"\b", text):
            problems.append("command {} is not named in root/CONTRACT.md".format(command))
    return problems


def _imported_names(tree, package_parts):
    """Every module name a file imports, relative imports resolved against its package."""
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                keep = len(package_parts) - (node.level - 1)
                base = package_parts[:keep] if keep > 0 else []
                parts = base + (node.module.split(".") if node.module else [])
            else:
                parts = node.module.split(".") if node.module else []
            full = ".".join(parts)
            names.append(full)
            names.extend(full + "." + alias.name for alias in node.names if alias.name != "*")
    return names


def _forbidden(name):
    for prefix in FORBIDDEN:
        if name == prefix or name.startswith(prefix + "."):
            return prefix
    return None


def import_problems(pkg):
    """No file in the module folders, or the package's own files, imports a moved module,
    another layer, or a network module."""
    package = Path(pkg) / "ospipe"
    files = sorted(package.glob("*.py"))
    for folder in module_folders(pkg):
        files.extend(sorted(folder.rglob("*.py")))
    problems = []
    for path in files:
        relative = path.relative_to(package)
        package_parts = ["ospipe"] + list(relative.parent.parts)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for name in _imported_names(tree, package_parts):
            hit = _forbidden(name)
            if hit is not None:
                problems.append("{} imports {}".format(relative.as_posix(), name))
    return problems


def test_package_has_a_contract_and_a_row_for_every_module():
    assert contract_problems(OSPIPE_DIR) == []


def test_every_command_is_named_in_the_root_contract():
    assert command_problems(OSPIPE_DIR) == []


def test_no_module_imports_another_layer_or_the_network():
    assert import_problems(OSPIPE_DIR) == []


@pytest.fixture()
def broken(tmp_path):
    copy = tmp_path / "ospipe"
    shutil.copytree(
        str(OSPIPE_DIR),
        str(copy),
        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "tests"),
    )
    return copy


def test_module_folder_without_contract_is_reported(broken):
    extra = broken / "ospipe" / "extra"
    extra.mkdir()
    (extra / "__init__.py").write_text("", encoding="utf-8")
    problems = contract_problems(broken)
    assert any("extra" in p and "CONTRACT.md" in p for p in problems)
    assert any("extra" in p and "MODULES.md" in p for p in problems)


def test_contract_missing_a_heading_is_reported(broken):
    contract = broken / "ospipe" / "resolve" / "CONTRACT.md"
    text = contract.read_text(encoding="utf-8").replace("## Frozen\n", "")
    contract.write_text(text, encoding="utf-8")
    problems = contract_problems(broken)
    assert any("resolve" in p and "## Frozen" in p for p in problems)


def test_command_missing_from_root_contract_is_reported(broken):
    contract = broken / "ospipe" / "root" / "CONTRACT.md"
    lines = contract.read_text(encoding="utf-8").splitlines(keepends=True)
    kept = [ln for ln in lines if "python3 -m ospipe build" not in ln]
    assert len(kept) < len(lines)
    contract.write_text("".join(kept), encoding="utf-8")
    problems = command_problems(broken)
    assert any("build" in p for p in problems)


@pytest.mark.parametrize(
    "line, named",
    [
        ("from audit_layer import store\n", "audit_layer"),
        ("import urllib.request\n", "urllib.request"),
        ("from ospipe.lint import lint\n", "ospipe.lint"),
        ("from .. import returns\n", "ospipe.returns"),
    ],
)
def test_import_across_the_boundary_is_reported(broken, line, named):
    module = broken / "ospipe" / "resolve" / "resolver.py"
    module.write_text(line + module.read_text(encoding="utf-8"), encoding="utf-8")
    problems = import_problems(broken)
    assert any("resolve/resolver.py" in p and named in p for p in problems)
