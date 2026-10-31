"""Record the independent second check beside the first verdict. A disagreement
marks the row disputed; the first verdict is kept and both are shown."""
import _lib

rows = _lib.read_json("rows_judged.json")
second = {a["item_id"]: a for a in _lib.read_json("second_check.json")}
out = []
for r in rows:
    row = dict(r, disputed=False, second_verdict="", second_reason="", second_executor="",
               second_prompt_sha256="")
    s = second.get(r["id"])
    if s is not None:
        agree = bool(s.get("agree")) and s.get("verdict") == r["verdict"]
        row.update(disputed=not agree, second_verdict=s.get("verdict", ""), second_reason=s.get("reason", ""),
                   second_executor=s.get("executor", ""), second_prompt_sha256=s.get("prompt_sha256", ""))
    out.append(row)
_lib.write_json("rows_settled.json", out)
