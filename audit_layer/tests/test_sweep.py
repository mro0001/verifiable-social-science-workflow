"""Tests for the sweep (Track A, Step A5).

Appendix A2.4 "Capture" sweeps each harness's session files while a session
runs, when it ends, and again on a schedule, and Figure A4 says the sweep is
safe to repeat. The sweep skips a session whose size equals its last stored
transcript, and one sweep runs at a time through a lock file in the audit home
(plan choice 6).

Every root here is a temporary folder holding the test story's synthetic
Claude Code sessions, with the folder token replaced, the subagent fixture,
or the synthetic Forge database that fixtures/forgecode/make_store.py writes.
Every harness the sweep is asked to reach is given its root, so no default
root is read. No real session file is read, nothing here calls a model or the
network, and every test runs with its home folder inside a temporary folder.
Run from the repository root with python3 -m pytest -q audit_layer/tests.
"""
import fcntl
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import audit_layer.capture.claude_code as claude_code  # noqa: E402
from audit_layer.capture import sweep as sweep_module  # noqa: E402
from audit_layer.capture.sweep import ANOTHER_SWEEP, LOCK, SweepSummary, sweep  # noqa: E402
from audit_layer.cli import main  # noqa: E402
from audit_layer.queries import current_session  # noqa: E402
from audit_layer.store import current, open_store  # noqa: E402

_SPEC = importlib.util.spec_from_file_location(
    "forgecode_make_store_for_sweep",
    Path(__file__).parent / "fixtures" / "forgecode" / "make_store.py",
)
forge = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(forge)

SESSIONS = ROOT / "examples" / "test_story" / "sessions" / "claude_code"
STORY_SESSION = SESSIONS / "story_session.jsonl"
EXCLUDED_SESSION = SESSIONS / "excluded_session.jsonl"
SUBAGENT = Path(__file__).parent / "fixtures" / "claude_code" / "subagent.jsonl"
TOKEN = "{{PROJECT}}"

STORY_ID = "5f3c0413-2a7d-4b9e-8c61-a0d4e7b2c913"
EXCLUDED_ID = "9b1e0414-6c3a-4f2d-b8e5-71d2a9c4f086"
BROKEN_ID = "0000broken-not-json-lines"
AGENT_ID = "a7c41e2b9d0f3856"
SUBAGENT_ID = STORY_ID + "/agent-" + AGENT_ID

TABLES = ("sessions", "events", "transcripts")

# The folder Claude Code would name after the project folder. Its name is
# made up here, and no test output may print it.
ENCODED = "-encoded-project-folder"


def lines_of(source, project):
    text = source.read_text(encoding="utf-8")
    text = text.replace(TOKEN, json.dumps(str(project))[1:-1])
    return [line for line in text.split("\n") if line]


def write_session(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes("".join(line + "\n" for line in lines).encode("utf-8"))
    return path


def settings_for(*folders):
    return {"excluded_folders": [str(folder) for folder in folders]}


def stored_rows(db, table):
    cursor = db.execute(f"SELECT * FROM {table} ORDER BY rowid")
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def all_rows(db):
    return {table: stored_rows(db, table) for table in TABLES}


def appended_records(project):
    """Two synthetic records the story session gains, one tool call and its result."""
    last = lines_of(STORY_SESSION, project)[-1]
    parent = json.loads(last)["uuid"]
    call = {
        "parentUuid": parent,
        "isSidechain": False,
        "cwd": str(project),
        "sessionId": STORY_ID,
        "type": "assistant",
        "message": {
            "role": "assistant",
            "model": "stand-in-model-1",
            "content": [
                {"type": "text", "text": "I will read the references file once more."},
                {
                    "type": "tool_use",
                    "id": "toolu_story_07_read",
                    "name": "Read",
                    "input": {"file_path": str(project / "refs.bib")},
                },
            ],
        },
        "uuid": "5f3c0413-0000-4000-8000-000000000016",
        "timestamp": "2026-10-21T14:03:10.000Z",
    }
    result = {
        "parentUuid": call["uuid"],
        "isSidechain": False,
        "cwd": str(project),
        "sessionId": STORY_ID,
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {"tool_use_id": "toolu_story_07_read", "type": "tool_result", "content": "@article{"}
            ],
        },
        "uuid": "5f3c0413-0000-4000-8000-000000000017",
        "timestamp": "2026-10-21T14:03:11.000Z",
    }
    return [json.dumps(call), json.dumps(result)]


