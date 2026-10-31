"""Tests for the model pass, answers into the store (Track A, Step A10).

Proposal Approach paragraph 5 has the audit layer tag every AI session
transcript and tool call. Appendix Table A4 gives the model pass one AI model
call per session, and its fields stay unreviewed until a person reviews them.
Table A3 stamps each field with the pass that produced it, and Table A5 says
the audit store records the model of the tagging pass. A decision is recorded
by superseding the event the answer names with kind decision and its
rationale (plan choice 10), and the model's name goes in the method (plan
choice 14). The reconciliation drops the excluded-folder guard (item 3), so
no session is withheld, and due skips sessions whose adapter lacks the AI
flag.

The answers are recorded, in fixtures/model_pass/recorded_tags.json, written
by hand for the story session, its subagent conversation, and three faulty
answers keyed to three more synthetic sessions made here from the story. The
sessions are the test story's synthetic Claude Code session and the synthetic
subagent conversation in fixtures/claude_code, with their folder token
{{PROJECT}} replaced with a temporary folder. No real session file is read,
nothing here calls a model or the network, and every test runs with its home
folder inside a temporary folder. Run from the repository root with
python3 -m pytest -q audit_layer/tests.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import audit_layer.capture as capture  # noqa: E402
from audit_layer.capture import capture_session  # noqa: E402
from audit_layer.cli import main  # noqa: E402
from audit_layer.queries import current_session, session_events  # noqa: E402
from audit_layer.store import add_row, current, open_store, supersede  # noqa: E402
from audit_layer.tagging.answers import open_answers  # noqa: E402
from audit_layer.tagging.model_pass import Outcome, due, parse_answer, tag_session  # noqa: E402

SESSIONS = ROOT / "examples" / "test_story" / "sessions" / "claude_code"
STORY_SESSION = SESSIONS / "story_session.jsonl"
SUBAGENT = Path(__file__).parent / "fixtures" / "claude_code" / "subagent.jsonl"
BOOK = Path(__file__).parent / "fixtures" / "model_pass" / "recorded_tags.json"
ANSWERS = f"recorded:{BOOK}"
TOKEN = "{{PROJECT}}"

STORY_ID = "5f3c0413-2a7d-4b9e-8c61-a0d4e7b2c913"
AGENT_ID = "a7c41e2b9d0f3856"
SUBAGENT_ID = STORY_ID + "/agent-" + AGENT_ID

# The three synthetic sessions whose recorded answers are faulty.
MISSING_SUMMARY = "c2a1e5f0-7b3d-4e8a-9c16-d4f0b8a2e357"
UNKNOWN_ORDINAL = "e8b4d2a6-1f7c-4a9e-b3d5-62c0f9e1a748"
TWO_SENTENCES = "a3f7c1d9-5e2b-4c8d-8a41-f6b0e2d7c935"
FAULTY = (MISSING_SUMMARY, UNKNOWN_ORDINAL, TWO_SENTENCES)

DERIVED = ("title", "gist", "summary", "keywords")
METHOD = "model_pass 1; model recorded:recorded_tags.json"
TABLES = ("sessions", "events", "transcripts")


def lines_of(source, project, session_id=STORY_ID, calls="toolu_story_"):
    """The session's records as lines, with the folder token replaced by project.

    Another session id and tool call prefix make a session of its own from the
    story, whose events have ids of their own.
    """
    text = source.read_text(encoding="utf-8")
    text = text.replace(TOKEN, json.dumps(str(project))[1:-1])
    text = text.replace(STORY_ID, session_id).replace("toolu_story_", calls)
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


def counts(store):
    return {table: len(stored_rows(store.db, table)) for table in TABLES}


def recorded(session_id):
    return json.loads(BOOK.read_text(encoding="utf-8"))[session_id]


@pytest.fixture(autouse=True)
def home_folder(tmp_path, monkeypatch):
    """Each test's own home folder, so nothing reaches the real ~/.audit_layer."""
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
def home(tmp_path):
    return tmp_path / "audit_home"


