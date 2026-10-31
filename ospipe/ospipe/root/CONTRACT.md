# root Contract

Purpose. The composition root. Wires resolve, build and rebuild, the manifest emitter, the build file's reader, writer, and archive lines, the notes installer, the evidence files, and the replication folder into the command line a paper workspace calls. It is the only place modules meet.

## Produces

- `run_check(manuscript_path, manifest_path, overlay_path=None, tables_dir=None, out_path=None) -> CheckResult(resolved, wrote)`
  - Loads the manifest (with overlay), resolves (the hard gate), and optionally writes the resolved markdown. Nothing else runs.
- `python3 -m ospipe check --manuscript <md> --manifest <yml> [--overlay <yml>] [--tables-dir <dir>] [--out <md>]`
  - Resolve failure exits 2 listing every missing key. Success exits 0 and prints the resolved text unless `--out` is given.
- `python3 -m ospipe build <check args> --builds-dir <dir> --purpose <str> [--baseline <str>] [--bib] [--csl] [--reference-doc] [--to docx|revealjs|html] [--verification-dir <dir>]`
  - Runs the check path, then the build leaf. `--to revealjs` builds reveal.js slides (`vNNN.html`) and `--to html` a standalone web page (`vNNN.html`) instead of a Word document. Build failure exits 3. Source git hash recorded best-effort from the manuscript's repo.
  - The build reads each stream's results file from `--verification-dir`, by default `verification` beside the manuscript, with the manuscript as the source text and the manifest as the numbers file. It records the status in the ledger row and prints it on the line after the build line, `unverified: <streams>` or `verified`. The status never stops a build.
- `python3 -m ospipe rebuild <check args> --builds-dir <dir> --version vNNN [--bib] [--csl] [--reference-doc] [--to docx|revealjs|html]`
  - Resolves the source as `check` does, then rebuilds the version from its snapshot under its ledger date (`ospipe/build/CONTRACT.md`). It prints `match vNNN sha256 <first 12>` and exits 0 when the resolved text equals the snapshot and the checksums agree. It prints `text differs from vNNN` and exits 1 when the resolved text is not the snapshot, and otherwise `mismatch vNNN ledger sha256 <sha> rebuilt sha256 <sha>` and exits 1. A resolve failure exits 2, and a rebuild that cannot run (no row for the version, for example) exits 3. Nothing is written.
- `python3 -m ospipe emit-manifest --manifest <yml> [--outputs-dir <dir>]`
  - Runs the manifest emitter (`ospipe/manifest/CONTRACT.md`) on the numbers file, reading each entry's output under `--outputs-dir`, by default the manifest's folder. It prints `<key>: <old> -> <new>` for each change, or `<file> unchanged`, and exits 0. Any problem exits 2 listing every problem, and the file is not touched.
- `python3 -m ospipe products [--map <Makefile>] [--json]`
  - Reads the build file (`ospipe/layout/CONTRACT.md`), by default `Makefile` in the current folder. It prints `<name>: <source> -> <builds_dir> (<to>)` for each product and then each problem. After the problems it prints `not archived: <path> reads as <source> (<reason>)` for each look-alike without an archive line, as advice that leaves the exit code alone. `--json` prints the whole map instead, `project_dir`, `products` with every field, and `problems`. Any problem exits 2, and a missing build file exits 2.
- `python3 -m ospipe add-product --name <name> --source <file> [--to docx|revealjs|html] [--builds-dir <dir>] [--bib <file>] [--csl <file>] [--reference-doc <file>] [--tables-dir <dir>] [--map <Makefile>]`
  - Appends the product's rule to the build file (`ospipe/layout/CONTRACT.md`), by default `Makefile` in the current folder, writing the header, variables, and `manifest` rule first when the file lacks them. Paths are relative to the build file's folder. It prints `added <name> to <map>, <source> -> <builds_dir> (<to>)` and exits 0. A refusal exits 2 listing every problem, and the file is not touched.
