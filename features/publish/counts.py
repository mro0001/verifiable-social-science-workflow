"""Every number the published repository shows (publish design A.3 and R11).

count_all(collected, sessions_rows) turns what collect() read into one
OrderedDict of flat keys, so the README, the docs pages, the figure, and the
manifest all take each number from the same place. The rules count the items
of the project's results files and the rows of the ledgers, and nothing else.
Per-group keys use the group's key, the product names joined with "+", and
appear only for a group that has that stream's results file.
"""
import collections
import csv
import io
import re

from features.publish import model

SCRIPT_CHANGE = re.compile(r"^AI (?:edit|write) to (.+?), ")
MISSING_PLACE = "The finding step gave no place"
PLACE_NOT_FOUND = ("The place ", "The finding step gave a place that cannot be read")
ONE_SOURCE_WARNINGS = ("Competing canonical", "The ARCHIVE line")

PROSE_NAMES = ("changes", "ai", "no_reason", "content")
CITATION_NAMES = ("rows", "ai", "scholar", "unknown", "not_found", "not_looked_up", "no_quote",
                  "record_quote_not_found", "no_reason")
DATA_NAMES = ("numbers", "reproduce", "changes", "change_no_reason", "parameters",
              "parameter_no_reason")
PHASE_NAMES = ("descriptions", "missing", "not_found", "confirmed")
BUILD_NAMES = ("blocking", "warnings", "hardcoding", "ai_writes")
SESSION_NAMES = ("indexed", "contributing", "contributions")

VERIFIED = "verified"
UNDECIDED_STATE = "unverified until the scholar decides"
REBUILD_STATE = "unverified until it is built again"
MISSING_STATE = "unverified: no %s report"
DECISION_NAMES = ("approved", "held", "undecided")


def read_sessions_csv(text):
    """The rows of the session index's sessions.csv, each an OrderedDict by column."""
    reader = csv.reader(io.StringIO(text))
    rows = []
    header = None
    for cells in reader:
        if header is None:
            header = cells
            continue
        if not any(cell.strip() for cell in cells):
            continue
        cells = cells + [""] * (len(header) - len(cells))
        rows.append(collections.OrderedDict(zip(header, cells)))
    return rows


# Reading results items.


def _items(results):
    items = results.get("items") if isinstance(results, dict) else None
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _findings(item):
    found = item.get("findings")
    if not isinstance(found, list):
        return []
    return [finding for finding in found if isinstance(finding, dict)]


def _has(item, check, severity=None, starts=None):
    for finding in _findings(item):
        if finding.get("check") != check:
            continue
        if severity is not None and finding.get("severity") != severity:
            continue
        if starts is not None and not str(finding.get("message") or "").startswith(starts):
            continue
        return True
    return False


def _kind(items, kind):
    return [item for item in items if item.get("kind") == kind]


def _whole(value):
    try:
        return int(str(value).strip() or 0)
    except ValueError:
        try:
            return int(float(str(value).strip()))
        except ValueError:
            return 0


# One stream's counts for one group.


def _prose(items):
    changes = _kind(items, "change")
    return collections.OrderedDict((
        ("changes", len(changes)),
        ("ai", sum(1 for item in changes if item.get("needs_decision") is True)),
        ("no_reason", sum(1 for item in changes
                          if _has(item, "rationale_coverage", "blocking"))),
        ("content", sum(1 for item in changes if _has(item, "content_handoff"))),
    ))


