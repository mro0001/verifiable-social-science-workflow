# Data verification, the final numbers

This report lists each number in the final build with the output and the script that produce it, for the scholar to verify. A script or a parameter is the AI's when the record of the AI's file edits shows that an AI tool call changed it. Each AI change to a script is shown with its text before and after and the reason the record gives, and each parameter the AI set is listed. A number that comes from AI work waits for the scholar to approve or hold it. A program notes each AI change with no recorded reason. No model judges anything. The Reproducibility section reruns the pipeline from the raw data in an empty folder and gives each number's match or mismatch, which covers every number whoever wrote its code.

The record of the AI's file edits was given. Numbers 5 (from AI work 5). AI changes to scripts 2 (with no recorded reason 1). Parameters the AI set 1. Steps 3, raw files 1.

## Summary

- Blocking: 8
- Warnings: 3
- Notes: 3

## Problems

| Severity | Check | Item | Problem | Evidence |
|---|---|---|---|---|
| blocking | attribute_ai | e02 | an AI change to s1_clean.py with no recorded reason | return [r for r in rows if r["age"].strip() != ""] |
| blocking | check_docs | s2_describe.py | module docstring lacks sections: Inputs, Outputs, Parameters, Assumptions | present: Purpose |
| blocking | check_numbers | slope_income_k | manuscript number does not come from the process | numbers.yml '0.015'; replayed table_model.csv estimate = '0.011' |
| blocking | check_params | s1_clean.py:L42 | hard-coded parameter: min_age = 21 here, params.yaml sets min_age: 18 | min_age = 21 |
| blocking | check_raw | raw_survey.csv | raw data changed after acquisition | recorded sha256:2ce927e550d1..., now sha256:6d2976a77b36... |
| blocking | check_records | model_record_model.json | stale model: record was made under a different params.yaml | record sha256:2546b1af7ea1..., current sha256:755c8cef6263... |
| blocking | replay_pipeline | model_record_model.json | output does not reproduce: hand-edited or stale | line 16: committed '  "params_sha256": "sha256:2546b1af7ea194f3e4e4ae377f285c21a9e90a2e73d' / replayed '  "params_sha256": "sha256:755c8cef6263a1ca74024255e53d… |
| blocking | replay_pipeline | table_descriptives.csv | output does not reproduce: hand-edited or stale | line 4: committed 'South,10,0,91.320,3.200' / replayed 'South,10,0,86.820,3.200' |
| warning | attribute_ai | params.yaml:fig_width | a parameter the AI set, for the scholar to check | fig_width 480 -> 520 (record e03), params.yaml now 520 |
| warning | check_docs | s1_clean.py | Parameters section names min_age, but the script never reads it from params.yaml | min_age - respondents younger than this are excluded. |
| warning | replay_pipeline | s3_model.py | step wrote warnings to stderr while exiting 0 | <replay>/s3_model.py:50: UserWarning: 3 rows dropped: blank satisfaction or income_k   warnings.warn("%d rows dropped: blank %s or %s" % (dropped, outcome, pre… |

## Numbers

Each number names the output it is read from and the script of the step that writes that output. AI work lists the AI changes and the parameters the AI set in that script, the scripts of the earlier steps it reads from, and the helpers.

| Key | numbers.yml | Output | Script | AI work |
|---|---|---|---|---|
| alpha | 0.05 | params_record_model.csv | s3_model.py | yes, e02 in s1_clean.py |
| mean_income_k_north | 63.487 | table_descriptives.csv | s2_describe.py | yes, e01 in s2_describe.py, e02 in s1_clean.py, parameter fig_width |
| n_analytic | 40 | model_record_model.json | s3_model.py | yes, e02 in s1_clean.py |
| p_income_k | 0.000 | table_model.csv | s3_model.py | yes, e02 in s1_clean.py |
| slope_income_k | 0.015 | table_model.csv | s3_model.py | yes, e02 in s1_clean.py |

## AI changes to scripts

Each change below is one an AI tool call made, as the record of the AI's file edits gives it. An AI change made through a shell command is not in the record and is not shown here.

### e01 (s2_describe.py, edit)

- **Before:** `# A blank income_k is skipped in the mean.`
- **After:** `# A blank income_k is skipped in the mean and counted, never dropped silently.`
- **Stated reason:** Say that a blank income is counted as well as skipped, since n_missing shows it.
- **In the script now:** yes

### e02 (s1_clean.py, edit)

- **Before:** `return [r for r in rows if r["income"].strip() != ""]`
- **After:** `return [r for r in rows if r["age"].strip() != ""]`
- **Stated reason:** No reason is recorded.
- **In the script now:** yes

- Change e01 came from session S5a0c91e7d2b4.
- Change e02 came from session S5a0c91e7d2b4.

## Parameters the AI set

Each parameter below is one whose value an AI tool call set in params.yaml, as the record gives it, with the scripts that read it.

| Param | Before | AI set | params.yaml now | Read by | Record | Stated reason |
|---|---|---|---|---|---|---|
| fig_width | 480 | 520 | 520 | s2_describe.py | e03 | Widen the figure so the four region labels do not crowd each other. |

- Parameter fig_width came from session S7f3e2d1c0b9a.

## Scripts

Each step script and helper, with the AI changes the record gives for it. Docs ok covers the docstring sections and the parameter scan of the script.

| Script | Step | AI changes | Docs ok |
|---|---|---|---|
| s1_clean.py | clean | e02 | **no** |
| s2_describe.py | describe | e01 | **no** |
| s3_model.py | model | none | yes |
| params_io.py | helper | none | yes |

## Reproducibility

The pipeline was rerun from the raw data in an empty folder. This covers every number, whoever wrote its code, and a number that does not reproduce is a problem to fix. The steps of the rerun follow.

| Step | Script | Reproduces | Records ok | Stderr |
|---|---|---|---|---|
| clean | s1_clean.py | yes | yes | clean |
| describe | s2_describe.py | **no** (table_descriptives.csv) | yes | clean |
| model | s3_model.py | **no** (model_record_model.json) | **no** | warning |

Each number against the rerun follows.

| Key | numbers.yml | Rerun | Agrees |
|---|---|---|---|
| alpha | 0.05 | 0.05 | yes |
| mean_income_k_north | 63.487 | 63.487 | yes |
| n_analytic | 40 | 40 | yes |
| p_income_k | 0.000 | 0.000 | yes |
| slope_income_k | 0.015 | 0.011 | **no** |

Each raw file's checksum, recorded at collection and as it is now, follows.

| File | At collection | Now | Agrees |
|---|---|---|---|
| raw_survey.csv | sha256:2ce927e550d1d826dc94c258d9934a99f5e55ee035b295783556605fff0f9bb5 | sha256:6d2976a77b36aa47dcda673dab7fdffbe0f937a6e485db9b3fe184be8e4e42a4 | **no** |

The parameter record follows, assembled from the records the rerun wrote and not from the committed copies.

| Param | Value recorded | params.yaml | Agrees | Step | Script |
|---|---|---|---|---|---|
| income_cap | 250000 | 250000 | yes | clean | s1_clean.py |
| fig_height | 260 | 260 | yes | describe | s2_describe.py |
| fig_width | 520 | 520 | yes | describe | s2_describe.py |
| round_digits | 3 | 3 | yes | describe | s2_describe.py |
| alpha | 0.05 | 0.05 | yes | model | s3_model.py |
| model_formula | satisfaction ~ income_k | satisfaction ~ income_k | yes | model | s3_model.py |
| round_digits | 3 | 3 | yes | model | s3_model.py |
| min_age | (not read by any step) | 18 | n/a | | |

The model records follow.

| Record | Model | Spec | n | Made under current params.yaml | Reproduces |
|---|---|---|---|---|---|
| model_record_model.json | OLS | satisfaction ~ income_k | 40 | **no** | **no** |

## Notes

- check_params / min_age: set in params.yaml but read by no script
- check_params / params_io.py:L106: literal declared not a parameter
- check_params / s2_describe.py:L58: literal declared not a parameter
