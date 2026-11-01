"""Publish design A.3 and R11. Every number the repository shows, from results items and ledgers.

The results here are small and made by hand, so each rule is seen alone. One
test builds results shaped like the published demo's and checks that the
rules give the demo's numbers.

Run from the repository root as python3 -m pytest -q features/tests.
"""
import collections
import json

from features.publish import collect, counts, model

NOW_DATE = "2026-10-31"
EPOCH = 1793404800


def ledger(count, last_date=NOW_DATE, verification="unverified: prose, citations, data, build"):
    rows = []
    for index in range(1, count + 1):
        day = last_date if index == count else "2026-10-30"
        rows.append(model.LedgerRow("v%03d" % index, day, "-", "sha%d" % index, "draft",
                                    verification, "-", collect._epoch(day)))
    return rows


def product(name, rows=0, verification_dir=None, **fields):
    built = ledger(rows, **fields) if rows else []
    return model.Product(name, "%s.md" % name, "builds/%s" % name,
                         verification_dir or "verification/%s" % name, "docx", built,
                         built[-1] if built else None)


def group(*products):
    names = [item.name for item in products]
    return model.Group("+".join(names), tuple(products), products[0].verification_dir,
                       collect._label(names))


def results(stream, run_id, items, decisions=()):
    return {"schema": "verification-results", "schema_version": 1, "stream": stream,
            "run_id": run_id, "procedure_version": 0.1, "inputs": {}, "items": list(items),
            "decisions": list(decisions)}


def report(owner, stream, items, run_id=None, decisions=()):
    run_id = run_id or "%s_%s" % (owner.key, stream)
    found = results(stream, run_id, items, decisions)
    return model.Report(owner, stream, run_id, found, json.dumps(found).encode("utf-8"),
                        b"# Report\n", "project", None)


def collected(products, groups, reports, pipeline=None, numbers_keys=(), refs_works=0,
              harness_names=None):
    answers = collect.read_answers(None, "project", {})
    if harness_names:
        names = collections.OrderedDict(answers.harness_names)
        names.update(harness_names)
        answers = answers._replace(harness_names=names)
    return model.Collected(
        project_dir="project", answers=answers, products=list(products), groups=list(groups),
        reports=list(reports), makefile_style="workflow_var", project_files={}, left_out=[],
        rewritten=[], pipeline=pipeline, numbers_keys=list(numbers_keys), refs_works=refs_works,
        notes=[], excluded_folders=[], workflow_root="workflow", workflow_commit="unknown")


def finding(check, severity, message="m"):
    return {"check": check, "severity": severity, "message": message, "evidence": ""}


def item(item_id, kind, findings=(), needs_decision=True, **fields):
    found = {"id": item_id, "kind": kind, "summary": fields.pop("summary", "x"),
             "findings": list(findings), "needs_decision": needs_decision}
    found.update(fields)
    return found


def session_rows(contributions, harnesses):
    return [collections.OrderedDict((("public_id", "S%012x" % index),
                                     ("harness", harnesses[index % len(harnesses)]),
                                     ("contributions", str(value))))
            for index, value in enumerate(contributions)]


# Results shaped like the demo's.


def prose_items(changes, ai, no_reason, content, findings_items=0):
    found = []
    for index in range(changes):
        marks = []
        if index < no_reason:
            marks.append(finding("rationale_coverage", "blocking",
                                 "AI change with no recorded reason"))
        if index < content:
            marks.append(finding("content_handoff", "warning", "content change"))
        found.append(item("c%03d" % index, "change", marks, needs_decision=index < ai))
    for index in range(findings_items):
        found.append(item("r%02d" % index, "finding",
                          [finding("rationale_coverage", "blocking", "x")]))
    return found


def citation_items(scholar, ai, no_quote, not_looked_up):
    found = [item("draft.md", "finding", citekey="", needs_decision=False)]
    for index in range(scholar):
        found.append(item("s%02d" % index, "citation", citekey="scholar%d" % index,
                          origin="scholar", lookup="not_checked", needs_decision=False))
    for index in range(ai):
        key = not_looked_up[index] if index < len(not_looked_up) else "work%d" % index
        found.append(item("a%02d" % index, "citation", citekey=key, origin="ai",
                          lookup="not_looked_up" if index < len(not_looked_up) else "found",
                          reason="because", quote_in_source="no" if index >= ai - no_quote
                          else "yes", quotes=[{"from": "record", "in_source": "no"}]))
    return found


