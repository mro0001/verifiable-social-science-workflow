"""System setup, once per scholar (steps F3 and S2).

python3 -m features setup system [--home DIR] [--audit-home DIR] [--answers FILE]

Setup asks the decisions of decisions.py in their order and words (step S2,
scope report section 3). The excluded folders come first, then the name when
git has none, the model service, the model, and the second model, then the
citation export, and the harness only when none is found. A review screen
then lists what was found, the defaults, and each change setup would make
outside the workflow's own homes, and ends with the one yes.

Setup detects the scholar's software (step F2) and checks that the three
layers answer. Its first write puts the excluded folders into the audit
settings through python3 -m audit_layer excluded add, which adds and never
removes, or runs audit_layer init when there are none and the audit home has
no settings file. It then writes the provider setting through python3 -m
connections provider set when a model service is given, never with a key.
That command replaces provider.yaml whole, so when the answers give no
output limit setup reads the earlier file read only and passes its limit on.
Last it writes <features home>/system.yaml. Connectors sit outside any one
project, so one setup serves every project (appendix A2.2 paragraph 2).

Until steps S5 to S8 are built, a yes is recorded in system.yaml as connect
yes and setup prints the hand steps that remain. Nothing outside the
workflow's own homes is changed.

Answers come from an answers file or from questions asked in the terminal,
so a harness session can run setup from the conversation and tests run with
no model (track F choice 4). The one network call is the model service's
list of models, made only after the scholar gives its address in the
terminal, to propose a second model.
"""
import collections
import datetime
import http.client
import json
import os
import sys
import urllib.parse
import urllib.request

import yaml

from features.layers import LAYERS, LayerMissing, default_root, run_layer
from features.setup import decisions
from features.setup.detect import (KEY_VARIABLE, SERVERS, detect, detect_state,
                                   git_user_name, install_hint, missing_required)

SCHEMA = "features-system"
SCHEMA_VERSION = 1
SYSTEM_FILE = "system.yaml"
COMMAND = "python3 -m features setup system"

HOME_VARIABLE = "FEATURES_HOME"
DEFAULT_HOME = "~/.workflow_features"
AUDIT_VARIABLE = "AUDIT_HOME"
DEFAULT_AUDIT_HOME = "~/.audit_layer"
AUDIT_SETTINGS = "settings.yaml"
CONNECTIONS_VARIABLE = "CONNECTIONS_HOME"
DEFAULT_CONNECTIONS_HOME = "~/.workflow_connections"
PROVIDER_FILE = "provider.yaml"

# The harness names are the audit layer's adapter names (audit_layer/capture).
# A scholar who works in another program is recorded as another.
HARNESSES = ("claude_code", "forgecode")
ANOTHER = "another"
HARNESS_LABELS = {"claude_code": "Claude Code", "forgecode": "ForgeCode"}

FIELDS = ("scholar_name", "harness", "excluded_folders", "citation_export",
          "model_service", "model", "second_model", "token_limit", "token_limit_field",
          "connect")
# An answers file must give this. The name may be left out when git has one,
# the harness when one is found, and the rest have defaults.
NEEDED = ("excluded_folders",)
TOKEN_LIMIT_FIELDS = ("max_tokens", "max_completion_tokens")

SYSTEM_FIELDS = ("schema", "schema_version", "written_at", "workflow_root", "python",
                 "scholar_name", "harness", "audit_home", "citation_export",
                 "excluded_folders", "layers", "ready", "software")

# The events of the harness's settings that run the capture hook
# (audit_layer/hooks/INSTALL.md).
CAPTURE_EVENTS = ("Stop", "SubagentStop", "SessionEnd")

NEXT_FOLDER = "Next folder, or an empty line to end. "
CHANGES_HEADING = "Changes outside the workflow's own folders"

# The connections setup does not make yet, printed with the documents that
# say how to make each by hand. Project setup prints them too.
LATER_CONNECTIONS = (
    "Capture at the end of each turn and every 30 minutes is set up by hand as"
    " audit_layer/hooks/INSTALL.md says.",
    "The three servers, the trigger hooks, the start commands, make verify, and the wrapper"
    " functions are set up by hand as connections/README.md says.",
    "The harness setting that sends events to the live view is a later connection of observability.",
)

