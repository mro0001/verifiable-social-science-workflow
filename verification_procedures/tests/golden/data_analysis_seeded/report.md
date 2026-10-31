# Data analysis report

This report shows the data analysis for the scholar to verify. The outline lists each step with a short title, and under it each title is shown again with the exact code that carries it out, copied from its script with its file and lines. A step is a section a script marks with a comment line `# step: <title>`, or, in a Python script that marks none, a function the script calls, in the order it calls them. The descriptions table lists each sentence of the final build's text that describes this phase, as one model step found them, with where the scripts carry it out or missing. A program checks that each quote is in the text and that each place is in the scripts. No model judges whether a description fits its code, and the scholar approves or holds each description.

Pipeline steps in this phase 1, outline steps 3. Descriptions found 2 (missing from the scripts 0, quotes not in the text 0, places not in the scripts 0).

## Summary

- Blocking: 0
- Warnings: 0
- Notes: 0

## Problems

None.

## Outline

- `model`, `s2_model.py`
  - Read data
  - Fit model
  - Write table

## Code

### Read data

`s2_model.py` lines 4-8

```python
# step: Read data
with open("clean_survey.csv", newline="") as f:
    rows = list(csv.DictReader(f))
x = [int(r["income"]) / 1000 for r in rows]
y = [int(r["satisfaction"]) for r in rows]
```

### Fit model

`s2_model.py` lines 10-14

```python
# step: Fit model
n = len(x)
mx, my = sum(x) / n, sum(y) / n
slope = sum((a - mx) * (b - my) for a, b in zip(x, y)) / sum((a - mx) ** 2 for a in x)
intercept = my - slope * mx
```

### Write table

`s2_model.py` lines 16-20

```python
# step: Write table
with open("table_model.csv", "w", newline="") as f:
    f.write("term,estimate\n")
    f.write("intercept,%.3f\n" % intercept)
    f.write("income_k,%.3f\n" % slope)
```

## Descriptions

Each row is a sentence of the final build's text that the finding step gave as describing this phase, with the places in the scripts it gave. The last two columns are the program's checks. A place is confirmed when it is lines of a script the pipeline declares, and the steps it falls in are named beside it.

| Id | Description in the final build's text | Where the scripts carry it out | Quote in the text | Location check |
|---|---|---|---|---|
| d01 | We regressed satisfaction on income in thousands by ordinary least squares. | `s2_model.py` line 7 (analysis, Read data); `s2_model.py` lines 10-14 (analysis, Fit model) | yes | confirmed |
| d02 | The table reports the intercept and the slope to three decimals. | `s2_model.py` lines 16-20 (analysis, Write table) | yes | confirmed |

## Files read

- `final_text.md`, the final build's text, sha256:b4f9a79c8351e92e2a08b5a88d10d9c6605598a7cb9d4f85b500be52d357c3c3
- `pipeline.yaml`, the pipeline, sha256:9a752b98b171686a03d463149886cf513692caef0641af0159e5ece64bf64dbf
- `s0_collect.py`, the script of step collect, sha256:83c741181757ee3fe498e3e7599dc17f72ebaa73d0c5c9dcd86616da3a7653ad
- `s1_clean.py`, the script of step clean, sha256:9bcad0ae4fea754a196d3f522b62278650e6c6f14f8834226d169a75538b083c
- `s2_model.py`, the script of step model, sha256:d2340d8510c10e9837930d84b9dc9e5434facdfae43e57d9e5e7d80257ccfc30

## Notes

None.