def data_items():
    found = [item("key%d" % index, "number", summary="key = 1, rerun 1, from a.csv")
             for index in range(152)]
    for index in range(22):
        script = ("s1.py", "s2.py", "helper.py")[index % 3]
        reason = index < 10
        found.append(item("e%02d" % index, "change",
                          [finding("attribute_ai", "blocking")] if reason else [],
                          summary="AI %s to %s, %s" % ("write" if index % 2 else "edit", script,
                                                       "no recorded reason" if reason
                                                       else "reason recorded")))
    for index in range(37):
        marks = [finding("attribute_ai", "warning", "a parameter the AI set")]
        if index < 9:
            marks.append(finding("attribute_ai", "blocking", "no recorded reason"))
        found.append(item("params.yaml:p%d" % index, "parameter", marks))
    found.append(item("s1.py", "finding", [finding("check_docs", "warning")]))
    return found


def build_items():
    found = [item("proposal", "deliverable", summary="source proposal.md"),
             item("appendix", "deliverable", summary="source appendix.md")]
    for prefix, blocking, warnings in (("proposal.md", 10, 4), ("appendix.md", 71, 55)):
        for index in range(blocking + warnings):
            severity = "blocking" if index < blocking else "warning"
            found.append(item("%s:%d" % (prefix, index), "finding",
                              [finding("check_hardcoding", severity, "Bare numeral")]))
    found.append(item("build_prefs.yaml", "finding",
                      [finding("check_prefs", "warning", "The author's build preferences")]))
    return found


def phase_items(missing, not_found, confirmed):
    found = []
    for index in range(missing + not_found + confirmed):
        if index < missing:
            marks = [finding("check_descriptions", "warning", "The finding step gave no place in"
                             " the scripts that carries out this description.")]
        elif index < missing + not_found:
            marks = [finding("check_descriptions", "warning",
                             "The place s1.py 3-9 is not in the scripts.")]
        else:
            marks = [finding("check_descriptions", "warning",
                             "The quote is not in the final build's text.")]
        found.append(item("d%02d" % index, "description", marks))
    return found


def demo():
    proposal = product("proposal", rows=6)
    appendix = product("appendix", rows=10)
    first, second = group(proposal), group(appendix)
    not_looked_up = ["healy2020", "kapoor2026", "oxford2026", "wiley2025"]
    reports = [
        report(first, "prose", prose_items(72, 72, 56, 60, findings_items=12)),
        report(first, "citations", citation_items(3, 32, 7, not_looked_up)),
        report(first, "build", build_items()),
        report(second, "prose", prose_items(201, 185, 130, 98, findings_items=170)),
        report(second, "citations", citation_items(0, 3, 0, ["healy2020"])),
        report(second, "data", data_items()),
        report(second, "build", build_items()),
        report(second, "data_collection", []),
        report(second, "data_cleaning", []),
        report(second, "data_analysis", phase_items(28, 0, 19)),
    ]
    pipeline = {"steps": [{"id": "artifact", "script": "s1.py"}, {"id": "live",
                                                                 "script": "./s2.py"}]}
    return collected([proposal, appendix], [first, second], reports, pipeline=pipeline,
                     numbers_keys=["key%d" % index for index in range(152)], refs_works=30)


