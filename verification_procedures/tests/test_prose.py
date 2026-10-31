"""Prose stream, version 0.3 (Track V, step V1): graph check, clean and seeded fixtures,
replay, and the report built for the scholar's verification.

the authors ruled on 2026-10-30 that a verification report is a verification step for the
human and that no AI makes its decisions. The report lists each change between the
scholar's last draft (baseline.md) and the final build's text (revised.md). A change is
the AI's when the record of the AI's changes (rationales.yaml, as the audit layer writes
it out) names it, and every other change is the scholar's own, listed and not checked.
Each AI change shows its sentence before and after and the reason the record gives, a
program notes each AI change with no recorded reason and points out each one that alters
a number, a citation, a quotation, a negation, or a claim's strength, and each AI change
is an item for the scholar to approve or hold. No step asks a model, so no run takes
--judge, and nothing here calls a model or the network.
"""
import json
import os
import shutil
import subprocess
import sys

import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GRAPH = os.path.join(ROOT, "graphs", "prose.yaml")
FIX = os.path.join(ROOT, "fixtures", "prose")
GRAPH_NODES = ["pin_versions", "diff_changes", "exclude_author", "content_handoff",
               "rationale_coverage"]


def vg(*args):
    return subprocess.run([sys.executable, os.path.join(ROOT, "vg.py")] + list(args),
                          capture_output=True, text=True, cwd=ROOT)


def run_fixture(tmp_path, name, inputs=None):
    inputs = inputs or os.path.join(FIX, name)
    run = str(tmp_path / ("run_" + name))
    proc = vg("run", GRAPH, "--run", run, "--inputs", inputs)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return run


def load(run, name):
    with open(os.path.join(run, "files", name)) as f:
        return json.load(f)


def report_text(run):
    with open(os.path.join(run, "files", "report.md"), encoding="utf-8") as f:
        return f.read()


def fixture_yaml(name, fname):
    with open(os.path.join(FIX, name, fname), encoding="utf-8") as f:
        return yaml.safe_load(f)


def problems(findings):
    return [f for f in findings if f["severity"] in ("blocking", "warning")]


def items_by_id(run):
    return {it["id"]: it for it in load(run, "fields.json")["items"]}


@pytest.fixture(scope="module")
def seeded(tmp_path_factory):
    return run_fixture(tmp_path_factory.mktemp("prose"), "seeded")


@pytest.fixture(scope="module")
def clean(tmp_path_factory):
    return run_fixture(tmp_path_factory.mktemp("prose"), "clean")


# ---------------------------------------------------------------- the graph

def test_graph_check():
    proc = vg("check", GRAPH)
    assert proc.returncode == 0, proc.stdout
    assert proc.stdout.startswith("OK")


def test_the_graph_is_version_0_3_and_no_step_asks_a_model():
    with open(GRAPH) as f:
        g = yaml.safe_load(f)
    assert g["version"] == 0.3
    assert [n["id"] for n in g["nodes"]] == GRAPH_NODES + ["report"]
    assert all(n["kind"] == "tool" for n in g["nodes"])
    # the model step that judged whether a reason was honest is removed with its prompt
    assert not [f for f in os.listdir(os.path.join(ROOT, "implementations", "prose"))
                if f.endswith(".prompt.md")]
    with open(os.path.join(ROOT, "contracts", "prose.yaml")) as f:
        contracts = yaml.safe_load(f)
    assert sorted(contracts) == sorted(GRAPH_NODES + ["report"])
    assert contracts["exclude_author"]["reads"] == ["changes.json", "rationales.yaml"]
    assert "author_edits.yaml" not in json.dumps(contracts)


def test_the_fixtures_hold_no_recorded_answers_and_no_list_of_the_scholars_edits():
    for name in ("clean", "seeded"):
        files = os.listdir(os.path.join(FIX, name))
        assert "recorded_judge.json" not in files and "author_edits.yaml" not in files, name


# ---------------------------------------------------------------- the clean and seeded runs

def test_clean_has_no_problems(clean):
    assert problems(load(clean, "findings.json")) == []
    kinds = sorted(c["kind"] for c in load(clean, "changes.json"))
    assert kinds == ["delete", "edit", "edit", "insert", "move"]
    # the record names every change, so every change is the AI's
    assert load(clean, "author_changes.json") == []


