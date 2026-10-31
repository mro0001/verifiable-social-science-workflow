"""Plan the commands that start the repository, stage the checked files by path,
commit, name the remote, and push, and the .gitignore to write first. Each .gitignore
line is an exclude entry anchored to the project folder, so a name without a slash
leaves out only that path, as the file check does. An entry without a trailing slash
is followed by the same entry with '!' before it and '/' after it, so git leaves out a
file of that name but not a folder, again as the file check does.

Nothing runs here. run_commands runs the plan only when the settings file sets apply
to true. The commit author is never set, so the identity is the scholar's git settings.
"""
import _lib

GROUP = 100


def ignore_line(entry):
    """The .gitignore line for one exclude entry, anchored to the project folder and
    with git's pattern characters escaped, so git leaves out exactly the paths the
    file check excluded."""
    text = "".join("\\" + ch if ch in "\\*?[" else ch for ch in entry)
    if text.endswith(" "):
        text = text[:-1] + "\\ "
    return "/" + text


def ignore_lines(entry):
    """The .gitignore lines for one exclude entry. An entry ending in '/' covers a
    folder. Any other entry names a file only, so a folder of that name is kept."""
    line = ignore_line(entry)
    return [line] if entry.endswith("/") else [line, "!" + line + "/"]


settings = _lib.read_json("settings.json")
files = _lib.read_json("files.json")

writes = []
paths = list(files["commit"])
if files["gitignore"] and ".gitignore" not in files["snapshot"]:
    writes.append({"path": ".gitignore", "text": "".join(ln + "\n" for e in files["gitignore"] for ln in ignore_lines(e))})
    paths.append(".gitignore")
paths.sort()

branch = settings["branch"]
steps = [(["git", "init", "-b", branch], "Start a repository in the project folder on branch {}.".format(branch))]
for start in range(0, len(paths), GROUP):
    group = paths[start:start + GROUP]
    steps.append((["git", "add", "--"] + group,
                  "Stage {} of the checked files, each by its path.".format(len(group))))
steps.append((["git", "commit", "-m", settings["message"]], "Commit the staged files."))
if settings["create_with"] == "gh":
    full = "{}/{}".format(settings["owner"], settings["repo_name"])
    steps.append((["gh", "repo", "create", full, "--" + settings["visibility"], "--source", ".",
                   "--remote", "origin"],
                  "Create the {} repository {} on GitHub and name it as the remote.".format(
                      settings["visibility"], full)))
else:
    steps.append((["git", "remote", "add", "origin", settings["remote_url"]],
                  "Name the repository the scholar made as the remote."))
steps.append((["git", "push", "-u", "origin", branch], "Push branch {} to the remote.".format(branch)))

_lib.write_json("commands.json", {
    "cwd": settings["project_dir"],
    "snapshot": files["snapshot"],
    "writes": writes,
    "commands": [{"n": n, "argv": argv, "why": why} for n, (argv, why) in enumerate(steps, 1)],
})
