"""Tests for the audit store server (Track D, step D7).

Appendix A2.2 says MCP servers expose the databases to the harness and the
model, and Figure A4 has the harness and the model read the databases through
them. The audit server, workflow-audit, reads the audit store read only and
serves current rows only, never a transcript's content (Track D choices 9 and
11).

The store is made with the audit layer's own commands in a temporary audit
home, python3 -m audit_layer init, then capture --harness claude_code on a
copy of the test story's session with its folder token filled in. Every test
runs with HOME, CONNECTIONS_HOME, and AUDIT_HOME inside a temporary folder.
Nothing here calls a model or the network. Run from the repository root with
python3 -m pytest -q connections/tests.
"""
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from connections.mcp import audit_server  # noqa: E402
from connections.mcp.audit_server import open_store, tools  # noqa: E402

SESSIONS = ROOT / "examples" / "test_story" / "sessions" / "claude_code"
STORY_SESSION = SESSIONS / "story_session.jsonl"
EXCLUDED_SESSION = SESSIONS / "excluded_session.jsonl"
TOKEN = "{{PROJECT}}"

STORY_ID = "5f3c0413-2a7d-4b9e-8c61-a0d4e7b2c913"
OTHER_ID = "9b1e0414-6c3a-4f2d-b8e5-71d2a9c4f086"

STORY_CHECK = (
    "python3 -m ospipe check --manuscript manuscript.md --manifest numbers.yml"
    " --tables-dir . | tail -n 3"
)
STORY_EVENT_IDS = [
    "toolu_story_01_read",
    "toolu_story_02_edit",
    "toolu_story_03_edit",
    "toolu_story_04_write",
    "toolu_story_05_bash",
    "toolu_story_06_bash",
]
SESSION_COLUMNS = {
    "id", "harness", "harness_session_id", "project", "started_at", "ended_at", "tools",
    "title", "gist", "summary", "keywords", "models", "harness_version",
    "created_at", "session", "origin", "method", "reason", "supersedes",
}


@pytest.fixture(autouse=True)
def homes(tmp_path, monkeypatch):
    user = tmp_path / "user"
    user.mkdir()
    monkeypatch.setenv("HOME", str(user))
    monkeypatch.setenv("CONNECTIONS_HOME", str(tmp_path / "connections_home"))
    monkeypatch.setenv("AUDIT_HOME", str(tmp_path / "audit_home"))
    return tmp_path


@pytest.fixture
def home(homes):
    return Path(os.environ["AUDIT_HOME"])


@pytest.fixture
def project(homes):
    folder = homes / "project"
    folder.mkdir()
    return folder