def test_the_rules_give_the_demo_numbers():
    rows = session_rows([0] * 162 + [15] * 18 + [22], ["claude_code", "forgecode"])
    found = counts.count_all(demo(), rows)
    expected = {
        "prose.changes": 273, "prose.ai": 257, "prose.no_reason": 186, "prose.content": 158,
        "prose.reports": 2, "prose.proposal.changes": 72, "prose.appendix.ai": 185,
        "citations.rows": 38, "citations.ai": 35, "citations.scholar": 3, "citations.unknown": 0,
        "citations.no_quote": 7, "citations.not_looked_up": 4, "citations.not_found": 0,
        "citations.record_quote_not_found": 35, "citations.no_reason": 0,
        "citations.proposal.not_looked_up": 4, "citations.appendix.not_looked_up": 1,
        "data.numbers": 152, "data.reproduce": 152, "data.changes": 22,
        "data.change_no_reason": 10, "data.parameters": 37, "data.parameter_no_reason": 9,
        "data.scripts": 2, "data.scripts_ai": 2, "data.reports": 1,
        "phases.appendix.data_analysis.descriptions": 47,
        "phases.appendix.data_analysis.missing": 28,
        "phases.appendix.data_analysis.not_found": 0,
        "phases.appendix.data_analysis.confirmed": 19,
        "phases.appendix.data_collection.descriptions": 0,
        "build.blocking": 81, "build.warnings": 60, "build.hardcoding": 81, "build.ai_writes": 0,
        "build.one_source": 1, "build.reports": 2,
        "builds.total": 16, "builds.proposal.latest": "v006", "builds.appendix.latest": "v010",
        "builds.proposal.date": NOW_DATE, "builds.proposal.epoch": EPOCH,
        "builds.appendix.epoch": EPOCH, "builds.proposal.sha256": "sha6",
        "builds.proposal.state": "unverified: no data report",
        "builds.appendix.state": "unverified until the scholar decides",
        "decisions.approved": 0, "decisions.held": 0,
        "numbers.total": 152, "refs.works": 30,
        "sessions.indexed": 181, "sessions.contributing": 19, "sessions.contributions": 292,
        "sessions.harnesses": "Claude Code; ForgeCode",
        "missing": "proposal/data",
    }
    assert dict((key, found[key]) for key in expected) == expected
    needing = sum(1 for each in demo().reports if each.stream in model.STREAMS
                  for entry in each.results["items"] if entry["needs_decision"])
    assert found["decisions.undecided"] == needing


def test_the_keys_come_in_a_fixed_order():
    found = counts.count_all(demo(), session_rows([1], ["claude_code"]))
    keys = list(found)
    assert keys[:5] == ["prose.changes", "prose.ai", "prose.no_reason", "prose.content",
                        "prose.reports"]
    assert keys[5:9] == ["prose.proposal.changes", "prose.proposal.ai",
                         "prose.proposal.no_reason", "prose.proposal.content"]
    starts = [key for key in keys if key.count(".") == 1 or key == "missing"]
    assert starts[-6:] == ["refs.works", "sessions.indexed", "sessions.contributing",
                           "sessions.contributions", "sessions.harnesses", "missing"]
    assert keys.index("data.reports") < keys.index("data.appendix.numbers") \
        < keys.index("phases.appendix.data_collection.descriptions") \
        < keys.index("build.blocking") < keys.index("builds.total") \
        < keys.index("builds.proposal.latest") < keys.index("decisions.approved") \
        < keys.index("numbers.total")
    assert "data.proposal.numbers" not in found
    assert [key for key in keys if key.startswith("builds.proposal.")] == [
        "builds.proposal.latest", "builds.proposal.date", "builds.proposal.sha256",
        "builds.proposal.epoch", "builds.proposal.state"]


def test_every_value_is_a_whole_number_except_the_named_text_keys():
    found = counts.count_all(demo(), session_rows([1], ["claude_code"]))
    text = [key for key, value in found.items() if not isinstance(value, int)]
    assert text == ["builds.proposal.latest", "builds.proposal.date", "builds.proposal.sha256",
                    "builds.proposal.state", "builds.appendix.latest", "builds.appendix.date",
                    "builds.appendix.sha256", "builds.appendix.state", "sessions.harnesses",
                    "missing"]
    assert not any(isinstance(value, bool) for value in found.values())


# One rule at a time.


