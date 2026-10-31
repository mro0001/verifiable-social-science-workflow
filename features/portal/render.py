"""The portal's pages and its catalog (step F13).

The site is static and opens from disk with no server or network (track F
choice 20). Pandoc turns each page's markdown into HTML, since the pipeline
already requires it.

- markdown_to_html runs pandoc --from markdown --to html5 on the text. When a
  rewrite function is given, the text goes through Pandoc's JSON form first,
  so each link and image can be pointed at its page or turned into plain
  text.
- page_html gives one complete page for an item, with its details and an
  empty critique section that step F15's script fills.
- write_site writes the catalog, a page for each entry, doc, and procedure
  (step F14), the stylesheet, and site_manifest.json. It writes only into a folder that
  is absent, empty, or an earlier portal build. Step F15 adds the home page's
  text above the catalog, search_index.js, the script, and on every page the
  search box and both script tags.
- build_command is python3 -m features portal build (step F15).

Appendix A2.7 (a site to learn, implement, and critique, built on a catalog
site generator, appendix only) and A2.4 "Serving entries" (an overview of the
corpus, a list of entries, a full entry, and an entry's origin).
"""
import collections
import datetime
import hashlib
import html
import json
import os
import posixpath
import re
import subprocess
import sys

from features.layers import default_root
from features.portal import procedures as procedure_pages
from features.portal.sources import CONSULT_ALSO, LONG_DASH, Item, PortalError, load_all

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
STYLESHEET = "assets/portal.css"
STYLESHEET_ORIGIN = "features/portal/assets/portal.css"
SCRIPT = "assets/portal.js"
SCRIPT_ORIGIN = "features/portal/assets/portal.js"
SEARCH_INDEX = "search_index.js"
SEARCH_INDEX_PREFIX = "window.PORTAL_INDEX = "
INDEX_KEYS = ("id", "title", "kind", "group", "section", "gist", "url")
DEFAULT_CONFIG = "features/portal/portal.yaml"
DEFAULT_OUT = "features/portal/_site"
MANIFEST = "site_manifest.json"
SCHEMA = "portal-site"
SCHEMA_VERSION = 1
SECTIONS = (("learn", "Learn"), ("implement", "Implement"), ("critique", "Critique"))
KEPT_LINKS = ("http://", "https://", "mailto:")
SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
DOCS_HEADING = "Documentation"
VERIFICATION_HEADING = "Verification procedures"
OTHER_HEADING = "Other procedures"

Site = collections.namedtuple("Site", "title")
SiteResult = collections.namedtuple("SiteResult", "pages warnings")
# One page to write. rank orders the catalog's groups inside a section, and
# proc is the Procedure behind a procedure page, None for any other page.
Page = collections.namedtuple("Page", "path item section heading rank proc")


def _escape(value):
    return html.escape("" if value is None else str(value), quote=True)


# Markdown to HTML.

