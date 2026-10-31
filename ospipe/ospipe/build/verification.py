"""Verification status. The build reads each stream's latest results file and runs no check itself.

Contract in CONTRACT.md. For each of the four streams the build reads
`verification_dir/<stream>.json`, the results file the scholar hands over from that
stream's verification run. A stream is verified only when that file exists, parses with
schema `verification-results` and schema_version 1, lists among its `inputs` checksums the
checksum of the input that stream covers, and every item that needs a decision has a latest
decision `approved` on the file's `run_id`. Otherwise the stream is flagged. The covered
input is the source text for prose, citations, and build, and the numbers file for data.

Nothing here raises over a results file or a missing input, so the status never stops a
build. Only reads happen here. No folder is made and no network is used.
"""
import hashlib
import json
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple, Union

PathLike = Union[str, Path]

STREAMS = ("prose", "citations", "data", "build")
SCHEMA = "verification-results"
SCHEMA_VERSION = 1
APPROVED = "approved"


def _checksum(path: Optional[PathLike]) -> Optional[str]:
    """The file's checksum in the form a verification run records (`sha256:` and the hex
    digest), or None when there is no path or the file cannot be read."""
    if path is None:
        return None
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                digest.update(chunk)
    except OSError:
        return None
    return "sha256:" + digest.hexdigest()


def _well_formed(data: object) -> bool:
    """True when data has the shape this module reads. Each item is an object with a text
    `id` and a true or false `needs_decision`, and each decision is an object naming its
    item by a text `item`."""
    if not isinstance(data, dict):
        return False
    version = data.get("schema_version")
    if data.get("schema") != SCHEMA or type(version) is not int or version != SCHEMA_VERSION:
        return False
    run_id = data.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        return False
    if not isinstance(data.get("inputs"), dict):
        return False
    items, decisions = data.get("items"), data.get("decisions")
    if not isinstance(items, list) or not isinstance(decisions, list):
        return False
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            return False
        if not isinstance(item.get("needs_decision"), bool):
            return False
    for entry in decisions:
        if not isinstance(entry, dict) or not isinstance(entry.get("item"), str):
            return False
    return True


def _read_results(path: Path) -> Optional[dict]:
    """The parsed results file, or None when it is missing, unreadable, or malformed."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return None
    return data if _well_formed(data) else None


def _all_approved(results: dict) -> bool:
    """Every item that needs a decision has, as its latest decision, `approved` on this
    file's run. Decisions are kept in the order they were made, so a later one replaces
    an earlier one for the same item."""
    latest = {}  # type: Dict[str, dict]
    for entry in results["decisions"]:
        latest[entry["item"]] = entry
    for item in results["items"]:
        if not item["needs_decision"]:
            continue
        entry = latest.get(item["id"])
        if entry is None:
            return False
        if entry.get("decision") != APPROVED or entry.get("run_id") != results["run_id"]:
            return False
    return True


def stream_status(
    verification_dir: PathLike,
    source_path: Optional[PathLike],
    numbers_path: Optional[PathLike],
) -> Tuple[List[str], Dict[str, str]]:
    """Return (flags, runs). `flags` lists the flagged streams in the order prose,
    citations, data, build. `runs` maps each stream whose results file is well formed to
    that file's run_id, whether or not the stream is flagged."""
    folder = Path(verification_dir)
    covered = {"source": _checksum(source_path), "numbers": _checksum(numbers_path)}
    flags = []  # type: List[str]
    runs = {}  # type: Dict[str, str]
    for stream in STREAMS:
        results = _read_results(folder / (stream + ".json"))
        if results is None:
            flags.append(stream)
            continue
        runs[stream] = results["run_id"]
        checksum = covered["numbers" if stream == "data" else "source"]
        current = checksum is not None and checksum in results["inputs"].values()
        if not (current and _all_approved(results)):
            flags.append(stream)
    return flags, runs


HELD = "held"
UNDECIDED = "undecided"


class StreamDetail(NamedTuple):
    """One stream's state. `state` is `missing`, `unreadable`, `out_of_date`, `open`, or
    `verified`. `run_id` is the results file's run, or None when the file is missing or
    unreadable. `open_items` lists `(item id, held or undecided, item)` for each item that
    needs a decision and has no approval on the file's run, in the file's order."""

    state: str
    run_id: Optional[str]
    open_items: List[Tuple[str, str, dict]]


def latest_decision(results: dict, item_id: str) -> Tuple[str, Optional[dict]]:
    """Return `(decision, entry)` for one item, by the rule `stream_status` uses. The
    last decision listed for the item counts only when it names the file's own run. It
    gives `approved` or `held` with that entry, and anything else gives `undecided` with
    None, as does no decision at all."""
    entry = None
    for candidate in results.get("decisions", []):
        if isinstance(candidate, dict) and candidate.get("item") == item_id:
            entry = candidate
    if entry is None or entry.get("run_id") != results.get("run_id"):
        return UNDECIDED, None
    if entry.get("decision") == APPROVED:
        return APPROVED, entry
    if entry.get("decision") == HELD:
        return HELD, entry
    return UNDECIDED, None


def stream_detail(
    verification_dir: PathLike,
    source_path: Optional[PathLike],
    numbers_path: Optional[PathLike],
) -> Dict[str, StreamDetail]:
    """Return each stream's StreamDetail in the order prose, citations, data, build. The
    streams it does not call `verified` are the flags `stream_status` returns. A stream
    out of date also lists its open items."""
    folder = Path(verification_dir)
    covered = {"source": _checksum(source_path), "numbers": _checksum(numbers_path)}
    found = {}  # type: Dict[str, StreamDetail]
    for stream in STREAMS:
        path = folder / (stream + ".json")
        results = _read_results(path)
        if results is None:
            found[stream] = StreamDetail("unreadable" if path.exists() else "missing", None, [])
            continue
        open_items = []  # type: List[Tuple[str, str, dict]]
        for item in results["items"]:
            if not item["needs_decision"]:
                continue
            word, _ = latest_decision(results, item["id"])
            if word != APPROVED:
                open_items.append((item["id"], word, item))
        checksum = covered["numbers" if stream == "data" else "source"]
        if checksum is None or checksum not in results["inputs"].values():
            state = "out_of_date"
        elif open_items:
            state = "open"
        else:
            state = "verified"
        found[stream] = StreamDetail(state, results["run_id"], open_items)
    return found


def status_text(flags: List[str]) -> str:
    """The ledger's verification cell, `unverified: <streams>` or `verified`."""
    return "unverified: " + ", ".join(flags) if flags else "verified"


def runs_text(runs: Dict[str, str]) -> str:
    """The ledger's runs cell, `<stream>=<run_id>` in stream order joined by `; `, or `-`."""
    return "; ".join("{0}={1}".format(s, runs[s]) for s in STREAMS if s in runs) or "-"
