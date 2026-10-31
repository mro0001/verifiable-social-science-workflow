"""outline_steps: read pipeline.yaml and each step's script, and list each script's steps
with a short title, its file, its first and last line, and its exact code. Then bundle the
final build's text and every script of the pipeline, with line numbers, as the one item the
finding step is asked about.

The steps of a script (Track V, choice 4).
- A script that marks its steps with comment lines `# step: <title>` has one step for each
  mark, from the mark's line to the line before the next mark, or to the end of the
  script, leaving out blank lines at its end. Any script may mark its steps, in any
  language whose comments start with #.
- A Python script that marks none has as its steps its top-level functions in the order
  the script calls them, each titled from its name (drop_missing is Drop missing). The
  order is found by walking from the script's module-level code into each function as it
  is called, a call's arguments before the call itself, as Python runs them. Every
  function the script calls is a step, main or another function that starts the script as
  well as a helper and the step that calls it, so no called function's code is left out.
  A function the script never calls is not a step, and a note names it.
- Any other script that marks none gives no step, and a warning says so.

Every pipeline step's script is read once, whatever its phase, so the check of a place in
the scripts can name the step it falls in. Its record names every pipeline step that runs
it and their phases. Findings about a script are given once in each report whose phase
has a step that runs it, while a pipeline step that declares no phase, or one that
is not collection, cleaning, or analysis, is named in every report, since no report would
show it.
"""
import ast
import hashlib
import os
import re

import _lib

PHASES = ("collection", "cleaning", "analysis")
MARK = re.compile(r"^\s*#\s*step:(.*)$")
CHECK = "outline_steps"