@pytest.fixture
def audit(home):
    store = open_store(home)
    yield store
    store.db.close()


@pytest.fixture
def folder(tmp_path):
    """The harness folder the sessions are kept in, as Claude Code keeps them."""
    return tmp_path / "root" / "-encoded-project-folder"


@pytest.fixture
def story_only(audit, folder, project, settings):
    """The store once the story and its subagent conversation are captured."""
    main_file = write_session(folder / (STORY_ID + ".jsonl"), lines_of(STORY_SESSION, project))
    write_session(
        folder / STORY_ID / "subagents" / ("agent-" + AGENT_ID + ".jsonl"),
        lines_of(SUBAGENT, project),
    )
    capture_session(audit, "claude_code", main_file, settings)
    return audit


@pytest.fixture
def with_faulty(story_only, folder, project, settings):
    """The store once the three sessions with faulty answers are captured too."""
    for number, session_id in enumerate(FAULTY, start=1):
        lines = lines_of(STORY_SESSION, project, session_id, f"toolu_faulty_{number}_")
        path = write_session(folder / (session_id + ".jsonl"), lines)
        capture_session(story_only, "claude_code", path, settings)
    return story_only


def run_pass(store, answers=ANSWERS):
    source = open_answers(answers)
    return [tag_session(store, row, source) for row in due(store)]


# The story and its subagent are tagged.


def test_the_story_gets_its_four_fields_stamped_with_the_pass(story_only):
    before = current_session(story_only, "claude_code", STORY_ID)
    outcomes = run_pass(story_only)
    assert [(o.session_id, o.status, o.problems) for o in outcomes] == [
        (STORY_ID, "tagged", ()),
        (SUBAGENT_ID, "tagged", ()),
    ]

    row = current_session(story_only, "claude_code", STORY_ID)
    answer = recorded(STORY_ID)
    assert {name: row[name] for name in DERIVED} == {name: answer[name] for name in DERIVED}
    assert row["supersedes"] == before["id"]
    assert (row["session"], row["origin"], row["method"], row["reason"]) == (
        STORY_ID,
        "model pass",
        METHOD,
        "tagging",
    )
    # The capture's fields carry over unchanged.
    for name in ("harness", "harness_session_id", "project", "started_at", "ended_at", "tools"):
        assert row[name] == before[name]
    # The earlier row stays in the table as it was written.
    kept = [r for r in stored_rows(story_only.db, "sessions") if r["id"] == before["id"]]
    assert len(kept) == 1
    assert kept[0]["title"] is None


def test_the_subagent_gets_its_own_four_fields(story_only):
    run_pass(story_only)
    row = current_session(story_only, "claude_code", SUBAGENT_ID)
    answer = recorded(SUBAGENT_ID)
    assert {name: row[name] for name in DERIVED} == {name: answer[name] for name in DERIVED}
    assert (row["session"], row["origin"], row["method"]) == (SUBAGENT_ID, "model pass", METHOD)


def test_the_named_event_becomes_a_decision_and_every_other_event_is_unchanged(story_only):
    story = current_session(story_only, "claude_code", STORY_ID)
    before = session_events(story_only, story)
    agent_before = session_events(
        story_only, current_session(story_only, "claude_code", SUBAGENT_ID)
    )
    run_pass(story_only)
    after = session_events(story_only, current_session(story_only, "claude_code", STORY_ID))

    assert [e["ordinal"] for e in after] == [1, 2, 3, 4, 5, 6]
    decision = after[1]
    first_edit = before[1]
    assert first_edit["id"] == "toolu_story_02_edit"
    assert decision["supersedes"] == first_edit["id"]
    assert decision["kind"] == "decision"
    assert decision["rationale"] == recorded(STORY_ID)["decisions"][0]["rationale"]
    for name in ("session_row_id", "ordinal", "verb", "object", "role"):
        assert decision[name] == first_edit[name]
    assert (decision["session"], decision["origin"], decision["method"], decision["reason"]) == (
        STORY_ID,
        "model pass",
        METHOD,
        "tagging",
    )
    assert [e for i, e in enumerate(after) if i != 1] == [
        e for i, e in enumerate(before) if i != 1
    ]
    # The subagent's answer names no decision, so its events are unchanged.
    assert (
        session_events(story_only, current_session(story_only, "claude_code", SUBAGENT_ID))
        == agent_before
    )
    # The first Edit stays in the table as it was written.
    kept = [r for r in stored_rows(story_only.db, "events") if r["id"] == "toolu_story_02_edit"]
    assert kept[0]["kind"] == "action" and kept[0]["rationale"] == ""


