"""Tests for subagents in Claude Code sessions (Track E, step E10, an appendix part).

Appendix A2.6 paragraph 1 has the observability layer add the work of
subagents, and A2.1 has the scholar watch AI work including the work of
subagents, serving the proposal's view of what the harness reads and calls
(Approach paragraph 4). A subagent is an invoke_agent span under the tool
call that started it (plan choice 6), and records carrying agentId form
subagents, so subagent files join their parent's trace however they are
stored (plan choice 7). The transcripts are Track E's synthetic session and
its synthetic subagent file, with folder marks replaced by temporary
folders. Nothing here calls a model or the network, and views are built only
in temporary folders. Run from the repository root with
python3 -m pytest -q observability/tests.
"""
import json
from pathlib import Path

from observability import build as bd
from observability import conventions as cv
from observability import spans as sp
from observability.adapters import claude_code as cc
from observability.tests.audit_fixture import AuditHome

TESTS = Path(__file__).resolve().parent
FIXTURES = TESTS / "fixtures" / "claude_code"
MAIN = FIXTURES / "obs_session.jsonl"
SUBAGENT = FIXTURES / "obs_session" / "subagents" / "agent-a1.jsonl"
FIXTURE_ID = "7c2e9d10-4b1a-4f3e-9a55-0e6b3c8d2f41"
KB = TESTS / "fixtures" / "kb"
AGENT_CALL = "toolu_obs_06_agent"
SUB_READ = "toolu_obs_a1_01_read"
SUB_SEARCH = "toolu_obs_a1_02_search"
SUB_TURNS = ["msg_obs_a1_01", "msg_obs_a1_02", "msg_obs_a1_03"]
PREFIX = "window.OBS = "


def _text(path, project):
    text = path.read_text(encoding="utf-8")
    return text.replace("{{PROJECT}}", str(project)).replace("{{KB}}", str(KB)).encode("utf-8")


def _project(tmp_path):
    return tmp_path / "work" / "obs_project"


def _spans(transcripts):
    records, _ = cc.read_records(transcripts)
    found = cc.traces(records, {})
    assert len(found) == 1
    return found[0][1]


def _both(tmp_path):
    project = _project(tmp_path)
    return _spans([_text(MAIN, project), _text(SUBAGENT, project)])


def _by_call(spans, call_id):
    [span] = [span for span in spans if span["attributes"].get(cv.TOOL_CALL_ID) == call_id]
    return span


def _agent(spans, agent_id):
    [span] = [span for span in spans
              if span["attributes"].get(cv.OPERATION_NAME) == cv.INVOKE_AGENT
              and span["attributes"].get(cv.AGENT_ID) == agent_id]
    return span


def _turn(spans, response_id):
    [span] = [span for span in spans
              if span["attributes"].get(cv.OPERATION_NAME) == cv.CHAT
              and span["attributes"].get(cv.RESPONSE_ID) == response_id]
    return span


def _subagent_spans(spans, agent_span):
    """Every span at or below agent_span."""
    below = {agent_span["span_id"]}
    grew = True
    while grew:
        grew = False
        for span in spans:
            if span["parent_span_id"] in below and span["span_id"] not in below:
                below.add(span["span_id"])
                grew = True
    return [span for span in spans if span["span_id"] in below]


# The subagent's own span


def test_the_subagent_span_sits_under_the_agent_call(tmp_path):
    spans = _both(tmp_path)
    trace_id = spans[0]["trace_id"]
    call = _by_call(spans, AGENT_CALL)
    agent = _agent(spans, "a1")
    assert agent["span_id"] == sp.span_id_for(trace_id, "agent:a1")
    assert agent["parent_span_id"] == call["span_id"]
    assert agent["name"] == "invoke_agent general-purpose"
    assert agent["kind"] == cv.SPAN_KIND_INTERNAL
    assert agent["start_ns"] == sp.time_ns("2026-10-22T09:00:18.120Z")
    assert agent["end_ns"] == sp.time_ns("2026-10-22T09:00:30.980Z")
    assert agent["attributes"] == {
        cv.OPERATION_NAME: cv.INVOKE_AGENT,
        cv.AGENT_ID: "a1",
        cv.AGENT_NAME: "general-purpose",
        cv.AGENT_DESCRIPTION: "Compare the procedure with the manuscript",
    }


