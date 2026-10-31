"""Tests for the mechanical tagging pass (plan Step 4, appendix A2.4 "Metadata tagging", Table A4).

Each tool call is built here in the shape the Claude Code adapter returns, with
the tool names and inputs Claude Code uses. The story session is read through
the adapter with its folder token {{PROJECT}} replaced by a temporary folder.
No real session file is read, and nothing here calls a model or the network.
Run from the repository root with python3 -m pytest -q audit_layer/tests.
"""
import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from audit_layer.capture.claude_code import ToolCall, read_session  # noqa: E402
from audit_layer.events import validate  # noqa: E402
from audit_layer.tagging.mechanical import session_tags, tag  # noqa: E402

STORY_SESSION = (
    ROOT / "examples" / "test_story" / "sessions" / "claude_code" / "story_session.jsonl"
)
TOKEN = "{{PROJECT}}"

# The working folder of the calls made up below, and two files in it.
CWD = "/home/scholar/project"
MANUSCRIPT = CWD + "/manuscript.md"
NOTES = CWD + "/source_notes.md"

# The story session's two commands, as its file holds them.
STORY_CHECK = (
    "python3 -m ospipe check --manuscript manuscript.md --manifest numbers.yml"
    " --tables-dir . | tail -n 3"
)
STORY_COMMIT = (
    "git add manuscript.md source_notes.md && git commit"
    ' -m "Add two findings on volunteer exit after the sentence on fit"'
)


def call(name, **inputs):
    """A tool call in the shape the adapter returns."""
    return ToolCall(
        record_id="toolu_test_01", name=name, input=inputs, time="2026-10-21T14:02:09.874Z"
    )


def fields(verb, kind, object_, role):
    """The event fields the tagging pass gives a tool call."""
    return {"verb": verb, "kind": kind, "object": object_, "role": role}


def bash(command):
    return call("Bash", command=command, description="A command")


