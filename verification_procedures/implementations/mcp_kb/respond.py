"""Write the response, a note naming the entries returned, and a report of the call."""
import json

import _lib

call = _lib.read_json("request_ok.json")
answer = _lib.read_json("answer.json")
_lib.write_json("response.json", {"tool": answer["tool"], "result": answer["result"]})

returned = answer["returned"]
if returned:
    note = "Returned the entries {}.".format(", ".join(returned))
else:
    note = "Returned no entry."
findings = _lib.collect_findings()
findings.append(_lib.finding("respond", "info", call["tool"] or "request", note))
findings.sort(key=lambda x: (_lib.SEVERITY_ORDER[x["severity"]], x["check"], x["item"], x["message"]))
_lib.write_json("findings.json", findings)

arguments = json.dumps(call["arguments"], sort_keys=True, ensure_ascii=False)
names = ", ".join("`{}`".format(i) for i in returned) or "none"
table = "\n".join([
    "| Tool | Arguments | Returned |",
    "|---|---|---|",
    "| {} | {} | {} |".format(_lib.cell(call["tool"] or "none"), _lib.cell(arguments, limit=400),
                              _lib.cell(names, limit=2000)),
])
if call["route"] == "refuse":
    intro = "The call was refused with the code {}.".format(call["error_code"])
else:
    intro = "The call was answered from the index given with it."
_lib.write_text("report.md", _lib.report("Knowledge base call", intro, findings, [("Call", table)]))
