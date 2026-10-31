---
id: procedures-data
title: Code
source: verification_procedures/graphs/data.yaml
source_commit: sha256:b3b85e52b15e
updated: 2026-10-31
group: PROCEDURES
---

# Code

The scholar verifies each number in the final build from the output and the script that produce it, with the scripts and parameters an AI wrote or changed marked by the record of the AI's file edits, each AI change to a script shown with the reason the record gives, and each parameter the AI set listed. The procedural graph system runs it with the command below, so a session finds it here and does not carry out its steps by hand.

1. Purpose. The scholar verifies each number in the final build from the output and the script that produce it, with the scripts and parameters an AI wrote or changed marked by the record of the AI's file edits, each AI change to a script shown with the reason the record gives, and each parameter the AI set listed. No model gives a verdict, and a number from AI work waits for the scholar to approve or hold it. Separately, the pipeline is rerun from unchanged raw data in an empty folder, and each number's match or mismatch, the raw data's checksums, and the parameter and model records the run wrote are shown.
2. Triggers. It starts on the harness events `ai_edit`, `turn_end`, `build`, and `commit`. It starts on a request that uses the phrase "verify data", "check the analysis", or "rerun the analysis".
3. Steps. 9 steps, in the order the runtime runs them, each only when a transition into it fires.
   - `inventory` (tool step) Parse pipeline.yaml; check every declared file exists, inputs come from raw or earlier steps; bundle the project and the record of the AI's file edits, when given, into project.json.
   - `check_raw` (tool step) Compare each raw file with its acquisition hash; a raw input without an acquisition record is blocking.
   - `check_params` (tool step) AST scan: literals that equal a params value or act as thresholds/settings without coming from params.yaml; unused and unknown params.
   - `replay_pipeline` (tool step) Run every step from raw in an empty folder; compare each output byte for byte with the committed copy; read stderr.
   - `check_docs` (tool step) Docstring sections present; Inputs/Outputs agree with pipeline.yaml; Parameters agree with what the script reads; functions documented.
   - `attribute_ai` (tool step) Mark each script and parameter the record of the AI's file edits shows an AI tool call wrote or changed; note each AI change with no recorded reason, each whose text is no longer in its script, and each parameter the AI set; trace each number to the scripts and parameters behind it.
   - `check_records` (tool step) Parameter and model records exist, equal params.yaml, equal the replay, and were made under the current params.yaml.
   - `check_numbers` (tool step) Each numbers.yml value equals the replayed output it names.
   - `report` (tool step) Write findings.json and report.md with each number's output, script, and AI work, each AI change to a script with its stated reason, the parameters the AI set, the scripts, and the Reproducibility section.
4. Run command. From the `verification_procedures` folder, run `python3 vg.py run graphs/data.yaml --run runs/<new run folder> --inputs <inputs folder>`. The inputs folder holds `acquisition.yaml`, `numbers.yml`, `params.yaml`, and `pipeline.yaml`, and any files matching `*`.
5. Version. Graph version 0.2, 9 steps and 13 transitions, checked with `python3 vg.py check graphs/data.yaml`.

## Consult also

- guidelines-authoring-procedures - to write a new procedure or revise this one.
