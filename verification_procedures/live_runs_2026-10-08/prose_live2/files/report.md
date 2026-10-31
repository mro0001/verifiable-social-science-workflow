# Prose verification

Every AI change between two pinned versions must be visible, carry a rationale, and have that rationale describe it honestly. Changes that touch numbers, citations, quotations, negation, or claim strength are handed to the data or citations stream. Author edits are listed, not judged.

Changes between the pinned versions: 9 (edit 7, insert 1, delete 0, move 1); AI 8, author 1. Judged: 7. Handed off to another stream: 4.

## Summary

- Blocking: 1
- Warnings: 9
- Notes: 3

## Problems

| Severity | Check | Item | Problem | Evidence |
|---|---|---|---|---|
| blocking | rationale_coverage | c05 | silent change: AI edit has no rationale | Managers in our sample described the format as slow but fair. -> Managers in our sample called the format slow but fair. |
| warning | content_handoff | c03 | content change: hand off to data stream | numbers: 48 -> 52 |
| warning | content_handoff | c04 | content change: hand off to citations stream | citations: kim2018 -> park2020 |
| warning | content_handoff | c06 | content change: hand off to citations stream | quotes: felt like a real conversation about the job. -> felt like a genuine conversation about the work. |
| warning | content_handoff | c08 | content change: hand off to data stream | strength: may, suggest -> show |
| warning | judge_rationale | c04 | rationale misdescribes the change, and the change alters meaning | The rationale claims 'Style' but the edit swaps the citation from '@kim2018' to '@park2020', which alters the evidence … (live:qwen/qwen3.5-122b) |
| warning | judge_rationale | c06 | rationale misdescribes the change, and the change alters meaning | The rationale falsely claims only punctuation was fixed while the quoted text changed from 'real conversation about the… (live:qwen/qwen3.5-122b) |
| warning | judge_rationale | c08 | rationale misdescribes the change, and the change alters meaning | The rationale claims 'tightened wording' but the edit replaces the hedge 'may' and the tentative verb 'suggest' with th… (live:qwen/qwen3.5-122b) |
| warning | rationale_coverage | c09 | kind mismatch: rationale r07 says edit, diff says insert | The next section turns to the interview protocol itself. |
| warning | rationale_coverage | r08 | claimed change not made | anchor text is present unchanged in revised.md: This pattern held across agencies of different sizes. |

## Versions

- Baseline: `baseline.md` v001 sha256:6120b6a078e5bff2b9acf9b206ea64ebec3ca04646845d15c34c75216348b840
- Revised: `revised.md` (not ledgered) sha256:916d5056cdb13387154b57442156ed12c0dfd67503f8e7644c2b8b4411c307eb

## Changes

| Id | Kind | Change (before -> after) | Rationale | Verdict | Hand-off |
|---|---|---|---|---|---|
| c01 | move | (moved, text unchanged) Prior work has focused mainly on private firms. | r01: Moved the gap statement ahead of the study aim so the aim answers it. | honest | - |
| c02 | edit | [-In this-] {+This+} study [-we examine-] {+examines+} whether structured interviews … in municipal agencies. | r02: Rewrote "In this study we examine" as "This study examines" for a more direct openin… | honest | - |
| c03 | edit | We draw on personnel records from [-48-] {+52+} agencies in three states [@alvarez2019]. | r03: Updated the agency count from 48 to 52 to match the sample table. | honest | data |
| c04 | edit | [-Turnover in the first year-] {+First-year turnover+} is {+especially+} costly for small agencies [-[@kim2018].-] {+[@park2020].+} | r04: Style. Smoothed the sentence so it reads more naturally. | rationale misdescribes; meaning changed | citations |
| c05 | edit | Managers in our sample [-described-] {+called+} the format [-as-] slow but fair. | (none) | SILENT: no rationale | - |
| c06 | edit | … "felt like a [-real-] {+genuine+} conversation about the [-job."-] {+work."+} | r05: Fixed punctuation in the quotation. | rationale misdescribes; meaning changed | citations |
| c07 | edit | Agencies [-that-] adopted the format [-did so-] for [-a variety of-] {+many+} different [-reasons, and those reasons varied a great deal.-] {+reasons.+} | author | author edit: listed, not judged | - |
| c08 | edit | The results [-suggest-] {+show+} that structured interviews [-may-] reduce early exits by 9 percentage points. | r06: Tightened wording. | rationale misdescribes; meaning changed | data |
| c09 | insert | {+The next section turns to the interview protocol itself.+} | r07: Added a signpost sentence pointing to the next section. | honest | - |

## Hand-off

| Change | Streams | Token differences |
|---|---|---|
| c03 | data | numbers: 48 -> 52 |
| c04 | citations | citations: kim2018 -> park2020 |
| c06 | citations | quotes: felt like a real conversation about the job. -> felt like a genuine conversation about the work. |
| c08 | data | strength: may, suggest -> show |

## Trail

Record numbers refer to `records/NN_<step>.json` in the run folder.

- c01: diff_changes (02, python3) -> content_handoff (04, no content tokens) -> rationale_coverage (05, r01) -> judge_rationale (06, live:qwen/qwen3.5-122b, prompt sha256:f0596234a9d3)
- c02: diff_changes (02, python3) -> content_handoff (04, no content tokens) -> rationale_coverage (05, r02) -> judge_rationale (06, live:qwen/qwen3.5-122b, prompt sha256:9cfe33ace5ec)
- c03: diff_changes (02, python3) -> content_handoff (04, data) -> rationale_coverage (05, r03) -> judge_rationale (06, live:qwen/qwen3.5-122b, prompt sha256:ab3ce3d68358); flagged by content_handoff
- c04: diff_changes (02, python3) -> content_handoff (04, citations) -> rationale_coverage (05, r04) -> judge_rationale (06, live:qwen/qwen3.5-122b, prompt sha256:4135b80a5918); flagged by content_handoff, judge_rationale
- c05: diff_changes (02, python3) -> content_handoff (04, no content tokens) -> rationale_coverage (05, no rationale); flagged by rationale_coverage
- c06: diff_changes (02, python3) -> content_handoff (04, citations) -> rationale_coverage (05, r05) -> judge_rationale (06, live:qwen/qwen3.5-122b, prompt sha256:971310f7c700); flagged by content_handoff, judge_rationale
- c07: diff_changes (02, python3) -> exclude_author (03, claim a01)
- c08: diff_changes (02, python3) -> content_handoff (04, data) -> rationale_coverage (05, r06) -> judge_rationale (06, live:qwen/qwen3.5-122b, prompt sha256:8ef6af19c534); flagged by content_handoff, judge_rationale
- c09: diff_changes (02, python3) -> content_handoff (04, no content tokens) -> rationale_coverage (05, r07) -> judge_rationale (06, live:qwen/qwen3.5-122b, prompt sha256:f4c872debafe); flagged by rationale_coverage

## Notes

- exclude_author / c07: author edit (a01), listed not judged: author shortened the sentence in Word without Track Changes
- pin_versions / baseline.md: baseline is pinned version v001
- pin_versions / revised.md: revised hashed for the record (not yet ledgered)
