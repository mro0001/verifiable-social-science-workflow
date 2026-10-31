---
id: guidelines-session-start-protocol
title: Session start protocol
source: MANUSCRIPT_WORKFLOW.md
source_commit: sha256:4f5317e8258d
updated: 2026-10-29
group: GUIDELINES
---

# Session start protocol

At the start of any task, a session queries the knowledge base server, workflow-kb, before improvising. A standard that is not opened at task start might as well not exist, so consulting the corpus is the first act of work, not a reference of last resort.

1. Orient over the corpus. Call orient_kb, or read the llms.txt index, to see which groups and entries exist.
2. Search for the standard or capability that matches the task. Use search_kb with the task's own vocabulary, for example build, manifest, citation, or returns.
3. Open the matched entry in full with get_entry and read it before producing anything.
4. Follow the entry, or depart consciously. A departure is allowed, but its reason is noted in the decision log so the standard can be revised rather than silently ignored.
5. Read the workspace notes areas that match the task. Select only the matching areas, never the whole notes tree.

## Gaps

- The ten notes areas and their boundary rules are defined by the notes README in the workspace, not restated here.

## Consult also

- guidelines-manuscript-style-preferences — apply before drafting or editing any prose.
- verification-witness-rule — apply before claiming any work is done.