def test_the_agent_call_carries_the_transfer_attributes(tmp_path):
    call = _by_call(_both(tmp_path), AGENT_CALL)
    assert call["attributes"][cv.TRANSFER_TARGET_NAME] == "general-purpose"
    assert call["attributes"][cv.TRANSFER_MODE] == "return_to_caller"


def test_the_subagent_read_search_and_turns_sit_under_it(tmp_path):
    project = _project(tmp_path)
    spans = _both(tmp_path)
    agent = _agent(spans, "a1")
    read = _by_call(spans, SUB_READ)
    search = _by_call(spans, SUB_SEARCH)
    assert read["parent_span_id"] == agent["span_id"]
    assert search["parent_span_id"] == agent["span_id"]
    assert read["attributes"][cv.FILE_PATH] == str(project / "manuscript.md")
    assert read["attributes"][cv.AUDIT_ROLE] == "read"
    assert search["attributes"][cv.TOOL_TYPE] == "extension"
    assert search["attributes"][cv.TOOL_CALL_RESULT].startswith(
        "1. verification-references-procedure")
    turns = [_turn(spans, key) for key in SUB_TURNS]
    assert all(turn["parent_span_id"] == agent["span_id"] for turn in turns)
    first = turns[0]
    prompt = first["attributes"][cv.INPUT_MESSAGES][0]["parts"][0]["content"]
    assert prompt.startswith("Read the procedure and the manuscript")
    [output] = first["attributes"][cv.OUTPUT_MESSAGES]
    assert output["parts"][0]["type"] == "reasoning"
    assert output["parts"][0]["content"].startswith("I should read the manuscript first")
    assert first["start_ns"] == sp.time_ns("2026-10-22T09:00:18.120Z")


def test_the_main_agent_spans_stay_as_they_were(tmp_path):
    project = _project(tmp_path)
    alone = _spans([_text(MAIN, project)])
    both = _both(tmp_path)
    agent = _agent(both, "a1")
    sub_ids = {span["span_id"] for span in _subagent_spans(both, agent)}
    main = [json.loads(json.dumps(span)) for span in both if span["span_id"] not in sub_ids]
    for span in main:
        span["attributes"].pop(cv.TRANSFER_TARGET_NAME, None)
        span["attributes"].pop(cv.TRANSFER_MODE, None)
    assert main == alone
    assert len(sub_ids) == 1 + 2 + len(SUB_TURNS)


def test_the_two_files_in_either_order_give_the_same_spans(tmp_path):
    project = _project(tmp_path)
    forward = _spans([_text(MAIN, project), _text(SUBAGENT, project)])
    backward = _spans([_text(SUBAGENT, project), _text(MAIN, project)])
    assert forward == backward


def test_without_the_main_file_the_subagent_hangs_from_the_root(tmp_path):
    project = _project(tmp_path)
    spans = _spans([_text(SUBAGENT, project)])
    root = spans[0]
    assert root["parent_span_id"] == ""
    assert root["trace_id"] == sp.trace_id_for("claude_code:" + FIXTURE_ID)
    assert root["attributes"][cv.CONVERSATION_ID] == FIXTURE_ID
    assert root["attributes"][cv.AUDIT_PROJECT] == str(project)
    agent = _agent(spans, "a1")
    assert agent["parent_span_id"] == root["span_id"]
    assert agent["name"] == "invoke_agent"
    assert cv.AGENT_NAME not in agent["attributes"]
    assert _by_call(spans, SUB_READ)["parent_span_id"] == agent["span_id"]
    assert root["start_ns"] <= agent["start_ns"] and agent["end_ns"] <= root["end_ns"]


def test_span_ids_of_the_main_agent_and_the_subagent_never_collide(tmp_path):
    spans = _both(tmp_path)
    ids = [span["span_id"] for span in spans]
    assert len(ids) == len(set(ids))


def test_every_span_passes_both_checks(tmp_path):
    for span in _both(tmp_path):
        assert sp.problems(span) == []
        assert cv.convention_problems(span) == []


def test_the_spans_survive_the_file_form(tmp_path):
    records, _ = cc.read_records([_text(MAIN, _project(tmp_path)),
                                  _text(SUBAGENT, _project(tmp_path))])
    [(resource, spans)] = cc.traces(records, {})
    path = tmp_path / "trace.json"
    sp.write_trace(path, spans, resource)
    _, back = sp.read_trace(path)
    assert [span["span_id"] for span in back] == [span["span_id"] for span in spans]
    assert [span["parent_span_id"] for span in back] == [
        span["parent_span_id"] for span in spans]


