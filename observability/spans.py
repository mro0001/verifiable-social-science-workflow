"""The span model and its file form, OTLP JSON.

A span is a dict with trace_id, span_id, parent_span_id (empty for a root),
name, kind, start_ns, end_ns, attributes, events (each with name, time_ns, and
attributes), status_code, and status_message. Ids come from sha256 of a
source and a key, so a rebuild gives the same ids. Trace files are OTLP JSON,
OpenTelemetry's own file form, which any OpenTelemetry viewer can open.
"""
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone

from observability import __version__

SCOPE_NAME = "observability"

_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_HEX16 = re.compile(r"^[0-9a-f]{16}$")
_ISO = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})"
    r"(?:\.(\d{1,6}))?"
    r"(Z|[+-]\d{2}:\d{2})$")
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def trace_id_for(source):
    """The first 32 hex characters of the sha256 of source."""
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:32]


def span_id_for(trace_id, key):
    """The first 16 hex characters of the sha256 of trace_id, a slash, and key."""
    return hashlib.sha256((trace_id + "/" + key).encode("utf-8")).hexdigest()[:16]


def new_span(trace_id, key, name, kind, start_ns, end_ns, parent_span_id="", attributes=None):
    """A span whose id comes from its trace and key."""
    return {
        "trace_id": trace_id,
        "span_id": span_id_for(trace_id, key),
        "parent_span_id": parent_span_id,
        "name": name,
        "kind": kind,
        "start_ns": start_ns,
        "end_ns": end_ns,
        "attributes": dict(attributes) if attributes else {},
        "events": [],
        "status_code": 0,
        "status_message": "",
    }


def time_ns(text):
    """Nanoseconds since 1970 for an ISO time ending in Z or an offset.

    The time may carry zero to six fraction digits. Any other form raises
    ValueError.
    """
    found = _ISO.match(text or "")
    if not found:
        raise ValueError("not an ISO time ending in Z or an offset: %r" % (text,))
    year, month, day, hour, minute, second = (int(found.group(i)) for i in range(1, 7))
    fraction = found.group(7) or ""
    zone = found.group(8)
    if zone == "Z":
        offset = timedelta(0)
    else:
        sign = -1 if zone[0] == "-" else 1
        offset = sign * timedelta(hours=int(zone[1:3]), minutes=int(zone[4:6]))
    moment = datetime(year, month, day, hour, minute, second, tzinfo=timezone(offset))
    seconds = (moment - _EPOCH) // timedelta(seconds=1)
    micro = int(fraction.ljust(6, "0")) if fraction else 0
    return seconds * 10 ** 9 + micro * 1000


def problems(span):
    """Name each field of a span that breaks the span model, as a list of sentences."""
    found = []
    trace_id = span.get("trace_id")
    if not isinstance(trace_id, str) or not _HEX32.match(trace_id):
        found.append("trace_id %r is not 32 lowercase hex characters" % (trace_id,))
    span_id = span.get("span_id")
    if not isinstance(span_id, str) or not _HEX16.match(span_id):
        found.append("span_id %r is not 16 lowercase hex characters" % (span_id,))
    parent = span.get("parent_span_id")
    if parent != "" and (not isinstance(parent, str) or not _HEX16.match(parent)):
        found.append("parent_span_id %r is neither empty nor 16 lowercase hex characters"
                     % (parent,))
    if not span.get("name"):
        found.append("name is empty")
    kind = span.get("kind")
    if not isinstance(kind, int) or isinstance(kind, bool) or not 0 <= kind <= 5:
        found.append("kind %r is outside 0 to 5" % (kind,))
    start, end = span.get("start_ns"), span.get("end_ns")
    if isinstance(start, int) and isinstance(end, int) and start > end:
        found.append("start_ns %d is after end_ns %d" % (start, end))
    return found


# Attribute values


