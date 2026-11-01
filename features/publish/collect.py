"""Read a verified project for publishing (publish design A.1, A.2, R1 to R3, R7 to R9, R13, R17).

collect() reads the scholar's answers, the product map that ospipe products
--json gives (through features.organizer.inventory.read_map and the layer
runner), each product's ledger, each results file and the report that goes
with it, and the project's files after the rules that leave files out. It
writes nothing. Each refusal is a PublishError whose message starts in lower
case, so it can follow "publish build stopped, ".

The folders the scholar excluded are the union of system.yaml's list and the
audit home's settings.yaml list. No file inside one is opened, and a project,
a sessions also_folders entry, or a runs folder inside one stops the command.
So does an excluded folder inside the project or inside an also_folders entry,
since the session index could name its files, unless the index is skipped.
"""
import collections
import datetime
import fnmatch
import json
import os
import posixpath
import re
import shutil
import subprocess
import unicodedata

import yaml

from features.layers import LayerMissing, run_layer
from features.organizer.inventory import read_map
from features.publish import model
from features.setup.detect import _excluded_folders

MAKEFILE = "Makefile"
LEDGER = "BUILDS.md"
GITIGNORE = ".gitignore"
PIPELINE = "pipeline.yaml"
DEFAULT_NUMBERS = "numbers.yml"
DEFAULT_BIB = "refs.bib"
DEFAULT_VERIFICATION = "verification"
RUNS_IN_WORKFLOW = ("verification_procedures", "runs")

ANSWER_FIELDS = ("title", "summary", "repo_url", "workflow_url", "workflow_folder", "runs",
                 "exclude", "harness_names", "notes", "files", "anonymous", "sessions", "check",
                 "github", "phase_runs")
NAME_PART_LETTERS = 3
NOTE_STREAMS = ("prose", "references", "data", "build", "record")
SESSION_DEFAULTS = collections.OrderedDict((
    ("skip", False),
    ("also_folders", []),
    ("no_summaries", False),
    ("withhold", []),
    ("scrub_terms", []),
))
CHECK_DEFAULTS = collections.OrderedDict((
    ("terms", []),
    ("allow", []),
    ("max_file_mb", 100),
    ("warn_file_mb", 50),
    ("rebuild", True),
))
GITHUB_DEFAULTS = collections.OrderedDict((
    ("repo_name", ""),
    ("owner", ""),
    ("visibility", "private"),
    ("create_with", "none"),
    ("remote_url", ""),
    ("branch", "main"),
    ("message", "First commit of the verification repository"),
))
ALLOW_KEYS = ("text", "path")
PUBLIC_ID = re.compile(r"^S[0-9a-f]{12}$")
REPO_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
RUN_NAME = re.compile(r"^[A-Za-z0-9._-]+$")

# The rules that leave files out (design A.2 and R9). Each left-out entry is
# (relpath, rule, why), with a folder's relpath ending in "/".
FIXED_PARTS = collections.OrderedDict((
    (".git", "version control data, which the repository gets fresh"),
    ("__pycache__", "compiled Python files"),
    (".homes", "the workflow's homes, which hold the record and the settings"),
    (".organizer", "the organizer's own records"),
    ("node_modules", "installed packages"),
))
TOP_FOLDERS = collections.OrderedDict((
    ("audit", "raw session ids and the AI's words, kept private"),
    ("sources", "source texts, most not openly licensed"),
    ("notes", "the scholar's notes"),
    ("ship", "replication folders, made again by ospipe emit"),
    ("sessions", "the session index, written fresh from the record"),
))
RUNS_FOLDER = "verification/runs"
RUN_FOLDER_WHY = "a run folder, whose manifest names local paths and the model service"
FINDER_WHY = "a file the Finder writes"
COMPILED_SUFFIXES = (".pyc",)
LOG_SUFFIXES = (".aux", ".log", ".log.txt")
EDITOR_FOLDERS = (".claude", ".vscode", ".idea", ".ipynb_checkpoints", ".Rproj.user", ".venv",
                  "venv", ".quarto", ".pytest_cache", ".cursor", ".specstory", ".continue", ".codex",
                  ".gemini", ".windsurf")
# An AI tool that keeps its saved chats in the project, such as aider, names them .aider*.
AI_TOOL_PREFIX = ".aider"
HISTORY_FILES = (".Rhistory", ".python_history", ".viminfo", ".lesshst", ".RData")
HISTORY_SUFFIXES = ("_history", ".history")
SETTINGS_FILES = (".envrc",)
EDITOR_WHY = "a folder an editor or a tool keeps for itself"
AI_TOOL_WHY = "a file or folder where an AI tool keeps its saved chats or its own records"
HISTORY_WHY = "a shell or editor history file, or a saved R workspace"
SETTINGS_WHY = "a file of environment settings, which may hold keys"
UNREADABLE_WHY = "a folder that cannot be read"
HOME_WHY = "a workflow home, which holds the record and the settings"
EXCLUDED_WHY = "a folder the scholar excluded, left out without being opened"
EXCLUDE_WHY = "listed under exclude in the answers file"
SYMLINK_WHY = "a symbolic link"
IGNORED_BY_GIT = "ignored by git"
STALE_REPORT_WHY = "a report whose results differ from the project's results file"
GIT_NOTE = "git could not be run, so only the .gitignore rules this command reads were applied"
UNREADABLE_NOTE = ("%d %s cannot be read, so %s left out; give this account read access and"
                   " build again to publish %s")
NO_NAME_NOTE = ("system.yaml gives no scholar_name, so in this anonymous build the session index"
                " withholds and the check looks for only the names the answers give")
WORDS_LEFT_NOTE = ("the sessions scrub_terms leave out %d %s of the scholar's name, so the session"
                   " index keeps %s and the check looks for %s only within the full name")
INSIDE_PROJECT_STOP = ("an excluded folder lies inside the project, so the session index could"
                       " name its files; move it out or leave the project out of the index with"
                       " sessions: {skip: true}")
INSIDE_ALSO_STOP = ("an excluded folder lies inside a sessions also_folders entry, so the session"
                    " index could name its files; move it out, take that entry out of"
                    " also_folders, or leave the project out of the index with sessions:"
                    " {skip: true}")

WORKFLOW_LINE = re.compile(r"^(\s*WORKFLOW\s*\??=)")
OSPIPE_LINE = re.compile(r"^\s*OSPIPE\s*\??=\s*PYTHONPATH='[^']*'\s+python3 -m ospipe\s*$")
OSPIPE_BY_WORKFLOW = "OSPIPE ?= PYTHONPATH='$(WORKFLOW)/ospipe' python3 -m ospipe"
WORKFLOW_VAR = "workflow_var"
PYTHONPATH_ENV = "pythonpath_env"

BIB_ENTRY = re.compile(r"^@\w+\{")
HEX_SHA = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
SEPARATOR = re.compile(r"^:?-{3,}:?$")

