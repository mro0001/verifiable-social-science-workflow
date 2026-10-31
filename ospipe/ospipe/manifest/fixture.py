"""Synthetic fixture for the manifest emitter contract. Fake values, real shape.

Two analysis outputs (a JSON results file and a CSV table) and a numbers
manifest in the data procedure's `numbers:` shape whose values all match them.
Tests write these into a temporary folder and change the outputs to see the
emitter fill the values.
"""
import json

OUTPUTS_JSON_NAME = "widget_results.json"
OUTPUTS_CSV_NAME = "widget_table.csv"

OUTPUTS = {
    "run": {"cities": 24, "label": "fake widget run"},
    "summary": {"smape": 33.5, "compliance_pct": "98.2"},
    "cities": [
        {"name": "Alpha", "smape": 12.25},
        {"name": "Beta", "smape": 9.75},
    ],
    "flags": {"weighted": True, "missing": None, "levels": [1, 2], "detail": {"a": 1}},
}

OUTPUTS_JSON = json.dumps(OUTPUTS, indent=2) + "\n"

OUTPUTS_CSV = """\
city,year,smape
Alpha,2020,12.5
Alpha,2021,13.0
Beta,2020,9.75
Beta,2020,9.80
"""

MANIFEST_YAML = """\
# Synthetic numbers manifest, every value from the widget outputs.
# The emitter keeps these leading lines.

numbers:
  run.cities: {value: "24", from: widget_results.json, field: run.cities}
  run.label: {value: "fake widget run", from: widget_results.json, field: run.label}
  summary.smape: {value: "33.5", from: widget_results.json, field: summary.smape}
  summary.compliance: {value: "98.2", from: widget_results.json, field: summary.compliance_pct}
  alpha.smape: {value: "12.25", from: widget_results.json, field: cities.0.smape}
  alpha_2021.smape: {value: "13.0", from: widget_table.csv, field: smape, where: {city: Alpha, year: 2021}}
"""

MANIFEST_KEYS = (
    "run.cities",
    "run.label",
    "summary.smape",
    "summary.compliance",
    "alpha.smape",
    "alpha_2021.smape",
)

# Every problem kind, one entry each, against the outputs above.
PROBLEM_MANIFEST_YAML = """\
numbers:
  no_from: {value: "1", field: run.cities}
  no_field: {value: "1", from: widget_results.json}
  missing_file: {value: "1", from: absent.json, field: run.cities}
  missing_json_field: {value: "1", from: widget_results.json, field: run.nothing}
  list_past_end: {value: "1", from: widget_results.json, field: cities.5.smape}
  missing_column: {value: "1", from: widget_table.csv, field: nothing, where: {city: Alpha, year: 2020}}
  zero_rows: {value: "1", from: widget_table.csv, field: smape, where: {city: Gamma}}
  several_rows: {value: "1", from: widget_table.csv, field: smape, where: {city: Beta, year: 2020}}
  refused_true: {value: "1", from: widget_results.json, field: flags.weighted}
  refused_null: {value: "1", from: widget_results.json, field: flags.missing}
  refused_list: {value: "1", from: widget_results.json, field: flags.levels}
  refused_object: {value: "1", from: widget_results.json, field: flags.detail}
"""

PROBLEM_KEYS = (
    "no_from",
    "no_field",
    "missing_file",
    "missing_json_field",
    "list_past_end",
    "missing_column",
    "zero_rows",
    "several_rows",
    "refused_true",
    "refused_null",
    "refused_list",
    "refused_object",
)
