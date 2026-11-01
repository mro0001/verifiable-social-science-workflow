"""The two publish commands (publish design A.6, R16).

python3 -m features publish plan DIR [--answers FILE] [--runs DIR] [--home DIR] [--json]
python3 -m features publish build DIR --out OUT [--answers FILE] [--runs DIR] [--home DIR]

Both are thin wrappers around assemble.run_publish. publish plan writes
nothing and runs no session index. It prints the products, the reports and
where each came from, the streams with no results file, how many project files
would be copied, what is left out and why, where the session index would come
from, and the notes, or with --json one JSON object with the same content for
an AI session. publish build writes the repository and the two inputs folders
beside it, then prints what was left out, what is missing, the notes, and the
run commands of the ops_publish check and the ops_github procedure, read from
their knowledge base entries. Neither command runs a graph, and git runs only to
ask, read only, which project files it ignores.
"""
import collections
import datetime
import glob
import json
import os
import shlex
import sys

from features.layers import LayerMissing, run_layer
from features.publish import assemble, collect, model
from features.setup.system import DEFAULT_HOME, SetupError, features_home, load_system

PUBLISH_ENTRY = "procedures-ops-publish"
GITHUB_ENTRY = "procedures-ops-github"
RUN_COMMAND = "4. Run command. "
INPUTS = "<inputs folder>"
PUBLISH_FALLBACK = ("From the `verification_procedures` folder, run `python3 vg.py run"
                    " graphs/ops_publish.yaml --run runs/<new run folder> --inputs <inputs folder>`."
                    " The inputs folder holds `publish_check.yaml` and `repo.tar`.")
GITHUB_FALLBACK = ("From the `verification_procedures` folder, run `python3 vg.py run"
                   " graphs/ops_github.yaml --run runs/<new run folder> --inputs <inputs folder>`."
                   " The inputs folder holds `github.yaml` and `project.tar`.")
PLANS_ONLY = "The procedure only plans until github.yaml sets apply: true."
NO_GITHUB = "Add a github block to the answers file to write its inputs"


def run_command(root, entry):
    """The run command in a procedure's knowledge base entry, the text after its line
    "4. Run command. ", or "" when the entry is not under <root>/audit_layer/kb/corpus."""
    pattern = os.path.join(str(root), "audit_layer", "kb", "corpus", "*", entry + ".md")
    for path in sorted(glob.glob(pattern)):
        try:
            with open(path, encoding="utf-8") as handle:
                lines = handle.read().splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for line in lines:
            if line.startswith(RUN_COMMAND):
                return line[len(RUN_COMMAND):].strip()
    return ""


def with_inputs(command, folder):
    """The run command with its inputs folder named."""
    quoted = shlex.quote(folder)
    if INPUTS in command:
        return command.replace(INPUTS, quoted, 1)
    return "%s The inputs folder is %s." % (command, quoted)


def check_command(root, folder):
    return with_inputs(run_command(root, PUBLISH_ENTRY) or PUBLISH_FALLBACK, folder)


def github_command(root, folder):
    return with_inputs(run_command(root, GITHUB_ENTRY) or GITHUB_FALLBACK, folder)


# Printing.


def _line(message):
    return message[:1].upper() + message[1:]


def _list(out, heading, items):
    out.write(heading + "\n")
    for item in items:
        out.write("  %s\n" % item)
    if not items:
        out.write("  none\n")


def _product_line(product):
    latest = product.latest
    if latest is None:
        return "%s, no numbered build yet" % product.name
    verification = latest.verification or "no verification recorded"
    return "%s, latest %s of %s, %s" % (product.name, latest.version, latest.date, verification)


def _report_where(report):
    if report.report_bytes is None and report.stream in model.STREAMS:
        return "no report whose results match the project's, so only its results file"
    if report.report_bytes is None:
        return "no report beside its results file, so only its results file"
    if report.report_from == "project":
        return "its report from the project's own report folder"
    return "its report from %s" % report.report_from


def _report_line(report):
    run = "run %s" % report.run_id if report.run_id else "no run id"
    return "%s/%s: %s, %s" % (report.group.key, report.stream, run, _report_where(report))


def _left_out_lines(left_out):
    return ["%s: %s" % (relpath, why) for relpath, _, why in left_out]


def _copied(result):
    prefix = assemble.PROJECT + "/"
    return sum(1 for relpath in result.collected.project_files
               if result.plan.get(prefix + relpath) == result.collected.project_files[relpath])


def _session_plan(result, audit_home):
    sessions = result.collected.answers.sessions
    if sessions.get("skip"):
        return "skipped, since the answers set sessions skip"
    if not audit_home:
        return ("system.yaml gives no audit_home, so publish build would stop; "
                + assemble.SKIP_HINT)
    return "will be written from the record in %s" % audit_home


