"""Synthetic fixture for the lint contract. Fake values, real shape.

SAMPLE_MD exercises every contract category: a bare percentage (must flag),
years (must not), an allowlisted constant (must not), a numeral in a fence
(must not), a numeral in an inline code span (must not), a placeholder
(must not), citation years (must not), a numbered list (must not), plus a
numbered heading and a table separator row.
"""

ALLOWLIST = ("42.7",)

# With ALLOWLIST, lint(SAMPLE_MD, ALLOWLIST) yields exactly one finding:
# '12.5%' on line 5. Without the allowlist, '42.7' on line 7 also flags.
SAMPLE_MD = """\
# Synthetic results

## 3. Findings

The gadget cohort improved by 12.5% overall.
Data collection ran from 2019 to 2024 across the region.
The literature benchmark of 42.7 is tracker-registered (Chung et al. 2025).
Sensitivity followed earlier work (Darwin 1859).
The widget rate was {{num:widget.rate}} in the final pass.

1. First step of the synthetic protocol
2. Second step with `retries = 3` inline

| model | score |
|---|---|
| widget | {{num:widget.rate}} |

```python
threshold = 0.75
```
"""
