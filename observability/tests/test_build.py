"""Tests for the build command and the view's data (Track E, steps E6 and E13).

Proposal Figure 2 has the observability dashboard fed from the databases, and
appendix A2.6 paragraph 1 asks for one view that is the same for every
harness and can be reopened after the session ends. build_view reads a
synthetic audit home, built by audit_fixture.py in a temporary folder, and
writes trace files and the view's data file into a temporary folder. The
sessions are Track E's own fixture, the test story's session, the story's
session from a folder on the excluded list, and a session of a harness named
other_harness, which the events adapter shows (step E11). The reconciliation file (item 3) drops the view's filtering
by excluded folder, so the excluded session is shown like any other session
in the record. Step E13 adds verification runs, from Track E's run fixture
fixtures/vg_run/ and copies of it in temporary folders. Nothing here calls a model or the network, and no view is
built outside a temporary folder. Run from the repository root with
python3 -m pytest -q observability/tests.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from observability import build as bd
from observability import cli
from observability import conventions as cv
from observability import spans as sp
from observability.tests.audit_fixture import STORY_SESSION_ID, AuditHome, story_transcript

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parents[1]
FIXTURE = TESTS / "fixtures" / "claude_code" / "obs_session.jsonl"
FIXTURE_ID = "7c2e9d10-4b1a-4f3e-9a55-0e6b3c8d2f41"
KB = TESTS / "fixtures" / "kb"
EXCLUDED_SESSION = (ROOT / "examples" / "test_story" / "sessions" / "claude_code"
                    / "excluded_session.jsonl")
EXCLUDED_ID = "9b1e0414-6c3a-4f2d-b8e5-71d2a9c4f086"
OTHER_ID = "other-session-0001"
PREFIX = "window.OBS = "


def _obs_transcript(project):
    text = FIXTURE.read_text(encoding="utf-8")
    text = text.replace("{{PROJECT}}", str(project)).replace("{{KB}}", str(KB))
    return text.encode("utf-8")


def _excluded_transcript(project):
    text = EXCLUDED_SESSION.read_text(encoding="utf-8")
    return text.replace("{{PROJECT}}", str(project)).encode("utf-8")


class Story:
    """The fixture audit home and the folders its sessions ran in."""

    def __init__(self, tmp_path):
        work = tmp_path / "work"
        self.obs_project = work / "obs_project"
        self.story_project = work / "story_project"
        self.excluded = self.story_project / "excluded_folder"
        self.other_project = work / "other_project"
        for folder in (self.obs_project, self.excluded, self.other_project):
            folder.mkdir(parents=True)
        self.audit = AuditHome(tmp_path / "audit_home")
        self.home = self.audit.home
        row = self.audit.add_session(FIXTURE_ID, self.obs_project,
                                     started_at="2026-10-22T09:00:01.000Z",
                                     ended_at="2026-10-22T09:01:04.622Z")
        self.audit.add_transcript(row, _obs_transcript(self.obs_project))
        row = self.audit.add_session(STORY_SESSION_ID, self.story_project)
        self.audit.add_transcript(row, story_transcript(self.story_project))
        row = self.audit.add_session(EXCLUDED_ID, self.excluded,
                                     started_at="2026-10-21T15:30:02.204Z",
                                     ended_at="2026-10-21T15:30:09.000Z")
        self.audit.add_transcript(row, _excluded_transcript(self.story_project))
        row = self.audit.add_session(OTHER_ID, self.other_project, harness="other_harness")
        self.audit.add_event(row, 1, "read", "notes.md", role="read")
        (self.home / "settings.yaml").write_text(
            "excluded_folders:\n  - {}\n".format(self.excluded), encoding="utf-8")
        self.out = tmp_path / "view"

    def build(self, **options):
        options.setdefault("kb_dirs", (str(KB),))
        return bd.build_view(self.home, self.out, **options)


@pytest.fixture
def story(tmp_path):
    return Story(tmp_path)


def _data(out):
    text = (Path(out) / "data.js").read_text(encoding="utf-8")
    assert text.startswith(PREFIX)
    body = text[len(PREFIX):].rstrip()
    assert body.endswith(";")
    return json.loads(body[:-1])


def _trace_id(session_id):
    return sp.trace_id_for("claude_code:" + session_id)


def _row(data, session_id):
    [row] = [row for row in data["traces"] if row["session_id"] == session_id]
    return row


# The trace files


def test_each_session_gives_one_trace_file(story):
    summary = story.build()
    names = sorted(path.name for path in (story.out / "traces").iterdir())
    expected = sorted([_trace_id(sid) + ".json"
                       for sid in (FIXTURE_ID, STORY_SESSION_ID, EXCLUDED_ID)]
                      + [sp.trace_id_for("other_harness:" + OTHER_ID) + ".json"])
    assert names == expected
    assert summary["traces"] == 4
    assert summary["out"] == str(story.out)
    assert isinstance(summary["notes"], list)


def test_every_trace_file_reads_back_and_every_span_passes(story):
    story.build()
    for path in (story.out / "traces").iterdir():
        resource, spans = sp.read_trace(path)
        assert resource[cv.SERVICE_NAME] in ("claude_code", "other_harness")
        assert spans
        for span in spans:
            assert sp.problems(span) == []
            assert cv.convention_problems(span) == []
            assert span["trace_id"] + ".json" == path.name


def test_retrievals_are_marked_in_the_trace_file(story):
    story.build()
    _, spans = sp.read_trace(story.out / "traces" / (_trace_id(FIXTURE_ID) + ".json"))
    sources = sorted(span["attributes"][cv.DATA_SOURCE_ID] for span in spans
                     if cv.DATA_SOURCE_ID in span["attributes"])
    assert sources == ["kb", "pipeline-kb", "pipeline-kb"]


def test_a_session_of_another_harness_is_a_trace_row_with_its_file_roles(story):
    """Step E11 replaces step E6's note with the events adapter's trace."""
    summary = story.build()
    data = _data(story.out)
    row = _row(data, OTHER_ID)
    assert row["source"] == "other_harness"
    assert row["trace_id"] == sp.trace_id_for("other_harness:" + OTHER_ID)
    assert row["title"] == "other_project"
    assert row["project"] == str(story.other_project)
    assert row["model_calls"] == 0
    assert row["tool_calls"] == 0
    files = [entry for entry in data["files"] if entry["session_id"] == OTHER_ID]
    assert [(entry["role"], entry["path"], entry["agent"]) for entry in files] == [
        ("read", "notes.md", "main")]
    categories = [span["category"] for span in data["spans"][row["trace_id"]]]
    assert categories == ["agent", "event"]
    assert not any(OTHER_ID in note for note in data["notes"])
    assert not any(OTHER_ID in note for note in summary["notes"])


def test_the_broken_line_of_the_fixture_is_a_note(story):
    data = _data(story.build()["out"])
    assert any("does not parse" in note for note in data["notes"])


def test_a_session_in_an_excluded_folder_is_still_shown(story):
    """The reconciliation drops the view's filtering by excluded folder (item 3)."""
    story.build()
    data = _data(story.out)
    assert _row(data, EXCLUDED_ID)["project"] == str(story.excluded)
    assert (story.out / "traces" / (_trace_id(EXCLUDED_ID) + ".json")).is_file()


