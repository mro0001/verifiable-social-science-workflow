---
id: verification-witness-rule
title: The witness rule
source: MANUSCRIPT_WORKFLOW.md
source_commit: sha256:4f5317e8258d
updated: 2026-07-23
group: VERIFICATION
---

# The witness rule

An AI's account of its own work is not evidence; the witness is, and the witness depends on the type of claim. A claim without a witness is unverified, and the pipeline can list every unverified claim on demand.

1. Computation ("I cleaned the data, ran the analysis, made this table"). The witness is runnable commented code, with comments tying each claimed or assumed action to the function that performs it.
2. Citation or summary ("I cited or summarized this source"). The witness is the exact reference, the passage relied on, and a judgment of whether the source was used correctly.
3. Prose ("I revised the prose"). The witness is tracked changes against the prior version.

The comment requirement in the computation witness exists because narrative and code drift apart. An assumption stated only in the AI's account, and nowhere near the line that implements it, can mislabel results for weeks with nothing in the story flagging it.

## Consult also

- loop-compare-and-return — for the procedure that produces the tracked-changes witness for prose.
