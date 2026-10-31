"""The references procedure, version 0.2, built to the authors' four steps for citations
(2026-10-30, Track C2 step C2).

1. Identify the citations that made it to the final build.
2. Determine which citations originated in some way from an AI.
3. For each AI citation, say whether it can be found, and for each real one give the
   sentence, the reason it was used, and a quote, with a check that the quote is in the
   source text.
4. Use the session transcripts, logs, and artifacts as much as possible.

No model gives a verdict, a severity, a fix, or a second opinion. The one model step
locates a passage when the record holds no quote. The fixtures are synthetic, with
synthetic provenance records. The passage step uses recorded answers and lookups stay
offline (VG_OFFLINE=1), so nothing here calls a model or the network."""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
VG = [sys.executable, str(ROOT / "vg.py")]
FIX = ROOT / "fixtures" / "citations"
GRAPH = "graphs/citations.yaml"
IMPL = ROOT / "implementations" / "citations"
ORDER = ["pin_document", "extract_citations", "match_references", "read_origin", "fetch_metadata",
         "check_existence", "pin_sources", "gather_reason_and_quote", "locate_passage", "verify_quote",
         "report"]
RESULTS = ["id", "citekey", "sentence", "origin", "origin_evidence", "reference", "lookup", "existence",
           "record", "reason", "reason_source", "quotes", "quote_in_source", "access", "source_file",
           "notes", "needs_decision", "sessions"]


def vg(*args):
    env = dict(os.environ, VG_OFFLINE="1")
    return subprocess.run(VG + [str(a) for a in args], cwd=str(ROOT), capture_output=True, text=True, env=env)


def run_inputs(rd, inputs, judge=None):
    judge = judge or Path(inputs) / "recorded_judge.json"
    p = vg("run", GRAPH, "--run", rd, "--inputs", inputs, "--judge", "recorded:%s" % judge)
    assert p.returncode == 0, p.stdout + p.stderr
    return rd


def load(rd, name):
    return json.loads((Path(rd) / "files" / name).read_text(encoding="utf-8"))


def truth(name):
    return yaml.safe_load((FIX / name / "truth.yaml").read_text(encoding="utf-8"))


def items(rd):
    return {it["id"]: it for it in load(rd, "fields.json")["items"]}


@pytest.fixture(scope="module")
def clean(tmp_path_factory):
    return run_inputs(tmp_path_factory.mktemp("clean") / "citations_clean", FIX / "clean")


@pytest.fixture(scope="module")
def seeded(tmp_path_factory):
    return run_inputs(tmp_path_factory.mktemp("seeded") / "citations_seeded", FIX / "seeded")


# ---------------------------------------------------------------- the graph

def test_the_graph_is_version_0_2_with_the_steps_in_the_order_of_the_four_steps():
    p = vg("check", GRAPH)
    assert p.returncode == 0 and p.stdout.startswith("OK"), p.stdout
    g = yaml.safe_load((ROOT / GRAPH).read_text(encoding="utf-8"))
    assert g["version"] == 0.2 and g["schema"] == "schemas/citations.yaml"
    assert [n["id"] for n in g["nodes"]] == ORDER
    assert [(e["from"], e["to"]) for e in g["edges"]] == list(zip(ORDER, ORDER[1:]))
    for e in g["edges"]:
        assert e["condition"] and e["guidance"] and e["pitfalls"], e


def test_the_only_model_step_locates_a_passage_and_no_step_judges_rechecks_or_fixes():
    g = yaml.safe_load((ROOT / GRAPH).read_text(encoding="utf-8"))
    judged = [n for n in g["nodes"] if n["kind"] == "judgment"]
    assert [n["id"] for n in judged] == ["locate_passage"]
    assert judged[0].get("role", "judge") == "judge"
    assert judged[0]["where"] == "status in [to_locate]"
    prompts = sorted(p.name for p in IMPL.glob("*.prompt.md"))
    assert prompts == ["locate_passage.prompt.md"]
    for gone in ("judge_support", "second_check", "draft_fix", "collect_verdicts", "settle_verdicts",
                 "settle_unanimous", "record_verdicts", "reuse_prior", "attribute_origin", "check_access"):
        assert not list(IMPL.glob(gone + ".*")), gone
    prompt = (IMPL / "locate_passage.prompt.md").read_text(encoding="utf-8")
    assert "Give no verdict" in prompt and "no rating, and no fix" in prompt
    contract = yaml.safe_load((ROOT / "contracts" / "citations.yaml").read_text(encoding="utf-8"))
    answer = contract["locate_passage"]["produces"]["locate_passage.json"]["items"]
    assert answer == {"item_id": "str", "kind": ["quote", "section", "paraphrase", "none"],
                      "text": "str", "location": "str"}