def test_seeded_full_recall(seeded):
    proc = vg("score", "--run", seeded, "--truth", os.path.join(FIX, "seeded", "truth.yaml"))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    with open(os.path.join(seeded, "score.json")) as f:
        score = json.load(f)
    assert score["faults"] == 7
    assert score["recall"] == 1.0
    assert score["missed"] == []
    assert score["extra_findings"] == []


def test_seeded_not_flagged(seeded):
    truth = fixture_yaml("seeded", "truth.yaml")
    flagged = {f["item"] for f in problems(load(seeded, "findings.json"))}
    for nf in truth["not_flagged"]:
        assert nf["item"] not in flagged, nf


def test_the_truth_file_plants_the_four_cases_of_the_step():
    truth = fixture_yaml("seeded", "truth.yaml")
    faults = {(t["check"], t["item"]) for t in truth["faults"]}
    assert ("rationale_coverage", "c05") in faults      # an AI change with no reason
    assert ("content_handoff", "c03") in faults         # an AI change that alters a number
    kept = {(t["item"], t.get("kind")) for t in truth["not_flagged"]}
    assert ("c01", "move") in kept                      # a moved sentence
    assert ("c07", "scholar") in kept                   # a scholar's change, never checked


def test_move_is_not_insert_plus_delete(seeded):
    changes = {c["id"]: c for c in load(seeded, "changes.json")}
    move = changes["c01"]
    assert move["kind"] == "move" and move["before"] == move["after"]
    others = [c for c in changes.values() if c["id"] != "c01"]
    assert all(move["after"] not in (c["before"], c["after"]) for c in others)


def test_the_record_marks_the_ai_changes_and_the_rest_are_the_scholars(seeded):
    record = fixture_yaml("seeded", "rationales.yaml")
    ai = {c["id"]: c for c in load(seeded, "ai_changes.json")}
    assert sorted(ai) == ["c01", "c02", "c03", "c04", "c05", "c06", "c08", "c09"]
    assert [c["id"] for c in load(seeded, "author_changes.json")] == ["c07"]
    by_id = {r["id"]: r for r in record}
    for c in ai.values():
        reasons = {by_id[rid]["rationale"] for rid in c["record_id"].split(" and ")}
        assert {c["rationale"]} == reasons, c["id"]
    assert ai["c05"]["record_id"] == "r09" and ai["c05"]["rationale"] == ""


def test_an_ai_change_with_no_recorded_reason_is_noted(seeded):
    found = [f for f in load(seeded, "findings.json")
             if f["check"] == "rationale_coverage" and f["item"] == "c05"]
    assert [(f["severity"], f["message"]) for f in found] == [
        ("blocking", "AI change with no recorded reason")]
    c05 = items_by_id(seeded)["c05"]
    assert "rationale" not in c05 and c05["record_id"] == "r09"
    assert c05["reason_cell"] == "No reason is recorded."
    assert load(seeded, "fields.json")["run"]["n_no_reason"] == 1


def test_each_ai_change_shows_its_sentence_before_and_after_and_its_stated_reason(seeded):
    c03 = items_by_id(seeded)["c03"]
    assert c03["before"] == "We draw on personnel records from 48 agencies in three states [@alvarez2019]."
    assert c03["after"] == "We draw on personnel records from 52 agencies in three states [@alvarez2019]."
    assert c03["rationale"] == "Updated the agency count from 48 to 52 to match the sample table."
    text = report_text(seeded)
    block = text.split("### c03 (edit)", 1)[1].split("###", 1)[0]
    assert "- **Before:** We draw on personnel records from 48 agencies" in block
    assert "- **After:** We draw on personnel records from 52 agencies" in block
    assert "- **Stated reason:** Updated the agency count from 48 to 52" in block
    assert "- **Content changed:** numbers 48 -> 52, for the data stream" in block


