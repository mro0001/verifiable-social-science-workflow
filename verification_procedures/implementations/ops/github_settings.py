"""Read the settings file, fill each missing field with its default, and block on a
missing folder, a bad repository name, or a missing remote or owner.

Every field of settings.json is written, with its default when it is missing or wrong,
so the contract holds. Each problem is blocking, and an unknown key is a warning.
"""
import os
import re

import _lib

CHECK = "github_settings"
TASK = "Add a project to version control on GitHub"
NAME = re.compile(r"^[A-Za-z0-9._-]+$")
DEFAULTS = {
    "apply": False,
    "project_dir": "",
    "repo_name": "",
    "owner": "",
    "visibility": "private",
    "create_with": "none",
    "remote_url": "",
    "branch": "main",
    "message": "First commit of the project",
    "exclude": [],
    "max_file_mb": 100,
    "warn_file_mb": 50,
}
REQUIRED = ("project_dir", "repo_name")


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def text(value):
    return isinstance(value, str) and value != ""


def exclude_ok(value):
    if not isinstance(value, list):
        return False
    for entry in value:
        if not text(entry) or os.path.isabs(entry) or ".." in entry.rstrip("/").split("/"):
            return False
    return True


RULES = {
    "apply": (lambda v: isinstance(v, bool), "must be true or false"),
    "project_dir": (lambda v: text(v) and os.path.isabs(v), "must be an absolute path"),
    "repo_name": (lambda v: isinstance(v, str) and NAME.match(v) is not None,
                  "may hold only letters, digits, '.', '_', and '-'"),
    "owner": (lambda v: isinstance(v, str), "must be text"),
    "visibility": (lambda v: v in ("private", "public"), "must be private or public"),
    "create_with": (lambda v: v in ("gh", "none"), "must be gh or none"),
    "remote_url": (lambda v: isinstance(v, str), "must be text"),
    "branch": (text, "must be text that is not empty"),
    "message": (text, "must be text that is not empty"),
    "exclude": (exclude_ok, "must be a list of relative paths without '..'"),
    "max_file_mb": (lambda v: is_number(v) and v > 0, "must be a number above 0"),
    "warn_file_mb": (lambda v: is_number(v) and v > 0, "must be a number above 0"),
}

findings = []
settings = dict(DEFAULTS)
try:
    raw = _lib.read_yaml("github.yaml")
except Exception as err:  # a file that is not YAML is reported, not raised
    raw = err
if raw is None:
    raw = {}
if not isinstance(raw, dict):
    findings.append(_lib.finding(CHECK, "blocking", "github.yaml",
                                 "The settings file could not be read as a set of fields.",
                                 str(raw)[:200] if isinstance(raw, Exception) else type(raw).__name__))
else:
    for key in sorted(raw, key=str):
        if key not in DEFAULTS:
            findings.append(_lib.finding(CHECK, "warning", key, "The settings file has a field this procedure does not use."))
    for key in sorted(DEFAULTS):
        if key not in raw:
            if key in REQUIRED:
                findings.append(_lib.finding(CHECK, "blocking", key, "The settings file must give {}.".format(key)))
            continue
        ok, rule = RULES[key]
        if ok(raw[key]):
            settings[key] = raw[key]
        else:
            findings.append(_lib.finding(CHECK, "blocking", key, "{} {}.".format(key, rule), repr(raw[key])[:200]))
    create_ok = "create_with" not in raw or RULES["create_with"][0](raw["create_with"])
    if create_ok and settings["create_with"] == "none" and settings["remote_url"] == "" \
            and RULES["remote_url"][0](raw.get("remote_url", "")):
        findings.append(_lib.finding(CHECK, "blocking", "remote_url",
                                     "With create_with none the settings file must give remote_url."))
    if create_ok and settings["create_with"] == "gh" and settings["owner"] == "" \
            and RULES["owner"][0](raw.get("owner", "")):
        findings.append(_lib.finding(CHECK, "blocking", "owner",
                                     "With create_with gh the settings file must give owner."))

settings["task"] = TASK
settings["valid"] = not any(f["severity"] == "blocking" for f in findings)
_lib.write_json("settings.json", settings)
_lib.emit_findings(CHECK, findings)
