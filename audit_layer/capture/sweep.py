"""The sweep, which captures every session a harness keeps that the store does not yet hold whole.

Appendix A2.4 "Capture" sweeps each harness's session files while a session
runs, when it ends, and again on a schedule, and Figure A4 says the sweep is
safe to repeat. Capture does not depend on a session closing cleanly, and the
sweep looks for transcripts not yet in custody (spec 0.11 "Audit", decision
log of 2026-08-05).

For each harness, every registered one unless named, the sweep lists the
sessions under the harness's root through its adapter, or takes the locations
it is given. A listed session whose size equals the byte size of its latest
stored transcript is counted unchanged and is not read (plan choice 6). Every
other session goes through capture_session, which stores what is new. A
session whose capture stores nothing new is counted unchanged too. A session
that fails to be read does not stop the sweep, and the summary names it by
its session id, never by its path, since a harness folder's name can spell out
the folder a session ran in.

After the sweep captures a session, it snapshots the working files the
session produced or edited (stores/working.py, Step A16), and so for each
subagent conversation captured with it. A snapshot is taken only of a session
the sweep reads, so a session counted unchanged is not snapshotted again.

A main session file's subagent conversations are captured along with it, so
the sweep counts each one once and does not capture it again when the listing
reaches its own file.

One sweep runs at a time. The sweep holds a lock on <home>/sweep.lock without
waiting, and a sweep that cannot take it gives ANOTHER_SWEEP in its summary
and touches nothing. The lock uses fcntl, which macOS and Linux have.
"""
import fcntl
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Sequence, Set, Tuple

from audit_layer.capture import (
    ADAPTERS,
    SessionRef,
    SubagentsNotCaptured,
    Summary,
    _origin,
    adapter,
    capture_session,
)
from audit_layer.queries import current_session, session_events
from audit_layer.store import Store, current
from audit_layer.stores.working import snapshot_session

LOCK = "sweep.lock"

ANOTHER_SWEEP = "another sweep is running"

# The start of the reason given for a session whose working files could not
# be snapshotted. Such a session was captured and is counted as captured, so
# the sweep command tells it apart from a session that could not be captured.
NOT_SNAPSHOTTED = "its working files could not be snapshotted"


class SweepSummary(NamedTuple):
    """What one sweep did, counted by session."""

    # Sessions the sweep stored something new for.
    captured: int
    # Sessions whose stored transcript is whole, so nothing new was stored.
    unchanged: int
    # Sessions run in an excluded folder, so nothing was stored.
    excluded: int
    # Sessions whose working folder could not be found, so nothing was stored.
    folder_unknown: int
    # Each session that could not be captured, as (session id, reason), and
    # each captured session whose working files could not be snapshotted,
    # whose reason starts with NOT_SNAPSHOTTED. The reason names no path.
    failed: Tuple[Tuple[str, str], ...]
    # ANOTHER_SWEEP when another sweep held the lock, so nothing was done.
    refused: Optional[str] = None


class _Tally:
    """The counts a sweep adds up as it goes."""

    def __init__(self):
        self.captured = 0
        self.unchanged = 0
        self.excluded = 0
        self.folder_unknown = 0
        self.failed = []  # type: List[Tuple[str, str]]

    def add(self, summary: Summary) -> None:
        """Count one capture's summary and each subagent summary in it."""
        if summary.folder_unknown:
            self.folder_unknown += 1
        elif summary.excluded:
            self.excluded += 1
        elif summary.sessions or summary.events or summary.transcripts:
            self.captured += 1
        else:
            self.unchanged += 1
        for subagent in summary.subagents:
            self.add(subagent)

    def done(self) -> SweepSummary:
        return SweepSummary(
            self.captured, self.unchanged, self.excluded, self.folder_unknown, tuple(self.failed)
        )


def sweep(
    store: Store,
    settings,
    home,
    harnesses: Optional[Sequence[str]] = None,
    roots: Optional[Dict[str, str]] = None,
    locations: Optional[Sequence[str]] = None,
) -> SweepSummary:
    """Capture every session of each harness that the store does not yet hold whole.

    harnesses names the harnesses to sweep, every registered one by default.
    roots gives a harness's root in place of its adapter's default_root().
    locations, when given, are swept in place of the listing, and then exactly
    one harness must be named. settings are the ones read from the audit
    home's settings.yaml, and home is the audit home, which holds the lock.
    """
    names = sorted(ADAPTERS) if harnesses is None else list(harnesses)
    for name in names:
        adapter(name)
    if locations is not None and len(names) != 1:
        raise ValueError("give exactly one harness to sweep the given locations")
    roots = dict(roots or {})

    lock = open(str(Path(home) / LOCK), "a")
    try:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return SweepSummary(0, 0, 0, 0, (), ANOTHER_SWEEP)
        try:
            tally = _Tally()
            if locations is not None:
                for location in locations:
                    _sweep_one(store, names[0], str(location), _given_name(location), settings, tally)
            else:
                for name in names:
                    _sweep_harness(store, name, roots, settings, tally)
            return tally.done()
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    finally:
        lock.close()


