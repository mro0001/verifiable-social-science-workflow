"""Synthetic fixture for the foundation contract. Fake values, real shape."""

MANIFEST_YAML = """\
widget_smape_real: 33.5
widget.compliance.rate: 98.2%
widget-p-method: "0.050"
n_cities: 24
"""

OVERLAY_YAML = """\
gadget_icc: "0.91"
"""

OVERLAY_COLLIDING_YAML = """\
n_cities: 25
"""

SAMPLE_MD = """\
# Synthetic section

The widget benchmark reached a sMAPE of {{num:widget_smape_real}} across {{num:n_cities}} cities.
Compliance was {{num:widget.compliance.rate}} overall (p = {{num:widget-p-method}}).

{{table:widget_summary}}

```python
d = {{'literal': 'braces in a fence stay untouched'}}
```
"""

SAMPLE_TABLE = """\
| model | sMAPE |
|---|---|
| widget | {{num:widget_smape_real}} |
"""
