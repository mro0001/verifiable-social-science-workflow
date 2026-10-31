"""The knowledge base server, workflow-kb, which answers each call by running the knowledge base graph.

Appendix A2.4 "Knowledge base" names a read-only server with five tools, an
overview of the corpus, search, a list of entries, a full entry, and an
entry's origin, and a session finds a procedure through the server's search.
The proposal stores procedural graphs in a queryable knowledge base (Approach
paragraph 1) and lets the scholar see which entries the harness retrieves
(Approach paragraph 4).

The server keeps the outside server's five tool names and arguments, so a
session that knows that server finds the same tools (Track D choice 9). It
holds no search or entry code of its own. Each call is answered by one run of
the knowledge base graph, verification_procedures/graphs/mcp_kb.yaml, through
vg.py run (reconciliation, Track D, D6). The server writes the call as
request.json beside a copy of the kb-index export, kb_index.json, in a new
inputs folder, runs the graph with the run folder under
<connections home>/kb_runs/, and gives back the result in the run's
response.json. Every call so leaves a run folder that shows what was asked,
the index it was answered from, and which entries came back.

The export is read on each call at the path the server was given, so a new
export shows without a restart. The server reads the export and never writes
it, and it reaches the graph only through vg.py's command line, so it imports
no other layer's code. It keeps no log of its own (reconciliation, item 6).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from connections.home import connections_home
from connections.mcp.protocol import Tool

SERVER_NAME = "workflow-kb"
SERVER_VERSION = "0.1.0"

# The verification procedures of this repository, found from this file's own
# place. The server runs vg.py and names the graph by its path, and reads
# nothing else of that layer.
PROCEDURES = Path(__file__).resolve().parents[2] / "verification_procedures"
VG = PROCEDURES / "vg.py"
GRAPH = PROCEDURES / "graphs" / "mcp_kb.yaml"

RUNS_FOLDER = "kb_runs"

# The names the graph reads its inputs under.
REQUEST = "request.json"
INDEX = "kb_index.json"
RESPONSE = "response.json"


def tools(index_path) -> List[Tool]:
    """The five tools, each answering from the kb-index export at index_path."""
    index = Path(index_path)

    def orient_kb():
        return answer(index, "orient_kb", {})

    def search_kb(query, group=None, limit=None):
        return answer(index, "search_kb", _given(query=query, group=group, limit=limit))

    def list_entries(group=None):
        return answer(index, "list_entries", _given(group=group))

    def get_entry(id):  # noqa: A002, the outside server's argument name
        return answer(index, "get_entry", {"id": id})

    def lookup_provenance(id):  # noqa: A002, the outside server's argument name
        return answer(index, "lookup_provenance", {"id": id})

    return [
        Tool(
            "orient_kb",
            "An overview of the knowledge base, its title, description, entry count,"
            " the count in each group, and every entry's id, title, group, and description.",
            {"type": "object", "properties": {}},
            orient_kb,
        ),
        Tool(
            "search_kb",
            "Search the entries for the words of a query, best match first, each with a"
            " snippet of its body. A group keeps only that group's entries, and a limit"
            " from 1 to 50 caps the results (10 when not given).",
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "the words to search for"},
                    "group": {"type": "string", "description": "only entries of this group"},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50,
                        "description": "the most results to give, 10 when not given",
                    },
                },
                "required": ["query"],
            },
            search_kb,
        ),
        Tool(
            "list_entries",
            "List every entry's id, title, and group, sorted by id, or only one group's.",
            {
                "type": "object",
                "properties": {
                    "group": {"type": "string", "description": "only entries of this group"},
                },
            },
            list_entries,
        ),
        Tool(
            "get_entry",
            "One entry whole, its frontmatter fields and its body.",
            {
                "type": "object",
                "properties": {"id": {"type": "string", "description": "the entry's id"}},
                "required": ["id"],
            },
            get_entry,
        ),
        Tool(
            "lookup_provenance",
            "Where one entry came from, its source, the source's checksum, and the date it"
            " was updated.",
            {
                "type": "object",
                "properties": {"id": {"type": "string", "description": "the entry's id"}},
                "required": ["id"],
            },
            lookup_provenance,
        ),
    ]


def _given(**arguments) -> Dict[str, Any]:
    """The arguments the client gave, leaving out those it did not."""
    return {name: value for name, value in arguments.items() if value is not None}


def answer(index: Path, tool: str, arguments: Dict[str, Any]) -> Any:
    """Answer one call by one run of the knowledge base graph, and give the response's result.

    The run folder is <connections home>/kb_runs/<run id>. An export that
    cannot be read is given to the graph as an empty kb_index.json, so the
    graph's own refusal, bad_index, answers the call and the run shows it. A
    run that does not finish with a response raises, naming its run folder.
    """
    runs = connections_home() / RUNS_FOLDER
    runs.mkdir(parents=True, exist_ok=True)
    run = runs / _run_id(tool)
    with tempfile.TemporaryDirectory(prefix="kb_call_") as inputs:
        with open(os.path.join(inputs, REQUEST), "w", encoding="utf-8") as f:
            json.dump({"tool": tool, "arguments": arguments}, f, ensure_ascii=False, sort_keys=True)
            f.write("\n")
        try:
            shutil.copyfile(str(index), os.path.join(inputs, INDEX))
        except OSError:
            Path(inputs, INDEX).write_bytes(b"")
        done = subprocess.run(
            [sys.executable, str(VG), "run", str(GRAPH), "--run", str(run), "--inputs", inputs],
            cwd=str(PROCEDURES),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
        )
    response = run / "files" / RESPONSE
    if done.returncode != 0 or not response.is_file():
        said = (done.stderr or done.stdout).strip().splitlines()
        raise RuntimeError(
            "the knowledge base graph did not answer the call, run folder {}{}".format(
                run, ", " + said[-1] if said else ""
            )
        )
    with open(str(response), encoding="utf-8") as f:
        return json.load(f)["result"]


def _run_id(tool: str) -> str:
    """A new run folder's name, the local time, the tool, and 8 random hex characters."""
    return "{}_{}_{}".format(datetime.now().strftime("%Y%m%dT%H%M%S"), tool, uuid.uuid4().hex[:8])
