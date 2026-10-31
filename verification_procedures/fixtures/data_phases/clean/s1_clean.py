"""Clean the raw survey into the analytic file. No step is marked, so the steps are the
functions in the order main calls them."""
import csv

COLUMNS = ["id", "region", "age", "income", "satisfaction"]


def read_rows(name):
    """Read a CSV file into a list of dicts, one per row."""
    with open(name, newline="") as f:
        return list(csv.DictReader(f))


def drop_missing(rows):
    """Drop rows whose income cell is blank."""
    return [r for r in rows if r["income"].strip() != ""]


def filter_age(rows):
    """Keep respondents aged 18 or older."""
    return [r for r in rows if r["age"].strip() != "" and int(r["age"]) >= 18]


def top_code(rows):
    """Set incomes above 250000 to 250000."""
    for r in rows:
        r["income"] = str(min(int(r["income"]), 250000))
    return rows


def winsorize(rows):
    """An older rule the script no longer calls."""
    return rows


def write_rows(name, rows):
    """Write the rows with a fixed column order."""
    with open(name, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main():
    """Run the cleaning rules in order."""
    rows = read_rows("raw_survey.csv")
    rows = drop_missing(rows)
    rows = filter_age(rows)
    write_rows("clean_survey.csv", top_code(rows))


if __name__ == "__main__":
    main()
