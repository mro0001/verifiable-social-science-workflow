"""Fit satisfaction on income in thousands by least squares and write the table."""
import csv

# step: Read data
with open("clean_survey.csv", newline="") as f:
    rows = list(csv.DictReader(f))
x = [int(r["income"]) / 1000 for r in rows]
y = [int(r["satisfaction"]) for r in rows]

# step: Fit model
n = len(x)
mx, my = sum(x) / n, sum(y) / n
slope = sum((a - mx) * (b - my) for a, b in zip(x, y)) / sum((a - mx) ** 2 for a in x)
intercept = my - slope * mx

# step: Write table
with open("table_model.csv", "w", newline="") as f:
    f.write("term,estimate\n")
    f.write("intercept,%.3f\n" % intercept)
    f.write("income_k,%.3f\n" % slope)
