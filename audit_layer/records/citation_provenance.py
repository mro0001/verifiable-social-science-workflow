"""The citation provenance record, which says where the record first names each cited work.

the authors' second step for citations (2026-10-30) asks which citations
originated in some way from an AI, and the fourth asks that the session
transcripts, logs, and artifacts be used as much as possible. For each work
in the reference list, this record lists every place the record names it, in
time order, and says whether an AI or the scholar named it first (Track C2,
plan choices 2 and 4). It gives no verdict. It lays out the record for the
references procedure and the scholar.

The record is every captured session in the audit store and every AI-written
artifact. An AI session's parts are read with its own harness's adapter
(capture.read_stored), so Claude Code and ForgeCode give the same parts, and
a subagent conversation is a session of its own. A part names the work in AI
output when it is the assistant's text, the content of a Write or the new
text of an Edit (an AI-written artifact, named by its path), or a tool call's
result, such as a search result. The other inputs of a tool call, such as a
search's query, are not read. Two results are read as the files they show
instead. The result of a Read of a file, or of a Grep of a file or folder
(its path, or the session's folder when it names none), shows the scholar's
own draft, unless that path lies in a folder named with artifacts or is a
file an AI Write produced earlier in the record, when it shows an AI-written
artifact. A part names the work in the scholar's own words when it
is text the scholar typed. In a subagent conversation, or a Forge
conversation an agent began, the user's text is the prompt the AI that
started it wrote, so it is the AI's own words. Text the harness put in a user
record, such as a finished task's notice or the summary that continues a
compacted session, is AI output but no AI's own words. A wrappers session's events, the scholar's own
software calls such as a git commit, are the scholar's, read with the time
each line of the events file gives. Each file in a folder the scholar names
with artifacts is an AI-written artifact, at the time the file was last
changed. Sessions run in an excluded folder are never in the store, since
capture stores nothing of them, so they are never read.

A work is recognized by its DOI (in any case, alone or in a doi.org link),
its title (compared in lower case with punctuation set aside, as whole
words), or its authors and year as a citation of it would give them. The
first author's family name, beginning with a capital letter, is followed
within six words by the year with no other year between. A work with two
authors needs the second family name within three words of the first, and
one with three or more needs et al. or the second family name there. An
organization is named in full, or by the short form its name gives before a
bracket. Each text names a work at most once, at its earliest match.

Times come from the record. A tool call and its result take the call's time.
A text part takes the time of the latest tool call before it in the session,
or the session's start, so a time is never later than the text's own, and
parts keep their order within a session. Appearances are put in time order,
and those with the same time keep the order of their sessions' starts.

The origin is ai when the first appearance is an AI's, scholar when it is the
scholar's, and unknown when the record never names the work. The reason is
the AI's own words at the work's first appearance in the assistant's text or
in an AI-written artifact, a tool result being no AI's own words. In the
assistant's text it is the sentence that names the work with the sentences on
either side within its paragraph, and in an artifact the paragraph. The
quotes are the passages in double quotes of four words or more in the
sentence that names the work and the sentence after it, within the reason's
paragraph, leaving out the work's own title, since a paragraph of a working
file can hold many works, each with its own quotes. A work with no reason has
none.

Each appearance gives its time, by (ai or scholar), its kind, the session's
public id as session_ref (Track P, step P2) and the artifact's path, as each
applies, and a short excerpt, the sentence that names the work, cut around
the mention when it is long. The kind is conversation for text typed in the
conversation, harness for text the harness put there, artifact for a file an
AI wrote, read for a Read's or a Grep's result, tool for any other tool's
result, and event for a wrapper event. A read or a tool also names its tool. No path is ever shown in full, in where an appearance is or
in any excerpt, reason, or quote. An artifact inside the project is named by
its path inside it, one in a folder named with artifacts by that folder's name
and its path inside it, and any other by its file name alone, and every full
path in a text's words is shown the same way.

A DOI in the reference list given as a doi.org or dx.doi.org link is read as
the DOI alone. A folder or a single file may be named with artifacts, so a
working folder that also holds the scholar's own drafts can be named file by
file. A folder or file named with fetched holds sources an AI fetched, such
as a paper's text saved by a search, and its text is AI output but no AI's
own words, of kind fetched, so it gives no reason.
"""
import datetime
import json
import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import yaml