def test_the_project_option_keeps_only_sessions_in_that_folder(story):
    summary = story.build(project=story.obs_project)
    assert summary["traces"] == 1
    data = _data(story.out)
    assert [row["session_id"] for row in data["traces"]] == [FIXTURE_ID]


def test_a_session_stored_under_two_rows_joins_one_trace(tmp_path):
    project = tmp_path / "work" / "story_project"
    project.mkdir(parents=True)
    audit = AuditHome(tmp_path / "audit_home")
    first = audit.add_session(STORY_SESSION_ID, project)
    audit.add_transcript(first, story_transcript(project, lines=6))
    second = audit.add_session(STORY_SESSION_ID, project, supersedes=first)
    audit.add_transcript(second, story_transcript(project))
    out = tmp_path / "view"
    summary = bd.build_view(audit.home, out)
    assert summary["traces"] == 1
    _, spans = sp.read_trace(out / "traces" / (_trace_id(STORY_SESSION_ID) + ".json"))
    tools = [span for span in spans
             if span["attributes"].get(cv.OPERATION_NAME) == cv.EXECUTE_TOOL]
    assert len(tools) == 6
    assert len({span["span_id"] for span in spans}) == len(spans)


def test_a_trace_file_left_by_an_earlier_build_is_removed(story):
    story.build()
    left = story.out / "traces" / (_trace_id(STORY_SESSION_ID) + ".json")
    assert left.is_file()
    story.build(project=story.obs_project)
    assert not left.exists()
    assert sorted(path.name for path in (story.out / "traces").iterdir()) == [
        _trace_id(FIXTURE_ID) + ".json"]