# Faulty answers write nothing.


def test_each_faulty_answer_writes_nothing_and_is_listed_with_its_problems(with_faulty):
    before = {
        session_id: (
            current_session(with_faulty, "claude_code", session_id),
            session_events(
                with_faulty, current_session(with_faulty, "claude_code", session_id)
            ),
        )
        for session_id in FAULTY
    }
    outcomes = {o.session_id: o for o in run_pass(with_faulty)}
    assert [outcomes[s].status for s in (STORY_ID, SUBAGENT_ID)] == ["tagged", "tagged"]
    for session_id in FAULTY:
        assert outcomes[session_id].status == "failed"

    assert outcomes[MISSING_SUMMARY].problems == ("summary is missing",)
    assert outcomes[UNKNOWN_ORDINAL].problems == (
        "decision 1 names ordinal 9, which the action log lacks",
    )
    assert outcomes[TWO_SENTENCES].problems == ("decision 1 has a rationale that is not one sentence",)

    for session_id, (row, events) in before.items():
        assert current_session(with_faulty, "claude_code", session_id) == row
        assert session_events(with_faulty, row) == events
        written = [
            r
            for table in ("sessions", "events")
            for r in stored_rows(with_faulty.db, table)
            if r["session"] == session_id and r["origin"] == "model pass"
        ]
        assert written == []
    # The faulty sessions stay due.
    assert [row["harness_session_id"] for row in due(with_faulty)] == list(FAULTY)


def test_a_second_run_finds_nothing_due(story_only):
    run_pass(story_only)
    held = counts(story_only)
    assert due(story_only) == []
    assert run_pass(story_only) == []
    assert counts(story_only) == held


def test_after_the_story_grows_and_is_captured_again_it_is_due_again(
    tmp_path, audit, project, settings
):
    path = tmp_path / "story_session.jsonl"
    lines = lines_of(STORY_SESSION, project)
    write_session(path, lines[:8])
    capture_session(audit, "claude_code", path, settings)
    assert [o.status for o in run_pass(audit)] == ["tagged"]
    assert due(audit) == []

    # Capturing the same file again keeps the tags.
    capture_session(audit, "claude_code", path, settings)
    assert due(audit) == []

    write_session(path, lines)
    capture_session(audit, "claude_code", path, settings)
    assert [row["harness_session_id"] for row in due(audit)] == [STORY_ID]
    # The decision the pass recorded stays current.
    events = session_events(audit, current_session(audit, "claude_code", STORY_ID))
    assert events[1]["kind"] == "decision"
    assert [o.status for o in run_pass(audit)] == ["tagged"]
    assert current_session(audit, "claude_code", STORY_ID)["title"] == recorded(STORY_ID)["title"]


def test_a_session_whose_adapter_lacks_the_ai_flag_is_never_asked(story_only, monkeypatch):
    class NotAI:
        NAME = "not_ai"
        AI = False

    monkeypatch.setitem(capture.ADAPTERS, "not_ai", NotAI)
    provenance = {
        "session": "w1",
        "origin": "not_ai adapter",
        "method": "by hand",
        "reason": "capture",
    }
    add_row(story_only, "sessions", {"harness": "not_ai", "harness_session_id": "w1"}, provenance)
    # The book has no answer for w1, and no error comes.
    outcomes = run_pass(story_only)
    assert [o.session_id for o in outcomes] == [STORY_ID, SUBAGENT_ID]


