"""The command wrapper, which logs each command the scholar runs through it.

The proposal connects the scholar's statistical software, version control,
and build tools through wrappers (Overview para 2, Figure 2), and appendix
A2.2 says wrappers are small programs that log each action in the scholar's
external software for the audit layer. Figure A2 says a wrapper logs each
action and never interrupts the call.

python3 -m connections wrap -- PROGRAM [ARGS...] runs the program with the
scholar's own input and output and exits with its code. Afterwards it writes
one event for the call and one wrote event, role produced, for each file the
call created or changed under its working folder, found by comparing sizes
and change times before and after (Track D choice 4). The call's verb follows
the rules the reconciliation fixes for wrapper events (item 7). Nothing is
walked or written in an excluded folder or while the audit settings file is
missing (choice 3), and a failure to log never changes what the call prints
or returns.
"""
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from typing import Dict, List, Optional, Tuple

from connections.events import append_event, make_event
from connections import home
from connections.home import excluded_folders, recording_allowed

# The snapshot stops after this many files, so a call in a very large folder
# is not held up by the walk.
SNAPSHOT_LIMIT = 20000

# Folders the snapshot never walks, besides those whose names start with a dot.
SKIPPED_FOLDERS = ("__pycache__", "node_modules")

# The object of a call event is its command line cut at this many characters
# (reconciliation item 7).
OBJECT_LIMIT = 200

# Git, as Track G's git wrapper graph reads it (reconciliation item 7). The
# subcommand is the first argument after git that is not an option, skipping
# the value after -C and after -c.
_GIT_VALUE_OPTIONS = ("-C", "-c")
_GIT_SEARCHES = ("status", "log", "diff", "show", "blame", "grep", "ls-files")

# Any other program follows the slice's mechanical pass for a Bash command,
# copied from audit_layer/tagging/mechanical.py and never imported, since
# connections imports no audit layer code. A change there is copied here by
# hand.
_COMMIT = re.compile(r"\bgit commit\b")
_CHECKS = re.compile(r"\bpytest\b|\bvg\.py (?:check|verify|score)\b|\bospipe check\b")


def call_verb(argv: List[str]) -> Tuple[str, str]:
    """The verb and kind of a call that ended well.

    For git, commit is committed and an action, status, log, diff, show,
    blame, grep, and ls-files are searched and an observation, and anything
    else is ran and an action. For any other program, the command line holding
    the words git commit is committed, one holding a test or check command is
    verified and an observation, and anything else is ran and an action.
    """
    if _is_git(argv):
        sub = _git_subcommand(argv)
        if sub == "commit":
            return ("committed", "action")
        if sub in _GIT_SEARCHES:
            return ("searched", "observation")
        return ("ran", "action")
    command = " ".join(argv)
    if _COMMIT.search(command):
        return ("committed", "action")
    if _CHECKS.search(command):
        return ("verified", "observation")
    return ("ran", "action")


def snapshot(folder: str) -> Dict[str, Tuple[int, int]]:
    """The size and change time of each file under folder, by real path.

    The walk skips .git and every folder whose name starts with a dot,
    __pycache__, node_modules, and every excluded folder, follows no folder
    links, and stops after SNAPSHOT_LIMIT files. Files are taken in name order,
    so two walks of the same folder cover the same files.
    """
    folders = home.case_rules(excluded_folders() or [])
    found: Dict[str, Tuple[int, int]] = {}
    for root, dirs, files in os.walk(folder):
        dirs[:] = sorted(
            name
            for name in dirs
            if not name.startswith(".")
            and name not in SKIPPED_FOLDERS
            and not _inside(os.path.join(root, name), folders)
        )
        for name in sorted(files):
            if len(found) >= SNAPSHOT_LIMIT:
                return found
            path = os.path.realpath(os.path.join(root, name))
            if _inside(path, folders):
                continue
            try:
                facts = os.stat(path)
            except OSError:
                continue
            found[path] = (facts.st_size, facts.st_mtime_ns)
    return found


