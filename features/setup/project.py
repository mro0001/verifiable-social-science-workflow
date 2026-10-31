"""Project setup, once per project (step F5).

python3 -m features setup project DIR [--home DIR] [--answers FILE]
    [--title TEXT] [--product NAME:SOURCE:FORMAT ...]

Setup loads system.yaml (step F3) and refuses without it. It lays out the
project skeleton (step F4), installs the notes templates with ospipe
install-notes, adds each product's rule to a new build file with ospipe
add-product, appends only the rule that copies the citation manager's export
to refs.bib, and runs ospipe check on each product's source. It never
overwrites, changes, or removes a file that exists (track F choice 6), so a
build file that exists is kept and gets no rule. It then reads the products
the build file names with ospipe products --json, prints make <product> only
for those, and gives the add-product line for each answered product the
build file lacks, which leaves the project not ready.

By the reconciliation (Track F), setup runs no git init and refuses no
folder for being excluded. It prints the run command of the GitHub
procedure from the procedures-ops-github entry when that entry exists, since
adding a project to version control is an operational procedure.

A session's project is the folder it ran in, so a project needs no
registration for capture (slice choice 4).
"""
import collections
import datetime
import glob
import json
import os
import shlex
import sys

import yaml

from features.layers import LayerMissing, run_layer
from features.setup import skeleton
from features.setup.skeleton import DEFAULT_PRODUCTS, Product, SkeletonError
from features.setup.system import COMMAND as SYSTEM_COMMAND
from features.setup.system import (DEFAULT_HOME, LATER_CONNECTIONS, SetupError,
                                   features_home, load_system)

COMMAND = "python3 -m features setup project"
FIELDS = ("title", "products", "citation_export")
PRODUCT_FIELDS = ("name", "source", "to")
PRODUCT_FORM = "NAME:SOURCE:FORMAT"
MAKEFILE = "Makefile"
MANIFEST = "numbers.yml"
GITHUB_ENTRY = "procedures-ops-github"
RUN_COMMAND = "4. Run command. "

CheckResult = collections.namedtuple("CheckResult", "source returncode problem")
ProjectResult = collections.namedtuple(
    "ProjectResult",
    "project_dir title products created kept notes_written notes_kept added makefile_kept"
    " rule_appended built missing add_lines differs build_problems checks github messages ok")


def _product_from_mapping(item, where):
    if not isinstance(item, dict):
        raise SetupError("%s must give each product as a mapping with %s"
                         % (where, ", ".join(PRODUCT_FIELDS)))
    unknown = sorted(str(key) for key in item if key not in PRODUCT_FIELDS)
    absent = [key for key in PRODUCT_FIELDS if key not in item]
    if unknown or absent:
        raise SetupError("%s must give each product exactly %s"
                         % (where, ", ".join(PRODUCT_FIELDS)))
    return Product(str(item["name"]), str(item["source"]), str(item["to"]))


def parse_product(text):
    """A Product from NAME:SOURCE:FORMAT, or SetupError."""
    parts = str(text).split(":", 1)
    if len(parts) == 2 and ":" in parts[1]:
        source, to = parts[1].rsplit(":", 1)
        if parts[0] and source and to:
            return Product(parts[0], source, to)
    raise SetupError("the product %r must be given as %s, such as manuscript:manuscript.md:docx"
                     % (text, PRODUCT_FORM))


def _check_answers(given, where):
    """The answers with each field checked, as title, products, and citation_export.

    products is a list of Product or None for the default. citation_export is
    None when the answers leave it to system.yaml, and "" for none.
    """
    if given is None:
        given = {}
    if not isinstance(given, dict):
        raise SetupError("%s must be a mapping with the fields %s" % (where, ", ".join(FIELDS)))
    unknown = sorted(str(key) for key in given if key not in FIELDS)
    if unknown:
        raise SetupError("%s has no field named %s. The fields are %s"
                         % (where, ", ".join(unknown), ", ".join(FIELDS)))
    title = given.get("title")
    if title is not None and not isinstance(title, str):
        raise SetupError("%s must give title as text" % where)
    products = given.get("products")
    if products is not None:
        if not isinstance(products, list) or not products:
            raise SetupError("%s must give products as a list of mappings with %s"
                             % (where, ", ".join(PRODUCT_FIELDS)))
        products = [_product_from_mapping(item, where) for item in products]
    export = None
    if "citation_export" in given:
        export = given["citation_export"]
        if export is None:
            export = ""
        if not isinstance(export, str):
            raise SetupError("%s must give citation_export as a file, or leave it empty" % where)
        export = export.strip()
    return {"title": (title or "").strip(), "products": products, "citation_export": export}