DECIDED_REPORT = "report_decided.md"
RUN_REPORT = ("files", "report.md")
RUN_RESULTS = "results.json"
RUN_MANIFEST = "manifest.json"
PHASE_STREAM = "data_phases"
DECIDED_NOTE = ("run %s was decided after its results reached the project; run"
                " handoffs/results_to_pipeline.py again")
NO_REPORT_NOTE = ("no report for run %s was found whose results match the project's; the"
                  " report is left out")
OTHER_RUN_NOTE = ("the runs folder holds another run named %s, whose results differ from the"
                  " project's, so its report is not used")

# prefix holds the parts from the folder of a .gitignore above the project down to the
# project, casefolded, so its rules are matched against the project's paths as git does.
GitignoreRule = collections.namedtuple(
    "GitignoreRule", "base source pattern segments anchored dir_only prefix", defaults=((),))
OUTER_SOURCE = "a .gitignore in a folder above the project"
EXCLUDE_SOURCE = "the info/exclude file of the repository that holds the project"


# Small helpers.


def _absolute(path):
    return os.path.abspath(os.path.expanduser(str(path)))


def _normalized(path):
    return os.path.realpath(os.path.expanduser(str(path)))


def _relative(path):
    """A path inside the project, with "/" between parts and no "./" or trailing "/"."""
    text = str(path).replace(os.sep, "/").strip()
    text = posixpath.normpath(text) if text else ""
    return "" if text == "." else text


def _join(folder, name):
    return name if folder in ("", ".") else folder + "/" + name


def _escapes(relpath):
    return relpath.startswith("/") or ".." in relpath.split("/")


def _read_bytes(path):
    with open(path, "rb") as handle:
        return handle.read()


def _parse_json(data):
    try:
        found = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return found if isinstance(found, dict) else None


def _without_decisions(results):
    return dict((key, value) for key, value in results.items() if key != "decisions")


def _same_results(first, second):
    """Whether two results files agree once their decisions are set aside (design R3)."""
    return _without_decisions(first) == _without_decisions(second)


def _label(names):
    names = list(names)
    if len(names) <= 1:
        return "".join(names)
    if len(names) == 2:
        return "%s and %s" % (names[0], names[1])
    return "%s, and %s" % (", ".join(names[:-1]), names[-1])


# The answers file (design A.1, R10, R13).


def _is_text(value):
    return isinstance(value, str)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _bad(field, rule):
    return model.PublishError("the answers file's %s must be %s" % (field, rule))


def _text(given, field, default):
    value = given.get(field)
    if value is None:
        return default
    if not _is_text(value):
        raise _bad(field, "text")
    return value


def _flag(given, field, where, default):
    value = given.get(field)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise _bad(where, "true or false")
    return value


def _full_path(value, where):
    if not _is_text(value) or not value.strip():
        raise _bad(where, "a full path starting with / or ~")
    value = value.strip()
    if not value.startswith(("/", "~")) or not os.path.isabs(os.path.expanduser(value)):
        raise _bad(where, "a full path starting with / or ~")
    return _absolute(value)


def _text_list(value, where):
    if value is None:
        return []
    if not isinstance(value, list) or not all(_is_text(item) and item.strip() for item in value):
        raise _bad(where, "a list of text")
    return [item.strip() for item in value]


def _text_map(value, where):
    if value is None:
        return collections.OrderedDict()
    if not isinstance(value, dict) or not all(
            _is_text(key) and _is_text(text) for key, text in value.items()):
        raise _bad(where, "a mapping of text to text")
    return collections.OrderedDict((key, value[key]) for key in value)


def _mapping(value, where):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise _bad(where, "a mapping")
    return value


def _unknown(given, known, prefix, unknown):
    for key in given:
        if key not in known:
            unknown.append("%s%s" % (prefix, key))


def _exclude(value):
    entries = []
    for entry in _text_list(value, "exclude"):
        folder = entry.endswith("/")
        relpath = _relative(entry)
        if not relpath or _escapes(entry.replace("\\", "/")) or _escapes(relpath):
            raise _bad("exclude", "a list of paths inside the project, without '..'")
        entries.append(relpath + "/" if folder else relpath)
    return entries


def _harness_names(value):
    names = collections.OrderedDict(model.HARNESS_NAMES)
    names.update(_text_map(value, "harness_names"))
    return names


def _notes(value):
    notes = _text_map(value, "notes")
    for key in notes:
        if key not in NOTE_STREAMS:
            raise _bad("notes", "a mapping whose keys are among %s" % ", ".join(NOTE_STREAMS))
    return notes


def _files(value):
    files = _text_map(value, "files")
    found = collections.OrderedDict()
    for key in files:
        relpath = _relative(key)
        if not relpath or _escapes(key.replace("\\", "/")) or _escapes(relpath):
            raise _bad("files", "a mapping from paths inside the project to text")
        # Written the way project/README.md lists its entries, so ./tools/ is tools/.
        found[relpath + "/" if key.strip().endswith("/") else relpath] = files[key]
    return found


def name_terms(name):
    """The scholar's name and each of its words with at least three letters that does
    not end with ".", once each, in order: "A. Jordan Doe" gives "A. Jordan Doe",
    "Jordan", and "Doe". A name that is not text, or is empty, gives []."""
    if not _is_text(name) or not name.strip():
        return []
    name = " ".join(name.split())
    terms = []
    seen = set()
    for term in [name] + name.split():
        if term != name and (term.endswith(".") or
                             sum(1 for letter in term if letter.isalpha()) < NAME_PART_LETTERS):
            continue
        if term.casefold() not in seen:
            seen.add(term.casefold())
            terms.append(term)
    return terms


def term_pattern(term):
    """The pattern the check matches a term with: its words in composed form, with any
    space, or none, or one '.', '_', or '-' between them, and no letter just before or
    after, case ignored."""
    tokens = [re.escape(token) for token in unicodedata.normalize("NFC", term).split()]
    return re.compile(r"(?<![^\W\d_])" + r"(?:\s+|[._-]?)".join(tokens) + r"(?![^\W\d_])", re.I)


def _sessions(value, system, unknown, anonymous):
    given = _mapping(value, "sessions")
    _unknown(given, SESSION_DEFAULTS, "sessions.", unknown)
    sessions = dict(SESSION_DEFAULTS)
    sessions["skip"] = _flag(given, "skip", "sessions skip", False)
    sessions["no_summaries"] = _flag(given, "no_summaries", "sessions no_summaries", False)
    folders = given.get("also_folders")
    if folders is None:
        folders = []
    if not isinstance(folders, list):
        raise _bad("sessions also_folders", "a list of full paths")
    sessions["also_folders"] = [_full_path(folder, "sessions also_folders") for folder in folders]
    withhold = _text_list(given.get("withhold"), "sessions withhold")
    for public_id in withhold:
        if not PUBLIC_ID.match(public_id):
            raise _bad("sessions withhold", "a list of public session ids, S and 12 hex characters")
    sessions["withhold"] = withhold
    name = system.get("scholar_name") if isinstance(system, dict) else None
    words = name_terms(name) if anonymous else []
    if given.get("scrub_terms") is None:
        # Anonymous by default: the scholar's name and its words are scrubbed.
        sessions["scrub_terms"] = words
    else:
        # The answers choose the words; the full name is always withheld when anonymous.
        chosen = _text_list(given.get("scrub_terms"), "sessions scrub_terms")
        if words and words[0].casefold() not in [term.casefold() for term in chosen]:
            chosen = [words[0]] + chosen
        sessions["scrub_terms"] = chosen
    return sessions