@pytest.fixture(autouse=True)
def home_folder(tmp_path, monkeypatch):
    """Each test's own home folder, so nothing reaches the real ~/.audit_layer or a real root."""
    home = tmp_path / "home_folder"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("AUDIT_HOME", raising=False)
    return home


@pytest.fixture
def project(tmp_path):
    folder = tmp_path / "project"
    folder.mkdir()
    return folder


@pytest.fixture
def settings(project):
    return settings_for(project / "excluded_folder")


@pytest.fixture
def audit_home(tmp_path):
    return tmp_path / "audit_home"


@pytest.fixture
def audit(audit_home):
    store = open_store(audit_home)
    yield store
    store.db.close()


@pytest.fixture
def root(tmp_path, project):
    """A Claude Code root holding the story, the excluded session, and a file that is not JSON Lines."""
    folder = tmp_path / "claude_root"
    write_session(folder / ENCODED / (STORY_ID + ".jsonl"), lines_of(STORY_SESSION, project))
    write_session(folder / ENCODED / (EXCLUDED_ID + ".jsonl"), lines_of(EXCLUDED_SESSION, project))
    broken = folder / ENCODED / (BROKEN_ID + ".jsonl")
    broken.write_bytes(b"this line is not JSON\n")
    return folder


def story_file(root):
    return root / ENCODED / (STORY_ID + ".jsonl")


def sweep_claude(audit, settings, audit_home, root):
    return sweep(audit, settings, audit_home, harnesses=["claude_code"], roots={"claude_code": str(root)})


# The first sweep captures the story, counts the excluded session, and names
# the broken file by its id.


def test_the_first_sweep_captures_the_story_counts_the_excluded_and_names_the_broken(
    audit, settings, audit_home, root
):
    summary = sweep_claude(audit, settings, audit_home, root)

    assert isinstance(summary, SweepSummary)
    assert summary.refused is None
    assert summary.captured == 1
    assert summary.unchanged == 0
    assert summary.excluded == 1
    assert summary.folder_unknown == 0
    assert [name for name, _ in summary.failed] == [BROKEN_ID]

    sessions = current(audit, "sessions")
    assert [row["harness_session_id"] for row in sessions] == [STORY_ID]
    assert len(current(audit, "events")) == 6
    assert len(current(audit, "transcripts")) == 1


def test_a_failure_names_no_path(audit, settings, audit_home, root, tmp_path):
    summary = sweep_claude(audit, settings, audit_home, root)

    (name, reason), = summary.failed
    assert name == BROKEN_ID
    assert reason
    for text in (name, reason):
        assert str(tmp_path) not in text
        assert ENCODED not in text


def test_a_broken_file_listed_first_does_not_stop_the_sweep(audit, settings, audit_home, root):
    # BROKEN_ID sorts before the story's id, so the broken file is met first.
    assert sorted([BROKEN_ID, STORY_ID])[0] == BROKEN_ID
    summary = sweep_claude(audit, settings, audit_home, root)
    assert summary.captured == 1
    assert current_session(audit, "claude_code", STORY_ID) is not None


# A second sweep counts the story unchanged, does not read it, and stores nothing.


def test_a_second_sweep_counts_the_story_unchanged_and_stores_nothing(
    audit, settings, audit_home, root
):
    sweep_claude(audit, settings, audit_home, root)
    before = all_rows(audit.db)

    summary = sweep_claude(audit, settings, audit_home, root)

    assert summary.captured == 0
    assert summary.unchanged == 1
    assert summary.excluded == 1
    assert [name for name, _ in summary.failed] == [BROKEN_ID]
    assert all_rows(audit.db) == before