# The defaults the review screen states, with the words that name each.
REVIEW_DEFAULTS = (
    ("light_check", "The light check at the end of each AI turn"),
    ("full_reports", "Full verification reports"),
    ("live_view", "The live view"),
    ("session_titles", "Session titles and summaries written by a model"),
    ("online_lookup", "The online lookup of each DOI"),
    ("past_sessions", "Capture of AI sessions"),
)

SystemResult = collections.namedtuple(
    "SystemResult",
    "path system found layers audit_initialized excluded_folders messages ready"
    " provider key_set connect")


class SetupError(Exception):
    """Setup cannot go on, or a file it reads is not in the form it wrote."""


def _chosen(given, variable, default):
    chosen = given or os.environ.get(variable) or default
    return os.path.abspath(os.path.expanduser(str(chosen)))


def features_home(arg):
    """--home, else FEATURES_HOME, else ~/.workflow_features."""
    return _chosen(arg, HOME_VARIABLE, DEFAULT_HOME)


def audit_home(arg):
    """--audit-home, else AUDIT_HOME, else ~/.audit_layer, the slice's default."""
    return _chosen(arg, AUDIT_VARIABLE, DEFAULT_AUDIT_HOME)


def connections_home(arg):
    """--connections-home, else CONNECTIONS_HOME, else ~/.workflow_connections."""
    return _chosen(arg, CONNECTIONS_VARIABLE, DEFAULT_CONNECTIONS_HOME)


def default_harness(found):
    """claude_code when claude is found, else forgecode when forge is found, else "".

    A harness that is not found is reported as not found and never recorded
    as one that is (step S1, stuck point 4).
    """
    present = {item.name for item in found if item.found}
    if "claude_code" in present:
        return "claude_code"
    if "forgecode" in present:
        return "forgecode"
    return ""


def _absolute(folder):
    return os.path.abspath(os.path.expanduser(str(folder)))


def is_full_path(folder):
    """Whether a folder is written as a full path, starting with / or ~."""
    return folder.startswith(("/", "~")) and os.path.isabs(os.path.expanduser(folder))


def is_web_address(text):
    """Whether text starts with http:// or https:// and names a host."""
    if not text.startswith(("http://", "https://")):
        return False
    return bool(urllib.parse.urlsplit(text).netloc)


def _connect(value, where):
    if value in (None, False, "no"):
        return "no"
    if value in (True, "yes"):
        return "yes"
    raise SetupError("%s gives connect %r, and connect is yes or no" % (where, value))


def _check_provider(given, where):
    """The provider answers, checked, as (service, model, second, limit, field)."""
    service = given.get("model_service") or ""
    model = given.get("model") or ""
    second = given.get("second_model") or ""
    limit = given.get("token_limit")
    field = given.get("token_limit_field") or ""
    for key, value in (("model_service", service), ("model", model), ("second_model", second),
                       ("token_limit_field", field)):
        if not isinstance(value, str):
            raise SetupError("%s must give %s as text" % (where, key))
    service, model, second, field = service.strip(), model.strip(), second.strip(), field.strip()
    if not service:
        named = [key for key, value in (("model", model), ("second_model", second),
                                        ("token_limit", limit), ("token_limit_field", field))
                 if value not in (None, "")]
        if named:
            raise SetupError("%s gives %s but no model_service, the model service's web address"
                             % (where, ", ".join(named)))
        return "", "", "", None, ""
    if not is_web_address(service):
        raise SetupError("%s gives the model_service %s, which must start with http:// or"
                         " https:// and name a host" % (where, service))
    if not model:
        raise SetupError("%s gives a model_service and must give model, the model on it" % where)
    if second and second == model:
        raise SetupError("%s gives the second_model %s, which must differ from model"
                         % (where, second))
    if (limit is None) != (not field):
        raise SetupError("%s must give token_limit and token_limit_field together" % where)
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0):
        raise SetupError("%s gives a token_limit that is not a whole number above 0" % where)
    if field and field not in TOKEN_LIMIT_FIELDS:
        raise SetupError("%s gives the token_limit_field %s, and it is %s"
                         % (where, field, " or ".join(TOKEN_LIMIT_FIELDS)))
    return service, model, second, limit, field


