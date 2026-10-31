"""check_params: parameters are set once, in params.yaml, and read from there.

AST scan of every step script and helper:
  - a literal that EQUALS a params.yaml value but does not come from params.yaml
    -> blocking (the value is set twice; the copies drift)
  - a numeric literal used as a threshold or setting (in a comparison, assigned
    straight to a name, a keyword argument, a default argument) -> blocking
    "hard-coded parameter"; named after a params key, the message gives both values
  - a line marked `# not-a-param: <reason>` is exempt and listed as a note
  - a key read that params.yaml does not define -> blocking
  - a params.yaml key no script reads -> note
0, 1 and -1 are never flagged (indices, counts, signs). Docstrings are skipped.
Writes params_usage.json: per script, the keys it reads and its Params objects.
"""
import ast
import io
import tokenize

import _lib

CHECK = "check_params"
EXEMPT_MARK = "not-a-param:"
proj = _lib.read_json("project.json")
inv = _lib.read_json("inventory.json")
params = proj["params"]
files = proj["files"]
findings, usage = [], {}


def same(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    return isinstance(a, str) and isinstance(b, str) and a == b


def comments(src):
    out = {}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                out[tok.start[0]] = tok.string
    except (tokenize.TokenError, IndentationError):
        pass
    return out


def slice_of(node):
    s = node.slice
    return s.value if isinstance(s, ast.Index) else s  # Python 3.8 wraps in Index


def scan(script, src):
    try:
        tree = ast.parse(src)
    except SyntaxError as err:
        findings.append(_lib.finding(CHECK, "blocking", script, "script does not parse", str(err)))
        return
    lines = src.splitlines()
    notes = comments(src)
    parent = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[child] = node
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                    and isinstance(first.value.value, str):
                docstrings.add(first.value)
    objects = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            f = node.value.func
            fname = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if fname == "Params":
                objects.update(t.id for t in node.targets if isinstance(t, ast.Name))
    reads, keys = [], set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id in objects:
            k = slice_of(node)
            if isinstance(k, ast.Constant) and isinstance(k.value, str):
                keys.add(k)
                reads.append(k.value)
                if k.value not in params:
                    findings.append(_lib.finding(CHECK, "blocking", f"{script}:L{node.lineno}",
                                                 f"reads {k.value!r}, which params.yaml does not define",
                                                 lines[node.lineno - 1].strip()))
    usage[script] = {"reads": sorted(set(reads)), "objects": sorted(objects)}

    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or node in docstrings or node in keys:
            continue
        value, at = node.value, node
        if isinstance(value, bool) or value is None or isinstance(value, bytes):
            continue
        if isinstance(parent.get(node), ast.UnaryOp) and isinstance(parent[node].op, ast.USub) \
                and isinstance(value, (int, float)):
            value, at = -value, parent[node]
        if isinstance(value, (int, float)) and value in (0, 1, -1):
            continue
        if isinstance(value, str) and isinstance(parent.get(node), ast.JoinedStr):
            continue
        ctx = parent.get(at)
        target = None
        if isinstance(ctx, ast.Assign) and ctx.value is at:
            names = [t.id for t in ctx.targets if isinstance(t, ast.Name)]
            target = names[0] if names else None
        setting = isinstance(value, (int, float)) and (
            isinstance(ctx, (ast.Compare, ast.keyword, ast.arguments, ast.AugAssign, ast.AnnAssign))
            or (isinstance(ctx, ast.Assign) and ctx.value is at))
        matches = [k for k in sorted(params) if same(params[k], value)]
        if not matches and not setting:
            continue
        line = at.lineno
        item = f"{script}:L{line}"
        evidence = lines[line - 1].strip()
        if EXEMPT_MARK in notes.get(line, ""):
            findings.append(_lib.finding(CHECK, "info", item, "literal declared not a parameter",
                                         notes[line].split(EXEMPT_MARK, 1)[1].strip()))
        elif target in params and not same(params[target], value):
            findings.append(_lib.finding(
                CHECK, "blocking", item,
                f"hard-coded parameter: {target} = {value!r} here, params.yaml sets {target}: {params[target]!r}",
                evidence))
        elif matches:
            findings.append(_lib.finding(
                CHECK, "blocking", item,
                f"literal {value!r} equals params.yaml {matches[0]} but bypasses params.yaml",
                evidence))
        else:
            findings.append(_lib.finding(CHECK, "blocking", item,
                                         f"hard-coded parameter: literal {value!r} used as a setting; "
                                         f"set it in params.yaml or mark the line '# not-a-param: <why>'",
                                         evidence))


for script in inv["scripts"] + inv["helpers"]:
    if script in files and "text" in files[script]:
        scan(script, files[script]["text"])

used = set()
for u in usage.values():
    used.update(u["reads"])
for k in sorted(params):
    if k not in used:
        findings.append(_lib.finding(CHECK, "info", k, "set in params.yaml but read by no script",
                                     f"{k}: {params[k]!r}"))

_lib.write_json("params_usage.json", usage)
_lib.emit_findings(CHECK, findings)
