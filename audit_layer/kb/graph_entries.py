"""Writing a procedural graph's knowledge base entry (appendix A2.4 "Procedural graphs").

Each graph gets one entry in the group PROCEDURES naming its purpose, its
triggers, its steps, and the command that runs it, so a session finds the
procedure through the knowledge base's search while the runtime runs it. The
entry is written from the graph file and the contract file it names, both
read from a procedures folder given by path. That folder is a plain copy of the
verification layer's files. Nothing here imports that layer's code.

For a graph the procedure registry names (registry.yaml in the procedures
folder), the title is the registry's procedure name and the triggers are its
events and phrases written as sentences. A graph the registry does not name
may carry its own title and triggers keys, which the runtime never reads.
"""
import hashlib
import re
from pathlib import Path

import yaml

from audit_layer.kb.entries import first_sentence, parse_entry
from audit_layer.kb.index import write_llms

GROUP = "PROCEDURES"
SOURCE_DIR = "verification_procedures/graphs"
REGISTRY_FILE = "registry.yaml"
NO_TRIGGERS = "None declared in the graph."
POINT_TAIL = (
    "The procedural graph system runs it with the command below, so a session finds it "
    "here and does not carry out its steps by hand."
)
FOLDER = "procedures"
AUTHORING_ENTRY = "guidelines/guidelines-authoring-procedures.md"
CONSULT = (
    "## Consult also\n\n"
    "- guidelines-authoring-procedures - to write a new procedure or revise this one.\n"
)
# Files the runtime itself writes into a run, which no inputs folder holds
# (C11's rule for steps.json).
RUNTIME_FILES = ("steps.json",)

_STEM = re.compile(r"[a-z0-9_]+")


def read_procedure(procedures_dir, name):
    """The graph graphs/<name>, the contract it names, and the graph file's bytes."""
    procedures_dir = Path(procedures_dir)
    graph_rel = "graphs/" + name
    graph_bytes = (procedures_dir / graph_rel).read_bytes()
    graph = yaml.safe_load(graph_bytes.decode("utf-8"))
    contract_rel = str((graph or {}).get("contracts", ""))
    try:
        with open(str(procedures_dir / contract_rel), encoding="utf-8") as handle:
            contract = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(
            "{} names the contract {}, which cannot be read ({})".format(
                graph_rel, contract_rel or "(none)", error
            )
        )
    if not isinstance(contract, dict):
        raise ValueError(
            "{} names the contract {}, which holds no steps".format(graph_rel, contract_rel)
        )
    return graph, contract, graph_bytes


def registry_entry(procedures_dir, name):
    """The registry entry naming graphs/<name>, or None when no registry names it."""
    procedures_dir = Path(procedures_dir)
    path = procedures_dir / REGISTRY_FILE
    if not path.is_file():
        return None
    registry = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    target = (procedures_dir / "graphs" / name).resolve()
    for entry in registry.get("procedures") or []:
        graph = str(entry.get("graph", ""))
        if graph and (procedures_dir / graph).resolve() == target:
            return entry
    return None


def runtime_order(graph):
    """Node ids in the order vg.py's topo_order runs them.

    Start with the nodes no transition enters, in node-list order, take the
    first ready node each time, and release its targets in edge-list order.
    """
    indeg = {node["id"]: 0 for node in graph["nodes"]}
    for edge in graph["edges"]:
        indeg[edge["to"]] += 1
    ready = [node["id"] for node in graph["nodes"] if indeg[node["id"]] == 0]
    order = []
    while ready:
        current = ready.pop(0)
        order.append(current)
        for edge in graph["edges"]:
            if edge["from"] == current:
                indeg[edge["to"]] -= 1
                if indeg[edge["to"]] == 0:
                    ready.append(edge["to"])
    if len(order) != len(graph["nodes"]):
        raise ValueError("the graph has a cycle")
    return order


