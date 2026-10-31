"""Tests for the knowledge base's index and export (Track G plan, Step G3).

Appendix A2.4 "Knowledge base" says the knowledge store stores the entries so
they can be searched, and "Serving entries" names an overview of the corpus
and search. The moved contract says the index llms.txt is rebuilt from the
corpus alone. index.py renders that index and exports every entry to one JSON
file, the exported index the server graph answers from. Every corpus here is
the synthetic one conftest.py writes, except the test against the real
corpus. Run from the repository root with python3 -m pytest audit_layer/kb/tests.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from audit_layer.kb import CORPUS  # noqa: E402
from audit_layer.kb.check import check_corpus  # noqa: E402
from audit_layer.kb.cli import main  # noqa: E402
from audit_layer.kb.entries import entry_files  # noqa: E402
from audit_layer.kb.index import (  # noqa: E402
    export_index,
    render_llms,
    write_export,
    write_llms,
)

from conftest import BETA, LLMS  # noqa: E402

KB = ROOT / "audit_layer" / "kb"

ALPHA_LINE = "- [The alpha format](formats/formats-alpha.md): An alpha record holds one row per sample.\n"
BETA_LINE = (
    "- [The beta format](formats/formats-beta.md): A beta record names the alpha rows it"
    " summarizes!\n"
)

AND = """---
id: formats-and
title: The and format
source: docs/and.md
source_commit: abc1234
updated: 2026-10-04
group: FORMATS
---

# The and format

An and record joins two alpha rows. It is written last.
"""

DELTA = """---
id: guides-delta
title: The delta guide
source: docs/delta.md
source_commit: abc1234
updated: 2026-10-05
group: GUIDES
---

# The delta guide

