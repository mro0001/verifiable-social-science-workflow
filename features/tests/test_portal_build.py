"""Step F15. Search, the critique box, the portal's own pages, and the portal command.

The real tree's portal is built with python3 -m features portal build into a
temporary out folder, and the site is read back as files. The script itself
is not run here, since no browser test is part of the step, so its tests read
its text. The home page's handling is also checked on a copy of the portal
fixture.

Run from the repository root as python3 -m pytest -q features/tests.
"""
import datetime
import glob
import html
import json
import os
import re
import shlex
import shutil
import subprocess
import sys

import pytest
import yaml

from features import cli
from features.portal import render, sources
from features.portal.sources import PortalError
from features.tests import helpers

ROOT = helpers.ROOT
FIXTURE = helpers.FIXTURES / "portal"
CONFIG = ROOT / "features" / "portal" / "portal.yaml"
PAGES = ROOT / "features" / "portal" / "pages"
ASSETS = ROOT / "features" / "portal" / "assets"
CORPUS = ROOT / "audit_layer" / "kb" / "corpus"
GRAPHS = ROOT / "verification_procedures" / "graphs"
NOW = datetime.datetime(2026, 10, 29, 9, 30, 0, tzinfo=datetime.timezone.utc)
PREFIX = "window.PORTAL_INDEX = "
ROW_KEYS = ["id", "title", "kind", "group", "section", "gist", "url"]
CRITIQUE_KEYS = ["schema", "schema_version", "page", "title", "source", "source_commit",
                 "section", "by", "date", "text"]
IMPLEMENT_PAGE = "docs/features-portal-pages-implement.html"
CRITIQUE_PAGE = "docs/features-portal-pages-critique.html"
VERIFICATION_PAGES = ["procedures/prose.html", "procedures/citations.html",
                      "procedures/data.html", "procedures/build.html"]


def run_features(*args):
    return subprocess.run([sys.executable, "-m", "features"] + [str(arg) for arg in args],
                          cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True)


def read(path):
    return path.read_text(encoding="utf-8")


def read_index(out):
    text = read(out / "search_index.js").strip()
    assert text.startswith(PREFIX)
    assert text.endswith(";")
    return json.loads(text[len(PREFIX):-1])


def item_pages(out):
    return [name for name in helpers.site_files(out)
            if name.endswith(".html") and name != "index.html"]


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("portal") / "site"
    result = run_features("portal", "build", "--out", out)
    return out, result


# The command on the real tree.

def test_the_command_exits_0_and_prints_the_count_the_warnings_and_the_index(built):
    out, result = built
    assert result.returncode == 0, result.stdout + result.stderr
    pages = [name for name in helpers.site_files(out) if name.endswith(".html")]
    assert "%d pages" % len(pages) in result.stdout
    assert str(out / "index.html") in result.stdout
    found = sources.load_all(str(CONFIG), str(ROOT))
    for warning in found.warnings:
        assert warning in result.stdout, warning


def test_the_site_has_a_page_for_each_entry_graph_and_listed_doc(built):
    out, _ = built
    files = set(helpers.site_files(out))
    assert "index.html" in files
    entries = sources.load_entries(str(CORPUS), str(ROOT))
    assert len(entries) == len(glob.glob(str(CORPUS / "*" / "*.md")))
    for item in entries:
        assert "entries/%s.html" % item.id in files, item.origin
    for path in glob.glob(str(GRAPHS / "*.yaml")):
        stem = os.path.splitext(os.path.basename(path))[0]
        assert "procedures/%s.html" % stem in files, path
    config = yaml.safe_load(read(CONFIG))
    for doc in config["docs"]:
        page = "docs/%s.html" % sources.doc_id(doc["path"])
        assert (page in files) == (ROOT / doc["path"]).is_file(), doc["path"]
    assert IMPLEMENT_PAGE in files and CRITIQUE_PAGE in files


def test_the_portal_yaml_names_the_home_page_and_the_two_portal_pages():
    config = yaml.safe_load(read(CONFIG))
    assert config["home"] == "features/portal/pages/home.md"
    sections = dict((doc["path"], (doc["section"], doc["optional"])) for doc in config["docs"])
    assert sections["features/portal/pages/implement.md"] == ("implement", False)
    assert sections["features/portal/pages/critique.md"] == ("critique", False)


