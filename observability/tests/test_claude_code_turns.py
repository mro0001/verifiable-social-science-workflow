"""Tests for Claude Code model turns and reasoning (Track E, step E4).

Proposal Approach paragraph 4 and Figure 1 have the observability layer show
the model reasoning behind the harness's choices, and appendix A2.6 paragraph
1 names an AI model's reasoning where the model exposes it. Each model turn is
a chat span under the session's root (plan choice 6), its reasoning is a
reasoning part of its output message (plan choice 8), and it keeps as input
only the typed prompt that started it (plan choice 9). Two synthetic
transcripts are read, the test story's session and Track E's own fixture, with
their folder marks replaced by temporary folders. Nothing here calls a model
or the network. Run from the repository root with
python3 -m pytest -q observability/tests.
"""
import json
from pathlib import Path

from observability import conventions as cv
from observability import spans as sp
from observability.adapters import claude_code as cc

TESTS = Path(__file__).resolve().parent
STORY_SESSION = (TESTS.parents[1] / "examples" / "test_story" / "sessions"
                 / "claude_code" / "story_session.jsonl")
STORY_ID = "5f3c0413-2a7d-4b9e-8c61-a0d4e7b2c913"
FIXTURE = TESTS / "fixtures" / "claude_code" / "obs_session.jsonl"


def _story(project):
    return STORY_SESSION.read_text(encoding="utf-8").replace(
        "{{PROJECT}}", str(project)).encode("utf-8")


def _fixture(tmp_path):
    text = FIXTURE.read_text(encoding="utf-8")
    text = text.replace("{{PROJECT}}", str(tmp_path / "work" / "obs_project"))
    text = text.replace("{{KB}}", str(tmp_path / "kb_entries"))
    return text.encode("utf-8")


def _spans(transcripts):
    records, _ = cc.read_records(transcripts)
    [(_, spans)] = cc.traces(records, {})
    return spans


def _turns(spans):
    return [span for span in spans
            if span["attributes"].get(cv.OPERATION_NAME) == cv.CHAT]


def _turn(spans, response_id):
    [span] = [span for span in _turns(spans)
              if span["attributes"].get(cv.RESPONSE_ID) == response_id]
    return span


def _output(span):
    [message] = span["attributes"][cv.OUTPUT_MESSAGES]
    return message


def _part_types(span):
    return [part["type"] for part in _output(span)["parts"]]


# Track E's fixture


def test_each_message_id_gives_one_turn_in_order(tmp_path):
    spans = _spans([_fixture(tmp_path)])
    turns = _turns(spans)
    assert [span["attributes"][cv.RESPONSE_ID] for span in turns] == [
        "msg_obs_0%d" % number for number in range(1, 9)]
    root = spans[0]
    for span in turns:
        response_id = span["attributes"][cv.RESPONSE_ID]
        assert span["name"] == "chat test-model"
        assert span["kind"] == cv.SPAN_KIND_CLIENT
        assert span["trace_id"] == root["trace_id"]
        assert span["parent_span_id"] == root["span_id"]
        assert span["span_id"] == sp.span_id_for(root["trace_id"], response_id)
        attributes = span["attributes"]
        assert attributes[cv.PROVIDER_NAME] == "anthropic"
        assert attributes[cv.REQUEST_MODEL] == "test-model"
        assert attributes[cv.RESPONSE_MODEL] == "test-model"
        assert _output(span)["role"] == "assistant"


def test_a_turn_runs_from_the_record_before_it_to_its_last_record(tmp_path):
    spans = _spans([_fixture(tmp_path)])
    first = _turn(spans, "msg_obs_01")
    assert first["start_ns"] == sp.time_ns("2026-10-22T09:00:01.000Z")
    assert first["end_ns"] == sp.time_ns("2026-10-22T09:00:04.733Z")
    second = _turn(spans, "msg_obs_02")
    assert second["start_ns"] == sp.time_ns("2026-10-22T09:00:05.020Z")
    assert second["end_ns"] == sp.time_ns("2026-10-22T09:00:07.655Z")
    # The record of an unknown type and the broken line are not kept, so
    # the turn after them starts at the tool result before them.
    sixth = _turn(spans, "msg_obs_06")
    assert sixth["start_ns"] == sp.time_ns("2026-10-22T09:00:15.871Z")
    assert sixth["end_ns"] == sp.time_ns("2026-10-22T09:00:18.040Z")


