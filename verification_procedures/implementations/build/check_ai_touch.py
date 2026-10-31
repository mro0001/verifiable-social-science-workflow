"""check_ai_touch: only the build writes deliverables.

session_writes.jsonl stands in for the session record: one line per file write,
{session, actor: ai|author|build, tool, path}. Protected paths are every builds dir
in the map plus ship/.
- ai write to a protected path -> blocking, even if later restored
- author write inside a builds dir, outside returns/ -> warning (builds are never edited)
- build write that did not come from `make <its deliverable>` -> warning
- ai writes to canonical sources are expected and only counted
A line that gives its session's public id, session_ref, puts it on the finding for an
AI write, so the report can name the session.
"""
import json
import posixpath

import _lib

NODE = "check_ai_touch"


def main():
    m = _lib.read_json("map.json")
    owners = {d["builds_dir"] + "/": d["name"] for d in m["deliverables"] if d["builds_dir"]}
    canon = {d["source"] for d in m["deliverables"]}
    findings, ai_canon = [], 0
    for n, line in enumerate(_lib.read_text("session_writes.jsonl").splitlines(), 1):
        if not line.strip():
            continue
        try:
            w = json.loads(line)
            actor, path, tool, session = w["actor"], posixpath.normpath(w["path"]), w.get("tool", ""), w.get("session", "")
        except (ValueError, KeyError, AttributeError):
            findings.append(_lib.finding(NODE, "warning", "session_writes.jsonl:%d" % n,
                                         "Unreadable record line; a write that cannot be read cannot be cleared.", line[:80]))
            continue
        owner = next((owners[p] for p in owners if path.startswith(p)), None)
        protected = owner is not None or path.startswith("ship/")
        ev = "session %s, %s via %s" % (session, actor, tool)
        if actor == "ai":
            if protected:
                found = _lib.finding(NODE, "blocking", path,
                                     "AI touched the deliverable directly; only the map's build rule may write here.", ev)
                if isinstance(w.get("session_ref"), str) and w["session_ref"]:
                    found["session_ref"] = w["session_ref"]
                findings.append(found)
            elif path in canon:
                ai_canon += 1
        elif actor == "author":
            if owner and "/returns/" not in path:
                findings.append(_lib.finding(NODE, "warning", path,
                                             "Hand edit inside a builds dir; builds are never edited (save reviews to returns/).", ev))
        elif actor == "build":
            if owner and tool.strip() != "make " + owner:
                findings.append(_lib.finding(NODE, "warning", path,
                                             "Build write that did not come from this deliverable's make rule.", ev))
            elif path.startswith("ship/") and not tool.startswith("make "):
                findings.append(_lib.finding(NODE, "warning", path, "Write to ship/ outside make.", ev))
        else:
            findings.append(_lib.finding(NODE, "warning", path, "Unknown actor in the trace.", ev))
    findings.append(_lib.finding(NODE, "info", "canonical sources",
                                 "%d AI write(s) to canonical sources; that is where AI works." % ai_canon, ""))
    _lib.emit_findings(NODE, findings)


if __name__ == "__main__":
    main()
