# build Contract

Purpose. Produce a numbered immutable build, a Word document, reveal.js slides, or a web page, from resolved markdown, and keep the ledger honest.

## Produces

- `build(resolved_md: str, builds_dir, *, purpose: str, baseline: Optional[str] = None, bibliography=None, csl=None, reference_docx=None, source_git_hash: Optional[str] = None, pandoc: str = "pandoc", to: str = "docx", verification_dir=None, source_path=None, numbers_path=None) -> BuildResult`
  - `to` is `"docx"` (the default), `"revealjs"` (slides, written as `vNNN.html`), or `"html"` (a standalone web page, written as `vNNN.html`). Any other value, or a reference docx with slides or a page, raises `BuildError` before anything is written.
  - `verification_dir` is the folder that holds each stream's results file. When it is given, the build reads the verification status before building, with `source_path` as the source text and `numbers_path` as the numbers file (see `stream_status` below), and records it in the ledger row. The status never stops a build. When it is not given, no status is read and both new cells hold `-`.
- `BuildResult` — NamedTuple `(version: str, docx_path: str, snapshot_path: str, sha256: str)`; version shaped `vNNN`. `docx_path` holds the built file's path whatever its format (`vNNN.html` for slides or a page); the field keeps its name because the shape is frozen.
- Side effects, in order:
  1. `verify_ledger(builds_dir)` — re-hash every ledgered build file (`vNNN.docx`, or `vNNN.html` for slides or a page); any mismatch, missing file, or version with both a `.docx` and a `.html` file raises `BuildError` listing ALL problems. Each distinct extension is looked for once, so slides and pages sharing `.html` never read as two files for one version. No new build over a corrupted archive.
  2. When `verification_dir` is given, read each stream's results file. Nothing is written and no check is run.
  3. Next version = highest ledgered or on-disk version + 1 (`v001` when empty; `v000` is reserved for externally archived submitted documents and is never auto-assigned).
  4. Write `builds_dir/vNNN.md`, the resolved markdown, byte-exact.
  5. Run pandoc, under the fixed date below, (`--from markdown --to docx`, or `--to revealjs --standalone` for slides, or `--to html --standalone` for a page, plus `--citeproc --bibliography --csl` when a bibliography is given, plus `--reference-doc` when given) to `builds_dir/vNNN.docx` or `builds_dir/vNNN.html`.
  6. Append a `BUILDS.md` row, creating the file with its header if absent. The row holds version, date (the build's date, below), git, sha256, purpose, baseline, reviewed, verification, and runs. `reviewed` starts `no`. `git` is `source_git_hash` or `-`. `verification` is `unverified: <streams>`, naming each flagged stream in the order prose, citations, data, build, or `verified` when none is flagged. `runs` names the run of each stream whose results file is well formed, as `<stream>=<run_id>` joined by `; ` (for example `citations=<run_id>`), or `-` when there is none.
- The fixed date. Every build has a date, today's, or the UTC date of `SOURCE_DATE_EPOCH` when the environment sets one. Pandoc runs with `SOURCE_DATE_EPOCH` set to midnight UTC of that date, and the rest of the environment passes through unchanged. The date is the ledger row's `date`. So the same text built on the same date gives the same bytes in any folder, and any build can be rebuilt from its snapshot and its row. A `SOURCE_DATE_EPOCH` that is not a whole number of seconds raises `BuildError` before anything is written.
- `read_ledger(builds_dir) -> List[Dict[str, str]]` — the ledger's rows as the build's own parser reads them, each a mapping from column name to cell, in file order. A row written with the first seven columns has those seven keys, and a nine-column row has all nine. No ledger gives an empty list. A row of another width is left out, and `verify_ledger` reports it.
- `rebuild(builds_dir, version, *, bibliography=None, csl=None, reference_docx=None, pandoc="pandoc", to="docx", resolved_md=None) -> RebuildResult`
  - Copies `vNNN.md` into a new temporary folder under the same name, so a page with no title keeps the version's name as its title, and runs the build's own pandoc command for `to` there, under the epoch of midnight UTC of the row's date. It compares the result's checksum with the row's and removes the temporary folder.
  - `RebuildResult` is the NamedTuple `(match: bool, ledger_sha256: str, rebuilt_sha256: str, text_matches: Optional[bool])`. `match` says whether the two checksums are equal. `text_matches` says whether `resolved_md`, when given, equals the snapshot byte for byte, and is None otherwise.
  - It writes nothing in `builds_dir`. A version with no row, a row whose date is not `YYYY-MM-DD`, a missing snapshot, a failed pandoc run, an unknown `to`, or a reference docx with slides or a page raises `BuildError`. When a version has more than one row, the last counts.
- `stream_status(verification_dir, source_path, numbers_path) -> (flags, runs)`, in `verification.py`, for the four streams `prose`, `citations`, `data`, and `build`.
  - A stream is verified only when `verification_dir/<stream>.json` exists, parses with `schema` `verification-results` and `schema_version` 1, lists among its `inputs` checksums the checksum of the input that stream covers, and every item that needs a decision has a latest decision `approved` on the file's `run_id`. Otherwise it is flagged.
  - The input a stream covers is the source text for prose, citations, and build, and the numbers file for data. Its checksum is written as a verification run writes one, `sha256:` followed by the hex digest.
  - The fields read are `schema`, `schema_version`, `run_id`, `inputs` (file name to checksum), `items` (each with a text `id` and a true or false `needs_decision`), and `decisions` (each naming its `item`, with `decision` and `run_id`, in the order they were made). Other fields are ignored.
  - `flags` lists the flagged streams in the order above. `runs` maps each stream whose file is well formed to its `run_id`, flagged or not.
- `stream_detail(verification_dir, source_path, numbers_path) -> Dict[str, StreamDetail(state, run_id, open_items)]`, in `verification.py`, for the same four streams in the same order, by the same rule as `stream_status`.
  - `state` is `missing` (no results file), `unreadable` (a file that cannot be read or does not have the shape above), `out_of_date` (its `inputs` lack the covered input's checksum), `open` (current, with an item not approved on the file's run), or `verified`. The streams whose state is not `verified` are exactly the flags `stream_status` returns.
  - `run_id` is the file's `run_id`, or None for `missing` and `unreadable`.
  - `open_items` lists `(item id, held or undecided, item)` for each item that needs a decision and whose latest decision is not `approved` on the file's run, in the file's order. An out-of-date stream lists them too.
- `latest_decision(results, item_id) -> (decision, entry)`, in `verification.py`. The last decision listed for the item counts only when its `run_id` is the file's own. It gives `approved` or `held` with that decision's entry. A decision on another run, a decision word other than those two, or no decision gives `undecided` with None.
- `verify_ledger(builds_dir) -> None` — exported for standalone integrity checks.
- `BuildError(RuntimeError)`.

## Frozen

- The signature, BuildResult shape, ledger column set and order, and the verify-before-build refusal. The `to` keyword was added 2026-10-27 with a default of `"docx"`, so every earlier call builds exactly as before. The value `"html"` was added 2026-10-29, a website built as one standalone web page from one source file.
- The ledger gained the columns `verification` and `runs` after `reviewed` on 2026-10-29, nine columns in all, together with the keywords `verification_dir`, `source_path`, and `numbers_path`, each defaulting to None. An earlier call still builds as before, and its row holds `-` in both new cells. A ledger written with the first seven columns still parses and verifies, and new rows are appended to it with all nine.
- The verification status rule under `stream_status`, which `stream_detail` and `latest_decision` follow. `stream_status` itself was left unchanged when they were added on 2026-10-29. The build only reads results files. It runs no check of its own, and the status never stops a build.
- The fixed date was added on 2026-10-29. It changes no signature, column, or refusal. A build made before it has no fixed date, so its bytes may not rebuild.
- Builds are never edited in place; the snapshot is the resolved text byte-exact; citations render only here (citeproc at build time, nowhere else).
- System pandoc (the `pandoc` argument resolves on PATH), never Quarto's bundled copy.

## Soft

- Date format, ledger row formatting, version padding width, pandoc extra args.
- Refinements as built: every ledgered row is fully verified (file must exist AND its 64-hex sha256 must match), including hand-ledgered v000 external archives; unledgered on-disk `.docx` or `.html` files matching `vNNN` with an optional `.`/`_`/`-` suffix (e.g. `v000_submitted.docx`) are ignored by verification but counted for version numbering. Pipes in purpose/baseline are rewritten to `/` and whitespace collapsed so the ledger stays one row per line. A failed pandoc run removes its snapshot and partial docx, appends no row, and does not burn the version number. `--csl` is passed only alongside a bibliography.
- Status as built. A results file that is missing, cannot be read, or has another shape flags its stream and names no run. A source or numbers file that cannot be read flags the streams that cover it. The latest decision for an item is the last one listed for it. An older ledger keeps its seven-column header when rows are appended, and the two new cells and the run cells pass through the same cell cleaning as purpose and baseline.

## Consumers

- root (`python3 -m ospipe rebuild`), which resolves the source and passes it as `resolved_md`.
- root (`python3 -m ospipe build`), which passes the manuscript as `source_path`, the manifest as `numbers_path`, and `--verification-dir`, by default `verification` beside the manuscript. MANUSCRIPT_WORKFLOW.md appendix Builds.
- The verification layer's `reconcile` in its review package (`verification_procedures/review/reconcile/`), which reads `version` and `baseline` from ledger rows of either width as a file.
- evidence, which lists the unverified claims through `stream_detail` and reads decisions through `latest_decision`.

## Fixture

- `fixture.py` — synthetic resolved markdown, slides, and a page with a title and two sections (no placeholders remaining, fake values), synthetic ledger states including a tampered-docx case.
- The status tests cut their synthetic results files from the test story in `examples/test_story/` (`tests/test_build_verification.py`).

## Status

- realized
