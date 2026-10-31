"""The verification run adapter, from vg.py's run folders to trace spans.

Appendix A2.6 paragraph 1 adds the work of AI programs that run outside the
harness, and A2.4 "Procedural graphs" has each run leave a folder recording
what ran, the prompts, and every model answer. vg.py calls the run's
trail.jsonl its observability log. This adapter reads a run folder in place
and read only (plan choice 4, reconciliation item 4), its manifest.json,
trail.jsonl, records/, prompts/, and responses/, and never changes it.

A run is an invoke_workflow span with a span for each step beneath it, and a
judgment step has a span for each judged item (plan choice 6). An item judged
by a live model is a chat span. One answered from recorded answers is marked
recorded and never counted as a model call (plan choice 12). When the
manifest holds the provider block (reconciliation item 7), a live executor
that names no model takes the block's model.
"""
import json
import os
from typing import Dict, List, Tuple

from observability import conventions as cv
from observability import spans as sp

SERVICE = "vg.py"
ROOT_KEY = "root"
MANIFEST = "manifest.json"
TRAIL = "trail.jsonl"
RECORDS = "records"
PROMPTS = "prompts"
RESPONSES = "responses"

RECORDED_PREFIX = "recorded:"
RECORDED_NAME = "recorded"
NOT_JUDGED = "not_judged"
ITEM_EVENTS = ("judgment_item", "judgment_unjudged")
DEFAULT_ROLE = "judge"


def find_runs(paths) -> Tuple[List[str], List[str]]:
    """The run folders among paths, as (run_dirs, notes).

    A path holding manifest.json is a run, a folder holding run folders gives
    each of them in name order, and anything else is a note. A run named more
    than once is given once.
    """
    runs = []
    notes = []
    seen = set()

    def keep(path):
        real = os.path.realpath(path)
        if real not in seen:
            seen.add(real)
            runs.append(path)

    for path in paths:
        path = str(path)
        if os.path.isfile(os.path.join(path, MANIFEST)):
            keep(path)
            continue
        found = []
        if os.path.isdir(path):
            for name in sorted(os.listdir(path)):
                child = os.path.join(path, name)
                if os.path.isfile(os.path.join(child, MANIFEST)):
                    found.append(child)
        if not found:
            notes.append("%s is not a run folder of vg.py and holds none" % path)
            continue
        for child in found:
            keep(child)
    return runs, notes


def trace(run_dir) -> Tuple[Dict, List[Dict]]:
    """One run folder as (resource, spans)."""
    run_dir = str(run_dir)
    manifest = _read_json(os.path.join(run_dir, MANIFEST))
    trail = _read_trail(os.path.join(run_dir, TRAIL))
    trace_id = sp.trace_id_for("vg:" + os.path.realpath(run_dir))
    stream = _text(manifest.get("stream"))
    start = _time(manifest.get("created_at"))
    times = [_time(event.get("at")) for event in trail]
    times = [at for at in times if at is not None]
    if start is None:
        start = times[0] if times else 0
    end = max([start] + times[-1:])
    graph = manifest.get("graph") if isinstance(manifest.get("graph"), dict) else {}
    root = sp.new_span(trace_id, ROOT_KEY, cv.INVOKE_WORKFLOW + " " + stream,
                       cv.SPAN_KIND_INTERNAL, start, end, attributes={
                           cv.OPERATION_NAME: cv.INVOKE_WORKFLOW,
                           cv.WORKFLOW_NAME: stream,
                           cv.VG_RUN_ID: os.path.basename(os.path.normpath(run_dir)),
                           cv.VG_STREAM: stream,
                           cv.VG_GRAPH_VERSION: _text(graph.get("version")),
                       })
    spans = [root]
    folder = os.path.join(run_dir, RECORDS)
    names = sorted(name for name in os.listdir(folder) if name.endswith(".json")) \
        if os.path.isdir(folder) else []
    for name in names:
        record = _read_json(os.path.join(folder, name))
        step = _step_span(trace_id, root["span_id"], name, record, start)
        spans.append(step)
        if record.get("kind") == "judgment":
            spans.extend(_item_spans(trace_id, step, name, record, manifest, trail, run_dir))
    return {cv.SERVICE_NAME: SERVICE}, spans


