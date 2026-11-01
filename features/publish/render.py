"""The text of the published repository's pages (publish design A.4).

Each function takes what collect() read and the counts counts.py made, and
gives one page as text. They are pure: they read no file and keep no state,
so the same inputs give the same bytes. Every number on a page comes from the
counts, and every page ends with one newline and has no trailing spaces.

- readme gives README.md, one screen: the summary with the decision sentence,
  the figure, a table of the four streams with links to their reports, the
  commands that rebuild each product, and links to the other pages.
- reading_reports gives docs/reading_reports.md: where each report is, one
  references entry field by field, a few terms, and what each report found.
- record gives docs/record.md: what the record of the AI sessions holds, what
  it cannot show, and how to search the session index.
- rebuild_page gives docs/rebuild.md: the build commands and how to rerun the
  reports.
- project_readme gives project/README.md, a table of the project's top-level
  files and folders.
- report_link gives the path of one report from the repository's top.

The scholar's own words (title, summary, notes, and file descriptions) are
placed as given. A product's name in a sentence is written as code, in
backticks, so a sentence that starts with one does not start with a lowercase
word; headings, table heads, and link texts give the names plain.
"""
import os
import re

from features.publish import figure
from features.publish.counts import REBUILD_STATE, VERIFIED, marked_before
from features.publish.model import PHASE_TITLES, PHASES, STREAMS, STREAM_TITLES, WORKFLOW_URL

PLACEHOLDER_URL = "URL-OF-THIS-REPOSITORY"
PLACEHOLDER_FOLDER = "THIS-REPOSITORY"
FIGURE_PATH = "docs/results.svg"
BACK = "[Back to the README](../README.md)"
CUT = 80

# The stream's name in a sentence, and the key of the scholar's notes for it.
STREAM_NOUNS = {"prose": "prose", "citations": "references", "data": "data", "build": "build"}
NOTE_KEYS = {"prose": "prose", "citations": "references", "data": "data", "build": "build"}

DATA_RULE = re.compile(r"^([^\s:#=][^:#=]*?)\s*::?(?!=)")
STATE_MISSING = re.compile(r"^unverified: no (.+) report$")


# Small helpers.

def _count(counts, key):
    value = counts.get(key, 0)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _plural(number, word, many=None):
    if number == 1:
        return "%d %s" % (number, word)
    return "%d %s" % (number, many or word + "s")


join_and = figure.join_and


def _verb(number, one, many):
    return one if number == 1 else many


def _times(number):
    """How many times, as "once" or "<n> times"."""
    return "once" if number == 1 else "%d times" % number


def code(name):
    """A product's name as it is written in a sentence, in backticks."""
    return "`%s`" % name


def _names(names):
    """Product names in a sentence, each in backticks, joined with commas and "and"."""
    return join_and([code(name) for name in names])


def _group_names(group):
    """The products of a group in a sentence, each in backticks."""
    names = [product.name for product in getattr(group, "products", None) or ()]
    return _names(names) if names else code(group.label)


def _cell(text):
    return " ".join(str(text).split()).replace("|", "\\|")


def _cut(text):
    text = " ".join(str(text or "").split())
    if len(text) > CUT:
        text = text[:CUT].rstrip() + " ..."
    return text.replace("|", "\\|")


def _rule(columns):
    """A table's rule line, for a first column and columns more."""
    return "|---|" + "---|" * columns


def _verbatim(text):
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip("\n")


def _finish(lines):
    text = "\n".join(lines).replace("\r\n", "\n")
    out = [line.rstrip() for line in text.split("\n")]
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out) + "\n"


def _key(group):
    return getattr(group, "key", group)


def _vdir(group):
    return (group.verification_dir or "").replace("\\", "/").strip("/")


def _project_path(group, *parts):
    """A path inside project/, from a group's verification folder."""
    path = [part for part in [_vdir(group)] if part and part != "."]
    path.extend(parts)
    return "/".join(path)


def _report(collected, group, stream):
    for report in collected.reports or []:
        if _key(report.group) == group.key and report.stream == stream:
            return report
    return None


def _groups_with(collected, stream):
    return [group for group in collected.groups if _report(collected, group, stream) is not None]


def _has_stream(collected, counts, stream):
    key = "%s.reports" % stream
    if key in counts:
        return _count(counts, key) > 0
    return bool(_groups_with(collected, stream))


def _has_sessions(collected, counts):
    sessions = getattr(collected.answers, "sessions", None) or {}
    return "sessions.indexed" in counts and not sessions.get("skip")


def _answer(collected, name, default=None):
    value = getattr(collected.answers, name, None)
    return default if value is None else value


def _title(collected):
    title = (_answer(collected, "title", "") or "").strip()
    if title:
        return title
    base = os.path.basename((collected.project_dir or "").rstrip("/\\")) or "the project"
    return "Verification reports for %s" % base


def _workflow_url(collected):
    return (_answer(collected, "workflow_url", "") or "").strip() or WORKFLOW_URL


