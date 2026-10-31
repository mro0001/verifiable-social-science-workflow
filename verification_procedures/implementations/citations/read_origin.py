"""Read each citation's origin from the citation provenance record (the authors' steps 2 and 4).

The record, citation_provenance.yaml, holds an entry under works for each work in the
reference list, with its origin (ai, scholar, or unknown), every appearance in the record
in time order, the first AI appearance, and the first scholar appearance (Track C2 plan
choice 2). A row takes its work's origin, and its evidence is the first appearance of
that origin, with the time, the session's public id or the artifact's path, and the
excerpt. A key the record holds no entry for is unknown.

sessions lists the public ids of the sessions in which an AI named the work, in the
order they first did, for an AI citation only. An AI citation and a citation of unknown
origin need the scholar's decision, and the scholar's own citation, which step 3 leaves
out, needs none. The scholar's citations and those of unknown origin are each a note."""
import _lib

ORIGINS = ("ai", "scholar", "unknown")
WHO = {"ai": "an AI", "scholar": "the scholar"}

# How the record named the work, by the appearance's kind, as the provenance record
# gives it. A record written before appearances had a kind gives none, and the line
# then says nothing of it.
SHELL = ("Bash", "shell")


def how(first):
    """The words that say how the record named the work, or empty text."""
    kind, by, tool = text(first.get("kind")), text(first.get("by")), text(first.get("tool"))
    if kind == "conversation":
        return "in the AI's own words" if by == "ai" else "in the scholar's own words"
    if kind == "harness":
        return "in text the harness put in the conversation, such as a finished task's notice or a summary"
    if kind == "artifact":
        return "in a file an AI wrote"
    if kind == "fetched":
        return "in a source the AI fetched"
    if kind == "read":
        what = "a file an AI wrote" if by == "ai" else "a file"
        return "in %s that the AI read%s" % (what, " with %s" % tool if tool else "")
    if kind == "tool":
        if tool in SHELL:
            return "in the output of a shell command the AI ran"
        return "in the result of the AI's %s call" % tool if tool else "in a tool's result"
    if kind == "event":
        return "in a wrapper event"
    return ""


def text(value):
    return value if isinstance(value, str) else ("" if value is None else str(value))


def evidence(origin, first):
    """The record's evidence for the origin, as one line of text."""
    parts = ["First named by %s" % WHO[origin]]
    if text(first.get("time")):
        parts.append("at %s" % text(first["time"]))
    if text(first.get("session_ref")):
        parts.append("in session %s" % text(first["session_ref"]))
    if text(first.get("artifact")):
        parts.append("in %s" % text(first["artifact"]))
    line = " ".join(parts)
    named = how(first)
    if named:
        line += ", " + named
    excerpt = text(first.get("excerpt")).strip()
    if excerpt:
        return line + ", where the record reads \"%s\"%s" % (excerpt, "" if excerpt[-1] in ".!?" else ".")
    return line + "."


rows = _lib.read_json("rows.json")
prov = _lib.read_yaml("citation_provenance.yaml") or {}
works = prov.get("works") if isinstance(prov, dict) else None
works = works if isinstance(works, dict) else {}

findings, out = [], []
for r in rows:
    key = r["citekey"]
    work = works.get(key)
    sessions = []
    if not isinstance(work, dict):
        origin = "unknown"
        line = "The provenance record has no entry for @%s." % key
        findings.append(_lib.finding(
            "read_origin", "info", r["id"],
            "the provenance record has no entry for @%s, so its origin is unknown and it is not checked" % key,
            "citation_provenance.yaml"))
    else:
        origin = work.get("origin") if work.get("origin") in ORIGINS else "unknown"
        first = work.get("first_ai" if origin == "ai" else "first_scholar")
        if origin != "unknown" and isinstance(first, dict):
            line = evidence(origin, first)
        elif origin != "unknown":
            line = "First named by %s, and the record gives no appearance." % WHO[origin]
        else:
            line = "The record never names @%s." % key
        if origin == "ai":
            # The session where the AI first named the work, the first AI appearance that
            # names a session, since a work can be named in dozens of later sessions.
            for app in work.get("appearances") or []:
                ref = text(app.get("session_ref")) if isinstance(app, dict) else ""
                if isinstance(app, dict) and app.get("by") == "ai" and ref:
                    sessions.append(ref)
                    break
        if origin == "scholar":
            findings.append(_lib.finding(
                "read_origin", "info", r["id"],
                "@%s was first named by the scholar in the record, so it is not checked further" % key,
                "citation_provenance.yaml"))
        elif origin == "unknown":
            findings.append(_lib.finding(
                "read_origin", "info", r["id"],
                "the record never names @%s, so its origin is unknown and it is not checked" % key,
                "citation_provenance.yaml"))
    out.append(dict(r, origin=origin, origin_evidence=line, sessions=sessions,
                    needs_decision=origin != "scholar"))

_lib.write_json("rows_origin.json", out)
_lib.emit_findings("read_origin", findings)