def test_an_ai_change_that_alters_a_number_is_pointed_out(seeded):
    found = [f for f in load(seeded, "findings.json")
             if f["check"] == "content_handoff" and f["item"] == "c03"]
    assert len(found) == 1 and found[0]["severity"] == "warning"
    assert found[0]["evidence"] == "numbers 48 -> 52"
    assert found[0]["message"] == "content change, hand off to data stream"
    assert items_by_id(seeded)["c03"]["streams"] == ["data"]


def test_the_scholars_change_is_listed_and_not_checked(seeded):
    c07 = items_by_id(seeded)["c07"]
    assert (c07["by"], c07["needs_decision"], c07["findings"]) == ("author", False, [])
    assert "record_id" not in c07 and "streams" not in c07 and "reason_cell" not in c07
    on_c07 = [f for f in load(seeded, "findings.json") if f["item"] == "c07"]
    assert [(f["check"], f["severity"]) for f in on_c07] == [("exclude_author", "info")]
    assert "c07" not in {t["id"] for t in load(seeded, "content_tokens.json")}
    text = report_text(seeded)
    assert "### c07" not in text
    scholars = text.split("## The scholar's own changes", 1)[1].split("\n## ", 1)[0]
    assert "| c07 | edit |" in scholars


def test_each_ai_change_is_an_item_for_the_scholar_to_approve_or_hold(seeded):
    with open(os.path.join(seeded, "results.json")) as f:
        items = {it["id"]: it for it in json.load(f)["items"]}
    ai = [c["id"] for c in load(seeded, "ai_changes.json")]
    assert all(items[cid]["needs_decision"] is True for cid in ai)
    assert items["c07"]["needs_decision"] is False


def test_no_model_gives_a_verdict(seeded):
    names = os.listdir(os.path.join(seeded, "files"))
    assert not [n for n in names if "judge" in n]
    assert os.listdir(os.path.join(seeded, "prompts")) == []
    for it in load(seeded, "fields.json")["items"]:
        assert not {"honest", "meaning_changed", "verdict_cell"} & set(it), it["id"]
    text = report_text(seeded).lower()
    for word in ("honest", "verdict", "judge_rationale", "meaning changed"):
        assert word not in text, word


def test_handoff_routes_streams(seeded):
    streams = {h["change_id"]: h["streams"] for h in load(seeded, "handoff.json")}
    assert streams == {"c03": ["data"], "c04": ["citations"], "c06": ["citations"], "c08": ["data"]}


def test_verify_replays_every_tool_step(seeded):
    proc = vg("verify", "--run", seeded)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    with open(os.path.join(seeded, "verify.json")) as f:
        steps = json.load(f)["steps"]
    assert [s["node"] for s in steps] == GRAPH_NODES + ["report"]
    assert all(s["verdict"] == "replay matches" for s in steps), steps


def test_report_sections(seeded):
    text = report_text(seeded)
    heads = [ln.lstrip("#").strip() for ln in text.splitlines() if ln.startswith("## ")]
    assert heads == ["Summary", "Problems", "Versions", "AI changes", "The scholar's own changes",
                     "Hand-off", "Trail", "Notes"]
    for cid in ("c01", "c05", "c07", "c09"):
        assert f"- {cid} went through diff_changes (02, python3)" in text
    assert ("- c07 went through diff_changes (02, python3) -> exclude_author (03, the scholar's own change, "
            "not checked)") in text
    assert ("- c03 went through diff_changes (02, python3) -> exclude_author (03, record r03) -> "
            "content_handoff (04, data) -> rationale_coverage (05, reason recorded)") in text
    assert ("- c05 went through diff_changes (02, python3) -> exclude_author (03, record r09) -> "
            "content_handoff (04, no content tokens) -> rationale_coverage (05, no reason recorded); "
            "flagged by rationale_coverage") in text


def test_unpinned_baseline_blocks(tmp_path):
    inputs = tmp_path / "unpinned"
    shutil.copytree(os.path.join(FIX, "clean"), str(inputs))
    (inputs / "versions.yaml").write_text("versions:\n  - {version: v001, file: baseline.md, sha256: 'sha256:00'}\n")
    run = run_fixture(tmp_path, "clean", inputs=str(inputs))
    hits = [f for f in load(run, "findings.json") if f["check"] == "pin_versions" and f["severity"] == "blocking"]
    assert len(hits) == 1 and "unanchored" in hits[0]["message"]


