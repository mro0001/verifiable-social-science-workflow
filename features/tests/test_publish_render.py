"""Publish design A.4 and R1, R5, R10, R11, R14, R15. The pages and the figure
of a published verification repository.

The inputs are made here by hand, as model namedtuples and a counts
OrderedDict with the keys counts.py writes, so these tests read no project.
Run from the repository root as python3 -m pytest -q features/tests.
"""
import collections
import json
import os
import re
import xml.etree.ElementTree as ElementTree

import pytest

from features.publish import figure, render
from features.publish.model import (HARNESS_NAMES, WORKFLOW_URL, Answers, Collected, Group,
                                    LedgerRow, Product, Report)

EPOCH = 1793404800
SVG = "{http://www.w3.org/2000/svg}"
DASHES = (chr(0x2014), chr(0x2013))
MAKEFILE = (b"WORKFLOW ?= ../../verifiable-social-science-workflow\n"
            b"OSPIPE ?= PYTHONPATH='$(WORKFLOW)/ospipe' python3 -m ospipe\n\n"
            b".PHONY: proposal\nproposal: proposal.md\n\t$(OSPIPE) build\n\n"
            b".PHONY: data\ndata:\n\tpython3 s1_numbers.py\n")
PLAIN_MAKEFILE = (b"OSPIPE ?= PYTHONPATH='/somewhere/ospipe' python3 -m ospipe\n\n"
                  b"manuscript: manuscript.md\n\t$(OSPIPE) build\n")


def ledger(count, date="2026-10-31", epoch=EPOCH):
    return [LedgerRow("v%03d" % number, date, "-", "ab" * 32, "draft",
                      "unverified: prose, citations, data, build", "-", epoch)
            for number in range(1, count + 1)]


def product(name, builds=0, verification_dir=None):
    rows = ledger(builds)
    return Product(name, name + ".md", "builds/" + name,
                   verification_dir or "verification/" + name, "docx", rows,
                   rows[-1] if rows else None)


def answers(**given):
    fields = dict(title="", summary="", repo_url="https://github.com/a-scholar/demo-repo",
                  workflow_url=WORKFLOW_URL, workflow_folder="verifiable-social-science-workflow",
                  runs="", exclude=[], harness_names=dict(HARNESS_NAMES), notes={}, files={},
                  anonymous=True, sessions={"skip": False, "also_folders": [], "no_summaries": False,
                            "withhold": [], "scrub_terms": []},
                  check={}, github=None, phase_runs={}, unknown_keys=[])
    fields.update(given)
    return Answers(**fields)


def citation(**given):
    item = {"id": "r18", "citekey": "walters2023",
            "sentence": "Plausibility failures appear in hallucinated citations [@walters2023], "
                        "misattributed claims, and analyses that skip required steps.",
            "origin": "ai",
            "origin_evidence": "First named by an AI at 2026-07-31T19:57:34Z in "
                               "research/report.md, in a file an AI wrote",
            "lookup": "found", "existence": "found in the metadata cache (DOI 10.1038/x)",
            "reason": "The first careful audit of LLM-generated bibliographies, with 636 "
                      "citations in 84 papers, and more words after the first eighty.",
            "quotes": [{"from": "record", "in_source": "yes",
                        "text": "55% of the GPT-3.5 citations but just 18% are fabricated"}],
            "quote_in_source": "yes", "source_file": "source_walters2023.txt",
            "needs_decision": True, "sessions": ["Sf2b3ddaba981"]}
    item.update(given)
    return item


def report(group, stream, items=(), report_bytes=b"# report\n"):
    results = {"schema": "verification-results", "stream": stream,
               "run_id": "%s_%s" % (group.key, stream), "items": list(items), "decisions": []}
    data = json.dumps(results, sort_keys=True).encode("utf-8")
    origin = "run %s" % results["run_id"] if report_bytes is not None else None
    return Report(group, stream, results["run_id"], results, data, report_bytes, origin, None)


def make_collected(products, groups, reports, style="workflow_var", project_files=None,
                   **given):
    if project_files is None:
        project_files = {"Makefile": MAKEFILE, "refs.bib": b"@article{a,\n}\n",
                         "numbers.yml": b"numbers: {}\n", "pipeline.yaml": b"steps: []\n"}
    pipeline = {"steps": [{"id": "one", "script": "s1_numbers.py", "phase": "analysis"},
                          {"id": "two", "script": "s2_numbers.py", "phase": "analysis"}]}
    return Collected("/projects/survey_study", answers(**given), products, groups, reports,
                     style, project_files, [], [], pipeline,
                     ["key%d" % number for number in range(152)], 30, [], [],
                     "/workflow", "e22136c0123456789abcdef")


def two_groups(**given):
    """Two products, each with its own verification folder, as in the demo.
    The proposal has no data report."""
    proposal = product("proposal", 6)
    appendix = product("appendix", 10)
    first = Group("proposal", (proposal,), "verification/proposal", "proposal")
    second = Group("appendix", (appendix,), "verification/appendix", "appendix")
    reports = [report(first, "prose"), report(first, "citations", [citation()]),
               report(first, "build"), report(second, "prose"),
               report(second, "citations", [citation(id="r02", citekey="liang2025")]),
               report(second, "data"), report(second, "build"),
               report(second, "data_analysis")]
    return make_collected([proposal, appendix], [first, second], reports, **given)


