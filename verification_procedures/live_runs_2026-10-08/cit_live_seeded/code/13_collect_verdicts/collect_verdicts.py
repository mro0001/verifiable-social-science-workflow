"""Join each row with its verdict and every finding that touches it (by row id,
or by citekey for rows that were checked). A row is a problem when a blocking
finding touches it, when its reference metadata or quote checks failed, or when
its verdict is not supports. Rows whose fresh verdict is not supports are marked
for the independent second check; verdict_tally.json counts them."""
import _lib

FINDINGS = ["attribute_origin", "match_references", "check_existence", "reuse_prior",
            "check_access", "verify_quote"]
PROBLEM_CHECKS = {"match_references", "check_existence", "verify_quote"}

rows = _lib.read_json("rows_quoted.json")
verdicts = {a["item_id"]: a for a in _lib.read_json("judge_support.json")}
refs = {r["id"]: r for r in _lib.read_json("refs_verified.json")}
found = []
for name in FINDINGS:
    found.extend(_lib.read_json("findings_%s.json" % name))

out, to_recheck, problems = [], 0, 0
for r in rows:
    row = dict(r)
    checked = r["status"] != "author"
    issues = [f for f in found if f["severity"] != "info"
              and (f["item"] == r["id"] or (checked and f["item"] == r["citekey"]))]
    ref = refs.get(r["citekey"])
    if not checked:
        ref_check = "not checked (author's warrant)"
    elif ref is None:
        ref_check = "no reference entry" if not any(f["check"] == "match_references" for f in issues) \
            else "cited key has no entry in the reference list"
    else:
        ref_check = ref["status"]
    row.setdefault("passage", "")
    row.setdefault("location", "")
    row.update(reference_check=ref_check, issues=[f["message"] for f in issues],
               judge_executor="", judge_prompt_sha256="", recheck=False)
    if r["status"] == "checking":
        v = verdicts.get(r["id"]) or {"verdict": "not_checked", "reason": "no verdict returned"}
        row.update(verdict=v["verdict"], reason=v.get("reason", ""),
                   judge_executor=v.get("executor", ""), judge_prompt_sha256=v.get("prompt_sha256", ""))
        row["recheck"] = v["verdict"] in ("partly", "does_not_support")
    elif r["status"] == "reused":
        p = r["prior"]
        row.update(verdict=p.get("verdict", "not_checked"), reason=p.get("reason", ""),
                   passage=p.get("quote", ""), location=p.get("location", ""),
                   judge_executor=p.get("checked_by", ""))
    elif r["status"] == "author":
        row.update(verdict="not_checked", reason="author's warrant: the author's source in the author's sentence")
    else:
        row.update(verdict="not_checked", reason="no usable retrieved copy")
    blocking = any(f["severity"] == "blocking" for f in issues)
    tool_problem = any(f["check"] in PROBLEM_CHECKS for f in issues)
    row["problem"] = checked and (blocking or tool_problem or row["verdict"] in ("partly", "does_not_support"))
    if not checked:
        row["category"] = "author"
    elif row["problem"]:
        row["category"] = "problem"
    elif row["verdict"] == "not_checked":
        row["category"] = "not_checked"
    else:
        row["category"] = "verified"
    to_recheck += int(row["recheck"])
    problems += int(row["problem"])
    out.append(row)

_lib.write_json("rows_judged.json", out)
_lib.write_json("verdict_tally.json", {"to_recheck": to_recheck, "problems": problems, "rows": len(out)})
