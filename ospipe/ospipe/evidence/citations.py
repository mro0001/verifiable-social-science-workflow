"""The citation evidence file. Contract in CONTRACT.md.

For each citation in the citations results file, the scholar's decision on the file's
run, who made it and when, and, from the citation log, who introduced the citation and
in which session. Only the project's files are read. No check is run and no database is
queried.
"""
import hashlib
import json
from pathlib import Path
from typing import Dict, Optional, Tuple, Union

import yaml

from ospipe.build.verification import SCHEMA, SCHEMA_VERSION, latest_decision

PathLike = Union[str, Path]

# The results item field that holds the citekey, as a references run writes it (printed
# from a run on the test story). The citation log is keyed by the same citekey.
CITEKEY_FIELD = "citekey"

EVIDENCE_SCHEMA = "citation-evidence"
EVIDENCE_SCHEMA_VERSION = 1
RESULTS_NAME = "citations.json"
NOT_NEEDED = "not needed"


class EvidenceError(ValueError):
    """A results file or citation log the evidence file cannot be written from."""


def _shape_problem(data: dict) -> Optional[str]:
    """What keeps the file from the results file's shape, or None."""
    if not isinstance(data.get("run_id"), str) or not data["run_id"]:
        return "no run_id"
    items, decisions = data.get("items"), data.get("decisions")
    if not isinstance(items, list) or not isinstance(decisions, list):
        return "items and decisions must be lists"
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            return "an item without a text id"
        if not isinstance(item.get("needs_decision"), bool):
            return "item {0} has no true or false needs_decision".format(item["id"])
    for entry in decisions:
        if not isinstance(entry, dict) or not isinstance(entry.get("item"), str):
            return "a decision that names no item"
    return None


def _read_results(path: Path) -> Tuple[dict, str]:
    """The parsed results file and the sha256 of its bytes."""
    try:
        raw = path.read_bytes()
    except OSError:
        raise EvidenceError("no results file {0}".format(path))
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise EvidenceError("{0} is not JSON".format(path))
    if not isinstance(data, dict):
        raise EvidenceError("{0} is not a results file".format(path))
    version = data.get("schema_version")
    if data.get("schema") != SCHEMA or type(version) is not int or version != SCHEMA_VERSION:
        raise EvidenceError(
            "{0} is not schema {1} version {2}".format(path, SCHEMA, SCHEMA_VERSION)
        )
    problem = _shape_problem(data)
    if problem is not None:
        raise EvidenceError("{0} does not have the results file's shape, {1}".format(path, problem))
    return data, hashlib.sha256(raw).hexdigest()


def _read_log(path: PathLike) -> Dict[str, dict]:
    """The citation log's entries by citekey."""
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except OSError:
        raise EvidenceError("no citation log {0}".format(path))
    except (UnicodeDecodeError, yaml.YAMLError):
        raise EvidenceError("{0} is not YAML".format(path))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise EvidenceError("{0} is not a citation log".format(path))
    entries = data.get("citations") or {}
    if not isinstance(entries, dict) or not all(isinstance(e, dict) for e in entries.values()):
        raise EvidenceError("{0} has no citations mapping of entries".format(path))
    return {str(key): entry for key, entry in entries.items()}


def _text(value: object) -> str:
    return "" if value is None else str(value)


def citation_evidence(verification_dir: PathLike, citation_log: Optional[PathLike] = None) -> dict:
    """Read `<verification_dir>/citations.json` and, when given, the citation log, and
    return the evidence file's content. Raises EvidenceError for a missing file, bad
    JSON, another schema or schema_version, or a file without the results file's shape,
    and for a named citation log that is missing or has another shape."""
    path = Path(verification_dir) / RESULTS_NAME
    results, sha256 = _read_results(path)
    log = _read_log(citation_log) if citation_log is not None else {}
    items = []
    for item in results["items"]:
        if item["needs_decision"]:
            word, entry = latest_decision(results, item["id"])
        else:
            word, entry = NOT_NEEDED, None
        logged = log.get(_text(item.get(CITEKEY_FIELD)), {})
        items.append(
            {
                "id": item["id"],
                "needs_decision": item["needs_decision"],
                "decision": word,
                "by": _text(entry.get("by")) if entry else "",
                "at": _text(entry.get("at")) if entry else "",
                "introduced_by": _text(logged.get("introduced_by")),
                "session": _text(logged.get("session")),
                "item": item,
            }
        )
    return {
        "schema": EVIDENCE_SCHEMA,
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "results_file": str(path),
        "results_sha256": sha256,
        "run_id": results["run_id"],
        "procedure_version": results.get("procedure_version"),
        "items": items,
    }


def evidence_yaml(evidence: dict) -> str:
    """The evidence file as YAML, keys in their order."""
    return yaml.safe_dump(evidence, sort_keys=False, allow_unicode=True, default_flow_style=False)
