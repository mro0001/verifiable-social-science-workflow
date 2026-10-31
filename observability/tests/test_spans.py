"""Tests for the span model and its file form (Track E, step E1).

Appendix A2.6 asks for events that follow OpenTelemetry's conventions for AI
calls, so the view does not depend on any one harness, and Table A7 reads the
record live with events in those conventions. The spans here are written in
the test and hold no real session text. Nothing here calls a model or the
network. Run from the repository root with python3 -m pytest -q observability/tests.
"""
import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from observability import __version__
from observability import conventions as cv
from observability import spans as sp


def _good_span(**changes):
    trace_id = sp.trace_id_for("session-a")
    span = sp.new_span(trace_id, "root", "invoke_agent", cv.SPAN_KIND_INTERNAL, 10, 20)
    span.update(changes)
    return span


# Ids that stay the same across rebuilds


def test_one_key_gives_one_trace_id_and_another_key_another():
    assert sp.trace_id_for("session-a") == sp.trace_id_for("session-a")
    assert sp.trace_id_for("session-a") != sp.trace_id_for("session-b")
    expected = hashlib.sha256("session-a".encode("utf-8")).hexdigest()[:32]
    assert sp.trace_id_for("session-a") == expected


def test_one_key_gives_one_span_id_and_another_key_another():
    trace_id = sp.trace_id_for("session-a")
    assert sp.span_id_for(trace_id, "tool/1") == sp.span_id_for(trace_id, "tool/1")
    assert sp.span_id_for(trace_id, "tool/1") != sp.span_id_for(trace_id, "tool/2")
    other_trace = sp.trace_id_for("session-b")
    assert sp.span_id_for(trace_id, "tool/1") != sp.span_id_for(other_trace, "tool/1")
    expected = hashlib.sha256((trace_id + "/tool/1").encode("utf-8")).hexdigest()[:16]
    assert sp.span_id_for(trace_id, "tool/1") == expected


def test_new_span_holds_every_field():
    trace_id = sp.trace_id_for("session-a")
    span = sp.new_span(trace_id, "turn/1", "chat", cv.SPAN_KIND_CLIENT, 5, 9,
                       parent_span_id=sp.span_id_for(trace_id, "root"),
                       attributes={"gen_ai.operation.name": "chat"})
    assert span == {
        "trace_id": trace_id,
        "span_id": sp.span_id_for(trace_id, "turn/1"),
        "parent_span_id": sp.span_id_for(trace_id, "root"),
        "name": "chat",
        "kind": 3,
        "start_ns": 5,
        "end_ns": 9,
        "attributes": {"gen_ai.operation.name": "chat"},
        "events": [],
        "status_code": 0,
        "status_message": "",
    }
    root = sp.new_span(trace_id, "root", "invoke_agent", cv.SPAN_KIND_INTERNAL, 1, 2)
    assert root["parent_span_id"] == ""
    assert root["attributes"] == {}


# Times


def _epoch_ns(year, month, day, hour, minute, second, micro=0):
    moment = datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
    seconds = (moment - datetime(1970, 1, 1, tzinfo=timezone.utc)) // timedelta(seconds=1)
    return seconds * 10 ** 9 + micro * 1000


def test_time_ns_reads_a_utc_time_with_milliseconds():
    assert sp.time_ns("2026-10-21T14:02:05.112Z") == _epoch_ns(2026, 10, 21, 14, 2, 5, 112000)


def test_time_ns_reads_an_offset_time_with_no_fraction():
    assert sp.time_ns("2026-10-28T20:59:59-07:00") == _epoch_ns(2026, 10, 29, 3, 59, 59)


def test_time_ns_reads_six_fraction_digits():
    assert sp.time_ns("2026-10-21T14:02:05.123456Z") == _epoch_ns(2026, 10, 21, 14, 2, 5, 123456)
    assert sp.time_ns("2026-10-21T14:02:05.1+00:00") == _epoch_ns(2026, 10, 21, 14, 2, 5, 100000)


@pytest.mark.parametrize("text", [
    "2026-10-21T14:02:05",
    "2026-10-21 14:02:05Z",
    "2026-10-21T14:02:05.1234567Z",
    "not a time",
])
def test_time_ns_refuses_other_forms(text):
    with pytest.raises(ValueError):
        sp.time_ns(text)


# Problems with a span's fields


def test_a_well_formed_span_has_no_problems():
    assert sp.problems(_good_span()) == []
    child = _good_span(parent_span_id=sp.span_id_for(sp.trace_id_for("session-a"), "root"))
    assert sp.problems(child) == []