# Each mapping of plan Step 4, as a tool call and the verb, kind, object, and
# role it gets.
MAPPINGS = [
    pytest.param(
        call("Write", file_path=NOTES, content="# Sources added in this session\n"),
        fields("wrote", "action", NOTES, "produced"),
        id="Write",
    ),
    pytest.param(
        call(
            "Edit",
            file_path=MANUSCRIPT,
            old_string="the tasks offered [@castellanos2017].",
            new_string="the tasks offered [@castellanos2017]. Clear end dates [@dumont2014].",
        ),
        fields("edited", "action", MANUSCRIPT, "edited"),
        id="Edit",
    ),
    pytest.param(
        call("Read", file_path=MANUSCRIPT),
        fields("searched", "observation", MANUSCRIPT, "read"),
        id="Read",
    ),
    pytest.param(
        call("Grep", pattern=r"@nakamura\d{4}", path=CWD, output_mode="content"),
        fields("searched", "observation", r"@nakamura\d{4}", ""),
        id="Grep",
    ),
    pytest.param(
        call("Glob", pattern="**/*.md", path=CWD),
        fields("searched", "observation", "**/*.md", ""),
        id="Glob",
    ),
    pytest.param(
        call("WebSearch", query="recognition events and volunteer exit"),
        fields("searched", "observation", "recognition events and volunteer exit", ""),
        id="web search",
    ),
    pytest.param(
        call(
            "WebFetch",
            url="https://doi.org/10.5555/nakamura2020",
            prompt="Does the article report on recognition events?",
        ),
        fields("searched", "observation", "https://doi.org/10.5555/nakamura2020", ""),
        id="web fetch",
    ),
    pytest.param(
        bash('git commit -m "Add two findings"'),
        fields("committed", "action", 'git commit -m "Add two findings"', ""),
        id="git commit",
    ),
    pytest.param(
        bash(STORY_COMMIT),
        fields("committed", "action", STORY_COMMIT, ""),
        id="git add then git commit",
    ),
    pytest.param(
        bash('python3 -m pytest -q && git commit -m "Pass the tests"'),
        fields("committed", "action", 'python3 -m pytest -q && git commit -m "Pass the tests"', ""),
        id="a commit after a test is a commit",
    ),
    pytest.param(
        bash("python3 -m pytest -q audit_layer/tests"),
        fields("verified", "observation", "python3 -m pytest -q audit_layer/tests", ""),
        id="pytest",
    ),
    pytest.param(
        bash("pytest -q"),
        fields("verified", "observation", "pytest -q", ""),
        id="pytest alone",
    ),
    pytest.param(
        bash("python3 vg.py check graphs/citations.yaml"),
        fields("verified", "observation", "python3 vg.py check graphs/citations.yaml", ""),
        id="vg.py check",
    ),
    pytest.param(
        bash("python3 vg.py verify --run runs/demo_citations"),
        fields("verified", "observation", "python3 vg.py verify --run runs/demo_citations", ""),
        id="vg.py verify",
    ),
    pytest.param(
        bash(
            "python3 vg.py score --run runs/demo_citations"
            " --truth fixtures/citations/seeded/truth.yaml"
        ),
        fields(
            "verified",
            "observation",
            "python3 vg.py score --run runs/demo_citations"
            " --truth fixtures/citations/seeded/truth.yaml",
            "",
        ),
        id="vg.py score",
    ),
    pytest.param(
        bash(STORY_CHECK),
        fields("verified", "observation", STORY_CHECK, ""),
        id="ospipe check",
    ),
    pytest.param(
        bash(
            "VG_OFFLINE=1 python3 vg.py run graphs/citations.yaml --run runs/demo_citations"
            " --inputs fixtures/citations/seeded"
        ),
        fields(
            "ran",
            "action",
            "VG_OFFLINE=1 python3 vg.py run graphs/citations.yaml --run runs/demo_citations"
            " --inputs fixtures/citations/seeded",
            "",
        ),
        id="vg.py run is not a check",
    ),
    pytest.param(
        bash("python3 -m ospipe build --manuscript manuscript.md --manifest numbers.yml"),
        fields(
            "ran",
            "action",
            "python3 -m ospipe build --manuscript manuscript.md --manifest numbers.yml",
            "",
        ),
        id="ospipe build is not a check",
    ),
    pytest.param(
        bash("git log --oneline -n 5"),
        fields("ran", "action", "git log --oneline -n 5", ""),
        id="other git command",
    ),
    pytest.param(
        bash("ls -la"),
        fields("ran", "action", "ls -la", ""),
        id="other command",
    ),
    pytest.param(
        call("TodoWrite", todos=[{"content": "Add two findings", "status": "pending"}]),
        fields("ran", "action", "TodoWrite", ""),
        id="other tool",
    ),
    pytest.param(
        call("NotebookEdit", notebook_path=CWD + "/analysis.ipynb", new_source="print(1)"),
        fields("ran", "action", "NotebookEdit", ""),
        id="other tool with a file",
    ),
    pytest.param(
        call("mcp__kb__search", query="volunteer retention"),
        fields("ran", "action", "mcp__kb__search", ""),
        id="other tool from a server",
    ),
]


@pytest.mark.parametrize("tool_call, expected", MAPPINGS)
def test_each_tool_call_gets_its_verb_kind_object_and_role(tool_call, expected):
    assert tag(tool_call, CWD) == expected


@pytest.mark.parametrize("tool_call, expected", MAPPINGS)
def test_each_tagged_call_makes_a_valid_event(tool_call, expected):
    event = dict(
        tag(tool_call, CWD),
        harness="claude_code",
        harness_session_id="5f3c0413-2a7d-4b9e-8c61-a0d4e7b2c913",
        source_id=tool_call.record_id,
        rationale="",
    )
    assert validate(event) == []


@pytest.mark.parametrize(
    "name, given, expected",
    [
        ("Write", "notes/sources.md", CWD + "/notes/sources.md"),
        ("Edit", "manuscript.md", MANUSCRIPT),
        ("Read", "./author_draft.md", CWD + "/author_draft.md"),
        ("Read", "../shared/refs.bib", "/home/scholar/shared/refs.bib"),
    ],
)
def test_a_relative_path_is_resolved_against_the_working_folder(name, given, expected):
    assert tag(call(name, file_path=given), CWD)["object"] == expected
    # The same call made from a folder with another parent names another file.
    elsewhere = "/srv/lab/project"
    assert tag(call(name, file_path=given), elsewhere)["object"] != expected