def _citations(items):
    rows = [item for item in items if item.get("citekey")]
    ai = [item for item in rows if item.get("origin") == "ai"]
    not_found = set(str(item["citekey"]) for item in ai if item.get("lookup") == "not_found")
    not_looked_up = set(str(item["citekey"]) for item in ai
                        if item.get("lookup") == "not_looked_up")
    record_quotes = 0
    for item in ai:
        quotes = item.get("quotes") if isinstance(item.get("quotes"), list) else []
        record_quotes += sum(1 for quote in quotes if isinstance(quote, dict)
                             and quote.get("from") == "record" and quote.get("in_source") == "no")
    counts = collections.OrderedDict((
        ("rows", len(rows)),
        ("ai", len(ai)),
        ("scholar", sum(1 for item in rows if item.get("origin") == "scholar")),
        ("unknown", sum(1 for item in rows if item.get("origin") not in ("ai", "scholar"))),
        ("not_found", len(not_found)),
        ("not_looked_up", len(not_looked_up)),
        ("no_quote", sum(1 for item in ai if item.get("quote_in_source") == "no")),
        ("record_quote_not_found", record_quotes),
        ("no_reason", sum(1 for item in ai
                          if item.get("lookup") == "found" and not item.get("reason"))),
    ))
    return counts, not_found, not_looked_up


def _data(items):
    numbers = _kind(items, "number")
    changes = _kind(items, "change")
    parameters = _kind(items, "parameter")
    return collections.OrderedDict((
        ("numbers", len(numbers)),
        ("reproduce", sum(1 for item in numbers if not _has(item, "check_numbers"))),
        ("changes", len(changes)),
        ("change_no_reason", sum(1 for item in changes
                                 if _has(item, "attribute_ai", "blocking"))),
        ("parameters", len(parameters)),
        ("parameter_no_reason", sum(1 for item in parameters
                                    if _has(item, "attribute_ai", "blocking"))),
    ))


def _phase(items):
    descriptions = _kind(items, "description")
    missing = 0
    not_found = 0
    for item in descriptions:
        if _has(item, "check_descriptions", "warning", MISSING_PLACE):
            missing += 1
        elif _has(item, "check_descriptions", "warning", PLACE_NOT_FOUND):
            not_found += 1
    return collections.OrderedDict((
        ("descriptions", len(descriptions)),
        ("missing", missing),
        ("not_found", not_found),
        ("confirmed", len(descriptions) - missing - not_found),
    ))


def _scripts_ai(pipeline, data_items):
    steps = pipeline.get("steps") if isinstance(pipeline, dict) else None
    steps = [step for step in steps if isinstance(step, dict)] if isinstance(steps, list) else []
    touched = set()
    for item in data_items:
        found = SCRIPT_CHANGE.match(str(item.get("summary") or ""))
        if found:
            touched.add(_path(found.group(1)))
    return len(steps), sum(1 for step in steps if _path(step.get("script") or "") in touched)


def _path(text):
    text = str(text).strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text


# The build (design R11).


def _owners(products):
    """For each product, the test that an item id belongs to it."""
    def owns(product, item_id):
        if item_id == product.name:
            return True
        for prefix in (product.source, product.builds_dir):
            if prefix and (item_id == prefix or item_id.startswith(prefix + ":")
                           or item_id.startswith(prefix + "/")):
                return True
        return False
    return lambda item_id: [product.name for product in products if owns(product, item_id)]


def _build(collected, build_reports):
    counts = collections.OrderedDict((name, 0) for name in BUILD_NAMES)
    owners_of = _owners(collected.products)
    project_level = collections.OrderedDict()
    one_source = 1

    def add(finding):
        severity = finding.get("severity")
        check = finding.get("check")
        if severity == "blocking":
            counts["blocking"] += 1
            if check == "check_hardcoding":
                counts["hardcoding"] += 1
            if check == "check_ai_touch":
                counts["ai_writes"] += 1
        elif severity == "warning":
            counts["warnings"] += 1

    for report in build_reports:
        names = set(product.name for product in report.group.products)
        for item in _items(report.results):
            item_id = str(item.get("id") or "")
            for finding in _findings(item):
                if finding.get("check") != "read_map":
                    continue
                message = str(finding.get("message") or "")
                if finding.get("severity") == "blocking" or (
                        finding.get("severity") == "warning"
                        and message.startswith(ONE_SOURCE_WARNINGS)):
                    one_source = 0
            owners = owners_of(item_id)
            if owners:
                if names.intersection(owners):
                    for finding in _findings(item):
                        add(finding)
                continue
            for finding in _findings(item):
                key = (item_id, finding.get("check"), finding.get("severity"),
                       finding.get("message"))
                if key not in project_level:
                    project_level[key] = finding
    for finding in project_level.values():
        add(finding)
    counts["one_source"] = one_source
    return counts


