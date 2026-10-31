"""Tests for the MCP protocol layer (Track D, step D5).

Appendix A2.2 says MCP servers expose the databases to the harness and the
model through the Model Context Protocol. The servers speak the protocol's
JSON-RPC over standard input and output with the standard library, one
message per line (Track D choice 8). These tests use a two-tool test server
and never start a real one. Nothing here calls a model or the network. Run
from the repository root with python3 -m pytest -q connections/tests.
"""
import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from connections.mcp import protocol  # noqa: E402
from connections.mcp.protocol import PROTOCOL_VERSIONS, Tool, handle, serve  # noqa: E402

NAME = "test-server"
VERSION = "0.0.1"


def echo(text, times=1, loud=False):
    said = text * times
    return {"said": said.upper() if loud else said}


def fail(mode):
    if mode == "raise":
        raise RuntimeError("the test tool broke")
    if mode == "print":
        print("noise that must not reach the reply stream")
        return {"printed": True}
    return {"error": {"code": "not_found", "message": "nothing called " + mode}}


ECHO_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "times": {"type": "integer"},
        "loud": {"type": "boolean"},
    },
    "required": ["text"],
}
FAIL_SCHEMA = {
    "type": "object",
    "properties": {"mode": {"type": "string"}},
    "required": ["mode"],
}

TOOLS = [
    Tool("echo", "Say the text back.", ECHO_SCHEMA, echo),
    Tool("fail", "Fail in the way asked.", FAIL_SCHEMA, fail),
]


def ask(method, params=None, message_id=1):
    message = {"jsonrpc": "2.0", "id": message_id, "method": method}
    if params is not None:
        message["params"] = params
    return handle(message, NAME, VERSION, TOOLS)


def call(name, arguments=None, message_id=7):
    params = {"name": name}
    if arguments is not None:
        params["arguments"] = arguments
    return ask("tools/call", params, message_id)


def text_of(reply):
    content = reply["result"]["content"]
    assert len(content) == 1 and content[0]["type"] == "text"
    return content[0]["text"]


def served(lines):
    stdin = io.StringIO("".join(line + "\n" for line in lines))
    stdout = io.StringIO()
    assert serve(NAME, VERSION, TOOLS, stdin, stdout) is None
    return stdout.getvalue()


def test_the_listed_versions():
    assert PROTOCOL_VERSIONS == ("2024-11-05", "2025-03-26", "2025-06-18")


def test_a_tool_holds_its_four_parts():
    tool = TOOLS[0]
    assert (tool.name, tool.description, tool.input_schema, tool.handler) == (
        "echo",
        "Say the text back.",
        ECHO_SCHEMA,
        echo,
    )


# Version agreement.


@pytest.mark.parametrize("version", ["2024-11-05", "2025-03-26", "2025-06-18"])
def test_initialize_answers_with_a_listed_client_version(version):
    reply = ask(
        "initialize",
        {"protocolVersion": version, "capabilities": {}, "clientInfo": {"name": "c", "version": "1"}},
    )
    assert reply == {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "protocolVersion": version,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": NAME, "version": VERSION},
        },
    }


@pytest.mark.parametrize("params", [{"protocolVersion": "2099-01-01"}, {}, None])
def test_initialize_answers_with_the_newest_listed_version_otherwise(params):
    reply = ask("initialize", params)
    assert reply["result"]["protocolVersion"] == "2025-06-18"
    assert reply["result"]["capabilities"] == {"tools": {}}


def test_ping_answers_an_empty_result():
    assert ask("ping", message_id="p-1") == {"jsonrpc": "2.0", "id": "p-1", "result": {}}


# The tool list.


def test_the_tool_list_gives_each_tool_name_description_and_schema():
    reply = ask("tools/list", {})
    assert reply["result"] == {
        "tools": [
            {"name": "echo", "description": "Say the text back.", "inputSchema": ECHO_SCHEMA},
            {"name": "fail", "description": "Fail in the way asked.", "inputSchema": FAIL_SCHEMA},
        ]
    }


