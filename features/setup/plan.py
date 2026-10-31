"""The setup plan (step S1).

python3 -m features setup plan [--json] [--home DIR] [--audit-home DIR] [--connections-home DIR]

Runs detection, then prints each decision in decisions.py with its state.

  found    detection settled it, and the detail says with what
  missing  detection looked and found nothing, and the detail says what to do
  default  the default is taken, and the detail gives its value
  open     the scholar answers it, and the question is shown

It writes nothing anywhere. --json prints the same as one JSON object, for
the AI session that walks the scholar through setup (scope report section 3).
The model key is never read beyond whether it is set.

Besides detection, the plan reads two files read only, the provider setting
<connections home>/provider.yaml (base_url, model, second_model, token_limit,
token_limit_field and nothing else) and, through detection, the audit
settings <audit home>/settings.yaml.
"""
import collections
import json
import os
import sys

import yaml

from features.setup import decisions, detect
from features.setup.system import (DEFAULT_CONNECTIONS_HOME, PROVIDER_FILE, audit_home,
                                   connections_home, features_home)

PROVIDER_KEYS = ("base_url", "model", "second_model", "token_limit", "token_limit_field")

STATES = ("found", "missing", "default", "open")
ROW_FIELDS = decisions.Decision._fields + ("state", "detail")

HARNESS_NAMES = (("claude_code", "Claude Code"), ("forgecode", "ForgeCode"))
CAPTURE_EVENTS = ("SessionEnd", "Stop", "SubagentStop")

Homes = collections.namedtuple("Homes", "features audit connections")


def read_provider(home, notes):
    """The provider setting's named keys, or {} when there is none. Nothing else is kept."""
    path = os.path.join(home, PROVIDER_FILE)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            setting = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as error:
        notes.append("the provider setting %s cannot be read (%s)" % (path, error))
        return {}
    if not isinstance(setting, dict):
        notes.append("the provider setting %s is not a mapping" % path)
        return {}
    return dict((key, setting[key]) for key in PROVIDER_KEYS
                if setting.get(key) not in (None, ""))


def _found(software):
    return dict((item.name, item) for item in software)


def _described(item):
    if item.version:
        return "%s %s" % (item.path or item.name, item.version)
    return item.path or item.name


def _harness(tools):
    present = ["%s at %s" % (label, _described(tools[name]))
               for name, label in HARNESS_NAMES if tools[name].found]
    if present:
        return "found", ", ".join(present)
    return "open", "Claude Code and ForgeCode were not found. %s. %s." % (
        detect.install_hint("claude_code"), detect.install_hint("forgecode"))


def _missing_tools(tools, names):
    return [tools[name] for name in names if not tools[name].ok]


def _pandoc_make(tools):
    absent = _missing_tools(tools, ("pandoc", "make"))
    if absent:
        return "missing", " ".join("%s missing. %s." % (item.name, detect.install_hint(item.name))
                                   for item in absent)
    return "found", ", ".join(_described(tools[name]) for name in ("pandoc", "make"))


def _version_control(tools):
    if not tools["git"].found:
        return "missing", "git missing. %s." % detect.install_hint("git")
    parts = [_described(tools["git"])]
    if tools["gh"].found:
        parts.append("the GitHub command line " + _described(tools["gh"]))
    else:
        parts.append("no GitHub command line")
    return "found", ", ".join(parts)


def _statistics(tools):
    parts = ["Python " + tools["python"].version]
    for name, label in (("rscript", "R"), ("quarto", "Quarto")):
        if tools[name].found:
            parts.append("%s at %s" % (label, _described(tools[name])))
    return "found", ", ".join(parts) + ". Stata is not looked for."


def _word(tools):
    if tools["word"].found:
        return "found", "Microsoft Word at %s" % tools["word"].path
    return "missing", "Microsoft Word not found, so prose review reads the plain-text file"


def _excluded(state):
    if state.excluded_folders is None:
        return "open", "The audit settings file does not exist yet."
    if not state.excluded_folders:
        return "open", "None listed yet in the audit settings."
    return "open", "Already listed in the audit settings, %s." % ", ".join(state.excluded_folders)


def _citation_export(tools):
    found = [tools[name].path for name in ("zotero", "zotero_data") if tools[name].found]
    if found:
        return "open", "Zotero found at %s." % " and ".join(found)
    return "open", ""


def _provider_value(provider, key):
    if key in provider:
        return "found", "provider.yaml names %s" % provider[key]
    return "open", ""


def _token_limit(provider, item):
    if "token_limit" in provider:
        return "found", "provider.yaml names %s tokens under %s" % (
            provider["token_limit"], provider.get("token_limit_field", "max_tokens"))
    return "default", item.default


