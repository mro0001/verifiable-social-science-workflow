"""Software detection for pipeline setup (steps F2 and S1).

Looks for the scholar's software and the workflow's own requirements and
reports what it finds. It writes no file, runs no layer command, and
installs nothing (track F choice 5). For anything missing, install_hint
gives one plain line to print.

detect_state (step S1) looks for what an earlier setup or the scholar has
already done. It reads git's user.name, whether WORKFLOW_MODEL_KEY is set
(never its value), the folders already listed in the audit layer's
settings.yaml, read only, the workflow's own hook commands in the
harness's ~/.claude/settings.json, read only, and the workflow's servers
that claude mcp list names.

Every outside program, claude, forge, git, and the rest, is started only by
run_program, the one runner function, so a test replaces it with a stand-in
that records each call. find_program and folder_exists are the other two
lookups a test replaces. Each lookup is also an argument of detect and
detect_state.
"""
import collections
import json
import os
import re
import shutil
import subprocess
import sys

import importlib.metadata as _metadata

Tool = collections.namedtuple("Tool", "name kind required check")
Found = collections.namedtuple("Found", "name kind required found path version ok note")

# check is (how, target, minimum). how is interpreter, package, command, or
# folder. minimum is a tuple of numbers, or None when any version will do.
SOFTWARE = [
    Tool("python", "language", True, ("interpreter", None, (3, 9))),
    Tool("pyyaml", "package", True, ("package", "PyYAML", None)),
    Tool("python-docx", "package", True, ("package", "python-docx", (1, 2))),
    Tool("pytest", "package", True, ("package", "pytest", None)),
    Tool("pandoc", "build", True, ("command", "pandoc", None)),
    Tool("make", "build", True, ("command", "make", None)),
    Tool("git", "version_control", False, ("command", "git", None)),
    Tool("gh", "version_control", False, ("command", "gh", None)),
    Tool("quarto", "build", False, ("command", "quarto", None)),
    Tool("rscript", "statistics", False, ("command", "Rscript", None)),
    Tool("word", "editor", False, ("folder", "/Applications/Microsoft Word.app", None)),
    Tool("zotero", "citations", False, ("folder", "/Applications/Zotero.app", None)),
    Tool("zotero_data", "citations", False, ("folder", "~/Zotero", None)),
    Tool("claude_code", "harness", False, ("command", "claude", None)),
    Tool("forgecode", "harness", False, ("command", "forge", None)),
]

# A4 paragraph 1. The build procedure's stored test builds were made with this Pandoc.
TESTED_PANDOC = "3.9.0.2"

PACKAGES_LINE = 'python3 -m pip install pyyaml "python-docx>=1.2" pytest'

HINTS = {
    "python": "Install Python 3.9 or later from python.org or your system's package manager",
    "pyyaml": PACKAGES_LINE,
    "python-docx": PACKAGES_LINE,
    "pytest": PACKAGES_LINE,
    "pandoc": "Install Pandoc " + TESTED_PANDOC + " from pandoc.org, the version the stored test builds were made with",
    "make": "Install make, on macOS with xcode-select --install",
    "git": "Install git, on macOS with xcode-select --install",
    "gh": "Install the GitHub command line from cli.github.com if you keep projects on GitHub",
    "quarto": "Install Quarto from quarto.org if your projects use it",
    "rscript": "Install R from cran.r-project.org if your projects use it",
    "word": "Microsoft Word is optional, and any editor that opens .docx files will do",
    "zotero": "Zotero is optional, and any reference manager that exports a BibTeX file will do",
    "zotero_data": "Zotero is optional, and any reference manager that exports a BibTeX file will do",
    "claude_code": "Install Claude Code, the first harness the workflow supports, with npm install -g @anthropic-ai/claude-code",
    "forgecode": "Install ForgeCode, the fallback harness, as forgecode.dev describes",
}


def run_program(argv, timeout=30):
    """(returncode, stdout, stderr) of one outside program, the one runner function.

    Setup starts claude, forge, launchctl, crontab, git, and every other
    outside program only through this function, so a test replaces it with a
    stand-in and no real program runs.
    """
    done = subprocess.run(
        argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        universal_newlines=True, timeout=timeout)
    return done.returncode, done.stdout, done.stderr


def find_program(name):
    """The full path of a program on the command path, or None."""
    return shutil.which(name)