def demo_counts(sessions=True, **changed):
    counts = collections.OrderedDict()
    values = [
        ("prose.changes", 273), ("prose.ai", 257), ("prose.no_reason", 186),
        ("prose.content", 158), ("prose.reports", 2),
        ("prose.proposal.changes", 72), ("prose.proposal.ai", 72),
        ("prose.proposal.no_reason", 56), ("prose.proposal.content", 60),
        ("prose.appendix.changes", 201), ("prose.appendix.ai", 185),
        ("prose.appendix.no_reason", 130), ("prose.appendix.content", 98),
        ("citations.rows", 38), ("citations.ai", 35), ("citations.scholar", 3),
        ("citations.unknown", 0), ("citations.not_found", 0), ("citations.not_looked_up", 4),
        ("citations.no_quote", 7), ("citations.record_quote_not_found", 10),
        ("citations.no_reason", 0), ("citations.reports", 2),
        ("citations.proposal.rows", 35), ("citations.proposal.ai", 32),
        ("citations.proposal.not_looked_up", 4), ("citations.proposal.no_quote", 7),
        ("citations.appendix.rows", 3), ("citations.appendix.ai", 3),
        ("citations.appendix.not_looked_up", 1), ("citations.appendix.no_quote", 0),
        ("data.numbers", 152), ("data.reproduce", 152), ("data.changes", 22),
        ("data.change_no_reason", 10), ("data.parameters", 37), ("data.parameter_no_reason", 9),
        ("data.scripts", 2), ("data.scripts_ai", 2), ("data.reports", 1),
        ("data.appendix.numbers", 152), ("data.appendix.reproduce", 152),
        ("phases.appendix.data_analysis.descriptions", 47),
        ("phases.appendix.data_analysis.missing", 28),
        ("phases.appendix.data_analysis.not_found", 0),
        ("phases.appendix.data_analysis.confirmed", 19),
        ("build.blocking", 81), ("build.warnings", 60), ("build.hardcoding", 81),
        ("build.ai_writes", 0), ("build.one_source", 1), ("build.reports", 2),
        ("builds.total", 16),
        ("builds.proposal.latest", "v006"), ("builds.proposal.date", "2026-10-31"),
        ("builds.proposal.sha256", "ab" * 32), ("builds.proposal.epoch", EPOCH),
        ("builds.proposal.state", "unverified: no data report"),
        ("builds.appendix.latest", "v010"), ("builds.appendix.date", "2026-10-31"),
        ("builds.appendix.sha256", "ab" * 32), ("builds.appendix.epoch", EPOCH),
        ("builds.appendix.state", "unverified until the scholar decides"),
        ("decisions.approved", 0), ("decisions.held", 0), ("decisions.undecided", 825),
        ("numbers.total", 152), ("refs.works", 30),
    ]
    if sessions:
        values.extend([("sessions.indexed", 181), ("sessions.contributing", 19),
                       ("sessions.contributions", 292),
                       ("sessions.harnesses", "Claude Code; ForgeCode")])
    values.append(("missing", "proposal/data"))
    for key, value in values:
        counts[key] = value
    for key, value in changed.items():
        counts[key.replace("__", ".")] = value
    return counts


def shared_group(**given):
    """Two products in one verification folder, as in the test story. Only the
    manuscript has a numbered build, and the Makefile names no WORKFLOW."""
    manuscript = product("manuscript", 2, "verification")
    slides = product("slides", 0, "verification")
    group = Group("manuscript+slides", (manuscript, slides), "verification",
                  "manuscript and slides")
    reports = [report(group, stream) for stream in ("prose", "citations", "data", "build")]
    given.setdefault("repo_url", "")
    files = {"Makefile": PLAIN_MAKEFILE, "manuscript.md": b"x"}
    return make_collected([manuscript, slides], [group], reports, style="pythonpath_env",
                          project_files=files, **given)


def shared_counts(**changed):
    counts = collections.OrderedDict()
    values = [
        ("prose.changes", 12), ("prose.ai", 9), ("prose.no_reason", 0), ("prose.content", 2),
        ("prose.reports", 1),
        ("citations.rows", 5), ("citations.ai", 4), ("citations.not_found", 2),
        ("citations.no_quote", 1), ("citations.reports", 1),
        ("data.numbers", 8), ("data.reproduce", 7), ("data.scripts", 3), ("data.scripts_ai", 1),
        ("data.reports", 1),
        ("build.blocking", 3), ("build.warnings", 1), ("build.hardcoding", 2),
        ("build.ai_writes", 2), ("build.one_source", 0), ("build.reports", 1),
        ("builds.total", 2), ("builds.manuscript.latest", "v002"),
        ("builds.manuscript.date", "2026-10-29"), ("builds.manuscript.sha256", "cd" * 32),
        ("builds.manuscript.epoch", 1793232000),
        ("builds.manuscript.state", "unverified until the scholar decides"),
        ("decisions.approved", 2), ("decisions.held", 1), ("decisions.undecided", 3),
        ("numbers.total", 8), ("refs.works", 5),
        ("sessions.indexed", 4), ("sessions.contributing", 2), ("sessions.contributions", 13),
        ("sessions.harnesses", "Claude Code"),
        ("missing", ""),
    ]
    for key, value in values:
        counts[key] = value
    for key, value in changed.items():
        counts[key.replace("__", ".")] = value
    return counts


def all_outputs(collected, counts, has_sessions=True):
    top = ["Makefile", "README.md", "builds/", "figures/", "manuscript.md", "numbers.yml",
           "params_io.py", "proposal.md", "s1_numbers.py", "sessions/", "table.csv",
           "verification/"]
    return {
        "README.md": render.readme(collected, counts, has_sessions),
        "docs/reading_reports.md": render.reading_reports(collected, counts),
        "docs/record.md": render.record(collected, counts, has_sessions),
        "docs/rebuild.md": render.rebuild_page(collected, counts),
        "project/README.md": render.project_readme(collected, top),
        "docs/results.svg": figure.results_svg(collected, counts),
    }


