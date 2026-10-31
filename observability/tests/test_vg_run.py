"""Tests for verification runs as traces (Track E, step E12).

Appendix A2.6 paragraph 1 adds the work of AI programs that run outside the
harness, and A2.4 "Procedural graphs" has each run leave a folder recording
what ran, the prompts, and every model answer. vg.py describes its
trail.jsonl as the run's observability log. The fixture
fixtures/vg_run/ was made by running the self-test graph once offline with
its recorded answers, keeping manifest.json, trail.jsonl, records/, prompts/,
and responses/, with inputs_from set to the relative fixtures/selftest. The
trail event of item w2 was edited by hand to name a live executor. Copies are
changed only inside temporary folders. Nothing here calls a model or the
network. Run from the repository root with python3 -m pytest -q
observability/tests.
"""
import json
import os
import shutil
from pathlib import Path

import pytest

from observability import conventions as cv
from observability import spans as sp
from observability.adapters import vg_run as vr

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "vg_run"
JUDGE_FILE = "02_judge_items.json"
LIVE_MODEL = "qwen/qwen3.5-122b"


def _copy(tmp_path, name="run_copy"):
    target = tmp_path / name
    shutil.copytree(str(FIXTURE), str(target))
    return target


def _trail(run_dir):
    with open(str(Path(run_dir) / "trail.jsonl"), encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _write_trail(run_dir, events):
    with open(str(Path(run_dir) / "trail.jsonl"), "w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event) + "\n")


def _json(path):
    with open(str(path), encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path, data):
    with open(str(path), "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)


def _root(spans):
    [root] = [span for span in spans if not span["parent_span_id"]]
    return root


def _by_parent(spans, parent):
    return [span for span in spans if span["parent_span_id"] == parent["span_id"]]


def _steps(spans):
    return _by_parent(spans, _root(spans))


def _items(spans):
    [judge] = [span for span in _steps(spans) if span["name"] == "judge_items"]
    return judge, _by_parent(spans, judge)


def _messages(span, key):
    value = span["attributes"][key]
    return json.loads(value) if isinstance(value, str) else value


# The fixture itself


def test_the_fixture_holds_no_machine_path():
    for path in FIXTURE.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            assert "/Users/" not in text and "/home/" not in text and "/tmp" not in text
    assert _json(FIXTURE / "manifest.json")["inputs_from"] == "fixtures/selftest"


def test_the_resource_and_trace_id_come_from_the_run_folder():
    resource, spans = vr.trace(FIXTURE)
    assert resource == {cv.SERVICE_NAME: "vg.py"}
    expected = sp.trace_id_for("vg:" + os.path.realpath(str(FIXTURE)))
    assert {span["trace_id"] for span in spans} == {expected}


def test_the_root_is_the_workflow_from_the_manifest_to_the_last_trail_event():
    _, spans = vr.trace(FIXTURE)
    root = _root(spans)
    manifest = _json(FIXTURE / "manifest.json")
    assert root["name"] == "invoke_workflow selftest"
    assert root["kind"] == cv.SPAN_KIND_INTERNAL
    assert root["span_id"] == sp.span_id_for(root["trace_id"], "root")
    assert root["start_ns"] == sp.time_ns(manifest["created_at"])
    assert root["end_ns"] == sp.time_ns(_trail(FIXTURE)[-1]["at"])
    assert root["attributes"] == {
        cv.OPERATION_NAME: cv.INVOKE_WORKFLOW,
        cv.WORKFLOW_NAME: "selftest",
        cv.VG_RUN_ID: "vg_run",
        cv.VG_STREAM: "selftest",
        cv.VG_GRAPH_VERSION: "0.1",
    }


def test_three_step_spans_in_order_with_their_fields():
    _, spans = vr.trace(FIXTURE)
    steps = _steps(spans)
    assert [span["name"] for span in steps] == ["list_items", "judge_items", "report"]
    names = sorted(os.listdir(str(FIXTURE / "records")))
    for span, name in zip(steps, names):
        record = _json(FIXTURE / "records" / name)
        assert span["span_id"] == sp.span_id_for(span["trace_id"], name)
        assert span["kind"] == cv.SPAN_KIND_INTERNAL
        assert span["start_ns"] == sp.time_ns(record["started_at"])
        assert span["end_ns"] == span["start_ns"] + int(round(record["duration_s"] * 1e9))
        assert span["attributes"] == {
            cv.VG_STEP_SEQ: record["seq"],
            cv.VG_STEP_KIND: record["kind"],
            cv.VG_CONTRACT: "pass",
        }
        assert span["status_code"] == cv.STATUS_UNSET


def test_four_item_spans_under_the_judgment_step_with_prompts_and_answers():
    _, spans = vr.trace(FIXTURE)
    judge, items = _items(spans)
    assert [span["name"] for span in items] == [
        "recorded w1", "chat " + LIVE_MODEL, "recorded w3", "recorded w4"]
    for span, item in zip(items, ("w1", "w2", "w3", "w4")):
        assert span["span_id"] == sp.span_id_for(span["trace_id"], JUDGE_FILE + "/" + item)
        prompt = (FIXTURE / "prompts" / "02_judge_items" / (item + ".txt")).read_text(
            encoding="utf-8")
        answer = (FIXTURE / "responses" / "02_judge_items" / (item + ".txt")).read_text(
            encoding="utf-8")
        assert _messages(span, cv.INPUT_MESSAGES) == [
            {"role": "user", "parts": [{"type": "text", "content": prompt}]}]
        assert _messages(span, cv.OUTPUT_MESSAGES) == [
            {"role": "assistant", "parts": [{"type": "text", "content": answer}]}]


def test_recorded_items_are_never_model_calls():
    _, spans = vr.trace(FIXTURE)
    _, items = _items(spans)
    recorded = [span for span in items if span["name"].startswith("recorded ")]
    assert len(recorded) == 3
    for span in recorded:
        assert span["kind"] == cv.SPAN_KIND_INTERNAL
        assert span["attributes"][cv.VG_EXECUTOR] == "recorded:recorded_judge.json"
        assert cv.OPERATION_NAME not in span["attributes"]
        assert cv.PROVIDER_NAME not in span["attributes"]
    chats = [span for span in spans
             if span["attributes"].get(cv.OPERATION_NAME) == cv.CHAT]
    assert len(chats) == 1


def test_the_live_item_is_a_chat_span_with_its_provider_and_model():
    _, spans = vr.trace(FIXTURE)
    _, items = _items(spans)
    live = items[1]
    assert live["name"] == "chat " + LIVE_MODEL
    assert live["kind"] == cv.SPAN_KIND_CLIENT
    assert live["attributes"][cv.OPERATION_NAME] == cv.CHAT
    assert live["attributes"][cv.PROVIDER_NAME] == "live"
    assert live["attributes"][cv.REQUEST_MODEL] == LIVE_MODEL


def test_item_spans_follow_one_another_from_the_step_start(tmp_path):
    run = _copy(tmp_path)
    events = _trail(run)
    seconds = iter(range(51, 60))
    for event in events:
        if event["event"] in ("judgment_item", "judgment_unjudged"):
            event["at"] = "2026-10-29T03:30:%02d-07:00" % next(seconds)
    _write_trail(run, events)
    _, spans = vr.trace(run)
    judge, items = _items(spans)
    assert items[0]["start_ns"] == judge["start_ns"]
    for before, after in zip(items, items[1:]):
        assert after["start_ns"] == before["end_ns"]
    assert [span["end_ns"] for span in items] == [
        sp.time_ns("2026-10-29T03:30:%02d-07:00" % second) for second in (51, 52, 53, 54)]


def test_a_step_that_failed_its_contract_has_the_error_status(tmp_path):
    run = _copy(tmp_path)
    path = run / "records" / "01_list_items.json"
    record = _json(path)
    record["checks"] = {"contract": "fail", "problems": ["items.json: missing", "second"]}
    _write_json(path, record)
    _, spans = vr.trace(run)
    first = _steps(spans)[0]
    assert first["attributes"][cv.VG_CONTRACT] == "fail"
    assert first["status_code"] == cv.STATUS_ERROR
    assert first["status_message"] == "items.json: missing"


def test_a_not_judged_item_has_not_judged_and_the_error_status(tmp_path):
    run = _copy(tmp_path)
    events = []
    for event in _trail(run):
        if event.get("event") == "judgment_item" and event.get("item") == "w3":
            event = {"at": event["at"], "event": "judgment_unjudged", "node": "judge_items",
                     "item": "w3", "reason": "unparseable response (no JSON)"}
        events.append(event)
    _write_trail(run, events)
    (run / "responses" / "02_judge_items" / "w3.retry.txt").write_text(
        "still not JSON", encoding="utf-8")
    _, spans = vr.trace(run)
    _, items = _items(spans)
    unjudged = items[2]
    assert unjudged["name"] == "recorded w3"
    assert unjudged["attributes"][cv.ERROR_TYPE] == "not_judged"
    assert unjudged["status_code"] == cv.STATUS_ERROR
    # With no executor in the event, the manifest's executor for the step's role is used.
    assert unjudged["attributes"][cv.VG_EXECUTOR] == (
        "recorded:fixtures/selftest/recorded_judge.json")
    outputs = _messages(unjudged, cv.OUTPUT_MESSAGES)
    assert [message["parts"][0]["content"] for message in outputs] == [
        (run / "responses" / "02_judge_items" / "w3.txt").read_text(encoding="utf-8"),
        "still not JSON"]
    for span in items:
        if span is not unjudged:
            assert span["status_code"] == cv.STATUS_UNSET


def test_long_prompts_and_answers_are_cut(tmp_path):
    run = _copy(tmp_path)
    (run / "prompts" / "02_judge_items" / "w1.txt").write_text("p" * 9000, encoding="utf-8")
    _, spans = vr.trace(run)
    _, items = _items(spans)
    content = _messages(items[0], cv.INPUT_MESSAGES)[0]["parts"][0]["content"]
    assert content == cv.cap("p" * 9000)
    assert "9000 characters" in content


def test_the_provider_block_gives_the_model_of_a_bare_live_executor(tmp_path):
    """The reconciliation's provider block (item 7), read when present."""
    run = _copy(tmp_path)
    manifest = _json(run / "manifest.json")
    manifest["executors"] = {"judge": "live", "second": None}
    manifest["provider"] = {"base_url": "http://127.0.0.1:9/v1", "model": "provider-model"}
    _write_json(run / "manifest.json", manifest)
    events = []
    for event in _trail(run):
        if event.get("event") == "judgment_item" and event.get("item") == "w1":
            event = {"at": event["at"], "event": "judgment_unjudged", "node": "judge_items",
                     "item": "w1", "reason": "executor failed"}
        if event.get("event") == "judgment_item" and event.get("item") == "w4":
            event = dict(event, executor="live:named-model")
        events.append(event)
    _write_trail(run, events)
    _, spans = vr.trace(run)
    _, items = _items(spans)
    assert items[0]["name"] == "chat provider-model"
    assert items[0]["attributes"][cv.REQUEST_MODEL] == "provider-model"
    assert items[0]["attributes"][cv.PROVIDER_NAME] == "live"
    assert items[3]["name"] == "chat named-model"
    assert items[3]["attributes"][cv.REQUEST_MODEL] == "named-model"
    for span in spans:
        assert cv.convention_problems(span) == []


def test_without_a_provider_block_a_bare_live_executor_has_no_model(tmp_path):
    run = _copy(tmp_path)
    events = []
    for event in _trail(run):
        if event.get("event") == "judgment_item" and event.get("item") == "w1":
            event = dict(event, executor="live")
        events.append(event)
    _write_trail(run, events)
    _, spans = vr.trace(run)
    _, items = _items(spans)
    assert items[0]["name"] == "chat"
    assert cv.REQUEST_MODEL not in items[0]["attributes"]
    assert cv.convention_problems(items[0]) == []


def test_every_span_passes_problems_and_convention_problems():
    _, spans = vr.trace(FIXTURE)
    assert len(spans) == 1 + 3 + 4
    assert len({span["span_id"] for span in spans}) == len(spans)
    for span in spans:
        assert sp.problems(span) == []
        assert cv.convention_problems(span) == []


def test_the_spans_survive_the_trace_file(tmp_path):
    resource, spans = vr.trace(FIXTURE)
    path = tmp_path / "trace.json"
    sp.write_trace(path, spans, resource)
    read_resource, read_spans = sp.read_trace(path)
    assert read_resource == resource
    # Messages are lists of dicts, which the file keeps as JSON text.
    for span in read_spans:
        for key in (cv.INPUT_MESSAGES, cv.OUTPUT_MESSAGES):
            if key in span["attributes"]:
                span["attributes"][key] = json.loads(span["attributes"][key])
    assert read_spans == spans


def test_the_fixture_is_not_changed_by_reading_it():
    before = {str(path): path.read_bytes() for path in FIXTURE.rglob("*") if path.is_file()}
    vr.trace(FIXTURE)
    vr.find_runs([str(FIXTURE)])
    after = {str(path): path.read_bytes() for path in FIXTURE.rglob("*") if path.is_file()}
    assert before == after


# Finding runs


def test_a_folder_holding_manifest_json_is_a_run():
    runs, notes = vr.find_runs([str(FIXTURE)])
    assert runs == [str(FIXTURE)]
    assert notes == []


def test_a_folder_holding_two_runs_gives_two_traces(tmp_path):
    holder = tmp_path / "runs"
    holder.mkdir()
    _copy(holder, "run_b")
    _copy(holder, "run_a")
    (holder / "not_a_run").mkdir()
    (holder / "loose.txt").write_text("x", encoding="utf-8")
    runs, notes = vr.find_runs([str(holder)])
    assert runs == [str(holder / "run_a"), str(holder / "run_b")]
    assert notes == []
    found = [vr.trace(run) for run in runs]
    trace_ids = {spans[0]["trace_id"] for _, spans in found}
    assert len(trace_ids) == 2
    assert [_root(spans)["attributes"][cv.VG_RUN_ID] for _, spans in found] == [
        "run_a", "run_b"]


def test_a_folder_without_manifest_json_is_a_note(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    missing = tmp_path / "missing"
    runs, notes = vr.find_runs([str(empty), str(missing)])
    assert runs == []
    assert len(notes) == 2
    assert str(empty) in notes[0]
    assert str(missing) in notes[1]


def test_a_run_named_twice_is_found_once(tmp_path):
    holder = tmp_path / "runs"
    holder.mkdir()
    run = _copy(holder, "run_a")
    runs, notes = vr.find_runs([str(holder), str(run)])
    assert runs == [str(run)]
    assert notes == []
