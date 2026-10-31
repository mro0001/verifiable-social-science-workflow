# layout Contract

Purpose. The project's build file, a Makefile at the project root with one rule per research product. Each product has one source file and the build file names it, so it is always clear which draft is current. An older draft that could be mistaken for the current one carries an archive line.

## Produces

- `read_map(makefile_path) -> ProjectMap(project_dir, products, problems)`
  - `project_dir` is the Makefile's folder. `products` lists a `Product` for each product rule in the file's order, and `problems` lists every problem found.
  - A `Product` has `name`, `source`, `builds_dir`, `to`, `manifest`, `overlay`, `tables_dir`, `bib`, `csl`, `reference_doc`, `verification_dir`, and `purpose`. Every path is relative to the project folder.
  - The reader handles variable assignments with `=`, `:=`, and `?=` (which sets only a name not yet defined), the references `$(NAME)` and `${NAME}`, rules with tab-indented recipes, and backslash continuations.
  - A product is a rule whose expanded recipe, split as a shell would split it, has a word ending in `ospipe` followed by `build`. Its fields come from that command's options (`--manuscript`, `--builds-dir`, `--to`, `--manifest`, `--overlay`, `--tables-dir`, `--bib`, `--csl`, `--reference-doc`, `--verification-dir`, and `--purpose`).
  - `to` defaults to `docx`, and `verification_dir` to `verification` beside the source.
  - The problems are a product with no `--manuscript` or more than one, a source that does not exist, no `--manifest`, no `--builds-dir`, and two products sharing a builds dir. A product with a problem is still listed, with the missing field as `None`.
  - Other rules are ignored. Two products may share a source.
- `add_product(makefile_path, name, source, to="docx", builds_dir=None, bib=None, csl=None, reference_doc=None, tables_dir=None) -> Product`
  - This is the one place the build file's format is written. It only appends and never changes earlier text. It returns the product as `read_map` reads it back.
  - When the Makefile is absent it first writes a header comment (one rule per research product, each naming its one source file), `OSPIPE ?= PYTHONPATH='<absolute folder that holds the ospipe package>' python3 -m ospipe`, `MANIFEST ?= numbers.yml`, `PURPOSE ?= draft`, `PRODUCT ?=`, the rule `manifest` running `$(OSPIPE) emit-manifest --manifest $(MANIFEST)`, and the rule `emit` running `$(OSPIPE) emit --map Makefile --product $(PRODUCT)`, so `make emit PRODUCT=<name>` writes that product's replication folder.
  - When the Makefile exists it writes the `manifest` rule only when the file lacks it, and the `emit` rule only when the file has no `emit` target. Before them it writes a `?=` line for each of `OSPIPE`, `MANIFEST`, and `PURPOSE` the file does not define, and `PRODUCT ?=` when it is about to write the `emit` rule and the file does not define `PRODUCT`.
  - It then appends `.PHONY: <name>` and the rule `<name>: <source> $(MANIFEST)` with one recipe line, `$(OSPIPE) build --manuscript <source> --manifest $(MANIFEST)`, the given `--tables-dir`, `--bib`, `--csl`, and `--reference-doc`, and then `--to <to> --builds-dir <builds_dir> --purpose "$(PURPOSE)"`. `builds_dir` defaults to `builds/<name>`.
  - `AddProductError(ValueError)` with `.problems` lists every refusal at once, and the file is not touched. It refuses a name that is already a target (or `manifest` or `emit` when that rule is about to be written), a name holding anything but letters, digits, `_`, and `-`, a `to` other than `docx`, `revealjs`, or `html`, a source that does not exist, a builds dir another product uses, and a rule that would not read back as a product (as when the file sets `OSPIPE` to a command that does not end in `ospipe`). It checks the read-back on the file's text plus the appended text before it writes.
