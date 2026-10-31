# returns Contract

Purpose. Extract the author's tracked edits and margin comments from a reviewed docx so they can be ported into canonical markdown delta by delta. Read-only; porting is a human-in-the-loop act.

## Produces

- `extract(reviewed_docx, *, pandoc: str = "pandoc") -> ReturnBundle`
- `ReturnBundle` — NamedTuple:
  - `deltas: List[Delta]`
  - `comments: List[Comment]`
  - `tracked_markdown: str` — pandoc `-f docx --track-changes=all --wrap=none -t markdown` output.
  - `accepted_markdown: str` — same with `--track-changes=accept`; the input for the belt-and-braces word-level diff against the frozen build snapshot.
- `Delta` — NamedTuple `(kind: str, text: str, author: str, date: str, touches_number: bool)`; kind is `insertion` or `deletion`; parsed from pandoc's `[text]{.insertion author="..." date="..."}` and `{.deletion}` spans, including multi-word spans and spans containing brackets-free punctuation.
- `Comment` — NamedTuple `(author: str, text: str)`; read via python-docx (API if available, raw XML part otherwise).

## Frozen

- The signature and the three shapes. extract never writes any file and never modifies the docx.
- `touches_number` is true iff the delta text contains a digit (the triage flag; porting rules live upstream).
- Span parsing recognizes pandoc's standard insertion/deletion span syntax with author and date attributes.

## Soft

- Comment anchoring detail, context extraction, additional flags on Delta, handling of nested or paired ins/del spans.

## Consumers

- The `review returns` command (`python3 -m review returns`, run from `verification_procedures/`).
- The `reconcile` and `annotate` modules of this package.
- MANUSCRIPT_WORKFLOW.md appendix Compare and return.

## Fixture

- `fixture.py` — a PROGRAMMATICALLY BUILT docx with one insertion, one deletion (standard OOXML `w:ins` / `w:del` elements, author and date attributes) and one margin comment, built with python-docx (raw oxml injection for revisions). Synthetic text, real revision-mark shapes; this is the real-shape test of the pandoc parse.

## Status

- realized
- Moved from `ospipe` into the verification layer on 2026-10-29.
