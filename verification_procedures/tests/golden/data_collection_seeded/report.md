# Data collection report

This report shows the data collection for the scholar to verify. The outline lists each step with a short title, and under it each title is shown again with the exact code that carries it out, copied from its script with its file and lines. A step is a section a script marks with a comment line `# step: <title>`, or, in a Python script that marks none, a function the script calls, in the order it calls them. The descriptions table lists each sentence of the final build's text that describes this phase, as one model step found them, with where the scripts carry it out or missing. A program checks that each quote is in the text and that each place is in the scripts. No model judges whether a description fits its code, and the scholar approves or holds each description.

Pipeline steps in this phase 1, outline steps 2. Descriptions found 3 (missing from the scripts 0, quotes not in the text 0, places not in the scripts 0).

## Summary

- Blocking: 0
- Warnings: 0
- Notes: 0

## Problems

None.

## Outline

- `collect`, `s0_collect.py`
  - Draw sample
  - Write raw

## Code

### Draw sample

`s0_collect.py` lines 7-13

```python
# step: Draw sample
rng = random.Random(2026)
rows = []
for i in range(1, 61):
    rows.append({"id": i, "region": rng.choice(["North", "South", "East", "West"]),
                 "age": rng.randint(15, 80), "income": rng.randint(20000, 340000),
                 "satisfaction": rng.randint(1, 5)})
```

### Write raw

`s0_collect.py` lines 15-19

```python
# step: Write raw
with open("raw_survey.csv", "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
```

## Descriptions

Each row is a sentence of the final build's text that the finding step gave as describing this phase, with the places in the scripts it gave. The last two columns are the program's checks. A place is confirmed when it is lines of a script the pipeline declares, and the steps it falls in are named beside it.

| Id | Description in the final build's text | Where the scripts carry it out | Quote in the text | Location check |
|---|---|---|---|---|
| d01 | We drew a synthetic sample of 60 respondents with a fixed random seed. | `s0_collect.py` lines 7-13 (collection, Draw sample) | yes | confirmed |
| d02 | Each record gives the respondent's region, age, income, and satisfaction on a five-point scale. | `s0_collect.py` lines 9-12 (collection, Draw sample) | yes | confirmed |
| d03 | The sample was saved once as the raw file and never edited. | `s0_collect.py` lines 15-19 (collection, Write raw) | yes | confirmed |

## Files read

- `final_text.md`, the final build's text, sha256:b4f9a79c8351e92e2a08b5a88d10d9c6605598a7cb9d4f85b500be52d357c3c3
- `pipeline.yaml`, the pipeline, sha256:9a752b98b171686a03d463149886cf513692caef0641af0159e5ece64bf64dbf
- `s0_collect.py`, the script of step collect, sha256:83c741181757ee3fe498e3e7599dc17f72ebaa73d0c5c9dcd86616da3a7653ad
- `s1_clean.py`, the script of step clean, sha256:9bcad0ae4fea754a196d3f522b62278650e6c6f14f8834226d169a75538b083c
- `s2_model.py`, the script of step model, sha256:d2340d8510c10e9837930d84b9dc9e5434facdfae43e57d9e5e7d80257ccfc30

## Notes

None.
