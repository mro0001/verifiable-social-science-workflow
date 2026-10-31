"""The list of unverified claims. Contract in CONTRACT.md.

Reads each stream's results file by the build's own rule (`build.verification`) and lists
every stream that is not verified as a whole and every item still open. Only reads
happen here. No check is run and no database is queried.
"""
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple, Union

from ospipe.build.verification import STREAMS, stream_detail

PathLike = Union[str, Path]

# The item fields worth showing for each stream, in the order tried. The citations
# fields are those a references run writes (printed from a run on the test story), and
# `summary` is the key every stream's items carry once their item lists are filled.
SUMMARY_FIELDS = {
    "prose": ("summary",),
    "citations": ("summary", "reason", "sentence"),
    "data": ("summary",),
    "build": ("summary",),
}  # type: Dict[str, Tuple[str, ...]]

SUMMARY_LENGTH = 120
WHOLE_STREAM = "-"
WHOLE_STREAM_STATES = ("missing", "unreadable", "out_of_date")


class Unverified(NamedTuple):
    stream: str
    item: str
    state: str
    summary: str


def summary_of(stream: str, item: dict) -> str:
    """The first non-empty text field among the stream's SUMMARY_FIELDS, on one line and
    cut to 120 characters, or an empty text when there is none."""
    for field in SUMMARY_FIELDS.get(stream, ()):
        value = item.get(field)
        if isinstance(value, str):
            text = " ".join(value.split())
            if text:
                return text[:SUMMARY_LENGTH]
    return ""


def unverified_claims(
    verification_dir: PathLike,
    source_path: Optional[PathLike],
    numbers_path: Optional[PathLike],
) -> List[Unverified]:
    """One entry for each stream that is missing, unreadable, or out of date (item `-`),
    then one for each of its open items, in stream order and then the file's order."""
    found = []  # type: List[Unverified]
    details = stream_detail(verification_dir, source_path, numbers_path)
    for stream in STREAMS:
        detail = details[stream]
        if detail.state in WHOLE_STREAM_STATES:
            found.append(Unverified(stream, WHOLE_STREAM, detail.state, ""))
        for item_id, state, item in detail.open_items:
            found.append(Unverified(stream, item_id, state, summary_of(stream, item)))
    return found


def entry_line(entry: Unverified) -> str:
    """`<stream> <item> <state>`, then `, <summary>` when there is one."""
    line = "{0} {1} {2}".format(entry.stream, entry.item, entry.state)
    return line + ", " + entry.summary if entry.summary else line


def count_line(entries: List[Unverified]) -> str:
    return "{0} unverified".format(len(entries))


def markdown_list(entries: List[Unverified]) -> str:
    """The entries as a markdown list, then the count as its own paragraph."""
    lines = ["- " + entry_line(entry) for entry in entries]
    if lines:
        lines.append("")
    lines.append(count_line(entries))
    return "\n".join(lines) + "\n"
