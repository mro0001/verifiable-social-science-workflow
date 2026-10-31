"""Synthetic fixture for the build contract. Fake values, real shape.

Resolved markdown, slides, and the page have no placeholders remaining; the bibliography
and cited manuscript are invented; ledger states cover the missing-file case. The
tampered-docx case is exercised by appending TAMPER_BYTES to a real build.
"""

RESOLVED_MD = """\
# Synthetic Widget Study

Across 24 fake cities the widget sMAPE was 33.5 and compliance reached 98.2%.

No placeholders remain in this resolved text.
"""

RESOLVED_MD_NEXT = RESOLVED_MD + """\

A second-round revision paragraph with an updated fake rate of 31.9.
"""

# Resolved slides: a title block, then one slide per level-2 heading.
SLIDES_MD = """\
---
title: Synthetic Widget Talk
---

## Counting widgets

Across 24 fake cities the widget sMAPE was 33.5.

## What changed

Compliance reached 98.2%.
"""

# A resolved web page: a title block, then two sections.
PAGE_MD = """\
---
title: Synthetic Widget Page
---

## Counting widgets

Across 24 fake cities the widget sMAPE was 33.5.

## What changed

Compliance reached 98.2%.
"""

CITED_MD = """\
# Synthetic Widget Study

Widgets were first counted by @doe2020 and later recounted [@smith2021].

# References
"""

BIB = """\
@article{doe2020,
  author  = {Doe, Jane},
  title   = {A Fake Study of Widget Counting},
  journal = {Journal of Synthetic Results},
  year    = {2020},
  volume  = {1},
  pages   = {1--10}
}

@article{smith2021,
  author  = {Smith, Alex},
  title   = {Gadget Baselines Reconsidered},
  journal = {Annals of Imaginary Data},
  year    = {2021},
  volume  = {2},
  pages   = {11--20}
}
"""

# A fake-but-well-formed sha256 for ledger rows whose file is absent.
FAKE_SHA256 = "deadbeef" * 8

# Ledger state referencing a v007.docx that does not exist on disk.
GHOST_LEDGER = """\
# Builds

| version | date | git | sha256 | purpose | baseline | reviewed |
|---|---|---|---|---|---|---|
| v007 | 2026-01-01 | - | {0} | ghost build | - | no |
""".format(FAKE_SHA256)

TAMPER_BYTES = b"tampered-after-build"


def external_row(version, sha256, purpose="externally archived submitted docx"):
    """A hand-ledgered row (e.g. v000 external archive) in contract column order."""
    return "| {0} | 2026-01-01 | - | {1} | {2} | - | no |\n".format(
        version, sha256, purpose
    )
