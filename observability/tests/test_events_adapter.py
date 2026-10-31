"""Tests for sessions of other harnesses (Track E, step E11).

Appendix A2.6 paragraph 2 asks for a view that does not depend on any one
harness, and Figure A1 names any harness. A harness without a transcript
adapter is shown from the audit events table, with verbs, kinds, and file
roles in Table A4's words but no results or reasoning (plan choice 5). The
sessions here are written to a synthetic audit home by audit_fixture.py in a
temporary folder, under a harness named other_harness. Nothing here calls a
model or the network. Run from the repository root with
python3 -m pytest -q observability/tests.
"""
import pytest

from observability import conventions as cv
from observability import record as rc
from observability import spans as sp
from observability.adapters import events as ev
from observability.tests.audit_fixture import AuditHome

HARNESS = "other_harness"
SESSION_ID = "other-session-0001"
STARTED = "2026-10-21T16:00:00.000Z"
ENDED = "2026-10-21T16:04:30.250Z"


class Home:
    """An audit home holding one other_harness session with four events, one superseded."""

    def __init__(self, tmp_path):
        self.project = tmp_path / "work" / "other_project"
        self.project.mkdir(parents=True)
        self.audit = AuditHome(tmp_path / "audit_home")
        row = self.audit.add_session(SESSION_ID, self.project, harness=HARNESS,
                                     started_at=STARTED, ended_at=ENDED)
        self.notes = str(self.project / "notes.md")
        self.draft = str(self.project / "draft.md")
        self.long = "/".join(["folder%02d" % number for number in range(1, 13)]) + "/out.md"
        self.audit.add_event(row, 2, "edited", self.draft, rationale="tighten the opening",
                             role="edited")
        old = self.audit.add_event(row, 1, "read", str(self.project / "old_notes.md"), role="read")
        self.audit.add_event(row, 1, "read", self.notes, role="read", supersedes=old)
        self.audit.add_event(row, 3, "ran", "pytest -q", kind="observation")
        self.audit.add_event(row, 4, "produced", self.long, role="produced")
        empty = self.audit.add_session("other-session-0002", self.project, harness=HARNESS,
                                       started_at=STARTED, ended_at=ENDED)
        assert empty

    def read(self, session_id=SESSION_ID):
        record = rc.open_record(self.audit.home)
        try:
            [session] = [item for item in rc.sessions(record)
                         if item["harness_session_id"] == session_id]
            return session, rc.events(record, session)
        finally:
            record.db.close()


@pytest.fixture
def home(tmp_path):
    return Home(tmp_path)


def _trace(home, session_id=SESSION_ID):
    session, events = home.read(session_id)
    return ev.trace(session, events)


def test_the_resource_and_trace_id_come_from_the_harness_and_its_session_id(home):
    resource, spans = _trace(home)
    assert resource == {cv.SERVICE_NAME: HARNESS}
    trace_id = sp.trace_id_for(HARNESS + ":" + SESSION_ID)
    assert {span["trace_id"] for span in spans} == {trace_id}


def test_the_root_is_the_harness_from_the_session_start_to_its_end(home):
    _, spans = _trace(home)
    [root] = [span for span in spans if not span["parent_span_id"]]
    assert root["name"] == "invoke_agent " + HARNESS
    assert root["kind"] == cv.SPAN_KIND_INTERNAL
    assert root["span_id"] == sp.span_id_for(root["trace_id"], "root")
    assert root["start_ns"] == sp.time_ns(STARTED)
    assert root["end_ns"] == sp.time_ns(ENDED)
    assert root["attributes"] == {
        cv.OPERATION_NAME: cv.INVOKE_AGENT,
        cv.AGENT_NAME: HARNESS,
        cv.CONVERSATION_ID: SESSION_ID,
        cv.AUDIT_HARNESS: HARNESS,
        cv.AUDIT_PROJECT: str(home.project),
    }
    assert cv.PROVIDER_NAME not in root["attributes"]


def test_one_span_per_current_event_in_ordinal_order(home):
    _, spans = _trace(home)
    [root] = [span for span in spans if not span["parent_span_id"]]
    events = [span for span in spans if span["parent_span_id"]]
    assert [span["attributes"][cv.AUDIT_ORDINAL] for span in events] == [1, 2, 3, 4]
    assert len(spans) == 5
    for span in events:
        assert span["parent_span_id"] == root["span_id"]
        assert span["kind"] == cv.SPAN_KIND_INTERNAL
        ordinal = span["attributes"][cv.AUDIT_ORDINAL]
        assert span["span_id"] == sp.span_id_for(span["trace_id"], str(ordinal))
        assert span["start_ns"] == span["end_ns"] == root["start_ns"]