# Inline records


def _line(**fields):
    fields.setdefault("sessionId", "s-sub")
    fields.setdefault("cwd", "/synthetic/project")
    return json.dumps(fields)


def _assistant(uuid, at, parts, message_id, **extra):
    return _line(uuid=uuid, timestamp=at, type="assistant",
                 message={"id": message_id, "model": "test-model", "role": "assistant",
                          "content": parts}, **extra)


def _user(uuid, at, content, **extra):
    return _line(uuid=uuid, timestamp=at, type="user",
                 message={"role": "user", "content": content}, **extra)


def _agent_call(call_id, subagent_type="general-purpose"):
    arguments = {"description": "a synthetic task", "prompt": "do it"}
    if subagent_type is not None:
        arguments["subagent_type"] = subagent_type
    return {"type": "tool_use", "id": call_id, "name": "Agent", "input": arguments}


def _inline(lines):
    records, _ = cc.read_records([("\n".join(lines) + "\n").encode("utf-8")])
    [(_, spans)] = cc.traces(records, {})
    return spans


def test_a_subagent_that_starts_another_follows_the_same_rule():
    spans = _inline([
        _user("u1", "2026-10-22T09:00:01Z", "go"),
        _assistant("m1", "2026-10-22T09:00:02Z", [_agent_call("t1", "planner")], "msg-1"),
        _user("s1-1", "2026-10-22T09:00:03Z", "plan it", agentId="s1"),
        _assistant("s1-2", "2026-10-22T09:00:04Z", [_agent_call("t2", "reader")], "msg-s1",
                   agentId="s1"),
        _user("s2-1", "2026-10-22T09:00:05Z", "read it", agentId="s2"),
        _assistant("s2-2", "2026-10-22T09:00:06Z",
                   [{"type": "tool_use", "id": "t3", "name": "Read",
                     "input": {"file_path": "/synthetic/project/a.md"}}], "msg-s2",
                   agentId="s2"),
        _user("s2-3", "2026-10-22T09:00:07Z",
              [{"type": "tool_result", "tool_use_id": "t3", "content": "a"}], agentId="s2"),
        _user("s1-3", "2026-10-22T09:00:08Z",
              [{"type": "tool_result", "tool_use_id": "t2", "content": "read"}],
              agentId="s1", toolUseResult={"agentId": "s2"}),
        _user("u2", "2026-10-22T09:00:09Z",
              [{"type": "tool_result", "tool_use_id": "t1", "content": "planned"}],
              toolUseResult={"agentId": "s1"}),
    ])
    root = spans[0]
    first = _agent(spans, "s1")
    second = _agent(spans, "s2")
    call_one = _by_call(spans, "t1")
    call_two = _by_call(spans, "t2")
    assert call_one["parent_span_id"] == root["span_id"]
    assert first["parent_span_id"] == call_one["span_id"]
    assert call_two["parent_span_id"] == first["span_id"]
    assert second["parent_span_id"] == call_two["span_id"]
    assert _by_call(spans, "t3")["parent_span_id"] == second["span_id"]
    assert first["name"] == "invoke_agent planner"
    assert second["name"] == "invoke_agent reader"
    assert call_two["attributes"][cv.TRANSFER_TARGET_NAME] == "reader"
    rows = bd.span_rows(spans)
    agents = {row["span_id"]: row["agent"] for row in rows}
    assert agents[_by_call(spans, "t3")["span_id"]] == "s2"
    assert agents[call_two["span_id"]] == "s1"
    assert agents[call_one["span_id"]] == "main"


def test_a_subagent_of_unknown_type_is_named_invoke_agent():
    spans = _inline([
        _user("u1", "2026-10-22T09:00:01Z", "go"),
        _assistant("m1", "2026-10-22T09:00:02Z", [_agent_call("t1", None)], "msg-1"),
        _user("s1-1", "2026-10-22T09:00:03Z", "do it", agentId="s1"),
        _user("u2", "2026-10-22T09:00:04Z",
              [{"type": "tool_result", "tool_use_id": "t1", "content": "done"}],
              toolUseResult={"agentId": "s1"}),
    ])
    agent = _agent(spans, "s1")
    call = _by_call(spans, "t1")
    assert agent["name"] == "invoke_agent"
    assert agent["parent_span_id"] == call["span_id"]
    assert agent["attributes"][cv.AGENT_DESCRIPTION] == "a synthetic task"
    assert cv.AGENT_NAME not in agent["attributes"]
    assert call["attributes"][cv.TRANSFER_MODE] == "return_to_caller"
    assert cv.TRANSFER_TARGET_NAME not in call["attributes"]
    for span in spans:
        assert cv.convention_problems(span) == []