def _check_answers(given, where, git_name=""):
    """The answers with each field checked, or SetupError naming what is wrong.

    The name may be left out when git_name is git's user.name.
    """
    if not isinstance(given, dict):
        raise SetupError("%s must be a mapping with the fields %s" % (where, ", ".join(FIELDS)))
    unknown = sorted(str(key) for key in given if key not in FIELDS)
    if unknown:
        raise SetupError("%s has no field named %s. The fields are %s"
                         % (where, ", ".join(unknown), ", ".join(FIELDS)))
    name = given.get("scholar_name")
    if name in (None, ""):
        name = git_name or ""
    if not isinstance(name, str) or not name.strip():
        raise SetupError("%s must give scholar_name, the scholar's name, since git's settings"
                         " hold no user.name" % where)
    harness = given.get("harness")
    if harness not in (None, "") and harness not in HARNESSES + (ANOTHER,):
        raise SetupError("%s gives the harness %r, and the harnesses are %s, or %s for another"
                         " program" % (where, harness, ", ".join(HARNESSES), ANOTHER))
    folders = given.get("excluded_folders")
    if folders is None:
        folders = []
    if not isinstance(folders, list) or not all(
            isinstance(folder, str) and folder.strip() for folder in folders):
        raise SetupError("%s must give excluded_folders as a list of folders, or [] for none" % where)
    for folder in folders:
        if not is_full_path(folder.strip()):
            raise SetupError("%s gives the excluded folder %s, which is not a full path. Give each"
                             " folder as a full path starting with / or ~" % (where, folder))
    export = given.get("citation_export")
    if export is None:
        export = ""
    if not isinstance(export, str):
        raise SetupError("%s must give citation_export as a file, or leave it empty" % where)
    service, model, second, limit, field = _check_provider(given, where)
    return {"scholar_name": name.strip(), "harness": harness or "",
            "excluded_folders": [folder.strip() for folder in folders],
            "citation_export": export.strip(),
            "model_service": service, "model": model, "second_model": second,
            "token_limit": limit, "token_limit_field": field,
            "connect": _connect(given.get("connect"), where)}


def read_answers_from(given, git_name=""):
    """The answers in a mapping, checked as an answers file's are."""
    return _check_answers(given, "the answers", git_name)


def read_answers(path, git_name=""):
    """The answers in a YAML answers file, checked."""
    try:
        with open(path, encoding="utf-8") as handle:
            given = yaml.safe_load(handle)
    except OSError as error:
        raise SetupError("the answers file %s cannot be read (%s)" % (path, error))
    except yaml.YAMLError as error:
        raise SetupError("the answers file %s is not YAML that can be read (%s)" % (path, error))
    if isinstance(given, dict):
        absent = [field for field in NEEDED if field not in given]
        if absent:
            raise SetupError("the answers file %s does not give %s"
                             % (path, ", ".join(absent)))
    return _check_answers(given, "the answers file %s" % path, git_name)


# The model service's list of models, the one network call.


def list_models(base_url, timeout=10):
    """The model ids the service lists at <base_url>/models, or [] when it gives none.

    One request, made only after the scholar gives the address. The key, when
    WORKFLOW_MODEL_KEY holds one, is sent as the live calls send it, and it
    is never printed or kept.
    """
    request = urllib.request.Request(base_url.rstrip("/") + "/models",
                                     headers={"Accept": "application/json"})
    key = (os.environ.get(KEY_VARIABLE) or "").strip()
    if key:
        request.add_header("Authorization", "Bearer " + key)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            listing = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, http.client.HTTPException):
        return []
    entries = listing.get("data") if isinstance(listing, dict) else None
    if not isinstance(entries, list):
        return []
    return [entry["id"] for entry in entries
            if isinstance(entry, dict) and isinstance(entry.get("id"), str) and entry["id"]]


def propose_second_model(models, model):
    """The first model in the service's list that differs from the first model, or ""."""
    for name in models:
        if name != model:
            return name
    return ""


# The questions, asked one at a time in the terminal.


def _question(decision_id):
    return decisions.by_id(decision_id).question + " "


def _ask_folders(ask, out):
    folders = []
    while True:
        prompt = NEXT_FOLDER if folders else _question("excluded_folders")
        folder = ask(prompt).strip()
        if not folder:
            if folders:
                return folders
            out.write("Give a full path, or type none if there are none.\n")
            continue
        if not folders and folder.lower() == "none":
            return folders
        if not is_full_path(folder):
            out.write("%s is not a full path. Give the folder as a full path starting with / or"
                      " ~.\n" % folder)
            continue
        folders.append(folder)


