"""The check for missed or interrupted captures, which lists what the sweep has yet to do.

Appendix Table A5 names a check for missed or interrupted captures, and
appendix A2.4 "Capture" sweeps each harness's session files. Spec 0.11
"Audit" says sessions do not reliably close, so a capture can miss a session
or stop partway. The check gives four lists and changes nothing, and the
sweep is the remedy (plan choice 8).

- not captured. Each session a harness keeps that has no session row, whose
  working folder is known and not excluded.
- working folder unknown. Each session with no session row that the adapter
  cannot place, so capture would store nothing of it (plan choice 3). A
  session file that cannot be read is listed here too, since its folder
  cannot be found.
- changed since capture. Each stored session whose size differs from the byte
  size of its latest stored transcript, a session still running or a capture
  that stopped.
- stored file missing or altered. Each session with a transcript row whose
  file is gone from the file store or no longer matches its sha256.

The check reaches a harness only through capture's registry of adapters (plan
choice 2). It reads the store and the harnesses' sessions, takes no lock, and
writes no row and no file. Every list names sessions by id and never by a
path, since a harness folder's name can spell out the folder a session ran in.
"""
import hashlib
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

from audit_layer.capture import ADAPTERS, SessionRef, _origin, adapter
from audit_layer.settings import excluded
from audit_layer.store import Store, current


class CheckReport(NamedTuple):
    """The four lists, each a tuple of session ids in the order found."""

    not_captured: Tuple[str, ...]
    working_folder_unknown: Tuple[str, ...]
    changed_since_capture: Tuple[str, ...]
    stored_file_missing_or_altered: Tuple[str, ...]


def check_captures(
    store: Store,
    settings,
    harnesses: Optional[Sequence[str]] = None,
    roots: Optional[Dict[str, str]] = None,
) -> CheckReport:
    """The four lists for each harness, every registered one unless named.

    roots gives a harness's root in place of its adapter's default_root().
    settings are the ones read from the audit home's settings.yaml. A harness
    whose sessions cannot be listed is refused with a ValueError naming the
    harness and no path.
    """
    names = sorted(ADAPTERS) if harnesses is None else list(harnesses)
    for name in names:
        adapter(name)
    roots = dict(roots or {})

    not_captured = []  # type: List[str]
    unknown = []  # type: List[str]
    changed = []  # type: List[str]
    for name in names:
        reader = adapter(name)
        root = roots[name] if name in roots else str(reader.default_root())
        try:
            refs = list(reader.list_sessions(root))
        except (OSError, ValueError) as error:
            raise ValueError(f"could not list the {name} sessions") from error
        for ref in refs:
            _place(store, settings, name, reader, ref, not_captured, unknown, changed)

    return CheckReport(
        tuple(not_captured),
        tuple(unknown),
        tuple(changed),
        tuple(_stored_files(store, names)),
    )


def _place(
    store: Store,
    settings,
    harness: str,
    reader,
    ref: SessionRef,
    not_captured: List[str],
    unknown: List[str],
    changed: List[str],
) -> None:
    """Put one listed session in the list it belongs to, if any."""
    session_id = ref.harness_session_id
    if not _stored(store, harness, session_id):
        try:
            session = reader.read_session(ref.location)
        except (OSError, ValueError):
            unknown.append(session_id)
            return
        if not session.cwd:
            unknown.append(session_id)
            return
        if excluded(session.cwd, settings):
            return
        if not _stored(store, harness, session.session_id):
            not_captured.append(session_id)
            return
        # The listing named the session under another id than its records
        # give, and the store holds it under the records' id.
        session_id = session.session_id
    if not _whole(store, harness, session_id, ref.size):
        changed.append(session_id)


def _stored(store: Store, harness: str, session_id: str) -> bool:
    """Whether the store holds a current session row for the session."""
    return bool(current(store, "sessions", harness=harness, harness_session_id=session_id))


def _whole(store: Store, harness: str, session_id: str, size: int) -> bool:
    """Whether the session's size equals the byte size of its latest stored transcript."""
    rows = current(store, "transcripts", session=session_id, origin=_origin(harness))
    return bool(rows) and rows[-1]["byte_size"] == size


def _stored_files(store: Store, harnesses: Sequence[str]) -> List[str]:
    """Each session, once, with a transcript row whose file is gone or no longer matches."""
    origins = {_origin(name) for name in harnesses}
    found = []  # type: List[str]
    for row in current(store, "transcripts"):
        if row["origin"] not in origins or row["session"] in found:
            continue
        path = store.files / row["file_sha256"]
        try:
            data = path.read_bytes()
        except OSError:
            found.append(row["session"])
            continue
        if hashlib.sha256(data).hexdigest() != row["file_sha256"]:
            found.append(row["session"])
    return found