def table_row(text, stream):
    for line in text.split("\n"):
        if line.startswith("| %s |" % stream):
            return line
    raise AssertionError("no row for %s" % stream)


def svg_texts(svg):
    root = ElementTree.fromstring(svg)
    return [element.text or "" for element in root.iter(SVG + "text")]


def alt_of(readme):
    match = re.search(r"^!\[(.*)\]\(docs/results\.svg\)$", readme, re.M)
    assert match, "the README shows no figure"
    return match.group(1)


CASES = [
    ("two groups", two_groups, demo_counts),
    ("shared group", shared_group, shared_counts),
]


# README.md for two groups.

def test_the_readme_for_two_groups_gives_each_stream_its_sentence_and_links():
    text = render.readme(two_groups(), demo_counts(), True)
    assert text.startswith("# Verification reports for survey_study\n\n")
    assert ("AI sessions helped write the documents in this repository, `proposal` and "
            "`appendix`.") in text
    assert "None is decided yet, so each document is marked unverified." in text
    assert ("`proposal` has no data report, so it stays unverified however the items are "
            "decided.") in text
    prose = table_row(text, "Prose")
    assert ("257 of 273 changes were made by an AI. Each is shown with the reason the AI gave, "
            "and 186 have none on record.") in prose
    assert prose.endswith("| [proposal](project/verification/proposal/prose/report.md) · "
                          "[appendix](project/verification/appendix/prose/report.md) |")
    references = table_row(text, "References")
    assert ("35 of 38 citations were first named by an AI. For 7 of them, no quote was found in "
            "the source.") in references
    assert "not found" not in references.replace("no quote was found", "")
    data = table_row(text, "Data and analysis code")
    assert ("AI sessions wrote or changed both analysis scripts. All 152 numbers reproduce from "
            "the raw data. `proposal` has no data report yet.") in data
    assert data.endswith("| [appendix](project/verification/appendix/data/report.md) · "
                         "[data analysis](project/verification/appendix/data_analysis/report.md) |")
    build = table_row(text, "Build")
    assert ("Each document has one source, and no AI wrote to a build folder. The report flags "
            "81 problems for the scholar, all from the check for results typed into the text."
            ) in build


def test_the_readme_try_it_clones_both_repositories_and_builds_each_product():
    text = render.readme(two_groups(), demo_counts(), True)
    block = text.split("## Try it\n\n```\n", 1)[1].split("```", 1)[0]
    assert block.split("\n") == [
        "git clone %s" % WORKFLOW_URL,
        "git clone https://github.com/a-scholar/demo-repo",
        "cd demo-repo/project",
        "SOURCE_DATE_EPOCH=%d make proposal" % EPOCH,
        "SOURCE_DATE_EPOCH=%d make appendix" % EPOCH,
        "",
    ]
    assert "`proposal` v006 and `appendix` v010" in text
    assert "`make data` recomputes every number from the raw data." in text


def test_the_readme_links_the_docs_pages_and_the_session_index():
    text = render.readme(two_groups(), demo_counts(), True)
    more = text.split("## Read more\n", 1)[1]
    for link in ("(docs/reading_reports.md)", "(docs/record.md)", "(docs/rebuild.md)",
                 "(project/README.md)", "(project/sessions/sessions.csv)"):
        assert link in more
    assert "the 181 AI sessions behind the reports" in more


# README.md for one group that two products share.

def test_the_readme_for_a_shared_group_gives_one_link_per_stream_named_by_its_label():
    text = render.readme(shared_group(), shared_counts(), True)
    for stream, folder in (("Prose", "prose"), ("References", "citations"),
                           ("Data and analysis code", "data"), ("Build", "build")):
        row = table_row(text, stream)
        assert row.endswith("| [manuscript and slides](project/verification/%s/report.md) |"
                            % folder)
        assert "·" not in row
    assert "9 of 12 changes were made by an AI." in text
    assert "and each has one on record." in text
    assert ("4 of 5 citations were first named by an AI. For 1 of them, no quote was found in "
            "the source. 2 cited works were not found.") in text
    assert "AI sessions wrote or changed 1 of the 3 analysis scripts." in text
    assert "7 of the 8 numbers reproduce from the raw data." in text
    assert "The build report finds a document with more than one source." in text
    assert "AI sessions wrote to a build folder 2 times." in text
    assert "The report flags 3 problems for the scholar, 2 of them from the check" in text
    assert "2 items are approved, 1 held, and 3 not yet decided." in text


def test_the_readme_for_a_shared_group_rebuilds_with_pythonpath_and_names_the_unbuilt_product():
    text = render.readme(shared_group(), shared_counts(), True)
    block = text.split("## Try it\n\n```\n", 1)[1].split("```", 1)[0]
    assert block.split("\n") == [
        "git clone %s" % WORKFLOW_URL,
        "git clone URL-OF-THIS-REPOSITORY",
        "cd THIS-REPOSITORY/project",
        "SOURCE_DATE_EPOCH=1793232000 PYTHONPATH=../../verifiable-social-science-workflow/ospipe "
        "make manuscript",
        "",
    ]
    assert "`slides` has no numbered build yet." in text
    assert "This builds `manuscript` again as its next numbered build." in text
    assert "make slides" not in text
    assert "date of v002" in text
    assert "make data" not in text


def test_the_citation_sentence_for_one_ai_citation_says_it():
    counts = shared_counts(citations__ai=1, citations__no_quote=1, citations__not_found=0)
    text = render.readme(shared_group(), counts, True)
    assert "1 of 5 citations was first named by an AI. For it, no quote was found in the source." \
        in text


