"""Tests for the knowledge base's entry checker (Track G plan, Step G2).

Appendix A2.4 "Creating entries" says an entry's heading fixes its identifier,
title, source, source version, date, and group, and that its body gives a short
answer first, then the facts, then related entries. The checker holds those
rules and the moved contract's frozen shape. Every corpus here is the synthetic
one conftest.py writes, with one file changed per test. Run from the
repository root with python3 -m pytest audit_layer/kb/tests.
"""
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from audit_layer.kb import CORPUS  # noqa: E402
from audit_layer.kb.check import check_corpus  # noqa: E402
from audit_layer.kb.cli import main  # noqa: E402
from audit_layer.kb.entries import (  # noqa: E402
    KEYS,
    entry_files,
    first_sentence,
    load,
    parse_entry,
)

from conftest import ALPHA, BETA, GAMMA, LLMS, LONG_DASH  # noqa: E402

KB = ROOT / "audit_layer" / "kb"


def one_problem(corpus, *words):
    problems = check_corpus(corpus)
    assert len(problems) == 1, problems
    for word in words:
        assert word in problems[0], problems[0]
    return problems[0]


# The entry reader.


def test_keys_are_the_six():
    assert list(KEYS) == ["id", "title", "source", "source_commit", "updated", "group"]


def test_entry_files_are_sorted_and_one_folder_deep(make_corpus):
    corpus = make_corpus({"stray.md": "not an entry\n"})
    rels = [str(p.relative_to(corpus)) for p in entry_files(corpus)]
    assert rels == ["formats/formats-alpha.md", "formats/formats-beta.md", "loop/loop-gamma.md"]


@pytest.mark.parametrize(
    "text,sentence",
    [
        ("An entry. Then more.", "An entry."),
        ("Does it run?  It does.", "Does it run?"),
        ("It\nruns   once! Again.", "It runs once!"),
        ("Version 1.2 is out. More.", "Version 1.2 is out."),
        ("No ending at all", "No ending at all"),
        ("Ends at the end.", "Ends at the end."),
    ],
)
def test_first_sentence(text, sentence):
    assert first_sentence(text) == sentence


def test_parse_entry_reads_every_part(make_corpus):
    corpus = make_corpus()
    entry = parse_entry(corpus / "formats" / "formats-alpha.md", corpus)
    assert entry["path"] == corpus / "formats" / "formats-alpha.md"
    assert entry["rel"] == "formats/formats-alpha.md"
    assert entry["front"] == {
        "id": "formats-alpha",
        "title": "The alpha format",
        "source": "docs/alpha.md",
        "source_commit": "sha256:0123456789ab",
        "updated": "2026-10-01",
        "group": "FORMATS",
    }
    assert entry["body"].startswith("# The alpha format\n\nAn alpha record")
    assert entry["body"].endswith("loop that writes alpha records.")
    assert entry["point"] == "An alpha record holds one row per sample. Each row names its sample."
    assert entry["description"] == "An alpha record holds one row per sample."
    assert entry["problems"] == []


def test_parse_entry_strips_quotes_and_splits_at_the_first_colon(make_corpus):
    text = ALPHA.replace("title: The alpha format", "title: 'The alpha format: a guide'")
    corpus = make_corpus({"formats/formats-alpha.md": text})
    entry = parse_entry(corpus / "formats" / "formats-alpha.md", corpus)
    assert entry["front"]["title"] == "The alpha format: a guide"


def test_parse_entry_joins_the_point_lines(make_corpus):
    text = GAMMA.replace("It runs once per sample, and", "It runs once\nper sample, and")
    corpus = make_corpus({"loop/loop-gamma.md": text})
    entry = parse_entry(corpus / "loop" / "loop-gamma.md", corpus)
    assert entry["point"] == (
        "Does the gamma loop run twice? It runs once per sample, and it writes one alpha record."
    )
    assert entry["description"] == "Does the gamma loop run twice?"


def test_parse_entry_reports_a_missing_or_unclosed_frontmatter(make_corpus):
    missing = ALPHA.split("---\n", 2)[2]
    unclosed = ALPHA.replace("group: FORMATS\n---\n", "group: FORMATS\n", 1)
    corpus = make_corpus({"formats/formats-alpha.md": missing, "formats/formats-beta.md": unclosed})
    assert parse_entry(corpus / "formats" / "formats-alpha.md", corpus)["problems"]
    assert parse_entry(corpus / "formats" / "formats-beta.md", corpus)["problems"]


def test_load_parses_every_entry(make_corpus):
    entries = load(make_corpus())
    assert [e["front"]["id"] for e in entries] == ["formats-alpha", "formats-beta", "loop-gamma"]