@pytest.mark.parametrize("field, value", [
    ("trace_id", "ABCDEF0123456789ABCDEF0123456789"),
    ("trace_id", "abc"),
    ("span_id", "0123456789abcde"),
    ("span_id", "0123456789abcdeg"),
    ("parent_span_id", "0123"),
    ("name", ""),
    ("kind", 6),
    ("kind", -1),
    ("start_ns", 21),
])
def test_each_wrong_field_is_named(field, value):
    found = sp.problems(_good_span(**{field: value}))
    assert len(found) == 1
    assert field in found[0]


# The OTLP JSON file form


def _sample_spans():
    trace_id = sp.trace_id_for("session-a")
    root = sp.new_span(trace_id, "root", "invoke_agent", cv.SPAN_KIND_INTERNAL,
                       1761055325112000000, 1761055399000000000,
                       attributes={"gen_ai.operation.name": "invoke_agent",
                                   "audit.ordinal": 3,
                                   "audit.harness": "claude_code"})
    tool = sp.new_span(trace_id, "tool/1", "execute_tool Read", cv.SPAN_KIND_INTERNAL,
                       1761055330000000000, 1761055331000000000,
                       parent_span_id=root["span_id"],
                       attributes={"gen_ai.operation.name": "execute_tool",
                                   "gen_ai.tool.name": "Read",
                                   "gen_ai.response.finish_reasons": ["stop", "tool_call"],
                                   "test.flag": True,
                                   "test.score": 0.5,
                                   "gen_ai.tool.call.arguments": {"file_path": "manuscript.md", "limit": 2}})
    tool["events"] = [{"name": "note", "time_ns": 1761055330500000000,
                       "attributes": {"audit.verb": "read"}}]
    tool["status_code"] = cv.STATUS_ERROR
    tool["status_message"] = "tool failed"
    return [root, tool]


RESOURCE = {"service.name": "observability"}


def test_spans_written_and_read_back_are_equal(tmp_path):
    spans = _sample_spans()
    path = tmp_path / "trace.json"
    sp.write_trace(path, spans, RESOURCE)
    resource, back = sp.read_trace(path)
    assert resource == RESOURCE
    expected = json.loads(json.dumps(spans))
    expected[1]["attributes"]["gen_ai.tool.call.arguments"] = json.dumps(
        {"file_path": "manuscript.md", "limit": 2}, sort_keys=True)
    assert back == expected
    assert back[1]["attributes"]["test.flag"] is True
    assert isinstance(back[0]["attributes"]["audit.ordinal"], int)


def test_a_list_holding_dicts_comes_back_as_its_json_string(tmp_path):
    trace_id = sp.trace_id_for("session-a")
    messages = [{"role": "user", "parts": [{"type": "text", "content": "Hello"}]}]
    span = sp.new_span(trace_id, "turn/1", "chat", cv.SPAN_KIND_CLIENT, 1, 2,
                       attributes={"gen_ai.input.messages": messages})
    path = tmp_path / "trace.json"
    sp.write_trace(path, [span], RESOURCE)
    _, back = sp.read_trace(path)
    assert json.loads(back[0]["attributes"]["gen_ai.input.messages"]) == messages


def test_the_file_holds_the_otlp_field_names_and_encodings(tmp_path):
    path = tmp_path / "trace.json"
    sp.write_trace(path, _sample_spans(), RESOURCE)
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert list(doc) == ["resourceSpans"]
    block = doc["resourceSpans"][0]
    assert block["resource"]["attributes"] == [
        {"key": "service.name", "value": {"stringValue": "observability"}}]
    scope_block = block["scopeSpans"][0]
    assert scope_block["scope"] == {"name": "observability", "version": __version__}
    root, tool = scope_block["spans"]

    assert "parentSpanId" not in root
    assert tool["parentSpanId"] == root["spanId"]
    for span in (root, tool):
        assert set(span) >= {"traceId", "spanId", "name", "kind", "startTimeUnixNano",
                             "endTimeUnixNano", "attributes", "events", "status"}
        assert isinstance(span["traceId"], str) and len(span["traceId"]) == 32
        assert isinstance(span["spanId"], str) and len(span["spanId"]) == 16
        assert isinstance(span["kind"], int)
        assert isinstance(span["startTimeUnixNano"], str)
        assert isinstance(span["endTimeUnixNano"], str)
    assert root["startTimeUnixNano"] == "1761055325112000000"
    assert tool["status"] == {"code": 2, "message": "tool failed"}
    assert root["status"] == {"code": 0, "message": ""}

    values = {item["key"]: item["value"] for item in tool["attributes"]}
    assert values["gen_ai.tool.name"] == {"stringValue": "Read"}
    assert values["test.flag"] == {"boolValue": True}
    assert values["test.score"] == {"doubleValue": 0.5}
    assert values["gen_ai.response.finish_reasons"] == {"arrayValue": {"values": [
        {"stringValue": "stop"}, {"stringValue": "tool_call"}]}}
    assert values["gen_ai.tool.call.arguments"] == {
        "stringValue": json.dumps({"file_path": "manuscript.md", "limit": 2}, sort_keys=True)}
    root_values = {item["key"]: item["value"] for item in root["attributes"]}
    assert root_values["audit.ordinal"] == {"intValue": "3"}

    event = tool["events"][0]
    assert event["name"] == "note"
    assert event["timeUnixNano"] == "1761055330500000000"
    assert event["attributes"] == [{"key": "audit.verb", "value": {"stringValue": "read"}}]