def test_a_session_the_book_has_no_answer_for_fails_and_writes_nothing(story_only, tmp_path):
    book = tmp_path / "partial.json"
    book.write_text(json.dumps({STORY_ID: recorded(STORY_ID)}), encoding="utf-8")
    held = counts(story_only)
    outcomes = run_pass(story_only, f"recorded:{book}")
    assert [(o.session_id, o.status) for o in outcomes] == [
        (STORY_ID, "tagged"),
        (SUBAGENT_ID, "failed"),
    ]
    assert "no answer for " + SUBAGENT_ID in outcomes[1].problems[0]
    # Only the story's session row and its one decision were written.
    assert counts(story_only) == dict(held, sessions=held["sessions"] + 1, events=held["events"] + 1)


def test_tag_session_asks_once_with_the_session_id_as_the_key(story_only):
    asked = []

    class Source:
        def ask(self, key, prompt):
            asked.append((key, prompt))
            return json.dumps(recorded(STORY_ID)), "counted"

    row = current_session(story_only, "claude_code", STORY_ID)
    outcome = tag_session(story_only, row, Source())
    assert outcome == Outcome(STORY_ID, "tagged", ())
    assert [key for key, _ in asked] == [STORY_ID]
    assert "1 searched observation" in asked[0][1]
    assert current_session(story_only, "claude_code", STORY_ID)["method"] == (
        "model_pass 1; model counted"
    )


# A sweep that changes a session's rows while the pass waits for its answer.

SWEEP = {
    "session": STORY_ID,
    "origin": "claude_code adapter",
    "method": "sweep",
    "reason": "capture",
}


class SweepsWhileAsked:
    """An answer source that lets a sweep supersede a row of the story before it answers."""

    def __init__(self, store, table, row_id):
        self.store, self.table, self.row_id = store, table, row_id
        self.source = open_answers(ANSWERS)

    def ask(self, key, prompt):
        if key == STORY_ID:
            changes = {"ended_at": "2026-10-21T15:00:00.000Z"} if self.table == "sessions" else {}
            supersede(self.store, self.table, self.row_id, changes, SWEEP)
        return self.source.ask(key, prompt)


def model_pass_rows(store, session_id):
    return [
        r
        for table in ("sessions", "events")
        for r in stored_rows(store.db, table)
        if r["session"] == session_id and r["origin"] == "model pass"
    ]


def test_a_session_row_superseded_while_the_pass_waits_fails_writes_nothing_and_the_run_goes_on(
    story_only,
):
    story = current_session(story_only, "claude_code", STORY_ID)
    source = SweepsWhileAsked(story_only, "sessions", story["id"])
    held = counts(story_only)
    outcomes = [tag_session(story_only, row, source) for row in due(story_only)]

    assert [(o.session_id, o.status) for o in outcomes] == [
        (STORY_ID, "failed"),
        (SUBAGENT_ID, "tagged"),
    ]
    (problem,) = outcomes[0].problems
    assert problem.startswith("its rows changed while it was tagged, so nothing was written")
    assert "already superseded" in problem
    assert model_pass_rows(story_only, STORY_ID) == []
    # Only the sweep's session row and the subagent's tagging were written.
    assert counts(story_only) == dict(held, sessions=held["sessions"] + 2)
    # The sweep's row is due, so the next run tags it.
    assert [row["harness_session_id"] for row in due(story_only)] == [STORY_ID]
    assert [o.status for o in run_pass(story_only)] == ["tagged"]


def test_an_event_superseded_while_the_pass_waits_leaves_the_session_row_untagged_too(
    story_only,
):
    story = current_session(story_only, "claude_code", STORY_ID)
    source = SweepsWhileAsked(story_only, "events", "toolu_story_02_edit")
    held = counts(story_only)
    outcome = tag_session(story_only, story, source)

    assert outcome.status == "failed"
    assert "already superseded" in outcome.problems[0]
    # The session row and its decision are written together or not at all.
    assert model_pass_rows(story_only, STORY_ID) == []
    assert current_session(story_only, "claude_code", STORY_ID) == story
    assert counts(story_only) == dict(held, events=held["events"] + 1)
    assert [row["harness_session_id"] for row in due(story_only)][0] == STORY_ID


