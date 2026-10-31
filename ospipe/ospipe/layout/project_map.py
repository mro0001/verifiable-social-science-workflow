"""Reading the project's build file, a Makefile with one rule per research product.

A product is a rule whose recipe runs `ospipe build`. Its fields come from that
command's options, as paths relative to the project folder (the Makefile's folder).
"""
import os
import re
import shlex
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple


class Product(NamedTuple):
    name: str
    source: Optional[str]
    builds_dir: Optional[str]
    to: str
    manifest: Optional[str]
    overlay: Optional[str]
    tables_dir: Optional[str]
    bib: Optional[str]
    csl: Optional[str]
    reference_doc: Optional[str]
    verification_dir: Optional[str]
    purpose: Optional[str]


class ProjectMap(NamedTuple):
    project_dir: str
    products: List[Product]
    problems: List[str]


# The build command's options the reader takes, by the Product field each fills.
OPTIONS = {
    "--manuscript": "source",
    "--builds-dir": "builds_dir",
    "--to": "to",
    "--manifest": "manifest",
    "--overlay": "overlay",
    "--tables-dir": "tables_dir",
    "--bib": "bib",
    "--csl": "csl",
    "--reference-doc": "reference_doc",
    "--verification-dir": "verification_dir",
    "--purpose": "purpose",
}
PATH_FIELDS = (
    "source",
    "builds_dir",
    "manifest",
    "overlay",
    "tables_dir",
    "bib",
    "csl",
    "reference_doc",
    "verification_dir",
)
DEFAULT_TO = "docx"
DEFAULT_VERIFICATION = "verification"

_ASSIGN = re.compile(r"^([^\s:#=?+]+)\s*(:=|\?=|=)\s*(.*)$")
_REFERENCE = re.compile(r"\$(?:\(([^()]*)\)|\{([^{}]*)\}|(\$)|([^({$]))")
_SHELL_BREAKS = set(";&|()<>")


class _Rule(NamedTuple):
    targets: List[str]
    recipe: List[str]


class _Parsed(NamedTuple):
    variables: Dict[str, Tuple[str, bool]]
    rules: List[_Rule]


def _logical_lines(text):
    """Join backslash continuations. A recipe line keeps a mark that it is one."""
    lines = text.splitlines()
    joined = []
    i = 0
    while i < len(lines):
        line = lines[i]
        is_recipe = line.startswith("\t")
        while _continues(line) and i + 1 < len(lines):
            i += 1
            following = lines[i]
            if is_recipe and following.startswith("\t"):
                following = following[1:]
            line = line[:-1].rstrip() + " " + following.lstrip()
        joined.append(line)
        i += 1
    return joined


def _continues(line):
    trailing = len(line) - len(line.rstrip("\\"))
    return trailing % 2 == 1


def _strip_comment(line):
    out = []
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == "\\" and i + 1 < len(line) and line[i + 1] == "#":
            out.append("#")
            i += 2
            continue
        if ch == "#":
            break
        out.append(ch)
        i += 1
    return "".join(out).rstrip()


def _expand(text, variables, depth=0):
    if depth > 50:
        return text

    def replace(match):
        if match.group(3):
            return "$"
        name = match.group(1)
        if name is None:
            name = match.group(2)
        if name is None:
            name = match.group(4)
        name = name.strip()
        if name not in variables:
            return ""
        value, recursive = variables[name]
        return _expand(value, variables, depth + 1) if recursive else value

    return _REFERENCE.sub(replace, text)


def _parse(text) -> _Parsed:
    variables: Dict[str, Tuple[str, bool]] = {}
    rules: List[_Rule] = []
    current: Optional[_Rule] = None
    for line in _logical_lines(text):
        if line.startswith("\t") and current is not None:
            current.recipe.append(line[1:])
            continue
        stripped = _strip_comment(line)
        if not stripped.strip():
            continue
        assign = _ASSIGN.match(stripped.strip())
        if assign:
            current = None
            name, op, value = assign.group(1), assign.group(2), assign.group(3).strip()
            if op == ":=":
                variables[name] = (_expand(value, variables), False)
            elif op == "?=":
                if name not in variables:
                    variables[name] = (value, True)
            else:
                variables[name] = (value, True)
            continue
        if ":" in stripped:
            before = stripped.split(":", 1)[0]
            targets = _expand(before, variables).split()
            current = _Rule(targets=targets, recipe=[])
            rules.append(current)
            continue
        current = None
    return _Parsed(variables=variables, rules=rules)


