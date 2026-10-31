"""Shared helpers for tool steps. Copied beside each step's code in the run, so a
replay uses exactly the helpers the step ran with.

Tool-step contract (FROZEN):
  python3 <node>.py <files_dir>
  - reads only the files its contract lists, from <files_dir>
  - writes only new files into <files_dir>; never overwrites (the runtime fails the step)
  - deterministic: no timestamps, no randomness, sorted output, so replay matches by hash
  - a check step writes findings_<node>.json (possibly an empty list)

Finding (FROZEN):
  {"check": <node id>, "severity": "blocking"|"warning"|"info",
   "item": <what it is about: row id, file, key, change id>,
   "message": <one sentence>, "evidence": <short quote, hash, or path>}
"""
import glob
import json
import os
import re
import sys
import unicodedata

SEVERITY_ORDER = {"blocking": 0, "warning": 1, "info": 2}


def files_dir():
    return sys.argv[1]


def path(name):
    return os.path.join(files_dir(), name)


def read_text(name):
    with open(path(name), encoding="utf-8") as f:
        return f.read()


def read_json(name):
    with open(path(name), encoding="utf-8") as f:
        return json.load(f)


def read_yaml(name):
    import yaml
    with open(path(name), encoding="utf-8") as f:
        return yaml.safe_load(f)


def write_json(name, obj):
    with open(path(name), "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write("\n")


def write_text(name, text):
    with open(path(name), "w", encoding="utf-8") as f:
        f.write(text)


def finding(check, severity, item, message, evidence=""):
    assert severity in SEVERITY_ORDER, severity
    return {"check": check, "severity": severity, "item": str(item), "message": message,
            "evidence": evidence}


def emit_findings(check, findings):
    findings = sorted(findings, key=lambda x: (SEVERITY_ORDER[x["severity"]], x["item"], x["message"]))
    write_json(f"findings_{check}.json", findings)


def collect_findings():
    out = []
    for p in sorted(glob.glob(os.path.join(files_dir(), "findings_*.json"))):
        with open(p, encoding="utf-8") as f:
            out.extend(json.load(f))
    return sorted(out, key=lambda x: (SEVERITY_ORDER[x["severity"]], x["check"], x["item"], x["message"]))


# The severities a scholar must decide on. Info findings make no item.
PROBLEM_SEVERITIES = ("blocking", "warning")
SUMMARY_MESSAGE_CHARS = 120


def problem_items(findings, row_ids):
    """Group every blocking or warning finding by its item. A group whose item is a row id
    is returned in the first value, keyed by that row, for the row to carry. Every other
    group becomes one item of kind finding that needs a decision, with a summary giving the
    number of problems and the first message cut to 120 characters. Groups keep the order
    in which their first finding appears. The same rule as the results file's items, used
    by the build, data, and prose streams' fill functions."""
    rows = set(row_ids)
    groups = {}
    for f in findings:
        if f["severity"] not in PROBLEM_SEVERITIES:
            continue
        groups.setdefault(str(f["item"]), []).append(
            {"check": f["check"], "severity": f["severity"], "message": f["message"],
             "evidence": f.get("evidence", "")})
    attached, items = {}, []
    for key, found in groups.items():
        if key in rows:
            attached[key] = found
            continue
        count = "%d %s" % (len(found), "problem" if len(found) == 1 else "problems")
        items.append({"id": key, "kind": "finding",
                      "summary": count + ". " + found[0]["message"][:SUMMARY_MESSAGE_CHARS],
                      "findings": found, "needs_decision": True})
    return attached, items


def report(title, intro, findings, sections=(), ranked=True):
    """Summary first, problems first. sections: [(heading, markdown body)].

    A report that ranks nothing (ranked=False), whose findings are all notes for the
    scholar, leaves out the Summary and Problems sections, so it never reads as if
    nothing needed the scholar's look."""
    lines = [f"# {title}", "", intro, ""]
    if ranked:
        counts = {s: sum(1 for x in findings if x["severity"] == s) for s in SEVERITY_ORDER}
        lines += ["## Summary", "",
                  f"- Blocking: {counts['blocking']}",
                  f"- Warnings: {counts['warning']}",
                  f"- Notes: {counts['info']}", "",
                  "## Problems", ""]
        probs = [x for x in findings if x["severity"] != "info"]
        if probs:
            lines += ["| Severity | Check | Item | Problem | Evidence |", "|---|---|---|---|---|"]
            for x in probs:
                lines.append("| {} | {} | {} | {} | {} |".format(
                    x["severity"], x["check"], cell(x["item"]), cell(x["message"]), cell(x["evidence"])))
        else:
            lines.append("None.")
        lines.append("")
    for heading, body in sections:
        lines += [f"## {heading}", "", body.rstrip(), ""]
    notes = [x for x in findings if x["severity"] == "info"]
    lines += ["## Notes", ""]
    lines += [f"- {x['check']} / {x['item']}: {x['message']}" for x in notes] or ["None."]
    lines.append("")
    return "\n".join(lines)


def cell(s, limit=160):
    s = str(s).replace("|", "\\|").replace("\n", " ")
    return s if len(s) <= limit else s[:limit - 1] + "…"


# ---------------------------------------------------------------- text

def norm(s):
    """Normalize for mechanical matching: unicode, quotes, dashes, whitespace, case."""
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("\u201c", '"').replace("\u201d", '"').replace("\u2018", "'").replace("\u2019", "'")
    s = s.replace("\u2013", "-").replace("\u2014", "-").replace("\u00ad", "")
    s = re.sub(r"-\s*\n\s*", "", s)  # hyphenation across line breaks
    s = re.sub(r"\s+", " ", s)
    return s.strip().lower()


def sentences(text):
    """Split markdown prose into sentences, keeping paragraph order. Headings,
    blank lines, and front matter are skipped."""
    body = re.sub(r"^---\n.*?\n---\n", "", text, flags=re.S)
    out = []
    for para in re.split(r"\n\s*\n", body):
        para = para.strip()
        if not para or para.startswith("#"):
            continue
        para = re.sub(r"\s+", " ", para)
        for s in re.split(r"(?<=[.!?])\s+(?=[A-Z\"(\[])", para):
            if s.strip():
                out.append(s.strip())
    return out


NUMBER = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?%?")


def numbers_in(s):
    return [n.rstrip(",") for n in NUMBER.findall(s)]
