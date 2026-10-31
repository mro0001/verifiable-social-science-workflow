# replication Contract

Purpose. Works out what a research product depends on, the source text, data, code, build settings, and records its replication folder needs (appendix A2.3 "Replication folder", Figure A3, Table A2 "Replication folder with fixed-date builds", and A2.4 ¶2), and writes that folder, `ship/<product>/` by default, so it rebuilds the shipped build with the project out of reach (`make emit`).

## Produces

- `closure(project_map, product_name) -> Closure(files, notes)`, in `closure.py`.
  - `project_map` is the build file's map as `layout.read_map` gives it. Every path is read relative to its `project_dir`, the build file's folder.
  - `files` is a sorted list of distinct paths relative to the project folder, written with `/`.
  - `notes` lists, in the order below, what was absent, such as `no pipeline.yaml, so the analysis is not shipped`.
- What `files` holds, each path once.
  - The product's source, its manifest, and its overlay, bibliography, citation style, and reference document when its rule names them.
  - `<tables_dir>/<key>.md` for each `{{table:key}}` in the source, by the foundation's placeholder grammar.
  - Each local image the source names in markdown image syntax, `![alt](path)` or `![alt](<path> "title")`, read relative to the project folder, where the build runs. An image inside a fenced code block is not an image, and a path that starts with a scheme such as `https:` or `data:` is not local.
  - When `pipeline.yaml` is in the project folder, that file and every file it names, its `helpers` and each step's `script`, `inputs`, and `outputs`. Then `params.yaml` when present, and, when `acquisition.yaml` is present, that file and each `raw` entry's `file`. Without `pipeline.yaml` none of the three is read, and the note says the analysis is not shipped.
  - `prose.json`, `citations.json`, `data.json`, and `build.json` in the product's verification folder (its rule's `--verification-dir`, by default `verification` beside the source), each when present.
  - The audit layer's written-out records at their default places in the project, `audit/citation_log.yaml`, `audit/session_writes.jsonl`, and `audit/rationales.yaml`, each when present.
- `notes` holds, for each absent file of the last three groups, one line `no <path>, so <what> is not shipped`, or for `params.yaml` and `acquisition.yaml` the lines `no params.yaml, so no parameters are shipped` and `no acquisition.yaml, so the raw data are not declared`.
- `ReplicationError(problems)`, a `ValueError` whose `.problems` lists every problem at once.
  - A file the rule, the source, `pipeline.yaml`, or `acquisition.yaml` names is missing.
  - A named path is absolute (it starts with `/`, `~`, or a drive letter) or leaves the project folder.
  - The source names a table and the rule has no `--tables-dir`.
  - `pipeline.yaml` or `acquisition.yaml` cannot be read as a YAML mapping, its steps or raw entries are not lists of mappings, or a raw entry has no `file`.
  - The build file has no product of that name, or reports a problem with that product.
- `STREAMS`, `PIPELINE`, `PARAMS`, `ACQUISITION`, and `AUDIT_RECORDS`, the names above.
- `PIPELINE_MODULES`, in `emit.py`, the pipeline's module folders, `foundation`, `resolve`, `build`, `root`, `manifest`, `layout`, `evidence`, `replication`, and `notes_templates`. A test keeps it equal to the package's module folders other than the ones moved to other layers.
- `emit(project_map, product_name, out_dir=None, version=None, replace=False) -> EmitResult(out_dir, version, files)`, in `emit.py`.
  - `out_dir` defaults to `<project>/ship/<product>`. The result gives it as an absolute path, the version shipped, and `files`, every file in the folder, sorted and relative to it.
  - It computes the closure and picks the build to ship, `version` or else the last row of the product's ledger.
  - In a new temporary folder beside `out_dir` it writes every closure file at its relative path, the chosen build's file (`vNNN.docx`, or `vNNN.html` for slides or a page) and its `vNNN.md` under the product's builds dir, a `BUILDS.md` there holding the project ledger's header lines and that version's row only, and the package under `tools/ospipe/`, its `__init__.py`, `__main__.py`, and the `PIPELINE_MODULES` folders, without `__pycache__`.
  - It then writes the folder's own files there (`ship_files.py`, below).
  - It then copies that folder to a second temporary folder outside the project and runs `python3 -m ospipe rebuild` there, with the Python that runs `emit`, `PYTHONPATH=tools`, and the product's options from its rule (`--manuscript`, `--manifest`, `--overlay`, `--tables-dir`, `--builds-dir`, `--version`, `--bib`, `--csl`, `--reference-doc`, and `--to`). Unless that prints `match vNNN`, it removes both temporary folders and refuses with the command's output.
  - Last, it puts the folder in place. With `replace`, an existing `out_dir` is set aside, the new folder is put in its place, and only then is the old one removed.
  - It refuses, with nothing written and any existing `out_dir` as it was, by raising `ReplicationError` for a closure problem, a product with no build, a `version` with no ledger row, a missing build file or snapshot, a builds dir outside the project folder, an `out_dir` that is or holds the project folder, any product's builds dir, or a closure file (so `replace` can never remove them), an existing `out_dir` that is not a folder, an existing `out_dir` without `replace`, an existing `out_dir` with `replace` that is not a replication folder emit wrote (one holding `tools/ospipe/__init__.py` and a ledger outside `tools/`), and a folder that does not rebuild with a match. A folder it made on the way to `out_dir` is removed again.
  - It also refuses, leaving nothing written, a closure file at the path of one of the folder's own files (`Makefile`, `README.md`, `citation_evidence.yaml`, `unverified_claims.md`), which would be written over, and a `pipeline.yaml` step with no `runner` or no one `script`, which `make results` cannot run.