# Ledgers and decisions.


def _state(product, group, present):
    """The product's state, from its latest ledger row: verified when the row says so;
    else unverified with the first stream its group has no results file for; else, when
    present maps each stream to its report and every item of them that needs a decision
    is approved, unverified until it is built again, since the next build marks it; else
    unverified until the scholar decides."""
    latest = product.latest
    if latest is not None and latest.verification == VERIFIED:
        return VERIFIED
    for stream in model.STREAMS:
        if (group.key, stream) not in present:
            return MISSING_STATE % stream
    if isinstance(present, dict) and all(
            _decided_all(present[(group.key, stream)].results) for stream in model.STREAMS):
        return REBUILD_STATE
    return UNDECIDED_STATE


def _decided_all(results):
    """Whether every item of the results that needs a decision is approved."""
    return all(_decision(results, item.get("id")) == "approved" for item in _items(results)
               if item.get("needs_decision") is True)


def ledger_runs(row):
    """{stream: run id} from a ledger row's runs cell, such as
    "prose=a_prose; citations=a_citations", or {} when the cell names none."""
    found = {}
    for part in str(getattr(row, "runs", "") or "").split(";"):
        if "=" in part:
            stream, run_id = part.split("=", 1)
            if stream.strip() and run_id.strip():
                found[stream.strip()] = run_id.strip()
    return found


def marked_before(collected):
    """The built products whose latest ledger row says verified but names runs other than
    the ones whose results are published, as (product, version), since that build was
    marked before these results reached the project."""
    runs = dict(((report.group.key, report.stream), report.run_id) for report in collected.reports
                if report.stream in model.STREAMS)
    found = []
    for group in collected.groups:
        for product in group.products:
            latest = product.latest
            if latest is None or latest.verification != VERIFIED:
                continue
            named = ledger_runs(latest)
            if not named:
                continue
            if any(named.get(stream) != runs.get((group.key, stream)) for stream in model.STREAMS
                   if (group.key, stream) in runs):
                found.append((product, latest.version))
    return found


def _decision(results, item_id):
    """approved, held, or undecided, by ospipe's latest_decision rule."""
    entry = None
    decisions = results.get("decisions") if isinstance(results.get("decisions"), list) else []
    for candidate in decisions:
        if isinstance(candidate, dict) and candidate.get("item") == item_id:
            entry = candidate
    if entry is None or entry.get("run_id") != results.get("run_id"):
        return "undecided"
    if entry.get("decision") in ("approved", "held"):
        return entry.get("decision")
    return "undecided"


def _harness(name, names):
    if name in names:
        return names[name]
    return name.replace("_", " ").title()


