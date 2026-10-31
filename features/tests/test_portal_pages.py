"""Step F13. Entry and documentation pages and the catalog.

The site is built from the portal fixture, features/tests/fixtures/portal/,
into temporary out folders. Pandoc converts each page's markdown, as the
pipeline already requires it.

Run from the repository root as python3 -m pytest -q features/tests.
"""
import datetime
import hashlib
import json
import os
import shutil

import pytest

from features.portal import render, sources
from features.portal.sources import PortalError
from features.tests import helpers

ROOT = helpers.ROOT
FIXTURE = helpers.FIXTURES / "portal"
STYLESHEET = ROOT / "features" / "portal" / "assets" / "portal.css"
NOW = datetime.datetime(2026, 10, 29, 9, 30, 0, tzinfo=datetime.timezone.utc)
ENTRY_PAGES = ["entries/alpha-first.html", "entries/beta-second.html"]
DOC_PAGES = ["docs/docs-guide.html", "docs/docs-more.html"]


@pytest.fixture
def fixture(tmp_path):
    """A copy of the portal fixture, so a test may change it."""
    folder = tmp_path / "portal"
    shutil.copytree(str(FIXTURE), str(folder))
    return folder


def build(folder, out):
    found = sources.load_all(str(folder / "portal.yaml"), str(folder))
    return render.write_site(found, str(out), NOW, root=str(folder))


@pytest.fixture
def site(fixture, tmp_path):
    out = tmp_path / "site"
    result = build(fixture, out)
    return out, result


def read(path):
    return path.read_text(encoding="utf-8")


def main_part(text):
    """The page after its header, where the item's own content sits."""
    return text.split("</header>", 1)[1]


# Markdown to HTML.

def test_markdown_to_html_drops_a_first_level_one_heading_and_keeps_the_rest():
    html = render.markdown_to_html("# The title\n\nA paragraph.\n\n## A part\n\nMore.\n")
    assert "The title" not in html
    assert "<p>A paragraph.</p>" in html
    assert ">A part</h2>" in html


def test_markdown_to_html_keeps_a_first_line_that_is_not_a_level_one_heading():
    html = render.markdown_to_html("## A part\n\nText.\n")
    assert ">A part</h2>" in html


def test_markdown_to_html_raises_when_pandoc_is_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(PortalError) as raised:
        render.markdown_to_html("Text.\n")
    assert "andoc" in str(raised.value)


# The pages and the catalog.

def test_each_item_has_a_page_and_the_catalog_links_to_each(site):
    out, result = site
    for page in ENTRY_PAGES + DOC_PAGES:
        assert (out / page).is_file(), page
        assert page in result.pages
    assert "index.html" in result.pages
    catalog = helpers.parse_site_page(out / "index.html")
    linked = [href for _, _, href in catalog.cards]
    for page in ENTRY_PAGES + DOC_PAGES:
        assert page in linked, page


def test_every_link_in_the_site_resolves_to_a_file_in_the_site(site):
    out, _ = site
    files = set(helpers.site_files(out))
    for page in [name for name in files if name.endswith(".html")]:
        folder = os.path.dirname(page)
        for tag, attribute, value in helpers.parse_site_page(out / page).links:
            if helpers.is_outside_link(value):
                continue
            target = os.path.normpath(os.path.join(folder, value.split("#")[0]))
            assert target.replace(os.sep, "/") in files, (page, tag, attribute, value)


def test_the_catalog_groups_cards_by_section_and_entries_by_group(site):
    out, _ = site
    cards = helpers.parse_site_page(out / "index.html").cards
    where = dict((href, (h2, h3)) for h2, h3, href in cards)
    assert where["entries/alpha-first.html"] == ("Learn", "ALPHA")
    assert where["entries/beta-second.html"] == ("Learn", "BETA")
    assert where["docs/docs-more.html"][0] == "Learn"
    assert where["docs/docs-guide.html"][0] == "Implement"
    text = read(out / "index.html")
    for anchor in ('id="learn"', 'id="implement"', 'id="critique"'):
        assert anchor in text


def test_each_card_shows_its_title_kind_group_and_gist(site):
    out, _ = site
    text = read(out / "index.html")
    card = text.split('href="entries/alpha-first.html"', 1)[1].split("</article>", 1)[0]
    assert "The first entry" in card
    assert "entry" in card
    assert "ALPHA" in card
    assert "The first entry&#x27;s short answer, written over two lines." in card
    doc_card = text.split('href="docs/docs-guide.html"', 1)[1].split("</article>", 1)[0]
    assert "The fixture guide" in doc_card and "doc" in doc_card
    assert "The fixture guide&#x27;s first paragraph." in doc_card