from audit_layer.capture import ADAPTERS, read_stored, wrappers
from audit_layer.queries import latest_transcript
from audit_layer.records.citation_log import _has_transcript
from audit_layer.records.session_index import public_id
from audit_layer.store import Store, current
from audit_layer.stores.bibtex import read_bib

# The longest excerpt, in characters, before the markers of a cut.
EXCERPT_LIMIT = 300

# The longest reason, in characters, before the marker of a cut.
REASON_LIMIT = 2000

# The fewest words a quoted passage needs to be a quote of the source.
QUOTE_WORDS = 4

# The most words between a family name and the year.
AUTHOR_YEAR_GAP = 6

# The most words between the first family name and the second.
SECOND_AUTHOR_GAP = 3

CUT = "..."

# Tools whose result shows the contents of files, read as those files.
_FILE_RESULTS = ("Read", "Grep")

# The tools that write a file, with the input that holds the new text.
_WRITES = {"Write": "content", "Edit": "new_string"}

_HEADER = (
    "# Where the record names each work in the reference list, written by\n"
    "# python3 -m audit_layer write-out citation-provenance. The origin is ai or\n"
    "# scholar by who named the work first, and unknown when nothing in the\n"
    "# record names it. Nothing here is a verdict.\n"
)

_PARAGRAPH = re.compile(r"\n[ \t]*\n")
# A sentence ends at ., !, or ?, and any closing quotes or brackets, before
# space and a capital, a quote, or an opening bracket.
_SENTENCE_END = re.compile(r"[.!?][\"'”’)\]]*\s+(?=[A-Z\"'“‘(\[])")
# Words a period ends that do not end a sentence.
_NOT_AN_END = re.compile(
    r"(?:\b(?:al|e\.g|i\.e|cf|p|pp|vol|no|ed|eds|vs|fig|ch|sec)|\b[A-Z])\.$", re.I
)
_QUOTE = re.compile(r"“([^”]+)”|\"([^\"\n]+)\"")
# A full path in a text's words, of two parts or more, standing alone or
# after file://, so that a web link's path is never taken for one.
_FULL_PATH = re.compile(r"(?:(?<=file://)|(?<![\w.:/~-]))(?:/[\w.+@%~-]+){2,}/?")
# A doi.org or dx.doi.org link's start, taken off a listed DOI.
_DOI_LINK = re.compile(r"^(?:https?://)?(?:dx\.)?doi\.org/", re.I)
_TIME = re.compile(
    r"^(\d{4})-(\d\d)-(\d\d)[T ](\d\d):(\d\d):(\d\d)(?:\.(\d+))?(Z|[+-]\d\d:?\d\d)?$"
)