def test_a_workflow_folder_unlike_the_clone_folder_is_named_on_the_clone_line():
    collected = two_groups(workflow_folder="workflow")
    text = render.readme(collected, demo_counts(), True)
    assert "git clone %s workflow\n" % WORKFLOW_URL in text


# R15, R5, R11, and the decision sentence.

def test_a_stream_no_group_has_says_no_report_yet_and_links_nothing():
    collected = two_groups()
    collected = collected._replace(reports=[found for found in collected.reports
                                            if found.stream != "citations"])
    counts = demo_counts(citations__reports=0)
    text = render.readme(collected, counts, True)
    assert table_row(text, "References") == "| References | No report yet. | |"
    svg = figure.results_svg(collected, counts)
    assert "no report yet" in svg_texts(svg)
    assert figure.GHOST in svg


def test_a_report_left_out_links_its_results_file():
    collected = two_groups()
    reports = []
    for found in collected.reports:
        if found.stream == "build" and found.group.key == "appendix":
            found = found._replace(report_bytes=None, report_from=None)
        reports.append(found)
    collected = collected._replace(reports=reports)
    left_out = [found for found in reports if found.report_bytes is None][0]
    assert render.report_link(left_out) == "project/verification/appendix/build/results.json"
    row = table_row(render.readme(collected, demo_counts(), True), "Build")
    assert "[appendix results](project/verification/appendix/build/results.json)" in row
    assert "[proposal](project/verification/proposal/build/report.md)" in row


def test_report_link_names_the_report_inside_the_group_folder():
    collected = shared_group()
    assert render.report_link(collected.reports[0]) == "project/verification/prose/report.md"
    one = report(Group("paper", (), "verification/paper/", "paper"), "data_analysis")
    assert render.report_link(one) == "project/verification/paper/data_analysis/report.md"


def test_every_item_approved_and_verified_says_so():
    counts = demo_counts(decisions__approved=825, decisions__undecided=0,
                         builds__proposal__state="verified", builds__appendix__state="verified")
    text = render.readme(two_groups(), counts, True)
    assert "Every item is approved, and each document is marked verified." in text
    assert "stays unverified" not in text


def test_a_build_with_one_source_zero_says_so_in_the_readme_and_the_figure():
    counts = demo_counts(build__one_source=0)
    text = render.readme(two_groups(), counts, True)
    assert "The build report finds a document with more than one source." in text
    assert "a document has more than one source" in figure.alt_text(two_groups(), counts)


def test_a_product_with_no_build_says_no_build_yet_in_the_figure():
    collected = shared_group()
    svg = figure.results_svg(collected, shared_counts())
    joined = " ".join(svg_texts(svg))
    assert "slides no build yet" in joined
    assert "manuscript v002" in joined


def three_in_one_group():
    """Two built products and one with no build, sharing one verification folder."""
    manuscript = product("manuscript", 2, "verification")
    appendix = product("appendix", 1, "verification")
    slides = product("slides", 0, "verification")
    group = Group("manuscript+appendix+slides", (manuscript, appendix, slides), "verification",
                  "manuscript, appendix, and slides")
    reports = [report(group, stream) for stream in ("prose", "citations", "data", "build")]
    return make_collected([manuscript, appendix, slides], [group], reports)


def test_every_item_approved_with_an_unbuilt_product_names_the_built_ones_verified():
    approved = dict(decisions__approved=6, decisions__held=0, decisions__undecided=0)
    collected = shared_group()
    counts = shared_counts(builds__manuscript__state="verified", **approved)
    sentence = "Every item is approved, and `manuscript` is marked verified."
    assert render.decision_sentence(collected, counts) == sentence
    text = render.readme(collected, counts, True)
    assert sentence in text
    assert "each document is marked verified" not in text
    assert "`slides` has no numbered build yet." in text

    collected = three_in_one_group()
    counts = shared_counts(builds__manuscript__state="verified", builds__appendix__state="verified",
                           **approved)
    assert render.decision_sentence(collected, counts) == \
        "Every item is approved, and `manuscript` and `appendix` are marked verified."

    # How each built product is marked comes from its ledger row, not the decisions.
    counts = shared_counts(builds__appendix__state="verified", **approved)
    assert render.decision_sentence(collected, counts) == \
        "Every item is approved, `appendix` is marked verified, and `manuscript` is marked unverified."


def test_undecided_phase_items_are_said_apart_from_the_stream_items():
    collected = shared_group()
    approved = dict(decisions__approved=6, decisions__held=0, decisions__undecided=0,
                    builds__manuscript__state="verified")
    counts = shared_counts(phases__decisions__approved=0, phases__decisions__held=0,
                           phases__decisions__undecided=2, **approved)
    sentence = render.decision_sentence(collected, counts)
    assert sentence == ("Every item of the four stream reports is approved, and `manuscript` is marked"
                        " verified. Of the 2 items of the data phase reports, 0 are approved, 0 held,"
                        " and 2 not yet decided.")
    alt = figure.alt_text(collected, counts)
    assert "all 6 approved, and 2 items of the data phases not yet approved" in alt
    # With every phase item approved, nothing more is said.
    counts = shared_counts(phases__decisions__approved=2, phases__decisions__held=0,
                           phases__decisions__undecided=0, **approved)
    assert render.decision_sentence(collected, counts) == \
        "Every item is approved, and `manuscript` is marked verified."