def folder_exists(path):
    """True when the folder or file exists. Nothing inside it is listed or opened."""
    return os.path.exists(path)


def _package_version(name):
    """The installed version of a package, or None when it is not installed."""
    try:
        return _metadata.version(name)
    except _metadata.PackageNotFoundError:
        return None


def _numbers(text):
    """The leading dotted numbers of a version, as a tuple, or () when there are none."""
    match = re.search(r"\d+(?:\.\d+)*", text or "")
    if not match:
        return ()
    return tuple(int(part) for part in match.group(0).split("."))


def _dotted(minimum):
    return ".".join(str(part) for part in minimum)


def _first_line(text):
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def _interpreter(tool, minimum, python_version):
    version = "%d.%d.%d" % tuple(python_version[:3])
    ok = tuple(python_version[:2]) >= tuple(minimum)
    note = "" if ok else "Python %s or later is needed" % _dotted(minimum)
    return Found(tool.name, tool.kind, tool.required, True, sys.executable, version, ok, note)


def _package(tool, target, minimum, package_version):
    version = package_version(target)
    if version is None:
        return Found(tool.name, tool.kind, tool.required, False, "", "", False, "not installed")
    ok = minimum is None or _numbers(version) >= tuple(minimum)
    note = "" if ok else "%s %s or later is needed" % (tool.name, _dotted(minimum))
    return Found(tool.name, tool.kind, tool.required, True, "", version, ok, note)


def _command(tool, target, minimum, which, run_version):
    path = which(target)
    if not path:
        return Found(tool.name, tool.kind, tool.required, False, "", "", False,
                     "not found on the command path")
    try:
        returncode, stdout, stderr = run_version([path, "--version"])
    except (OSError, subprocess.SubprocessError, ValueError):
        returncode, stdout, stderr = None, "", ""
    if returncode != 0:
        return Found(tool.name, tool.kind, tool.required, True, path, "", minimum is None,
                     "found, but %s --version failed, so its version is not known" % target)
    version = _first_line(stdout) or _first_line(stderr)
    ok = minimum is None or _numbers(version) >= tuple(minimum)
    note = ""
    if not ok:
        note = "%s %s or later is needed" % (tool.name, _dotted(minimum))
    elif tool.name == "pandoc" and _numbers(version) != _numbers(TESTED_PANDOC):
        note = "the stored test builds were made with Pandoc %s" % TESTED_PANDOC
    return Found(tool.name, tool.kind, tool.required, True, path, version, ok, note)


def _folder(tool, target, path_exists):
    target = os.path.expanduser(target)
    if path_exists(target):
        return Found(tool.name, tool.kind, tool.required, True, target, "", True, "")
    return Found(tool.name, tool.kind, tool.required, False, "", "", False, "not found")


def detect(which=None, run_version=None, path_exists=None, package_version=_package_version,
           python_version=sys.version_info):
    """One Found for each tool in SOFTWARE, in order.

    A lookup left out is find_program, run_program, or folder_exists, read
    when detect runs so a test can replace each one.
    """
    which = which or find_program
    run_version = run_version or run_program
    path_exists = path_exists or folder_exists
    found = []
    for tool in SOFTWARE:
        how, target, minimum = tool.check
        if how == "interpreter":
            found.append(_interpreter(tool, minimum, python_version))
        elif how == "package":
            found.append(_package(tool, target, minimum, package_version))
        elif how == "command":
            found.append(_command(tool, target, minimum, which, run_version))
        else:
            found.append(_folder(tool, target, path_exists))
    return found


def install_hint(name):
    """One plain line saying how to install a tool in SOFTWARE."""
    if name not in HINTS:
        raise ValueError("no tool named %r" % name)
    return HINTS[name]


def missing_required(found):
    """The required tools that are missing or below their minimum."""
    return [item for item in found if item.required and not item.ok]


# What an earlier setup or the scholar has already done (step S1).

State = collections.namedtuple(
    "State", "git_name model_key_set excluded_folders hooks servers notes")

KEY_VARIABLE = "WORKFLOW_MODEL_KEY"
AUDIT_SETTINGS = "settings.yaml"

# The workflow's own hook commands, told apart from the scholar's own hooks
# by these parts of the command (audit_layer/hooks/INSTALL.md and
# connections/README.md section 3).
HOOK_MARKS = (
    ("capture", "audit_layer/hooks/claude_code_hook.py"),
    ("trigger", "connections trigger hook"),
)