def test_citation_works_are_counted_once_across_groups():
    paper, slides = product("paper"), product("slides")
    first, second = group(paper), group(slides)
    rows = [item("r1", "citation", citekey="w1", origin="ai", lookup="not_found"),
            item("r2", "citation", citekey="w1", origin="ai", lookup="not_found"),
            item("r3", "citation", citekey="w2", origin="ai", lookup="not_looked_up"),
            item("r4", "citation", citekey="w9", origin="scholar", lookup="not_found"),
            item("r5", "citation", citekey="w5", origin="unknown", lookup="found")]
    found = counts.count_all(collected([paper, slides], [first, second],
                                       [report(first, "citations", rows),
                                        report(second, "citations", rows[:3])]), None)
    assert found["citations.rows"] == 8
    assert found["citations.unknown"] == 1
    assert found["citations.not_found"] == 1
    assert found["citations.not_looked_up"] == 1
    assert found["citations.paper.not_found"] == 1
    assert found["citations.reports"] == 2
    assert found["citations.no_reason"] == 0


def test_numbers_that_do_not_reproduce_and_script_changes_are_counted():
    paper = product("paper")
    owner = group(paper)
    items = [item("a", "number"), item("b", "number", [finding("check_numbers", "blocking")]),
             item("e1", "change", summary="AI write to ./s1.py, no recorded reason"),
             item("e2", "change", summary="AI edit to other.py, reason recorded"),
             item("e3", "change", summary="An edit to s2.py by the scholar")]
    pipeline = {"steps": [{"script": "s1.py"}, {"script": "s2.py"}, "not a step"]}
    found = counts.count_all(collected([paper], [owner], [report(owner, "data", items)],
                                       pipeline=pipeline), None)
    assert (found["data.numbers"], found["data.reproduce"]) == (2, 1)
    assert (found["data.scripts"], found["data.scripts_ai"]) == (2, 1)
    assert found["data.paper.changes"] == 3


def test_no_pipeline_gives_no_scripts():
    paper = product("paper")
    owner = group(paper)
    found = counts.count_all(collected([paper], [owner], [report(owner, "data", [])]), None)
    assert (found["data.scripts"], found["data.scripts_ai"]) == (0, 0)


def test_a_place_that_is_not_found_is_neither_missing_nor_confirmed():
    paper = product("paper")
    owner = group(paper)
    items = phase_items(2, 3, 4) + [item("d99", "description", [finding(
        "check_descriptions", "warning",
        "The finding step gave a place that cannot be read, so it is not checked.")])]
    found = counts.count_all(collected([paper], [owner],
                                       [report(owner, "data_analysis", items)]), None)
    assert [found["phases.paper.data_analysis.%s" % name] for name in
            ("descriptions", "missing", "not_found", "confirmed")] == [10, 2, 4, 4]
    assert "phases.paper.data_cleaning.descriptions" not in found


# The build (design R11).


def test_build_findings_count_by_owner_and_project_level_ones_once():
    proposal, appendix = product("proposal"), product("appendix")
    first, second = group(proposal), group(appendix)
    shared = item("build_prefs.yaml", "finding", [finding("check_prefs", "warning", "prefs")])
    one = [item("proposal", "deliverable"),
           item("proposal.md:1", "finding", [finding("check_hardcoding", "blocking")]),
           item("builds/proposal/v001.docx", "finding",
                [finding("check_ai_touch", "blocking", "AI touched the deliverable")]),
           item("appendix.md:1", "finding", [finding("check_hardcoding", "blocking")] * 5),
           shared]
    two = [item("appendix", "deliverable"),
           item("appendix.md:1", "finding", [finding("check_hardcoding", "blocking")] * 2),
           item("proposal.md:1", "finding", [finding("check_hardcoding", "blocking")] * 9),
           shared, item("build_prefs.yaml", "finding", [finding("check_prefs", "warning",
                                                                "other")])]
    found = counts.count_all(collected([proposal, appendix], [first, second],
                                       [report(first, "build", one),
                                        report(second, "build", two)]), None)
    assert found["build.blocking"] == 1 + 1 + 2
    assert found["build.hardcoding"] == 1 + 2
    assert found["build.ai_writes"] == 1
    assert found["build.warnings"] == 2
    assert found["build.reports"] == 2