def test_how_a_product_is_marked_comes_from_its_ledger_not_the_decisions():
    # The ledger says verified, but the published results are newer and undecided.
    collected = shared_group()
    manuscript = collected.products[0]
    row = manuscript.latest._replace(verification="verified",
                                     runs="prose=old_prose; citations=old_citations")
    manuscript = manuscript._replace(latest=row, ledger=manuscript.ledger[:-1] + [row])
    group = collected.groups[0]._replace(products=(manuscript, collected.products[1]))
    reports = [item._replace(group=group) for item in collected.reports]
    collected = collected._replace(products=[manuscript, collected.products[1]], groups=[group],
                                   reports=reports)
    counts = shared_counts(decisions__approved=0, decisions__held=0, decisions__undecided=6,
                           builds__manuscript__state="verified")
    assert render.decision_sentence(collected, counts) == (
        "None is decided yet, and `manuscript` is marked verified. The latest build of"
        " `manuscript`, v002, was marked before these results reached the project, so build it"
        " again to mark it.")
    # Every item is decided, but the latest build was not marked: it is marked when built again.
    collected = shared_group()
    counts = shared_counts(decisions__approved=6, decisions__held=0, decisions__undecided=0,
                           builds__manuscript__state="unverified until it is built again")
    assert render.decision_sentence(collected, counts) == (
        "Every item is approved, and `manuscript` is marked unverified. `manuscript` is marked"
        " verified when it is built again.")
    assert "manuscript v002, unverified until it is built again" in figure.alt_text(collected, counts)


@pytest.mark.parametrize("scripts, scripts_ai, sentence", [
    (1, 0, "No AI session wrote or changed the analysis script."),
    (1, 1, "AI sessions wrote or changed the analysis script."),
    (2, 2, "AI sessions wrote or changed both analysis scripts."),
    (3, 0, "No AI session wrote or changed any of the 3 analysis scripts."),
    (3, 3, "AI sessions wrote or changed all 3 analysis scripts."),
    (3, 1, "AI sessions wrote or changed 1 of the 3 analysis scripts."),
    (0, 0, ""),
])
def test_the_data_sentence_names_the_analysis_scripts_in_number(scripts, scripts_ai, sentence):
    counts = shared_counts(data__scripts=scripts, data__scripts_ai=scripts_ai)
    found = render.data_sentence(counts)
    assert found == ("%s 7 of the 8 numbers reproduce from the raw data." % sentence).strip()
    text = render.readme(shared_group(), counts, True)
    assert " 1 analysis script" not in text and "of the 1 " not in text


@pytest.mark.parametrize("numbers, reproduce, sentence", [
    (1, 1, "The 1 number reproduces from the raw data."),
    (1, 0, "The 1 number does not reproduce from the raw data."),
    (2, 1, "1 of the 2 numbers reproduces from the raw data."),
    (0, 0, "The data report lists no number."),
])
def test_the_data_sentence_counts_the_numbers_in_number(numbers, reproduce, sentence):
    counts = shared_counts(data__scripts=0, data__numbers=numbers, data__reproduce=reproduce)
    assert render.data_sentence(counts) == sentence


@pytest.mark.parametrize("scripts, scripts_ai, sentence", [
    (1, 0, "declares 1 analysis script, and no AI session wrote or changed it."),
    (1, 1, "declares 1 analysis script, and an AI session wrote or changed it."),
    (3, 0, "declares 3 analysis scripts, and no AI session wrote or changed any of them."),
    (3, 2, "declares 3 analysis scripts, and AI sessions wrote or changed 2 of them."),
])
def test_the_reading_page_counts_the_scripts_in_number(scripts, scripts_ai, sentence):
    counts = shared_counts(data__scripts=scripts, data__scripts_ai=scripts_ai)
    text = render.reading_reports(shared_group(), counts)
    assert "The project's `pipeline.yaml` %s" % sentence in text


@pytest.mark.parametrize("changed, sentence", [
    ({"prose__changes": 1, "prose__ai": 1, "prose__no_reason": 0},
     "The 1 change was made by an AI. It is shown with the reason the AI gave, and it has one on "
     "record."),
    ({"prose__changes": 1, "prose__ai": 0}, "The 1 change was not made by an AI."),
    ({"prose__changes": 3, "prose__ai": 1, "prose__no_reason": 1},
     "1 of 3 changes was made by an AI. It is shown with the reason the AI gave, and it has none "
     "on record."),
    ({"prose__changes": 4, "prose__ai": 0}, "None of the 4 changes was made by an AI."),
])
def test_the_prose_sentence_is_worded_for_one_change(changed, sentence):
    assert render.prose_sentence(shared_counts(**changed)) == sentence


@pytest.mark.parametrize("changed, sentence", [
    ({"citations__rows": 1, "citations__ai": 1, "citations__no_quote": 0,
      "citations__not_found": 0},
     "The 1 citation was first named by an AI. Every quote checked for it was found in the "
     "source."),
    ({"citations__rows": 1, "citations__ai": 0, "citations__not_found": 1},
     "The 1 citation was not first named by an AI. 1 cited work was not found."),
    ({"citations__rows": 4, "citations__ai": 0, "citations__not_found": 0},
     "None of the 4 citations was first named by an AI."),
])
def test_the_citation_sentence_is_worded_for_one_citation(changed, sentence):
    assert render.citations_sentence(shared_counts(**changed)) == sentence


