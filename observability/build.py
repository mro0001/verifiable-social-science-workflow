"""The build of the view, trace files and the view's data file.

Proposal Figure 2 has the observability dashboard fed from the databases,
and appendix A2.6 paragraph 1 asks for one view that is the same for every
harness and can be reopened after the session ends. build_view reads the
audit layer's record read only, at the path given on the command line (plan
choice 4, reconciliation item 4), and writes each session as a trace file in
OTLP JSON (plan choice 1) and the tables the dashboard reads as data.js
(plan choice 14), and copies the dashboard page beside them unchanged
(step E7). A session of a harness other than Claude Code is shown from
the audit events table by the events adapter (step E11, plan choice 5).
Verification runs named on the command line join the same view, each read
from its run folder in place by the run adapter (step E13, plan choice 12).
The reconciliation drops the view's filtering by excluded folder (item 3),
so every session in the record and every run given is shown.
"""
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from observability import conventions as cv
from observability import kb
from observability import record as rc
from observability import spans as sp
from observability.adapters import claude_code as cc
from observability.adapters import events as ev
from observability.adapters import vg_run as vr

RecordError = rc.RecordError

TRACES = "traces"
DATA_FILE = "data.js"
DATA_PREFIX = "window.OBS = "
DASHBOARD = Path(__file__).resolve().parent / "dashboard"
PAGE_FILES = ("index.html", "app.js", "style.css")

MAIN_AGENT = "main"
STATUS_TEXT = {cv.STATUS_UNSET: "unset", cv.STATUS_OK: "ok", cv.STATUS_ERROR: "error"}


def build_view(audit_home, out, project=None, kb_dirs=(), kb_servers=kb.KB_SERVERS,
               live=False, refresh_seconds=5, vg_runs=()) -> Dict:
    """Build the view in out from the audit record in audit_home and the runs in vg_runs.

    Returns a summary with out, traces (the number of trace files written),
    and notes. Each session and each run becomes <out>/traces/<trace_id>.json,
    a trace file this build did not write is removed, the dashboard page's
    files are copied into out unchanged, and the tables the dashboard reads
    go to <out>/data.js as window.OBS = <json>;. vg_runs names run folders of
    vg.py and folders holding them.
    """
    kb_dirs = [str(folder) for folder in (kb_dirs or ())]
    vg_runs = [str(path) for path in (vg_runs or ())]
    record = rc.open_record(audit_home)
    try:
        found, notes = _read_traces(record, project)
    finally:
        record.db.close()
    for _, spans in found:
        kb.mark_retrievals(spans, kb_servers=kb_servers, kb_dirs=kb_dirs)
    runs, run_notes = _read_runs(vg_runs)
    found.extend(runs)
    notes.extend(run_notes)

    out = Path(out)
    folder = out / TRACES
    folder.mkdir(parents=True, exist_ok=True)
    written = set()
    for resource, spans in found:
        name = spans[0]["trace_id"] + ".json"
        sp.write_trace(folder / name, spans, resource)
        written.add(name)
    for path in folder.iterdir():
        if path.suffix == ".json" and path.name not in written and path.is_file():
            path.unlink()

    for name in PAGE_FILES:
        shutil.copyfile(str(DASHBOARD / name), str(out / name))

    data = view_data(found, notes, audit_home, kb_dirs, live, refresh_seconds, vg_runs)
    _write_data(out / DATA_FILE, data)
    return {"out": str(out), "traces": len(written), "notes": notes}


def _read_traces(record, project):
    """The traces of the selected sessions and the notes made reading them."""
    notes = []
    transcripts = []
    meta = {}
    others = []
    for session in rc.sessions(record, project=project):
        if session["harness"] != cc.HARNESS:
            # A harness with no transcript adapter is shown from its events.
            others.append(ev.trace(session, rc.events(record, session)))
            continue
        try:
            kept = rc.transcripts(record, session)
        except rc.RecordError as error:
            notes.append("session %s is not shown, %s" % (session["harness_session_id"], error))
            continue
        transcripts.extend(kept)
        meta[session["harness_session_id"]] = session
    # All transcripts go through together, so the files of one session stored
    # under several rows join one trace.
    records, read_notes = cc.read_records(transcripts)
    notes.extend(read_notes)
    return cc.traces(records, meta) + others, notes


def _read_runs(vg_runs):
    """The traces of the runs found in vg_runs and the notes made finding them."""
    run_dirs, notes = vr.find_runs(vg_runs)
    found = []
    for run_dir in run_dirs:
        try:
            found.append(vr.trace(run_dir))
        except (OSError, ValueError) as error:
            # A run being written may hold a half written file, so it is a
            # note until the next build.
            notes.append("run %s is not shown, %s" % (run_dir, error))
    return found, notes


