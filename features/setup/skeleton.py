"""The project skeleton (step F4).

A new project follows the sample project's flat layout (track F choice 10).
The skeleton plans the project's files from the templates in
project_template/ and writes each one only when it is absent, so it never
changes or removes a file that exists (track F choice 6).

By the reconciliation (Track F), the skeleton writes no .gitignore, no
Makefile, and no notes. Project setup (step F5) adds each product's rule with
ospipe add-product, installs the notes with ospipe install-notes, and appends
only the rule that copies the citation manager's export to refs.bib, whose
text makefile_text gives (track F choice 12).

Nothing here runs a command.
"""
import collections
import datetime
import os
import posixpath
import re

TEMPLATES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "project_template")

# The template each fixed file is written from, and where it goes.
FIXED = (
    ("README.md", "README.md"),
    ("numbers.yml", "numbers.yml"),
    ("pipeline.yaml", "pipeline.yaml"),
    ("params.yaml", "params.yaml"),
    ("acquisition.yaml", "acquisition.yaml"),
    ("verification_README.md", "verification/README.md"),
)
REFS = "refs.bib"
# The template a product's source is written from, by the product's format.
SOURCE_TEMPLATES = {"docx": "manuscript.md", "revealjs": "slides.md"}

NAME = re.compile(r"^[a-z][a-z0-9_]*$")
# ospipe add-product writes rules with these names into a new build file.
RESERVED = ("manifest", "emit")
# Paths a product's source may not take, since the skeleton or the build uses them.
TAKEN = tuple(path for _, path in FIXED) + (REFS, "Makefile")
# The first headings of the two guides, which a title may not read as.
HEADINGS = ("Project guide", "Verification results")
# Characters make cannot take in a file name in a rule.
MAKE_UNSAFE = re.compile(r"[\n\r:%\\*?\[]")
TOKEN = re.compile(r"@@(TITLE|DATE)@@")

Product = collections.namedtuple("Product", "name source to")
DEFAULT_PRODUCTS = [Product("manuscript", "manuscript.md", "docx")]

PlannedFile = collections.namedtuple("PlannedFile", "path data")
SkeletonResult = collections.namedtuple("SkeletonResult", "created kept messages")
MakefileText = collections.namedtuple("MakefileText", "text messages")


class SkeletonError(ValueError):
    """The skeleton cannot be planned. .problems lists every reason at once."""

    def __init__(self, problems):
        self.problems = list(problems)
        ValueError.__init__(self, "; ".join(self.problems))


def _plain(text):
    return " ".join(str(text).split()).lower()


def _quoted(text):
    """A YAML double-quoted string holding text."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _title_problems(title):
    problems = []
    if "\n" in title or "\r" in title:
        problems.append("the title must be one line")
    if "{{" in title:
        problems.append("the title may not hold a placeholder's two opening braces")
    if "@@" in title:
        problems.append("the title may not hold @@")
    if _plain(title) in [_plain(heading) for heading in HEADINGS]:
        problems.append("the title may not be {0!r}, the heading of one of the project's guides".format(title))
    return problems


def check_products(products):
    """Every problem with the products, as a list of plain lines."""
    problems = []
    if not products:
        problems.append("a project needs at least one product")
    names = []
    sources = []
    for product in products:
        name, source, to = product.name, product.source, product.to
        if not NAME.match(str(name)):
            problems.append("product name {0!r} must be lower case letters, digits, and _, starting with a letter".format(name))
        elif name in RESERVED:
            problems.append("product name {0!r} is the name of a rule the build file already has".format(name))
        if to not in SOURCE_TEMPLATES:
            problems.append("product {0!r} has format {1!r}, which must be docx or revealjs".format(name, to))
        normal = posixpath.normpath(str(source).replace(os.sep, "/"))
        if (not source or posixpath.isabs(normal) or normal == ".." or normal.startswith("../")
                or normal == "."):
            problems.append("product {0!r} has source {1!r}, which must be a file inside the project".format(name, source))
        elif normal in TAKEN:
            problems.append("product {0!r} has source {1!r}, which the project uses for another file".format(name, source))
        if name in names:
            problems.append("product name {0!r} is given twice".format(name))
        if normal in sources:
            problems.append("source {0!r} is given to two products".format(source))
        names.append(name)
        sources.append(normal)
    return problems


def _fill(text, title, date):
    values = {"TITLE": _quoted(title), "DATE": date}
    return TOKEN.sub(lambda match: values[match.group(1)], text)


def _template(name):
    with open(os.path.join(TEMPLATES, name), "r", encoding="utf-8") as handle:
        return handle.read()


def _readme(text, products):
    """The guide's template with each product listed under its Products heading."""
    lines = ["- `{0}`, built from `{1}` as {2} with `make {0}`.".format(
        product.name, posixpath.normpath(product.source),
        "a Word document" if product.to == "docx" else "reveal.js slides")
        for product in products]
    heading = "## Products\n"
    at = text.index(heading) + len(heading)
    return text[:at] + "\n" + "\n".join(lines) + "\n" + text[at:]


