"""The manifest emitter. Fills each value in the numbers file from the analysis outputs.

FROZEN surface documented in CONTRACT.md: the emit_manifest() signature, the
EmitResult shape, the fields read (`from`, `field`, `where`), the lookup rules
(those of the data procedure's numbers check), the one refusal that lists every
problem, and values written as strings the build reads unchanged.
The emitter does not run the analysis and formats nothing beyond str() of a number.
"""
import csv
import json
import unicodedata
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple, Union

import yaml

PathLike = Union[str, Path]

# The fields of an entry the emitter reads, and the order a rewritten entry starts with.
ENTRY_FIELDS = ("value", "from", "field", "where")


class ManifestEmitError(ValueError):
    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__(
            "manifest emit failed:\n" + "\n".join("- " + p for p in self.problems)
        )


class EmitResult(NamedTuple):
    changed: List[Tuple[str, Optional[str], str]]
    unchanged: List[str]


class _Missing(Exception):
    pass


def _walk_json(data, field: str, source: str):
    """Walk a dotted path, through objects by name and lists by position."""
    cur = data
    for part in field.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            raise _Missing("no field {0} in {1}".format(field, source))
    return cur


def _csv_cell(rows: List[Dict[str, str]], field: str, where, source: str) -> str:
    """The `field` column of the one row whose cells equal every `where` pair, as text."""
    pairs = list((where or {}).items())
    matching = [r for r in rows if all(str(r.get(k)) == str(v) for k, v in pairs)]
    if len(matching) != 1:
        raise _Missing(
            "{0} rows of {1} match {2}".format(
                len(matching), source, dict(pairs) if pairs else "no where"
            )
        )
    if field not in matching[0]:
        raise _Missing("no column {0} in {1}".format(field, source))
    return matching[0][field]


def _display(value) -> str:
    """Text as it is, a whole or decimal number through str(). Anything else is refused."""
    if isinstance(value, str):
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _Missing("refused value {0} (only text or a number is written)".format(json.dumps(value)))
    return str(value)


def _old_text(entry: Dict) -> Optional[str]:
    old = entry.get("value")
    if old is None:
        return None
    return old if isinstance(old, str) else str(old)


def _is_current(entry: Dict, new: str) -> bool:
    old = entry.get("value")
    if isinstance(old, str):
        return old == new
    if isinstance(old, (int, float)) and not isinstance(old, bool):
        return str(old) == new
    return False


def _quote(text: str) -> str:
    """A JSON-style double-quoted string that YAML loads back as the same text."""
    out = []
    for ch in json.dumps(text, ensure_ascii=False):
        if ord(ch) > 0x7E and unicodedata.category(ch)[0] in ("C", "Z"):
            code = ord(ch)
            out.append("\\u{0:04x}".format(code) if code <= 0xFFFF else "\\U{0:08x}".format(code))
        else:
            out.append(ch)
    return "".join(out)


def _key_text(key: str) -> str:
    """The key plain when it loads back as the same text, otherwise quoted."""
    try:
        if yaml.safe_load("{0}: 0".format(key)) == {key: 0}:
            return key
    except yaml.YAMLError:
        pass
    return _quote(key)


def _json_text(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _entry_line(key: str, entry: Dict, value: str) -> str:
    parts = [
        "value: " + _quote(value),
        "from: " + _quote(str(entry["from"])),
        "field: " + _quote(str(entry["field"])),
    ]
    if "where" in entry:
        parts.append("where: " + _json_text(entry["where"]))
    for name, other in entry.items():
        if name not in ENTRY_FIELDS:
            parts.append(_key_text(str(name)) + ": " + _json_text(other))
    return "  {0}: {{{1}}}\n".format(_key_text(key), ", ".join(parts))


def _leading_lines(text: str) -> str:
    """The comment and blank lines before the first other line, unchanged."""
    lead = []
    for line in text.splitlines(True):
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            break
        lead.append(line)
    return "".join(lead)


class _Outputs:
    """Each output file read once, as JSON or as CSV rows."""

    def __init__(self, folder: Path):
        self.folder = folder
        self.cache: Dict[str, object] = {}

    def get(self, name: str):
        if name not in self.cache:
            path = self.folder / name
            if not path.is_file():
                self.cache[name] = _Missing("output file {0} is missing from {1}".format(name, self.folder))
            else:
                try:
                    if name.endswith(".json"):
                        self.cache[name] = json.loads(path.read_text(encoding="utf-8"))
                    else:
                        with open(path, encoding="utf-8", newline="") as fh:
                            self.cache[name] = list(csv.DictReader(fh))
                except (OSError, ValueError, csv.Error) as err:
                    self.cache[name] = _Missing("output file {0} cannot be read ({1})".format(name, err))
        found = self.cache[name]
        if isinstance(found, _Missing):
            raise found
        return found


def emit_manifest(manifest_path: PathLike, outputs_dir: Optional[PathLike] = None) -> EmitResult:
    path = Path(manifest_path)
    try:
        text = path.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
    except (OSError, yaml.YAMLError) as err:
        raise ManifestEmitError(["{0} cannot be read ({1})".format(path, err)])
    if not (isinstance(data, dict) and set(data) == {"numbers"} and isinstance(data["numbers"], dict)):
        raise ManifestEmitError(["{0} must hold one top-level numbers: mapping".format(path)])

    outputs = _Outputs(Path(outputs_dir) if outputs_dir is not None else path.parent)
    problems: List[str] = []
    values: Dict[str, str] = {}
    for raw_key, entry in data["numbers"].items():
        key = str(raw_key)
        if not isinstance(entry, dict):
            problems.append("{0}: entry is not a mapping with from and field".format(key))
            continue
        lacking = [name for name in ("from", "field") if name not in entry]
        if lacking:
            problems.append("{0}: entry has no {1}".format(key, " or ".join(lacking)))
            continue
        where = entry.get("where")
        if where is not None and not isinstance(where, dict):
            problems.append("{0}: where is not a mapping of column to value".format(key))
            continue
        source, field = str(entry["from"]), str(entry["field"])
        try:
            found = outputs.get(source)
            if source.endswith(".json"):
                raw = _walk_json(found, field, source)
            else:
                raw = _csv_cell(found, field, where, source)
            values[key] = _display(raw)
        except _Missing as err:
            problems.append("{0}: {1}".format(key, err))
    if problems:
        raise ManifestEmitError(problems)

    changed: List[Tuple[str, Optional[str], str]] = []
    unchanged: List[str] = []
    for raw_key, entry in data["numbers"].items():
        key = str(raw_key)
        if _is_current(entry, values[key]):
            unchanged.append(key)
        else:
            changed.append((key, _old_text(entry), values[key]))
    if changed:
        lines = [_leading_lines(text), "numbers:\n"]
        for raw_key, entry in data["numbers"].items():
            lines.append(_entry_line(str(raw_key), entry, values[str(raw_key)]))
        path.write_text("".join(lines), encoding="utf-8")
    return EmitResult(changed=changed, unchanged=unchanged)
