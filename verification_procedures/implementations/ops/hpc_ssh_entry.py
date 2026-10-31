"""Find the alias's Host entry in the copy of the ssh config, say whether its host
name, user, and identity file match the settings, and write the entry to add, without
opening the identity file.

Host lines start blocks and Match blocks are skipped. Keywords match in any case,
values split at spaces or '=', and quotes are stripped. present means a Host line names
the alias exactly, and the first such block is the one compared, with the first value
of each keyword in it, as ssh takes the first value it finds. An Include line is an
info note, since the files it names are not part of the copy. The copy is the only
file read, and it is never written.
"""
import os
import re

import _lib

CHECK = "hpc_ssh_entry"
FIELDS = (("HostName", "host"), ("User", "user"), ("IdentityFile", "identity_file"))
LINE = re.compile(r"^\s*([^\s=]+)\s*=?\s*(.*?)\s*$")


def unquote(value):
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1]
    return value


def config_value(value):
    """A value as the block writes it, quoted when it holds a space."""
    return '"{}"'.format(value) if any(ch.isspace() for ch in value) else value


def parse(text):
    """The Host blocks of the config as [(patterns, {keyword lowercased: first value})]
    and the Include values, in file order."""
    blocks, includes, current = [], [], None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = LINE.match(line)
        if not m:
            continue
        key, value = m.group(1).lower(), m.group(2)
        if key == "include":
            includes.append(value)
            continue
        if key == "host":
            current = ([unquote(p) for p in value.split()], {})
            blocks.append(current)
            continue
        if key == "match":
            current = None
            continue
        if current is not None:
            current[1].setdefault(key, unquote(value))
    return blocks, includes


settings = _lib.read_json("settings.json")
alias = settings["alias"]
findings = []
block = "Host {}\n".format(alias) + "".join(
    "    {} {}\n".format(keyword, config_value(settings[field])) for keyword, field in FIELDS
) + "    IdentitiesOnly yes\n"

given = os.path.exists(_lib.path("ssh_config"))
present = matches = False
if not given:
    findings.append(_lib.finding(CHECK, "warning", "ssh_config",
                                 "No copy of the ssh config was given, so the entry for {} was not checked. "
                                 "Add the entry in the report to the ssh config by hand if it is not there.".format(alias)))
else:
    blocks, includes = parse(_lib.read_text("ssh_config"))
    for value in includes:
        findings.append(_lib.finding(CHECK, "info", "Include",
                                     "The ssh config includes other files, which were not checked.", value[:200]))
    found = next((values for patterns, values in blocks if alias in patterns), None)
    if found is None:
        findings.append(_lib.finding(CHECK, "warning", alias,
                                     "The ssh config has no Host entry for {}. Add the entry in the report by hand.".format(alias)))
    else:
        present = True
        matches = True
        for keyword, field in FIELDS:
            have = found.get(keyword.lower())
            if have is None:
                matches = False
                findings.append(_lib.finding(CHECK, "warning", "{} {}".format(alias, keyword),
                                             "The ssh entry for {} gives no {}, where the settings give {}.".format(
                                                 alias, keyword, settings[field])))
            elif have != settings[field]:
                matches = False
                findings.append(_lib.finding(CHECK, "warning", "{} {}".format(alias, keyword),
                                             "The ssh entry for {} gives {} {}, where the settings give {}.".format(
                                                 alias, keyword, have, settings[field]), have[:200]))

_lib.write_json("ssh_entry.json", {"given": given, "present": present, "matches": matches, "block": block})
_lib.emit_findings(CHECK, findings)