- `python3 -m ospipe archive <draft> --by <file> [--date YYYY-MM-DD] [--map <Makefile>]`
  - Marks an older draft as archived (`ospipe/layout/CONTRACT.md`), inserting `> ARCHIVE <date>: superseded by <file>` after its front matter. Paths are relative to the build file's folder, and the date defaults to today. It prints `archived <draft>, <line>` and exits 0. A refusal exits 2 listing every problem, and the file is not touched. A missing build file exits 2.
- `python3 -m ospipe install-notes --project <dir> [--templates <dir>]`
  - Copies the notes templates into the project's `notes/` folder (`ospipe/notes_templates/CONTRACT.md`), by default from the repository's `templates/notes/`. It prints `wrote notes/<file>` for each file it wrote and `skipped notes/<file>, already there` for each file it left alone, and exits 0. A refusal exits 2 and writes nothing.

- `python3 -m ospipe unverified --source <file> --manifest <yml> [--verification-dir <dir>] [--out <md>]`
  - Lists the unverified claims (`ospipe/evidence/CONTRACT.md`) of the source file, reading each stream's results file from `--verification-dir`, by default `verification` beside the source, with the manifest as the numbers file. It prints one line per entry, `<stream> <item> <state>` and then `, <summary>` when there is one, and then `<n> unverified`. With `--out` it also writes the same as a markdown list. It always exits 0.

- `python3 -m ospipe emit --product <name> [--map <Makefile>] [--out <dir>] [--version vNNN] [--replace]`
  - Writes the product's replication folder (`ospipe/replication/CONTRACT.md`), by default `ship/<product>` in the build file's folder, from the build file, by default `Makefile` in the current folder. It ships `--version`, or else the last row of the product's ledger, with the folder's own `Makefile`, `README.md`, `unverified_claims.md`, and, when the folder holds the citations results, `citation_evidence.yaml`, and puts the folder in place only after a copy of it outside the project rebuilds with a match. `--replace` puts a new folder in place of an existing replication folder emit wrote, and refuses any other existing `--out`. An `--out` that is or holds the project folder, any product's builds dir, or a file the product needs is refused. It prints `emitted <product> <version> to <dir>, <n> files` and exits 0. A refusal exits 2 listing every problem, or the rebuild's output, and nothing is written. A missing build file exits 2.

- `python3 -m ospipe citation-evidence [--verification-dir <dir>] [--citation-log <yaml>] --out <yaml>`
  - Writes the citation evidence file (`ospipe/evidence/CONTRACT.md`) as YAML from `<dir>/citations.json`, by default `verification` in the current folder, joined to the citation log, by default `audit/citation_log.yaml` in the current folder when that file exists. It prints `wrote <out>, <n> citations` and exits 0. A results file or a named citation log it cannot read exits 2 and writes nothing.

## Frozen

- A resolve error always fails the check (exit 2). Nothing downstream sees unresolved text.
- A build error exits 3.
- `rebuild` exits 0 only on a match, and writes nothing.
- An emit-manifest problem exits 2 and leaves the numbers file as it was.
- A problem in the build file exits 2 from `products`, and a refusal exits 2 from `add-product` with the build file as it was.
- A refusal exits 2 from `archive` with the draft as it was.
- `install-notes` never overwrites a file, and a refusal exits 2.
- `unverified` always exits 0.
- A refusal exits 2 from `citation-evidence`, and nothing is written.
- A refusal exits 2 from `emit`, nothing is written, and an existing folder is left as it was.
- Table includes come from `--tables-dir`. Each `<key>.md` file in the directory is table key `<key>`.

## Soft

- Flag names beyond the four check flags, message formats, CheckResult extras.

## Consumers

- Paper-workspace `make` rules (adoption-time). MANUSCRIPT_WORKFLOW.md appendix.

## Fixture

- Assembled from children's fixtures in `tests/test_root_composition.py`.

## Status

- realized
