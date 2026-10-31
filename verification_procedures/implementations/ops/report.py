"""Write a report with the settings, the file counts, and each command with its result.

Shared by the operational procedures. The title is the settings' task. The Files
section appears only when the file check ran, and the SSH entry section only when the
ssh entry was compared, with the entry to add in a code fence. The Commands section
lists each command with its result, from applied.json when the run step ran and from
commands.json when only the plan exists.
"""
import json
import os
import shlex

import _lib

settings = _lib.read_json("settings.json")
findings = _lib.collect_findings()
_lib.write_json("findings.json", findings)


def value(v):
    return json.dumps(v, ensure_ascii=False, sort_keys=True) if not isinstance(v, str) else (v or "(empty)")


rows = ["| Field | Value |", "|---|---|"]
rows += ["| {} | {} |".format(key, _lib.cell(value(settings[key]), limit=300)) for key in sorted(settings)]
sections = [("Settings", "\n".join(rows))]

if os.path.exists(_lib.path("files.json")):
    files = _lib.read_json("files.json")
    lines = ["- Files in the project tar, {}".format(files["files"]),
             "- Files to commit, {}".format(len(files["commit"])),
             "- Files excluded, {}".format(len(files["excluded"])),
             "- Lines for .gitignore, {}".format(len(files["gitignore"])),
             "- Blocking problems in the files, {}".format(files["blocked"]),
             "- A repository already there, {}".format("yes" if files["already_repo"] else "no")]
    sections.append(("Files", "\n".join(lines)))

if os.path.exists(_lib.path("ssh_entry.json")):
    entry = _lib.read_json("ssh_entry.json")
    lines = ["- A copy of the ssh config given, {}".format("yes" if entry["given"] else "no"),
             "- An entry for the alias present, {}".format("yes" if entry["present"] else "no"),
             "- The entry matches the settings, {}".format("yes" if entry["matches"] else "no"),
             "",
             "The entry to add to the ssh config by hand, when it is missing or differs.",
             "",
             "```",
             entry["block"].rstrip("\n"),
             "```"]
    sections.append(("SSH entry", "\n".join(lines)))


def commands_section():
    if os.path.exists(_lib.path("applied.json")):
        results = _lib.read_json("applied.json")["results"]
    elif os.path.exists(_lib.path("commands.json")):
        results = [{"n": c["n"], "argv": c["argv"], "status": "planned"}
                   for c in _lib.read_json("commands.json")["commands"]]
    else:
        return "None planned."
    if not results:
        return "None planned."
    rows = ["| n | Command | Result | Exit |", "|---|---|---|---|"]
    for r in results:
        exit_code = r.get("exit_code")
        rows.append("| {} | {} | {} | {} |".format(r["n"], _lib.cell(shlex.join(r["argv"]), limit=300), r["status"],
                                                   "-" if exit_code is None else exit_code))
    return "\n".join(rows)


sections.append(("Commands", commands_section()))

intro = ("Planned commands run only when the settings file sets apply to true. "
         "This run had apply set to {}.".format("true" if settings["apply"] else "false"))
_lib.write_text("report.md", _lib.report(settings["task"], intro, findings, sections))
