"""Exit step: findings.json and report.md in the agreed shape. Counts first
(verified / problems / couldn't check / author's warrant), problems first, then
every row: claim, reference, passage + location, verdict + reason, access,
proposed fix, origin, trail (who checked, which retrieved copy, which records)."""
import _lib

# Step order as the runtime walks graphs/citations.yaml (topological order).
# Which settle node ran depends on whether any verdict needed a second check.
BEFORE = ["pin_document", "extract_citations", "attribute_origin", "match_references", "fetch_metadata",
          "check_existence", "pin_sources", "reuse_prior", "check_access", "locate_passage",
          "verify_quote", "judge_support", "collect_verdicts"]
AFTER_SECOND = ["second_check", "settle_verdicts", "draft_fix", "record_verdicts", "report"]
AFTER_NONE = ["settle_unanimous", "draft_fix", "record_verdicts", "report"]

ORIGIN = {
    "yours": "yours (author's source, author's sentence)",
    "ai_added": "ai_added (AI introduced the source)",
    "ai_reworded": "ai_reworded (author's source, AI rewrote the sentence)",
    "ai_sourced_author_worded": "ai_sourced_author_worded (AI suggested the source; author reworded or moved the sentence)",
    "unknown": "unknown (no log entry; checked as if AI)",
}
VERDICT = {"supports": "supports", "partly": "partly supports", "does_not_support": "does not support",
           "not_checked": "not checked"}
ACCESS = {"fulltext": "full text", "abstract": "abstract only", "none": "no retrieved copy"}

rows = _lib.read_json("rows_final.json")
tally = _lib.read_json("verdict_tally.json")
pin = _lib.read_json("doc_pin.json")
findings = _lib.collect_findings()

order = BEFORE + (AFTER_SECOND if tally["to_recheck"] > 0 else AFTER_NONE)
seq = {node: "%02d_%s" % (i + 1, node) for i, node in enumerate(order)}


def short(h):
    return h[:19] + "..." if h else ""


def trail(r):
    parts = []
    if r["status"] == "checking":
        parts.append("passage located by %s (record %s), checked mechanically (record %s), verdict by %s (record %s)"
                     % (r.get("locate_executor") or "?", seq["locate_passage"], seq["verify_quote"],
                        r.get("judge_executor") or "?", seq["judge_support"]))
        if r.get("second_executor"):
            parts.append("second check by %s (record %s)" % (r["second_executor"], seq["second_check"]))
    elif r["status"] == "reused":
        p = r.get("prior", {})
        parts.append("verdict carried over from the check by %s on %s (record %s)"
                     % (p.get("checked_by", "?"), p.get("checked_on", "?"), seq["reuse_prior"]))
    if r["citekey"] and r["status"] != "author":
        parts.append("reference checked (records %s, %s)" % (seq["fetch_metadata"], seq["check_existence"]))
    if r.get("source_file"):
        parts.append("retrieved copy %s %s" % (r["source_file"], short(r.get("source_sha256", ""))))
    if r.get("fix_executor"):
        parts.append("fix proposed by %s (record %s)" % (r["fix_executor"], seq["draft_fix"]))
    parts.append("times: each record's started_at")
    return "; ".join(parts)


def block(r):
    access = ACCESS.get(r.get("access", "none"), r.get("access", ""))
    verdict = VERDICT.get(r["verdict"], r["verdict"])
    if r.get("access") == "abstract" and r["verdict"] != "not_checked":
        verdict += " (abstract only)"
    if r.get("disputed"):
        verdict += "; second checker says %s" % VERDICT.get(r["second_verdict"], r["second_verdict"] or "nothing")
    elif r.get("second_verdict"):
        verdict += "; second checker agrees"
    lines = ["### %s: %s, @%s" % (r["id"], verdict, r["citekey"]), "",
             "- **Claim:** %s" % r["sentence"],
             "- **Reference:** %s Check: %s." % (r.get("reference", ""), r.get("reference_check", "").rstrip("."))]
    if r.get("passage"):
        lines.append("- **Passage:** \"%s\" (%s)" % (r["passage"], r.get("location") or "location not given"))
    elif r["status"] in ("checking", "reused"):
        lines.append("- **Passage:** none located")
    reason = r.get("reason", "")
    lines.append("- **Verdict:** %s. %s" % (verdict, reason[:1].upper() + reason[1:]))
    lines.append("- **Access:** %s" % access)
    if r.get("issues"):
        label = "Problems found" if r["category"] == "problem" else "Flags"
        lines.append("- **%s:** %s" % (label, "; ".join(r["issues"])))
    if r["category"] == "problem":
        lines.append("- **Proposed fix:** %s" % (r.get("fix") or "none proposed"))
    lines.append("- **Origin:** %s%s" % (ORIGIN.get(r["origin"], r["origin"]),
                                          "; sentence moved, text unchanged" if r.get("moved") else ""))
    lines.append("- **Trail:** %s" % trail(r))
    return "\n".join(lines)


groups = [("problem", "Problems"), ("not_checked", "Couldn't check"), ("verified", "Verified")]
counts = {k: sum(1 for r in rows if r["category"] == k) for k in ("problem", "not_checked", "verified", "author")}
abstract_verified = sum(1 for r in rows if r["category"] == "verified" and r.get("access") == "abstract")
reused = sum(1 for r in rows if r["status"] == "reused")

intro = "\n".join([
    "Document: `draft.md` (%s). Only AI-contributed citations are checked; a citation the author "
    "introduced, in a sentence the author wrote, is listed as the author's warrant and not checked." % pin["draft_sha256"],
    "",
    "**%d citation rows: %d verified, %d problems, %d couldn't check, %d author's warrant (not checked).**"
    % (len(rows), counts["verified"], counts["problem"], counts["not_checked"], counts["author"]),
    "",
    "- Verified on the abstract only: %d. Verdicts carried over from an earlier check: %d." % (abstract_verified, reused),
    "- To confirm any verdict: open the retrieved copy named in its trail, search for the quoted passage, "
    "and read it beside the claim. Every ask and answer is saved under `prompts/` and `responses/` in the run folder.",
])

body = []
for key, heading in groups:
    sel = [r for r in rows if r["category"] == key]
    body.append("**%s (%d)**" % (heading, len(sel)))
    body.append("")
    body.extend(block(r) + "\n" for r in sel)
    if not sel:
        body.append("None.\n")
mine = [r for r in rows if r["category"] == "author"]
body.append("**Author's warrant, not checked (%d)**" % len(mine))
body.append("")
for r in mine:
    body.append("- %s, @%s: %s%s" % (r["id"], r["citekey"], r["sentence"],
                                      " (moved, text unchanged)" if r.get("moved") else ""))
if not mine:
    body.append("None.")

_lib.write_json("findings.json", findings)
_lib.write_text("report.md", _lib.report("Citation verification report", intro, findings,
                                         sections=[("Rows", "\n".join(body))]))
