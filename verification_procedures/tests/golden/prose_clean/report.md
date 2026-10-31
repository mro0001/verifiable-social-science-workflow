# Prose verification

This report lists each change between the scholar's last draft and the final build's text, for the scholar to verify. A change is the AI's when the record of the AI's changes names it. Each AI change is shown with its sentence before and after and the reason the record gives, and the scholar approves or holds it. A program notes each AI change with no recorded reason and points out each one that alters a number, a citation, a quotation, a negation, or how strongly a claim is stated. No model judges any change. The scholar's own changes are listed and not checked.

Changes between the two texts 5 (edits 2, inserts 1, deletes 1, moves 1). AI changes by the record 5 (with no recorded reason 0, altering content 0). The scholar's own changes 0.

## Summary

- Blocking: 0
- Warnings: 0
- Notes: 2

## Problems

None.

## Versions

- The scholar's last draft `baseline.md` (v001) sha256:9ad819dfea4749532771aa6951edcc632e46d51d13be26a8fa12b6781c63d2c2
- The final build's text `revised.md` (not ledgered) sha256:1911caaa40c99550d07077b5191aff6e7c50f7a1d4112ac37d3877f4ed476426

## AI changes

### c01 (move)

- **Before:** Prior work has focused mainly on private firms.
- **After:** Prior work has focused mainly on private firms.
- **Stated reason:** Moved the gap statement ahead of the study aim so the aim answers it.

### c02 (edit)

- **Before:** In this study we examine whether structured interviews are associated with lower first-year turnover in municipal agencies.
- **After:** This study examines whether structured interviews are associated with lower first-year turnover in municipal agencies.
- **Stated reason:** Rewrote "In this study we examine" as "This study examines" for a more direct opening; the aim is unchanged.

### c03 (edit)

- **Before:** Structured interviews standardize the questions that every candidate answers.
- **After:** Structured interviews ask every candidate the same questions in the same order.
- **Stated reason:** Rephrased the definition in plainer words and made explicit that the order of questions is also fixed, which "standardize" implied.

### c04 (delete)

- **Before:** Agencies that adopted the format did so for a variety of different reasons, and those reasons varied a great deal.
- **After:** (none)
- **Stated reason:** Deleted a redundant sentence that repeated itself and carried no evidence.

### c05 (insert)

- **Before:** (none)
- **After:** The next section turns to the interview protocol itself.
- **Stated reason:** Added a signpost sentence pointing to the next section.

## The scholar's own changes

These changes are not in the record of the AI's changes. They are listed and not checked. An AI change made through a shell command, or one the record cannot split such as a whole file an AI tool call wrote or a sentence an AI moved within one edit, would also be listed here.

None.

## Hand-off

None.

## Trail

Record numbers refer to `records/NN_<step>.json` in the run folder.

- c01 went through diff_changes (02, python3) -> exclude_author (03, record r01) -> content_handoff (04, no content tokens) -> rationale_coverage (05, reason recorded)
- c02 went through diff_changes (02, python3) -> exclude_author (03, record r02) -> content_handoff (04, no content tokens) -> rationale_coverage (05, reason recorded)
- c03 went through diff_changes (02, python3) -> exclude_author (03, record r03) -> content_handoff (04, no content tokens) -> rationale_coverage (05, reason recorded)
- c04 went through diff_changes (02, python3) -> exclude_author (03, record r04) -> content_handoff (04, no content tokens) -> rationale_coverage (05, reason recorded)
- c05 went through diff_changes (02, python3) -> exclude_author (03, record r05) -> content_handoff (04, no content tokens) -> rationale_coverage (05, reason recorded)

## Notes

- pin_versions / baseline.md: baseline is pinned version v001
- pin_versions / revised.md: revised hashed for the record (not yet ledgered)
