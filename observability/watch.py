"""Live mode, the view rebuilt while the record grows.

Proposal Approach paragraphs 4 and 5 have the scholar observe AI work in real
time, and Status paragraph 3 names a live view of what the harness reads,
calls, and retrieves. Appendix A2.6 paragraph 2 uses the record as it is
written, and Figures A1 and A4 show the live view fed as records are
written. watch builds the view with live true, so the page reloads itself,
then at each interval rebuilds only when the record, the kb folders, or the
verification runs changed (plan choice 14, step E13). When it stops it builds once more with live false,
so a view reopened later does not reload itself. The record grows only when
the audit layer's capture writes to it, so the view lags the capture (plan
gap 2). Nothing here captures, sweeps, or serves.
"""
import hashlib
import os
import time
from pathlib import Path
from typing import Dict, List

from observability import build as bd
from observability.adapters import vg_run as vr

DATABASE = "audit.sqlite"
WAL_SUFFIX = "-wal"


def _stat_line(path):
    """One line naming a file with its size and modification time, or as missing."""
    try:
        found = os.stat(str(path))
    except OSError:
        return "%s missing" % path
    return "%s %d %d" % (path, found.st_size, found.st_mtime_ns)


def fingerprint(audit_home, kb_dirs, vg_runs=()) -> str:
    """A fingerprint of what the view is built from.

    It comes from the size and modification time of audit.sqlite, of its
    -wal file when there is one, and of the markdown files in the kb folders
    and their subfolders, and from the list of runs found in vg_runs with the
    size and modification time of each run's trail.jsonl and manifest.json.
    Any change to one of them, or a new run, gives another fingerprint.
    """
    database = Path(audit_home) / DATABASE
    lines = [_stat_line(database)]
    wal = database.with_name(database.name + WAL_SUFFIX)
    if wal.exists():
        lines.append(_stat_line(wal))
    for folder in kb_dirs or ():
        for path in sorted(Path(folder).rglob("*.md")):
            if path.is_file():
                lines.append(_stat_line(path))
    run_dirs, _ = vr.find_runs([str(path) for path in (vg_runs or ())])
    for run_dir in run_dirs:
        lines.append("run %s" % run_dir)
        for name in (vr.TRAIL, vr.MANIFEST):
            lines.append(_stat_line(Path(run_dir) / name))
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def watch(options, interval, cycles=None, sleep=time.sleep) -> List[Dict]:
    """Build the view live and rebuild it at each interval while it changes.

    options holds build_view's arguments by name (audit_home, out, and any of
    project, kb_dirs, kb_servers, and vg_runs). The first build has live true, and the
    page reloads every interval seconds. After each sleep of interval seconds
    the view is rebuilt only when the fingerprint changed. After cycles
    sleeps, or on an interrupt, the view is built once more with live false.
    Returns the summary of every build, in order.
    """
    options = dict(options)
    options.pop("live", None)
    options.setdefault("refresh_seconds", interval)
    kb_dirs = options.get("kb_dirs") or ()
    vg_runs = options.get("vg_runs") or ()
    summaries = []
    try:
        seen = fingerprint(options["audit_home"], kb_dirs, vg_runs)
        summaries.append(bd.build_view(live=True, **options))
        done = 0
        while cycles is None or done < cycles:
            sleep(interval)
            done += 1
            now = fingerprint(options["audit_home"], kb_dirs, vg_runs)
            if now != seen:
                seen = now
                summaries.append(bd.build_view(live=True, **options))
    except KeyboardInterrupt:
        pass
    summaries.append(bd.build_view(live=False, **options))
    return summaries
