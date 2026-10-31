"""The events adapter, which shows a session of any harness from the audit events table.

Appendix A2.6 paragraph 2 asks for a view that does not depend on any one
harness, Figure A1 names any harness, and proposal Overview paragraph 2 lets
any harness fill the harness slot. A harness without a transcript adapter is
shown from the audit layer's events, with verbs, kinds, objects, and file
roles in Table A4's words but no results or reasoning (plan choice 5). This
is how ForgeCode, the fallback harness, appears until a ForgeCode transcript
adapter is written.

The session is an invoke_agent span with one span for each current event
beneath it. The events table keeps the order of events and not their times,
so every event span starts and ends at the session's start.
"""
from typing import Dict, List, Tuple

from observability import conventions as cv
from observability import spans as sp

ROOT_KEY = "root"

# How much of an event's object its span name keeps, from the end.
NAME_OBJECT_CHARS = 60


def trace(session, events) -> Tuple[Dict, List[Dict]]:
    """One session of the record and its current events as (resource, spans).

    session is a row from record.sessions, and events the rows from
    record.events, by ordinal.
    """
    harness = _text(session.get("harness"))
    session_id = _text(session.get("harness_session_id"))
    trace_id = sp.trace_id_for(harness + ":" + session_id)
    start = _time(session.get("started_at"))
    end = _time(session.get("ended_at"))
    if start is None:
        start = end if end is not None else 0
    if end is None or end < start:
        end = start
    root = sp.new_span(trace_id, ROOT_KEY, cv.INVOKE_AGENT + " " + harness,
                       cv.SPAN_KIND_INTERNAL, start, end, attributes={
                           cv.OPERATION_NAME: cv.INVOKE_AGENT,
                           cv.AGENT_NAME: harness,
                           cv.CONVERSATION_ID: session_id,
                           cv.AUDIT_HARNESS: harness,
                           cv.AUDIT_PROJECT: _text(session.get("project")),
                       })
    spans = [root]
    used = set()
    for event in events:
        # Each event is keyed by its ordinal. Should two current events share
        # one, the later gets a numbered key, so span ids never collide.
        key = _text(event.get("ordinal"))
        number = 1
        while key in used or key == ROOT_KEY:
            number += 1
            key = "%s#%d" % (_text(event.get("ordinal")), number)
        used.add(key)
        spans.append(_event_span(trace_id, root["span_id"], start, event, key))
    return {cv.SERVICE_NAME: harness}, spans


def _event_span(trace_id, root_id, at, event, key):
    verb = _text(event.get("verb"))
    obj = _text(event.get("object"))
    role = _text(event.get("role"))
    ordinal = event.get("ordinal")
    name = (verb + " " + obj[-NAME_OBJECT_CHARS:]).strip() or "event"
    attributes = {
        cv.AUDIT_VERB: verb,
        cv.AUDIT_KIND: _text(event.get("kind")),
        cv.AUDIT_OBJECT: obj,
        cv.AUDIT_RATIONALE: _text(event.get("rationale")),
        cv.AUDIT_ORDINAL: ordinal if isinstance(ordinal, int) else _text(ordinal),
        cv.AUDIT_ROLE: role,
    }
    if role:
        attributes[cv.FILE_PATH] = obj
    return sp.new_span(trace_id, key, name, cv.SPAN_KIND_INTERNAL, at, at,
                       parent_span_id=root_id, attributes=attributes)


def _time(text):
    """Nanoseconds for an ISO time, or None when there is none or it does not parse."""
    if not isinstance(text, str) or not text:
        return None
    try:
        return sp.time_ns(text)
    except ValueError:
        return None


def _text(value):
    return "" if value is None else str(value)
