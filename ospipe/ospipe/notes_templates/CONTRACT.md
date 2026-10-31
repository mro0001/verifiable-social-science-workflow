# notes_templates Contract

Purpose. Installs the notes templates into a project. The templates in the repository's `templates/notes/` (a README and one file per area) become the project's `notes/` folder. Appendix only (Table A2, "Notes templates").

## Produces

- `install_notes(project_dir, templates_dir=None) -> InstallResult(written, skipped)`
  - Copies each `*.md` in the templates folder to `<project_dir>/notes/` byte for byte, creating the `notes/` folder.
  - A file that already exists in `notes/` is listed as skipped and is not touched.
  - `written` and `skipped` list paths relative to the project folder (`notes/<file>`), in file name order.
  - The default templates folder is the repository's `templates/notes/`, found from the package's own path. When that folder does not exist, as in a replication folder's copy of `ospipe`, the call refuses and asks for `templates_dir`.
- `NotesTemplatesError(ValueError)`, raised for a templates folder that does not exist (the default one or a named one) and for a project folder that does not exist. Nothing is written.
- `default_templates_dir()`, the default templates folder.
- `python3 -m ospipe install-notes`, in the root contract.

## Frozen

- The installer never overwrites a file. Notes are records that are appended to, never replaced.
- Copies are byte for byte, and the templates folder is only read.
- The target is `<project_dir>/notes/`, and the default source is the repository's `templates/notes/`.

## Soft

- Message wording.
- As built. Only the templates folder's own `*.md` files are copied, not its subfolders. A project folder that does not exist is refused rather than made.

## Consumers

- root (`python3 -m ospipe install-notes`). The scholar runs it once when a project starts, and again to add a template that was added later.

## Fixture

- `tests/test_notes_templates.py` installs into temporary projects from the repository's `templates/notes/`, read only and checked unchanged, and counts the templates from that folder. It also runs a copy of the package that has no `templates/notes/` beside it.

## Status

- realized

## Not in this module

- What the notes say, and any change to `templates/notes/`.
