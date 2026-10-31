---
id: capabilities-discourse-review
title: The discourse-review narrativity pass
source: discourse-review
source_commit: sha256:cb1292830b05
updated: 2026-10-30
group: CAPABILITIES
---

# The discourse-review narrativity pass

Propose /discourse-review after a manuscript's argument is stable and the remaining weakness is prose-level storytelling. It is an optional pass, not a required stage. It diagnoses narrativity, drafts targeted enhancements, and never modifies the manuscript itself, so every approved change leaves the session in changes_summary.md for manual application.

The prerequisite is a stable argument structure, which can come from /abt-review Phase 3 or later or from any manuscript the author already considers argumentatively sound. The skill does not add claims, change evidence, reorder sections, or alter what the paper argues. Argument-level problems that surface during diagnosis are flagged for /abt-review, not addressed here.

The skill runs three phases.

1. Narrativity profile. The manuscript is scored on five dimensions, which are modal balance, tension architecture, experiential grounding, worldmaking coherence, and discourse-story alignment, plus a separate comprehension-barriers check.
2. Enhancement drafting. Targeted drafts address the weakest two or three dimensions by default, with an optional drafting agent on a second model as a second perspective.
3. Author decision. The author accepts, rejects, or modifies each enhancement.

Sessions live in a discourse_sessions bundle under the working directory. The bundle holds a read-only copy of manuscript.md, an optional abt.md copied from the /abt-review session, state.yml, and one numbered directory per phase.

The skill's record is changes_summary.md, the handoff list of approved enhancements. Because the skill never edits the manuscript, the tracked-changes witness for the prose must be produced wherever the changes are actually applied, for example /abt-review Phase 4 or the pipeline's own compare step.

## Consult also

- capabilities-abt-review — for the argument-construction pipeline this pass complements.
- verification-witness-rule — for the tracked-changes witness the applying step must produce.
- loop-compare-and-return — for the pipeline procedure that produces that witness when changes are applied here.
