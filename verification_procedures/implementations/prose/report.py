"""report: the prose stream's fill function. The step outputs fill the fields of
schemas/prose.yaml (copied beside this file as schema.yaml) with the wording the report
shows, and the one report builder writes fields.json, findings.json, and report.md.

The report is a verification step for the scholar, and no model decides anything in it.
It lists every change between the scholar's last draft and the final build's text. Each
AI change, a change the record names, is shown with its sentence before and after, the
reason the record gives or a note that none is recorded, and the content it alters, and
it is an item for the scholar to approve or hold. The block lines join the whitespace of
their text into single spaces, so a reason written over several lines stays on its line,
while the item's rationale keeps it word for word. The scholar's own changes are listed in
a table and not checked. One Trail line per change names the step records that touched
it.

Record numbers. Every edge in graphs/prose.yaml is unconditional, so the run order is
fixed (the graph's topological order) and STEPS gives each record's sequence number. If a
conditional edge is ever added, this must change.

A change whose record entry gives its session's public id carries it in sessions, and the
report names the session on a line of its own below the AI changes.
"""
import difflib

import _lib
import _report

STEPS = ["pin_versions", "diff_changes", "exclude_author", "content_handoff",
         "rationale_coverage", "report"]
SEQ = {n: f"{i:02d}" for i, n in enumerate(STEPS, 1)}

pins = _lib.read_json("pins.json")
changes = _lib.read_json("changes.json")
ai = {c["id"]: c for c in _lib.read_json("ai_changes.json")}
author = {c["id"]: c for c in _lib.read_json("author_changes.json")}
handoff = {h["change_id"]: h for h in _lib.read_json("handoff.json")}

allf = _lib.collect_findings()
by_item = {}
for f in allf:
    if f["severity"] != "info":
        by_item.setdefault(f["item"], []).append(f["check"])


def one_line(s):
    """Text on one line of a block, its whitespace joined into single spaces, so that no part
    of a reason over several lines can start a heading or a list item in the report. Every
    word is kept."""
    return " ".join(str(s).split())


def short(s, n=90):
    return _lib.cell(s, n) if s else "(none)"


def word_diff(before, after, keep=3):
    """Inline word diff, [-old-] {+new+}, with long unchanged runs elided."""
    a, b = before.split(), after.split()
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            run = a[i1:i2]
            if len(run) > 2 * keep + 1:
                run = (run[:keep] if out else []) + ["…"] + run[-keep:]
            out += run
            continue
        if i2 > i1:
            out.append("[-" + " ".join(a[i1:i2]) + "-]")
        if j2 > j1:
            out.append("{+" + " ".join(b[j1:j2]) + "+}")
    return " ".join(out)


def what_changed(c):
    if c["kind"] == "move":
        return "(moved, text unchanged) " + short(c["after"], 70)
    if c["kind"] == "insert":
        return "{+" + short(c["after"]) + "+}"
    if c["kind"] == "delete":
        return "[-" + short(c["before"]) + "-]"
    return _lib.cell(word_diff(c["before"], c["after"]), 200)


def content_text(h):
    """The content an AI change alters, as the hand-off found it, and the streams it goes to."""
    parts = ["{} {} -> {}".format(k, ", ".join(v["removed"]) or "(none)", ", ".join(v["added"]) or "(none)")
             for k, v in sorted(h["token_diff"].items())]
    return "{}, for the {} stream".format("; ".join(parts), "/".join(h["streams"]))


b, r = pins["baseline"], pins["revised"]
counts = {k: sum(1 for c in changes if c["kind"] == k) for k in ("edit", "insert", "delete", "move")}
run = {"baseline_file": "{}".format(b["file"]), "baseline_version": "{}".format(b["version"] or "not pinned"),
       "baseline_sha256": "{}".format(b["sha256"]),
       "revised_file": "{}".format(r["file"]), "revised_version": "{}".format(r["version"] or "not ledgered"),
       "revised_sha256": "{}".format(r["sha256"]),
       "n_changes": len(changes), "n_edit": counts["edit"], "n_insert": counts["insert"],
       "n_delete": counts["delete"], "n_move": counts["move"],
       "n_ai": len(ai), "n_author": len(author),
       "n_no_reason": sum(1 for c in ai.values() if not c["rationale"]),
       "n_handoff": len(handoff)}


def trail_line(c):
    cid = c["id"]
    steps = ["diff_changes ({}, python3)".format(SEQ["diff_changes"])]
    if cid in author:
        steps.append("exclude_author ({}, the scholar's own change, not checked)".format(SEQ["exclude_author"]))
    else:
        steps.append("exclude_author ({}, record {})".format(SEQ["exclude_author"], ai[cid]["record_id"]))
        steps.append("content_handoff ({}, {})".format(
            SEQ["content_handoff"], "/".join(handoff[cid]["streams"]) if cid in handoff else "no content tokens"))
        steps.append("rationale_coverage ({}, {})".format(
            SEQ["rationale_coverage"], "reason recorded" if ai[cid]["rationale"] else "no reason recorded"))
    flagged = sorted(set(by_item.get(cid, [])))
    return "{} went through {}{}".format(cid, " -> ".join(steps), "; flagged by " + ", ".join(flagged) if flagged else "")


def change_items():
    """One item for each change, giving its kind and the revised sentence (the deleted one
    for a delete) cut to 120 characters, then one item for each other group of problems. The
    scholar's own change needs no decision, and every AI change needs one. A problem found
    on a change's own id is carried by its row."""
    attached, problems = _lib.problem_items(allf, [c["id"] for c in changes])
    rows = []
    for c in changes:
        cid = c["id"]
        text = c["before"] if c["kind"] == "delete" else c["after"]
        row = {"id": cid, "kind": "change",
               "summary": "%s: %s" % (c["kind"], text[:_lib.SUMMARY_MESSAGE_CHARS]),
               "findings": attached.get(cid, []), "needs_decision": cid not in author,
               "change_kind": c["kind"], "before": c["before"], "after": c["after"],
               "moved": bool(c.get("moved")), "by": "author" if cid in author else "ai",
               "kind_cell": c["kind"] + (" (moved)" if c.get("moved") and c["kind"] != "move" else ""),
               "change_cell": what_changed(c),
               "trail": trail_line(c)}
        if cid in ai:
            a = ai[cid]
            h = handoff.get(cid)
            row["record_id"] = a["record_id"]
            if a["rationale"]:
                row["rationale"] = a["rationale"]
            row["before_cell"] = one_line(c["before"]) or "(none)"
            row["after_cell"] = one_line(c["after"]) or "(none)"
            row["reason_cell"] = one_line(a["rationale"]) or "No reason is recorded."
            row["streams"] = list(h["streams"]) if h else []
            if h:
                row["content_cell"] = one_line(content_text(h))
            if a.get("session_ref"):
                row["sessions"] = [a["session_ref"]]
                row["session_line"] = a["session_ref"]
        rows.append(row)
    return rows + problems


def handoff_rows():
    rows = []
    for cid in sorted(handoff):
        h = handoff[cid]
        diffs = "; ".join("{} {} -> {}".format(k, ", ".join(v["removed"]) or "(none)", ", ".join(v["added"]) or "(none)")
                          for k, v in sorted(h["token_diff"].items()))
        rows.append({"change": "{}".format(cid), "streams": "/".join(h["streams"]), "token_diffs": _lib.cell(diffs, 200)})
    return rows


_report.build({"run": run, "items": change_items(), "tables": {"handoff": handoff_rows()}})