def _allow(value):
    if value is None:
        return []
    if not isinstance(value, list):
        raise _bad("check allow", "a list of text or of mappings with text and path")
    entries = []
    for entry in value:
        if _is_text(entry) and entry:
            entries.append(entry)
            continue
        if isinstance(entry, dict) and entry and all(key in ALLOW_KEYS for key in entry) \
                and all(_is_text(text) and text for text in entry.values()):
            entries.append(collections.OrderedDict((key, entry[key]) for key in ALLOW_KEYS
                                                   if key in entry))
            continue
        raise _bad("check allow", "a list of text or of mappings with text and path")
    return entries


def _check(value, unknown):
    given = _mapping(value, "check")
    _unknown(given, CHECK_DEFAULTS, "check.", unknown)
    check = dict(CHECK_DEFAULTS)
    check["terms"] = _text_list(given.get("terms"), "check terms")
    check["allow"] = _allow(given.get("allow"))
    for field in ("max_file_mb", "warn_file_mb"):
        number = given.get(field)
        if number is None:
            continue
        if not _is_number(number) or number <= 0:
            raise _bad("check %s" % field, "a number above 0")
        check[field] = number
    check["rebuild"] = _flag(given, "rebuild", "check rebuild", True)
    return check


def _github(value, unknown):
    if value is None:
        return None
    given = _mapping(value, "github")
    _unknown(given, GITHUB_DEFAULTS, "github.", unknown)
    github = dict(GITHUB_DEFAULTS)
    for field in GITHUB_DEFAULTS:
        found = given.get(field)
        if found is None:
            continue
        if not _is_text(found):
            raise _bad("github %s" % field, "text")
        github[field] = found.strip()
    if not github["repo_name"]:
        raise model.PublishError("the github block needs repo_name")
    if not REPO_NAME.match(github["repo_name"]):
        raise _bad("github repo_name", "made of letters, digits, '.', '_', and '-'")
    if github["visibility"] not in ("private", "public"):
        raise _bad("github visibility", "private or public")
    if github["create_with"] not in ("gh", "none"):
        raise _bad("github create_with", "gh or none")
    for field in ("branch", "message"):
        if not github[field]:
            raise _bad("github %s" % field, "text that is not empty")
    if github["create_with"] == "none" and not github["remote_url"]:
        raise model.PublishError("the github block needs remote_url when create_with is none")
    if github["create_with"] == "gh" and not github["owner"]:
        raise model.PublishError("the github block needs owner when create_with is gh")
    return github


def _phase_runs(value):
    given = _mapping(value, "phase_runs")
    runs = collections.OrderedDict()
    rule = "a mapping from a product or group to a mapping from a phase to a run id"
    for key, phases in given.items():
        if not _is_text(key) or not isinstance(phases, dict):
            raise _bad("phase_runs", rule)
        chosen = collections.OrderedDict()
        for phase, run_id in phases.items():
            if phase not in model.PHASES or not _is_text(run_id) or not RUN_NAME.match(run_id) \
                    or run_id in (".", ".."):
                raise _bad("phase_runs", "%s, with the phases %s" % (rule, ", ".join(model.PHASES)))
            chosen[phase] = run_id
        runs[key] = chosen
    return runs


SSH_URL = re.compile(r"^(?:ssh://)?git@([A-Za-z0-9.-]+)[:/](.+?)/*$")


def web_url(url):
    """A repository's address as a web page: an address like git@host:owner/repo.git, or
    ssh://git@host/owner/repo.git, becomes https://host/owner/repo, since the README's
    clone line is for anyone and holds no account name. Other text is kept."""
    found = SSH_URL.match(url.strip())
    if not found:
        return url.strip()
    path = found.group(2)
    if path.endswith(".git"):
        path = path[:-len(".git")]
    return "https://%s/%s" % (found.group(1), path.lstrip("/"))


def _workflow_folder(url):
    last = url.strip().rstrip("/").split("/")[-1]
    return last[:-len(".git")] if last.endswith(".git") else last


def read_answers(path, project_dir, system):
    """The answers in the YAML file at path, checked, with every default filled.

    path None gives every default. A key this command does not use goes to
    unknown_keys (sessions, check, and github keys as "sessions.<key>" and so
    on). A value that is wrong raises PublishError. Paths in runs and in
    sessions also_folders must be full paths, starting with / or ~. anonymous
    is true unless given false, and then sessions scrub_terms, when the answers
    give none, are name_terms of the scholar's name in system.yaml; when the
    answers give some, they choose the words, and the full name is added when
    they leave it out. With anonymous false they are only what the answers give.
    A repository address of the git@host:owner/repo form becomes its web
    address, https://host/owner/repo.
    """
    given = {}
    if path is not None:
        try:
            with open(str(path), encoding="utf-8") as handle:
                given = yaml.safe_load(handle)
        except (OSError, UnicodeDecodeError) as error:
            raise model.PublishError("the answers file %s cannot be read (%s)" % (path, error))
        except yaml.YAMLError as error:
            raise model.PublishError("the answers file %s is not YAML that can be read (%s)"
                                     % (path, str(error).splitlines()[0]))
        if given is None:
            given = {}
        if not isinstance(given, dict):
            raise model.PublishError("the answers file %s must be a mapping of fields" % path)
    system = system if isinstance(system, dict) else {}
    unknown = []
    _unknown(given, ANSWER_FIELDS, "", unknown)

    folder = os.path.basename(os.path.normpath(_absolute(project_dir)))
    workflow_url = web_url(_text(given, "workflow_url", model.WORKFLOW_URL))
    if not workflow_url:
        raise _bad("workflow_url", "text that is not empty")
    workflow_folder = _text(given, "workflow_folder", _workflow_folder(workflow_url)).strip()
    if not REPO_NAME.match(workflow_folder) or workflow_folder in (".", ".."):
        raise _bad("workflow_folder", "one folder name made of letters, digits, '.', '_', and '-'")
    if given.get("runs") is None:
        root = system.get("workflow_root") or ""
        runs = os.path.join(_absolute(root), *RUNS_IN_WORKFLOW) if root else ""
    else:
        runs = _full_path(given.get("runs"), "runs")

    title = _text(given, "title", "").strip() or "Verification reports for %s" % folder
    anonymous = _flag(given, "anonymous", "anonymous", True)
    return model.Answers(
        title=title,
        summary=_text(given, "summary", ""),
        repo_url=web_url(_text(given, "repo_url", "")),
        workflow_url=workflow_url,
        workflow_folder=workflow_folder,
        runs=runs,
        exclude=_exclude(given.get("exclude")),
        harness_names=_harness_names(given.get("harness_names")),
        notes=_notes(given.get("notes")),
        files=_files(given.get("files")),
        anonymous=anonymous,
        sessions=_sessions(given.get("sessions"), system, unknown, anonymous),
        check=_check(given.get("check"), unknown),
        github=_github(given.get("github"), unknown),
        phase_runs=_phase_runs(given.get("phase_runs")),
        unknown_keys=sorted(unknown),
    )


