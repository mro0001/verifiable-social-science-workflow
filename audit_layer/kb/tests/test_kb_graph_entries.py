"""Tests for the knowledge base's generated graph entries (Track G plan, Steps G4 and G5).

Appendix A2.4 "Procedural graphs" says each graph gets an entry naming its
purpose, triggers, steps, and the command that runs it, so a session finds the
procedure through the knowledge base's search while the runtime runs it.
graph_entries.py writes that entry from the graph and its contract. For a
graph the procedure registry names, the title and triggers come from the
registry (reconciliation, Track G). Every graph, contract, registry, and
corpus here is synthetic, written by conftest.py. Run from the repository root
with python3 -m pytest audit_layer/kb/tests.
"""
import hashlib
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from audit_layer.kb.check import check_corpus  # noqa: E402
from audit_layer.kb.cli import main  # noqa: E402
from audit_layer.kb.entries import parse_entry  # noqa: E402
from audit_layer.kb.graph_entries import (  # noqa: E402
    entry_id,
    inputs_of,
    read_procedure,
    registry_entry,
    render_entry,
    runtime_order,
    sync,
)
from audit_layer.kb.index import write_llms  # noqa: E402

from conftest import REGISTRY, TWO_STEPS_GRAPH  # noqa: E402

KB = ROOT / "audit_layer" / "kb"
DATE = "2026-10-29"
POINT_TAIL = (
    "The procedural graph system runs it with the command below, so a session finds it "
    "here and does not carry out its steps by hand."
)
CONSULT = (
    "## Consult also\n\n"
    "- guidelines-authoring-procedures - to write a new procedure or revise this one.\n"
)


def render(procedures, name, consult=False, procedure=None):
    graph, contract, graph_bytes = read_procedure(procedures, name)
    return render_entry(name, graph, contract, graph_bytes, DATE, consult, procedure=procedure)


def short_sum(path):
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]


def two_steps_entry(commit):
    return (
        "---\n"
        "id: procedures-two-steps\n"
        "title: The word count procedure\n"
        "source: verification_procedures/graphs/two_steps.yaml\n"
        "source_commit: " + commit + "\n"
        "updated: 2026-10-29\n"
        "group: PROCEDURES\n"
        "---\n"
        "\n"
        "# The word count procedure\n"
        "\n"
        "Count the words in a words file and report the count. " + POINT_TAIL + "\n"
        "\n"
        "1. Purpose. Count the words in a words file and report the count. "
        "The count is kept for the next run.\n"
        "2. Triggers. A new words file arrives in the project. The scholar asks for a word count.\n"
        "3. Steps. 2 steps, in the order the runtime runs them, each only when a transition "
        "into it fires.\n"
        "   - `read_words` (tool step) Read the words file and count its words.\n"
        "   - `report_count` (tool step) Write the count to the report.\n"
        "4. Run command. From the `verification_procedures` folder, run "
        "`python3 vg.py run graphs/two_steps.yaml --run runs/<new run folder> "
        "--inputs <inputs folder>`. The inputs folder holds `words.txt`, and when present "
        "`stopwords.txt`.\n"
        "5. Version. Graph version 0.2, 2 steps and 1 transition, checked with "
        "`python3 vg.py check graphs/two_steps.yaml`.\n"
    )


# Reading a procedure.


def test_read_procedure_gives_the_graph_the_contract_and_the_bytes(make_procedures):
    procedures = make_procedures()
    graph, contract, graph_bytes = read_procedure(procedures, "two_steps.yaml")
    assert graph["stream"] == "wordcount"
    assert sorted(contract) == ["read_words", "report_count"]
    assert graph_bytes == (procedures / "graphs" / "two_steps.yaml").read_bytes()


def test_a_missing_contract_is_an_error_naming_both_files(make_procedures):
    procedures = make_procedures({"contracts/judged.yaml": None})
    with pytest.raises(ValueError) as caught:
        read_procedure(procedures, "judged.yaml")
    assert "graphs/judged.yaml" in str(caught.value)
    assert "contracts/judged.yaml" in str(caught.value)


def test_runtime_order_follows_the_transitions_not_the_node_list(make_procedures):
    procedures = make_procedures()
    graph, _, _ = read_procedure(procedures, "two_steps.yaml")
    assert [node["id"] for node in graph["nodes"]] == ["report_count", "read_words"]
    assert runtime_order(graph) == ["read_words", "report_count"]


