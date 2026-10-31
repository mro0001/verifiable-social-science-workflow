"""The public id of a session, and the public index of a project's AI sessions.

the authors asked on 2026-10-30 for a public, searchable index of a project's AI
sessions, with a link from each report item an AI session contributed to the
session's entry. The link is the session's public id (Track P choice 1), S
followed by the first 12 hex characters of the sha256 of the harness's id for
the session, read as UTF-8 text. It reveals nothing about the harness's id or
the machine, it stays the same as a session grows, and anyone holding the
transcript can work it out again from the id the transcript names.

The audit layer alone holds the rule. The citation log, the rationales
record, and the file-writes record carry the public id as session_ref beside
the harness's id, and the verification procedures copy it from them.

write_session_index (Track P, step P3) writes the index into a new or empty
folder as files a GitHub repository shows as they are (choice 6),
sessions.csv, README.md, one <public id>.md per session, and index.html, one
page with the rows inside it, a search box, and a checkbox that keeps only
the sessions with an AI contribution in the final reports. The pages come
from the templates in session_index_templates/.

- The sessions are those of a harness whose adapter has the AI flag that
  touched the project, which is that the session ran in the project's folder
  or a folder inside it, or one of its tool calls read, edited, or wrote a
  file inside it, compared as real paths (choice 2). They come in the order
  they started. A session that a contribution in the results files names is
  listed as well, so each reference id links to a session in the index. A
  project that moved names the folders its work was done in
  before (also), which count as the project's, and a file in one is named by
  that folder's name and its path inside it.
- No transcript text, prompt, or tool output is written. A project file is
  named relative to the project, and a file outside it is counted, never
  named (choice 3).
- The model pass's title, gist, summary, and keywords are written unless the
  scholar withholds them for every session (summaries false) or for the
  sessions whose public ids are listed (withheld). Each is labeled as written
  by a model, and as reviewed by the author only when a person's review wrote
  the session's current row (choice 4). In them the home folder's path
  becomes ~ and each scrub term, in any case, becomes [withheld].
- A contribution reached the final report when its item is in the stream's
  latest results file given, the last one given for the stream, and names
  the session's public id in its sessions list. Its reference id is
  <stream>/<item id>, written with the results file's run and the latest
  decision the file records, approved or held, else not yet decided, or
  needs no decision for an item that needs none (choice 5).
- A project with several products keeps each product's results in
  verification/<product>/<stream>.json (Track Q, steps Q1 and Q2). A results
  file that sits there, or is given as PRODUCT=FILE, belongs to that product,
  and its reference ids are <product>/<stream>/<item id>. Every product's
  files are read, and the last one given for a product's stream counts. A
  file of no product keeps the ids above.

The results files are the verification layer's, read as JSON files named on
the command line, and nothing of that layer's code is imported.
"""
import csv
import hashlib
import io
import json
import os
import re
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from audit_layer.capture import ADAPTERS
from audit_layer.queries import _session_row_ids, session_events
from audit_layer.store import current

# The number of hex characters of the sha256 the public id keeps.
PUBLIC_ID_HEX = 12

# A public id, as public_id gives it.
PUBLIC_ID = re.compile(r"S[0-9a-f]{%d}" % PUBLIC_ID_HEX)

# The index's files besides one page per session.
CSV_FILE = "sessions.csv"
README_FILE = "README.md"
HTML_FILE = "index.html"

TEMPLATES = Path(__file__).resolve().parent / "session_index_templates"

# The columns of sessions.csv, in order, and the keys of each row in index.html.
COLUMNS = (
    "public_id",
    "started_at",
    "minutes",
    "harness",
    "harness_version",
    "models",
    "parent",
    "tool_calls",
    "files_read",
    "files_edited",
    "files_written",
    "other_files",
    "title",
    "gist",
    "summary",
    "keywords",
    "model_fields",
    "transcript_sha256",
    "transcript_bytes",
    "contributions",
    "references",
)

# The model pass's fields (Table A4).
MODEL_FIELDS = ("title", "gist", "summary", "keywords")

# The labels of the model pass's fields.
UNREVIEWED = "written by a model, not reviewed by the author"
REVIEWED = "written by a model, reviewed by the author"
WITHHELD = "withheld by the author"

