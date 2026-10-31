"""The one event schema, which every harness adapter fills.

Appendix A2.4 "Capture" sweeps each harness's session files through one event
schema with an adapter for each harness, and A2.2 calls these event adapters.
Table A3 gives an event a verb, a kind, an object, and a rationale. Table A4
gives each action a verb from a fixed list and each file touched a role. The
harness, the harness's own session id, and the harness's own id for the
record say where an event came from.
"""
from collections.abc import Mapping
from typing import Any, List, Optional

# The event schema, one name for each field.
FIELDS = (
    # The harness that ran the session, such as claude_code.
    "harness",
    # The harness's own id for the session.
    "harness_session_id",
    # The harness's own id for the record, used only to keep a repeated
    # capture from storing an event twice.
    "source_id",
    # What was done, one of VERBS.
    "verb",
    # One of KINDS.
    "kind",
    # What the event acted on or looked at, such as a file, a search pattern,
    # an address, or a command.
    "object",
    # Why it was done. It may be empty.
    "rationale",
    # The role of the file involved, one of ROLES, or empty when no file is
    # involved.
    "role",
)

VERBS = ("wrote", "edited", "ran", "searched", "verified", "committed")
KINDS = ("action", "decision", "observation", "blocker")
ROLES = ("produced", "edited", "read", "cited")

_LISTS = {"verb": VERBS, "kind": KINDS, "role": ROLES}


def validate(event: Any) -> List[str]:
    """The event's problems, one naming each wrong field, or an empty list.

    Each problem starts with the name of the field it is about. Fields the
    schema lacks are named after the schema's own fields.
    """
    if not isinstance(event, Mapping):
        return ["an event is a mapping from field names to values"]
    problems = []
    for name in FIELDS:
        if name not in event:
            problems.append(f"{name} is missing")
            continue
        problem = _problem(name, event[name])
        if problem is not None:
            problems.append(problem)
    for name in sorted((name for name in event if name not in FIELDS), key=str):
        problems.append(f"{name} is not a field of the event schema")
    return problems


def _problem(name: str, value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return f"{name} must be text"
    if name == "rationale":
        return None
    allowed = _LISTS.get(name)
    if allowed is not None:
        if value in allowed or (name == "role" and value == ""):
            return None
        also = ", or empty" if name == "role" else ""
        return f"{name} {value!r} is not one of {', '.join(allowed)}{also}"
    if not value.strip():
        return f"{name} is empty"
    return None