def test_a_record_entry_that_names_an_unchanged_sentence_is_shown(seeded):
    found = [f for f in load(seeded, "findings.json") if f["item"] == "r08"]
    assert [(f["check"], f["severity"], f["message"]) for f in found] == [
        ("rationale_coverage", "warning", "recorded AI change matches no change between the two texts")]
    assert found[0]["evidence"].startswith("anchor text is present unchanged in revised.md, ")


def test_the_evidence_of_the_record_checks_has_no_colon_inside_a_sentence(seeded):
    found = [f for f in load(seeded, "findings.json") if f["check"] == "rationale_coverage"]
    assert found and all(":" not in f["evidence"] for f in found), found


def test_the_handoff_cells_and_trail_lines_have_no_colon(seeded):
    text = report_text(seeded)
    handoff = text.split("## Hand-off", 1)[1].split("\n## ", 1)[0]
    trail = text.split("## Trail", 1)[1].split("\n## ", 1)[0]
    rows = [ln for ln in handoff.splitlines() if ln.startswith("| c")]
    lines = [ln for ln in trail.splitlines() if ln.startswith("- ")]
    assert rows and lines
    assert [ln for ln in rows + lines if ":" in ln] == []
    msgs = {f["message"] for f in load(seeded, "findings.json") if f["check"] == "content_handoff"}
    assert msgs and not [m for m in msgs if ":" in m]


def test_a_move_the_record_gives_as_a_delete_and_an_insert_binds_both_entries(seeded):
    # The audit layer writes an AI move made by two Edits as a delete entry and an insert
    # entry on the same sentence, and the seeded record plants it that way (r01 and r10).
    record = {r["id"]: r for r in fixture_yaml("seeded", "rationales.yaml")}
    assert (record["r01"]["kind"], record["r10"]["kind"]) == ("delete", "insert")
    assert record["r01"]["anchor"] == record["r10"]["anchor"]
    c01 = {c["id"]: c for c in load(seeded, "ai_changes.json")}["c01"]
    assert (c01["record_id"], c01["record_kind"]) == ("r01 and r10", "delete and insert")
    assert c01["rationale"] == record["r01"]["rationale"]
    found = [f for f in load(seeded, "findings.json") if f["item"] in ("c01", "r01", "r10")]
    assert problems(found) == []
    assert "exclude_author (03, record r01 and r10)" in items_by_id(seeded)["c01"]["trail"]


def test_an_entry_of_kind_move_still_binds_the_move(clean):
    record = fixture_yaml("clean", "rationales.yaml")
    assert record[0]["kind"] == "move"
    c01 = [c for c in load(clean, "ai_changes.json") if c["kind"] == "move"][0]
    assert c01["record_id"] == "r01"


def test_an_ai_rewrite_given_as_a_delete_and_an_insert_binds_both_entries(seeded, tmp_path):
    # An AI rewrite made by a delete Edit on the old sentence and an insert Edit on the new
    # one gives a non-moved edit in the diff, and both entries bind to it with no warning.
    c03 = {c["id"]: c for c in load(seeded, "ai_changes.json")}["c03"]
    assert c03["kind"] == "edit" and not c03["moved"]
    inputs = tmp_path / "rewrite_as_pair"
    shutil.copytree(os.path.join(FIX, "seeded"), str(inputs))
    record = fixture_yaml("seeded", "rationales.yaml")
    r03 = [r for r in record if r["id"] == "r03"][0]
    r03.update(anchor=c03["before"], kind="delete")
    record.append({"id": "r11", "anchor": c03["after"], "kind": "insert",
                   "rationale": r03["rationale"]})
    (inputs / "rationales.yaml").write_text(yaml.safe_dump(record, sort_keys=False), encoding="utf-8")
    run = run_fixture(tmp_path, "seeded", inputs=str(inputs))
    got = {c["id"]: c for c in load(run, "ai_changes.json")}["c03"]
    assert (got["record_id"], got["record_kind"]) == ("r03 and r11", "delete and insert")
    found = [f for f in problems(load(run, "findings.json"))
             if f["item"] in ("c03", "r03", "r11") and f["check"] != "content_handoff"]
    assert found == []