def inputs_of(graph, contract):
    """The files a run's inputs folder holds, as (required, optional, patterns).

    Required are the reads no step produces, apart from the files the runtime
    writes itself. Optional are the reads_optional names without a wildcard
    that no step produces. Patterns are the wildcard reads_optional patterns
    that do not start with findings_.
    """
    steps = [contract.get(node["id"]) or {} for node in graph["nodes"]]
    produced = set()
    for step in steps:
        produced.update((step.get("produces") or {}).keys())
    required = set()
    optional = set()
    patterns = set()
    for step in steps:
        for name in step.get("reads") or []:
            if name not in produced and name not in RUNTIME_FILES:
                required.add(name)
        for name in step.get("reads_optional") or []:
            if any(mark in name for mark in "*?["):
                if not name.startswith("findings_"):
                    patterns.add(name)
            elif name not in produced and name not in RUNTIME_FILES:
                optional.add(name)
    return sorted(required), sorted(optional - required), sorted(patterns)


def entry_id(name):
    """procedures- plus the graph file's stem with _ turned into -."""
    stem = Path(name).stem
    if not _STEM.fullmatch(stem):
        raise ValueError(
            "{} cannot name an entry, a graph file's stem holds only lowercase letters, "
            "digits, and _".format(name)
        )
    return "procedures-" + stem.replace("_", "-")


def render_entry(name, graph, contract, graph_bytes, date, consult, procedure=None):
    """The entry text for graphs/<name>.

    procedure is the registry entry naming the graph, or None. When given, its
    procedure name is the title and its events and phrases are the triggers.
    """
    if procedure is not None:
        title = str(procedure.get("procedure", ""))
        triggers = _registry_triggers(procedure.get("triggers") or {})
    else:
        title = str(graph.get("title") or "The {} procedure".format(graph["stream"]))
        triggers = _sentences(graph.get("triggers") or []) or NO_TRIGGERS
    goal = " ".join(str(graph.get("goal", "")).split())
    nodes = {node["id"]: node for node in graph["nodes"]}
    order = runtime_order(graph)
    lines = [
        "---",
        "id: " + entry_id(name),
        "title: " + title,
        "source: {}/{}".format(SOURCE_DIR, name),
        "source_commit: sha256:" + hashlib.sha256(graph_bytes).hexdigest()[:12],
        "updated: " + date,
        "group: " + GROUP,
        "---",
        "",
        "# " + title,
        "",
        _ended(first_sentence(goal)) + " " + POINT_TAIL,
        "",
        "1. Purpose. " + goal,
        "2. Triggers. " + triggers,
        "3. Steps. {}, in the order the runtime runs them, each only when a transition "
        "into it fires.".format(_count(len(order), "step")),
    ]
    for node_id in order:
        lines.append("   - `{}` ({}) {}".format(node_id, _kind(nodes[node_id]), nodes[node_id].get("does", "")))
    lines.append("4. Run command. " + _run_command(name, graph, contract))
    lines.append(
        "5. Version. Graph version {}, {} and {}, checked with "
        "`python3 vg.py check graphs/{}`.".format(
            graph.get("version"),
            _count(len(order), "step"),
            _count(len(graph["edges"]), "transition"),
            name,
        )
    )
    text = "\n".join(lines) + "\n"
    if consult:
        text += "\n" + CONSULT
    return text


