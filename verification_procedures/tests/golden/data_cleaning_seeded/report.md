# Data cleaning report

This report shows the data cleaning for the scholar to verify. The outline lists each step with a short title, and under it each title is shown again with the exact code that carries it out, copied from its script with its file and lines. A step is a section a script marks with a comment line `# step: <title>`, or, in a Python script that marks none, a function the script calls, in the order it calls them. The descriptions table lists each sentence of the final build's text that describes this phase, as one model step found them, with where the scripts carry it out or missing. A program checks that each quote is in the text and that each place is in the scripts. No model judges whether a description fits its code, and the scholar approves or holds each description.

Pipeline steps in this phase 1, outline steps 6. Descriptions found 4 (missing from the scripts 1, quotes not in the text 1, places not in the scripts 0).

## Summary

- Blocking: 0
- Warnings: 2
- Notes: 1

## Problems

| Severity | Check | Item | Problem | Evidence |
|---|---|---|---|---|
| warning | check_descriptions | d02 | The quote is not in the final build's text. | We kept only respondents aged 18 or older. |
| warning | check_descriptions | d04 | The finding step gave no place in the scripts that carries out this description. |  |

## Outline

- `clean`, `s1_clean.py`
  - Main
  - Read rows
  - Drop missing
  - Filter age
  - Top code
  - Write rows

## Code

### Main

`s1_clean.py` lines 44-49

```python
def main():
    """Run the cleaning rules in order."""
    rows = read_rows("raw_survey.csv")
    rows = drop_missing(rows)
    rows = filter_age(rows)
    write_rows("clean_survey.csv", top_code(rows))
```

### Read rows

`s1_clean.py` lines 8-11

```python
def read_rows(name):
    """Read a CSV file into a list of dicts, one per row."""
    with open(name, newline="") as f:
        return list(csv.DictReader(f))
```

### Drop missing

`s1_clean.py` lines 14-16

```python
def drop_missing(rows):
    """Drop rows whose income cell is blank."""
    return [r for r in rows if r["income"].strip() != ""]
```

### Filter age

`s1_clean.py` lines 19-21

```python
def filter_age(rows):
    """Keep respondents aged 18 or older."""
    return [r for r in rows if r["age"].strip() != "" and int(r["age"]) >= 18]
```

### Top code

`s1_clean.py` lines 24-28

```python
def top_code(rows):
    """Set incomes above 250000 to 250000."""
    for r in rows:
        r["income"] = str(min(int(r["income"]), 250000))
    return rows
```

### Write rows

`s1_clean.py` lines 36-41

```python
def write_rows(name, rows):
    """Write the rows with a fixed column order."""
    with open(name, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
```

## Descriptions

Each row is a sentence of the final build's text that the finding step gave as describing this phase, with the places in the scripts it gave. The last two columns are the program's checks. A place is confirmed when it is lines of a script the pipeline declares, and the steps it falls in are named beside it.

| Id | Description in the final build's text | Where the scripts carry it out | Quote in the text | Location check |
|---|---|---|---|---|
| d01 | Rows with a missing income were dropped. | `s1_clean.py` lines 14-16 (cleaning, Drop missing) | yes | confirmed |
| d02 | We kept only respondents aged 18 or older. | `s1_clean.py` lines 19-21 (cleaning, Filter age) | no | confirmed |
| d03 | Incomes above 250,000 were top-coded to 250,000. | `s1_clean.py` lines 24-28 (cleaning, Top code) | yes | confirmed |
| d04 | Responses were weighted to the regional population shares. | missing | yes | missing |

## Files read

- `final_text.md`, the final build's text, sha256:b4f9a79c8351e92e2a08b5a88d10d9c6605598a7cb9d4f85b500be52d357c3c3
- `pipeline.yaml`, the pipeline, sha256:9a752b98b171686a03d463149886cf513692caef0641af0159e5ece64bf64dbf
- `s0_collect.py`, the script of step collect, sha256:83c741181757ee3fe498e3e7599dc17f72ebaa73d0c5c9dcd86616da3a7653ad
- `s1_clean.py`, the script of step clean, sha256:9bcad0ae4fea754a196d3f522b62278650e6c6f14f8834226d169a75538b083c
- `s2_model.py`, the script of step model, sha256:d2340d8510c10e9837930d84b9dc9e5434facdfae43e57d9e5e7d80257ccfc30

## Notes

- outline_steps / s1_clean.py line 31: The function winsorize is never called by the script, so it is not a step.
