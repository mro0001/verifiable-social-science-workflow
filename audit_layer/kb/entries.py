"""Reading the knowledge base's entry files (appendix A2.4 "Creating entries").

An entry is one file <group lowercased>/<id>.md in the corpus. It opens with a
frontmatter block of six keys between two lines of three hyphens, then a title
line, a point paragraph, the facts, and optional Gaps and Consult also
sections. This module only reads entries. The rules they must keep live in
check.py.
"""
import re
from pathlib import Path

KEYS = ("id", "title", "source", "source_commit", "updated", "group")

_FENCE = "---"


def entry_files(corpus):
    """The entry files of a corpus, every <folder>/<file>.md, sorted."""
    return sorted(Path(corpus).glob("*/*.md"))


def first_sentence(text):
    """The shortest start of the text that ends a sentence, uncut.

    The text's whitespace is collapsed first. A sentence ends at a full stop,
    exclamation mark, or question mark followed by a space or by the end. Text
    with no such end is returned whole.
    """
    flat = " ".join(text.split())
    match = re.search(r"[.!?](?= |$)", flat)
    if match is None:
        return flat
    return flat[: match.end()]


def parse_entry(path, corpus):
    """One entry file read into its parts.

    The dict holds path, rel (<folder>/<file>), front (each frontmatter key
    with its value as text), body (the text after the frontmatter, stripped),
    point (the first paragraph of the body that is not a heading, with its
    newlines as spaces), description (the point's first sentence), and
    problems (a missing or unclosed frontmatter block).
    """
    path = Path(path)
    rel = path.relative_to(Path(corpus)).as_posix()
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    front = {}
    problems = []
    if not lines or lines[0].strip() != _FENCE:
        problems.append("no frontmatter block")
        body_lines = lines
    else:
        closing = None
        for number in range(1, len(lines)):
            if lines[number].strip() == _FENCE:
                closing = number
                break
        if closing is None:
            problems.append("the frontmatter block is not closed")
            body_lines = []
        else:
            for line in lines[1:closing]:
                if not line.strip():
                    continue
                key, _, value = line.partition(":")
                front[key.strip()] = value.strip().strip("'\"")
            body_lines = lines[closing + 1 :]
    body = "\n".join(body_lines).strip()
    point = ""
    for block in _blocks(body):
        if not block[0].startswith("#"):
            point = " ".join(line.strip() for line in block)
            break
    return {
        "path": path,
        "rel": rel,
        "front": front,
        "body": body,
        "point": point,
        "description": first_sentence(point),
        "problems": problems,
    }


def _blocks(body):
    """The body split into paragraphs, each a list of lines.

    A blank line ends a paragraph, and a heading line is a paragraph of its own.
    """
    found = []
    current = []
    for line in body.splitlines():
        if not line.strip():
            if current:
                found.append(current)
                current = []
        elif line.startswith("#"):
            if current:
                found.append(current)
                current = []
            found.append([line])
        else:
            current.append(line)
    if current:
        found.append(current)
    return found


def load(corpus):
    """Every entry of a corpus, parsed, in file order."""
    return [parse_entry(path, corpus) for path in entry_files(corpus)]
