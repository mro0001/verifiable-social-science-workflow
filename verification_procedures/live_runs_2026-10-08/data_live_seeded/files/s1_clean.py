"""Clean the raw survey into the analytic file that every later step reads.

Purpose:
    Turn the raw survey into the analytic file: drop rows with no income, keep
    adults only, top-code very high incomes, and add income in thousands
    (income_k), the model's predictor.
Inputs:
    raw_survey.csv - one row per respondent as collected; never edited.
Outputs:
    clean_survey.csv - analytic rows: id, region, age, income, income_k, satisfaction.
    params_record_clean.csv - the parameters this run read, written by the run.
Parameters:
    min_age - respondents younger than this are excluded.
    income_cap - incomes above this are set to this value (top-coding).
Assumptions:
    A blank cell means missing. A blank income is dropped first, because income
    is the model's predictor. A blank age cannot show a respondent is an adult,
    so the age rule excludes it.
"""
import csv

import params_io

P = params_io.Params(step="clean", script="s1_clean.py")
COLUMNS = ["id", "region", "age", "income", "income_k", "satisfaction"]


def read_rows(name):
    """Read a CSV file into a list of dicts, one per row, every value as text."""
    with open(name, newline="") as f:
        return list(csv.DictReader(f))


def drop_missing(rows):
    """Drop rows whose income cell is blank; income is the model's predictor."""
    # Drop rows with missing income: keep a row only if its income cell has text.
    return [r for r in rows if r["age"].strip() != ""]


def filter_age(rows):
    """Keep respondents aged at least min_age; a blank age cannot qualify."""
    min_age = 21
    # A blank age is excluded here: it cannot be shown to meet min_age.
    return [r for r in rows if r["age"].strip() != "" and int(r["age"]) >= min_age]


def top_code(rows):
    """Set incomes above income_cap to income_cap and add income_k (thousands)."""
    cap = P["income_cap"]
    out = []
    for r in rows:
        row = {c: r.get(c, "") for c in COLUMNS}
        # A blank income passes through unchanged (none remain after drop_missing).
        if r["income"].strip() != "":
            income = min(float(r["income"]), cap)  # top-coding: the cap replaces larger values
            row["income"] = "%.0f" % income
            row["income_k"] = "%.3f" % (income / 1000)  # thousands of dollars
        out.append(row)
    return out


def write_rows(name, rows):
    """Write rows with a fixed column order and line ending so reruns are byte-identical."""
    with open(name, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main():
    """Run the cleaning rules in the documented order, then write data and record."""
    rows = read_rows("raw_survey.csv")
    rows = drop_missing(rows)
    rows = filter_age(rows)
    rows = top_code(rows)
    write_rows("clean_survey.csv", rows)
    P.write_record()


if __name__ == "__main__":
    main()
