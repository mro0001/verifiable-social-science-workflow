"""Tests for marking knowledge base retrievals (Track E, step E5).

Proposal Approach paragraph 4 has the observability layer show which knowledge
base entries the harness retrieves, so a harness asked to apply a verification
procedure can be seen retrieving it. Appendix A2.6 paragraph 1 names the
knowledge base entries the AI reads, and A2.4 "Knowledge base" has the entries
served by a server with five tools. A retrieval is a call to a listed server,
by default pipeline-kb and workflow-kb (the reconciliation file, Track E), or a
read of a markdown entry inside a listed folder (plan choice 10). The entries
are Track E's two synthetic fixtures. Nothing here calls a model, the network,
or a knowledge base server. Run from the repository root with
python3 -m pytest -q observability/tests.
"""
import copy
import json
import os
from pathlib import Path

from observability import conventions as cv
from observability import kb
from observability import spans as sp
from observability.adapters import claude_code as cc

TESTS = Path(__file__).resolve().parent
FIXTURE = TESTS / "fixtures" / "claude_code" / "obs_session.jsonl"
KB = TESTS / "fixtures" / "kb"
TRACE = sp.trace_id_for("kb-test")


def _session_spans(tmp_path, kb_folder=KB):
    text = FIXTURE.read_text(encoding="utf-8")
    text = text.replace("{{PROJECT}}", str(tmp_path / "work" / "obs_project"))
    text = text.replace("{{KB}}", str(kb_folder))
    records, _ = cc.read_records([text])
    [(_, spans)] = cc.traces(records, {})
    return spans


def _by_call(spans, call_id):
    [span] = [span for span in spans
              if span["attributes"].get(cv.TOOL_CALL_ID) == call_id]
    return span


def _tool(key, name, arguments, role=None, file_path=None):
    attributes = {
        cv.OPERATION_NAME: cv.EXECUTE_TOOL,
        cv.TOOL_NAME: name,
        cv.TOOL_CALL_ID: key,
        cv.TOOL_TYPE: "extension" if name.startswith("mcp__") else "function",
        cv.TOOL_CALL_ARGUMENTS: arguments,
    }
    if role:
        attributes[cv.AUDIT_ROLE] = role
    if file_path:
        attributes[cv.FILE_PATH] = str(file_path)
    return sp.new_span(TRACE, key, cv.EXECUTE_TOOL + " " + name, cv.SPAN_KIND_INTERNAL,
                       1, 2, parent_span_id=sp.span_id_for(TRACE, "root"),
                       attributes=attributes)


# Track E's session fixture


def test_get_entry_call_gets_its_entry_id(tmp_path):
    spans = kb.mark_retrievals(_session_spans(tmp_path), kb_dirs=(str(KB),))
    entry = _by_call(spans, "toolu_obs_02_entry")["attributes"]
    assert entry[cv.TOOL_TYPE] == "datastore"
    assert entry[cv.DATA_SOURCE_ID] == "pipeline-kb"
    assert entry[cv.RETRIEVAL_DOCUMENTS] == [{"id": "verification-references-procedure"}]
    assert cv.RETRIEVAL_QUERY_TEXT not in entry


def test_search_call_gets_its_query(tmp_path):
    spans = kb.mark_retrievals(_session_spans(tmp_path), kb_dirs=(str(KB),))
    search = _by_call(spans, "toolu_obs_01_search")["attributes"]
    assert search[cv.TOOL_TYPE] == "datastore"
    assert search[cv.DATA_SOURCE_ID] == "pipeline-kb"
    assert search[cv.RETRIEVAL_QUERY_TEXT] == "checking references"
    assert cv.RETRIEVAL_DOCUMENTS not in search


def test_read_of_an_entry_file_gets_the_id_from_its_front_matter(tmp_path):
    spans = kb.mark_retrievals(_session_spans(tmp_path), kb_dirs=(str(KB),))
    read = _by_call(spans, "toolu_obs_04_read")["attributes"]
    assert read[cv.TOOL_TYPE] == "datastore"
    assert read[cv.DATA_SOURCE_ID] == "kb"
    assert read[cv.RETRIEVAL_DOCUMENTS] == [{"id": "verification-references-procedure"}]


def test_other_calls_in_the_session_are_unchanged(tmp_path):
    before = _session_spans(tmp_path)
    after = kb.mark_retrievals(copy.deepcopy(before), kb_dirs=(str(KB),))
    changed = [span["attributes"].get(cv.TOOL_CALL_ID)
               for span, old in zip(after, before) if span != old]
    assert changed == ["toolu_obs_01_search", "toolu_obs_02_entry", "toolu_obs_04_read"]


def test_without_a_folder_the_entry_read_is_not_marked(tmp_path):
    spans = kb.mark_retrievals(_session_spans(tmp_path))
    read = _by_call(spans, "toolu_obs_04_read")["attributes"]
    assert read[cv.TOOL_TYPE] == "function"
    assert cv.DATA_SOURCE_ID not in read


def test_marked_spans_pass_both_checks_and_the_file_form(tmp_path):
    resource = {cv.SERVICE_NAME: "claude_code"}
    spans = kb.mark_retrievals(_session_spans(tmp_path), kb_dirs=(str(KB),))
    for span in spans:
        assert sp.problems(span) == [], span["name"]
        assert cv.convention_problems(span) == [], span["name"]
    path = tmp_path / "trace.json"
    sp.write_trace(path, spans, resource)
    _, back = sp.read_trace(path)
    entry = _by_call(back, "toolu_obs_02_entry")["attributes"]
    assert json.loads(entry[cv.RETRIEVAL_DOCUMENTS]) == [
        {"id": "verification-references-procedure"}]