# The checker, one rule at a time.


def test_the_valid_corpus_passes(make_corpus):
    assert check_corpus(make_corpus()) == []


def test_rule_1_a_corpus_with_no_entry(make_corpus):
    corpus = make_corpus(
        {"formats/formats-alpha.md": None, "formats/formats-beta.md": None, "loop/loop-gamma.md": None}
    )
    one_problem(corpus, "no entry file")


def test_rule_2_no_frontmatter_block(make_corpus):
    corpus = make_corpus({"formats/formats-beta.md": BETA.split("---\n", 2)[2]})
    assert one_problem(corpus, "frontmatter block").startswith("formats/formats-beta.md")


def test_rule_2_an_unclosed_frontmatter_block(make_corpus):
    text = BETA.replace("group: FORMATS\n---\n", "group: FORMATS\n", 1)
    corpus = make_corpus({"formats/formats-beta.md": text})
    assert one_problem(corpus, "frontmatter block").startswith("formats/formats-beta.md")


def test_rule_3_keys_not_exactly_the_six(make_corpus):
    text = BETA.replace("updated: 2026-10-02\n", "author: someone\n")
    corpus = make_corpus({"formats/formats-beta.md": text})
    problem = one_problem(corpus, "frontmatter keys", "updated", "author")
    assert problem.startswith("formats/formats-beta.md")


@pytest.mark.parametrize(
    "overrides",
    [
        # The id differs from the file name.
        {"formats/formats-beta.md": BETA.replace("id: formats-beta", "id: formats-delta")},
        # The id lacks the group prefix, in a file named after it.
        {
            "formats/formats-beta.md": None,
            "formats/beta.md": BETA.replace("id: formats-beta", "id: beta"),
            "formats/formats-alpha.md": ALPHA.replace("- formats-beta ", "- beta "),
            "llms.txt": LLMS.replace("formats/formats-beta.md", "formats/beta.md"),
        },
        # The entry sits in a folder other than its group's.
        {
            "formats/formats-beta.md": None,
            "loop/formats-beta.md": BETA,
            "llms.txt": LLMS.replace("formats/formats-beta.md", "loop/formats-beta.md"),
        },
        # The group is not capital letters only.
        {
            "loop/loop-gamma.md": GAMMA.replace("group: LOOP", "group: Loop"),
            "llms.txt": LLMS.replace("## LOOP", "## Loop"),
        },
    ],
)
def test_rule_4_id_and_group_fit_the_file(make_corpus, overrides):
    one_problem(make_corpus(overrides), "id or group")


def test_rule_5_first_body_line_is_the_title(make_corpus):
    text = BETA.replace("# The beta format", "# Another title")
    corpus = make_corpus({"formats/formats-beta.md": text})
    one_problem(corpus, "first body line")


def test_rule_6_a_point_follows_the_title(make_corpus):
    text = BETA.replace(
        "A beta record names the alpha rows it summarizes!\n\n"
        "The beta record is written once, after the alpha rows are complete.\n",
        "## Gaps\n\n- The beta record has no point.\n",
    )
    corpus = make_corpus({"formats/formats-beta.md": text})
    one_problem(corpus, "point paragraph")


@pytest.mark.parametrize(
    "text",
    [
        ALPHA.replace("## Gaps", "## Notes"),
        ALPHA.replace(
            "## Gaps\n\n- Nothing is known about very large alpha records.\n\n", ""
        ).rstrip("\n")
        + "\n\n## Gaps\n\n- Nothing is known about very large alpha records.\n",
    ],
)
def test_rule_7_only_gaps_then_consult_also(make_corpus, text):
    one_problem(make_corpus({"formats/formats-alpha.md": text}), "heading")


def test_rule_7_a_third_level_heading_is_allowed(make_corpus):
    text = BETA + "\n### A detail\n\nMore about beta.\n"
    assert check_corpus(make_corpus({"formats/formats-beta.md": text})) == []


@pytest.mark.parametrize("value", ["2026-10", "10/02/2026", "2026-10-2"])
def test_rule_8_updated_is_a_date(make_corpus, value):
    text = BETA.replace("updated: 2026-10-02", "updated: " + value)
    one_problem(make_corpus({"formats/formats-beta.md": text}), "updated")


@pytest.mark.parametrize(
    "value", ["sha256:0123456789", "sha256:0123456789AB", "abc123", "abc1234567890", "deadbeefZ"]
)
def test_rule_9_source_commit_shape(make_corpus, value):
    text = BETA.replace("source_commit: abc1234", "source_commit: " + value)
    one_problem(make_corpus({"formats/formats-beta.md": text}), "source_commit")