def read_answers(path):
    """The fields an answers file gives, checked, as a mapping of the fields it names."""
    try:
        with open(path, encoding="utf-8") as handle:
            given = yaml.safe_load(handle)
    except OSError as error:
        raise SetupError("the answers file %s cannot be read (%s)" % (path, error))
    except yaml.YAMLError as error:
        raise SetupError("the answers file %s is not YAML that can be read (%s)" % (path, error))
    if given is None:
        given = {}
    _check_answers(given, "the answers file %s" % path)
    return given


def ask_answers(folder_name, system, given, ask=None, out=sys.stdout):
    """Ask in the terminal for each field the file and the flags did not give."""
    ask = ask or input
    answers = dict(given)
    if "title" not in answers:
        answers["title"] = ask("The project's title [%s]. " % folder_name).strip() or folder_name
    if "products" not in answers:
        out.write("Each research product, one a line as %s, where FORMAT is docx or revealjs."
                  " An empty line ends, and none gives the manuscript alone.\n" % PRODUCT_FORM)
        products = []
        while True:
            line = ask("Product, or an empty line to end. ").strip()
            if not line:
                break
            try:
                product = parse_product(line)
            except SetupError as error:
                text = str(error)
                out.write(text[:1].upper() + text[1:] + "\n")
                continue
            products.append(dict(product._asdict()))
        answers["products"] = products or [dict(item._asdict()) for item in DEFAULT_PRODUCTS]
    if "citation_export" not in answers:
        default = system.get("citation_export") or ""
        reply = ask("The BibTeX file your citation manager exports [%s], or none. "
                    % (default or "none")).strip()
        if reply.lower() == "none":
            reply = ""
        elif not reply:
            reply = default
        answers["citation_export"] = reply
    _check_answers(answers, "the answers given")
    return answers


def github_run_command(root):
    """The run command of the GitHub procedure from its knowledge base entry, or ""."""
    pattern = os.path.join(str(root), "audit_layer", "kb", "corpus", "*", GITHUB_ENTRY + ".md")
    for path in sorted(glob.glob(pattern)):
        try:
            with open(path, encoding="utf-8") as handle:
                lines = handle.read().splitlines()
        except OSError:
            continue
        for line in lines:
            if line.startswith(RUN_COMMAND):
                return line[len(RUN_COMMAND):].strip()
    return ""


def _ospipe(runner, root, args, cwd=None):
    try:
        return runner("ospipe", args, root=root, cwd=cwd)
    except LayerMissing as error:
        raise SetupError("ospipe %s could not run, %s" % (args[0], error))


def _failed(done, what):
    return SetupError("%s failed with exit %d. %s"
                      % (what, done.returncode, (done.stderr or done.stdout).strip()))


def _add_product_args(product):
    return ["add-product", "--name", product.name, "--source", product.source,
            "--to", product.to, "--bib", skeleton.REFS, "--tables-dir", "."]


def _add_product_line(root, product):
    """The shell line that adds one product's rule, run in the project folder."""
    words = ["python3", "-m", "ospipe"] + _add_product_args(product)
    return "PYTHONPATH=%s %s" % (shlex.quote(os.path.join(str(root), "ospipe")),
                                 " ".join(shlex.quote(word) for word in words))


def _build_file(runner, root, folder):
    """The products the project's build file names and its problems, from ospipe products --json.

    A nonzero exit with no problem named is itself a problem.
    """
    done = _ospipe(runner, root, ["products", "--json"], cwd=folder)
    try:
        found = json.loads(done.stdout)
        products = [dict(item) for item in found["products"]]
        problems = [str(problem) for problem in found["problems"]]
        for item in products:
            item["name"] = str(item["name"])
    except (ValueError, TypeError, KeyError):
        raise _failed(done, "ospipe products")
    if done.returncode != 0 and not problems:
        problems.append("ospipe products exited %d" % done.returncode)
    return products, problems