def read_references(path) -> List[Dict[str, str]]:
    """The works in the reference list, in its order, each with key, title, family, year, and doi.

    The list is the references procedure's refs.yaml, a list of entries or a
    mapping with references, each with id, author, issued, title, and DOI, or
    a BibTeX file, read when its name ends in .bib. A field a work lacks is
    empty. Each work also gives families, its authors' family names in order,
    an organization's by its name (_organization). A list that cannot be read
    is refused with a ValueError.
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".bib":
        return [_bib_work(entry) for entry in read_bib(text)]
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ValueError(f"the reference list {path} is not YAML, {error}")
    if isinstance(data, Mapping):
        data = data.get("references")
    if not isinstance(data, list):
        raise ValueError(f"the reference list {path} holds no list of references")
    works = []
    for number, entry in enumerate(data, start=1):
        if not isinstance(entry, Mapping) or not str(entry.get("id") or "").strip():
            raise ValueError(f"entry {number} of the reference list {path} has no id")
        authors = entry.get("author")
        families = []
        for author in authors if isinstance(authors, list) else []:
            if not isinstance(author, Mapping):
                continue
            if author.get("family"):
                families.append(_plain(author["family"]))
            elif author.get("literal"):
                families.append(_organization(_plain(author["literal"])))
        works.append(
            {
                "key": str(entry["id"]).strip(),
                "title": _plain(entry.get("title")),
                "family": families[0] if families else "",
                "families": families,
                "year": _csl_year(entry.get("issued")),
                "doi": _doi(entry.get("DOI") or entry.get("doi")),
            }
        )
    return works


def citation_provenance(
    store: Store, project, works: Sequence[Dict[str, str]], artifacts: Sequence = (), fetched: Sequence = ()
) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """The provenance record of the works, as a mapping works from each key to its entry."""
    top = os.path.realpath(str(project))
    written = [os.path.realpath(str(folder)) for folder in artifacts]
    found = [os.path.realpath(str(folder)) for folder in fetched]
    folders = written + found
    texts = _record_texts(store, top, folders, written, found)
    record: Dict[str, Dict[str, Any]] = {}
    for work in works:
        record[work["key"]] = _entry(work, texts, top, folders)
    return {"works": record}


def write_citation_provenance(store: Store, project, works, artifacts, out, fetched=()) -> Dict[str, Any]:
    """Write the provenance record to the file out as YAML and return it.

    The whole record is read before the file is written, so a transcript that
    cannot be read leaves the file as it was.
    """
    record = citation_provenance(store, project, works, artifacts, fetched)
    text = yaml.safe_dump(
        record, sort_keys=False, default_flow_style=False, allow_unicode=True, width=4096
    )
    Path(out).write_text(_HEADER + text, encoding="utf-8")
    return record


class _Text:
    """One text in the record that may name a work."""

    def __init__(self, text, time, by, own_words, kind, session_ref=None, artifact=None, tool=None):
        self.text = text
        self.time = time
        self.by = by
        # True when the text is the AI's own words, the assistant's text or an
        # AI-written artifact, where a reason may be read.
        self.own_words = own_words
        # conversation for text typed in the conversation, harness for text
        # the harness put there, artifact for a file's text, read for a Read's
        # or a Grep's result, tool for any other tool result, and event for a
        # wrapper event.
        self.kind = kind
        self.session_ref = session_ref
        self.artifact = artifact
        # The tool whose result this is, for a read or a tool.
        self.tool = tool
        # The full real path of the file or folder a Read or a Grep showed, or empty text.
        self.full = ""
        self._lowered = None
        self._normal = None

    def lowered(self) -> str:
        """The text in lower case, made once."""
        if self._lowered is None:
            self._lowered = self.text.lower()
        return self._lowered

    def normal(self) -> Tuple[str, List[int]]:
        """The text as _normalized gives it, made once."""
        if self._normal is None:
            self._normal = _normalized(self.text)
        return self._normal


def _record_texts(store: Store, top: str, folders: List[str], artifact_folders=None, fetched_folders=()) -> List[_Text]:
    """Every text in the record, in time order, those with one time in their sessions' order.

    folders are every artifacts and fetched folder, artifact_folders the artifacts ones
    (all of folders when not given), and fetched_folders the fetched ones.
    """
    texts: List[_Text] = []
    written: List[Tuple[Any, str]] = []
    rows = sorted(current(store, "sessions"), key=lambda row: row["started_at"] or "")
    for row in rows:
        if row["harness"] == wrappers.NAME:
            texts.extend(_wrapper_texts(store, row))
            continue
        if getattr(ADAPTERS.get(row["harness"]), "AI", False) is not True:
            continue
        session = _read(store, row, top)
        if session is None:
            continue
        texts.extend(_session_texts(session, row, top, folders, written))
    for folder in folders if artifact_folders is None else artifact_folders:
        texts.extend(_artifact_texts(folder, top, folders))
    for folder in fetched_folders:
        texts.extend(_artifact_texts(folder, top, folders, own_words=False))
    texts.sort(key=lambda text: _moment(text.time))
    _settle_reads(texts, written, folders)
    return texts


def _read(store: Store, row: Dict[str, Any], top: str):
    """The stored session, or None for one with no stored transcript that ran outside the project.

    As the citation log does, such a session is named on standard error and
    skipped, and any other that cannot be read stops the record.
    """
    try:
        return read_stored(store, row)
    except ValueError:
        folder = str(row.get("project") or "")
        if not folder or _inside(folder, top) or _has_transcript(store, row):
            raise
        print(
            f"skipped session {row['harness_session_id']} from harness {row['harness']},"
            " which ran outside the project and has no stored transcript",
            file=sys.stderr,
        )
        return None


def _session_texts(session, row, top, folders, written) -> List[_Text]:
    """The texts of one AI session's parts, in order."""
    ref = public_id(row["harness_session_id"])
    # A subagent conversation's id holds /agent-, and an agent may begin a
    # conversation in another harness, as with Forge. Its user text is the
    # prompt the AI that started it wrote.
    by_agent = "/agent-" in str(row["harness_session_id"] or "") or bool(
        getattr(session, "started_by_agent", False)
    )
    time = session.started_at
    texts = []
    for part in session.parts:
        call = part.tool_call
        if call is None:
            if not isinstance(part.text, str):
                continue
            if part.role == "meta":
                # Text the harness put in a user record, AI output but no AI's own words.
                texts.append(_Text(part.text, time, "ai", False, "harness", ref))
                continue
            by = "ai" if part.role == "assistant" or by_agent else "scholar"
            texts.append(_Text(part.text, time, by, by == "ai", "conversation", ref))
            continue
        time = call.time or time
        given = call.input if isinstance(call.input, Mapping) else {}
        path = given.get("file_path") if isinstance(given.get("file_path"), str) else ""
        full = os.path.realpath(os.path.join(session.cwd, path)) if path.strip() else ""
        if call.name in _WRITES and full:
            new = given.get(_WRITES[call.name])
            if call.name == "Write":
                written.append((_moment(time), full))
            texts.append(
                _Text(_string(new), time, "ai", True, "artifact", ref, _shown(full, top, folders))
            )
        if isinstance(part.result, str):
            if call.name in _FILE_RESULTS:
                result = _Text(part.result, time, "scholar", False, "read", ref, tool=call.name)
                if call.name == "Read" and full:
                    result.artifact = _shown(full, top, folders)
                    result.full = full
                elif call.name == "Grep":
                    # A Grep names its file or folder under path, and searches
                    # the session's folder when it names none.
                    target = given.get("path") if isinstance(given.get("path"), str) else ""
                    result.full = os.path.realpath(os.path.join(session.cwd, target.strip()))
                texts.append(result)
            else:
                texts.append(_Text(part.result, time, "ai", False, "tool", ref, tool=call.name))
    return texts


