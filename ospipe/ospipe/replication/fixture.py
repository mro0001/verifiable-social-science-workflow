"""Synthetic fixture for the replication contract. Fake values, real shape.

The tests copy the sample project (`examples/sample_project/`) into a temporary folder
and write its build file with `add_product`. This file holds the closures they expect,
stand-ins for the results files and the audit layer's written-out records, and lines a
test appends to the manuscript.
"""

# The manuscript's closure in the sample project, rule from
# add_product("manuscript", "manuscript.md", bib="refs.bib", tables_dir=".").
MANUSCRIPT_CLOSURE = (
    "acquisition.yaml",
    "manuscript.md",
    "next_word_counts.json",
    "next_word_results.json",
    "numbers.yml",
    "params.yaml",
    "params_io.py",
    "params_record_results.csv",
    "pipeline.yaml",
    "refs.bib",
    "s1_results.py",
    "top_words.md",
)

# The slides' closure, rule from add_product("slides", "slides.md", to="revealjs", tables_dir=".").
SLIDES_CLOSURE = tuple(
    sorted(
        ("slides.md" if name == "manuscript.md" else name)
        for name in MANUSCRIPT_CLOSURE
        if name != "refs.bib"
    )
)

# The audit layer's written-out records a project may hold, at their default places.
AUDIT_RECORDS = (
    "audit/citation_log.yaml",
    "audit/rationales.yaml",
    "audit/session_writes.jsonl",
)

# Stand-ins. The closure ships these files whole and never reads them.
RESULTS_STUB = '{"schema": "verification-results", "schema_version": 1, "run_id": "fake_run", "items": []}\n'
RECORD_STUB = "# fake written-out record\n"

# A local image, a remote image, and an image inside a code fence, which is not an image.
IMAGE_LINES = """
![A fake plot](figs/plot.png "Fake plot")

![A remote figure](https://example.org/figure.png)

```
![not an image](figs/fenced.png)
```
"""

# A missing table, an image outside the project, and an image at an absolute path.
BAD_LINES = """
{{table:ghost_table}}

![Outside](../outside.png)

![Absolute](/Users/someone/plot.png)
"""