def _ask_service(ask, out, models):
    while True:
        service = ask(_question("model_service")).strip()
        if not service:
            return "", "", ""
        if is_web_address(service):
            break
        out.write("%s is not a web address. Give one starting with http:// or https://, or press"
                  " Enter to skip.\n" % service)
    model = ask(_question("model")).strip()
    if not model:
        out.write("No model was given, so the model service is skipped for now.\n")
        return "", "", ""
    proposal = propose_second_model(models(service), model)
    prompt = _question("second_model")
    if proposal:
        prompt = prompt.replace(" Press Enter to skip.",
                                " The service also offers %s. Press Enter to skip." % proposal)
    while True:
        second = ask(prompt).strip()
        if second != model:
            return service, model, second
        out.write("The second model must differ from the first.\n")


def _harness_answer(text):
    words = text.strip().lower().replace(" ", "").replace("_", "")
    if not words:
        return ""
    if words in ("claudecode", "claude"):
        return "claude_code"
    if words in ("forgecode", "forge"):
        return "forgecode"
    return ANOTHER


def ask_answers(found, state=None, ask=None, out=sys.stdout, models=None):
    """Ask each question in the terminal in the list's order, asking a bad answer again.

    The name is asked only when git has none, and the harness only when none
    is found. The one yes is asked after the review screen, by ask_connect.
    """
    ask = ask or input
    models = models or list_models
    git_name = state.git_name if state is not None else ""
    folders = _ask_folders(ask, out)
    name = git_name
    while not name:
        name = ask(_question("scholar_name")).strip()
        if not name:
            out.write("A name is needed.\n")
    service, model, second = _ask_service(ask, out, models)
    zotero = [item.path for item in found if item.name in ("zotero", "zotero_data") and item.found]
    if zotero:
        out.write("Zotero was found at %s.\n" % " and ".join(zotero))
    export = ask(_question("citation_export")).strip()
    harness = ""
    if not default_harness(found):
        harness = _harness_answer(ask(_question("harness")))
    return _check_answers({"scholar_name": name, "harness": harness, "excluded_folders": folders,
                           "citation_export": export, "model_service": service,
                           "model": model, "second_model": second},
                          "the answers given", git_name)


def ask_connect(ask=None, out=sys.stdout):
    """The answer to the one yes, yes or no. Enter says yes."""
    ask = ask or input
    while True:
        answer = ask(decisions.YES_QUESTION + " ").strip().lower()
        if answer in ("", "yes", "y"):
            return "yes"
        if answer in ("no", "n"):
            return "no"
        out.write("Answer yes or no.\n")


# The review screen.


def shell_profile(user_home, shell):
    """The shell profile the wrapper lines and the key line go in."""
    name = os.path.basename(shell or "")
    if name == "zsh":
        return os.path.join(user_home, ".zshrc")
    if name == "bash":
        return os.path.join(user_home, ".bashrc")
    return os.path.join(user_home, ".profile")


def _found_lines(tools, harness, given, key_set):
    lines = []
    if tools["claude_code"].found:
        lines.append("Claude Code at %s. Its sessions are captured at the end of each turn and every"
                     " 30 minutes, the light check can run, and the three servers are registered"
                     " with it." % tools["claude_code"].path)
    if tools["forgecode"].found:
        lines.append("ForgeCode at %s. Its sessions are captured every 30 minutes, and setup prints"
                     " its server registration for you to add." % tools["forgecode"].path)
    if not tools["claude_code"].found and not tools["forgecode"].found:
        if harness == ANOTHER:
            lines.append("You use another AI assistant program. Its sessions are not captured,"
                         " and the light check cannot run.")
        elif harness:
            lines.append("You use %s, which was not found here. Install it, then run setup again"
                         " to connect it." % HARNESS_LABELS[harness])
        else:
            lines.append("No AI assistant program was found. Nothing is captured until you"
                         " install one and run setup again.")
    if tools["word"].found:
        lines.append("Microsoft Word. Prose review reads the changes you track in Word.")
    else:
        lines.append("Microsoft Word was not found, so prose review reads the plain-text file.")
    if tools["zotero"].found or tools["zotero_data"].found:
        lines.append("Zotero. The references check reads the BibTeX file it exports.")
    if tools["rscript"].found:
        lines.append("R. Runs of R and Rscript are logged.")
    if tools["quarto"].found:
        lines.append("Quarto. Runs of quarto are logged.")
    if tools["git"].found:
        lines.append("git. Nothing is put on GitHub unless you ask.")
    if given["model_service"]:
        line = "The model service %s, where %s answers the checks' questions" % (
            given["model_service"], given["model"])
        if given["second_model"]:
            line += " and %s rechecks doubtful source verdicts" % given["second_model"]
        lines.append(line + ".")
    else:
        lines.append("No model service, so full checks run without a judge and each judged item"
                     " reads not judged.")
    lines.append("%s is %s." % (KEY_VARIABLE, "set" if key_set else "not set"))
    if given["excluded_folders"]:
        lines.append("Excluded folders. Nothing is recorded or started for work in %s."
                     % ", ".join(given["excluded_folders"]))
    else:
        lines.append("No excluded folders.")
    return lines