# What a scrubbed term becomes.
SCRUBBED = "[withheld]"

# The decision an item shows when its results file records none.
NOT_DECIDED = "not yet decided"
NO_DECISION = "needs no decision"

# The origin of the rows a person's review writes (tagging/review.py).
PERSON = "person "

# The separator of a list's values in a CSV cell.
JOIN = "; "

# A product's name, one folder name, as ospipe add-product names a product, and
# the folder whose product folders hold the products' results files.
PRODUCT_NAME = re.compile(r"[A-Za-z0-9_-]+")
VERIFICATION = "verification"

# A subagent conversation's id is its parent's followed by this and its agent id.
AGENT = "/agent-"

# The mechanical pass's verbs, in the order events.py lists them, and the
# verbs and role that name a file a tool call wrote, edited, or read.
VERBS = ("wrote", "edited", "ran", "searched", "verified", "committed")
READ_ROLE = "read"

Contribution = namedtuple("Contribution", ["reference", "run", "decision"])

# What write_session_index wrote. rows are the index's rows, set_aside the
# results files given whose stream a later file given replaced, and unlisted
# the public ids the results files name that no listed session has.
Index = namedtuple("Index", ["rows", "files", "set_aside", "unlisted"])


class SessionIndexError(ValueError):
    """A session index the audit layer refuses to write."""


def public_id(harness_session_id: str) -> str:
    """The public id of the session the harness names harness_session_id."""
    if not isinstance(harness_session_id, str) or not harness_session_id.strip():
        raise ValueError("a public id needs the harness's id for the session, as text")
    digest = hashlib.sha256(harness_session_id.encode("utf-8")).hexdigest()
    return "S" + digest[:PUBLIC_ID_HEX]


