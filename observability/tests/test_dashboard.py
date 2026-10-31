"""Tests for the dashboard page (Track E, steps E7 and E8).

Proposal Figure 3 shows the prototype's run table, timeline, and step detail,
Figure 2 the dashboard, and Approach paragraph 4 the tools the harness calls
and the reasoning behind its choices. Appendix A2.6 paragraph 1 names the
reasoning, tool calls, and tool results, and Table A7 leaves the dashboard's
design still to be developed. The page is three files in
observability/dashboard/, a static page that opens from disk with no server
and no network and reads only data.js (plan choices 14 and 15). build_view
copies the three files into the view folder unchanged. Step E8 adds the
files tab and the knowledge base tab, which Approach paragraph 4 and A2.6
paragraph 1 name (which files the harness reads and which knowledge base
entries it retrieves), and the checks of step E7 still hold. Views are built in
temporary folders from a synthetic audit home. Nothing here calls a model or
the network. Run from the repository root with
python3 -m pytest -q observability/tests.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from observability import build as bd
from observability.tests.audit_fixture import STORY_SESSION_ID, AuditHome, story_transcript

TESTS = Path(__file__).resolve().parent
DASHBOARD = TESTS.parent / "dashboard"
PAGE_FILES = ("index.html", "app.js", "style.css")
FORBIDDEN = ("http://", "https://", "fetch(", "XMLHttpRequest", "innerHTML", "outerHTML",
             "insertAdjacentHTML", "document.write")


def _text(name):
    return (DASHBOARD / name).read_text(encoding="utf-8")


def _defines(name):
    return re.search(r"\bfunction\s+%s\s*\(" % re.escape(name), _text("app.js")) is not None


@pytest.fixture
def built(tmp_path):
    project = tmp_path / "work" / "story_project"
    project.mkdir(parents=True)
    audit = AuditHome(tmp_path / "audit_home")
    row = audit.add_session(STORY_SESSION_ID, project)
    audit.add_transcript(row, story_transcript(project))
    out = tmp_path / "view"
    bd.build_view(audit.home, out)
    return out


def test_the_three_page_files_exist():
    for name in PAGE_FILES:
        assert (DASHBOARD / name).is_file(), name


def test_a_build_writes_the_three_files_byte_for_byte(built):
    for name in PAGE_FILES:
        assert (built / name).read_bytes() == (DASHBOARD / name).read_bytes(), name
    assert (built / "data.js").is_file()


def test_a_second_build_writes_them_again_unchanged(built, tmp_path):
    (built / "app.js").write_text("changed", encoding="utf-8")
    bd.build_view(tmp_path / "audit_home", built)
    assert (built / "app.js").read_bytes() == (DASHBOARD / "app.js").read_bytes()


def test_index_html_loads_only_its_style_its_data_and_its_script():
    page = _text("index.html")
    loaded = re.findall(r"""\b(?:src|href)\s*=\s*["']([^"']*)["']""", page, flags=re.I)
    assert sorted(loaded) == ["app.js", "data.js", "style.css"]
    scripts = re.findall(r"""<script\b[^>]*\bsrc\s*=\s*["']([^"']*)["']""", page, flags=re.I)
    assert scripts == ["data.js", "app.js"]
    assert not re.search(r"<script\b(?![^>]*\bsrc=)[^>]*>\s*\S", page, flags=re.I)
    assert "@import" not in _text("style.css")
    assert "url(" not in _text("style.css")


@pytest.mark.parametrize("name", PAGE_FILES)
def test_no_page_file_reaches_the_network_or_parses_text_as_html(name):
    text = _text(name)
    for word in FORBIDDEN:
        assert word not in text, "%s holds %s" % (name, word)


def test_app_js_defines_render_traces():
    assert _defines("renderTraces")


def test_app_js_reads_only_window_obs():
    script = _text("app.js")
    assert "window.OBS" in script
    assert "localStorage" not in script and "sessionStorage" not in script
    assert not re.search(r"\beval\s*\(", script)
    assert "new Function" not in script


def test_the_page_keeps_its_place_after_the_hash_and_reloads_while_live():
    script = _text("app.js")
    assert "location.hash" in script
    assert "hashchange" in script
    assert "refresh_seconds" in script and "location.reload" in script


def test_record_text_is_placed_with_text_content():
    assert "textContent" in _text("app.js")


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not on the command path")
def test_node_check_passes_on_app_js():
    done = subprocess.run(["node", "--check", str(DASHBOARD / "app.js")],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


# Step E8, the files tab and the knowledge base tab


def test_app_js_defines_render_files_and_render_kb():
    assert _defines("renderFiles")
    assert _defines("renderKb")


def test_index_html_names_the_files_and_knowledge_base_tabs():
    page = _text("index.html")
    tabs = re.findall(r"""<button\b[^>]*\bdata-tab\s*=\s*["']([^"']*)["'][^>]*>([^<]*)<""", page)
    assert [name for name, _ in tabs] == ["traces", "files", "kb"]
    words = dict(tabs)
    assert words["files"].strip() == "Files"
    assert words["kb"].strip() == "Knowledge base"
    for name in ("traces", "files", "kb"):
        assert 'id="tab-%s"' % name in page
