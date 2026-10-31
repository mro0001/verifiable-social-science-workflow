---
id: capabilities-preground-and-ground
title: The preground and ground evidence grounding loop
source: preground
source_commit: sha256:780ad4ccc03b
updated: 2026-10-30
group: CAPABILITIES
---

# The preground and ground evidence grounding loop

Propose the grounding loop when a document's claims need verification against the scholarly literature, either standalone or from /abt-review Phase 3. It is an option to offer when claims are load-bearing, not a required stage. /preground prepares and orchestrates, /ground verifies in isolation, and the loop runs at most three rounds before producing a final assessment.

/preground runs five phases.

1. Argument scan. Mode A reuses the stress-test output when the document comes from /abt-review, while Mode B runs a standalone five-question scan.
2. Claim extraction and classification. Claims are typed T1, T2, or T3 by the kind of vulnerability each one has, not by its length or citation count.
3. Assembly. The grounding request is built and must pass a ten-criterion quality gate.
4. Grounding loop. Each round invokes /ground, reviews its output against the argument map, verifies any new citations the round introduced, and loops on unverified citations, up to three rounds.
5. Final assessment.

/ground operates in complete isolation. It receives only the grounding request document, never the argument map, the ABT, or the pregrounding analysis. Inside it, a second model reads the sources while three Claude agents judge. Agent 1 issues per-claim verdicts of Supported, Partially Supported, Not Supported, or Blocked. Agent 2 runs convergence triage with seven elevation criteria and a two-trigger threshold. Agent 3 assesses the evidence landscape and runs critical interrogation. Source discovery, retrieval, and reading are delegated to the scholar trio, so every ground session contains its own scholar session bundle.

/preground stores its session in a preground_sessions bundle under the working directory, with source.md as the immutable original, state.yml, numbered phase directories, and one subdirectory per grounding round. /ground stores its sessions in a fixed global grounding sessions directory rather than the caller's workspace, one session per round named for the pregrounding session and round number.

The deliverable is final_assessment.md, which categorizes findings as must-address, should-consider, can-dismiss, or fundamental-reconception, plus a consolidated change list and an inventory of new citations. /abt-review Phase 4b consumes it.

The witnesses are the CER entries in the ground session's scholar bundle. Each one carries the exact reference, the passage relied on, and a mechanical quote_match result, which is what the witness rule requires for citation claims.

## Consult also

- verification-witness-rule — for why CER entries are the required witness for citation claims.
- capabilities-scholar-trio — for the search, retrieve, and read skills /ground delegates to.
- capabilities-abt-review — for the editing pipeline whose Phase 3 invokes this loop.