def _settle_reads(texts: List[_Text], written, folders: List[str]) -> None:
    """Give a Read's or a Grep's result to the AI when its path lies in an artifacts folder or an AI wrote it before."""
    for text in texts:
        full = text.full
        if text.kind != "read" or not full:
            continue
        moment = _moment(text.time)
        if any(_inside(full, folder) for folder in folders) or any(
            path == full and at <= moment for at, path in written
        ):
            text.by = "ai"


def _wrapper_texts(store: Store, row: Dict[str, Any]) -> List[_Text]:
    """The scholar's texts in one wrappers session, an event's command and its rationale, at its time."""
    _, data = latest_transcript(store, row)
    ref = public_id(row["harness_session_id"])
    texts = []
    end = data.rfind(b"\n")
    for line in data[: end + 1].split(b"\n"):
        if not line.strip():
            continue
        event = json.loads(line.decode("utf-8"))
        parts = [event.get(name) for name in ("object", "rationale")]
        text = "\n\n".join(part for part in parts if isinstance(part, str) and part)
        texts.append(_Text(text, event.get("at") or row["started_at"], "scholar", False, "event", ref))
    return texts


def _artifact_texts(folder: str, top: str, folders: List[str], own_words: bool = True) -> List[_Text]:
    """The text of each file in an artifacts folder, or of an artifacts file, at the time it was last changed.

    A folder's files come in path order. A file that is not UTF-8 text is passed over.
    """
    texts = []
    paths = [Path(folder)] if Path(folder).is_file() else sorted(Path(folder).rglob("*"))
    for path in paths:
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        changed = datetime.datetime.fromtimestamp(path.stat().st_mtime, datetime.timezone.utc)
        time = changed.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        full = os.path.realpath(str(path))
        kind = "artifact" if own_words else "fetched"
        texts.append(_Text(text, time, "ai", own_words, kind, None, _shown(full, top, folders)))
    return texts