def test_parts_follow_the_records_order(tmp_path):
    spans = _spans([_fixture(tmp_path)])
    first = _turn(spans, "msg_obs_01")
    assert _output(first)["parts"] == [
        {"type": "reasoning", "content": "The knowledge base should hold a procedure "
                                         "for checking references. I will search it first."},
        {"type": "text", "content": "I'll search the knowledge base for the reference "
                                    "procedure."},
        {"type": "tool_call", "id": "toolu_obs_01_search",
         "name": "mcp__pipeline-kb__search_kb",
         "arguments": {"query": "checking references", "group": "verification",
                       "limit": 5}},
    ]
    assert _part_types(_turn(spans, "msg_obs_03")) == ["text", "tool_call"]
    assert _part_types(_turn(spans, "msg_obs_07")) == ["text"]
    assert _part_types(_turn(spans, "msg_obs_08")) == ["text", "tool_call"]


def test_token_counts_are_the_largest_and_input_sums_both_caches(tmp_path):
    spans = _spans([_fixture(tmp_path)])
    first = _turn(spans, "msg_obs_01")["attributes"]
    assert first[cv.USAGE_INPUT_TOKENS] == 3 + 4200 + 610
    assert first[cv.USAGE_OUTPUT_TOKENS] == 58
    assert first[cv.USAGE_CACHE_READ_INPUT_TOKENS] == 4200
    assert first[cv.USAGE_CACHE_WRITE_INPUT_TOKENS] == 610
    second = _turn(spans, "msg_obs_02")["attributes"]
    assert second[cv.USAGE_INPUT_TOKENS] == 2 + 4810
    assert second[cv.USAGE_OUTPUT_TOKENS] == 41
    assert second[cv.USAGE_CACHE_READ_INPUT_TOKENS] == 4810
    # A cache count of zero is not written.
    assert cv.USAGE_CACHE_WRITE_INPUT_TOKENS not in second


def test_stop_reasons_map_to_finish_reasons(tmp_path):
    spans = _spans([_fixture(tmp_path)])
    # The turn's last record with a stop reason gives it, so the records
    # before it whose stop reason is null do not.
    first = _turn(spans, "msg_obs_01")
    assert first["attributes"][cv.RESPONSE_FINISH_REASONS] == ["tool_call"]
    assert _output(first)["finish_reason"] == "tool_call"
    last_answer = _turn(spans, "msg_obs_07")
    assert last_answer["attributes"][cv.RESPONSE_FINISH_REASONS] == ["stop"]
    assert _output(last_answer)["finish_reason"] == "stop"


def test_reasoning_with_text_empty_reasoning_and_none(tmp_path):
    spans = _spans([_fixture(tmp_path)])
    with_text = [part for part in _output(_turn(spans, "msg_obs_01"))["parts"]
                 if part["type"] == "reasoning"]
    assert with_text == [{"type": "reasoning", "content": "The knowledge base should "
                          "hold a procedure for checking references. I will search "
                          "it first."}]
    empty = _turn(spans, "msg_obs_02")
    assert _output(empty)["parts"][0] == {"type": "reasoning", "content": ""}
    assert _part_types(empty) == ["reasoning", "tool_call"]
    for response_id in ("msg_obs_03", "msg_obs_04", "msg_obs_07", "msg_obs_08"):
        assert "reasoning" not in _part_types(_turn(spans, response_id))


def test_the_first_turn_carries_the_typed_prompt(tmp_path):
    spans = _spans([_fixture(tmp_path)])
    first = _turn(spans, "msg_obs_01")
    assert first["attributes"][cv.INPUT_MESSAGES] == [
        {"role": "user", "parts": [{"type": "text", "content":
            "Find the procedure for checking references in the knowledge base, "
            "read it beside my manuscript, and try a build."}]}]
    # A prompt held as text parts counts as typed too.
    later = _turn(spans, "msg_obs_08")
    assert later["attributes"][cv.INPUT_MESSAGES] == [
        {"role": "user", "parts": [{"type": "text",
                                    "content": "Write that down in a notes file."}]}]


def test_a_turn_after_a_tool_result_carries_no_prompt(tmp_path):
    spans = _spans([_fixture(tmp_path)])
    for number in range(2, 8):
        span = _turn(spans, "msg_obs_0%d" % number)
        assert cv.INPUT_MESSAGES not in span["attributes"]


def test_turns_leave_the_tool_spans_as_they_were(tmp_path):
    spans = _spans([_fixture(tmp_path)])
    tools = [span for span in spans
             if span["attributes"].get(cv.OPERATION_NAME) == cv.EXECUTE_TOOL]
    assert len(tools) == 7
    assert len(spans) == 1 + 7 + 8
    assert all(span["parent_span_id"] == spans[0]["span_id"] for span in spans[1:])
    assert len({span["span_id"] for span in spans}) == len(spans)


