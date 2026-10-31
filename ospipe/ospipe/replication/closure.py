"""What a research product depends on, the files its replication folder needs.

Read from the project's build file (its map), the product's source, and the
declarations the data procedure already reads (`pipeline.yaml`, `params.yaml`, and
`acquisition.yaml`). Nothing is copied or written here.
"""
import os
import re
from pathlib import Path
from typing import List, NamedTuple, Optional

import yaml

from ospipe.foundation import PLACEHOLDER

STREAMS = ("prose", "citations", "data", "build")
PIPELINE = "pipeline.yaml"
PARAMS = "params.yaml"
ACQUISITION = "acquisition.yaml"
# The audit layer's written-out records, at their default places in the project,
# with what each one is called in a note.
AUDIT_RECORDS = (
    ("audit/citation_log.yaml", "the citation log"),
    ("audit/session_writes.jsonl", "the session writes"),
    ("audit/rationales.yaml", "the rationales"),
)

_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
# ![alt](path) or ![alt](<path> "title"). The path is the first word in the brackets.
_IMAGE = re.compile(r"!\[[^\]]*\]\(\s*(?:<([^>]*)>|([^)\s]+))")
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]+:")
_DRIVE = re.compile(r"^[A-Za-z]:[\\/]")


class Closure(NamedTuple):
    files: List[str]
    notes: List[str]


class ReplicationError(ValueError):
    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__(
            "cannot work out what the product depends on\n"
            + "\n".join("  " + p for p in self.problems)
        )


class _Collector:
    """Gathers project-relative files and every problem with them."""

    def __init__(self, project_dir: Path):
        self.project_dir = project_dir
        self.files = set()
        self.problems: List[str] = []

    def place(self, path: str, named_by: str) -> Optional[str]:
        """The path relative to the project folder, or None with a problem recorded."""
        text = str(path).strip()
        if text.startswith("/") or text.startswith("~") or _DRIVE.match(text):
            self.problems.append("{0} names {1}, an absolute path".format(named_by, text))
            return None
        normal = Path(os.path.normpath(text)).as_posix()
        if normal == ".." or normal.startswith("../"):
            self.problems.append("{0} names {1}, which leaves the project folder".format(named_by, text))
            return None
        return normal

    def add(self, path: str, named_by: str) -> None:
        relative = self.place(path, named_by)
        if relative is None:
            return
        if not (self.project_dir / relative).is_file():
            self.problems.append("{0} names {1}, which is missing".format(named_by, relative))
            return
        self.files.add(relative)

    def add_if_present(self, path: str) -> bool:
        if (self.project_dir / path).is_file():
            self.files.add(Path(path).as_posix())
            return True
        return False


def _outside_fences(text: str) -> str:
    kept = []
    fence_char = None
    for line in text.split("\n"):
        fence = _FENCE.match(line)
        if fence_char is not None:
            if fence and fence.group(1)[0] == fence_char:
                fence_char = None
            continue
        if fence:
            fence_char = fence.group(1)[0]
            continue
        kept.append(line)
    return "\n".join(kept)


def _images(text: str) -> List[str]:
    found = []
    for match in _IMAGE.finditer(_outside_fences(text)):
        target = match.group(1) if match.group(1) is not None else match.group(2)
        target = target.strip()
        if target and not _SCHEME.match(target):
            found.append(target)
    return found


def _list_of(value) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if item is not None]
    return [str(value)]


