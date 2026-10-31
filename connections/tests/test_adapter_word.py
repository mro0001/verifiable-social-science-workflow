"""Tests for the Word adapter (Track D, step D19).

Appendix-only. Table A6 lists an adapter for Word as specified and notes that
the adapter that fills the prose stream's files is not built. A2.5 Prose says
that for Word, programs show AI changes as tracked changes and then read back
the scholar's responses, and the A2.2 Adapters bullet names an adapter from a
Word document with tracked changes to the files the prose procedure checks.

The adapter writes baseline.md, revised.md, rationales.yaml, and versions.yaml,
the files the prose procedure of version 0.3 requires (Track D choices 12, 14,
and 15, and Track V choices 2 and 3). rationales.yaml is the record of the
AI's changes, an entry for each sentence the AI's tracked changes touch, with
the reason the AI's margin comment on that sentence gives after its bracketed
kind, or empty text when no comment covers it. A change no entry names is the
scholar's own.

Every document here is built by the test with docx_builder.py from the prose
procedure's seeded and clean fixtures, sentence by sentence. The adapter
numbers its entries in document order, so the seeded record's ids are
renumbered through SEEDED_ORDER. The prose procedure asks no model, and it is
run offline through vg.py's command line, so no model or network is called.
Every test runs with HOME, CONNECTIONS_HOME, and AUDIT_HOME inside a temporary
folder. Run from the repository root with python3 -m pytest -q
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
import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import docx_builder  # noqa: E402
from connections.adapters import ADAPTERS  # noqa: E402
from connections.adapters.word import sentences  # noqa: E402
from connections.cli import main  # noqa: E402

VP = ROOT / "verification_procedures"
FIX = VP / "fixtures" / "prose"
SEEDED = FIX / "seeded"
CLEAN = FIX / "clean"
GRAPH = "graphs/prose.yaml"

AI = "AI Reviewer"
SCHOLAR = "Scholar"
FILLS = ("baseline.md", "revised.md", "rationales.yaml", "versions.yaml")
TITLE = (("Heading 1", [("plain", "Hiring practices and early turnover")]),)
PRIOR = "Prior work has focused mainly on private firms."
OPENING = ("This study examines whether structured interviews are associated with lower first-year turnover in"
           " municipal agencies.")
PATTERN = "This pattern held across agencies of different sizes."

# The seeded fixture's drafts as one Word document, sentence by sentence. Every
# AI change is a tracked change by the AI author, and the author's edit is a
# tracked change by the scholar.
SEEDED_PARAGRAPHS = TITLE + (
    (None, [
        ("plain", "Local governments face persistent difficulty retaining new hires. "),
        ("moveTo", "Prior work has focused mainly on private firms. ", AI),
        ("del", "In this study we examine", AI),
        ("ins", "This study examines", AI),
        ("plain", " whether structured interviews are associated with lower first-year turnover in municipal"
                  " agencies. We draw on personnel records from "),
        ("del", "48", AI),
        ("ins", "52", AI),
        ("plain", " agencies in three states [@alvarez2019]. "),
        ("del", "Turnover in the first year is", AI),
        ("ins", "First-year turnover is especially", AI),
        ("plain", " costly for small agencies [@"),
        ("del", "kim2018", AI),
        ("ins", "park2020", AI),
        ("plain", "]."),
        ("moveFrom", " Prior work has focused mainly on private firms.", AI),
    ]),
    (None, [
        ("plain", "Structured interviews standardize the questions that every candidate answers. Managers in our"
                  " sample "),
        ("del", "described", AI),
        ("ins", "called", AI),
        ("plain", " the format "),
        ("del", "as ", AI),
        ("plain", "slow but fair. One clerk said the process \"felt like a "),
        ("del", "real", AI),
        ("ins", "genuine", AI),
        ("plain", " conversation about the "),
        ("del", "job", AI),
        ("ins", "work", AI),
        ("plain", ".\" Agencies "),
        ("del", "that ", SCHOLAR),
        ("plain", "adopted the format "),
        ("del", "did so ", SCHOLAR),
        ("plain", "for "),
        ("del", "a variety of", SCHOLAR),
        ("ins", "many", SCHOLAR),
        ("plain", " different reasons"),
        ("del", ", and those reasons varied a great deal", SCHOLAR),
        ("plain", "."),
    ]),
    (None, [
        ("plain", "The results "),
        ("del", "suggest", AI),
        ("ins", "show", AI),
        ("plain", " that structured interviews "),
        ("del", "may ", AI),
        ("plain", "reduce early exits by 9 percentage points. "),
        ("plain", "This pattern held across agencies of different sizes."),
        ("plain", " Future research should test whether the effect persists beyond the first year."),
        ("ins", " The next section turns to the interview protocol itself.", AI),
    ]),
)

# Where the comment for each seeded record entry sits, (paragraph, segment) to
# (paragraph, segment). The move's delete entry r01 sits on the sentence at its
# old place and its insert entry r10 at its new place. r09 has no comment, as
# it is the AI change with no recorded reason, and r08 sits on a sentence that
# did not change.
SEEDED_PLACES = {
    "r01": ((1, 14), (1, 14)), "r02": ((1, 3), (1, 3)), "r03": ((1, 6), (1, 6)), "r04": ((1, 9), (1, 12)),
    "r05": ((2, 7), (2, 10)), "r06": ((3, 2), (3, 2)), "r07": ((3, 8), (3, 8)), "r08": ((3, 6), (3, 6)),
    "r10": ((1, 1), (1, 1)),
}

# The seeded record's entries in the order the adapter writes them, each AI
# change in document order and then r08, the comment that covers no change.
# The adapter's entry rNN is the fixture's entry at place NN here.
SEEDED_ORDER = ("r10", "r02", "r03", "r04", "r01", "r09", "r05", "r06", "r07", "r08")

# The own kind of each of the seeded document's nine AI changes, in document order.
SEEDED_OWN_KINDS = ("insert", "edit", "edit", "edit", "delete", "edit", "edit", "edit", "insert")

CLEAN_PARAGRAPHS = TITLE + (
    (None, [
        ("plain", "Local governments face persistent difficulty retaining new hires. "),
        ("moveTo", "Prior work has focused mainly on private firms. ", AI),
        ("del", "In this study we examine", AI),
        ("ins", "This study examines", AI),
        ("plain", " whether structured interviews are associated with lower first-year turnover in municipal"
                  " agencies. We draw on personnel records from 48 agencies in three states [@alvarez2019]."),
        ("moveFrom", " Prior work has focused mainly on private firms.", AI),
    ]),
    (None, [
        ("plain", "Structured interviews "),
        ("del", "standardize the questions that every candidate answers", AI),
        ("ins", "ask every candidate the same questions in the same order", AI),
        ("plain", ". Managers in our sample described the format as slow but fair. One clerk said the process"
                  " \"felt like a real conversation about the job.\""),
        ("del", " Agencies that adopted the format did so for a variety of different reasons, and those reasons"
                " varied a great deal.", AI),
    ]),
    (None, [
        ("plain", "The results suggest that structured interviews may reduce early exits by 9 percentage points."
                  " This pattern held across agencies of different sizes. Future research should test whether"
                  " the effect persists beyond the first year."),
        ("ins", " The next section turns to the interview protocol itself.", AI),
    ]),
)

# The clean record's move r01 is one [move] comment, on the sentence at its new place.
CLEAN_PLACES = {
    "r01": ((1, 1), (1, 1)), "r02": ((1, 3), (1, 3)), "r03": ((2, 2), (2, 2)), "r04": ((2, 4), (2, 4)),
    "r05": ((3, 1), (3, 1)),
}

LEDGER_NINE = (
    "# Builds\n\n"
    "| version | date | git | sha256 | purpose | baseline | reviewed | verification | runs |\n"
    "|---|---|---|---|---|---|---|---|---|\n"
    "| v001 | 2026-10-29 | - | {sha} | draft for review | - | no | verified | - |\n"
)
LEDGER_SEVEN = (
    "# Builds\n\n"
    "| version | date | git | sha256 | purpose | baseline | reviewed |\n"
    "|---|---|---|---|---|---|---|\n"
    "| v001 | 2026-10-29 | - | {sha} | draft for review | - | no |\n"
)


@pytest.fixture(autouse=True)
def homes(tmp_path, monkeypatch):
    user = tmp_path / "user"
    user.mkdir()
    monkeypatch.setenv("HOME", str(user))
    monkeypatch.setenv("CONNECTIONS_HOME", str(tmp_path / "connections_home"))
    monkeypatch.setenv("AUDIT_HOME", str(tmp_path / "audit_home"))
    return tmp_path


def fixture_rationales(fixture):
    return yaml.safe_load((fixture / "rationales.yaml").read_text(encoding="utf-8"))


def comments_for(fixture, places):
    """One comment by the AI author for each fixture entry places names, its kind tag first, in the fixture's order."""
    return [(AI, "[{}] {}".format(r["kind"], r["rationale"])) + places[r["id"]]
            for r in fixture_rationales(fixture) if r["id"] in places]


