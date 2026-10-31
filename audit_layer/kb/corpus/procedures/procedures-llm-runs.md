---
id: procedures-llm-runs
title: Evaluate an LLM run
source: verification_procedures/graphs/llm_runs.yaml
source_commit: sha256:cdcc5d83366c
updated: 2026-10-29
group: PROCEDURES
---

# Evaluate an LLM run

Check a finished run of any procedure that put questions to a model, so the scholar can see which model answered, whether every question and answer was kept and matches the record, which items went unanswered, and how the answers compare with a reference, before relying on its verdicts. The procedural graph system runs it with the command below, so a session finds it here and does not carry out its steps by hand.

1. Purpose. Check a finished run of any procedure that put questions to a model, so the scholar can see which model answered, whether every question and answer was kept and matches the record, which items went unanswered, and how the answers compare with a reference, before relying on its verdicts. Read the run from its archive, and rerun nothing and ask nothing.
2. Triggers. A procedure has finished a run with live judgment. The scholar compares two runs of the same procedure on the same files.
3. Steps. 7 steps, in the order the runtime runs them, each only when a transition into it fires.
   - `read_run` (tool step) Read the run's archive, index its manifest, its judgment steps, its tool steps, and its trail, and write its answers in the recorded answers form.
   - `check_record` (tool step) For each judgment step, check that every answer's saved prompt matches its recorded checksum and that its response was saved, and count the items answered, not judged, and retried.
   - `check_models` (tool step) Name the executor of each role, say when its answers came from a recorded file, warn when the judge and the second checker are the same, and say what the run does not record about the model.
   - `compare_reference` (tool step) Compare the run's answers with a reference answer book on the short fields both answers hold, and count the items that agree for each judgment step.
   - `skip_reference` (tool step) Say that no reference was given, so the run's answers were not compared.
   - `check_replay` (tool step) Read the replay the run's verify command saved and the score against planted faults, and name each failed step and each missed fault.
   - `report` (tool step) Write a report with the models and settings the run used, each judgment step with its items, the agreement with a reference, and the replay and score.
4. Run command. From the `verification_procedures` folder, run `python3 vg.py run graphs/llm_runs.yaml --run runs/<new run folder> --inputs <inputs folder>`. The inputs folder holds `reference.json` and `run.tar`.
5. Version. Graph version 0.3, 7 steps and 11 transitions, checked with `python3 vg.py check graphs/llm_runs.yaml`.

## Consult also

- guidelines-authoring-procedures - to write a new procedure or revise this one.