def _servers(state):
    if state.servers is None:
        return "open", "Not checked, since Claude Code was not found or claude mcp list failed."
    if len(state.servers) == len(detect.SERVERS):
        return "found", "Registered with Claude Code, %s." % ", ".join(state.servers)
    if state.servers:
        return "open", "Registered now, %s." % ", ".join(state.servers)
    return "open", "Not registered yet."


def _connect(state):
    capture = state.hooks.get("capture", [])
    servers = state.servers or []
    if set(CAPTURE_EVENTS) <= set(capture) and len(servers) == len(detect.SERVERS):
        return "found", "The capture hooks and the three servers are in place."
    parts = []
    if capture:
        parts.append("The capture hook is in ~/.claude/settings.json for %s." % ", ".join(capture))
    else:
        parts.append("No capture hook in ~/.claude/settings.json yet.")
    trigger = state.hooks.get("trigger", [])
    if trigger:
        parts.append("The trigger hook is there for %s." % ", ".join(trigger))
    return "open", " ".join(parts)


def _state_of(item, tools, state, provider, homes):
    """(state, detail) of one decision."""
    if item.id == "excluded_folders":
        return _excluded(state)
    if item.id == "scholar_name":
        if state.git_name:
            return "found", "git's user.name, %s" % state.git_name
        return "open", "git's settings hold no user.name."
    if item.id in ("model_service", "model", "second_model"):
        return _provider_value(provider, "base_url" if item.id == "model_service" else item.id)
    if item.id == "model_key":
        if state.model_key_set:
            return "found", "%s is set" % detect.KEY_VARIABLE
        return "missing", "%s is not set" % detect.KEY_VARIABLE
    if item.id == "token_limit":
        return _token_limit(provider, item)
    if item.id == "citation_export":
        return _citation_export(tools)
    if item.id == "harness":
        return _harness(tools)
    if item.id == "statistical_software":
        return _statistics(tools)
    if item.id in ("word", "word_review"):
        return _word(tools)
    if item.id == "version_control":
        return _version_control(tools)
    if item.id == "pandoc_make":
        return _pandoc_make(tools)
    if item.id == "homes":
        return "default", "features home %s, audit home %s, connections home %s" % homes
    if item.id == "servers":
        return _servers(state)
    if item.id == "connect":
        return _connect(state)
    if item.how == "default":
        return "default", item.default
    return "open", ""


def build_plan(homes, software, state, provider):
    """Each decision as an ordered mapping of its fields, its state, and its detail."""
    tools = _found(software)
    plan = []
    for item in decisions.DECISIONS:
        chosen, detail = _state_of(item, tools, state, provider, tuple(homes))
        row = collections.OrderedDict(zip(decisions.Decision._fields, item))
        row["state"] = chosen
        row["detail"] = detail or ""
        plan.append(row)
    return plan


def run_plan(home=None, audit=None, connections=None):
    """Detect and give back (plan, notes). Nothing is written."""
    homes = Homes(features_home(home), audit_home(audit), connections_home(connections))
    software = detect.detect()
    state = detect.detect_state(homes.audit)
    notes = list(state.notes)
    provider = read_provider(homes.connections, notes)
    return build_plan(homes, software, state, provider), notes


# The command.


def add_command(commands):
    parser = commands.add_parser(
        "plan", help="list setup's decisions with what is found, writing nothing",
        description="Run detection and print each setup decision as found, missing, default,"
                    " or open, writing nothing anywhere.")
    parser.add_argument("--json", action="store_true",
                        help="print the plan as one JSON object, for an AI session")
    parser.add_argument("--home", help="the features home, else FEATURES_HOME, else "
                        "~/.workflow_features")
    parser.add_argument("--audit-home", help="the audit home, else AUDIT_HOME, else "
                        "~/.audit_layer")
    parser.add_argument("--connections-home", help="the connections home, else CONNECTIONS_HOME,"
                        " else " + DEFAULT_CONNECTIONS_HOME)
    parser.set_defaults(run=command)


def _text(plan, notes, out):
    out.write("Setup plan, found without writing anything\n")
    for scope, heading in (("system", "Once per scholar"), ("project", "Once per project")):
        out.write(heading + "\n")
        for row in plan:
            if row["scope"] != scope:
                continue
            out.write("  %s, %s\n" % (row["id"], row["state"]))
            if row["state"] == "open":
                out.write("    %s\n" % row["question"])
            if row["detail"]:
                out.write("    %s\n" % row["detail"])
    if notes:
        out.write("Notes\n")
        for note in notes:
            out.write("  %s\n" % (note[:1].upper() + note[1:]))


def command(options, out=None):
    out = out or sys.stdout
    plan, notes = run_plan(options.home, options.audit_home, options.connections_home)
    if options.json:
        out.write(json.dumps(collections.OrderedDict([("decisions", plan), ("notes", notes)]),
                             indent=2) + "\n")
    else:
        _text(plan, notes, out)
    return 0