def test_the_implement_and_critique_pages_link_to_the_home_page_and_to_each_other(built):
    out, _ = built
    implement = [value for _, _, value in helpers.parse_site_page(out / IMPLEMENT_PAGE).links]
    critique = [value for _, _, value in helpers.parse_site_page(out / CRITIQUE_PAGE).links]
    body_implement = read(out / IMPLEMENT_PAGE).split('<div class="body">', 1)[1]
    body_critique = read(out / CRITIQUE_PAGE).split('<div class="body">', 1)[1]
    assert 'href="../index.html"' in body_implement
    assert 'href="../index.html"' in body_critique
    assert 'href="features-portal-pages-critique.html"' in body_implement
    assert 'href="features-portal-pages-implement.html"' in body_critique
    assert "features-portal-pages-critique.html" in implement
    assert "features-portal-pages-implement.html" in critique


def test_the_implement_page_points_to_the_sample_project_page(built):
    out, _ = built
    body = read(out / IMPLEMENT_PAGE).split('<div class="body">', 1)[1]
    assert 'href="examples-sample-project-readme.html"' in body


def test_the_home_text_opens_the_catalog_and_links_the_four_procedures(built):
    out, _ = built
    text = read(out / "index.html")
    home = text.split('<div class="home">', 1)[1].split('<section class="section"', 1)[0]
    for page in VERIFICATION_PAGES:
        assert 'href="%s"' % page in home, page
    assert 'href="%s"' % IMPLEMENT_PAGE in home
    assert 'href="%s"' % CRITIQUE_PAGE in home
    for name in ("Change review", "Source support", "Build integrity"):
        assert name in home, name
    assert text.index('<div class="home">') < text.index('<section class="section"')
    assert text.count("<h1>") == 1


def test_the_search_index_has_one_row_per_page_and_each_url_is_a_file(built):
    out, _ = built
    rows = read_index(out)
    files = set(helpers.site_files(out))
    assert sorted(row["url"] for row in rows) == sorted(item_pages(out))
    for row in rows:
        assert list(row) == ROW_KEYS, row
        assert row["url"] in files, row
        assert row["section"] in ("learn", "implement", "critique"), row
    ids = [row["id"] for row in rows]
    assert len(ids) == len(set(ids))


def test_each_search_row_matches_its_page_and_its_catalog_card(built):
    out, _ = built
    cards = dict((href, (h2, h3)) for h2, h3, href in
                 helpers.parse_site_page(out / "index.html").cards)
    labels = {"learn": "Learn", "implement": "Implement", "critique": "Critique"}
    for row in read_index(out):
        text = read(out / row["url"])
        assert 'data-page-id="%s"' % row["id"] in text, row
        assert cards[row["url"]][0] == labels[row["section"]], row
    kinds = dict((row["url"], row["kind"]) for row in read_index(out))
    assert kinds["procedures/prose.html"] == "procedure"
    assert kinds[IMPLEMENT_PAGE] == "doc"
    assert kinds[CRITIQUE_PAGE] == "doc"


def test_every_item_page_has_the_critique_section_with_its_id_source_and_version(built):
    out, _ = built
    found = sources.load_all(str(CONFIG), str(ROOT))
    expected = {}
    for item in found.items:
        folder = "entries" if item.kind == "entry" else "docs"
        expected["%s/%s.html" % (folder, item.id)] = (item.id, item.source, item.source_commit)
    for proc in found.procedures:
        stem = os.path.splitext(os.path.basename(proc.origin))[0]
        expected["procedures/%s.html" % stem] = (stem, proc.origin, None)
    assert sorted(expected) == sorted(item_pages(out))
    for name in item_pages(out):
        text = read(out / name)
        section = re.search(r'<section class="critique" data-page-id="([^"]+)" data-title="[^"]+"'
                            r' data-source="([^"]+)" data-source-commit="([^"]+)"></section>',
                            text)
        assert section, name
        page_id, source, commit = expected[name]
        assert section.group(1) == page_id, name
        assert html.unescape(section.group(2)) == source, name
        if commit is None:
            assert section.group(3).startswith("sha256:"), name
        else:
            assert html.unescape(section.group(3)) == commit, name


def test_every_page_has_the_search_box_and_both_scripts_in_order(built):
    out, _ = built
    for name in helpers.site_files(out):
        if not name.endswith(".html"):
            continue
        prefix = "../" * name.count("/")
        text = read(out / name)
        assert '<form class="search" role="search" hidden data-root="%s"' % prefix in text, name
        assert 'type="search"' in text, name
        first = text.index('<script src="%ssearch_index.js"></script>' % prefix)
        second = text.index('<script src="%sassets/portal.js"></script>' % prefix)
        assert first < second, name
    catalog = read(out / "index.html")
    for section in ("all", "learn", "implement", "critique"):
        assert 'data-section="%s"' % section in catalog, section


