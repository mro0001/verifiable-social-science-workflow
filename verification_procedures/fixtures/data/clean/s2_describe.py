"""Describe income and satisfaction by region: one table and one figure.

Purpose:
    Summarize the analytic file by region for the manuscript's descriptive
    table and its bar chart of mean income.
Inputs:
    clean_survey.csv - analytic rows from s1_clean.py.
Outputs:
    table_descriptives.csv - per region: n, n_missing, mean_income_k, mean_satisfaction.
    fig_income_by_region.svg - bar chart of mean_income_k by region.
    params_record_describe.csv - the parameters this run read, written by the run.
Parameters:
    round_digits - decimals shown in the published table.
    fig_width - figure width in pixels.
    fig_height - figure height in pixels.
Assumptions:
    Incomes are complete after s1_clean.py. A blank income_k is skipped in the
    mean and counted in n_missing, so a nonzero n_missing is visible in the
    table rather than silent. Regions appear in alphabetical order.
"""
import csv
import statistics

import params_io

P = params_io.Params(step="describe", script="s2_describe.py")


def read_rows(name):
    """Read a CSV file into a list of dicts, one per row, every value as text."""
    with open(name, newline="") as f:
        return list(csv.DictReader(f))


def by_region(rows):
    """Group rows by region; regions sorted alphabetically for a stable order."""
    groups = {}
    for r in rows:
        groups.setdefault(r["region"], []).append(r)
    return [(region, groups[region]) for region in sorted(groups)]


def summarize(rows):
    """Compute n, n_missing, mean income_k, and mean satisfaction for each region."""
    digits = P["round_digits"]
    table = []
    for region, group in by_region(rows):
        incomes = [float(r["income_k"]) for r in group if r["income_k"].strip() != ""]
        # A blank income_k is skipped in the mean and counted, never dropped silently.
        n_missing = len(group) - len(incomes)
        table.append({
            "region": region,
            "n": len(group),
            "n_missing": n_missing,
            "mean_income_k": "%.*f" % (digits, statistics.mean(incomes)),
            "mean_satisfaction": "%.*f" % (digits, statistics.mean(float(r["satisfaction"]) for r in group)),
        })
    return table


def write_table(name, table):
    """Write the descriptive table with a fixed column order and line ending."""
    cols = ["region", "n", "n_missing", "mean_income_k", "mean_satisfaction"]
    with open(name, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
        writer.writeheader()
        writer.writerows(table)


def svg_bars(table):
    """Draw mean income_k by region as an SVG bar chart sized by fig_width and fig_height."""
    width, height = P["fig_width"], P["fig_height"]
    margin = 40  # not-a-param: layout margin in pixels, not an analytic choice
    top = max(float(t["mean_income_k"]) for t in table)
    slot = (width - 2 * margin) / len(table)
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d">' % (width, height)]
    for i, t in enumerate(table):
        # Bar height is proportional to mean income_k; the tallest bar fills the plot area.
        h = (height - 2 * margin) * float(t["mean_income_k"]) / top
        x = margin + i * slot
        y = height - margin - h
        parts.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#4a6fa5"/>'
                     % (x + slot * 0.1, y, slot * 0.8, h))
        parts.append('<text x="%.1f" y="%.1f" text-anchor="middle" font-size="12">%s</text>'
                     % (x + slot / 2, height - margin / 2, t["region"]))
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def main():
    """Summarize, write the table and the figure, then write the parameter record."""
    table = summarize(read_rows("clean_survey.csv"))
    write_table("table_descriptives.csv", table)
    with open("fig_income_by_region.svg", "w") as f:
        f.write(svg_bars(table))
    P.write_record()


if __name__ == "__main__":
    main()