def test_the_database_bytes_are_unchanged(story):
    before = story.audit.digest()
    story.build()
    assert story.audit.digest() == before


def test_two_builds_with_no_change_give_identical_trace_files(story):
    story.build()
    first = {path.name: path.read_bytes() for path in (story.out / "traces").iterdir()}
    story.build()
    second = {path.name: path.read_bytes() for path in (story.out / "traces").iterdir()}
    assert first == second


# The view's data


def test_data_js_parses_as_json_after_its_prefix(story):
    story.build(live=True, refresh_seconds=7)
    data = _data(story.out)
    for key in ("built_at", "live", "refresh_seconds", "semconv", "sources", "notes",
                "traces", "spans", "files", "kb_reads", "kb_entries"):
        assert key in data
    assert data["live"] is True
    assert data["refresh_seconds"] == 7
    assert data["semconv"] == cv.SEMCONV_SOURCE
    assert data["built_at"].endswith("Z")


def test_live_defaults_to_false_and_five_seconds(story):
    story.build()
    data = _data(story.out)
    assert data["live"] is False
    assert data["refresh_seconds"] == 5


def test_sources_name_the_audit_home_and_the_kb_folders(story):
    story.build()
    sources = _data(story.out)["sources"]
    assert sources["audit_home"] == str(story.home)
    assert sources["kb_dirs"] == [str(KB)]


def test_the_trace_rows_hold_the_expected_counts(story):
    story.build()
    data = _data(story.out)
    row = _row(data, FIXTURE_ID)
    assert row["trace_id"] == _trace_id(FIXTURE_ID)
    assert row["source"] == "claude_code"
    assert row["title"] == "obs_project"
    assert row["project"] == str(story.obs_project)
    assert row["started"] == "2026-10-22T09:00:01.000Z"
    assert row["duration_s"] == pytest.approx(63.622)
    assert row["model_calls"] == 8
    assert row["tool_calls"] == 7
    assert row["subagents"] == 0
    assert row["kb_reads"] == 3
    assert row["errors"] == 1
    assert row["reasoning"] == {"exposed": 1, "turns": 2}
    _, spans = sp.read_trace(story.out / "traces" / (row["trace_id"] + ".json"))
    chats = [span for span in spans
             if span["attributes"].get(cv.OPERATION_NAME) == cv.CHAT]
    assert row["input_tokens"] == sum(span["attributes"][cv.USAGE_INPUT_TOKENS]
                                      for span in chats)
    assert row["output_tokens"] == sum(span["attributes"][cv.USAGE_OUTPUT_TOKENS]
                                       for span in chats)
    assert row["input_tokens"] > 0 and row["output_tokens"] > 0

    story_row = _row(data, STORY_SESSION_ID)
    assert story_row["title"] == "story_project"
    assert story_row["model_calls"] == 7
    assert story_row["tool_calls"] == 6
    assert story_row["kb_reads"] == 0
    assert story_row["errors"] == 0
    assert story_row["input_tokens"] == 0
    assert story_row["reasoning"] == {"exposed": 0, "turns": 0}


