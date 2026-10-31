"""The portal's sources (step F12).

The portal is built from what features/portal/portal.yaml names, the
knowledge base corpus, the procedural graphs folder, and a list of
documentation files, so private folders such as notes/ and recon/ never enter
the site. This module reads those sources and writes nothing.

- load_entries reads each knowledge base entry, <group>/<id>.md, by its
  heading of six keys between two lines of three hyphens (appendix A2.4
  "Knowledge base"). The entry checker owns the entries' form, so an entry
  that does not parse raises PortalError naming the file.
- load_procedures reads each graph with its steps, edges, step contracts, and
  the implementation files that exist for each step (A2.4 "Procedural
  graphs").
- load_docs reads the listed documentation files.
- load_home reads the home page's markdown, whose text opens the catalog
  (step F15).

The features never import another layer's code, so the entries and graphs are
read here as files.
"""
import collections
import glob
import hashlib
import os
import re

import yaml

from features.layers import default_root

ENTRY_KEYS = ("id", "title", "source", "source_commit", "updated", "group")
CONFIG_KEYS = ("title", "kb_corpus", "graphs", "docs")
# home is optional, the markdown whose text opens the catalog (step F15).
HOME_KEY = "home"
DOC_KEYS = ("path", "title", "section", "optional")
SECTIONS = ("learn", "implement", "critique")
VERIFICATION_STREAMS = ("prose", "citations", "data", "build")
NODE_KEYS = ("id", "kind", "does", "invariant", "foreach", "where", "role", "replay")
EDGE_KEYS = ("from", "to", "rel", "condition", "guidance", "pitfalls", "source", "check")
CONTRACT_KEYS = ("reads", "reads_optional", "produces")
IMPLEMENTATION_ENDINGS = (".py", ".prompt.md")
FENCE = "---"
CONSULT_ALSO = "## Consult also"
LONG_DASH = "\u2014"

# kind is entry or doc (step F13, the catalog shows each card's kind).
Item = collections.namedtuple(
    "Item", "kind id title group source source_commit updated gist markdown consult_also origin")
# origin is the graph file's path from the root, since step F14 names each
# procedure page by the file's stem (reconciliation, Track F).
Procedure = collections.namedtuple(
    "Procedure", "stream version goal entry exit nodes edges verification origin")
# title is the config's title, which the site shows (step F13), and home is
# the home page's Item, or None when the config names none (step F15).
PortalSources = collections.namedtuple("PortalSources", "items procedures warnings title home")
PortalSources.__new__.__defaults__ = (None, None)


class PortalError(Exception):
    """A portal source that is missing or cannot be read."""


def _origin(path, root):
    """The path from the root, with forward slashes."""
    return os.path.relpath(os.path.abspath(str(path)), os.path.abspath(str(root))).replace(
        os.sep, "/")


def _read_text(path, root):
    try:
        with open(str(path), encoding="utf-8") as handle:
            return handle.read()
    except (OSError, UnicodeDecodeError) as error:
        raise PortalError("%s cannot be read, %s" % (_origin(path, root), error))


def _blocks(body):
    """The body as paragraphs, each a list of lines. A heading is a paragraph of its own."""
    found = []
    current = []
    for line in body.splitlines():
        if not line.strip():
            if current:
                found.append(current)
                current = []
        elif line.startswith("#"):
            if current:
                found.append(current)
                current = []
            found.append([line])
        else:
            current.append(line)
    if current:
        found.append(current)
    return found


def gist_of(body):
    """The first paragraph that is not a heading, its lines joined by spaces."""
    for block in _blocks(body):
        if not block[0].startswith("#"):
            return " ".join(line.strip() for line in block)
    return ""


def _prose_lines(text):
    """The lines of the text outside code fences."""
    inside = False
    for line in text.splitlines():
        if line.lstrip().startswith("```") or line.lstrip().startswith("~~~"):
            inside = not inside
            continue
        if not inside:
            yield line


def consult_also_of(body):
    """The ids the Consult also section names, in order."""
    found = []
    in_section = False
    for line in _prose_lines(body):
        if line.startswith("## "):
            in_section = line.rstrip() == CONSULT_ALSO
            continue
        if in_section and line.startswith("- "):
            ref = line[2:].split(" " + LONG_DASH + " ")[0].split(" - ")[0].strip().strip("`")
            if ref:
                found.append(ref)
    return found


