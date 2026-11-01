"""Write a report with the settings, the file scan, the recount, and the rebuild.

The title is the settings' task. The Settings section gives the number of terms, allow
entries, excluded folders, and excluded folders inside the repository, never the terms
or the folders themselves, and says
only whether a workflow folder is given, so the report names nothing private. The
Files, Counts, and Rebuild sections each say "Not run." when their step did not run.
"""
import json
import os

import _lib

settings = _lib.read_json("settings.json")
findings = _lib.collect_findings()
_lib.write_json("findings.json", findings)

COUNTED = ("terms", "allow", "excluded_folders", "excluded_paths")


def value(key, v):
    if key in COUNTED:
        n = len(v) if isinstance(v, list) else 0
        return "%d %s" % (n, "entry" if n == 1 else "entries")
    if key == "workflow_root":
        return "given" if v else "(empty)"
    if isinstance(v, str):
        return v or "(empty)"
    return json.dumps(v, ensure_ascii=False, sort_keys=True)


def optional(name):
    return _lib.read_json(name) if os.path.exists(_lib.path(name)) else None


rows = ["| Field | Value |", "|---|---|"]
rows += ["| %s | %s |" % (key, _lib.cell(value(key, settings[key]), limit=300)) for key in sorted(settings)]
sections = [("Settings", "\n".join(rows))]

scan = optional("scan.json")
if scan is None:
    sections.append(("Files", "Not run."))
else:
    sections.append(("Files", "\n".join([
        "- Files in the repository, %d" % scan["files"],
        "- Files whose text was scanned, %d" % scan["text_files"],
        "- Office files scanned part by part, %d" % scan["office_files"],
        "- Tars opened, %d, holding %d files" % (scan["archives"], scan["archive_members"]),
        "- Images and PDF files, whose text and metadata were scanned but not what they show, %d"
        % scan["images"],
        "- Blocking problems, %d" % scan["blocked"],
        "- Warnings, %d" % scan["warned"],
        "- Findings accepted by the settings, %d" % scan["accepted"],
    ])))

counts = optional("counts.json")
if counts is None:
    sections.append(("Counts", "Not run."))
else:
    lines = [
        "- Counts in the manifest rechecked, %d" % counts["checked"],
        "- Counts that differ from the recount, %d" % counts["differ"],
        "- Counts not rechecked, %d" % counts["not_rechecked"],
        "- Generated pages changed or missing, %d" % counts["generated_changed"],
        "- Listed files changed or missing, %d" % counts["files_changed"],
        "- Files not listed in the manifest, %d" % counts["files_unlisted"],
        "- Report files missing, %d" % counts["reports_missing"],
    ]
    differ = [r for r in counts["rows"] if r["same"] is False]
    if differ:
        lines += ["", "| Count | Manifest | Recount |", "|---|---|---|"]
        lines += ["| %s | %s | %s |" % (_lib.cell(r["key"]), _lib.cell(r["manifest"]), _lib.cell(r["recount"]))
                  for r in differ]
    sections.append(("Counts", "\n".join(lines)))

rebuild = optional("rebuild.json")
if rebuild is None:
    sections.append(("Rebuild", "Not run."))
elif not rebuild["products"]:
    sections.append(("Rebuild", "No product was rebuilt."))
else:
    lines = ["| Product | Latest | Result | Text matches |", "|---|---|---|---|"]
    for p in rebuild["products"]:
        matches = "-" if p["text_matches"] is None else ("yes" if p["text_matches"] else "no")
        lines.append("| %s | %s | %s | %s |" % (_lib.cell(p["name"]), p["latest"] or "-", p["result"], matches))
    sections.append(("Rebuild", "\n".join(lines)))

intro = ("The check reads the repository packed as repo.tar, scans every file for private files and text, "
         "recounts every number its manifest records, and rebuilds each product when the settings ask. "
         "This run had rebuild set to %s." % ("true" if settings["rebuild"] else "false"))
_lib.write_text("report.md", _lib.report(settings["task"], intro, findings, sections))