# Excluded folders and homes (design R7, R9).


def _parts(path):
    return [unicodedata.normalize("NFC", part).casefold()
            for part in os.path.normpath(str(path)).split(os.sep) if part]


def inside(path, folder):
    """Whether path is folder or lies below it, comparing whole path parts in Unicode's
    composed form, casefolded, so a name with an accent matches however it is stored."""
    path_parts = _parts(path)
    folder_parts = _parts(folder)
    return len(folder_parts) <= len(path_parts) and path_parts[:len(folder_parts)] == folder_parts


def relative_inside(path, folder):
    """path's parts below folder joined with "/", as stored on disk, or None when path is
    not inside folder."""
    if not inside(path, folder):
        return None
    parts = [part for part in os.path.normpath(str(path)).split(os.sep) if part]
    below = parts[len(_parts(folder)):]
    return "/".join(unicodedata.normalize("NFC", part) for part in below)


def excluded_folders(system, notes):
    """The folders the scholar excluded: system.yaml's list and the audit home's, normalized.

    Each is realpath(expanduser(folder)). None of them is listed or opened.
    """
    found = []
    system = system if isinstance(system, dict) else {}
    listed = system.get("excluded_folders") or []
    if not isinstance(listed, list):
        notes.append("system.yaml gives excluded_folders that is not a list, so only the audit"
                     " settings' list applies")
        listed = []
    audit_notes = []
    audit_home = system.get("audit_home")
    from_audit = _excluded_folders(audit_home, audit_notes) if audit_home else None
    if audit_notes:
        notes.append("the audit home's settings.yaml cannot be read or gives no list of"
                     " excluded_folders, so only the excluded folders in system.yaml apply")
    for folder in list(listed) + list(from_audit or []):
        if not isinstance(folder, str) or not folder.strip():
            continue
        normal = _normalized(folder.strip())
        if not any(_parts(normal) == _parts(earlier) for earlier in found):
            found.append(normal)
    return found


def _homes(system, home):
    found = []
    system = system if isinstance(system, dict) else {}
    candidates = [system.get("audit_home"), home, system.get("connections_home"),
                  system.get("observability_home"), os.environ.get("CONNECTIONS_HOME"),
                  os.environ.get("OBSERVABILITY_HOME")]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            normal = _normalized(candidate.strip())
            if normal not in found:
                found.append(normal)
    return found


def _refuse_excluded(folder, also_folders, runs, excluded, notes, skip_index=False):
    """Stop when the project, an also_folders entry, or the runs folder lies inside an
    excluded folder, and, unless the session index is skipped, when an excluded folder
    lies inside the project or an also_folders entry, since the index could name the
    files in it that a session read. With the index skipped, an excluded folder inside
    the project is only left out of the copy unopened."""
    for ex in excluded:
        if inside(folder, ex):
            raise model.PublishError("the project folder lies inside a folder the scholar"
                                     " excluded, so nothing in it may be published")
        for also in also_folders:
            if inside(_normalized(also), ex):
                raise model.PublishError("a sessions also_folders entry lies inside a folder the"
                                         " scholar excluded, so the session index may not name"
                                         " its files")
        if runs and inside(_normalized(runs), ex):
            raise model.PublishError("the runs folder lies inside a folder the scholar excluded")
    for ex in excluded:
        if inside(ex, folder):
            if not skip_index:
                raise model.PublishError(INSIDE_PROJECT_STOP)
            notes.append("a folder the scholar excluded lies inside the project folder and is left"
                         " out unopened")
        for also in also_folders:
            if inside(ex, _normalized(also)) and not skip_index:
                raise model.PublishError(INSIDE_ALSO_STOP)


# The .gitignore subset (design R8).


def _segments_match(pattern, parts):
    if not pattern:
        return not parts
    if pattern[0] == "**":
        return any(_segments_match(pattern[1:], parts[index:]) for index in range(len(parts) + 1))
    if not parts:
        return False
    return fnmatch.fnmatchcase(parts[0], pattern[0]) and _segments_match(pattern[1:], parts[1:])


def _strip_line(raw):
    """A .gitignore line as git reads it: trailing spaces dropped unless escaped with a
    backslash, and each escaped space a space."""
    line = raw.rstrip("\r\n\t")
    while line.endswith(" ") and not line.endswith("\\ "):
        line = line[:-1]
    return line


def gitignore_lines(text):
    """(pattern line, negated) for each rule line of a .gitignore's text, read as git
    reads it: a byte order mark at the start dropped, blank and # lines skipped, a
    leading backslash before # or ! taken away, and '\\ ' read as a space."""
    found = []
    for raw in text.lstrip("\ufeff").splitlines():
        line = _strip_line(raw)
        if not line.strip() or line.startswith("#"):
            continue
        negated = line.startswith("!")
        if negated:
            line = line[1:]
        if line.startswith(("\\#", "\\!")):
            line = line[1:]
        found.append((line.replace("\\ ", " "), negated))
    return found


def gitignore_rules_of(text, base, source):
    """(rules, negated) for one .gitignore's text, each rule relative to base. The
    patterns are compared with case ignored, as git does on a Mac or Windows machine,
    so a rule leaves out at least what git would."""
    rules = []
    negated = False
    for line, is_negation in gitignore_lines(text):
        if is_negation:
            negated = True
            continue
        dir_only = line.endswith("/")
        pattern = line.rstrip("/")
        if not pattern:
            continue
        anchored = "/" in pattern
        segments = [part.casefold() for part in pattern.strip("/").split("/") if part]
        if not segments:
            continue
        rules.append(GitignoreRule(base, source, line, segments, anchored, dir_only))
    return rules, negated


def _gitignore_rules(path, base, source, notes):
    """The rules of one .gitignore, each relative to the folder that holds it."""
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError:
        notes.append("%s cannot be read, so its rules were not applied" % source)
        return []
    rules, negated = gitignore_rules_of(text, base, source)
    if negated:
        notes.append("a .gitignore negation in %s is not applied, so what it would bring back"
                     " stays out" % source)
    return rules


def _ignored_by(rules, relpath, is_dir):
    for rule in rules:
        if rule.base:
            if not relpath.casefold().startswith(rule.base.casefold() + "/"):
                continue
            below = relpath[len(rule.base) + 1:]
        else:
            below = relpath
        if rule.dir_only and not is_dir:
            continue
        parts = list(rule.prefix) + below.casefold().split("/")
        if rule.anchored:
            if _segments_match(rule.segments, parts):
                return rule
        elif fnmatch.fnmatchcase(parts[-1], rule.segments[0]):
            return rule
    return None


