"""Read the git wrapper's call file, calls.jsonl, one JSON object per line.

A line is kept when it is an object with a non-empty text id, an argv list of
text starting with git, a text cwd, text started_at and ended_at, and a whole
number exit_code. Every other line gives a warning whose item is "line <n>". A
repeated id gives a warning whose item is the id, and the first is kept. The
calls kept are sorted by started_at and then id.
"""
import json

import _lib

TEXT_FIELDS = ("cwd", "started_at", "ended_at")


def line_problem(call):
    """What is wrong with one parsed line, or empty when it is a whole git call."""
    if not isinstance(call, dict):
        return "The line is not a JSON object."
    if not isinstance(call.get("id"), str) or not call["id"]:
        return "The call has no id as text that is not empty."
    argv = call.get("argv")
    if not isinstance(argv, list) or not all(isinstance(a, str) for a in argv):
        return "The call's argv is not a list of text."
    if not argv or argv[0] != "git":
        return "The call's argv does not start with git."
    for name in TEXT_FIELDS:
        if not isinstance(call.get(name), str):
            return "The call's {} is not text.".format(name)
    code = call.get("exit_code")
    if type(code) is not int:
        return "The call's exit_code is not a whole number."
    return ""


findings = []
calls = []
seen = set()
for n, line in enumerate(_lib.read_text("calls.jsonl").splitlines(), 1):
    try:
        call = json.loads(line)
    except ValueError:
        findings.append(_lib.finding("read_calls", "warning", "line {}".format(n),
                                     "The line is not JSON.", _lib.cell(line, limit=80)))
        continue
    problem = line_problem(call)
    if problem:
        findings.append(_lib.finding("read_calls", "warning", "line {}".format(n), problem,
                                     _lib.cell(line, limit=80)))
        continue
    if call["id"] in seen:
        findings.append(_lib.finding("read_calls", "warning", call["id"],
                                     "The call id is repeated on line {}, and the first call is kept.".format(n),
                                     "line {}".format(n)))
        continue
    seen.add(call["id"])
    calls.append({"id": call["id"], "argv": call["argv"], "cwd": call["cwd"],
                  "started_at": call["started_at"], "ended_at": call["ended_at"],
                  "exit_code": call["exit_code"]})

calls.sort(key=lambda c: (c["started_at"], c["id"]))
_lib.write_json("calls.json", calls)
_lib.emit_findings("read_calls", findings)
