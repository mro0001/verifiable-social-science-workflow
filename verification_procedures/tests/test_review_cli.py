"""The `review` command line, run as `python3 -m review <command>`.

The expected lines below were recorded once, at the start of Step C18, by
running ospipe's root (`python3 -m ospipe returns`, `reconcile`, `annotate`,
and `check` for the lint lines) on each module's fixture. They are kept here
rather than read from ospipe, since layers never import each other's code.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

VP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(VP))

from review.annotate import fixture as a_fix  # noqa: E402
from review.lint import fixture as l_fix  # noqa: E402
from review.reconcile import fixture as c_fix  # noqa: E402
from review.returns import fixture as r_fix  # noqa: E402


def _review(*args):
    return subprocess.run(
        [sys.executable, "-m", "review"] + [str(a) for a in args],
        cwd=str(VP),
        capture_output=True,
        text=True,
    )


# --- recorded from ospipe's root on 2026-10-29 -------------------------------

RETURNS_REVIEWED_OUT = (
    "insertion (Synthetic Reviewer, 2026-07-23T00:00:00Z) [NUMBER — triage]: "
    "'48.6% in the final pass'\n"
    "deletion (Second Reviewer, 2026-07-23T00:00:00Z): 'entirely redundant and'\n"
    "comment (Margin Annotator): 'Please cite the synthetic archive here.'\n"
)
RETURNS_CLEAN_ERR = "no tracked changes or comments found\n"

_INS = (
    '  - insertion "A wholly new synthetic sentence was inserted by the reviser." '
    "(context 'sites across four seasons. ... The widget assay was')"
)
_SWAP = (
    '  - "calibrated" -> "aligned" '
    "(context 'The widget assay was ... against the archived reference')"
)
_REWRITE = (
    '  - "drifted upward during the second week" -> "held steady across the middle fortnight" '
    "(context 'morning. The gadget pipeline ... of the fabricated period.')"
)
_DEL = (
    '  - deletion "An obsolete disclaimer sentence sits here awaiting deletion." '
    "(context '12 South B 9 ... The closing summary restates')"
)

RECONCILE_OUT = {
    "all_accepted": [
        "accepted (4):", _INS, _SWAP, _REWRITE, _DEL,
        "rejected (0):", "modified (0):", "pending (0):",
        "author edits (0):", "comments (0):", "conflicts (0):",
    ],
    "one_rejected": [
        "accepted (3):", _INS, _SWAP, _DEL,
        "rejected (1):", _REWRITE,
        "modified (0):", "pending (0):",
        "author edits (0):", "comments (0):", "conflicts (0):",
    ],
    "one_modified": [
        "accepted (3):", _INS, _REWRITE, _DEL,
        "rejected (0):",
        "modified (1):",
        '  - "calibrated" -> "aligned" ; return reads "recalibrated" '
        "(context 'The widget assay was ... against the archived reference')",
        "pending (0):",
        "author edits (0):", "comments (0):", "conflicts (0):",
    ],
    "author_edit": [
        "accepted (4):", _INS, _SWAP, _REWRITE, _DEL,
        "rejected (0):", "modified (0):", "pending (0):",
        "author edits (1):",
        '  - added: "The author appended this untracked remark at the very end." '
        '(after "fabricated findings plainly.")',
        "comments (1):",
        "  - Margin Author: A synthetic margin remark about the fabricated cohort.",
        "conflicts (0):",
    ],
    "pending": [
        "accepted (3):", _SWAP, _REWRITE, _DEL,
        "rejected (0):", "modified (0):",
        "pending (1):",
        '  - insertion by Claude: "A wholly new synthetic sentence was inserted by the reviser."',
        "author edits (0):", "comments (0):", "conflicts (0):",
    ],
    "conflict": [
        "accepted (3):", _INS, _SWAP, _DEL,
        "rejected (0):", "modified (0):", "pending (0):",
        "author edits (0):", "comments (0):",
        "conflicts (1):",
        '  - cannot classify region "drifted upward during the second week" -> '
        "\"held steady across the middle fortnight\" (context 'morning. The gadget "
        "pipeline ... of the fabricated period.': context not found in return)",
    ],
}

ANNOTATE_OUT = "2 comments -> {out}\n"
ANNOTATE_ERR = "miss: anchor not found: 'this text appears nowhere in the document'\n"

LINT_ALLOW_OUT = "lint: line 5: bare numeral '12.5%': The gadget cohort improved by 12.5% overall.\n"
LINT_NOALLOW_OUT = LINT_ALLOW_OUT + (
    "lint: line 7: bare numeral '42.7': The literature benchmark of 42.7 is "
    "tracker-registered (Chung et al. 2025).\n"
)

DELTA_KEYS = {"kind", "text", "author", "date", "touches_number"}
COMMENT_KEYS = {"author", "text"}
CHANGE_KEYS = {"baseline_text", "revision_text", "context", "found_text"}


# --- fixtures -----------------------------------------------------------------


@pytest.fixture(scope="module")
def work(tmp_path_factory):
    return tmp_path_factory.mktemp("review_cli")


@pytest.fixture(scope="module")
def builds_dir(work):
    return c_fix.build_builds_dir(work / "builds")


@pytest.fixture(scope="module")
def lint_paths(work):
    manuscript = work / "sample.md"
    manuscript.write_text(l_fix.SAMPLE_MD, encoding="utf-8")
    allowlist = work / "allow.txt"
    allowlist.write_text("# tracker constants\n" + "\n".join(l_fix.ALLOWLIST) + "\n", encoding="utf-8")
    return manuscript, allowlist


# --- returns -----------------------------------------------------------------


def test_returns_prints_each_delta_and_comment(work):
    reviewed = r_fix.build_reviewed_docx(work / "reviewed.docx")
    proc = _review("returns", reviewed)
    assert proc.returncode == 0
    assert proc.stdout == RETURNS_REVIEWED_OUT
    assert proc.stderr == ""


def test_returns_on_a_clean_docx_says_so_on_standard_error(work):
    clean = r_fix.build_clean_docx(work / "clean.docx")
    proc = _review("returns", clean)
    assert proc.returncode == 0
    assert proc.stdout == ""
    assert proc.stderr == RETURNS_CLEAN_ERR


def test_returns_json_holds_deltas_and_comments(work):
    reviewed = r_fix.build_reviewed_docx(work / "reviewed_json.docx")
    proc = _review("returns", reviewed, "--json")
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert set(data) == {"deltas", "comments"}
    assert [set(d) for d in data["deltas"]] == [DELTA_KEYS, DELTA_KEYS]
    assert [(d["kind"], d["text"], d["touches_number"]) for d in data["deltas"]] == [
        ("insertion", r_fix.INSERTION_TEXT, True),
        ("deletion", r_fix.DELETION_TEXT, False),
    ]
    assert data["comments"] == [{"author": r_fix.COMMENT_AUTHOR, "text": r_fix.COMMENT_TEXT}]


# --- reconcile ----------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(RECONCILE_OUT))
def test_reconcile_prints_the_recorded_lines(work, builds_dir, name):
    ret = getattr(c_fix, "build_return_" + name)(work / (name + ".docx"))
    proc = _review("reconcile", ret, "--builds-dir", builds_dir, "--of", "v002")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "\n".join(RECONCILE_OUT[name]) + "\n"
    assert proc.stderr == ""


def _reconcile_json(work, builds_dir, name):
    ret = getattr(c_fix, "build_return_" + name)(work / (name + "_json.docx"))
    proc = _review("reconcile", ret, "--builds-dir", builds_dir, "--of", "v002", "--json")
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert set(data) == {
        "accepted", "rejected", "modified", "pending", "author_edits", "conflicts", "comments",
    }
    for bucket in ("accepted", "rejected", "modified"):
        for change in data[bucket]:
            assert set(change) == CHANGE_KEYS
    for delta in data["pending"]:
        assert set(delta) == DELTA_KEYS
    for comment in data["comments"]:
        assert set(comment) == COMMENT_KEYS
    assert all(isinstance(s, str) for s in data["author_edits"] + data["conflicts"])
    return data


def test_reconcile_json_modified_and_buckets(work, builds_dir):
    data = _reconcile_json(work, builds_dir, "one_modified")
    assert [len(data[b]) for b in ("accepted", "rejected", "modified")] == [3, 0, 1]
    assert data["modified"] == [{
        "baseline_text": c_fix.SWAP_BASE_WORD,
        "revision_text": c_fix.SWAP_REV_WORD,
        "context": "The widget assay was ... against the archived reference",
        "found_text": c_fix.MODIFIED_WORD,
    }]
    assert data["accepted"][0]["found_text"] is None


def test_reconcile_json_pending_delta(work, builds_dir):
    data = _reconcile_json(work, builds_dir, "pending")
    assert [(d["kind"], d["author"], d["text"]) for d in data["pending"]] == [
        ("insertion", c_fix.PENDING_AUTHOR, c_fix.S_INSERTED),
    ]


def test_reconcile_json_author_edits_comments_and_conflicts(work, builds_dir):
    data = _reconcile_json(work, builds_dir, "author_edit")
    assert data["author_edits"] == [
        'added: "The author appended this untracked remark at the very end." '
        '(after "fabricated findings plainly.")'
    ]
    assert data["comments"] == [{"author": c_fix.COMMENT_AUTHOR, "text": c_fix.COMMENT_TEXT}]
    conflict = _reconcile_json(work, builds_dir, "conflict")
    assert len(conflict["conflicts"]) == 1
    assert conflict["conflicts"][0].startswith("cannot classify region")


def test_reconcile_with_a_missing_ledger_exits_2(work):
    ret = c_fix.build_return_pending(work / "pending_noledger.docx")
    missing = work / "nobuilds"
    proc = _review("reconcile", ret, "--builds-dir", missing, "--of", "v002")
    assert proc.returncode == 2
    assert proc.stdout == ""
    assert proc.stderr == "reconcile failed: ledger absent: {0}\n".format(missing / "BUILDS.md")
    proc_json = _review("reconcile", ret, "--builds-dir", missing, "--of", "v002", "--json")
    assert proc_json.returncode == 2
    assert proc_json.stdout == ""
    assert proc_json.stderr.startswith("reconcile failed: ")


# --- annotate -----------------------------------------------------------------


def test_annotate_prints_the_count_and_each_miss(work):
    source = a_fix.build_source_docx(work / "source.docx")
    spec = work / "spec.yaml"
    spec.write_text(
        yaml.safe_dump([{"anchor": a.anchor, "text": a.text, "tag": a.tag} for a in a_fix.ANNOTATIONS]),
        encoding="utf-8",
    )
    out = work / "annotated.docx"
    proc = _review("annotate", "--docx", source, "--spec", spec, "--out", out, "--author", "Synthetic Checker")
    assert proc.returncode == 0
    assert proc.stdout == ANNOTATE_OUT.format(out=out)
    assert proc.stderr == ANNOTATE_ERR
    assert out.exists()
    from review.returns import extract

    assert {c.author for c in extract(out).comments} == {"Synthetic Checker"}


# --- lint ----------------------------------------------------------------------


def test_lint_prints_one_line_per_finding_and_exits_0(lint_paths):
    manuscript, allowlist = lint_paths
    proc = _review("lint", "--manuscript", manuscript)
    assert proc.returncode == 0
    assert proc.stdout == LINT_NOALLOW_OUT
    assert proc.stderr == ""
    allowed = _review("lint", "--manuscript", manuscript, "--allowlist", allowlist)
    assert allowed.returncode == 0
    assert allowed.stdout == LINT_ALLOW_OUT


def test_lint_json_is_a_list_of_findings(lint_paths):
    manuscript, allowlist = lint_paths
    proc = _review("lint", "--manuscript", manuscript, "--allowlist", allowlist, "--json")
    assert proc.returncode == 0
    assert json.loads(proc.stdout) == [{
        "line": 5,
        "token": "12.5%",
        "context": "The gadget cohort improved by 12.5% overall.",
    }]


def test_lint_on_clean_text_prints_nothing(work):
    clean = work / "clean.md"
    clean.write_text("No numbers here, only the year 2024.\n", encoding="utf-8")
    proc = _review("lint", "--manuscript", clean)
    assert (proc.returncode, proc.stdout) == (0, "")
    proc_json = _review("lint", "--manuscript", clean, "--json")
    assert (proc_json.returncode, json.loads(proc_json.stdout)) == (0, [])


# --- the Word compare script -------------------------------------------------


def test_compare_script_exists_and_names_its_four_arguments():
    script = VP / "review" / "word_compare.applescript"
    assert script.is_file()
    header = script.read_text(encoding="utf-8").splitlines()[0]
    assert header == "-- word_compare.applescript ORIGINAL REVISED OUTPUT LABEL"
