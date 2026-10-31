"""Tests for the Claude Code adapter (plan Step 3, appendix A2.4 "Capture").

The adapter reads the test story's two synthetic Claude Code session files,
whose folder token {{PROJECT}} the tests replace with a temporary folder. No
real session file is read, and nothing here calls a model or the network. Run
from the repository root with python3 -m pytest -q audit_layer/tests.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from audit_layer.capture.claude_code import read_session  # noqa: E402

SESSIONS = ROOT / "examples" / "test_story" / "sessions" / "claude_code"
STORY_SESSION = SESSIONS / "story_session.jsonl"
EXCLUDED_SESSION = SESSIONS / "excluded_session.jsonl"
TOKEN = "{{PROJECT}}"

STORY_ID = "5f3c0413-2a7d-4b9e-8c61-a0d4e7b2c913"
EXCLUDED_ID = "9b1e0414-6c3a-4f2d-b8e5-71d2a9c4f086"

# The story session's tool calls in order, each with the harness's own id for
# the call, the tool, and the time of the record that holds the call.
STORY_CALLS = [
    ("toolu_story_01_read", "Read", "2026-10-21T14:02:09.874Z"),
    ("toolu_story_02_edit", "Edit", "2026-10-21T14:02:16.302Z"),
    ("toolu_story_03_edit", "Edit", "2026-10-21T14:02:22.640Z"),
    ("toolu_story_04_write", "Write", "2026-10-21T14:02:30.055Z"),
    ("toolu_story_05_bash", "Bash", "2026-10-21T14:02:35.478Z"),
    ("toolu_story_06_bash", "Bash", "2026-10-21T14:02:41.233Z"),
]


def lines_of(source, project):
    """The session file's records as lines of text, with the token replaced by project."""
    text = source.read_text(encoding="utf-8")
    text = text.replace(TOKEN, json.dumps(str(project))[1:-1])
    return [line for line in text.split("\n") if line]


def write_session(path, lines):
    """Write the lines as a JSON Lines file, each ending in a newline."""
    path.write_bytes("".join(line + "\n" for line in lines).encode("utf-8"))
    return path


def tool_uses(lines):
    """The tool_use parts of the records, read here without the adapter."""
    uses = []
    for line in lines:
        content = (json.loads(line).get("message") or {}).get("content")
        for part in content if isinstance(content, list) else []:
            if part.get("type") == "tool_use":
                uses.append(part)
    return uses


@pytest.fixture
def project(tmp_path):
    return tmp_path / "project"


@pytest.fixture
def story(tmp_path, project):
    """The story session file with its folder token replaced by project."""
    return write_session(tmp_path / "story_session.jsonl", lines_of(STORY_SESSION, project))


def test_the_adapter_returns_the_session_id_working_folder_start_and_end(story, project):
    session = read_session(story)
    assert session.session_id == STORY_ID
    assert session.cwd == str(project)
    assert session.started_at == "2026-10-21T14:02:05.112Z"
    assert session.ended_at == "2026-10-21T14:02:46.009Z"


def test_the_adapter_returns_the_tool_calls_in_order_with_their_inputs(story, project):
    calls = read_session(story).tool_calls
    assert [(call.record_id, call.name, call.time) for call in calls] == STORY_CALLS
    expected = [use["input"] for use in tool_uses(lines_of(STORY_SESSION, project))]
    assert [call.input for call in calls] == expected

    manuscript = str(project / "manuscript.md")
    assert calls[0].input == {"file_path": manuscript}
    assert calls[1].input["file_path"] == manuscript
    assert calls[1].input["new_string"].endswith("[@dumont2014].")
    assert calls[2].input["file_path"] == manuscript
    assert calls[2].input["new_string"].endswith("[@nakamura2020].")
    assert calls[3].input["file_path"] == str(project / "source_notes.md")
    assert calls[4].input["command"].startswith("python3 -m ospipe check")
    assert calls[5].input["command"].startswith(
        "git add manuscript.md source_notes.md && git commit"
    )


@pytest.mark.parametrize("source", [STORY_SESSION, EXCLUDED_SESSION], ids=["story", "excluded"])
def test_the_transcript_bytes_are_identical_to_the_file(tmp_path, source):
    placed = write_session(tmp_path / source.name, lines_of(source, tmp_path / "project"))
    for path in (source, placed):
        transcript = read_session(path).transcript
        assert isinstance(transcript, bytes)
        assert transcript == path.read_bytes()


