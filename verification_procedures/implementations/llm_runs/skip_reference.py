"""Say that no reference was given, so the run's answers were not compared.

agreement.json is {compared: false, total: 0, agreed: 0, steps: []}.
"""
import _lib

CHECK = "skip_reference"

_lib.read_json("run_index.json")
_lib.write_json("agreement.json", {"compared": False, "total": 0, "agreed": 0, "steps": []})
_lib.emit_findings(CHECK, [_lib.finding(
    CHECK, "info", "reference",
    "No reference was given, so the run's answers were not compared and their agreement is unknown.")])
