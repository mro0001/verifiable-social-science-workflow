"""Step F1. The features import no other layer's code.

Every .py file under features/ is parsed with ast, and any import of the
seven names below fails the test. Only files and command lines cross a
layer edge, through features/layers.py.
"""
import ast
from pathlib import Path

FEATURES = Path(__file__).resolve().parents[1]

FORBIDDEN = frozenset([
    "ospipe", "audit_layer", "verification_procedures", "vg", "_lib",
    "observability", "connections",
])


def _top(name):
    return (name or "").split(".")[0]


def import_problems(path):
    """Each forbidden import in one file, as 'path:line name'."""
    tree = ast.parse(Path(path).read_text(encoding="utf-8"), filename=str(path))
    problems = []
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            names = [node.module]
        elif isinstance(node, ast.Call) and node.args:
            func = node.func
            called = getattr(func, "id", None) or getattr(func, "attr", None)
            first = node.args[0]
            if called in ("__import__", "import_module") and isinstance(first, ast.Constant) \
                    and isinstance(first.value, str):
                names = [first.value]
        for name in names:
            if _top(name) in FORBIDDEN:
                problems.append((node.lineno, name))
    return ["%s:%d %s" % (path, line, name) for line, name in sorted(problems)]


def test_no_file_under_features_imports_another_layer():
    files = sorted(FEATURES.rglob("*.py"))
    assert FEATURES / "layers.py" in files
    problems = []
    for path in files:
        problems.extend(import_problems(path))
    assert problems == []


def test_the_check_catches_each_form_of_import(tmp_path):
    planted = tmp_path / "planted.py"
    planted.write_text(
        "import ospipe\n"
        "import audit_layer.cli as cli\n"
        "from verification_procedures import vg\n"
        "from vg import main\n"
        "import _lib.sentences\n"
        "import importlib\n"
        "importlib.import_module('observability.build')\n"
        "__import__('connections')\n"
        "import os, json\n"
        "from . import layers\n",
        encoding="utf-8")
    found = [line.split(" ", 1)[1] for line in import_problems(planted)]
    assert found == ["ospipe", "audit_layer.cli", "verification_procedures", "vg",
                     "_lib.sentences", "observability.build", "connections"]
