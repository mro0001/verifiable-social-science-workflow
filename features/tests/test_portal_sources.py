"""Step F12. The portal's sources.

The fixture features/tests/fixtures/portal/ holds two entries in two groups
with one consult-also line, one graph with its contract and two step files,
two docs (the second added in step F13 for the doc links), and its own
portal.yaml. The real tree's portal.yaml names the
knowledge base corpus, the graphs folder, and the documentation files, with
the optional learn pages the reconciliation (Track F) names.

Run from the repository root as python3 -m pytest -q features/tests.
"""
import glob
import hashlib
import os
import shutil

import pytest
import yaml

from features.portal import sources
from features.portal.sources import PortalError
from features.tests import helpers

ROOT = helpers.ROOT
FIXTURE = helpers.FIXTURES / "portal"
CONFIG = ROOT / "features" / "portal" / "portal.yaml"
CORPUS = ROOT / "audit_layer" / "kb" / "corpus"
GRAPHS = ROOT / "verification_procedures" / "graphs"
STREAMS = ("prose", "citations", "data", "build")

REQUIRED_DOCS = [
    ("verification_procedures/README.md", "learn"),
    ("features/portal/pages/implement.md", "implement"),
    ("examples/sample_project/README.md", "implement"),
    ("features/setup/GUIDE.md", "implement"),
    ("features/organizer/GUIDE.md", "implement"),
    ("features/portal/pages/critique.md", "critique"),
]
OPTIONAL_DOCS = [
    "verification_procedures/AUTHORING.md",
    "audit_layer/hooks/INSTALL.md",
    "observability/CONTRACT.md",
    "handoffs/README.md",
    "connections/README.md",
]


@pytest.fixture
def fixture(tmp_path):
    """A copy of the portal fixture, so a test may break it."""
    folder = tmp_path / "portal"
    shutil.copytree(str(FIXTURE), str(folder))
    return folder


def by_id(items):
    return dict((item.id, item) for item in items)


# The fixture's entries.

def test_the_fixture_entries_load_with_their_parts():
    entries = by_id(sources.load_entries(str(FIXTURE / "kb"), str(FIXTURE)))
    assert sorted(entries) == ["alpha-first", "beta-second"]
    first = entries["alpha-first"]
    assert first.title == "The first entry"
    assert first.group == "ALPHA"
    assert first.source == "docs/guide.md"
    assert first.source_commit == "sha256:0123456789ab"
    assert first.updated == "2026-10-01"
    assert first.gist == "The first entry's short answer, written over two lines."
    assert first.consult_also == ["beta-second"]
    assert first.origin == "kb/alpha/alpha-first.md"
    assert first.markdown.startswith("# The first entry\n")
    assert "---" not in first.markdown.splitlines()[0]
    second = entries["beta-second"]
    assert second.group == "BETA"
    assert second.gist == "The second entry's short answer."
    assert second.consult_also == []


def test_a_consult_also_line_with_a_long_dash_or_backticks_gives_its_id(fixture):
    path = fixture / "kb" / "alpha" / "alpha-first.md"
    text = path.read_text(encoding="utf-8").replace(
        "- beta-second - for the second entry.",
        "- `beta-second` \u2014 for the second entry.\n- alpha-first - itself.")
    path.write_text(text, encoding="utf-8")
    entries = by_id(sources.load_entries(str(fixture / "kb"), str(fixture)))
    assert entries["alpha-first"].consult_also == ["beta-second", "alpha-first"]


def test_an_entry_without_its_heading_raises_naming_it(fixture):
    path = fixture / "kb" / "beta" / "beta-second.md"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.split("---\n", 2)[2], encoding="utf-8")
    with pytest.raises(PortalError) as raised:
        sources.load_entries(str(fixture / "kb"), str(fixture))
    assert "kb/beta/beta-second.md" in str(raised.value)


def test_an_entry_whose_heading_is_not_closed_raises_naming_it(fixture):
    path = fixture / "kb" / "beta" / "beta-second.md"
    path.write_text("---\nid: beta-second\ntitle: The second entry\n", encoding="utf-8")
    with pytest.raises(PortalError) as raised:
        sources.load_entries(str(fixture / "kb"), str(fixture))
    assert "kb/beta/beta-second.md" in str(raised.value)


@pytest.mark.parametrize("key", ["id", "title", "source", "source_commit", "updated", "group"])
def test_an_entry_missing_a_heading_key_raises_naming_it_and_the_key(fixture, key):
    path = fixture / "kb" / "alpha" / "alpha-first.md"
    lines = [line for line in path.read_text(encoding="utf-8").splitlines(True)
             if not line.startswith(key + ":")]
    path.write_text("".join(lines), encoding="utf-8")
    with pytest.raises(PortalError) as raised:
        sources.load_entries(str(fixture / "kb"), str(fixture))
    assert "kb/alpha/alpha-first.md" in str(raised.value)
    assert key in str(raised.value)


# The fixture's graph.

