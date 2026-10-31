"""Tests for the check for missed or interrupted captures (Track A, Step A7).

Appendix Table A5 names a check for missed or interrupted captures, and spec
0.11 "Audit" says sessions do not reliably close. The check gives four lists
(not captured, working folder unknown, changed since capture, stored file
missing or altered) and changes nothing, and the sweep is the remedy (plan
choice 8).

Every root here is a temporary folder holding copies of the test story's
synthetic Claude Code sessions, with the folder token replaced, or the
synthetic Forge database that fixtures/forgecode/make_store.py writes. Every
harness the check is asked to reach is given its root, so no default root is
read. No real session file is read, nothing here calls a model or the
network, and every test runs with its home folder inside a temporary folder.
Run from the repository root with python3 -m pytest -q audit_layer/tests.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from audit_layer.capture import capture_session  # noqa: E402
from audit_layer.capture.check import CheckReport, check_captures  # noqa: E402
from audit_layer.capture.sweep import sweep  # noqa: E402
from audit_layer.cli import main  # noqa: E402
from audit_layer.store import current, open_store  # noqa: E402

_SPEC = importlib.util.spec_from_file_location(
    "forgecode_make_store_for_check",
    Path(__file__).parent / "fixtures" / "forgecode" / "make_store.py",
)
forge = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(forge)

SESSIONS = ROOT / "examples" / "test_story" / "sessions" / "claude_code"
STORY_SESSION = SESSIONS / "story_session.jsonl"
EXCLUDED_SESSION = SESSIONS / "excluded_session.jsonl"
TOKEN = "{{PROJECT}}"

STORY_ID = "5f3c0413-2a7d-4b9e-8c61-a0d4e7b2c913"
EXCLUDED_ID = "9b1e0414-6c3a-4f2d-b8e5-71d2a9c4f086"
# The two copies of the story, each under a session id of its own.
NEW_ID = "1d6e2f07-4c8b-4a3e-9f15-b2c7d0e8a462"
GROWN_ID = "8a4c3e19-7b2d-4f6a-a0e8-c5d1f9b3e724"
BROKEN_ID = "0000broken-not-json-lines"

TABLES = ("sessions", "events", "transcripts")

# The folder Claude Code would name after the project folder. Its name is
# made up here, and no output may print it.
ENCODED = "-encoded-project-folder"


def story_lines(project, session_id=STORY_ID):
    """The story's lines run in project, under session_id, with tool call ids of their own."""
    text = STORY_SESSION.read_text(encoding="utf-8")
    text = text.replace(TOKEN, json.dumps(str(project))[1:-1])
    if session_id != STORY_ID:
        text = text.replace(STORY_ID, session_id)
        text = text.replace("toolu_story_", "toolu_" + session_id[:8] + "_")
    return [line for line in text.split("\n") if line]


def excluded_lines(project):
    text = EXCLUDED_SESSION.read_text(encoding="utf-8")
    text = text.replace(TOKEN, json.dumps(str(project))[1:-1])
    return [line for line in text.split("\n") if line]