def test_an_entry_page_shows_its_details_and_consult_also_link_and_its_title_once(site):
    out, _ = site
    text = read(out / "entries" / "alpha-first.html")
    body = main_part(text)
    assert body.count("<h1") == 1
    assert body.count("The first entry</h1>") == 1
    for value in ("docs/guide.md", "sha256:0123456789ab", "2026-10-01", "ALPHA",
                  "kb/alpha/alpha-first.md"):
        assert value in body, value
    for label in ("Source", "Source version", "Updated", "Group", "Origin"):
        assert ">%s</dt>" % label in body, label
    assert 'href="beta-second.html"' in body
    assert "A second paragraph with the facts." in body


def test_every_page_is_complete_with_its_head_header_and_critique_section(site):
    out, _ = site
    for page in ENTRY_PAGES + DOC_PAGES:
        text = read(out / page)
        assert text.startswith("<!doctype html>")
        assert '<meta charset="utf-8">' in text
        assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in text
        assert '<link rel="stylesheet" href="../assets/portal.css">' in text
        header = text.split("</header>", 1)[0]
        for href in ("../index.html", "../index.html#learn", "../index.html#implement",
                     "../index.html#critique"):
            assert 'href="%s"' % href in header, (page, href)
        assert '<section class="critique"' in text
    entry = read(out / "entries" / "alpha-first.html")
    assert "<title>The first entry</title>" in entry
    critique = entry.split('<section class="critique"', 1)[1].split(">", 1)[0]
    assert 'data-page-id="alpha-first"' in critique
    assert 'data-title="The first entry"' in critique
    assert 'data-source="docs/guide.md"' in critique
    assert 'data-source-commit="sha256:0123456789ab"' in critique
    index = read(out / "index.html")
    assert index.startswith("<!doctype html>")
    assert '<link rel="stylesheet" href="assets/portal.css">' in index
    assert "<title>A fixture portal</title>" in index


def test_page_html_escapes_the_item_text():
    item = sources.Item(
        kind="entry", id="odd", title="Fish & <chips>", group="G", source="a<b>.md",
        source_commit="sha256:000000000000", updated="2026-10-01", gist="", markdown="",
        consult_also=[], origin="kb/g/odd.md")
    text = render.page_html(item, render.Site(title="T & T"), "<p>body</p>", 1)
    assert "Fish &amp; &lt;chips&gt;" in text
    assert "<chips>" not in text
    assert "a&lt;b&gt;.md" in text
    assert "<p>body</p>" in text


def test_a_doc_link_to_a_listed_doc_or_entry_points_at_its_page(site):
    out, _ = site
    body = main_part(read(out / "docs" / "docs-guide.html"))
    assert 'href="docs-more.html#start"' in body
    assert 'href="../entries/alpha-first.html"' in body
    back = main_part(read(out / "docs" / "docs-more.html"))
    assert 'href="docs-guide.html"' in back


def test_a_doc_link_or_image_to_a_file_outside_the_site_is_plain_text_and_a_warning(site):
    out, result = site
    body = main_part(read(out / "docs" / "docs-guide.html"))
    assert "raw data" in body
    assert "raw.csv" not in body
    assert "a small chart" in body
    assert "chart.png" not in body
    assert "<img" not in body
    raw = [warning for warning in result.warnings if "../data/raw.csv" in warning]
    image = [warning for warning in result.warnings if "chart.png" in warning]
    assert len(raw) == 1 and "docs/guide.md" in raw[0]
    assert len(image) == 1 and "docs/guide.md" in image[0]


def test_links_to_the_web_a_fragment_or_mail_are_kept(site):
    out, _ = site
    body = main_part(read(out / "docs" / "docs-guide.html"))
    assert 'href="https://example.org/"' in body
    assert 'href="#more-text"' in body
    assert 'href="mailto:author@example.org"' in body


def test_no_page_holds_an_absolute_path(site, fixture):
    out, _ = site
    for name in helpers.site_files(out):
        text = read(out / name)
        for bad in ("/Users/", "/private/tmp/", str(ROOT), str(fixture),
                    os.path.realpath(str(fixture))):
            assert bad not in text, (name, bad)


