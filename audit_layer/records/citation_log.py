"""The written-out citation log, which names the citations AI sessions introduced in a project.

Appendix A2.4 writes a project's records out as files, and Table A5 lists the
citation log among the records the procedures read, which nothing wrote
before. Figure A6 shows a citation's entry in the log, naming who introduced
it, the draft, and the session.

citation_log reads every current session from any harness whose adapter has
the AI flag (Track A, Step A4), wherever the session ran, as the record of
file writes does, so work done from another folder counts for the project
whose files it changed (Track L, Step L2). For each session it reads the
latest stored transcript, which holds every tool call captured so far, with
the session's own harness's adapter (capture.read_stored), and finds each
Edit or Write on a markdown file inside the project. A ForgeCode session's
tool calls come with the names the mechanical pass maps, so its patch is an
Edit and its write a Write, and a subagent conversation is a session of its
own. An Edit introduces the keys its new text cites and its old text did
not. A Write introduces every key in its content, since the earlier text is
not in the record. The first session to introduce a key, by start, is the one
named. Folders are compared as real paths, so a link to the project counts.

A session with no stored transcript that ran outside the project, by the
folder its row names, is skipped and named on standard error, as the
rationales record names a session it skips, so one broken session elsewhere
does not stop every project's write-out. One that ran in the project, or in a
folder inside it, still stops the write-out (Track L, Step L7).

An @ that pandoc prints as text is not a citation (Track L, Step L3), as the
references procedure's extractor reads it. That is an @ a backslash escapes,
as in \\@key and [\\@key], and any @ inside inline code or a fenced code
block. An Edit's old and new text are each read on their own, so a fence
outside the edited text is not seen.

Only citations an AI session introduced get an entry (plan choice 6). A
citation with no record, such as one the scholar typed, gets none, so the
references procedure checks it and flags its origin as unknown. The draft is
written empty, since the audit layer does not know build versions.
"""
import os
import re
import string
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from audit_layer.capture import ADAPTERS, read_stored
from audit_layer.queries import latest_transcript
from audit_layer.records.session_index import public_id
from audit_layer.store import Store, current

# A citation key, read with the characters the references procedure reads,
# letters, digits, and underscores, with colons and hyphens inside a key. Both
# then name a key the same way.
_KEY = r"[A-Za-z0-9_][A-Za-z0-9_:\-]*[A-Za-z0-9_]|[A-Za-z0-9_]"

# A key cited in pandoc's syntax, as in [@key], [@key, p. 5], [@a; @b], or @key
# after a space or at a line start. So the @ comes after an opening bracket, a
# semicolon, a space, or nothing at all, and an email address does not count.
_CITATION = re.compile(r"(?<![^\[;\s])@(" + _KEY + r")")

# A fence that opens a code block, three or more backticks or tildes after at
# most three spaces. A backtick fence's info text holds no backtick.
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_BLANK_LINE = re.compile(r"\n[ \t]*\n")

# The tools that change a file, with the inputs that hold the old and the new
# text. A Write's record holds no old text.
_CHANGES = {
    "Edit": ("old_string", "new_string"),
    "Write": (None, "content"),
}

# The file's opening lines. They are comments, so the reader passes over them.
_HEADER = (
    "# Citations that recorded AI sessions introduced in the project, written by\n"
    "# python3 -m audit_layer write-out citation-log. A citation not listed here\n"
    "# was not found in a recorded session's edits, so the references procedure\n"
    "# checks it and flags its origin as unknown.\n"
)


def citation_keys(text: str) -> List[str]:
    """The keys the text cites in pandoc's syntax, each once, in the order first cited."""
    keys: List[str] = []
    for key in _CITATION.findall(_printed(text)):
        if key not in keys:
            keys.append(key)
    return keys


def project_sessions(store: Store, project) -> List[Dict[str, Any]]:
    """The current AI session rows with an Edit or Write on a markdown file in the project.

    An AI session is one whose harness's adapter has the AI flag, and it
    counts wherever it ran. They come earliest start first, and sessions with
    the same start in the order they were captured. A session skipped for
    having no stored transcript is passed over without naming it, since the
    log names it.
    """
    return [row for row, _ in _project_changes(store, project, name_skipped=False)]


def citation_log(store: Store, project) -> Dict[str, Dict[str, Dict[str, str]]]:
    """The project's citation log, in the form the references procedure reads.

    The form is citations, a mapping from each key AI sessions introduced in
    the project, in sorted order, to introduced_by ai, an empty draft, the
    harness's id for the first session to introduce it, and that session's
    public id as session_ref (Track P, step P2).
    """
    citations: Dict[str, Dict[str, str]] = {}
    for row, introduced in _project_changes(store, project):
        for keys in introduced:
            for key in keys:
                if key not in citations:
                    citations[key] = {
                        "introduced_by": "ai",
                        "draft": "",
                        "session": row["harness_session_id"],
                        "session_ref": public_id(row["harness_session_id"]),
                    }
    return {"citations": {key: citations[key] for key in sorted(citations)}}


def write_citation_log(store: Store, project, out) -> Dict[str, Dict[str, Dict[str, str]]]:
    """Write the project's citation log to the file out as YAML and return it.

    Every transcript is read before the file is written, so a transcript that
    cannot be read leaves the file as it was.
    """
    log = citation_log(store, project)
    text = yaml.safe_dump(log, sort_keys=False, default_flow_style=None, width=4096)
    Path(out).write_text(_HEADER + text, encoding="utf-8")
    return log