def count_all(collected, sessions_rows):
    """The OrderedDict of every published number (design A.3 and R11).

    collected is collect()'s Collected; sessions_rows are read_sessions_csv's
    rows, or None when no index is published, which leaves out sessions.*.
    """
    counts = collections.OrderedDict()
    groups = collected.groups
    by_stream = collections.OrderedDict()
    for report in collected.reports:
        if report.stream in model.STREAMS:
            by_stream[(report.group.key, report.stream)] = report

    def reports_of(stream):
        return [by_stream[(group.key, stream)] for group in groups
                if (group.key, stream) in by_stream]

    # Prose.
    per_group = [(report.group.key, _prose(_items(report.results)))
                 for report in reports_of("prose")]
    for name in PROSE_NAMES:
        counts["prose.%s" % name] = sum(found[name] for _, found in per_group)
    counts["prose.reports"] = len(per_group)
    for key, found in per_group:
        for name in PROSE_NAMES:
            counts["prose.%s.%s" % (key, name)] = found[name]

    # Citations.
    per_group = []
    not_found = set()
    not_looked_up = set()
    for report in reports_of("citations"):
        found, missing_works, unlooked = _citations(_items(report.results))
        per_group.append((report.group.key, found))
        not_found.update(missing_works)
        not_looked_up.update(unlooked)
    for name in CITATION_NAMES:
        counts["citations.%s" % name] = sum(found[name] for _, found in per_group)
    counts["citations.not_found"] = len(not_found)
    counts["citations.not_looked_up"] = len(not_looked_up)
    counts["citations.reports"] = len(per_group)
    for key, found in per_group:
        for name in CITATION_NAMES:
            counts["citations.%s.%s" % (key, name)] = found[name]

    # Data.
    data_reports = reports_of("data")
    per_group = [(report.group.key, _data(_items(report.results))) for report in data_reports]
    changes = [item for report in data_reports for item in _kind(_items(report.results), "change")]
    scripts, scripts_ai = _scripts_ai(collected.pipeline, changes)
    for name in DATA_NAMES:
        counts["data.%s" % name] = sum(found[name] for _, found in per_group)
    counts["data.scripts"] = scripts
    counts["data.scripts_ai"] = scripts_ai
    counts["data.reports"] = len(per_group)
    for key, found in per_group:
        for name in DATA_NAMES:
            counts["data.%s.%s" % (key, name)] = found[name]

    # Data phases.
    phases = dict(((report.group.key, report.stream), report) for report in collected.reports
                  if report.stream in model.PHASES)
    for group in groups:
        for phase in model.PHASES:
            report = phases.get((group.key, phase))
            if report is None:
                continue
            found = _phase(_items(report.results))
            for name in PHASE_NAMES:
                counts["phases.%s.%s.%s" % (group.key, phase, name)] = found[name]

    # The build.
    build_reports = reports_of("build")
    for name, value in _build(collected, build_reports).items():
        counts["build.%s" % name] = value
    counts["build.reports"] = len(build_reports)

    # Ledgers.
    counts["builds.total"] = sum(len(product.ledger) for product in collected.products)
    group_of = dict((product.name, group) for group in groups for product in group.products)
    for product in collected.products:
        latest = product.latest
        if latest is None:
            continue
        counts["builds.%s.latest" % product.name] = latest.version
        counts["builds.%s.date" % product.name] = latest.date
        counts["builds.%s.sha256" % product.name] = latest.sha256
        counts["builds.%s.epoch" % product.name] = latest.epoch
        counts["builds.%s.state" % product.name] = _state(product, group_of[product.name],
                                                          by_stream)

    # Decisions over the four streams' files.
    decided = collections.OrderedDict((name, 0) for name in DECISION_NAMES)
    for report in by_stream.values():
        for item in _items(report.results):
            if item.get("needs_decision") is True:
                decided[_decision(report.results, item.get("id"))] += 1
    for name, value in decided.items():
        counts["decisions.%s" % name] = value

    # Decisions over the data phase reports, counted apart, since no build reads them.
    phase_reports = [report for report in collected.reports if report.stream in model.PHASES]
    if phase_reports:
        decided = collections.OrderedDict((name, 0) for name in DECISION_NAMES)
        for report in phase_reports:
            for item in _items(report.results):
                if item.get("needs_decision") is True:
                    decided[_decision(report.results, item.get("id"))] += 1
        for name, value in decided.items():
            counts["phases.decisions.%s" % name] = value

    counts["numbers.total"] = len(collected.numbers_keys)
    counts["refs.works"] = collected.refs_works

    # The session index.
    if sessions_rows is not None:
        contributions = [_whole(row.get("contributions")) for row in sessions_rows]
        counts["sessions.indexed"] = len(sessions_rows)
        counts["sessions.contributing"] = sum(1 for value in contributions if value > 0)
        counts["sessions.contributions"] = sum(contributions)
        names = collected.answers.harness_names
        harnesses = set(_harness(str(row.get("harness") or "").strip(), names)
                        for row in sessions_rows if str(row.get("harness") or "").strip())
        counts["sessions.harnesses"] = "; ".join(sorted(harnesses))

    missing = ["%s/%s" % (group.key, stream) for group in groups for stream in model.STREAMS
               if (group.key, stream) not in by_stream]
    counts["missing"] = "; ".join(missing)
    return counts
