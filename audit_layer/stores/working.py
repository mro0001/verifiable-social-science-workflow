"""The working store, snapshots of the working files AI sessions produced or edited.

Proposal Overview paragraph 2 gives the databases stores for scholarly
manuscripts. Appendix Table A3's Working row keeps snapshots of notes,
scripts, and drafts, with the workspace-relative path and kind of each, and
Figure A4 says the sweep also snapshots working files. Spec 0.11 "Working"
says the sweep reads the workspace and never owns it, and the kept path lets
a working file be written back into the layout it came from. Each snapshot's
bytes are kept once in the file store, with checksum and size (decision log
of 2026-08-05).

Which files, and of what kind (plan choice 18).

- kind_of(path) gives script for a .py, .R, .r, .sh, .jl, .do, .sql, .qmd, or
  .Rmd file, note for a .md, .txt, or .tex file with a folder named notes in
  its relative path, draft for any other .md, .txt, or .tex file, and None
  for any other file.
- snapshot_session(store, session_row, events) takes each event with role
  produced or edited whose file is inside the session's project folder, is
  still there, and is of a kind, and keeps its bytes with a new row when
  they differ from the latest snapshot of that path. Each file is read once
  however many events name it. A file that cannot be read is passed over, so
  one file never stops the others.

A session whose adapter lacks the AI flag is not snapshotted (reconciliation,
Track A section), and no folder is passed over for being excluded, since
excluded folders guard only what runs inside them (reconciliation, item 3).
A file is inside the project folder when its real path is, with links
followed, so a link out of the folder does not count. Files the scholar edits
by hand are not snapshotted.
"""
import os
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Sequence

from audit_layer.capture import ADAPTERS
from audit_layer.store import Store, add_row, current, put_file

VERSION = 1

ORIGIN = "sweep"
METHOD = f"working snapshot {VERSION}"
REASON = "snapshot"

_SCRIPTS = (".py", ".R", ".r", ".sh", ".jl", ".do", ".sql", ".qmd", ".Rmd")
_TEXTS = (".md", ".txt", ".tex")
_ROLES = ("produced", "edited")


class SnapshotSummary(NamedTuple):
    """What one session's snapshot did, counted by file."""

    # Files whose bytes were kept with a new row.
    taken: int
    # Files whose bytes equal the latest snapshot of their path.
    unchanged: int


def kind_of(path) -> Optional[str]:
    """The kind of the file at path, relative to its project folder, or None."""
    given = Path(str(path))
    suffix = given.suffix
    if suffix in _SCRIPTS:
        return "script"
    if suffix in _TEXTS:
        return "note" if "notes" in given.parts[:-1] else "draft"
    return None


def snapshot_session(
    store: Store, session_row: Dict[str, Any], events: Sequence[Dict[str, Any]]
) -> SnapshotSummary:
    """Keep the session's produced and edited working files that changed since their last snapshot.

    session_row is the session's current row, whose project is its folder,
    and events are its events (queries.session_events). Every row written
    names the session's id as its session.
    """
    reader = ADAPTERS.get(session_row["harness"])
    project = session_row.get("project")
    if reader is None or getattr(reader, "AI", False) is not True or not project:
        return SnapshotSummary(0, 0)
    top = os.path.realpath(project)
    provenance = {
        "session": session_row["harness_session_id"],
        "origin": ORIGIN,
        "method": METHOD,
        "reason": REASON,
    }
    taken = unchanged = 0
    for path, rel in _files(top, events):
        kind = kind_of(rel)
        if kind is None or not os.path.isfile(path):
            continue
        try:
            data = Path(path).read_bytes()
        except OSError:
            continue
        checksum = put_file(store, data)
        rows = current(store, "snapshots", project=project, path=rel)
        if rows and rows[-1]["file_sha256"] == checksum:
            unchanged += 1
            continue
        fields = {
            "project": project,
            "path": rel,
            "kind": kind,
            "file_sha256": checksum,
            "byte_size": len(data),
        }
        add_row(store, "snapshots", fields, provenance)
        taken += 1
    return SnapshotSummary(taken, unchanged)


def _files(top: str, events: Sequence[Dict[str, Any]]) -> List[tuple]:
    """Each produced or edited file inside the folder top, once, as (real path, relative path)."""
    found = []
    seen = set()
    for event in events:
        if event.get("role") not in _ROLES or not event.get("object"):
            continue
        real = os.path.realpath(event["object"])
        if real in seen or not real.startswith(top.rstrip(os.sep) + os.sep):
            continue
        seen.add(real)
        found.append((real, Path(os.path.relpath(real, top)).as_posix()))
    return found