def plan_skeleton(project_dir, title, products, citation_export, now):
    """The files of a new project, as PlannedFile(path, data), writing nothing.

    path is relative to the project folder and data is bytes. title defaults
    to the folder's name. refs.bib is empty, or a copy of citation_export when
    that file exists.
    """
    title = title if title and str(title).strip() else os.path.basename(os.path.abspath(str(project_dir)))
    title = str(title)
    problems = _title_problems(title) + check_products(products)
    if problems:
        raise SkeletonError(problems)
    date = now.date().isoformat() if isinstance(now, datetime.datetime) else str(now)

    planned = []
    for template, path in FIXED:
        text = _fill(_template(template), title, date)
        if path == "README.md":
            text = _readme(text, products)
        planned.append(PlannedFile(path, text.encode("utf-8")))
    for product in products:
        text = _fill(_template(SOURCE_TEMPLATES[product.to]), title, date)
        planned.append(PlannedFile(posixpath.normpath(product.source), text.encode("utf-8")))
    refs = b""
    if citation_export and os.path.isfile(os.path.expanduser(str(citation_export))):
        with open(os.path.expanduser(str(citation_export)), "rb") as handle:
            refs = handle.read()
    planned.append(PlannedFile(REFS, refs))
    return sorted(planned, key=lambda item: item.path)


def write_skeleton(project_dir, planned):
    """Write each planned file only when it is absent. Never change or remove one."""
    created = []
    kept = []
    messages = []
    for item in planned:
        target = os.path.join(str(project_dir), *item.path.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        try:
            handle = open(target, "xb")
        except FileExistsError:
            kept.append(item.path)
            messages.append("kept {0} as it was, since setup never changes a file that exists".format(item.path))
            continue
        with handle:
            handle.write(item.data)
        created.append(item.path)
    return SkeletonResult(created, kept, messages)


def _make_name(path):
    """A file name as a make rule's target or prerequisite."""
    return path.replace("$", "$$").replace("#", "\\#").replace(" ", "\\ ")


def _shell_quoted(path):
    """A file name single-quoted for the shell, inside a make recipe."""
    return "'" + path.replace("$", "$$").replace("'", "'\\''") + "'"


def makefile_text(products, citation_export, project_dir):
    """The one rule this track appends to the build file ospipe add-product wrote.

    The rule copies the citation manager's export to refs.bib whenever the
    export is newer, and each product needs refs.bib, so each build uses the
    scholar's current library. The text is empty, with a message, when the
    export is missing, has a name make cannot take, or refs.bib already holds
    something else. It is empty with no message when there is no export.
    """
    if not citation_export:
        return MakefileText("", [])
    export = os.path.abspath(os.path.expanduser(str(citation_export)))
    if not os.path.isfile(export):
        return MakefileText("", ["the citation export {0} was not found, so no rule copies it to refs.bib".format(export)])
    if MAKE_UNSAFE.search(export):
        return MakefileText("", ["the citation export {0} has a character make cannot take in a file name,"
                                 " so no rule copies it to refs.bib".format(export)])
    refs = os.path.join(str(project_dir), REFS)
    if os.path.lexists(refs):
        with open(export, "rb") as handle:
            wanted = handle.read()
        try:
            with open(refs, "rb") as handle:
                held = handle.read()
        except OSError:
            held = None
        if held != wanted:
            return MakefileText("", ["refs.bib already holds references other than the citation export {0},"
                                     " so no rule copies the export over it".format(export)])
    names = " ".join(product.name for product in products)
    lines = [
        "",
        "# refs.bib is copied from the citation manager's export whenever the export is newer.",
        "refs.bib: {0}".format(_make_name(export)),
        "\tcp {0} refs.bib".format(_shell_quoted(export)),
        "",
        "{0}: refs.bib".format(names),
        "",
    ]
    return MakefileText("\n".join(lines), [])