def run_wrapped(argv: List[str], cwd: Optional[str] = None) -> int:
    """Run the program in argv in cwd, log the call, and give its exit code.

    A program that cannot be found prints <program>: command not found and
    gives 127, with no event. A program ended by a signal gives 128 plus the
    signal's number. Ctrl-C reaches the program, and the wrapper keeps
    waiting, so the program decides how to stop.
    """
    folder = os.path.abspath(cwd if cwd is not None else os.getcwd())
    program = argv[0]
    found = shutil.which(program)
    if found is None:
        sys.stderr.write(f"{program}: command not found\n")
        sys.stderr.flush()
        return 127

    before = None
    try:
        if recording_allowed(folder):
            before = snapshot(folder)
    except Exception:
        before = None

    started = time.monotonic()
    code = _run(found, argv, folder)
    duration = time.monotonic() - started

    if before is not None:
        try:
            _log(argv, folder, code, duration, before)
        except Exception:
            pass
    return code


def _run(found: str, argv: List[str], folder: str) -> int:
    """Run the program with the scholar's input and output, and wait for it."""
    # A handler that does nothing, set before the program starts, so Ctrl-C
    # leaves the wrapper waiting. A program's own signal handling is reset at
    # its start, so the program still gets Ctrl-C as it would unwrapped.
    previous = None
    try:
        previous = signal.signal(signal.SIGINT, _keep_waiting)
    except (ValueError, OSError):
        previous = None
    try:
        try:
            process = subprocess.Popen(argv, executable=found, cwd=folder)
        except OSError as error:
            # Found but could not be started, which a shell reports as 126.
            sys.stderr.write(f"{argv[0]}: {error.strerror or error}\n")
            sys.stderr.flush()
            return 126
        code = process.wait()
    finally:
        if previous is not None:
            try:
                signal.signal(signal.SIGINT, previous)
            except (ValueError, OSError):
                pass
    if code < 0:
        return 128 + (-code)
    return code


def _keep_waiting(signum, frame):
    return None


def _log(argv, folder, code, duration, before):
    """Write the call event and a wrote event for each file created or changed."""
    after = snapshot(folder)
    command = " ".join(argv)[:OBJECT_LIMIT]
    name = os.path.basename(argv[0])
    verb, kind = call_verb(argv)
    rationale = _commit_message(argv) if verb == "committed" and _is_git(argv) else ""
    if code != 0 and _is_git(argv):
        kind = "blocker"
        rationale = f"exit {code}" + (f"; {rationale}" if rationale else "")
    extra = {"exit_code": code, "duration_s": round(duration, 3), "files_scanned": len(after)}
    append_event(
        make_event(folder, verb, kind, command, rationale=rationale, program=name, extra=extra)
    )
    for path in sorted(after):
        if before.get(path) != after[path]:
            append_event(
                make_event(
                    folder,
                    "wrote",
                    "action",
                    path,
                    role="produced",
                    program=name,
                    extra={"by": command},
                )
            )


def _is_git(argv: List[str]) -> bool:
    return os.path.basename(argv[0]) == "git"


def _git_subcommand(argv: List[str]) -> str:
    place = _git_subcommand_place(argv)
    return argv[place] if place else ""


def _git_subcommand_place(argv: List[str]) -> int:
    """Where the subcommand sits in argv, or 0 when there is none."""
    skip = False
    for place in range(1, len(argv)):
        arg = argv[place]
        if skip:
            skip = False
            continue
        if arg in _GIT_VALUE_OPTIONS:
            skip = True
            continue
        if arg.startswith("-"):
            continue
        return place
    return 0


def _commit_message(argv: List[str]) -> str:
    """The -m or --message text of a git commit, paragraphs joined as git joins them."""
    place = _git_subcommand_place(argv)
    args = argv[place + 1 :] if place else []
    messages = []
    index = 0
    while index < len(args):
        arg = args[index]
        value = None
        if arg == "--message":
            if index + 1 < len(args):
                value = args[index + 1]
                index += 1
        elif arg.startswith("--message="):
            value = arg[len("--message=") :]
        elif arg.startswith("-") and not arg.startswith("--") and "m" in arg[1:]:
            rest = arg[arg.index("m", 1) + 1 :]
            if rest:
                value = rest
            elif index + 1 < len(args):
                value = args[index + 1]
                index += 1
        if value is not None:
            messages.append(value)
        index += 1
    return "\n\n".join(messages)


def _inside(path: str, rules: List[home.Rule]) -> bool:
    """Whether the real path of path is one of the listed folders or inside one.

    The same comparison as recording_allowed in connections/home.py, made here
    with the list read and each folder's disk checked once for the whole walk.
    """
    return home.inside(path, rules)