def test_an_unchanged_session_is_not_read(audit, settings, audit_home, root, monkeypatch):
    sweep_claude(audit, settings, audit_home, root)
    read = []
    reader = claude_code.read_session

    def recording(location):
        read.append(str(location))
        return reader(location)

    monkeypatch.setattr(claude_code, "read_session", recording)
    sweep_claude(audit, settings, audit_home, root)

    assert str(story_file(root)) not in read


# After two records are appended, a sweep captures only the new event.


def test_a_grown_session_adds_only_its_new_event(audit, settings, audit_home, root, project):
    sweep_claude(audit, settings, audit_home, root)
    before_events = {row["id"] for row in current(audit, "events")}
    path = story_file(root)
    with path.open("a", encoding="utf-8") as handle:
        for line in appended_records(project):
            handle.write(line + "\n")

    summary = sweep_claude(audit, settings, audit_home, root)

    assert summary.captured == 1
    assert summary.unchanged == 0
    after_events = {row["id"] for row in current(audit, "events")}
    assert after_events - before_events == {"toolu_story_07_read"}
    assert before_events <= after_events
    transcripts = current(audit, "transcripts")
    assert len(transcripts) == 2
    assert transcripts[-1]["byte_size"] == path.stat().st_size
    # And the sweep after that finds it unchanged.
    assert sweep_claude(audit, settings, audit_home, root).unchanged == 1


# Given locations, the sweep takes them and lists nothing.


def test_given_locations_sweep_one_named_file(audit, settings, audit_home, root):
    summary = sweep(
        audit,
        settings,
        audit_home,
        harnesses=["claude_code"],
        roots={"claude_code": str(root / "no_such_root")},
        locations=[str(story_file(root))],
    )
    assert summary.captured == 1
    assert summary.excluded == 0
    assert summary.failed == ()
    assert [row["harness_session_id"] for row in current(audit, "sessions")] == [STORY_ID]

    again = sweep(
        audit, settings, audit_home, harnesses=["claude_code"], locations=[str(story_file(root))]
    )
    assert again.captured == 0
    assert again.unchanged == 1


def test_given_locations_need_one_harness(audit, settings, audit_home, root):
    with pytest.raises(ValueError, match="one harness"):
        sweep(
            audit,
            settings,
            audit_home,
            harnesses=["claude_code", "forgecode"],
            locations=[str(story_file(root))],
        )
    with pytest.raises(ValueError, match="one harness"):
        sweep(audit, settings, audit_home, locations=[str(story_file(root))])
    assert all(rows == [] for rows in all_rows(audit.db).values())


def test_a_given_location_that_fails_is_named_without_its_folders(
    audit, settings, audit_home, root, tmp_path
):
    broken = root / ENCODED / (BROKEN_ID + ".jsonl")
    summary = sweep(audit, settings, audit_home, harnesses=["claude_code"], locations=[str(broken)])
    (name, reason), = summary.failed
    assert name == BROKEN_ID
    for text in (name, reason):
        assert str(tmp_path) not in text
        assert ENCODED not in text


@pytest.mark.parametrize("join", ["//", "/./"])
def test_a_given_location_written_loosely_is_still_kept_out_of_the_reason(
    audit, settings, audit_home, root, tmp_path, join
):
    loose = str(root / ENCODED) + join + BROKEN_ID + ".jsonl"
    summary = sweep(audit, settings, audit_home, harnesses=["claude_code"], locations=[loose])
    (name, reason), = summary.failed
    assert name == BROKEN_ID
    for text in (name, reason):
        assert str(tmp_path) not in text
        assert ENCODED not in text


def test_a_given_forge_location_that_fails_is_named_by_its_conversation_id(
    audit, settings, audit_home, tmp_path, project
):
    database = forge.make_store(tmp_path / "forge" / ".forge.db", project)
    loose = str(database.parent) + "//" + database.name + "#no-such-conversation"
    summary = sweep(audit, settings, audit_home, harnesses=["forgecode"], locations=[loose])
    (name, reason), = summary.failed
    assert name == "no-such-conversation"
    assert str(tmp_path) not in reason