def test_runtime_order_releases_targets_in_edge_order():
    graph = {
        "nodes": [{"id": "c"}, {"id": "a"}, {"id": "b"}, {"id": "d"}],
        "edges": [
            {"from": "a", "to": "c"},
            {"from": "a", "to": "b"},
            {"from": "b", "to": "d"},
            {"from": "c", "to": "d"},
        ],
    }
    assert runtime_order(graph) == ["a", "c", "b", "d"]


def test_inputs_come_from_the_contract_without_produced_files(make_procedures):
    procedures = make_procedures()
    graph, contract, _ = read_procedure(procedures, "two_steps.yaml")
    assert inputs_of(graph, contract) == (["words.txt"], ["stopwords.txt"], [])


def test_inputs_leave_out_steps_json_and_findings_patterns(make_procedures):
    procedures = make_procedures()
    graph, contract, _ = read_procedure(procedures, "judged.yaml")
    required, optional, patterns = inputs_of(graph, contract)
    assert required == ["claims_rules.yaml", "draft.md"]
    assert optional == ["notes.yaml"]
    assert patterns == ["source_*.txt"]


# The entry's id.


@pytest.mark.parametrize(
    "name,expected",
    [("two_steps.yaml", "procedures-two-steps"), ("judged.yaml", "procedures-judged"),
     ("ops_hpc2.yaml", "procedures-ops-hpc2")],
)
def test_entry_id_turns_underscores_into_hyphens(name, expected):
    assert entry_id(name) == expected


@pytest.mark.parametrize("name", ["Bad-Name.yaml", "bad-name.yaml", "Upper.yaml"])
def test_entry_id_refuses_a_stem_outside_lowercase_digits_and_underscores(name):
    with pytest.raises(ValueError) as caught:
        entry_id(name)
    assert name in str(caught.value)


# The rendered entry.


def test_the_whole_entry_for_a_graph_with_a_title_and_triggers(make_procedures):
    procedures = make_procedures()
    text = render(procedures, "two_steps.yaml")
    assert text == two_steps_entry(short_sum(procedures / "graphs" / "two_steps.yaml"))


def test_each_frontmatter_value(make_procedures, tmp_path):
    procedures = make_procedures()
    path = tmp_path / "procedures" / "procedures-judged.md"
    path.parent.mkdir()
    path.write_text(render(procedures, "judged.yaml"), encoding="utf-8")
    front = parse_entry(path, tmp_path)["front"]
    assert front == {
        "id": "procedures-judged",
        "title": "The claims procedure",
        "source": "verification_procedures/graphs/judged.yaml",
        "source_commit": short_sum(procedures / "graphs" / "judged.yaml"),
        "updated": DATE,
        "group": "PROCEDURES",
    }


def test_the_point_is_the_goals_first_sentence_and_the_runtime_line(make_procedures, tmp_path):
    procedures = make_procedures()
    path = tmp_path / "procedures" / "procedures-judged.md"
    path.parent.mkdir()
    path.write_text(render(procedures, "judged.yaml"), encoding="utf-8")
    entry = parse_entry(path, tmp_path)
    first = "Judge each open claim in a draft, then have a second checker look again."
    assert entry["point"] == first + " " + POINT_TAIL
    assert entry["description"] == first


def test_the_steps_carry_the_judgment_details_in_runtime_order(make_procedures):
    text = render(make_procedures(), "judged.yaml")
    steps = [line for line in text.splitlines() if line.startswith("   - ")]
    assert steps == [
        "   - `list_claims` (tool step) List the claims in the draft as items.",
        "   - `judge_claims` (judgment step, once per item in `claims.json` where status in [open])"
        " Say whether each claim holds.",
        "   - `second_look` (judgment step by the second checker, once per item in `claims.json`)"
        " Look again at each claim.",
        "   - `report` (tool step) Write findings and the report.",
    ]
    assert "3. Steps. 4 steps, in the order the runtime runs them" in text


def test_judge_and_second_appear_only_for_judgment_steps(make_procedures):
    procedures = make_procedures()
    judged = render(procedures, "judged.yaml")
    plain = render(procedures, "two_steps.yaml")
    assert "--inputs <inputs folder> --judge <executor> --second <executor>`." in judged
    assert "An executor is `recorded:<answers file>` or a model the runtime can reach." in judged
    assert "--judge" not in plain and "--second" not in plain
    assert "An executor is" not in plain