def read_list(path, what: str) -> List[str]:
    """The lines of the file at path, each stripped, blank ones left out."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise SessionIndexError(f"could not read the {what} {path}, {error}")
    return [line.strip() for line in text.splitlines() if line.strip()]


def read_results(paths: Sequence) -> Tuple[Dict[str, List[Contribution]], List[str]]:
    """Each public id's contributions in the results files, and the files set aside.

    Each of paths is a results file, or PRODUCT=FILE for a file of that
    product. The last file given for a product's stream counts, and the
    earlier ones of that product's stream are set aside. A file that is not a
    results file is refused.
    """
    latest = {}  # type: Dict[Tuple[Optional[str], str], Tuple[str, Optional[str], Dict[str, Any]]]
    set_aside = []
    for given in paths:
        named, path = _product_given(given)
        results = _results(path)
        stream = results["stream"]
        product = named if named is not None else _product_folder(path, stream)
        key = (product, stream)
        if key in latest:
            set_aside.append(latest[key][0])
        latest[key] = (str(path), product, results)
    found = {}  # type: Dict[str, List[Contribution]]
    for key in latest:
        path, product, results = latest[key]
        stream = results["stream"]
        prefix = stream if product is None else f"{product}/{stream}"
        decided = {}  # type: Dict[str, str]
        for entry in results.get("decisions") or []:
            if isinstance(entry, dict) and isinstance(entry.get("item"), str):
                decided[entry["item"]] = str(entry.get("decision") or "")
        for item in results["items"]:
            sessions = item.get("sessions") or []
            if not sessions:
                continue
            if item.get("needs_decision") is False:
                decision = NO_DECISION
            else:
                decision = decided.get(item["id"]) or NOT_DECIDED
            contribution = Contribution(f"{prefix}/{item['id']}", results["run_id"], decision)
            for ref in sessions:
                if contribution not in found.setdefault(ref, []):
                    found[ref].append(contribution)
    return found, set_aside


def _product_given(given) -> Tuple[Optional[str], Any]:
    """The product named with a results file given as PRODUCT=FILE, and the file.

    Text that names an existing file is that file, so a file whose name holds
    = is read as it is. Otherwise text whose part before its first = is a
    product's name is PRODUCT=FILE. Anything else names a file of no product.
    """
    if not isinstance(given, str) or "=" not in given or os.path.isfile(given):
        return None, given
    product, path = given.split("=", 1)
    if PRODUCT_NAME.fullmatch(product) and path:
        return product, path
    return None, given


def _product_folder(path, stream: str) -> Optional[str]:
    """The product whose folder holds the results file, verification/<product>/<stream>.json, else None."""
    full = Path(os.path.abspath(str(path)))
    folder = full.parent
    if full.name != stream + ".json" or folder.parent.name != VERIFICATION:
        return None
    return folder.name if PRODUCT_NAME.fullmatch(folder.name) else None


def _results(path) -> Dict[str, Any]:
    """The results file at path, refused when it is not one."""
    try:
        results = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise SessionIndexError(f"could not read the results file {path}, {error}")
    problem = None
    if not isinstance(results, dict):
        problem = "it is not a JSON object"
    elif not isinstance(results.get("stream"), str) or not results["stream"].strip():
        problem = "it names no stream"
    elif not isinstance(results.get("run_id"), str) or not results["run_id"].strip():
        problem = "it names no run"
    elif not isinstance(results.get("items"), list):
        problem = "it has no list of items"
    else:
        for item in results["items"]:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                problem = "an item has no id"
                break
            sessions = item.get("sessions")
            if sessions is not None and not (
                isinstance(sessions, list) and all(isinstance(ref, str) for ref in sessions)
            ):
                problem = f"the sessions of item {item['id']} are not a list of public ids"
                break
    if problem is not None:
        raise SessionIndexError(f"the results file {path} is not one, since {problem}")
    return results


def index_rows(
    store,
    project,
    contributions: Optional[Dict[str, List[Contribution]]] = None,
    summaries: bool = True,
    withheld: Sequence[str] = (),
    scrub: Sequence[str] = (),
    home: Optional[str] = None,
    also: Sequence = (),
) -> List[Dict[str, Any]]:
    """The index's rows for the sessions that touched the project, in the order they started.

    Each row holds the keys of COLUMNS, with lists, numbers, and the
    references as they are written into index.html. home is the home folder
    whose path the model's fields write as ~, by default the current one.
    also are the folders the project's work was done in before it moved.
    """
    top = os.path.realpath(str(project))
    # Each of the project's folders, with what a file's name inside it begins with.
    tops = [(top, "")] + [
        (os.path.realpath(str(folder)), os.path.basename(os.path.realpath(str(folder))) + "/") for folder in also
    ]
    contributions = contributions or {}
    homes = _homes(home)
    rows = []
    for session in current(store, "sessions"):
        if getattr(ADAPTERS.get(session["harness"]), "AI", False) is not True:
            continue
        events = session_events(store, session)
        files = {"read": [], "edited": [], "wrote": []}  # type: Dict[str, List[str]]
        other = set()
        for event in events:
            kind = _file_kind(event)
            if kind is None:
                continue
            real = os.path.realpath(event["object"])
            within = next(((folder, start) for folder, start in tops if _inside(real, folder)), None)
            if within is not None:
                name = within[1] + Path(os.path.relpath(real, within[0])).as_posix()
                if name not in files[kind]:
                    files[kind].append(name)
            else:
                other.add(real)
        ran_here = bool(session["project"]) and any(
            _inside(os.path.realpath(session["project"]), folder) for folder, _ in tops
        )
        # A session a contribution names is listed too, so every reference id links to its
        # session, as when an AI found a cited work in a session run elsewhere.
        named = public_id(session["harness_session_id"]) in contributions
        if not ran_here and not any(files.values()) and not named:
            continue
        rows.append(
            _row(store, session, events, files, len(other), contributions, summaries, withheld, scrub, homes)
        )
    rows.sort(key=_start_order)
    for row in rows:
        row.pop("_order")
    return rows


def _row(store, session, events, files, other, contributions, summaries, withheld, scrub, homes):
    """One session's row of the index."""
    ref = public_id(session["harness_session_id"])
    counts = {}  # type: Dict[str, int]
    for event in events:
        counts[event["verb"]] = counts.get(event["verb"], 0) + 1
    tool_calls = {verb: counts[verb] for verb in VERBS if verb in counts}
    for verb in sorted(counts):
        if verb not in tool_calls:
            tool_calls[verb] = counts[verb]
    transcript = _latest_transcript(store, session)
    found = contributions.get(ref, [])
    row = {
        "public_id": ref,
        "started_at": session["started_at"] or "",
        "minutes": _minutes(session["started_at"], session["ended_at"]),
        "harness": session["harness"],
        "harness_version": session["harness_version"] or "",
        "models": list(session["models"] or []),
        "parent": _parent(session["harness_session_id"]),
        "tool_calls": tool_calls,
        "files_read": sorted(files["read"]),
        "files_edited": sorted(files["edited"]),
        "files_written": sorted(files["wrote"]),
        "other_files": other,
    }
    row.update(_model_fields(session, ref, summaries, withheld, scrub, homes))
    row.update(
        {
            "transcript_sha256": transcript["file_sha256"] if transcript else "",
            "transcript_bytes": transcript["byte_size"] if transcript else None,
            "contributions": len(found),
            "references": [item._asdict() for item in found],
            "_order": (
                _when(session["started_at"]) or datetime.max.replace(tzinfo=timezone.utc),
                session["started_at"] or "",
                session["harness_session_id"],
            ),
        }
    )
    return row


