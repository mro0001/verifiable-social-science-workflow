"""The review of the model pass's fields by a person.

Appendix Table A4 and the sentence after it say the model pass's fields stay
marked unreviewed until a person reviews them, Table A5 plans the review
marking, and the sentence after Table A3 says records are never overwritten.
No review field is added (spec 0.11). A row is unreviewed while its current
version's origin is model pass, and a review writes rows that supersede them
with origin person <name>, method review, and the session's id (plan choice
12).

- unreviewed(store) lists each session with a current row the model pass
  wrote, its session row and its decision events.
- review(store, harness_session_id, by, changes, rationales) records one
  person's review of one session, in one transaction.

A session's row is reviewed only while its current version is the model
pass's. Once capture has superseded it because the transcript grew, its four
fields start empty and the session is due for the pass again (plan choice
13), so a review then covers only the decisions still awaiting review and
leaves the session row to the pass.
"""
from typing import Any, Dict, List, NamedTuple, Tuple

from audit_layer.queries import session_events
from audit_layer.store import Store, StoreError, current, supersede_all

# The origin of every row the model pass writes (model_pass.py).
MODEL_PASS = "model pass"

METHOD = "review"
REASON = "reviewed"
REASON_CHANGED = "reviewed with changes"

# The session fields a review may change, the model pass's four.
FIELDS = ("title", "gist", "summary", "keywords")


class ReviewError(ValueError):
    """A review the audit layer refuses, which writes nothing."""


class Pending(NamedTuple):
    """One session with rows awaiting review."""

    # The session's current row, unreviewed when its origin is model pass.
    session: Dict[str, Any]
    # The session's current decision events the model pass wrote, in ordinal order.
    decisions: List[Dict[str, Any]]


class Reviewed(NamedTuple):
    """What one review wrote."""

    session_id: str
    # The rows written, one superseding each model-pass row of the session.
    rows: int
    # What changed, as field names and rationale <ordinal>, in that order.
    changed: Tuple[str, ...]


def unreviewed(store: Store) -> List[Pending]:
    """The sessions with a current row the model pass wrote, in the order their rows were written."""
    found = []
    for row in current(store, "sessions"):
        decisions = _model_decisions(store, row)
        if row["origin"] == MODEL_PASS or decisions:
            found.append(Pending(row, decisions))
    return found


def review(
    store: Store,
    harness_session_id: str,
    by: str,
    changes: Dict[str, Any],
    rationales: Dict[int, str],
) -> Reviewed:
    """Record a person's review of one session and say what it wrote.

    The review writes a row superseding the session's current row, when the
    model pass wrote it, and one superseding each of the session's
    model-pass event rows. changes replace the values of title, gist,
    summary, and keywords, and rationales replace a decision's rationale by
    its ordinal. Each row's reason is reviewed with changes when one of its
    values changed, else reviewed. Every row is written together or not at
    all, and a refused review writes nothing.
    """
    name = (by or "").strip() if isinstance(by, str) else ""
    if not name:
        raise ReviewError("a review needs the name of the person who reviewed")
    rows = current(store, "sessions", harness_session_id=harness_session_id)
    if not rows:
        raise ReviewError(f"there is no session {harness_session_id} in the audit store")
    if len({row["harness"] for row in rows}) > 1:
        raise ReviewError(
            f"two harnesses have a session {harness_session_id}, so it cannot be told apart"
        )
    session_row = rows[-1]
    decisions = _model_decisions(store, session_row)
    session_unreviewed = session_row["origin"] == MODEL_PASS
    if not session_unreviewed and not decisions:
        raise ReviewError(
            f"session {harness_session_id} has nothing from the model pass awaiting review"
        )

    unknown = sorted(set(changes) - set(FIELDS))
    if unknown:
        raise ReviewError(
            f"a review cannot change {', '.join(map(str, unknown))}, only "
            + ", ".join(FIELDS)
        )
    for field, value in changes.items():
        _check_value(field, value)
    if changes and not session_unreviewed:
        raise ReviewError(
            f"session {harness_session_id} has grown since the model pass, so its"
            " fields are empty until python3 -m audit_layer tag fills them again"
        )
    by_ordinal = {event["ordinal"]: event for event in decisions}
    for ordinal, text in rationales.items():
        if ordinal not in by_ordinal:
            raise ReviewError(
                f"ordinal {ordinal} is not one of the decisions of session"
                f" {harness_session_id} awaiting review"
            )
        if not isinstance(text, str):
            raise ReviewError(f"the rationale for ordinal {ordinal} must be text")

    provenance = {"session": harness_session_id, "origin": "person " + name, "method": METHOD}
    writes = []
    changed: List[str] = []
    if session_unreviewed:
        moved = {
            field: value for field, value in changes.items() if session_row[field] != _as_stored(value)
        }
        changed += [field for field in FIELDS if field in moved]
        reason = REASON_CHANGED if moved else REASON
        writes.append(("sessions", session_row["id"], moved, dict(provenance, reason=reason)))
    for event in decisions:
        ordinal = event["ordinal"]
        edit = {}
        if ordinal in rationales and rationales[ordinal] != event["rationale"]:
            edit = {"rationale": rationales[ordinal]}
            changed.append(f"rationale {ordinal}")
        reason = REASON_CHANGED if edit else REASON
        writes.append(("events", event["id"], edit, dict(provenance, reason=reason)))
    try:
        supersede_all(store, writes)
    except StoreError as error:
        raise ReviewError(
            f"the rows of session {harness_session_id} changed while it was reviewed,"
            f" so nothing was written, {error}"
        )
    return Reviewed(harness_session_id, len(writes), tuple(changed))


def _model_decisions(store: Store, session_row: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [event for event in session_events(store, session_row) if event["origin"] == MODEL_PASS]


def _check_value(field: str, value: Any) -> None:
    if field == "keywords":
        if not isinstance(value, (list, tuple)) or not all(isinstance(t, str) for t in value):
            raise ReviewError("keywords must be given as a list of terms")
    elif not isinstance(value, str):
        raise ReviewError(f"{field} must be text")


def _as_stored(value: Any) -> Any:
    return list(value) if isinstance(value, tuple) else value