# The three servers connections/README.md section 2 registers.
SERVERS = ("workflow-kb", "workflow-audit", "workflow-events")


def _git_name(which, run):
    git = which("git")
    if not git:
        return ""
    try:
        returncode, stdout, _ = run([git, "config", "--global", "--get", "user.name"])
    except (OSError, subprocess.SubprocessError, ValueError):
        return ""
    if returncode != 0:
        return ""
    return _first_line(stdout)


def git_user_name(which=None, run=None):
    """git's user.name, or "" when git is not found or names none (step S2)."""
    return _git_name(which or find_program, run or run_program)


def _excluded_folders(audit_home, notes):
    """The folders listed in <audit home>/settings.yaml, or None when there is no such list.

    Only the settings file is read. No excluded folder is listed or opened.
    """
    path = os.path.join(os.path.abspath(os.path.expanduser(str(audit_home))), AUDIT_SETTINGS)
    if not os.path.isfile(path):
        return None
    import yaml  # here, so detection runs before PyYAML is known to be installed
    try:
        with open(path, encoding="utf-8") as handle:
            settings = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as error:
        notes.append("the audit settings %s cannot be read (%s)" % (path, error))
        return None
    folders = settings.get("excluded_folders") if isinstance(settings, dict) else None
    if not isinstance(folders, list) or not all(isinstance(folder, str) for folder in folders):
        notes.append("the audit settings %s give no list of excluded_folders" % path)
        return None
    return list(folders)


def _hooks(user_home, notes):
    """For each of the workflow's hook commands, the events of ~/.claude/settings.json holding it."""
    found = dict((kind, []) for kind, _ in HOOK_MARKS)
    path = os.path.join(user_home, ".claude", "settings.json")
    if not os.path.isfile(path):
        return found
    try:
        with open(path, encoding="utf-8") as handle:
            settings = json.load(handle)
    except (OSError, ValueError) as error:
        notes.append("the harness settings %s cannot be read (%s)" % (path, error))
        return found
    hooks = settings.get("hooks") if isinstance(settings, dict) else None
    if not isinstance(hooks, dict):
        return found
    for event, entries in hooks.items():
        commands = []
        for entry in entries if isinstance(entries, list) else []:
            inner = entry.get("hooks") if isinstance(entry, dict) else None
            for hook in inner if isinstance(inner, list) else []:
                if isinstance(hook, dict) and isinstance(hook.get("command"), str):
                    commands.append(hook["command"])
        for kind, mark in HOOK_MARKS:
            if any(mark in command for command in commands) and event not in found[kind]:
                found[kind].append(event)
    return dict((kind, sorted(events)) for kind, events in found.items())


def _servers(which, run, notes):
    """The workflow's servers claude mcp list names, or None when they cannot be known."""
    claude = which("claude")
    if not claude:
        return None
    try:
        returncode, stdout, _ = run([claude, "mcp", "list"], timeout=60)
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        notes.append("claude mcp list could not run (%s)" % error)
        return None
    if returncode != 0:
        notes.append("claude mcp list failed with exit %d" % returncode)
        return None
    named = [line.strip().split(":", 1)[0] for line in (stdout or "").splitlines()
             if ":" in line]
    return [name for name in SERVERS if name in named]


def detect_state(audit_home, user_home=None, environ=None, which=None, run=None):
    """State, what is already set up, found without writing anything.

    git_name is git's user.name or "". model_key_set says whether
    WORKFLOW_MODEL_KEY is set, and the key itself is never kept.
    excluded_folders is the list in the audit settings, or None when that
    file is absent or cannot be read. hooks maps capture and trigger to the
    events of ~/.claude/settings.json holding the workflow's command.
    servers lists the workflow's servers claude mcp list names, or None when
    Claude Code is not found or the list fails. notes says what could not be
    read.
    """
    which = which or find_program
    run = run or run_program
    environ = os.environ if environ is None else environ
    user_home = os.path.expanduser("~") if user_home is None else str(user_home)
    notes = []
    key_set = bool((environ.get(KEY_VARIABLE) or "").strip())
    return State(
        git_name=_git_name(which, run),
        model_key_set=key_set,
        excluded_folders=_excluded_folders(audit_home, notes),
        hooks=_hooks(user_home, notes),
        servers=_servers(which, run, notes),
        notes=notes)
