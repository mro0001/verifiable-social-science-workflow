"""Tests for the events tool for outside software (Track D, step D8).

Proposal Status paragraph 3 names MCP tools that bring AI observability into
tools outside the workflow, with the same events written to the logs, and
appendix A2.2 names MCP tools that bring events in from software outside the
workflow. The events server, workflow-events, offers one tool, record_event,
which writes an event for the server's working folder with the shared event
writer (Track D choices 2 and 3). Nothing is recorded in an excluded folder
or while the audit settings file is missing.

Every test runs with HOME, CONNECTIONS_HOME, and AUDIT_HOME inside a
temporary folder. Nothing here calls a model or the network. Run from the
repository root with python3 -m pytest -q connections/tests.
"""
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from connections.events import KINDS, ROLES, VERBS  # noqa: E402
from connections import home  # noqa: E402
from connections.home import folder_key  # noqa: E402
from connections.mcp import events_server  # noqa: E402
from connections.mcp.events_server import tools  # noqa: E402
from connections.mcp.protocol import handle  # noqa: E402

SCHEMA_FIELDS = {"harness", "harness_session_id", "source_id", "verb", "kind", "object", "rationale", "role"}


@pytest.fixture(autouse=True)
def homes(tmp_path, monkeypatch):
    user = tmp_path / "user"
    user.mkdir()
    monkeypatch.setenv("HOME", str(user))
    monkeypatch.setenv("CONNECTIONS_HOME", str(tmp_path / "connections_home"))
    monkeypatch.setenv("AUDIT_HOME", str(tmp_path / "audit_home"))
    return tmp_path


def exclude(*folders):
    path = Path(os.environ["AUDIT_HOME"]) / "settings.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = "".join(f"  - {folder}\n" for folder in folders)
    path.write_text("excluded_folders:\n" + lines if folders else "excluded_folders: []\n")


@pytest.fixture
def project(homes):
    folder = homes / "project"
    folder.mkdir()
    exclude(str(homes / "records"))
    return folder


@pytest.fixture
def records(homes):
    folder = homes / "records"
    folder.mkdir()
    exclude(str(folder))
    return folder


def events_dir():
    return Path(os.environ["CONNECTIONS_HOME"]) / "events"


def all_events():
    found = []
    if events_dir().is_dir():
        for path in sorted(events_dir().glob("*.jsonl")):
            found.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
    return found


def record(folder, **arguments):
    tool = [t for t in tools(folder) if t.name == "record_event"][0]
    return tool.handler(**arguments)


def call(folder, arguments):
    """The tool called through the protocol layer, as a client calls it."""
    reply = handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "record_event", "arguments": arguments}},
        events_server.SERVER_NAME, events_server.SERVER_VERSION, tools(folder),
    )
    result = reply["result"]
    return result["isError"], json.loads(result["content"][0]["text"])


# The tool.


def test_the_server_is_workflow_events_with_one_tool():
    assert events_server.SERVER_NAME == "workflow-events"
    listed = tools(ROOT)
    assert [t.name for t in listed] == ["record_event"]
    schema = listed[0].input_schema
    assert schema["required"] == ["verb", "kind", "object"]
    assert set(schema["properties"]) == {"verb", "kind", "object", "rationale", "role", "program"}
    for name in schema["properties"]:
        assert schema["properties"][name]["type"] == "string"
    assert schema["properties"]["verb"]["enum"] == list(VERBS)
    assert schema["properties"]["kind"]["enum"] == list(KINDS)
    assert schema["properties"]["role"]["enum"] == list(ROLES) + [""]


