"""Rebuild each research product with make from a copy of the repository's project
folder, dated by its latest build, and block when make fails or the new build's text
differs from the latest one.

make is the first command whose version line names GNU Make: the one on the path, the
same one run for the machine's own architecture, or the copy in the command line tools,
since on a Mac whose Python runs translated the first one fails. Each product is built
with WORKFLOW set to the settings' workflow folder as a make variable, PYTHONPATH naming
its ospipe, and SOURCE_DATE_EPOCH at the date of the latest build the manifest names,
so the same pandoc gives the same bytes. Every file of the copy gets one modification
time, so make rebuilds nothing but the product. A product with no numbered build is
skipped with a note. The copy is made in a temporary folder that is removed afterwards,
and no temporary path reaches any output.
"""
import collections
import json
import os
import posixpath
import shutil
import subprocess
import tarfile
import tempfile

import _lib

CHECK = "publish_rebuild"
MANIFEST = "docs/publish_manifest.json"
TIMEOUT = 600
MAKES = (["make"], ["arch", "-arm64", "make"], ["/Library/Developer/CommandLineTools/usr/bin/make"])
LEDGER_COLUMNS = ("version", "date", "git", "sha256", "purpose", "baseline", "reviewed", "verification", "runs")
SEPARATOR_CHARS = set("-: ")
MTIME = 946684800  # one time for every file of the copy, so no rule's target looks older than its inputs

findings = []
products_out = []


def problem(severity, item, message, evidence=""):
    findings.append(_lib.finding(CHECK, severity, item, message, evidence))


def clean_name(name):
    while name.startswith("./"):
        name = name[2:]
    return name