def plan_record(result, audit_home):
    """publish plan's content as one record, for --json."""
    collected = result.collected
    products = []
    for product in collected.products:
        latest = product.latest
        products.append(collections.OrderedDict((
            ("name", product.name),
            ("group", [group.key for group in collected.groups
                       if product in group.products][0]),
            ("latest", latest.version if latest is not None else None),
            ("date", latest.date if latest is not None else None),
            ("verification", latest.verification if latest is not None else None),
        )))
    reports = [collections.OrderedDict((
        ("group", report.group.key),
        ("stream", report.stream),
        ("run_id", report.run_id),
        ("report_from", report.report_from),
        ("note", report.note),
    )) for report in collected.reports]
    sessions = collected.answers.sessions
    return collections.OrderedDict((
        ("project", collected.project_dir),
        ("products", products),
        ("reports", reports),
        ("missing", list(result.missing)),
        ("copied", _copied(result)),
        ("left_out", [collections.OrderedDict((("path", relpath), ("rule", rule), ("why", why)))
                      for relpath, rule, why in result.left_out_local]),
        ("session_index", collections.OrderedDict((
            ("skip", bool(sessions.get("skip"))),
            ("audit_home", audit_home),
        ))),
        ("notes", list(result.notes)),
        ("counts", collections.OrderedDict(result.counts)),
    ))


def print_plan(result, audit_home, out):
    collected = result.collected
    out.write("Project %s\n" % collected.project_dir)
    _list(out, "Products", [_product_line(product) for product in collected.products])
    _list(out, "Reports", [_report_line(report) for report in collected.reports])
    _list(out, "Missing", list(result.missing))
    copied = _copied(result)
    _list(out, "Copied", ["%d project %s" % (copied, "file" if copied == 1 else "files")])
    _list(out, "Left out", _left_out_lines(result.left_out_local))
    session = [_session_plan(result, audit_home)]
    if not collected.answers.sessions.get("skip") and audit_home and not os.path.isfile(
            os.path.join(audit_home, "audit.sqlite")):
        session.append("the audit home holds no audit.sqlite, so publish build would stop; "
                       + assemble.SKIP_HINT)
    _list(out, "Session index", session)
    _list(out, "Notes", [_line(note) for note in result.notes])


def print_build(result, outs, out):
    out_dir, check_dir, github_dir = outs
    root = result.collected.workflow_root
    out.write("Wrote %s\n" % out_dir)
    _list(out, "Left out", _left_out_lines(result.left_out_local))
    _list(out, "Missing", list(result.missing))
    _list(out, "Notes", [_line(note) for note in result.notes])
    out.write("Check it before it goes public\n")
    out.write("  %s\n" % check_command(root, check_dir))
    out.write("  The verification_procedures folder is %s.\n"
              % os.path.join(root, "verification_procedures"))
    out.write("Put it on GitHub\n")
    if result.github_plan is not None:
        out.write("  %s %s\n" % (github_command(root, github_dir), PLANS_ONLY))
    else:
        out.write("  %s\n" % NO_GITHUB)


# The commands.


def _now(now):
    return now or datetime.datetime.now(datetime.timezone.utc)


def plan(options, out=None, err=None, now=None):
    out = out or sys.stdout
    err = err or sys.stderr
    try:
        result = assemble.run_publish(options.dir, None, options.answers, options.runs,
                                      options.home, _now(now), runner=run_layer, write=False)
        audit_home = load_system(features_home(options.home)).get("audit_home")
    except (model.PublishError, SetupError, LayerMissing) as error:
        err.write("publish plan stopped, %s\n" % error)
        return 1
    audit_home = os.path.abspath(os.path.expanduser(str(audit_home))) if audit_home else None
    if options.json:
        out.write(json.dumps(plan_record(result, audit_home), indent=2, ensure_ascii=False) + "\n")
    else:
        print_plan(result, audit_home, out)
    return 0


def build(options, out=None, err=None, now=None):
    out = out or sys.stdout
    err = err or sys.stderr
    try:
        result = assemble.run_publish(options.dir, options.out, options.answers, options.runs,
                                      options.home, _now(now), runner=run_layer, write=True)
    except (model.PublishError, SetupError, LayerMissing) as error:
        err.write("publish build stopped, %s\n" % error)
        return 1
    print_build(result, assemble.output_folders(options.out), out)
    return 0


def _common(parser):
    parser.add_argument("dir", metavar="DIR", help="the project folder, laid out by the workflow")
    parser.add_argument("--answers", metavar="FILE",
                        help="a YAML file giving any of " + ", ".join(collect.ANSWER_FIELDS))
    parser.add_argument("--runs", metavar="DIR",
                        help="the folder that holds the run folders, else the answers' runs, else"
                        " verification_procedures/runs in the workflow's folder")
    parser.add_argument("--home", help="the features home, else FEATURES_HOME, else " + DEFAULT_HOME)


def add_command(commands):
    parser = commands.add_parser(
        "plan", help="show what publish build would write, writing nothing",
        description="Read a verified project and show what publish build would put in the"
                    " verification repository, what it would leave out, and why, writing"
                    " nothing.")
    _common(parser)
    parser.add_argument("--json", action="store_true",
                        help="print one JSON object, for an AI session")
    parser.set_defaults(run=plan)
    parser = commands.add_parser(
        "build", help="assemble the verification repository and the inputs of its checks",
        description="Assemble a verification repository from a verified project, with the"
                    " inputs folder of the check that runs before it goes public and, when the"
                    " answers ask, the inputs folder of the GitHub procedure.")
    _common(parser)
    parser.add_argument("--out", metavar="OUT", required=True,
                        help="the folder to write the repository in, absent, empty, or an earlier"
                        " publish build; OUT.check and OUT.github go beside it")
    parser.set_defaults(run=build)