def test_a_call_writes_one_event_to_the_folders_events_file(project):
    answer = record(
        project, verb="edited", kind="action", object="chapter2.docx",
        rationale="tightened the second paragraph", role="edited", program="word",
    )
    assert answer["recorded"] is True
    found = all_events()
    assert len(found) == 1
    event = found[0]
    assert answer["source_id"] == event["source_id"]
    assert event["verb"] == "edited"
    assert event["kind"] == "action"
    assert event["object"] == "chapter2.docx"
    assert event["rationale"] == "tightened the second paragraph"
    assert event["role"] == "edited"
    assert event["program"] == "word"
    assert event["harness"] == "wrappers"
    assert event["cwd"] == str(project)
    assert event["harness_session_id"].endswith("_" + folder_key(project))
    files = list(events_dir().glob("*.jsonl"))
    assert [f.name for f in files] == [event["harness_session_id"] + ".jsonl"]


def test_the_program_is_mcp_and_rationale_and_role_are_empty_when_left_out(project):
    record(project, verb="searched", kind="observation", object="smith2020")
    event = all_events()[0]
    assert event["program"] == "mcp"
    assert event["rationale"] == ""
    assert event["role"] == ""
    assert SCHEMA_FIELDS | {"at", "cwd", "program"} == set(event)


def test_two_calls_append_two_lines_to_the_same_file(project):
    first = record(project, verb="ran", kind="action", object="export references")
    second = record(project, verb="wrote", kind="action", object="refs.bib", role="produced")
    files = list(events_dir().glob("*.jsonl"))
    assert len(files) == 1
    assert [e["source_id"] for e in all_events()] == [first["source_id"], second["source_id"]]


def test_a_wrong_kind_is_an_error_naming_kind(project):
    failed, answer = call(project, {"verb": "edited", "kind": "guess", "object": "a.docx"})
    assert failed is True
    assert answer["error"]["code"] == "invalid_argument"
    assert "kind" in answer["error"]["message"]
    assert all_events() == []


def test_a_wrong_verb_is_an_error_naming_verb(project):
    failed, answer = call(project, {"verb": "typed", "kind": "action", "object": "a.docx"})
    assert failed is True
    assert "verb" in answer["error"]["message"]
    assert all_events() == []


def test_a_wrong_role_is_an_error_naming_role(project):
    failed, answer = call(project, {"verb": "edited", "kind": "action", "object": "a.docx", "role": "owner"})
    assert failed is True
    assert "role" in answer["error"]["message"]
    assert all_events() == []


def test_an_empty_object_is_an_error_naming_object(project):
    failed, answer = call(project, {"verb": "edited", "kind": "action", "object": "  "})
    assert failed is True
    assert "object" in answer["error"]["message"]


def test_a_missing_object_is_an_error_naming_object(project):
    failed, answer = call(project, {"verb": "edited", "kind": "action"})
    assert failed is True
    assert "object" in answer["error"]["message"]


def test_a_good_call_through_the_protocol_is_not_an_error(project):
    failed, answer = call(project, {"verb": "edited", "kind": "decision", "object": "a.docx"})
    assert failed is False
    assert answer["recorded"] is True


def test_an_excluded_folder_records_nothing(records):
    answer = record(records, verb="edited", kind="action", object="grades.docx")
    assert answer == {"recorded": False, "reason": "recording is off for this folder"}
    assert not events_dir().exists()


def test_a_folder_inside_an_excluded_folder_records_nothing(records):
    inside = records / "term1"
    inside.mkdir()
    answer = record(inside, verb="edited", kind="action", object="grades.docx")
    assert answer["recorded"] is False
    assert not events_dir().exists()


def test_nothing_is_recorded_while_exclusions_are_not_declared(homes):
    folder = homes / "project"
    folder.mkdir()
    answer = record(folder, verb="edited", kind="action", object="a.docx")
    assert answer == {"recorded": False, "reason": "recording is off for this folder"}
    assert not events_dir().exists()


@pytest.mark.parametrize("ignores, recorded", [(True, False), (False, True)])
def test_a_folder_listed_in_another_case_records_nothing_only_on_a_disk_that_ignores_case(
    homes, monkeypatch, ignores, recorded
):
    # Track L, Step L4, decision 51, with a stand-in for the disk check.
    folder = homes / "records"
    folder.mkdir()
    exclude(str(homes / "RECORDS"))
    monkeypatch.setattr(home, "ignores_case", lambda path: ignores)
    answer = record(folder, verb="edited", kind="action", object="grades.docx")
    assert answer["recorded"] is recorded
    assert events_dir().exists() is recorded


