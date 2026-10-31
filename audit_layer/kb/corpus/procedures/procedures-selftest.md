---
id: procedures-selftest
title: The selftest procedure
source: verification_procedures/graphs/selftest.yaml
source_commit: sha256:ea4fc8b778d0
updated: 2026-10-29
group: PROCEDURES
---

# The selftest procedure

Prove the runtime walks, branches, judges per item, and replays. The procedural graph system runs it with the command below, so a session finds it here and does not carry out its steps by hand.

1. Purpose. Prove the runtime walks, branches, judges per item, and replays.
2. Triggers. None declared in the graph.
3. Steps. 4 steps, in the order the runtime runs them, each only when a transition into it fires.
   - `list_items` (tool step) List the words in words.txt as items.
   - `judge_items` (judgment step, once per item in `items.json`) Say whether each word is a color.
   - `skipped_branch` (tool step) Runs only when there are more than 100 items.
   - `report` (tool step) Write findings and the report.
4. Run command. From the `verification_procedures` folder, run `python3 vg.py run graphs/selftest.yaml --run runs/<new run folder> --inputs <inputs folder> --judge <executor>`. The inputs folder holds `words.txt`. An executor is `recorded:<answers file>` or a model the runtime can reach.
5. Version. Graph version 0.1, 4 steps and 4 transitions, checked with `python3 vg.py check graphs/selftest.yaml`.

## Consult also

- guidelines-authoring-procedures - to write a new procedure or revise this one.
