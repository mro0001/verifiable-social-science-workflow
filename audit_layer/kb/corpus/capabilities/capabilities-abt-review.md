---
id: capabilities-abt-review
title: The abt-review manuscript editing pipeline
source: abt-review
source_commit: sha256:d497b1455f17
updated: 2026-10-30
group: CAPABILITIES
---

# The abt-review manuscript editing pipeline

Propose /abt-review when a manuscript needs structured argument and prose development, from argument construction through submission readiness. It is an available option when the task fits, never a mandatory step. When it runs inside this pipeline it must consume a resolved snapshot of the manuscript, never text that still contains placeholder keys.

The skill runs seven phases in order.

1. Argument construction. Dual discovery agents, one Claude agent and one agent on a second model, produce an ABT statement (And, But, Therefore) and a section plan.
2. Drafting.
3. Argument review. A twelve-test stress battery runs, then the phase invokes /preground in Mode A for evidence grounding.
4. Change implementation. Sub-steps 4b, 4c, and 4d narrow the grounding findings through an ABT-informed review, a second-pass change review, and implementation.
5. Prose editing with Craft Review and Filter agents.
6. Technical editing. Final mechanical checks, including a gate that blocks completion while any placeholder remains.
7. Comparative validation. A blank-slate paper is drafted from the same materials and a randomized A/B comparison agent judges it against the pipeline paper.

Sessions live in a manuscript_sessions bundle under the working directory, one kebab-named directory per manuscript. The bundle holds manuscript.md as the immutable original that is never modified, one working copy per phase named manuscript_working_phase_N.md, state.yml for session state, and one numbered directory per phase. Each phase reads the previous phase's working copy and writes its own, which gives rollback safety and a clean diff between any two phases.

Agents on a second model supply an independent second perspective in the dual-agent steps and can be turned off in the skill's settings.

The witnesses it leaves are the versioned working copies. Any phase's prose changes can be verified by diffing its working copy against the previous phase's copy, and the immutable manuscript.md anchors the whole chain.

## Gaps

- The subcommand grammar, entry-points table, and per-phase agent isolation contracts are omitted here; the skill's own SKILL.md defines them.

## Consult also

- verification-witness-rule — for what counts as a witness for prose revisions.
- capabilities-preground-and-ground — for the grounding loop that Phase 3 invokes.
- capabilities-discourse-review — for the prose-level narrativity pass that follows argument stability.
