"""Tests for the knowledge base server (Track D, step D6).

Appendix A2.4 "Knowledge base" names a read-only server with five tools, an
overview of the corpus, search, a list of entries, a full entry, and an
entry's origin, and the proposal (Approach paragraph 4) lets the scholar see
which entries the harness retrieves. The server, workflow-kb, keeps the
outside server's five tool names and arguments (Track D choice 9). By the
reconciliation (Track D, D6), it answers each call by writing request.json
beside a copy of a kb-index export and running the knowledge base graph,
verification_procedures/graphs/mcp_kb.yaml, through vg.py run, with the run
folder under <connections home>/kb_runs/. It keeps no copy of the outside
server's kb.py and no call log of its own.

The export is made with the audit layer's own command, python3 -m
audit_layer.kb export, from the synthetic corpus of three entries in two
groups that the graph's tests use, verification_procedures/fixtures/mcp_kb/
corpus, read only. Every test runs with HOME, CONNECTIONS_HOME, and
AUDIT_HOME inside a temporary folder. Nothing here calls a model or the
network. Run from the repository root with python3 -m pytest -q
connections/tests.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from connections.mcp import kb_server  # noqa: E402
from connections.mcp.kb_server import tools  # noqa: E402
from connections.mcp.protocol import handle  # noqa: E402

CORPUS = ROOT / "verification_procedures" / "fixtures" / "mcp_kb" / "corpus"
REPO_CORPUS = ROOT / "audit_layer" / "kb" / "corpus"
TOOLS = ["get_entry", "list_entries", "lookup_provenance", "orient_kb", "search_kb"]
FRONTMATTER = {"id", "title", "source", "source_commit", "updated", "group"}


@pytest.fixture(autouse=True)
def homes(tmp_path, monkeypatch):
    user = tmp_path / "user"
    user.mkdir()
    monkeypatch.setenv("HOME", str(user))
    monkeypatch.setenv("CONNECTIONS_HOME", str(tmp_path / "connections_home"))
    monkeypatch.setenv("AUDIT_HOME", str(tmp_path / "audit_home"))
    return tmp_path


def export(corpus, out):
    done = subprocess.run(
        [sys.executable, "-m", "audit_layer.kb", "export", "--corpus", str(corpus), "--out", str(out)],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    assert done.returncode == 0, done.stderr
    return Path(out)


@pytest.fixture(scope="module")
def made_export(tmp_path_factory):
    return export(CORPUS, tmp_path_factory.mktemp("export") / "kb_index.json")


@pytest.fixture
def index(made_export, tmp_path):
    """A copy of the export, which the server reads at its path."""
    path = tmp_path / "server_inputs" / "kb_index.json"
    path.parent.mkdir()
    shutil.copy2(str(made_export), str(path))
    return path


def by_name(index_path):
    return {tool.name: tool.handler for tool in tools(index_path)}


def call(index_path, name, **arguments):
    return by_name(index_path)[name](**arguments)


def protocol_call(index_path, name, arguments):
    """The reply the protocol layer gives a tools/call, and the answer its text holds."""
    reply = handle(
        {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
         "params": {"name": name, "arguments": arguments}},
        kb_server.SERVER_NAME, kb_server.SERVER_VERSION, tools(index_path),
    )
    result = reply["result"]
    return result["isError"], json.loads(result["content"][0]["text"])


def runs_folder():
    return Path(os.environ["CONNECTIONS_HOME"]) / "kb_runs"


def runs():
    folder = runs_folder()
    return sorted(p for p in folder.iterdir() if p.is_dir()) if folder.exists() else []


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# The five tools.


def test_the_server_offers_the_outside_servers_five_tools_with_their_arguments(index):
    found = {tool.name: tool.input_schema for tool in tools(index)}
    assert sorted(found) == TOOLS
    props = {name: schema.get("properties", {}) for name, schema in found.items()}
    assert props["orient_kb"] == {}
    assert {k: v["type"] for k, v in props["search_kb"].items()} == {
        "query": "string", "group": "string", "limit": "integer",
    }
    assert {k: v["type"] for k, v in props["list_entries"].items()} == {"group": "string"}
    assert {k: v["type"] for k, v in props["get_entry"].items()} == {"id": "string"}
    assert {k: v["type"] for k, v in props["lookup_provenance"].items()} == {"id": "string"}
    assert found["search_kb"]["required"] == ["query"]
    assert found["get_entry"]["required"] == ["id"]
    assert found["lookup_provenance"]["required"] == ["id"]
    assert not found["list_entries"].get("required")
    assert kb_server.SERVER_NAME == "workflow-kb"


def test_the_overview_counts_groups_and_entries(index):
    answer = call(index, "orient_kb")
    assert answer["entry_count"] == 3
    assert answer["groups"] == {"FORMATS": 2, "LOOP": 1}
    assert [e["id"] for e in answer["index"]] == ["formats-ledger", "formats-manifest", "loop-review"]
    assert answer["title"] == "Synthetic knowledge base for the server graph"


def test_search_ranks_a_title_match_first(index):
    answer = call(index, "search_kb", query="ledger")
    assert answer["results"][0]["id"] == "formats-ledger"
    assert answer["results"][0]["score"] >= max(r["score"] for r in answer["results"])


def test_search_filters_by_group_and_takes_a_limit(index):
    answer = call(index, "search_kb", query="build", group="LOOP")
    assert [r["group"] for r in answer["results"]] == ["LOOP"] * len(answer["results"])
    assert answer["results"]
    assert len(call(index, "search_kb", query="the", limit=1)["results"]) == 1


def test_list_entries_lists_every_entry_or_one_group(index):
    assert [e["id"] for e in call(index, "list_entries")["entries"]] == [
        "formats-ledger", "formats-manifest", "loop-review",
    ]
    assert [e["id"] for e in call(index, "list_entries", group="LOOP")["entries"]] == ["loop-review"]


def test_get_entry_returns_every_frontmatter_key_and_the_body(index):
    entry = call(index, "get_entry", id="loop-review")
    assert set(entry) == FRONTMATTER | {"body"}
    assert entry["group"] == "LOOP"
    assert entry["source"] == "docs/review.md"
    assert "The scholar reviews each build in Word" in entry["body"]


def test_an_unknown_id_gives_the_not_found_envelope_marked_as_an_error(index):
    assert call(index, "get_entry", id="no-such-entry")["error"]["code"] == "not_found"
    failed, answer = protocol_call(index, "get_entry", {"id": "no-such-entry"})
    assert failed is True
    assert answer["error"]["code"] == "not_found"
    failed, answer = protocol_call(index, "lookup_provenance", {"id": "no-such-entry"})
    assert (failed, answer["error"]["code"]) == (True, "not_found")


def test_lookup_provenance_returns_the_id_source_commit_and_date(index):
    assert call(index, "lookup_provenance", id="formats-ledger") == {
        "id": "formats-ledger",
        "source": "docs/ledger.md",
        "source_commit": "sha256:111111111111",
        "updated": "2026-10-01",
    }


def test_a_limit_the_graph_refuses_comes_back_as_its_refusal(index):
    failed, answer = protocol_call(index, "search_kb", {"query": "ledger", "limit": 0})
    assert failed is True
    assert answer["error"]["code"] == "bad_request"
    assert "limit" in answer["error"]["message"]


def test_a_wrong_type_is_refused_by_the_protocol_layer_before_any_run(index):
    failed, answer = protocol_call(index, "get_entry", {"id": 3})
    assert failed is True
    assert answer["error"]["code"] == "invalid_argument"
    assert runs() == []


# Each call is one run of the graph.


def test_each_call_leaves_one_run_folder_holding_the_call_and_the_index(index):
    call(index, "get_entry", id="loop-review")
    call(index, "search_kb", query="ledger")
    found = runs()
    assert len(found) == 2
    first = found[0] if "get_entry" in found[0].name else found[1]
    files = first / "files"
    assert json.loads((files / "request.json").read_text()) == {
        "tool": "get_entry", "arguments": {"id": "loop-review"},
    }
    assert digest(files / "kb_index.json") == digest(index)
    response = json.loads((files / "response.json").read_text())
    assert response["tool"] == "get_entry"
    manifest = json.loads((first / "manifest.json").read_text())
    assert manifest["stream"] == "mcp_kb"
    assert manifest["graph"]["path"] == "graphs/mcp_kb.yaml"
    assert manifest["inputs"] == {
        "kb_index.json": "sha256:" + digest(index),
        "request.json": "sha256:" + digest(files / "request.json"),
    }
    # The run's findings name the entry returned.
    findings = json.loads((files / "findings.json").read_text())
    assert any("loop-review" in f["message"] for f in findings)


def test_a_run_replays_with_vg_verify(index):
    call(index, "orient_kb")
    (run,) = runs()
    done = subprocess.run(
        [sys.executable, str(ROOT / "verification_procedures" / "vg.py"), "verify", "--run", str(run)],
        cwd=str(ROOT / "verification_procedures"), capture_output=True, text=True,
    )
    assert done.returncode == 0, done.stdout + done.stderr


def test_arguments_left_out_are_not_sent(index):
    call(index, "search_kb", query="ledger")
    (run,) = runs()
    assert json.loads((run / "files" / "request.json").read_text()) == {
        "tool": "search_kb", "arguments": {"query": "ledger"},
    }


def test_the_export_is_read_on_each_call_so_a_new_one_shows_without_a_restart(index):
    handlers = by_name(index)
    assert handlers["orient_kb"]()["entry_count"] == 3
    data = json.loads(index.read_text())
    extra = dict(data["entries"][0], id="formats-extra", title="An extra entry")
    data["entries"].append(extra)
    index.write_text(json.dumps(data))
    assert handlers["orient_kb"]()["entry_count"] == 4
    assert handlers["get_entry"](id="formats-extra")["title"] == "An extra entry"


def test_a_missing_export_gives_the_graphs_bad_index_refusal_and_a_run(tmp_path):
    failed, answer = protocol_call(tmp_path / "no_export.json", "list_entries", {})
    assert failed is True
    assert answer["error"]["code"] == "bad_index"
    assert len(runs()) == 1


def test_an_export_that_is_not_kb_index_version_1_is_refused_as_bad_index(index):
    index.write_text(json.dumps({"schema": "kb-index", "schema_version": 2, "entries": []}))
    failed, answer = protocol_call(index, "orient_kb", {})
    assert (failed, answer["error"]["code"]) == (True, "bad_index")


def test_a_run_that_cannot_finish_is_a_failed_tool_call(index, monkeypatch, tmp_path):
    monkeypatch.setattr(kb_server, "GRAPH", tmp_path / "missing_graph.yaml")
    failed, answer = protocol_call(index, "orient_kb", {})
    assert failed is True
    assert answer["error"]["code"] == "tool_failed"


def test_the_export_and_the_corpus_are_never_changed(index):
    before_index = digest(index)
    before_corpus = {str(p): digest(p) for p in sorted(CORPUS.rglob("*")) if p.is_file()}
    for name, arguments in (
        ("orient_kb", {}), ("search_kb", {"query": "build"}), ("list_entries", {}),
        ("get_entry", {"id": "loop-review"}), ("lookup_provenance", {"id": "loop-review"}),
    ):
        call(index, name, **arguments)
    assert digest(index) == before_index
    assert {str(p): digest(p) for p in sorted(CORPUS.rglob("*")) if p.is_file()} == before_corpus


def test_the_server_writes_no_call_log_and_nothing_outside_its_runs(index, homes):
    call(index, "get_entry", id="loop-review")
    home = Path(os.environ["CONNECTIONS_HOME"])
    assert sorted(p.name for p in home.iterdir()) == ["kb_runs"]
    assert not (home / "events").exists()


# The command, over standard input and output.


MESSAGES = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize",
     "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"}}},
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
     "params": {"name": "get_entry", "arguments": {"id": "formats-manifest"}}},
]


def serve_kb(messages, *options):
    lines = "".join(json.dumps(m) + "\n" for m in messages)
    done = subprocess.run(
        [sys.executable, "-m", "connections", "serve", "kb"] + [str(o) for o in options],
        cwd=str(ROOT), env=dict(os.environ), input=lines,
        capture_output=True, text=True, timeout=120,
    )
    assert done.returncode == 0, done.stderr
    return [json.loads(line) for line in done.stdout.splitlines()]


def test_serve_kb_answers_over_standard_input_and_output(index):
    replies = serve_kb(MESSAGES, "--index", index)
    assert [r["id"] for r in replies] == [1, 2, 3]
    assert replies[0]["result"]["serverInfo"]["name"] == "workflow-kb"
    assert replies[0]["result"]["protocolVersion"] == "2025-03-26"
    assert sorted(t["name"] for t in replies[1]["result"]["tools"]) == TOOLS
    assert replies[2]["result"]["isError"] is False
    entry = json.loads(replies[2]["result"]["content"][0]["text"])
    assert entry["id"] == "formats-manifest"
    assert len(runs()) == 1


def test_serve_kb_needs_the_index_option():
    done = subprocess.run(
        [sys.executable, "-m", "connections", "serve", "kb"],
        cwd=str(ROOT), env=dict(os.environ), input="", capture_output=True, text=True, timeout=60,
    )
    assert done.returncode == 2
    assert "--index" in done.stderr
    assert done.stdout == ""


def test_the_repositorys_own_corpus_serves_every_entry_it_lists(tmp_path):
    exported = export(REPO_CORPUS, tmp_path / "repo_index.json")
    listed = [e["id"] for e in call(exported, "list_entries")["entries"]]
    assert listed
    files = sorted(p for p in REPO_CORPUS.rglob("*.md") if p.parent != REPO_CORPUS)
    assert len(listed) == len(files)
    messages = [
        {"jsonrpc": "2.0", "id": n, "method": "tools/call",
         "params": {"name": "get_entry", "arguments": {"id": entry_id}}}
        for n, entry_id in enumerate(listed, start=1)
    ]
    replies = serve_kb(messages, "--index", exported)
    got = [json.loads(r["result"]["content"][0]["text"]) for r in replies]
    assert [r["result"]["isError"] for r in replies] == [False] * len(listed)
    assert [g["id"] for g in got] == listed


def test_the_server_imports_no_other_layer_and_holds_no_copy_of_kb_py():
    source = Path(kb_server.__file__).read_text(encoding="utf-8")
    for layer in ("audit_layer", "ospipe", "verification_procedures", "observability", "features"):
        assert "import " + layer not in source and "from " + layer not in source
    assert not (ROOT / "connections" / "mcp" / "kb.py").exists()