def _heading(text, where):
    """The heading's keys and the body after it, or PortalError naming the file."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != FENCE:
        raise PortalError("%s has no heading, the six keys between two lines of three hyphens"
                          % where)
    closing = None
    for number in range(1, len(lines)):
        if lines[number].strip() == FENCE:
            closing = number
            break
    if closing is None:
        raise PortalError("%s has a heading that is not closed" % where)
    front = {}
    for line in lines[1:closing]:
        if not line.strip():
            continue
        key, _, value = line.partition(":")
        front[key.strip()] = value.strip().strip("'\"")
    missing = [key for key in ENTRY_KEYS if not front.get(key)]
    if missing:
        raise PortalError("%s has no %s in its heading" % (where, ", ".join(missing)))
    return front, "\n".join(lines[closing + 1:]).strip()


def load_entries(corpus_dir, root=None):
    """Each knowledge base entry, <group>/<id>.md, as an Item, in file order."""
    root = str(root or default_root())
    items = []
    for path in sorted(glob.glob(os.path.join(str(corpus_dir), "*", "*.md"))):
        where = _origin(path, root)
        front, body = _heading(_read_text(path, root), where)
        items.append(Item(
            kind="entry", id=front["id"], title=front["title"], group=front["group"], source=front["source"],
            source_commit=front["source_commit"], updated=front["updated"],
            gist=gist_of(body), markdown=body + "\n", consult_also=consult_also_of(body),
            origin=where))
    return items


def _load_yaml(path, root):
    try:
        return yaml.safe_load(_read_text(path, root))
    except yaml.YAMLError as error:
        raise PortalError("%s is not YAML, %s" % (_origin(path, root), error))


def _text(value):
    return None if value is None else str(value)


def _file_names(value):
    """The file names a contract lists, from a list or the keys of a mapping."""
    if isinstance(value, dict):
        return [str(name) for name in value]
    if isinstance(value, list):
        return [str(name) for name in value]
    return []


def _implementations(home, stream, node_id, root):
    found = []
    for ending in IMPLEMENTATION_ENDINGS:
        path = os.path.join(home, "implementations", stream, node_id + ending)
        if os.path.isfile(path):
            found.append(_origin(path, root))
    return found


def _node(raw, contract, home, stream, where, root):
    if not isinstance(raw, dict) or not raw.get("id"):
        raise PortalError("%s has a step that is not a mapping with an id" % where)
    node = dict((key, raw.get(key)) for key in NODE_KEYS)
    node["id"] = str(node["id"])
    step = contract.get(node["id"]) if isinstance(contract, dict) else None
    step = step if isinstance(step, dict) else {}
    for key in CONTRACT_KEYS:
        node[key] = _file_names(step.get(key))
    node["implementations"] = _implementations(home, stream, node["id"], root)
    node["extra"] = dict((key, value) for key, value in raw.items() if key not in NODE_KEYS)
    return node


def _edge(raw, where):
    if not isinstance(raw, dict):
        raise PortalError("%s has an edge that is not a mapping" % where)
    edge = dict((key, raw.get(key)) for key in EDGE_KEYS)
    pitfalls = edge["pitfalls"]
    if pitfalls is None:
        edge["pitfalls"] = []
    elif not isinstance(pitfalls, list):
        edge["pitfalls"] = [pitfalls]
    edge["extra"] = dict((key, value) for key, value in raw.items() if key not in EDGE_KEYS)
    return edge


def load_procedure(path, root=None):
    """One graph file as a Procedure, with its contracts read from the procedures' folder."""
    root = str(root or default_root())
    where = _origin(path, root)
    graph = _load_yaml(path, root)
    if not isinstance(graph, dict):
        raise PortalError("%s is not a graph, a mapping of its keys" % where)
    home = os.path.dirname(os.path.dirname(os.path.abspath(str(path))))
    stream = _text(graph.get("stream")) or os.path.splitext(os.path.basename(str(path)))[0]
    contract = {}
    if graph.get("contracts"):
        contract_path = os.path.join(home, str(graph["contracts"]))
        if not os.path.isfile(contract_path):
            raise PortalError("%s names the contracts file %s, which is missing"
                              % (where, _origin(contract_path, root)))
        contract = _load_yaml(contract_path, root) or {}
        if not isinstance(contract, dict):
            raise PortalError("%s is not a mapping of steps" % _origin(contract_path, root))
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise PortalError("%s has nodes or edges that are not a list" % where)
    return Procedure(
        stream=stream, version=_text(graph.get("version")), goal=_text(graph.get("goal")),
        entry=_text(graph.get("entry")), exit=_text(graph.get("exit")),
        nodes=[_node(raw, contract, home, stream, where, root) for raw in nodes],
        edges=[_edge(raw, where) for raw in edges],
        verification=stream in VERIFICATION_STREAMS, origin=where)


def load_procedures(graphs_dir, root=None):
    """Each graph, <graphs_dir>/*.yaml, as a Procedure, in file order."""
    return [load_procedure(path, root)
            for path in sorted(glob.glob(os.path.join(str(graphs_dir), "*.yaml")))]


def doc_id(path):
    """A doc's id, its path without .md in lower case, with each run of other characters a hyphen."""
    stem = path[:-3] if path.lower().endswith(".md") else path
    return re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")


def _inside_root(relative, root, what):
    """The absolute path of a path the config gives, which must stay inside the root."""
    if not isinstance(relative, str) or not relative.strip():
        raise PortalError("%s must be a path from the workflow's folder" % what)
    if os.path.isabs(relative):
        raise PortalError("%s %s must be a path from the workflow's folder" % (what, relative))
    full = os.path.normpath(os.path.join(root, relative))
    real_root = os.path.realpath(root)
    real = os.path.realpath(full)
    if real != real_root and not real.startswith(real_root + os.sep):
        raise PortalError("%s %s lies outside the workflow's folder" % (what, relative))
    return full


