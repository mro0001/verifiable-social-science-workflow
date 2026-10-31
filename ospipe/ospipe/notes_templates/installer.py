"""Installing the notes templates into a project.

Each `*.md` in the templates folder is copied byte for byte to `<project>/notes/`. A file
that already exists is skipped and never touched, because notes are records that are
appended to, never replaced.
"""
import shutil
from pathlib import Path
from typing import List, NamedTuple

NOTES_DIR = "notes"


class InstallResult(NamedTuple):
    written: List[str]
    skipped: List[str]


class NotesTemplatesError(ValueError):
    pass


def default_templates_dir() -> Path:
    """The repository's `templates/notes/`, found from this package's own path."""
    return Path(__file__).resolve().parents[3] / "templates" / "notes"


def install_notes(project_dir, templates_dir=None) -> InstallResult:
    """Copy each template the project's notes folder lacks. Paths in the result are
    relative to the project folder."""
    project = Path(project_dir)
    if templates_dir is None:
        templates = default_templates_dir()
        if not templates.is_dir():
            raise NotesTemplatesError(
                "no templates folder at {0}, so name one with --templates".format(templates)
            )
    else:
        templates = Path(templates_dir)
        if not templates.is_dir():
            raise NotesTemplatesError("templates folder {0} does not exist".format(templates))
    if not project.is_dir():
        raise NotesTemplatesError("project folder {0} does not exist".format(project))

    notes = project / NOTES_DIR
    notes.mkdir(exist_ok=True)
    written: List[str] = []
    skipped: List[str] = []
    for template in sorted(templates.glob("*.md")):
        if not template.is_file():
            continue
        target = notes / template.name
        relative = "{0}/{1}".format(NOTES_DIR, template.name)
        if target.exists():
            skipped.append(relative)
            continue
        shutil.copyfile(str(template), str(target))
        written.append(relative)
    return InstallResult(written=written, skipped=skipped)
