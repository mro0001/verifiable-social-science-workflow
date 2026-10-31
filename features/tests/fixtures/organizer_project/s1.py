"""The fixture's one pipeline step, which counts the agencies in raw.csv."""
import csv
import json

with open("raw.csv", newline="") as handle:
    rows = list(csv.DictReader(handle))
with open("results.json", "w") as handle:
    json.dump({"agencies": len(rows)}, handle)