@pytest.mark.parametrize(
    "command",
    [
        'echo "a legit commit"',
        "cat notes/pytest_tips.md",
        "python3 figures/make_svg.py check",
        "ls ospipe checkpoints",
    ],
)
def test_a_named_word_inside_a_longer_word_does_not_count(command):
    assert tag(bash(command), CWD) == fields("ran", "action", command, "")


def test_an_absolute_path_is_kept_whatever_the_working_folder():
    other = "/home/scholar/other_project/notes.md"
    assert tag(call("Read", file_path=other), CWD)["object"] == other


@pytest.mark.parametrize(
    "tool_call",
    [
        call("Write", content="Text with no file path"),
        call("Edit", file_path="", old_string="a", new_string="b"),
        call("Read", file_path=None),
        call("Grep", path=CWD),
        call("Glob", pattern="   "),
        call("WebSearch", query=3),
        call("WebFetch", prompt="A question with no address"),
        call("Bash", description="A command with no command"),
        bash("   "),
        ToolCall(record_id="toolu_test_01", name="Read", input="manuscript.md", time=None),
    ],
    ids=[
        "Write without a path",
        "Edit with an empty path",
        "Read with no path",
        "Grep without a pattern",
        "Glob with a blank pattern",
        "web search with a number",
        "web fetch without an address",
        "Bash without a command",
        "Bash with a blank command",
        "input that is not a mapping",
    ],
)
def test_a_call_without_what_its_rule_reads_is_tagged_as_any_other_tool(tool_call):
    assert tag(tool_call, CWD) == fields("ran", "action", tool_call.name, "")


def test_tag_leaves_the_tool_call_unchanged():
    tool_call = call("Edit", file_path="manuscript.md", old_string="a", new_string="b")
    before = copy.deepcopy(tool_call)
    tag(tool_call, CWD)
    assert tool_call == before


@pytest.fixture
def story(tmp_path):
    """The story session read through the adapter, and the folder it ran in."""
    project = tmp_path / "project"
    text = STORY_SESSION.read_text(encoding="utf-8")
    path = tmp_path / "story_session.jsonl"
    path.write_bytes(text.replace(TOKEN, json.dumps(str(project))[1:-1]).encode("utf-8"))
    return read_session(path), project


def test_the_story_sessions_events(story):
    session, project = story
    manuscript = str(project / "manuscript.md")
    notes = str(project / "source_notes.md")
    assert [tag(tool_call, session.cwd) for tool_call in session.tool_calls] == [
        fields("searched", "observation", manuscript, "read"),
        fields("edited", "action", manuscript, "edited"),
        fields("edited", "action", manuscript, "edited"),
        fields("wrote", "action", notes, "produced"),
        fields("verified", "observation", STORY_CHECK, ""),
        fields("committed", "action", STORY_COMMIT, ""),
    ]


def test_the_story_sessions_events_are_valid_events(story):
    session, _ = story
    for tool_call in session.tool_calls:
        event = dict(
            tag(tool_call, session.cwd),
            harness="claude_code",
            harness_session_id=session.session_id,
            source_id=tool_call.record_id,
            rationale="",
        )
        assert validate(event) == []


def test_the_story_sessions_tool_list(story):
    session, _ = story
    assert session_tags(session.tool_calls) == ["Read", "Edit", "Write", "Bash"]


def test_each_tool_is_listed_once_in_the_order_first_used():
    tool_calls = [
        bash("ls -la"),
        call("Read", file_path=MANUSCRIPT),
        bash("git status"),
        call("Edit", file_path=MANUSCRIPT, old_string="a", new_string="b"),
        call("Read", file_path=NOTES),
    ]
    assert session_tags(tool_calls) == ["Bash", "Read", "Edit"]


def test_a_session_with_no_tool_calls_used_no_tools():
    assert session_tags([]) == []