def test_one_write_to_a_build_folder_is_once_and_more_are_times():
    counts = shared_counts(build__ai_writes=1)
    assert "An AI session wrote to a build folder once." in render.build_sentence(counts)
    text = render.readme(shared_group(), counts, True)
    assert "1 time" not in text
    assert "AI wrote to a build once" in figure.alt_text(shared_group(), counts)
    assert "AI wrote to a build once" in " ".join(svg_texts(figure.results_svg(shared_group(),
                                                                               counts)))
    counts = shared_counts(build__ai_writes=3)
    assert "AI sessions wrote to a build folder 3 times." in render.build_sentence(counts)
    assert "AI wrote to a build 3 times" in figure.alt_text(shared_group(), counts)


def test_one_indexed_session_is_counted_in_the_singular():
    text = render.readme(shared_group(), shared_counts(sessions__indexed=1), True)
    assert "one row for the 1 AI session behind the reports" in text
    assert "each of the 1" not in text


def sentence_starts(text, cells):
    """The first character of each sentence of a markdown page, and of each table cell
    when cells is true, leaving out code blocks and the figure's alt text."""
    starts = []
    in_code = False
    for line in text.split("\n"):
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code or line.startswith("![") or line.startswith("|---"):
            continue
        if line.startswith("|") and not cells:
            continue
        line = re.sub(r"\]\([^)]*\)", "]", line)
        starts.extend(re.findall(r"(?:^|[.!?]\s+|\|\s*)([^\s|])", line))
    return starts


@pytest.mark.parametrize("name,make,make_counts", CASES + [
    ("unbuilt", shared_group, lambda: shared_counts(
        decisions__approved=6, decisions__held=0, decisions__undecided=0,
        builds__manuscript__state="verified")),
    ("three", three_in_one_group, shared_counts),
])
def test_no_sentence_of_a_generated_page_starts_with_a_lowercase_word(name, make, make_counts):
    outputs = all_outputs(make(), make_counts())
    # The README's table cells are sentences; the other pages' tables hold values.
    for path in ("README.md", "docs/rebuild.md", "docs/reading_reports.md", "docs/record.md",
                 "project/README.md"):
        starts = sentence_starts(outputs[path], cells=path == "README.md")
        assert starts, (name, path)
        lower = [start for start in starts if start.islower()]
        assert lower == [], (name, path)


# The data row's phase reports.

def test_the_data_row_links_each_phase_report_after_its_groups_data_report():
    collected = two_groups()
    first = collected.groups[0]
    reports = list(collected.reports) + [report(first, "data"), report(first, "data_cleaning")]
    collected = collected._replace(reports=reports)
    row = table_row(render.readme(collected, demo_counts(), True), "Data and analysis code")
    assert row.endswith(
        "| [proposal](project/verification/proposal/data/report.md) · "
        "[proposal data cleaning](project/verification/proposal/data_cleaning/report.md) · "
        "[appendix](project/verification/appendix/data/report.md) · "
        "[appendix data analysis](project/verification/appendix/data_analysis/report.md) |")
    assert "has no data report yet" not in row


def test_a_phase_report_with_no_report_links_its_results():
    collected = two_groups()
    reports = []
    for found in collected.reports:
        if found.stream == "data_analysis":
            found = found._replace(report_bytes=None, report_from=None)
        reports.append(found)
    row = table_row(render.readme(collected._replace(reports=reports), demo_counts(), True),
                    "Data and analysis code")
    assert row.endswith(" · [data analysis results]"
                        "(project/verification/appendix/data_analysis/results.json) |")


def test_phase_reports_are_linked_even_when_no_group_has_a_data_report():
    collected = two_groups()
    collected = collected._replace(reports=[found for found in collected.reports
                                            if found.stream != "data"])
    row = table_row(render.readme(collected, demo_counts(data__reports=0), True),
                    "Data and analysis code")
    assert row == ("| Data and analysis code | No report yet. | "
                   "[data analysis](project/verification/appendix/data_analysis/report.md) |")
    collected = collected._replace(reports=[found for found in collected.reports
                                            if found.stream != "data_analysis"])
    row = table_row(render.readme(collected, demo_counts(data__reports=0), True),
                    "Data and analysis code")
    assert row == "| Data and analysis code | No report yet. | |"


def test_a_group_lacking_a_stream_is_named_by_its_products_in_backticks():
    shared = shared_group()
    alone = product("appendix", 1)
    other = Group("appendix", (alone,), "verification/appendix", "appendix")
    reports = list(shared.reports) + [report(other, stream) for stream in ("prose", "build")]
    collected = shared._replace(products=list(shared.products) + [alone],
                                groups=list(shared.groups) + [other], reports=reports)
    row = table_row(render.readme(collected, shared_counts(), True), "References")
    assert "`appendix` has no references report yet." in row
    collected = collected._replace(reports=[found for found in reports
                                            if found.group.key != "manuscript+slides"
                                            or found.stream != "build"])
    row = table_row(render.readme(collected, shared_counts(), True), "Build")
    assert "`manuscript` and `slides` have no build report yet." in row


# R10, no session index.

def test_without_the_session_index_no_page_links_to_it():
    collected = two_groups(sessions={"skip": True, "also_folders": [], "no_summaries": False,
                                     "withhold": [], "scrub_terms": []})
    counts = demo_counts(sessions=False)
    outputs = all_outputs(collected, counts, has_sessions=False)
    for name, text in outputs.items():
        assert "sessions.csv" not in text, name
        assert "sessions/README.md" not in text, name
        assert "project/sessions" not in text, name
    assert "The session index is not published in this repository." in outputs["docs/record.md"]
    assert "how to search the session index" not in outputs["README.md"]
    assert "index not published" in " ".join(svg_texts(outputs["docs/results.svg"]))


