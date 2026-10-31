"""read_map: parse the Makefile map in project.tar into map.json.

A map entry is a Makefile rule whose recipe calls the build with --source (the
canonical file), --builds-dir, and a pandoc command after `--`. A rule whose recipe
runs ospipe's build names the canonical file with --manuscript instead, and its
pandoc command is the one ospipe's build composes from --to, --bib, --csl, and
--reference-doc. Also finds
look-alikes: other markdown files that read as a deliverable (same title, or the
canonical's file stem in their name). A look-alike without an ARCHIVE line right
after its front matter is a competing canonical.
"""
import hashlib
import posixpath
import re
import shlex
import tarfile

import _lib

NODE = "read_map"
VALUE_OPTS = {"--source", "--manifest", "--builds-dir", "--ext", "--purpose"}
# ospipe build's options that take a value, and its output formats: the pandoc writer
# named by --to -> (file extension, extra pandoc args), as ospipe's build has them.
OSPIPE_OPTS = {"--manuscript", "--manifest", "--overlay", "--tables-dir", "--allowlist", "--builds-dir",
               "--purpose", "--baseline", "--bib", "--csl", "--reference-doc", "--to", "--verification-dir"}
OSPIPE_FORMATS = {"docx": ("docx", []), "revealjs": ("html", ["--standalone"])}


def project_files():
    out = {}
    with tarfile.open(_lib.path("project.tar")) as tf:
        for m in tf.getmembers():
            if m.isfile() and not m.name.startswith("/") and ".." not in m.name.split("/"):
                out[posixpath.normpath(m.name)] = tf.extractfile(m).read()
    return out


def parse_makefile(text):
    lines, buf = [], ""
    for raw in text.splitlines():
        if raw.endswith("\\"):
            buf += raw[:-1] + " "
            continue
        lines.append(buf + raw)
        buf = ""
    if buf:
        lines.append(buf)
    variables, rules, cur = {}, [], None
    for ln in lines:
        if ln.startswith("\t"):
            if cur is not None:
                cur["recipe"].append(ln.strip())
            continue
        stripped = ln.split("#", 1)[0].rstrip()
        if not stripped.strip():
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*(\?=|:=|=)\s*(.*)$", stripped)
        if m:
            name, op, val = m.groups()
            if op != "?=" or name not in variables:
                variables[name] = val.strip()
            cur = None
            continue
        m = re.match(r"^([^:=\s][^:=]*?)\s*:(?!=)\s*(.*)$", stripped)
        if m:
            cur = {"target": m.group(1).strip(), "prereqs": m.group(2).split(), "recipe": []}
            rules.append(cur)
    return variables, rules


def expand(s, variables, depth=0):
    if depth > 10:
        return s
    out = re.sub(r"\$\(([A-Za-z_][A-Za-z0-9_]*)\)", lambda m: variables.get(m.group(1), ""), s)
    return out if out == s else expand(out, variables, depth + 1)


def title_of(text):
    fm = re.match(r"^---\n(.*?)\n---\n", text, flags=re.S)
    if fm:
        m = re.search(r"^title:\s*[\"']?(.*?)[\"']?\s*$", fm.group(1), flags=re.M)
        if m:
            return m.group(1).strip()
    m = re.search(r"^#\s+(.+)$", text, flags=re.M)
    return m.group(1).strip() if m else ""


def banner_of(text):
    body = re.sub(r"^---\n.*?\n---\n", "", text, count=1, flags=re.S)
    for ln in body.splitlines():
        if ln.strip():
            return ln.strip() if ln.strip().startswith("> ARCHIVE") else None
    return None


