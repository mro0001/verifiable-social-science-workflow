"""Synthetic fixture for the resolve contract. Fake values, real shape."""

MANIFEST = {
    "alpha": "1.5",
    "beta": "97.4%",
    "widget_smape_real": "33.5",
    "widget.compliance.rate": "98.2%",
    "widget-p-method": "0.050",
    "n_cities": "24",
}

TABLES = {
    "tiny_table": "| a | b |\n|---|---|\n| {{num:alpha}} | 2 |\n",
}

START_MD = "{{table:tiny_table}}\nProse after a leading table of {{num:alpha}} units.\n"

TWO_ON_ONE_LINE_MD = "Rates were {{num:alpha}} and then {{num:beta}} at follow-up.\n"

TYPO_MD = "Line one is fine.\nThis line has a {{numb:alpha}} typo.\n"

FENCE_EXEMPT_MD = """\
Prose with {{num:alpha}} resolves.

```text
A fence may contain {{fake:thing}} and it is not a remnant.
```
"""

INLINE_SPAN_MD = "An inline span `{{oops:1}}` is exempt from the remnant scan.\n"

MISSING_BOTH_MD = "Needs {{num:ghost_number}} and {{table:phantom_table}} to build.\n"