def _sweep_harness(store: Store, harness: str, roots: Dict[str, str], settings, tally: _Tally) -> None:
    """Sweep every session the harness lists under its root."""
    reader = adapter(harness)
    root = roots[harness] if harness in roots else str(reader.default_root())
    try:
        refs = _listed(reader, root)
    except (OSError, ValueError) as error:
        tally.failed.append((f"the {harness} listing", _scrubbed(error, root, root)))
        return
    handled = set()  # type: Set[str]
    for ref in refs:
        if ref.location in handled or ref.harness_session_id in handled:
            continue
        if _unchanged(store, harness, ref):
            tally.unchanged += 1
            continue
        handled.update(_sweep_one(store, harness, ref.location, ref.harness_session_id, settings, tally, root))


def _listed(reader, root: str) -> List[SessionRef]:
    """The sessions the adapter lists under root."""
    return list(reader.list_sessions(root))


def _sweep_one(
    store: Store,
    harness: str,
    location: str,
    name: str,
    settings,
    tally: _Tally,
    root: str = "",
) -> Set[str]:
    """Capture one session and count it, giving back the locations and ids it handled.

    A subagent conversation captured with its main session file is handled,
    so the listing does not reach it again.
    """
    handled = {location}
    try:
        summary = capture_session(store, harness, location, settings)
    except SubagentsNotCaptured as error:
        tally.add(error.summary)
        _snapshot(store, harness, error.summary, tally)
        handled.update(_locations(error.summary))
        for failed, reason in zip(error.failed, error.reasons):
            tally.failed.append((failed, reason))
            handled.add(failed)
        return handled
    except Exception as error:  # noqa: BLE001, one session never stops the sweep
        tally.failed.append((name, _scrubbed(error, location, root)))
        return handled
    tally.add(summary)
    _snapshot(store, harness, summary, tally)
    handled.update(_locations(summary))
    return handled


def _snapshot(store: Store, harness: str, summary: Summary, tally: _Tally) -> None:
    """Snapshot the working files of the session the summary names, and of each subagent in it.

    A session run in an excluded folder or in a folder not found stored no
    row, so it has none to snapshot (stores/working.py). A snapshot that
    fails is named among the failures by the session's id, with a reason that
    starts with NOT_SNAPSHOTTED, gives the kind of error, and names no path,
    since a working file's path spells out the folder the session ran in. It
    does not stop the sweep, and the session stays counted as captured.
    """
    if summary.session_id and not summary.excluded and not summary.folder_unknown:
        try:
            row = current_session(store, harness, summary.session_id)
            if row is not None:
                snapshot_session(store, row, session_events(store, row))
        except Exception as error:  # noqa: BLE001, one session never stops the sweep
            tally.failed.append(
                (
                    summary.session_id,
                    f"{NOT_SNAPSHOTTED}, {type(error).__name__}",
                )
            )
    for subagent in summary.subagents:
        _snapshot(store, harness, subagent, tally)


def _locations(summary: Summary) -> Set[str]:
    """The locations of the subagent conversations captured with a session."""
    found = set()
    for subagent in summary.subagents:
        found.add(subagent.path)
        found.update(_locations(subagent))
    return found


def _unchanged(store: Store, harness: str, ref: SessionRef) -> bool:
    """Whether the session's size equals the byte size of its latest stored transcript."""
    rows = current(store, "transcripts", session=ref.harness_session_id, origin=_origin(harness))
    return bool(rows) and rows[-1]["byte_size"] == ref.size


def _given_name(location) -> str:
    """The session id a given location's failure is reported under, which names no folder.

    A Forge location ends in #<conversation id>, and a Claude Code session
    file is named <session id>.jsonl, so the id is read from the location's
    last part.
    """
    name = Path(str(location)).name
    if "#" in name:
        return name.rpartition("#")[2]
    if name.endswith(".jsonl"):
        return name[: -len(".jsonl")]
    return name


def _scrubbed(error: BaseException, location: str, root: str) -> str:
    """The error's text with the session's location and the harness's root taken out.

    Each is taken out as given and as Path writes it, since an adapter that
    names the file through Path drops a doubled slash or a ./ in it.
    """
    text = str(error) or type(error).__name__
    paths = set()
    for given in (location, location.rpartition("#")[0], root):
        if given:
            paths.update({given, str(Path(given))})
    for path in sorted(paths, key=len, reverse=True):
        text = text.replace(path, "its file")
    return text