def _changes(tools, state, user_home, platform, shell):
    changes = []
    settings = os.path.join(user_home, ".claude", "settings.json")
    if tools["claude_code"].found:
        capture = state.hooks.get("capture", [])
        if not set(CAPTURE_EVENTS) <= set(capture):
            changes.append("Add the workflow's capture hooks to %s for Stop, SubagentStop, and"
                           " SessionEnd, keeping every hook already there." % settings)
        if not state.hooks.get("trigger"):
            changes.append("Add the light check's trigger hooks to %s, keeping every hook already"
                           " there." % settings)
        missing = [name for name in SERVERS if name not in (state.servers or [])]
        if missing:
            changes.append("Register the servers %s with claude mcp add."
                           % _listed(missing))
    if tools["claude_code"].found or tools["forgecode"].found:
        if platform == "darwin":
            agent = os.path.join(user_home, "Library", "LaunchAgents", "audit_layer.sweep.plist")
            changes.append("Install the capture sweep every 30 minutes as the launch agent %s and"
                           " load it with launchctl." % agent)
        else:
            changes.append("Add a line to your crontab that runs the capture sweep every 30"
                           " minutes.")
    changes.append("Add the wrapper functions for R, Rscript, quarto, pandoc, make, and git to %s"
                   " as one marked block." % shell_profile(user_home, shell))
    return changes


def _listed(names):
    if len(names) == 1:
        return names[0]
    return "%s, and %s" % (", ".join(names[:-1]), names[-1])


def review_screen(found, state, given, harness, user_home=None, platform=None, shell=None):
    """The review screen's lines, ending with the one yes.

    It lists what was found and what each finding gets, the defaults, and
    each change setup would make outside the workflow's own homes, leaving
    out what is already in place.
    """
    user_home = os.path.expanduser("~") if user_home is None else str(user_home)
    platform = sys.platform if platform is None else platform
    shell = os.environ.get("SHELL", "") if shell is None else shell
    tools = dict((item.name, item) for item in found)
    lines = ["Review", "What setup found, and what each finding gets"]
    lines += ["  " + line for line in _found_lines(tools, harness, given, state.model_key_set)]
    lines.append("Defaults, each changed only when you ask")
    for decision_id, label in REVIEW_DEFAULTS:
        lines.append("  %s, %s." % (label, decisions.by_id(decision_id).default))
    lines.append(CHANGES_HEADING)
    lines += ["  " + line for line in _changes(tools, state, user_home, platform, shell)]
    lines.append(decisions.YES_QUESTION)
    return lines


# Writing the workflow's own files.


def _previous_folders(home):
    """The excluded folders an earlier run recorded, so a run never drops one.

    When the earlier system.yaml cannot be read, setup stops and leaves it as
    it is. Running setup again would not help, so the message says to repair
    the file or move it aside.
    """
    path = os.path.join(home, SYSTEM_FILE)
    if not os.path.exists(path):
        return []
    fix = ("Setup will not drop the excluded folders recorded there, so repair %s"
           " or move it aside, then set up again." % path)
    record = _read_system(path, fix)
    folders = record.get("excluded_folders")
    if not isinstance(folders, list) or not all(isinstance(folder, str) for folder in folders):
        raise SetupError("%s gives excluded_folders in a form setup did not write. %s"
                         % (path, fix))
    return list(folders)


def _merged(earlier, answered):
    folders = []
    for folder in list(earlier) + [_absolute(folder) for folder in answered]:
        if folder not in folders:
            folders.append(folder)
    return folders


