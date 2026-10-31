"""Checking each entry's source against its recorded checksum (appendix A2.4
"Managing entries").

An entry records its source and a checksum of that source when the entry was
written. source_status compares the recorded checksum with the file at
<root>/<source> today, so a session can see which entries may be stale. It
reads nothing outside root. Rewriting a stale entry stays by hand.
"""
import hashlib
import os
import re
from pathlib import Path

from audit_layer.kb.entries import load

STATUSES = ("same", "changed", "not_found", "not_checked")

_SHA = re.compile(r"sha256:([0-9a-f]{12})")
_WEB = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://")


def _file_under(root, source):
    """The source's file inside root, or None when the source is absolute, holds
    '..', is not a file, or leads outside root through a link."""
    if not source or os.path.isabs(source) or ".." in re.split(r"[\\/]", source):
        return None
    root = Path(root).resolve()
    path = (root / source).resolve()
    if path != root and root not in path.parents:
        return None
    return path if path.is_file() else None


def _checksum(path):
    digest = hashlib.sha256()
    with open(str(path), "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()[:12]


def source_status(corpus, root):
    """One row per entry, sorted by id, {id, source, recorded, current, status}.

    The status is not_checked for a source recorded by a git short hash or one
    that is a web address, not_found for a source that is absolute, holds '..',
    or is not a file under root, same when the first 12 hex characters of the
    file's sha256 equal the recorded ones, and changed otherwise. A recorded
    value that is neither form is not_checked too, since there is nothing to
    compare it with. current is the file's checksum in the recorded form, or
    empty when no file was read.
    """
    rows = []
    for parsed in load(corpus):
        front = parsed["front"]
        ident = front.get("id") or Path(parsed["rel"]).stem
        source = front.get("source", "")
        recorded = front.get("source_commit", "")
        current = ""
        match = _SHA.fullmatch(recorded)
        if _WEB.match(source) or match is None:
            status = "not_checked"
        else:
            path = _file_under(root, source)
            if path is None:
                status = "not_found"
            else:
                current = _checksum(path)
                status = "same" if current == recorded else "changed"
        rows.append({"id": ident, "source": source, "recorded": recorded, "current": current, "status": status})
    return sorted(rows, key=lambda row: row["id"])


def counts(rows):
    """The number of rows with each status, in the order of STATUSES."""
    return {status: sum(1 for row in rows if row["status"] == status) for status in STATUSES}
