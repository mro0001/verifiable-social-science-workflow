"""Fit the manuscript's model: satisfaction regressed on income (OLS, one predictor).

Purpose:
    Estimate how satisfaction changes with income and write the coefficient
    table and the model record the manuscript's numbers come from.
Inputs:
    clean_survey.csv - analytic rows from s1_clean.py.
Outputs:
    table_model.csv - term, estimate, se, t, p, significant.
    model_record_model.json - spec, parameters used, params.yaml hash, n, outputs, estimates.
    params_record_model.csv - the parameters this run read, written by the run.
Parameters:
    model_formula - "outcome ~ predictor", one predictor.
    alpha - significance threshold for the significant column.
    round_digits - decimals shown in the published table.
Assumptions:
    Ordinary least squares with an intercept. p uses the normal approximation
    to the t distribution, adequate for n above about 30. A row with a blank
    outcome or predictor is dropped and the drop is announced on stderr as a
    warning, so a replay that reads stderr sees it. (R binding: lm(formula,
    data); a dropped-row warning must be read from stderr there too.)
"""
import csv
import math
import warnings

import params_io

P = params_io.Params(step="model", script="s3_model.py")


def read_rows(name):
    """Read a CSV file into a list of dicts, one per row, every value as text."""
    with open(name, newline="") as f:
        return list(csv.DictReader(f))


def parse_formula(formula):
    """Split 'outcome ~ predictor' into its two column names."""
    outcome, _, predictor = formula.partition("~")
    return outcome.strip(), predictor.strip()


def complete_cases(rows, outcome, predictor):
    """Keep rows with both outcome and predictor present; warn on stderr if any are dropped."""
    kept = [r for r in rows if r[outcome].strip() != "" and r[predictor].strip() != ""]
    dropped = len(rows) - len(kept)
    # The drop is announced, never silent: a replay reads this warning from stderr.
    if dropped:
        warnings.warn("%d rows dropped: blank %s or %s" % (dropped, outcome, predictor))
    return kept


def ols(xs, ys):
    """Fit y = a + b*x by least squares; return intercept, slope, and their standard errors."""
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx
    intercept = my - slope * mx
    sse = sum((y - intercept - slope * x) ** 2 for x, y in zip(xs, ys))
    sigma2 = sse / (n - 2)  # residual variance on n - 2 degrees of freedom
    se_slope = math.sqrt(sigma2 / sxx)
    se_intercept = math.sqrt(sigma2 * (1 / n + mx ** 2 / sxx))
    return intercept, slope, se_intercept, se_slope


def coef_rows(names, estimates, ses):
    """Build the coefficient table: t = estimate / se, p from the normal approximation."""
    digits, alpha = P["round_digits"], P["alpha"]
    rows = []
    for name, est, se in zip(names, estimates, ses):
        t = est / se
        p = math.erfc(abs(t) / math.sqrt(2))  # two-sided p, normal approximation to t
        rows.append({"term": name, "estimate": "%.*f" % (digits, est), "se": "%.*f" % (digits, se),
                     "t": "%.*f" % (digits, t), "p": "%.*f" % (digits, p),
                     "significant": "yes" if p < alpha else "no"})
    return rows


def main():
    """Fit the model, write the coefficient table, the model record, and the parameter record."""
    formula = P["model_formula"]
    outcome, predictor = parse_formula(formula)
    rows = complete_cases(read_rows("clean_survey.csv"), outcome, predictor)
    xs = [float(r[predictor]) for r in rows]
    ys = [float(r[outcome]) for r in rows]
    a, b, se_a, se_b = ols(xs, ys)
    table = coef_rows(["intercept", predictor], [a, b], [se_a, se_b])
    with open("table_model.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(table[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(table)
    params_io.write_model_record(P, model="OLS", spec=formula, n=len(rows),
                                 outputs=["table_model.csv"],
                                 estimates={t["term"]: t["estimate"] for t in table})
    P.write_record()


if __name__ == "__main__":
    main()