# The view's data


def view_data(found, notes, audit_home, kb_dirs, live, refresh_seconds, vg_runs=()) -> Dict:
    """The tables the dashboard reads, from the traces as (resource, spans)."""
    rows = []
    span_tables = {}
    files = []
    kb_reads = []
    ordered = sorted(found, key=lambda item: (_root(item[1])["start_ns"],
                                              item[1][0]["trace_id"]))
    for resource, spans in ordered:
        root = _root(spans)
        trace_id = root["trace_id"]
        span_list = span_rows(spans)
        span_tables[trace_id] = span_list
        row = trace_row(resource, spans)
        rows.append(row)
        by_id = {span["span_id"]: span for span in spans}
        for item in span_list:
            span = by_id[item["span_id"]]
            attributes = span["attributes"]
            common = {
                "trace_id": trace_id,
                "span_id": span["span_id"],
                "session_id": row["session_id"],
                "project": row["project"],
                "agent": item["agent"],
                "time": iso(span["start_ns"]),
                "tool": _text(attributes.get(cv.TOOL_NAME, "")),
            }
            if cv.FILE_PATH in attributes:
                entry = dict(common)
                entry["role"] = _text(attributes.get(cv.AUDIT_ROLE, ""))
                entry["path"] = _text(attributes[cv.FILE_PATH])
                files.append(entry)
            if cv.DATA_SOURCE_ID in attributes:
                entry = dict(common)
                entry["source"] = _text(attributes[cv.DATA_SOURCE_ID])
                entry["entries"] = _documents(attributes.get(cv.RETRIEVAL_DOCUMENTS))
                entry["query"] = _text(attributes.get(cv.RETRIEVAL_QUERY_TEXT, ""))
                entry["outcome"] = "error" if span["status_code"] == cv.STATUS_ERROR else "ok"
                kb_reads.append(entry)
    reads = {}
    for entry in kb_reads:
        for entry_id in entry["entries"]:
            reads[entry_id] = reads.get(entry_id, 0) + 1
    kb_entries = []
    for entry in kb.entries(kb_dirs):
        item = dict(entry)
        item["reads"] = reads.get(entry["id"], 0)
        kb_entries.append(item)
    return {
        "built_at": iso(_now_ns()),
        "live": bool(live),
        "refresh_seconds": refresh_seconds,
        "semconv": cv.SEMCONV_SOURCE,
        "sources": {"audit_home": str(audit_home), "kb_dirs": list(kb_dirs),
                    "vg_runs": [str(path) for path in (vg_runs or ())]},
        "notes": list(notes),
        "traces": rows,
        "spans": span_tables,
        "files": files,
        "kb_reads": kb_reads,
        "kb_entries": kb_entries,
    }


def trace_row(resource, spans) -> Dict:
    """One row of the traces table.

    A run's row is titled by its stream and run id, has the run id as its
    session id, and has no project (step E13).
    """
    root = _root(spans)
    attributes = root["attributes"]
    project = _text(attributes.get(cv.AUDIT_PROJECT, ""))
    title = os.path.basename(project.rstrip("/\\")) if project else ""
    session_id = _text(attributes.get(cv.CONVERSATION_ID, ""))
    if _operation(root) == cv.INVOKE_WORKFLOW:
        run_id = _text(attributes.get(cv.VG_RUN_ID, ""))
        title = " ".join(part for part in (_text(attributes.get(cv.VG_STREAM, "")), run_id)
                         if part)
        session_id = run_id
    chats = [span for span in spans if _operation(span) == cv.CHAT]
    exposed = 0
    turns = 0
    for span in chats:
        parts = _reasoning_parts(span["attributes"].get(cv.OUTPUT_MESSAGES))
        if parts:
            turns += 1
            if any(part.get("content") for part in parts):
                exposed += 1
    return {
        "trace_id": root["trace_id"],
        "source": _text((resource or {}).get(cv.SERVICE_NAME, "")),
        "title": title,
        "project": project,
        "session_id": session_id,
        "started": iso(root["start_ns"]),
        "duration_s": _seconds(root["end_ns"] - root["start_ns"]),
        "model_calls": len(chats),
        "input_tokens": sum(_count(span, cv.USAGE_INPUT_TOKENS) for span in chats),
        "output_tokens": sum(_count(span, cv.USAGE_OUTPUT_TOKENS) for span in chats),
        "tool_calls": sum(1 for span in spans if _operation(span) == cv.EXECUTE_TOOL),
        "subagents": sum(1 for span in spans
                         if _operation(span) == cv.INVOKE_AGENT and span["parent_span_id"]),
        "kb_reads": sum(1 for span in spans if cv.DATA_SOURCE_ID in span["attributes"]),
        "errors": sum(1 for span in spans if span["status_code"] == cv.STATUS_ERROR),
        "reasoning": {"exposed": exposed, "turns": turns},
    }


