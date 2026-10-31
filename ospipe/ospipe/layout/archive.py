"""Archive lines for older drafts.

A markdown file that reads as a product's source (same title, or a file name holding the
source's name) is a look-alike. An older draft is marked by the line
`> ARCHIVE <YYYY-MM-DD>: superseded by <path>` right after its front matter. Marking never
moves, renames, or deletes a file.
"""
import datetime
import os
import re
from pathlib import Path
from typing import List, NamedTuple, Optional, Tuple

import yaml

from .project_map import ProjectMap, _relative

ARCHIVE_MARK = "> ARCHIVE"
SHIP_DIR = "ship"
# Read by the references and prose procedures, so never a look-alike and never archived.
PROTECTED = ("author_draft.md",)
SAME_TITLE = "same title"
SAME_NAME = "name"

_SPACES = re.compile(r"\s+")


class LookAlike(NamedTuple):
    path: str
    claims: str
    reason: str
    archived: bool


class ArchiveError(ValueError):
    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("cannot archive the draft\n" + "\n".join("  " + p for p in self.problems))


def _front_matter_end(text) -> Optional[int]:
    """The index just past the front matter's closing line, or None when there is none."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n").rstrip() != "---":
        return None
    offset = len(lines[0])
    for line in lines[1:]:
        offset += len(line)
        if line.rstrip("\r\n").rstrip() in ("---", "..."):
            return offset
    return None


def _split(text) -> Tuple[str, str]:
    end = _front_matter_end(text)
    if end is None:
        return "", text
    return text[:end], text[end:]


def _normal(title) -> str:
    return _SPACES.sub(" ", title).strip().lower()


def title_of(text) -> str:
    """The front matter's `title`, else the first `# ` heading, in lower case with runs of
    spaces collapsed. Empty when there is neither."""
    front, body = _split(text)
    if front:
        inner = front.splitlines()[1:-1]
        try:
            data = yaml.safe_load("\n".join(inner))
        except yaml.YAMLError:
            data = None
        if isinstance(data, dict) and isinstance(data.get("title"), str) and data["title"].strip():
            return _normal(data["title"])
    for line in body.splitlines():
        if line.startswith("# "):
            return _normal(line[2:])
    return ""


def is_archived(text) -> bool:
    """The first non-empty line after any front matter starts with `> ARCHIVE`."""
    _, body = _split(text)
    for line in body.splitlines():
        if line.strip():
            return line.strip().startswith(ARCHIVE_MARK)
    return False


def _read(path) -> str:
    return Path(path).read_bytes().decode("utf-8", errors="replace")


def _skipped_dirs(project_map) -> List[str]:
    skipped = [SHIP_DIR]
    for product in project_map.products:
        if product.builds_dir is not None:
            skipped.append(product.builds_dir.rstrip("/"))
    return skipped


def _inside(relative, folders) -> bool:
    return any(relative == folder or relative.startswith(folder + "/") for folder in folders)


def _sources(project_map) -> List[str]:
    found = []
    for product in project_map.products:
        if product.source is not None and product.source not in found:
            found.append(product.source)
    return found


def look_alikes(project_map: ProjectMap) -> List[LookAlike]:
    """Every markdown file in the project folder that reads as a product's source."""
    project_dir = Path(project_map.project_dir)
    sources = _sources(project_map)
    titles = []
    stems = []
    for source in sources:
        path = project_dir / source
        if path.is_file():
            title = title_of(_read(path))
            if title:
                titles.append((title, source))
        stem = os.path.splitext(os.path.basename(source))[0].lower()
        if stem:
            stems.append((stem, source))
    skipped = _skipped_dirs(project_map)

    found: List[LookAlike] = []
    for folder, dirs, files in os.walk(str(project_dir)):
        here = Path(folder).relative_to(project_dir).as_posix()
        kept = []
        for name in sorted(dirs):
            relative = name if here == "." else here + "/" + name
            if name.startswith(".") or _inside(relative, skipped):
                continue
            kept.append(name)
        dirs[:] = kept
        for name in sorted(files):
            if not name.endswith(".md") or name in PROTECTED:
                continue
            relative = name if here == "." else here + "/" + name
            if relative in sources:
                continue
            text = _read(project_dir / relative)
            claims, reason = None, None
            title = title_of(text)
            for source_title, source in titles:
                if title and title == source_title:
                    claims, reason = source, SAME_TITLE
                    break
            if claims is None:
                for stem, source in stems:
                    if stem in name.lower():
                        claims, reason = source, SAME_NAME
                        break
            if claims is None:
                continue
            found.append(LookAlike(path=relative, claims=claims, reason=reason, archived=is_archived(text)))
    return sorted(found, key=lambda item: item.path)


def _date_text(on) -> str:
    if on is None:
        return datetime.date.today().isoformat()
    if isinstance(on, datetime.date):
        return on.isoformat()
    try:
        return datetime.datetime.strptime(str(on), "%Y-%m-%d").date().isoformat()
    except ValueError:
        raise ArchiveError(["date {0} is not YYYY-MM-DD".format(on)])


def _in_project(path, project_dir) -> Tuple[str, Path]:
    relative = _relative(str(path), project_dir)
    full = Path(relative)
    if not full.is_absolute():
        full = project_dir / full
    return relative, full


def archive(draft_path, superseded_by, project_map: ProjectMap, on=None) -> str:
    """Insert the archive line and one blank line right after the draft's front matter,
    or first when there is none, keeping every other byte. Paths are relative to the
    project folder. Returns the line written."""
    project_dir = Path(project_map.project_dir)
    date_text = _date_text(on)
    draft, draft_full = _in_project(draft_path, project_dir)
    by, by_full = _in_project(superseded_by, project_dir)

    problems: List[str] = []
    data = None
    if os.path.basename(draft) in PROTECTED:
        problems.append(
            "{0} is read by the references and prose procedures and is never archived".format(draft)
        )
    if draft in _sources(project_map):
        problems.append("{0} is a product's source in the build file".format(draft))
    if not draft_full.is_file():
        problems.append("draft {0} does not exist".format(draft))
    else:
        data = draft_full.read_bytes()
        if is_archived(data.decode("utf-8", errors="replace")):
            problems.append("{0} already has an archive line".format(draft))
    if not by_full.is_file():
        problems.append("{0} does not exist".format(by))
    if problems:
        raise ArchiveError(problems)

    text = data.decode("utf-8", errors="surrogateescape")
    newline = "\r\n" if text.split("\n", 1)[0].endswith("\r") else "\n"
    line = "{0} {1}: superseded by {2}".format(ARCHIVE_MARK, date_text, by)
    end = _front_matter_end(text)
    if end is None:
        new_text = line + newline + newline + text
    else:
        head = text[:end]
        if not head.endswith("\n"):
            head += newline
        new_text = head + line + newline + newline + text[end:]
    draft_full.write_bytes(new_text.encode("utf-8", errors="surrogateescape"))
    return line