def _clone_folder(url):
    """The folder git clone makes for url, or "" for an empty url."""
    url = (url or "").strip().rstrip("/")
    if not url:
        return ""
    name = re.split(r"[/:\\]", url)[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return name


def _workflow_folder(collected):
    folder = (_answer(collected, "workflow_folder", "") or "").strip()
    return folder or _clone_folder(_workflow_url(collected))


def _repo_url(collected):
    return (_answer(collected, "repo_url", "") or "").strip()


def _repo_folder(collected):
    return _clone_folder(_repo_url(collected)) or PLACEHOLDER_FOLDER


def _note(collected, key):
    notes = _answer(collected, "notes", {}) or {}
    return _verbatim(notes.get(key))


def _built(collected):
    return [product for product in collected.products if product.latest is not None]


def _unbuilt(collected):
    return [product for product in collected.products if product.latest is None]


def _epoch(product, counts):
    value = counts.get("builds.%s.epoch" % product.name)
    if value in (None, ""):
        value = product.latest.epoch
    return value


def _version(product, counts):
    return counts.get("builds.%s.latest" % product.name) or product.latest.version


def _make_lines(collected, counts):
    lines = []
    folder = _workflow_folder(collected)
    for product in _built(collected):
        if collected.makefile_style == "pythonpath_env":
            lines.append("SOURCE_DATE_EPOCH=%s PYTHONPATH=../../%s/ospipe make %s" % (
                _epoch(product, counts), folder, product.name))
        else:
            lines.append("SOURCE_DATE_EPOCH=%s make %s" % (_epoch(product, counts), product.name))
    return lines


def _make_targets(makefile):
    """The targets of the Makefile's rules."""
    if isinstance(makefile, bytes):
        makefile = makefile.decode("utf-8", "replace")
    targets = set()
    for line in (makefile or "").split("\n"):
        if line.startswith("\t"):
            continue
        match = DATA_RULE.match(line)
        if match:
            targets.update(match.group(1).split())
    return targets


def has_data_rule(collected):
    return "data" in _make_targets((collected.project_files or {}).get("Makefile"))


def _unbuilt_sentence(collected):
    names = [product.name for product in _unbuilt(collected)]
    if not names:
        return ""
    return "%s %s no numbered build yet." % (_names(names), _verb(len(names), "has", "have"))


def _versions(collected, counts):
    return join_and(["%s %s" % (code(product.name), _version(product, counts))
                     for product in _built(collected)])


def report_link(report):
    """project/<verification_dir>/<stream>/report.md, or results.json when
    the run's report was left out."""
    name = "report.md" if report.report_bytes is not None else "results.json"
    return "project/" + _project_path(report.group, report.stream, name)


def _link_text(report, label, several):
    if report.report_bytes is not None:
        return label
    return "%s results" % label if several else "results"


# README.md.

def _marked(collected, counts):
    """The clauses on how the ledger marks the built products, such as "`a` is marked
    verified", taken from each latest ledger row, never from the decisions."""
    built = _built(collected)
    verified = [product.name for product in built
                if counts.get("builds.%s.state" % product.name) == VERIFIED]
    unverified = [product.name for product in built if product.name not in verified]
    if len(built) == len(collected.products):
        documents = "the document" if len(built) == 1 else "each document"
        if not unverified:
            return ["%s is marked verified" % documents]
        if not verified:
            return ["%s is marked unverified" % documents]
    parts = []
    for names, word in ((verified, "verified"), (unverified, "unverified")):
        if names:
            parts.append("%s %s marked %s" % (_names(names), _verb(len(names), "is", "are"), word))
    return parts


def _with_marks(lead, marks):
    """lead and the clauses, as one sentence: "lead, and a." or "lead, a, and b."."""
    if not marks:
        return "%s." % lead
    if len(marks) == 1:
        return "%s, and %s." % (lead, marks[0])
    return "%s, %s, and %s." % (lead, ", ".join(marks[:-1]), marks[-1])


def _phase_items(counts):
    """(approved, held, undecided) over the data phase reports' items, or None."""
    if "phases.decisions.approved" not in counts:
        return None
    found = tuple(_count(counts, "phases.decisions.%s" % name)
                  for name in ("approved", "held", "undecided"))
    return found if sum(found) else None


def decision_sentence(collected, counts):
    approved = _count(counts, "decisions.approved")
    held = _count(counts, "decisions.held")
    undecided = _count(counts, "decisions.undecided")
    phases = _phase_items(counts)
    # The four streams' items, and the phase reports' when some of them are not approved.
    every = "Every item is approved"
    if phases is not None and phases[0] < sum(phases):
        every = "Every item of the four stream reports is approved"
    # A product with no numbered build has no ledger row to mark, so only the
    # products with one are named (design A.4, R5), and how each is marked comes
    # from its ledger.
    marks = _marked(collected, counts)
    if approved + held + undecided == 0:
        sentence = "No item waits for the scholar's decision."
    elif approved == 0 and held == 0:
        if len(marks) == 1 and marks[0].endswith(" marked unverified"):
            sentence = "None is decided yet, so %s." % marks[0]
        else:
            sentence = _with_marks("None is decided yet", marks)
    elif held == 0 and undecided == 0:
        sentence = _with_marks(every, marks)
    else:
        sentence = "%s %s approved, %d held, and %d not yet decided." % (
            _plural(approved, "item"), _verb(approved, "is", "are"), held, undecided)
    extra = []
    if phases is not None and phases[0] < sum(phases):
        extra.append("Of the %s of the data phase reports, %d %s approved, %d held, and %d not yet"
                     " decided." % (_plural(sum(phases), "item"), phases[0],
                                    _verb(phases[0], "is", "are"), phases[1], phases[2]))
    for product, version in marked_before(collected):
        extra.append("The latest build of %s, %s, was marked before these results reached the"
                     " project, so build it again to mark it." % (code(product.name), version))
    again = [product.name for product in _built(collected)
             if counts.get("builds.%s.state" % product.name) == REBUILD_STATE]
    if again:
        extra.append("%s %s marked verified when %s built again." % (
            _names(again), _verb(len(again), "is", "are"), _verb(len(again), "it is", "they are")))
    return " ".join([sentence] + extra)


def _missing_sentences(collected, counts):
    """A sentence for each stream a product's group has no report for, since
    such a product stays unverified."""
    by_stream = {}
    order = []
    for product in collected.products:
        state = counts.get("builds.%s.state" % product.name) or ""
        match = STATE_MISSING.match(state)
        if match:
            stream = match.group(1)
            if stream not in by_stream:
                by_stream[stream] = []
                order.append(stream)
            by_stream[stream].append(product.name)
    sentences = []
    for stream in order:
        names = by_stream[stream]
        sentences.append("%s %s no %s report, so %s unverified however the items are decided." % (
            _names(names), _verb(len(names), "has", "have"), STREAM_NOUNS.get(stream, stream),
            _verb(len(names), "it stays", "they stay")))
    return sentences


def summary(collected, counts):
    """The README's first paragraph."""
    given = _verbatim(_answer(collected, "summary", ""))
    if given:
        text = given
    else:
        names = [product.name for product in collected.products]
        if len(names) == 1:
            wrote = "the document in this repository, %s" % code(names[0])
        else:
            wrote = "the documents in this repository, %s" % _names(names)
        text = ("AI sessions helped write %s. The [workflow](%s) found each AI contribution, "
                "checked it, and wrote a report for the scholar. No model gives a verdict in any "
                "report. The scholar approves or holds each item." % (wrote, _workflow_url(collected)))
    parts = [text, decision_sentence(collected, counts)]
    parts.extend(_missing_sentences(collected, counts))
    return " ".join(parts)


def prose_sentence(counts):
    changes = _count(counts, "prose.changes")
    ai = _count(counts, "prose.ai")
    no_reason = _count(counts, "prose.no_reason")
    if changes == 0:
        return "The prose report finds no change to the text."
    if ai == 0 and changes == 1:
        return "The 1 change was not made by an AI."
    if ai == 0:
        return "None of the %s was made by an AI." % _plural(changes, "change")
    if changes == 1:
        first = "The 1 change was made by an AI."
    else:
        first = "%d of %s %s made by an AI." % (ai, _plural(changes, "change"),
                                                _verb(ai, "was", "were"))
    if ai == 1:
        second = "It is shown with the reason the AI gave, and it has %s on record." % (
            "none" if no_reason else "one")
    elif no_reason == 0:
        second = "Each is shown with the reason the AI gave, and each has one on record."
    else:
        second = "Each is shown with the reason the AI gave, and %d %s none on record." % (
            no_reason, _verb(no_reason, "has", "have"))
    return "%s %s" % (first, second)


def citations_sentence(counts):
    rows = _count(counts, "citations.rows")
    ai = _count(counts, "citations.ai")
    no_quote = _count(counts, "citations.no_quote")
    not_found = _count(counts, "citations.not_found")
    if rows == 0:
        return "The references report finds no citation."
    if ai == 0 and rows == 1:
        parts = ["The 1 citation was not first named by an AI."]
    elif ai == 0:
        parts = ["None of the %s was first named by an AI." % _plural(rows, "citation")]
    else:
        if rows == 1:
            parts = ["The 1 citation was first named by an AI."]
        else:
            parts = ["%d of %s %s first named by an AI." % (
                ai, _plural(rows, "citation"), _verb(ai, "was", "were"))]
        them = "it" if ai == 1 else "them"
        if no_quote == 0:
            parts.append("Every quote checked for %s was found in the source." % them)
        elif ai == 1:
            parts.append("For it, no quote was found in the source.")
        else:
            parts.append("For %d of them, no quote was found in the source." % no_quote)
    if not_found:
        parts.append("%s %s not found." % (_plural(not_found, "cited work"),
                                           _verb(not_found, "was", "were")))
    return " ".join(parts)


def data_sentence(counts):
    scripts = _count(counts, "data.scripts")
    scripts_ai = _count(counts, "data.scripts_ai")
    numbers = _count(counts, "data.numbers")
    reproduce = _count(counts, "data.reproduce")
    parts = []
    if scripts:
        if scripts_ai == 0 and scripts == 1:
            parts.append("No AI session wrote or changed the analysis script.")
        elif scripts_ai == 0:
            parts.append("No AI session wrote or changed any of the %s." % _plural(
                scripts, "analysis script"))
        elif scripts_ai == scripts == 1:
            parts.append("AI sessions wrote or changed the analysis script.")
        elif scripts_ai == scripts == 2:
            parts.append("AI sessions wrote or changed both analysis scripts.")
        elif scripts_ai == scripts:
            parts.append("AI sessions wrote or changed all %d analysis scripts." % scripts)
        else:
            parts.append("AI sessions wrote or changed %d of the %s." % (
                scripts_ai, _plural(scripts, "analysis script")))
    if numbers == 0:
        parts.append("The data report lists no number.")
    elif numbers == 1:
        parts.append("The 1 number %s from the raw data." % (
            "reproduces" if reproduce else "does not reproduce"))
    elif reproduce == numbers:
        parts.append("All %d numbers reproduce from the raw data." % numbers)
    else:
        parts.append("%d of the %d numbers %s from the raw data." % (
            reproduce, numbers, _verb(reproduce, "reproduces", "reproduce")))
    return " ".join(parts)


def build_sentence(counts):
    one_source = _count(counts, "build.one_source") if "build.one_source" in counts else 1
    ai_writes = _count(counts, "build.ai_writes")
    blocking = _count(counts, "build.blocking")
    hardcoding = _count(counts, "build.hardcoding")
    parts = []
    if one_source and ai_writes == 0:
        parts.append("Each document has one source, and no AI wrote to a build folder.")
    else:
        if one_source:
            parts.append("Each document has one source.")
        else:
            parts.append("The build report finds a document with more than one source.")
        if ai_writes == 0:
            parts.append("No AI wrote to a build folder.")
        elif ai_writes == 1:
            parts.append("An AI session wrote to a build folder once.")
        else:
            parts.append("AI sessions wrote to a build folder %s." % _times(ai_writes))
    if blocking == 0:
        parts.append("The report flags no problem for the scholar.")
    elif hardcoding == 0:
        parts.append("The report flags %s for the scholar." % _plural(blocking, "problem"))
    elif blocking == 1:
        parts.append("The report flags 1 problem for the scholar, from the check for results "
                     "typed into the text.")
    elif hardcoding == blocking:
        parts.append("The report flags %d problems for the scholar, all from the check for results "
                     "typed into the text." % blocking)
    else:
        parts.append("The report flags %d problems for the scholar, %d of them from the check for "
                     "results typed into the text." % (blocking, hardcoding))
    return " ".join(parts)


SENTENCES = {
    "prose": prose_sentence,
    "citations": citations_sentence,
    "data": data_sentence,
    "build": build_sentence,
}


def _phase_reports(collected, group):
    """The group's data phase reports, in the order of PHASES."""
    found = [_report(collected, group, phase) for phase in PHASES]
    return [report for report in found if report is not None]


def _phase_links(collected, group):
    """The links to a group's phase reports, each named by its phase, and by the
    group as well when more than one group has phase reports."""
    several = len([other for other in collected.groups if _phase_reports(collected, other)]) > 1
    links = []
    for report in _phase_reports(collected, group):
        label = PHASE_TITLES[report.stream]
        if several:
            label = "%s %s" % (group.label, label)
        if report.report_bytes is None:
            label += " results"
        links.append("[%s](%s)" % (_cell(label), report_link(report)))
    return links


def _row(title, found, links):
    if not links:
        return "| %s | %s | |" % (title, found)
    return "| %s | %s | %s |" % (title, found, " · ".join(links))


def stream_row(collected, counts, stream):
    """The README table's row for one stream: what the check found, and the
    report links, one for each group that has the stream. The data row also
    links each group's phase reports, after the group's data report."""
    having = _groups_with(collected, stream)
    phases = stream == "data"
    if not _has_stream(collected, counts, stream):
        links = []
        if phases:
            for group in collected.groups:
                links.extend(_phase_links(collected, group))
        return _row(STREAM_TITLES[stream], "No report yet.", links)
    found = SENTENCES[stream](counts)
    lacking = [group for group in collected.groups if group not in having]
    if lacking and having:
        names = [product.name for group in lacking for product in group.products]
        found = "%s %s %s no %s report yet." % (
            found, _names(names) if names else join_and([code(group.label) for group in lacking]),
            _verb(len(names) or len(lacking), "has", "have"), STREAM_NOUNS[stream])
    links = []
    several = len(having) > 1
    for group in collected.groups:
        if group in having:
            report = _report(collected, group, stream)
            links.append("[%s](%s)" % (_cell(_link_text(report, group.label, several)),
                                       report_link(report)))
        if phases:
            links.extend(_phase_links(collected, group))
    return _row(STREAM_TITLES[stream], _cell(found), links)


def _clone_lines(collected):
    workflow_url = _workflow_url(collected)
    folder = _workflow_folder(collected)
    if folder and folder != _clone_folder(workflow_url):
        first = "git clone %s %s" % (workflow_url, folder)
    else:
        first = "git clone %s" % workflow_url
    return [first, "git clone %s" % (_repo_url(collected) or PLACEHOLDER_URL),
            "cd %s/project" % _repo_folder(collected)]


def _try_it_text(collected, counts):
    built = _built(collected)
    parts = []
    if len(built) == 1:
        product = built[0]
        version = _version(product, counts)
        parts.append("This builds %s again as its next numbered build. SOURCE_DATE_EPOCH sets the "
                     "build's date to the date of %s, so with the same pandoc the new build is "
                     "byte for byte the same as %s." % (code(product.name), version, version))
    elif built:
        parts.append("Each command builds its product again as the next numbered build. "
                     "SOURCE_DATE_EPOCH sets the build's date to the date of the product's latest "
                     "build, %s, so with the same pandoc each new build is byte for byte the same "
                     "as that build." % _versions(collected, counts))
    unbuilt = _unbuilt_sentence(collected)
    if unbuilt:
        parts.append(unbuilt)
    parts.append("It needs Python 3.9 or later with PyYAML and python-docx, pandoc, make, and the "
                 "workflow cloned beside this repository.")
    if has_data_rule(collected):
        parts.append("`make data` recomputes every number from the raw data.")
    return " ".join(parts)


def readme(collected, counts, has_sessions):
    """README.md."""
    lines = ["# %s" % _title(collected), "", summary(collected, counts), ""]
    lines.append("![%s](%s)" % (figure.alt_text(collected, counts), FIGURE_PATH))
    lines.extend(["", "| Stream | What the check found | Reports |", "|---|---|---|"])
    for stream in STREAMS:
        lines.append(stream_row(collected, counts, stream))
    lines.extend(["", "## Try it", "", "```"])
    lines.extend(_clone_lines(collected))
    lines.extend(_make_lines(collected, counts))
    lines.extend(["```", "", _try_it_text(collected, counts), "", "## Read more", ""])
    lines.append("- [How to read the reports](docs/reading_reports.md): where each report is, "
                 "one entry explained field by field, and what each report found")
    if has_sessions:
        lines.append("- [The record behind the reports](docs/record.md): what the record of the AI "
                     "sessions holds, what it cannot show, and how to search the session index")
    else:
        lines.append("- [The record behind the reports](docs/record.md): what the record of the AI "
                     "sessions holds, and what it cannot show")
    lines.append("- [Rebuild and rerun](docs/rebuild.md): the build commands, and how the reports "
                 "are rerun with the record")
    lines.append("- [The project folder](project/README.md): what each file is")
    if has_sessions:
        indexed = _count(counts, "sessions.indexed")
        if indexed == 1:
            rows = "one row for the 1 AI session"
        else:
            rows = "one row for each of the %d AI sessions" % indexed
        lines.append("- [The session index](project/sessions/sessions.csv): %s behind the reports, "
                     "which GitHub shows as a table with a search box" % rows)
    return _finish(lines)


# docs/reading_reports.md.

PROSE_ROWS = (
    ("changes", "Changes to the text"),
    ("ai", "Made by an AI"),
    ("no_reason", "AI changes with no recorded reason"),
    ("content", "Changes flagged as content changes"),
)
CITATION_ROWS = (
    ("rows", "Citations in the final build"),
    ("ai", "From an AI"),
    ("scholar", "The scholar's"),
    ("unknown", "Origin unknown"),
    ("not_found", "Works not found"),
    ("not_looked_up", "Works not looked up"),
    ("no_quote", "AI citations with no quote found in their source"),
    ("record_quote_not_found", "Quotes in the record not found in their source"),
    ("no_reason", "AI citations with no recorded reason"),
)
DATA_ROWS = (
    ("numbers", "Numbers the report lists"),
    ("reproduce", "Numbers that reproduce from the raw data"),
    ("changes", "AI changes to the scripts"),
    ("change_no_reason", "AI changes to the scripts with no recorded reason"),
    ("parameters", "Parameters the AI set"),
    ("parameter_no_reason", "Parameters set with no recorded reason"),
)
BUILD_ROWS = (
    ("blocking", "Blocking findings"),
    ("hardcoding", "Blocking findings from the check for typed results"),
    ("warnings", "Warnings"),
    ("ai_writes", "AI writes to a build folder"),
    ("one_source", "Each document has one source"),
)
PHASE_ROWS = (
    ("descriptions", "Descriptions"),
    ("confirmed", "Confirmed"),
    ("missing", "Missing"),
    ("not_found", "Place not found"),
)
ROWS = {"prose": PROSE_ROWS, "citations": CITATION_ROWS, "data": DATA_ROWS, "build": BUILD_ROWS}

ABOUT = {
    "prose": (
        "Each prose report compares the draft the scholar pinned with the current source text, "
        "and takes from the record which changes an AI made and the reason it stated. A program "
        "flags an AI change with no recorded reason as blocking, and one that alters a number, a "
        "citation, a quotation, a negation, or a claim's strength as a warning. No model judges "
        "any change."),
    "citations": (
        "For each citation in the final build, the report gives its sentence and who first named "
        "the cited work in the record, with the session's public id, the time, and the words. For "
        "each citation from an AI it then says whether the work was found, gives the AI's recorded "
        "reason, and gives a quote, taken from the record when the record quotes the source and "
        "otherwise located in the source by a model. A program checks every exact quote against "
        "the source text."),
    "data": (
        "The data report lists each number in `numbers.yml` with the output and the script that "
        "produce it, the AI's changes to the scripts, and the parameters the AI set, each for the "
        "scholar to check. A program flags an AI change or parameter with no recorded reason as "
        "blocking. Its reproducibility section reruns the pipeline from the raw data in an empty "
        "folder and compares every number with the rerun."),
    "build": (
        "The build report checks the packed project. It checks that each document has one source, "
        "that no AI session wrote to a build folder, that the ledger matches every build file, and "
        "that no number in the text equals a value in `numbers.yml`, the check for results typed "
        "into the text."),
}
PHASES_ABOUT = (
    "Each phase report gives an outline of the phase's steps, then each step's exact code with its "
    "file and lines, then the sentences of the text that a model found describing the phase, each "
    "with where the scripts carry it out or \"missing\". A program checks that each quote is in the "
    "text and that each place is lines of a script the pipeline declares. Each description is an "
    "item for the scholar, to approve as a fair account of what the scripts do or to hold.")

ENTRY_FIELDS = (
    ("Sentence", "Where the final build cites the work"),
    ("Origin", "Who first named the work in the record, and where"),
    ("Session", None),
    ("Found", "Whether the work exists, looked up by its DOI"),
    ("Reason", "Why the AI cited it, in its own recorded words"),
    ("Quote", "A passage of the source, taken from the record or, when the record has none, "
              "located by a model"),
    ("Quote check", "Whether a program found the quote word for word in the source text"),
)


def anchor(text):
    """The anchor GitHub gives a heading."""
    slug = re.sub(r"[^\w\- ]", "", text.strip().lower(), flags=re.UNICODE)
    return slug.replace(" ", "-")


def example_entry(collected):
    """The first citation from an AI that was found, has its quote in the
    source, a reason, and a sentence, as (group, report, item), or None."""
    for group in collected.groups:
        report = _report(collected, group, "citations")
        if report is None or not isinstance(report.results, dict):
            continue
        for item in report.results.get("items") or []:
            if not isinstance(item, dict):
                continue
            if (item.get("origin") == "ai" and item.get("lookup") == "found"
                    and item.get("quote_in_source") == "yes"
                    and str(item.get("reason") or "").strip()
                    and str(item.get("sentence") or "").strip()):
                return group, report, item
    return None


def _entry_values(item, has_sessions):
    sessions = item.get("sessions") or []
    quotes = item.get("quotes") or []
    quote = quotes[0].get("text") if quotes and isinstance(quotes[0], dict) else ""
    source = str(item.get("source_file") or "").strip()
    values = {
        "Sentence": '"%s"' % _cut(item.get("sentence")),
        "Origin": _cut(item.get("origin_evidence")) or "not given",
        "Session": "`%s`" % _cut(sessions[0]) if sessions else "none recorded",
        "Found": _cut(item.get("existence")) or "found",
        "Reason": '"%s"' % _cut(item.get("reason")),
        "Quote": '"%s"' % _cut(quote) if quote else "none",
        "Quote check": "yes, found in `%s`" % _cut(source) if source else "yes",
    }
    return values


def _session_meaning(has_sessions):
    if has_sessions:
        return ("The session's public id, a row in "
                "[`sessions/sessions.csv`](../project/sessions/sessions.csv)")
    return "The session's public id"


def _entry_section(collected, has_sessions):
    lines = ["## One entry, field by field", ""]
    found = example_entry(collected)
    if found is None:
        lines.append("No references report holds an entry from an AI with its quote found in the "
                     "source, so the fields are listed without an example.")
        lines.extend(["", "| Field | What it tells you |", "|---|---|"])
        for field, meaning in ENTRY_FIELDS:
            lines.append("| %s | %s |" % (field, meaning or _session_meaning(has_sessions)))
    else:
        group, report, item = found
        entry_id = str(item.get("id") or "")
        link = "../" + report_link(report)
        if report.report_bytes is not None:
            link += "#" + anchor("%s: @%s" % (entry_id, item.get("citekey") or ""))
            what = "references report of %s" % _group_names(group)
        else:
            what = "references results of %s" % _group_names(group)
        lines.append("Entry %s of the [%s](%s), shortened:" % (entry_id, what, link))
        lines.extend(["", "| Field | In %s | What it tells you |" % _cell(entry_id), "|---|---|---|"])
        values = _entry_values(item, has_sessions)
        for field, meaning in ENTRY_FIELDS:
            lines.append("| %s | %s | %s |" % (field, values[field],
                                                meaning or _session_meaning(has_sessions)))
    lines.extend(["", "The scholar reads the entry and approves or holds it. The other reports "
                  "follow the same pattern: each item, the evidence from the record, what a "
                  "program checked, and a decision left to the scholar."])
    return lines


def _where_section(collected):
    lines = ["## Where they are", ""]
    groups = collected.groups
    lines.append("| Stream | %s |" % " | ".join(_cell(group.label) for group in groups))
    lines.append(_rule(len(groups)))
    any_results = False
    for stream in STREAMS:
        cells = []
        for group in groups:
            links = []
            report = _report(collected, group, stream)
            if report is not None:
                text = "report" if report.report_bytes is not None else "results"
                any_results = any_results or report.report_bytes is None
                links.append("[%s](../%s)" % (text, report_link(report)))
            if stream == "data":
                for phase in PHASES:
                    found = _report(collected, group, phase)
                    if found is not None:
                        any_results = any_results or found.report_bytes is None
                        links.append("[%s](../%s)" % (PHASE_TITLES[phase], report_link(found)))
            cells.append(", ".join(links))
        lines.append("| %s | %s |" % (STREAM_TITLES[stream], " | ".join(cells)))
    lines.extend(["", "Each report folder also holds `results.json`, the items with their "
                  "decisions. For the four streams it is the same file as `<stream>.json` beside "
                  "the folder, which the build reads."])
    if any_results:
        lines.extend(["", "Where no report whose results match the project's was found, the table "
                      "links the results file instead."])
    return lines


def _terms_section(counts):
    lines = ["## Terms", "", "A few words recur in what follows.", ""]
    lines.append("- **The workflow** is the system that builds the documents and runs the reports. "
                 "**The pipeline** is its build part.")
    lines.append("- **A stream** is one kind of verification, prose, citations (shown as the "
                 "references report), data, or build. The build marks each document verified or "
                 "not for each stream.")
    lines.append("- **The record** is the audit layer's store of the AI sessions, their transcripts "
                 "and tool calls. **The audit home** is the folder that holds it.")
    lines.append("- **A handoff** is a script that copies a report's inputs from the project into a "
                 "new folder. **`vg.py`** is the program that runs a report's procedure, step by "
                 "step, and writes the report.")
    lines.append("- **A phase** is collection, cleaning, or analysis, as each step of "
                 "`pipeline.yaml` declares.")
    harness = figure.harness_text(counts)
    if harness:
        names = [name.strip() for name in str(counts.get("sessions.harnesses")).split(";")]
        names = [name for name in names if name]
        lines.append("- %s %s the AI coding %s whose sessions the record holds." % (
            join_and(["**%s**" % name for name in names]), _verb(len(names), "is", "are"),
            _verb(len(names), "program", "programs")))
    return lines


def _value(counts, key, name):
    if key not in counts:
        return ""
    if name == "one_source":
        return "yes" if _count(counts, key) else "no"
    return str(counts.get(key))


def _count_table(collected, counts, stream, rows):
    having = _groups_with(collected, stream)
    per_group = any("%s.%s.%s" % (stream, group.key, name) in counts
                    for group in having for name, _ in rows)
    if len(having) == 1:
        heads = [having[0].label]
    elif per_group:
        heads = [group.label for group in having] + ["All"]
    else:
        heads = ["All"]
    lines = ["| Count | %s |" % " | ".join(_cell(head) for head in heads),
             _rule(len(heads))]
    for name, label in rows:
        total = "%s.%s" % (stream, name)
        if len(having) == 1:
            cells = [_value(counts, total, name)]
        elif per_group:
            cells = [_value(counts, "%s.%s.%s" % (stream, group.key, name), name)
                     for group in having]
            cells.append(_value(counts, total, name))
        else:
            cells = [_value(counts, total, name)]
        if not any(cells):
            continue
        lines.append("| %s | %s |" % (label, " | ".join(cells)))
    return lines


def _scripts_sentence(counts):
    scripts = _count(counts, "data.scripts")
    scripts_ai = _count(counts, "data.scripts_ai")
    declared = "The project's `pipeline.yaml` declares %s" % _plural(scripts, "analysis script")
    if scripts == 1:
        return "%s, and %s wrote or changed it." % (
            declared, "an AI session" if scripts_ai else "no AI session")
    if scripts_ai == 0:
        return "%s, and no AI session wrote or changed any of them." % declared
    return "%s, and AI sessions wrote or changed %d of them." % (declared, scripts_ai)


def _report_folders(collected, stream):
    paths = ["`%s/`" % _project_path(group, stream) for group in _groups_with(collected, stream)]
    if not paths:
        return ""
    return "%s in %s." % (_verb(len(paths), "Report", "Reports"), join_and(paths))


def _phase_rows(collected, counts):
    rows = []
    several = len(collected.groups) > 1
    for group in collected.groups:
        for phase in PHASES:
            prefix = "phases.%s.%s." % (group.key, phase)
            if not any(key.startswith(prefix) for key in counts) and \
                    _report(collected, group, phase) is None:
                continue
            label = PHASE_TITLES[phase]
            label = label[:1].upper() + label[1:]
            if several:
                label = "%s, %s" % (label, group.label)
            cells = [str(_count(counts, prefix + name)) for name, _ in PHASE_ROWS]
            rows.append("| %s | %s |" % (_cell(label), " | ".join(cells)))
    return rows


def _found_section(collected, counts):
    lines = ["## What each report found"]
    for stream in STREAMS:
        lines.extend(["", "### %s" % STREAM_TITLES[stream], ""])
        if not _has_stream(collected, counts, stream):
            lines.append("No report yet.")
        else:
            lines.append(ABOUT[stream])
            lines.append("")
            lines.extend(_count_table(collected, counts, stream, ROWS[stream]))
            if stream == "citations" and len(_groups_with(collected, stream)) > 1:
                lines.extend(["", "In the All column, a work cited in more than one document "
                              "counts once among the works not found and not looked up."])
            if stream == "data" and _count(counts, "data.scripts"):
                lines.extend(["", _scripts_sentence(counts)])
            folders = _report_folders(collected, stream)
            if folders:
                lines.extend(["", folders])
        note = _note(collected, NOTE_KEYS[stream])
        if note:
            lines.extend(["", note])
        if stream == "data":
            phase_rows = _phase_rows(collected, counts)
            if phase_rows:
                lines.extend(["", "### Data collection, cleaning, and analysis", "",
                              PHASES_ABOUT, "",
                              "| Report | %s |" % " | ".join(label for _, label in PHASE_ROWS),
                              _rule(len(PHASE_ROWS))])
                lines.extend(phase_rows)
                lines.extend(["", "A confirmed description is carried out at a place a program "
                              "found in the scripts. A missing one has no place in the scripts, "
                              "and for one whose place is not found the place given cannot be "
                              "read."])
    return lines


def reading_reports(collected, counts):
    """docs/reading_reports.md."""
    has_sessions = _has_sessions(collected, counts)
    lines = ["# How to read the reports", "",
             "The paths on this page are inside `project/`.", "",
             "Each report lists items for the scholar to approve or hold. It lays out what the "
             "record of the AI sessions shows and what programs checked. No model gives a verdict "
             "in any report.", ""]
    lines.extend(_where_section(collected))
    lines.append("")
    lines.extend(_entry_section(collected, has_sessions))
    lines.append("")
    lines.extend(_terms_section(counts))
    lines.append("")
    lines.extend(_found_section(collected, counts))
    lines.extend(["", BACK])
    return _finish(lines)


# docs/record.md.

def record(collected, counts, has_sessions):
    """docs/record.md."""
    lines = ["# The record behind the reports", "",
             "The paths on this page are inside `project/`.", "",
             "The reports read the record of the AI sessions that worked on the project, kept in "
             "the scholar's audit home. The audit home stays out of this repository, since it "
             "holds whole transcripts, and no transcript is published here.", "",
             "The record has limits, which each report's evidence lets the scholar weigh.", "",
             "- It shows who first named a work within the captured sessions and files, not what "
             "the scholar knew before.",
             "- It cannot see what a shell command read, so a shell command's output counts as AI "
             "output.",
             "- A file an AI read is dated by when it was read, not when it was written.",
             "- It reads an AI's stated reason only from the words it shows, not from its "
             "thinking, so a reason the AI gave only in its thinking is not on record."]
    note = _note(collected, "record")
    if note:
        lines.extend(["", note])
    lines.extend(["", "## The session index", ""])
    if has_sessions:
        sessions = getattr(collected.answers, "sessions", None) or {}
        also = [folder for folder in (sessions.get("also_folders") or []) if folder]
        where = "those that ran in this project's folder or touched a file in it"
        if also:
            where += ", or did so in %s the scholar named as earlier folders of the project" % (
                "the 1 folder" if len(also) == 1 else "one of the %d folders" % len(also))
        lines.append("`sessions/` lists %s of the record, %s, and any session an item of the "
                     "reports names." % (_plural(_count(counts, "sessions.indexed"), "AI session"),
                                         where))
        harness = figure.harness_text(counts)
        contributing = _count(counts, "sessions.contributing")
        contributions = _count(counts, "sessions.contributions")
        if contributing:
            led = "%d of them led to an AI contribution in the reports, %s in all" % (
                contributing, _plural(contributions, "contribution"))
        else:
            led = "none of them led to an AI contribution the reports name"
        if harness:
            lines.extend(["", "They come from %s, and %s." % (harness, led)])
        else:
            lines.extend(["", "Of these, %s." % led])
        lines.extend(["", "Each session has a public id, S followed by 12 hex characters of a "
                      "sha256 hash of the harness's own id, which cannot be turned back into it, "
                      "and the reports name sessions only by it. For each session the index gives "
                      "its start and length, the harness and the models, its tool calls counted by "
                      "verb, the files it read, edited, and wrote, and the checksum and size of its "
                      "transcript. Transcripts are not included.", "",
                      "To search the index, open "
                      "[`sessions/sessions.csv`](../project/sessions/sessions.csv), which GitHub "
                      "shows as a table with a search box, or open `sessions/index.html` in a "
                      "browser, which has a search box and a box to keep only the sessions with a "
                      "contribution. Each session also has its own page, "
                      "`sessions/<public id>.md`.", "",
                      "A transcript shared later can be checked against its row's checksum and "
                      "size, as [`sessions/README.md`](../project/sessions/README.md) explains."])
    else:
        lines.append("The session index is not published in this repository. The reports name "
                     "sessions only by their public ids, S followed by 12 hex characters of a sha256 "
                     "hash of the harness's own id, which cannot be turned back into it, and no "
                     "file here lists the sessions.")
    lines.extend(["", BACK])
    return _finish(lines)


# docs/rebuild.md.

RERUN = (
    "# References (citations), for one product",
    "python3 -m audit_layer write-out citation-provenance --project PROJECT "
    "--references PROJECT/refs.bib --out PROV.yaml",
    "python3 -m connections adapt citations --out REFS --export PROJECT/refs.bib",
    "python3 handoffs/project_to_references.py --project COPY --references REFS "
    "--provenance PROV.yaml --to INPUTS --builds-dir builds/PRODUCT --source SOURCE",
    "(cd verification_procedures && python3 vg.py run graphs/citations.yaml --run RUN "
    "--inputs INPUTS --judge live)",
    "",
    "# Prose",
    "python3 -m audit_layer write-out rationales --project PROJECT --source SOURCE "
    "--out RATIONALES.yaml",
    "python3 handoffs/audit_to_project.py --record rationales --from RATIONALES.yaml "
    "--project COPY",
    "python3 handoffs/project_to_prose.py --project COPY --prose PIN --to INPUTS --source SOURCE",
    "(cd verification_procedures && VG_OFFLINE=1 python3 vg.py run graphs/prose.yaml --run RUN "
    "--inputs INPUTS)",
    "",
    "# Data, and a phase report (data_collection, data_cleaning, or data_analysis)",
    "python3 -m audit_layer write-out file-edits --project PROJECT --out EDITS.yaml",
    "python3 handoffs/project_to_data.py --project COPY --to INPUTS --file-edits EDITS.yaml",
    "(cd verification_procedures && VG_OFFLINE=1 python3 vg.py run graphs/data.yaml --run RUN "
    "--inputs INPUTS)",
    "python3 handoffs/project_to_data_phases.py --project COPY --to PHASES "
    "--builds-dir builds/PRODUCT",
    "(cd verification_procedures && python3 vg.py run graphs/data_analysis.yaml --run RUN "
    "--inputs PHASES --judge live)",
    "",
    "# Build",
    "python3 -m audit_layer write-out session-writes --project PROJECT --out WRITES.jsonl",
    "python3 handoffs/audit_to_project.py --record session_writes --from WRITES.jsonl "
    "--project COPY",
    "python3 handoffs/project_to_build.py --project COPY --to INPUTS --source SOURCE",
    "(cd verification_procedures && VG_OFFLINE=1 python3 vg.py run graphs/build.yaml --run RUN "
    "--inputs INPUTS)",
    "",
    "# The results file where the build reads it, and the scholar's decision on an item",
    "python3 handoffs/results_to_pipeline.py --run RUN --stream prose --project PROJECT "
    "--product PRODUCT",
    "(cd verification_procedures && python3 vg.py decide --run RUN --item ITEM --approve "
    "--by \"NAME\")",
)


def _commit(collected):
    commit = str(collected.workflow_commit or "").strip()
    if not commit or commit == "unknown":
        return ""
    if re.match(r"^[0-9a-f]{12,}$", commit):
        return commit[:7]
    return commit


def rebuild_page(collected, counts):
    """docs/rebuild.md."""
    folder = _workflow_folder(collected)
    url = _workflow_url(collected)
    lines = ["# Rebuild and rerun", "",
             "The paths on this page are inside `project/`, and `make` runs there.", "",
             "## What is here", "",
             "[`project/README.md`](../project/README.md) says what each file in the project "
             "folder is.", "", "## Rebuilding", ""]
    needs = ("You need Python 3.9 or later with PyYAML and python-docx, pandoc, make, and the "
             "[workflow](%s)." % url)
    commit = _commit(collected)
    if commit:
        needs += " This repository was assembled with the workflow at commit %s." % commit
    if collected.makefile_style == "pythonpath_env":
        needs += (" Each command names the workflow's build program with `PYTHONPATH`, at "
                  "`../../%s/ospipe` from `project/`, where `git clone` puts it beside this "
                  "repository." % folder)
    else:
        needs += (" The `Makefile` looks for the workflow beside this repository, at `../../%s` "
                  "from `project/`, where `git clone` puts it. To use another copy, name its "
                  "folder with `WORKFLOW=`, as in `make %s WORKFLOW=/path/to/workflow`." % (
                      folder, collected.products[0].name if collected.products else "PRODUCT"))
    lines.append(needs)
    make_lines = _make_lines(collected, counts)
    if make_lines:
        lines.extend(["", "```"] + make_lines + ["```", ""])
        lines.append("A build carries the date it was made, and `SOURCE_DATE_EPOCH` sets that date "
                     "to the date of the product's latest build, %s, so a rebuild with the same "
                     "pandoc gives the same bytes. Each build fills every placeholder from "
                     "`numbers.yml`, stops if one has no value, writes the next numbered build in "
                     "the product's builds folder, and adds a ledger row that names each stream's "
                     "current results and whether it is verified." % _versions(collected, counts))
    unbuilt = _unbuilt_sentence(collected)
    if unbuilt:
        lines.extend(["", "%s `make <product>` writes the first one." % unbuilt])
    if has_data_rule(collected):
        lines.extend(["", "To compute the numbers again from the raw data, run `make data`."])
    lines.extend(["", "## Rerunning the reports", "",
                  "The references, prose, and build reports, and the data report's account of the "
                  "AI's edits, read the record of the AI sessions, and the record is not in this "
                  "repository. Neither are the cited works' texts. These reports can be read here "
                  "but not rerun from here. A report run with an empty record says nothing about "
                  "it. The prose report then lists every change as the scholar's, and the build "
                  "report counts no AI write, so a reader who starts an empty audit home gets "
                  "clean-looking reports that are wrong. With the record in place, the commands "
                  "below rerun each report. The phase reports and the data report's rerun of the "
                  "pipeline need no record.", "",
                  "Run them from the workflow's folder. `PROJECT` is the project folder, at the "
                  "path the record was captured with, and `COPY` is a copy of it, made with "
                  "`git archive`, into which the records go. `PRODUCT` and `SOURCE` name one "
                  "product and its source text, `PIN` is the folder that holds the pin of the "
                  "scholar's draft for the prose report, and `REFS` must also hold "
                  "`metadata_cache.json` and the cited works' texts as `source_<citekey>.txt`. "
                  "Each `vg.py run` writes its report to `RUN/files/report.md` and its items to "
                  "`RUN/results.json`. Name each run as the published ones are named, since the "
                  "folder's name becomes the run's id.", "", "```"])
    lines.extend(RERUN)
    lines.extend(["```", "",
                  "Leave out `--product` when the project keeps one verification folder for all "
                  "its products. A live model, used by the references and phase reports, reads the "
                  "provider setting in `CONNECTIONS_HOME` and the key in `WORKFLOW_MODEL_KEY`. "
                  "Point every workflow home (`AUDIT_HOME`, `CONNECTIONS_HOME`, `FEATURES_HOME`, "
                  "`OBSERVABILITY_HOME`) at folders of their own.", "", BACK])
    return _finish(lines)


# project/README.md.

def _first(path):
    """The top-level entry a relative path lies under, "name/" for a folder."""
    path = (path or "").replace("\\", "/")
    parts = [part for part in path.split("/") if part and part != "."]
    if not parts:
        return ""
    return parts[0] + "/" if len(parts) > 1 or path.endswith("/") else parts[0]


def _step_scripts(collected):
    scripts = []
    pipeline = collected.pipeline if isinstance(collected.pipeline, dict) else {}
    for step in pipeline.get("steps") or []:
        if isinstance(step, dict) and step.get("script"):
            scripts.append(str(step["script"]))
    return scripts


def _role(collected, entry):
    numbers = len(collected.numbers_keys or [])
    works = collected.refs_works or 0
    fixed = {
        "Makefile": "The build file, one rule per research product",
        "README.md": "What each file in this folder is",
        ".gitignore": "The files git leaves out of the repository",
        "numbers.yml": "Every number the text cites by placeholder, %s, each tied to the output it "
                       "comes from" % _plural(numbers, "key"),
        "pipeline.yaml": "The analysis steps, each with its script and phase",
        "params.yaml": "Every analytic choice, set once",
        "acquisition.yaml": "The raw data, with where each file came from and its checksum",
        "refs.bib": "The references, %s" % _plural(works, "work"),
        "sessions/": "The public index of the AI sessions behind the reports",
    }
    if entry in fixed:
        return fixed[entry]
    if entry in set(_first(product.builds_dir + "/") for product in collected.products):
        return "Every numbered build, with its ledger `BUILDS.md`"
    if entry in set(_first(group.verification_dir + "/") for group in collected.groups):
        return "Each report, `report.md`, and its results file, `results.json`, by product"
    sources = [product.name for product in collected.products if _first(product.source) == entry]
    if sources and not entry.endswith("/"):
        return "The source text of %s" % _names(sources)
    if sources:
        return "The source text of %s, among other files" % _names(sources)
    scripts = _step_scripts(collected)
    if entry in set(_first(script) for script in scripts if "/" not in script.strip("./")):
        return "An analysis script"
    if entry in set(_first(script) for script in scripts):
        return "Analysis scripts, among other files"
    if entry.endswith(".py"):
        return "A helper script"
    if entry.endswith(".csv"):
        return "An analysis output"
    return "-"


def project_readme(collected, top_entries):
    """project/README.md, a table of the top-level entries of OUT/project."""
    given = _answer(collected, "files", {}) or {}
    names = [product.name for product in collected.products]
    lines = ["# The project folder", ""]
    if names:
        lines.append("This folder is the project behind %s, laid out by the workflow. Every path in "
                     "the reports is a path inside this folder. Run `make` here." % _names(names))
    else:
        lines.append("This folder is the project, laid out by the workflow. Every path in the "
                     "reports is a path inside this folder. Run `make` here.")
    lines.extend(["", "| Path | What it holds |", "|---|---|"])
    for entry in top_entries:
        bare = entry.rstrip("/")
        description = None
        for key in (entry, bare, bare + "/"):
            if given.get(key):
                description = _verbatim(given[key])
                break
        if description is None:
            description = _role(collected, entry)
        lines.append("| `%s` | %s |" % (entry, _cell(description)))
    lines.extend(["", "[Back to the README](../README.md)"])
    return _finish(lines)
