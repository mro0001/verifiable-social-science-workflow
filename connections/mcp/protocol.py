"""The Model Context Protocol layer every server shares (Track D, step D5).

Appendix A2.2 says MCP servers expose the databases to the harness and the
model through the Model Context Protocol (Table A1 row "MCP servers for the
databases"). The existing knowledge base server's mcp package needs Python
3.10 and the build allows no other packages, so the servers speak the
protocol's JSON-RPC over standard input and output with the standard library,
one message per line (Track D choice 8).

A server is a name, a version, and a list of Tool. handle answers one
message, and serve answers each line of its input until the input closes.
The methods answered are initialize, ping, tools/list, and tools/call. A
notification, a message with no id, gets no reply.

A tool's arguments are checked against its input schema before its handler
runs. A missing required argument, or one of the wrong type among string,
integer, and boolean, gives a result marked as an error that names the
argument. A handler's result goes back as one text part holding its JSON,
marked as an error when it is {"error": ...} or the handler raised. Errors in
results use the envelope the existing server uses, {"error": {"code": ...,
"message": ...}}.
"""
import contextlib
import json
import sys
from typing import Any, Callable, Dict, List, NamedTuple, Optional

# The protocol versions this layer answers, oldest first.
PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18")

# JSON-RPC error codes.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

# The JSON types an argument is checked against, and the Python types they read as.
_TYPES = {"string": "a string", "integer": "an integer", "boolean": "true or false"}


class Tool(NamedTuple):
    """One tool a server offers."""

    name: str
    description: str
    # The JSON schema of the tool's arguments, an object with properties and
    # an optional list of required names.
    input_schema: Dict[str, Any]
    # Called with the arguments as keywords. It gives a value JSON can hold.
    handler: Callable[..., Any]


def handle(message, server_name: str, server_version: str, tools: List[Tool]) -> Optional[dict]:
    """The reply to one message, or None when it gets no reply.

    message is a line of text, which is read as JSON, or a message already
    read. A line that is not JSON gives a parse error with a null id, and an
    array or anything else that is not a request gives an invalid request.
    """
    if isinstance(message, (str, bytes)):
        try:
            message = json.loads(message)
        except ValueError as error:
            return _error(None, PARSE_ERROR, f"the line is not JSON, {error}")

    if not isinstance(message, dict):
        what = "a batch of messages" if isinstance(message, list) else "not a request"
        return _error(None, INVALID_REQUEST, f"the message is {what}, send one request per line")

    message_id = message.get("id")
    has_id = "id" in message
    if has_id and not _good_id(message_id):
        return _error(None, INVALID_REQUEST, "a request id must be a string or a number")
    method = message.get("method")
    if not isinstance(method, str):
        return _error(message_id if has_id else None, INVALID_REQUEST, "the message names no method")
    if not has_id:
        # A notification, which is never answered, whatever its method.
        return None

    params = message.get("params")
    if method == "initialize":
        return _result(message_id, _initialize(params, server_name, server_version))
    if method == "ping":
        return _result(message_id, {})
    if method == "tools/list":
        return _result(message_id, {"tools": [_listed(tool) for tool in tools]})
    if method == "tools/call":
        return _call(message_id, params, tools)
    return _error(message_id, METHOD_NOT_FOUND, f"there is no method {method}")


def serve(server_name: str, server_version: str, tools: List[Tool], stdin, stdout) -> None:
    """Answer each line of stdin on stdout, one reply per line, until stdin closes.

    Each reply is flushed as it is written, and nothing else is written to
    stdout. What a handler prints goes to standard error instead. A blank line
    is passed over.
    """
    for line in stdin:
        if not line.strip():
            continue
        try:
            with contextlib.redirect_stdout(sys.stderr):
                reply = handle(line, server_name, server_version, tools)
        except Exception as error:  # a fault in this layer still gets an answer
            reply = _error(None, INTERNAL_ERROR, f"the server failed, {error}")
        if reply is None:
            continue
        stdout.write(json.dumps(reply) + "\n")
        stdout.flush()


def _good_id(value) -> bool:
    return value is None or (isinstance(value, (str, int, float)) and not isinstance(value, bool))


def _result(message_id, result) -> dict:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def _error(message_id, code: int, text: str) -> dict:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": text}}


def _initialize(params, server_name: str, server_version: str) -> dict:
    asked = params.get("protocolVersion") if isinstance(params, dict) else None
    version = asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[-1]
    return {
        "protocolVersion": version,
        "capabilities": {"tools": {}},
        "serverInfo": {"name": server_name, "version": server_version},
    }


def _listed(tool: Tool) -> dict:
    return {"name": tool.name, "description": tool.description, "inputSchema": tool.input_schema}


def _call(message_id, params, tools: List[Tool]) -> dict:
    name = params.get("name") if isinstance(params, dict) else None
    found = [tool for tool in tools if isinstance(name, str) and tool.name == name]
    if not found:
        return _error(message_id, INVALID_PARAMS, f"there is no tool {name!r}")
    tool = found[0]
    arguments = params.get("arguments")
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        return _error(message_id, INVALID_PARAMS, "the arguments must be an object")

    problem = _check_arguments(tool.input_schema, arguments)
    if problem is not None:
        return _result(message_id, _content({"error": {"code": "invalid_argument", "message": problem}}))
    try:
        answer = tool.handler(**arguments)
        text = _content(answer)
    except Exception as error:
        failure = f"the tool {tool.name} failed, {type(error).__name__}: {error}"
        text = _content({"error": {"code": "tool_failed", "message": failure}}, failed=True)
    return _result(message_id, text)


def _check_arguments(schema: Dict[str, Any], arguments: Dict[str, Any]) -> Optional[str]:
    """A sentence naming the first argument that is missing or of the wrong type, or None."""
    for name in schema.get("required", []):
        if name not in arguments:
            return f"missing required argument {name!r}"
    properties = schema.get("properties", {})
    for name, value in arguments.items():
        kind = (properties.get(name) or {}).get("type")
        if kind in _TYPES and not _is(kind, value):
            return f"argument {name!r} must be {_TYPES[kind]}"
    return None


def _is(kind: str, value) -> bool:
    if kind == "string":
        return isinstance(value, str)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, bool)


def _content(answer, failed: bool = False) -> dict:
    is_error = failed or (isinstance(answer, dict) and "error" in answer)
    text = json.dumps(answer, ensure_ascii=False)
    return {"content": [{"type": "text", "text": text}], "isError": bool(is_error)}
