# Notes Layer

A recording layer for human-AI collaboration during manuscript development. It changes nothing in the pipeline system. One file per area. The AI files purposeful notes in the same turn they arise. A session declares its task and loads the matching areas in full.

Rules.

1. Notes are complete records of thinking, never summaries. Write each note so its point survives without the conversation that produced it.
2. Append and annotate, never delete. A superseded note gets a dated annotation pointing at what replaced it.
3. Context scoping happens by area selection. Load the areas the task needs and nothing else. A failed data hunt never contaminates a literature session because the literature session never opens that file.
4. `writing.md` is the handoff entry point. A fresh drafting session starts there and follows its links.
5. Working-method rules do not live here. Project-specific rules go to the workspace CLAUDE.md. Cross-project standards go to the knowledge base corpus, which the knowledge base server `workflow-kb` serves.
6. Citation-integrity ledgers (per-source verification status, the citation_inventory pattern) are standalone files created as needed. Their process design is deferred until the reference machinery is designed as one piece.

Evidence base for this structure: two session-history reviews, 195 note-events across two papers of different genres.
