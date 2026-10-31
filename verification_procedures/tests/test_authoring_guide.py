"""The authoring guide for new procedures (AUTHORING.md) checked against the runtime.

The guide names files, keys, and commands a new procedure uses, so these tests
keep it from drifting from vg.py. Every path it gives in backticks under
graphs/, contracts/, implementations/, fixtures/, or tests/ must exist, its
three marked lists must equal the keys and relations vg.py allows, every graph
must pass vg.py check, and its worked example must run. The worked example
evaluates the test story's references run with the llm_runs procedure, offline
with recorded answers, its story inputs arranged the way
examples/test_story/test_story.py arranges them.
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
GUIDE = ROOT / "AUTHORING.md"
STORY = REPO / "examples" / "test_story"
PREFIXES = ("graphs/", "contracts/", "implementations/", "fixtures/", "tests/")
PLACEHOLDERS = ("<story inputs>", "<story run>", "<eval inputs>", "<eval run>")

sys.path.insert(0, str(ROOT))
import vg  # noqa: E402


def guide():
    return GUIDE.read_text(encoding="utf-8")


def without_fences(text):
    """The text with every fenced code block left out."""
    return re.sub(r"^```.*?^```[ \t]*$", "", text, flags=re.S | re.M)


def marked_list(text, marker):
    """The first backticked word of each item in the list after <!-- marker -->."""
    lines = text.splitlines()
    start = lines.index("<!-- {} -->".format(marker))
    items = []
    for line in lines[start + 1:]:
        if not line.strip():
            if items:
                break
            continue
        match = re.match(r"^- `([^`]+)`", line)
        assert match, "{} list has a line that is not an item, {!r}".format(marker, line)
        items.append(match.group(1))
    return items


def worked_example(text):
    """The command lines of the fenced block after <!-- worked example -->."""
    match = re.search(r"<!-- worked example -->\s*```sh\n(.*?)^```", text, flags=re.S | re.M)
    assert match, "no worked example block"
    return [line for line in match.group(1).splitlines() if line.strip() and not line.startswith("#")]


def arrange_story_inputs(folder):
    """The story's references inputs, arranged as test_story.py arranges them."""
    folder.mkdir()
    shutil.copyfile(str(STORY / "project" / "manuscript.md"), str(folder / "draft.md"))
    refs = STORY / "references"
    shutil.copyfile(str(refs / "expected_citation_provenance.yaml"), str(folder / "citation_provenance.yaml"))
    for src in sorted(refs.iterdir()):
        if not src.name.startswith("expected_"):
            shutil.copyfile(str(src), str(folder / src.name))


def test_the_guide_exists_with_its_sections():
    headings = [line[3:] for line in guide().splitlines() if line.startswith("## ")]
    assert headings == [
        "What a procedure is",
        "The graph",
        "The contract",
        "Tool steps",
        "Judgment steps",
        "The report",
        "Test files",
        "The knowledge base entry",
        "Revising a procedure",
        "Graphs that are not a stream",
        "The four streams only",
        "The worked example",
    ]


def test_every_path_in_backticks_exists():
    spans = re.findall(r"`([^`\n]+)`", without_fences(guide()))
    paths = [span.split()[0] for span in spans if span.startswith(PREFIXES) and "<" not in span]
    assert len(paths) >= 10
    missing = sorted(set(path for path in paths if not (ROOT / path).exists()))
    assert missing == []


def test_the_marked_lists_equal_the_runtime_keys_and_relations():
    text = guide()
    for marker, allowed in (("node keys", vg.NODE_KEYS), ("edge keys", vg.EDGE_KEYS),
                            ("relations", vg.RELATIONS)):
        items = marked_list(text, marker)
        assert len(items) == len(set(items)), marker
        assert set(items) == set(allowed), marker


@pytest.mark.parametrize("graph", sorted(p.name for p in (ROOT / "graphs").glob("*.yaml")))
def test_every_graph_passes_check(graph):
    p = subprocess.run([sys.executable, "vg.py", "check", "graphs/" + graph], cwd=str(ROOT),
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
    assert p.stdout.startswith("OK: ")


def test_the_worked_example_runs(tmp_path):
    lines = worked_example(guide())
    assert len(lines) >= 4
    text = "\n".join(lines)
    for placeholder in PLACEHOLDERS:
        assert placeholder in text, placeholder
    assert "graphs/llm_runs.yaml" in text and "graphs/citations.yaml" in text
    arrange_story_inputs(tmp_path / "story_inputs")
    filled = {
        "<story inputs>": str(tmp_path / "story_inputs"),
        "<story run>": str(tmp_path / "story_run"),
        "<eval inputs>": str(tmp_path / "eval_inputs"),
        "<eval run>": str(tmp_path / "eval_run"),
    }
    env = dict(os.environ, VG_OFFLINE="1")
    for line in lines:
        command = line
        for placeholder, value in filled.items():
            command = command.replace(placeholder, value)
        assert "<" not in command, command
        p = subprocess.run(command, shell=True, cwd=str(ROOT), capture_output=True, text=True,
                           env=env)
        assert p.returncode == 0, "{}\n{}{}".format(line, p.stdout, p.stderr)
    report = tmp_path / "eval_run" / "files" / "report.md"
    assert report.read_text(encoding="utf-8").startswith("# ")


def test_the_guide_holds_no_em_dash():
    assert "—" not in guide()


def test_this_test_imports_no_other_layer():
    pattern = re.compile(r"^\s*(import|from)\s+(audit_layer|ospipe|observability|connections|features)\b")
    for number, line in enumerate(Path(__file__).read_text(encoding="utf-8").splitlines(), 1):
        assert not pattern.match(line), "{}:{} {}".format(__file__, number, line)
