# reconcile Contract

Purpose. Classify a reviewed return against the build lineage so every native Word gesture (accept, reject, edit, leave pending, comment) is recognized mechanically. Replaces the resolve-first procedure; the author reviews like a normal Word user.

## Produces

- `reconcile(return_docx, builds_dir, version) -> Reconciliation`
  - `version` is the build the review was of (e.g. `v002`); its baseline (e.g. `v001`) is read from the BUILDS.md ledger row; both md snapshots are read from `builds_dir`.
  - `Reconciliation` — NamedTuple:
    - `accepted: List[Change]` — AI change regions where the return carries the revision text.
    - `rejected: List[Change]` — AI change regions where the return carries the BASELINE text (the native Reject gesture).
    - `modified: List[Change]` — AI change regions where the return carries neither form (the author rewrote it; the return text is authoritative and reported).
    - `pending: List` — AI-authored tracked changes still unresolved in the return (from the returns leaf).
    - `author_edits: List[str]` — differences outside every known AI change region (the author's own work).
    - `comments: List` — margin comments (from the returns leaf).
    - `conflicts: List[str]` — regions the matcher cannot classify unambiguously. Never guessed.
  - `Change` — NamedTuple `(baseline_text: str, revision_text: str, context: str, found_text: Optional[str])`; `found_text` populated for `modified`.
- CLI `python3 -m review reconcile <return.docx> --builds-dir <dir> --of vNNN [--json]` prints each bucket and exits 0, since it classifies and is not a gate. A missing ledger, ledger row, baseline, or snapshot prints `reconcile failed` and the reason and exits 2.

## Frozen

- The semantics. Rejection means restoration of baseline text within a known AI change region. Silence is never converted into a ruling (pending stays pending; unmatchable stays conflict). reconcile never writes any file.
- Change regions are derived mechanically from the ledgered baseline and revision snapshots, never hand-declared.
- Builds on the returns leaf for extraction (pending spans, comments, accepted text); does not reimplement docx parsing.

## Soft

- Region derivation and matching mechanics (word-level diff granularity, context window size, whitespace and pandoc round-trip normalization), output formatting, additional Change fields.
- Realized choices (see reconciler.py docstring for detail):
  - Normalization: shared token normalizer for snapshots and return text — table decoration lines dropped, pipes become spaces (pipe tables and pandoc's re-rendered tables tokenize identically), hard-break backslashes stripped, pandoc escapes undone, ATX `#` markers dropped, smart punctuation to ASCII. Multiline-table cell wrapping is outside its guarantees.
  - Regions: SequenceMatcher word opcodes (autojunk off) merged across equal gaps of <= 2 tokens; context window 4 words each side, drawn from the revision. Both knobs are keyword parameters.
  - Ties break toward accepted (context+revision checked before context+baseline); an author edit inside a region makes the region `modified` with `found_text` authoritative, never a separate author edit (region-level subsumes word-level).
  - Pending: `ai_authors=("Claude",)` keyword selects AI deltas. A region whose "acceptance" is manufactured by pandoc's accept-mode applying an unresolved AI delta is suppressed from `accepted` and reported only via `pending`. Non-AI unresolved tracked changes surface as author edits or modified regions, not pending.
  - Author edits: word-diff hunks of return vs revision overlapping any derived region are attributed to that region's classification; only hunks outside every region are reported, as human-readable strings with a short location anchor.
  - `reconcile` also accepts `pandoc=` (passed to the returns leaf) and raises `ReconcileError` when ledger, row, baseline, or snapshot is absent. `format_reconciliation(rec)` renders the buckets for the CLI.
  - Ledger rows are read by the header row's column names, so the nine columns the build writes since 2026-10-29 and the seven of an older ledger both read. A row with more cells than its header, such as a nine-cell row a newer build appended under an older ledger's seven-column header, is read by the header's names for its first cells, and its extra trailing cells are ignored. A row with fewer cells than its header is skipped. Only `version` and `baseline` are used.

## Consumers

- The port step of the loop; ROUND_TRIP procedure; MANUSCRIPT_WORKFLOW.md appendix Compare and return.

## Fixture

- `fixture.py` — synthetic baseline and revision markdown with at least four AI change regions (word swap, sentence insertion, deletion, phrase rewrite), plus return builders producing final-state docx for each gesture (all accepted; one rejected; one modified; plus an author edit outside regions) and one return with a genuinely pending tracked change (reusing the returns fixture's OOXML injection).

## Status

- realized
- Moved from `ospipe` into the verification layer on 2026-10-29, reading the ledger by column name.
