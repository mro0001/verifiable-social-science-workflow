"""Shared vocabulary for the ospipe tree. FROZEN surface documented in CONTRACT.md."""
import re
from pathlib import Path
from typing import Dict, Optional, Union

import yaml

PathLike = Union[str, Path]

PLACEHOLDER = re.compile(r"\{\{(num|table):([A-Za-z0-9_.\-]+)\}\}")
SUSPECT = re.compile(r"\{\{\w+:")


class ManifestError(ValueError):
    pass


class MissingKeyError(KeyError):
    def __init__(self, keys):
        self.keys = sorted(set(keys))
        super().__init__(", ".join(self.keys))


def _load_yaml_map(path: PathLike) -> Dict:
    raw = Path(path).read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ManifestError(f"{path}: manifest must be a YAML mapping, got {type(data).__name__}")
    if set(data) == {"numbers"} and isinstance(data["numbers"], dict):
        return _values_of_numbers(data["numbers"], path)
    return data


def _values_of_numbers(numbers: Dict, path: PathLike) -> Dict:
    """The data procedure's numbers.yml shape: `numbers:` maps each key to
    {value, from, field, where}. The build needs only each entry's value."""
    out = {}
    for key, entry in numbers.items():
        if isinstance(entry, dict):
            if "value" not in entry:
                raise ManifestError(f"{path}: numbers entry {key!r} has no value")
            entry = entry["value"]
        out[key] = entry
    return out


def load_manifest(path: PathLike, overlay_path: Optional[PathLike] = None) -> Dict[str, str]:
    data = _load_yaml_map(path)
    if overlay_path is not None and Path(overlay_path).exists():
        overlay = _load_yaml_map(overlay_path)
        collisions = sorted(set(data) & set(overlay))
        if collisions:
            raise ManifestError(f"overlay redefines manifest keys: {collisions}")
        data.update(overlay)
    out: Dict[str, str] = {}
    for key, value in data.items():
        key = str(key)
        if not re.fullmatch(r"[A-Za-z0-9_.\-]+", key):
            raise ManifestError(f"manifest key {key!r} outside the placeholder key grammar")
        if isinstance(value, bool) or value is None or isinstance(value, (list, dict)):
            raise ManifestError(f"manifest key {key!r}: value must be a scalar string or number")
        out[key] = value if isinstance(value, str) else str(value)
    return out