# Reading an answer.


def clean_answer(**changes):
    answer = {
        "title": "A title",
        "gist": "A gist on one line.",
        "summary": "A summary in one paragraph.",
        "keywords": ["one", "two", "three"],
        "decisions": [{"ordinal": 2, "rationale": "It was asked for."}],
    }
    answer.update(changes)
    return answer


def problems_of(answer, ordinals=(1, 2, 3)):
    text = answer if isinstance(answer, str) else json.dumps(answer)
    return parse_answer(text, ordinals)[1]


def test_a_clean_answer_gives_its_tags():
    tags, problems = parse_answer(json.dumps(clean_answer()), [1, 2, 3])
    assert problems == ()
    assert tags == {
        "title": "A title",
        "gist": "A gist on one line.",
        "summary": "A summary in one paragraph.",
        "keywords": ["one", "two", "three"],
        "decisions": [(2, "It was asked for.")],
    }


def test_an_answer_is_read_from_inside_a_code_fence_and_after_a_think_block():
    text = "<think>\nSome reasoning {not json}.\n</think>\nHere it is.\n```json\n"
    text += json.dumps(clean_answer()) + "\n```\n"
    tags, problems = parse_answer(text, [1, 2, 3])
    assert problems == ()
    assert tags["title"] == "A title"
    plain_fence = "```\n" + json.dumps(clean_answer()) + "\n```"
    assert parse_answer(plain_fence, [1, 2, 3])[1] == ()


def test_an_answer_is_read_after_a_lead_in_line_with_no_code_fence():
    text = "Here it is, with {braces} in the lead-in.\n" + json.dumps(clean_answer())
    tags, problems = parse_answer(text, [1, 2, 3])
    assert problems == ()
    assert tags["title"] == "A title"
    after = json.dumps(clean_answer()) + "\nThat is the answer."
    assert parse_answer(after, [1, 2, 3])[1] == ()
    # A list before the object is skipped, and the first object is the one read.
    first = "[1, 2] " + json.dumps(clean_answer(title="First")) + json.dumps(clean_answer())
    assert parse_answer(first, [1, 2, 3])[0]["title"] == "First"


@pytest.mark.parametrize(
    "rationale",
    [
        "The scholar cited Dr. Smith for it.",
        "Mr. Jones and Prof. Lee asked for it.",
        "It follows J. Smith and the U.S. Census.",
        'It was what the scholar asked "for."',
        "It was the change asked for (in the second round.)",
        "It was the change \u201casked for.\u201d",
    ],
)
def test_a_single_sentence_with_a_title_initials_or_a_closing_quote_is_one_sentence(rationale):
    answer = clean_answer(decisions=[{"ordinal": 2, "rationale": rationale}])
    assert problems_of(answer) == ()


@pytest.mark.parametrize(
    "rationale",
    [
        "It ran. Then it stopped.",
        'It was "asked for." Then it ran.',
        "It ran (twice.) Then it stopped.",
        "It was asked for",
        'It was "asked for"',
    ],
)
def test_two_sentences_or_no_end_mark_is_still_refused(rationale):
    answer = clean_answer(decisions=[{"ordinal": 2, "rationale": rationale}])
    assert problems_of(answer) == ("decision 1 has a rationale that is not one sentence",)


def test_an_answer_that_is_not_a_json_object_is_refused():
    assert problems_of("no JSON here") == ("the answer is not a JSON object",)
    assert problems_of("[1, 2]") == ("the answer is not a JSON object",)
    assert parse_answer("no JSON here", [1])[0] is None


def test_each_missing_key_and_each_extra_key_is_a_problem():
    answer = clean_answer(blocker="x")
    del answer["title"]
    del answer["keywords"]
    assert problems_of(answer) == (
        "title is missing",
        "keywords is missing",
        "blocker is not one of the five keys",
    )