The delta guide says how to read a gamma loop's records.
"""

ROW_FIELDS = [
    "body",
    "description",
    "group",
    "id",
    "path",
    "point",
    "source",
    "source_commit",
    "title",
    "updated",
]


def run_kb(*args):
    return subprocess.run(
        [sys.executable, "-m", "audit_layer.kb"] + list(args),
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )


# The index.


def test_render_on_the_real_corpus_is_the_committed_index():
    committed = (CORPUS / "llms.txt").read_bytes()
    assert render_llms(CORPUS).encode("utf-8") == committed


def test_render_on_the_synthetic_corpus_is_its_index(make_corpus):
    assert render_llms(make_corpus()) == LLMS


def test_a_new_entry_adds_one_line_to_its_group_in_id_order(make_corpus):
    corpus = make_corpus({"formats/formats-and.md": AND})
    line = "- [The and format](formats/formats-and.md): An and record joins two alpha rows.\n"
    assert render_llms(corpus) == LLMS.replace(ALPHA_LINE, ALPHA_LINE + line)


def test_a_new_group_gets_its_section_in_sorted_order(make_corpus):
    corpus = make_corpus({"guides/guides-delta.md": DELTA})
    section = (
        "## GUIDES\n\n"
        "- [The delta guide](guides/guides-delta.md): The delta guide says how to read a gamma"
        " loop's records.\n\n"
    )
    assert render_llms(corpus) == LLMS.replace("## LOOP\n", section + "## LOOP\n")


def test_a_removed_entry_loses_its_line(make_corpus):
    corpus = make_corpus({"formats/formats-beta.md": None})
    assert render_llms(corpus) == LLMS.replace(BETA_LINE, "")


def test_the_header_lines_are_kept(make_corpus):
    text = LLMS.replace("# Synthetic knowledge base", "# Another name").replace(
        "> Entries made up for the knowledge base tests.", "> Another description."
    )
    corpus = make_corpus({"llms.txt": text})
    rendered = render_llms(corpus)
    assert rendered.startswith("# Another name\n\n> Another description.\n\n## FORMATS\n")
    assert rendered == text


def test_the_header_lines_default_without_an_index(make_corpus):
    corpus = make_corpus({"llms.txt": None})
    rendered = render_llms(corpus)
    assert rendered.startswith(
        "# Knowledge base\n\n> Entries for any AI session to apply.\n\n## FORMATS\n"
    )
    assert rendered.endswith("Does the gamma loop run twice?\n")
    assert not rendered.endswith("\n\n")


def test_write_llms_rewrites_a_stale_index_then_leaves_it(make_corpus):
    corpus = make_corpus({"formats/formats-and.md": AND})
    assert write_llms(corpus) is True
    assert (corpus / "llms.txt").read_text(encoding="utf-8") == render_llms(corpus)
    assert write_llms(corpus) is False
    assert check_corpus(corpus) == []


def test_write_llms_writes_a_missing_index(make_corpus):
    corpus = make_corpus({"llms.txt": None})
    assert write_llms(corpus) is True
    assert write_llms(corpus) is False
    assert check_corpus(corpus) == []


def test_the_checker_flags_a_hand_edited_description(make_corpus):
    corpus = make_corpus({"llms.txt": LLMS.replace("holds one row per sample.", "holds rows.")})
    problems = check_corpus(corpus)
    assert len(problems) == 1, problems
    assert problems[0].startswith("llms.txt")
    assert "python3 -m audit_layer.kb llms" in problems[0]


def test_the_checker_flags_an_index_out_of_order(make_corpus):
    corpus = make_corpus({"llms.txt": LLMS.replace(ALPHA_LINE + BETA_LINE, BETA_LINE + ALPHA_LINE)})
    problems = check_corpus(corpus)
    assert len(problems) == 1, problems
    assert "python3 -m audit_layer.kb llms" in problems[0]


def test_the_real_corpus_index_passes_the_checker():
    assert check_corpus(CORPUS) == []


# The export.


def test_export_has_the_schema_and_the_header(make_corpus):
    exported = export_index(make_corpus())
    assert sorted(exported) == ["description", "entries", "schema", "schema_version", "title"]
    assert exported["schema"] == "kb-index"
    assert exported["schema_version"] == 1
    assert exported["title"] == "Synthetic knowledge base"
    assert exported["description"] == "Entries made up for the knowledge base tests."


def test_export_has_one_row_per_entry_with_the_ten_fields(make_corpus):
    corpus = make_corpus({"formats/formats-and.md": AND})
    rows = export_index(corpus)["entries"]
    assert len(rows) == len(entry_files(corpus)) == 4
    assert [row["id"] for row in rows] == ["formats-alpha", "formats-and", "formats-beta", "loop-gamma"]
    for row in rows:
        assert sorted(row) == ROW_FIELDS


def test_export_rows_hold_the_entry(make_corpus):
    rows = {row["id"]: row for row in export_index(make_corpus())["entries"]}
    beta = rows["formats-beta"]
    assert beta["title"] == "The beta format"
    assert beta["group"] == "FORMATS"
    assert beta["source"] == "docs/beta.md"
    assert beta["source_commit"] == "abc1234"
    assert beta["updated"] == "2026-10-02"
    assert beta["path"] == "formats/formats-beta.md"
    assert beta["point"] == "A beta record names the alpha rows it summarizes!"
    assert beta["description"] == "A beta record names the alpha rows it summarizes!"
    assert beta["body"] == BETA.split("---\n", 2)[2].strip()
    assert not beta["body"].startswith("---")
    assert "source_commit" not in beta["body"]


def test_export_of_the_real_corpus_lists_every_entry():
    exported = export_index(CORPUS)
    ids = [row["id"] for row in exported["entries"]]
    assert ids == sorted(ids)
    paths = sorted(row["path"] for row in exported["entries"])
    assert paths == sorted(p.relative_to(CORPUS).as_posix() for p in entry_files(CORPUS))
    assert exported["title"] == "Manuscript pipeline standards"


def test_write_export_is_sorted_indented_json_with_the_same_bytes_twice(make_corpus, tmp_path):
    corpus = make_corpus()
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    write_export(corpus, first)
    write_export(corpus, second)
    assert first.read_bytes() == second.read_bytes()
    text = first.read_text(encoding="utf-8")
    assert text.endswith("}\n")
    assert not text.endswith("\n\n")
    assert json.loads(text) == export_index(corpus)
    assert text == json.dumps(export_index(corpus), sort_keys=True, indent=2, ensure_ascii=False) + "\n"


# The commands.


def test_command_llms_rewrites_then_reports_unchanged(make_corpus):
    corpus = make_corpus({"formats/formats-and.md": AND})
    first = run_kb("llms", "--corpus", str(corpus))
    assert first.returncode == 0, first.stderr
    assert first.stdout == "rewrote\n"
    second = run_kb("llms", "--corpus", str(corpus))
    assert second.returncode == 0, second.stderr
    assert second.stdout == "unchanged\n"


def test_command_llms_leaves_the_package_index_unchanged(capsys):
    before = (CORPUS / "llms.txt").read_bytes()
    assert main(["llms"]) == 0
    assert capsys.readouterr().out == "unchanged\n"
    assert (CORPUS / "llms.txt").read_bytes() == before


def test_command_export_writes_the_file(make_corpus, tmp_path):
    corpus = make_corpus()
    out = tmp_path / "kb_index.json"
    result = run_kb("export", "--out", str(out), "--corpus", str(corpus))
    assert result.returncode == 0, result.stderr
    assert json.loads(out.read_text(encoding="utf-8")) == export_index(corpus)


def test_command_export_needs_out():
    result = run_kb("export")
    assert result.returncode == 2


# The layer's edge.


def test_no_import_of_another_layer():
    pattern = re.compile(r"^\s*(import|from)\s+(ospipe|verification_procedures|vg)\b")
    for path in sorted(KB.rglob("*.py")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            assert not pattern.match(line), "{}:{} {}".format(path, number, line)