def _same_path(one, other):
    if one is None or other is None:
        return False
    return os.path.normpath(str(one)) == os.path.normpath(str(other))


def _problem_names(problems):
    """The products a problem names, from the '<product>: ' each problem from ospipe starts with."""
    return set(problem.split(": ", 1)[0] for problem in problems if ": " in problem)


def _compare(products, found, problems):
    """The names to build, the answered products missing, and those the build file builds otherwise."""
    by_name = {}
    for item in found:
        by_name.setdefault(item["name"], item)
    missing, differs = [], []
    for product in products:
        item = by_name.get(product.name)
        if item is None:
            missing.append(product)
        elif not _same_path(item.get("source"), product.source) or item.get("to") != product.to:
            differs.append((product, item))
    held = _problem_names(problems) | set(product.name for product, _ in differs)
    built = []
    for item in found:
        if item["name"] not in held and item["name"] not in built:
            built.append(item["name"])
    return built, missing, differs


def _notes(done):
    written, kept = [], []
    for line in done.stdout.splitlines():
        if line.startswith("wrote "):
            written.append(line[len("wrote "):].strip())
        elif line.startswith("skipped "):
            kept.append(line[len("skipped "):].split(",", 1)[0].strip())
    return written, kept


def run_project_setup(project_dir, home, answers, now, runner=run_layer):
    """Lay out one project, add its build rules, and check each product's source."""
    system = load_system(home)
    root = system["workflow_root"]
    given = _check_answers(answers, "the answers")
    folder = os.path.abspath(os.path.expanduser(str(project_dir)))
    if os.path.lexists(folder) and not os.path.isdir(folder):
        raise SetupError("%s exists and is not a folder" % folder)

    products = given["products"] or list(DEFAULT_PRODUCTS)
    export = given["citation_export"]
    if export is None:
        export = system.get("citation_export") or ""
    try:
        planned = skeleton.plan_skeleton(folder, given["title"], products, export or None, now)
    except SkeletonError as error:
        raise SetupError("the project cannot be set up. " + "; ".join(error.problems))
    title = given["title"] or os.path.basename(folder)
    if not os.path.isdir(os.path.join(str(root), "ospipe", "ospipe")):
        raise SetupError("the workflow_root %s that system.yaml records holds no ospipe. Run %s"
                         " again from the workflow's folder." % (root, SYSTEM_COMMAND))

    makefile = os.path.join(folder, MAKEFILE)
    makefile_kept = os.path.lexists(makefile)
    os.makedirs(folder, exist_ok=True)
    # The report's Kept list names each kept file, so the skeleton's messages are left out.
    laid = skeleton.write_skeleton(folder, planned)
    messages = []

    done = _ospipe(runner, root, ["install-notes", "--project", folder])
    if done.returncode != 0:
        raise _failed(done, "ospipe install-notes")
    notes_written, notes_kept = _notes(done)

    added = []
    rule_appended = False
    if not makefile_kept:
        for product in products:
            done = _ospipe(runner, root, _add_product_args(product), cwd=folder)
            if done.returncode != 0:
                raise _failed(done, "ospipe add-product for %s" % product.name)
            added.append(product)
        addition = skeleton.makefile_text(products, export or None, folder)
        messages.extend(addition.messages)
        if addition.text:
            with open(makefile, "a", encoding="utf-8") as handle:
                handle.write(addition.text)
            rule_appended = True

    found, build_problems = _build_file(runner, root, folder)
    built, missing, differs = _compare(products, found, build_problems)
    add_lines = [_add_product_line(root, product) for product in missing]

    checks = []
    for product in products:
        done = _ospipe(runner, root, ["check", "--manuscript", product.source,
                                      "--manifest", MANIFEST, "--tables-dir", "."], cwd=folder)
        problem = "" if done.returncode == 0 else (done.stderr or done.stdout).strip()
        checks.append(CheckResult(product.source, done.returncode, problem))

    ok = (all(check.returncode == 0 for check in checks) and not missing and not differs
          and not build_problems)
    return ProjectResult(folder, title, products, laid.created, laid.kept, notes_written,
                         notes_kept, added, makefile_kept, rule_appended, built, missing,
                         add_lines, differs, build_problems, checks, github_run_command(root),
                         messages, ok)


# The command.


