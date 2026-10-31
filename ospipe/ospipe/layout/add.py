"""Adding a product to the project's build file.

This is the one place the build file's format is written. It only appends and never
changes earlier text.
"""
import re
import shlex
from pathlib import Path
from typing import List

from .project_map import Product, _map_from_text, _parse, _relative, _targets, read_map

HEADER = "# The build file. One rule per research product, each naming its one source file.\n"
TO_CHOICES = ("docx", "revealjs", "html")
MANIFEST_RULE = "manifest"
EMIT_RULE = "emit"
DEFAULT_MANIFEST = "numbers.yml"
DEFAULT_PURPOSE = "draft"
_NAME = re.compile(r"[A-Za-z0-9_-]+")


class AddProductError(ValueError):
    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("cannot add the product\n" + "\n".join("  " + p for p in self.problems))


def ospipe_home() -> str:
    """The absolute folder that holds the ospipe package."""
    return str(Path(__file__).resolve().parents[2])


def _make_text(text):
    return text.replace("$", "$$")


def _word(path):
    return _make_text(shlex.quote(path))


def _variable_lines(defined, with_product):
    home = ospipe_home().replace("'", "'\"'\"'")
    wanted = [
        ("OSPIPE", "PYTHONPATH='{0}' python3 -m ospipe".format(_make_text(home))),
        ("MANIFEST", DEFAULT_MANIFEST),
        ("PURPOSE", DEFAULT_PURPOSE),
    ]
    if with_product:
        wanted.append(("PRODUCT", ""))
    lines = []
    for name, value in wanted:
        if name not in defined:
            lines.append("{0} ?= {1}".format(name, value).rstrip() + "\n")
    return lines


def _manifest_rule():
    return "{0}:\n\t$(OSPIPE) emit-manifest --manifest $(MANIFEST)\n".format(MANIFEST_RULE)


def _emit_rule():
    return "{0}:\n\t$(OSPIPE) emit --map Makefile --product $(PRODUCT)\n".format(EMIT_RULE)


def _product_rule(name, source, to, builds_dir, tables_dir, bib, csl, reference_doc):
    words = ["$(OSPIPE)", "build", "--manuscript", _word(source), "--manifest", "$(MANIFEST)"]
    for flag, value in (
        ("--tables-dir", tables_dir),
        ("--bib", bib),
        ("--csl", csl),
        ("--reference-doc", reference_doc),
    ):
        if value is not None:
            words.extend([flag, _word(value)])
    words.extend(["--to", to, "--builds-dir", _word(builds_dir), "--purpose", '"$(PURPOSE)"'])
    return ".PHONY: {0}\n{0}: {1} $(MANIFEST)\n\t{2}\n".format(name, _make_text(source), " ".join(words))


def add_product(
    makefile_path,
    name,
    source,
    to="docx",
    builds_dir=None,
    bib=None,
    csl=None,
    reference_doc=None,
    tables_dir=None,
) -> Product:
    makefile = Path(makefile_path)
    project_dir = makefile.parent.resolve()
    text = makefile.read_text(encoding="utf-8") if makefile.is_file() else None
    parsed = _parse(text or "")
    targets = _targets(parsed)
    write_manifest = MANIFEST_RULE not in targets
    write_emit = EMIT_RULE not in targets
    for rule_name, missing in ((MANIFEST_RULE, write_manifest), (EMIT_RULE, write_emit)):
        if missing:
            targets.append(rule_name)

    problems: List[str] = []
    if not _NAME.fullmatch(name or ""):
        problems.append("name {0!r} may hold only letters, digits, _, and -".format(name))
    elif name in targets:
        problems.append("{0} is already a target in {1}".format(name, makefile))
    if to not in TO_CHOICES:
        problems.append("--to {0} is not one of {1}".format(to, ", ".join(TO_CHOICES)))

    source = _relative(source, project_dir)
    source_path = Path(source)
    if not source_path.is_absolute():
        source_path = project_dir / source_path
    if not source_path.is_file():
        problems.append("source {0} does not exist".format(source))

    if builds_dir is None:
        builds_dir = "builds/{0}".format(name)
    builds_dir = _relative(builds_dir, project_dir)
    if text is not None:
        for product in read_map(makefile).products:
            if product.builds_dir == builds_dir:
                problems.append("builds dir {0} is used by {1}".format(builds_dir, product.name))
    if problems:
        raise AddProductError(problems)

    paths = [_relative(p, project_dir) for p in (tables_dir, bib, csl, reference_doc)]
    rule = _product_rule(name, source, to, builds_dir, *paths)

    added = []
    if text is None:
        added.append(HEADER)
        added.append("\n")
        added.extend(_variable_lines(set(), write_emit))
        added.append("\n")
        added.append(_manifest_rule())
        added.append("\n")
        added.append(_emit_rule())
    else:
        if text and not text.endswith("\n"):
            added.append("\n")
        variables = _variable_lines(set(parsed.variables), write_emit)
        if variables:
            added.append("\n")
            added.extend(variables)
        for missing, rule_text in ((write_manifest, _manifest_rule()), (write_emit, _emit_rule())):
            if missing:
                added.append("\n")
                added.append(rule_text)
    added.append("\n")
    added.append(rule)
    appended = "".join(added)

    for product in _map_from_text((text or "") + appended, project_dir).products:
        if product.name == name:
            break
    else:
        raise AddProductError(
            ["{0} would not read back as a product from {1}, so nothing was written".format(name, makefile)]
        )

    with open(str(makefile), "a", encoding="utf-8", newline="") as handle:
        handle.write(appended)
    return product
