# Data verification report

Data stream verification: the pipeline replayed from raw data in an empty folder; parameters checked for being set once in params.yaml; parameter and model records checked against params.yaml and the replay; manuscript numbers checked against the replayed outputs; method documentation checked for structure (tool) and truth (judgment). 3 steps, 1 raw file(s), 5 manuscript numbers.

## Summary

- Blocking: 7
- Warnings: 5
- Notes: 3

## Problems

| Severity | Check | Item | Problem | Evidence |
|---|---|---|---|---|
| blocking | check_docs | s2_describe.py | module docstring lacks sections: Inputs, Outputs, Parameters, Assumptions | present: Purpose |
| blocking | check_numbers | slope_income_k | manuscript number does not come from the process | numbers.yml '0.015'; replayed table_model.csv estimate = '0.011' |
| blocking | check_params | s1_clean.py:L42 | hard-coded parameter: min_age = 21 here, params.yaml sets min_age: 18 | min_age = 21 |
| blocking | check_raw | raw_survey.csv | raw data changed after acquisition | recorded sha256:2ce927e550d1..., now sha256:6d2976a77b36... |
| blocking | check_records | model_record_model.json | stale model: record was made under a different params.yaml | record sha256:f2dd99589ab9..., current sha256:0a5141ade027... |
| blocking | replay_pipeline | model_record_model.json | output does not reproduce: hand-edited or stale | line 16: committed '  "params_sha256": "sha256:f2dd99589ab9088ba40d9eacf1ca176fd2f2ef4a829' / replayed '  "params_sha256": "sha256:0a5141ade02767b3bc4075e416ab… |
| blocking | replay_pipeline | table_descriptives.csv | output does not reproduce: hand-edited or stale | line 4: committed 'South,10,0,91.320,3.200' / replayed 'South,10,0,86.820,3.200' |
| warning | check_docs | s1_clean.py | Parameters section names min_age, but the script never reads it from params.yaml | min_age - respondents younger than this are excluded. |
| warning | judge_method_docs | s1_clean | documentation does not describe what the code does (judgment: confirm) | says 'Drop rows with missing income: keep a row only if its income cell has text.', code 'return [r for r in rows if r["age"].strip() != ""]'; says 'min_age - … |
| warning | judge_method_docs | s1_clean.drop_missing | documentation does not describe what the code does (judgment: confirm) | says 'Drop rows whose income cell is blank', code 'return [r for r in rows if r["age"].strip() != ""]'; says 'keep a row only if its income cell has text', cod… |
| warning | judge_method_docs | s1_clean.filter_age | documentation does not describe what the code does (judgment: confirm) | says 'Keep respondents aged at least min_age', code 'min_age = 21' [live:qwen/qwen3.5-122b] |
| warning | replay_pipeline | s3_model.py | step wrote warnings to stderr while exiting 0 | <replay>/s3_model.py:50: UserWarning: 3 rows dropped: blank satisfaction or income_k   warnings.warn("%d rows dropped: blank %s or %s" % (dropped, outcome, pre… |

## Pipeline

| Step | Script | Reproduces | Records ok | Docs ok | Stderr |
|---|---|---|---|---|---|
| clean | s1_clean.py | yes | yes | **no** | clean |
| describe | s2_describe.py | **no** (table_descriptives.csv) | yes | **no** | clean |
| model | s3_model.py | **no** (model_record_model.json) | **no** | yes | warning |

Docs ok covers the docstring sections, the parameter scan of the script, and the per-function judgment.

## Parameter record

Assembled from the parameter records the replay wrote, not from the committed copies.

| Param | Value recorded | params.yaml | Agrees | Step | Script |
|---|---|---|---|---|---|
| income_cap | 250000 | 250000 | yes | clean | s1_clean.py |
| fig_height | 260 | 260 | yes | describe | s2_describe.py |
| fig_width | 480 | 480 | yes | describe | s2_describe.py |
| round_digits | 3 | 3 | yes | describe | s2_describe.py |
| alpha | 0.05 | 0.05 | yes | model | s3_model.py |
| model_formula | satisfaction ~ income_k | satisfaction ~ income_k | yes | model | s3_model.py |
| round_digits | 3 | 3 | yes | model | s3_model.py |
| min_age | (not read by any step) | 18 | n/a | | |

## Model records

| Record | Model | Spec | n | Made under current params.yaml | Reproduces |
|---|---|---|---|---|---|
| model_record_model.json | OLS | satisfaction ~ income_k | 40 | **no** | **no** |

## Manuscript numbers

| Key | numbers.yml | Replayed | From | Agrees |
|---|---|---|---|---|
| alpha | 0.05 | 0.05 | params_record_model.csv | yes |
| mean_income_k_north | 63.487 | 63.487 | table_descriptives.csv | yes |
| n_analytic | 40 | 40 | model_record_model.json | yes |
| p_income_k | 0.000 | 0.000 | table_model.csv | yes |
| slope_income_k | 0.015 | 0.011 | table_model.csv | **no** |

## Method documentation judgments

30 method items judged (4 step, 26 function); 3 judged not to match the code.

## Notes

- check_params / min_age: set in params.yaml but read by no script
- check_params / params_io.py:L106: literal declared not a parameter
- check_params / s2_describe.py:L58: literal declared not a parameter
