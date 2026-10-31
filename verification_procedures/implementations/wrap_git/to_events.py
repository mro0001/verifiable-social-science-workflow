"""Turn each git call into one event in the audit layer's event schema.

The subcommand is the first argument after git that is not an option, skipping
the value after -C and after -c. commit is committed, kind action, with its -m
or --message text as the rationale. status, log, diff, show, blame, grep, and
ls-files are searched, kind observation. Anything else is ran, kind action. A
non-zero exit keeps the verb, takes kind blocker, and starts the rationale with
"exit <code>". The object is the command line cut at 200 characters, and the
session is "<YYYY-MM-DD>_<first 12 hex characters of the sha256 of the folder's
real path>", the date taken from started_at.
"""
import hashlib
import os

import _lib

SEARCHES = ("status", "log", "diff", "show", "blame", "grep", "ls-files")
TAKES_VALUE = ("-C", "-c")


def subcommand(argv):
    """(index, name) of the subcommand, or (None, "") when there is none."""
    i = 1
    while i < len(argv):
        arg = argv[i]
        if arg in TAKES_VALUE:
            i += 2
            continue
        if arg.startswith("-"):
            i += 1
            continue
        return i, arg
    return None, ""


def commit_message(args):
    """The -m or --message text of a commit's arguments, paragraphs joined as git joins them."""
    parts = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("-m", "--message"):
            if i + 1 < len(args):
                parts.append(args[i + 1])
            i += 2
            continue
        if arg.startswith("--message="):
            parts.append(arg[len("--message="):])
        elif arg.startswith("-m") and not arg.startswith("--"):
            parts.append(arg[2:])
        i += 1
    return "\n\n".join(parts)


def session_id(call):
    key = hashlib.sha256(os.path.realpath(call["cwd"]).encode("utf-8")).hexdigest()[:12]
    return "{}_{}".format(call["started_at"][:10], key)


def to_event(call):
    argv = call["argv"]
    at, name = subcommand(argv)
    rationale = ""
    if name == "commit":
        verb, kind = "committed", "action"
        rationale = commit_message(argv[at + 1:])
    elif name in SEARCHES:
        verb, kind = "searched", "observation"
    else:
        verb, kind = "ran", "action"
    if call["exit_code"] != 0:
        kind = "blocker"
        rationale = "exit {}".format(call["exit_code"]) + (", " + rationale if rationale else "")
    return {"harness": "wrappers", "harness_session_id": session_id(call), "source_id": call["id"],
            "verb": verb, "kind": kind, "object": " ".join(argv)[:200], "rationale": rationale,
            "role": ""}


_lib.write_json("events.json", [to_event(c) for c in _lib.read_json("calls.json")])
