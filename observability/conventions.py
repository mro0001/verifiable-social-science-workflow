"""The names this layer writes, from OpenTelemetry's conventions for AI calls.

Appendix A2.6 asks for events that follow OpenTelemetry's conventions for AI
calls, so the view does not depend on any one harness. Every name those
conventions give is in Development status, so all of them live here and change
in one place. What the conventions do not name uses file.path from
OpenTelemetry's general registry, the prefix audit. for fields taken from the
audit record, and vg. for verification runs.
"""

SEMCONV_SOURCE = ("open-telemetry/semantic-conventions-genai at commit 3fe84604a581, "
                  "read on 2026-10-28, Development status")

# Operations

CHAT = "chat"
EXECUTE_TOOL = "execute_tool"
INVOKE_AGENT = "invoke_agent"
INVOKE_WORKFLOW = "invoke_workflow"
OPERATIONS = (CHAT, EXECUTE_TOOL, INVOKE_AGENT, INVOKE_WORKFLOW)

# Span attributes from the GenAI conventions

OPERATION_NAME = "gen_ai.operation.name"
PROVIDER_NAME = "gen_ai.provider.name"
REQUEST_MODEL = "gen_ai.request.model"
RESPONSE_MODEL = "gen_ai.response.model"
RESPONSE_ID = "gen_ai.response.id"
RESPONSE_FINISH_REASONS = "gen_ai.response.finish_reasons"
USAGE_INPUT_TOKENS = "gen_ai.usage.input_tokens"
USAGE_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
USAGE_CACHE_READ_INPUT_TOKENS = "gen_ai.usage.cache_read.input_tokens"
USAGE_CACHE_WRITE_INPUT_TOKENS = "gen_ai.usage.cache_write.input_tokens"
CONVERSATION_ID = "gen_ai.conversation.id"
INPUT_MESSAGES = "gen_ai.input.messages"
OUTPUT_MESSAGES = "gen_ai.output.messages"
AGENT_ID = "gen_ai.agent.id"
AGENT_NAME = "gen_ai.agent.name"
AGENT_DESCRIPTION = "gen_ai.agent.description"
TOOL_NAME = "gen_ai.tool.name"
TOOL_CALL_ID = "gen_ai.tool.call.id"
TOOL_TYPE = "gen_ai.tool.type"
TOOL_CALL_ARGUMENTS = "gen_ai.tool.call.arguments"
TOOL_CALL_RESULT = "gen_ai.tool.call.result"
TRANSFER_TARGET_NAME = "gen_ai.transfer.target.name"
TRANSFER_MODE = "gen_ai.transfer.mode"
WORKFLOW_NAME = "gen_ai.workflow.name"
DATA_SOURCE_ID = "gen_ai.data_source.id"
RETRIEVAL_DOCUMENTS = "gen_ai.retrieval.documents"
RETRIEVAL_QUERY_TEXT = "gen_ai.retrieval.query.text"
ERROR_TYPE = "error.type"
MCP_METHOD_NAME = "mcp.method.name"

# From OpenTelemetry's general attribute registry

FILE_PATH = "file.path"

# The resource key

SERVICE_NAME = "service.name"

# This layer's own keys, for fields the conventions do not name

AUDIT_HARNESS = "audit.harness"
AUDIT_PROJECT = "audit.project"
AUDIT_ROLE = "audit.role"
AUDIT_VERB = "audit.verb"
AUDIT_KIND = "audit.kind"
AUDIT_OBJECT = "audit.object"
AUDIT_RATIONALE = "audit.rationale"
AUDIT_ORDINAL = "audit.ordinal"
VG_RUN_ID = "vg.run_id"
VG_STREAM = "vg.stream"
VG_GRAPH_VERSION = "vg.graph_version"
VG_STEP_SEQ = "vg.step.seq"
VG_STEP_KIND = "vg.step.kind"
VG_CONTRACT = "vg.contract"
VG_EXECUTOR = "vg.executor"