def test_the_procedure_reads_the_final_builds_text_and_the_provenance_record():
    contract = yaml.safe_load((ROOT / "contracts" / "citations.yaml").read_text(encoding="utf-8"))
    assert contract["pin_document"]["reads"] == ["draft.md", "citation_provenance.yaml", "refs.yaml",
                                                 "metadata_cache.json"]
    assert contract["read_origin"]["reads"] == ["rows.json", "citation_provenance.yaml"]


# ---------------------------------------------------------------- what the report surfaces

def test_the_seeded_run_surfaces_every_planted_fault(seeded):
    p = vg("score", "--run", seeded, "--truth", FIX / "seeded" / "truth.yaml")
    assert p.returncode == 0, p.stdout + p.stderr
    score = json.loads((seeded / "score.json").read_text(encoding="utf-8"))
    assert score["faults"] == 13 and score["recall"] == 1.0 and score["missed"] == []


@pytest.mark.parametrize("which", ["clean", "seeded"])
def test_every_finding_is_a_note_and_nothing_ranks_a_citation(which, request):
    rd = request.getfixturevalue(which)
    assert {f["severity"] for f in load(rd, "findings.json")} <= {"info"}
    report = (rd / "files" / "report.md").read_text(encoding="utf-8")
    # A report that ranks nothing has no Summary or Problems section to rank with.
    assert "Blocking" not in report and "Warnings" not in report and "## Problems" not in report
    for word in ("partly supports", "does not support", "problem row", "proposed fix", "second checker",
                 "verdict by"):
        assert word not in report.lower(), word


def test_the_clean_run_has_no_fault_to_surface(clean):
    fields = load(clean, "fields.json")
    assert fields["run"]["n_not_found"] == 0 and fields["run"]["n_quote_not_found"] == 0
    assert fields["run"]["n_no_reason"] == 0 and fields["run"]["n_unknown"] == 0
    for it in fields["items"]:
        if it["origin"] == "ai":
            assert it["lookup"] == "found" and it["reason"] and it["quote_in_source"] == "yes", it["id"]


@pytest.mark.parametrize("which", ["clean", "seeded"])
def test_each_citations_origin_is_read_from_the_provenance_record(which, request):
    rd = request.getfixturevalue(which)
    got = items(rd)
    for rid, origin in truth(which)["origins"].items():
        assert got[rid]["origin"] == origin, rid


def test_the_scholars_citations_are_listed_and_never_checked(seeded):
    not_checked = truth("seeded")["not_checked"]
    looked_up = [lk["id"] for lk in load(seeded, "lookups.json")]
    for name in ("findings_check_existence.json", "findings_gather_reason_and_quote.json",
                 "findings_verify_quote.json"):
        assert not [f for f in load(seeded, name) if f["item"] in not_checked], name
    got = items(seeded)
    for rid in ("r03", "r15"):
        it = got[rid]
        assert it["citekey"] not in looked_up
        assert it["origin"] == "scholar" and it["needs_decision"] is False
        assert it["lookup"] == "not_checked" and it["quotes"] == [] and it["reason"] == ""
        assert "sessions" not in it
    assert "r15" not in [p.stem for p in (seeded / "prompts").glob("*/*.txt")]


def test_a_citation_dropped_before_the_final_build_is_not_listed_or_checked(seeded):
    rows = load(seeded, "rows_quoted.json")
    assert "whitlock2020" not in [r["citekey"] for r in rows]
    assert "whitlock2020" not in [lk["id"] for lk in load(seeded, "lookups.json")]
    notes = [f for f in load(seeded, "findings_match_references.json") if f["item"] == "whitlock2020"]
    assert len(notes) == 1 and "not cited in the final build" in notes[0]["message"]