def _start_order(row):
    return row["_order"]


def _file_kind(event: Dict[str, Any]) -> Optional[str]:
    """read, edited, or wrote for a tool call that read, edited, or wrote a file, else None."""
    target = event.get("object")
    if not isinstance(target, str) or not target.strip() or not os.path.isabs(target):
        return None
    if event["verb"] in ("wrote", "edited"):
        return event["verb"]
    if event.get("role") == READ_ROLE:
        return "read"
    return None


def _inside(real: str, top: str) -> bool:
    """Whether the real path is the folder top or inside it."""
    return real == top or real.startswith(top.rstrip(os.sep) + os.sep)


def _parent(harness_session_id: str) -> str:
    """The public id of the session a subagent conversation belongs to, else empty."""
    if AGENT not in harness_session_id:
        return ""
    return public_id(harness_session_id.rsplit(AGENT, 1)[0])


def _latest_transcript(store, session) -> Optional[Dict[str, Any]]:
    """The session's latest stored transcript row, across every row the session has had."""
    ids = set(_session_row_ids(store, session))
    rows = [row for row in current(store, "transcripts") if row["session_row_id"] in ids]
    return rows[-1] if rows else None


_TIME = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:?\d{2})?"
)


def _when(text: Optional[str]) -> Optional[datetime]:
    """The time an ISO 8601 text gives, in UTC, a time with no zone read as UTC, else None."""
    found = _TIME.fullmatch((text or "").strip())
    if found is None:
        return None
    year, month, day, hour, minute, second, fraction, zone = found.groups()
    micro = int((fraction or "0")[:6].ljust(6, "0"))
    try:
        when = datetime(int(year), int(month), int(day), int(hour), int(minute), int(second), micro)
    except ValueError:
        return None
    offset = timedelta(0)
    if zone and zone != "Z":
        digits = zone.replace(":", "")
        offset = timedelta(hours=int(digits[1:3]), minutes=int(digits[3:5]))
        if digits[0] == "-":
            offset = -offset
    return (when - offset).replace(tzinfo=timezone.utc)


def _minutes(started: Optional[str], ended: Optional[str]) -> Optional[float]:
    """The session's length in minutes, to one decimal place, or None when a time cannot be read."""
    start, end = _when(started), _when(ended)
    if start is None or end is None:
        return None
    return round((end - start).total_seconds() / 60.0, 1)


def _homes(home: Optional[str]) -> List[str]:
    """The home folder's path as given and as a real path, the longer first."""
    given = os.path.expanduser("~") if home is None else str(home)
    given = given.rstrip(os.sep) or given
    paths = {given, os.path.realpath(given)}
    return sorted((path for path in paths if path and path != os.sep), key=len, reverse=True)


def _model_fields(session, ref, summaries, withheld, scrub, homes) -> Dict[str, Any]:
    """The model pass's four fields as published, with their label."""
    empty = {"title": "", "gist": "", "summary": "", "keywords": []}
    if not summaries or ref in withheld:
        return dict(empty, model_fields=WITHHELD)
    fields = {
        "title": session["title"] or "",
        "gist": session["gist"] or "",
        "summary": session["summary"] or "",
        "keywords": [str(word) for word in (session["keywords"] or [])],
    }
    if not any(fields.values()):
        return dict(empty, model_fields="")
    label = REVIEWED if str(session["origin"]).startswith(PERSON) else UNREVIEWED
    scrubbed = {name: _scrub(fields[name], scrub, homes) for name in ("title", "gist", "summary")}
    scrubbed["keywords"] = [_scrub(word, scrub, homes) for word in fields["keywords"]]
    scrubbed["model_fields"] = label
    return scrubbed