def _layer_ok(runner, layer, root):
    try:
        done = runner(layer, ["--help"], root=root)
    except LayerMissing:
        return False
    return done.returncode == 0


def _run_or_stop(runner, layer, args, root, env, what):
    try:
        done = runner(layer, args, root=root, env=env)
    except LayerMissing as error:
        raise SetupError("%s could not run, %s" % (what, error))
    if done.returncode != 0:
        raise SetupError("%s failed with exit %d. %s"
                         % (what, done.returncode, (done.stderr or done.stdout).strip()))
    return done


def _init_audit_home(runner, root, audit):
    """Run audit_layer init with AUDIT_HOME set, or stop with the command's error."""
    _run_or_stop(runner, "audit_layer", ["init"], root, {AUDIT_VARIABLE: audit},
                 "audit_layer init")


def _add_excluded(runner, root, audit, folders):
    """List the folders in the audit settings through the audit layer's own command."""
    _run_or_stop(runner, "audit_layer", ["excluded", "add", "--home", audit] + list(folders),
                 root, {AUDIT_VARIABLE: audit}, "audit_layer excluded add")


def _earlier_limit(connections, messages):
    """The output limit and its field an earlier provider.yaml names, read only, or None.

    provider set replaces the whole file, so a run that gives no limit passes
    the earlier one on and never drops it. A limit named with no field was
    sent under max_tokens, so it is kept under max_tokens.
    """
    path = os.path.join(connections, PROVIDER_FILE)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            setting = yaml.safe_load(handle)
    except (OSError, ValueError, yaml.YAMLError):
        setting = None
    if not isinstance(setting, dict):
        messages.append("the earlier provider setting %s could not be read, so no earlier output"
                        " limit was kept from it" % path)
        return None
    limit = setting.get("token_limit")
    if limit is None:
        return None
    field = setting.get("token_limit_field") or TOKEN_LIMIT_FIELDS[0]
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0 \
            or field not in TOKEN_LIMIT_FIELDS:
        messages.append("the earlier provider setting %s names an output limit in a form setup"
                        " cannot use, so it was not kept" % path)
        return None
    return limit, field


def _earlier_timeout(connections):
    """The request_timeout an earlier provider.yaml names, read only, or None.

    Setup asks for no timeout, and provider set replaces the whole file, so a
    timeout the scholar set earlier is passed on and never dropped.
    """
    path = os.path.join(connections, PROVIDER_FILE)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            setting = yaml.safe_load(handle)
    except (OSError, ValueError, yaml.YAMLError):
        return None
    if not isinstance(setting, dict):
        return None
    wait = setting.get("request_timeout")
    if isinstance(wait, bool) or not isinstance(wait, int) or wait <= 0:
        return None
    return wait


def _set_provider(runner, root, connections, given):
    """Write provider.yaml through the connectors' own command, and give back its path."""
    args = ["provider", "set", "--base-url", given["model_service"], "--model", given["model"]]
    if given["second_model"]:
        args += ["--second-model", given["second_model"]]
    if given["token_limit"] is not None:
        args += ["--token-limit", str(given["token_limit"]),
                 "--token-limit-field", given["token_limit_field"]]
    if given.get("request_timeout") is not None:
        args += ["--request-timeout", str(given["request_timeout"])]
    args += ["--home", connections]
    _run_or_stop(runner, "connections", args, root, {CONNECTIONS_VARIABLE: connections},
                 "connections provider set")
    return os.path.join(connections, PROVIDER_FILE)


