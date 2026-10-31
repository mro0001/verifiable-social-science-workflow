"""The Claude Code adapter, from kept transcripts to trace spans.

Proposal Approach paragraph 4 and Figure 1 have the layer show which files
the harness reads and which tools it calls, with their results, and appendix
A2.6 paragraph 1 names the tool calls and the tool results. Claude Code is
the first harness.

A transcript is JSON Lines. Records carry uuid, timestamp, type, sessionId,
and cwd. Assistant records hold tool_use parts (id, name, input), and user
records hold tool_result parts (tool_use_id, content, is_error). Records join
into one trace for each sessionId (plan choice 7). Each session is an
invoke_agent span, with its model turns as chat spans and its tool calls as
execute_tool spans beneath it (plan choice 6). Proposal Approach paragraph 4
and appendix A2.6 paragraph 1 also name the model's reasoning where the model
exposes it, which is a reasoning part of a turn's output message (plan choice
8). A turn keeps as input only the typed prompt that started it (plan choice
9). Records carrying agentId belong to subagents (appendix A2.6 paragraph 1
and A2.1). Each agentId gives one invoke_agent span under the tool call whose
result record names that agentId in toolUseResult, or under the session's
root when that call is not in the trace, and the subagent's own model turns
and tool calls sit beneath it (plan choices 6 and 7). The .meta.json files
beside subagent transcripts are not read.
"""
import json
from typing import Dict, List, Tuple

from observability import conventions as cv
from observability import spans as sp

HARNESS = "claude_code"
ROOT_KEY = "root"
AGENT_KEY = "agent:"
MAIN = ""

KNOWN_TYPES = ("user", "assistant")

# File roles on tool calls, in Table A4's words (plan choice 11).
FILE_ROLES = {"Read": "read", "Edit": "edited", "Write": "produced"}

MCP_PREFIX = "mcp__"
MCP_TOOLS_CALL = "tools/call"
TOOL_ERROR = "tool_error"

# Claude Code turns are marked with this provider (plan gap 8).
PROVIDER = "anthropic"