def _check_doc(doc, number):
    where = "docs line %d" % number
    if not isinstance(doc, dict):
        raise PortalError("%s is not a mapping of %s" % (where, ", ".join(DOC_KEYS)))
    unknown = sorted(set(doc) - set(DOC_KEYS))
    if unknown:
        raise PortalError("%s has the unknown key %s" % (where, ", ".join(unknown)))
    for key in ("path", "title"):
        if not isinstance(doc.get(key), str) or not doc[key].strip():
            raise PortalError("%s needs a %s" % (where, key))
    if doc.get("section") not in SECTIONS:
        raise PortalError("%s has the section %r, not one of %s"
                          % (where, doc.get("section"), ", ".join(SECTIONS)))
    if not isinstance(doc.get("optional", False), bool):
        raise PortalError("%s has an optional that is not true or false" % where)


def _read_doc(full, origin):
    """A doc's bytes and text, or PortalError naming it."""
    with open(full, "rb") as handle:
        data = handle.read()
    try:
        return data, data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise PortalError("%s cannot be read, %s" % (origin, error))


def load_home(root, path, title):
    """The home page's markdown as an Item of kind home, or PortalError when it is missing."""
    root = str(root)
    full = _inside_root(path, root, "home")
    origin = _origin(full, root)
    if not os.path.isfile(full):
        raise PortalError("the home page %s is missing" % origin)
    data, text = _read_doc(full, origin)
    return Item(
        kind="home", id="home", title=title, group=None, source=origin,
        source_commit="sha256:" + hashlib.sha256(data).hexdigest()[:12], updated=None,
        gist=gist_of(text), markdown=text, consult_also=[], origin=origin)


def load_docs(root, docs, warnings=None):
    """Each listed doc that exists as an Item.

    A missing optional doc adds a warning to the warnings list when one is
    given, and a missing required one raises PortalError.
    """
    root = str(root)
    items = []
    for number, doc in enumerate(docs or [], start=1):
        _check_doc(doc, number)
        full = _inside_root(doc["path"], root, "the doc")
        origin = _origin(full, root)
        if not os.path.isfile(full):
            if doc.get("optional", False):
                if warnings is not None:
                    warnings.append("the optional doc %s is missing, so it has no page" % origin)
                continue
            raise PortalError("the doc %s is missing" % origin)
        data, text = _read_doc(full, origin)
        items.append(Item(
            kind="doc", id=doc_id(origin), title=doc["title"].strip(), group=doc["section"], source=origin,
            source_commit="sha256:" + hashlib.sha256(data).hexdigest()[:12], updated=None,
            gist=gist_of(text), markdown=text, consult_also=[], origin=origin))
    return items


def load_config(config_path):
    """The portal's config, checked for its four keys and its optional home."""
    config_path = str(config_path)
    if not os.path.isfile(config_path):
        raise PortalError("the portal config %s is missing" % config_path)
    try:
        with open(config_path, encoding="utf-8") as handle:
            config = yaml.safe_load(handle)
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as error:
        raise PortalError("the portal config %s cannot be read, %s" % (config_path, error))
    if not isinstance(config, dict):
        raise PortalError("the portal config %s is not a mapping" % config_path)
    missing = [key for key in CONFIG_KEYS if key not in config]
    if missing:
        raise PortalError("the portal config %s has no %s" % (config_path, ", ".join(missing)))
    if not isinstance(config["title"], str) or not config["title"].strip():
        raise PortalError("the portal config %s needs a title" % config_path)
    if not isinstance(config["docs"], list):
        raise PortalError("the portal config %s has docs that are not a list" % config_path)
    if HOME_KEY in config and (not isinstance(config[HOME_KEY], str)
                               or not config[HOME_KEY].strip()):
        raise PortalError("the portal config %s has a home that is not a path" % config_path)
    return config


def load_all(config_path, root=None):
    """Every source the config names, as PortalSources(items, procedures, warnings, title, home).

    The items are the knowledge base entries and then the docs, the title is
    the config's, and home is the home page's Item, or None when the config
    names no home.
    """
    root = str(root or default_root())
    config = load_config(config_path)
    corpus = _inside_root(config["kb_corpus"], root, "kb_corpus")
    graphs = _inside_root(config["graphs"], root, "graphs")
    for key, folder in (("kb_corpus", corpus), ("graphs", graphs)):
        if not os.path.isdir(folder):
            raise PortalError("the %s folder %s is missing" % (key, config[key]))
    warnings = []
    items = load_entries(corpus, root)
    procedures = load_procedures(graphs, root)
    items.extend(load_docs(root, config["docs"], warnings))
    title = config["title"].strip()
    home = load_home(root, config[HOME_KEY], title) if config.get(HOME_KEY) else None
    return PortalSources(items=items, procedures=procedures, warnings=warnings,
                         title=title, home=home)