def test_judge_alone_when_no_step_has_the_second_role(make_procedures):
    graph = TWO_STEPS_GRAPH.replace(
        "{id: report_count, kind: tool,", "{id: report_count, kind: judgment,"
    )
    text = render(make_procedures({"graphs/two_steps.yaml": graph}), "two_steps.yaml")
    assert "--inputs <inputs folder> --judge <executor>`." in text
    assert "--second" not in text


def test_the_inputs_line_names_required_optional_and_patterns(make_procedures):
    text = render(make_procedures(), "judged.yaml")
    assert (
        "The inputs folder holds `claims_rules.yaml` and `draft.md`, and when present "
        "`notes.yaml`, and any files matching `source_*.txt`."
    ) in text
    assert "findings_" not in text
    assert "steps.json" not in text


def test_the_two_fallbacks_without_title_or_triggers(make_procedures):
    text = render(make_procedures(), "judged.yaml")
    assert "# The claims procedure\n" in text
    assert "2. Triggers. None declared in the graph.\n" in text


def test_the_version_line(make_procedures):
    text = render(make_procedures(), "judged.yaml")
    assert (
        "5. Version. Graph version 1.0, 4 steps and 3 transitions, checked with "
        "`python3 vg.py check graphs/judged.yaml`.\n"
    ) in text


def test_the_consult_line_only_when_asked(make_procedures):
    procedures = make_procedures()
    without = render(procedures, "two_steps.yaml", consult=False)
    with_line = render(procedures, "two_steps.yaml", consult=True)
    assert "## Consult also" not in without
    assert with_line == without + "\n" + CONSULT


def test_a_rendered_entry_passes_the_checker_in_a_corpus(make_procedures, make_corpus):
    procedures = make_procedures()
    corpus = make_corpus(
        {
            "procedures/procedures-two-steps.md": render(procedures, "two_steps.yaml"),
            "procedures/procedures-judged.md": render(procedures, "judged.yaml"),
        }
    )
    assert write_llms(corpus) is True
    assert check_corpus(corpus) == []
    assert "## PROCEDURES" in (corpus / "llms.txt").read_text(encoding="utf-8")


# Titles and triggers from the procedure registry.


def test_no_registry_names_nothing(make_procedures):
    assert registry_entry(make_procedures(), "judged.yaml") is None


def test_the_registry_names_its_graph(make_procedures):
    procedures = make_procedures({"registry.yaml": REGISTRY})
    entry = registry_entry(procedures, "judged.yaml")
    assert entry["procedure"] == "Claim review"
    assert registry_entry(procedures, "two_steps.yaml") is None


def test_a_registered_graph_takes_the_registry_title_and_triggers(make_procedures):
    procedures = make_procedures({"registry.yaml": REGISTRY})
    text = render(procedures, "judged.yaml", procedure=registry_entry(procedures, "judged.yaml"))
    assert "title: Claim review\n" in text
    assert "# Claim review\n" in text
    assert (
        "2. Triggers. It starts on the harness events `ai_edit` and `turn_end`. "
        "It starts on a request that uses the phrase \"check the claims\" or \"claim review\".\n"
    ) in text


def test_the_registry_wins_over_the_graph_keys(make_procedures):
    registry = REGISTRY + (
        "  - id: wordcount\n"
        "    stream: wordcount\n"
        "    name: Words\n"
        "    procedure: Word counting\n"
        "    graph: graphs/two_steps.yaml\n"
        "    triggers:\n"
        "      events: [build]\n"
        "      phrases: [count the words]\n"
        "      files: [\"*.txt\"]\n"
        "    quick_steps: [read_words]\n"
    )
    procedures = make_procedures({"registry.yaml": registry})
    text = render(procedures, "two_steps.yaml",
                  procedure=registry_entry(procedures, "two_steps.yaml"))
    assert "# Word counting\n" in text
    assert "The word count procedure" not in text
    assert (
        "2. Triggers. It starts on the harness event `build`. "
        "It starts on a request that uses the phrase \"count the words\".\n"
    ) in text
    assert "A new words file arrives" not in text