ATTRIBUTE_KEYS = (
    OPERATION_NAME, PROVIDER_NAME, REQUEST_MODEL, RESPONSE_MODEL, RESPONSE_ID,
    RESPONSE_FINISH_REASONS, USAGE_INPUT_TOKENS, USAGE_OUTPUT_TOKENS,
    USAGE_CACHE_READ_INPUT_TOKENS, USAGE_CACHE_WRITE_INPUT_TOKENS, CONVERSATION_ID,
    INPUT_MESSAGES, OUTPUT_MESSAGES, AGENT_ID, AGENT_NAME, AGENT_DESCRIPTION,
    TOOL_NAME, TOOL_CALL_ID, TOOL_TYPE, TOOL_CALL_ARGUMENTS, TOOL_CALL_RESULT,
    TRANSFER_TARGET_NAME, TRANSFER_MODE, WORKFLOW_NAME, DATA_SOURCE_ID,
    RETRIEVAL_DOCUMENTS, RETRIEVAL_QUERY_TEXT, ERROR_TYPE, FILE_PATH, MCP_METHOD_NAME,
    SERVICE_NAME,
    AUDIT_HARNESS, AUDIT_PROJECT, AUDIT_ROLE, AUDIT_VERB, AUDIT_KIND, AUDIT_OBJECT,
    AUDIT_RATIONALE, AUDIT_ORDINAL,
    VG_RUN_ID, VG_STREAM, VG_GRAPH_VERSION, VG_STEP_SEQ, VG_STEP_KIND, VG_CONTRACT,
    VG_EXECUTOR,
)

# The transfer mode of a call that starts a subagent and waits for it

TRANSFER_RETURN_TO_CALLER = "return_to_caller"

# Span kinds and status codes, as OTLP numbers them

SPAN_KIND_INTERNAL = 1
SPAN_KIND_CLIENT = 3

STATUS_UNSET = 0
STATUS_OK = 1
STATUS_ERROR = 2


class _KeepOthers(dict):
    """A mapping that gives back any key it does not hold."""

    def __missing__(self, key):
        return key


# From a model's stop reason to the conventions' finish reason. Any other
# stop reason is kept as given.
FINISH_REASONS = _KeepOthers({
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
    "tool_use": "tool_call",
    "refusal": "content_filter",
})

# Text longer than this is cut, since the full text stays in the audit record.
TEXT_CAP = 8000


def cap(text):
    """Cut text longer than TEXT_CAP and note its full length."""
    if len(text) <= TEXT_CAP:
        return text
    return text[:TEXT_CAP] + " [cut, %d characters in all]" % len(text)


def _name_problem(name, allowed):
    return "span name %r should be %s" % (name, " or ".join(repr(a) for a in allowed))


def convention_problems(span):
    """Name what breaks the conventions in one span, as a list of sentences.

    A chat span needs gen_ai.provider.name and an execute_tool span needs
    gen_ai.tool.name. Each operation's span name has its own form. A span
    with no operation, or one the conventions here do not name, passes.
    """
    attributes = span.get("attributes") or {}
    operation = attributes.get(OPERATION_NAME)
    name = span.get("name", "")
    found = []
    if operation == CHAT:
        if not attributes.get(PROVIDER_NAME):
            found.append("chat span %r has no %s" % (name, PROVIDER_NAME))
        allowed = [CHAT]
        if attributes.get(REQUEST_MODEL):
            allowed.append(CHAT + " " + str(attributes[REQUEST_MODEL]))
        if name not in allowed:
            found.append(_name_problem(name, allowed))
    elif operation == EXECUTE_TOOL:
        tool = attributes.get(TOOL_NAME)
        if not tool:
            found.append("execute_tool span %r has no %s" % (name, TOOL_NAME))
        elif name != EXECUTE_TOOL + " " + str(tool):
            found.append(_name_problem(name, [EXECUTE_TOOL + " " + str(tool)]))
    elif operation == INVOKE_AGENT:
        allowed = [INVOKE_AGENT]
        if attributes.get(AGENT_NAME):
            allowed.append(INVOKE_AGENT + " " + str(attributes[AGENT_NAME]))
        if name not in allowed:
            found.append(_name_problem(name, allowed))
    elif operation == INVOKE_WORKFLOW:
        workflow = attributes.get(WORKFLOW_NAME)
        if not workflow:
            found.append("invoke_workflow span %r has no %s, which its name needs"
                         % (name, WORKFLOW_NAME))
        elif name != INVOKE_WORKFLOW + " " + str(workflow):
            found.append(_name_problem(name, [INVOKE_WORKFLOW + " " + str(workflow)]))
    return found