@pytest.mark.parametrize(
    "changes, problem",
    [
        ({"title": ""}, "title is empty"),
        ({"title": 7}, "title must be text"),
        ({"title": "x" * 81}, "title is longer than 80 characters"),
        ({"gist": "x" * 201}, "gist is longer than 200 characters"),
        ({"gist": "one line\nand another"}, "gist is not one line"),
        ({"summary": "x" * 1201}, "summary is longer than 1,200 characters"),
        ({"summary": "One paragraph.\n\nAnd another."}, "summary is not one paragraph"),
        ({"keywords": ["one", "two"]}, "keywords must hold 3 to 10 terms"),
        ({"keywords": [str(n) for n in range(11)]}, "keywords must hold 3 to 10 terms"),
        ({"keywords": "one, two, three"}, "keywords must be a list of terms"),
        ({"keywords": ["one", "", "three"]}, "keywords must be a list of terms"),
        ({"decisions": {"ordinal": 2}}, "decisions must be a list"),
        ({"decisions": ["x"]}, "decision 1 must be an object with an ordinal and a rationale"),
        (
            {"decisions": [{"ordinal": 2}]},
            "decision 1 must be an object with an ordinal and a rationale",
        ),
        (
            {"decisions": [{"ordinal": "2", "rationale": "It was asked for."}]},
            "decision 1 has an ordinal that is not a whole number",
        ),
        (
            {"decisions": [{"ordinal": True, "rationale": "It was asked for."}]},
            "decision 1 has an ordinal that is not a whole number",
        ),
        (
            {"decisions": [{"ordinal": 4, "rationale": "It was asked for."}]},
            "decision 1 names ordinal 4, which the action log lacks",
        ),
        (
            {
                "decisions": [
                    {"ordinal": 2, "rationale": "It was asked for."},
                    {"ordinal": 2, "rationale": "It was asked for again."},
                ]
            },
            "decision 2 names ordinal 2, which an earlier decision names",
        ),
        (
            {"decisions": [{"ordinal": 2, "rationale": "It was asked for"}]},
            "decision 1 has a rationale that is not one sentence",
        ),
        (
            {"decisions": [{"ordinal": 2, "rationale": "It was asked for. So it was done."}]},
            "decision 1 has a rationale that is not one sentence",
        ),
        (
            {"decisions": [{"ordinal": 2, "rationale": "Was it asked for? Yes."}]},
            "decision 1 has a rationale that is not one sentence",
        ),
        (
            {"decisions": [{"ordinal": 2, "rationale": ""}]},
            "decision 1 has a rationale that is not one sentence",
        ),
    ],
)
def test_each_limit_is_checked(changes, problem):
    assert problems_of(clean_answer(**changes)) == (problem,)


def test_limits_at_their_edge_are_allowed():
    answer = clean_answer(
        title="x" * 80,
        gist="x" * 200,
        summary="x" * 1200,
        keywords=[str(n) for n in range(10)],
        decisions=[
            {"ordinal": 1, "rationale": "The scholar asked, e.g. in the first message, for it!"},
            {"ordinal": 3, "rationale": "Was it what the scholar asked for?"},
        ],
    )
    assert problems_of(answer) == ()
    assert problems_of(clean_answer(decisions=[])) == ()


# The tag command.


def run_tag(home, *extra):
    return main(["tag", "--home", str(home), "--answers", ANSWERS, *extra])


def test_the_tag_command_lists_tagged_and_failed_sessions_and_exits_1(
    with_faulty, home, tmp_path, capsys
):
    assert run_tag(home) == 1
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert f"tagged {STORY_ID}" in lines
    assert f"tagged {SUBAGENT_ID}" in lines
    for session_id in FAULTY:
        assert f"failed {session_id}" in lines
    assert "  summary is missing" in lines
    assert "  decision 1 names ordinal 9, which the action log lacks" in lines
    assert "  decision 1 has a rationale that is not one sentence" in lines
    assert lines[-1] == "tagged 2 sessions, 3 failed"
    # Output names sessions by id and never a session file's path.
    assert str(tmp_path) not in out


