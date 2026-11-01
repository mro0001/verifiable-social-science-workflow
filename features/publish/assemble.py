"""Plan and write a verification repository (publish design A.2, A.4 to A.5, R4 to R7, R10, R12, R16).

python3 -m features publish plan DIR [--answers FILE] [--runs DIR] [--home DIR] [--json]
python3 -m features publish build DIR --out OUT [--answers FILE] [--runs DIR] [--home DIR]

run_publish() is the one function both commands call. It loads system.yaml,
reads the answers, reads the project with collect(), runs the audit layer's
session index through the layer runner, takes every number from count_all(),
renders the pages, and plans every file of three folders before it writes
any: OUT, the repository (.gitignore, README.md, docs/, and project/);
OUT.check, the inputs of the ops_publish check (publish_check.yaml, repo.tar,
and the full list of what was left out, left_out.json); and OUT.github, the
inputs of the ops_github procedure (github.yaml and project.tar), only when
the answers have a github block. OUT.check and OUT.github sit beside OUT.

A plan with no OUT runs no session index and writes nothing. A build writes
only when nothing stopped, and it replaces only folders it wrote before: OUT
when every file in it is one the earlier manifest lists with the same
checksum, and OUT.check and OUT.github when they hold only the files this
command writes there. No folder the scholar excluded is opened.
"""
import collections
import datetime
import hashlib
import io
import json
import os
import posixpath
import re
import shutil
import subprocess
import tarfile
import tempfile
import unicodedata

import yaml

from features.layers import LayerMissing, run_layer
from features.organizer.inventory import read_map
from features.publish import collect, figure, model, render
from features.publish import counts as counting
from features.setup.system import features_home, load_system

PROJECT = "project"
SESSIONS = "project/sessions"
GENERATED = (".gitignore", "README.md", "docs/reading_reports.md", "docs/record.md",
             "docs/rebuild.md", "docs/results.svg", "project/README.md")
# The repository's own .gitignore, so the Finder's files never reach a commit.
GITIGNORE = ".DS_Store\n"

CHECK_SUFFIX = ".check"
GITHUB_SUFFIX = ".github"
CHECK_FILE = "publish_check.yaml"
REPO_TAR = "repo.tar"
LEFT_OUT_FILE = "left_out.json"
GITHUB_FILE = "github.yaml"
PROJECT_TAR = "project.tar"
CHECK_FILES = (CHECK_FILE, REPO_TAR, LEFT_OUT_FILE)
GITHUB_FILES = (GITHUB_FILE, PROJECT_TAR)
LEFT_OUT_SCHEMA = "publish-left-out"

SESSION_FILES = ("README.md", "index.html", "sessions.csv")
SESSION_PAGE = re.compile(r"^S[0-9a-f]{12}\.md$")
SESSION_CSV = "sessions.csv"
SKIP_HINT = "set sessions: {skip: true} in the answers file to publish without the index"
SET_ASIDE = "set aside "
UNLISTED = "the results files name session "

# The left-out folders the published manifest names (design R12). Every other
# rule is given only as a count, and the homes and the excluded folders not
# at all, so the public file never names a private file.
NAMED_FOLDERS = ("audit/", "sources/", "notes/", "ship/", ".homes/", "verification/runs/",
                 "sessions/")
COUNTED_RULES = ("fixed", "exclude", "gitignore", "symlink", "history", "editor", "replaced",
                 "unreadable")
FINDER_FILE = ".DS_Store"
FINDER_PREFIX = "._"

GENERATED_WHY = "replaced by the generated file table"
SESSIONS_WHY = "replaced by the session index"
RUN_WHY = "replaced by the report of run %s"
RESULTS_WHY = "replaced by %s, the project's results file, which every count reads"
DASHES = (u"\u2014", u"\u2013")
UNBUILT_STATE = "no numbered build yet"
NAME_WORD_STOP = ("the word '%s' of the scholar's name, which the check looks for in an anonymous"
                  " build, is in %s, which publish writes, so the check would block it; when it is"
                  " an ordinary word there, give sessions scrub_terms that leave it out, since the"
                  " full name is always withheld; when the answers' own text names the scholar,"
                  " take the name out")
IGNORED_STOP = ("the line '%s' of %s would hide %s, which publish writes, from git, so a commit"
                " would leave it out and the links to it would break; take the line out of the"
                " project's .gitignore, or leave that .gitignore out with exclude")
DECIDED_STOP = ("run %s was decided after its results reached the project, so the README would"
                " count other decisions than its report shows; run handoffs/results_to_pipeline.py"
                " again to hand the decided results to the project, then build again")