def test_a_third_entry_on_a_move_is_not_bound(tmp_path):
    inputs = tmp_path / "three_on_a_move"
    shutil.copytree(os.path.join(FIX, "seeded"), str(inputs))
    record = fixture_yaml("seeded", "rationales.yaml")
    record.append({"id": "r11", "anchor": record[0]["anchor"], "kind": "insert", "rationale": "Again."})
    (inputs / "rationales.yaml").write_text(yaml.safe_dump(record, sort_keys=False), encoding="utf-8")
    run = run_fixture(tmp_path, "seeded", inputs=str(inputs))
    found = [f for f in problems(load(run, "findings.json")) if f["item"] == "r11"]
    assert [(f["check"], f["message"]) for f in found] == [
        ("rationale_coverage", "recorded AI change matches no change between the two texts")]


def test_a_reason_over_several_lines_stays_on_its_line_of_the_report(tmp_path):
    inputs = tmp_path / "long_reason"
    shutil.copytree(os.path.join(FIX, "seeded"), str(inputs))
    record = fixture_yaml("seeded", "rationales.yaml")
    reason = "I'll tighten the opening.\n\n## Plan\n\n- first | second\n# Done"
    record[1]["rationale"] = reason
    (inputs / "rationales.yaml").write_text(yaml.safe_dump(record, sort_keys=False), encoding="utf-8")
    run = run_fixture(tmp_path, "seeded", inputs=str(inputs))
    assert items_by_id(run)["c02"]["rationale"] == reason      # kept word for word
    text = report_text(run)
    assert ("- **Stated reason:** I'll tighten the opening. ## Plan - first | second # Done"
            in text.split("### c02 (edit)", 1)[1])
    heads = [ln for ln in text.splitlines() if ln.startswith("#")]
    assert not [h for h in heads if "Plan" in h or "Done" in h], heads
    assert "- first" not in [ln.strip()[:7] for ln in text.splitlines()]


def test_an_ai_write_of_the_whole_file_is_shown_to_the_scholar(tmp_path):
    # A Write gives no sentences, so the record cannot tell its changes from the scholar's.
    # A program says so on the record entry, and the entry is an item for the scholar.
    inputs = tmp_path / "with_write"
    shutil.copytree(os.path.join(FIX, "clean"), str(inputs))
    record = fixture_yaml("clean", "rationales.yaml")
    record.append({"id": "r06", "anchor": "", "kind": "write", "rationale": "Writing the draft.",
                   "session_ref": "S0123456789ab"})
    (inputs / "rationales.yaml").write_text(yaml.safe_dump(record, sort_keys=False), encoding="utf-8")
    run = run_fixture(tmp_path, "clean", inputs=str(inputs))
    found = [f for f in load(run, "findings.json") if f["item"] == "r06"]
    assert [(f["check"], f["severity"]) for f in found] == [("exclude_author", "blocking")]
    assert found[0]["message"] == ("an AI tool call wrote the whole file, so the record cannot tell "
                                   "which changes are the AI's")
    assert "Writing the draft." in found[0]["evidence"] and ":" not in found[0]["evidence"]
    assert "It came from session S0123456789ab." in found[0]["evidence"]   # names its session
    item = items_by_id(run)["r06"]
    assert item["kind"] == "finding" and item["needs_decision"] is True
    assert all(c["id"] != "r06" for c in load(run, "ai_changes.json"))


def test_the_scholars_own_changes_name_what_the_record_cannot_see(seeded):
    text = report_text(seeded)
    scholars = text.split("## The scholar's own changes", 1)[1].split("\n## ", 1)[0]
    assert ("An AI change made through a shell command, or one the record cannot split such as "
            "a whole file an AI tool call wrote or a sentence an AI moved within one edit, would "
            "also be listed here.") in scholars


# ---------------------------------------------------------------- the schema and the one builder

CHANGE_FIELDS = {"change_kind", "before", "after", "moved", "by", "streams", "record_id",
                 "rationale", "kind_cell", "before_cell", "after_cell", "change_cell",
                 "reason_cell", "content_cell", "trail", "sessions", "session_line"}
