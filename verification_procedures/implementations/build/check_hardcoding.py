"""check_hardcoding: results reach each canonical through {{num:key}}, not typed in.

The manifest is read flat (key: value) or in the nested `numbers:` form.

- every {{num:key}} must have a value in the deliverable's manifest (the build refuses otherwise, by design)
- a placeholder-shaped remnant ({{numb:x}}, {{num:}}) is malformed
- a bare numeral equal to a manifest value is a hard-coded result (blocking)
- any other bare numeral outside the allowlist is unbound; ship refuses it (warning)
Not results (ospipe lint's six exemptions): fenced code and inline code, years
1900-2099, numbers inside placeholders, list markers / headings / table separator
rows, allowlisted tokens, citation years.
"""
import posixpath
import re
import tarfile

import yaml

import _lib

NODE = "check_hardcoding"
PLACEHOLDER = re.compile(r"\{\{num:([A-Za-z0-9_.\-]+)\}\}")
SUSPECT = re.compile(r"\{\{\s*\w*\s*:?[^}]*\}\}")


def project_files():
    out = {}
    with tarfile.open(_lib.path("project.tar")) as tf:
        for m in tf.getmembers():
            if m.isfile() and not m.name.startswith("/") and ".." not in m.name.split("/"):
                out[posixpath.normpath(m.name)] = tf.extractfile(m).read()
    return out


def manifest_values(data):
    """{key: value text} from numbers.yml, flat (key: value) or in the data procedure's
    nested form, where `numbers:` maps each key to {value, from, field}."""
    data = data or {}
    if isinstance(data, dict) and set(data) == {"numbers"} and isinstance(data["numbers"], dict):
        data = {k: (v.get("value") if isinstance(v, dict) else v) for k, v in data["numbers"].items()}
    return {str(k): str(v) for k, v in data.items()}


def numeric(tok):
    t = tok.replace(",", "").rstrip("%")
    try:
        return float(t)
    except ValueError:
        return None


def prose_lines(text):
    """(line number, line) for prose: no front matter, fences, headings, separator rows."""
    lines = text.splitlines()
    start = 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() in ("---", "..."):
                start = i + 1
                break
    fence = None
    for i in range(start, len(lines)):
        ln = lines[i]
        s = ln.strip()
        if fence:
            if s.startswith(fence):
                fence = None
            continue
        if s.startswith("```") or s.startswith("~~~"):
            fence = s[:3]
            continue
        if s.startswith("#") or re.match(r"^\|?[\s:\-|]+\|?$", s) and "-" in s:
            continue
        yield i + 1, ln


def main():
    files = project_files()
    m = _lib.read_json("map.json")
    allow = set(m["allowlist"])
    findings = []
    seen = set()
    for d in m["deliverables"]:
        src = d["source"]
        if not src or src not in files or src in seen:
            continue
        seen.add(src)
        man = d["manifest"]
        if man not in files:
            findings.append(_lib.finding(NODE, "blocking", man, "The manifest the map names does not exist.", d["name"]))
            manifest = {}
        else:
            manifest = manifest_values(yaml.safe_load(files[man].decode("utf-8")))
        values = {}
        for k in sorted(manifest):
            for tok in _lib.numbers_in(manifest[k]) or [manifest[k]]:
                values.setdefault(tok, k)
                n = numeric(tok)
                if n is not None:
                    values.setdefault(n, k)
        text = files[src].decode("utf-8")
        missing = sorted({k for k in PLACEHOLDER.findall(text) if k not in manifest})
        for k in missing:
            findings.append(_lib.finding(NODE, "blocking", "%s:{{num:%s}}" % (src, k),
                                         "Placeholder with no value in %s; the build will refuse, by design." % man,
                                         k))
        for lineno, ln in prose_lines(text):
            for bad in SUSPECT.findall(ln):
                if not PLACEHOLDER.fullmatch(bad) and not bad.startswith("{{table:"):
                    findings.append(_lib.finding(NODE, "blocking", "%s:%s" % (src, bad),
                                                 "Malformed placeholder; it will not resolve.", "line %d" % lineno))
            body = PLACEHOLDER.sub(" ", ln)
            body = re.sub(r"`[^`]*`", " ", body)                       # inline code
            body = re.sub(r"\[[^\]]*@[^\]]*\]", " ", body)             # [@key, p. 4] citations
            body = re.sub(r"\([^()]*\b(19|20)\d\d[a-z]?\)", " ", body)  # (Name 2019)
            body = re.sub(r"^\s*(\d+[.)]|[-*+])\s+", " ", body)        # list markers
            for tok in _lib.numbers_in(body):
                n = numeric(tok)
                if re.fullmatch(r"(19|20)\d\d", tok) or tok in allow:
                    continue
                key = values.get(tok) or (values.get(n) if n is not None else None)
                ctx = "line %d: %s" % (lineno, _lib.cell(ln.strip(), 120))
                if key:
                    findings.append(_lib.finding(NODE, "blocking", "%s:%s" % (src, tok),
                                                 "Hard-coded result: equals %s key '%s'; use {{num:%s}} so it moves with the data." % (man, key, key),
                                                 ctx))
                else:
                    findings.append(_lib.finding(NODE, "warning", "%s:%s" % (src, tok),
                                                 "Bare numeral outside the allowlist; ship refuses it until it is keyed or allowlisted.",
                                                 ctx))
    _lib.emit_findings(NODE, findings)


if __name__ == "__main__":
    main()