def audit_command(*args):
    """Run python3 -m audit_layer with the test's homes, from the repository root."""
    done = subprocess.run(
        [sys.executable, "-m", "audit_layer"] + [str(a) for a in args],
        cwd=str(ROOT),
        env=dict(os.environ),
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr
    return done


def story_lines(source, project):
    text = source.read_text(encoding="utf-8").replace(TOKEN, json.dumps(str(project))[1:-1])
    return [line for line in text.split("\n") if line]


def write_lines(path, lines):
    path.write_bytes("".join(line + "\n" for line in lines).encode("utf-8"))
    return path


@pytest.fixture
def story_file(homes, project):
    return write_lines(homes / "story_session.jsonl", story_lines(STORY_SESSION, project))


@pytest.fixture
def store(home, story_file):
    """The audit store holding the story session, made with the audit layer's commands."""
    audit_command("init")
    audit_command("capture", "--harness", "claude_code", story_file)
    return home


@pytest.fixture
def two_sessions(store, homes, project):
    """The store with the story session and the later session run in a folder inside the project."""
    other = write_lines(homes / "other_session.jsonl", story_lines(EXCLUDED_SESSION, project))
    audit_command("capture", "--harness", "claude_code", other)
    return store


def by_name(home):
    return {tool.name: tool.handler for tool in tools(home)}


def call(home, name, **arguments):
    return by_name(home)[name](**arguments)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# The three tools.


def test_the_server_offers_three_tools_with_their_arguments(home):
    found = {tool.name: tool.input_schema for tool in tools(home)}
    assert sorted(found) == ["get_session", "list_sessions", "search_events"]

    def types(schema):
        return {name: spec["type"] for name, spec in schema["properties"].items()}

    assert types(found["list_sessions"]) == {"project": "string", "limit": "integer"}
    assert found["list_sessions"].get("required", []) == []
    assert types(found["get_session"]) == {"harness_session_id": "string"}
    assert found["get_session"]["required"] == ["harness_session_id"]
    assert types(found["search_events"]) == {"text": "string", "project": "string", "limit": "integer"}
    assert found["search_events"]["required"] == ["text"]
    assert audit_server.SERVER_NAME == "workflow-audit"


# list_sessions.


def test_list_sessions_returns_the_story_session_with_its_project(store, project):
    found = call(store, "list_sessions")
    assert found["sessions"][0]["harness_session_id"] == STORY_ID
    assert len(found["sessions"]) == 1
    session = found["sessions"][0]
    assert set(session) == SESSION_COLUMNS
    assert session["project"] == str(project)
    assert session["harness"] == "claude_code"
    assert session["tools"] == ["Read", "Edit", "Write", "Bash"]
    # The models the session used come back as a list, as tools do.
    assert isinstance(session["models"], list)
    # The model pass's four fields stay empty until it tags the session.
    assert [session[name] for name in ("title", "gist", "summary", "keywords")] == [None] * 4
    assert session["supersedes"] is None
    assert session["session"] == STORY_ID


def test_list_sessions_on_the_project_or_a_folder_above_it_finds_the_session(store, project, homes):
    for folder in (project, homes, str(project) + "/"):
        found = call(store, "list_sessions", project=str(folder))
        assert [s["harness_session_id"] for s in found["sessions"]] == [STORY_ID]


@pytest.mark.parametrize("other", ["elsewhere", "project_old", "project/inside"])
def test_list_sessions_on_another_folder_returns_none(store, homes, other):
    assert call(store, "list_sessions", project=str(homes / other)) == {"sessions": []}


def test_list_sessions_gives_the_newest_first_and_keeps_to_the_limit(two_sessions, project):
    found = call(two_sessions, "list_sessions")["sessions"]
    assert [s["harness_session_id"] for s in found] == [OTHER_ID, STORY_ID]
    assert found[0]["started_at"] > found[1]["started_at"]
    limited = call(two_sessions, "list_sessions", limit=1)["sessions"]
    assert [s["harness_session_id"] for s in limited] == [OTHER_ID]
    inside = call(two_sessions, "list_sessions", project=str(project / "excluded_folder"))
    assert [s["harness_session_id"] for s in inside["sessions"]] == [OTHER_ID]


@pytest.mark.parametrize("name", ["list_sessions", "search_events"])
@pytest.mark.parametrize("limit", [0, -1])
def test_a_limit_below_one_is_refused(store, name, limit):
    arguments = {"limit": limit}
    if name == "search_events":
        arguments["text"] = "manuscript"
    found = call(store, name, **arguments)
    assert found["error"]["code"] == "invalid_argument"
    assert "limit" in found["error"]["message"]


# get_session.


def test_get_session_returns_its_events_in_the_order_of_the_tool_calls(store, project):
    found = call(store, "get_session", harness_session_id=STORY_ID)
    assert set(found) == {"session", "events", "transcripts"}
    assert found["session"]["harness_session_id"] == STORY_ID
    assert found["session"]["tools"] == ["Read", "Edit", "Write", "Bash"]
    events = found["events"]
    assert [e["id"] for e in events] == STORY_EVENT_IDS
    assert [e["ordinal"] for e in events] == [1, 2, 3, 4, 5, 6]
    first = events[0]
    assert (first["verb"], first["kind"], first["object"], first["role"]) == (
        "searched",
        "observation",
        str(project / "manuscript.md"),
        "read",
    )


def test_get_session_gives_the_transcripts_checksums_and_sizes_and_never_their_content(
    store, story_file
):
    found = call(store, "get_session", harness_session_id=STORY_ID)
    data = story_file.read_bytes()
    assert len(found["transcripts"]) == 1
    transcript = found["transcripts"][0]
    assert transcript["file_sha256"] == hashlib.sha256(data).hexdigest()
    assert transcript["byte_size"] == len(data)
    assert "content" not in transcript and "text" not in transcript
    # Words that are only in the transcript appear nowhere in the answer.
    said = json.dumps(found)
    assert "old_string" not in said
    assert "Castellanos and Ibe describe retention" not in said


def test_get_session_on_an_unknown_id_gives_not_found(store):
    found = call(store, "get_session", harness_session_id="no-such-session")
    assert found["error"]["code"] == "not_found"
    assert "no-such-session" in found["error"]["message"]


# search_events.


def test_search_events_finds_the_check_command(store, project):
    found = call(store, "search_events", text="ospipe check")["events"]
    assert [e["object"] for e in found] == [STORY_CHECK]
    event = found[0]
    assert event["verb"] == "verified" and event["kind"] == "observation"
    assert event["harness_session_id"] == STORY_ID
    assert event["project"] == str(project)


def test_search_events_ignores_case(store):
    found = call(store, "search_events", text="OSPIPE Check")["events"]
    assert [e["object"] for e in found] == [STORY_CHECK]


def test_search_events_on_the_manuscript_includes_the_read_and_both_edits(store):
    found = call(store, "search_events", text="manuscript.md")["events"]
    ids = [e["id"] for e in found]
    for wanted in STORY_EVENT_IDS[:3]:
        assert wanted in ids


def add_correction(home, old_id, rationale):
    """Write a corrected event row that supersedes old_id, as a later pass would.

    The store refuses updates and deletes, so a correction is a new row. It is
    written here straight into the database, which the store allows.
    """
    db = sqlite3.connect(str(home / "audit.sqlite"))
    try:
        cursor = db.execute("SELECT * FROM events WHERE id = ?", (old_id,))
        names = [d[0] for d in cursor.description]
        row = dict(zip(names, cursor.fetchone()))
        row.update(id=old_id + "_fixed", rationale=rationale, supersedes=old_id,
                   method="a test correction", reason="test")
        with db:
            db.execute(
                "INSERT INTO events ({}) VALUES ({})".format(
                    ", ".join(row), ", ".join("?" for _ in row)
                ),
                list(row.values()),
            )
    finally:
        db.close()


def test_search_events_matches_the_rationale_and_leaves_out_a_superseded_event(store):
    add_correction(store, "toolu_story_05_bash", "Checked the Numbers Again before the commit")
    found = call(store, "search_events", text="numbers again")["events"]
    assert [e["id"] for e in found] == ["toolu_story_05_bash_fixed"]
    assert found[0]["harness_session_id"] == STORY_ID
    # The superseded event no longer comes back, only its correction.
    assert [e["id"] for e in call(store, "search_events", text="ospipe check")["events"]] == [
        "toolu_story_05_bash_fixed"
    ]
    events = call(store, "get_session", harness_session_id=STORY_ID)["events"]
    assert [e["id"] for e in events] == STORY_EVENT_IDS[:4] + [
        "toolu_story_05_bash_fixed", "toolu_story_06_bash",
    ]


def test_search_events_keeps_to_the_project_and_the_limit(store, homes, project):
    assert call(store, "search_events", text="manuscript", project=str(homes / "elsewhere")) == {
        "events": []
    }
    inside = call(store, "search_events", text="manuscript", project=str(project))["events"]
    assert len(inside) >= 3
    assert len(call(store, "search_events", text="manuscript", limit=2)["events"]) == 2


# Current rows only.


def test_after_a_grown_copy_the_superseded_row_is_left_out_and_both_captures_events_come_back(
    home, homes, project
):
    audit_command("init")
    lines = story_lines(STORY_SESSION, project)
    path = homes / "growing_session.jsonl"
    write_lines(path, lines[:8])
    audit_command("capture", "--harness", "claude_code", path)
    first = call(home, "list_sessions")["sessions"]
    assert len(first) == 1
    first_id = first[0]["id"]

    write_lines(path, lines)
    audit_command("capture", "--harness", "claude_code", path)
    listed = call(home, "list_sessions")["sessions"]
    assert len(listed) == 1
    assert listed[0]["id"] != first_id
    assert listed[0]["supersedes"] == first_id

    found = call(home, "get_session", harness_session_id=STORY_ID)
    assert found["session"]["id"] == listed[0]["id"]
    assert [e["id"] for e in found["events"]] == STORY_EVENT_IDS
    assert {e["session_row_id"] for e in found["events"]} == {first_id, listed[0]["id"]}
    assert len(found["transcripts"]) == 2
    assert all(e["session_row_id"] != first_id or e["ordinal"] <= 3 for e in found["events"])

    searched = call(home, "search_events", text="ospipe check")["events"]
    assert [e["project"] for e in searched] == [str(project)]


# Read only.


def test_the_database_hashes_the_same_before_and_after_the_calls(two_sessions):
    database = two_sessions / "audit.sqlite"
    before = digest(database)
    names_before = sorted(p.name for p in two_sessions.iterdir())
    call(two_sessions, "list_sessions")
    call(two_sessions, "list_sessions", project="/nowhere")
    call(two_sessions, "get_session", harness_session_id=STORY_ID)
    call(two_sessions, "get_session", harness_session_id="missing")
    call(two_sessions, "search_events", text="manuscript")
    assert digest(database) == before
    assert sorted(p.name for p in two_sessions.iterdir()) == names_before


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO sessions (id, created_at, session, origin, method, reason)"
        " VALUES ('x', 'now', 's', 'o', 'm', 'r')",
        "CREATE TABLE extra (n INTEGER)",
        "DROP TABLE events",
    ],
)
def test_a_write_through_open_store_fails(store, sql):
    before = digest(store / "audit.sqlite")
    db = open_store(store)
    try:
        with pytest.raises(sqlite3.OperationalError):
            db.execute(sql)
            db.commit()
    finally:
        db.close()
    assert digest(store / "audit.sqlite") == before


