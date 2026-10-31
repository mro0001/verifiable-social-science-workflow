"""What the references procedure's extractor reads as a citation (Track L, Steps L3 and L5).

Step L3. Pandoc prints an @ that a backslash escapes as text, as in \\@nakamura2020
and [\\@nakamura2020], and prints anything inside inline code or a fenced code
block as written. The extractor skips those as pandoc does, so a document that
shows the citation syntax as an example reports no cited work for it. The cases
follow what pandoc 3.9 reads (pandoc -f markdown -t native): an unclosed fence
and an unmatched backtick are text, and a fence may be indented by up to three
spaces.

Step L5. A document that cites by author and year in parentheses, with no keyed
citation, gets one blocking finding that says the citations must be written as
keys first, with a count of the author-year citations seen, and the finding is
an item of the run's results file.

The extractor runs as the runtime runs it, from a folder that holds the step's
code and _lib.py, on a files folder in tmp_path. Whole runs use the clean
fixture's inputs with the draft replaced, offline and with recorded answers, so
nothing here calls a model or the network.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
IMPL = ROOT / "implementations"
FIX = ROOT / "fixtures" / "citations" / "clean"
VG = [sys.executable, str(ROOT / "vg.py")]
GRAPH = "graphs/citations.yaml"


def extract(tmp_path, text):
    """Run the extractor on a draft.md holding text, and return its rows and findings."""
    code = tmp_path / "code"
    files = tmp_path / "files"
    code.mkdir()
    files.mkdir()
    shutil.copy2(str(IMPL / "citations" / "extract_citations.py"), str(code))
    shutil.copy2(str(IMPL / "_lib.py"), str(code))
    (files / "draft.md").write_text(text, encoding="utf-8")
    done = subprocess.run([sys.executable, str(code / "extract_citations.py"), str(files)],
                          capture_output=True, text=True,
                          env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    assert done.returncode == 0, done.stdout + done.stderr
    rows = json.loads((files / "rows.json").read_text(encoding="utf-8"))
    path = files / "findings_extract_citations.json"
    findings = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    return rows, findings


def keys(rows):
    return [r["citekey"] for r in rows]


# ---------------------------------------------------------------- L3, escapes and code

@pytest.mark.parametrize("text", [
    "The appendix writes \\@nakamura2020 so it prints as text.\n",
    "The appendix writes [\\@nakamura2020] so it prints as text.\n",
    "The appendix writes [\\@nakamura2020, p. 4; \\@okafor2019] as text.\n",
    "The syntax is `@nakamura2020` in the source.\n",
    "The syntax is `[@nakamura2020]` in the source.\n",
    "The syntax is ``a ` then @nakamura2020`` in the source.\n",
    "The syntax is `@nakamura2020\nacross a line` in the source.\n",
    "Before the block.\n\n```\n[@nakamura2020]\n\n@okafor2019\n```\n\nAfter the block.\n",
    "Before the block.\n\n~~~ {.markdown}\nAs @nakamura2020 finds.\n~~~\n",
    "Before the block.\n```\n@nakamura2020\n```\n",
    "Before the block.\n\n   ````\n@nakamura2020\n```\n@okafor2019\n   ````\n",
    "Before the block.\n\n~~~\n@nakamura2020\n~~~~~\n",
], ids=["escaped", "escaped in brackets", "escaped in brackets with a locator", "inline code",
        "inline code in brackets", "double backticks around a backtick", "inline code across a line",
        "fenced block with a blank line", "tilde fence with a class", "fence with no blank line before",
        "indented fence holding a shorter fence", "longer closing fence"])
def test_what_pandoc_prints_as_text_gives_no_citation(tmp_path, text):
    rows, _ = extract(tmp_path, text)
    assert rows == []


def test_a_real_citation_beside_an_escaped_one_and_code_is_read_and_the_sentence_kept(tmp_path):
    text = "Write `@key` or \\@key for text, as Lee found [@lee2019, p. 4; \\@not2020].\n"
    rows, _ = extract(tmp_path, text)
    assert keys(rows) == ["lee2019"]
    assert rows[0]["sentence"] == text.strip()
    assert rows[0]["locator"] == "p. 4"


@pytest.mark.parametrize("text, expected", [
    ("Before.\n\n```\n@inside2001\n\nStill open, as @open2002 says.\n", ["inside2001", "open2002"]),
    ("One `@tick2003 here, unmatched.\n", ["tick2003"]),
    ("One \\`@tick2004` here.\n", ["tick2004"]),
    ("An escaped backslash \\\\@real2005 cites.\n", ["real2005"]),
    ("A bare @bare2006 and a bracketed one [@brack2007; @brack2008, ch. 2].\n",
     ["bare2006", "brack2007", "brack2008"]),
], ids=["an unclosed fence is text", "an unmatched backtick is text", "an escaped backtick opens no code",
        "an escaped backslash leaves the @", "the forms read before"])
def test_what_pandoc_reads_as_a_citation_still_counts(tmp_path, text, expected):
    rows, _ = extract(tmp_path, text)
    assert keys(rows) == expected


def test_a_sentence_after_a_code_block_keeps_its_row_number(tmp_path):
    text = ("First [@a2001].\n\n```\n[@code2002]\n```\n\nSecond [@b2003].\n")
    rows, _ = extract(tmp_path, text)
    assert [(r["id"], r["citekey"]) for r in rows] == [("r01", "a2001"), ("r02", "b2003")]


# ---------------------------------------------------------------- L5, citations the check cannot read

AUTHOR_YEAR = ("# Results\n\nFit matters for retention (Smith, 2020). Others agree "
               "(Lee & Park, 2019; Chan et al., 2021, p. 4).\n")


def test_author_year_citations_and_no_keys_give_one_blocking_finding(tmp_path):
    rows, findings = extract(tmp_path, AUTHOR_YEAR)
    assert rows == []
    assert len(findings) == 1
    f = findings[0]
    assert (f["check"], f["severity"], f["item"]) == ("extract_citations", "blocking", "draft.md")
    assert "cannot read" in f["message"]
    assert "citation keys first" in f["message"]
    assert f["message"].startswith("3 author-year citations are written in a form")
    assert f["evidence"] == "Fit matters for retention (Smith, 2020)."


def test_one_author_year_citation_is_counted_as_one(tmp_path):
    _, findings = extract(tmp_path, "Fit matters (Smith 2020).\n")
    assert len(findings) == 1
    assert findings[0]["message"].startswith("1 author-year citation is written")


@pytest.mark.parametrize("text", [
    "Fit matters [@smith2020], as others found (Lee, 2019).\n",
    "Fit matters for retention.\n",
    "Fit matters (n = 40), as measured in March 2020 (March 2020).\n",
    "Write a citation as `(Smith, 2020)` in that style.\n",
], ids=["keys with author-year", "no citations at all", "parentheses that are not citations",
        "author-year inside code"])
def test_a_document_with_keys_or_no_author_year_citations_gives_no_finding(tmp_path, text):
    _, findings = extract(tmp_path, text)
    assert findings == []


def run_on(tmp_path, draft):
    """A whole references run, offline, on the clean fixture's inputs with draft.md
    replaced by draft."""
    inputs = tmp_path / "inputs"
    shutil.copytree(str(FIX), str(inputs))
    (inputs / "draft.md").write_text(draft, encoding="utf-8")
    rd = tmp_path / "run"
    env = dict(os.environ, VG_OFFLINE="1")
    done = subprocess.run(VG + ["run", GRAPH, "--run", str(rd), "--inputs", str(inputs),
                                "--judge", "recorded:" + str(FIX / "recorded_judge.json")],
                          cwd=str(ROOT), capture_output=True, text=True, env=env)
    assert done.returncode == 0, done.stdout + done.stderr
    return rd


def test_the_finding_is_an_item_of_the_results_file_and_the_report_blocks(tmp_path):
    rd = run_on(tmp_path, AUTHOR_YEAR)
    results = json.loads((rd / "results.json").read_text(encoding="utf-8"))
    assert [it["id"] for it in results["items"]] == ["draft.md"]
    item = results["items"][0]
    assert item["needs_decision"] is True
    assert item["origin"] == "unknown" and item["lookup"] == "not_checked"
    assert len(item["notes"]) == 1 and "cannot read" in item["notes"][0]
    findings = json.loads((rd / "files" / "findings.json").read_text(encoding="utf-8"))
    blocking = [f for f in findings if f["severity"] == "blocking"]
    assert [(f["check"], f["item"]) for f in blocking] == [("extract_citations", "draft.md")]
    report = (rd / "files" / "report.md").read_text(encoding="utf-8")
    assert "- Blocking: 1" in report
    assert "### draft.md: citations not read" in report
    done = subprocess.run(VG + ["verify", "--run", str(rd)], cwd=str(ROOT), capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr


def test_a_document_with_keys_gives_no_such_item(tmp_path):
    rd = run_on(tmp_path, "# Results\n\nFit matters [@abara2019], as others found (Lee, 2019).\n")
    results = json.loads((rd / "results.json").read_text(encoding="utf-8"))
    assert "draft.md" not in [it["id"] for it in results["items"]]
    findings = json.loads((rd / "files" / "findings.json").read_text(encoding="utf-8"))
    assert [f for f in findings if f["check"] == "extract_citations"] == []
