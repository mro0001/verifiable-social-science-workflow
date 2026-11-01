"""Recount every number the manifest records from the results files, the ledgers, the
numbers file, the references, and the session index in the repository, and block on a
count that differs, a generated page changed after it was assembled, or a file missing
from the repository or not listed in its manifest.

The counting rules are written here again on purpose and share no code with the
command that assembles the repository, so the code that writes a number does not grade
it. Products are grouped as the manifest groups them, by the folder that holds their
results, and each results file counts once per group. A count the manifest records and
this step cannot recompute is a warning, and a count this step makes that the manifest
lacks is a note. The manifest itself is the one file its own file list leaves out.
"""
import collections
import csv
import datetime
import hashlib
import io
import json
import posixpath
import re
import tarfile

import yaml

import _lib

CHECK = "publish_counts"
MANIFEST = "docs/publish_manifest.json"
SCHEMA = "publish-repo"
SCHEMA_VERSION = 1
STREAMS = ("prose", "citations", "data", "build")
PHASES = ("data_collection", "data_cleaning", "data_analysis")
SESSIONS = "project/sessions/sessions.csv"
PIPELINE = "project/pipeline.yaml"
SCRIPT_CHANGE = re.compile(r"^AI (?:edit|write) to (.+?), ")
BIB_ENTRY = re.compile(r"^@\w+\{")
LEDGER_COLUMNS = ("version", "date", "git", "sha256", "purpose", "baseline", "reviewed", "verification", "runs")
SEPARATOR = re.compile(r":?-{3,}:?$")
HARNESS_NAMES = {"claude_code": "Claude Code", "forgecode": "ForgeCode"}
ONE_SOURCE_WARNINGS = ("Competing canonical", "The ARCHIVE line")
SHOWN = 5

findings = []


def problem(severity, item, message, evidence=""):
    findings.append(_lib.finding(CHECK, severity, item, message, evidence))


def clean_name(name):
    while name.startswith("./"):
        name = name[2:]
    return name