def test_ids_the_subagent_shares_with_the_main_agent_give_distinct_spans():
    read = {"type": "tool_use", "id": "t-same", "name": "Read",
            "input": {"file_path": "/synthetic/project/a.md"}}
    spans = _inline([
        _user("u1", "2026-10-22T09:00:01Z", "go"),
        _assistant("m1", "2026-10-22T09:00:02Z", [read], "msg-same"),
        _user("u2", "2026-10-22T09:00:03Z",
              [{"type": "tool_result", "tool_use_id": "t-same", "content": "a"}]),
        _user("s1-1", "2026-10-22T09:00:04Z", "do it", agentId="s1"),
        _assistant("s1-2", "2026-10-22T09:00:05Z", [read], "msg-same", agentId="s1"),
        _user("s1-3", "2026-10-22T09:00:06Z",
              [{"type": "tool_result", "tool_use_id": "t-same", "content": "a"}],
              agentId="s1"),
    ])
    ids = [span["span_id"] for span in spans]
    assert len(ids) == len(set(ids))
    agent = _agent(spans, "s1")
    reads = [span for span in spans if span["attributes"].get(cv.TOOL_CALL_ID) == "t-same"]
    assert sorted(span["parent_span_id"] for span in reads) == sorted(
        [spans[0]["span_id"], agent["span_id"]])


def test_a_subagent_named_as_its_own_caller_hangs_from_the_root():
    spans = _inline([
        _user("u1", "2026-10-22T09:00:01Z", "go"),
        _user("s1-1", "2026-10-22T09:00:02Z", "do it", agentId="s1"),
        _assistant("s1-2", "2026-10-22T09:00:03Z", [_agent_call("t1")], "msg-s1",
                   agentId="s1"),
        _user("s1-3", "2026-10-22T09:00:04Z",
              [{"type": "tool_result", "tool_use_id": "t1", "content": "done"}],
              agentId="s1", toolUseResult={"agentId": "s1"}),
    ])
    agent = _agent(spans, "s1")
    assert agent["parent_span_id"] == spans[0]["span_id"]
    assert len(bd.span_rows(spans)) == len(spans)


# In the view


def test_the_view_names_the_subagent_on_its_file_and_retrieval_rows(tmp_path):
    project = _project(tmp_path)
    project.mkdir(parents=True)
    audit = AuditHome(tmp_path / "audit_home")
    row = audit.add_session(FIXTURE_ID, project, started_at="2026-10-22T09:00:01.000Z",
                            ended_at="2026-10-22T09:01:04.622Z")
    audit.add_transcript(row, _text(MAIN, project))
    audit.add_transcript(row, _text(SUBAGENT, project))
    out = tmp_path / "view"
    summary = bd.build_view(audit.home, out, kb_dirs=(str(KB),))
    assert summary["traces"] == 1
    text = (out / "data.js").read_text(encoding="utf-8")
    data = json.loads(text[len(PREFIX):].rstrip()[:-1])
    [trace] = data["traces"]
    assert trace["subagents"] == 1
    by_span = {}
    for item in data["spans"][trace["trace_id"]]:
        by_span[item["span_id"]] = item
    trace_id = trace["trace_id"]
    files = {(item["tool"], item["path"], item["agent"]) for item in data["files"]}
    assert ("Read", str(project / "manuscript.md"), "a1") in files
    assert ("Read", str(project / "manuscript.md"), "main") in files
    reads = [(item["tool"], item["agent"], item["query"]) for item in data["kb_reads"]]
    assert ("mcp__pipeline-kb__search_kb", "a1",
            "quoted claims checked against sources") in reads
    assert ("mcp__pipeline-kb__search_kb", "main", "checking references") in reads
    agent_row = by_span[sp.span_id_for(trace_id, "agent:a1")]
    assert agent_row["category"] == "agent"
    assert agent_row["agent"] == "a1"
    assert agent_row["depth"] == 2
    _, spans = sp.read_trace(out / "traces" / (trace_id + ".json"))
    for span in spans:
        assert sp.problems(span) == []
        assert cv.convention_problems(span) == []