- `write_ship_files(folder, project_dir, product, version, found) -> List[str]`, in `ship_files.py`, which `emit` calls on the new folder before its rebuild check. It returns the names it wrote, in the order below.
  - `Makefile`. A header comment saying `ospipe emit` wrote it from the project's build file and naming the project folder, the product, and the build, that it is never edited by hand, and that the project is fixed and emitted again instead. Then `OSPIPE := PYTHONPATH=tools python3 -m ospipe`, the first and default rule `check` running `$(OSPIPE) rebuild` with the product's options and `--version vNNN`, and, when the closure holds `pipeline.yaml`, the rule `results` running each step as `<runner> <script>` in the file's order and then `$(OSPIPE) emit-manifest --manifest <manifest>`. Last, `.PHONY` names the rules. Nothing in it is newer than GNU Make 3.81.
  - `unverified_claims.md`, the list of unverified claims (`evidence.unverified_claims` and `evidence.markdown_list`) read from the folder's own source, numbers file, and results files, the same text `python3 -m ospipe unverified --out` writes there.
  - `citation_evidence.yaml`, when the folder holds the product's `citations.json`, the citation evidence file (`evidence.citation_evidence`) with the folder's `audit/citation_log.yaml` when it holds one. Its `results_file` is the path relative to the folder, so it is the same text `python3 -m ospipe citation-evidence --verification-dir <dir> --out FILE` writes when run in the folder. A results file or log the evidence file cannot be written from gives no file and a README line saying why.
  - `README.md`, written last. What the folder is and which project and product it came from. How to rebuild (`make`, and the check rule's command line for use without Make) and how to rerun the analysis (`make results`, then `make`), or, without `pipeline.yaml`, that the folder ships its computed results only. The shipped build's file, version, ledger date, and checksum. The tool versions at emit (Python, PyYAML, and the first line of `pandoc --version`) with a note that a different Pandoc can change the bytes. The verification status at emit (`build.verification.stream_status`'s flags on the folder's results files, in the ledger's form, which can differ from the shipped ledger row when results came after the build), the citation evidence file when there is one, the unverified claims or `None`, and the closure's notes. A line asking for a review before the folder is shared. A table of every other file in the folder with its sha256.
- `rebuild_args(product, version)`, `check_command(product, version)`, and `makefile_text(project_name, product, version, steps)`, in `ship_files.py`, the rebuild's words, the check rule's command line, and the Makefile's text.
- `SHIP_FILES`, the four names above.

## Frozen

- The closure copies and writes nothing and runs no program. It only reads the build file's map, the source, and the three declarations.
- `emit` ships one existing build, rebuilt byte for byte from the shipped files before the folder is put in place, and never writes over an existing folder without `replace`.
- The folder's `Makefile` has `check` as its default rule, and its README lists every other file in the folder with its sha256. Both are written by `emit` and never by hand.
- The folder's package holds only the `PIPELINE_MODULES` folders and the package's two own files.
- Every path in `files` is inside the project folder.
- The closure never reads the contents of a script, a data file, a results file, or a record. Those files ship whole.
- Every problem is reported in one `ReplicationError`.

## Soft

- Note and problem wording. The order of the notes.
- The README's wording and section order, the Makefile's header wording.
- As built for `write_ship_files`. The project is named by its folder's name, never its full path. A step's runner is written as it stands in `pipeline.yaml` and its script quoted for the shell. The README's checksum table escapes `|` in a path.
- As built for `emit`. The temporary folder beside `out_dir` is hidden (its name starts with `.`). The ledger row shipped is the last line in `BUILDS.md` for that version, copied as written. Closure files are copied by content only, without their times or modes. An `out_dir` inside the project folder but outside `ship/` is not skipped by `layout.look_alikes`, so the shipped source there reads as a look-alike. The default `ship/<product>` is skipped.

## Consumers

- `emit`, which copies the closure's `files` into the replication folder, and `write_ship_files`, whose README carries the closure's `notes`.
- root (`python3 -m ospipe emit`), and the build file's `emit` rule that `layout.add_product` writes (`make emit PRODUCT=<name>`).

## Fixture

- `fixture.py` holds the closures expected for the sample project's manuscript and slides, stand-ins for the results files and the audit records, and lines a test appends to the manuscript. The tests run on a temporary copy of `examples/sample_project/` with a build file written by `layout.add_product` (`tests/test_replication_closure.py`).
- `tests/test_replication_emit.py` builds the manuscript of such a copy once with `python3 -m ospipe build` and emits it, and runs `make emit PRODUCT=manuscript` when `make` is on the path.
- `tests/test_replication_ship.py` emits such a copy, moves the folder out of the project, and runs `make`, `make results`, and the check rule's command line there. Its results files and citation log are written in the test from `evidence/fixture.py`.
- `tests/test_pipeline_composition.py` runs the pipeline's commands as a scholar would, from source files to replication folder.

## Status

- realized