def test_the_trace_rows_come_in_order_of_their_start(story):
    story.build()
    starts = [row["started"] for row in _data(story.out)["traces"]]
    assert starts == sorted(starts)


def test_spans_come_parents_first_and_siblings_by_start(story):
    story.build()
    data = _data(story.out)
    rows = data["spans"][_trace_id(FIXTURE_ID)]
    assert rows[0]["depth"] == 0
    assert rows[0]["parent_span_id"] == ""
    assert rows[0]["category"] == "agent"
    assert rows[0]["start_s"] == 0
    seen = set()
    for row in rows:
        if row["parent_span_id"]:
            assert row["parent_span_id"] in seen
            assert row["depth"] == 1
        seen.add(row["span_id"])
    starts = [row["start_s"] for row in rows[1:]]
    assert starts == sorted(starts)
    assert rows[-1]["end_s"] <= _row(data, FIXTURE_ID)["duration_s"] + 1e-9


def test_span_rows_carry_category_status_agent_and_text_attributes(story):
    story.build()
    rows = _data(story.out)["spans"][_trace_id(FIXTURE_ID)]
    by_name = {}
    for row in rows:
        by_name.setdefault(row["name"], []).append(row)
    assert {row["category"] for row in by_name["chat test-model"]} == {"model"}
    assert {row["category"] for row in by_name["execute_tool mcp__pipeline-kb__search_kb"]} == {"kb"}
    assert {row["category"] for row in by_name["execute_tool Bash"]} == {"tool"}
    reads = {row["attributes"][cv.FILE_PATH]: row["category"]
             for row in by_name["execute_tool Read"]}
    assert reads[str(story.obs_project / "manuscript.md")] == "tool"
    assert reads[str(KB / "verification" / "verification-references-procedure.md")] == "kb"
    [bash] = by_name["execute_tool Bash"]
    assert bash["status"] == "error"
    assert bash["error_type"] == "tool_error"
    [write] = by_name["execute_tool Write"]
    assert write["status"] == "unset"
    assert write["error_type"] == ""
    for row in rows:
        assert row["agent"] == "main"
        for key, value in row["attributes"].items():
            assert isinstance(key, str) and isinstance(value, str)
    [search] = by_name["execute_tool mcp__pipeline-kb__search_kb"]
    assert json.loads(search["attributes"][cv.TOOL_CALL_ARGUMENTS])["query"] == "checking references"
    assert search["attributes"][cv.TOOL_TYPE] == "datastore"
    assert search["start_s"] == pytest.approx(3.733)
    assert search["end_s"] == pytest.approx(4.020)


def test_span_categories_for_spans_of_other_kinds():
    trace = sp.trace_id_for("category-test")

    def span(key, attributes):
        return sp.new_span(trace, key, "x " + key, cv.SPAN_KIND_INTERNAL, 1, 2,
                           attributes=attributes)

    assert bd.category(span("w", {cv.OPERATION_NAME: cv.INVOKE_WORKFLOW})) == "agent"
    assert bd.category(span("a", {cv.OPERATION_NAME: cv.INVOKE_AGENT})) == "agent"
    assert bd.category(span("c", {cv.OPERATION_NAME: cv.CHAT, cv.VG_EXECUTOR: "live"})) == "model"
    assert bd.category(span("s", {cv.VG_STEP_SEQ: 1})) == "step"
    assert bd.category(span("j", {cv.VG_EXECUTOR: "recorded"})) == "judgment"
    assert bd.category(span("e", {cv.AUDIT_ORDINAL: 3})) == "event"
    assert bd.category(span("o", {})) == "other"
    assert bd.category(span("k", {cv.OPERATION_NAME: cv.EXECUTE_TOOL,
                                  cv.DATA_SOURCE_ID: "pipeline-kb"})) == "kb"