def test_items_of_a_product_whose_group_has_no_build_file_are_not_counted():
    proposal, appendix = product("proposal"), product("appendix")
    first, second = group(proposal), group(appendix)
    items = [item("proposal.md:1", "finding", [finding("check_hardcoding", "blocking")]),
             item("appendix.md:1", "finding", [finding("check_hardcoding", "blocking")]),
             item("appendix.mdx", "finding", [finding("check_hardcoding", "blocking")])]
    found = counts.count_all(collected([proposal, appendix], [first, second],
                                       [report(first, "build", items)]), None)
    assert found["build.blocking"] == 2
    assert found["missing"] == ("proposal/prose; proposal/citations; proposal/data; "
                                "appendix/prose; appendix/citations; appendix/data; "
                                "appendix/build")


def test_one_source_turns_off_only_for_the_read_map_findings_that_mean_two_sources():
    paper = product("paper")
    owner = group(paper)

    def one_source(findings):
        items = [item("paper", "deliverable"), item("paper.md", "finding", findings)]
        found = counts.count_all(collected([paper], [owner], [report(owner, "build", items)]),
                                 None)
        return found["build.one_source"]

    assert one_source([]) == 1
    assert one_source([finding("read_map", "warning", "The canonical file is not a"
                               " prerequisite of the rule.")]) == 1
    assert one_source([finding("read_map", "warning", "Competing canonical file")]) == 0
    assert one_source([finding("read_map", "warning", "The ARCHIVE line is wrong")]) == 0
    assert one_source([finding("read_map", "blocking", "A map entry must name exactly one")]) == 0


def test_a_shared_verification_folder_is_counted_once():
    manuscript = product("manuscript", verification_dir="verification")
    slides = product("slides", verification_dir="verification")
    owner = group(manuscript, slides)
    items = [item("c1", "change"), item("c2", "change", needs_decision=False)]
    found = counts.count_all(collected([manuscript, slides], [owner],
                                       [report(owner, "prose", items)]), None)
    assert found["prose.changes"] == 2
    assert found["prose.manuscript+slides.ai"] == 1
    assert found["decisions.undecided"] == 1


# Ledgers and decisions.


def test_a_product_with_no_build_has_no_builds_keys():
    paper, slides = product("paper", rows=2), product("slides")
    found = counts.count_all(collected([paper, slides], [group(paper), group(slides)], []), None)
    assert found["builds.total"] == 2
    assert not any(key.startswith("builds.slides.") for key in found)
    assert found["builds.paper.state"] == "unverified: no prose report"


def test_a_verified_ledger_row_gives_the_verified_state():
    paper = product("paper", rows=1, verification="verified")
    owner = group(paper)
    reports = [report(owner, stream, []) for stream in model.STREAMS]
    found = counts.count_all(collected([paper], [owner], reports), None)
    assert found["builds.paper.state"] == "verified"
    assert found["missing"] == ""


def test_only_the_latest_decision_on_the_files_run_counts():
    paper = product("paper")
    owner = group(paper)

    def decided(item_id, decision, run_id="paper_prose"):
        return {"item": item_id, "decision": decision, "by": "A. Scholar", "at": NOW_DATE,
                "run_id": run_id}

    items = [item("c1", "change"), item("c2", "change"), item("c3", "change"),
             item("c4", "change"), item("c5", "change"), item("c6", "change",
                                                              needs_decision=False)]
    decisions = [decided("c1", "approved"), decided("c2", "approved"), decided("c2", "held"),
                 decided("c3", "approved", run_id="older_run"), decided("c4", "held"),
                 decided("c4", "approved", run_id="older_run"), decided("c6", "approved")]
    found = counts.count_all(collected([paper], [owner],
                                       [report(owner, "prose", items, decisions=decisions)]),
                             None)
    assert (found["decisions.approved"], found["decisions.held"],
            found["decisions.undecided"]) == (1, 1, 3)


def test_phase_items_are_not_counted_as_decisions():
    paper = product("paper")
    owner = group(paper)
    found = counts.count_all(collected([paper], [owner],
                                       [report(owner, "data_analysis", phase_items(1, 0, 1))]),
                             None)
    assert found["decisions.undecided"] == 0


