# annotate Contract

Purpose. Attach Word margin comments to a docx, anchored to text. The companion channel to tracked changes; edits carry the what, comments carry the why (claim grounding, rearrangement rationale, section jobs, outline notes).

## Produces

- `annotate(docx_path, annotations, out_path, author: str = "Claude") -> AnnotateResult`
  - `annotations: Sequence[Annotation]`; `Annotation` — NamedTuple `(anchor: str, text: str, tag: Optional[str])`. `anchor` is literal text located in the document; the comment lands on the first paragraph whose text contains it. A non-empty `tag` is prefixed to the comment as `[tag] `.
  - `AnnotateResult` — NamedTuple `(count: int, out_path: str, misses: List[str])`; `misses` lists anchors found nowhere (reported, never fatal; the caller decides).
- `load_annotations(yaml_path) -> List[Annotation]` — YAML list of mappings with keys `anchor`, `text`, optional `tag`.
- CLI: `python3 -m review annotate --docx <in> --spec <yaml> --out <out> [--author NAME]` — prints count and misses; exit 0 even with misses (they print to stderr).

## Frozen

- The signatures and shapes. The input docx is never modified; output goes to `out_path` only.
- Comments are readable back by the returns leaf (`extract(out).comments` returns them with author and text); this round trip is the contract's test.
- Ledgered builds are never annotated in place; annotation targets working artifacts (compare documents, copies).

## Soft

- Anchor matching detail (paragraph-level v1; run-level tightening later), tag vocabulary, initials, comment ordering.
- Known v1 limitation, discovered live 2026-07-23. Text inside PENDING tracked changes (w:ins runs) is invisible to paragraph-level anchoring, so a comment cannot anchor on an unaccepted insertion; anchor on adjacent base text instead. Walking w:ins runs is the tightening path.

## Consumers

- The compare step of the loop (annotated compare documents for author review). MANUSCRIPT_WORKFLOW.md appendix Compare and return.

## Fixture

- `fixture.py` — synthetic docx builder plus a three-annotation spec (one heading section-job, one claim grounding note, one deliberate miss).

## Status

- realized
- Moved from `ospipe` into the verification layer on 2026-10-29.