def test_the_agent_is_the_nearest_invoke_agent_with_an_id():
    trace = sp.trace_id_for("agent-test")
    root = sp.new_span(trace, "root", "invoke_agent claude_code", cv.SPAN_KIND_INTERNAL,
                       0, 10, attributes={cv.OPERATION_NAME: cv.INVOKE_AGENT,
                                          cv.AGENT_NAME: "claude_code"})
    call = sp.new_span(trace, "call", "execute_tool Agent", cv.SPAN_KIND_INTERNAL, 1, 9,
                       parent_span_id=root["span_id"],
                       attributes={cv.OPERATION_NAME: cv.EXECUTE_TOOL, cv.TOOL_NAME: "Agent"})
    sub = sp.new_span(trace, "sub", "invoke_agent", cv.SPAN_KIND_INTERNAL, 2, 8,
                      parent_span_id=call["span_id"],
                      attributes={cv.OPERATION_NAME: cv.INVOKE_AGENT, cv.AGENT_ID: "a1"})
    inner = sp.new_span(trace, "inner", "execute_tool Read", cv.SPAN_KIND_INTERNAL, 3, 4,
                        parent_span_id=sub["span_id"],
                        attributes={cv.OPERATION_NAME: cv.EXECUTE_TOOL, cv.TOOL_NAME: "Read"})
    rows = bd.span_rows([inner, sub, call, root])
    assert [row["span_id"] for row in rows] == [
        root["span_id"], call["span_id"], sub["span_id"], inner["span_id"]]
    assert [row["depth"] for row in rows] == [0, 1, 2, 3]
    assert [row["agent"] for row in rows] == ["main", "main", "a1", "a1"]


def test_the_files_rows_hold_the_story_reads_edits_and_write(story):
    story.build()
    data = _data(story.out)
    rows = [row for row in data["files"] if row["session_id"] == STORY_SESSION_ID]
    manuscript = str(story.story_project / "manuscript.md")
    notes = str(story.story_project / "source_notes.md")
    assert [(row["tool"], row["role"], row["path"]) for row in rows] == [
        ("Read", "read", manuscript),
        ("Edit", "edited", manuscript),
        ("Edit", "edited", manuscript),
        ("Write", "produced", notes),
    ]
    trace_spans = {row["span_id"] for row in data["spans"][_trace_id(STORY_SESSION_ID)]}
    for row in rows:
        assert row["trace_id"] == _trace_id(STORY_SESSION_ID)
        assert row["span_id"] in trace_spans
        assert row["project"] == str(story.story_project)
        assert row["agent"] == "main"
        assert row["time"].startswith("2026-10-21T14:02:")
    assert rows[0]["time"] == "2026-10-21T14:02:09.874Z"


def test_the_kb_reads_rows_hold_both_calls_and_the_entry_file_read(story):
    story.build()
    rows = _data(story.out)["kb_reads"]
    assert [(row["tool"], row["source"], row["entries"], row["query"], row["outcome"])
            for row in rows] == [
        ("mcp__pipeline-kb__search_kb", "pipeline-kb", [], "checking references", "ok"),
        ("mcp__pipeline-kb__get_entry", "pipeline-kb",
         ["verification-references-procedure"], "", "ok"),
        ("Read", "kb", ["verification-references-procedure"], "", "ok"),
    ]
    for row in rows:
        assert row["trace_id"] == _trace_id(FIXTURE_ID)
        assert row["session_id"] == FIXTURE_ID
        assert row["project"] == str(story.obs_project)
        assert row["agent"] == "main"
        assert row["span_id"]
        assert row["time"].startswith("2026-10-22T09:00:")


def test_the_kb_entries_rows_count_reads(story):
    story.build()
    entries = {row["id"]: row for row in _data(story.out)["kb_entries"]}
    assert set(entries) == {"verification-references-procedure", "formats-results-file"}
    assert entries["verification-references-procedure"]["reads"] == 2
    assert entries["formats-results-file"]["reads"] == 0
    assert entries["formats-results-file"]["title"]
    assert entries["formats-results-file"]["group"]
    assert entries["formats-results-file"]["path"].endswith("formats-results-file.md")


