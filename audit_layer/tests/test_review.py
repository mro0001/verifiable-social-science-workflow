"""Tests for the review command (Track A, Step A11).

Appendix Table A4 and the sentence after it say the model pass's fields stay
marked unreviewed until a person reviews them, and the sentence after Table
A3 says records are never overwritten. A row is unreviewed while its current
version's origin is model pass, and a review writes superseding rows with
origin person <name> and method review (plan choice 12).

The sessions are the test story's synthetic Claude Code session and the
synthetic subagent conversation in fixtures/claude_code, with their folder
token {{PROJECT}} replaced with a temporary folder, tagged from the recorded
answers in fixtures/model_pass/recorded_tags.json. No real session file is
read, nothing here calls a model or the network, and every test runs with its
home folder inside a temporary folder. Run from the repository root with
python3 -m pytest -q audit_layer/tests.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from audit_layer.capture import capture_session  # noqa: E402
from audit_layer.cli import main  # noqa: E402
from audit_layer.queries import current_session, session_events  # noqa: E402
from audit_layer.store import add_row, current, open_store  # noqa: E402
from audit_layer.tagging.answers import open_answers  # noqa: E402
from audit_layer.tagging.model_pass import due, tag_session  # noqa: E402
from audit_layer.tagging.review import ReviewError, review, unreviewed  # noqa: E402

SESSIONS = ROOT / "examples" / "test_story" / "sessions" / "claude_code"
STORY_SESSION = SESSIONS / "story_session.jsonl"
SUBAGENT = Path(__file__).parent / "fixtures" / "claude_code" / "subagent.jsonl"
BOOK = Path(__file__).parent / "fixtures" / "model_pass" / "recorded_tags.json"
ANSWERS = f"recorded:{BOOK}"
TOKEN = "{{PROJECT}}"

STORY_ID = "5f3c0413-2a7d-4b9e-8c61-a0d4e7b2c913"
AGENT_ID = "a7c41e2b9d0f3856"
SUBAGENT_ID = STORY_ID + "/agent-" + AGENT_ID

DERIVED = ("title", "gist", "summary", "keywords")
TABLES = ("sessions", "events", "transcripts")


def lines_of(source, project):
    text = source.read_text(encoding="utf-8")
    text = text.replace(TOKEN, json.dumps(str(project))[1:-1])
    return [line for line in text.split("\n") if line]


def write_session(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes("".join(line + "\n" for line in lines).encode("utf-8"))
    return path


def stored_rows(db, table):
    cursor = db.execute(f"SELECT * FROM {table} ORDER BY rowid")
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def all_rows(store):
    return {table: stored_rows(store.db, table) for table in TABLES}


def recorded(session_id):
    return json.loads(BOOK.read_text(encoding="utf-8"))[session_id]


def run_pass(store):
    source = open_answers(ANSWERS)
    return [tag_session(store, row, source) for row in due(store)]


def story(store):
    return current_session(store, "claude_code", STORY_ID)


def story_events(store):
    return session_events(store, story(store))


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
    return {"excluded_folders": [str(project / "excluded_folder")]}


@pytest.fixture
def home(tmp_path):
    return tmp_path / "audit_home"


@pytest.fixture
def audit(home):
    store = open_store(home)
    yield store
    store.db.close()


@pytest.fixture
def captured(audit, tmp_path, project, settings):
    """The store once the story and its subagent conversation are captured, not tagged."""
    folder = tmp_path / "root" / "-encoded-project-folder"
    main_file = write_session(folder / (STORY_ID + ".jsonl"), lines_of(STORY_SESSION, project))
    write_session(
        folder / STORY_ID / "subagents" / ("agent-" + AGENT_ID + ".jsonl"),
        lines_of(SUBAGENT, project),
    )
    capture_session(audit, "claude_code", main_file, settings)
    return audit


@pytest.fixture
def tagged(captured):
    """The store once the model pass has tagged the story and its subagent."""
    assert [o.status for o in run_pass(captured)] == ["tagged", "tagged"]
    return captured


# What awaits review.


def test_after_the_model_pass_the_story_and_its_decision_are_listed(tagged):
    pending = unreviewed(tagged)
    assert [p.session["harness_session_id"] for p in pending] == [STORY_ID, SUBAGENT_ID]
    story_pending = pending[0]
    assert story_pending.session["origin"] == "model pass"
    assert story_pending.session["title"] == recorded(STORY_ID)["title"]
    assert [(e["ordinal"], e["kind"], e["rationale"]) for e in story_pending.decisions] == [
        (2, "decision", recorded(STORY_ID)["decisions"][0]["rationale"])
    ]
    # The subagent's answer names no decision.
    assert pending[1].decisions == []


def test_nothing_is_listed_before_the_model_pass(captured):
    assert unreviewed(captured) == []


# A review with no changes.


def test_a_review_with_no_changes_keeps_every_value_and_empties_the_list(tagged):
    before_row = story(tagged)
    before_events = story_events(tagged)
    model_rows = all_rows(tagged)

    outcome = review(tagged, STORY_ID, "scholar", {}, {})
    assert outcome.session_id == STORY_ID
    assert outcome.changed == ()
    assert outcome.rows == 2

    row = story(tagged)
    assert row["supersedes"] == before_row["id"]
    for name in ("harness", "harness_session_id", "project", "started_at", "ended_at", "tools"):
        assert row[name] == before_row[name]
    assert {name: row[name] for name in DERIVED} == {name: before_row[name] for name in DERIVED}
    assert (row["session"], row["origin"], row["method"], row["reason"]) == (
        STORY_ID,
        "person scholar",
        "review",
        "reviewed",
    )

    after_events = story_events(tagged)
    decision = after_events[1]
    assert decision["supersedes"] == before_events[1]["id"]
    assert (decision["kind"], decision["rationale"]) == (
        before_events[1]["kind"],
        before_events[1]["rationale"],
    )
    assert (decision["origin"], decision["method"], decision["reason"], decision["session"]) == (
        "person scholar",
        "review",
        "reviewed",
        STORY_ID,
    )
    # Every other event is as it was.
    assert [e for i, e in enumerate(after_events) if i != 1] == [
        e for i, e in enumerate(before_events) if i != 1
    ]

    review(tagged, SUBAGENT_ID, "scholar", {}, {})
    assert unreviewed(tagged) == []
    # The model's rows stay in the table as they were written.
    after = all_rows(tagged)
    for table in TABLES:
        assert after[table][: len(model_rows[table])] == model_rows[table]
    assert len(after["sessions"]) == len(model_rows["sessions"]) + 2
    assert len(after["events"]) == len(model_rows["events"]) + 1
    # A reviewed session is not due, so the pass does not tag it again.
    assert due(tagged) == []


def test_a_reviewer_name_is_written_without_space_at_its_ends(tagged):
    review(tagged, STORY_ID, "  scholar  ", {}, {})
    assert story(tagged)["origin"] == "person scholar"


# A review with changes.


def test_a_changed_title_changes_only_the_title_with_reason_reviewed_with_changes(tagged):
    before_row = story(tagged)
    before_events = story_events(tagged)
    outcome = review(tagged, STORY_ID, "scholar", {"title": "Two findings on volunteer exit"}, {})
    assert outcome.changed == ("title",)

    row = story(tagged)
    assert row["title"] == "Two findings on volunteer exit"
    for name in ("gist", "summary", "keywords"):
        assert row[name] == before_row[name]
    assert row["reason"] == "reviewed with changes"
    # The decision's rationale did not change, so its row says reviewed.
    decision = story_events(tagged)[1]
    assert decision["rationale"] == before_events[1]["rationale"]
    assert decision["reason"] == "reviewed"


def test_a_value_given_as_it_was_is_not_a_change(tagged):
    title = story(tagged)["title"]
    outcome = review(tagged, STORY_ID, "scholar", {"title": title}, {})
    assert outcome.changed == ()
    assert story(tagged)["reason"] == "reviewed"


def test_keywords_are_replaced_as_a_list(tagged):
    review(tagged, STORY_ID, "scholar", {"keywords": ["volunteer exit", "citations", "Results"]}, {})
    assert story(tagged)["keywords"] == ["volunteer exit", "citations", "Results"]


def test_a_rationale_changes_one_decision_only(tagged):
    before_row = story(tagged)
    text = "The scholar named the sentence on fit as the place for the first finding."
    outcome = review(tagged, STORY_ID, "scholar", {}, {2: text})
    assert outcome.changed == ("rationale 2",)

    decision = story_events(tagged)[1]
    assert decision["rationale"] == text
    assert decision["kind"] == "decision"
    assert decision["reason"] == "reviewed with changes"
    row = story(tagged)
    assert {name: row[name] for name in DERIVED} == {name: before_row[name] for name in DERIVED}
    assert row["reason"] == "reviewed"


# Refusals, each of which writes nothing.


def refused(store, *args):
    held = all_rows(store)
    with pytest.raises(ReviewError) as error:
        review(store, *args)
    assert all_rows(store) == held
    return str(error.value)


def test_an_unknown_session_is_refused(tagged):
    message = refused(tagged, "no-such-session", "scholar", {}, {})
    assert "no session no-such-session" in message


def test_an_id_two_harnesses_share_is_refused(tagged):
    provenance = {"session": STORY_ID, "origin": "by hand", "method": "test", "reason": "test"}
    add_row(tagged, "sessions", {"harness": "forgecode", "harness_session_id": STORY_ID}, provenance)
    message = refused(tagged, STORY_ID, "scholar", {}, {})
    assert "two harnesses" in message


def test_a_session_with_no_model_pass_rows_is_refused(captured):
    message = refused(captured, STORY_ID, "scholar", {}, {})
    assert "nothing from the model pass" in message


def test_a_session_already_reviewed_is_refused(tagged):
    review(tagged, STORY_ID, "scholar", {}, {})
    message = refused(tagged, STORY_ID, "scholar", {}, {})
    assert "nothing from the model pass" in message


def test_an_unknown_field_is_refused(tagged):
    message = refused(tagged, STORY_ID, "scholar", {"project": "elsewhere"}, {})
    assert "project" in message and "title, gist, summary, keywords" in message


@pytest.mark.parametrize(
    "changes",
    [{"title": ["not", "text"]}, {"keywords": "not a list"}, {"keywords": ["fine", 3]}],
)
def test_a_value_of_the_wrong_kind_is_refused(tagged, changes):
    refused(tagged, STORY_ID, "scholar", changes, {})


@pytest.mark.parametrize("ordinal", [1, 9])
def test_an_ordinal_that_is_not_one_of_the_decisions_is_refused(tagged, ordinal):
    message = refused(tagged, STORY_ID, "scholar", {}, {ordinal: "A reason."})
    assert f"ordinal {ordinal}" in message


@pytest.mark.parametrize("name", ["", "   "])
def test_an_empty_name_is_refused(tagged, name):
    message = refused(tagged, STORY_ID, name, {}, {})
    assert "name" in message


# After the story grows.


def test_after_the_story_grows_is_captured_and_is_tagged_again_it_is_listed_again(
    audit, tmp_path, project, settings
):
    path = tmp_path / "story_session.jsonl"
    lines = lines_of(STORY_SESSION, project)
    write_session(path, lines[:8])
    capture_session(audit, "claude_code", path, settings)
    assert [o.status for o in run_pass(audit)] == ["tagged"]
    review(audit, STORY_ID, "scholar", {}, {})
    assert unreviewed(audit) == []

    write_session(path, lines)
    capture_session(audit, "claude_code", path, settings)
    assert [o.status for o in run_pass(audit)] == ["tagged"]
    assert [p.session["harness_session_id"] for p in unreviewed(audit)] == [STORY_ID]
    assert unreviewed(audit)[0].session["origin"] == "model pass"


def test_between_a_grown_capture_and_the_next_pass_only_the_decision_is_reviewed(
    audit, tmp_path, project, settings
):
    path = tmp_path / "story_session.jsonl"
    lines = lines_of(STORY_SESSION, project)
    write_session(path, lines[:8])
    capture_session(audit, "claude_code", path, settings)
    run_pass(audit)
    write_session(path, lines)
    capture_session(audit, "claude_code", path, settings)

    # The grown session's row is capture's, and the decision is still the model's.
    (pending,) = unreviewed(audit)
    assert pending.session["origin"] != "model pass"
    assert [e["ordinal"] for e in pending.decisions] == [2]
    message = refused(audit, STORY_ID, "scholar", {"title": "A title"}, {})
    assert "tag" in message

    held = story(audit)
    outcome = review(audit, STORY_ID, "scholar", {}, {})
    assert outcome.rows == 1
    assert story(audit) == held
    # The session stays due, so the next run tags it.
    assert [row["harness_session_id"] for row in due(audit)] == [STORY_ID]


# The command line.


def run(home, *extra):
    return main(["review", "--home", str(home), *extra])


def test_review_list_prints_each_unreviewed_session(tagged, home, capsys):
    assert run(home, "--list") == 0
    out = capsys.readouterr().out
    answer = recorded(STORY_ID)
    lines = out.splitlines()
    assert lines[0] == STORY_ID
    assert f"  title {answer['title']}" in lines
    assert f"  gist {answer['gist']}" in lines
    assert "  keywords " + ", ".join(answer["keywords"]) in lines
    assert f"  decision 2 {answer['decisions'][0]['rationale']}" in lines
    assert SUBAGENT_ID in lines
    assert lines[-1] == "2 sessions await review"
    # Output names sessions by id and never by a path.
    assert "/" + "root" not in out and ".jsonl" not in out


def test_review_list_counts_one_session(tagged, home, capsys):
    review(tagged, SUBAGENT_ID, "scholar", {}, {})
    assert run(home, "--list") == 0
    assert capsys.readouterr().out.splitlines()[-1] == "1 session awaits review"


def test_review_list_says_when_nothing_awaits_review(captured, home, capsys):
    assert run(home, "--list") == 0
    assert capsys.readouterr().out.splitlines() == ["0 sessions await review"]


def test_review_with_no_changes_on_the_command_line(tagged, home, capsys):
    assert run(home, "--session", STORY_ID, "--by", "scholar") == 0
    assert capsys.readouterr().out.splitlines() == [
        f"reviewed {STORY_ID}, every value kept"
    ]
    assert story(tagged)["origin"] == "person scholar"


def test_review_set_and_rationale_on_the_command_line(tagged, home, capsys):
    text = "The scholar named the sentence on fit as the place for the first finding."
    code = run(
        home,
        "--session",
        STORY_ID,
        "--by",
        "scholar",
        "--set",
        "title=Two findings on volunteer exit",
        "--set",
        "keywords=volunteer exit, citations, Results",
        "--rationale",
        f"2={text}",
    )
    assert code == 0
    assert capsys.readouterr().out.splitlines() == [
        f"reviewed {STORY_ID}, changed title, keywords, rationale 2"
    ]
    row = story(tagged)
    assert row["title"] == "Two findings on volunteer exit"
    assert row["keywords"] == ["volunteer exit", "citations", "Results"]
    assert row["reason"] == "reviewed with changes"
    assert story_events(tagged)[1]["rationale"] == text


def test_a_value_holding_an_equals_sign_is_kept_whole(tagged, home):
    assert run(home, "--session", STORY_ID, "--by", "m", "--set", "title=a=b") == 0
    assert story(tagged)["title"] == "a=b"


def test_review_refusals_on_the_command_line_exit_1(tagged, home, capsys):
    held = all_rows(tagged)
    assert run(home, "--session", STORY_ID, "--by", "scholar", "--set", "project=x") == 1
    assert "review refused" in capsys.readouterr().err
    assert run(home, "--session", STORY_ID) == 1
    assert "--by" in capsys.readouterr().err
    assert run(home, "--list", "--by", "scholar") == 1
    assert "--list takes no" in capsys.readouterr().err
    assert all_rows(tagged) == held


@pytest.mark.parametrize(
    "extra",
    [
        ["--session", STORY_ID, "--by", "m", "--set", "title"],
        ["--session", STORY_ID, "--by", "m", "--rationale", "two=A reason."],
        ["--session", STORY_ID, "--by", "m", "--rationale", "2"],
        ["--list", "--session", STORY_ID],
        [],
    ],
)
def test_badly_formed_options_are_refused(tagged, home, extra):
    with pytest.raises(SystemExit) as stop:
        run(home, *extra)
    assert stop.value.code == 2


def test_review_refuses_a_home_with_no_store(tmp_path, capsys):
    empty = tmp_path / "empty_home"
    assert run(empty, "--list") == 1
    assert "no audit store" in capsys.readouterr().err
    assert not empty.exists()


def test_nothing_reviewed_is_current_from_the_model_pass(tagged):
    review(tagged, STORY_ID, "scholar", {}, {})
    review(tagged, SUBAGENT_ID, "scholar", {}, {})
    for table in ("sessions", "events"):
        assert [r for r in current(tagged, table) if r["origin"] == "model pass"] == []
