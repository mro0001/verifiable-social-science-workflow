---
id: procedures-data-cleaning
title: Data cleaning report
source: verification_procedures/graphs/data_cleaning.yaml
source_commit: sha256:f5b0ac0d8013
updated: 2026-10-31
group: PROCEDURES
---

# Data cleaning report

Show the scholar each step of the data cleaning as the pipeline's scripts carry it out, as an outline of short titles and then each title with its exact code, file, and lines, and list each sentence of the final build's text that describes the cleaning with where the scripts carry it out or that it is missing. The procedural graph system runs it with the command below, so a session finds it here and does not carry out its steps by hand.

1. Purpose. Show the scholar each step of the data cleaning as the pipeline's scripts carry it out, as an outline of short titles and then each title with its exact code, file, and lines, and list each sentence of the final build's text that describes the cleaning with where the scripts carry it out or that it is missing. A program checks each quote against the text and each place against the scripts, no model gives a verdict, and the scholar approves or holds each description.
2. Triggers. The scholar asks for the data cleaning report. The scholar asks which steps carry out the data cleaning and where the manuscript describes them.
3. Steps. 5 steps, in the order the runtime runs them, each only when a transition into it fires.
   - `phase_cleaning` (tool step) Name the phase this report shows, cleaning.
   - `outline_steps` (tool step) Read pipeline.yaml and each step's script; list each script's steps (marked sections, or the functions a Python script calls in order) with title, file, lines, and exact code; bundle the final build's text and the numbered scripts for the finding step.
   - `find_descriptions` (judgment step, once per item in `find_items.json`) Find each sentence of the final build's text that describes the phase, quoted exactly, and the places in the scripts that carry it out, or none. Finds only and judges nothing.
   - `check_descriptions` (tool step) Check that each quote is in the final build's text and that each place is lines of a script the pipeline declares; name the steps each place falls in.
   - `report` (tool step) Write findings.json, report.md, and fields.json with the outline, the code under each title, the descriptions table, and the files read; each description is an item for the scholar.
4. Run command. From the `verification_procedures` folder, run `python3 vg.py run graphs/data_cleaning.yaml --run runs/<new run folder> --inputs <inputs folder> --judge <executor>`. The inputs folder holds `final_text.md` and `pipeline.yaml`, and any files matching `*`. An executor is `recorded:<answers file>` or a model the runtime can reach.
5. Version. Graph version 0.1, 5 steps and 6 transitions, checked with `python3 vg.py check graphs/data_cleaning.yaml`.

## Consult also

- guidelines-authoring-procedures - to write a new procedure or revise this one.
