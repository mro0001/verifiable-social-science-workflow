"""Read the settings file, fill each missing field with its default, and block on a
missing or badly formed alias, host, user, identity file, or remote folder, or a
scheduler this procedure does not know.

Every field of settings.json is written, with its default when it is missing or wrong,
so the contract holds. Each problem is blocking, and an unknown key is a warning, as in
github_settings. The alias must also start with a letter or a digit, since it is passed
to ssh as an argument and a leading '-' would read as an option. The remote folder may
not start with '-' either, since it is passed to mkdir -p on the cluster. The identity
file is named by its path and never opened.
"""
import re

import _lib

CHECK = "hpc_settings"
TASK = "Connect a project to a university computing cluster"
NAME = re.compile(r"^[A-Za-z0-9._-]+$")
DEFAULTS = {
    "apply": False,
    "alias": "",
    "host": "",
    "user": "",
    "identity_file": "",
    "scheduler": "slurm",
    "modules": [],
    "remote_dir": "",
}
REQUIRED = ("alias", "host", "user", "identity_file", "remote_dir")


def text(value):
    return isinstance(value, str) and value != ""


def one_line(value):
    return text(value) and "\n" not in value and "\r" not in value


def name(value):
    return isinstance(value, str) and NAME.match(value) is not None


RULES = {
    "apply": (lambda v: isinstance(v, bool), "must be true or false"),
    "alias": (lambda v: name(v) and v[0].isalnum(),
              "may hold only letters, digits, '.', '_', and '-', and must start with a letter or a digit"),
    "host": (one_line, "must be text on one line that is not empty"),
    "user": (name, "may hold only letters, digits, '.', '_', and '-'"),
    "identity_file": (one_line, "must be text on one line that is not empty"),
    "scheduler": (lambda v: v in ("slurm", "none"), "must be slurm or none"),
    "modules": (lambda v: isinstance(v, list) and all(one_line(m) for m in v),
                "must be a list of module names, each text on one line that is not empty"),
    "remote_dir": (lambda v: one_line(v) and not v.startswith("-"),
                   "must be text on one line that is not empty and does not start with '-'"),
}

findings = []
settings = dict(DEFAULTS)
try:
    raw = _lib.read_yaml("hpc.yaml")
except Exception as err:  # a file that is not YAML is reported, not raised
    raw = err
if raw is None:
    raw = {}
if not isinstance(raw, dict):
    findings.append(_lib.finding(CHECK, "blocking", "hpc.yaml",
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

settings["task"] = TASK
settings["valid"] = not any(f["severity"] == "blocking" for f in findings)
_lib.write_json("settings.json", settings)
_lib.emit_findings(CHECK, findings)