def test_an_unknown_harness_is_refused(audit, settings, audit_home, root):
    with pytest.raises(ValueError, match="no adapter"):
        sweep(audit, settings, audit_home, harnesses=["no_such_harness"], roots={})


# One sweep runs at a time.


def test_a_sweep_that_cannot_take_the_lock_touches_nothing(audit, settings, audit_home, root):
    before = all_rows(audit.db)
    with open(str(audit_home / LOCK), "a") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        summary = sweep_claude(audit, settings, audit_home, root)
    assert summary.refused == ANOTHER_SWEEP == "another sweep is running"
    assert (summary.captured, summary.unchanged, summary.excluded, summary.folder_unknown) == (0, 0, 0, 0)
    assert summary.failed == ()
    assert all_rows(audit.db) == before


def test_the_lock_is_let_go_after_a_sweep(audit, settings, audit_home, root):
    sweep_claude(audit, settings, audit_home, root)
    with open(str(audit_home / LOCK), "a") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(held.fileno(), fcntl.LOCK_UN)
    assert sweep_claude(audit, settings, audit_home, root).refused is None


def test_the_lock_is_let_go_when_a_sweep_fails(audit, settings, audit_home, root, monkeypatch):
    def broken_listing(*given):
        raise RuntimeError("the listing broke")

    monkeypatch.setattr(sweep_module, "_listed", broken_listing)
    with pytest.raises(RuntimeError):
        sweep_claude(audit, settings, audit_home, root)
    monkeypatch.undo()
    assert sweep_claude(audit, settings, audit_home, root).refused is None


# Subagent conversations are captured once per sweep.


def test_a_subagent_is_captured_once_with_its_main_session(
    audit, settings, audit_home, tmp_path, project
):
    folder = tmp_path / "claude_root"
    write_session(folder / ENCODED / (STORY_ID + ".jsonl"), lines_of(STORY_SESSION, project))
    write_session(
        folder / ENCODED / STORY_ID / "subagents" / ("agent-" + AGENT_ID + ".jsonl"),
        lines_of(SUBAGENT, project),
    )
    summary = sweep_claude(audit, settings, audit_home, folder)
    assert summary.captured == 2
    assert summary.unchanged == 0
    assert summary.failed == ()
    ids = sorted(row["harness_session_id"] for row in current(audit, "sessions"))
    assert ids == sorted([STORY_ID, SUBAGENT_ID])

    again = sweep_claude(audit, settings, audit_home, folder)
    assert (again.captured, again.unchanged) == (0, 2)


def test_a_grown_subagent_is_captured_on_its_own(audit, settings, audit_home, tmp_path, project):
    folder = tmp_path / "claude_root"
    write_session(folder / ENCODED / (STORY_ID + ".jsonl"), lines_of(STORY_SESSION, project))
    agent = write_session(
        folder / ENCODED / STORY_ID / "subagents" / ("agent-" + AGENT_ID + ".jsonl"),
        lines_of(SUBAGENT, project),
    )
    sweep_claude(audit, settings, audit_home, folder)
    lines = lines_of(SUBAGENT, project)
    last = json.loads(lines[-1])
    extra = dict(last, uuid="a7c41e2b-0000-4000-8000-0000000000ff", parentUuid=last["uuid"])
    extra["timestamp"] = "2026-10-21T14:09:00.000Z"
    write_session(agent, lines + [json.dumps(extra)])

    summary = sweep_claude(audit, settings, audit_home, folder)
    assert (summary.captured, summary.unchanged) == (1, 1)


# One sweep reaches both harnesses.


