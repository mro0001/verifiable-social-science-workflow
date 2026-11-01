"""Conformance test, the real corpus against the entry checker.

The shape rules live in the checker (audit_layer/kb/check.py), so this test
asks that the real corpus has entries and that the checker finds no problem in
it. It also checks the PROCEDURES group generated from the procedural graphs
and the hand-written entry for the authoring guide. Three of its checks cross
from the knowledge base to the verification layer, each through files and
command lines only, never an import. They are graph-entries --check on a fresh
copy of the graphs and contracts, made by hand and made by the graphs_to_kb.py
handoff, source-check against the repository, a search of an export of the
corpus through the knowledge base server's graph, and a comparison of each
registered procedure's input files with those vg.py procedures prints.
Run from the repository root with python3 -m pytest audit_layer/kb/tests.
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from audit_layer.kb import CORPUS  # noqa: E402
from audit_layer.kb.check import check_corpus  # noqa: E402
from audit_layer.kb.entries import entry_files, load  # noqa: E402

VERIFICATION = ROOT / "verification_procedures"
PROCEDURE_IDS = [
    "procedures-build",
    "procedures-citations",
    "procedures-data",
    "procedures-data-analysis",
    "procedures-data-cleaning",
    "procedures-data-collection",
    "procedures-llm-runs",
    "procedures-mcp-kb",
    "procedures-ops-github",
    "procedures-ops-hpc",
    "procedures-ops-publish",
    "procedures-prose",
    "procedures-selftest",
    "procedures-wrap-git",
]
GUIDE_ID = "guidelines-authoring-procedures"
FACTS = ("1. Purpose. ", "2. Triggers. ", "3. Steps. ", "4. Run command. ", "5. Version. ")
CONSULT_LINE = "- guidelines-authoring-procedures - to write a new procedure or revise this one."
DESCRIPTION = (
    "> Standards, capabilities, guidelines, and procedures of the reproducible, verifiable "
    "manuscript pipeline, distilled for any AI session to apply."
)


def kb(*args):
    return subprocess.run([sys.executable, "-m", "audit_layer.kb"] + list(args), cwd=str(ROOT),
                          capture_output=True, text=True)


def entries_by_id():
    return {entry["front"]["id"]: entry for entry in load(CORPUS)}


def consult_lines(body):
    lines = body.splitlines()
    if "## Consult also" not in lines:
        return []
    return [line for line in lines[lines.index("## Consult also") + 1:] if line.startswith("- ")]


def test_the_real_corpus_passes_the_checker():
    assert CORPUS == Path(__file__).resolve().parents[1] / "corpus"
    assert len(entry_files(CORPUS)) >= 3
    assert check_corpus(CORPUS) == []


def test_the_procedures_group_holds_one_entry_per_graph():
    entries = entries_by_id()
    ids = sorted(i for i, e in entries.items() if e["front"]["group"] == "PROCEDURES")
    assert ids == PROCEDURE_IDS
    graphs = sorted(p.stem.replace("_", "-") for p in (VERIFICATION / "graphs").glob("*.yaml"))
    assert ["procedures-" + g for g in graphs] == PROCEDURE_IDS
    for ident in PROCEDURE_IDS:
        entry = entries[ident]
        assert entry["rel"] == "procedures/{}.md".format(ident)
        source = entry["front"]["source"]
        assert source.startswith("verification_procedures/graphs/"), ident
        assert (ROOT / source).is_file(), ident
        lines = entry["body"].splitlines()
        assert [f for f in FACTS if not any(line.startswith(f) for line in lines)] == [], ident
        assert consult_lines(entry["body"]) == [CONSULT_LINE], ident


def test_the_authoring_guide_has_its_hand_written_entry():
    entry = entries_by_id()[GUIDE_ID]
    front = entry["front"]
    assert entry["rel"] == "guidelines/{}.md".format(GUIDE_ID)
    assert front["group"] == "GUIDELINES"
    assert front["source"] == "verification_procedures/AUTHORING.md"
    point = entry["point"]
    for words in ("graph", "contract", "code or a prompt", "test files", "vg.py check",
                  "planted fault", "AUTHORING.md"):
        assert words in point, words
    body = entry["body"]
    for words in ("replay: network", "graph-entries", "never edited by hand", "version"):
        assert words in body, words
    refs = [line[2:].split(" - ")[0] for line in consult_lines(body)]
    assert refs == ["procedures-llm-runs", "procedures-ops-github"]


def test_the_index_names_procedures_in_its_description_and_lists_them():
    text = (CORPUS / "llms.txt").read_text(encoding="utf-8")
    assert text.splitlines()[2] == DESCRIPTION
    assert "\n## PROCEDURES\n" in text
    for ident in PROCEDURE_IDS:
        assert "](procedures/{}.md): ".format(ident) in text
    assert "](guidelines/{}.md): ".format(GUIDE_ID) in text


def test_the_contract_names_every_group_in_use_and_every_command():
    contract = (CORPUS.parent / "CONTRACT.md").read_text(encoding="utf-8")
    groups = sorted({e["front"]["group"] for e in load(CORPUS)})
    assert groups == ["CAPABILITIES", "FORMATS", "GUIDELINES", "LOOP", "PROCEDURES", "VERIFICATION"]
    for group in groups:
        assert "`{}`".format(group) in contract, group
    for command in ("check", "llms", "export", "graph-entries", "source-check"):
        assert "python3 -m audit_layer.kb {}".format(command) in contract, command
    assert "mcp_kb" in contract


def test_graph_entries_check_on_a_fresh_copy_of_the_graphs_exits_0(tmp_path):
    copy = tmp_path / "procedures"
    shutil.copytree(str(VERIFICATION / "graphs"), str(copy / "graphs"))
    shutil.copytree(str(VERIFICATION / "contracts"), str(copy / "contracts"))
    # The registry gives each registered graph's title and triggers (reconciliation, G4).
    shutil.copy2(str(VERIFICATION / "registry.yaml"), str(copy / "registry.yaml"))
    p = kb("graph-entries", "--procedures", str(copy), "--check")
    assert p.returncode == 0, p.stdout + p.stderr
    assert p.stdout == ""



def test_graph_entries_check_on_a_fresh_graphs_to_kb_copy_exits_0(tmp_path):
    copy = tmp_path / "procedures"
    p = subprocess.run([sys.executable, str(ROOT / "handoffs" / "graphs_to_kb.py"),
                        "--procedures", str(VERIFICATION), "--to", str(copy)],
                       cwd=str(ROOT), capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
    p = kb("graph-entries", "--procedures", str(copy), "--check")
    assert p.returncode == 0, p.stdout + p.stderr
    assert p.stdout == ""


def entry_inputs(body):
    """The required and the other input files an entry's run command fact names.

    The fact reads "The inputs folder holds A, and B, and when present C, and any
    files matching D." Required are the names before "when present" or "any files
    matching", and the rest are the files the folder may hold.
    """
    line = [x for x in body.splitlines() if x.startswith("4. Run command. ")][0]
    if "The inputs folder needs no files." in line:
        return [], []
    sentence = line.split("The inputs folder ", 1)[1].split(". An executor is ")[0]
    cut = re.search(r"(?:holds |, and )(?:when present|any files matching) ", sentence)
    head = sentence[:cut.start()] if cut else sentence
    tail = sentence[cut.start():] if cut else ""
    return sorted(re.findall(r"`([^`]+)`", head)), sorted(re.findall(r"`([^`]+)`", tail))


def test_each_registered_procedure_entry_lists_the_inputs_vg_procedures_prints():
    p = subprocess.run([sys.executable, str(VERIFICATION / "vg.py"), "procedures"],
                       cwd=str(ROOT), capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
    printed = json.loads(p.stdout)
    assert printed, "vg.py procedures printed no procedure"
    entries = entries_by_id()
    for procedure in printed:
        ident = "procedures-" + Path(procedure["graph"]).stem.replace("_", "-")
        assert ident in entries, ident
        required = sorted(n for n in procedure["inputs"]["required"] if n != "steps.json")
        optional = sorted(n for n in procedure["inputs"]["optional"] if n != "steps.json")
        assert entry_inputs(entries[ident]["body"]) == (required, optional), ident

def test_source_check_reads_same_for_the_procedures_and_the_guide():
    p = kb("source-check", "--root", ".")
    status = {}
    for line in p.stdout.splitlines()[:-1]:
        word, ident, _source = line.split(" ", 2)
        status[ident] = word
    for ident in PROCEDURE_IDS + [GUIDE_ID]:
        assert status[ident] == "same", ident


def test_a_search_for_github_through_the_server_graph_finds_its_procedure_first(tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    p = kb("export", "--out", str(inputs / "kb_index.json"))
    assert p.returncode == 0, p.stdout + p.stderr
    request = {"tool": "search_kb", "arguments": {"query": "github"}}
    (inputs / "request.json").write_text(json.dumps(request), encoding="utf-8")
    run = tmp_path / "run"
    p = subprocess.run([sys.executable, "vg.py", "run", "graphs/mcp_kb.yaml", "--run", str(run),
                        "--inputs", str(inputs)], cwd=str(VERIFICATION), capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
    response = json.loads((run / "files" / "response.json").read_text(encoding="utf-8"))
    results = response["result"]["results"]
    assert results[0]["id"] == "procedures-ops-github"
