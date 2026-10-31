---
id: guidelines-authoring-procedures
title: Authoring a new procedure
source: verification_procedures/AUTHORING.md
source_commit: sha256:c79d160a3094
updated: 2026-10-31
group: GUIDELINES
---

# Authoring a new procedure

A new procedure is a graph, a contract, code or a prompt for each step, and test files. It is ready when `vg.py check` passes on its graph and its tests catch every planted fault, and the full guide is `verification_procedures/AUTHORING.md`.

1. Parts. Inside `verification_procedures/`, a procedure adds its graph to `graphs/`, its contract to `contracts/`, a Python file for each tool step or a prompt file for each judgment step to the code folder its `stream` key names, its clean and seeded test files with a `truth.yaml` to `fixtures/`, and its tests to `tests/`. Every transition in the graph carries a condition, guidance, pitfalls, and a source, and the graph is acyclic with every step reachable from its entry.
2. Acting outside the run. A tool step is deterministic and never calls the network or a model. The one exception is a step that acts outside the run, such as a push or an SSH connection, which is marked `replay: network` so `verify` compares its outputs by checksum and never reruns it, and which acts only when the settings file says so.
3. The generated entry. Each procedure's knowledge base entry is written by `python3 -m audit_layer.kb graph-entries` from a copy of the graphs and contracts, and is never edited by hand. It is regenerated whenever a graph changes.
4. Revision. Change the guidance and pitfalls first, then the prompt or code where the fault lies, raise the graph's version, run the clean and seeded test files again, and regenerate the entry.

## Consult also

- procedures-llm-runs - the guide's worked example, evaluating an LLM run.
- procedures-ops-github - a graph that does a task, with a step that acts outside the run.