def _scrub(text: str, terms: Sequence[str], homes: Sequence[str]) -> str:
    """The text with each home path made ~ and each term, in any case, made [withheld]."""
    for home in homes:
        text = text.replace(home, "~")
    for term in sorted(terms, key=len, reverse=True):
        text = re.sub(re.escape(term), SCRUBBED, text, flags=re.IGNORECASE)
    return text


def write_session_index(
    store,
    project,
    out_dir,
    results: Sequence = (),
    summaries: bool = True,
    withhold: Sequence[str] = (),
    scrub: Sequence[str] = (),
    home: Optional[str] = None,
    also: Sequence = (),
) -> Index:
    """Write the project's session index into the new or empty folder out_dir.

    results are the results files given, each a file or PRODUCT=FILE,
    withhold the public ids whose model fields are withheld, scrub the terms
    written as [withheld], and also the folders the project's work was done in
    before it moved. Every file is made before any is written, so a refusal
    leaves the folder as it was.
    """
    for folder in also:
        if not Path(folder).is_dir():
            raise SessionIndexError(f"the earlier folder {folder} is not a folder")
    out = Path(out_dir)
    if out.exists() and not out.is_dir():
        raise SessionIndexError(f"the output {out} is not a folder")
    if out.is_dir() and any(out.iterdir()):
        raise SessionIndexError(f"the output folder {out} is not empty, so give a new or empty folder")
    for ref in withhold:
        if not PUBLIC_ID.fullmatch(ref):
            raise SessionIndexError(f"the withhold list names {ref}, which is not a public id")
    contributions, set_aside = read_results(results)
    rows = index_rows(store, project, contributions, summaries, withhold, scrub, home, also)
    listed = {row["public_id"] for row in rows}
    for ref in withhold:
        if ref not in listed:
            raise SessionIndexError(f"the withhold list names {ref}, which no session in the index has")
    unlisted = sorted(ref for ref in contributions if ref not in listed)
    name = os.path.basename(os.path.realpath(str(project)))
    planned = [(CSV_FILE, _csv(rows))]
    planned.append((README_FILE, _readme(rows, name, summaries, withhold, scrub)))
    for row in rows:
        planned.append((row["public_id"] + ".md", _page(row, listed)))
    planned.append((HTML_FILE, _html(rows, name)))
    out.mkdir(parents=True, exist_ok=True)
    for path, text in planned:
        (out / path).write_bytes(text.encode("utf-8"))
    return Index(rows, [path for path, _ in planned], set_aside, unlisted)


# ------------------------------------------------------------------ the files


def _cell_text(row: Dict[str, Any], column: str) -> str:
    """A row's value as one CSV cell."""
    value = row[column]
    if column == "tool_calls":
        return JOIN.join(f"{verb} {count}" for verb, count in value.items())
    if column == "references":
        return JOIN.join(_reference(item) for item in value)
    if isinstance(value, list):
        return JOIN.join(str(item) for item in value)
    if value is None:
        return ""
    return str(value)


def _reference(item: Dict[str, str]) -> str:
    return f"{item['reference']} ({item['decision']}, run {item['run']})"


