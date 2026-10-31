"""Synthetic fixture for the evidence contract. Fake values, real shape.

Results files in the shape the verification procedures write (`verification-results`,
schema_version 1) and the build's status tests use. The citations file carries three
fake reference rows with the item fields a references run writes, and the other three
streams carry one item each with the keys every stream's items share (`id`,
`needs_decision`, `kind`, `summary`, `findings`). A citation log in the audit layer's
written-out shape names two of the three citekeys. Tests write these into a temporary
folder.
"""
import hashlib
import json
from pathlib import Path

RUN_ID = "fake_citations_2"
OLDER_RUN_ID = "fake_citations_1"
AT = "2026-10-29T09:00:00-07:00"
SESSION = "00000000-1111-4222-8333-444444444444"

SOURCE_TEXT = """\
---
title: A fake manuscript
---

Widgets grew in every city [@alpha2017]. The rise was steady [@beta2014].
One city fell behind [@gamma2020], and {{num:widget.total}} widgets were counted.
"""

NUMBERS_TEXT = """\
numbers:
  widget.total: {value: "24", from: widget_results.json, field: total}
"""

# (id, citekey, category, reason, sentence)
CITATION_ROWS = [
    ("r01", "alpha2017", "verified", "", "Widgets grew in every city."),
    ("r02", "beta2014", "verified", "", "The rise was steady."),
    ("r03", "gamma2020", "problem", "The source reports a rise, not a fall.", "One city fell behind."),
]

CITATION_LOG = {
    "citations": {
        "beta2014": {"introduced_by": "ai", "draft": "", "session": SESSION},
        "gamma2020": {"introduced_by": "ai", "draft": "", "session": SESSION},
    }
}

CITATION_LOG_YAML = """\
# Synthetic citation log, two citekeys added in one fake session.
citations:
  beta2014: {introduced_by: ai, draft: "", session: "%s"}
  gamma2020: {introduced_by: ai, draft: "", session: "%s"}
""" % (SESSION, SESSION)


def checksum_text(text):
    """The checksum form a verification run records for a file holding `text`."""
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def decision(item, verdict="approved", run_id=RUN_ID, by="scholar", at=AT):
    return {"item": item, "decision": verdict, "by": by, "at": at, "run_id": run_id}


def citation_item(row_id, citekey, category, reason, sentence, needs_decision=True):
    return {
        "id": row_id,
        "citekey": citekey,
        "category": category,
        "origin": "ai",
        "moved": False,
        "sentence": sentence,
        "reference": citekey,
        "reference_check": "matches",
        "passage": "A fake passage.",
        "location": "p. 1",
        "verdict": "supported" if category == "verified" else "not supported",
        "reason": reason,
        "second_verdict": "",
        "disputed": False,
        "access": "full text",
        "issues": [],
        "fix": "",
        "needs_decision": needs_decision,
    }


def citations_results(source_text=SOURCE_TEXT, decisions=None, extra_items=(), run_id=RUN_ID):
    """The citations results file, every row approved on its run unless decisions are given."""
    items = [citation_item(*row) for row in CITATION_ROWS]
    items.extend(extra_items)
    if decisions is None:
        decisions = [decision(row[0], run_id=run_id) for row in CITATION_ROWS]
    return {
        "schema": "verification-results",
        "schema_version": 1,
        "stream": "citations",
        "run_id": run_id,
        "procedure_version": 0.1,
        "inputs": {"draft.md": checksum_text(source_text), "refs.yaml": checksum_text("fake refs\n")},
        "items": items,
        "decisions": decisions,
    }


def stream_results(stream, covered_text, decisions=None, summary="A fake finding."):
    """A results file for prose, data, or build, with one item, approved on its run."""
    run_id = "fake_{0}_1".format(stream)
    if decisions is None:
        decisions = [decision("i1", run_id=run_id)]
    return {
        "schema": "verification-results",
        "schema_version": 1,
        "stream": stream,
        "run_id": run_id,
        "procedure_version": 0.1,
        "inputs": {"covered": checksum_text(covered_text)},
        "items": [
            {"id": "i1", "needs_decision": True, "kind": "change", "summary": summary, "findings": []}
        ],
        "decisions": decisions,
    }


def write_results(folder, stream, data):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / (stream + ".json")).write_text(json.dumps(data, indent=2), encoding="utf-8")


def write_project(folder):
    """The fake source text and numbers file. Returns (source_path, numbers_path)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    source, numbers = folder / "manuscript.md", folder / "numbers.yml"
    source.write_text(SOURCE_TEXT, encoding="utf-8")
    numbers.write_text(NUMBERS_TEXT, encoding="utf-8")
    return source, numbers


def write_all_four(folder):
    """Every stream verified against the fake source text and numbers file."""
    write_results(folder, "citations", citations_results())
    write_results(folder, "prose", stream_results("prose", SOURCE_TEXT))
    write_results(folder, "data", stream_results("data", NUMBERS_TEXT))
    write_results(folder, "build", stream_results("build", SOURCE_TEXT))


HELD_BY = "another scholar"
HELD_AT = "2026-10-29T10:30:00-07:00"


def evidence_results():
    """A citations results file with one item of each kind the evidence file reports. r01
    is approved on the file's run, r02 held, r03 undecided, r04 the author's warrant
    (needs no decision), and r05 approved only on an older run, which does not count."""
    warrant = citation_item("r04", "author2019", "author", "", "As argued before.", needs_decision=False)
    older = citation_item("r05", "epsilon2018", "verified", "", "Widgets are old.")
    decisions = [
        decision("r01"),
        decision("r02", "held", by=HELD_BY, at=HELD_AT),
        decision("r05", run_id=OLDER_RUN_ID),
    ]
    return citations_results(decisions=decisions, extra_items=[warrant, older])