# Calls.


def test_a_good_call_gives_the_result_as_one_text_part_holding_its_json():
    reply = call("echo", {"text": "ab", "times": 2, "loud": True})
    assert reply["id"] == 7 and reply["jsonrpc"] == "2.0"
    assert reply["result"]["isError"] is False
    assert json.loads(text_of(reply)) == {"said": "ABAB"}


def test_optional_arguments_may_be_left_out():
    reply = call("echo", {"text": "ab"})
    assert reply["result"]["isError"] is False
    assert json.loads(text_of(reply)) == {"said": "ab"}


@pytest.mark.parametrize("arguments", [{}, None, {"times": 2}])
def test_a_missing_argument_gives_an_error_result_naming_it(arguments):
    reply = call("echo", arguments)
    assert "error" not in reply
    assert reply["result"]["isError"] is True
    said = json.loads(text_of(reply))
    assert "text" in said["error"]["message"]
    assert "missing" in said["error"]["message"]


@pytest.mark.parametrize(
    "arguments, name",
    [
        ({"text": 3}, "text"),
        ({"text": None}, "text"),
        ({"text": "a", "times": "2"}, "times"),
        ({"text": "a", "times": 2.5}, "times"),
        ({"text": "a", "times": True}, "times"),
        ({"text": "a", "loud": 1}, "loud"),
        ({"text": "a", "loud": "yes"}, "loud"),
    ],
)
def test_a_wrong_type_gives_an_error_result_naming_the_argument(arguments, name):
    reply = call("echo", arguments)
    assert reply["result"]["isError"] is True
    message = json.loads(text_of(reply))["error"]["message"]
    assert repr(name) in message or name in message.split()


def test_a_handler_that_raises_gives_an_error_result_that_says_so():
    reply = call("fail", {"mode": "raise"})
    assert reply["result"]["isError"] is True
    message = json.loads(text_of(reply))["error"]["message"]
    assert "the test tool broke" in message


def test_a_result_holding_an_error_is_marked_as_an_error():
    reply = call("fail", {"mode": "elsewhere"})
    assert reply["result"]["isError"] is True
    assert json.loads(text_of(reply)) == {
        "error": {"code": "not_found", "message": "nothing called elsewhere"}
    }


def test_after_a_handler_raises_the_next_message_is_still_answered():
    lines = [
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": "fail", "arguments": {"mode": "raise"}}}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"}),
    ]
    replies = [json.loads(line) for line in served(lines).splitlines()]
    assert [reply["id"] for reply in replies] == [1, 2]
    assert replies[0]["result"]["isError"] is True
    assert replies[1]["result"] == {}


@pytest.mark.parametrize("params", [{"name": "nothing"}, {}, {"name": 5}, None])
def test_an_unknown_tool_is_refused_with_invalid_params(params):
    reply = ask("tools/call", params)
    assert "result" not in reply
    assert reply["error"]["code"] == -32602
    assert reply["id"] == 1


# Messages that are not ordinary requests.


def test_an_unknown_method_gives_method_not_found():
    reply = ask("resources/list")
    assert reply["error"]["code"] == -32601
    assert reply["id"] == 1
    assert "resources/list" in reply["error"]["message"]


@pytest.mark.parametrize("method", ["notifications/initialized", "ping", "nothing/here"])
def test_a_notification_gets_no_reply(method):
    assert handle({"jsonrpc": "2.0", "method": method}, NAME, VERSION, TOOLS) is None


@pytest.mark.parametrize("line", ["{not json", "", "[1, 2"])
def test_a_line_that_is_not_json_gives_a_parse_error_with_a_null_id(line):
    reply = handle(line, NAME, VERSION, TOOLS)
    assert reply["error"]["code"] == -32700
    assert reply["id"] is None
    assert reply["jsonrpc"] == "2.0"