# Small helpers.


def _absolute(path):
    return os.path.abspath(os.path.expanduser(str(path)))


def _real(path):
    return os.path.realpath(os.path.expanduser(str(path)))


def _sha(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _join(*parts):
    return "/".join(part for part in parts if part and part != ".")


def _dumps(record):
    return (json.dumps(record, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _plain(value):
    """value with every mapping a plain dict and every tuple a list, for yaml.safe_dump."""
    if isinstance(value, dict):
        return dict((key, _plain(item)) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _yaml(header, record):
    text = yaml.safe_dump(_plain(record), sort_keys=False, default_flow_style=False,
                          allow_unicode=True)
    return ("%s%s" % (header, text)).encode("utf-8")


def _day(now):
    if getattr(now, "tzinfo", None) is not None:
        now = now.astimezone(datetime.timezone.utc)
    return now.strftime("%Y-%m-%d")


def _last_line(text, default):
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    return lines[-1] if lines else default


def pack(files):
    """A USTAR tar of {relpath: bytes}: sorted names, regular files only, times 0,
    mode 0644, owner and group 0 with no names, so the same files give the same bytes."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for name in sorted(files):
            data = files[name]
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mtime = 0
            info.mode = 0o644
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            try:
                archive.addfile(info, io.BytesIO(data))
            except ValueError:
                raise model.PublishError("the path %s is too long for the archive, so move it to a"
                                         " shorter path in the project" % name)
    return buffer.getvalue()


def output_folders(out_dir):
    """(OUT, OUT.check, OUT.github) as absolute paths; the two others sit beside OUT."""
    out = _absolute(out_dir)
    parent, name = os.path.split(out)
    if not name:
        raise model.PublishError("the output folder %s is a top folder, so name a folder inside"
                                 " one" % out)
    return (out, os.path.join(parent, name + CHECK_SUFFIX),
            os.path.join(parent, name + GITHUB_SUFFIX))


# The product map, read once (design R16).


class _Remembered(object):
    """The layer runner, with the answer of ospipe products --json kept, so the product
    map read again here is the one collect() read, and ospipe runs once."""

    def __init__(self, runner):
        self.runner = runner
        self.kept = {}

    def __call__(self, layer, args, **options):
        if layer == "ospipe" and list(args) == ["products", "--json"]:
            key = (str(options.get("root")), str(options.get("cwd")))
            if key not in self.kept:
                self.kept[key] = self.runner(layer, args, **options)
            return self.kept[key]
        return self.runner(layer, args, **options)


def _relpath(value):
    text = str(value or "").replace("\\", "/").strip()
    if not text:
        return None
    text = posixpath.normpath(text)
    return None if text == "." else text


def _product_files(collected, runner):
    """{product name: (bib, numbers file)} from the product map, as paths inside project/."""
    found = read_map(collected.project_dir, root=collected.workflow_root, runner=runner)
    files = {}
    for item in found.products:
        files[str(item.get("name") or "")] = (_relpath(item.get("bib")),
                                              _relpath(item.get("manifest")))
    return files


# Where the three folders may be (design A.1, R7) and what they may hold (R6).


def _check_places(folder, outs, excluded):
    """Stop when an output folder lies inside an excluded folder or holds one, or the
    output folders and the project lie inside one another. Nothing is opened, and no
    path below an excluded folder is named."""
    names = ("the output folder", "the check's inputs folder", "the GitHub inputs folder")
    for name, path in zip(names, outs):
        real = _real(path)
        for ex in excluded:
            if collect.inside(real, ex):
                raise model.PublishError("%s %s lies inside a folder the scholar excluded, so"
                                         " nothing is written there" % (name, path))
            if collect.inside(ex, real):
                raise model.PublishError("%s %s holds a folder the scholar excluded, which this"
                                         " command never opens, so name another folder"
                                         % (name, path))
        if collect.inside(real, _real(folder)):
            raise model.PublishError("%s %s lies inside the project folder, so name a folder"
                                     " outside it" % (name, path))
        if collect.inside(_real(folder), real):
            raise model.PublishError("the project folder lies inside %s %s, so name a folder"
                                     " outside the project" % (name, path))


def _is_finder(name):
    return name == FINDER_FILE or name.startswith(FINDER_PREFIX)


def _found_in(out, excluded=()):
    """The files in OUT, as relpaths, leaving out a top-level .git and the Finder's own
    files. A link, to a file or a folder, counts as a file. A folder the scholar
    excluded is never entered."""
    found = []
    for root, dirs, files in os.walk(out):
        dirs.sort()
        files.sort()
        base = os.path.relpath(root, out).replace(os.sep, "/")
        base = "" if base == "." else base
        keep = []
        for name in dirs:
            relpath = _join(base, name)
            if relpath == ".git":
                continue
            if os.path.islink(os.path.join(root, name)):
                found.append(relpath)
                continue
            if any(collect.inside(_real(os.path.join(root, name)), ex) for ex in excluded):
                raise model.PublishError("the output folder %s holds a folder the scholar"
                                         " excluded, which this command never opens, so name"
                                         " another folder" % out)
            keep.append(name)
        dirs[:] = keep
        for name in files:
            if _is_finder(name) or (base == "" and name == ".git"):
                continue
            found.append(_join(base, name))
    return found


def owned_out(out, excluded=()):
    """The files to remove before OUT is written again, or PublishError (design R6).

    OUT may be absent, hold nothing but a top-level .git, or be an earlier publish
    build: one whose manifest is a publish-repo manifest of version 1 and lists every
    other file in OUT with the checksum it has now. The listed files that are there
    and the manifest are given back. Nothing is changed.
    """
    if not os.path.lexists(out):
        return []
    if os.path.islink(out) or not os.path.isdir(out):
        raise model.PublishError("the output folder %s is not a folder" % out)
    found = _found_in(out, excluded)
    if not found:
        return []
    foreign = "the output folder %s holds files this command did not write, such as %s, so it is" \
              " left as it is"
    path = os.path.join(out, *model.MANIFEST_PATH.split("/"))
    if model.MANIFEST_PATH not in found or os.path.islink(path):
        raise model.PublishError(foreign % (out, found[0]))
    try:
        with open(path, "rb") as handle:
            manifest = json.loads(handle.read().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        raise model.PublishError(foreign % (out, model.MANIFEST_PATH))
    if not isinstance(manifest, dict) or manifest.get("schema") != model.MANIFEST_SCHEMA \
            or manifest.get("schema_version") != model.SCHEMA_VERSION \
            or not isinstance(manifest.get("files"), dict):
        raise model.PublishError(foreign % (out, model.MANIFEST_PATH))
    listed = manifest["files"]
    for relpath in sorted(listed, key=str):
        parts = str(relpath).split("/")
        if str(relpath).startswith("/") or ".." in parts or "" in parts or "." in parts:
            raise model.PublishError("the manifest in the output folder %s lists %s, a path"
                                     " outside it, so the folder is left as it is"
                                     % (out, relpath))
    for relpath in found:
        if relpath == model.MANIFEST_PATH:
            continue
        if relpath not in listed:
            raise model.PublishError(foreign % (out, relpath))
        full = os.path.join(out, *relpath.split("/"))
        if os.path.islink(full) or not os.path.isfile(full):
            raise model.PublishError("the output folder %s holds a file changed since it was"
                                     " written: %s" % (out, relpath))
        try:
            with open(full, "rb") as handle:
                data = handle.read()
        except OSError as error:
            raise model.PublishError("the output folder %s holds a file that cannot be read,"
                                     " %s (%s)" % (out, relpath, error.strerror or error))
        if _sha(data) != listed[relpath]:
            raise model.PublishError("the output folder %s holds a file changed since it"
                                     " was written: %s" % (out, relpath))
    present = set(found)
    remove = [relpath for relpath in sorted(listed) if relpath in present]
    return remove + [model.MANIFEST_PATH]


def owned_inputs(folder, names):
    """The files of names to remove before folder is written again, or PublishError.

    folder may be absent or empty, or hold only regular files named in names (and the
    Finder's own files), which this command wrote. Nothing is changed.
    """
    if not os.path.lexists(folder):
        return []
    if os.path.islink(folder) or not os.path.isdir(folder):
        raise model.PublishError("%s is not a folder" % folder)
    remove = []
    for name in sorted(os.listdir(folder)):
        if _is_finder(name):
            continue
        full = os.path.join(folder, name)
        if name not in names or os.path.islink(full) or not os.path.isfile(full):
            raise model.PublishError("%s holds files this command did not write, such as %s, so it"
                                     " is left as it is" % (folder, name))
        remove.append(name)
    return remove


def _earlier_inputs(folder, names):
    """Whether folder holds files this command wrote there and nothing else."""
    try:
        return bool(owned_inputs(folder, names))
    except model.PublishError:
        return False


def _owned(outs, github, excluded=()):
    out, check, github_dir = outs
    found = [owned_out(out, excluded), owned_inputs(check, CHECK_FILES)]
    found.append(owned_inputs(github_dir, GITHUB_FILES) if github is not None else [])
    return found


# The session index (design A.2, R10).


def _results_args(collected):
    args = []
    for report in collected.reports:
        if report.stream not in model.STREAMS:
            continue
        relpath = _join(report.group.verification_dir, report.stream + ".json")
        path = os.path.join(collected.project_dir, *relpath.split("/"))
        if len(report.group.products) == 1:
            args.append("%s=%s" % (report.group.products[0].name, path))
        else:
            args.append(path)
    return args


def _without_project(text, folder):
    for prefix in sorted(set([folder, _real(folder)]), key=len, reverse=True):
        text = text.replace(prefix + os.sep, "")
    return text


def _write_list(folder, name, lines):
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("".join(line + "\n" for line in lines))
    return path


def _read_index(folder):
    found = collections.OrderedDict()
    for root, dirs, files in os.walk(folder):
        if dirs:
            raise model.PublishError("the session index wrote a folder, %s, which publish does not"
                                     " publish, so nothing was written" % sorted(dirs)[0])
        for name in sorted(files):
            if name not in SESSION_FILES and not SESSION_PAGE.match(name):
                raise model.PublishError("the session index wrote %s, a file publish does not"
                                         " publish, so nothing was written" % name)
            with open(os.path.join(root, name), "rb") as handle:
                found[name] = handle.read()
    if SESSION_CSV not in found:
        raise model.PublishError("the session index wrote no %s, so nothing was written; %s"
                                 % (SESSION_CSV, SKIP_HINT))
    return found


def session_index(collected, system, runner, notes):
    """({name: bytes} of the session index, its rows), written into a temporary folder
    by the audit layer's write-out session-index and read back, or PublishError.

    The list files for --withhold and --scrub go in a second temporary folder. Both
    folders are removed afterwards.
    """
    sessions = collected.answers.sessions
    audit_home = system.get("audit_home") if isinstance(system, dict) else None
    if not isinstance(audit_home, str) or not audit_home.strip():
        raise model.PublishError("system.yaml gives no audit_home, so the session index cannot"
                                 " be written; %s" % SKIP_HINT)
    index_base = tempfile.mkdtemp(prefix="publish_index_")
    list_base = tempfile.mkdtemp(prefix="publish_lists_")
    try:
        out = os.path.join(index_base, "index")
        args = ["write-out", "session-index", "--home", _absolute(audit_home),
                "--project", collected.project_dir, "--out", out]
        results = _results_args(collected)
        if results:
            args += ["--results"] + results
        also = [_absolute(folder) for folder in sessions.get("also_folders") or []]
        if also:
            args += ["--also-folder"] + also
        if sessions.get("no_summaries"):
            args.append("--no-summaries")
        if sessions.get("withhold"):
            args += ["--withhold", _write_list(list_base, "withhold.txt", sessions["withhold"])]
        if sessions.get("scrub_terms"):
            args += ["--scrub", _write_list(list_base, "scrub.txt", sessions["scrub_terms"])]
        try:
            done = runner("audit_layer", args, root=collected.workflow_root)
        except LayerMissing as error:
            raise model.PublishError("the session index could not be written, %s; %s"
                                     % (error, SKIP_HINT))
        except subprocess.TimeoutExpired:
            raise model.PublishError("the session index was not written in time; %s" % SKIP_HINT)
        if done.returncode != 0:
            raise model.PublishError("the session index could not be written, %s; %s" % (
                _last_line(done.stderr or done.stdout, "it exited %d" % done.returncode),
                SKIP_HINT))
        files = _read_index(out) if os.path.isdir(out) else None
        if files is None:
            raise model.PublishError("the session index wrote no folder; %s" % SKIP_HINT)
        for line in str(done.stdout or "").splitlines():
            line = line.strip()
            if line.startswith(SET_ASIDE):
                notes.append("the session index " + _without_project(line, collected.project_dir))
            elif line.startswith(UNLISTED):
                notes.append(line)
        rows = counting.read_sessions_csv(files[SESSION_CSV].decode("utf-8", "replace"))
        return files, rows
    finally:
        shutil.rmtree(index_base, ignore_errors=True)
        shutil.rmtree(list_base, ignore_errors=True)


# The plan of OUT (design R4).


def report_folder(report):
    """project/<verification_dir>/<stream>, where a report and its results go."""
    return _join(PROJECT, report.group.verification_dir, report.stream)


def _report_tier(collected):
    tier = collections.OrderedDict()
    why = {}
    for report in collected.reports:
        folder = report_folder(report)
        planned = [(folder + "/results.json", report.results_bytes)]
        if report.report_bytes is not None:
            planned.append((folder + "/report.md", report.report_bytes))
        for path, data in planned:
            if path in tier:
                raise model.PublishError("two reports would be written to %s, so nothing was"
                                         " written" % path)
            tier[path] = data
            from_run = (report.report_from or "").startswith("run ")
            if path.endswith("/results.json") and report.stream in model.STREAMS:
                why[path] = RESULTS_WHY % _join(report.group.verification_dir,
                                                report.stream + ".json")
            elif from_run:
                why[path] = RUN_WHY % report.report_from[len("run "):]
            else:
                why[path] = "replaced by the report the project's results match"
    return tier, why


def _top_entries(paths):
    entries = set(["README.md"])
    prefix = PROJECT + "/"
    for path in paths:
        if not path.startswith(prefix):
            continue
        parts = path[len(prefix):].split("/")
        entries.add(parts[0] + "/" if len(parts) > 1 else parts[0])
    return sorted(entries, key=lambda entry: (entry.rstrip("/").lower(), entry))


def _pages(collected, counts, has_sessions, top_entries):
    pages = collections.OrderedDict()
    pages[".gitignore"] = GITIGNORE
    pages["README.md"] = render.readme(collected, counts, has_sessions)
    pages["docs/reading_reports.md"] = render.reading_reports(collected, counts)
    pages["docs/record.md"] = render.record(collected, counts, has_sessions)
    pages["docs/rebuild.md"] = render.rebuild_page(collected, counts)
    pages["docs/results.svg"] = figure.results_svg(collected, counts)
    pages["project/README.md"] = render.project_readme(collected, top_entries)
    return collections.OrderedDict((path, text.encode("utf-8")) for path, text in pages.items())


def plan_repository(collected, counts, session_files, has_sessions):
    """(plan, displaced): every file of OUT but the manifest, as {relpath: bytes} in path
    order, and the walked files a higher one took the place of, as (relpath, rule, why).

    The order of precedence is the generated pages, the session index, the report
    folders, then the project's own files. A walked file whose bytes equal the file
    that takes its place is not counted as left out.
    """
    walked = collections.OrderedDict((_join(PROJECT, relpath), data)
                                     for relpath, data in collected.project_files.items())
    reports, report_why = _report_tier(collected)
    sessions = collections.OrderedDict((_join(SESSIONS, name), data)
                                       for name, data in (session_files or {}).items())
    top = _top_entries(list(walked) + list(reports) + list(sessions))
    generated = _pages(collected, counts, has_sessions, top)

    plan = collections.OrderedDict()
    why = {}
    for path in generated:
        why[path] = GENERATED_WHY
    for path in sessions:
        why[path] = SESSIONS_WHY
    why.update(report_why)
    displaced = []
    for tier in (generated, sessions, reports):
        for path, data in tier.items():
            if path in plan:
                raise model.PublishError("the report folder %s would take the place of a page"
                                         " publish writes, so nothing was written" % path)
            plan[path] = data
    for path, data in walked.items():
        if path in plan:
            if plan[path] != data:
                displaced.append((path[len(PROJECT) + 1:], "replaced", why[path]))
            continue
        plan[path] = data
    if model.MANIFEST_PATH in plan:
        raise model.PublishError("a file would take the place of the manifest, so nothing was"
                                 " written")
    ordered = collections.OrderedDict((path, plan[path]) for path in sorted(plan))
    return ordered, displaced


# The manifest (design A.4, R6, R12).


def _public_left_out(left_out):
    fixed = []
    counted = collections.OrderedDict((rule, 0) for rule in COUNTED_RULES)
    for relpath, rule, _ in left_out:
        if rule == "fixed" and relpath in NAMED_FOLDERS:
            if relpath not in fixed:
                fixed.append(relpath)
        elif rule in counted:
            counted[rule] += 1
    rules = [collections.OrderedDict((("rule", rule), ("count", count)))
             for rule, count in counted.items() if count]
    return collections.OrderedDict((("fixed", [name for name in NAMED_FOLDERS if name in fixed]),
                                    ("rules", rules)))


def _latest(row):
    if row is None:
        return None
    return collections.OrderedDict((("version", row.version), ("date", row.date),
                                    ("sha256", row.sha256), ("epoch", row.epoch)))


def _states(collected, counts):
    present = set((report.group.key, report.stream) for report in collected.reports
                  if report.stream in model.STREAMS)
    group_of = dict((product.name, group) for group in collected.groups
                    for product in group.products)
    states = {}
    for product in collected.products:
        if product.latest is None:
            # No ledger row, so nothing is marked yet (design R5).
            states[product.name] = UNBUILT_STATE
            continue
        state = counts.get("builds.%s.state" % product.name)
        states[product.name] = state or counting._state(product, group_of[product.name], present)
    return states


def manifest(collected, counts, plan, product_files, now, notes, left_out):
    """docs/publish_manifest.json as an OrderedDict: schema publish-repo, version 1."""
    states = _states(collected, counts)
    products = []
    for product in collected.products:
        bib, numbers = product_files.get(product.name, (None, None))
        latest = product.latest
        products.append(collections.OrderedDict((
            ("name", product.name),
            ("source", product.source),
            ("builds_dir", product.builds_dir),
            ("verification_dir", product.verification_dir or "."),
            ("bib", bib),
            ("numbers", numbers),
            ("latest", _latest(latest)),
            ("verification", latest.verification if latest is not None else None),
            ("state", states[product.name]),
        )))
    groups = [collections.OrderedDict((
        ("key", group.key),
        ("products", [product.name for product in group.products]),
        ("verification_dir", group.verification_dir or "."),
        ("label", group.label),
    )) for group in collected.groups]
    reports = []
    for report in collected.reports:
        folder = report_folder(report)
        reports.append(collections.OrderedDict((
            ("group", report.group.key),
            ("stream", report.stream),
            ("run_id", report.run_id),
            ("results", folder + "/results.json"),
            ("report", folder + "/report.md" if report.report_bytes is not None else None),
        )))
    answers = collected.answers
    return collections.OrderedDict((
        ("schema", model.MANIFEST_SCHEMA),
        ("schema_version", model.SCHEMA_VERSION),
        ("assembled_on", _day(now)),
        ("workflow", collections.OrderedDict((("url", answers.workflow_url),
                                              ("folder", answers.workflow_folder),
                                              ("commit", collected.workflow_commit)))),
        ("make_style", collected.makefile_style),
        ("anonymous", bool(answers.anonymous)),
        ("harness_names", collections.OrderedDict(answers.harness_names)),
        ("products", products),
        ("groups", groups),
        ("reports", reports),
        ("counts", collections.OrderedDict(counts)),
        ("generated", collections.OrderedDict((path, _sha(plan[path])) for path in GENERATED)),
        ("files", collections.OrderedDict((path, _sha(plan[path])) for path in sorted(plan))),
        ("rewritten", [collections.OrderedDict((("path", _join(PROJECT, relpath)),
                                                ("what", what)))
                       for relpath, what in collected.rewritten]),
        ("left_out", _public_left_out(left_out)),
        ("notes", list(notes)),
    ))


# OUT.check and OUT.github (design A.5, R7, R18).


def check_terms(answers):
    """The names the check looks for: the check's terms and, when the repository is
    anonymous, the scrub terms, each once, compared with case ignored."""
    given = list(answers.check.get("terms") or [])
    if answers.anonymous:
        given += list(answers.sessions.get("scrub_terms") or [])
    terms = []
    seen = set()
    for term in given:
        key = term.strip().casefold()
        if key and key not in seen:
            seen.add(key)
            terms.append(term.strip())
    return terms


def check_settings(collected):
    """publish_check.yaml's fields, exactly those publish_settings reads."""
    check = collected.answers.check
    return collections.OrderedDict((
        ("workflow_root", collected.workflow_root),
        ("terms", check_terms(collected.answers)),
        ("allow", list(check.get("allow") or [])),
        ("max_file_mb", check["max_file_mb"]),
        ("warn_file_mb", check["warn_file_mb"]),
        ("rebuild", check["rebuild"]),
        ("excluded_folders", list(collected.excluded_folders)),
        ("excluded_paths", excluded_paths(collected)),
    ))


def excluded_paths(collected):
    """Each excluded folder inside the project, as its path in the repository, such as
    project/records, so the check blocks any file below it."""
    found = []
    for ex in collected.excluded_folders:
        below = collect.relative_inside(ex, _real(collected.project_dir))
        if below is None:
            below = collect.relative_inside(ex, collected.project_dir)
        if below:
            path = _join(PROJECT, below)
            if path not in found:
                found.append(path)
    return found


def _left_out_record(left_out):
    return collections.OrderedDict((
        ("schema", LEFT_OUT_SCHEMA),
        ("schema_version", model.SCHEMA_VERSION),
        ("left_out", [collections.OrderedDict((("path", relpath), ("rule", rule), ("why", why)))
                      for relpath, rule, why in left_out]),
    ))


def check_plan(collected, repo_tar, left_out):
    header = ("# The settings of the check that runs before the repository is published,\n"
              "# python3 vg.py run graphs/ops_publish.yaml, written by python3 -m features\n"
              "# publish build. This folder stays on this machine.\n")
    return collections.OrderedDict((
        (CHECK_FILE, _yaml(header, check_settings(collected))),
        (REPO_TAR, repo_tar),
        (LEFT_OUT_FILE, _dumps(_left_out_record(left_out))),
    ))


def github_settings(out, github, check):
    """github.yaml's fields for the ops_github procedure, with apply false."""
    return collections.OrderedDict((
        ("project_dir", out),
        ("repo_name", github["repo_name"]),
        ("owner", github["owner"]),
        ("visibility", github["visibility"]),
        ("create_with", github["create_with"]),
        ("remote_url", github["remote_url"]),
        ("branch", github["branch"]),
        ("message", github["message"]),
        ("max_file_mb", check["max_file_mb"]),
        ("warn_file_mb", check["warn_file_mb"]),
        ("apply", False),
    ))


def github_plan(out, answers, repo_tar):
    header = ("# The settings of the GitHub procedure, python3 vg.py run graphs/ops_github.yaml,\n"
              "# written by python3 -m features publish build. The procedure only plans until\n"
              "# apply is true, which the scholar sets after reading its report.\n")
    return collections.OrderedDict((
        (GITHUB_FILE, _yaml(header, github_settings(out, answers.github, answers.check))),
        (PROJECT_TAR, repo_tar),
    ))


# Writing (design A.5, R6).


def _remove_files(folder, relpaths):
    parents = set()
    for relpath in relpaths:
        path = os.path.join(folder, *relpath.split("/"))
        if os.path.lexists(path):
            os.remove(path)
        parent = os.path.dirname(path)
        while parent != folder and parent.startswith(folder + os.sep):
            parents.add(parent)
            parent = os.path.dirname(parent)
    for parent in sorted(parents, key=len, reverse=True):
        try:
            os.rmdir(parent)
        except OSError:
            pass


def _write_files(folder, planned):
    """Write each planned file with mode x, the manifest first, so a write that stops
    part way leaves a folder whose manifest lists every file in it."""
    os.makedirs(folder, exist_ok=True)
    order = [relpath for relpath in planned if relpath == model.MANIFEST_PATH]
    order += [relpath for relpath in planned if relpath != model.MANIFEST_PATH]
    for relpath in order:
        data = planned[relpath]
        path = os.path.join(folder, *relpath.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "xb") as handle:
            handle.write(data)


def write_all(outs, plan, check, github, excluded=()):
    """Clear what an earlier build wrote in the three folders and write the new plan."""
    out, check_dir, github_dir = outs
    removals = _owned(outs, github, excluded)
    try:
        _remove_files(out, removals[0])
        _write_files(out, plan)
        _remove_files(check_dir, removals[1])
        _write_files(check_dir, check)
        if github is not None:
            _remove_files(github_dir, removals[2])
            _write_files(github_dir, github)
    except OSError as error:
        raise model.PublishError("writing the repository failed (%s), so the folders may hold"
                                 " part of it; fix the cause and build again"
                                 % (error.strerror or error))


# The whole run (design R16).


def _public_text(text, folder):
    """text with the project folder's path left out and the home folder written ~, for
    the notes, which the published manifest carries."""
    text = _without_project(str(text), folder)
    home = os.path.expanduser("~")
    for prefix in sorted(set([home, _real(home)]), key=len, reverse=True):
        if len(prefix) > 1:
            text = text.replace(prefix + os.sep, "~" + os.sep)
    return text


def _missing(counts):
    text = str(counts.get("missing") or "")
    return [part.strip() for part in text.split(";") if part.strip()]


def _local_notes(collected, outs):
    """Advice for the scholar's machine, printed but never written into the repository."""
    notes = []
    if not collected.answers.repo_url:
        notes.append("the answers give no repo_url, so the README's clone line says %s; set"
                     " repo_url and build again once the repository has an address"
                     % render.PLACEHOLDER_URL)
    if outs is not None and collected.answers.github is None \
            and _earlier_inputs(outs[2], GITHUB_FILES):
        notes.append("%s is from an earlier build and the answers now have no github block, so"
                     " it was left as it was, and it no longer matches the repository"
                     % os.path.basename(outs[2]))
    return notes


def _page_notes(collected, plan):
    notes = []
    for path in GENERATED:
        text = plan[path].decode("utf-8", "replace")
        if any(dash in text for dash in DASHES):
            notes.append("%s holds a long or en dash from the answers' own text, which the page"
                         " keeps as given" % path)
    return notes


def _decided_stop(collected):
    """Stop when a run was decided after its results reached the project, since the README
    counts the project's decisions and the report shows the run's."""
    for report in collected.reports:
        if report.note and report.note == collect.DECIDED_NOTE % report.run_id:
            raise model.PublishError(DECIDED_STOP % report.run_id)


def _ignored_stop(collected, plan):
    """Stop when a .gitignore of the project, copied into project/, would hide a file
    publish writes, a page, the session index, or a report, from git."""
    rules = []
    for path in sorted(plan, key=lambda name: (name.count("/"), name)):
        if posixpath.basename(path) == ".gitignore" and path.startswith(PROJECT + "/"):
            found, _ = collect.gitignore_rules_of(plan[path].decode("utf-8", "replace"),
                                                  posixpath.dirname(path), path)
            rules.extend(found)
    if not rules:
        return
    walked = set(_join(PROJECT, relpath) for relpath in collected.project_files)
    for path in plan:
        if path in walked:
            continue
        parts = path.split("/")
        for end in range(1, len(parts) + 1):
            rule = collect._ignored_by(rules, "/".join(parts[:end]), end < len(parts))
            if rule is not None:
                raise model.PublishError(IGNORED_STOP % (rule.pattern, rule.source, path))


def _name_word_stop(collected, system, plan, session_files):
    """Stop when a word of the scholar's name that an anonymous build checks for is in a
    page publish writes or in the session index, since the check would block it there and
    the scholar cannot edit those pages."""
    answers = collected.answers
    if not answers.anonymous:
        return
    terms = set(term.casefold() for term in check_terms(answers))
    words = [word for word in collect.name_terms(system.get("scholar_name"))[1:]
             if word.casefold() in terms]
    if not words:
        return
    pages = [path for path in GENERATED if path in plan]
    pages += sorted(_join(SESSIONS, name) for name in (session_files or {}))
    for word in words:
        pattern = collect.term_pattern(word)
        for page in pages:
            text = unicodedata.normalize("NFC", plan[page].decode("utf-8", "replace"))
            if pattern.search(text):
                raise model.PublishError(NAME_WORD_STOP % (word, page))


def run_publish(project_dir, out_dir, answers_path, runs_dir, home, now, runner=run_layer,
                write=True):
    """PublishResult(collected, counts, plan, check_plan, github_plan, left_out_local,
    notes, missing), or PublishError or SetupError.

    With out_dir None this is publish plan: the session index is not run, check_plan
    and github_plan are None, and nothing is written. With out_dir given, every file of
    OUT, OUT.check, and OUT.github is planned first, and the three folders are written
    only when write is true and nothing stopped. runner runs ospipe products --json and
    the audit layer's session index.
    """
    features = features_home(home)
    system = load_system(features)
    folder = _absolute(project_dir)
    answers_path = _absolute(answers_path) if answers_path else None
    answers = collect.read_answers(answers_path, folder, system)
    outs = None
    excluded = collect.excluded_folders(system, [])
    if out_dir is not None:
        outs = output_folders(out_dir)
        _check_places(folder, outs, excluded)
        _owned(outs, answers.github, excluded)

    remembered = _Remembered(runner)
    collected = collect.collect(folder, answers, system, runs_dir, features, runner=remembered)
    _decided_stop(collected)
    notes = list(collected.notes)
    product_files = _product_files(collected, remembered)

    session_files = None
    rows = None
    if outs is not None and not answers.sessions.get("skip"):
        session_files, rows = session_index(collected, system, runner, notes)
    counts = counting.count_all(collected, rows)
    for product, version in counting.marked_before(collected):
        notes.append("the latest build of %s, %s, was marked before the published results reached"
                     " the project, so build it again to mark it" % (product.name, version))
    plan, displaced = plan_repository(collected, counts, session_files, rows is not None)
    _ignored_stop(collected, plan)
    _name_word_stop(collected, system, plan, session_files)
    left_out = list(collected.left_out) + displaced
    notes.extend(_page_notes(collected, plan))
    notes = [_public_text(note, collected.project_dir) for note in notes]
    record = manifest(collected, counts, plan, product_files, now, notes, left_out)
    notes = notes + _local_notes(collected, outs)
    plan[model.MANIFEST_PATH] = _dumps(record)
    plan = collections.OrderedDict((path, plan[path]) for path in sorted(plan))

    checks = None
    github = None
    if outs is not None:
        repo_tar = pack(plan)
        checks = check_plan(collected, repo_tar, left_out)
        if answers.github is not None:
            github = github_plan(outs[0], answers, repo_tar)
        if write:
            write_all(outs, plan, checks, github, excluded)
    return model.PublishResult(collected, counts, plan, checks, github, left_out, notes,
                               _missing(counts))
