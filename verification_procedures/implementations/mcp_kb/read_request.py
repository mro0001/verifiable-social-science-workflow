"""Read one call to a knowledge base tool and the exported index given with it.

The call is request.json, {"tool": <name>, "arguments": {...}}. The step routes
it to the step that answers it, or to refuse with the problem stated in one
sentence. A problem in the call has the code bad_request, and a problem in the
index has the code bad_index. It never guesses what a malformed call meant.
"""
import json

import _lib

# Each tool's arguments, as {name: (kind, required)}. A kind is "text", "query"
# (text that is not blank), or "limit" (a whole number from 1 to 50).
TOOLS = {
    "orient_kb": {},
    "search_kb": {"query": ("query", True), "group": ("text", False), "limit": ("limit", False)},
    "list_entries": {"group": ("text", False)},
    "get_entry": {"id": ("text", True)},
    "lookup_provenance": {"id": ("text", True)},
}

KIND_WORDS = {
    "text": "text",
    "query": "text that is not empty",
    "limit": "a whole number from 1 to 50",
}


def fits(kind, value):
    """Whether the argument's value is of its kind."""
    if kind == "limit":
        return type(value) is int and 1 <= value <= 50
    if not isinstance(value, str):
        return False
    return kind == "text" or bool(value.strip())


def load(name):
    """The file's JSON, or None when it cannot be read as JSON."""
    try:
        with open(_lib.path(name), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def request_problem(request):
    """(tool, arguments, problem) for the call, with problem empty when it is in order."""
    if not isinstance(request, dict):
        return "", {}, "The call is not a JSON object with a tool and its arguments."
    tool = request.get("tool")
    arguments = request.get("arguments")
    tool_text = tool if isinstance(tool, str) else ""
    args = arguments if isinstance(arguments, dict) else {}
    extra = sorted(k for k in request if k not in ("tool", "arguments"))
    if extra:
        return tool_text, args, "The call has unexpected keys {}.".format(", ".join(extra))
    if not isinstance(tool, str):
        return tool_text, args, "The call names no tool as text."
    if not isinstance(arguments, dict):
        return tool_text, args, "The call's arguments are not a JSON object."
    if tool not in TOOLS:
        return tool_text, args, "The tool {} is not one of {}.".format(tool, ", ".join(sorted(TOOLS)))
    spec = TOOLS[tool]
    unexpected = sorted(k for k in arguments if k not in spec)
    if unexpected:
        return tool_text, args, "The tool {} takes no argument {}.".format(tool, ", ".join(unexpected))
    for name in sorted(spec):
        kind, required = spec[name]
        if name not in arguments:
            if required:
                return tool_text, args, "The tool {} needs the argument {}.".format(tool, name)
            continue
        if not fits(kind, arguments[name]):
            return tool_text, args, "The argument {} of the tool {} is not {}.".format(
                name, tool, KIND_WORDS[kind])
    return tool_text, args, ""


def index_problem(index):
    """The problem with the exported index, or empty when it can be read."""
    if not isinstance(index, dict):
        return "The index kb_index.json cannot be read as a JSON object."
    version = index.get("schema_version")
    if index.get("schema") != "kb-index" or type(version) is not int or version != 1:
        return "The index is not kb-index version 1."
    entries = index.get("entries")
    if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
        return "The index holds no list of entries."
    return ""


request = load("request.json")
tool, arguments, problem = request_problem(request)
code = "bad_request" if problem else ""
if not problem:
    problem = index_problem(load("kb_index.json"))
    code = "bad_index" if problem else ""

route = "refuse" if problem else tool
_lib.write_json("request_ok.json", {"route": route, "tool": tool, "arguments": arguments,
                                    "problem": problem, "error_code": code})
findings = []
if problem:
    findings.append(_lib.finding("read_request", "warning", tool or "request", problem, code))
_lib.emit_findings("read_request", findings)
