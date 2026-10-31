"""The procedure registry and the trigger settings (Track D, step D9).

Table A6 lists the procedure registry and triggers as specified, and A3 says
the registry names each stream's procedure and what starts it. The registry
is the verification layer's file verification_procedures/registry.yaml. The
triggers read it directly and read only (reconciliation item 4), since
connections imports no verification code, and take from each entry its id,
its graph, and the file patterns under triggers.files, the files whose change
makes the stream out of date.

The command that starts a procedure for a project is written by the scholar,
one per procedure, in <connections home>/triggers.yaml under start, with
{project} standing for the project folder (Track D choice 19). The file may
also name another registry under registry.

triggers.yaml looks like this.

    registry: ~/my_registry.yaml        # optional
    start:
      citations: sh ~/handoffs/citations_turn.sh {project}
"""
import fnmatch
import os
import shlex
from pathlib import Path
from typing import List, Optional

import yaml

from connections.home import connections_home

# The registry in this repository, found from this file's own place.
DEFAULT_REGISTRY = Path(__file__).resolve().parents[2] / "verification_procedures" / "registry.yaml"

SETTINGS = "triggers.yaml"


class RegistryError(ValueError):
    """The registry cannot be read. The message names the file and the entry."""


def load_registry(path=None) -> List[dict]:
    """The registry's procedures, in its order, each as {id, graph, files}.

    path defaults to verification_procedures/registry.yaml in this
    repository. The file may be a list of entries or a mapping holding them
    under procedures. files comes from each entry's triggers.files, empty when
    the entry has no triggers or no files. RegistryError is raised when the
    file is missing, does not parse, or an entry is not a mapping with a text
    id, or its triggers or files are not in the registry's form.
    """
    chosen = Path(path) if path is not None else DEFAULT_REGISTRY
    try:
        data = yaml.safe_load(chosen.read_text(encoding="utf-8"))
    except (OSError, ValueError, yaml.YAMLError) as error:
        raise RegistryError(f"the registry {chosen} cannot be read, {error}")
    if isinstance(data, dict):
        data = data.get("procedures")
    if not isinstance(data, list):
        raise RegistryError(f"the registry {chosen} is not a list of procedures")
    registry = []
    for number, entry in enumerate(data, start=1):
        at = f"the registry {chosen}, entry {number}"
        if not isinstance(entry, dict):
            raise RegistryError(f"{at} is not a mapping")
        pid = entry.get("id")
        if not isinstance(pid, str) or not pid.strip():
            raise RegistryError(f"{at} has no id")
        triggers = entry.get("triggers")
        if triggers is None:
            triggers = {}
        if not isinstance(triggers, dict):
            raise RegistryError(f"{at}, {pid}, has triggers that are not a mapping")
        files = triggers.get("files")
        if files is None:
            files = []
        if not isinstance(files, list) or not all(isinstance(f, str) and f for f in files):
            raise RegistryError(f"{at}, {pid}, has triggers.files that is not a list of patterns")
        graph = entry.get("graph")
        registry.append({"id": pid, "graph": graph if isinstance(graph, str) else "", "files": list(files)})
    return registry


def matching(registry, path, project) -> List[str]:
    """The ids, in registry order, whose file patterns match the edited file.

    A pattern matches, by fnmatch, the file's path relative to the project
    folder, with / between parts, or the file's base name. A relative path is
    taken from the project folder. Links are followed. A file outside the
    project matches nothing.
    """
    top = os.path.realpath(str(project))
    edited = str(path)
    if not os.path.isabs(edited):
        edited = os.path.join(top, edited)
    edited = os.path.realpath(edited)
    try:
        relative = os.path.relpath(edited, top)
    except ValueError:
        return []
    if relative == os.curdir or relative == os.pardir or relative.startswith(os.pardir + os.sep):
        return []
    relative = relative.replace(os.sep, "/")
    name = os.path.basename(edited)
    found = []
    for entry in registry:
        for pattern in entry["files"]:
            if fnmatch.fnmatchcase(relative, pattern) or fnmatch.fnmatchcase(name, pattern):
                found.append(entry["id"])
                break
    return found


def load_trigger_settings() -> dict:
    """The scholar's trigger settings, {start, registry}, from <connections home>/triggers.yaml.

    start maps each procedure id to its command. registry is the path of the
    registry the settings name, with ~ taken from the home folder and a
    relative path taken from the connections home, or None. A missing file,
    or one that cannot be read or is not in this form, gives empty settings,
    {"start": {}, "registry": None}, so a trigger starts nothing.
    """
    empty = {"start": {}, "registry": None}
    home = connections_home()
    try:
        data = yaml.safe_load((home / SETTINGS).read_text(encoding="utf-8"))
    except (OSError, ValueError, yaml.YAMLError):
        return empty
    if data is None:
        return empty
    if not isinstance(data, dict):
        return empty
    start = data.get("start")
    if start is None:
        start = {}
    if not isinstance(start, dict):
        return empty
    if not all(isinstance(k, str) and isinstance(v, str) and v.strip() for k, v in start.items()):
        return empty
    registry = data.get("registry")
    if registry is not None:
        if not isinstance(registry, str) or not registry.strip():
            return empty
        expanded = os.path.expanduser(registry)
        if not os.path.isabs(expanded):
            expanded = str(home / expanded)
        registry = expanded
    return {"start": dict(start), "registry": registry}


def start_command(settings, procedure_id, project) -> Optional[str]:
    """The command that starts procedure_id for project, or None when there is none.

    Every {project} in the scholar's command is replaced by the project
    folder, quoted for the shell with shlex.quote.
    """
    command = (settings.get("start") or {}).get(procedure_id)
    if not isinstance(command, str) or not command.strip():
        return None
    return command.replace("{project}", shlex.quote(str(project)))
