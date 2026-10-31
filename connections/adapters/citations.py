"""The citation manager export adapter, which turns an export into the references stream's refs.yaml (Track D, step D17).

Appendix-only. The proposal's Table 1 names the citation manager as the
references stream's tool, and Table A6 lists an adapter for a citation
manager's export as specified. The references procedure reads refs.yaml, a
list of references under the key references.

python3 -m connections adapt citations --out DIR --export FILE reads a .json
file as CSL JSON, either a list of items or a mapping holding items, and
converts a .bib file with pandoc -f bibtex -t csljson FILE before reading it
the same way (Track D choice 16). Any other extension is refused. Pandoc is
the only program the adapter runs.

Each item keeps seven fields, in this order, and leaves out any the item
lacks. They are id, type, author (each name as family and given, an
institution's literal name as family), issued (the year, from date-parts,
else the first four digits of raw or literal), title, container-title, and
DOI (from DOI or doi). Items are sorted by id. An item with no id, and two
items with one id, are refused.
"""
import json
import re
import subprocess
from pathlib import Path

import yaml

from connections.adapters import ADAPTERS, Adapter, AdapterError

FILL = "refs.yaml"


def add_arguments(parser) -> None:
    parser.add_argument(
        "--export",
        required=True,
        metavar="FILE",
        help="the citation manager's export, CSL JSON (.json) or BibTeX (.bib)",
    )


def _csl_text(path: str) -> str:
    """The export as CSL JSON text, converting BibTeX with Pandoc."""
    suffix = Path(path).suffix.lower()
    if suffix == ".json":
        try:
            return Path(path).read_text(encoding="utf-8")
        except (OSError, ValueError) as error:
            raise AdapterError(f"{path} cannot be read as UTF-8 text, {error}")
    if suffix == ".bib":
        if not Path(path).is_file():
            raise AdapterError(f"{path} cannot be read, there is no such file")
        try:
            done = subprocess.run(
                ["pandoc", "-f", "bibtex", "-t", "csljson", path],
                capture_output=True,
            )
        except OSError as error:
            raise AdapterError(f"{path} is BibTeX and pandoc cannot be started to convert it, {error}")
        if done.returncode != 0:
            message = done.stderr.decode("utf-8", "replace").strip()
            raise AdapterError(f"pandoc could not convert {path} from BibTeX, {message}")
        return done.stdout.decode("utf-8", "replace")
    raise AdapterError(f"{path} is neither CSL JSON (.json) nor BibTeX (.bib)")


def _items(path: str) -> list:
    try:
        data = json.loads(_csl_text(path))
    except ValueError as error:
        raise AdapterError(f"{path} is not CSL JSON, {error}")
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        data = data["items"]
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise AdapterError(f"{path} holds neither a list of CSL items nor a mapping holding items")
    return data


def _name(name) -> dict:
    if not isinstance(name, dict):
        return {}
    if "family" in name:
        kept = {"family": name["family"]}
        if "given" in name:
            kept["given"] = name["given"]
        return kept
    if "literal" in name:
        return {"family": name["literal"]}
    return {}


def _year(issued):
    """The year of a CSL date, or None when it gives none."""
    if not isinstance(issued, dict):
        return None
    parts = issued.get("date-parts")
    if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
        try:
            return int(str(parts[0][0]))
        except ValueError:
            pass
    for key in ("raw", "literal"):
        found = re.search(r"\d{4}", str(issued.get(key, "")))
        if found:
            return int(found.group(0))
    return None


def reference(item: dict) -> dict:
    """One reference with the seven fields the references procedure reads, in order."""
    ref = {"id": str(item["id"])}
    if "type" in item:
        ref["type"] = item["type"]
    if isinstance(item.get("author"), list):
        ref["author"] = [kept for kept in (_name(name) for name in item["author"]) if kept]
    year = _year(item.get("issued"))
    if year is not None:
        ref["issued"] = year
    for key in ("title", "container-title"):
        if key in item:
            ref[key] = item[key]
    doi = item.get("DOI", item.get("doi"))
    if doi is not None:
        ref["DOI"] = doi
    return ref


def read(args):
    path = args.export
    refs, seen = [], set()
    for number, item in enumerate(_items(path), 1):
        if item.get("id") in (None, ""):
            raise AdapterError(f"item {number} in {path} has no id")
        ref = reference(item)
        if ref["id"] in seen:
            raise AdapterError(f"{path} holds two items with the id {ref['id']}")
        seen.add(ref["id"])
        refs.append(ref)
    refs.sort(key=lambda ref: ref["id"])
    text = yaml.safe_dump(
        {"references": refs},
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )
    return [path], {FILL: text.encode("utf-8")}


ADAPTER = Adapter("citations", "citations", (FILL,), add_arguments, read)
ADAPTERS[ADAPTER.name] = ADAPTER