def test_the_tag_command_exits_0_when_none_failed(story_only, home, capsys):
    assert run_tag(home) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines == [f"tagged {STORY_ID}", f"tagged {SUBAGENT_ID}", "tagged 2 sessions, 0 failed"]
    assert run_tag(home) == 0
    assert capsys.readouterr().out.splitlines() == ["tagged 0 sessions, 0 failed"]


def test_the_tag_command_runs_only_the_named_sessions(with_faulty, home, capsys):
    assert run_tag(home, "--session", SUBAGENT_ID, "--session", STORY_ID) == 0
    assert capsys.readouterr().out.splitlines() == [
        f"tagged {SUBAGENT_ID}",
        f"tagged {STORY_ID}",
        "tagged 2 sessions, 0 failed",
    ]
    assert [row["harness_session_id"] for row in due(with_faulty)] == list(FAULTY)


def test_the_tag_command_tags_a_session_named_twice_once(story_only, home, capsys):
    assert run_tag(home, "--session", STORY_ID, "--session", STORY_ID) == 0
    assert capsys.readouterr().out.splitlines() == [
        f"tagged {STORY_ID}",
        "tagged 1 session, 0 failed",
    ]
    assert len(model_pass_rows(story_only, STORY_ID)) == 2


def test_the_tag_command_fails_a_named_session_the_store_lacks(story_only, home, capsys):
    assert run_tag(home, "--session", "no-such-session") == 1
    assert capsys.readouterr().out.splitlines() == [
        "failed no-such-session",
        "  there is no session no-such-session in the audit store",
        "tagged 0 sessions, 1 failed",
    ]


def test_the_tag_command_fails_a_named_session_it_cannot_tell_apart_or_that_no_ai_kept(
    story_only, home, capsys, monkeypatch
):
    class NotAI:
        NAME = "not_ai"
        AI = False

    monkeypatch.setitem(capture.ADAPTERS, "not_ai", NotAI)
    provenance = {"session": "x", "origin": "by hand", "method": "by hand", "reason": "test"}
    add_row(story_only, "sessions", {"harness": "not_ai", "harness_session_id": "w1"}, provenance)
    add_row(
        story_only, "sessions", {"harness": "forgecode", "harness_session_id": STORY_ID}, provenance
    )
    held = counts(story_only)
    assert run_tag(home, "--session", "w1", "--session", STORY_ID, "--session", SUBAGENT_ID) == 1
    assert capsys.readouterr().out.splitlines() == [
        "failed w1",
        "  session w1 was not kept by an AI harness, so the pass does not tag it",
        f"failed {STORY_ID}",
        f"  two harnesses have a session {STORY_ID}, so it cannot be told apart",
        f"tagged {SUBAGENT_ID}",
        "tagged 1 session, 2 failed",
    ]
    assert counts(story_only) == dict(held, sessions=held["sessions"] + 1)


def test_the_tag_command_refuses_a_limit_below_1(story_only, home, capsys):
    held = counts(story_only)
    for given in ("0", "-1", "two"):
        with pytest.raises(SystemExit):
            run_tag(home, "--limit", given)
        assert "at least 1" in capsys.readouterr().err
    assert counts(story_only) == held


def test_the_tag_command_takes_at_most_the_limit(with_faulty, home, capsys):
    assert run_tag(home, "--limit", "1") == 0
    assert capsys.readouterr().out.splitlines() == [
        f"tagged {STORY_ID}",
        "tagged 1 session, 0 failed",
    ]


def test_the_tag_command_refuses_an_unknown_kind_and_a_missing_store(
    story_only, home, tmp_path, capsys
):
    held = counts(story_only)
    assert main(["tag", "--home", str(home), "--answers", "service:x"]) == 1
    assert "there is no answer source of the kind service" in capsys.readouterr().err
    assert counts(story_only) == held

    empty = tmp_path / "no_home"
    assert main(["tag", "--home", str(empty), "--answers", ANSWERS]) == 1
    assert "no audit store" in capsys.readouterr().err
    assert not empty.exists()