W_KEYS = ("id", "kind", "summary", "findings", "needs_decision")


def test_graph_names_its_schema_and_keeps_its_version():
    with open(GRAPH) as f:
        g = yaml.safe_load(f)
    assert g["schema"] == "schemas/prose.yaml"
    with open(os.path.join(ROOT, "schemas", "prose.yaml")) as f:
        schema = yaml.safe_load(f)
    assert schema["stream"] == "prose" and schema["version"] == 3
    assert schema["fields"]["change_kind"]["values"] == ["edit", "insert", "delete", "move"]
    assert schema["fields"]["by"]["values"] == ["ai", "author"]
    assert not {"honest", "meaning_changed", "verdict_cell", "rationale_id"} & set(schema["fields"])
    assert "n_judged" not in schema["run"]
    assert vg("check", GRAPH).returncode == 0


@pytest.mark.parametrize("which", ["clean", "seeded"])
def test_report_is_written_by_the_one_builder(which, request):
    run = request.getfixturevalue(which)
    code = [d for d in os.listdir(os.path.join(run, "code")) if d.endswith("_report")][0]
    assert sorted(os.listdir(os.path.join(run, "code", code))) == [
        "_lib.py", "_report.py", "report.py", "schema.yaml"]
    fields = load(run, "fields.json")
    assert fields["schema"] == {"stream": "prose", "version": 3}
    assert set(fields) == {"schema", "run", "items", "tables"}
    assert set(fields["tables"]) == {"handoff"}
    assert load(run, "findings_completeness.json") == []
    # the items are the ones the results file lists for the prose stream
    with open(os.path.join(run, "results.json")) as f:
        results = json.load(f)
    assert [{k: it[k] for k in W_KEYS} for it in fields["items"]] == [
        {k: it[k] for k in W_KEYS} for it in results["items"]]
    changes = [c["id"] for c in load(run, "changes.json")]
    assert [it["id"] for it in fields["items"] if it["kind"] == "change"] == changes


def test_a_change_item_carries_what_the_steps_found(seeded):
    items = items_by_id(seeded)
    c03 = items["c03"]
    assert (c03["change_kind"], c03["by"], c03["streams"], c03["record_id"]) == ("edit", "ai", ["data"], "r03")
    assert items["c01"]["change_kind"] == "move" and items["c01"]["moved"] is True
    assert items["c07"]["by"] == "author"
    assert items["c07"]["trail"] == ("c07 went through diff_changes (02, python3) -> exclude_author "
                                     "(03, the scholar's own change, not checked)")
    # an item of kind finding carries none of a change's fields
    other = [it for it in items.values() if it["kind"] == "finding"]
    assert [it["id"] for it in other] == ["r08"]
    assert all(not (CHANGE_FIELDS & set(it)) for it in other)


def test_steps_json_lists_every_step_as_ran(seeded):
    steps = load(seeded, "steps.json")["steps"]
    assert [s["node"] for s in steps] == GRAPH_NODES
    assert all(s["status"] == "ran" for s in steps)


def test_verify_replays_the_report_through_the_builder(seeded):
    proc = vg("verify", "--run", seeded)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    with open(os.path.join(seeded, "verify.json")) as f:
        steps = json.load(f)["steps"]
    assert steps[-1] == {"seq": 6, "node": "report", "verdict": "replay matches"}


def test_a_session_named_by_the_record_is_shown_on_its_change(tmp_path):
    inputs = tmp_path / "with_session"
    shutil.copytree(os.path.join(FIX, "seeded"), str(inputs))
    record = fixture_yaml("seeded", "rationales.yaml")
    record[2]["session_ref"] = "S0123456789ab"
    (inputs / "rationales.yaml").write_text(yaml.safe_dump(record, sort_keys=False), encoding="utf-8")
    run = run_fixture(tmp_path, "seeded", inputs=str(inputs))
    c03 = items_by_id(run)["c03"]
    assert c03["sessions"] == ["S0123456789ab"]
    assert "- Change c03 came from session S0123456789ab." in report_text(run)