- `look_alikes(project_map) -> List[LookAlike(path, claims, reason, archived)]`
  - A markdown file in the project folder reads as a product when its title equals a source's title (reason `same title`), or its file name contains the source's file name without its extension (reason `name`). The title is the front matter's `title`, else the first `# ` heading, compared in lower case with runs of spaces collapsed. `claims` is that source and `path` the file, both relative to the project folder. The list is sorted by path.
  - Files in hidden folders, in every product's builds dir, and in `ship/` are not looked at, and neither is a product's source.
  - `author_draft.md` is never a look-alike, because the references and prose procedures read it.
  - `archived` is true when the first non-empty line after any front matter starts with `> ARCHIVE`.
- `archive(draft_path, superseded_by, project_map, on=None) -> str`
  - Inserts `> ARCHIVE <YYYY-MM-DD>: superseded by <path relative to the project folder>` and one blank line right after the front matter, or first when there is none, and keeps every other byte. It returns the line. `on` is a date or `YYYY-MM-DD` text and defaults to today. Relative paths are taken from the project folder.
  - `ArchiveError(ValueError)` with `.problems` lists every refusal at once, and the file is not touched. It refuses a draft that already has an archive line, a draft that is a product's source, `author_draft.md`, a draft that does not exist, a `superseded_by` that does not exist, and a date that is not `YYYY-MM-DD`.
  - It never moves, renames, or deletes a file.
- `python3 -m ospipe products`, `python3 -m ospipe add-product`, and `python3 -m ospipe archive`, in the root contract.

## Frozen

- The build file is a Makefile with one rule per research product, and a product is found by the `ospipe build` command in its recipe.
- The `Product` fields and their defaults, `to` as `docx` and `verification_dir` as `verification` beside the source.
- The five problem kinds above.
- `add_product` only appends, writes the `manifest` rule only when the file lacks it and the `emit` rule only when the file has no `emit` target, and refuses without touching the file.
- The product rule's form, one recipe line running `$(OSPIPE) build` with `--manuscript` naming the one source file.
- The archive line's form, `> ARCHIVE <YYYY-MM-DD>: superseded by <path>` as the first non-empty line after the front matter, the form the build procedure reads in its own test project.
- The `LookAlike` fields, the two reasons `same title` and `name`, and the folders a look-alike is never looked for in.
- `author_draft.md` is never a look-alike and never archived.

## Soft

- Problem wording and the order of problems, in all three functions.
- The header comment's wording and the blank lines between appended parts.
- As built. Comments start at an unescaped `#` outside a recipe. A reference to an undefined variable expands to nothing, and so does an automatic variable such as `$<`, and the environment is not read. An option never takes a following word that starts with `--` as its value, and an option with no value counts as not given. Rules whose target starts with `.` are skipped. A recipe line's leading `@`, `-`, and `+` are dropped, and the build command's options end at a shell word such as `&&` or `;`. When a rule's recipe holds more than one build command, the first is read. An option given twice other than `--manuscript` keeps its last value. A path outside the project folder is kept as written.
- As built for look-alikes. The name test is in lower case, as the build procedure's is. A title match is tried before a name match, and the first source in the build file's order that matches is the one claimed. `author_draft.md` is protected by its file name in any folder. Files that are not UTF-8 are read with replacement characters for the title, and `archive` keeps their bytes. The archive line takes the draft's own line ending.

## Consumers

- root (`python3 -m ospipe products`, `python3 -m ospipe add-product`, and `python3 -m ospipe archive`). Pipeline setup reads `products --json` and adds products with `add-product`, and writes no product or manifest rule of its own. The scholar or an AI session runs `archive`.
- replication, whose `closure` reads a product's fields from the map `read_map` gives.

## Fixture

- `fixture.py` for the reader. A build file with a manuscript and slides written with variables, a `?=` after an `=`, a continuation line, and a `manifest` rule that is not a product, the files it names, and a build file with one rule for each problem kind.
- `tests/test_layout_archive.py` writes its own project, with drafts that read as the sources by title and by name and files in each folder a look-alike is never looked for in.
- `tests/test_layout_add.py` writes its own sources, and runs `make` on a temporary copy of `examples/sample_project/` when `make` is on the path.

## Status

- realized

## Not in this module

- Removing or renaming a product, and archiving without a command.