def _pandoc(args, text):
    try:
        done = subprocess.run(["pandoc"] + list(args), input=text.encode("utf-8"),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError:
        raise PortalError("Pandoc is not on the path, and the portal needs it to turn "
                          "markdown into pages")
    if done.returncode != 0:
        raise PortalError("Pandoc stopped with exit %d, %s"
                          % (done.returncode, done.stderr.decode("utf-8", "replace").strip()))
    return done.stdout.decode("utf-8")


def _drop_title(text):
    """The text without its first line when that line is a level-one heading."""
    lines = text.split("\n")
    number = 0
    while number < len(lines) and not lines[number].strip():
        number += 1
    if number < len(lines) and re.match(r"#(\s|$)", lines[number]):
        return "\n".join(lines[number + 1:])
    return text


def _has_image(value):
    if isinstance(value, dict):
        if value.get("t") == "Image":
            return True
        return any(_has_image(part) for part in value.values())
    if isinstance(value, list):
        return any(_has_image(part) for part in value)
    return False


def _as_paragraph(block):
    if isinstance(block, dict) and block.get("t") == "Plain":
        return {"t": "Para", "c": block["c"]}
    return block


def _walk(value, rewrite):
    """Pandoc's JSON tree with each link and image passed through rewrite.

    rewrite(kind, target) gives the new target, or None to turn the link or
    image into its plain text. A figure left with no image becomes its
    paragraphs, so its caption does not repeat the text.
    """
    if isinstance(value, list):
        found = []
        for element in value:
            kind = element.get("t") if isinstance(element, dict) else None
            if kind in ("Link", "Image"):
                attr, inlines, target = element["c"]
                inlines = _walk(inlines, rewrite)
                new = rewrite(kind.lower(), target[0])
                if new is None:
                    found.extend(inlines or [{"t": "Str", "c": posixpath.basename(target[0])}])
                else:
                    found.append({"t": kind, "c": [attr, inlines, [new, target[1]]]})
            elif kind == "Figure":
                parts = _walk(element["c"], rewrite)
                if _has_image(parts[2]):
                    found.append({"t": "Figure", "c": parts})
                else:
                    found.extend(_as_paragraph(block) for block in parts[2])
            else:
                found.append(_walk(element, rewrite))
        return found
    if isinstance(value, dict):
        return dict((key, _walk(part, rewrite)) for key, part in value.items())
    return value


def markdown_to_html(text, rewrite=None):
    """The text as HTML from pandoc --from markdown --to html5.

    A first line that is a level-one heading is dropped, since the page shows
    the title. rewrite, when given, is called for each link and image as in
    _walk. PortalError when Pandoc is missing or fails.
    """
    text = _drop_title(text)
    if rewrite is None:
        return _pandoc(["--from", "markdown", "--to", "html5"], text)
    tree = json.loads(_pandoc(["--from", "markdown", "--to", "json"], text))
    tree["blocks"] = _walk(tree["blocks"], rewrite)
    return _pandoc(["--from", "json", "--to", "html5"], json.dumps(tree))


# Pages.

def _search_box(prefix):
    """The search box, hidden until the script shows it, since it needs the script."""
    return "\n".join([
        '<form class="search" role="search" hidden data-root="%s">' % _escape(prefix),
        '<label for="portal-search">Search the portal</label>',
        '<input type="search" id="portal-search" autocomplete="off">',
        "</form>"])


def _document(title, site, depth, main_html):
    prefix = "../" * depth
    nav = " ".join('<a href="%sindex.html#%s">%s</a>' % (prefix, key, label)
                   for key, label in SECTIONS)
    return "\n".join([
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>%s</title>" % _escape(title),
        '<link rel="stylesheet" href="%s%s">' % (prefix, STYLESHEET),
        "</head>",
        "<body>",
        '<a class="skip" href="#main">Skip to the content</a>',
        '<header class="site-header">',
        '<p class="site-title"><a href="%sindex.html">%s</a></p>' % (prefix, _escape(site.title)),
        '<nav aria-label="Sections">%s</nav>' % nav,
        _search_box(prefix),
        "</header>",
        '<main id="main">',
        main_html,
        "</main>",
        '<script src="%s%s"></script>' % (prefix, SEARCH_INDEX),
        '<script src="%s%s"></script>' % (prefix, SCRIPT),
        "</body>",
        "</html>",
        ""])


def page_html(item, site, body_html, depth):
    """One complete page for an item, depth folders below the site's folder."""
    details = (("Source", item.source), ("Source version", item.source_commit),
               ("Updated", item.updated or "none"), ("Group", item.group),
               ("Origin", item.origin))
    rows = "\n".join("<dt>%s</dt><dd>%s</dd>" % (label, _escape(value))
                     for label, value in details)
    critique = ('<section class="critique" data-page-id="%s" data-title="%s" data-source="%s" '
                'data-source-commit="%s"></section>'
                % (_escape(item.id), _escape(item.title), _escape(item.source),
                   _escape(item.source_commit)))
    main = "\n".join([
        '<article class="item">',
        "<h1>%s</h1>" % _escape(item.title),
        '<dl class="details">\n%s\n</dl>' % rows,
        '<div class="body">',
        body_html.rstrip("\n"),
        "</div>",
        critique,
        "</article>"])
    return _document(item.title, site, depth, main)


def _card(page):
    item = page.item
    return "\n".join([
        '<article class="card">',
        '<h4><a href="%s">%s</a></h4>' % (_escape(page.path), _escape(item.title)),
        '<p class="meta"><span class="kind">%s</span> <span class="group">%s</span></p>'
        % (_escape(item.kind), _escape(item.group)),
        '<p class="gist">%s</p>' % _escape(item.gist),
        "</article>"])


def _section_filter():
    """The buttons that show one section of the catalog, hidden until the script shows them."""
    buttons = [("all", "All")] + list(SECTIONS)
    return "\n".join(
        ['<div class="section-filter" role="group" aria-label="Show one section" hidden>']
        + ['<button type="button" data-section="%s" aria-pressed="%s">%s</button>'
           % (key, "true" if key == "all" else "false", label) for key, label in buttons]
        + ["</div>", '<p class="search-status" aria-live="polite"></p>'])


def catalog_html(site, pages, home_html=None):
    """The catalog, a card per page grouped by section and then by group.

    home_html, the home page's text, opens the catalog when given.
    """
    parts = ["<h1>%s</h1>" % _escape(site.title)]
    if home_html:
        parts.append('<div class="home">\n%s\n</div>' % home_html.rstrip("\n"))
    parts.append(_section_filter())
    for key, label in SECTIONS:
        inside = [page for page in pages if page.section == key]
        parts.append('<section class="section" id="%s">' % key)
        parts.append("<h2>%s</h2>" % label)
        if not inside:
            parts.append('<p class="empty">No pages here yet.</p>')
        groups = collections.OrderedDict()
        for page in sorted(inside, key=lambda page: (page.rank, page.heading)):
            groups.setdefault(page.heading, []).append(page)
        for heading, members in groups.items():
            parts.append('<section class="group">')
            parts.append("<h3>%s</h3>" % _escape(heading))
            parts.append('<div class="cards">')
            parts.extend(_card(page) for page in members)
            parts.append("</div>")
            parts.append("</section>")
        parts.append("</section>")
    return _document(site.title, site, 0, "\n".join(parts))


# Links.

def _rewriter(origin, page_path, origin_pages, warnings):
    """A rewrite function for one page's markdown, as markdown_to_html takes."""
    here = posixpath.dirname(page_path)

    def rewrite(kind, target):
        if kind == "image":
            warnings.append("%s shows the image %s, which is not in the site, so the page "
                            "gives its text instead" % (origin, target))
            return None
        if target.startswith("#") or target.lower().startswith(KEPT_LINKS):
            return target
        path, mark, fragment = target.partition("#")
        page = None
        if path and not SCHEME.match(path) and not path.startswith("/"):
            resolved = posixpath.normpath(posixpath.join(posixpath.dirname(origin), path))
            page = origin_pages.get(resolved)
        if page is None:
            warnings.append("%s links to %s, which is not in the site, so the page gives "
                            "the link's text instead" % (origin, target))
            return None
        return posixpath.relpath(page, here) + mark + fragment

    return rewrite


def _consult_also_ref(rest):
    return rest.split(" " + LONG_DASH + " ")[0].split(" - ")[0].strip().strip("`")


def link_consult_also(markdown, origin, entry_origins, warnings):
    """The entry's markdown with each Consult also id linked to that entry's file.

    The link names the other entry's file from this one, so the page's link
    rewrite then points it at that entry's page. An id with no entry stays
    plain text and gives a warning.
    """
    lines = markdown.split("\n")
    in_section = False
    in_fence = False
    for number, line in enumerate(lines):
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if line.startswith("## "):
            in_section = line.rstrip() == CONSULT_ALSO
            continue
        if not in_section or not line.startswith("- "):
            continue
        rest = line[2:]
        ref = _consult_also_ref(rest)
        if not ref:
            continue
        if ref not in entry_origins:
            warnings.append("%s names %s under Consult also, which has no page, so it stays "
                            "plain text" % (origin, ref))
            continue
        token = "`%s`" % ref if rest.startswith("`%s`" % ref) else ref
        if not rest.startswith(token):
            continue
        link = posixpath.relpath(entry_origins[ref], posixpath.dirname(origin))
        lines[number] = "- [%s](%s)%s" % (token, link, rest[len(token):])
    return "\n".join(lines)


# The site.

def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _file_sha256(path):
    with open(path, "rb") as handle:
        return _sha256(handle.read())


def _inside(path):
    """True when a manifest's page path stays inside the out folder."""
    if not isinstance(path, str) or not path or os.path.isabs(path) or "\\" in path:
        return False
    normal = posixpath.normpath(path)
    return normal != "." and not normal.startswith("../") and normal != ".."


def _earlier_files(out_dir):
    """The files an earlier build in out_dir wrote, or PortalError when out_dir is not one.

    Nothing is removed here, so a refusal leaves the folder as it is.
    """
    if not os.path.exists(out_dir):
        return []
    if not os.path.isdir(out_dir):
        raise PortalError("the out folder %s is a file, not a folder" % out_dir)
    if not os.listdir(out_dir):
        return []
    manifest_path = os.path.join(out_dir, MANIFEST)
    if not os.path.isfile(manifest_path):
        raise PortalError("the out folder %s is not empty and holds no %s, so it is not an "
                          "earlier portal build, and it is left as it is" % (out_dir, MANIFEST))
    try:
        with open(manifest_path, encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise PortalError("%s in %s cannot be read, %s" % (MANIFEST, out_dir, error))
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA \
            or not isinstance(manifest.get("pages"), list):
        raise PortalError("%s in %s is not a portal build's manifest, so the folder is left "
                          "as it is" % (MANIFEST, out_dir))
    found = []
    for page in manifest["pages"]:
        path = page.get("path") if isinstance(page, dict) else None
        if not _inside(path):
            raise PortalError("%s in %s names the page %r, which is not a path inside the "
                              "folder, so nothing is replaced" % (MANIFEST, out_dir, path))
        found.append(posixpath.normpath(path))
    return found + [MANIFEST]


def _remove(out_dir, paths):
    folders = set()
    for path in paths:
        full = os.path.join(out_dir, *path.split("/"))
        if os.path.isfile(full) or os.path.islink(full):
            os.remove(full)
        parent = posixpath.dirname(path)
        while parent:
            folders.add(parent)
            parent = posixpath.dirname(parent)
    for folder in sorted(folders, key=lambda name: name.count("/"), reverse=True):
        full = os.path.join(out_dir, *folder.split("/"))
        if os.path.isdir(full) and not os.listdir(full):
            os.rmdir(full)


def _procedure_item(proc, root):
    """A procedure as an Item, so its page has the same details and critique section.

    Its id is the graph file's stem, which names its page (reconciliation,
    Track F), and its source version is the graph file's checksum in the form
    the docs use.
    """
    stem = posixpath.splitext(posixpath.basename(proc.origin))[0]
    digest = _file_sha256(os.path.join(root, *proc.origin.split("/")))
    return Item(
        kind="procedure", id=stem, title="The %s procedure" % stem,
        group=VERIFICATION_HEADING if proc.verification else OTHER_HEADING,
        source=proc.origin, source_commit="sha256:" + digest[:12], updated=None,
        gist=" ".join((proc.goal or "").split()), markdown="", consult_also=[],
        origin=proc.origin)


def _plan(sources, root):
    """Every page to write, with its section and its group in the catalog.

    Procedures sit under Learn, the four streams as Verification procedures
    and every other graph as Other procedures, then the entries by group,
    then the docs.
    """
    pages = []
    for proc in sources.procedures:
        item = _procedure_item(proc, root)
        pages.append(Page(path="procedures/%s.html" % item.id, item=item, section="learn",
                          heading=item.group, rank=0 if proc.verification else 1, proc=proc))
    for item in sources.items:
        if item.kind == "entry":
            pages.append(Page(path="entries/%s.html" % item.id, item=item, section="learn",
                              heading=item.group, rank=2, proc=None))
        else:
            pages.append(Page(path="docs/%s.html" % item.id, item=item, section=item.group,
                              heading=DOCS_HEADING, rank=3, proc=None))
    seen = {}
    for page in pages:
        if page.path in seen:
            raise PortalError("%s and %s would both be the page %s"
                              % (seen[page.path], page.item.origin, page.path))
        seen[page.path] = page.item.origin
    return pages


def search_index_js(pages):
    """search_index.js, one row per item page, as a script so the site works from disk.

    Each row holds the page's id, title, kind, group, section, gist, and url
    from the site's folder. The JSON is ASCII, so no character can end the
    script's text.
    """
    rows = [collections.OrderedDict([
        ("id", page.item.id), ("title", page.item.title), ("kind", page.item.kind),
        ("group", page.item.group), ("section", page.section), ("gist", page.item.gist),
        ("url", page.path)]) for page in pages]
    return SEARCH_INDEX_PREFIX + json.dumps(rows, ensure_ascii=True, indent=1) + ";\n"


def write_site(sources, out_dir, now, root=None):
    """Write the site for the sources into out_dir, as SiteResult(pages, warnings).

    pages lists the HTML pages written, from the site's folder. warnings holds
    the sources' warnings and each link or image the site could not keep.
    Every page is made before the folder is touched, so a failure leaves an
    earlier build as it was.
    """
    root = str(root or default_root())
    out_dir = os.path.abspath(str(out_dir))
    earlier = _earlier_files(out_dir)
    site = Site(title=getattr(sources, "title", None) or "The portal")
    warnings = list(sources.warnings)
    pages = _plan(sources, root)
    origin_pages = dict((page.item.origin, page.path) for page in pages)
    entry_origins = dict((page.item.id, page.item.origin) for page in pages
                         if page.item.kind == "entry")
    home = getattr(sources, "home", None)
    if home is not None:
        origin_pages[home.origin] = "index.html"
    written = collections.OrderedDict()
    home_html = None
    if home is not None:
        home_html = markdown_to_html(home.markdown, _rewriter(home.origin, "index.html",
                                                              origin_pages, warnings))
    written["index.html"] = (catalog_html(site, pages, home_html).encode("utf-8"), None)
    for page in pages:
        item = page.item
        if page.proc is not None:
            body = procedure_pages.procedure_body(page.proc)
        else:
            markdown = item.markdown
            if item.kind == "entry":
                markdown = link_consult_also(markdown, item.origin, entry_origins, warnings)
            body = markdown_to_html(markdown, _rewriter(item.origin, page.path, origin_pages,
                                                        warnings))
        text = page_html(item, site, body, page.path.count("/"))
        written[page.path] = (text.encode("utf-8"), item.origin)
    written[SEARCH_INDEX] = (search_index_js(pages).encode("utf-8"), None)
    with open(os.path.join(ASSETS, "portal.css"), "rb") as handle:
        written[STYLESHEET] = (handle.read(), STYLESHEET_ORIGIN)
    with open(os.path.join(ASSETS, "portal.js"), "rb") as handle:
        written[SCRIPT] = (handle.read(), SCRIPT_ORIGIN)

    _remove(out_dir, earlier)
    listed = []
    for path, (data, origin) in written.items():
        full = os.path.join(out_dir, *path.split("/"))
        if not os.path.isdir(os.path.dirname(full)):
            os.makedirs(os.path.dirname(full))
        with open(full, "wb") as handle:
            handle.write(data)
        listed.append(collections.OrderedDict(
            [("path", path), ("origin", origin), ("sha256", _sha256(data))]))
    origins = sorted(set([page.item.origin for page in pages]
                         + ([home.origin] if home is not None else [])))
    manifest = collections.OrderedDict([
        ("schema", SCHEMA),
        ("schema_version", SCHEMA_VERSION),
        ("built_at", now.isoformat(timespec="seconds")),
        ("pages", listed),
        ("sources", [collections.OrderedDict(
            [("origin", origin), ("sha256", _file_sha256(os.path.join(root, origin)))])
            for origin in origins]),
    ])
    with open(os.path.join(out_dir, MANIFEST), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    pages_written = [path for path in written if path.endswith(".html")]
    return SiteResult(pages=pages_written, warnings=warnings)



# The command, python3 -m features portal build (step F15).

def add_command(commands):
    parser = commands.add_parser(
        "build", help="build the portal's static site",
        description="Build the portal from the sources its config names into a folder that"
        " opens from disk with no server or network.")
    parser.add_argument("--config", metavar="FILE",
                        help="the portal's config, else " + DEFAULT_CONFIG)
    parser.add_argument("--out", metavar="DIR",
                        help="the site's folder, else " + DEFAULT_OUT + "/")
    parser.set_defaults(run=build_command)


def build_command(options, out=None, err=None, now=None):
    """Build the site, print the page count, each warning, and the catalog's path.

    It exits 1 when a source or the out folder is refused, and 0 otherwise.
    """
    out = out or sys.stdout
    err = err or sys.stderr
    now = now or datetime.datetime.now(datetime.timezone.utc)
    root = default_root()
    config = os.path.abspath(os.path.expanduser(options.config)) if options.config \
        else os.path.join(root, *DEFAULT_CONFIG.split("/"))
    target = os.path.abspath(os.path.expanduser(options.out)) if options.out \
        else os.path.join(root, *DEFAULT_OUT.split("/"))
    try:
        found = load_all(config, root)
        result = write_site(found, target, now, root=root)
    except PortalError as error:
        err.write("The portal was not built. %s\n" % error)
        return 1
    out.write("Wrote %d pages to %s\n" % (len(result.pages), target))
    for warning in result.warnings:
        out.write("Warning. %s\n" % warning)
    out.write("Open %s\n" % os.path.join(target, "index.html"))
    return 0
