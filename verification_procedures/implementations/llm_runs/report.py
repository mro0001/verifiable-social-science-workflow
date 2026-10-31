"""Write the evaluation's findings and its report, with the models and settings the
run used, each judgment step with its items, the agreement with a reference, and
the replay and score. The answered, retries, and prompt mismatch columns come
from record_check.json, and read "-" when the run's record was not checked. The
Agreement table comes from agreement.json, and the Replay and score section from
the run index and check_replay's findings."""
import os

import _lib

index = _lib.read_json("run_index.json")
findings = _lib.collect_findings()
_lib.write_json("findings.json", findings)

if index["is_run"]:
    intro = ("The run of {} (version {}, stream {}), read from its archive. {} tool steps "
             "and {} judgment steps.".format(index["graph"], index["graph_version"], index["stream"],
                                             index["tool_steps"], len(index["judgment_steps"])))
    intro += " The run finished." if index["finished"] else (
        " The run stopped at {}.".format(index["stopped_at"]) if index["stopped_at"]
        else " The run did not finish.")
    models = ["| Role | Executor |", "|---|---|"]
    for role in ("judge", "second"):
        models.append("| {} | {} |".format(role, _lib.cell(index[role] or "none", limit=400)))
    models = "\n".join(models)
else:
    intro = "The archive holds no run, so there is nothing to evaluate."
    models = "None."

checked = {}
if os.path.exists(_lib.path("record_check.json")):
    checked = {row["node"]: row for row in _lib.read_json("record_check.json")}

steps = ["| Step | Role | Items asked | Answered | Items not judged | Retries | Prompt mismatches |",
         "|---|---|---|---|---|---|---|"]
for st in index["judgment_steps"]:
    row = checked.get(st["node"])
    extra = [row["answered"], row["retries"], row["prompt_mismatches"]] if row else ["-", "-", "-"]
    steps.append("| {} | {} | {} | {} | {} | {} | {} |".format(
        st["node"], st["role"], st["items"], extra[0], len(st["unjudged"]), extra[1], extra[2]))
steps = "\n".join(steps) if index["judgment_steps"] else "None."

if os.path.exists(_lib.path("agreement.json")):
    agreement = _lib.read_json("agreement.json")
    if agreement["compared"]:
        rows = ["{} of {} compared items agree with the reference.".format(
            agreement["agreed"], agreement["total"]), "",
            "| Step | Compared | Agreed |", "|---|---|---|"]
        rows += ["| {} | {} | {} |".format(st["node"], st["compared"], st["agreed"])
                 for st in agreement["steps"]]
        agreed = "\n".join(rows)
    else:
        agreed = "No reference was given."
else:
    agreed = "Not checked."

if index["is_run"]:
    replay = ["- The archive holds verify.json." if index["has_verify"]
              else "- The archive holds no verify.json.",
              "- The archive holds score.json." if index["has_score"]
              else "- The archive holds no score.json."]
    replay += ["- {}: {}".format(f["severity"], f["message"]) for f in findings
               if f["check"] == "check_replay" and f["severity"] != "info"]
    replay = "\n".join(replay)
else:
    replay = "Not checked."

_lib.write_text("report.md", _lib.report("Evaluation of an LLM run", intro, findings,
                                         [("Models and settings", models), ("Judgment steps", steps),
                                          ("Agreement", agreed), ("Replay and score", replay)]))