def test_a_graph_the_registry_does_not_name_keeps_its_keys(make_procedures):
    procedures = make_procedures({"registry.yaml": REGISTRY})
    text = render(procedures, "two_steps.yaml",
                  procedure=registry_entry(procedures, "two_steps.yaml"))
    assert text == two_steps_entry(short_sum(procedures / "graphs" / "two_steps.yaml"))


def test_a_registered_entry_passes_the_checker(make_procedures, make_corpus):
    procedures = make_procedures({"registry.yaml": REGISTRY})
    text = render(procedures, "judged.yaml", procedure=registry_entry(procedures, "judged.yaml"))
    corpus = make_corpus({"procedures/procedures-judged.md": text})
    write_llms(corpus)
    assert check_corpus(corpus) == []


# Keeping the procedures group in step with the graphs (Step G5).

AUTHORING = """---
id: guidelines-authoring-procedures
title: Writing a procedure
source: docs/authoring.md
source_commit: sha256:00112233aabb
updated: 2026-10-20
group: GUIDELINES
---

# Writing a procedure

A procedure is a graph, a contract, and code for each step.
"""


def snapshot(folder):
    return {
        str(path.relative_to(folder)): path.read_bytes()
        for path in sorted(Path(folder).rglob("*"))
        if path.is_file()
    }


def entry_text(corpus, entry):
    return (Path(corpus) / "procedures" / (entry + ".md")).read_text(encoding="utf-8")


def test_a_first_sync_adds_both_entries_and_their_index_lines(make_procedures, make_corpus):
    procedures, corpus = make_procedures(), make_corpus()
    result = sync(procedures, corpus, DATE)
    assert result == {
        "added": ["procedures-judged", "procedures-two-steps"],
        "changed": [],
        "removed": [],
        "unchanged": [],
    }
    assert entry_text(corpus, "procedures-two-steps") == render(procedures, "two_steps.yaml")
    index = (corpus / "llms.txt").read_text(encoding="utf-8")
    assert "- [The claims procedure](procedures/procedures-judged.md): " in index
    assert "- [The word count procedure](procedures/procedures-two-steps.md): " in index
    assert check_corpus(corpus) == []


def test_a_second_sync_changes_nothing(make_procedures, make_corpus):
    procedures, corpus = make_procedures(), make_corpus()
    sync(procedures, corpus, DATE)
    before = snapshot(corpus)
    result = sync(procedures, corpus, "2026-11-05")
    assert result["unchanged"] == ["procedures-judged", "procedures-two-steps"]
    assert result["added"] == result["changed"] == result["removed"] == []
    assert snapshot(corpus) == before


def test_a_changed_goal_rewrites_only_that_entry_with_a_new_date(make_procedures, make_corpus):
    procedures, corpus = make_procedures(), make_corpus()
    sync(procedures, corpus, DATE)
    judged_before = entry_text(corpus, "procedures-judged")
    graph = procedures / "graphs" / "two_steps.yaml"
    graph.write_text(
        TWO_STEPS_GRAPH.replace("report the count.", "report the count twice."), encoding="utf-8"
    )
    result = sync(procedures, corpus, "2026-11-02")
    assert result["changed"] == ["procedures-two-steps"]
    assert result["unchanged"] == ["procedures-judged"]
    text = entry_text(corpus, "procedures-two-steps")
    assert "updated: 2026-11-02\n" in text
    assert "source_commit: " + short_sum(graph) + "\n" in text
    assert "report the count twice." in text
    assert entry_text(corpus, "procedures-judged") == judged_before
    assert "updated: " + DATE + "\n" in judged_before
    assert check_corpus(corpus) == []


def test_a_removed_graph_removes_its_entry_and_index_line(make_procedures, make_corpus):
    procedures, corpus = make_procedures(), make_corpus()
    sync(procedures, corpus, DATE)
    alpha = (corpus / "formats" / "formats-alpha.md").read_bytes()
    (procedures / "graphs" / "judged.yaml").unlink()
    result = sync(procedures, corpus, DATE)
    assert result["removed"] == ["procedures-judged"]
    assert result["unchanged"] == ["procedures-two-steps"]
    assert not (corpus / "procedures" / "procedures-judged.md").exists()
    assert "procedures-judged" not in (corpus / "llms.txt").read_text(encoding="utf-8")
    assert (corpus / "formats" / "formats-alpha.md").read_bytes() == alpha
    assert check_corpus(corpus) == []