# The test story's session


def test_story_session_gives_seven_turns_one_per_assistant_record(tmp_path):
    project = tmp_path / "work" / "story_project"
    spans = _spans([_story(project)])
    turns = _turns(spans)
    records = [json.loads(line) for line in _story(project).decode("utf-8").splitlines()]
    assistants = [record for record in records if record["type"] == "assistant"]
    assert len(turns) == 7 == len(assistants)
    root = spans[0]
    for span, record in zip(turns, assistants):
        assert span["name"] == "chat"
        assert span["kind"] == cv.SPAN_KIND_CLIENT
        assert span["parent_span_id"] == root["span_id"]
        assert span["span_id"] == sp.span_id_for(root["trace_id"], record["uuid"])
        assert span["end_ns"] == sp.time_ns(record["timestamp"])
        attributes = span["attributes"]
        assert attributes[cv.PROVIDER_NAME] == "anthropic"
        for key in (cv.REQUEST_MODEL, cv.RESPONSE_MODEL, cv.RESPONSE_ID,
                    cv.RESPONSE_FINISH_REASONS, cv.USAGE_INPUT_TOKENS,
                    cv.USAGE_OUTPUT_TOKENS):
            assert key not in attributes
        expected = []
        for part in record["message"]["content"]:
            if part["type"] == "text":
                expected.append({"type": "text", "content": part["text"]})
            elif part["type"] == "tool_use":
                expected.append({"type": "tool_call", "id": part["id"],
                                 "name": part["name"], "arguments": part["input"]})
        assert _output(span) == {"role": "assistant", "parts": expected}
    assert turns[0]["attributes"][cv.INPUT_MESSAGES][0]["parts"][0]["content"].startswith(
        "In manuscript.md, after my sentence on fit")
    assert all(cv.INPUT_MESSAGES not in span["attributes"] for span in turns[1:])


def test_every_span_passes_both_checks(tmp_path):
    for transcript in (_fixture(tmp_path), _story(tmp_path / "work" / "story_project")):
        for span in _spans([transcript]):
            assert sp.problems(span) == [], span["name"]
            assert cv.convention_problems(span) == [], span["name"]


def test_turns_survive_the_file_form(tmp_path):
    records, _ = cc.read_records([_fixture(tmp_path)])
    [(resource, spans)] = cc.traces(records, {})
    path = tmp_path / "trace.json"
    sp.write_trace(path, spans, resource)
    _, back = sp.read_trace(path)
    [turn] = [span for span in back
              if span["attributes"].get(cv.RESPONSE_ID) == "msg_obs_01"]
    assert json.loads(turn["attributes"][cv.OUTPUT_MESSAGES])[0]["parts"][0]["type"] == (
        "reasoning")
    assert turn["attributes"][cv.RESPONSE_FINISH_REASONS] == ["tool_call"]
    assert turn["attributes"][cv.USAGE_INPUT_TOKENS] == 4813


# Small cases written here


def _line(**fields):
    record = {"sessionId": "s-1", "cwd": "/synthetic/project"}
    record.update(fields)
    return json.dumps(record)


def _assistant(uuid, at, parts, **message):
    body = {"role": "assistant", "content": parts}
    body.update(message)
    return _line(uuid=uuid, timestamp=at, type="assistant", message=body)


def _user(uuid, at, content, **extra):
    return _line(uuid=uuid, timestamp=at, type="user",
                 message={"role": "user", "content": content}, **extra)


def _inline(lines):
    return _spans(["\n".join(lines) + "\n"])


def test_redacted_thinking_gives_an_empty_reasoning_part():
    spans = _inline([
        _user("u1", "2026-10-22T09:00:01Z", "go"),
        _assistant("a1", "2026-10-22T09:00:02Z",
                   [{"type": "redacted_thinking", "data": "b3BhcXVl"},
                    {"type": "text", "text": "done"}], id="m1", model="test-model",
                   stop_reason="end_turn"),
    ])
    [turn] = _turns(spans)
    assert _output(turn)["parts"] == [{"type": "reasoning", "content": ""},
                                      {"type": "text", "content": "done"}]