def _value(value):
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, str):
        return {"stringValue": value}
    if isinstance(value, dict) or (isinstance(value, (list, tuple))
                                   and any(isinstance(item, dict) for item in value)):
        return {"stringValue": json.dumps(value, sort_keys=True, ensure_ascii=False)}
    if isinstance(value, (list, tuple)):
        return {"arrayValue": {"values": [_value(item) for item in value]}}
    raise TypeError("cannot write an attribute value of type %s" % type(value).__name__)


def _unvalue(value):
    if "boolValue" in value:
        return bool(value["boolValue"])
    if "intValue" in value:
        return int(value["intValue"])
    if "doubleValue" in value:
        return float(value["doubleValue"])
    if "stringValue" in value:
        return value["stringValue"]
    if "arrayValue" in value:
        return [_unvalue(item) for item in value["arrayValue"].get("values", [])]
    raise ValueError("unknown attribute value %r" % (value,))


def _attributes(attributes):
    return [{"key": key, "value": _value(attributes[key])} for key in sorted(attributes)]


def _unattributes(items):
    return {item["key"]: _unvalue(item["value"]) for item in items or []}


# The OTLP JSON form


def to_otlp(spans, resource):
    """The OTLP JSON document for spans under one resource."""
    out = []
    for span in spans:
        item = {
            "traceId": span["trace_id"],
            "spanId": span["span_id"],
            "name": span["name"],
            "kind": span["kind"],
            "startTimeUnixNano": str(span["start_ns"]),
            "endTimeUnixNano": str(span["end_ns"]),
            "attributes": _attributes(span.get("attributes") or {}),
            "events": [{"name": event["name"],
                        "timeUnixNano": str(event["time_ns"]),
                        "attributes": _attributes(event.get("attributes") or {})}
                       for event in span.get("events") or []],
            "status": {"code": span.get("status_code", 0),
                       "message": span.get("status_message", "")},
        }
        if span.get("parent_span_id"):
            item["parentSpanId"] = span["parent_span_id"]
        out.append(item)
    return {"resourceSpans": [{
        "resource": {"attributes": _attributes(resource or {})},
        "scopeSpans": [{
            "scope": {"name": SCOPE_NAME, "version": __version__},
            "spans": out,
        }],
    }]}


def from_otlp(doc):
    """The resource and spans held in an OTLP JSON document, as (resource, spans).

    The resource is the first block's. Spans come from every block in order.
    """
    resource = {}
    spans = []
    for index, block in enumerate(doc.get("resourceSpans") or []):
        if index == 0:
            resource = _unattributes((block.get("resource") or {}).get("attributes"))
        for scope_block in block.get("scopeSpans") or []:
            for item in scope_block.get("spans") or []:
                status = item.get("status") or {}
                spans.append({
                    "trace_id": item["traceId"],
                    "span_id": item["spanId"],
                    "parent_span_id": item.get("parentSpanId", ""),
                    "name": item["name"],
                    "kind": int(item.get("kind", 0)),
                    "start_ns": int(item["startTimeUnixNano"]),
                    "end_ns": int(item["endTimeUnixNano"]),
                    "attributes": _unattributes(item.get("attributes")),
                    "events": [{"name": event["name"],
                                "time_ns": int(event["timeUnixNano"]),
                                "attributes": _unattributes(event.get("attributes"))}
                               for event in item.get("events") or []],
                    "status_code": int(status.get("code", 0)),
                    "status_message": status.get("message", ""),
                })
    return resource, spans


def write_trace(path, spans, resource):
    """Write spans as an OTLP JSON file with sorted keys, so the same spans give the same bytes."""
    text = json.dumps(to_otlp(spans, resource), sort_keys=True, indent=1, ensure_ascii=False)
    with open(str(path), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text + "\n")


def read_trace(path):
    """Read an OTLP JSON file and return (resource, spans)."""
    with open(str(path), encoding="utf-8") as handle:
        return from_otlp(json.load(handle))