def _load_yaml(collector: _Collector, relative: str):
    try:
        with open(str(collector.project_dir / relative), encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as err:
        collector.problems.append("{0} cannot be read: {1}".format(relative, err))
        return None
    if data is None:
        return {}
    if not isinstance(data, dict):
        collector.problems.append("{0} is not a mapping".format(relative))
        return None
    return data


def _analysis(collector: _Collector, notes: List[str]) -> None:
    if not collector.add_if_present(PIPELINE):
        notes.append("no {0}, so the analysis is not shipped".format(PIPELINE))
        return
    pipeline = _load_yaml(collector, PIPELINE)
    if pipeline is not None:
        for helper in _list_of(pipeline.get("helpers")):
            collector.add(helper, "{0} helpers".format(PIPELINE))
        steps = pipeline.get("steps") or []
        if not isinstance(steps, list):
            collector.problems.append("{0} steps is not a list".format(PIPELINE))
            steps = []
        for number, step in enumerate(steps, start=1):
            if not isinstance(step, dict):
                collector.problems.append("{0} step {1} is not a mapping".format(PIPELINE, number))
                continue
            label = "{0} step {1}".format(PIPELINE, step.get("id", number))
            for key in ("script", "inputs", "outputs"):
                for path in _list_of(step.get(key)):
                    collector.add(path, label)

    if not collector.add_if_present(PARAMS):
        notes.append("no {0}, so no parameters are shipped".format(PARAMS))

    if not collector.add_if_present(ACQUISITION):
        notes.append("no {0}, so the raw data are not declared".format(ACQUISITION))
        return
    acquisition = _load_yaml(collector, ACQUISITION)
    if acquisition is None:
        return
    raw = acquisition.get("raw") or []
    if not isinstance(raw, list):
        collector.problems.append("{0} raw is not a list".format(ACQUISITION))
        return
    for number, entry in enumerate(raw, start=1):
        if not isinstance(entry, dict) or not entry.get("file"):
            collector.problems.append("{0} raw entry {1} has no file".format(ACQUISITION, number))
            continue
        collector.add(str(entry["file"]), "{0} raw".format(ACQUISITION))


def closure(project_map, product_name) -> Closure:
    """The files a product depends on, sorted and relative to the project folder, and
    notes on what was absent. Raises ReplicationError listing every problem at once."""
    project_dir = Path(project_map.project_dir)
    products = [p for p in project_map.products if p.name == product_name]
    if not products:
        raise ReplicationError(["no product {0} in the build file".format(product_name)])
    product = products[-1]
    collector = _Collector(project_dir)
    notes: List[str] = []
    rule = "the {0} rule".format(product.name)

    for problem in project_map.problems:
        if problem.startswith(product.name + ":"):
            collector.problems.append(problem)

    source_text = None
    if product.source is not None:
        collector.add(product.source, rule)
        relative = collector.place(product.source, rule)
        if relative is not None and (project_dir / relative).is_file():
            source_text = (project_dir / relative).read_text(encoding="utf-8")

    for field in ("manifest", "overlay", "bib", "csl", "reference_doc"):
        value = getattr(product, field)
        if value is not None:
            collector.add(value, rule)

    if source_text is not None:
        source_label = "the source {0}".format(product.source)
        tables = []
        for kind, key in PLACEHOLDER.findall(source_text):
            if kind == "table" and key not in tables:
                tables.append(key)
        for key in tables:
            if product.tables_dir is None:
                collector.problems.append(
                    "{0} names the table {1}, but {2} has no --tables-dir".format(source_label, key, rule)
                )
            else:
                collector.add("{0}/{1}.md".format(product.tables_dir, key), source_label)
        for image in _images(source_text):
            collector.add(image, source_label)

    _analysis(collector, notes)

    verification_dir = product.verification_dir
    if verification_dir is not None:
        place = collector.place(verification_dir, rule)
        if place is not None:
            for stream in STREAMS:
                path = "{0}/{1}.json".format(place, stream)
                if not collector.add_if_present(path):
                    notes.append("no {0}, so the {1} results are not shipped".format(path, stream))

    for path, called in AUDIT_RECORDS:
        if not collector.add_if_present(path):
            notes.append("no {0}, so {1} is not shipped".format(path, called))

    if collector.problems:
        raise ReplicationError(collector.problems)
    return Closure(files=sorted(collector.files), notes=notes)