def _project_changes(
    store: Store, project, name_skipped: bool = True
) -> List[Tuple[Dict[str, Any], List[List[str]]]]:
    """Each current AI session with a change to a markdown file in the project, and the keys of each change.

    Every current AI session's latest transcript is read, wherever the
    session ran. A session comes with the keys each of its Edit or Write calls
    on a markdown file in the project introduced, in the order of the calls,
    and a session with no such call is left out. Sessions come earliest start
    first, and those with the same start in the order they were captured. A
    session with no stored transcript that ran outside the project is
    skipped, and named on standard error when name_skipped is true. One with
    no project folder is not known to have run outside, so it stops the log.
    """
    top = os.path.realpath(str(project))
    rows = [row for row in current(store, "sessions") if _ai(row["harness"])]
    found = []
    for row in sorted(rows, key=lambda row: row["started_at"]):
        try:
            session = read_stored(store, row)
        except ValueError:
            folder = str(row.get("project") or "")
            if not folder or _inside(folder, top) or _has_transcript(store, row):
                raise
            if name_skipped:
                print(
                    f"skipped session {row['harness_session_id']} from harness {row['harness']},"
                    " which ran outside the project and has no stored transcript",
                    file=sys.stderr,
                )
            continue
        introduced = []
        for tool_call in session.tool_calls:
            keys = _introduced(tool_call, session.cwd, top)
            if keys is not None:
                introduced.append(keys)
        if introduced:
            found.append((row, introduced))
    return found


def _has_transcript(store: Store, row: Dict[str, Any]) -> bool:
    """Whether the session has a stored transcript, so a failure to read it is not for want of one."""
    try:
        latest_transcript(store, row)
    except ValueError:
        return False
    except OSError:
        return True
    return True


def _ai(harness: str) -> bool:
    """Whether the harness's adapter has the AI flag. A harness with no adapter has none."""
    return getattr(ADAPTERS.get(harness), "AI", False) is True


def _introduced(tool_call, cwd: str, top: str) -> Optional[List[str]]:
    """The keys one tool call introduced in a markdown file in the project.

    None when the call is not an Edit or Write on a markdown file in the project.
    """
    if tool_call.name not in _CHANGES:
        return None
    given = tool_call.input if isinstance(tool_call.input, Mapping) else {}
    path = given.get("file_path")
    if not isinstance(path, str) or not path.strip():
        return None
    # A relative path is resolved against the session's working folder, as
    # the tagging pass does.
    path = os.path.normpath(os.path.join(cwd, path))
    if os.path.splitext(path)[1].lower() != ".md" or not _inside(path, top):
        return None
    old_name, new_name = _CHANGES[tool_call.name]
    old = set(citation_keys(_text(given.get(old_name)))) if old_name else set()
    return [key for key in citation_keys(_text(given.get(new_name))) if key not in old]


def _inside(path: str, top: str) -> bool:
    """Whether path is the folder top or inside it, compared as real paths. top is a real path."""
    real = os.path.realpath(path)
    return real == top or real.startswith(top.rstrip(os.sep) + os.sep)


def _printed(text: str) -> str:
    """The text with each @ pandoc prints as text replaced by a space.

    That is an @ a backslash escapes, and any @ inside a fenced code block or
    inline code. A fence closes at the next line of the same character, at
    least as long, with nothing after it but spaces, and a fence that never
    closes is text. A run of backticks opens inline code that the next run of
    the same length closes within the paragraph, and a run with no such close
    is text. A backslash before any ASCII punctuation makes it text.
    """
    lines = text.splitlines(True)
    starts, at = [], 0
    for line in lines:
        starts.append(at)
        at += len(line)
    blocks: List[Tuple[int, int]] = []
    i = 0
    while i < len(lines):
        fence = _FENCE.match(lines[i].rstrip("\r\n"))
        if fence and not (fence.group(1)[0] == "`" and "`" in fence.group(2)):
            mark = fence.group(1)
            close = re.compile(r"^ {0,3}%s{%d,}[ \t]*$" % (re.escape(mark[0]), len(mark)))
            ends = [j for j in range(i + 1, len(lines)) if close.match(lines[j].rstrip("\r\n"))]
            if ends:
                blocks.append((starts[i], starts[ends[0]] + len(lines[ends[0]])))
                i = ends[0] + 1
                continue
        i += 1
    hidden = set()
    at = 0
    for start, end in blocks + [(len(text), len(text))]:
        hidden.update(range(start, end))
        hidden.update(_inline(text, at, start))
        at = end
    return "".join(" " if ch == "@" and k in hidden else ch for k, ch in enumerate(text))


def _inline(text: str, start: int, end: int) -> List[int]:
    """The positions between start and end inside inline code or after an escaping backslash."""
    hidden: List[int] = []
    k = start
    while k < end:
        if text[k] == "\\" and k + 1 < end and text[k + 1] in string.punctuation:
            hidden.append(k + 1)
            k += 2
            continue
        if text[k] == "`":
            run = len(text[k:end]) - len(text[k:end].lstrip("`"))
            blank = _BLANK_LINE.search(text, k, end)
            close = re.compile(r"(?<!`)`{%d}(?!`)" % run).search(text, k + run, blank.start() if blank else end)
            if close:
                hidden.extend(range(k, close.end()))
                k = close.end()
            else:
                k += run
            continue
        k += 1
    return hidden


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""