def sha256(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def read_bytes(name):
    with open(_lib.path(name), "rb") as f:
        return f.read()


def exists(name):
    return os.path.isfile(_lib.path(name))


def title_from(name):
    words = name.strip("_").replace("_", " ").split()
    text = " ".join(words) or name
    return text[0].upper() + text[1:]


def marked_steps(lines):
    """[(title, start, end)] for each mark, lines counted from 1, or [] when none."""
    marks = [(i + 1, m.group(1).strip()) for i, ln in enumerate(lines) for m in [MARK.match(ln)] if m]
    out = []
    for k, (start, title) in enumerate(marks):
        end = marks[k + 1][0] - 1 if k + 1 < len(marks) else len(lines)
        while end > start and not lines[end - 1].strip():
            end -= 1
        out.append((title, start, end))
    return out


class Calls(ast.NodeVisitor):
    """The names of the script's own functions in the order a block calls them, each
    once, a call's arguments before the call itself."""

    def __init__(self, defs):
        self.defs = defs
        self.order = []

    def visit_Call(self, node):
        for arg in node.args:
            self.visit(arg)
        for kw in node.keywords:
            self.visit(kw)
        self.visit(node.func)
        if isinstance(node.func, ast.Name) and node.func.id in self.defs and node.func.id not in self.order:
            self.order.append(node.func.id)


def calls_in(statements, defs):
    visitor = Calls(defs)
    for stmt in statements:
        visitor.visit(stmt)
    return visitor.order


def function_steps(tree):
    """(steps, never_called), where steps is [(name, start, end)] in call order."""
    defs = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defs[node.name] = node
    module = [s for s in tree.body if not isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    first = calls_in(module, defs)
    order, seen = [], set()

    def walk(name):
        if name in seen:
            return
        seen.add(name)
        order.append(name)
        for inner in calls_in(defs[name].body, defs):
            walk(inner)

    for name in first:
        walk(name)
    steps = []
    for name in order:
        node = defs[name]
        start = min([node.lineno] + [d.lineno for d in node.decorator_list])
        steps.append((name, start, node.end_lineno))
    never = [(name, defs[name].lineno) for name in defs if name not in seen]
    return steps, never


def read_script(name, lines, findings):
    """[(title, start, end, source)] for one script. findings gets (severity, item, message)."""
    marked = marked_steps(lines)
    if marked:
        out = []
        for title, start, end in marked:
            if not title:
                findings.append(("warning", "%s line %d" % (name, start), "The mark gives no title."))
                title = "(no title)"
            out.append((title, start, end, "marked"))
        return out
    if not name.endswith(".py"):
        findings.append(("warning", name, "The script marks no step, and only a Python script's "
                                          "functions can be read in place of marks."))
        return []
    try:
        tree = ast.parse("\n".join(lines) + "\n")
    except SyntaxError as err:
        findings.append(("warning", name, "The script cannot be read as Python at line %s, so its "
                                          "steps are not listed." % (err.lineno or "?")))
        return []
    steps, never = function_steps(tree)
    for fname, line in never:
        findings.append(("info", "%s line %d" % (name, line),
                         "The function %s is never called by the script, so it is not a step." % fname))
    if not steps:
        findings.append(("warning", name, "The script marks no step and calls none of its own "
                                          "functions, so no step could be read."))
    return [(title_from(fname), start, end, "function") for fname, start, end in steps]


def numbered(lines):
    return "\n".join("%4d  %s" % (i, ln) for i, ln in enumerate(lines, 1))


phase = _lib.read_json("phase.json")
this = phase["phase"]
findings = []
text_bytes = read_bytes("final_text.md")
pipe_bytes = read_bytes("pipeline.yaml")
try:
    pipeline = _lib.read_yaml("pipeline.yaml") or {}
except Exception as err:  # a pipeline file that is not YAML gives no steps and says so
    pipeline = {}
    findings.append(_lib.finding(CHECK, "blocking", "pipeline.yaml",
                                 "The pipeline file cannot be read as YAML, so no step is listed.",
                                 type(err).__name__))
declared = pipeline.get("steps") if isinstance(pipeline, dict) else None
if not isinstance(declared, list):
    declared = []
    if pipe_bytes.strip() and not findings:
        findings.append(_lib.finding(CHECK, "blocking", "pipeline.yaml",
                                     "The pipeline file holds no list of steps, so no step is listed."))

pipeline_steps, steps, scripts, files = [], [], [], []
files.append({"file": "final_text.md", "role": "the final build's text", "sha256": sha256(text_bytes)})
files.append({"file": "pipeline.yaml", "role": "the pipeline", "sha256": sha256(pipe_bytes)})
read_scripts, script_findings, record_of, emitted, noted = {}, {}, {}, set(), set()


def joined(words):
    words = [w for w in words if w]
    if len(words) < 2:
        return "".join(words)
    return ", ".join(words[:-1]) + " and " + words[-1]


for n, entry in enumerate(declared, 1):
    entry = entry if isinstance(entry, dict) else {}
    sid = str(entry.get("id") or "step %d" % n)
    step_phase = entry.get("phase")
    script = entry.get("script")
    script = str(script) if script else ""
    if step_phase is None or step_phase == "":
        findings.append(_lib.finding(CHECK, "warning", sid, "The step declares no phase, so no phase report shows it."))
        step_phase = ""
    elif step_phase not in PHASES:
        findings.append(_lib.finding(CHECK, "warning", sid, "The step declares the phase %s, which is not "
                                                           "collection, cleaning, or analysis." % step_phase))
    step_phase = str(step_phase)
    in_phase = step_phase == this
    record = {"id": sid, "phase": step_phase, "script": script, "read": False}
    pipeline_steps.append(record)
    if not script:
        if in_phase:
            findings.append(_lib.finding(CHECK, "warning", sid, "The step names no script, so it has no steps."))
        continue
    if script not in read_scripts:
        found = []
        if not exists(script):
            read_scripts[script] = None
            found.append(("warning", script, "The pipeline names this script, and it is not among the inputs."))
        else:
            data = read_bytes(script)
            try:
                lines = data.decode("utf-8").splitlines()
            except UnicodeDecodeError:
                read_scripts[script] = None
                found.append(("warning", script, "The script is not UTF-8 text, so its steps are not listed."))
            else:
                parts = read_script(script, lines, found)
                read_scripts[script] = (lines, parts)
                record_of[script] = {"file": script, "pipeline_steps": [], "phases": [],
                                     "lines": len(lines), "sha256": sha256(data)}
                scripts.append(record_of[script])
                files.append({"file": script, "role": "", "sha256": sha256(data)})
        script_findings[script] = found
    if script in record_of:
        rec = record_of[script]
        rec["pipeline_steps"].append(sid)
        if step_phase not in rec["phases"]:
            rec["phases"].append(step_phase)
    if in_phase and script not in emitted:
        emitted.add(script)
        for severity, item, message in script_findings[script]:
            findings.append(_lib.finding(CHECK, severity, item, message))
    got = read_scripts[script]
    if got is None:
        continue
    lines, parts = got
    record["read"] = bool(parts)
    for title, start, end, source in parts:
        steps.append({"pipeline_step": sid, "phase": step_phase, "script": script, "title": title,
                      "start": start, "end": end, "source": source,
                      "code": "\n".join(lines[start - 1:end])})
        words = len(title.split())
        if in_phase and words > 2 and (script, start) not in noted:
            noted.add((script, start))
            findings.append(_lib.finding(CHECK, "info", "%s line %d" % (script, start),
                                         "The title has %d words, and the outline asks for one or two." % words))

if not [p for p in pipeline_steps if p["phase"] == this]:
    findings.append(_lib.finding(CHECK, "info", this, "No step of the pipeline declares the phase %s." % this))

for f in files:
    if f["file"] in record_of:
        ids = record_of[f["file"]]["pipeline_steps"]
        f["role"] = "the script of step%s %s" % ("s" if len(ids) > 1 else "", joined(ids))

listing = []
for s in scripts:
    lines = read_scripts[s["file"]][0]
    ids, phases = s["pipeline_steps"], [p or "none declared" for p in s["phases"]]
    listing.append("=== %s (pipeline step%s %s, phase%s %s) ===\n%s" % (
        s["file"], "s" if len(ids) > 1 else "", joined(ids),
        "s" if len(phases) > 1 else "", joined(phases), numbered(lines)))

_lib.write_json("outline.json", {"phase": this, "pipeline_steps": pipeline_steps, "steps": steps,
                                 "scripts": scripts, "files": files})
_lib.write_json("find_items.json", [{"id": this, "phase": this, "phase_name": phase["name"],
                                     "text": text_bytes.decode("utf-8"),
                                     "code": "\n\n".join(listing) or "(the pipeline declares no script)"}])
_lib.emit_findings(CHECK, findings)