def test_the_fixture_graph_gives_every_node_and_edge():
    found = sources.load_procedures(str(FIXTURE / "procedures" / "graphs"), str(FIXTURE))
    assert len(found) == 1
    proc = found[0]
    assert proc.stream == "demo"
    assert proc.version == "0.1"
    assert proc.goal == "Show the portal a small graph."
    assert (proc.entry, proc.exit) == ("first", "last")
    assert proc.verification is False
    assert [node["id"] for node in proc.nodes] == ["first", "judge", "last"]
    first, judge, last = proc.nodes
    assert first["kind"] == "tool" and first["does"] == "List the items."
    assert first["invariant"] == "Every item has an id."
    assert first["foreach"] is None and first["role"] is None
    assert judge["foreach"] == "items.json" and judge["role"] == "judge"
    assert last["where"] == "report.md" and last["replay"] is True
    assert [(edge["from"], edge["to"], edge["rel"]) for edge in proc.edges] == [
        ("first", "judge", "LEADS_TO"), ("judge", "last", "CONVERGES_TO")]
    one, two = proc.edges
    assert one["condition"] == "Always."
    assert one["guidance"] == "One ask per item."
    assert one["pitfalls"] == ["Judging all items in one ask."]
    assert one["source"] == "proposed"
    assert one["check"] is None
    assert two["check"] == "count.json:n > 0"
    assert two["pitfalls"] == ["Dropping an answer.", "Mixing < and & in a message."]


def test_unknown_node_and_edge_keys_land_in_extra():
    proc = sources.load_procedures(str(FIXTURE / "procedures" / "graphs"), str(FIXTURE))[0]
    assert proc.nodes[0]["extra"] == {"note": "A key the portal does not know."}
    assert proc.nodes[1]["extra"] == {}
    assert proc.edges[1]["extra"] == {"weight": 2}
    assert proc.edges[0]["extra"] == {}


def test_each_step_has_its_contract_files_and_its_implementation_files():
    proc = sources.load_procedures(str(FIXTURE / "procedures" / "graphs"), str(FIXTURE))[0]
    first, judge, last = proc.nodes
    assert first["reads"] == ["items.txt"] and first["produces"] == ["items.json"]
    assert first["reads_optional"] == []
    assert judge["reads"] == ["items.json"] and judge["produces"] == ["judge.json"]
    assert last["reads"] == ["judge.json"]
    assert last["reads_optional"] == ["findings_*.json"]
    assert last["produces"] == ["report.md"]
    assert first["implementations"] == ["procedures/implementations/demo/first.py"]
    assert judge["implementations"] == ["procedures/implementations/demo/judge.prompt.md"]
    assert last["implementations"] == []


def test_a_graph_with_no_stream_takes_its_file_name(fixture):
    path = fixture / "procedures" / "graphs" / "demo.yaml"
    text = path.read_text(encoding="utf-8").replace("stream: demo\n", "")
    (fixture / "procedures" / "graphs" / "nameless.yaml").write_text(text, encoding="utf-8")
    path.unlink()
    proc = sources.load_procedures(str(fixture / "procedures" / "graphs"), str(fixture))[0]
    assert proc.stream == "nameless"


def test_a_graph_that_is_not_a_mapping_raises_naming_it(fixture):
    path = fixture / "procedures" / "graphs" / "demo.yaml"
    path.write_text("- just\n- a list\n", encoding="utf-8")
    with pytest.raises(PortalError) as raised:
        sources.load_procedures(str(fixture / "procedures" / "graphs"), str(fixture))
    assert "procedures/graphs/demo.yaml" in str(raised.value)


def test_a_missing_contracts_file_raises_naming_it(fixture):
    (fixture / "procedures" / "contracts" / "demo.yaml").unlink()
    with pytest.raises(PortalError) as raised:
        sources.load_procedures(str(fixture / "procedures" / "graphs"), str(fixture))
    assert "contracts/demo.yaml" in str(raised.value)


# The fixture's doc and the whole fixture.

def test_the_fixture_doc_loads_with_its_title_section_and_gist():
    docs = [{"path": "docs/guide.md", "title": "The fixture guide", "section": "implement",
             "optional": False}]
    warnings = []
    items = sources.load_docs(str(FIXTURE), docs, warnings)
    assert warnings == []
    assert len(items) == 1
    doc = items[0]
    assert doc.id == "docs-guide"
    assert doc.title == "The fixture guide"
    assert doc.group == "implement"
    assert doc.source == "docs/guide.md"
    assert doc.origin == "docs/guide.md"
    digest = hashlib.sha256((FIXTURE / "docs" / "guide.md").read_bytes()).hexdigest()
    assert doc.source_commit == "sha256:" + digest[:12]
    assert doc.updated is None
    assert doc.gist == "The fixture guide's first paragraph."
    assert doc.consult_also == []
    assert doc.markdown.startswith("# The fixture guide\n")


def test_load_all_gives_the_fixtures_items_and_procedures():
    found = sources.load_all(str(FIXTURE / "portal.yaml"), str(FIXTURE))
    assert sorted(item.id for item in found.items) == ["alpha-first", "beta-second", "docs-guide",
                                                         "docs-more"]
    assert [proc.stream for proc in found.procedures] == ["demo"]
    assert found.warnings == []