def main():
    files = project_files()
    findings = []
    if "Makefile" not in files:
        findings.append(_lib.finding(NODE, "blocking", "Makefile", "No map: the project has no Makefile.", ""))
        variables, rules = {}, []
    else:
        variables, rules = parse_makefile(files["Makefile"].decode("utf-8"))

    deliverables = []
    for rule in rules:
        recipe = expand(" ".join(rule["recipe"]), variables)
        if "--builds-dir" not in recipe:
            continue
        argv = shlex.split(recipe)
        cut = argv.index("--") if "--" in argv else len(argv)
        head, pandoc = argv[:cut], argv[cut + 1:]
        ospipe = "--source" not in head and "--manuscript" in head
        opts = {}
        for i, a in enumerate(head):
            if a in (OSPIPE_OPTS if ospipe else VALUE_OPTS) and i + 1 < len(head):
                opts.setdefault(a, []).append(head[i + 1])
        name = rule["target"]
        if ospipe:
            to = (opts.get("--to") or ["docx"])[0]
            ext, extra = OSPIPE_FORMATS.get(to, (to, []))
            args = ["--from", "markdown", "--to", to] + extra
            if opts.get("--bib"):
                args += ["--citeproc", "--bibliography", opts["--bib"][0]]
                if opts.get("--csl"):
                    args += ["--csl", opts["--csl"][0]]
            if opts.get("--reference-doc"):
                args += ["--reference-doc", opts["--reference-doc"][0]]
            pandoc = ["pandoc"] + args
            opts["--source"] = opts.get("--manuscript", [])
            opts["--ext"] = [ext]
        sources = opts.get("--source", [])
        if len(sources) != 1:
            findings.append(_lib.finding(NODE, "blocking", name,
                                         "A map entry must name exactly one canonical file; this one names %d." % len(sources),
                                         " ".join(sources)))
        source = sources[0] if sources else ""
        if source and source not in files:
            findings.append(_lib.finding(NODE, "blocking", source,
                                         "The map names a canonical file that does not exist.", "rule " + name))
        prereqs = [expand(p, variables) for p in rule["prereqs"]]
        if source and source not in prereqs:
            findings.append(_lib.finding(NODE, "warning", name,
                                         "The canonical file is not a prerequisite, so make will not rebuild when it changes.",
                                         " ".join(prereqs)))
        if not pandoc or "pandoc" not in posixpath.basename(pandoc[0]):
            findings.append(_lib.finding(NODE, "blocking", name, "The map entry has no pandoc render after `--`.", recipe[:120]))
        args = pandoc[1:]
        tmpl = None
        for i, a in enumerate(args):
            if a == "--template" and i + 1 < len(args):
                tmpl = args[i + 1]
            elif a.startswith("--template="):
                tmpl = a.split("=", 1)[1]
        deliverables.append({
            "name": name, "source": source,
            "builds_dir": (opts.get("--builds-dir") or [""])[0].rstrip("/"),
            "manifest": (opts.get("--manifest") or ["numbers.yml"])[0],
            "ext": (opts.get("--ext") or ["html"])[0],
            "template": tmpl, "pandoc_args": args, "prereqs": prereqs,
            "command_sha256": hashlib.sha256(" ".join(args).encode()).hexdigest(),
        })
    if not deliverables:
        findings.append(_lib.finding(NODE, "blocking", "Makefile", "The map has no deliverable entries.", ""))

    seen = {}
    for d in deliverables:
        if d["builds_dir"] in seen:
            findings.append(_lib.finding(NODE, "blocking", d["builds_dir"],
                                         "Two deliverables share one builds dir, so their ledgers would collide.",
                                         "%s, %s" % (seen[d["builds_dir"]], d["name"])))
        seen[d["builds_dir"]] = d["name"]

    canon = {d["source"] for d in deliverables if d["source"]}
    canon_titles = {}
    canon_stems = {}
    for c in canon:
        if c in files:
            t = _lib.norm(title_of(files[c].decode("utf-8")))
            if t:
                canon_titles[t] = c
        canon_stems[posixpath.splitext(posixpath.basename(c))[0].lower()] = c
    excluded = tuple(d["builds_dir"] + "/" for d in deliverables if d["builds_dir"]) + ("ship/",)
    look_alikes = []
    for p in sorted(files):
        if not p.endswith(".md") or p in canon or p.startswith(excluded):
            continue
        text = files[p].decode("utf-8", errors="replace")
        stem = posixpath.splitext(posixpath.basename(p))[0].lower()
        reason, claims = None, None
        t = _lib.norm(title_of(text))
        if t and t in canon_titles:
            reason, claims = "same title as the canonical", canon_titles[t]
        else:
            for s, c in canon_stems.items():
                if s and s in stem:
                    reason, claims = "file name contains the canonical's name", c
                    break
        if not reason:
            continue
        banner = banner_of(text)
        look_alikes.append({"path": p, "claims": claims, "reason": reason, "banner": banner})
        if banner is None:
            findings.append(_lib.finding(NODE, "warning", p,
                                         "Competing canonical: this file reads as %s (%s) and has no ARCHIVE line." % (claims, reason),
                                         "add '> ARCHIVE <date>: superseded by %s' after the front matter" % claims))
        else:
            m = re.search(r"superseded by (\S+)", banner)
            target = m.group(1) if m else None
            if not target or target not in files:
                findings.append(_lib.finding(NODE, "warning", p,
                                             "The ARCHIVE line does not point at a file that exists.", banner))
            else:
                findings.append(_lib.finding(NODE, "info", p, "Archived look-alike, correctly bannered.", banner))

    allow = []
    allow_path = expand(variables.get("ALLOW", ""), variables)
    if allow_path and allow_path in files:
        allow = sorted({ln.strip() for ln in files[allow_path].decode("utf-8").splitlines() if ln.strip()})
    _lib.write_json("map.json", {
        "deliverables": sorted(deliverables, key=lambda d: d["name"]),
        "n_deliverables": len(deliverables),
        "variables": {k: variables[k] for k in sorted(variables)},
        "allowlist_file": allow_path or None,
        "allowlist": allow,
        "look_alikes": look_alikes,
    })
    _lib.emit_findings(NODE, findings)


if __name__ == "__main__":
    main()