def test_no_script_image_or_stylesheet_comes_from_the_web(built):
    out, _ = built
    for name in helpers.site_files(out):
        if not name.endswith(".html"):
            continue
        for tag, attribute, value in helpers.parse_site_page(out / name).links:
            if attribute == "src" or tag == "link":
                assert not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:|^//", value), (name, tag, value)


def test_no_file_holds_an_absolute_path(built):
    out, _ = built
    for name in helpers.site_files(out):
        text = read(out / name)
        for bad in ("/Users/", "/private/tmp/", str(ROOT), os.path.realpath(str(ROOT))):
            assert bad not in text, (name, bad)


def test_every_internal_link_resolves(built):
    out, _ = built
    files = set(helpers.site_files(out))
    for page in [name for name in files if name.endswith(".html")]:
        folder = os.path.dirname(page)
        for tag, attribute, value in helpers.parse_site_page(out / page).links:
            if helpers.is_outside_link(value):
                continue
            target = os.path.normpath(os.path.join(folder, value.split("#")[0]))
            assert target.replace(os.sep, "/") in files, (page, tag, attribute, value)


def test_the_assets_are_copied_byte_for_byte_and_listed(built):
    out, _ = built
    for name in ("portal.css", "portal.js"):
        assert (out / "assets" / name).read_bytes() == (ASSETS / name).read_bytes(), name
    manifest = json.loads(read(out / "site_manifest.json"))
    pages = dict((page["path"], page) for page in manifest["pages"])
    assert pages["assets/portal.js"]["origin"] == "features/portal/assets/portal.js"
    assert pages["search_index.js"]["origin"] is None
    listed = [source["origin"] for source in manifest["sources"]]
    assert "features/portal/pages/home.md" in listed
    assert sorted(helpers.site_files(out)) == sorted(list(pages) + ["site_manifest.json"])


def test_building_again_into_the_same_folder_replaces_the_site(built, tmp_path):
    out, _ = built
    copy = tmp_path / "site"
    shutil.copytree(str(out), str(copy))
    result = run_features("portal", "build", "--out", copy)
    assert result.returncode == 0, result.stdout + result.stderr
    assert helpers.site_files(copy) == helpers.site_files(out)


def test_a_folder_that_is_not_a_portal_build_is_refused_with_exit_1(tmp_path):
    out = tmp_path / "mine"
    out.mkdir()
    (out / "keep.txt").write_text("mine\n", encoding="utf-8")
    result = run_features("portal", "build", "--out", out)
    assert result.returncode == 1
    assert "site_manifest.json" in result.stderr
    assert helpers.site_files(out) == ["keep.txt"]


def test_a_config_that_cannot_be_read_is_refused_with_exit_1(tmp_path):
    result = run_features("portal", "build", "--config", tmp_path / "none.yaml",
                          "--out", tmp_path / "site")
    assert result.returncode == 1
    assert "none.yaml" in result.stderr
    assert not (tmp_path / "site").exists()


def test_the_command_defaults_to_the_portal_yaml_and_the_site_folder():
    parser, _ = cli._parser()
    options = parser.parse_args(["portal", "build"])
    assert options.config is None and options.out is None
    assert render.DEFAULT_CONFIG == "features/portal/portal.yaml"
    assert render.DEFAULT_OUT == "features/portal/_site"
    lines = read(ROOT / "features" / ".gitignore").splitlines()
    assert "portal/_site/" in lines


# The script.

def script_text():
    return read(ASSETS / "portal.js")


def test_the_script_uses_no_library_and_no_network():
    text = script_text()
    for bad in ("http://", "https://", "fetch(", "XMLHttpRequest", "import ", "require(",
                "WebSocket", "sendBeacon"):
        assert bad not in text, bad


def test_the_script_reads_the_index_and_writes_the_critique_fields_in_order():
    text = script_text()
    assert "window.PORTAL_INDEX" in text
    places = [text.index('"%s: "' % key) for key in CRITIQUE_KEYS]
    assert places == sorted(places)
    assert '"portal-critique"' in text
    assert '"critique_"' in text and '".yaml"' in text
    assert "whole page" in text
    for field in ("title", "gist", "group", "kind"):
        assert "row.%s" % field in text, field


