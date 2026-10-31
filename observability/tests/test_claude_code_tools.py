"""Tests for Claude Code tool calls and their results (Track E, step E3).

Proposal Approach paragraph 4 and Figure 1 have the observability layer show
which files the harness reads and which tools it calls, with their results,
and appendix A2.6 paragraph 1 names the tool calls and the tool results.
Claude Code is the first harness. Two synthetic transcripts are read here, the
test story's session and Track E's own fixture, each with its folder marks
replaced by temporary folders, so no test holds a real folder name or machine
path. Nothing here calls a model or the network. Run from the repository root
with python3 -m pytest -q observability/tests.
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
FIXTURE_ID = "7c2e9d10-4b1a-4f3e-9a55-0e6b3c8d2f41"


def _story(project):
    return STORY_SESSION.read_text(encoding="utf-8").replace(
        "{{PROJECT}}", str(project)).encode("utf-8")


def _fixture(project, kb, lines=None):
    text = FIXTURE.read_text(encoding="utf-8")
    text = text.replace("{{PROJECT}}", str(project)).replace("{{KB}}", str(kb))
    if lines is not None:
        text = "".join(text.splitlines(True)[:lines])
    return text.encode("utf-8")


def _folders(tmp_path):
    return tmp_path / "work" / "obs_project", tmp_path / "kb_entries"


def _one_trace(transcripts, meta=None):
    records, notes = cc.read_records(transcripts)
    found = cc.traces(records, meta or {})
    assert len(found) == 1
    resource, spans = found[0]
    return resource, spans, notes


def _tools(spans):
    return [span for span in spans
            if span["attributes"].get(cv.OPERATION_NAME) == cv.EXECUTE_TOOL]


def _by_call(spans, call_id):
    [span] = [span for span in spans
              if span["attributes"].get(cv.TOOL_CALL_ID) == call_id]
    return span


def _story_records(project):
    return [json.loads(line) for line in _story(project).decode("utf-8").splitlines()]


# The test story's session


def test_story_session_gives_one_trace_with_its_root(tmp_path):
    project = tmp_path / "work" / "story_project"
    resource, spans, notes = _one_trace([_story(project)],
                                        {STORY_ID: {"project": str(project)}})
    assert notes == []
    assert resource == {cv.SERVICE_NAME: "claude_code"}
    root = spans[0]
    trace_id = sp.trace_id_for("claude_code:" + STORY_ID)
    assert root["trace_id"] == trace_id
    assert root["span_id"] == sp.span_id_for(trace_id, "root")
    assert root["parent_span_id"] == ""
    assert root["name"] == "invoke_agent claude_code"
    assert root["kind"] == cv.SPAN_KIND_INTERNAL
    assert root["start_ns"] == sp.time_ns("2026-10-21T14:02:05.112Z")
    assert root["end_ns"] == sp.time_ns("2026-10-21T14:02:46.009Z")
    assert root["attributes"] == {
        cv.OPERATION_NAME: cv.INVOKE_AGENT,
        cv.AGENT_NAME: "claude_code",
        cv.CONVERSATION_ID: STORY_ID,
        cv.AUDIT_HARNESS: "claude_code",
        cv.AUDIT_PROJECT: str(project),
    }


def test_story_session_gives_six_tool_spans_in_order(tmp_path):
    project = tmp_path / "work" / "story_project"
    _, spans, _ = _one_trace([_story(project)], {STORY_ID: {"project": str(project)}})
    tools = _tools(spans)
    assert [span["name"] for span in tools] == [
        "execute_tool Read", "execute_tool Edit", "execute_tool Edit",
        "execute_tool Write", "execute_tool Bash", "execute_tool Bash"]
    # The root and the six tool spans, beside the model turns of step E4.
    assert len([span for span in spans
                if span["attributes"].get(cv.OPERATION_NAME) != cv.CHAT]) == 7
    root = spans[0]
    records = _story_records(project)
    calls = {}
    results = {}
    for record in records:
        for part in record["message"]["content"] if isinstance(
                record.get("message", {}).get("content"), list) else []:
            if part.get("type") == "tool_use":
                calls[part["id"]] = (record["timestamp"], part)
            if part.get("type") == "tool_result":
                results[part["tool_use_id"]] = (record["timestamp"], part["content"])
    assert [span["attributes"][cv.TOOL_CALL_ID] for span in tools] == list(calls)
    for span in tools:
        call_id = span["attributes"][cv.TOOL_CALL_ID]
        called_at, part = calls[call_id]
        answered_at, content = results[call_id]
        assert span["trace_id"] == root["trace_id"]
        assert span["parent_span_id"] == root["span_id"]
        assert span["span_id"] == sp.span_id_for(root["trace_id"], call_id)
        assert span["kind"] == cv.SPAN_KIND_INTERNAL
        assert span["start_ns"] == sp.time_ns(called_at)
        assert span["end_ns"] == sp.time_ns(answered_at)
        attributes = span["attributes"]
        assert attributes[cv.OPERATION_NAME] == cv.EXECUTE_TOOL
        assert attributes[cv.TOOL_NAME] == part["name"]
        assert attributes[cv.TOOL_TYPE] == "function"
        assert attributes[cv.TOOL_CALL_ARGUMENTS] == part["input"]
        assert attributes[cv.TOOL_CALL_RESULT] == content
        assert cv.MCP_METHOD_NAME not in attributes
        assert cv.ERROR_TYPE not in attributes
        assert span["status_code"] == cv.STATUS_UNSET


def test_story_file_calls_carry_their_path_and_role(tmp_path):
    project = tmp_path / "work" / "story_project"
    _, spans, _ = _one_trace([_story(project)], {STORY_ID: {"project": str(project)}})
    found = [(span["attributes"][cv.TOOL_NAME], span["attributes"].get(cv.FILE_PATH),
              span["attributes"].get(cv.AUDIT_ROLE)) for span in _tools(spans)]
    assert found == [
        ("Read", str(project / "manuscript.md"), "read"),
        ("Edit", str(project / "manuscript.md"), "edited"),
        ("Edit", str(project / "manuscript.md"), "edited"),
        ("Write", str(project / "source_notes.md"), "produced"),
        ("Bash", None, None),
        ("Bash", None, None),
    ]


def test_project_comes_from_the_first_record_without_a_record_row(tmp_path):
    project = tmp_path / "work" / "story_project"
    _, spans, _ = _one_trace([_story(project)])
    assert spans[0]["attributes"][cv.AUDIT_PROJECT] == str(project)


def test_the_record_row_project_wins_over_the_records_folder(tmp_path):
    project = tmp_path / "work" / "story_project"
    _, spans, _ = _one_trace([_story(project)], {STORY_ID: {"project": "/elsewhere/top"}})
    assert spans[0]["attributes"][cv.AUDIT_PROJECT] == "/elsewhere/top"


# Track E's own fixture


def test_fixture_failing_call_has_the_error_status(tmp_path):
    project, kb = _folders(tmp_path)
    _, spans, _ = _one_trace([_fixture(project, kb)])
    bash = _by_call(spans, "toolu_obs_05_bash")
    assert bash["status_code"] == cv.STATUS_ERROR
    assert bash["attributes"][cv.ERROR_TYPE] == "tool_error"
    assert bash["attributes"][cv.TOOL_CALL_RESULT].startswith("Exit code 2\n")
    ok = _by_call(spans, "toolu_obs_03_read")
    assert ok["status_code"] == cv.STATUS_UNSET
    assert cv.ERROR_TYPE not in ok["attributes"]


def test_fixture_last_call_has_no_result_and_ends_at_its_own_time(tmp_path):
    project, kb = _folders(tmp_path)
    _, spans, _ = _one_trace([_fixture(project, kb)])
    write = _by_call(spans, "toolu_obs_07_write")
    assert cv.TOOL_CALL_RESULT not in write["attributes"]
    assert write["start_ns"] == write["end_ns"] == sp.time_ns("2026-10-22T09:01:04.622Z")
    assert write["attributes"][cv.FILE_PATH] == str(project / "obs_notes.md")
    assert write["attributes"][cv.AUDIT_ROLE] == "produced"
    assert write["status_code"] == cv.STATUS_UNSET


def test_fixture_knowledge_base_calls_are_extension_tools_over_mcp(tmp_path):
    project, kb = _folders(tmp_path)
    _, spans, _ = _one_trace([_fixture(project, kb)])
    for call_id, tool in (("toolu_obs_01_search", "mcp__pipeline-kb__search_kb"),
                          ("toolu_obs_02_entry", "mcp__pipeline-kb__get_entry")):
        span = _by_call(spans, call_id)
        assert span["name"] == "execute_tool " + tool
        assert span["attributes"][cv.TOOL_TYPE] == "extension"
        assert span["attributes"][cv.MCP_METHOD_NAME] == "tools/call"
        assert cv.AUDIT_ROLE not in span["attributes"]
    search = _by_call(spans, "toolu_obs_01_search")
    assert search["attributes"][cv.TOOL_CALL_ARGUMENTS] == {
        "query": "checking references", "group": "verification", "limit": 5}
    for call_id in ("toolu_obs_03_read", "toolu_obs_05_bash", "toolu_obs_06_agent"):
        span = _by_call(spans, call_id)
        assert span["attributes"][cv.TOOL_TYPE] == "function"
        assert cv.MCP_METHOD_NAME not in span["attributes"]


def test_fixture_list_result_is_joined_from_its_text(tmp_path):
    project, kb = _folders(tmp_path)
    _, spans, _ = _one_trace([_fixture(project, kb)])
    entry = _by_call(spans, "toolu_obs_02_entry")
    assert entry["attributes"][cv.TOOL_CALL_RESULT] == (
        "id: verification-references-procedure\n"
        "Each reference is matched to a source text, and each quoted claim is "
        "checked against that text.")
    agent = _by_call(spans, "toolu_obs_06_agent")
    assert agent["attributes"][cv.TOOL_CALL_RESULT] == "No reference would be flagged."


def test_fixture_reads_carry_their_paths(tmp_path):
    project, kb = _folders(tmp_path)
    _, spans, _ = _one_trace([_fixture(project, kb)])
    assert _by_call(spans, "toolu_obs_03_read")["attributes"][cv.FILE_PATH] == str(
        project / "manuscript.md")
    kb_read = _by_call(spans, "toolu_obs_04_read")
    assert kb_read["attributes"][cv.FILE_PATH] == str(
        kb / "verification" / "verification-references-procedure.md")
    assert kb_read["attributes"][cv.AUDIT_ROLE] == "read"


def test_fixture_unknown_record_and_broken_line_leave_only_a_note(tmp_path):
    project, kb = _folders(tmp_path)
    records, notes = cc.read_records([_fixture(project, kb)])
    assert len(notes) == 1
    assert "does not parse" in notes[0]
    assert all(record["type"] in ("user", "assistant") for record in records)
    _, spans, _ = _one_trace([_fixture(project, kb)])
    assert [span["attributes"][cv.TOOL_CALL_ID] for span in _tools(spans)] == [
        "toolu_obs_01_search", "toolu_obs_02_entry", "toolu_obs_03_read",
        "toolu_obs_04_read", "toolu_obs_05_bash", "toolu_obs_06_agent",
        "toolu_obs_07_write"]
    # The root runs from the first kept record to the last, so the unknown
    # record's time is not part of it.
    assert spans[0]["start_ns"] == sp.time_ns("2026-10-22T09:00:01.000Z")
    assert spans[0]["end_ns"] == sp.time_ns("2026-10-22T09:01:04.622Z")


def test_fixture_and_a_copy_cut_short_give_the_same_spans(tmp_path):
    project, kb = _folders(tmp_path)
    _, alone, _ = _one_trace([_fixture(project, kb)])
    _, together, _ = _one_trace([_fixture(project, kb, lines=9), _fixture(project, kb)])
    assert together == alone


def test_cut_copy_alone_leaves_the_pending_call_without_a_result(tmp_path):
    project, kb = _folders(tmp_path)
    # The first seven lines end with the get_entry call, before its result.
    _, spans, _ = _one_trace([_fixture(project, kb, lines=7)])
    entry = _by_call(spans, "toolu_obs_02_entry")
    assert cv.TOOL_CALL_RESULT not in entry["attributes"]
    assert entry["start_ns"] == entry["end_ns"]


def test_every_span_passes_both_checks(tmp_path):
    project, kb = _folders(tmp_path)
    story_project = tmp_path / "work" / "story_project"
    for transcript in (_fixture(project, kb), _story(story_project)):
        _, spans, _ = _one_trace([transcript])
        for span in spans:
            assert sp.problems(span) == [], span["name"]
            assert cv.convention_problems(span) == [], span["name"]


def test_spans_survive_the_file_form(tmp_path):
    project, kb = _folders(tmp_path)
    resource, spans, _ = _one_trace([_fixture(project, kb)])
    path = tmp_path / "trace.json"
    sp.write_trace(path, spans, resource)
    back_resource, back = sp.read_trace(path)
    assert back_resource == resource
    assert [span["span_id"] for span in back] == [span["span_id"] for span in spans]
    search = [span for span in back
              if span["attributes"].get(cv.TOOL_CALL_ID) == "toolu_obs_01_search"][0]
    assert json.loads(search["attributes"][cv.TOOL_CALL_ARGUMENTS])["limit"] == 5


# Reading records


def _line(**fields):
    record = {"sessionId": "s-1", "cwd": "/synthetic/project"}
    record.update(fields)
    return json.dumps(record)


def _assistant(uuid, at, parts, **extra):
    return _line(uuid=uuid, timestamp=at, type="assistant",
                 message={"role": "assistant", "content": parts}, **extra)


def _user(uuid, at, content, **extra):
    return _line(uuid=uuid, timestamp=at, type="user",
                 message={"role": "user", "content": content}, **extra)


def test_records_keep_the_first_copy_of_each_uuid():
    first = _user("u1", "2026-10-22T09:00:01Z", "first text")
    again = _user("u1", "2026-10-22T09:00:01Z", "a later copy")
    records, notes = cc.read_records([first + "\n", again + "\n"])
    assert notes == []
    assert [record["message"]["content"] for record in records] == ["first text"]


def test_records_sort_by_time_and_keep_file_order_for_equal_times():
    lines = [
        _user("u3", "2026-10-22T09:00:03Z", "third"),
        _user("u1", "2026-10-22T09:00:01Z", "first"),
        _user("u2b", "2026-10-22T09:00:02Z", "second b"),
        _user("u2a", "2026-10-22T09:00:02.000Z", "second a"),
    ]
    records, _ = cc.read_records(["\n".join(lines) + "\n"])
    assert [record["uuid"] for record in records] == ["u1", "u2b", "u2a", "u3"]


def test_records_need_a_uuid_a_time_and_a_known_type():
    lines = [
        _user("u1", "2026-10-22T09:00:01Z", "kept"),
        _line(timestamp="2026-10-22T09:00:02Z", type="user", message={"content": "no uuid"}),
        _line(uuid="u3", type="user", message={"content": "no time"}),
        _line(uuid="u4", timestamp="2026-10-22T09:00:04Z", type="system", content="skipped"),
        _line(uuid="u5", timestamp="2026-10-22T09:00:05Z", type="summary"),
        "",
        "not json at all",
    ]
    records, notes = cc.read_records([("\n".join(lines) + "\n").encode("utf-8")])
    assert [record["uuid"] for record in records] == ["u1"]
    assert len(notes) == 1
    assert "line 7" in notes[0]


def test_subagent_calls_sit_under_their_own_agent_not_the_root():
    # Step E10 places subagent records under their own invoke_agent span.
    lines = [
        _user("u1", "2026-10-22T09:00:01Z", "go"),
        _assistant("a1", "2026-10-22T09:00:02Z",
                   [{"type": "tool_use", "id": "t1", "name": "Read",
                     "input": {"file_path": "/synthetic/project/a.md"}}]),
        _assistant("s1", "2026-10-22T09:00:03Z",
                   [{"type": "tool_use", "id": "t-sub", "name": "Read",
                     "input": {"file_path": "/synthetic/project/b.md"}}],
                   agentId="a1", isSidechain=True),
        _user("s2", "2026-10-22T09:00:04Z",
              [{"type": "tool_result", "tool_use_id": "t-sub", "content": "b"}],
              agentId="a1", isSidechain=True),
        _user("u2", "2026-10-22T09:00:05Z",
              [{"type": "tool_result", "tool_use_id": "t1", "content": "a"}]),
    ]
    records, _ = cc.read_records(["\n".join(lines) + "\n"])
    [(_, spans)] = cc.traces(records, {})
    root = spans[0]
    [agent] = [span for span in spans
               if span["attributes"].get(cv.OPERATION_NAME) == cv.INVOKE_AGENT
               and span["parent_span_id"]]
    assert [span["attributes"].get(cv.TOOL_CALL_ID) for span in _tools(spans)
            if span["parent_span_id"] == root["span_id"]] == ["t1"]
    assert [span["attributes"].get(cv.TOOL_CALL_ID) for span in _tools(spans)
            if span["parent_span_id"] == agent["span_id"]] == ["t-sub"]
    assert root["end_ns"] == sp.time_ns("2026-10-22T09:00:05Z")


def test_one_trace_for_each_session_id():
    lines = [
        _user("u1", "2026-10-22T09:00:01Z", "one", sessionId="s-1"),
        _user("u2", "2026-10-22T09:00:02Z", "two", sessionId="s-2"),
        _user("u3", "2026-10-22T09:00:03Z", "one again", sessionId="s-1"),
    ]
    records, _ = cc.read_records(["\n".join(lines) + "\n"])
    found = cc.traces(records, {"s-2": {"project": "/synthetic/second"}})
    roots = [spans[0] for _, spans in found]
    assert [root["attributes"][cv.CONVERSATION_ID] for root in roots] == ["s-1", "s-2"]
    assert roots[0]["end_ns"] == sp.time_ns("2026-10-22T09:00:03Z")
    assert roots[1]["attributes"][cv.AUDIT_PROJECT] == "/synthetic/second"


def test_other_result_parts_are_named_and_long_text_is_cut():
    long_text = "x" * (cv.TEXT_CAP + 10)
    lines = [
        _assistant("a1", "2026-10-22T09:00:01Z",
                   [{"type": "tool_use", "id": "t1", "name": "Bash",
                     "input": {"command": long_text, "options": {"note": long_text},
                               "count": 3}}]),
        _user("u1", "2026-10-22T09:00:02Z",
              [{"type": "tool_result", "tool_use_id": "t1",
                "content": [{"type": "text", "text": "before"},
                            {"type": "image", "source": {"type": "base64", "data": "AAAA"}},
                            {"type": "text", "text": long_text}]}]),
    ]
    records, _ = cc.read_records(["\n".join(lines) + "\n"])
    [(_, spans)] = cc.traces(records, {})
    [span] = _tools(spans)
    arguments = span["attributes"][cv.TOOL_CALL_ARGUMENTS]
    assert arguments["command"] == cv.cap(long_text)
    assert arguments["options"]["note"] == cv.cap(long_text)
    assert arguments["count"] == 3
    assert span["attributes"][cv.TOOL_CALL_RESULT] == cv.cap(
        "before\n[image]\n" + long_text)