def numbered(entries):
    return [dict(e, id=f"r{n:02d}") for n, e in enumerate(entries, 1)]


def seeded_record():
    """The seeded record's ten entries, numbered as the adapter numbers them."""
    by_id = {r["id"]: r for r in fixture_rationales(SEEDED)}
    return numbered(by_id[old] for old in SEEDED_ORDER)


def renumbered_truth(path):
    """The seeded truth file, with each record entry id it names renumbered as the adapter numbers it."""
    new = {old: f"r{n:02d}" for n, old in enumerate(SEEDED_ORDER, 1)}
    truth = yaml.safe_load((SEEDED / "truth.yaml").read_text(encoding="utf-8"))
    for fault in truth["faults"]:
        fault["item"] = new.get(fault["item"], fault["item"])
    path.write_text(yaml.safe_dump(truth, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def build_review(path, paragraphs, comments):
    return docx_builder.build(path, list(paragraphs), comments)


def baseline_build(folder, fixture, ledger=LEDGER_NINE):
    """builds/v001.docx holding the fixture's baseline as plain text, and a BUILDS.md row for it."""
    folder.mkdir(parents=True, exist_ok=True)
    blocks = (fixture / "baseline.md").read_text(encoding="utf-8").rstrip("\n").split("\n\n")
    paragraphs = []
    for block in blocks:
        if block.startswith("# "):
            paragraphs.append(("Heading 1", [("plain", block[2:])]))
        else:
            paragraphs.append((None, [("plain", block)]))
    docx = docx_builder.build(folder / "v001.docx", paragraphs)
    sha = hashlib.sha256(docx.read_bytes()).hexdigest()
    (folder / "BUILDS.md").write_text(ledger.format(sha=sha), encoding="utf-8")
    return folder


def adapt(out, docx, *extra):
    return main(["adapt", "word", "--out", str(out), "--docx", str(docx), "--ai-author", AI] + list(extra))


def adapt_seeded(tmp_path, name="out", paragraphs=SEEDED_PARAGRAPHS, comments=None, extra=None):
    review = build_review(tmp_path / (name + "_review.docx"), paragraphs,
                          comments_for(SEEDED, SEEDED_PLACES) if comments is None else comments)
    builds = tmp_path / "builds"
    if not (builds / "BUILDS.md").exists():
        baseline_build(builds, SEEDED)
    args = ["--builds-dir", str(builds), "--baseline-version", "v001"] if extra is None else extra
    out = tmp_path / name
    assert adapt(out, review, *args) == 0
    return out


def adapt_annotated(tmp_path, items, comments=()):
    annotations = tmp_path / "annotations.yaml"
    annotations.write_text(yaml.safe_dump(items, sort_keys=False, allow_unicode=True), encoding="utf-8")
    review = build_review(tmp_path / "annotated_review.docx", SEEDED_PARAGRAPHS, list(comments))
    out = tmp_path / "annotated"
    assert adapt(out, review, "--annotations", str(annotations)) == 0
    return out, annotations


def load(out, name):
    return yaml.safe_load((out / name).read_text(encoding="utf-8"))


def vg(*args):
    env = dict(os.environ, VG_OFFLINE="1")
    return subprocess.run(
        [sys.executable, str(VP / "vg.py")] + list(args),
        cwd=str(VP),
        capture_output=True,
        text=True,
        env=env,
    )


def run_prose(out, run, tmp_path):
    inputs = tmp_path / (run.name + "_inputs")
    inputs.mkdir()
    for name in FILLS:
        shutil.copyfile(str(out / name), str(inputs / name))
    done = vg("run", GRAPH, "--run", str(run), "--inputs", str(inputs))
    assert done.returncode == 0, done.stdout + done.stderr
    return run


def problems(run):
    findings = json.loads((run / "files" / "findings.json").read_text(encoding="utf-8"))
    return [f for f in findings if f["severity"] in ("blocking", "warning")]


def ai_changes(run):
    return {c["id"]: c for c in json.loads((run / "files" / "ai_changes.json").read_text(encoding="utf-8"))}


def test_the_word_adapter_is_registered_for_the_prose_stream():
    adapter = ADAPTERS["word"]
    assert adapter.stream == "prose"
    assert tuple(adapter.fills) == FILLS


def test_the_two_drafts_equal_the_fixtures_byte_for_byte(tmp_path):
    out = adapt_seeded(tmp_path)
    assert (out / "baseline.md").read_bytes() == (SEEDED / "baseline.md").read_bytes()
    assert (out / "revised.md").read_bytes() == (SEEDED / "revised.md").read_bytes()


def test_the_record_holds_the_seeded_records_ten_entries_in_document_order(tmp_path):
    out = adapt_seeded(tmp_path)
    record = load(out, "rationales.yaml")
    assert record == seeded_record()
    assert [(e["id"], e["kind"]) for e in record if e["anchor"] == PRIOR] == [("r01", "insert"), ("r05", "delete")]


def test_the_scholars_tracked_change_gets_no_entry_and_no_author_edits_file_is_written(tmp_path):
    out = adapt_seeded(tmp_path)
    assert sorted(p.name for p in out.iterdir()) == sorted(FILLS + ("adapter_record.json",))
    anchors = [e["anchor"] for e in load(out, "rationales.yaml")]
    assert "Agencies adopted the format for many different reasons." not in anchors


def test_versions_pins_the_baseline_build(tmp_path):
    out = adapt_seeded(tmp_path)
    versions = load(out, "versions.yaml")["versions"]
    fixture = yaml.safe_load((SEEDED / "versions.yaml").read_text(encoding="utf-8"))["versions"]
    assert versions == [{"version": "v001", "file": "v001.docx", "sha256": fixture[0]["sha256"]}]
    digest = "sha256:" + hashlib.sha256((out / "baseline.md").read_bytes()).hexdigest()
    assert versions[0]["sha256"] == digest


def test_the_prose_procedure_catches_every_planted_fault_from_the_adapters_files(tmp_path):
    out = adapt_seeded(tmp_path)
    run = run_prose(out, tmp_path / "run_seeded", tmp_path)
    truth_path = renumbered_truth(tmp_path / "truth.yaml")
    scored = vg("score", "--run", str(run), "--truth", str(truth_path))
    assert scored.returncode == 0, scored.stdout + scored.stderr
    score = json.loads((run / "score.json").read_text(encoding="utf-8"))
    assert score["faults"] == 7
    assert len(score["caught"]) == 7
    assert score["recall"] == 1.0
    assert score["extra_findings"] == []
    truth = yaml.safe_load(truth_path.read_text(encoding="utf-8"))
    assert [f["item"] for f in truth["faults"]] == ["c05", "c03", "c04", "c06", "c08", "r10", "c09"]
    flagged = {f["item"] for f in problems(run)}
    for clean_item in truth["not_flagged"]:
        assert clean_item["item"] not in flagged, clean_item
    ai = ai_changes(run)
    assert ai["c01"]["record_id"] == "r01 and r05"
    assert "c07" not in ai


def test_the_clean_fixture_built_the_same_way_gives_no_blocking_finding_or_warning(tmp_path):
    review = build_review(tmp_path / "clean.docx", CLEAN_PARAGRAPHS, comments_for(CLEAN, CLEAN_PLACES))
    builds = baseline_build(tmp_path / "builds", CLEAN)
    out = tmp_path / "out"
    assert adapt(out, review, "--builds-dir", str(builds), "--baseline-version", "v001") == 0
    assert (out / "baseline.md").read_bytes() == (CLEAN / "baseline.md").read_bytes()
    assert (out / "revised.md").read_bytes() == (CLEAN / "revised.md").read_bytes()
    clean = {r["id"]: r for r in fixture_rationales(CLEAN)}
    # The [move] comment covers the half at the new place, which takes its own kind and the
    # reason. The half at the old place, which no comment covers, is a delete entry with none.
    assert load(out, "rationales.yaml") == numbered([
        dict(clean["r01"], kind="insert"), clean["r02"], dict(clean["r01"], kind="delete", rationale=""),
        clean["r03"], clean["r04"], clean["r05"],
    ])
    run = run_prose(out, tmp_path / "run_clean", tmp_path)
    assert problems(run) == []
    assert ai_changes(run)["c01"]["rationale"] == clean["r01"]["rationale"]


def test_each_ai_change_with_no_comment_gets_an_entry_of_its_own_kind_and_no_reason(tmp_path):
    out = adapt_seeded(tmp_path, comments=[])
    assert load(out, "rationales.yaml") == [
        dict(e, kind=kind, rationale="") for e, kind in zip(seeded_record(), SEEDED_OWN_KINDS)
    ]


def test_a_move_tag_on_one_half_gives_each_half_its_own_kind(tmp_path):
    reason = "Moved the gap statement ahead of the study aim."
    out = adapt_seeded(tmp_path, comments=[(AI, "[move] " + reason, (1, 14), (1, 14))])
    record = load(out, "rationales.yaml")
    assert [(e["id"], e["kind"], e["rationale"]) for e in record if e["anchor"] == PRIOR] == [
        ("r01", "insert", ""), ("r05", "delete", reason),
    ]
    run = run_prose(out, tmp_path / "run_move", tmp_path)
    ai = ai_changes(run)
    assert (ai["c01"]["record_id"], ai["c01"]["rationale"]) == ("r01 and r05", reason)
    assert "c01" not in {f["item"] for f in problems(run)}


def test_a_comment_on_any_text_of_a_changed_sentence_covers_its_entry(tmp_path):
    comments = [(AI, "[edit] Chose the plainer verb.", (2, 1), (2, 1)),  # the deleted word only
                (AI, "[edit] Dropped the hedge.", (3, 0), (3, 0))]       # text the sentence keeps
    out = adapt_seeded(tmp_path, comments=comments)
    record = load(out, "rationales.yaml")
    assert len(record) == 9
    assert [(e["id"], e["rationale"]) for e in record if e["rationale"]] == [
        ("r06", "Chose the plainer verb."), ("r08", "Dropped the hedge."),
    ]


def test_a_tracked_change_across_two_sentences_gives_an_entry_for_each(tmp_path):
    paragraphs = TITLE + ((None, [("plain", "Most volunteers stayed."),
                                  ("ins", " Some left early. Training helped.", AI)]),)
    review = build_review(tmp_path / "review.docx", paragraphs,
                          [(AI, "[insert] Added the two findings.", (1, 1), (1, 1))])
    out = tmp_path / "out"
    assert adapt(out, review) == 0
    assert load(out, "rationales.yaml") == [
        {"id": "r01", "anchor": "Some left early.", "kind": "insert", "rationale": "Added the two findings."},
        {"id": "r02", "anchor": "Training helped.", "kind": "insert", "rationale": "Added the two findings."},
    ]


def test_an_ai_deletion_anchors_its_sentence_and_another_authors_gets_no_entry(tmp_path):
    def paragraphs(author):
        return TITLE + ((None, [
            ("plain", "Most volunteers stayed."),
            ("del", " Some left early.", author),
            ("plain", " Training "),
            ("del", "clearly ", author),
            ("plain", "helped."),
        ]),)

    assert adapt(tmp_path / "ai", build_review(tmp_path / "ai.docx", paragraphs(AI), [])) == 0
    assert load(tmp_path / "ai", "rationales.yaml") == [
        {"id": "r01", "anchor": "Some left early.", "kind": "delete", "rationale": ""},
        {"id": "r02", "anchor": "Training helped.", "kind": "edit", "rationale": ""},
    ]
    assert adapt(tmp_path / "scholar", build_review(tmp_path / "scholar.docx", paragraphs(SCHOLAR), [])) == 0
    assert load(tmp_path / "scholar", "rationales.yaml") == []


def test_an_annotations_file_gives_the_same_rationales_as_the_comments(tmp_path):
    with_comments = adapt_seeded(tmp_path, name="commented")
    out, annotations = adapt_annotated(tmp_path, [
        {"anchor": r["anchor"], "text": r["rationale"], "tag": r["kind"]}
        for r in fixture_rationales(SEEDED) if r["id"] in SEEDED_PLACES
    ])
    assert (out / "rationales.yaml").read_bytes() == (with_comments / "rationales.yaml").read_bytes()
    record = json.loads((out / "adapter_record.json").read_text(encoding="utf-8"))
    assert str(annotations) in record["read"]


def test_an_annotations_file_overrides_the_documents_comments(tmp_path):
    out, _ = adapt_annotated(tmp_path, [{"anchor": PATTERN, "text": "Kept as it was."}],
                             comments=comments_for(SEEDED, SEEDED_PLACES))
    assert load(out, "rationales.yaml") == [
        dict(e, kind=kind, rationale="") for e, kind in zip(seeded_record(), SEEDED_OWN_KINDS)
    ] + [{"id": "r10", "anchor": PATTERN, "kind": "", "rationale": "Kept as it was."}]


def test_an_annotation_names_a_sentence_by_a_part_of_four_words_or_more(tmp_path):
    out, _ = adapt_annotated(tmp_path, [
        {"anchor": "whether structured interviews are associated", "text": "Made the opening direct.", "tag": "edit"},
        {"anchor": "called the format", "text": "Three words name no sentence."},
    ])
    record = load(out, "rationales.yaml")
    assert record[1] == {"id": "r02", "anchor": OPENING, "kind": "edit", "rationale": "Made the opening direct."}
    assert record[-1] == {"id": "r10", "anchor": "called the format", "kind": "",
                          "rationale": "Three words name no sentence."}


def test_a_build_that_no_longer_matches_its_ledger_row_gives_no_versions(tmp_path, capsys):
    builds = baseline_build(tmp_path / "builds", SEEDED)
    docx_builder.build(builds / "v001.docx", [(None, [("plain", "Changed after the build.")])])
    capsys.readouterr()
    out = adapt_seeded(tmp_path)
    assert load(out, "versions.yaml") == {"versions": []}
    printed = capsys.readouterr().out
    assert "v001.docx" in printed and "sha256" in printed


def test_without_the_build_options_versions_is_empty_and_says_why(tmp_path, capsys):
    out = adapt_seeded(tmp_path, extra=[])
    assert load(out, "versions.yaml") == {"versions": []}
    assert "--builds-dir" in capsys.readouterr().out


def test_a_version_the_ledger_lacks_gives_no_versions(tmp_path, capsys):
    out = adapt_seeded(tmp_path, extra=["--builds-dir", str(baseline_build(tmp_path / "builds", SEEDED)),
                                        "--baseline-version", "v002"])
    assert load(out, "versions.yaml") == {"versions": []}
    assert "v002" in capsys.readouterr().out


def test_a_seven_column_ledger_is_read_by_its_header_names(tmp_path):
    baseline_build(tmp_path / "builds", SEEDED, ledger=LEDGER_SEVEN)
    out = adapt_seeded(tmp_path)
    assert [v["version"] for v in load(out, "versions.yaml")["versions"]] == ["v001"]


def test_an_edit_made_without_tracked_changes_breaks_the_pin(tmp_path):
    paragraphs = list(SEEDED_PARAGRAPHS)
    last = list(paragraphs[3][1])
    last[7] = ("plain", " Future research should test whether the effect lasts beyond the first year.")
    paragraphs[3] = (None, last)
    out = adapt_seeded(tmp_path, paragraphs=paragraphs)
    versions = load(out, "versions.yaml")["versions"]
    digest = "sha256:" + hashlib.sha256((out / "baseline.md").read_bytes()).hexdigest()
    assert [v["version"] for v in versions] == ["v001"]
    assert versions[0]["sha256"] != digest


def test_a_comment_without_a_tag_gives_the_changes_own_kind(tmp_path):
    # On a sentence that did not change there is no own kind, so the kind is empty.
    comments = [(AI, "Smoothed the opening.", (1, 3), (1, 3)), (AI, "Kept as it was.", (3, 6), (3, 6))]
    out = adapt_seeded(tmp_path, comments=comments)
    record = load(out, "rationales.yaml")
    assert record[1] == {"id": "r02", "anchor": OPENING, "kind": "edit", "rationale": "Smoothed the opening."}
    assert record[-1] == {"id": "r10", "anchor": PATTERN, "kind": "", "rationale": "Kept as it was."}


def test_other_authors_comments_are_left_out(tmp_path):
    comments = [(SCHOLAR, "[edit] I made this one.", (2, 17), (2, 17)),
                (AI, "[edit] Changed the count.", (1, 6), (1, 6))]
    out = adapt_seeded(tmp_path, comments=comments)
    record = load(out, "rationales.yaml")
    assert len(record) == 9
    assert [(r["id"], r["rationale"]) for r in record if r["rationale"]] == [("r03", "Changed the count.")]


def test_an_ai_comment_on_a_sentence_only_another_author_changed_is_left_out(tmp_path, capsys):
    capsys.readouterr()
    out = adapt_seeded(tmp_path, comments=[(AI, "[edit] Shortened the sentence.", (2, 17), (2, 17))])
    record = load(out, "rationales.yaml")
    assert len(record) == 9 and not any(r["rationale"] for r in record)
    assert "by AI Reviewer is left out of rationales.yaml" in capsys.readouterr().out


def test_no_tracked_change_and_no_comment_give_an_empty_record(tmp_path):
    review = build_review(tmp_path / "plain.docx", TITLE + ((None, [("plain", "Nothing changed here.")]),), [])
    out = tmp_path / "out"
    assert adapt(out, review) == 0
    assert (out / "rationales.yaml").read_text(encoding="utf-8") == "[]\n"
    assert not (out / "author_edits.yaml").exists()


def test_the_same_document_gives_the_same_bytes_in_two_folders(tmp_path):
    first = adapt_seeded(tmp_path, name="first")
    second = adapt_seeded(tmp_path, name="second")
    for name in FILLS:
        assert (first / name).read_bytes() == (second / name).read_bytes()


def test_the_build_folder_without_a_version_is_refused(tmp_path, capsys):
    review = build_review(tmp_path / "review.docx", SEEDED_PARAGRAPHS, [])
    out = tmp_path / "out"
    assert adapt(out, review, "--builds-dir", str(tmp_path)) == 1
    assert "--baseline-version" in capsys.readouterr().err
    assert not out.exists()


def test_a_file_that_is_not_a_word_document_is_refused(tmp_path, capsys):
    bad = tmp_path / "notes.docx"
    bad.write_text("plain text", encoding="utf-8")
    out = tmp_path / "out"
    assert adapt(out, bad) == 1
    assert "notes.docx" in capsys.readouterr().err
    assert not out.exists()


SAMPLE = (
    "# A heading. Not a sentence\n\n"
    "A first one. A second? Yes! He said \"stop.\" Then (aside) ok. She wrote “done.”"
    " “Next” came. It was 'over.' [Bracketed] next. Not e.g. here, and 3.5 stays.\n\n"
    "A second paragraph\nruns over a line break. Done."
)


def test_the_sentence_rule_splits_as_the_prose_procedure_does(tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "baseline.md").write_text(SAMPLE, encoding="utf-8")
    (inputs / "revised.md").write_text("Zebra quilting xylophone.\n", encoding="utf-8")
    (inputs / "rationales.yaml").write_text("[]\n", encoding="utf-8")
    (inputs / "versions.yaml").write_text("versions: []\n", encoding="utf-8")
    run = tmp_path / "run"
    done = vg("run", GRAPH, "--run", str(run), "--inputs", str(inputs))
    assert done.returncode == 0, done.stdout + done.stderr
    changes = json.loads((run / "files" / "changes.json").read_text(encoding="utf-8"))
    deleted = [c["before"] for c in sorted(changes, key=lambda c: c["b_index"] if c["b_index"] is not None else -1)
               if c["kind"] == "delete"]
    assert sentences(SAMPLE) == deleted
    assert "He said \"stop.\"" in deleted and "It was 'over.'" in deleted
