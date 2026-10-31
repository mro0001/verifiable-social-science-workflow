"""Read a written-out folder back into rows, from the folder alone (Track A, Step A21).

read_written(folder) gives {element: rows} for a folder write-out project
wrote. It uses the standard library and PyYAML only and never imports
audit_layer, so what it reads back is what the folder itself says. Each file
written_out.yaml lists is matched to its form in the folder's own
schema/export_registry.yaml, by its element and its path.

- A YAML list or a JSON Lines file gives its records as rows.
- A codebook CSV file gives a row for each variable, with its variable,
  type, and description, and dataset set to the path of the dataset
  version's CSV file, which is how the catalog record names it.
- A dataset's CSV file (element ds_*) gives one item, with dataset set to
  its path and rows holding each line as a dict of its values. Each value
  takes the type its codebook gives, a whole number for INTEGER and a number
  for REAL, and an empty value is None.
- Files kept unchanged, as bytes, text, or markdown, are not rows and are
  not read.

This file holds no tests.
"""
import csv
import io
import json
import re
from pathlib import Path
from typing import Any, Dict, List

import yaml

WRITTEN_OUT = "written_out.yaml"
REGISTRY = "schema/export_registry.yaml"

_ROWS = ("YAML list", "JSON Lines", "CSV")


def read_written(folder) -> Dict[str, List[Any]]:
    """The rows of each element the folder holds, keyed by element."""
    folder = Path(folder)
    listed = yaml.safe_load((folder / WRITTEN_OUT).read_text(encoding="utf-8"))["files"]
    forms = yaml.safe_load((folder / REGISTRY).read_text(encoding="utf-8"))
    read = {}  # type: Dict[str, List[Any]]
    datasets = []
    for item in listed:
        path, element = item["path"], item["element"]
        form = _form(forms, element, path)
        if form not in _ROWS:
            continue
        read.setdefault(element, [])
        text = (folder / path).read_text(encoding="utf-8")
        if form == "YAML list":
            read[element] += yaml.safe_load(text) or []
        elif form == "JSON Lines":
            read[element] += [json.loads(line) for line in text.splitlines() if line]
        elif element == "codebook":
            dataset = path[: -len("_codebook.csv")] + ".csv"
            for line in _csv(text):
                read[element].append(dict(line, dataset=dataset))
        else:
            datasets.append(path)
    for path in datasets:
        types = {
            entry["variable"]: entry["type"]
            for entry in read.get("codebook", [])
            if entry["dataset"] == path
        }
        lines = _csv((folder / path).read_text(encoding="utf-8"))
        rows = [{name: _typed(value, types.get(name)) for name, value in line.items()} for line in lines]
        read["ds_*"].append({"dataset": path, "rows": rows})
    return read


def _form(forms: List[Dict[str, Any]], element: str, path: str) -> str:
    """The file form the registry gives the element's file at path."""
    for form in forms:
        if form["element"] != element:
            continue
        pattern = "".join(
            ".+" if part.startswith("<") else re.escape(part)
            for part in re.split(r"(<[^>]*>)", form["path"])
        )
        if re.fullmatch(pattern, path):
            return form["file_form"]
    raise ValueError(f"the registry gives no form for {path}, element {element}")


def _csv(text: str) -> List[Dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text, newline="")))


def _typed(value: str, kind: Any) -> Any:
    if value == "":
        return None
    if kind == "INTEGER":
        return int(value)
    if kind == "REAL":
        return float(value)
    return value