def test_without_kb_folders_there_are_no_entries_and_no_entry_file_read(story):
    story.build(kb_dirs=())
    data = _data(story.out)
    assert data["kb_entries"] == []
    assert data["sources"]["kb_dirs"] == []
    assert [row["tool"] for row in data["kb_reads"]] == [
        "mcp__pipeline-kb__search_kb", "mcp__pipeline-kb__get_entry"]


def test_kb_servers_choose_which_calls_are_retrievals(story):
    story.build(kb_servers=("workflow-kb",))
    tools = [row["tool"] for row in _data(story.out)["kb_reads"]]
    assert tools == ["Read"]


def test_a_missing_audit_record_is_refused(tmp_path):
    with pytest.raises(bd.RecordError):
        bd.build_view(tmp_path / "nowhere", tmp_path / "view")
    assert not (tmp_path / "view").exists()


# The command line


def test_the_build_command_prints_the_folder_and_the_number_of_traces(story, capsys):
    code = cli.main(["build", "--audit-home", str(story.home), "--kb-dir", str(KB),
                     "--out", str(story.out)])
    assert code == 0
    printed = capsys.readouterr().out
    assert str(story.out) in printed
    assert "4 traces" in printed
    data = _data(story.out)
    assert data["sources"]["kb_dirs"] == [str(KB)]
    assert len(data["kb_reads"]) == 3


def test_the_build_command_takes_project_and_kb_server(story, capsys):
    code = cli.main(["build", "--audit-home", str(story.home), "--project",
                     str(story.obs_project), "--kb-dir", str(KB), "--kb-server",
                     "workflow-kb", "--kb-server", "other-kb", "--out", str(story.out)])
    assert code == 0
    assert ", 1 trace\n" in capsys.readouterr().out
    assert [row["tool"] for row in _data(story.out)["kb_reads"]] == ["Read"]


def test_the_default_kb_servers_are_pipeline_kb_and_workflow_kb(story, capsys):
    cli.main(["build", "--audit-home", str(story.home), "--out", str(story.out)])
    tools = [row["tool"] for row in _data(story.out)["kb_reads"]]
    assert tools == ["mcp__pipeline-kb__search_kb", "mcp__pipeline-kb__get_entry"]


