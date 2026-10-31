"""report: the fill function of the data phase reports. The step outputs fill the fields of
schemas/data_phases.yaml (copied beside this file as schema.yaml), and the one report builder
writes fields.json, findings.json, and report.md.

The report is in the form the authors gave on 2026-10-30. First the outline, one bullet for each
pipeline step of the phase and under it one bullet for each of its steps, with its short
title. Then each title again, with its file and lines and its code copied exactly, in a
fence longer than any run of backticks in the code, each shown once even when two pipeline
steps of the phase run the same script. Then the descriptions table, each row
the quote, where the scripts carry it out or missing, and the program's two checks. Each
description is an item for the scholar to approve or hold, and so is each other group of
problems. The files read are named by their names inside the run's inputs, never by a path.
"""
import re

import _lib
import _report

phase = _lib.read_json("phase.json")
outline = _lib.read_json("outline.json")
descriptions = _lib.read_json("descriptions.json")
allf = _lib.collect_findings()
this = phase["phase"]
FENCE_LANG = {".py": "python", ".r": "r"}


def one_line(s):
    return " ".join(str(s).split())


def cell(s):
    """A table cell holding the whole text on one line, its bars escaped."""
    return one_line(s).replace("|", "\\|")


def lines_text(start, end):
    return "line %d" % start if start == end else "lines %d-%d" % (start, end)


def fence(code):
    longest = max([len(m) for m in re.findall(r"`+", code)] + [0])
    return "`" * max(3, longest + 1)


def lang(script):
    for ext, name in FENCE_LANG.items():
        if script.lower().endswith(ext):
            return name
    return ""


in_phase = [p for p in outline["pipeline_steps"] if p["phase"] == this]
steps = [s for s in outline["steps"] if s["phase"] == this]

if in_phase:
    out = []
    for p in in_phase:
        out.append("- `%s`, `%s`" % (p["id"], p["script"]) if p["script"] else "- `%s`, no script named" % p["id"])
        mine = [s for s in steps if s["pipeline_step"] == p["id"]]
        out += ["  - " + one_line(s["title"]) for s in mine] or ["  - No step could be read from this script."]
    outline_text = "\n".join(out)
else:
    outline_text = ("No step of the pipeline declares the phase %s (`phase: %s` in `pipeline.yaml`)." % (this, this))

blocks, shown = [], set()
for s in steps:
    key = (s["script"], s["title"], s["start"], s["end"])
    if key in shown:
        continue
    shown.add(key)
    f = fence(s["code"])
    blocks.append("### %s\n\n`%s` %s\n\n%s%s\n%s\n%s" % (
        one_line(s["title"]), s["script"], lines_text(s["start"], s["end"]), f, lang(s["script"]), s["code"], f))
code_text = "\n\n".join(blocks) or "None."

files_text = "\n".join("- `%s`, %s, %s" % (f["file"], f["role"], f["sha256"]) for f in outline["files"])

run = {"phase": this, "phase_name": phase["name"], "title": phase["title"],
       "n_pipeline_steps": len(in_phase), "n_steps": len(steps),
       "n_descriptions": len(descriptions),
       "n_missing": sum(1 for d in descriptions if d["location_status"] == "missing"),
       "n_quote_not_found": sum(1 for d in descriptions if not d["quote_found"]),
       "n_location_not_found": sum(1 for d in descriptions if d["location_status"] == "not found"),
       "outline_text": outline_text, "code_text": code_text, "files_text": files_text}

attached, problems = _lib.problem_items(allf, [d["id"] for d in descriptions])
items = []
for d in descriptions:
    items.append({"id": d["id"], "kind": "description", "summary": d["quote"][:_lib.SUMMARY_MESSAGE_CHARS],
                  "findings": attached.get(d["id"], []), "needs_decision": True,
                  "quote": d["quote"], "quote_found": d["quote_found"], "where": d["where"],
                  "location_status": d["location_status"],
                  "quote_cell": cell(d["quote"]), "where_cell": cell(d["where_cell"]),
                  "quote_check_cell": "yes" if d["quote_found"] else "no"})

_report.build({"run": run, "items": items + problems, "tables": {}})
