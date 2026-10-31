"""Turn verdicts into findings (under the judgment step that reached them) and
attach proposed fixes to rows. does_not_support -> blocking; partly -> warning;
checkers disagree -> warning."""
import _lib

rows = _lib.read_json("rows_settled.json")
fixes = {a["item_id"]: a for a in _lib.read_json("draft_fix.json")}
support, second, out = [], [], []
for r in rows:
    fx = fixes.get(r["id"])
    out.append(dict(r, fix=(fx or {}).get("fix", ""), fix_executor=(fx or {}).get("executor", "")))
    if r["status"] != "checking":
        continue
    if r["verdict"] == "does_not_support":
        support.append(_lib.finding("judge_support", "blocking", r["id"],
                                    "source does not support the claim: " + r["reason"],
                                    _lib.cell(r.get("passage", ""), 120)))
    elif r["verdict"] == "partly":
        support.append(_lib.finding("judge_support", "warning", r["id"],
                                    "source only partly supports the claim: " + r["reason"],
                                    _lib.cell(r.get("passage", ""), 120)))
    if r.get("disputed"):
        second.append(_lib.finding("second_check", "warning", r["id"],
                                   "the two checkers disagree (%s vs %s): %s"
                                   % (r["verdict"], r["second_verdict"] or "no answer", r["second_reason"]),
                                   r.get("second_executor", "")))
_lib.write_json("rows_final.json", out)
_lib.emit_findings("judge_support", support)
_lib.emit_findings("second_check", second)