def test_a_line_of_text_holding_json_is_read_as_the_message():
    reply = handle(json.dumps({"jsonrpc": "2.0", "id": 4, "method": "ping"}), NAME, VERSION, TOOLS)
    assert reply == {"jsonrpc": "2.0", "id": 4, "result": {}}


def test_an_array_gives_invalid_request():
    message = [{"jsonrpc": "2.0", "id": 1, "method": "ping"}]
    reply = handle(message, NAME, VERSION, TOOLS)
    assert reply["error"]["code"] == -32600
    assert reply["id"] is None
    assert handle(json.dumps(message), NAME, VERSION, TOOLS)["error"]["code"] == -32600


@pytest.mark.parametrize("message", [5, "\"text\"", {"jsonrpc": "2.0", "id": 3}, {"id": 3, "method": 9}])
def test_a_message_that_is_not_a_request_gives_invalid_request(message):
    reply = handle(message, NAME, VERSION, TOOLS)
    assert reply["error"]["code"] == -32600


# Serving over standard input and output.


def test_serve_answers_three_messages_with_exactly_three_reply_lines():
    lines = [
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2025-03-26"}}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
        json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                    "params": {"name": "echo", "arguments": {"text": "hi"}}}),
    ]
    out = served(lines)
    assert out.endswith("\n")
    replies = out.splitlines()
    assert len(replies) == 3
    parsed = [json.loads(line) for line in replies]
    assert [reply["id"] for reply in parsed] == [1, 2, 3]
    assert parsed[0]["result"]["protocolVersion"] == "2025-03-26"
    assert [tool["name"] for tool in parsed[1]["result"]["tools"]] == ["echo", "fail"]
    assert json.loads(parsed[2]["result"]["content"][0]["text"]) == {"said": "hi"}


def test_serve_writes_no_line_for_a_notification_or_a_blank_line():
    lines = [
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        "",
        "   ",
        json.dumps({"jsonrpc": "2.0", "id": 9, "method": "ping"}),
    ]
    replies = served(lines).splitlines()
    assert [json.loads(line)["id"] for line in replies] == [9]


def test_serve_answers_a_line_that_is_not_json_and_goes_on():
    replies = served(["oops", json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"})]).splitlines()
    assert [json.loads(line)["id"] for line in replies] == [None, 2]
    assert json.loads(replies[0])["error"]["code"] == -32700


def test_serve_keeps_what_a_handler_prints_out_of_the_reply_stream(monkeypatch):
    real_out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", real_out)
    replies = served([json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                  "params": {"name": "fail", "arguments": {"mode": "print"}}})])
    assert len(replies.splitlines()) == 1
    assert json.loads(json.loads(replies)["result"]["content"][0]["text"]) == {"printed": True}
    assert real_out.getvalue() == ""


def test_serve_flushes_each_reply():
    class Counting(io.StringIO):
        flushes = 0

        def flush(self):
            Counting.flushes += 1
            super().flush()

    stdin = io.StringIO(
        "".join(json.dumps({"jsonrpc": "2.0", "id": n, "method": "ping"}) + "\n" for n in (1, 2))
    )
    stdout = Counting()
    serve(NAME, VERSION, TOOLS, stdin, stdout)
    assert Counting.flushes >= 2
    assert len(stdout.getvalue().splitlines()) == 2


def test_serve_returns_when_the_input_closes():
    assert served([]) == ""


def test_a_reply_line_holds_no_raw_line_break():
    out = served([json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                              "params": {"name": "echo", "arguments": {"text": "a\nbé"}}})])
    assert len(out.splitlines()) == 1
    reply = json.loads(out)
    assert json.loads(reply["result"]["content"][0]["text"]) == {"said": "a\nbé"}


def test_the_module_imports_no_other_layer():
    source = Path(protocol.__file__).read_text(encoding="utf-8")
    for layer in ("audit_layer", "ospipe", "verification_procedures", "observability", "features"):
        assert "import " + layer not in source and "from " + layer not in source