def _words(command):
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    return list(lexer)


def _build_options(recipe_line, variables):
    """The words after `<...>ospipe build` up to the end of that shell command, or None."""
    line = _expand(recipe_line, variables).lstrip()
    while line[:1] in ("@", "-", "+"):
        line = line[1:].lstrip()
    try:
        words = _words(line)
    except ValueError:
        return None
    for i in range(len(words) - 1):
        if words[i].endswith("ospipe") and words[i + 1] == "build":
            rest = []
            for word in words[i + 2:]:
                if word and set(word) <= _SHELL_BREAKS:
                    break
                rest.append(word)
            return rest
    return None


def _relative(path, project_dir):
    if path is None:
        return None
    candidate = Path(path)
    if candidate.is_absolute():
        try:
            candidate = candidate.resolve().relative_to(project_dir)
        except ValueError:
            return os.path.normpath(path)
    return Path(os.path.normpath(str(candidate))).as_posix()


def _product(name, options, project_dir, problems):
    values: Dict[str, Optional[str]] = {field: None for field in OPTIONS.values()}
    counts: Dict[str, int] = {}
    i = 0
    while i < len(options):
        word = options[i]
        flag, value = word, None
        if word.startswith("--") and "=" in word:
            flag, value = word.split("=", 1)
        if flag in OPTIONS:
            if value is None and i + 1 < len(options) and not options[i + 1].startswith("--"):
                i += 1
                value = options[i]
            if value is not None:
                counts[flag] = counts.get(flag, 0) + 1
                values[OPTIONS[flag]] = value
        i += 1

    if counts.get("--manuscript", 0) == 0:
        problems.append("{0}: no --manuscript".format(name))
    elif counts["--manuscript"] > 1:
        problems.append("{0}: more than one --manuscript".format(name))
        values["source"] = None
    if counts.get("--manifest", 0) == 0:
        problems.append("{0}: no --manifest".format(name))
    if counts.get("--builds-dir", 0) == 0:
        problems.append("{0}: no --builds-dir".format(name))

    for field in PATH_FIELDS:
        values[field] = _relative(values[field], project_dir)
    if values["source"] is not None:
        source_path = Path(values["source"])
        if not source_path.is_absolute():
            source_path = project_dir / source_path
        if not source_path.is_file():
            problems.append("{0}: source {1} does not exist".format(name, values["source"]))
        if values["verification_dir"] is None:
            beside = Path(values["source"]).parent / DEFAULT_VERIFICATION
            values["verification_dir"] = _relative(str(beside), project_dir)
    if values["to"] is None:
        values["to"] = DEFAULT_TO
    return Product(name=name, **values)


def _targets(parsed):
    found = []
    for rule in parsed.rules:
        for target in rule.targets:
            if target not in found:
                found.append(target)
    return found


def read_map(makefile_path) -> ProjectMap:
    makefile = Path(makefile_path)
    text = makefile.read_text(encoding="utf-8")
    return _map_from_text(text, makefile.resolve().parent)


def _map_from_text(text, project_dir) -> ProjectMap:
    """The map a build file holding `text` in `project_dir` reads as."""
    project_dir = Path(project_dir)
    parsed = _parse(text)
    products: List[Product] = []
    problems: List[str] = []
    for rule in parsed.rules:
        options = None
        for recipe_line in rule.recipe:
            options = _build_options(recipe_line, parsed.variables)
            if options is not None:
                break
        if options is None:
            continue
        for target in rule.targets:
            if target.startswith("."):
                continue
            products.append(_product(target, options, project_dir, problems))

    seen: Dict[str, str] = {}
    for product in products:
        if product.builds_dir is None:
            continue
        if product.builds_dir in seen:
            problems.append(
                "{0}: shares the builds dir {1} with {2}".format(
                    product.name, product.builds_dir, seen[product.builds_dir]
                )
            )
        else:
            seen[product.builds_dir] = product.name
    return ProjectMap(project_dir=str(project_dir), products=products, problems=problems)