def choose_make():
    for command in MAKES:
        try:
            done = subprocess.run(command + ["--version"], stdin=subprocess.DEVNULL, capture_output=True,
                                  text=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            continue
        if done.returncode == 0 and "GNU Make" in done.stdout:
            return command
    return None


def ledger_rows(text):
    rows = []
    for raw in text.splitlines():
        line = raw.strip()
        if len(line) < 2 or not (line.startswith("|") and line.endswith("|")):
            continue
        cells = [cell.strip() for cell in line[1:-1].split("|")]
        if cells[0].lower() == LEDGER_COLUMNS[0] or all(c and set(c) <= SEPARATOR_CHARS for c in cells):
            continue
        if len(cells) in (len(LEDGER_COLUMNS), 7):
            rows.append(dict(zip(LEDGER_COLUMNS, cells)))
    return rows


def read_file(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def hide(text, folders):
    """The text with each named folder replaced by its label, longest first."""
    for folder, label in sorted(folders, key=lambda pair: len(pair[0]), reverse=True):
        if folder and folder != "/":
            text = text.replace(folder, label)
    return text


def last_line(text):
    """The last line that is not blank and not make's own summary, else the last line."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    own = [ln for ln in lines if not ln.startswith(("make:", "make[", "gmake:"))]
    return (own or lines or [""])[-1][:300]


def entry(name, latest, ledger_sha, rebuilt_sha, text_matches, result):
    products_out.append(collections.OrderedDict((
        ("name", name), ("latest", latest), ("ledger_sha256", ledger_sha), ("rebuilt_sha256", rebuilt_sha),
        ("text_matches", text_matches), ("result", result))))


settings = _lib.read_json("settings.json")
workflow = settings["workflow_root"]
files = collections.OrderedDict()
with tarfile.open(_lib.path("repo.tar")) as tf:
    for member in tf.getmembers():
        name = clean_name(member.name)
        if member.isfile() and name:
            files[name] = tf.extractfile(member).read()

manifest = None
if MANIFEST in files:
    try:
        manifest = json.loads(files[MANIFEST].decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        manifest = None
products = [p for p in ((manifest or {}).get("products") or []) if isinstance(p, dict) and p.get("name")] \
    if isinstance(manifest, dict) else []

make = None
if not isinstance(manifest, dict):
    problem("blocking", MANIFEST, "The repository has no manifest that publish build wrote, so no product was rebuilt.")
elif not os.path.isdir(os.path.join(workflow, "ospipe")):
    problem("blocking", "workflow_root", "The settings' workflow folder holds no ospipe, so no product was rebuilt.")
    for p in products:
        entry(p["name"], (p.get("latest") or {}).get("version"), None, None, None, "not run")
else:
    to_build = [p for p in products if isinstance(p.get("latest"), dict)]
    for p in products:
        if not isinstance(p.get("latest"), dict):
            problem("info", p["name"], "The product has no numbered build, so it is not rebuilt.")
    make = choose_make() if to_build else None
    if to_build and make is None:
        problem("blocking", "make", "make could not run on this machine, so no product was rebuilt.")
    work = tempfile.mkdtemp() if make else None
    try:
        if work:
            project = os.path.join(work, "project")
            for name, data in files.items():
                if not name.startswith("project/"):
                    continue
                rel = name[len("project/"):]
                parts = rel.split("/")
                if not rel or rel.startswith("/") or ".." in parts or "" in parts:
                    problem("blocking", name, "The path cannot be copied out of the tar safely, so it was left out of the rebuild.")
                    continue
                target = os.path.join(project, *parts)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, "wb") as f:
                    f.write(data)
            for top, dirs, names in os.walk(project):
                for fn in names:
                    os.utime(os.path.join(top, fn), (MTIME, MTIME))
            hidden = [(work, "<copy>"), (os.path.realpath(work), "<copy>"),
                      (workflow, "<workflow>"), (os.path.realpath(workflow), "<workflow>"),
                      (os.path.expanduser("~"), "~"), (os.path.realpath(os.path.expanduser("~")), "~")]
        for p in products:
            latest = p.get("latest")
            if not isinstance(latest, dict):
                entry(p["name"], None, None, None, None, "skipped")
                continue
            ledger_sha = latest.get("sha256")
            if not work:
                entry(p["name"], latest.get("version"), ledger_sha, None, None, "not run")
                continue
            builds = str(p.get("builds_dir") or "").strip("/")
            ledger = os.path.join(project, *builds.split("/")) if builds else project
            before = ledger_rows((read_file(os.path.join(ledger, "BUILDS.md")) or b"").decode("utf-8", "replace"))
            env = dict(os.environ, PYTHONPATH=os.path.join(workflow, "ospipe"),
                       SOURCE_DATE_EPOCH=str(latest.get("epoch")), PYTHONDONTWRITEBYTECODE="1")
            try:
                done = subprocess.run(make + [p["name"], "WORKFLOW=" + workflow], cwd=project, env=env,
                                      stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=TIMEOUT)
                code, out, err = done.returncode, done.stdout, done.stderr
            except subprocess.TimeoutExpired:
                problem("blocking", p["name"], "make did not finish within %d seconds, so the product did not rebuild."
                        % TIMEOUT)
                entry(p["name"], latest.get("version"), ledger_sha, None, None, "failed")
                continue
            if code != 0:
                problem("blocking", p["name"], "make failed with exit %d, so the product did not rebuild." % code,
                        hide(last_line(err) or last_line(out), hidden))
                entry(p["name"], latest.get("version"), ledger_sha, None, None, "failed")
                continue
            after = ledger_rows((read_file(os.path.join(ledger, "BUILDS.md")) or b"").decode("utf-8", "replace"))
            if len(after) <= len(before):
                problem("blocking", p["name"], "make ran and wrote no new numbered build to the product's ledger.",
                        hide(last_line(out), hidden))
                entry(p["name"], latest.get("version"), ledger_sha, None, None, "failed")
                continue
            new = after[-1]
            rebuilt_sha = new.get("sha256")
            old_text = files.get(posixpath.join("project", builds, "%s.md" % latest.get("version")))
            new_text = read_file(os.path.join(ledger, "%s.md" % new.get("version")))
            text_matches = None if old_text is None or new_text is None else old_text == new_text
            if rebuilt_sha == ledger_sha:
                problem("info", p["name"], "The product rebuilds byte for byte as %s." % latest.get("version"))
                result = "same bytes"
            elif text_matches:
                problem("warning", p["name"], "The rebuild has the same text in different bytes, often from another "
                                              "pandoc version.", "%s %s" % (latest.get("version"), rebuilt_sha))
                result = "same text"
            else:
                problem("blocking", p["name"], "The rebuild's text differs from the latest build, or the latest "
                                               "build's text is not in the repository.",
                        "%s %s" % (latest.get("version"), rebuilt_sha))
                result = "differs"
            entry(p["name"], latest.get("version"), ledger_sha, rebuilt_sha, text_matches, result)
    finally:
        if work:
            shutil.rmtree(work, ignore_errors=True)

_lib.write_json("rebuild.json", {"products": products_out})
_lib.emit_findings(CHECK, findings)
