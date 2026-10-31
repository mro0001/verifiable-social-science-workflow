# Data verification, the final numbers

This report lists each number in the final build with the output and the script that produce it, for the scholar to verify. A script or a parameter is the AI's when the record of the AI's file edits shows that an AI tool call changed it. Each AI change to a script is shown with its text before and after and the reason the record gives, and each parameter the AI set is listed. A number that comes from AI work waits for the scholar to approve or hold it. A program notes each AI change with no recorded reason. No model judges anything. The Reproducibility section reruns the pipeline from the raw data in an empty folder and gives each number's match or mismatch, which covers every number whoever wrote its code.

The record of the AI's file edits was given. Numbers 5 (from AI work 1). AI changes to scripts 1 (with no recorded reason 0). Parameters the AI set 0. Steps 3, raw files 1.

## Summary

- Blocking: 0
- Warnings: 0
- Notes: 2

## Problems

None.

## Numbers

Each number names the output it is read from and the script of the step that writes that output. AI work lists the AI changes and the parameters the AI set in that script, the scripts of the earlier steps it reads from, and the helpers.

| Key | numbers.yml | Output | Script | AI work |
|---|---|---|---|---|
| alpha | 0.05 | params_record_model.csv | s3_model.py | no |
| mean_income_k_north | 59.311 | table_descriptives.csv | s2_describe.py | yes, e01 in s2_describe.py |
| n_analytic | 41 | model_record_model.json | s3_model.py | no |
| p_income_k | 0.000 | table_model.csv | s3_model.py | no |
| slope_income_k | 0.011 | table_model.csv | s3_model.py | no |

## AI changes to scripts

Each change below is one an AI tool call made, as the record of the AI's file edits gives it. An AI change made through a shell command is not in the record and is not shown here.

### e01 (s2_describe.py, edit)

- **Before:** `# A blank income_k is skipped in the mean.`
- **After:** `# A blank income_k is skipped in the mean and counted, never dropped silently.`
- **Stated reason:** Say that a blank income is counted as well as skipped, since n_missing shows it.
- **In the script now:** yes

- Change e01 came from session S5a0c91e7d2b4.

## Parameters the AI set

Each parameter below is one whose value an AI tool call set in params.yaml, as the record gives it, with the scripts that read it.

None.

## Scripts

Each step script and helper, with the AI changes the record gives for it. Docs ok covers the docstring sections and the parameter scan of the script.

| Script | Step | AI changes | Docs ok |
|---|---|---|---|
| s1_clean.py | clean | none | yes |
| s2_describe.py | describe | e01 | yes |
| s3_model.py | model | none | yes |
| params_io.py | helper | none | yes |

## Reproducibility

The pipeline was rerun from the raw data in an empty folder. This covers every number, whoever wrote its code, and a number that does not reproduce is a problem to fix. The steps of the rerun follow.

| Step | Script | Reproduces | Records ok | Stderr |
|---|---|---|---|---|
| clean | s1_clean.py | yes | yes | clean |
| describe | s2_describe.py | yes | yes | clean |
| model | s3_model.py | yes | yes | clean |

Each number against the rerun follows.

| Key | numbers.yml | Rerun | Agrees |
|---|---|---|---|
| alpha | 0.05 | 0.05 | yes |
| mean_income_k_north | 59.311 | 59.311 | yes |
| n_analytic | 41 | 41 | yes |
| p_income_k | 0.000 | 0.000 | yes |
| slope_income_k | 0.011 | 0.011 | yes |

Each raw file's checksum, recorded at collection and as it is now, follows.

| File | At collection | Now | Agrees |
|---|---|---|---|
| raw_survey.csv | sha256:2ce927e550d1d826dc94c258d9934a99f5e55ee035b295783556605fff0f9bb5 | sha256:2ce927e550d1d826dc94c258d9934a99f5e55ee035b295783556605fff0f9bb5 | yes |

The parameter record follows, assembled from the records the rerun wrote and not from the committed copies.

| Param | Value recorded | params.yaml | Agrees | Step | Script |
|---|---|---|---|---|---|
| income_cap | 250000 | 250000 | yes | clean | s1_clean.py |
| min_age | 18 | 18 | yes | clean | s1_clean.py |
| fig_height | 260 | 260 | yes | describe | s2_describe.py |
| fig_width | 480 | 480 | yes | describe | s2_describe.py |
| round_digits | 3 | 3 | yes | describe | s2_describe.py |
| alpha | 0.05 | 0.05 | yes | model | s3_model.py |
| model_formula | satisfaction ~ income_k | satisfaction ~ income_k | yes | model | s3_model.py |
| round_digits | 3 | 3 | yes | model | s3_model.py |

The model records follow.

| Record | Model | Spec | n | Made under current params.yaml | Reproduces |
|---|---|---|---|---|---|
| model_record_model.json | OLS | satisfaction ~ income_k | 41 | yes | yes |

## Notes

- check_params / params_io.py:L106: literal declared not a parameter
- check_params / s2_describe.py:L73: literal declared not a parameter
