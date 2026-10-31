"""The knowledge base server written as a procedural graph (graphs/mcp_kb.yaml).

Each case writes request.json beside a copy of the fixture index in a temporary
inputs folder and runs the graph with vg.py, as the process that serves the
graph will once per call.

The fixture index fixtures/mcp_kb/kb_index.json was made once from the
synthetic corpus fixtures/mcp_kb/corpus/ with the knowledge base's own export,
run from the repository root, and committed:

    python3 -m audit_layer.kb export --corpus verification_procedures/fixtures/mcp_kb/corpus \
        --out verification_procedures/fixtures/mcp_kb/kb_index.json

The tests read the index file only, never the corpus, since the graph answers
from the index given with the call.
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VG = [sys.executable, str(ROOT / "vg.py")]
FIX = ROOT / "fixtures" / "mcp_kb"
GRAPH = "graphs/mcp_kb.yaml"
ANSWERS = ("orient_kb", "search_kb", "list_entries", "get_entry", "lookup_provenance", "refuse")


def skipped_but(*ran_nodes):
    return sorted(n for n in ANSWERS if n not in ran_nodes)


def vg(*args):
    return subprocess.run(VG + list(args), cwd=ROOT, capture_output=True, text=True)


def call(tmp_path, request, index=None):
    """Run the graph on one call and return the run folder. request is an object
    written as JSON, or text written as it is. index replaces the fixture index."""
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    if isinstance(request, str):
        (inputs / "request.json").write_text(request, encoding="utf-8")
    else:
        (inputs / "request.json").write_text(json.dumps(request), encoding="utf-8")
    if index is None:
        shutil.copy2(FIX / "kb_index.json", inputs / "kb_index.json")
    elif isinstance(index, str):
        (inputs / "kb_index.json").write_text(index, encoding="utf-8")
    else:
        (inputs / "kb_index.json").write_text(json.dumps(index), encoding="utf-8")
    run = tmp_path / "run"
    p = vg("run", GRAPH, "--run", str(run), "--inputs", str(inputs))
    assert p.returncode == 0, p.stdout + p.stderr
    return run


def read(run, name):
    return json.loads((run / "files" / name).read_text(encoding="utf-8"))


def ran(run):
    events = [json.loads(line) for line in (run / "trail.jsonl").read_text().splitlines()]
    return ([e["node"] for e in events if e["event"] == "step_finished"],
            [e["node"] for e in events if e["event"] == "step_skipped"])


def fixture_index():
    return json.loads((FIX / "kb_index.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- the graph

def test_graph_passes_check():
    p = vg("check", GRAPH)
    assert p.returncode == 0, p.stdout + p.stderr
    assert p.stdout.startswith("OK: 8 nodes")


def test_graph_is_version_0_2_with_a_branch_per_tool():
    import yaml
    graph = yaml.safe_load((ROOT / GRAPH).read_text(encoding="utf-8"))
    assert graph["version"] == 0.2
    checks = {e["to"]: e["check"] for e in graph["edges"] if e["from"] == "read_request"}
    assert checks == {n: "request_ok.json:route == " + n for n in ANSWERS}
    assert sorted(e["from"] for e in graph["edges"] if e["to"] == "respond") == sorted(ANSWERS)


def test_fixture_index_is_a_kb_index_of_three_entries_in_two_groups():
    index = fixture_index()
    assert (index["schema"], index["schema_version"]) == ("kb-index", 1)
    assert [e["id"] for e in index["entries"]] == ["formats-ledger", "formats-manifest", "loop-review"]
    assert sorted({e["group"] for e in index["entries"]}) == ["FORMATS", "LOOP"]
    assert (FIX / "corpus" / "llms.txt").is_file()


# ---------------------------------------------------------------- list_entries

def test_list_entries_without_a_group(tmp_path):
    run = call(tmp_path, {"tool": "list_entries", "arguments": {}})
    assert read(run, "response.json") == {"tool": "list_entries", "result": {"entries": [
        {"id": "formats-ledger", "title": "The build ledger", "group": "FORMATS"},
        {"id": "formats-manifest", "title": "The numbers manifest", "group": "FORMATS"},
        {"id": "loop-review", "title": "The review loop", "group": "LOOP"}]}}
    answer = read(run, "answer.json")
    assert answer["returned"] == ["formats-ledger", "formats-manifest", "loop-review"]
    finished, skipped = ran(run)
    assert finished == ["read_request", "list_entries", "respond"]
    assert sorted(skipped) == skipped_but("list_entries")


def test_list_entries_with_a_group(tmp_path):
    run = call(tmp_path, {"tool": "list_entries", "arguments": {"group": "LOOP"}})
    result = read(run, "response.json")["result"]
    assert result == {"entries": [{"id": "loop-review", "title": "The review loop", "group": "LOOP"}]}
    assert read(run, "answer.json")["returned"] == ["loop-review"]


def test_list_entries_with_a_group_no_entry_has(tmp_path):
    run = call(tmp_path, {"tool": "list_entries", "arguments": {"group": "NONE"}})
    assert read(run, "response.json")["result"] == {"entries": []}
    assert read(run, "answer.json")["returned"] == []


# ---------------------------------------------------------------- get_entry

def test_get_entry_for_a_known_id(tmp_path):
    run = call(tmp_path, {"tool": "get_entry", "arguments": {"id": "loop-review"}})
    result = read(run, "response.json")["result"]
    row = next(e for e in fixture_index()["entries"] if e["id"] == "loop-review")
    assert sorted(result) == ["body", "group", "id", "source", "source_commit", "title", "updated"]
    for key in ("id", "title", "source", "source_commit", "updated", "group", "body"):
        assert result[key] == row[key]
    assert result["body"].startswith("# The review loop\n\n")
    assert result["body"].endswith("on the next build.")
    assert read(run, "answer.json")["returned"] == ["loop-review"]
    finished, _ = ran(run)
    assert finished == ["read_request", "get_entry", "respond"]


def test_get_entry_for_an_unknown_id(tmp_path):
    run = call(tmp_path, {"tool": "get_entry", "arguments": {"id": "loop-missing"}})
    assert read(run, "response.json")["result"] == {
        "error": {"code": "not_found", "message": "No entry with id 'loop-missing'"}}
    assert read(run, "answer.json")["returned"] == []


# ---------------------------------------------------------------- lookup_provenance

def test_lookup_provenance(tmp_path):
    run = call(tmp_path, {"tool": "lookup_provenance", "arguments": {"id": "formats-manifest"}})
    assert read(run, "response.json") == {"tool": "lookup_provenance", "result": {
        "id": "formats-manifest", "source": "docs/manifest.md",
        "source_commit": "sha256:222222222222", "updated": "2026-10-02"}}
    assert read(run, "answer.json")["returned"] == ["formats-manifest"]


def test_lookup_provenance_for_an_unknown_id(tmp_path):
    run = call(tmp_path, {"tool": "lookup_provenance", "arguments": {"id": "nope"}})
    assert read(run, "response.json")["result"] == {
        "error": {"code": "not_found", "message": "No entry with id 'nope'"}}


# ---------------------------------------------------------------- refusals

def assert_refused(run, code):
    ok = read(run, "request_ok.json")
    assert ok["route"] == "refuse" and ok["error_code"] == code and ok["problem"]
    result = read(run, "response.json")["result"]
    assert result == {"error": {"code": code, "message": ok["problem"]}}
    assert read(run, "answer.json")["returned"] == []
    finished, skipped = ran(run)
    assert finished == ["read_request", "refuse", "respond"]
    assert sorted(skipped) == skipped_but("refuse")
    warnings = [f for f in read(run, "findings_read_request.json") if f["severity"] == "warning"]
    assert len(warnings) == 1 and warnings[0]["message"] == ok["problem"]
    assert any(f["severity"] == "warning" for f in read(run, "findings.json"))
    return ok


def test_unknown_tool_is_refused(tmp_path):
    ok = assert_refused(call(tmp_path, {"tool": "delete_entry", "arguments": {"id": "loop-review"}}),
                        "bad_request")
    assert "delete_entry" in ok["problem"]
    assert ok["tool"] == "delete_entry"


def test_missing_id_is_refused(tmp_path):
    ok = assert_refused(call(tmp_path, {"tool": "get_entry", "arguments": {}}), "bad_request")
    assert "id" in ok["problem"]


def test_mistyped_id_is_refused(tmp_path):
    assert_refused(call(tmp_path, {"tool": "lookup_provenance", "arguments": {"id": 7}}), "bad_request")


def test_mistyped_group_is_refused(tmp_path):
    assert_refused(call(tmp_path, {"tool": "list_entries", "arguments": {"group": ["LOOP"]}}),
                   "bad_request")


def test_unexpected_argument_is_refused(tmp_path):
    ok = assert_refused(call(tmp_path, {"tool": "get_entry",
                                        "arguments": {"id": "loop-review", "full": True}}),
                        "bad_request")
    assert "full" in ok["problem"]


def test_unreadable_request_is_refused(tmp_path):
    ok = assert_refused(call(tmp_path, '{"tool": "get_entry", "arguments": '), "bad_request")
    assert ok["tool"] == ""


def test_request_that_is_not_an_object_with_tool_and_arguments_is_refused(tmp_path):
    assert_refused(call(tmp_path, ["get_entry"]), "bad_request")


def test_index_with_the_wrong_schema_is_refused(tmp_path):
    index = fixture_index()
    index["schema"] = "kb-other"
    ok = assert_refused(call(tmp_path, {"tool": "list_entries", "arguments": {}}, index=index),
                        "bad_index")
    assert ok["tool"] == "list_entries"


def test_index_with_the_wrong_schema_version_is_refused(tmp_path):
    index = fixture_index()
    index["schema_version"] = 2
    assert_refused(call(tmp_path, {"tool": "list_entries", "arguments": {}}, index=index), "bad_index")


def test_unreadable_index_is_refused(tmp_path):
    assert_refused(call(tmp_path, {"tool": "list_entries", "arguments": {}}, index="{not json"),
                   "bad_index")


# ---------------------------------------------------------------- orient_kb

def test_orient_kb_gives_the_counts_and_the_index(tmp_path):
    run = call(tmp_path, {"tool": "orient_kb", "arguments": {}})
    result = read(run, "response.json")["result"]
    assert result["title"] == "Synthetic knowledge base for the server graph"
    assert result["description"] == "Three made-up entries for the mcp_kb tests."
    assert result["entry_count"] == 3
    assert result["groups"] == {"FORMATS": 2, "LOOP": 1}
    assert result["index"] == [
        {"id": "formats-ledger", "title": "The build ledger", "group": "FORMATS",
         "description": "The build ledger holds one row per numbered build."},
        {"id": "formats-manifest", "title": "The numbers manifest", "group": "FORMATS",
         "description": "The numbers manifest maps each placeholder key to the output that produced it."},
        {"id": "loop-review", "title": "The review loop", "group": "LOOP",
         "description": "The scholar reviews each build in Word and hands it back."}]
    assert read(run, "answer.json")["returned"] == ["formats-ledger", "formats-manifest", "loop-review"]
    finished, skipped = ran(run)
    assert finished == ["read_request", "orient_kb", "respond"]
    assert sorted(skipped) == skipped_but("orient_kb")


def test_orient_kb_takes_no_arguments(tmp_path):
    assert_refused(call(tmp_path, {"tool": "orient_kb", "arguments": {"group": "LOOP"}}), "bad_request")


# ---------------------------------------------------------------- search_kb

def search(tmp_path, **arguments):
    run = call(tmp_path, {"tool": "search_kb", "arguments": arguments})
    finished, skipped = ran(run)
    assert finished == ["read_request", "search_kb", "respond"]
    assert sorted(skipped) == skipped_but("search_kb")
    results = read(run, "response.json")["result"]["results"]
    assert read(run, "answer.json")["returned"] == [r["id"] for r in results]
    return results


def test_search_hand_worked_case_scores_and_snippets_are_exact(tmp_path):
    # "ledger" is in formats-ledger's title (5), id (4), point (2), and body (1),
    # and only in formats-manifest's body (1), past its point. Each snippet is 140
    # characters of the body from 40 before the first "ledger", whitespace collapsed.
    assert search(tmp_path, query="ledger") == [
        {"id": "formats-ledger", "title": "The build ledger", "group": "FORMATS", "score": 12,
         "snippet": "# The build ledger The build ledger holds one row per numbered build. "
                    "Each row names the build's source hash. 1. A row is added after the"},
        {"id": "formats-manifest", "title": "The numbers manifest", "group": "FORMATS", "score": 1,
         "snippet": "ords the manifest beside its row in the ledger. ## Consult also - "
                    "formats-ledger - for the rows a build writes."}]


def test_search_title_match_outranks_body_only_match(tmp_path):
    results = search(tmp_path, query="LEDGER")
    assert [r["id"] for r in results] == ["formats-ledger", "formats-manifest"]
    assert results[0]["score"] > results[1]["score"]


def test_search_ties_fall_back_to_id_order(tmp_path):
    results = search(tmp_path, query="checks")
    assert [(r["id"], r["score"]) for r in results] == [("formats-ledger", 1), ("loop-review", 1)]


def test_search_snippet_falls_back_to_the_description(tmp_path):
    # "formats" is in both ids (4), and in formats-manifest's body (1), never in
    # formats-ledger's body, whose snippet is then its description.
    results = search(tmp_path, query="formats")
    assert [(r["id"], r["score"]) for r in results] == [("formats-manifest", 5), ("formats-ledger", 4)]
    assert results[1]["snippet"] == "The build ledger holds one row per numbered build."


def test_search_scores_each_token(tmp_path):
    # "review" adds 5 + 4 + 2 + 1 for loop-review ("reviews" in its point), and
    # "checks" adds 1 for it and for formats-ledger.
    results = search(tmp_path, query="review, checks!")
    assert [(r["id"], r["score"]) for r in results] == [("loop-review", 13), ("formats-ledger", 1)]


def test_search_group_filter_applies(tmp_path):
    first, second = tmp_path / "loop", tmp_path / "none"
    first.mkdir()
    second.mkdir()
    assert [r["id"] for r in search(first, query="checks", group="LOOP")] == ["loop-review"]
    assert search(second, query="checks", group="NONE") == []


def test_search_limit_applies(tmp_path):
    assert [r["id"] for r in search(tmp_path, query="checks", limit=1)] == ["formats-ledger"]


def test_search_limit_of_fifty_is_accepted(tmp_path):
    assert len(search(tmp_path, query="checks", limit=50)) == 2


def test_search_with_no_match_gives_empty_results(tmp_path):
    assert search(tmp_path, query="zebra") == []


def test_empty_query_is_refused(tmp_path):
    ok = assert_refused(call(tmp_path, {"tool": "search_kb", "arguments": {"query": ""}}), "bad_request")
    assert "query" in ok["problem"]


def test_blank_query_is_refused(tmp_path):
    assert_refused(call(tmp_path, {"tool": "search_kb", "arguments": {"query": "   "}}), "bad_request")


def test_missing_query_is_refused(tmp_path):
    assert_refused(call(tmp_path, {"tool": "search_kb", "arguments": {"group": "LOOP"}}), "bad_request")


def test_limit_out_of_range_or_not_a_whole_number_is_refused(tmp_path):
    for n, limit in enumerate([0, 51, 2.5, "5", True]):
        sub = tmp_path / str(n)
        sub.mkdir()
        ok = assert_refused(call(sub, {"tool": "search_kb", "arguments": {"query": "ledger", "limit": limit}}),
                            "bad_request")
        assert "limit" in ok["problem"]


def test_search_unexpected_argument_is_refused(tmp_path):
    assert_refused(call(tmp_path, {"tool": "search_kb", "arguments": {"query": "ledger", "rank": "model"}}),
                   "bad_request")


# ---------------------------------------------------------------- the response and the run

def test_response_findings_and_report_name_the_returned_entries(tmp_path):
    run = call(tmp_path, {"tool": "list_entries", "arguments": {"group": "FORMATS"}})
    findings = read(run, "findings.json")
    assert [f["severity"] for f in findings] == ["info"]
    assert "formats-ledger" in findings[0]["message"] and "formats-manifest" in findings[0]["message"]
    report = (run / "files" / "report.md").read_text(encoding="utf-8")
    for heading in ("## Summary", "## Problems", "## Call"):
        assert heading in report
    call_section = report.split("## Call", 1)[1].split("\n## ", 1)[0]
    assert "list_entries" in call_section and "FORMATS" in call_section
    assert "formats-ledger" in call_section and "formats-manifest" in call_section


def test_run_writes_only_inside_the_run_folder(tmp_path):
    before = sorted(p.name for p in FIX.iterdir())
    call(tmp_path, {"tool": "list_entries", "arguments": {}})
    assert sorted(p.name for p in FIX.iterdir()) == before
    assert sorted(p.name for p in (tmp_path / "inputs").iterdir()) == ["kb_index.json", "request.json"]


def test_verify_reports_replay_matches_for_every_step(tmp_path):
    for n, request in enumerate([{"tool": "list_entries", "arguments": {}},
                                 {"tool": "get_entry", "arguments": {"id": "formats-ledger"}},
                                 {"tool": "lookup_provenance", "arguments": {"id": "loop-review"}},
                                 {"tool": "unknown", "arguments": {}}]):
        sub = tmp_path / str(n)
        sub.mkdir()
        run = call(sub, request)
        p = vg("verify", "--run", str(run))
        assert p.returncode == 0, p.stdout + p.stderr
        lines = p.stdout.strip().splitlines()
        assert len(lines) == 3
        assert all(line.endswith("replay matches") for line in lines), p.stdout


def test_verify_reports_replay_matches_for_overview_and_search(tmp_path):
    for n, request in enumerate([{"tool": "orient_kb", "arguments": {}},
                                 {"tool": "search_kb", "arguments": {"query": "ledger", "limit": 2}},
                                 {"tool": "search_kb", "arguments": {"query": ""}}]):
        sub = tmp_path / str(n)
        sub.mkdir()
        run = call(sub, request)
        p = vg("verify", "--run", str(run))
        assert p.returncode == 0, p.stdout + p.stderr
        lines = p.stdout.strip().splitlines()
        assert len(lines) == 3
        assert all(line.endswith("replay matches") for line in lines), p.stdout


def test_no_code_imports_another_layer():
    pattern = re.compile(r"^\s*(import|from)\s+(audit_layer|ospipe|vg)\b")
    files = sorted((ROOT / "implementations" / "mcp_kb").glob("*.py"))
    assert files
    for path in files:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            assert not pattern.match(line), "{}:{} {}".format(path, number, line)