def outer_rules(folder, notes):
    """The ignore rules git applies to the project from outside its own .gitignore files:
    each .gitignore of the folders above it, up to the repository that holds it, and that
    repository's info/exclude file, which the project's own .git may be. They are read
    here, so they apply even when git cannot run."""
    chain = [folder]
    while not os.path.exists(os.path.join(chain[-1], ".git")):
        parent = os.path.dirname(chain[-1])
        if parent == chain[-1]:
            return []
        chain.append(parent)
    sources = []
    exclude = os.path.join(chain[-1], ".git", "info", "exclude")
    if os.path.isfile(exclude):
        sources.append((chain[-1], exclude, EXCLUDE_SOURCE))
    for above in reversed(chain[1:]):
        path = os.path.join(above, GITIGNORE)
        if os.path.isfile(path) and not os.path.islink(path):
            sources.append((above, path, OUTER_SOURCE))
    rules = []
    for above, path, source in sources:
        prefix = tuple(part.casefold() for part in os.path.relpath(folder, above).split(os.sep)
                       if part not in ("", "."))
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                text = handle.read()
        except OSError:
            notes.append("%s cannot be read, so its rules were not applied" % source)
            continue
        found, _ = gitignore_rules_of(text, "", source)
        rules.extend(rule._replace(prefix=prefix) for rule in found)
    return rules


def _in_repository(folder):
    """Whether folder or a folder above it holds .git."""
    current = folder
    while True:
        if os.path.exists(os.path.join(current, ".git")):
            return True
        parent = os.path.dirname(current)
        if parent == current:
            return False
        current = parent


def _run_git(git, args, data=None):
    env = dict(os.environ)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env["GIT_TERMINAL_PROMPT"] = "0"
    return subprocess.run([git] + list(args), input=data, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, env=env, timeout=120)


def gitignore_ignored(project_dir, relpaths, notes):
    """The relpaths git ignores, by git check-ignore, when the project lies in a git
    work tree, its own or one above it, so the rules of a parent repository and its
    info/exclude file apply too. git is only asked, read only.

    This is best effort: when git cannot run, as when only a stand-in for it is
    installed, a note says so and nothing more is left out than the .gitignore
    rules this file reads. git check-ignore answers 1 when it ignores nothing,
    which counts only when it wrote no error.
    """
    folder = _absolute(project_dir)
    relpaths = list(relpaths)
    if not relpaths or not _in_repository(folder):
        return set()
    git = shutil.which("git")
    if not git:
        notes.append(GIT_NOTE)
        return set()
    data = ("\0".join(relpaths) + "\0").encode("utf-8", "surrogateescape")
    try:
        version = _run_git(git, ["--version"])
        if version.returncode != 0 or not version.stdout.startswith(b"git version"):
            notes.append(GIT_NOTE)
            return set()
        tree = _run_git(git, ["-C", folder, "rev-parse", "--is-inside-work-tree"])
        if tree.returncode != 0 or tree.stdout.strip() != b"true":
            if b"not a git repository" not in tree.stderr:
                notes.append(GIT_NOTE)
            return set()
        done = _run_git(git, ["-C", folder, "check-ignore", "-z", "--stdin"], data)
    except (OSError, subprocess.SubprocessError, ValueError):
        notes.append(GIT_NOTE)
        return set()
    if done.returncode not in (0, 1) or (done.returncode == 1 and done.stderr.strip()):
        notes.append(GIT_NOTE)
        return set()
    found = set(part for part in done.stdout.decode("utf-8", "surrogateescape").split("\0")
                if part)
    return set(relpath for relpath in relpaths if relpath in found)


# The walk (design A.2, R7 to R9).


def _excluded_entry(relpath, entries):
    for entry in entries:
        if entry.endswith("/"):
            if relpath == entry[:-1]:
                return True
        elif relpath == entry:
            return True
    return False


def _named(name, names):
    """The entry of names that name is, with case ignored, or None."""
    folded = name.casefold()
    for entry in names:
        if entry.casefold() == folded:
            return entry
    return None


def _folder_rule(full, name, relpath, top, excluded, homes, exclude, rules):
    if os.path.islink(full):
        return "symlink", SYMLINK_WHY
    real = os.path.realpath(full)
    if any(inside(real, ex) for ex in excluded):
        return "excluded_folder", EXCLUDED_WHY
    if any(inside(real, home) for home in homes):
        return "home", HOME_WHY
    # Folder names are compared with case ignored, since a Mac's disk ignores it.
    fixed = _named(name, FIXED_PARTS)
    if fixed is not None:
        return "fixed", FIXED_PARTS[fixed]
    top_folder = _named(name, TOP_FOLDERS) if top else None
    if top_folder is not None:
        return "fixed", TOP_FOLDERS[top_folder]
    if relpath.casefold() == RUNS_FOLDER.casefold():
        return "fixed", RUN_FOLDER_WHY
    if os.path.isfile(os.path.join(full, "manifest.json")) \
            and os.path.isfile(os.path.join(full, "trail.jsonl")):
        return "fixed", RUN_FOLDER_WHY
    if _named(name, EDITOR_FOLDERS) is not None:
        return "editor", EDITOR_WHY
    if name.casefold().startswith(AI_TOOL_PREFIX):
        return "editor", AI_TOOL_WHY
    if _excluded_entry(relpath, exclude):
        return "exclude", EXCLUDE_WHY
    rule = _ignored_by(rules, relpath, True)
    if rule is not None:
        return "gitignore", "matched by %s in %s" % (rule.pattern, rule.source)
    return None, None


def _file_rule(full, name, relpath, exclude, rules):
    if os.path.islink(full):
        return "symlink", SYMLINK_WHY
    if not os.path.isfile(full):
        return "fixed", "not a regular file"
    folded = name.casefold()
    fixed = _named(name, FIXED_PARTS)
    if fixed is not None:
        return "fixed", FIXED_PARTS[fixed]
    if name == ".DS_Store" or name.startswith("._"):
        return "fixed", FINDER_WHY
    if name.endswith(COMPILED_SUFFIXES):
        return "fixed", "a compiled Python file"
    if name.endswith(LOG_SUFFIXES):
        return "fixed", "a log file or a LaTeX byproduct"
    if folded.endswith(HISTORY_SUFFIXES) or _named(name, HISTORY_FILES) is not None:
        return "history", HISTORY_WHY
    if folded.startswith(AI_TOOL_PREFIX):
        return "editor", AI_TOOL_WHY
    if _named(name, SETTINGS_FILES) is not None:
        return "fixed", SETTINGS_WHY
    if _excluded_entry(relpath, exclude):
        return "exclude", EXCLUDE_WHY
    rule = _ignored_by(rules, relpath, False)
    if rule is not None:
        return "gitignore", "matched by %s in %s" % (rule.pattern, rule.source)
    return None, None


