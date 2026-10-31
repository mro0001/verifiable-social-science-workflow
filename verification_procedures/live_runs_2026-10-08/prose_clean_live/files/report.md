# Prose verification

Every AI change between two pinned versions must be visible, carry a rationale, and have that rationale describe it honestly. Changes that touch numbers, citations, quotations, negation, or claim strength are handed to the data or citations stream. Author edits are listed, not judged.

Changes between the pinned versions: 5 (edit 2, insert 1, delete 1, move 1); AI 5, author 0. Judged: 5. Handed off to another stream: 0.

## Summary

- Blocking: 0
- Warnings: 1
- Notes: 2

## Problems

| Severity | Check | Item | Problem | Evidence |
|---|---|---|---|---|
| warning | judge_rationale | c04 | change alters meaning beyond what the rationale says | The rationale accurately describes the deletion of a redundant sentence, but the removal of the sentence itself constit… (live:qwen/qwen3.5-122b) |

## Versions

- Baseline: `baseline.md` v001 sha256:9ad819dfea4749532771aa6951edcc632e46d51d13be26a8fa12b6781c63d2c2
- Revised: `revised.md` (not ledgered) sha256:1911caaa40c99550d07077b5191aff6e7c50f7a1d4112ac37d3877f4ed476426

## Changes

| Id | Kind | Change (before -> after) | Rationale | Verdict | Hand-off |
|---|---|---|---|---|---|
| c01 | move | (moved, text unchanged) Prior work has focused mainly on private firms. | r01: Moved the gap statement ahead of the study aim so the aim answers it. | honest | - |
| c02 | edit | [-In this-] {+This+} study [-we examine-] {+examines+} whether structured interviews … in municipal agencies. | r02: Rewrote "In this study we examine" as "This study examines" for a more direct openin… | honest | - |
| c03 | edit | Structured interviews [-standardize the questions that-] {+ask+} every candidate [-answers.-] {+the same questions in the same order.+} | r03: Rephrased the definition in plainer words and made explicit that the order of questi… | honest | - |
| c04 | delete | [-Agencies that adopted the format did so for a variety of different reasons, and those rea…-] | r04: Deleted a redundant sentence that repeated itself and carried no evidence. | meaning changed | - |
| c05 | insert | {+The next section turns to the interview protocol itself.+} | r05: Added a signpost sentence pointing to the next section. | honest | - |

## Hand-off

None.

## Trail

Record numbers refer to `records/NN_<step>.json` in the run folder.

- c01: diff_changes (02, python3) -> content_handoff (04, no content tokens) -> rationale_coverage (05, r01) -> judge_rationale (06, live:qwen/qwen3.5-122b, prompt sha256:f0596234a9d3)
- c02: diff_changes (02, python3) -> content_handoff (04, no content tokens) -> rationale_coverage (05, r02) -> judge_rationale (06, live:qwen/qwen3.5-122b, prompt sha256:9cfe33ace5ec)
- c03: diff_changes (02, python3) -> content_handoff (04, no content tokens) -> rationale_coverage (05, r03) -> judge_rationale (06, live:qwen/qwen3.5-122b, prompt sha256:2696a893751d)
- c04: diff_changes (02, python3) -> content_handoff (04, no content tokens) -> rationale_coverage (05, r04) -> judge_rationale (06, live:qwen/qwen3.5-122b, prompt sha256:db33ea8a9380); flagged by judge_rationale
- c05: diff_changes (02, python3) -> content_handoff (04, no content tokens) -> rationale_coverage (05, r05) -> judge_rationale (06, live:qwen/qwen3.5-122b, prompt sha256:628fe40bf00f)

## Notes

- pin_versions / baseline.md: baseline is pinned version v001
- pin_versions / revised.md: revised hashed for the record (not yet ledgered)
