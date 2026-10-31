---
id: formats-numbers-manifest
title: The numbers manifest standard
source: MANUSCRIPT_WORKFLOW.md
source_commit: sha256:4f5317e8258d
updated: 2026-07-23
group: FORMATS
---

# The numbers manifest standard

Computed values never sit as literal numerals in canonical manuscript text. Each appears as a placeholder that the build resolves from the numbers manifest (numbers.yml), so a data rerun reaches every deliverable by rebuild instead of rotting inside prose, and a build that cannot supply a value fails instead of shipping.

Placeholder grammar: `{{num:key}}` substitutes a single value and `{{table:key}}` substitutes a generated exhibit. A key may contain only ASCII letters, digits, underscores, dots, and hyphens; spaces and slashes are outside the grammar.

Two files feed the resolver. The pipeline emits the numbers manifest (numbers.yml), and a hand-edited overlay file holds quick manual additions. The overlay adds keys and never overrides them; a key present in both files is a build error, not a silent win for either side.

Manifest values are display-formatted strings, such as "33.50", "0.050", or "98.2%". The resolver substitutes text verbatim and formats nothing, so a value whose display would lose precision as a bare scalar, "0.050" for example, must be written as a quoted string in the manifest.

A build with any placeholder key missing from the merged manifest fails, and the failure reports every missing key at once rather than only the first.

A linter flags bare numerals in canonical text so no quantity can bypass the manifest. Two classes are allowlisted: years, and literature constants already registered in the claim tracker (the record of numbers taken verbatim from sources, with the passage and page for each).

## Consult also

- loop-compare-and-return — for how resolved builds reach the author and why a returned edit that touches a number becomes a question.