def _entry(work: Dict[str, str], texts: List[_Text], top: str, folders: List[str]) -> Dict[str, Any]:
    appearances = []
    reason = None
    quotes: List[Dict[str, str]] = []
    find = _finder(work)
    for text in texts:
        span = find(text)
        if span is None:
            continue
        fields = {"time": text.time, "by": text.by, "kind": text.kind}
        if text.tool:
            fields["tool"] = text.tool
        appearance = _where(text, fields)
        appearance["excerpt"] = _excerpt(text.text, span, top, folders)
        appearances.append(appearance)
        if reason is None and text.by == "ai" and text.own_words:
            paragraph = _paragraph(text.text, span)
            if text.kind == "conversation":
                words = _around(text.text, paragraph, span)
            else:
                words = _flat(text.text[paragraph[0] : paragraph[1]])
            words = _hide_paths(words, top, folders)
            reason = _where(text, {"time": text.time, "text": _cut(words, REASON_LIMIT)})
            quotes = _quotes(text, _mention_sentences(text.text, paragraph, span), work, top, folders)
    first_ai = next((dict(a) for a in appearances if a["by"] == "ai"), None)
    first_scholar = next((dict(a) for a in appearances if a["by"] == "scholar"), None)
    origin = appearances[0]["by"] if appearances else "unknown"
    return {
        "origin": origin,
        "appearances": appearances,
        "first_ai": first_ai,
        "first_scholar": first_scholar,
        "reason": reason,
        "quotes": quotes,
    }


def _where(text: _Text, fields: Dict[str, Any]) -> Dict[str, Any]:
    """The fields with the text's session_ref and artifact, as each applies."""
    out = dict(fields)
    if text.session_ref:
        out["session_ref"] = text.session_ref
    if text.artifact:
        out["artifact"] = text.artifact
    return out


