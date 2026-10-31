"""check_prefs: the author's build preferences are carried by the map and show in the builds.

build_prefs.yaml holds preferences in the author's words: an `all:` block plus one
block per deliverable (a deliverable block overrides `all`). Each known preference
maps to what the pandoc command must carry and, where the output can show it, a
mark in the latest build. A preference the verifier does not know is a warning,
never a silent pass.
"""
import posixpath
import re
import tarfile

import yaml

import _lib

NODE = "check_prefs"
VALUE_FLAGS = {"--template", "--bibliography", "--csl", "--to", "-t", "--reference-doc", "--from", "-f",
               "--output", "-o", "--metadata", "-M", "--variable", "-V", "--resource-path"}
FORMATS = {"html": {"html", "html5", "html4"}, "slides": {"revealjs", "slidy", "s5", "dzslides", "beamer"},
           "revealjs": {"revealjs"}, "docx": {"docx"}, "pdf": {"pdf", "latex"}, "markdown": {"markdown", "gfm"}}


def project_files():
    out = {}
    with tarfile.open(_lib.path("project.tar")) as tf:
        for m in tf.getmembers():
            if m.isfile() and not m.name.startswith("/") and ".." not in m.name.split("/"):
                out[posixpath.normpath(m.name)] = tf.extractfile(m).read()
    return out


def parse_args(args):
    flags, values = set(), {}
    i = 0
    while i < len(args):
        a = args[i]
        if "=" in a and a.startswith("--"):
            k, v = a.split("=", 1)
            values.setdefault(k, []).append(v)
        elif a in VALUE_FLAGS and i + 1 < len(args):
            values.setdefault(a, []).append(args[i + 1])
            i += 1
        else:
            flags.add(a)
        i += 1
    return flags, values


def template_mark(text):
    """The longest static line of the template (no $ variables), if long enough to be distinctive."""
    static = sorted((s for s in (ln.strip() for ln in text.splitlines()) if "$" not in s and len(s) >= 20),
                    key=lambda s: (-len(s), s))
    return static[0] if static else None


def judge(pref, value, flags, values, out, snapshot, files):
    """Returns (in_command, why_not, visible) where visible is True/False/None (not checkable)."""
    to = (values.get("--to") or values.get("-t") or [""])[0]
    has_cites = "[@" in snapshot or re.search(r"(?<![\w.])@[A-Za-z]", snapshot) is not None
    if pref == "bibliography":
        ok = str(value) in values.get("--bibliography", []) and "--citeproc" in flags
        vis = None if out is None or not has_cites else ("csl-bib-body" in out or 'id="refs"' in out)
        return ok, "needs --citeproc --bibliography %s" % value, vis
    if pref == "citation_style":
        ok = str(value) in values.get("--csl", []) and "--citeproc" in flags
        vis = None if out is None or not has_cites else ("[@" not in out and "csl-entry" in out)
        return ok, "needs --citeproc --csl %s" % value, vis
    if pref == "template":
        ok = str(value) in values.get("--template", [])
        mark = template_mark(files[str(value)].decode("utf-8")) if str(value) in files else None
        vis = None if out is None or mark is None else mark in out
        return ok, "needs --template %s" % value, vis
    if pref in ("toc", "number_sections"):
        names = {"toc": ("--toc", "--table-of-contents"), "number_sections": ("--number-sections", "-N")}[pref]
        present = any(n in flags for n in names)
        want = bool(value)
        mark = {"toc": 'id="TOC"', "number_sections": "header-section-number"}[pref]
        vis = None if out is None else ((mark in out) == want)
        return present == want, ("needs %s" % names[0]) if want else ("must not carry %s" % names[0]), vis
    if pref == "format":
        allowed = FORMATS.get(str(value), {str(value)})
        return to in allowed, "needs --to one of %s" % sorted(allowed), None
    if pref == "reference_doc":
        ok = str(value) in values.get("--reference-doc", [])
        return ok, "needs --reference-doc %s" % value, None
    return None, "unknown preference", None


def show(v):
    return str(v).lower() if isinstance(v, bool) else str(v)


def main():
    files = project_files()
    m = _lib.read_json("map.json")
    ledger = _lib.read_json("ledger.json")
    findings, rows = [], []
    if "build_prefs.yaml" not in files:
        findings.append(_lib.finding(NODE, "warning", "build_prefs.yaml",
                                     "The author's build preferences are not written down, so none can be checked.", ""))
        prefs = {}
    else:
        prefs = yaml.safe_load(files["build_prefs.yaml"].decode("utf-8")) or {}
    names = {d["name"] for d in m["deliverables"]}
    for block in sorted(k for k in prefs if k != "all" and k not in names):
        findings.append(_lib.finding(NODE, "warning", block,
                                     "Preferences declared for a deliverable the map does not have.", "build_prefs.yaml"))
    for d in m["deliverables"]:
        eff = dict(prefs.get("all") or {})
        eff.update(prefs.get(d["name"]) or {})
        flags, values = parse_args(d["pandoc_args"])
        latest = ledger["latest"].get(d["name"])
        out = snap = None
        if latest and latest["path"] in files:
            out = files[latest["path"]].decode("utf-8", errors="replace")
        if latest and latest["snapshot"] in files:
            snap = files[latest["snapshot"]].decode("utf-8", errors="replace")
        for pref in sorted(eff):
            value = eff[pref]
            item = "%s:%s" % (d["name"], pref)
            ok, why, vis = judge(pref, value, flags, values, out, snap or "", files)
            if ok is None:
                findings.append(_lib.finding(NODE, "warning", item,
                                             "A preference the verifier cannot check; add it to check_prefs or drop it.",
                                             "%s: %s" % (pref, show(value))))
                rows.append({"deliverable": d["name"], "pref": pref, "value": show(value),
                             "in_command": False, "visible": None, "known": False})
                continue
            if not ok:
                findings.append(_lib.finding(NODE, "blocking", item,
                                             "Preference not integrated: the author declared it but the map's command for %s does not carry it." % d["name"],
                                             "%s: %s; %s" % (pref, show(value), why)))
            elif vis is False:
                findings.append(_lib.finding(NODE, "warning", "%s:%s" % (item, latest["path"]),
                                             "The map carries this preference but the latest build does not show it; the build predates the map.",
                                             "%s: %s" % (pref, show(value))))
            rows.append({"deliverable": d["name"], "pref": pref, "value": show(value),
                         "in_command": bool(ok), "visible": vis, "known": True})
    _lib.write_json("prefs.json", rows)
    _lib.emit_findings(NODE, findings)


if __name__ == "__main__":
    main()
