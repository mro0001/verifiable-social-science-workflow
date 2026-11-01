"""Read the settings file, fill each missing field with its default, and block on a
value of the wrong kind or a workflow folder that is not an absolute path.

Every field of settings.json is written, with its default when it is missing or wrong,
so the contract holds. A bad value is blocking, and an unknown key is a warning. With
no workflow folder the products cannot be rebuilt, so rebuild is turned off with a
note. The evidence of a bad term or allow entry names only its place in the list, so
the report never prints a term.
"""
import os

import _lib

CHECK = "publish_settings"
TASK = "Check a verification repository before it is published"
DEFAULTS = {
    "workflow_root": "",
    "terms": [],
    "allow": [],
    "max_file_mb": 100,
    "warn_file_mb": 50,
    "rebuild": True,
    "excluded_folders": [],
    "excluded_paths": [],
}
ALLOW_KEYS = ("text", "path")
HIDDEN = ("terms", "allow")


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def text(value):
    return isinstance(value, str) and value.strip() != ""


def first_bad(value, ok):
    """The 1-based place of the first entry of the list that fails ok, or 0."""
    for n, entry in enumerate(value, 1):
        if not ok(entry):
            return n
    return 0


def allow_entry_ok(entry):
    if isinstance(entry, str):
        return text(entry)
    if not isinstance(entry, dict) or not entry:
        return False
    for key, value in entry.items():
        if key not in ALLOW_KEYS or not text(value):
            return False
    return True


def folder_ok(entry):
    return text(entry) and (os.path.isabs(entry) or entry == "~" or entry.startswith("~/"))


def repo_path_ok(entry):
    """A folder's path in the repository, such as project/records, with no '..' part."""
    if not text(entry) or entry.startswith("/") or "\\" in entry:
        return False
    return ".." not in entry.split("/")


def list_ok(ok):
    return lambda v: isinstance(v, list) and first_bad(v, ok) == 0


RULES = {
    "workflow_root": (lambda v: isinstance(v, str) and (v == "" or os.path.isabs(v)),
                      "must be an absolute path, or empty"),
    "terms": (list_ok(text), "must be a list of words or names, none empty"),
    "allow": (list_ok(allow_entry_ok),
              "must be a list whose entries are text, or a mapping with only text and path, each not empty"),
    "max_file_mb": (lambda v: is_number(v) and v > 0, "must be a number above 0"),
    "warn_file_mb": (lambda v: is_number(v) and v > 0, "must be a number above 0"),
    "rebuild": (lambda v: isinstance(v, bool), "must be true or false"),
    "excluded_folders": (list_ok(folder_ok), "must be a list of absolute folders"),
    "excluded_paths": (list_ok(repo_path_ok), "must be a list of folders inside the repository, without '..'"),
}
ENTRY_RULES = {"terms": text, "allow": allow_entry_ok}


def evidence(key, value):
    """What a bad value shows: for terms and allow, the place and kind of the first bad
    entry, never its text; otherwise the value itself, cut to 200 characters."""
    if key in HIDDEN:
        if not isinstance(value, list):
            return type(value).__name__
        n = first_bad(value, ENTRY_RULES[key])
        return "entry %d is %s" % (n, type(value[n - 1]).__name__)
    return repr(value)[:200]


def error_text(err):
    """The error's text without the run's own folder, so a replay elsewhere matches."""
    out = str(err)
    for folder in sorted(set([_lib.files_dir(), os.path.realpath(_lib.files_dir())]), key=len, reverse=True):
        out = out.replace(folder + os.sep, "")
    return out[:200]


findings = []
settings = dict(DEFAULTS)
try:
    raw = _lib.read_yaml("publish_check.yaml")
except Exception as err:  # a file that is not YAML is reported, not raised
    raw = err
if raw is None:
    raw = {}
if not isinstance(raw, dict):
    findings.append(_lib.finding(CHECK, "blocking", "publish_check.yaml",
                                 "The settings file could not be read as a set of fields.",
                                 error_text(raw) if isinstance(raw, Exception) else type(raw).__name__))
else:
    for key in sorted(raw, key=str):
        if key not in DEFAULTS:
            findings.append(_lib.finding(CHECK, "warning", key,
                                         "The settings file has a field this procedure does not use."))
    for key in sorted(DEFAULTS):
        if key not in raw:
            continue
        ok, rule = RULES[key]
        if ok(raw[key]):
            settings[key] = raw[key]
        else:
            findings.append(_lib.finding(CHECK, "blocking", key, "%s %s." % (key, rule), evidence(key, raw[key])))
if settings["rebuild"] and settings["workflow_root"] == "":
    settings["rebuild"] = False
    findings.append(_lib.finding(CHECK, "info", "rebuild",
                                 "The settings give no workflow folder, so no product is rebuilt."))

settings["task"] = TASK
settings["valid"] = not any(f["severity"] == "blocking" for f in findings)
_lib.write_json("settings.json", settings)
_lib.emit_findings(CHECK, findings)
