"""check_docs: method documentation is literate and agrees with the declarations.

Each step script opens with a docstring holding the sections Purpose, Inputs,
Outputs, Parameters, Assumptions (a line `Name:` at the left margin starts a
section). Mechanical checks:
  - a missing module docstring or section -> blocking
  - file names under Inputs / Outputs differ from pipeline.yaml -> warning
  - names under Parameters differ from the keys the script reads -> warning
  - a function, class, or method without a docstring -> warning
Helpers need a module docstring with Purpose and documented functions.
Whether the words describe what the code does is for the scholar, who reads the code;
no model judges it.
"""
import ast
import re

import _lib

CHECK = "check_docs"
SECTIONS = ["Purpose", "Inputs", "Outputs", "Parameters", "Assumptions"]
FILE = re.compile(r"[\w.\-<>]+\.(?:csv|json|svg|png|pdf|yaml|yml|txt|py|rds|qmd|md)\b")
proj = _lib.read_json("project.json")
inv = _lib.read_json("inventory.json")
usage = _lib.read_json("params_usage.json")
files = proj["files"]
findings = []


def sections(doc):
    out, cur = {}, None
    for line in doc.splitlines():
        m = re.match(r"^([A-Z][A-Za-z ]*):\s*$", line)
        if m and m.group(1) in SECTIONS:
            cur = m.group(1)
            out[cur] = []
        elif cur:
            out[cur].append(line)
    return {k: "\n".join(v).strip() for k, v in out.items()}


def defs(tree, prefix=""):
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield prefix + node.name, node
            if isinstance(node, ast.ClassDef):
                yield from defs(node, prefix + node.name + ".")


def check_script(script, step):
    src = files[script]["text"]
    try:
        tree = ast.parse(src)
    except SyntaxError as err:
        findings.append(_lib.finding(CHECK, "blocking", script, "script does not parse", str(err)))
        return
    doc = ast.get_docstring(tree) or ""
    need = SECTIONS if step else ["Purpose"]
    if not doc:
        findings.append(_lib.finding(CHECK, "blocking", script, "no module docstring: method undocumented",
                                     "expected sections: " + ", ".join(need)))
    secs = sections(doc)
    missing = [s for s in need if not secs.get(s)]
    if doc and missing:
        findings.append(_lib.finding(CHECK, "blocking", script,
                                     "module docstring lacks sections: " + ", ".join(missing),
                                     "present: " + (", ".join(s for s in SECTIONS if secs.get(s)) or "none")))
    if step:
        for sec, declared in (("Inputs", step["inputs"]), ("Outputs", step["outputs"])):
            if not secs.get(sec):
                continue
            said = {f for f in FILE.findall(secs[sec]) if not f.endswith(".py")} - {"params.yaml"}  # producers named, not inputs
            want = set(declared)
            if said != want:
                diff = []
                if want - said:
                    diff.append("pipeline.yaml only: " + ", ".join(sorted(want - said)))
                if said - want:
                    diff.append("docstring only: " + ", ".join(sorted(said - want)))
                findings.append(_lib.finding(CHECK, "warning", script,
                                             f"{sec} section disagrees with pipeline.yaml", "; ".join(diff)))
        if secs.get("Parameters"):
            named = {ln.strip().split()[0].strip(":-,") for ln in secs["Parameters"].splitlines()
                     if ln.strip() and not ln.startswith("        ")}
            named.discard("none;")
            reads = set(usage.get(script, {}).get("reads", []))
            for k in sorted(named - reads):
                findings.append(_lib.finding(CHECK, "warning", script,
                                             f"Parameters section names {k}, but the script never reads it from params.yaml",
                                             secs["Parameters"].splitlines()[0][:80]))
            for k in sorted(reads - named):
                findings.append(_lib.finding(CHECK, "warning", script,
                                             f"script reads parameter {k} that its Parameters section omits", k))
    for name, node in defs(tree):
        fdoc = ast.get_docstring(node) or ""
        if not fdoc:
            findings.append(_lib.finding(CHECK, "warning", f"{script}:{name}", "no docstring",
                                         f"line {node.lineno}"))


for step in inv["steps"]:
    if step["script"] in files:
        check_script(step["script"], step)
for helper in inv["helpers"]:
    if helper in files:
        check_script(helper, None)

_lib.emit_findings(CHECK, findings)
