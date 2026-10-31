"""report: judge answers become findings; findings.json and report.md.

A judge answer with honest=false or meaning_changed=true is a warning on that
change. The report lists every change between the pinned versions, AI and
author, with its rationale, verdict, and hand-off, then one Trail line per
change naming the step records that touched it.

Record numbers: every edge in graphs/prose.yaml is unconditional, so the run
order is fixed (the graph's topological order) and STEPS gives each record's
sequence number. If a conditional edge is ever added, this must change.
"""
import difflib

import _lib

STEPS = ["pin_versions", "diff_changes", "exclude_author", "content_handoff",
         "rationale_coverage", "judge_rationale", "report"]
SEQ = {n: f"{i:02d}" for i, n in enumerate(STEPS, 1)}

pins = _lib.read_json("pins.json")
changes = _lib.read_json("changes.json")
author = {c["id"]: c for c in _lib.read_json("author_changes.json")}
items = {it["id"]: it for it in _lib.read_json("judge_items.json")}
answers = {a["item_id"]: a for a in _lib.read_json("judge_rationale.json")}
handoff = {h["change_id"]: h for h in _lib.read_json("handoff.json")}

jf = []
for cid in sorted(answers):
    a = answers[cid]
    honest, changed = a.get("honest") is True, a.get("meaning_changed") is True
    if honest and not changed:
        continue
    if not honest and changed:
        msg = "rationale misdescribes the change, and the change alters meaning"
    elif not honest:
        msg = "rationale misdescribes the change"
    else:
        msg = "change alters meaning beyond what the rationale says"
    jf.append(_lib.finding("judge_rationale", "warning", cid, msg,
                           "{} ({})".format(_lib.cell(a.get("reason", ""), 120), a.get("executor", ""))))
_lib.emit_findings("judge_rationale", jf)
allf = _lib.collect_findings()
by_item = {}
for f in allf:
    if f["severity"] != "info":
        by_item.setdefault(f["item"], []).append(f["check"])


def verdict(cid):
    if cid in author:
        return "author edit: listed, not judged"
    if cid not in items:
        return "SILENT: no rationale"
    a = answers.get(cid)
    if a is None:
        return "not judged (no answer)"
    if a.get("honest") is True and a.get("meaning_changed") is not True:
        return "honest"
    parts = []
    if a.get("honest") is not True:
        parts.append("rationale misdescribes")
    if a.get("meaning_changed") is True:
        parts.append("meaning changed")
    return "; ".join(parts)


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


b, r = pins["baseline"], pins["revised"]
versions = "\n".join([
    "- Baseline: `{}` {} {}".format(b["file"], b["version"] or "NOT PINNED", b["sha256"]),
    "- Revised: `{}` {} {}".format(r["file"], r["version"] or "(not ledgered)", r["sha256"]),
])

rows = ["| Id | Kind | Change (before -> after) | Rationale | Verdict | Hand-off |", "|---|---|---|---|---|---|"]
for c in changes:
    cid = c["id"]
    kind = c["kind"] + (" (moved)" if c.get("moved") and c["kind"] != "move" else "")
    it = items.get(cid)
    rat = "{}: {}".format(it["rationale_id"], it["rationale"]) if it else ("author" if cid in author else "(none)")
    h = handoff.get(cid)
    rows.append("| {} | {} | {} | {} | {} | {} |".format(
        cid, kind, what_changed(c), _lib.cell(rat, 90), verdict(cid),
        "/".join(h["streams"]) if h else "-"))
table = "\n".join(rows)

counts = {k: sum(1 for c in changes if c["kind"] == k) for k in ("edit", "insert", "delete", "move")}
overview = ("Changes between the pinned versions: {} (edit {}, insert {}, delete {}, move {}); "
            "AI {}, author {}. Judged: {}. Handed off to another stream: {}.").format(
    len(changes), counts["edit"], counts["insert"], counts["delete"], counts["move"],
    len(changes) - len(author), len(author), len(answers), len(handoff))

hand = ["| Change | Streams | Token differences |", "|---|---|---|"]
for cid in sorted(handoff):
    h = handoff[cid]
    diffs = "; ".join("{}: {} -> {}".format(k, ", ".join(v["removed"]) or "(none)", ", ".join(v["added"]) or "(none)")
                      for k, v in sorted(h["token_diff"].items()))
    hand.append("| {} | {} | {} |".format(cid, "/".join(h["streams"]), _lib.cell(diffs, 200)))
hand_body = "\n".join(hand) if handoff else "None."

trail = []
for c in changes:
    cid = c["id"]
    steps = ["diff_changes ({}, python3)".format(SEQ["diff_changes"])]
    if cid in author:
        steps.append("exclude_author ({}, claim {})".format(SEQ["exclude_author"], author[cid]["author_claim"]))
    else:
        steps.append("content_handoff ({}, {})".format(
            SEQ["content_handoff"], "/".join(handoff[cid]["streams"]) if cid in handoff else "no content tokens"))
        it = items.get(cid)
        steps.append("rationale_coverage ({}, {})".format(SEQ["rationale_coverage"],
                                                          it["rationale_id"] if it else "no rationale"))
        a = answers.get(cid)
        if a is not None:
            steps.append("judge_rationale ({}, {}, prompt {})".format(
                SEQ["judge_rationale"], a.get("executor", "?"), str(a.get("prompt_sha256", ""))[:19]))
    flagged = sorted(set(by_item.get(cid, [])))
    trail.append("- {}: {}{}".format(cid, " -> ".join(steps),
                                     "; flagged by " + ", ".join(flagged) if flagged else ""))

_lib.write_json("findings.json", allf)
_lib.write_text("report.md", _lib.report(
    "Prose verification",
    "Every AI change between two pinned versions must be visible, carry a rationale, and have that "
    "rationale describe it honestly. Changes that touch numbers, citations, quotations, negation, or "
    "claim strength are handed to the data or citations stream. Author edits are listed, not judged.\n\n"
    + overview,
    allf,
    sections=[("Versions", versions), ("Changes", table), ("Hand-off", hand_body),
              ("Trail", "Record numbers refer to `records/NN_<step>.json` in the run folder.\n\n"
               + "\n".join(trail))]))