def test_the_stylesheet_is_copied_byte_for_byte_and_covers_both_themes(site):
    out, _ = site
    assert (out / "assets" / "portal.css").read_bytes() == STYLESHEET.read_bytes()
    css = read(STYLESHEET)
    assert "prefers-color-scheme: dark" in css
    assert ":focus-visible" in css
    assert "@media (max-width" in css


def test_the_manifest_names_each_page_and_source_with_its_checksum(site, fixture):
    out, result = site
    manifest = json.loads(read(out / "site_manifest.json"))
    assert manifest["schema"] == "portal-site"
    assert manifest["schema_version"] == 1
    assert manifest["built_at"] == "2026-10-29T09:30:00+00:00"
    pages = dict((page["path"], page) for page in manifest["pages"])
    for name in result.pages + ["assets/portal.css"]:
        assert name in pages, name
        digest = hashlib.sha256((out / name).read_bytes()).hexdigest()
        assert pages[name]["sha256"] == digest, name
    assert pages["entries/alpha-first.html"]["origin"] == "kb/alpha/alpha-first.md"
    assert pages["docs/docs-guide.html"]["origin"] == "docs/guide.md"
    assert pages["index.html"]["origin"] is None
    listed = dict((source["origin"], source["sha256"]) for source in manifest["sources"])
    for origin in ("kb/alpha/alpha-first.md", "kb/beta/beta-second.md", "docs/guide.md",
                   "docs/more.md"):
        assert listed[origin] == hashlib.sha256((fixture / origin).read_bytes()).hexdigest()
    assert sorted(helpers.site_files(out)) == sorted(list(pages) + ["site_manifest.json"])


# The out folder.

def test_rebuilding_after_removing_an_entry_leaves_no_page_for_it(fixture, tmp_path):
    out = tmp_path / "site"
    build(fixture, out)
    assert (out / "entries" / "beta-second.html").is_file()
    (fixture / "kb" / "beta" / "beta-second.md").unlink()
    result = build(fixture, out)
    assert not (out / "entries" / "beta-second.html").exists()
    assert (out / "entries" / "alpha-first.html").is_file()
    assert "entries/beta-second.html" not in read(out / "index.html")
    manifest = json.loads(read(out / "site_manifest.json"))
    assert "entries/beta-second.html" not in [page["path"] for page in manifest["pages"]]
    assert any("beta-second" in warning for warning in result.warnings)
    assert 'href="beta-second.html"' not in read(out / "entries" / "alpha-first.html")


def test_an_empty_out_folder_is_used(fixture, tmp_path):
    out = tmp_path / "site"
    out.mkdir()
    build(fixture, out)
    assert (out / "index.html").is_file()


def test_a_folder_that_is_not_a_portal_build_is_refused_and_left_as_it_is(fixture, tmp_path):
    out = tmp_path / "site"
    out.mkdir()
    (out / "mine.txt").write_text("keep me\n", encoding="utf-8")
    with pytest.raises(PortalError) as raised:
        build(fixture, out)
    assert "site_manifest.json" in str(raised.value)
    assert helpers.site_files(out) == ["mine.txt"]


def test_a_folder_whose_manifest_is_not_a_portal_build_is_refused(fixture, tmp_path):
    out = tmp_path / "site"
    out.mkdir()
    (out / "site_manifest.json").write_text('{"schema": "other"}\n', encoding="utf-8")
    with pytest.raises(PortalError):
        build(fixture, out)
    assert helpers.site_files(out) == ["site_manifest.json"]


def test_a_manifest_page_outside_the_out_folder_is_never_removed(fixture, tmp_path):
    out = tmp_path / "site"
    build(fixture, out)
    keep = tmp_path / "keep.html"
    keep.write_text("keep\n", encoding="utf-8")
    manifest = json.loads(read(out / "site_manifest.json"))
    manifest["pages"].append({"path": "../keep.html", "origin": None, "sha256": "0"})
    (out / "site_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(PortalError):
        build(fixture, out)
    assert keep.is_file()


def test_the_sources_give_each_item_its_kind_and_the_config_its_title():
    found = sources.load_all(str(FIXTURE / "portal.yaml"), str(FIXTURE))
    kinds = dict((item.id, item.kind) for item in found.items)
    assert kinds == {"alpha-first": "entry", "beta-second": "entry", "docs-guide": "doc",
                     "docs-more": "doc"}
    assert found.title == "A fixture portal"