# The home page on the fixture.

@pytest.fixture
def fixture(tmp_path):
    folder = tmp_path / "portal"
    shutil.copytree(str(FIXTURE), str(folder))
    return folder


def with_home(folder, text, path="home.md"):
    (folder / path).write_text(text, encoding="utf-8")
    config = yaml.safe_load(read(folder / "portal.yaml"))
    config["home"] = path
    (folder / "portal.yaml").write_text(yaml.safe_dump(config, sort_keys=False),
                                        encoding="utf-8")


def test_the_home_text_opens_the_fixture_catalog_with_its_links_pointed_at_pages(fixture,
                                                                              tmp_path):
    with_home(fixture, "# Home\n\nStart with [the guide](docs/guide.md) and "
                       "[the demo](procedures/graphs/demo.yaml).\n")
    found = sources.load_all(str(fixture / "portal.yaml"), str(fixture))
    assert found.home.origin == "home.md"
    out = tmp_path / "site"
    render.write_site(found, str(out), NOW, root=str(fixture))
    text = read(out / "index.html")
    home = text.split('<div class="home">', 1)[1].split('<section class="section"', 1)[0]
    assert 'href="docs/docs-guide.html"' in home
    assert 'href="procedures/demo.html"' in home
    assert ">Home<" not in home


def test_a_doc_link_to_the_home_file_points_at_the_catalog(fixture, tmp_path):
    with_home(fixture, "# Home\n\nThe start.\n")
    guide = fixture / "docs" / "guide.md"
    guide.write_text(read(guide) + "\nBack to [the start](../home.md).\n", encoding="utf-8")
    found = sources.load_all(str(fixture / "portal.yaml"), str(fixture))
    out = tmp_path / "site"
    render.write_site(found, str(out), NOW, root=str(fixture))
    assert 'href="../index.html">the start</a>' in read(out / "docs" / "docs-guide.html")


def test_a_config_without_home_builds_a_catalog_with_no_home_text(fixture, tmp_path):
    found = sources.load_all(str(fixture / "portal.yaml"), str(fixture))
    assert found.home is None
    out = tmp_path / "site"
    render.write_site(found, str(out), NOW, root=str(fixture))
    assert '<div class="home">' not in read(out / "index.html")


def test_a_missing_home_file_raises_naming_it(fixture):
    with_home(fixture, "# Home\n")
    (fixture / "home.md").unlink()
    with pytest.raises(PortalError) as raised:
        sources.load_all(str(fixture / "portal.yaml"), str(fixture))
    assert "home.md" in str(raised.value)


def test_a_home_outside_the_workflow_folder_is_refused(fixture, tmp_path):
    (tmp_path / "outside.md").write_text("# Out\n", encoding="utf-8")
    config = yaml.safe_load(read(fixture / "portal.yaml"))
    config["home"] = "../outside.md"
    (fixture / "portal.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    with pytest.raises(PortalError):
        sources.load_all(str(fixture / "portal.yaml"), str(fixture))


def test_the_fixture_search_index_lists_its_pages(fixture, tmp_path):
    found = sources.load_all(str(fixture / "portal.yaml"), str(fixture))
    out = tmp_path / "site"
    result = render.write_site(found, str(out), NOW, root=str(fixture))
    rows = read_index(out)
    assert sorted(row["url"] for row in rows) == sorted(
        page for page in result.pages if page != "index.html")
    alpha = [row for row in rows if row["id"] == "alpha-first"][0]
    assert alpha == {"id": "alpha-first", "title": "The first entry", "kind": "entry",
                     "group": "ALPHA", "section": "learn",
                     "gist": "The first entry's short answer, written over two lines.",
                     "url": "entries/alpha-first.html"}


# The portal's own pages.

def test_every_features_command_on_the_portal_pages_parses():
    parser, _ = cli._parser()
    seen = set()
    for name in ("home.md", "implement.md", "critique.md"):
        for line in re.findall(r"python3 -m features ([^`\n]*)", read(PAGES / name)):
            options = parser.parse_args(shlex.split(line))
            seen.add((options.group, options.command))
    assert ("setup", "system") in seen and ("setup", "project") in seen
    assert ("portal", "build") in seen


def test_the_portal_pages_use_no_long_dash():
    for name in ("home.md", "implement.md", "critique.md"):
        assert "\u2014" not in read(PAGES / name), name