def _step_span(trace_id, root_id, name, record, fallback):
    start = _time(record.get("started_at"))
    if start is None:
        start = fallback
    duration = record.get("duration_s")
    if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration < 0:
        duration = 0
    checks = record.get("checks") if isinstance(record.get("checks"), dict) else {}
    contract = _text(checks.get("contract"))
    span = sp.new_span(trace_id, name, _text(record.get("node")) or name,
                       cv.SPAN_KIND_INTERNAL, start, start + int(round(duration * 1e9)),
                       parent_span_id=root_id, attributes={
                           cv.VG_STEP_SEQ: record.get("seq") if isinstance(record.get("seq"), int)
                           else _text(record.get("seq")),
                           cv.VG_STEP_KIND: _text(record.get("kind")),
                           cv.VG_CONTRACT: contract,
                       })
    if contract == "fail":
        span["status_code"] = cv.STATUS_ERROR
        problems = checks.get("problems") or []
        span["status_message"] = _text(problems[0]) if problems else ""
    return span


def _item_events(trail, node, seq):
    """The item events of one step, in trail order.

    They are the events for the node between the step_started and the
    step_finished of the step's seq, or every item event for the node when
    the trail does not mark the step.
    """
    inside = []
    marked = False
    current = False
    for event in trail:
        kind = event.get("event")
        if kind == "step_started" and event.get("node") == node:
            current = event.get("seq") == seq
            marked = marked or current
        elif kind == "step_finished" and event.get("node") == node and event.get("seq") == seq:
            current = False
        elif kind in ITEM_EVENTS and event.get("node") == node and current:
            inside.append(event)
    if marked:
        return inside
    return [event for event in trail
            if event.get("event") in ITEM_EVENTS and event.get("node") == node]


def _item_spans(trace_id, step, name, record, manifest, trail, run_dir):
    tag = name[:-len(".json")]
    node = _text(record.get("node"))
    execution = record.get("execution") if isinstance(record.get("execution"), dict) else {}
    role = _text(execution.get("role")) or DEFAULT_ROLE
    executors = manifest.get("executors") if isinstance(manifest.get("executors"), dict) else {}
    provider = manifest.get("provider") if isinstance(manifest.get("provider"), dict) else {}
    spans = []
    previous = step["start_ns"]
    for event in _item_events(trail, node, record.get("seq")):
        item = _text(event.get("item"))
        end = _time(event.get("at"))
        if end is None:
            end = previous
        start = min(previous, end)
        executor = _text(event.get("executor")) or _text(executors.get(role))
        attributes = {}
        messages = _messages(run_dir, tag, item)
        attributes.update(messages)
        if executor.startswith(RECORDED_PREFIX):
            span_name = RECORDED_NAME + " " + item
            kind = cv.SPAN_KIND_INTERNAL
            attributes[cv.VG_EXECUTOR] = executor
        else:
            prefix, _, model = executor.partition(":")
            if not model and isinstance(provider.get("model"), str):
                model = provider["model"]
            span_name = cv.CHAT + " " + model if model else cv.CHAT
            kind = cv.SPAN_KIND_CLIENT
            attributes[cv.OPERATION_NAME] = cv.CHAT
            attributes[cv.PROVIDER_NAME] = prefix
            if model:
                attributes[cv.REQUEST_MODEL] = model
        not_judged = event.get("event") == "judgment_unjudged"
        if not_judged:
            attributes[cv.ERROR_TYPE] = NOT_JUDGED
        span = sp.new_span(trace_id, name + "/" + item, span_name, kind, start, end,
                           parent_span_id=step["span_id"], attributes=attributes)
        if not_judged:
            span["status_code"] = cv.STATUS_ERROR
            span["status_message"] = _text(event.get("reason"))
        spans.append(span)
        previous = end
    return spans


def _messages(run_dir, tag, item):
    """An item's prompt and answers in the conventions' message form, each cut by cap."""
    found = {}
    prompt = _read_text(os.path.join(run_dir, PROMPTS, tag, item + ".txt"))
    if prompt is not None:
        found[cv.INPUT_MESSAGES] = [
            {"role": "user", "parts": [{"type": "text", "content": cv.cap(prompt)}]}]
    outputs = []
    for name in (item + ".txt", item + ".retry.txt"):
        answer = _read_text(os.path.join(run_dir, RESPONSES, tag, name))
        if answer is not None:
            outputs.append(
                {"role": "assistant", "parts": [{"type": "text", "content": cv.cap(answer)}]})
    if outputs:
        found[cv.OUTPUT_MESSAGES] = outputs
    return found


def _read_json(path):
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def _read_trail(path):
    """The trail's events, skipping a line that does not parse, such as one half written."""
    events = []
    if not os.path.isfile(path):
        return events
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):
                events.append(event)
    return events


def _read_text(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return None


def _time(text):
    if not isinstance(text, str) or not text:
        return None
    try:
        return sp.time_ns(text)
    except ValueError:
        return None


def _text(value):
    return "" if value is None else str(value)
