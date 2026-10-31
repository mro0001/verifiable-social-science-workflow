---
id: procedures-prose
title: Change review
source: verification_procedures/graphs/prose.yaml
source_commit: sha256:860441788112
updated: 2026-10-31
group: PROCEDURES
---

# Change review

The scholar verifies each AI change between their last draft and the final build's text, which the record of the AI's changes names, from its sentence before and after and the reason the record gives, while their own changes are listed and not checked. The procedural graph system runs it with the command below, so a session finds it here and does not carry out its steps by hand.

1. Purpose. The scholar verifies each AI change between their last draft and the final build's text, which the record of the AI's changes names, from its sentence before and after and the reason the record gives, while their own changes are listed and not checked. A program notes each AI change with no recorded reason and points out each one that alters a number, a citation, a quotation, a negation, or a claim's strength. No model gives a verdict, and the scholar approves or holds each AI change.
2. Triggers. It starts on the harness events `ai_edit`, `turn_end`, `build`, and `commit`. It starts on a request that uses the phrase "verify prose", "check AI edits", or "change review".
3. Steps. 6 steps, in the order the runtime runs them, each only when a transition into it fires.
   - `pin_versions` (tool step) Hash the scholar's last draft (baseline) and the final build's text (revised); the baseline must match a ledgered version in versions.yaml.
   - `diff_changes` (tool step) Align sentences of baseline and revised; emit edits, inserts, deletes, and moves with deterministic ids.
   - `exclude_author` (tool step) Mark each change the record of the AI's changes (rationales.yaml) names as the AI's, with the entry's stated reason; every other change is the scholar's own, listed not checked. A record entry for an AI tool call that wrote the whole file is a blocking finding, since the record cannot tell its changes from the scholar's.
   - `content_handoff` (tool step) Point out AI changes that alter numbers, citation keys, quoted passages, negation, or hedge/booster strength; write handoff.json for the other streams.
   - `rationale_coverage` (tool step) Note each AI change with no recorded reason, each record entry that matches no change, and each kind the record and the diff give differently.
   - `report` (tool step) Write findings.json and report.md with each AI change's sentence before and after, its stated reason, and the content it alters, the scholar's own changes in a table, and a Trail line per change.
4. Run command. From the `verification_procedures` folder, run `python3 vg.py run graphs/prose.yaml --run runs/<new run folder> --inputs <inputs folder>`. The inputs folder holds `baseline.md`, `rationales.yaml`, `revised.md`, and `versions.yaml`.
5. Version. Graph version 0.3, 6 steps and 5 transitions, checked with `python3 vg.py check graphs/prose.yaml`.

## Consult also

- guidelines-authoring-procedures - to write a new procedure or revise this one.
