"""The knowledge store sketch, loaded from the knowledge base's entry files.

Proposal Approach paragraph 1 stores the procedural graphs in a queryable
knowledge base, and Overview paragraph 2 says the databases hold it. Appendix
Table A3's Knowledge row is a sketch only, with an entry class, title, gist,
keywords, content, and a checksum of the source material, and a history
table that keeps every prior version. A2.4 "Knowledge base" keeps each entry
as a markdown file whose heading fixes its identifier, title, source, source
version, date, and group. The entry files stay the source, and this store
reads them only by the path it is given.

Each file maps as plan choice 17 and the reconciliation's Track A section
say. The heading is the block between the first two --- lines, one key and
value to a line, split at the first colon, with quotes around a value
stripped. The entry id is id, the class is group, the title is title, and the
source checksum is source_commit. The gist is the first sentence of the
first paragraph after the heading block that is not a heading line, which is
the first paragraph after the # title line, with its lines joined by spaces.
A sentence ends at ., !, or ? followed by a space or the end, and a paragraph
with none of them is a gist whole. Keywords stay empty, and the content is
the whole file. The keys source and updated are read and not stored, since
Table A3 names no field for them.

- parse_entry(text) gives the mapped fields and the problems that keep the
  file out of the store.
- sync(store, paths, provenance) loads the files and folders given, each
  *.md file under a folder. A new entry is added, an unchanged one is left
  alone, and a changed one's current row moves whole into knowledge_history
  in the same transaction that adds the row replacing it, which names it in
  supersedes. A file that is not UTF-8 text, or whose heading lacks id or
  title, or repeats an id an earlier file has, is reported and not stored.
- history(store, entry_id) gives every version of an entry, oldest first.

There is no search (reconciliation, item 6).
"""
import re
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Sequence, Tuple

from audit_layer.store import Store, _columns, _decode, current, writing

VERSION = 1

FIELDS = ("entry_id", "class", "title", "gist", "keywords", "content", "source_checksum")

# The heading keys of A2.4, as the knowledge base's entry files write them.
KEYS = ("id", "title", "source", "source_commit", "updated", "group")

_SENTENCE = re.compile(r"^(.*?[.!?])(?:\s|$)")


class KnowledgeError(ValueError):
    """Paths the knowledge store refuses to sync."""


class SyncSummary(NamedTuple):
    """What one sync did, counted by entry."""

    added: int
    unchanged: int
    replaced: int
    # Each file not synced, as (its path inside the folder given, or its name
    # when a file was given, and the problem).
    problems: Tuple[Tuple[str, str], ...]


def parse_entry(text: str) -> Tuple[Dict[str, Any], List[str]]:
    """The entry file's fields, as the knowledge store keeps them, and its problems.

    With any problem, the fields are not to be stored.
    """
    heading, body = _split(text)
    if heading is None:
        return {}, ["the file has no heading block between --- lines"]
    problems = [f"the heading has no {key}" for key in ("id", "title") if not heading.get(key)]
    fields = {
        "entry_id": heading.get("id", ""),
        "class": heading.get("group", ""),
        "title": heading.get("title", ""),
        "gist": _gist(body),
        "keywords": [],
        "content": text,
        "source_checksum": heading.get("source_commit", ""),
    }
    return fields, problems


def sync(store: Store, paths: Sequence, provenance: Dict[str, str]) -> SyncSummary:
    """Load the entry files at paths into the knowledge store and say what changed.

    A path that is neither a file nor a folder is refused before anything is
    stored. Files are read in path order within each path given.
    """
    files = _files(paths)
    added = unchanged = replaced = 0
    problems = []  # type: List[Tuple[str, str]]
    seen = {}  # type: Dict[str, str]
    for name, path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            problems.append((name, "the file is not UTF-8 text"))
            continue
        fields, found = parse_entry(text)
        if not found and fields["entry_id"] in seen:
            found = [f"repeats the id {fields['entry_id']} of {seen[fields['entry_id']]}"]
        if found:
            problems.extend((name, problem) for problem in found)
            continue
        seen[fields["entry_id"]] = name
        with writing(store) as write:
            rows = current(store, "knowledge_entries", entry_id=fields["entry_id"])
            if not rows:
                write.add("knowledge_entries", fields, provenance)
                added += 1
                continue
            old = rows[-1]
            if all(old[field] == fields[field] for field in FIELDS):
                unchanged += 1
                continue
            _move_to_history(store, old["id"])
            write.supersede("knowledge_entries", old["id"], fields, provenance)
            store.db.execute("DELETE FROM knowledge_entries WHERE id = ?", (old["id"],))
            replaced += 1
    return SyncSummary(added, unchanged, replaced, tuple(problems))


def history(store: Store, entry_id: str) -> List[Dict[str, Any]]:
    """Every version of the entry, the replaced ones from knowledge_history, oldest first.

    The last is the current version. An entry the store has never held gives
    an empty list.
    """
    versions = []
    # Every history row is a version, the ones a later version names in
    # supersedes among them, so the rows are read whole and not as current.
    for table in ("knowledge_history", "knowledge_entries"):
        cursor = store.db.execute(
            f"SELECT * FROM {table} WHERE entry_id = ? ORDER BY rowid", (entry_id,)
        )
        versions.extend(_decode(table, cursor, row) for row in cursor.fetchall())
    return versions


def _move_to_history(store: Store, row_id: str) -> None:
    """Copy the current row, whole, into knowledge_history, inside the caller's transaction."""
    names = ", ".join(_columns("knowledge_entries"))
    store.db.execute(
        f"INSERT INTO knowledge_history ({names}) SELECT {names} FROM knowledge_entries"
        " WHERE id = ?",
        (row_id,),
    )


def _files(paths: Sequence) -> List[Tuple[str, Path]]:
    """Each entry file to read, with the name it is reported under."""
    found = []
    for given in paths:
        path = Path(given)
        if path.is_file():
            found.append((path.name, path))
        elif path.is_dir():
            for entry in sorted(path.rglob("*.md")):
                if entry.is_file():
                    found.append((entry.relative_to(path).as_posix(), entry))
        else:
            raise KnowledgeError(f"there is no file or folder at {path}")
    return found


def _split(text: str):
    """The heading block's keys and values, and the text after it, or None and the text."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None, text
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            heading = {}
            for line in lines[1:index]:
                key, mark, value = line.partition(":")
                if mark and key.strip():
                    heading[key.strip()] = _unquoted(value.strip())
            return heading, "\n".join(lines[index + 1:])
    return None, text


def _unquoted(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _gist(body: str) -> str:
    """The first sentence of the body's first paragraph that is not a heading line."""
    for paragraph in re.split(r"\n\s*\n", body.strip()):
        if not paragraph.strip() or paragraph.lstrip().startswith("#"):
            continue
        point = " ".join(paragraph.split())
        found = _SENTENCE.match(point)
        return found.group(1) if found else point
    return ""