def test_one_sweep_captures_from_claude_code_and_forge(
    audit, settings, audit_home, tmp_path, project
):
    folder = tmp_path / "claude_root"
    write_session(folder / ENCODED / (STORY_ID + ".jsonl"), lines_of(STORY_SESSION, project))
    database = forge.make_store(tmp_path / "forge" / ".forge.db", project)

    summary = sweep(
        audit,
        settings,
        audit_home,
        roots={"claude_code": str(folder), "forgecode": str(database)},
    )

    assert summary.captured == 2
    assert summary.excluded == 1
    assert summary.folder_unknown == 1
    assert summary.failed == ()
    harnesses = sorted(
        (row["harness"], row["harness_session_id"]) for row in current(audit, "sessions")
    )
    assert harnesses == [("claude_code", STORY_ID), ("forgecode", forge.STORY_ID)]

    again = sweep(
        audit,
        settings,
        audit_home,
        roots={"claude_code": str(folder), "forgecode": str(database)},
    )
    assert again.captured == 0
    assert again.unchanged == 2


# The sweep command.


def init_home(home, project):
    assert main(["init", "--home", str(home)]) == 0
    (home / "settings.yaml").write_text(
        "excluded_folders:\n  - " + str(project / "excluded_folder") + "\n", encoding="utf-8"
    )


def test_the_command_refuses_without_the_settings_file(tmp_path, root, capsys):
    home = tmp_path / "fresh_home"
    code = main(["sweep", "--home", str(home), "--harness", "claude_code", "--root", f"claude_code={root}"])
    assert code == 1
    assert "sweep refused" in capsys.readouterr().err
    assert not (home / "audit.sqlite").exists()


def test_the_command_prints_the_summary_and_exits_1_on_a_failure(
    tmp_path, root, project, capsys
):
    home = tmp_path / "cli_home"
    init_home(home, project)
    capsys.readouterr()

    code = main(["sweep", "--home", str(home), "--harness", "claude_code", "--root", f"claude_code={root}"])
    out = capsys.readouterr()
    assert code == 1
    assert "1 captured" in out.out
    assert "1 excluded" in out.out
    assert "1 failed" in out.out
    assert BROKEN_ID in out.out
    for text in (out.out, out.err):
        assert str(tmp_path) not in text
        assert ENCODED not in text


def test_the_command_exits_0_when_nothing_failed(tmp_path, root, project, capsys):
    (root / ENCODED / (BROKEN_ID + ".jsonl")).unlink()
    home = tmp_path / "cli_home"
    init_home(home, project)
    code = main(["sweep", "--home", str(home), "--harness", "claude_code", "--root", f"claude_code={root}"])
    assert code == 0
    assert "0 failed" in capsys.readouterr().out


def test_the_command_sweeps_a_named_file(tmp_path, root, project, capsys):
    home = tmp_path / "cli_home"
    init_home(home, project)
    capsys.readouterr()
    code = main(
        ["sweep", "--home", str(home), "--harness", "claude_code", "--file", str(story_file(root))]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "1 captured" in out
    assert str(tmp_path) not in out
    store = open_store(home)
    try:
        assert [row["harness_session_id"] for row in current(store, "sessions")] == [STORY_ID]
    finally:
        store.db.close()


def test_the_command_refuses_a_file_without_one_harness(tmp_path, root, project, capsys):
    home = tmp_path / "cli_home"
    init_home(home, project)
    capsys.readouterr()
    code = main(["sweep", "--home", str(home), "--file", str(story_file(root))])
    assert code == 1
    assert "one harness" in capsys.readouterr().err


@pytest.mark.parametrize("given", ["claude_code", "no_such_harness=/x", "=/x", "claude_code="])
def test_the_command_refuses_a_root_it_cannot_read(tmp_path, project, given, capsys):
    home = tmp_path / "cli_home"
    init_home(home, project)
    with pytest.raises(SystemExit) as stopped:
        main(["sweep", "--home", str(home), "--harness", "claude_code", "--root", given])
    assert stopped.value.code == 2


def test_the_command_says_when_another_sweep_is_running(tmp_path, root, project, capsys):
    home = tmp_path / "cli_home"
    init_home(home, project)
    capsys.readouterr()
    with open(str(home / LOCK), "a") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        code = main(
            ["sweep", "--home", str(home), "--harness", "claude_code", "--root", f"claude_code={root}"]
        )
    assert code == 1
    assert "another sweep is running" in capsys.readouterr().err