def _walk(folder, exclude, excluded, homes, notes):
    """(kept relpaths, left_out) for the project folder, sorted, pruning as it goes."""
    kept = []
    left_out = []
    rules = outer_rules(folder, notes)
    unreadable = []

    def cannot_read(error):
        # A folder this account cannot list is left out, with a note, never skipped quietly.
        where = _relative(os.path.relpath(str(error.filename or folder), folder))
        if where:
            unreadable.append(where)
            left_out.append((where + "/", "unreadable", UNREADABLE_WHY))

    for root, dirs, files in os.walk(folder, onerror=cannot_read):
        dirs.sort()
        files.sort()
        base = _relative(os.path.relpath(root, folder))
        top = base == ""
        if GITIGNORE in files:
            path = os.path.join(root, GITIGNORE)
            if os.path.isfile(path) and not os.path.islink(path):
                rules.extend(_gitignore_rules(path, base, _join(base, GITIGNORE), notes))
        keep = []
        for name in dirs:
            relpath = _join(base, name)
            rule, why = _folder_rule(os.path.join(root, name), name, relpath, top, excluded,
                                     homes, exclude, rules)
            if rule is None:
                keep.append(name)
            else:
                left_out.append((relpath if rule == "symlink" else relpath + "/", rule, why))
        dirs[:] = keep
        for name in files:
            relpath = _join(base, name)
            rule, why = _file_rule(os.path.join(root, name), name, relpath, exclude, rules)
            if rule is None:
                kept.append(relpath)
            else:
                left_out.append((relpath, rule, why))
    if unreadable:
        count = len(unreadable)
        notes.append(UNREADABLE_NOTE % (count, "folder" if count == 1 else "folders",
                                        "it is" if count == 1 else "they are",
                                        "it" if count == 1 else "them"))
    return kept, left_out


# The Makefile (design R1).


def _machine_paths(workflow_root):
    found = []
    for path in (workflow_root, os.path.realpath(workflow_root), os.path.expanduser("~"),
                 os.path.realpath(os.path.expanduser("~"))):
        path = str(path).rstrip("/")
        if path.startswith("/") and len(path) > 1 and path not in found:
            found.append(path)
    return [re.compile(re.escape(path) + r"(?![A-Za-z0-9._-])") for path in found]


def rewrite_makefile(data, workflow_folder, workflow_root):
    """(new bytes, make_style, rewritten) for the Makefile, or PublishError (design R1).

    A WORKFLOW line gets the value ../../<workflow_folder>. With no WORKFLOW
    line, the OSPIPE line add-product writes, which names ospipe's folder on
    this machine, becomes a WORKFLOW line and an OSPIPE line that uses it.
    Otherwise the file is left as it is. Any line that still names the
    workflow's folder or the home folder on this machine stops the command.
    """
    text = data.decode("utf-8", "surrogateescape")
    lines = text.splitlines(True)
    value = "../../%s" % workflow_folder
    out = []
    rewritten = []
    style = PYTHONPATH_ENV
    if any(WORKFLOW_LINE.match(line) for line in lines):
        style = WORKFLOW_VAR
        index = 0
        while index < len(lines):
            line = lines[index]
            match = WORKFLOW_LINE.match(line)
            if not match:
                out.append(line)
                index += 1
                continue
            body = line.rstrip("\r\n")
            ending = line[len(body):] or "\n"
            while body.endswith("\\") and index + 1 < len(lines):
                index += 1
                body = lines[index].rstrip("\r\n")
                ending = lines[index][len(body):] or ending
            out.append("%s %s%s" % (match.group(1), value, ending))
            rewritten.append((MAKEFILE, "the WORKFLOW default is now %s, the workflow cloned"
                                        " beside this repository" % value))
            index += 1
    else:
        for line in lines:
            body = line.rstrip("\r\n")
            if style == PYTHONPATH_ENV and OSPIPE_LINE.match(body):
                ending = line[len(body):] or "\n"
                out.append("WORKFLOW ?= %s%s" % (value, ending))
                out.append(OSPIPE_BY_WORKFLOW + ending)
                rewritten.append((MAKEFILE, "WORKFLOW ?= %s takes the place of the OSPIPE line"
                                            " that named ospipe's folder on this machine" % value))
                rewritten.append((MAKEFILE, "%s finds ospipe in WORKFLOW" % OSPIPE_BY_WORKFLOW))
                style = WORKFLOW_VAR
            else:
                out.append(line)
    patterns = _machine_paths(workflow_root)
    for number, line in enumerate(out, start=1):
        if any(pattern.search(line) for pattern in patterns):
            raise model.PublishError(
                "the Makefile line %d still names a folder on this machine, the workflow's or the"
                " home folder, so the published build file would not work elsewhere; make that"
                " line name a path relative to the project" % number)
    return "".join(out).encode("utf-8", "surrogateescape"), style, rewritten


# Ledgers and the workflow's commit (design A.3, R17).