def test_the_excluded_session_is_read_the_same_way(tmp_path, project):
    path = write_session(tmp_path / "excluded_session.jsonl", lines_of(EXCLUDED_SESSION, project))
    session = read_session(path)
    assert session.session_id == EXCLUDED_ID
    assert session.cwd == str(project / "excluded_folder")
    assert session.started_at == "2026-10-21T15:30:02.204Z"
    assert session.ended_at == "2026-10-21T15:30:09.431Z"
    assert [(call.record_id, call.name, call.time) for call in session.tool_calls] == [
        ("toolu_excluded_01_read", "Read", "2026-10-21T15:30:05.817Z")
    ]
    assert session.tool_calls[0].input == {
        "file_path": str(project / "excluded_folder" / "README.txt")
    }


def test_records_and_fields_the_adapter_does_not_use_change_nothing(tmp_path, story, project):
    plain = read_session(story)
    records = [json.loads(line) for line in lines_of(STORY_SESSION, project)]
    for record in records:
        record["version"] = "2.0.0"
        record["gitBranch"] = "main"
    # Two record types the story leaves out, written here for the test. Neither
    # carries a sessionId, cwd, or timestamp of its own at the top level. The
    # snapshot's own time, earlier than the first record's, is not a record time.
    summary = {
        "type": "summary",
        "summary": "Two findings added after the sentence on fit",
        "leafUuid": records[-1]["uuid"],
    }
    snapshot = {
        "type": "file-history-snapshot",
        "messageId": records[0]["uuid"],
        "snapshot": {
            "messageId": records[0]["uuid"],
            "trackedFileBackups": {},
            "timestamp": "2026-10-21T14:02:05.100Z",
        },
        "isSnapshotUpdate": False,
    }
    lines = [json.dumps(summary), json.dumps(snapshot)]
    lines += [json.dumps(record) for record in records]
    path = write_session(tmp_path / "with_other_records.jsonl", lines)

    session = read_session(path)
    assert session.transcript == path.read_bytes()
    # The version is read since Step P1, as the session's harness_version.
    assert session.harness_version == "2.0.0"
    assert session._replace(transcript=b"", harness_version="") == plain._replace(transcript=b"")


def test_the_session_id_and_working_folder_are_the_first_a_record_gives(tmp_path, project):
    records = [json.loads(line) for line in lines_of(STORY_SESSION, project)]
    for record in records[5:]:
        record["cwd"] = str(project / "excluded_folder")
        record["sessionId"] = EXCLUDED_ID
    path = write_session(tmp_path / "moved.jsonl", [json.dumps(record) for record in records])

    session = read_session(path)
    assert session.session_id == STORY_ID
    assert session.cwd == str(project)


def test_a_line_separator_inside_a_record_stays_in_its_record(tmp_path, project):
    records = [json.loads(line) for line in lines_of(STORY_SESSION, project)]
    write = records[8]["message"]["content"][1]
    assert write["name"] == "Write"
    write["input"]["content"] += "Line and paragraph separators are text here.\n"
    # Written unescaped, as a harness may write them.
    path = write_session(
        tmp_path / "separators.jsonl",
        [json.dumps(record, ensure_ascii=False) for record in records],
    )
    assert " ".encode("utf-8") in path.read_bytes()

    session = read_session(path)
    assert [call.record_id for call in session.tool_calls] == [call[0] for call in STORY_CALLS]
    assert session.tool_calls[3].input == write["input"]
    assert session.transcript == path.read_bytes()


def cut_last_record(lines):
    return lines[:-1] + [lines[-1][: len(lines[-1]) // 2]]


def put_a_list_third(lines):
    return lines[:2] + ["[1, 2]"] + lines[2:]


def drop_the_write_call_id(lines):
    record = json.loads(lines[8])
    del record["message"]["content"][1]["id"]
    return lines[:8] + [json.dumps(record)] + lines[9:]


@pytest.mark.parametrize(
    "change, line",
    [(cut_last_record, 15), (put_a_list_third, 3), (drop_the_write_call_id, 9)],
    ids=["cut record", "not an object", "tool call without an id"],
)
def test_a_broken_record_is_refused_with_its_line_number(tmp_path, project, change, line):
    path = write_session(tmp_path / "broken.jsonl", change(lines_of(STORY_SESSION, project)))
    with pytest.raises(ValueError, match=r"line %d\b" % line):
        read_session(path)


@pytest.mark.parametrize(
    "lines",
    [[], [json.dumps({"type": "summary", "summary": "Nothing yet", "leafUuid": "x"})]],
    ids=["empty file", "summary only"],
)
def test_a_file_with_no_session_record_is_refused(tmp_path, lines):
    path = write_session(tmp_path / "no_session.jsonl", lines)
    with pytest.raises(ValueError, match="session id"):
        read_session(path)
