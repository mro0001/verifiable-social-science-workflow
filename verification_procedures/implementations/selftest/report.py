import _lib
ans = _lib.read_json("judge_items.json")
f = [_lib.finding("judge_items", "warning", a["item_id"], "not a color", a["executor"]) for a in ans if not a["is_color"]]
_lib.emit_findings("judge_items", f)
allf = _lib.collect_findings()
_lib.write_json("findings.json", allf)
_lib.write_text("report.md", _lib.report("Self-test", "Runtime self-test.", allf))