def test_phase_items_that_need_a_decision_are_counted_apart():
    paper = product("paper")
    owner = group(paper)
    items = phase_items(1, 0, 1)
    for found_item in items:
        found_item["needs_decision"] = True
    decisions = [{"item": items[0]["id"], "decision": "approved", "by": "the scholar",
                  "at": NOW_DATE, "run_id": "paper_data_analysis"}]
    found = counts.count_all(collected([paper], [owner], [report(
        owner, "data_analysis", items, decisions=decisions)]), None)
    assert (found["phases.decisions.approved"], found["phases.decisions.held"],
            found["phases.decisions.undecided"]) == (1, 0, len(items) - 1)
    # No phase report gives no phase decision keys.
    found = counts.count_all(collected([paper], [owner], [report(owner, "prose", [])]), None)
    assert not [key for key in found if key.startswith("phases.decisions.")]


def test_a_build_marked_before_every_item_was_approved_waits_for_the_next_build():
    paper = product("paper", rows=1)
    owner = group(paper)

    def approved(stream):
        return [{"item": "c1", "decision": "approved", "by": "the scholar", "at": NOW_DATE,
                 "run_id": "paper_%s" % stream}]
    reports = [report(owner, stream, [item("c1", "change")], decisions=approved(stream))
               for stream in model.STREAMS]
    found = counts.count_all(collected([paper], [owner], reports), None)
    assert found["builds.paper.state"] == counts.REBUILD_STATE
    reports[0] = report(owner, "prose", [item("c1", "change")])
    found = counts.count_all(collected([paper], [owner], reports), None)
    assert found["builds.paper.state"] == counts.UNDECIDED_STATE


def test_a_verified_row_that_names_other_runs_was_marked_before_the_results():
    paper = product("paper", rows=1, verification="verified")
    row = paper.latest._replace(runs="prose=paper_prose; citations=old_citations")
    paper = paper._replace(latest=row, ledger=[row])
    owner = group(paper)
    reports = [report(owner, stream, []) for stream in model.STREAMS]
    assert counts.marked_before(collected([paper], [owner], reports)) == [(paper, "v001")]
    row = row._replace(runs="; ".join("%s=paper_%s" % (stream, stream) for stream in model.STREAMS))
    paper = paper._replace(latest=row, ledger=[row])
    owner = group(paper)
    reports = [report(owner, stream, []) for stream in model.STREAMS]
    assert counts.marked_before(collected([paper], [owner], reports)) == []


# The session index.


def test_no_session_rows_leaves_out_the_session_keys():
    found = counts.count_all(demo(), None)
    assert not any(key.startswith("sessions.") for key in found)


def test_harness_names_come_from_the_answers_and_are_sorted():
    rows = session_rows([2, 0, 1, "", "x"], ["forgecode", "claude_code", "open_hands", "aider", ""])
    found = counts.count_all(collected([], [], [], harness_names={"aider": "Aider"}), rows)
    assert found["sessions.harnesses"] == "Aider; Claude Code; ForgeCode; Open Hands"
    assert (found["sessions.indexed"], found["sessions.contributing"],
            found["sessions.contributions"]) == (5, 2, 3)


def test_read_sessions_csv_gives_ordered_rows():
    text = ('public_id,harness,contributions,references\n'
            'S0123456789ab,claude_code,2,"proposal/prose/c1 (not yet decided, run p); x"\n'
            '\n'
            'S0123456789ac,forgecode,0\n')
    rows = counts.read_sessions_csv(text)
    assert rows == [
        collections.OrderedDict((("public_id", "S0123456789ab"), ("harness", "claude_code"),
                                 ("contributions", "2"),
                                 ("references", "proposal/prose/c1 (not yet decided, run p); x"))),
        collections.OrderedDict((("public_id", "S0123456789ac"), ("harness", "forgecode"),
                                 ("contributions", "0"), ("references", "")))]
    assert all(isinstance(row, collections.OrderedDict) for row in rows)
    assert counts.read_sessions_csv("") == []
