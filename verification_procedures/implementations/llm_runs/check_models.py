"""Say which executor answered for each role and what the run does not record.

An info note per role names its executor and says when the answers came from a
recorded file. When the manifest held a provider block, the executor live is the
provider's model, and the note names that model and the service's address. A
warning when the judge and the second checker are the same, with live read as
live:<the provider's model>. An info note that the run records the model's name
only (appendix A5, Table A10).
"""
import _lib

CHECK = "check_models"
ROLES = (("judge", "judge"), ("second", "second checker"))

index = _lib.read_json("run_index.json")
provider = index.get("provider") or {}


def resolved(executor):
    """The executor with live named as the provider's model, when the run gave one."""
    if executor == "live" and provider.get("model"):
        return "live:" + provider["model"]
    return executor


findings = []
for role, words in ROLES:
    executor = index[role]
    if not executor:
        findings.append(_lib.finding(CHECK, "info", role, "No executor was set for the {}.".format(words)))
        continue
    message = "The {} was {}.".format(words, executor)
    if executor.startswith("recorded:"):
        message += " Its answers came from a recorded file, not from a model."
    elif executor.startswith("live") and provider:
        model = resolved(executor).partition(":")[2]
        message += " It reached the model {} at {}, as the run's provider setting gave.".format(
            model, provider.get("base_url", ""))
    findings.append(_lib.finding(CHECK, "info", role, message, executor))

if index["judge"] and index["second"] and resolved(index["judge"]) == resolved(index["second"]):
    findings.append(_lib.finding(
        CHECK, "warning", "second",
        "The judge and the second checker are the same, so the second check is not made by a different model.",
        resolved(index["second"])))

findings.append(_lib.finding(
    CHECK, "info", "run",
    "The run records the model's name only, and not its version, its settings, token counts, "
    "finish reasons, seeds, or reasoning."))
_lib.emit_findings(CHECK, findings)