def test_a_meta_record_or_a_tool_result_is_not_a_typed_prompt():
    spans = _inline([
        _user("u1", "2026-10-22T09:00:01Z", "a note the harness added", isMeta=True),
        _assistant("a1", "2026-10-22T09:00:02Z", [{"type": "text", "text": "one"}],
                   id="m1", model="test-model"),
        _user("u2", "2026-10-22T09:00:03Z",
              [{"type": "text", "text": "also typed"},
               {"type": "tool_result", "tool_use_id": "t0", "content": "r"}]),
        _assistant("a2", "2026-10-22T09:00:04Z", [{"type": "text", "text": "two"}],
                   id="m2", model="test-model"),
    ])
    for turn in _turns(spans):
        assert cv.INPUT_MESSAGES not in turn["attributes"]


def test_a_turn_with_no_record_before_it_starts_at_its_own_time():
    spans = _inline([
        _assistant("a1", "2026-10-22T09:00:02Z", [{"type": "text", "text": "first"}],
                   id="m1", model="test-model"),
        _assistant("a2", "2026-10-22T09:00:03Z", [{"type": "text", "text": "more"}],
                   id="m1", model="test-model"),
    ])
    [turn] = _turns(spans)
    assert turn["start_ns"] == sp.time_ns("2026-10-22T09:00:02Z")
    assert turn["end_ns"] == sp.time_ns("2026-10-22T09:00:03Z")


def test_no_stop_reason_and_no_usage_leave_their_fields_out():
    spans = _inline([
        _user("u1", "2026-10-22T09:00:01Z", "go"),
        _assistant("a1", "2026-10-22T09:00:02Z", [{"type": "text", "text": "partial"}],
                   id="m1", model="test-model", stop_reason=None),
    ])
    [turn] = _turns(spans)
    attributes = turn["attributes"]
    assert cv.RESPONSE_FINISH_REASONS not in attributes
    assert "finish_reason" not in _output(turn)
    for key in (cv.USAGE_INPUT_TOKENS, cv.USAGE_OUTPUT_TOKENS,
                cv.USAGE_CACHE_READ_INPUT_TOKENS, cv.USAGE_CACHE_WRITE_INPUT_TOKENS):
        assert key not in attributes


def test_an_unknown_stop_reason_is_kept_as_given():
    spans = _inline([
        _assistant("a1", "2026-10-22T09:00:02Z", [{"type": "text", "text": "x"}],
                   id="m1", model="test-model", stop_reason="pause_turn"),
    ])
    [turn] = _turns(spans)
    assert turn["attributes"][cv.RESPONSE_FINISH_REASONS] == ["pause_turn"]


def test_long_text_reasoning_and_arguments_are_cut():
    long_text = "y" * (cv.TEXT_CAP + 5)
    spans = _inline([
        _user("u1", "2026-10-22T09:00:01Z", long_text),
        _assistant("a1", "2026-10-22T09:00:02Z",
                   [{"type": "thinking", "thinking": long_text, "signature": "c2ln"},
                    {"type": "text", "text": long_text},
                    {"type": "tool_use", "id": "t1", "name": "Bash",
                     "input": {"command": long_text, "timeout": 5}}],
                   id="m1", model="test-model", stop_reason="tool_use"),
    ])
    [turn] = _turns(spans)
    parts = _output(turn)["parts"]
    assert parts[0]["content"] == cv.cap(long_text)
    assert parts[1]["content"] == cv.cap(long_text)
    assert parts[2]["arguments"] == {"command": cv.cap(long_text), "timeout": 5}
    prompt = turn["attributes"][cv.INPUT_MESSAGES][0]["parts"][0]["content"]
    assert prompt == cv.cap(long_text)


def test_subagent_turns_sit_under_their_own_agent_not_the_root():
    # Step E10 places subagent records under their own invoke_agent span.
    spans = _inline([
        _user("u1", "2026-10-22T09:00:01Z", "go"),
        _assistant("a1", "2026-10-22T09:00:02Z", [{"type": "text", "text": "main"}],
                   id="m1", model="test-model"),
        _line(uuid="s1", timestamp="2026-10-22T09:00:03Z", type="assistant",
              agentId="sub1", isSidechain=True,
              message={"id": "m-sub", "model": "test-model", "role": "assistant",
                       "content": [{"type": "text", "text": "sub"}]}),
    ])
    root = spans[0]
    [agent] = [span for span in spans
               if span["attributes"].get(cv.OPERATION_NAME) == cv.INVOKE_AGENT
               and span["parent_span_id"]]
    assert agent["attributes"][cv.AGENT_ID] == "sub1"
    assert [turn["attributes"][cv.RESPONSE_ID] for turn in _turns(spans)
            if turn["parent_span_id"] == root["span_id"]] == ["m1"]
    assert [turn["attributes"][cv.RESPONSE_ID] for turn in _turns(spans)
            if turn["parent_span_id"] == agent["span_id"]] == ["m-sub"]