def test_only_ai_citations_are_looked_up_and_what_cannot_be_found_is_a_note(seeded):
    ai_keys = {it["citekey"] for it in items(seeded).values() if it["origin"] == "ai"}
    assert {lk["id"] for lk in load(seeded, "lookups.json")} == ai_keys
    got = items(seeded)
    assert got["r02"]["lookup"] == "not_found" and got["r13"]["lookup"] == "not_found"
    assert got["r02"]["reason"] == "" and got["r02"]["quotes"] == []
    assert got["r01"]["lookup"] == "found" and "found in the metadata cache" in got["r01"]["existence"]
    assert got["r01"]["record"].startswith("Abara, N., Hollis, T. (2019).")
    assert load(seeded, "fields.json")["run"]["n_not_found"] == 2


def test_a_work_with_no_doi_is_listed_as_not_looked_up(tmp_path):
    inputs = tmp_path / "inputs"
    shutil.copytree(str(FIX / "seeded"), str(inputs))
    refs = yaml.safe_load((inputs / "refs.yaml").read_text(encoding="utf-8"))
    for ref in refs["references"]:
        if ref["id"] == "okafor2018":
            del ref["DOI"]
    (inputs / "refs.yaml").write_text(yaml.safe_dump(refs, sort_keys=False), encoding="utf-8")
    rd = run_inputs(tmp_path / "run", inputs, FIX / "seeded" / "recorded_judge.json")
    it = items(rd)["r06"]
    assert it["lookup"] == "not_looked_up" and it["existence"] == "no DOI, not looked up"
    assert load(rd, "fields.json")["run"]["n_not_looked_up"] == 1
    notes = [f for f in load(rd, "findings_check_existence.json") if f["item"] == "okafor2018"]
    assert [(f["severity"], f["message"]) for f in notes] == [
        ("info", "@okafor2018 has no DOI, so it was not looked up")]


def test_the_reason_is_the_record_and_a_missing_one_is_said(seeded):
    got = items(seeded)
    prov = yaml.safe_load((FIX / "seeded" / "citation_provenance.yaml").read_text(encoding="utf-8"))
    assert got["r01"]["reason"] == prov["works"]["abara2019"]["reason"]["text"]
    assert got["r01"]["reason_source"] == "at 2026-10-12T09:00:05Z in session S3a41c0d2e9f7"
    for rid in ("r06", "r09"):
        assert got[rid]["reason"] == "" and got[rid]["lookup"] == "found"
    report = (seeded / "files" / "report.md").read_text(encoding="utf-8")
    assert report.count("- **Reason:** no reason recorded") == 2
    assert load(seeded, "fields.json")["run"]["n_no_reason"] == 2


def test_the_passage_step_asks_only_for_citations_with_no_recorded_quote_in_the_source(seeded):
    # r04's record quote is not in its source, so the step is asked for it too.
    asked = sorted(p.stem for p in (seeded / "prompts").glob("*_locate_passage/*.txt"))
    assert asked == ["r04", "r05", "r06", "r07", "r08", "r09"]
    got = items(seeded)
    assert [q["from"] for q in got["r01"]["quotes"]] == ["record"]
    assert [q["from"] for q in got["r08"]["quotes"]] == ["located"]
    assert got["r10"]["quotes"] == [] and "no source text" in got["r10"]["notes_line"]


def test_every_exact_quote_is_checked_against_the_source_text(seeded):
    got = items(seeded)
    for rid, want in truth("seeded")["quote_in_source"].items():
        assert got[rid]["quote_in_source"] == want, rid
    assert got["r01"]["quotes"][0]["found_at"] == "p. 7"
    assert got["r08"]["quotes"][0]["found_at"] == "p. 15"
    assert got["r07"]["quotes"][0]["kind"] == "section"
    assert "abstract only" in got["r12"]["quote_check_line"]
    # r05's located quote is the one AI citation with no quote found in its source, and
    # r04's record quote, which sent it to the passage step, the one record quote not found.
    run = load(seeded, "fields.json")["run"]
    assert run["n_quote_not_found"] == 1 and run["n_record_quote_not_found"] == 1


def test_the_evidence_names_the_session_time_and_excerpt_and_no_full_path(seeded):
    got = items(seeded)
    assert got["r07"]["origin_evidence"] == (
        "First named by an AI at 2026-10-13T10:01:00Z in session S7be25f19c0a4 in notes/sources.md, "
        "where the record reads \"Marchetti (2012) studies the records volunteers leave behind.\"")
    assert got["r01"]["sessions"] == ["S3a41c0d2e9f7"] and got["r01"]["session_line"] == "S3a41c0d2e9f7"
    report = (seeded / "files" / "report.md").read_text(encoding="utf-8")
    assert str(seeded) not in report and "/Users/" not in report and str(ROOT) not in report


