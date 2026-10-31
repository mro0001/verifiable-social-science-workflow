# Sample project

A small project with two research products built from one set of computed results.

- `manuscript.md`, a one-page test manuscript, built as a Word document.
- `slides.md`, a four-slide deck abbreviated from a talk on prompting, built as reveal.js slides.

Both cite the same results through placeholders such as `{{num:none.distinct}}` and `{{table:top_words}}`, and the slides also carry plain prose. The project follows the conventions of the data verification procedure, so that procedure can check every cited number against a rerun of the analysis from the raw data.

## Files

- `next_word_counts.json` is the raw data, the counts of one model's one-word answers to the same question in three conditions, 60 answers each at temperature 1.0, sampled through a university-hosted inference service on July 27, 2026. It is copied unchanged from the talk's sampling run, and `acquisition.yaml` records its checksum.
- `pipeline.yaml` declares the one analysis step, `s1_results.py`, which reads the raw data and writes `next_word_results.json`, the table `top_words.md`, and `params_record_results.csv`. The step declares its phase, `phase: analysis`, and the script marks its five steps with comment lines such as `# step: Table`, so the data analysis report can show each step with its code. `params.yaml` sets its two choices once, and `params_io.py` is the helper that reads them and writes the record.
- `numbers.yml` lists each value the manuscript and slides cite, with the output and field it comes from. The build fills each placeholder from it, and the data procedure checks each value against its rerun.
- `refs.bib` holds the one reference the manuscript cites.
- `recorded_phases.json` holds fixed answers for the one model step of the data phase reports, which finds the sentences of the built text that describe each phase and the lines of the script that carry them out, so the reports run without a model. A live run asks a model instead. The data procedure itself asks no model.

## Build

Run these from this folder after the repository's install step. Nothing here uses the network or calls a model.

```
python3 s1_results.py
PYTHONPATH=../../ospipe python3 -m ospipe build --manuscript manuscript.md --manifest numbers.yml --tables-dir . --bib refs.bib --builds-dir builds/manuscript --purpose "sample manuscript"
PYTHONPATH=../../ospipe python3 -m ospipe build --manuscript slides.md --manifest numbers.yml --tables-dir . --to revealjs --builds-dir builds/slides --purpose "sample slides"
```

Each build fills every placeholder, stops if any is missing, and writes the next numbered build (`v001.docx`, then `v002.docx`, and so on) with a copy of its filled-in text and a ledger row in `BUILDS.md`. Opening the slides in a browser loads the reveal.js library from the web.

## Check the numbers and the analysis

```
cd ../../verification_procedures
python3 ../handoffs/project_to_data.py --project ../examples/sample_project --to runs/demo_sample_inputs
python3 vg.py run graphs/data.yaml --run runs/demo_sample --inputs runs/demo_sample_inputs
python3 ../handoffs/project_to_data_phases.py --project ../examples/sample_project --to runs/demo_sample_phases
python3 vg.py run graphs/data_analysis.yaml --run runs/demo_sample_analysis --inputs runs/demo_sample_phases --judge recorded:../examples/sample_project/recorded_phases.json
```

The first handoff gathers the project's files for the data procedure, whose final-numbers report lists each cited number with the output and the script that produce it, reruns the analysis from the raw data in an empty folder, and gives each number's rerun value and whether they agree. With `--file-edits FILE`, the record of the AI's file edits that `python3 -m audit_layer write-out file-edits` writes, the report also marks the scripts and parameters an AI changed. The second handoff gathers the pipeline, its script, and the text of the latest manuscript build for the data analysis report, which lists the script's steps, then each step with its exact code, then each sentence of the text that describes the analysis with where the script carries it out.