def test_a_wrong_kind_in_an_excluded_folder_is_still_named(records):
    failed, answer = call(records, {"verb": "edited", "kind": "guess", "object": "a.docx"})
    assert failed is True
    assert "kind" in answer["error"]["message"]


def test_a_write_that_fails_is_not_recorded_and_does_not_raise(project, homes, monkeypatch):
    blocked = homes / "a_file"
    blocked.write_text("not a folder")
    monkeypatch.setenv("CONNECTIONS_HOME", str(blocked))
    answer = record(project, verb="edited", kind="action", object="a.docx")
    assert answer["recorded"] is False
    assert answer["reason"] == "the event could not be written"


def test_the_server_imports_no_other_layer():
    source = Path(events_server.__file__).read_text(encoding="utf-8")
    for layer in ("audit_layer", "ospipe", "verification_procedures", "observability", "features"):
        assert "import " + layer not in source and "from " + layer not in source


# The command, over standard input and output.


def serve_events(messages, folder):
    lines = "".join(json.dumps(m) + "\n" for m in messages)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    done = subprocess.run(
        [sys.executable, "-m", "connections", "serve", "events"],
        cwd=str(folder),
        env=env,
        input=lines,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 0, done.stderr
    return [json.loads(line) for line in done.stdout.splitlines()]


MESSAGES = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize",
     "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"}}},
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
     "params": {"name": "record_event",
                "arguments": {"verb": "edited", "kind": "action", "object": "chapter2.docx",
                              "rationale": "accepted the AI's change", "role": "edited",
                              "program": "word"}}},
]


def test_serve_events_lists_the_tool_and_records_over_standard_input_and_output(project):
    replies = serve_events(MESSAGES, project)
    assert [r["id"] for r in replies] == [1, 2, 3]
    assert replies[0]["result"]["serverInfo"]["name"] == "workflow-events"
    assert [t["name"] for t in replies[1]["result"]["tools"]] == ["record_event"]
    assert replies[2]["result"]["isError"] is False
    answer = json.loads(replies[2]["result"]["content"][0]["text"])
    assert answer["recorded"] is True
    found = all_events()
    assert len(found) == 1
    assert found[0]["source_id"] == answer["source_id"]
    assert found[0]["cwd"] == str(project)
    assert found[0]["program"] == "word"


def test_serve_events_in_an_excluded_folder_records_nothing(records):
    replies = serve_events(MESSAGES, records)
    answer = json.loads(replies[2]["result"]["content"][0]["text"])
    assert answer == {"recorded": False, "reason": "recording is off for this folder"}
    assert not events_dir().exists()


# End to end through commands. The events file the tool wrote is stored by
# the audit layer's capture of the wrappers harness (step D4).


def test_capture_of_the_wrappers_harness_stores_the_event(project):
    replies = serve_events(MESSAGES, project)
    answer = json.loads(replies[2]["result"]["content"][0]["text"])
    path = list(events_dir().glob("*.jsonl"))[0]
    env = dict(os.environ)
    for args in (["init"], ["capture", "--harness", "wrappers", str(path)]):
        done = subprocess.run(
            [sys.executable, "-m", "audit_layer"] + args,
            cwd=str(ROOT), env=env, capture_output=True, text=True,
        )
        assert done.returncode == 0, done.stderr
    db = sqlite3.connect(str(Path(os.environ["AUDIT_HOME"]) / "audit.sqlite"))
    try:
        rows = db.execute("SELECT verb, kind, object FROM events").fetchall()
    finally:
        db.close()
    assert ("edited", "action", "chapter2.docx") in rows
    assert answer["source_id"]