def span_rows(spans) -> List[Dict]:
    """The spans of one trace as rows, parents first and siblings by start.

    Times are seconds from the start of the trace's earliest root. A span
    whose parent is not in the trace is placed as a root.
    """
    by_id = {span["span_id"]: span for span in spans}
    children = {}
    roots = []
    for index, span in enumerate(spans):
        parent = span.get("parent_span_id") or ""
        if parent and parent in by_id:
            children.setdefault(parent, []).append((index, span))
        else:
            roots.append((index, span))
    if not roots:
        return []
    origin = min(span["start_ns"] for _, span in roots)

    def by_start(item):
        return (item[1]["start_ns"], item[0])

    rows = []
    pending = [(span, 0, MAIN_AGENT) for _, span in sorted(roots, key=by_start)]
    pending.reverse()
    while pending:
        span, depth, agent = pending.pop()
        if _operation(span) == cv.INVOKE_AGENT:
            agent_id = span["attributes"].get(cv.AGENT_ID)
            agent = _text(agent_id) if agent_id else (MAIN_AGENT if depth == 0 else agent)
        attributes = span["attributes"]
        rows.append({
            "span_id": span["span_id"],
            "parent_span_id": span.get("parent_span_id") or "",
            "depth": depth,
            "name": span["name"],
            "category": category(span),
            "start_s": _seconds(span["start_ns"] - origin),
            "end_s": _seconds(span["end_ns"] - origin),
            "status": STATUS_TEXT.get(span.get("status_code", 0), "unset"),
            "error_type": _text(attributes.get(cv.ERROR_TYPE, "")),
            "agent": agent,
            "attributes": {key: _text(attributes[key]) for key in sorted(attributes)},
        })
        below = sorted(children.get(span["span_id"], []), key=by_start)
        for _, child in reversed(below):
            pending.append((child, depth + 1, agent))
    return rows


def category(span) -> str:
    """The span's category on the page."""
    attributes = span.get("attributes") or {}
    operation = attributes.get(cv.OPERATION_NAME)
    if operation in (cv.INVOKE_AGENT, cv.INVOKE_WORKFLOW):
        return "agent"
    if operation == cv.CHAT:
        return "model"
    if cv.DATA_SOURCE_ID in attributes:
        return "kb"
    if operation == cv.EXECUTE_TOOL:
        return "tool"
    if cv.VG_STEP_SEQ in attributes:
        return "step"
    if cv.VG_EXECUTOR in attributes and not operation:
        return "judgment"
    if cv.AUDIT_ORDINAL in attributes:
        return "event"
    return "other"


def iso(ns) -> str:
    """An ISO time in UTC to the millisecond, ending in Z."""
    seconds, rest = divmod(int(ns), 10 ** 9)
    moment = datetime.fromtimestamp(seconds, tz=timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (rest // 10 ** 6)


def _now_ns():
    now = datetime.now(timezone.utc)
    return int(now.timestamp()) * 10 ** 9 + now.microsecond * 1000


def _seconds(ns):
    return round(ns / 1e9, 6)


def _root(spans):
    for span in spans:
        if not span.get("parent_span_id"):
            return span
    return spans[0]


def _operation(span):
    return (span.get("attributes") or {}).get(cv.OPERATION_NAME)


def _count(span, key):
    value = span["attributes"].get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return 0


def _loaded(value):
    """A value kept as JSON text, or as itself, as Python data."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return None
    return value


def _reasoning_parts(messages):
    messages = _loaded(messages)
    if not isinstance(messages, list):
        return []
    found = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        for part in message.get("parts") or []:
            if isinstance(part, dict) and part.get("type") == "reasoning":
                found.append(part)
    return found


def _documents(value):
    documents = _loaded(value)
    if not isinstance(documents, list):
        return []
    return [_text(item.get("id")) for item in documents
            if isinstance(item, dict) and item.get("id") is not None]


def _text(value):
    """An attribute value as text, JSON for anything but a string."""
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _write_data(path, data):
    """Write data.js whole, so a page reading it never sees half a file."""
    text = DATA_PREFIX + json.dumps(data, sort_keys=True, ensure_ascii=True) + ";\n"
    partial = path.with_name(path.name + ".partial")
    with open(str(partial), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    os.replace(str(partial), str(path))