def test_an_empty_home_gives_no_store_from_every_tool(home):
    home.mkdir(parents=True)
    answers = [
        call(home, "list_sessions"),
        call(home, "get_session", harness_session_id=STORY_ID),
        call(home, "search_events", text="manuscript"),
    ]
    for answer in answers:
        assert answer["error"]["code"] == "no_store"
        assert str(home) in answer["error"]["message"]
    assert list(home.iterdir()) == []


def test_a_missing_home_gives_no_store_and_is_not_made(homes):
    missing = homes / "never_made"
    assert call(missing, "list_sessions")["error"]["code"] == "no_store"
    assert not missing.exists()


def test_open_store_on_an_empty_home_raises_and_makes_no_file(home):
    home.mkdir(parents=True)
    with pytest.raises(sqlite3.OperationalError):
        open_store(home)
    assert list(home.iterdir()) == []


def test_a_home_whose_path_needs_quoting_is_opened(homes, project, story_file):
    odd = homes / "audit home #1?"
    audit_command("init", "--home", odd)
    audit_command("capture", "--home", odd, "--harness", "claude_code", story_file)
    found = call(odd, "list_sessions")["sessions"]
    assert [s["harness_session_id"] for s in found] == [STORY_ID]


# The command, over standard input and output.


def serve_audit(messages, *options):
    lines = "".join(json.dumps(m) + "\n" for m in messages)
    done = subprocess.run(
        [sys.executable, "-m", "connections", "serve", "audit"] + [str(o) for o in options],
        cwd=str(ROOT),
        env=dict(os.environ),
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
     "params": {"name": "get_session", "arguments": {"harness_session_id": STORY_ID}}},
]