@pytest.mark.parametrize(
    "line",
    [
        "The file sat in /Users/someone/project.",
        "```\ncat /Users/someone/project/notes.md\n```",
        "```\nls /private/tmp/run\n```",
        "The run wrote /private/tmp/run/out.json.",
        "The run wrote /tmp/run/out.json.",
        "The project lived in /home/someone/project.",
        "The project lived in `/home/someone/project`.",
    ],
)
def test_rule_10_no_authoring_machine_paths(make_corpus, line):
    text = BETA + "\n" + line + "\n"
    one_problem(make_corpus({"formats/formats-beta.md": text}), "machine path")


@pytest.mark.parametrize(
    "line",
    [
        "```\npython3 gamma.py --out /tmp/run/out.json\n```",
        "```\ncd /home/someone/project\n```",
        "See https://example.org/home/page for more.",
    ],
)
def test_rule_10_code_fences_and_web_addresses_pass(make_corpus, line):
    text = BETA + "\n" + line + "\n"
    assert check_corpus(make_corpus({"formats/formats-beta.md": text})) == []


@pytest.mark.parametrize(
    "line",
    ["See [the alpha entry](formats-alpha.md).", "See [a folder](./docs/).", "![a picture](figure.png)"],
)
def test_rule_11_links_are_web_addresses(make_corpus, line):
    text = BETA + "\n" + line + "\n"
    one_problem(make_corpus({"formats/formats-beta.md": text}), "link")


def test_rule_11_web_links_pass(make_corpus):
    text = BETA + "\nSee [the guide](http://example.org/guide).\n"
    assert check_corpus(make_corpus({"formats/formats-beta.md": text})) == []


@pytest.mark.parametrize(
    "old,new",
    [
        ("- formats-beta " + LONG_DASH, "- formats-zeta " + LONG_DASH),
        ("- loop-gamma - ", "- loop-omega - "),
    ],
)
def test_rule_12_consult_also_names_known_ids(make_corpus, old, new):
    text = ALPHA.replace(old, new)
    problem = one_problem(make_corpus({"formats/formats-alpha.md": text}), "Consult also")
    assert new[2:12] in problem


def test_rule_13_llms_missing(make_corpus):
    assert one_problem(make_corpus({"llms.txt": None}), "missing").startswith("llms.txt")


@pytest.mark.parametrize(
    "text,word",
    [
        (LLMS.replace("# Synthetic knowledge base", "Synthetic knowledge base"), "# "),
        (LLMS.replace("> Entries made up", "Entries made up"), "> "),
        (LLMS.replace("- [The beta format](formats/formats-beta.md): A beta record names"
                      " the alpha rows it summarizes!\n", ""), "leaves out"),
        (LLMS + "- [The delta format](formats/formats-delta.md): A delta.\n", "does not exist"),
        (LLMS + "- [The gamma loop](loop/loop-gamma.md): Does the gamma loop run twice?\n", "twice"),
        (LLMS + "\n## EXTRA\n", "groups"),
    ],
)
def test_rule_13_llms_matches_the_corpus(make_corpus, text, word):
    problem = one_problem(make_corpus({"llms.txt": text}), word)
    assert problem.startswith("llms.txt")


# The command.


def run_check(*args):
    return subprocess.run(
        [sys.executable, "-m", "audit_layer.kb", "check"] + list(args),
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )


def test_command_passes_a_valid_corpus(make_corpus):
    result = run_check("--corpus", str(make_corpus()))
    assert result.returncode == 0, result.stderr
    assert result.stdout == "OK: 3 entries\n"


def test_command_fails_a_broken_corpus(make_corpus):
    corpus = make_corpus({"formats/formats-beta.md": BETA.replace("updated: 2026-10-02", "updated: soon")})
    result = run_check("--corpus", str(corpus))
    assert result.returncode == 1
    lines = result.stdout.splitlines()
    assert lines[0] == "FAIL (1)"
    assert lines[1] == check_corpus(corpus)[0]
    assert len(lines) == 2


def test_command_reads_the_package_corpus_by_default(capsys):
    assert main(["check"]) == 0
    assert capsys.readouterr().out == "OK: {} entries\n".format(len(entry_files(CORPUS)))


# The layer's edge.


def test_no_import_of_another_layer():
    pattern = re.compile(r"^\s*(import|from)\s+(ospipe|verification_procedures|vg)\b")
    for path in sorted(KB.rglob("*.py")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            assert not pattern.match(line), "{}:{} {}".format(path, number, line)
