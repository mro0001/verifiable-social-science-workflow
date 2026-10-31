"""Step F14. Procedure pages.

The fixture graph, features/tests/fixtures/portal/procedures/graphs/demo.yaml,
gives a page whose steps, edges, contract files, and implementation files are
checked here. For each real graph in verification_procedures/graphs, the
page's step and edge counts equal the graph file's. Pages are named by the
graph file's stem (reconciliation, Track F).

Run from the repository root as python3 -m pytest -q features/tests.
"""
import datetime
import glob
import os
import shutil

import pytest
import yaml

from features.portal import procedures, render, sources
from features.tests import helpers

ROOT = helpers.ROOT
FIXTURE = helpers.FIXTURES / "portal"
GRAPHS = ROOT / "verification_procedures" / "graphs"
CONFIG = ROOT / "features" / "portal" / "portal.yaml"
STREAMS = ("prose", "citations", "data", "build")
NOW = datetime.datetime(2026, 10, 29, 9, 30, 0, tzinfo=datetime.timezone.utc)
STEP = '<li class="step"'
EDGE = '<details class="edge"'


def fixture_procedure(folder=FIXTURE):
    return sources.load_procedures(str(folder / "procedures" / "graphs"), str(folder))[0]


def step_chunks(body):
    """Each step's part of the body, by step id, in page order."""
    chunks = []
    for part in body.split(STEP)[1:]:
        step_id = part.split('id="step-', 1)[1].split('"', 1)[0]
        chunks.append((step_id, part.split("</li>\n</ol>", 1)[0]))
    return chunks


@pytest.fixture
def fixture(tmp_path):
    folder = tmp_path / "portal"
    shutil.copytree(str(FIXTURE), str(folder))
    return folder


# The fixture graph's page.

def test_the_body_gives_the_stream_version_goal_and_first_and_last_steps():
    body = procedures.procedure_body(fixture_procedure())
    summary = body.split(STEP, 1)[0]
    for label, value in (("Stream", "demo"), ("Version", "0.1"),
                         ("Goal", "Show the portal a small graph."),
                         ("First step", "first"), ("Last step", "last")):
        assert ">%s</dt>" % label in summary, label
        assert value in summary, value


def test_every_step_is_listed_in_file_order_with_its_parts():
    body = procedures.procedure_body(fixture_procedure())
    chunks = dict(step_chunks(body))
    assert [step for step, _ in step_chunks(body)] == ["first", "judge", "last"]
    assert body.count(STEP) == 3
    assert "tool" in chunks["first"] and "List the items." in chunks["first"]
    assert "Every item has an id." in chunks["first"]
    assert "judgment" in chunks["judge"] and "Judge each item." in chunks["judge"]
    assert ">For each</dt>" in chunks["judge"] and "items.json" in chunks["judge"]
    assert ">Role</dt>" in chunks["judge"] and ">judge</dd>" in chunks["judge"]
    assert ">Where</dt>" in chunks["last"] and "report.md" in chunks["last"]
    for absent in (">For each</dt>", ">Where</dt>", ">Role</dt>"):
        assert absent not in chunks["first"], absent


def test_every_edge_sits_under_its_source_step_with_its_parts():
    body = procedures.procedure_body(fixture_procedure())
    chunks = dict(step_chunks(body))
    assert body.count(EDGE) == 2
    first = chunks["first"]
    assert first.count(EDGE) == 1
    edge = first.split(EDGE, 1)[1].split("</details>", 1)[0]
    for value in ("judge", "LEADS_TO", "Always.", "One ask per item.",
                  "Judging all items in one ask.", "proposed"):
        assert value in edge, value
    for label in ("Next step", "Relation", "Condition", "Guidance", "Pitfalls", "Source"):
        assert ">%s</dt>" % label in edge, label
    assert ">Check</dt>" not in edge
    judge = chunks["judge"]
    assert judge.count(EDGE) == 1
    edge = judge.split(EDGE, 1)[1].split("</details>", 1)[0]
    for value in ("last", "CONVERGES_TO", "At least one item.", "Report each verdict.",
                  "Dropping an answer.", "proposed", "count.json:n &gt; 0"):
        assert value in edge, value
    assert edge.count("<li>") == 2
    assert ">Check</dt>" in edge
    assert EDGE not in chunks["last"]


def test_each_step_lists_its_contract_files_and_its_implementation_files():
    chunks = dict(step_chunks(procedures.procedure_body(fixture_procedure())))
    assert "items.txt" in chunks["first"] and "items.json" in chunks["first"]
    assert "procedures/implementations/demo/first.py" in chunks["first"]
    assert "judge.json" in chunks["judge"]
    assert "procedures/implementations/demo/judge.prompt.md" in chunks["judge"]
    assert "judge.json" in chunks["last"] and "findings_*.json" in chunks["last"]
    assert ">Reads when present</dt>" in chunks["last"]
    assert ">Reads when present</dt>" not in chunks["first"]
    for label in ("Reads", "Produces", "Implementation"):
        assert ">%s</dt>" % label in chunks["last"], label


def test_graph_text_is_escaped(fixture):
    body = procedures.procedure_body(fixture_procedure())
    assert "Mixing &lt; and &amp; in a message." in body
    assert "Mixing < and &" not in body
    path = fixture / "procedures" / "graphs" / "demo.yaml"
    text = path.read_text(encoding="utf-8").replace(
        "does: List the items.", 'does: "List <b>all</b> the items & more."')
    path.write_text(text, encoding="utf-8")
    body = procedures.procedure_body(fixture_procedure(fixture))
    assert "List &lt;b&gt;all&lt;/b&gt; the items &amp; more." in body
    assert "<b>" not in body