def write_session(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes("".join(line + "\n" for line in lines).encode("utf-8"))
    return path


def appended_record(project, session_id):
    """One synthetic assistant record the grown copy gains, a read of the references file."""
    record = {
        "parentUuid": None,
        "isSidechain": False,
        "cwd": str(project),
        "sessionId": session_id,
        "type": "assistant",
        "message": {
            "role": "assistant",
            "model": "stand-in-model-1",
            "content": [
                {"type": "text", "text": "I will read the references file once more."},
                {
                    "type": "tool_use",
                    "id": "toolu_grown_07_read",
                    "name": "Read",
                    "input": {"file_path": str(project / "refs.bib")},
                },
            ],
        },
        "uuid": "8a4c3e19-0000-4000-8000-000000000016",
        "timestamp": "2026-10-21T14:03:10.000Z",
    }
    return json.dumps(record)


def row_counts(db):
    return {table: db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in TABLES}


def home_files(home):
    """Every file in the audit home with its bytes, so a test can see nothing changed."""
    return {
        str(path.relative_to(home)): path.read_bytes()
        for path in sorted(Path(home).rglob("*"))
        if path.is_file()
    }


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
    return {"excluded_folders": [str(project / "excluded_folder")]}


@pytest.fixture
def audit_home(tmp_path):
    return tmp_path / "audit_home"


@pytest.fixture
def audit(audit_home):
    store = open_store(audit_home)
    yield store
    store.db.close()


@pytest.fixture
def no_forge(tmp_path):
    """A Forge root that does not exist, so the check never reads Forge's default database."""
    return str(tmp_path / "no_forge" / ".forge.db")


@pytest.fixture
def root(tmp_path, project, audit, settings):
    """The step's root, with the story captured and unchanged, a copy never captured,
    a copy captured and then appended to, and the excluded session.
    """
    folder = tmp_path / "claude_root"
    story = write_session(folder / ENCODED / (STORY_ID + ".jsonl"), story_lines(project))
    write_session(folder / ENCODED / (EXCLUDED_ID + ".jsonl"), excluded_lines(project))
    grown = write_session(folder / ENCODED / (GROWN_ID + ".jsonl"), story_lines(project, GROWN_ID))
    capture_session(audit, "claude_code", str(story), settings)
    capture_session(audit, "claude_code", str(grown), settings)
    write_session(folder / ENCODED / (NEW_ID + ".jsonl"), story_lines(project, NEW_ID))
    with grown.open("a", encoding="utf-8") as handle:
        handle.write(appended_record(project, GROWN_ID) + "\n")
    return folder


def check(audit, settings, root, no_forge):
    return check_captures(
        audit, settings, roots={"claude_code": str(root), "forgecode": no_forge}
    )


def check_command(audit_home, root, no_forge, *more):
    return main(
        [
            "check-captures",
            "--home",
            str(audit_home),
            "--root",
            f"claude_code={root}",
            "--root",
            f"forgecode={no_forge}",
        ]
        + list(more)
    )


def write_settings_file(audit_home, settings):
    Path(audit_home).mkdir(parents=True, exist_ok=True)
    (Path(audit_home) / "settings.yaml").write_text(json.dumps(settings), encoding="utf-8")


# The step's root gives one not captured, one changed since capture, and
# nothing for the excluded session.


def test_the_root_gives_one_not_captured_and_one_changed(audit, settings, root, no_forge):
    report = check(audit, settings, root, no_forge)

    assert isinstance(report, CheckReport)
    assert report.not_captured == (NEW_ID,)
    assert report.changed_since_capture == (GROWN_ID,)
    assert report.working_folder_unknown == ()
    assert report.stored_file_missing_or_altered == ()


def test_the_excluded_session_is_in_no_list(audit, settings, root, no_forge):
    report = check(audit, settings, root, no_forge)
    for names in report:
        assert EXCLUDED_ID not in names


def test_the_captured_unchanged_story_is_in_no_list(audit, settings, root, no_forge):
    report = check(audit, settings, root, no_forge)
    for names in report:
        assert STORY_ID not in names


def test_the_check_writes_nothing(audit, audit_home, settings, root, no_forge):
    before_counts = row_counts(audit.db)
    before_files = home_files(audit_home)

    check(audit, settings, root, no_forge)

    assert row_counts(audit.db) == before_counts
    assert home_files(audit_home) == before_files
    # No lock is taken, since the check is not a sweep.
    assert not (Path(audit_home) / "sweep.lock").exists()


def test_the_check_leaves_the_session_files_as_they_were(audit, settings, root, no_forge):
    before = home_files(root)
    check(audit, settings, root, no_forge)
    assert home_files(root) == before


# After a sweep the check finds nothing.


def test_after_a_sweep_the_check_finds_nothing(audit, audit_home, settings, root, no_forge):
    sweep(audit, settings, audit_home, harnesses=["claude_code"], roots={"claude_code": str(root)})
    report = check(audit, settings, root, no_forge)
    assert report == CheckReport((), (), (), ())


def test_after_a_sweep_the_command_exits_0(audit, audit_home, settings, root, no_forge, capsys):
    write_settings_file(audit_home, settings)
    sweep(audit, settings, audit_home, harnesses=["claude_code"], roots={"claude_code": str(root)})
    capsys.readouterr()

    assert check_command(audit_home, root, no_forge) == 0
    out = capsys.readouterr().out
    assert "not captured, 0 sessions" in out
    assert "working folder unknown, 0 sessions" in out
    assert "changed since capture, 0 sessions" in out
    assert "stored file missing or altered, 0 sessions" in out


# Stored files that are gone or altered.


def test_a_deleted_and_an_altered_transcript_file_are_both_listed(
    audit, audit_home, settings, root, no_forge
):
    by_session = {row["session"]: row["file_sha256"] for row in current(audit, "transcripts")}
    (audit.files / by_session[STORY_ID]).unlink()
    (audit.files / by_session[GROWN_ID]).write_bytes(b"not the stored transcript\n")
    before = row_counts(audit.db)

    report = check(audit, settings, root, no_forge)

    assert report.stored_file_missing_or_altered == (STORY_ID, GROWN_ID)
    assert row_counts(audit.db) == before


def test_a_whole_file_store_lists_nothing_missing(audit, settings, root, no_forge):
    assert check(audit, settings, root, no_forge).stored_file_missing_or_altered == ()


# Forge, whose conversation with no System message cannot be placed.


def test_the_forge_conversation_with_no_system_message_has_no_known_folder(
    audit, settings, tmp_path, project
):
    database = forge.make_store(tmp_path / "forge" / ".forge.db", project)
    empty = tmp_path / "empty_claude_root"
    before = row_counts(audit.db)

    report = check_captures(
        audit, settings, roots={"claude_code": str(empty), "forgecode": str(database)}
    )

    assert report.working_folder_unknown == (forge.NO_SYSTEM_ID,)
    # The story's conversation was never captured, and the excluded one is in no list.
    assert report.not_captured == (forge.STORY_ID,)
    for names in report:
        assert forge.EXCLUDED_ID not in names
    assert row_counts(audit.db) == before


def test_a_captured_forge_conversation_is_not_listed(audit, settings, tmp_path, project):
    database = forge.make_store(tmp_path / "forge" / ".forge.db", project)
    capture_session(audit, "forgecode", f"{database}#{forge.STORY_ID}", settings)

    report = check_captures(audit, settings, harnesses=["forgecode"], roots={"forgecode": str(database)})

    assert report.not_captured == ()
    assert report.changed_since_capture == ()
    assert report.working_folder_unknown == (forge.NO_SYSTEM_ID,)


def test_harnesses_limit_the_check(audit, settings, root, tmp_path, project):
    database = forge.make_store(tmp_path / "forge" / ".forge.db", project)
    roots = {"claude_code": str(root), "forgecode": str(database)}

    only_forge = check_captures(audit, settings, harnesses=["forgecode"], roots=roots)
    assert only_forge.not_captured == (forge.STORY_ID,)
    assert only_forge.changed_since_capture == ()

    only_claude = check_captures(audit, settings, harnesses=["claude_code"], roots=roots)
    assert only_claude.not_captured == (NEW_ID,)
    assert only_claude.working_folder_unknown == ()


def test_an_unknown_harness_is_refused(audit, settings, root):
    with pytest.raises(ValueError, match="no adapter"):
        check_captures(audit, settings, harnesses=["no_such_harness"], roots={})


# A session file that cannot be read cannot be placed.


def test_a_file_that_cannot_be_read_has_no_known_folder(audit, settings, root, no_forge):
    (root / ENCODED / (BROKEN_ID + ".jsonl")).write_bytes(b"this line is not JSON\n")
    report = check(audit, settings, root, no_forge)
    assert report.working_folder_unknown == (BROKEN_ID,)
    assert report.not_captured == (NEW_ID,)


# The command.


def test_the_command_prints_the_lists_by_id_and_exits_1(
    audit, audit_home, settings, root, no_forge, tmp_path, capsys
):
    write_settings_file(audit_home, settings)
    capsys.readouterr()

    assert check_command(audit_home, root, no_forge) == 1
    out = capsys.readouterr().out
    assert "not captured, 1 session" in out
    assert "changed since capture, 1 session" in out
    assert "working folder unknown, 0 sessions" in out
    assert "stored file missing or altered, 0 sessions" in out
    assert NEW_ID in out
    assert GROWN_ID in out
    assert EXCLUDED_ID not in out
    assert "sweep" in out
    # Sessions are named by id, never by a path.
    assert str(tmp_path) not in out
    assert ENCODED not in out


def test_the_command_names_the_sweep_for_the_first_three_lists_only(
    audit, audit_home, settings, root, no_forge, capsys
):
    write_settings_file(audit_home, settings)
    by_session = {row["session"]: row["file_sha256"] for row in current(audit, "transcripts")}
    (audit.files / by_session[STORY_ID]).unlink()
    capsys.readouterr()

    assert check_command(audit_home, root, no_forge) == 1
    lines = capsys.readouterr().out.splitlines()
    headings = [line for line in lines if not line.startswith(" ")]
    assert headings == [
        "not captured, 1 session, run python3 -m audit_layer sweep",
        "working folder unknown, 0 sessions",
        "changed since capture, 1 session, run python3 -m audit_layer sweep",
        "stored file missing or altered, 1 session",
    ]
    assert "  " + STORY_ID in lines


def test_the_command_writes_nothing(audit, audit_home, settings, root, no_forge):
    write_settings_file(audit_home, settings)
    before_counts = row_counts(audit.db)
    before_files = home_files(audit_home)

    check_command(audit_home, root, no_forge)

    assert row_counts(audit.db) == before_counts
    assert home_files(audit_home) == before_files


def test_the_command_takes_one_harness(audit, audit_home, settings, root, tmp_path, capsys):
    write_settings_file(audit_home, settings)
    capsys.readouterr()
    code = main(
        [
            "check-captures",
            "--home",
            str(audit_home),
            "--harness",
            "claude_code",
            "--root",
            f"claude_code={root}",
        ]
    )
    assert code == 1
    assert NEW_ID in capsys.readouterr().out


def test_the_command_refuses_without_the_settings_file(audit_home, root, no_forge, capsys):
    assert check_command(audit_home, root, no_forge) == 1
    assert "check refused" in capsys.readouterr().err


def test_the_command_refuses_without_a_store_and_makes_none(tmp_path, root, no_forge, capsys):
    home = tmp_path / "empty_home"
    write_settings_file(home, {"excluded_folders": []})
    assert check_command(home, root, no_forge) == 1
    assert "check refused" in capsys.readouterr().err
    assert sorted(path.name for path in home.iterdir()) == ["settings.yaml"]


@pytest.mark.parametrize("given", ["claude_code", "no_such_harness=/tmp/x"])
def test_the_command_refuses_a_root_it_cannot_read(audit_home, given):
    with pytest.raises(SystemExit) as raised:
        main(["check-captures", "--home", str(audit_home), "--root", given])
    assert raised.value.code == 2


def test_the_command_lists_the_forge_conversation_it_cannot_place(
    audit, audit_home, settings, tmp_path, project, capsys
):
    write_settings_file(audit_home, settings)
    database = forge.make_store(tmp_path / "forge" / ".forge.db", project)
    capsys.readouterr()
    code = main(
        [
            "check-captures",
            "--home",
            str(audit_home),
            "--harness",
            "forgecode",
            "--root",
            f"forgecode={database}",
        ]
    )
    assert code == 1
    lines = capsys.readouterr().out.splitlines()
    at = lines.index("working folder unknown, 1 session, run python3 -m audit_layer sweep")
    assert lines[at + 1] == "  " + forge.NO_SYSTEM_ID
    assert str(tmp_path) not in "\n".join(lines)


# A harness whose sessions cannot be listed.


def test_a_listing_that_fails_is_refused_by_harness(audit, settings, tmp_path):
    bad = tmp_path / "forge" / ".forge.db"
    bad.parent.mkdir()
    bad.write_bytes(b"this is not a database")
    with pytest.raises(ValueError) as raised:
        check_captures(audit, settings, harnesses=["forgecode"], roots={"forgecode": str(bad)})
    assert str(raised.value) == "could not list the forgecode sessions"


def test_the_command_says_a_listing_failed_without_its_path(
    audit, audit_home, settings, tmp_path, capsys
):
    write_settings_file(audit_home, settings)
    bad = tmp_path / "forge" / ".forge.db"
    bad.parent.mkdir()
    bad.write_bytes(b"this is not a database")
    capsys.readouterr()
    code = main(
        ["check-captures", "--home", str(audit_home), "--harness", "forgecode", "--root", f"forgecode={bad}"]
    )
    assert code == 1
    out = capsys.readouterr()
    assert "could not list the forgecode sessions" in out.err
    assert str(bad) not in out.err + out.out


def test_a_file_named_apart_from_its_records_is_checked_under_the_records_id(
    audit, settings, tmp_path, project, no_forge
):
    folder = tmp_path / "renamed_root"
    renamed = write_session(folder / ENCODED / "renamed.jsonl", story_lines(project))
    capture_session(audit, "claude_code", str(renamed), settings)
    assert check(audit, settings, folder, no_forge) == CheckReport((), (), (), ())

    with renamed.open("a", encoding="utf-8") as handle:
        handle.write(appended_record(project, STORY_ID) + "\n")
    assert check(audit, settings, folder, no_forge).changed_since_capture == (STORY_ID,)