def _epoch(day):
    try:
        found = datetime.datetime.strptime(day, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None
    return (found - datetime.date(1970, 1, 1)).days * 86400


def read_ledger(path):
    """The rows of a ledger, BUILDS.md (or the folder that holds it), oldest first.

    Nine-column rows and older seven-column rows parse as ospipe's builder
    parses them; an older row has empty verification and runs cells. epoch is
    midnight UTC of the row's date in seconds, or None when the date is not
    YYYY-MM-DD. A missing ledger gives [], and one that cannot be read a
    PublishError.
    """
    path = str(path)
    if os.path.isdir(path):
        path = os.path.join(path, LEDGER)
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            lines = handle.read().splitlines()
    except OSError as error:
        raise model.PublishError("the ledger %s cannot be read (%s)"
                                 % (path, error.strerror or error))
    rows = []
    for raw in lines:
        line = raw.strip()
        if len(line) < 2 or not (line.startswith("|") and line.endswith("|")):
            continue
        cells = [cell.strip() for cell in line[1:-1].split("|")]
        if cells[0].lower() == "version":
            continue
        if all(SEPARATOR.match(cell) for cell in cells):
            continue
        if len(cells) == 9:
            version, day, git, sha256, purpose, _, _, verification, runs = cells
        elif len(cells) == 7:
            version, day, git, sha256, purpose = cells[:5]
            verification, runs = "", ""
        else:
            continue
        rows.append(model.LedgerRow(version, day, git, sha256, purpose, verification, runs,
                                    _epoch(day)))
    return rows


def _first_line(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read().strip()


def _commit(root):
    dot = os.path.join(root, ".git")
    if os.path.isdir(dot):
        gitdir = dot
    elif os.path.isfile(dot):
        pointer = _first_line(dot)
        if not pointer.startswith("gitdir:"):
            return None
        gitdir = pointer[len("gitdir:"):].strip()
        if not os.path.isabs(gitdir):
            gitdir = os.path.normpath(os.path.join(root, gitdir))
    else:
        return None
    common = gitdir
    commondir = os.path.join(gitdir, "commondir")
    if os.path.isfile(commondir):
        found = _first_line(commondir)
        common = found if os.path.isabs(found) else os.path.normpath(os.path.join(gitdir, found))
    head = _first_line(os.path.join(gitdir, "HEAD"))
    if HEX_SHA.match(head):
        return head
    if not head.startswith("ref:"):
        return None
    ref = head[len("ref:"):].strip()
    if not ref or ref.startswith("/") or ".." in ref.split("/"):
        return None
    for folder in (gitdir, common):
        path = os.path.join(folder, *ref.split("/"))
        if os.path.isfile(path):
            found = _first_line(path)
            if HEX_SHA.match(found):
                return found
    for folder in (common, gitdir):
        packed = os.path.join(folder, "packed-refs")
        if not os.path.isfile(packed):
            continue
        with open(packed, encoding="utf-8") as handle:
            for line in handle.read().splitlines():
                parts = line.split()
                if len(parts) == 2 and parts[1] == ref and HEX_SHA.match(parts[0]):
                    return parts[0]
    return None


def workflow_commit(workflow_root):
    """The commit the workflow's checkout is at, read from its .git, or "unknown".

    A .git file (a worktree) is followed through gitdir: and then commondir to
    HEAD, the refs, and packed-refs. No git command is run.
    """
    try:
        found = _commit(_absolute(workflow_root))
    except (OSError, UnicodeDecodeError, ValueError):
        return "unknown"
    return found or "unknown"


# Products and groups (design R2, R5).


def _products(found, folder):
    products = []
    for item in found:
        name = str(item.get("name") or "")
        source = _relative(item.get("source") or "")
        builds_dir = _relative(item.get("builds_dir") or "")
        verification_dir = _relative(item.get("verification_dir") or DEFAULT_VERIFICATION)
        for relpath in (source, builds_dir, verification_dir):
            if relpath and _escapes(relpath):
                raise model.PublishError("the product %s names %s, which is outside the project"
                                         % (name, relpath))
        try:
            ledger = read_ledger(os.path.join(folder, builds_dir, LEDGER)) if builds_dir else []
        except model.PublishError:
            raise model.PublishError("the ledger %s cannot be read"
                                     % _join(builds_dir, LEDGER))
        products.append(model.Product(name, source, builds_dir, verification_dir,
                                      item.get("to") or "", ledger,
                                      ledger[-1] if ledger else None))
    return products


def _groups(products):
    order = []
    members = collections.OrderedDict()
    for product in products:
        if product.verification_dir not in members:
            members[product.verification_dir] = []
            order.append(product.verification_dir)
        members[product.verification_dir].append(product)
    groups = []
    for verification_dir in order:
        names = [product.name for product in members[verification_dir]]
        groups.append(model.Group("+".join(names), tuple(members[verification_dir]),
                                  verification_dir, _label(names)))
    return groups


# Reports (design R3).


def _safe_run(run_id):
    return isinstance(run_id, str) and RUN_NAME.match(run_id) is not None \
        and run_id not in (".", "..")


def _run_files(runs, run_id):
    """(results, report bytes or None, manifest or None, results bytes) of RUNS/<run_id>/.

    None when the folder or its results.json is absent or cannot be read.
    """
    if not runs or not _safe_run(run_id):
        return None
    folder = os.path.join(runs, run_id)
    results_path = os.path.join(folder, RUN_RESULTS)
    if not os.path.isfile(results_path):
        return None
    try:
        data = _read_bytes(results_path)
        results = _parse_json(data)
        if results is None:
            return None
        report = None
        for path in (os.path.join(folder, DECIDED_REPORT), os.path.join(folder, *RUN_REPORT)):
            if os.path.isfile(path):
                report = _read_bytes(path)
                break
        manifest = None
        manifest_path = os.path.join(folder, RUN_MANIFEST)
        if os.path.isfile(manifest_path):
            manifest = _parse_json(_read_bytes(manifest_path))
    except OSError:
        return None
    return results, report, manifest, data


def _stream_report(group, stream, folder, runs, project_files, left_out, notes):
    relpath = _join(group.verification_dir, stream + ".json")
    path = os.path.join(folder, relpath)
    if not os.path.isfile(path):
        return None
    try:
        data = _read_bytes(path)
    except OSError as error:
        raise model.PublishError("the results file %s cannot be read (%s)"
                                 % (relpath, error.strerror or error))
    results = _parse_json(data)
    if results is None:
        notes.append("%s is not a results file that can be read, so it counts as missing"
                     % relpath)
        return None
    run_id = str(results.get("run_id") or "")
    report_bytes = None
    report_from = None
    note = None
    run = _run_files(runs, run_id)
    if run is not None:
        run_results, run_report, _, _ = run
        if _same_results(run_results, results) and run_report is not None:
            report_bytes = run_report
            report_from = "run %s" % run_id
            if run_results.get("decisions") != results.get("decisions"):
                note = DECIDED_NOTE % run_id
        elif not _same_results(run_results, results):
            notes.append(OTHER_RUN_NOTE % run_id)
    own_folder = _join(group.verification_dir, stream)
    own_report = own_folder + "/report.md"
    own_results = own_folder + "/" + RUN_RESULTS
    if report_bytes is None and own_report in project_files and own_results in project_files:
        sibling = _parse_json(project_files[own_results])
        if sibling is not None and _same_results(sibling, results):
            report_bytes = project_files[own_report]
            report_from = "project"
    if report_bytes is None:
        note = NO_REPORT_NOTE % (run_id or relpath)
        if own_report in project_files:
            del project_files[own_report]
            left_out.append((own_report, "fixed", STALE_REPORT_WHY))
    if note:
        notes.append(note)
    return model.Report(group, stream, run_id, results, data, report_bytes, report_from, note)


def _phase_from_run(group, phase, run_id, run):
    if run is None:
        return None
    results, report, _, data = run
    if results.get("stream") != PHASE_STREAM:
        return None
    return model.Report(group, phase, str(results.get("run_id") or run_id), results, data,
                        report, "run %s" % run_id, None)


def _graph_path(manifest):
    graph = manifest.get("graph") if isinstance(manifest, dict) else None
    path = graph.get("path") if isinstance(graph, dict) else None
    return str(path).replace("\\", "/") if path else ""


def _phase_report(group, phase, answers, runs, project_files, notes):
    chosen = answers.phase_runs if isinstance(answers.phase_runs, dict) else {}
    for key in [group.key] + [product.name for product in group.products]:
        run_id = (chosen.get(key) or {}).get(phase)
        if not run_id:
            continue
        found = _phase_from_run(group, phase, run_id, _run_files(runs, run_id))
        if found is not None:
            return found
        notes.append("the phase run %s that the answers name for %s is not a data phase run in"
                     " the runs folder" % (run_id, key))
    for product in group.products:
        run_id = "%s_%s" % (product.name, phase)
        run = _run_files(runs, run_id)
        if run is None or not _graph_path(run[2]).endswith("graphs/%s.yaml" % phase):
            continue
        found = _phase_from_run(group, phase, run_id, run)
        if found is not None:
            return found
    own_folder = _join(group.verification_dir, phase)
    own_results = own_folder + "/" + RUN_RESULTS
    if own_results in project_files:
        data = project_files[own_results]
        results = _parse_json(data)
        if results is not None and results.get("stream") == PHASE_STREAM:
            return model.Report(group, phase, str(results.get("run_id") or ""), results, data,
                                project_files.get(own_folder + "/report.md"), "project", None)
    return None


def _reports(groups, answers, folder, runs, project_files, left_out, notes, has_pipeline):
    reports = []
    absent = []
    for group in groups:
        has_data = False
        for stream in model.STREAMS:
            found = _stream_report(group, stream, folder, runs, project_files, left_out, notes)
            if found is not None:
                reports.append(found)
                has_data = has_data or stream == "data"
        for phase in model.PHASES:
            found = _phase_report(group, phase, answers, runs, project_files, notes)
            if found is not None:
                reports.append(found)
            elif has_data:
                # Only a group with data results is expected to have phase reports.
                absent.append("%s %s" % (group.label, model.PHASE_TITLES[phase]))
    if absent and has_pipeline:
        notes.append("the project has a pipeline.yaml, and no data phase report was found for %s"
                     % _label(absent))
    return reports


# The numbers file, the references, and the pipeline.


def _distinct(values, default):
    found = []
    for value in values:
        relpath = _relative(value or "")
        if relpath and relpath not in found:
            found.append(relpath)
    return found or [default]


def _numbers_keys(found, project_files, notes):
    keys = []
    for relpath in _distinct([item.get("manifest") for item in found], DEFAULT_NUMBERS):
        data = project_files.get(relpath)
        if data is None:
            continue
        try:
            loaded = yaml.safe_load(data.decode("utf-8"))
        except (UnicodeDecodeError, yaml.YAMLError):
            notes.append("%s cannot be read as YAML, so its numbers are not counted" % relpath)
            continue
        numbers = loaded.get("numbers") if isinstance(loaded, dict) else None
        if isinstance(numbers, dict):
            for key in numbers:
                if str(key) not in keys:
                    keys.append(str(key))
    return keys


def _refs_works(found, project_files):
    total = 0
    for relpath in _distinct([item.get("bib") for item in found], DEFAULT_BIB):
        data = project_files.get(relpath)
        if data is None:
            continue
        text = data.decode("utf-8", "replace")
        total += sum(1 for line in text.splitlines() if BIB_ENTRY.match(line))
    return total


def _pipeline(project_files, notes):
    data = project_files.get(PIPELINE)
    if data is None:
        return None
    try:
        loaded = yaml.safe_load(data.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError):
        notes.append("pipeline.yaml cannot be read as YAML, so its steps are not counted")
        return None
    return loaded if isinstance(loaded, dict) else None


# The whole read.


def _name_notes(answers, system, notes):
    """Notes on the names an anonymous build withholds: none from system.yaml, or words
    of the name the answers' scrub_terms leave out."""
    if not answers.anonymous:
        return
    words = name_terms(system.get("scholar_name"))
    if not words:
        notes.append(NO_NAME_NOTE)
        return
    chosen = set(term.casefold() for term in answers.sessions.get("scrub_terms") or [])
    left = [word for word in words[1:] if word.casefold() not in chosen]
    if left:
        count = len(left)
        notes.append(WORDS_LEFT_NOTE % (count, "word" if count == 1 else "words",
                                        "it" if count == 1 else "them",
                                        "it" if count == 1 else "them"))


def collect(project_dir, answers, system, runs_dir, home, runner=run_layer):
    """Collected(...) for the project at project_dir, or PublishError.

    answers comes from read_answers. system is system.yaml's record (it uses
    workflow_root, audit_home, excluded_folders, and the homes). runs_dir is
    the --runs folder or None, which means answers.runs. home is the features
    home, left out of the copy when it lies inside the project. runner runs
    ospipe products --json through read_map. Nothing is written.
    """
    folder = _absolute(project_dir)
    if not os.path.isdir(folder):
        raise model.PublishError("%s is not a folder" % folder)
    system = system if isinstance(system, dict) else {}
    root = system.get("workflow_root") or ""
    if not root:
        raise model.PublishError("system.yaml gives no workflow_root")
    root = _absolute(root)
    notes = []
    if answers.unknown_keys:
        notes.append("the answers file has fields this command does not use: %s"
                     % ", ".join(answers.unknown_keys))
    for key in answers.files:
        if "/" in key.rstrip("/"):
            notes.append("the answers' files key %s is not at the top of the project, so"
                         " project/README.md, which lists only the top, does not use it" % key)
    runs = _absolute(runs_dir) if runs_dir else (answers.runs or "")
    if runs and not os.path.isdir(runs):
        notes.append("the runs folder does not exist, so no report comes from a run folder")

    excluded = excluded_folders(system, notes)
    _name_notes(answers, system, notes)
    also = answers.sessions.get("also_folders") or []
    _refuse_excluded(_normalized(folder), also, runs, excluded, notes,
                     skip_index=bool(answers.sessions.get("skip")))

    try:
        project_map = read_map(folder, root=root, runner=runner)
    except LayerMissing as error:
        raise model.PublishError(str(error))
    if not project_map.products:
        reason = project_map.problems[0] if project_map.problems else "the build file names no" \
            " research product"
        raise model.PublishError("the project has no research product to publish, since %s"
                                 % reason)
    for problem in project_map.problems:
        notes.append("ospipe products found a problem in the build file: %s" % problem)
    products = _products(project_map.products, folder)
    groups = _groups(products)

    kept, left_out = _walk(folder, answers.exclude, excluded, _homes(system, home), notes)
    ignored = gitignore_ignored(folder, kept, notes)
    project_files = collections.OrderedDict()
    for relpath in kept:
        if relpath in ignored:
            left_out.append((relpath, "gitignore", IGNORED_BY_GIT))
            continue
        try:
            project_files[relpath] = _read_bytes(os.path.join(folder, *relpath.split("/")))
        except OSError as error:
            raise model.PublishError("the project file %s cannot be read (%s)"
                                     % (relpath, error.strerror or error))

    if MAKEFILE not in project_files:
        raise model.PublishError("the Makefile is left out of the copy by a rule, such as a"
                                 " .gitignore line or the answers' exclude list, and the"
                                 " repository needs it to build each product")
    data, make_style, rewritten = rewrite_makefile(project_files[MAKEFILE],
                                                   answers.workflow_folder, root)
    project_files[MAKEFILE] = data

    pipeline = _pipeline(project_files, notes)
    reports = _reports(groups, answers, folder, runs, project_files, left_out, notes,
                       PIPELINE in project_files)
    for report in reports:
        relpath = _join(report.group.verification_dir, report.stream + ".json")
        if report.stream in model.STREAMS and relpath not in project_files:
            notes.append("%s is left out of the copy by a rule, so the published project has no"
                         " results file where its build reads one, though the report folder"
                         " holds the same bytes" % relpath)
    return model.Collected(
        project_dir=folder,
        answers=answers,
        products=products,
        groups=groups,
        reports=reports,
        makefile_style=make_style,
        project_files=project_files,
        left_out=left_out,
        rewritten=rewritten,
        pipeline=pipeline,
        numbers_keys=_numbers_keys(project_map.products, project_files, notes),
        refs_works=_refs_works(project_map.products, project_files),
        notes=notes,
        excluded_folders=excluded,
        workflow_root=root,
        workflow_commit=workflow_commit(root),
    )