def test_with_the_session_index_the_record_gives_its_counts_and_how_to_search_it():
    collected = two_groups(sessions={"skip": False, "also_folders": ["/a", "/b"],
                                     "no_summaries": False, "withhold": [], "scrub_terms": []})
    text = render.record(collected, demo_counts(), True)
    assert "`sessions/` lists 181 AI sessions of the record" in text
    assert "one of the 2 folders the scholar named as earlier folders of the project" in text
    assert "They come from Claude Code and ForgeCode, and 19 of them led to an AI contribution in " \
        "the reports, 292 contributions in all." in text
    assert "[`sessions/sessions.csv`](../project/sessions/sessions.csv)" in text
    assert "`sessions/index.html`" in text
    assert "[`sessions/README.md`](../project/sessions/README.md)" in text
    assert "/a" not in text


# Every output.

@pytest.mark.parametrize("name,make,make_counts", CASES)
def test_no_output_holds_a_long_or_en_dash(name, make, make_counts):
    for path, text in all_outputs(make(), make_counts()).items():
        for dash in DASHES:
            assert dash not in text, (name, path)


@pytest.mark.parametrize("name,make,make_counts", CASES)
def test_every_output_is_the_same_each_time_and_ends_cleanly(name, make, make_counts):
    first = all_outputs(make(), make_counts())
    second = all_outputs(make(), make_counts())
    assert first == second
    for path, text in first.items():
        assert text.endswith("\n") and not text.endswith("\n\n"), (name, path)
        assert "\r" not in text, (name, path)
        assert text.encode("utf-8").decode("utf-8") == text
        for line in text.split("\n"):
            assert line == line.rstrip(), (name, path, line)


@pytest.mark.parametrize("name,make,make_counts", CASES)
def test_the_alt_text_holds_every_number_the_figure_shows(name, make, make_counts):
    collected = make()
    counts = make_counts()
    svg = figure.results_svg(collected, counts)
    alt = alt_of(render.readme(collected, counts, True))
    assert alt == figure.alt_text(collected, counts)
    shown = set()
    for text in svg_texts(svg):
        shown.update(re.findall(r"\d+", text))
    assert shown
    told = set(re.findall(r"\d+", alt))
    assert shown <= told, sorted(shown - told)


def test_the_demo_alt_text_names_the_demo_numbers():
    alt = figure.alt_text(two_groups(), demo_counts())
    for number in ("273", "257", "186", "38", "35", "7", "152", "16", "81", "181", "30",
                   "v006", "v010"):
        assert re.search(r"(?<![\w.])%s(?![\w])" % re.escape(number), alt), number


# The figure.

def test_the_svg_parses_and_starts_with_a_white_background():
    svg = figure.results_svg(two_groups(), demo_counts())
    root = ElementTree.fromstring(svg)
    assert root.tag == SVG + "svg"
    first = list(root)[0]
    assert first.tag == SVG + "rect"
    assert first.attrib == {"x": "0", "y": "0", "width": "100%", "height": "100%",
                            "fill": "#FFFFFF"}
    assert root.attrib["width"] == str(figure.WIDTH)
    texts = svg_texts(svg)
    for expected in ("Scholar", "AI harness", "Claude Code and ForgeCode", "Prose",
                     "References", "Build", "Change review", "Source support", "Code",
                     "Build integrity", "What was", "checked", "Audit layer", "make",
                     "refs.bib", "numbers.yml", "proposal.md", "appendix.md", "proposal v006",
                     "appendix v010"):
        assert expected in texts, expected
    joined = " ".join(texts)
    for expected in ("273 changes", "257 by an AI", "186 AI changes", "38 citations",
                     "152 numbers", "16 numbered", "181 AI", "30 works"):
        assert expected in joined, expected
    for color in ("#16191F", "#7A5C12", "#F5EFDE", "#8C2F39", "#F8E9EA", "#FBF2F2", "#2F4858",
                  "#E9EFF3", "#5B3A8E", "#EFE9F6", "#F5F2FA"):
        assert color in svg, color
    assert 'font-family="Helvetica, Arial, sans-serif"' in svg


def test_no_wrapped_line_is_wider_than_its_box_by_the_estimate():
    lines = figure.wrap("Data and analysis code holds a remarkably_long_unbroken_identifier",
                        figure.COLUMN_WIDTH, figure.TITLE_SIZE, bold=True)
    room = (figure.COLUMN_WIDTH - 2 * figure.PAD_X) / (figure.BOLD_FACTOR * figure.TITLE_SIZE)
    assert all(len(line) <= room for line in lines)
    assert "".join(lines).replace(" ", "") == \
        "Dataandanalysiscodeholdsaremarkably_long_unbroken_identifier"


def test_the_svg_escapes_text():
    collected = shared_group()
    odd = collected.products[0]._replace(name="a<b&c")
    collected = collected._replace(products=[odd] + list(collected.products[1:]))
    counts = shared_counts()
    counts["builds.a<b&c.latest"] = "v002"
    svg = figure.results_svg(collected, counts)
    ElementTree.fromstring(svg)
    assert "a&lt;b&amp;c v002" in svg


# docs/reading_reports.md.

def test_reading_reports_shows_one_entry_field_by_field_with_its_anchor():
    collected = two_groups(notes={"references": "The scholar's own note on references.",
                                  "prose": "A prose note.\nWith a second line."})
    text = render.reading_reports(collected, demo_counts())
    assert ("Entry r18 of the [references report of `proposal`]"
            "(../project/verification/proposal/citations/report.md#r18-walters2023), shortened:"
            ) in text
    assert "| Field | In r18 | What it tells you |" in text
    sentence = [line for line in text.split("\n") if line.startswith("| Sentence |")][0]
    shown = sentence.split(" | ")[1]
    assert shown.startswith('"Plausibility failures') and shown.endswith(' ..."')
    assert len(shown) == len('""') + 80 + len(" ...")
    assert "| Session | `Sf2b3ddaba981` |" in text
    assert "| Quote check | yes, found in `source_walters2023.txt` |" in text
    assert '"55% of the GPT-3.5 citations but just 18% are fabricated"' in text
    assert "The scholar's own note on references." in text
    assert "A prose note.\nWith a second line." in text
    assert "(../project/sessions/sessions.csv)" in text