# Spans written here


def test_list_entries_gets_only_the_source():
    [span] = kb.mark_retrievals([_tool("t1", "mcp__pipeline-kb__list_entries",
                                       {"group": "verification"})])
    attributes = span["attributes"]
    assert attributes[cv.TOOL_TYPE] == "datastore"
    assert attributes[cv.DATA_SOURCE_ID] == "pipeline-kb"
    assert cv.RETRIEVAL_DOCUMENTS not in attributes
    assert cv.RETRIEVAL_QUERY_TEXT not in attributes


def test_lookup_provenance_gets_its_entry_id():
    [span] = kb.mark_retrievals([_tool("t1", "mcp__pipeline-kb__lookup_provenance",
                                       {"id": "formats-results-file"})])
    assert span["attributes"][cv.RETRIEVAL_DOCUMENTS] == [{"id": "formats-results-file"}]


def test_workflow_kb_is_a_server_by_default():
    [span] = kb.mark_retrievals([_tool("t1", "mcp__workflow-kb__get_entry",
                                       {"id": "formats-results-file"})])
    assert span["attributes"][cv.DATA_SOURCE_ID] == "workflow-kb"
    assert span["attributes"][cv.RETRIEVAL_DOCUMENTS] == [{"id": "formats-results-file"}]


def test_a_server_not_listed_is_unchanged():
    spans = [_tool("t1", "mcp__other-server__get_entry", {"id": "x"}),
             _tool("t2", "mcp__pipeline-kb__search_kb", {"query": "q"})]
    before = copy.deepcopy(spans)
    after = kb.mark_retrievals(spans, kb_servers=("workflow-kb",))
    assert after == before


def test_arguments_kept_as_json_text_are_read_too():
    [span] = kb.mark_retrievals([_tool("t1", "mcp__pipeline-kb__search_kb",
                                       json.dumps({"query": "fit", "limit": 3}))])
    assert span["attributes"][cv.RETRIEVAL_QUERY_TEXT] == "fit"


def test_reads_outside_the_folder_and_edits_inside_it_are_unchanged(tmp_path):
    outside = tmp_path / "notes" / "outside.md"
    sibling = Path(str(KB) + "_old") / "verification" / "verification-references-procedure.md"
    inside = KB / "formats" / "formats-results-file.md"
    spans = [
        _tool("t1", "Read", {"file_path": str(outside)}, role="read", file_path=outside),
        _tool("t2", "Read", {"file_path": str(sibling)}, role="read", file_path=sibling),
        _tool("t3", "Edit", {"file_path": str(inside)}, role="edited", file_path=inside),
        _tool("t4", "Read", {"file_path": str(KB / "notes.txt")}, role="read",
              file_path=KB / "notes.txt"),
    ]
    before = copy.deepcopy(spans)
    assert kb.mark_retrievals(spans, kb_dirs=(str(KB),)) == before


def test_a_read_through_a_link_into_the_folder_counts(tmp_path):
    link = tmp_path / "kb_link"
    os.symlink(str(KB), str(link))
    target = KB / "formats" / "formats-results-file.md"
    [span] = kb.mark_retrievals(
        [_tool("t1", "Read", {"file_path": str(target)}, role="read", file_path=target)],
        kb_dirs=(str(link),))
    assert span["attributes"][cv.DATA_SOURCE_ID] == "kb_link"
    assert span["attributes"][cv.RETRIEVAL_DOCUMENTS] == [{"id": "formats-results-file"}]


def test_an_entry_that_can_no_longer_be_read_takes_its_file_name(tmp_path):
    folder = tmp_path / "entries"
    folder.mkdir()
    gone = folder / "group" / "gone-entry.md"
    [span] = kb.mark_retrievals(
        [_tool("t1", "Read", {"file_path": str(gone)}, role="read", file_path=gone)],
        kb_dirs=(str(folder),))
    assert span["attributes"][cv.DATA_SOURCE_ID] == "entries"
    assert span["attributes"][cv.RETRIEVAL_DOCUMENTS] == [{"id": "gone-entry"}]


# Listing entries


def test_entries_lists_the_two_fixtures():
    found = kb.entries((str(KB),))
    assert [(entry["id"], entry["title"], entry["group"]) for entry in found] == [
        ("formats-results-file", "The results file", "FORMATS"),
        ("verification-references-procedure", "The references procedure",
         "VERIFICATION"),
    ]
    assert [Path(entry["path"]) for entry in found] == [
        KB / "formats" / "formats-results-file.md",
        KB / "verification" / "verification-references-procedure.md"]


def test_entries_skip_files_without_front_matter(tmp_path):
    folder = tmp_path / "entries"
    (folder / "deep" / "deeper").mkdir(parents=True)
    (folder / "plain.md").write_text("# No front matter\n\nJust text.\n", encoding="utf-8")
    (folder / "deep" / "deeper" / "kept.md").write_text(
        "---\nid: kept\ntitle: Kept\ngroup: TEST\n---\n\n# Kept\n", encoding="utf-8")
    (folder / "deep" / "other.txt").write_text("---\nid: not-markdown\n---\n",
                                               encoding="utf-8")
    found = kb.entries((str(folder),))
    assert [(entry["id"], entry["title"], entry["group"]) for entry in found] == [
        ("kept", "Kept", "TEST")]
