"""The projects table, one row for each project (Track A, Step A17).

Appendix Table A3's Shared tables row keeps a row for each project, and
Figure A4 draws the projects table among the shared tables. A session's
project is the folder it ran in (slice plan choice 4). Capture adds a project
row the first time a session runs in a folder, named after the folder's last
part (plan choice 19), so a project exists once work starts accruing in it.
Projects are a row and never a container (spec 0.11), so a session names its
project by folder and nothing is moved.

- ensure_project(store, folder, provenance) adds a row when no current row
  has the folder, and otherwise gives the existing row's id.
- list_projects(store) gives each current project, in the order added, with
  its number of current sessions.

Renaming or merging projects is not built.
"""
import os
from typing import Any, Dict, List, NamedTuple

from audit_layer.store import Store, add_row, current

VERSION = 1
METHOD = f"projects {VERSION}"
REASON = "first session in folder"


class ProjectCount(NamedTuple):
    """A project's current row and the number of current sessions run in its folder."""

    project: Dict[str, Any]
    sessions: int


def name_of(folder: str) -> str:
    """The folder's last part, which names the project, else the folder as given."""
    return os.path.basename(str(folder).rstrip("/\\")) or str(folder)


def ensure_project(store: Store, folder: str, provenance: Dict[str, str]) -> str:
    """The id of the current project row for folder, adding the row when there is none."""
    rows = current(store, "projects", folder=str(folder))
    if rows:
        return rows[0]["id"]
    return add_row(store, "projects", {"folder": str(folder), "name": name_of(folder)}, provenance)


def list_projects(store: Store) -> List[ProjectCount]:
    """Each current project, in the order added, with its number of current sessions.

    A subagent conversation is a session of its own (plan choice 5), so it is
    counted in the folder it ran in.
    """
    counts = {}  # type: Dict[str, int]
    for row in current(store, "sessions"):
        counts[row["project"]] = counts.get(row["project"], 0) + 1
    return [ProjectCount(row, counts.get(row["folder"], 0)) for row in current(store, "projects")]