def test_reading_reports_lists_each_report_and_phase_report_by_group():
    text = render.reading_reports(two_groups(), demo_counts())
    assert "| Stream | proposal | appendix |" in text
    assert ("| Data and analysis code |  | [report](../project/verification/appendix/data/report.md), "
            "[data analysis](../project/verification/appendix/data_analysis/report.md) |") in text
    assert "| Changes to the text | 72 | 201 | 273 |" in text
    assert "| Works not looked up | 4 | 1 | 4 |" in text
    assert "| Data analysis, appendix | 47 | 19 | 28 | 0 |" in text
    assert "| Count | All |" in text
    assert "| Blocking findings | 81 |" in text
    assert "| Each document has one source | yes |" in text
    for term in ("**A stream**", "**The record**", "**A handoff**", "**`vg.py`**", "**A phase**"):
        assert term in text


def test_reading_reports_with_no_fitting_entry_lists_the_fields_alone():
    collected = shared_group()
    text = render.reading_reports(collected, shared_counts())
    assert "| Field | What it tells you |" in text
    assert "| Field | In" not in text
    assert "### Prose" in text and "| Count | manuscript and slides |" in text


def test_reading_reports_says_no_report_yet_for_a_missing_stream():
    collected = two_groups()
    collected = collected._replace(reports=[found for found in collected.reports
                                            if found.stream != "build"])
    text = render.reading_reports(collected, demo_counts(build__reports=0))
    build = text.split("### Build\n", 1)[1]
    assert build.startswith("\nNo report yet.\n")


def test_the_anchor_is_the_one_github_gives_the_heading():
    assert render.anchor("r18: @walters2023") == "r18-walters2023"
    assert render.anchor("R3: @Smith_2020.x") == "r3-smith_2020x"


# docs/rebuild.md and project/README.md.

def test_the_rebuild_page_gives_the_commands_and_the_empty_audit_home_warning():
    text = render.rebuild_page(two_groups(), demo_counts())
    assert "SOURCE_DATE_EPOCH=%d make proposal\n" % EPOCH in text
    assert "`make proposal WORKFLOW=/path/to/workflow`" in text
    assert "run `make data`" in text
    assert "commit e22136c" in text
    assert "a reader who starts an empty audit home gets clean-looking reports that are wrong" in text
    assert "python3 handoffs/results_to_pipeline.py --run RUN --stream prose" in text
    assert "(`AUDIT_HOME`, `CONNECTIONS_HOME`, `FEATURES_HOME`, `OBSERVABILITY_HOME`)" in text
    shared = render.rebuild_page(shared_group(), shared_counts())
    assert "PYTHONPATH=../../verifiable-social-science-workflow/ospipe make manuscript" in shared
    assert "`slides` has no numbered build yet." in shared


def test_the_project_readme_describes_each_entry_and_the_answers_win():
    collected = two_groups(files={"figures/": "The figures of each document",
                                  "Makefile": "The build file | with a bar"})
    top = ["Makefile", "builds/", "figures/", "numbers.yml", "params_io.py", "proposal.md",
           "refs.bib", "s1_numbers.py", "sessions/", "table.csv", "tools/", "verification/"]
    text = render.project_readme(collected, top)
    rows = dict((line.split(" | ")[0][2:], line.split(" | ", 1)[1][:-2])
                for line in text.split("\n") if line.startswith("| `"))
    assert rows["`Makefile`"] == "The build file \\| with a bar"
    assert rows["`figures/`"] == "The figures of each document"
    assert rows["`builds/`"] == "Every numbered build, with its ledger `BUILDS.md`"
    assert rows["`verification/`"].startswith("Each report, `report.md`")
    assert rows["`numbers.yml`"].startswith("Every number the text cites by placeholder, 152 keys")
    assert rows["`refs.bib`"] == "The references, 30 works"
    assert rows["`proposal.md`"] == "The source text of `proposal`"
    assert rows["`s1_numbers.py`"] == "An analysis script"
    assert rows["`params_io.py`"] == "A helper script"
    assert rows["`table.csv`"] == "An analysis output"
    assert rows["`sessions/`"] == "The public index of the AI sessions behind the reports"
    assert rows["`tools/`"] == "-"
    assert list(rows) == ["`%s`" % entry for entry in top]


def test_the_scholar_box_names_only_the_decisions_made():
    assert figure.scholar_text(shared_counts()) == \
        "approves or holds each item, with 2 approved, 1 held, and 3 not yet decided"
    counts = shared_counts(decisions__approved=4, decisions__held=1, decisions__undecided=0)
    assert figure.scholar_text(counts) == "approves or holds each item, with 4 approved and 1 held"
    counts = shared_counts(decisions__approved=0, decisions__held=0, decisions__undecided=3)
    assert figure.scholar_text(counts) == "approves or holds each item, none decided yet"


def test_the_render_and_figure_code_has_no_long_or_en_dash():
    folder = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "publish")
    for path in (os.path.join(folder, "render.py"), os.path.join(folder, "figure.py"),
                 os.path.abspath(__file__)):
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        assert chr(0x2014) not in text and chr(0x2013) not in text, path
