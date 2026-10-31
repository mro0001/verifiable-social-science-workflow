---
id: loop-compare-and-return
title: The Word compare-and-return loop
source: MANUSCRIPT_WORKFLOW.md
source_commit: sha256:4f5317e8258d
updated: 2026-07-23
group: LOOP
---

# The Word compare-and-return loop

AI edits reach the author as native Microsoft Word tracked changes, and the author reviews with ordinary Word gestures. Accept, reject, edit, comment, or leave a change pending; three-way reconciliation against the build lineage recognizes every gesture mechanically. Builds are numbered and immutable, and after the author's review is ported, a port-only build becomes the next compare baseline.

1. Build a numbered document from canonical markdown. Builds are never edited in place; hash checks enforce immutability.
2. Run Word Compare on the last baseline against the new build, with formatting comparison unchecked and the label set to the AI's name. The comparison renders the AI's edits as ordinary tracked changes for the author. Margin comments carrying rationale, section jobs, or grounding notes are attached to the compare document by the annotate step.
3. The author reviews natively and hands the document back. Track Changes on is recommended because it preserves attribution and dates, but nothing is lost without it.
4. The AI reconciles the return against the ledgered baseline and revision snapshots. An AI change region carrying the revision text was accepted; carrying the baseline text, rejected; carrying neither, rewritten by the author (the author's text wins). Changes still pending as unresolved revision marks stay pending and become questions; silence is never converted into a ruling. Differences outside every AI change region are the author's own edits, recovered even when made without Track Changes.
5. A change touching a number becomes a question to the author, never an automatic edit, because canonical text carries manifest placeholders where the returned document carries resolved numerals.
6. A change touching a citation or the References section becomes an edit to the citation key in canonical markdown. Rendered citations are generated at build time and cannot round-trip back into source form.
7. After porting, run a port-only build. That build is the next compare baseline.

The reconciliation in step 4 works because the system holds three states of the document, the baseline snapshot, the revision snapshot, and the return; a rejection is recognizable as restoration of baseline text inside a known change region.

## Consult also

- formats-numbers-manifest — for the placeholder grammar behind the number-question rule in step 5.
- verification-witness-rule — the tracked changes this loop produces are the witness for prose revisions.