def test_a_missing_optional_doc_warns(fixture):
    config = yaml.safe_load((fixture / "portal.yaml").read_text(encoding="utf-8"))
    config["docs"].append({"path": "docs/absent.md", "title": "Absent", "section": "learn",
                           "optional": True})
    (fixture / "portal.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    found = sources.load_all(str(fixture / "portal.yaml"), str(fixture))
    assert len(found.warnings) == 1
    assert "docs/absent.md" in found.warnings[0]
    assert "docs-guide" in [item.id for item in found.items]


def test_a_missing_required_doc_fails(fixture):
    (fixture / "docs" / "guide.md").unlink()
    with pytest.raises(PortalError) as raised:
        sources.load_all(str(fixture / "portal.yaml"), str(fixture))
    assert "docs/guide.md" in str(raised.value)


@pytest.mark.parametrize("change", [
    {"section": "elsewhere"},
    {"title": ""},
    {"path": ""},
    {"optional": "yes"},
    {"path": "../outside.md"},
])
def test_a_bad_doc_line_is_refused(fixture, change):
    config = yaml.safe_load((fixture / "portal.yaml").read_text(encoding="utf-8"))
    config["docs"][0].update(change)
    (fixture / "portal.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    with pytest.raises(PortalError):
        sources.load_all(str(fixture / "portal.yaml"), str(fixture))


@pytest.mark.parametrize("key", ["title", "kb_corpus", "graphs", "docs"])
def test_a_config_missing_a_key_is_refused_naming_it(fixture, key):
    config = yaml.safe_load((fixture / "portal.yaml").read_text(encoding="utf-8"))
    del config[key]
    (fixture / "portal.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    with pytest.raises(PortalError) as raised:
        sources.load_all(str(fixture / "portal.yaml"), str(fixture))
    assert key in str(raised.value)


def test_a_missing_config_is_refused_naming_it(tmp_path):
    with pytest.raises(PortalError) as raised:
        sources.load_all(str(tmp_path / "portal.yaml"), str(tmp_path))
    assert "portal.yaml" in str(raised.value)


def test_a_missing_corpus_or_graphs_folder_is_refused(fixture):
    shutil.rmtree(str(fixture / "kb"))
    with pytest.raises(PortalError) as raised:
        sources.load_all(str(fixture / "portal.yaml"), str(fixture))
    assert "kb" in str(raised.value)


# The real tree.

def real_config():
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def test_the_real_portal_yaml_names_its_title_sources_and_docs():
    config = real_config()
    assert config["title"] == "An AI-Enhanced Workflow for Verifiable Social Science"
    assert config["kb_corpus"] == "audit_layer/kb/corpus"
    assert config["graphs"] == "verification_procedures/graphs"
    docs = config["docs"]
    required = [(doc["path"], doc["section"]) for doc in docs if not doc["optional"]]
    assert required == REQUIRED_DOCS
    optional = [doc for doc in docs if doc["optional"]]
    assert [doc["path"] for doc in optional] == OPTIONAL_DOCS
    assert all(doc["section"] == "learn" for doc in optional)
    assert all(doc["title"].strip() for doc in docs)
    for name in ("ospipe/README.md", "audit_layer/README.md", "observability/README.md",
                 "notes/", "recon/", "CLAUDE.md"):
        assert all(not doc["path"].startswith(name) for doc in docs), name


def test_the_real_tree_loads_every_entry_and_every_graph():
    found = sources.load_all(str(CONFIG), str(ROOT))
    entry_files = sorted(glob.glob(str(CORPUS / "*" / "*.md")))
    entries = [item for item in found.items if item.origin.startswith("audit_layer/kb/corpus/")]
    assert len(entries) == len(entry_files)
    assert sorted(os.path.join(str(ROOT), item.origin) for item in entries) == entry_files
    ids = set(item.id for item in entries)
    for item in entries:
        assert item.title and item.group and item.gist, item.origin
        assert set(item.consult_also) <= ids, item.origin
    assert len(found.procedures) == len(glob.glob(str(GRAPHS / "*.yaml")))
    for proc in found.procedures:
        assert proc.nodes and proc.edges, proc.stream


def test_the_four_streams_are_marked_verification_and_no_other():
    found = sources.load_all(str(CONFIG), str(ROOT))
    marked = sorted(proc.stream for proc in found.procedures if proc.verification)
    assert marked == sorted(STREAMS)


def test_the_real_tree_has_each_required_doc_and_warns_only_for_absent_optional_ones():
    found = sources.load_all(str(CONFIG), str(ROOT))
    origins = [item.origin for item in found.items]
    for path, _ in REQUIRED_DOCS:
        assert path in origins, path
    absent = [path for path in OPTIONAL_DOCS if not (ROOT / path).is_file()]
    assert len(found.warnings) == len(absent)
    for path in absent:
        assert any(path in warning for warning in found.warnings), path
    for path in OPTIONAL_DOCS:
        if (ROOT / path).is_file():
            assert path in origins, path
