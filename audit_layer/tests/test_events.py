"""Tests for the one event schema (plan Step 3, appendix A2.4 "Capture", Tables A3 and A4).

The valid events are the test story's Claude Code tool calls written as events
by hand, with the folder token {{PROJECT}} replaced by a temporary folder.
Nothing here calls a model or the network. Run from the repository root with
python3 -m pytest -q audit_layer/tests.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from audit_layer.events import FIELDS, validate  # noqa: E402

STORY_SESSION = (
    ROOT / "examples" / "test_story" / "sessions" / "claude_code" / "story_session.jsonl"
)
TOKEN = "{{PROJECT}}"

# The schema's fields as plan Step 3 names them, in its order.
SCHEMA = (
    "harness",
    "harness_session_id",
    "source_id",
    "verb",
    "kind",
    "object",
    "rationale",
    "role",
)
VERBS = ("wrote", "edited", "ran", "searched", "verified", "committed")  # Table A4
KINDS = ("action", "decision", "observation", "blocker")  # Table A3
ROLES = ("produced", "edited", "read", "cited")  # Table A4
# Every field but the rationale and the role must hold text.
REQUIRED = ("harness", "harness_session_id", "source_id", "verb", "kind", "object")

# The verb, kind, and role of each of the story session's six tool calls,
# written by hand. A read takes the verb searched (plan choice 3).
BY_HAND = [
    ("searched", "observation", "read"),  # Read of manuscript.md
    ("edited", "action", "edited"),  # Edit adding dumont2014
    ("edited", "action", "edited"),  # Edit adding nakamura2020
    ("wrote", "action", "produced"),  # Write of source_notes.md
    ("verified", "observation", ""),  # Bash running the manuscript check
    ("committed", "action", ""),  # Bash running git commit
]


def story_events(project):
    """The story session's tool calls as events, in order."""
    lines = STORY_SESSION.read_text(encoding="utf-8").split("\n")
    records = [json.loads(line) for line in lines if line.strip()]
    uses = []
    for record in records:
        content = (record.get("message") or {}).get("content")
        for part in content if isinstance(content, list) else []:
            if part.get("type") == "tool_use":
                uses.append(part)
    assert len(uses) == len(BY_HAND)
    events = []
    for use, (verb, kind, role) in zip(uses, BY_HAND):
        target = use["input"].get("file_path") or use["input"]["command"]
        events.append(
            {
                "harness": "claude_code",
                "harness_session_id": records[0]["sessionId"],
                "source_id": use["id"],
                "verb": verb,
                "kind": kind,
                "object": target.replace(TOKEN, str(project)),
                "rationale": "",
                "role": role,
            }
        )
    return events


@pytest.fixture
def events(tmp_path):
    return story_events(tmp_path / "project")


@pytest.fixture
def edit(events):
    """The event for the story's first Edit, the one that adds dumont2014."""
    return dict(events[1])


def named(problems):
    """The field each problem names, which is the problem's first word."""
    return [problem.split(" ", 1)[0] for problem in problems]


def test_the_schema_is_one_field_list():
    assert tuple(FIELDS) == SCHEMA


def test_valid_events_pass(events):
    assert len(events) == 6
    assert [validate(event) for event in events] == [[] for _ in events]


@pytest.mark.parametrize(
    "field, value",
    [("verb", verb) for verb in VERBS]
    + [("kind", kind) for kind in KINDS]
    + [("role", role) for role in ROLES + ("",)]
    + [
        ("rationale", ""),
        ("rationale", "The scholar asked for two findings after the sentence on fit."),
    ],
)
def test_each_value_the_schema_allows_passes(edit, field, value):
    assert validate(dict(edit, **{field: value})) == []


@pytest.mark.parametrize("field", SCHEMA)
def test_a_missing_field_is_named(edit, field):
    del edit[field]
    assert named(validate(edit)) == [field]


@pytest.mark.parametrize("value", [None, 3])
@pytest.mark.parametrize("field", SCHEMA)
def test_a_field_that_is_not_text_is_named(edit, field, value):
    assert named(validate(dict(edit, **{field: value}))) == [field]


@pytest.mark.parametrize("value", ["", "   "])
@pytest.mark.parametrize("field", REQUIRED)
def test_an_empty_field_is_named_unless_it_may_be_empty(edit, field, value):
    assert named(validate(dict(edit, **{field: value}))) == [field]


@pytest.mark.parametrize(
    "field, value",
    [
        ("verb", "deleted"),
        ("verb", "Edited"),
        ("verb", "read"),
        ("kind", "note"),
        ("kind", "Action"),
        ("role", "wrote"),
        ("role", "Read"),
        ("role", "   "),
    ],
)
def test_a_value_off_its_fixed_list_is_named(edit, field, value):
    problems = validate(dict(edit, **{field: value}))
    assert named(problems) == [field]
    assert repr(value) in problems[0]


def test_a_field_outside_the_schema_is_named(edit):
    assert named(validate(dict(edit, title="Adds two findings"))) == ["title"]


def test_each_wrong_field_is_named_once_in_schema_order(edit):
    event = dict(edit, verb="deleted", kind="note", object="", role="wrote", title="x")
    del event["source_id"]
    assert named(validate(event)) == ["source_id", "verb", "kind", "object", "role", "title"]


def test_validate_leaves_the_event_unchanged(edit):
    before = dict(edit)
    validate(edit)
    wrong = dict(edit, verb="deleted")
    validate(wrong)
    assert edit == before
    assert wrong == dict(before, verb="deleted")


@pytest.mark.parametrize("event", [None, "edited", ["harness", "verb"]])
def test_an_event_that_is_not_a_mapping_is_refused(event):
    assert len(validate(event)) == 1
