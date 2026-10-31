"""Count the calls and the events by verb and kind, and write a report listing every event."""
import _lib

VERBS = ("wrote", "edited", "ran", "searched", "verified", "committed")
KINDS = ("action", "decision", "observation", "blocker")

calls = _lib.read_json("calls.json")
events = _lib.read_json("events.json")


def counts(field, names):
    parts = ["{} {}".format(name, sum(1 for e in events if e[field] == name))
             for name in names if any(e[field] == name for e in events)]
    return ", ".join(parts) or "none"


note = "Read {} calls and wrote {} events, by verb {}, and by kind {}.".format(
    len(calls), len(events), counts("verb", VERBS), counts("kind", KINDS))
findings = _lib.collect_findings()
findings.append(_lib.finding("report", "info", "calls", note))
findings.sort(key=lambda x: (_lib.SEVERITY_ORDER[x["severity"]], x["check"], x["item"], x["message"]))
_lib.write_json("findings.json", findings)

rows = ["| Source id | Verb | Kind | Object |", "|---|---|---|---|"]
rows += ["| {} | {} | {} | {} |".format(_lib.cell(e["source_id"]), e["verb"], e["kind"],
                                        _lib.cell(e["object"], limit=200)) for e in events]
table = "\n".join(rows) if events else "None."
intro = "Each git command the wrapper recorded, turned into one event in the audit layer's schema."
_lib.write_text("report.md", _lib.report("Git wrapper calls", intro, findings, [("Events", table)]))