def test_an_edge_from_no_listed_step_is_still_shown(fixture):
    path = fixture / "procedures" / "graphs" / "demo.yaml"
    graph = yaml.safe_load(path.read_text(encoding="utf-8"))
    graph["edges"].append({"from": "nowhere", "rel": "LEADS_TO", "to": "last",
                           "condition": "Never.", "guidance": "None.", "pitfalls": [],
                           "source": "proposed"})
    path.write_text(yaml.safe_dump(graph, sort_keys=False), encoding="utf-8")
    body = procedures.procedure_body(fixture_procedure(fixture))
    assert body.count(EDGE) == 3
    assert "nowhere" in body and "Never." in body


# Procedure pages in the site.

def test_the_site_has_a_page_per_graph_named_by_its_stem(fixture, tmp_path):
    graphs = fixture / "procedures" / "graphs"
    (graphs / "demo.yaml").rename(graphs / "demo_graph.yaml")
    found = sources.load_all(str(fixture / "portal.yaml"), str(fixture))
    out = tmp_path / "site"
    result = render.write_site(found, str(out), NOW, root=str(fixture))
    assert "procedures/demo_graph.html" in result.pages
    text = (out / "procedures" / "demo_graph.html").read_text(encoding="utf-8")
    assert text.count(STEP) == 3 and text.count(EDGE) == 2
    assert '<section class="critique" data-page-id="demo_graph"' in text
    assert "procedures/graphs/demo_graph.yaml" in text
    assert '<link rel="stylesheet" href="../assets/portal.css">' in text
    cards = helpers.parse_site_page(out / "index.html").cards
    assert ("Learn", "Other procedures", "procedures/demo_graph.html") in cards


def test_a_verification_stream_card_sits_under_verification_procedures(fixture, tmp_path):
    path = fixture / "procedures" / "graphs" / "demo.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace("stream: demo", "stream: data"),
                    encoding="utf-8")
    found = sources.load_all(str(fixture / "portal.yaml"), str(fixture))
    out = tmp_path / "site"
    render.write_site(found, str(out), NOW, root=str(fixture))
    cards = helpers.parse_site_page(out / "index.html").cards
    assert ("Learn", "Verification procedures", "procedures/demo.html") in cards


def test_a_doc_link_to_a_graph_file_points_at_its_procedure_page(fixture, tmp_path):
    guide = fixture / "docs" / "guide.md"
    guide.write_text(guide.read_text(encoding="utf-8")
                     + "\nThe [demo graph](../procedures/graphs/demo.yaml).\n", encoding="utf-8")
    found = sources.load_all(str(fixture / "portal.yaml"), str(fixture))
    out = tmp_path / "site"
    render.write_site(found, str(out), NOW, root=str(fixture))
    text = (out / "docs" / "docs-guide.html").read_text(encoding="utf-8")
    assert 'href="../procedures/demo.html"' in text


# The real graphs.

@pytest.mark.parametrize("path", sorted(glob.glob(str(GRAPHS / "*.yaml"))),
                         ids=lambda path: os.path.basename(path))
def test_each_real_graphs_page_has_its_step_and_edge_counts(path):
    graph = yaml.safe_load(open(path, encoding="utf-8").read())
    proc = sources.load_procedure(path, str(ROOT))
    body = procedures.procedure_body(proc)
    assert body.count(STEP) == len(graph["nodes"])
    assert body.count(EDGE) == len(graph["edges"])
    assert [step for step, _ in step_chunks(body)] == [node["id"] for node in graph["nodes"]]


@pytest.fixture(scope="module")
def real_site(tmp_path_factory):
    out = tmp_path_factory.mktemp("real") / "site"
    found = sources.load_all(str(CONFIG), str(ROOT))
    result = render.write_site(found, str(out), NOW, root=str(ROOT))
    return out, result


def test_the_real_sites_four_streams_sit_under_verification_procedures(real_site):
    out, result = real_site
    cards = helpers.parse_site_page(out / "index.html").cards
    stems = [os.path.splitext(os.path.basename(path))[0]
             for path in glob.glob(str(GRAPHS / "*.yaml"))]
    verification = sorted(href for h2, h3, href in cards
                          if (h2, h3) == ("Learn", "Verification procedures"))
    other = sorted(href for h2, h3, href in cards if (h2, h3) == ("Learn", "Other procedures"))
    assert verification == sorted("procedures/%s.html" % stream for stream in STREAMS)
    assert other == sorted("procedures/%s.html" % stem for stem in stems
                           if stem not in STREAMS)
    assert "procedures/ops_github.html" in other and "procedures/ops_hpc.html" in other
    for stem in stems:
        assert "procedures/%s.html" % stem in result.pages


def test_every_link_in_the_real_site_resolves(real_site):
    out, _ = real_site
    files = set(helpers.site_files(out))
    for page in [name for name in files if name.endswith(".html")]:
        folder = os.path.dirname(page)
        for tag, attribute, value in helpers.parse_site_page(out / page).links:
            if helpers.is_outside_link(value):
                continue
            target = os.path.normpath(os.path.join(folder, value.split("#")[0]))
            assert target.replace(os.sep, "/") in files, (page, tag, attribute, value)
