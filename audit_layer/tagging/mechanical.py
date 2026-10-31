"""The mechanical tagging pass, which tags each tool call by rule, with no model.

Appendix A2.4 "Metadata tagging" fills metadata in two passes. Table A4 gives
the mechanical pass, a program with no model, the tools a session used, each
file touched with its role, and each action with a verb from a fixed list and
whether it was an action or an observation. A read or a search takes the verb
searched and the kind observation (plan choice 3).

tag gives a tool call's verb, kind, object, and role. To make a whole event
(events.py), capture adds the harness, the harness's session id, and the
call's own id, and leaves the rationale empty, since Table A4 gives decisions
their rationale in the model pass. The rules use Claude Code's tool names.
"""
import os
import re
from collections.abc import Mapping
from typing import Any, Dict, Iterable, List, Optional

# The pass's version, which capture names in the method of every row it
# writes. Raise it when a change alters how a tool call is tagged.
VERSION = 1

# Tools that act on one file, named by the input file_path, with the verb,
# kind, and role each gives it.
_FILE_TOOLS = {
    "Write": ("wrote", "action", "produced"),
    "Edit": ("edited", "action", "edited"),
    "Read": ("searched", "observation", "read"),
}

# Tools that search, with the input that holds the pattern or address. A web
# search's object is its query.
_SEARCH_TOOLS = {
    "Grep": "pattern",
    "Glob": "pattern",
    "WebSearch": "query",
    "WebFetch": "url",
}

# A command holding the words git commit is a commit. Words inside a longer
# word, such as legit, do not count.
_COMMIT = re.compile(r"\bgit commit\b")

# A command holding one of these words is a test or check.
_CHECKS = re.compile(r"\bpytest\b|\bvg\.py (?:check|verify|score)\b|\bospipe check\b")


def tag(tool_call, cwd: str) -> Dict[str, str]:
    """The verb, kind, object, and role of one tool call.

    The tool call needs a name and an input, as the adapter's ToolCall has. A
    file is named by its full path, with a relative path resolved against cwd,
    the session's working folder. A pattern, an address, or a command is kept
    as given. A call whose input lacks what its rule reads, such as a Write
    with no file path, is tagged like any other tool.
    """
    name = tool_call.name
    given = tool_call.input if isinstance(tool_call.input, Mapping) else {}
    if name in _FILE_TOOLS:
        path = _text(given.get("file_path"))
        if path is not None:
            verb, kind, role = _FILE_TOOLS[name]
            return _fields(verb, kind, _resolve(path, cwd), role)
    elif name in _SEARCH_TOOLS:
        target = _text(given.get(_SEARCH_TOOLS[name]))
        if target is not None:
            return _fields("searched", "observation", target, "")
    elif name == "Bash":
        command = _text(given.get("command"))
        if command is not None:
            if _COMMIT.search(command):
                return _fields("committed", "action", command, "")
            if _CHECKS.search(command):
                return _fields("verified", "observation", command, "")
            return _fields("ran", "action", command, "")
    return _fields("ran", "action", name, "")


def session_tags(tool_calls: Iterable) -> List[str]:
    """The tools the session used, each once, in the order it first used them."""
    tools: List[str] = []
    for tool_call in tool_calls:
        if tool_call.name not in tools:
            tools.append(tool_call.name)
    return tools


def _fields(verb: str, kind: str, object_: str, role: str) -> Dict[str, str]:
    return {"verb": verb, "kind": kind, "object": object_, "role": role}


def _text(value: Any) -> Optional[str]:
    """The value when it is text that is not blank, else None."""
    if isinstance(value, str) and value.strip():
        return value
    return None


def _resolve(path: str, cwd: str) -> str:
    """The file's full path. A relative path is joined to cwd, and . and .. parts are worked out."""
    return os.path.normpath(os.path.join(cwd, path))