def test_to_otlp_and_from_otlp_are_inverse():
    spans = _sample_spans()
    spans[1]["attributes"].pop("gen_ai.tool.call.arguments")
    doc = sp.to_otlp(spans, RESOURCE)
    resource, back = sp.from_otlp(doc)
    assert resource == RESOURCE
    assert back == spans


def test_writing_the_same_spans_twice_gives_the_same_bytes(tmp_path):
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    sp.write_trace(first, _sample_spans(), RESOURCE)
    spans = _sample_spans()
    spans[1]["attributes"] = dict(reversed(list(spans[1]["attributes"].items())))
    sp.write_trace(second, spans, RESOURCE)
    assert first.read_bytes() == second.read_bytes()


# Conventions


def test_semconv_source_names_the_repository_commit_and_date():
    assert "open-telemetry/semantic-conventions-genai" in cv.SEMCONV_SOURCE
    assert "3fe84604a581" in cv.SEMCONV_SOURCE
    assert "2026-10-28" in cv.SEMCONV_SOURCE


def test_kinds_codes_and_operations():
    assert (cv.SPAN_KIND_INTERNAL, cv.SPAN_KIND_CLIENT) == (1, 3)
    assert (cv.STATUS_UNSET, cv.STATUS_OK, cv.STATUS_ERROR) == (0, 1, 2)
    assert cv.OPERATIONS == ("chat", "execute_tool", "invoke_agent", "invoke_workflow")


def test_finish_reasons_map_stop_reasons_and_keep_others():
    assert cv.FINISH_REASONS["end_turn"] == "stop"
    assert cv.FINISH_REASONS["stop_sequence"] == "stop"
    assert cv.FINISH_REASONS["max_tokens"] == "length"
    assert cv.FINISH_REASONS["tool_use"] == "tool_call"
    assert cv.FINISH_REASONS["refusal"] == "content_filter"
    assert cv.FINISH_REASONS["pause_turn"] == "pause_turn"


def test_cap_leaves_short_text_alone():
    assert cv.TEXT_CAP == 8000
    assert cv.cap("short") == "short"
    assert cv.cap("x" * 8000) == "x" * 8000


def test_cap_cuts_long_text_and_names_its_full_length():
    cut = cv.cap("y" * 8001)
    assert cut == "y" * 8000 + " [cut, 8001 characters in all]"


def _op_span(operation, name, **attributes):
    attributes["gen_ai.operation.name"] = operation
    return _good_span(name=name, attributes=attributes)


@pytest.mark.parametrize("span", [
    _op_span("chat", "chat", **{"gen_ai.provider.name": "anthropic"}),
    _op_span("chat", "chat claude-test-1",
             **{"gen_ai.provider.name": "anthropic", "gen_ai.request.model": "claude-test-1"}),
    _op_span("execute_tool", "execute_tool Read", **{"gen_ai.tool.name": "Read"}),
    _op_span("invoke_agent", "invoke_agent"),
    _op_span("invoke_agent", "invoke_agent reviewer", **{"gen_ai.agent.name": "reviewer"}),
    _op_span("invoke_workflow", "invoke_workflow references",
             **{"gen_ai.workflow.name": "references"}),
])
def test_a_well_formed_span_of_each_operation_passes(span):
    assert cv.convention_problems(span) == []


def test_a_chat_span_with_no_provider_is_named():
    found = cv.convention_problems(_op_span("chat", "chat"))
    assert len(found) == 1
    assert "gen_ai.provider.name" in found[0]


def test_an_execute_tool_span_named_for_another_tool_is_named():
    span = _op_span("execute_tool", "execute_tool Write", **{"gen_ai.tool.name": "Read"})
    found = cv.convention_problems(span)
    assert len(found) == 1
    assert "execute_tool Write" in found[0]


@pytest.mark.parametrize("span", [
    _op_span("execute_tool", "execute_tool Read"),
    _op_span("chat", "chat other-model",
             **{"gen_ai.provider.name": "anthropic", "gen_ai.request.model": "claude-test-1"}),
    _op_span("invoke_agent", "invoke_agent other", **{"gen_ai.agent.name": "reviewer"}),
    _op_span("invoke_workflow", "invoke_workflow"),
])
def test_other_broken_spans_are_named(span):
    assert cv.convention_problems(span) != []
