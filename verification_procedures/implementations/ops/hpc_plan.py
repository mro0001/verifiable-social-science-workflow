"""Plan the commands that connect with no password prompt, make the project folder on
the cluster, ask the scheduler for its version, and load each module.

The plan names no folder, no snapshot, and no file to write, so run_commands runs it
without comparing a folder. The first command sets BatchMode, so ssh fails at once
instead of waiting for a password when the key is not accepted. The remote folder and
each module go to the cluster's shell, so each is quoted with shlex.quote, and each
module is loaded in a login shell, where the module command is set up. A remote folder
that is ~ or starts with ~/ keeps that part outside the quotes, so the cluster's shell
still reads it as the home folder, and only the rest is quoted.

Nothing runs here. run_commands runs the plan only when the settings file sets apply
to true.
"""
import shlex

import _lib

settings = _lib.read_json("settings.json")
_lib.read_json("ssh_entry.json")  # read so the plan follows the entry check, as the contract says
alias = settings["alias"]


def remote_folder(path):
    """The remote folder as one argument for the cluster's shell, with a leading ~ or ~/
    left unquoted so the shell expands it."""
    if path == "~":
        return "~"
    if path.startswith("~/"):
        rest = path[2:]
        return "~/" + (shlex.quote(rest) if rest else "")
    return shlex.quote(path)


steps = [
    (["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", alias, "true"],
     "Connect to {} with no password prompt.".format(alias)),
    (["ssh", alias, "mkdir", "-p", remote_folder(settings["remote_dir"])],
     "Make the project folder {} on the cluster if it is not there.".format(settings["remote_dir"])),
]
if settings["scheduler"] == "slurm":
    steps.append((["ssh", alias, "sinfo", "--version"], "Ask the Slurm scheduler for its version."))
for module in settings["modules"]:
    steps.append((["ssh", alias, "bash -lc " + shlex.quote("module load " + shlex.quote(module))],
                  "Load the module {} on the cluster.".format(module)))

_lib.write_json("commands.json", {
    "cwd": "",
    "snapshot": {},
    "writes": [],
    "commands": [{"n": n, "argv": argv, "why": why} for n, (argv, why) in enumerate(steps, 1)],
})