def _finder(work: Dict[str, str]):
    """A function giving where a text first names the work, as a span of its text, or None.

    The work's patterns are made once, and each text is put in lower case and
    normalized once, however many works are looked for in it.
    """
    doi_pattern = None
    doi = work.get("doi", "").lower()
    if doi:
        # The DOI stands alone, or follows doi.org/ (or dx.doi.org/) in a link.
        doi_pattern = re.compile(
            r"(?:(?<=doi\.org/)|(?<![a-z0-9./]))" + re.escape(doi) + r"(?![a-z0-9/_-])(?!\.[a-z0-9])"
        )
    # Each pattern of the normalized text, with a word it must hold, looked for
    # first since a plain search is far quicker than a pattern's.
    norm_patterns = []
    title = _normalized(work.get("title", ""))[0].strip()
    if title:
        norm_patterns.append((title, re.compile(r"(?<!\w)" + re.escape(title) + r"(?!\w)"), False))
    families = [name for name in work.get("families") or [work.get("family", "")] if name]
    family = _normalized(families[0])[0].strip() if families else ""
    year = work.get("year", "")
    # Whether the family name must begin with a capital letter in the text, as
    # it does in the list. A name such as de Vries begins in lower case.
    capital = bool(families) and families[0][:1].isupper()
    if family and year:

        def other(most):
            # Up to most words, none of them a year.
            return r"(?: (?!\d{4}[a-z]?(?!\w))\w+){0,%d}" % most

        authors = ""
        if len(families) >= 2:
            second = _normalized(families[1])[0].strip()
            then_second = other(SECOND_AUTHOR_GAP) + " " + re.escape(second)
            authors = then_second if len(families) == 2 else "(?: et al|" + then_second + ")"
        norm_patterns.append(
            (
                family,
                re.compile(
                    r"(?<!\w)" + re.escape(family) + authors + other(AUTHOR_YEAR_GAP) + " " + re.escape(year)
                    + r"[a-z]?(?!\w)"
                ),
                capital,
            )
        )

    def find(text: _Text) -> Optional[Tuple[int, int]]:
        if not text.text:
            return None
        spans = []
        if doi_pattern is not None and doi in text.lowered():
            found = doi_pattern.search(text.lowered())
            if found:
                spans.append(found.span())
        if norm_patterns:
            norm, at = text.normal()
            for word, pattern, capital in norm_patterns:
                if word not in norm:
                    continue
                for found in pattern.finditer(norm):
                    if capital and not text.text[at[found.start()]].isupper():
                        continue
                    spans.append((at[found.start()], at[found.end() - 1] + 1))
                    break
        return min(spans) if spans else None

    return find


def _normalized(text: str) -> Tuple[str, List[int]]:
    """The text in lower case with each run of other than letters and digits one space.

    The list gives, for each character of the result, where it came from in the text.
    """
    out: List[str] = []
    at: List[int] = []
    for index, char in enumerate(text):
        if char.isalnum():
            for lowered in char.lower():
                out.append(lowered)
                at.append(index)
        elif out and out[-1] != " ":
            out.append(" ")
            at.append(index)
    return "".join(out), at


def _paragraph(text: str, span: Tuple[int, int]) -> Tuple[int, int]:
    """The start and end of the paragraph that holds the span, set apart by blank lines."""
    start = 0
    for found in _PARAGRAPH.finditer(text):
        if found.end() <= span[0]:
            start = found.end()
    after = _PARAGRAPH.search(text, span[1])
    return start, after.start() if after else len(text)


def _sentences(text: str, start: int, end: int) -> List[Tuple[int, int]]:
    """The sentences between start and end, as spans of the text."""
    found = []
    at = start
    for match in _SENTENCE_END.finditer(text, start, end):
        if _NOT_AN_END.search(text[at : match.start() + 1]):
            continue
        found.append((at, match.end()))
        at = match.end()
    found.append((at, end))
    return found


def _sentence_index(sentences: List[Tuple[int, int]], span: Tuple[int, int]) -> int:
    return next(i for i, (start, end) in enumerate(sentences) if span[0] < end or i == len(sentences) - 1)