def sha(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def project_path(rel):
    rel = posixpath.normpath(str(rel).strip("/"))
    return "project" if rel == "." else "project/" + rel


def parse_json(name):
    try:
        return json.loads(files[name].decode("utf-8"), object_pairs_hook=collections.OrderedDict)
    except (ValueError, UnicodeDecodeError):
        return None


def findings_of(item):
    return [f for f in (item.get("findings") or []) if isinstance(f, dict)]


def has(item, check, severity=None, starts=None):
    for f in findings_of(item):
        if f.get("check") != check:
            continue
        if severity is not None and f.get("severity") != severity:
            continue
        if starts is not None and not str(f.get("message", "")).startswith(starts):
            continue
        return True
    return False


def items_of(results):
    return [i for i in (results.get("items") or []) if isinstance(i, dict)]


# ---------------------------------------------------------------- the count rules

def count_prose(items):
    changes = [i for i in items if i.get("kind") == "change"]
    return collections.OrderedDict((
        ("changes", len(changes)),
        ("ai", sum(1 for i in changes if i.get("needs_decision") is True)),
        ("no_reason", sum(1 for i in changes if has(i, "rationale_coverage", "blocking"))),
        ("content", sum(1 for i in changes if has(i, "content_handoff"))),
    ))


def count_citations(items):
    rows = [i for i in items if i.get("citekey")]
    ai = [i for i in rows if i.get("origin") == "ai"]
    not_found = set(str(i["citekey"]) for i in ai if i.get("lookup") == "not_found")
    not_looked_up = set(str(i["citekey"]) for i in ai if i.get("lookup") == "not_looked_up")
    out = collections.OrderedDict((
        ("rows", len(rows)),
        ("ai", len(ai)),
        ("scholar", sum(1 for i in rows if i.get("origin") == "scholar")),
        ("unknown", sum(1 for i in rows if i.get("origin") not in ("ai", "scholar"))),
        ("not_found", len(not_found)),
        ("not_looked_up", len(not_looked_up)),
        ("no_quote", sum(1 for i in ai if i.get("quote_in_source") == "no")),
        ("record_quote_not_found", sum(1 for i in ai for q in (i.get("quotes") or [])
                                       if isinstance(q, dict) and q.get("from") == "record"
                                       and q.get("in_source") == "no")),
        ("no_reason", sum(1 for i in ai if i.get("lookup") == "found" and not i.get("reason"))),
    ))
    return out, not_found, not_looked_up


def count_data(items):
    numbers = [i for i in items if i.get("kind") == "number"]
    changes = [i for i in items if i.get("kind") == "change"]
    parameters = [i for i in items if i.get("kind") == "parameter"]
    out = collections.OrderedDict((
        ("numbers", len(numbers)),
        ("reproduce", sum(1 for i in numbers if not has(i, "check_numbers"))),
        ("changes", len(changes)),
        ("change_no_reason", sum(1 for i in changes if has(i, "attribute_ai", "blocking"))),
        ("parameters", len(parameters)),
        ("parameter_no_reason", sum(1 for i in parameters if has(i, "attribute_ai", "blocking"))),
    ))
    return out, [str(i.get("summary", "")) for i in changes]


def count_phase(items):
    descriptions = [i for i in items if i.get("kind") == "description"]
    missing = not_found = 0
    for i in descriptions:
        if has(i, "check_descriptions", "warning", "The finding step gave no place"):
            missing += 1
        elif has(i, "check_descriptions", "warning", ("The place ", "The finding step gave a place that cannot be read")):
            not_found += 1
    return collections.OrderedDict((
        ("descriptions", len(descriptions)),
        ("missing", missing),
        ("not_found", not_found),
        ("confirmed", len(descriptions) - missing - not_found),
    ))


def owns(product, item_id):
    """Whether a build item belongs to the product: its id is the product's name, or is
    its source path or builds folder, or starts with either followed by a colon or a
    slash."""
    if item_id == product.get("name"):
        return True
    for lead in (product.get("source"), product.get("builds_dir")):
        lead = str(lead or "").rstrip("/")
        if lead and (item_id == lead or item_id.startswith(lead + ":") or item_id.startswith(lead + "/")):
            return True
    return False


def norm_path(text):
    text = str(text or "").strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text


def read_ledger(path):
    """The ledger's rows, nine columns or the older seven, as the build reads them."""
    rows = []
    if path not in files:
        return rows
    for raw in files[path].decode("utf-8", "replace").splitlines():
        line = raw.strip()
        if len(line) < 2 or not (line.startswith("|") and line.endswith("|")):
            continue
        cells = [cell.strip() for cell in line[1:-1].split("|")]
        if cells[0].lower() == LEDGER_COLUMNS[0] or all(SEPARATOR.match(cell) for cell in cells):
            continue
        if len(cells) not in (len(LEDGER_COLUMNS), 7):
            continue
        rows.append(dict(zip(LEDGER_COLUMNS, cells)))
    return rows


def epoch_of(day):
    try:
        when = datetime.datetime.strptime(day, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None
    return (when - datetime.date(1970, 1, 1)).days * 86400


def latest_decision(results, item_id):
    entry = None
    for candidate in results.get("decisions") or []:
        if isinstance(candidate, dict) and candidate.get("item") == item_id:
            entry = candidate
    if entry is None or entry.get("run_id") != results.get("run_id"):
        return "undecided"
    if entry.get("decision") in ("approved", "held"):
        return entry["decision"]
    return "undecided"


def harness_name(value, names):
    if value in names:
        return names[value]
    return str(value).replace("_", " ").title()


def recount():
    """Every count, by the rules the assembling command uses, and the missing streams."""
    out = collections.OrderedDict()
    results = collections.OrderedDict()
    for group in groups:
        for stream in STREAMS:
            found = results_of(group, stream)
            if found is not None:
                results[(group["key"], stream)] = found

    def add_stream(stream, names, per_group):
        totals = collections.OrderedDict((name, 0) for name in names)
        for key, values in per_group:
            for name in names:
                totals[name] += values[name]
        for name in names:
            out["%s.%s" % (stream, name)] = totals[name]
        out["%s.reports" % stream] = len(per_group)
        for key, values in per_group:
            for name in names:
                out["%s.%s.%s" % (stream, key, name)] = values[name]

    prose = [(g["key"], count_prose(items_of(results[(g["key"], "prose")])))
             for g in groups if (g["key"], "prose") in results]
    add_stream("prose", ("changes", "ai", "no_reason", "content"), prose)

    cites, all_not_found, all_not_looked_up = [], set(), set()
    for g in groups:
        if (g["key"], "citations") in results:
            values, not_found, not_looked_up = count_citations(items_of(results[(g["key"], "citations")]))
            cites.append((g["key"], values))
            all_not_found |= not_found
            all_not_looked_up |= not_looked_up
    add_stream("citations", ("rows", "ai", "scholar", "unknown", "not_found", "not_looked_up", "no_quote",
                             "record_quote_not_found", "no_reason"), cites)
    out["citations.not_found"] = len(all_not_found)
    out["citations.not_looked_up"] = len(all_not_looked_up)

    data, summaries = [], []
    for g in groups:
        if (g["key"], "data") in results:
            values, found = count_data(items_of(results[(g["key"], "data")]))
            data.append((g["key"], values))
            summaries += found
    add_stream("data", ("numbers", "reproduce", "changes", "change_no_reason", "parameters",
                        "parameter_no_reason"), data)
    steps = []
    if PIPELINE in files:
        try:
            pipeline = yaml.safe_load(files[PIPELINE].decode("utf-8")) or {}
        except (yaml.YAMLError, UnicodeDecodeError):
            pipeline = {}
        if isinstance(pipeline, dict) and isinstance(pipeline.get("steps"), list):
            steps = [s for s in pipeline["steps"] if isinstance(s, dict)]
    touched = set()
    for summary in summaries:
        m = SCRIPT_CHANGE.match(summary)
        if m:
            touched.add(norm_path(m.group(1)))
    out["data.scripts"] = len(steps)
    out["data.scripts_ai"] = sum(1 for s in steps if norm_path(s.get("script")) in touched)

    phase_results = []
    for g in groups:
        for phase in PHASES:
            path = "%s/%s/results.json" % (project_path(g["verification_dir"]), phase)
            found = parse_json(path) if path in files else None
            if not isinstance(found, dict) or found.get("stream") != "data_phases":
                continue
            phase_results.append(found)
            for name, value in count_phase(items_of(found)).items():
                out["phases.%s.%s.%s" % (g["key"], phase, name)] = value

    build = collections.OrderedDict((name, 0) for name in ("blocking", "warnings", "hardcoding", "ai_writes"))
    one_source, seen = 1, set()

    def tally(f):
        severity, check = f.get("severity"), f.get("check")
        build["blocking"] += severity == "blocking"
        build["warnings"] += severity == "warning"
        build["hardcoding"] += severity == "blocking" and check == "check_hardcoding"
        build["ai_writes"] += severity == "blocking" and check == "check_ai_touch"

    reports = 0
    for g in groups:
        if (g["key"], "build") not in results:
            continue
        reports += 1
        items = items_of(results[(g["key"], "build")])
        for item in items:
            for f in findings_of(item):
                if f.get("check") == "read_map" and (
                        f.get("severity") == "blocking" or
                        (f.get("severity") == "warning" and str(f.get("message", "")).startswith(ONE_SOURCE_WARNINGS))):
                    one_source = 0
        for item in items:
            item_id = str(item.get("id") or "")
            owners = [name for name, p in products.items() if owns(p, item_id)]
            if owners:
                if set(owners) & set(g["products"]):
                    for f in findings_of(item):
                        tally(f)
                continue
            for f in findings_of(item):
                key = (item_id, f.get("check"), f.get("severity"), f.get("message"))
                if key not in seen:
                    seen.add(key)
                    tally(f)
    for name, value in build.items():
        out["build." + name] = int(value)
    out["build.one_source"] = one_source
    out["build.reports"] = reports

    total = 0
    for name, product in products.items():
        rows = read_ledger("%s/BUILDS.md" % project_path(product.get("builds_dir", "")))
        total += len(rows)
        ledgers[name] = rows
        if not rows:
            continue
        last = rows[-1]
        out["builds.%s.latest" % name] = last["version"]
        out["builds.%s.date" % name] = last["date"]
        out["builds.%s.sha256" % name] = last["sha256"]
        epoch = epoch_of(last["date"])
        if epoch is not None:
            out["builds.%s.epoch" % name] = epoch
        group = group_of.get(name)
        lacking = [s for s in STREAMS if group is None or (group["key"], s) not in results]
        if last.get("verification", "") == "verified":
            state = "verified"
        elif lacking:
            state = "unverified: no %s report" % lacking[0]
        elif all(latest_decision(results[(group["key"], s)], item.get("id")) == "approved"
                 for s in STREAMS for item in items_of(results[(group["key"], s)])
                 if item.get("needs_decision") is True):
            state = "unverified until it is built again"
        else:
            state = "unverified until the scholar decides"
        out["builds.%s.state" % name] = state
    out["builds.total"] = total

    decided = collections.OrderedDict((("approved", 0), ("held", 0), ("undecided", 0)))
    for (key, stream), found in results.items():
        for item in items_of(found):
            if item.get("needs_decision") is True:
                decided[latest_decision(found, item.get("id"))] += 1
    for name, value in decided.items():
        out["decisions." + name] = value
    if phase_results:
        decided = collections.OrderedDict((("approved", 0), ("held", 0), ("undecided", 0)))
        for found in phase_results:
            for item in items_of(found):
                if item.get("needs_decision") is True:
                    decided[latest_decision(found, item.get("id"))] += 1
        for name, value in decided.items():
            out["phases.decisions." + name] = value

    keys = []
    for path in named_files("numbers", "numbers.yml"):
        for key in number_keys(path):
            if key not in keys:
                keys.append(key)
    out["numbers.total"] = len(keys)
    out["refs.works"] = sum(count_works(path) for path in named_files("bib", "refs.bib"))

    rows = []
    if SESSIONS in files:
        rows = [r for r in csv.DictReader(io.StringIO(files[SESSIONS].decode("utf-8", "replace")))
                if any(str(v or "").strip() for v in r.values())]
    contributions = [whole(r.get("contributions")) for r in rows]
    out["sessions.indexed"] = len(rows)
    out["sessions.contributing"] = sum(1 for n in contributions if n > 0)
    out["sessions.contributions"] = sum(contributions)
    out["sessions.harnesses"] = "; ".join(sorted(set(harness_name(str(r.get("harness") or "").strip(), harness_names)
                                                     for r in rows if str(r.get("harness") or "").strip())))

    by_product, by_group = [], []
    for g in groups:
        lacking = [s for s in STREAMS if (g["key"], s) not in results]
        by_group += ["%s/%s" % (g["key"], s) for s in lacking]
        by_product += ["%s/%s" % (name, s) for name in g["products"] for s in lacking]
    out["missing"] = "; ".join(by_group)
    return out, results, (by_product, by_group)


def whole(value):
    text = str(value if value is not None else "").strip()
    try:
        return int(text or 0)
    except ValueError:
        try:
            return int(float(text))
        except ValueError:
            return 0


def named_files(field, default):
    """The distinct files the products name for the field, as paths in the tar, or the
    project's default file when no product names one."""
    named = []
    for product in products.values():
        value = product.get(field)
        if value and project_path(value) not in named:
            named.append(project_path(value))
    if not named and project_path(default) in files:
        named.append(project_path(default))
    return [path for path in named if path in files]


def number_keys(path):
    try:
        loaded = yaml.safe_load(files[path].decode("utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError):
        return []
    if isinstance(loaded, dict) and isinstance(loaded.get("numbers"), dict):
        return [str(key) for key in loaded["numbers"]]
    return []


def count_works(path):
    return sum(1 for line in files[path].decode("utf-8", "replace").splitlines() if BIB_ENTRY.match(line))


def results_of(group, stream):
    """The group's results file for the stream: the project's own file, or else the
    report folder's copy the manifest names."""
    path = "%s/%s.json" % (project_path(group["verification_dir"]), stream)
    candidates = [path] + [r.get("results") for r in report_list
                           if r.get("group") == group["key"] and r.get("stream") == stream]
    for candidate in candidates:
        if candidate in files:
            found = parse_json(candidate)
            if isinstance(found, dict):
                return found
            problem("blocking", candidate, "The results file could not be read as JSON.")
            return None
    return None


# ---------------------------------------------------------------- comparing

def split_list(value):
    if isinstance(value, list):
        parts = [str(v) for v in value]
    else:
        parts = re.split(r"[;,]", str(value))
    return sorted(p.strip() for p in parts if p.strip() and p.strip().lower() != "none")


def plain(value):
    return int(value) if isinstance(value, bool) else value


def same(key, given, counted, missing_forms):
    if key == "missing":
        return split_list(given) in (sorted(missing_forms[0]), sorted(missing_forms[1]))
    if key == "sessions.harnesses":
        return split_list(given) == split_list(counted)
    given, counted = plain(given), plain(counted)
    return given == counted or str(given) == str(counted)


def write(out):
    _lib.write_json("counts.json", out)
    _lib.emit_findings(CHECK, findings)


EMPTY = collections.OrderedDict((key, 0) for key in (
    "checked", "differ", "not_rechecked", "generated_changed", "files_changed", "files_unlisted",
    "reports_missing"))
EMPTY["rows"] = []

files = collections.OrderedDict()
with tarfile.open(_lib.path("repo.tar")) as tf:
    for member in tf.getmembers():
        name = clean_name(member.name)
        if member.isfile() and name:
            files[name] = tf.extractfile(member).read()

manifest = parse_json(MANIFEST) if MANIFEST in files else None
if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA or \
        manifest.get("schema_version") != SCHEMA_VERSION:
    problem("blocking", MANIFEST,
            "The repository has no manifest that publish build wrote, so its numbers cannot be rechecked."
            if manifest is None or MANIFEST not in files else
            "The manifest is not a publish-repo manifest of schema version 1, so its numbers cannot be rechecked.",
            "" if not isinstance(manifest, dict) else "%s %s" % (manifest.get("schema"), manifest.get("schema_version")))
    write(EMPTY)
    raise SystemExit(0)

products = collections.OrderedDict()
for p in manifest.get("products") or []:
    if isinstance(p, dict) and p.get("name"):
        products[str(p["name"])] = p
groups = []
for g in manifest.get("groups") or []:
    if isinstance(g, dict) and g.get("key") is not None:
        groups.append({"key": str(g["key"]), "products": [str(n) for n in (g.get("products") or [])],
                       "verification_dir": str(g.get("verification_dir") or ".")})
group_of = {}
for g in groups:
    for name in g["products"]:
        group_of.setdefault(name, g)
report_list = [r for r in (manifest.get("reports") or []) if isinstance(r, dict)]
names = dict(HARNESS_NAMES)
if isinstance(manifest.get("harness_names"), dict):
    names.update(manifest["harness_names"])
harness_names = names
ledgers = collections.OrderedDict()
given = manifest.get("counts")
if not isinstance(given, dict):
    problem("blocking", "counts", "The manifest records no counts, so no number it shows can be rechecked.")
    given = collections.OrderedDict()

counted, results, missing_forms = recount()
out = collections.OrderedDict(EMPTY)
out["rows"] = []
for key, value in given.items():
    if key not in counted:
        out["not_rechecked"] += 1
        out["rows"].append({"key": key, "manifest": value, "recount": None, "same": None})
        problem("warning", key, "The manifest records a count this check does not recompute, so it is not rechecked.",
                _lib.cell(value, limit=120))
        continue
    out["checked"] += 1
    agrees = same(key, value, counted[key], missing_forms)
    out["rows"].append({"key": key, "manifest": value, "recount": counted[key], "same": agrees})
    if not agrees:
        out["differ"] += 1
        problem("blocking", key, "The manifest's count differs from the recount of the results, so the README "
                                 "would show a number its results do not give.",
                "manifest %s, recount %s" % (json.dumps(value), json.dumps(counted[key])))
extra = [key for key in counted if key not in given]
if extra:
    problem("info", "counts", "The recount makes %d %s the manifest does not record, so nothing published shows %s."
            % (len(extra), "count" if len(extra) == 1 else "counts", "it" if len(extra) == 1 else "them"),
            ", ".join(extra[:SHOWN]) + (", and %d more" % (len(extra) - SHOWN) if len(extra) > SHOWN else ""))

for name, product in products.items():
    rows = ledgers.get(name) or []
    latest = product.get("latest")
    if not rows:
        if latest:
            problem("blocking", "products.%s.latest" % name,
                    "The manifest names a latest build, and the repository holds no ledger row for it.")
        continue
    last = rows[-1]
    want = {"version": last["version"], "date": last["date"], "sha256": last["sha256"], "epoch": epoch_of(last["date"])}
    if not isinstance(latest, dict) or any(plain(latest.get(k)) != want[k] for k in sorted(want)):
        problem("blocking", "products.%s.latest" % name,
                "The manifest's latest build differs from the last row of the product's ledger.",
                "ledger %s %s" % (last["version"], last["date"]))

generated = manifest.get("generated") if isinstance(manifest.get("generated"), dict) else {}
for path in sorted(generated):
    if path not in files:
        out["generated_changed"] += 1
        problem("blocking", path, "A generated page the manifest names is missing from the repository.")
    elif sha(files[path]) != generated[path]:
        out["generated_changed"] += 1
        problem("blocking", path, "The generated page changed after it was assembled, so a number in it may have "
                                  "been typed by hand.", sha(files[path])[:19])

for r in report_list:
    for field in ("results", "report"):
        path = r.get(field)
        if path and path not in files:
            out["reports_missing"] += 1
            problem("blocking", str(path), "The manifest names a report file the repository does not hold.")
    if r.get("stream") in STREAMS and r.get("results") in files:
        group = [g for g in groups if g["key"] == r.get("group")]
        own = "%s/%s.json" % (project_path(group[0]["verification_dir"]), r["stream"]) if group else None
        if own in files and files[own] != files[r["results"]]:
            problem("blocking", r["results"], "The published results.json differs from the project's results file "
                                              "for the stream, so the report and the README disagree.", own)

listed = manifest.get("files") if isinstance(manifest.get("files"), dict) else {}
if not isinstance(manifest.get("files"), dict):
    problem("blocking", "files", "The manifest lists no files, so the repository cannot be checked for files "
                                 "added after it was assembled.")
for path in sorted(listed):
    parts = str(path).split("/")
    if str(path).startswith("/") or ".." in parts:
        out["files_changed"] += 1
        problem("blocking", str(path), "The manifest lists a path outside the repository.")
    elif path not in files:
        out["files_changed"] += 1
        problem("blocking", path, "A file the manifest lists is missing from the repository.")
    elif sha(files[path]) != listed[path]:
        out["files_changed"] += 1
        problem("blocking", path, "The file changed after the repository was assembled.", sha(files[path])[:19])
for path in files if isinstance(manifest.get("files"), dict) else []:
    if path != MANIFEST and path not in listed:
        out["files_unlisted"] += 1
        problem("blocking", path, "The repository holds a file its manifest does not list, so it was added after "
                                  "the repository was assembled.")

write(out)
