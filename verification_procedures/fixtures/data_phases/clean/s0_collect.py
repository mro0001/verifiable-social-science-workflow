"""Draw the synthetic survey and write it as the raw file. Invented values only."""
import csv
import random

COLUMNS = ["id", "region", "age", "income", "satisfaction"]

# step: Draw sample
rng = random.Random(2026)
rows = []
for i in range(1, 61):
    rows.append({"id": i, "region": rng.choice(["North", "South", "East", "West"]),
                 "age": rng.randint(15, 80), "income": rng.randint(20000, 340000),
                 "satisfaction": rng.randint(1, 5)})

# step: Write raw
with open("raw_survey.csv", "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