def _excerpt(text: str, span: Tuple[int, int], top: str, folders: Sequence[str]) -> str:
    """The sentence that names the work, cut around the mention when it is long.

    Each full path in it is shown as _shown shows it. A cut never falls inside
    a full path, so no part of one is left.
    """
    start, end = _paragraph(text, span)
    sentences = _sentences(text, start, end)
    first = _sentence_index(sentences, span)
    last = _sentence_index(sentences, (span[1] - 1, span[1]))
    begin, finish = sentences[first][0], sentences[last][1]
    sentence = _flat(_hide_paths(text[begin:finish], top, folders))
    if len(sentence) <= EXCERPT_LIMIT:
        return sentence
    room = max(0, (EXCERPT_LIMIT - (span[1] - span[0])) // 2)
    left = max(begin, span[0] - room)
    right = min(finish, span[1] + room)
    for found in _FULL_PATH.finditer(text, begin, finish):
        if found.start() < left < found.end():
            left = found.start()
        if found.start() < right < found.end():
            right = found.end()
    cut = _flat(_hide_paths(text[left:right], top, folders))[:EXCERPT_LIMIT]
    return (CUT if left > begin else "") + cut + (CUT if right < finish else "")


def _around(text: str, paragraph: Tuple[int, int], span: Tuple[int, int]) -> str:
    """The sentence that names the work and the sentences on either side within the paragraph."""
    sentences = _sentences(text, paragraph[0], paragraph[1])
    first = _sentence_index(sentences, span)
    last = _sentence_index(sentences, (span[1] - 1, span[1]))
    begin = sentences[max(0, first - 1)][0]
    finish = sentences[min(len(sentences) - 1, last + 1)][1]
    return _flat(text[begin:finish])


def _mention_sentences(text: str, paragraph: Tuple[int, int], span: Tuple[int, int]) -> Tuple[int, int]:
    """The start and end of the sentence that names the work and the sentence after it, within the paragraph."""
    sentences = _sentences(text, paragraph[0], paragraph[1])
    first = _sentence_index(sentences, span)
    last = _sentence_index(sentences, (span[1] - 1, span[1]))
    return sentences[first][0], sentences[min(len(sentences) - 1, last + 1)][1]


def _quotes(
    text: _Text, paragraph: Tuple[int, int], work: Dict[str, str], top: str, folders: Sequence[str]
) -> List[Dict[str, str]]:
    """The quoted passages of four words or more in the stretch of text, leaving out the work's title.

    Each full path in a quote is shown as _shown shows it.
    """
    title = _normalized(work.get("title", ""))[0].strip()
    found = []
    for match in _QUOTE.finditer(text.text, paragraph[0], paragraph[1]):
        quoted = _flat(_hide_paths(match.group(1) or match.group(2), top, folders))
        norm = _normalized(quoted)[0].strip()
        if len(norm.split()) < QUOTE_WORDS or (title and norm == title):
            continue
        if any(quote["text"] == quoted for quote in found):
            continue
        found.append(_where(text, {"text": quoted, "time": text.time}))
    return found


def _bib_work(entry: Dict[str, Any]) -> Dict[str, Any]:
    fields = entry["fields"]
    families = _bib_families(str(fields.get("author") or ""))
    year = re.match(r"\d{4}", _plain(fields.get("year") or fields.get("date")))
    return {
        "key": entry["key"],
        "title": _plain(fields.get("title")),
        "family": families[0] if families else "",
        "families": families,
        "year": year.group(0) if year else "",
        "doi": _doi(fields.get("doi")),
    }


def _bib_families(field: str) -> List[str]:
    """The family names of a BibTeX author field, an organization's by its name.

    The names are split at each and outside braces. A name held whole in one
    pair of braces is an organization (_organization).
    """
    names, depth, start = [], 0, 0
    for index, char in enumerate(field):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        elif depth == 0 and field.startswith(" and ", index):
            names.append(field[start:index])
            start = index + len(" and ")
    names.append(field[start:])
    families = []
    for name in (name.strip() for name in names):
        if not name:
            continue
        if name.startswith("{") and name.endswith("}") and _closes_at_end(name):
            families.append(_organization(_plain(name)))
        else:
            families.append(_bib_family(_plain(name)))
    return [family for family in families if family]


def _closes_at_end(name: str) -> bool:
    """True when the brace that opens the name closes at its end."""
    depth = 0
    for index, char in enumerate(name):
        depth += {"{": 1, "}": -1}.get(char, 0)
        if depth == 0:
            return index == len(name) - 1
    return False


def _organization(name: str) -> str:
    """An organization's name as a citation gives it, the short form before a bracket when there is one."""
    short = name.split("(", 1)[0].strip()
    return short or name


def _bib_family(name: str) -> str:
    """The family name of a BibTeX name, Last, First or First von Last."""
    if "," in name:
        return name.split(",", 1)[0].strip()
    words = name.split()
    for index, word in enumerate(words[:-1]):
        if word[:1].islower():
            return " ".join(words[index:])
    return words[-1] if words else ""


def _doi(value: Any) -> str:
    """A listed DOI, with any doi.org or dx.doi.org link's start taken off."""
    return _DOI_LINK.sub("", _plain(value))


def _csl_year(issued: Any) -> str:
    if isinstance(issued, Mapping) and issued.get("date-parts"):
        issued = issued["date-parts"][0][0]
    elif isinstance(issued, Mapping) and "raw" in issued:
        issued = issued["raw"]
    elif isinstance(issued, list) and issued and isinstance(issued[0], Mapping):
        issued = issued[0].get("year")
    found = re.match(r"\d{4}", str(issued if issued is not None else ""))
    return found.group(0) if found else ""


def _moment(time: Any) -> datetime.datetime:
    """The time as a moment in UTC, a time with no zone read as UTC, and one not read as the latest."""
    found = _TIME.match(str(time or "").strip())
    if not found:
        return datetime.datetime.max.replace(tzinfo=datetime.timezone.utc)
    year, month, day, hour, minute, second, fraction, zone = found.groups()
    micro = int((fraction or "0")[:6].ljust(6, "0"))
    offset = datetime.timedelta(0)
    if zone and zone != "Z":
        sign = -1 if zone[0] == "-" else 1
        digits = zone[1:].replace(":", "")
        offset = sign * datetime.timedelta(hours=int(digits[:2]), minutes=int(digits[2:]))
    moment = datetime.datetime(
        int(year), int(month), int(day), int(hour), int(minute), int(second), micro,
        tzinfo=datetime.timezone(offset),
    )
    return moment.astimezone(datetime.timezone.utc)


def _shown(full: str, top: str, folders: Sequence[str] = ()) -> str:
    """A file's path as the record shows it, never in full.

    A file inside the project is named by its path inside it, one in an
    artifacts folder by that folder's name and its path inside it, and any
    other by its file name alone, so no path holding a user name is shown.
    """
    if _inside(full, top):
        return os.path.relpath(full, top).replace(os.sep, "/")
    for folder in folders:
        if _inside(full, folder):
            inner = os.path.relpath(full, folder).replace(os.sep, "/")
            name = os.path.basename(folder.rstrip(os.sep))
            return name if inner == "." else name + "/" + inner
    return os.path.basename(full)


def _hide_paths(text: str, top: str, folders: Sequence[str]) -> str:
    """The text with each full path in it shown as _shown shows it.

    A period or comma that ends the path is taken as the text's, not the path's.
    """

    def shown(found) -> str:
        path = found.group(0)
        tail = len(path) - len(path.rstrip(".,"))
        path = path[: len(path) - tail]
        return _shown(os.path.realpath(path), top, folders) + found.group(0)[len(path) :]

    return _FULL_PATH.sub(shown, text)


def _inside(path: str, top: str) -> bool:
    real = os.path.realpath(path)
    return real == top or real.startswith(top.rstrip(os.sep) + os.sep)


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + CUT


def _plain(value: Any) -> str:
    """A value as one line of text, with BibTeX's braces dropped."""
    if value is None:
        return ""
    return _flat(str(value).replace("{", "").replace("}", ""))


def _string(value: Any) -> str:
    return value if isinstance(value, str) else ""
