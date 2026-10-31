# Data verification report

Data stream verification: the pipeline replayed from raw data in an empty folder; parameters checked for being set once in params.yaml; parameter and model records checked against params.yaml and the replay; manuscript numbers checked against the replayed outputs; method documentation checked for structure (tool) and truth (judgment). 3 steps, 1 raw file(s), 5 manuscript numbers.

## Summary

- Blocking: 0
- Warnings: 0
- Notes: 2

## Problems

None.

## Pipeline

| Step | Script | Reproduces | Records ok | Docs ok | Stderr |
|---|---|---|---|---|---|
| clean | s1_clean.py | yes | yes | yes | clean |
| describe | s2_describe.py | yes | yes | yes | clean |
| model | s3_model.py | yes | yes | yes | clean |

Docs ok covers the docstring sections, the parameter scan of the script, and the per-function judgment.

## Parameter record

Assembled from the parameter records the replay wrote, not from the committed copies.

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

## Model records

| Record | Model | Spec | n | Made under current params.yaml | Reproduces |
|---|---|---|---|---|---|
| model_record_model.json | OLS | satisfaction ~ income_k | 41 | yes | yes |

## Manuscript numbers

| Key | numbers.yml | Replayed | From | Agrees |
|---|---|---|---|---|
| alpha | 0.05 | 0.05 | params_record_model.csv | yes |
| mean_income_k_north | 59.311 | 59.311 | table_descriptives.csv | yes |
| n_analytic | 41 | 41 | model_record_model.json | yes |
| p_income_k | 0.000 | 0.000 | table_model.csv | yes |
| slope_income_k | 0.011 | 0.011 | table_model.csv | yes |

## Method documentation judgments

30 method items judged (4 step, 26 function); 0 judged not to match the code.

## Notes

- check_params / params_io.py:L106: literal declared not a parameter
- check_params / s2_describe.py:L73: literal declared not a parameter
