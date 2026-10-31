"""A reader of the BibTeX file a citation manager exports.

Sources arrive from the citation manager's BibTeX export (plan choice 15,
spec 0.11 The systems). read_bib reads entries of the form

    @type{key, field = {value}, field = "value", field = bare}

with braces nested inside values, and gives each entry's type and field names
in lower case, its key as written, and each value with its runs of space and
line breaks made one space. A bare value is a run of letters and digits, read
as written, so Zotero's month = jan gives jan and year = 2020 gives 2020.
Text outside entries is passed over, as BibTeX itself passes it over. A value
in any other form, such as a string macro definition or values joined with #,
is refused with the line it starts on, so nothing is misread.
"""
import re
from typing import Any, Dict, List, Tuple


class BibError(ValueError):
    """Text the reader cannot read as BibTeX entries."""


_START = re.compile(r"@[ \t]*([A-Za-z]+)[ \t]*\{")
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_:.+-]*")
_SPACE = re.compile(r"\s+")
_BARE = re.compile(r"[A-Za-z0-9]+")


def read_bib(text: str) -> List[Dict[str, Any]]:
    """The entries in text, in order, each as {"type", "key", "fields"}."""
    entries = []
    position = 0
    while True:
        found = _START.search(text, position)
        if found is None:
            return entries
        entry, position = _entry(text, found)
        entries.append(entry)


def _entry(text: str, found) -> Tuple[Dict[str, Any], int]:
    kind = found.group(1).lower()
    at = found.start()
    position = found.end()
    comma = text.find(",", position)
    close = text.find("}", position)
    if comma == -1 or (close != -1 and close < comma):
        raise BibError(f"the entry on line {_line(text, at)} has no key followed by a comma")
    key = text[position:comma].strip()
    if not key or _SPACE.search(key):
        raise BibError(f"the entry on line {_line(text, at)} has no key followed by a comma")
    position = comma + 1
    fields: Dict[str, str] = {}
    while True:
        position = _skip(text, position)
        if position >= len(text):
            raise BibError(f"the entry {key} on line {_line(text, at)} is never closed")
        if text[position] == "}":
            return {"type": kind, "key": key, "fields": fields}, position + 1
        name_match = _NAME.match(text, position)
        if name_match is None:
            raise BibError(
                f"the entry {key} has text that is not a field on line {_line(text, position)}"
            )
        name = name_match.group(0).lower()
        position = _skip(text, name_match.end())
        if position >= len(text) or text[position] != "=":
            raise BibError(f"the field {name} of {key} has no = after it")
        position = _skip(text, position + 1)
        value, position = _value(text, position, key, name)
        if name in fields:
            raise BibError(f"the entry {key} gives the field {name} twice")
        fields[name] = _SPACE.sub(" ", value).strip()
        position = _skip(text, position)
        if position < len(text) and text[position] == ",":
            position += 1
        elif position < len(text) and text[position] != "}":
            raise BibError(
                f"the field {name} of {key} is not followed by a comma or the entry's end"
            )


def _value(text: str, position: int, key: str, name: str) -> Tuple[str, int]:
    """The value starting at position, without its outer braces or quotes, and where it ends."""
    if position >= len(text):
        raise BibError(f"the entry {key} is never closed")
    opener = text[position]
    bare = _BARE.match(text, position)
    if bare is not None:
        return bare.group(0), bare.end()
    if opener not in "{\"":
        raise BibError(
            f"the field {name} of {key} on line {_line(text, position)} is not given in"
            " braces, quotes, or as a bare run of letters and digits"
        )
    depth = 0
    index = position + 1
    while index < len(text):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            if depth == 0:
                if opener == "{":
                    return text[position + 1 : index], index + 1
                raise BibError(f"the field {name} of {key} has a closing brace with no opening one")
            depth -= 1
        elif char == '"' and opener == '"' and depth == 0:
            return text[position + 1 : index], index + 1
        index += 1
    raise BibError(f"the field {name} of {key} on line {_line(text, position)} is never closed")


def _skip(text: str, position: int) -> int:
    while position < len(text) and text[position].isspace():
        position += 1
    return position


def _line(text: str, position: int) -> int:
    return text.count("\n", 0, position) + 1