def test_check_only_reports_and_writes_nothing(make_procedures, make_corpus):
    procedures, corpus = make_procedures(), make_corpus()
    before = snapshot(corpus)
    result = sync(procedures, corpus, DATE, check_only=True)
    assert result["added"] == ["procedures-judged", "procedures-two-steps"]
    assert snapshot(corpus) == before


def test_the_command_check_exits_1_when_stale_and_writes_nothing(make_procedures, make_corpus, capsys):
    procedures, corpus = make_procedures(), make_corpus()
    before = snapshot(corpus)
    code = main(["graph-entries", "--procedures", str(procedures), "--corpus", str(corpus), "--check"])
    assert code == 1
    assert snapshot(corpus) == before
    assert capsys.readouterr().out.splitlines() == [
        "added procedures-judged",
        "added procedures-two-steps",
    ]


def test_the_command_check_exits_0_when_current(make_procedures, make_corpus, capsys):
    procedures, corpus = make_procedures(), make_corpus()
    assert main(["graph-entries", "--procedures", str(procedures), "--corpus", str(corpus),
                 "--date", DATE]) == 0
    capsys.readouterr()
    code = main(["graph-entries", "--procedures", str(procedures), "--corpus", str(corpus), "--check"])
    assert code == 0
    assert capsys.readouterr().out == ""


def test_the_command_prints_one_line_per_change(make_procedures, make_corpus, capsys):
    procedures, corpus = make_procedures(), make_corpus()
    main(["graph-entries", "--procedures", str(procedures), "--corpus", str(corpus), "--date", DATE])
    capsys.readouterr()
    (procedures / "graphs" / "judged.yaml").unlink()
    graph = procedures / "graphs" / "two_steps.yaml"
    graph.write_text(TWO_STEPS_GRAPH.replace("version: 0.2", "version: 0.3"), encoding="utf-8")
    assert main(["graph-entries", "--procedures", str(procedures), "--corpus", str(corpus)]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "changed procedures-two-steps",
        "removed procedures-judged",
    ]


def test_the_command_dates_a_new_entry_today_by_default(make_procedures, make_corpus):
    import datetime

    procedures, corpus = make_procedures(), make_corpus()
    main(["graph-entries", "--procedures", str(procedures), "--corpus", str(corpus)])
    today = datetime.date.today().isoformat()
    assert "updated: " + today + "\n" in entry_text(corpus, "procedures-judged")


def test_the_command_reports_a_graph_whose_contract_is_missing(make_procedures, make_corpus, capsys):
    procedures = make_procedures({"contracts/judged.yaml": None})
    corpus = make_corpus()
    before = snapshot(corpus)
    code = main(["graph-entries", "--procedures", str(procedures), "--corpus", str(corpus)])
    assert code == 1
    assert "contracts/judged.yaml" in capsys.readouterr().out
    assert snapshot(corpus) == before


def test_adding_the_authoring_entry_gives_both_entries_the_consult_line(make_procedures, make_corpus):
    procedures, corpus = make_procedures(), make_corpus()
    sync(procedures, corpus, DATE)
    assert "## Consult also" not in entry_text(corpus, "procedures-judged")
    guide = corpus / "guidelines" / "guidelines-authoring-procedures.md"
    guide.parent.mkdir()
    guide.write_text(AUTHORING, encoding="utf-8")
    result = sync(procedures, corpus, "2026-11-03")
    assert result["changed"] == ["procedures-judged", "procedures-two-steps"]
    for entry in ("procedures-judged", "procedures-two-steps"):
        assert entry_text(corpus, entry).endswith("\n" + CONSULT)
    assert check_corpus(corpus) == []


def test_sync_takes_titles_and_triggers_from_the_registry(make_procedures, make_corpus):
    procedures, corpus = make_procedures({"registry.yaml": REGISTRY}), make_corpus()
    sync(procedures, corpus, DATE)
    text = entry_text(corpus, "procedures-judged")
    assert "# Claim review\n" in text
    assert "`ai_edit` and `turn_end`" in text
    assert "# The word count procedure\n" in entry_text(corpus, "procedures-two-steps")
    assert check_corpus(corpus) == []


# Layers stay separate.


def test_no_import_of_another_layer():
    pattern = re.compile(r"^\s*(import|from)\s+(ospipe|verification_procedures|vg)\b")
    for path in sorted(KB.rglob("*.py")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            assert not pattern.match(line), "{}:{} {}".format(path, number, line)