def _interactive():
    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def add_command(commands):
    parser = commands.add_parser(
        "project", help="set up one project",
        description="Lay out a reproducible project once per project, so it builds with make.")
    parser.add_argument("dir", metavar="DIR", help="the project folder, made when absent")
    parser.add_argument("--home", help="the features home, else FEATURES_HOME, else " + DEFAULT_HOME)
    parser.add_argument("--answers", help="a YAML file giving any of " + ", ".join(FIELDS))
    parser.add_argument("--title", help="the project's title, by default the folder's name")
    parser.add_argument("--product", action="append", metavar=PRODUCT_FORM,
                        help="a research product, given once for each, by default"
                        " manuscript:manuscript.md:docx")
    parser.set_defaults(run=command)


def _list(out, heading, items):
    out.write(heading + "\n")
    for item in items:
        out.write("  %s\n" % item)
    if not items:
        out.write("  none\n")


def _report(result, out):
    out.write("Project %s\n" % result.project_dir)
    _list(out, "Created", result.created)
    _list(out, "Kept", result.kept)
    _list(out, "Notes written", result.notes_written)
    if result.notes_kept:
        _list(out, "Notes kept", result.notes_kept)
    out.write("Build file\n")
    if result.makefile_kept:
        out.write("  Makefile kept as it was, so setup added no rule to it\n")
    for product in result.added:
        out.write("  added %s, built from %s as %s\n" % (product.name, product.source, product.to))
    if result.rule_appended:
        out.write("  added the rule that copies the citation export to refs.bib\n")
    for message in result.messages:
        out.write(message[:1].upper() + message[1:] + "\n")
    out.write("Checks\n")
    for check in result.checks:
        if check.returncode == 0:
            out.write("  %s passed\n" % check.source)
        else:
            out.write("  %s failed with exit %d. %s\n" % (check.source, check.returncode,
                                                         check.problem))
    _list(out, "Build each product in %s with" % result.project_dir,
          ["make " + name for name in result.built])
    if result.missing:
        out.write("The build file has no rule for %s. Add each in %s with\n"
                  % (", ".join(product.name for product in result.missing), result.project_dir))
        for line in result.add_lines:
            out.write("  %s\n" % line)
    if result.differs:
        out.write("The build file builds a product otherwise than answered, and setup changes"
                  " no rule in it\n")
        for product, found in result.differs:
            out.write("  %s is built from %s as %s, not from %s as %s\n"
                      % (product.name, found.get("source") or "no source", found.get("to"),
                         product.source, product.to))
    if result.build_problems:
        _list(out, "Problems ospipe products found in the build file", result.build_problems)
    out.write("Version control\n")
    if result.github:
        out.write("  Setup runs no git. To add the project to version control on GitHub, use the"
                  " GitHub procedure. %s\n" % result.github)
    else:
        out.write("  Setup runs no git.\n")
    out.write("Later connections\n")
    for line in LATER_CONNECTIONS:
        out.write("  %s\n" % line)
    if result.ok:
        out.write("Ready\n")
        return
    reasons = []
    if any(check.returncode != 0 for check in result.checks):
        reasons.append("a check failed")
    if result.missing:
        reasons.append("the build file has no rule for %s"
                       % ", ".join(product.name for product in result.missing))
    if result.differs:
        reasons.append("the build file builds %s otherwise than answered"
                       % ", ".join(product.name for product, _ in result.differs))
    if result.build_problems:
        reasons.append("the build file has a problem")
    out.write("Not ready, since %s\n" % " and ".join(reasons))


def command(options, out=None, err=None):
    out = out or sys.stdout
    err = err or sys.stderr
    try:
        given = read_answers(options.answers) if options.answers else {}
        if options.title is not None:
            given["title"] = options.title
        if options.product:
            given["products"] = [dict(parse_product(text)._asdict()) for text in options.product]
        home = features_home(options.home)
        if not options.answers and _interactive():
            name = os.path.basename(os.path.abspath(os.path.expanduser(options.dir)))
            given = ask_answers(name, load_system(home), given, out=out)
        result = run_project_setup(options.dir, home, given,
                                   datetime.datetime.now(datetime.timezone.utc))
    except SetupError as error:
        err.write("setup project stopped, %s\n" % error)
        return 1
    _report(result, out)
    return 0 if result.ok else 1