def test_ai_citations_and_those_the_record_never_names_wait_for_the_scholar(seeded):
    results = json.loads((seeded / "results.json").read_text(encoding="utf-8"))
    deciding = [it["id"] for it in results["items"] if it["needs_decision"]]
    by_origin = {it["id"]: it["origin"] for it in results["items"]}
    assert deciding == [rid for rid, o in by_origin.items() if o in ("ai", "unknown")]
    assert [list(it) for it in results["items"]] == [
        [k for k in RESULTS if k != "sessions" or by_origin[it["id"]] == "ai"] for it in results["items"]]


def test_the_report_leads_with_the_counts_and_gives_each_citation(seeded):
    md = (seeded / "files" / "report.md").read_text(encoding="utf-8")
    heads = [ln[3:] for ln in md.splitlines() if ln.startswith("## ")]
    assert heads == ["Citations", "Notes"]
    lead = md.split("## Citations")[0]
    for row in ("| Citations in the final build | 15 |", "| From an AI | 11 |", "| Works not found | 2 |",
                "| AI citations with no quote found in their source | 1 |",
                "| Quotes in the record not found in their source | 1 |", "| AI citations with no recorded reason | 2 |"):
        assert row in lead, row
    assert md.index("**From an AI (11)**") < md.index("**Never named in the record (2)**") < md.index(
        "**The scholar's citations, not checked further (2)**")
    for label in ("Sentence", "Origin", "Session", "Reference", "Found", "Reason", "Quote", "Quote check",
                  "Trail"):
        assert "- **%s:**" % label in md, label
    cited = set(re.findall(r"\b(\d\d_[a-z_]+)\b", md))
    have = {p.stem for p in (seeded / "records").iterdir()}
    assert cited and cited <= have, cited - have
    assert "—" not in md


@pytest.mark.parametrize("which", ["clean", "seeded"])
def test_verify_replays_every_tool_step_with_the_report(which, request):
    rd = request.getfixturevalue(which)
    p = vg("verify", "--run", rd)
    assert p.returncode == 0, p.stdout
    for s in json.loads((rd / "verify.json").read_text())["steps"]:
        if s["node"] == "fetch_metadata":
            assert s["verdict"].startswith("network step")
        elif s["node"] == "locate_passage":
            assert s["verdict"].startswith("judgment")
        else:
            assert s["verdict"] == "replay matches", s


@pytest.mark.parametrize("which", ["clean", "seeded"])
def test_the_report_is_written_by_the_one_builder_and_the_results_carry_the_schemas_fields(which, request):
    rd = request.getfixturevalue(which)
    code = [d for d in os.listdir(str(rd / "code")) if d.endswith("_report")][0]
    assert sorted(os.listdir(str(rd / "code" / code))) == ["_lib.py", "_report.py", "report.py", "schema.yaml"]
    fields = load(rd, "fields.json")
    assert fields["schema"] == {"stream": "citations", "version": 4}
    assert load(rd, "findings_completeness.json") == []
    assert [it["id"] for it in fields["items"]] == [r["id"] for r in load(rd, "rows_quoted.json")]
    schema = yaml.safe_load((ROOT / "schemas" / "citations.yaml").read_text(encoding="utf-8"))
    assert schema["results"] == RESULTS
    results = json.loads((rd / "results.json").read_text())
    assert results["items"] == [{k: it[k] for k in RESULTS if k in it} for it in fields["items"]]


def test_a_record_quote_not_in_the_source_sends_the_citation_to_the_passage_step(seeded):
    # The record's quote for r04 is not in its source, so the passage step locates one,
    # and the program checks both. The record's quote is kept and shown as not found.
    rows = {r["id"]: r for r in load(seeded, "rows_quoted.json")}
    r04 = rows["r04"]
    assert r04["status"] == "to_locate"
    assert [(q["from"], q["in_source"]) for q in r04["quotes"]] == [("record", "no"), ("located", "yes")]
    assert r04["quote_in_source"] == "yes"
    notes = [f["message"] for f in load(seeded, "findings.json") if f["item"] == "r04"]
    assert any("not in its source text" in n for n in notes), notes
    # A citation whose record quote is in its source is not sent to the passage step.
    assert all(r["status"] != "to_locate" for r in rows.values() if r["id"] == "r01")