def check_served(replies, project):
    assert [r["id"] for r in replies] == [1, 2, 3]
    assert replies[0]["result"]["serverInfo"]["name"] == "workflow-audit"
    assert replies[0]["result"]["protocolVersion"] == "2025-06-18"
    assert sorted(t["name"] for t in replies[1]["result"]["tools"]) == [
        "get_session", "list_sessions", "search_events",
    ]
    assert replies[2]["result"]["isError"] is False
    found = json.loads(replies[2]["result"]["content"][0]["text"])
    assert found["session"]["project"] == str(project)
    assert [e["id"] for e in found["events"]] == STORY_EVENT_IDS


def test_serve_audit_answers_over_standard_input_and_output_with_the_home_option(
    store, project, monkeypatch, homes
):
    monkeypatch.setenv("AUDIT_HOME", str(homes / "not_this_one"))
    check_served(serve_audit(MESSAGES, "--home", store), project)


def test_serve_audit_finds_the_home_in_the_variable(store, project):
    check_served(serve_audit(MESSAGES), project)


def test_serve_audit_finds_the_home_in_the_home_folder_last(store, project, monkeypatch, homes):
    monkeypatch.delenv("AUDIT_HOME")
    target = Path(os.environ["HOME"]) / ".audit_layer"
    store.rename(target)
    check_served(serve_audit(MESSAGES), project)


def test_serve_audit_on_an_empty_home_answers_no_store(home, homes):
    replies = serve_audit(MESSAGES, "--home", homes / "empty")
    assert replies[2]["result"]["isError"] is True
    assert json.loads(replies[2]["result"]["content"][0]["text"])["error"]["code"] == "no_store"


def test_serve_audit_answers_each_message_before_the_input_closes(store):
    server = subprocess.Popen(
        [sys.executable, "-m", "connections", "serve", "audit"],
        cwd=str(ROOT),
        env=dict(os.environ),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        for number in (1, 2):
            server.stdin.write(json.dumps({"jsonrpc": "2.0", "id": number, "method": "ping"}) + "\n")
            server.stdin.flush()
            assert json.loads(server.stdout.readline()) == {"jsonrpc": "2.0", "id": number, "result": {}}
        server.stdin.close()
        assert server.wait(timeout=30) == 0
        assert server.stdout.read() == ""
    finally:
        if server.poll() is None:
            server.kill()
        server.stdout.close()


def test_the_server_imports_no_other_layer():
    source = Path(audit_server.__file__).read_text(encoding="utf-8")
    for layer in ("audit_layer", "ospipe", "verification_procedures", "observability", "features"):
        assert "import " + layer not in source and "from " + layer not in source