def test_the_view_goes_to_the_home_folder_by_default(story, tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    assert cli.main(["build", "--audit-home", str(story.home)]) == 0
    view = home / ".observability" / "view"
    assert (view / "data.js").is_file()
    assert str(view) in capsys.readouterr().out


def test_a_missing_audit_record_fails_the_command(tmp_path, capsys):
    code = cli.main(["build", "--audit-home", str(tmp_path / "nowhere"),
                     "--out", str(tmp_path / "view")])
    assert code != 0
    assert "audit.sqlite" in capsys.readouterr().err


def test_python_m_observability_runs_the_command(story):
    done = subprocess.run(
        [sys.executable, "-m", "observability", "build", "--audit-home", str(story.home),
         "--out", str(story.out)],
        cwd=str(ROOT), capture_output=True, text=True,
        env=dict(os.environ, PYTHONPATH=str(ROOT)))
    assert done.returncode == 0, done.stderr
    assert "4 traces" in done.stdout
    assert (story.out / "data.js").is_file()


# Verification runs in the view (step E13)

RUN_FIXTURE = TESTS / "fixtures" / "vg_run"


def _run_copy(folder, name="run_one"):
    target = Path(folder) / name
    shutil.copytree(str(RUN_FIXTURE), str(target))
    return target


def _run_trace_id(run_dir):
    return sp.trace_id_for("vg:" + os.path.realpath(str(run_dir)))


def test_a_run_is_a_trace_row_with_one_model_call_and_no_errors(story):
    summary = story.build(vg_runs=(str(RUN_FIXTURE),))
    assert summary["traces"] == 5
    data = _data(story.out)
    [row] = [row for row in data["traces"] if row["source"] == "vg.py"]
    assert row["trace_id"] == _run_trace_id(RUN_FIXTURE)
    assert row["title"] == "selftest vg_run"
    assert row["session_id"] == "vg_run"
    assert row["project"] == ""
    assert row["model_calls"] == 1
    assert row["errors"] == 0
    assert row["tool_calls"] == 0
    categories = [span["category"] for span in data["spans"][row["trace_id"]]]
    assert categories.count("step") == 3
    assert categories.count("judgment") == 3
    assert categories.count("model") == 1


def test_the_run_trace_file_reads_back_and_every_span_passes(story):
    story.build(vg_runs=(str(RUN_FIXTURE),))
    path = story.out / "traces" / (_run_trace_id(RUN_FIXTURE) + ".json")
    resource, spans = sp.read_trace(path)
    assert resource[cv.SERVICE_NAME] == "vg.py"
    assert len(spans) == 8
    for span in spans:
        assert sp.problems(span) == []
        assert cv.convention_problems(span) == []


def test_sources_name_the_runs_given(story, tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    _run_copy(runs)
    story.build(vg_runs=(str(runs),))
    assert _data(story.out)["sources"]["vg_runs"] == [str(runs)]
    story.build()
    assert _data(story.out)["sources"]["vg_runs"] == []


def test_a_folder_of_runs_gives_each_run_a_row(story, tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    first = _run_copy(runs, "run_a")
    second = _run_copy(runs, "run_b")
    summary = story.build(vg_runs=(str(runs),))
    assert summary["traces"] == 6
    rows = [row for row in _data(story.out)["traces"] if row["source"] == "vg.py"]
    assert sorted(row["session_id"] for row in rows) == ["run_a", "run_b"]
    assert sorted(row["trace_id"] for row in rows) == sorted(
        [_run_trace_id(first), _run_trace_id(second)])


def test_a_path_that_holds_no_run_is_a_note(story, tmp_path):
    empty = tmp_path / "no_runs"
    empty.mkdir()
    summary = story.build(vg_runs=(str(empty),))
    assert summary["traces"] == 4
    assert any(str(empty) in note for note in summary["notes"])
    assert any(str(empty) in note for note in _data(story.out)["notes"])


def test_a_run_whose_manifest_does_not_parse_is_a_note(story, tmp_path):
    run = _run_copy(tmp_path)
    (run / "manifest.json").write_text("{ half written", encoding="utf-8")
    summary = story.build(vg_runs=(str(run),))
    assert summary["traces"] == 4
    assert any("run_one" in note for note in summary["notes"])


def test_a_run_in_an_excluded_folder_is_still_shown(story):
    """The reconciliation drops the view's filtering by excluded folder (item 3)."""
    run = _run_copy(story.excluded)
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    manifest["inputs_from"] = str(story.excluded / "inputs")
    (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    summary = story.build(vg_runs=(str(run),))
    assert summary["traces"] == 5
    assert (story.out / "traces" / (_run_trace_id(run) + ".json")).is_file()


def test_a_run_trace_left_by_an_earlier_build_is_removed(story):
    story.build(vg_runs=(str(RUN_FIXTURE),))
    left = story.out / "traces" / (_run_trace_id(RUN_FIXTURE) + ".json")
    assert left.is_file()
    story.build()
    assert not left.exists()


def test_the_run_folder_is_not_changed_by_the_build(story, tmp_path):
    run = _run_copy(tmp_path)

    def contents():
        return {str(path.relative_to(run)): path.read_bytes()
                for path in sorted(run.rglob("*")) if path.is_file()}

    before = contents()
    story.build(vg_runs=(str(run),))
    assert contents() == before


def test_the_build_command_takes_vg_runs(story, tmp_path, capsys):
    runs = tmp_path / "runs"
    runs.mkdir()
    _run_copy(runs, "run_a")
    code = cli.main(["build", "--audit-home", str(story.home), "--out", str(story.out),
                     "--vg-runs", str(RUN_FIXTURE), str(runs)])
    assert code == 0
    assert "6 traces" in capsys.readouterr().out
    assert _data(story.out)["sources"]["vg_runs"] == [str(RUN_FIXTURE), str(runs)]