def _write_system(home, record):
    os.makedirs(home, exist_ok=True)
    path = os.path.join(home, SYSTEM_FILE)
    text = yaml.safe_dump(record, sort_keys=False, allow_unicode=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


def run_system_setup(home, audit_home, answers, root, now, detector=None, runner=run_layer,
                     connections_home=None, git_name=None):
    """Detect, check the layers, list the excluded folders first, write the provider setting
    when a service is given, and write system.yaml.

    git_name is git's user.name, looked up through the runner function only
    when the answers leave out the name and no git_name is given.
    """
    detector = detector or detect
    home = os.path.abspath(os.path.expanduser(str(home)))
    audit = os.path.abspath(os.path.expanduser(str(audit_home)))
    connections = _chosen(connections_home, CONNECTIONS_VARIABLE, DEFAULT_CONNECTIONS_HOME)
    root = os.path.abspath(str(root))
    if git_name is None and isinstance(answers, dict) and not answers.get("scholar_name"):
        git_name = git_user_name()
    given = _check_answers(answers, "the answers", git_name or "")
    messages = []

    # Read the earlier record first, so a file setup cannot read stops it
    # before it runs anything.
    earlier = _previous_folders(home)

    found = detector()
    harness = given["harness"] or default_harness(found)

    checked = collections.OrderedDict(
        (layer, {"ok": _layer_ok(runner, layer, root)}) for layer in LAYERS)

    # The first write. The excluded folders reach the audit settings before
    # anything else is written (stuck point 1).
    folders = _merged(earlier, given["excluded_folders"])
    initialized = not os.path.exists(os.path.join(audit, AUDIT_SETTINGS))
    if folders:
        _add_excluded(runner, root, audit, folders)
    elif initialized:
        _init_audit_home(runner, root, audit)

    provider = None
    if given["model_service"]:
        if given["token_limit"] is None:
            kept = _earlier_limit(connections, messages)
            if kept:
                given = dict(given, token_limit=kept[0], token_limit_field=kept[1])
                messages.append("kept the earlier output limit of %d tokens under %s, since the"
                                " answers give none" % kept)
        wait = _earlier_timeout(connections)
        if wait is not None:
            given = dict(given, request_timeout=wait)
            messages.append("kept the earlier request timeout of %d seconds" % wait)
        provider = _set_provider(runner, root, connections, given)

    export = _absolute(given["citation_export"]) if given["citation_export"] else ""
    if export and not os.path.isfile(export):
        messages.append("the citation export %s does not exist yet, so refs.bib cannot be copied"
                        " from it until the citation manager writes it" % export)

    ready = not missing_required(found) and all(item["ok"] for item in checked.values())
    record = collections.OrderedDict([
        ("schema", SCHEMA),
        ("schema_version", SCHEMA_VERSION),
        ("written_at", now.isoformat(timespec="seconds")),
        ("workflow_root", root),
        ("python", sys.executable),
        ("scholar_name", given["scholar_name"]),
        ("harness", harness),
        ("audit_home", audit),
        ("citation_export", export),
        ("excluded_folders", folders),
        ("connect", given["connect"]),
        ("layers", dict(checked)),
        ("ready", ready),
        ("software", [dict(item._asdict()) for item in found]),
    ])
    path = _write_system(home, dict(record))
    key_set = bool((os.environ.get(KEY_VARIABLE) or "").strip())
    return SystemResult(path, dict(record), found, dict(checked), initialized, folders,
                        messages, ready, provider, key_set, given["connect"])


def load_system(home):
    """The record in <home>/system.yaml, checked, or SetupError naming the setup command."""
    path = os.path.join(os.path.abspath(os.path.expanduser(str(home))), SYSTEM_FILE)
    fix = "Run %s to write it." % COMMAND
    if not os.path.isfile(path):
        raise SetupError("there is no %s. %s" % (path, fix))
    return _read_system(path, fix)


def _read_system(path, fix):
    """The checked record in system.yaml at path, or SetupError ending with fix."""
    try:
        with open(path, encoding="utf-8") as handle:
            record = yaml.safe_load(handle)
    except OSError as error:
        raise SetupError("%s cannot be read (%s). %s" % (path, error, fix))
    except yaml.YAMLError as error:
        raise SetupError("%s is not YAML that can be read (%s). %s" % (path, error, fix))
    if not isinstance(record, dict):
        raise SetupError("%s is not a mapping. %s" % (path, fix))
    if record.get("schema") != SCHEMA or record.get("schema_version") != SCHEMA_VERSION:
        raise SetupError("%s is not a %s file of version %d. %s"
                         % (path, SCHEMA, SCHEMA_VERSION, fix))
    absent = [field for field in SYSTEM_FIELDS if field not in record]
    if absent:
        raise SetupError("%s lacks %s. %s" % (path, ", ".join(absent), fix))
    return record


# The command.


def _interactive():
    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def add_command(commands):
    parser = commands.add_parser(
        "system", help="set up the scholar's system once",
        description="Ask the scholar's decisions in order, then check and record the scholar's"
                    " software and harness once per scholar.")
    parser.add_argument("--home", help="the features home, else FEATURES_HOME, else "
                        + DEFAULT_HOME)
    parser.add_argument("--audit-home", help="the audit home, else AUDIT_HOME, else "
                        + DEFAULT_AUDIT_HOME)
    parser.add_argument("--answers", help="a YAML file giving " + ", ".join(FIELDS))
    parser.set_defaults(run=command)


def _report(result, out):
    out.write("Software\n")
    for item in result.found:
        if item.ok and not item.version and item.note:
            line = "  %s, %s" % (item.name, item.note)
        elif item.ok:
            line = "  %s %s" % (item.name, item.version or "found")
            if item.note:
                line += ", " + item.note
        elif item.found:
            line = "  %s %s, %s. %s" % (item.name, item.version or "found", item.note,
                                        install_hint(item.name))
        else:
            line = "  %s missing%s. %s" % (item.name, "" if item.required else ", optional",
                                          install_hint(item.name))
        out.write(line + "\n")
    out.write("Layers\n")
    for layer, state in result.layers.items():
        out.write("  %s %s\n" % (layer, "answers" if state["ok"] else "does not answer"))
    system = result.system
    if system["harness"] == ANOTHER:
        out.write("Harness another program\n")
    elif system["harness"]:
        out.write("Harness %s\n" % system["harness"])
    else:
        out.write("Harness not found. %s. %s\n" % (install_hint("claude_code"),
                                                   install_hint("forgecode")))
    out.write("Audit home %s%s\n" % (system["audit_home"],
                                     ", initialized now" if result.audit_initialized else ""))
    out.write("Excluded folders, listed in %s\n"
              % os.path.join(system["audit_home"], AUDIT_SETTINGS))
    for folder in result.excluded_folders:
        out.write("  %s\n" % folder)
    if not result.excluded_folders:
        out.write("  none\n")
    if result.provider:
        out.write("Provider setting %s\n" % result.provider)
        if not result.key_set:
            out.write("  %s is not set. Add this line to your shell profile, %s, with the key your"
                      " model service gave you, then open a new shell.\n"
                      % (KEY_VARIABLE, shell_profile(os.path.expanduser("~"),
                                                     os.environ.get("SHELL", ""))))
            out.write("  export %s=your-key\n" % KEY_VARIABLE)
    else:
        out.write("No model service given, so no provider setting was written\n")
    for message in result.messages:
        out.write(message[:1].upper() + message[1:] + "\n")
    if result.connect == "yes":
        out.write("You said yes. Setup cannot make these changes itself yet, so make them by hand"
                  " as these say.\n")
    else:
        out.write("Setup changes nothing outside the workflow's own folders. To make the changes"
                  " by hand, follow these.\n")
    for line in LATER_CONNECTIONS:
        out.write("  %s\n" % line)
    out.write("Wrote %s\n" % result.path)
    if result.ready:
        out.write("Ready\n")
    else:
        out.write("Not ready, since a required tool or a layer is missing\n")


def command(options, out=None, err=None):
    out = out or sys.stdout
    err = err or sys.stderr
    interactive = not options.answers and _interactive()
    if not options.answers and not interactive:
        err.write("setup system refused, there is no answers file and no terminal to ask in."
                  " Give --answers FILE, a YAML file with the fields %s\n" % ", ".join(FIELDS))
        return 2
    home = features_home(options.home)
    audit = audit_home(options.audit_home)
    try:
        found = detect()
        state = detect_state(audit)
        if interactive:
            given = ask_answers(found, state, out=out)
        else:
            given = read_answers(options.answers, state.git_name)
        harness = given["harness"] or default_harness(found)
        for line in review_screen(found, state, given, harness):
            out.write(line + "\n")
        if interactive:
            given["connect"] = ask_connect(out=out)
        elif given["connect"] == "yes":
            out.write("The answers file says connect yes.\n")
        else:
            out.write("The answers file does not say connect yes, so setup changes nothing"
                      " outside the workflow's own folders.\n")
        result = run_system_setup(
            home, audit, given, default_root(), datetime.datetime.now(datetime.timezone.utc),
            detector=lambda: found, connections_home=connections_home(None),
            git_name=state.git_name)
    except SetupError as error:
        err.write("setup system stopped, %s\n" % error)
        return 1
    _report(result, out)
    return 0 if result.ready else 1