def sync(procedures_dir, corpus, date, check_only=False):
    """Bring the corpus's PROCEDURES group in step with the graphs.

    Every graphs/*.yaml gets its entry, rendered with the existing entry's
    updated date when that entry exists. An entry that would come out the same
    is left alone, a different one is written with date, and each file in
    procedures/ with no graph is removed. The index is then rewritten. Every
    graph is rendered before anything is written, so a broken graph leaves the
    corpus as it was. With check_only nothing is written. The result holds the
    entry ids added, changed, removed, and unchanged.
    """
    procedures_dir = Path(procedures_dir)
    corpus = Path(corpus)
    folder = corpus / FOLDER
    consult = (corpus / AUTHORING_ENTRY).is_file()
    result = {"added": [], "changed": [], "removed": [], "unchanged": []}
    writes = []
    kept = set()
    for graph_path in sorted((procedures_dir / "graphs").glob("*.yaml")):
        name = graph_path.name
        ident = entry_id(name)
        kept.add(ident + ".md")
        graph, contract, graph_bytes = read_procedure(procedures_dir, name)
        procedure = registry_entry(procedures_dir, name)
        path = folder / (ident + ".md")
        if path.is_file():
            old = path.read_text(encoding="utf-8")
            updated = parse_entry(path, corpus)["front"].get("updated") or date
            same = render_entry(name, graph, contract, graph_bytes, updated, consult, procedure)
            if same == old:
                result["unchanged"].append(ident)
                continue
            result["changed"].append(ident)
        else:
            result["added"].append(ident)
        writes.append((path, render_entry(name, graph, contract, graph_bytes, date, consult, procedure)))
    stale = sorted(path for path in folder.glob("*.md") if path.name not in kept) if folder.is_dir() else []
    result["removed"] = [path.stem for path in stale]
    if check_only:
        return result
    for path, text in writes:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    for path in stale:
        path.unlink()
    write_llms(corpus)
    return result


def _kind(node):
    """How a step runs, as the steps fact names it."""
    if node.get("kind") != "judgment":
        return "tool step"
    text = "judgment step"
    if node.get("role") == "second":
        text += " by the second checker"
    if node.get("foreach"):
        text += ", once per item in `{}`".format(node["foreach"])
        if node.get("where"):
            text += " where {}".format(node["where"])
    return text


def _run_command(name, graph, contract):
    """The run command fact, with its executors and the inputs folder's files."""
    roles = {
        node.get("role", "judge") for node in graph["nodes"] if node.get("kind") == "judgment"
    }
    command = "python3 vg.py run graphs/{} --run runs/<new run folder> --inputs <inputs folder>".format(name)
    if "judge" in roles:
        command += " --judge <executor>"
    if "second" in roles:
        command += " --second <executor>"
    text = "From the `verification_procedures` folder, run `{}`.".format(command)
    required, optional, patterns = inputs_of(graph, contract)
    parts = []
    if required:
        parts.append("holds " + _join(required))
    if optional:
        parts.append(("and when present " if parts else "holds when present ") + _join(optional))
    if patterns:
        parts.append(("and any files matching " if parts else "holds any files matching ") + _join(patterns))
    if parts:
        text += " The inputs folder " + ", ".join(parts) + "."
    else:
        text += " The inputs folder needs no files."
    if roles:
        text += " An executor is `recorded:<answers file>` or a model the runtime can reach."
    return text


def _registry_triggers(triggers):
    """The registry's events and phrases written as sentences."""
    sentences = []
    events = [str(event) for event in triggers.get("events") or []]
    phrases = [str(phrase) for phrase in triggers.get("phrases") or []]
    if events:
        sentences.append(
            "It starts on the harness {} {}.".format(
                "event" if len(events) == 1 else "events",
                _join(["`{}`".format(event) for event in events], quote=False),
            )
        )
    if phrases:
        sentences.append(
            "It starts on a request that uses the phrase {}.".format(
                _join(['"{}"'.format(phrase) for phrase in phrases], quote=False, word="or")
            )
        )
    return " ".join(sentences) or "None declared in the registry."


def _sentences(items):
    """Each trigger as a sentence ending with a period, joined by spaces."""
    return " ".join(_ended(" ".join(str(item).split())) for item in items if str(item).strip())


def _ended(sentence):
    """The sentence with a full stop when it has no end of its own."""
    return sentence if sentence.endswith((".", "!", "?")) else sentence + "."


def _join(items, quote=True, word="and"):
    """Items as a list in words, each in backticks unless quote is false."""
    items = ["`{}`".format(item) for item in items] if quote else list(items)
    if len(items) <= 2:
        return " {} ".format(word).join(items)
    return ", ".join(items[:-1]) + ", {} ".format(word) + items[-1]


def _count(n, noun):
    return "{} {}{}".format(n, noun, "" if n == 1 else "s")