def read_records(transcripts) -> Tuple[List[Dict], List[str]]:
    """The user and assistant records of transcripts, as (records, notes).

    transcripts is a list of transcript texts or bytes, oldest first. A record
    is kept when it has a uuid, a timestamp, and the type user or assistant.
    The first copy of each uuid is kept, so a transcript and its grown copy
    give each record once. Records are sorted by time, keeping file order for
    equal times. A line that does not parse becomes a note, and a record type
    this adapter does not know is skipped.
    """
    kept = []
    notes = []
    seen = set()
    for number, transcript in enumerate(transcripts, start=1):
        if isinstance(transcript, bytes):
            transcript = transcript.decode("utf-8", errors="replace")
        for line_number, line in enumerate(transcript.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError:
                notes.append("transcript %d line %d does not parse as JSON"
                             % (number, line_number))
                continue
            if not isinstance(record, dict):
                notes.append("transcript %d line %d does not parse as a record"
                             % (number, line_number))
                continue
            if record.get("type") not in KNOWN_TYPES:
                continue
            uuid = record.get("uuid")
            stamp = record.get("timestamp")
            if not uuid or not stamp:
                continue
            if uuid in seen:
                continue
            try:
                at = sp.time_ns(stamp)
            except ValueError:
                notes.append("transcript %d line %d has a time that does not parse, %r"
                             % (number, line_number, stamp))
                continue
            seen.add(uuid)
            kept.append((at, len(kept), record))
    kept.sort(key=lambda item: (item[0], item[1]))
    return [record for _, _, record in kept], notes


def traces(records, sessions_meta) -> List[Tuple[Dict, List[Dict]]]:
    """One trace for each sessionId in records, as a list of (resource, spans).

    sessions_meta maps a harness session id to its record row, whose project
    names the session's folder. Without a row, the first record's cwd does.
    Records carrying agentId join their session's trace as subagents. Traces
    come in the order their first records appear.
    """
    groups = {}
    order = []
    for record in records:
        session_id = record.get("sessionId")
        if not session_id:
            continue
        if session_id not in groups:
            groups[session_id] = []
            order.append(session_id)
        groups[session_id].append(record)
    found = []
    for session_id in order:
        meta = (sessions_meta or {}).get(session_id) or {}
        found.append(_trace(session_id, groups[session_id], meta))
    return found


def _owner(record):
    """The agent a record belongs to, its agentId, or MAIN for the session's own agent."""
    agent_id = record.get("agentId")
    if isinstance(agent_id, str) and agent_id:
        return agent_id
    return MAIN


def _prefix(owner):
    """What each span key of an agent starts with, so agents' keys never collide."""
    return "" if owner == MAIN else AGENT_KEY + owner + "/"


def _trace(session_id, records, meta):
    trace_id = sp.trace_id_for(HARNESS + ":" + session_id)
    times = [sp.time_ns(record["timestamp"]) for record in records]
    attributes = {
        cv.OPERATION_NAME: cv.INVOKE_AGENT,
        cv.AGENT_NAME: HARNESS,
        cv.CONVERSATION_ID: session_id,
        cv.AUDIT_HARNESS: HARNESS,
    }
    project = meta.get("project") or records[0].get("cwd")
    if project:
        attributes[cv.AUDIT_PROJECT] = str(project)
    root = sp.new_span(trace_id, ROOT_KEY, cv.INVOKE_AGENT + " " + HARNESS,
                       cv.SPAN_KIND_INTERNAL, times[0], times[-1], attributes=attributes)

    by_owner = {MAIN: []}
    owners = []
    for record in records:
        owner = _owner(record)
        if owner not in by_owner:
            by_owner[owner] = []
        if owner != MAIN and owner not in owners:
            owners.append(owner)
        by_owner[owner].append(record)

    # Every agent's turns and calls are made first, each under its own span,
    # whose id comes from its key alone, so a subagent can then be placed
    # under a call made by any agent, a subagent's included.
    calls = {}
    beneath = {MAIN: _agent_spans(trace_id, root["span_id"], MAIN, by_owner[MAIN], calls)}
    for owner in owners:
        agent_id = sp.span_id_for(trace_id, AGENT_KEY + owner)
        beneath[owner] = _agent_spans(trace_id, agent_id, owner, by_owner[owner], calls)
    callers = _callers(records, calls)
    spans = [root] + beneath[MAIN]
    for owner in owners:
        caller = _caller_span(owner, callers, calls)
        parent_id = caller[0]["span_id"] if caller is not None else root["span_id"]
        spans.append(_subagent_span(trace_id, parent_id, owner, by_owner[owner], caller))
        spans.extend(beneath[owner])
    return {cv.SERVICE_NAME: HARNESS}, spans


def _agent_spans(trace_id, parent_id, owner, records, calls):
    """The model turns and tool calls of one agent, under parent_id.

    Each tool span is kept in calls by (owner, call id), so a subagent can
    find the call that started it.
    """
    if not records:
        return []
    prefix = _prefix(owner)
    times = [sp.time_ns(record["timestamp"]) for record in records]
    results = _results(records, times)
    turns = _turns(records)
    made = set()
    spans = []
    for index, (record, at) in enumerate(zip(records, times)):
        if record.get("type") != "assistant":
            continue
        key = _turn_key(record)
        if turns[key][0] == index:
            spans.append(_turn_span(trace_id, parent_id, prefix + key, turns[key],
                                    records, times))
        for part in _parts(record):
            if part.get("type") != "tool_use" or not part.get("id"):
                continue
            if part["id"] in made:
                continue
            made.add(part["id"])
            span = _tool_span(trace_id, parent_id, part, at, results.get(part["id"]),
                              key=prefix + part["id"])
            calls[(owner, part["id"])] = (span, part)
            spans.append(span)
    return spans


def _callers(records, calls):
    """For each subagent, the (owner, call id) of the call whose result names it.

    A user record whose toolUseResult carries agentId names the subagent, and
    its first tool_result part names the call. The first such record wins.
    """
    found = {}
    for record in records:
        if record.get("type") != "user":
            continue
        result = record.get("toolUseResult")
        if not isinstance(result, dict):
            continue
        agent_id = result.get("agentId")
        if not isinstance(agent_id, str) or not agent_id or agent_id in found:
            continue
        for part in _parts(record):
            if part.get("type") == "tool_result" and part.get("tool_use_id"):
                found[agent_id] = (_owner(record), part["tool_use_id"])
                break
    return {agent_id: caller for agent_id, caller in found.items() if caller in calls}


def _caller_span(owner, callers, calls):
    """The tool span that started the subagent owner with its tool_use part, or None.

    None when no call in the trace names it, or when following the calls up
    from it comes back to it, so a subagent is never placed under itself.
    """
    if owner not in callers:
        return None
    seen = {owner}
    current = callers[owner][0]
    while current != MAIN:
        if current in seen:
            return None
        seen.add(current)
        if current not in callers:
            break
        current = callers[current][0]
    return calls[callers[owner]]


def _subagent_span(trace_id, parent_id, owner, records, caller):
    """A subagent's invoke_agent span, from its first record's time to its last.

    Its name and description come from the input of the call that started it,
    and that call's span gains the transfer attributes.
    """
    times = [sp.time_ns(record["timestamp"]) for record in records]
    attributes = {
        cv.OPERATION_NAME: cv.INVOKE_AGENT,
        cv.AGENT_ID: owner,
    }
    agent_type = None
    if caller is not None:
        call_span, part = caller
        arguments = part.get("input") if isinstance(part.get("input"), dict) else {}
        if isinstance(arguments.get("subagent_type"), str) and arguments["subagent_type"]:
            agent_type = arguments["subagent_type"]
        if agent_type:
            attributes[cv.AGENT_NAME] = agent_type
            call_span["attributes"][cv.TRANSFER_TARGET_NAME] = agent_type
        if isinstance(arguments.get("description"), str) and arguments["description"]:
            attributes[cv.AGENT_DESCRIPTION] = cv.cap(arguments["description"])
        call_span["attributes"][cv.TRANSFER_MODE] = cv.TRANSFER_RETURN_TO_CALLER
    name = cv.INVOKE_AGENT + " " + agent_type if agent_type else cv.INVOKE_AGENT
    return sp.new_span(trace_id, AGENT_KEY + owner, name, cv.SPAN_KIND_INTERNAL,
                       times[0], times[-1], parent_span_id=parent_id, attributes=attributes)


def _turn_key(record):
    """A model turn's key, its message.id, else the record's own uuid."""
    message_id = (record.get("message") or {}).get("id")
    if isinstance(message_id, str) and message_id:
        return message_id
    return record["uuid"]


def _turns(records):
    """The indexes of each model turn's assistant records, by turn key."""
    found = {}
    for index, record in enumerate(records):
        if record.get("type") == "assistant":
            found.setdefault(_turn_key(record), []).append(index)
    return found


def _turn_span(trace_id, root_id, key, indexes, records, times):
    """One model turn as a chat span.

    The turn runs from the time of the last kept record before its first
    record (its own first record's time when there is none) to the time of its
    last record.
    """
    first = indexes[0]
    start = times[first - 1] if first > 0 else times[first]
    end = max(start, times[indexes[-1]])
    turn_records = [records[index] for index in indexes]
    messages = [record.get("message") or {} for record in turn_records]
    model = None
    for message in messages:
        if isinstance(message.get("model"), str) and message["model"]:
            model = message["model"]
            break
    attributes = {
        cv.OPERATION_NAME: cv.CHAT,
        cv.PROVIDER_NAME: PROVIDER,
    }
    if model:
        attributes[cv.REQUEST_MODEL] = model
        attributes[cv.RESPONSE_MODEL] = model
    response_id = messages[0].get("id")
    if isinstance(response_id, str) and response_id:
        attributes[cv.RESPONSE_ID] = response_id
    finish = None
    for message in messages:
        if message.get("stop_reason"):
            finish = cv.FINISH_REASONS[message["stop_reason"]]
    if finish:
        attributes[cv.RESPONSE_FINISH_REASONS] = [finish]
    attributes.update(_usage(messages))
    output = {"role": "assistant"}
    if finish:
        output["finish_reason"] = finish
    output["parts"] = [mapped for record in turn_records
                       for mapped in (_output_part(part) for part in _parts(record))
                       if mapped is not None]
    attributes[cv.OUTPUT_MESSAGES] = [output]
    if first > 0:
        prompt = _typed_prompt(records[first - 1])
        if prompt is not None:
            attributes[cv.INPUT_MESSAGES] = [
                {"role": "user", "parts": [{"type": "text", "content": cv.cap(prompt)}]}]
    name = cv.CHAT + " " + model if model else cv.CHAT
    return sp.new_span(trace_id, key, name, cv.SPAN_KIND_CLIENT, start, end,
                       parent_span_id=root_id, attributes=attributes)


def _usage(messages):
    """A turn's token counts, each the largest among its records.

    The input count is input_tokens plus both cache counts, as the
    conventions' Anthropic page requires. The cache counts are written only
    when not zero, and nothing is written when no record carries usage.
    """
    largest = {}
    seen = False
    for message in messages:
        usage = message.get("usage")
        if not isinstance(usage, dict):
            continue
        seen = True
        for field in ("input_tokens", "output_tokens", "cache_read_input_tokens",
                      "cache_creation_input_tokens"):
            value = usage.get(field)
            if isinstance(value, int) and not isinstance(value, bool):
                largest[field] = max(largest.get(field, 0), value)
    if not seen:
        return {}
    cache_read = largest.get("cache_read_input_tokens", 0)
    cache_write = largest.get("cache_creation_input_tokens", 0)
    found = {
        cv.USAGE_INPUT_TOKENS: largest.get("input_tokens", 0) + cache_read + cache_write,
        cv.USAGE_OUTPUT_TOKENS: largest.get("output_tokens", 0),
    }
    if cache_read:
        found[cv.USAGE_CACHE_READ_INPUT_TOKENS] = cache_read
    if cache_write:
        found[cv.USAGE_CACHE_WRITE_INPUT_TOKENS] = cache_write
    return found


def _output_part(part):
    """One content part of a model turn in the conventions' message form.

    Thinking becomes a reasoning part, empty when its text is empty, and a
    redacted thinking part an empty reasoning part. A part of another type
    is left out.
    """
    kind = part.get("type")
    if kind == "thinking":
        return {"type": "reasoning", "content": cv.cap(str(part.get("thinking") or ""))}
    if kind == "redacted_thinking":
        return {"type": "reasoning", "content": ""}
    if kind == "text":
        return {"type": "text", "content": cv.cap(str(part.get("text") or ""))}
    if kind == "tool_use":
        arguments = part.get("input")
        if arguments is None:
            arguments = {}
        return {"type": "tool_call", "id": part.get("id"), "name": part.get("name"),
                "arguments": _cap_texts(arguments)}
    return None


def _typed_prompt(record):
    """The text of a typed prompt, or None when record is not one.

    A typed prompt is a user record whose content is a string or holds text
    parts, with no tool_result part, and whose isMeta is not true. Text parts
    are joined one to a line.
    """
    if record.get("type") != "user" or record.get("isMeta") is True:
        return None
    content = (record.get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return None
    parts = [part for part in content if isinstance(part, dict)]
    if any(part.get("type") == "tool_result" for part in parts):
        return None
    texts = [str(part.get("text") or "") for part in parts if part.get("type") == "text"]
    if not texts:
        return None
    return "\n".join(texts)


def _parts(record):
    content = (record.get("message") or {}).get("content")
    if isinstance(content, list):
        return [part for part in content if isinstance(part, dict)]
    return []


def _results(records, times):
    """The first tool_result for each tool_use_id, with its record's time."""
    found = {}
    for record, at in zip(records, times):
        if record.get("type") != "user":
            continue
        for part in _parts(record):
            if part.get("type") != "tool_result":
                continue
            call_id = part.get("tool_use_id")
            if call_id and call_id not in found:
                found[call_id] = (at, part)
    return found


def _tool_span(trace_id, root_id, part, called_at, result, key=None):
    name = str(part.get("name") or "")
    tool_input = part.get("input")
    if tool_input is None:
        tool_input = {}
    is_mcp = name.startswith(MCP_PREFIX)
    attributes = {
        cv.OPERATION_NAME: cv.EXECUTE_TOOL,
        cv.TOOL_NAME: name,
        cv.TOOL_CALL_ID: part["id"],
        cv.TOOL_TYPE: "extension" if is_mcp else "function",
        cv.TOOL_CALL_ARGUMENTS: _cap_texts(tool_input),
    }
    if is_mcp:
        attributes[cv.MCP_METHOD_NAME] = MCP_TOOLS_CALL
    if isinstance(tool_input, dict) and isinstance(tool_input.get("file_path"), str):
        attributes[cv.FILE_PATH] = tool_input["file_path"]
    if name in FILE_ROLES:
        attributes[cv.AUDIT_ROLE] = FILE_ROLES[name]
    end = called_at
    failed = False
    if result is not None:
        answered_at, result_part = result
        end = max(called_at, answered_at)
        attributes[cv.TOOL_CALL_RESULT] = cv.cap(_result_text(result_part.get("content")))
        failed = result_part.get("is_error") is True
    if failed:
        attributes[cv.ERROR_TYPE] = TOOL_ERROR
    span = sp.new_span(trace_id, key or part["id"], cv.EXECUTE_TOOL + " " + name,
                       cv.SPAN_KIND_INTERNAL, called_at, end,
                       parent_span_id=root_id, attributes=attributes)
    if failed:
        span["status_code"] = cv.STATUS_ERROR
    return span


def _cap_texts(value):
    """value with each text inside it cut by cap."""
    if isinstance(value, str):
        return cv.cap(value)
    if isinstance(value, dict):
        return {key: _cap_texts(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_cap_texts(item) for item in value]
    return value


def _result_text(content):
    """A tool result's content as text.

    A string is kept as given. A list is joined from its parts' text, one part
    to a line, with any other part written as [<type>].
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        pieces = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                pieces.append(str(part.get("text", "")))
            elif isinstance(part, dict):
                pieces.append("[%s]" % part.get("type", "part"))
            else:
                pieces.append(str(part))
        return "\n".join(pieces)
    return str(content)