def _csv(rows: List[Dict[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(COLUMNS)
    for row in rows:
        writer.writerow([_cell_text(row, column) for column in COLUMNS])
    return buffer.getvalue()


# A slot in a template, {{name}}.
_SLOT = re.compile(r"\{\{([a-z_]+)\}\}")


def _fill(template: str, values: Dict[str, str]) -> str:
    """The template file with each {{name}} replaced by its value."""
    text = (TEMPLATES / template).read_text(encoding="utf-8")
    missing = sorted(set(_SLOT.findall(text)) - set(values))
    if missing:
        raise SessionIndexError(f"the template {template} has {{{{{missing[0]}}}}} with no value")
    # One pass over the template, so a value holding {{name}} stays as it is.
    return _SLOT.sub(lambda found: values[found.group(1)], text)


def _md(text: Any) -> str:
    """Text for a Markdown table cell, on one line, with its pipes escaped."""
    return " ".join(str(text).split()).replace("|", "\\|")


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


def _readme(rows, name, summaries, withhold, scrub) -> str:
    contributing = sum(1 for row in rows if row["contributions"])
    notes = []
    if not summaries:
        notes.append("The author withheld these fields for every session.")
    elif withhold:
        notes.append(f"The author withheld these fields for {_count(len(withhold), 'session')}.")
    if scrub:
        notes.append(
            "In them only the home folder's path is written as ~, and each term on the author's"
            " list as [withheld], so they may name other files and full paths."
        )
    else:
        notes.append(
            "In them only the home folder's path is written as ~, so they may name other files"
            " and full paths."
        )
    table = [
        "| Session | Started | Minutes | Harness | Title | AI contributions in the final reports |",
        "|---|---|---|---|---|---|",
    ]
    for row in rows:
        cells = [
            "[{0}]({0}.md)".format(row["public_id"]),
            _md(row["started_at"]),
            _md(_cell_text(row, "minutes")),
            _md(row["harness"]),
            _md(row["title"]),
            str(row["contributions"]),
        ]
        table.append("| " + " | ".join(cells) + " |")
    return _fill(
        README_FILE,
        {
            "project": _md(name),
            "sessions": _count(len(rows), "AI session"),
            "contributing": str(contributing),
            "model_note": " ".join(notes),
            "table": "\n".join(table),
        },
    )


def _page(row: Dict[str, Any], listed) -> str:
    """A session's page. A parent the index lists is a link to its page, else its public id."""
    parent = row["parent"]
    if parent in listed:
        parent = "[{0}]({0}.md)".format(parent)
    fields = [
        ("Public id", row["public_id"]),
        ("Started", row["started_at"]),
        ("Minutes", _cell_text(row, "minutes")),
        ("Harness", row["harness"]),
        ("Harness version", row["harness_version"]),
        ("Models", _cell_text(row, "models")),
        ("Started by session", parent),
        ("Tool calls by verb", _cell_text(row, "tool_calls")),
        ("Project files read", _cell_text(row, "files_read")),
        ("Project files edited", _cell_text(row, "files_edited")),
        ("Project files written", _cell_text(row, "files_written")),
        ("Other files touched, counted only", _cell_text(row, "other_files")),
        ("Transcript sha256", row["transcript_sha256"]),
        ("Transcript size in bytes", _cell_text(row, "transcript_bytes")),
        ("AI contributions in the final reports", str(row["contributions"])),
    ]
    table = ["| Field | Value |", "|---|---|"]
    table += ["| {} | {} |".format(label, value if label == "Started by session" else _md(value))
              for label, value in fields]
    if row["references"]:
        listed = ["| Reference id | Run | Decision |", "|---|---|---|"]
        listed += [
            "| {} | {} | {} |".format(_md(item["reference"]), _md(item["run"]), _md(item["decision"]))
            for item in row["references"]
        ]
        contributions = "\n".join(listed)
    else:
        contributions = "None of this session's work is an item of the final reports given to the index."
    if row["model_fields"] == WITHHELD:
        model = "The author withheld the fields a model wrote for this session."
    elif not row["model_fields"]:
        model = "No model has written fields for this session."
    else:
        listed = ["| Field | Value |", "|---|---|", "| Status | {} |".format(row["model_fields"])]
        for label, column in (("Title", "title"), ("Gist", "gist"), ("Summary", "summary"), ("Keywords", "keywords")):
            listed.append("| {} | {} |".format(label, _md(_cell_text(row, column))))
        model = "\n".join(listed)
    return _fill(
        "session.md",
        {
            "public_id": row["public_id"],
            "fields": "\n".join(table),
            "contributions": contributions,
            "model": model,
        },
    )


def _html(rows: List[Dict[str, Any]], name: str) -> str:
    data = json.dumps(rows, ensure_ascii=False, indent=1)
    # Nothing in the data can close the script or start markup.
    for char, escaped in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026"),
                          ("\u2028", "\\u2028"), ("\u2029", "\\u2029")):
        data = data.replace(char, escaped)
    title = name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    return _fill(HTML_FILE, {"project": title, "data": data})