def test_event_spans_carry_the_event_fields_roles_and_file_paths(home):
    _, spans = _trace(home)
    by_ordinal = {span["attributes"][cv.AUDIT_ORDINAL]: span
                  for span in spans if span["parent_span_id"]}
    read = by_ordinal[1]
    assert read["name"] == "read " + home.notes[-60:]
    assert read["attributes"] == {
        cv.AUDIT_VERB: "read",
        cv.AUDIT_KIND: "action",
        cv.AUDIT_OBJECT: home.notes,
        cv.AUDIT_RATIONALE: "",
        cv.AUDIT_ORDINAL: 1,
        cv.AUDIT_ROLE: "read",
        cv.FILE_PATH: home.notes,
    }
    edited = by_ordinal[2]
    assert edited["attributes"][cv.AUDIT_RATIONALE] == "tighten the opening"
    assert edited["attributes"][cv.AUDIT_ROLE] == "edited"
    assert edited["attributes"][cv.FILE_PATH] == home.draft
    ran = by_ordinal[3]
    assert ran["name"] == "ran pytest -q"
    assert ran["attributes"][cv.AUDIT_KIND] == "observation"
    assert ran["attributes"][cv.AUDIT_ROLE] == ""
    assert cv.FILE_PATH not in ran["attributes"]


def test_the_object_in_a_span_name_is_cut_to_its_last_60_characters(home):
    _, spans = _trace(home)
    [produced] = [span for span in spans
                  if span["attributes"].get(cv.AUDIT_ORDINAL) == 4]
    assert len(home.long) > 60
    assert produced["name"] == "produced " + home.long[-60:]
    assert produced["attributes"][cv.AUDIT_OBJECT] == home.long
    assert produced["attributes"][cv.FILE_PATH] == home.long


def test_a_superseded_event_is_not_shown(home):
    _, spans = _trace(home)
    objects = [span["attributes"].get(cv.AUDIT_OBJECT) for span in spans]
    assert str(home.project / "old_notes.md") not in objects
    assert not any("old_notes" in span["name"] for span in spans)


def test_a_session_with_no_events_gives_the_root_alone(home):
    resource, spans = _trace(home, "other-session-0002")
    assert resource == {cv.SERVICE_NAME: HARNESS}
    assert len(spans) == 1
    assert spans[0]["name"] == "invoke_agent " + HARNESS
    assert spans[0]["parent_span_id"] == ""


def test_empty_fields_in_the_record_become_empty_text():
    session = {"harness": HARNESS, "harness_session_id": "s3", "project": None,
               "started_at": STARTED, "ended_at": None, "row_ids": ["r"]}
    events = [{"ordinal": 1, "verb": "searched", "kind": None, "object": None,
               "rationale": None, "role": None}]
    _, spans = ev.trace(session, events)
    root, event = spans
    assert root["end_ns"] == root["start_ns"] == sp.time_ns(STARTED)
    assert root["attributes"][cv.AUDIT_PROJECT] == ""
    assert event["name"] == "searched"
    assert event["attributes"][cv.AUDIT_OBJECT] == ""
    assert event["attributes"][cv.AUDIT_ROLE] == ""
    assert cv.FILE_PATH not in event["attributes"]


def test_every_span_passes_problems_and_convention_problems(home):
    for session_id in (SESSION_ID, "other-session-0002"):
        resource, spans = _trace(home, session_id)
        for span in spans:
            assert sp.problems(span) == []
            assert cv.convention_problems(span) == []


def test_the_spans_survive_the_trace_file(home, tmp_path):
    resource, spans = _trace(home)
    path = tmp_path / "trace.json"
    sp.write_trace(path, spans, resource)
    assert sp.read_trace(path) == (resource, spans)


def test_two_events_sharing_an_ordinal_never_share_a_span_id():
    session = {"harness": HARNESS, "harness_session_id": "s4", "project": "p",
               "started_at": STARTED, "ended_at": ENDED, "row_ids": ["r"]}
    events = [{"ordinal": 1, "verb": "read", "kind": "action", "object": "a.md",
               "rationale": "", "role": "read"},
              {"ordinal": 1, "verb": "read", "kind": "action", "object": "b.md",
               "rationale": "", "role": "read"}]
    _, spans = ev.trace(session, events)
    assert len({span["span_id"] for span in spans}) == 3
