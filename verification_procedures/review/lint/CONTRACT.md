# lint Contract

Purpose. Detect literal-number creep in canonical markdown. Advisory findings, never a hard gate; policy on findings belongs to the caller.

## Produces

- `lint(text: str, allowlist: Collection[str] = ()) -> List[Finding]`
- `Finding` — NamedTuple `(line: int, token: str, context: str)`; `line` 1-indexed, `context` the stripped source line.
- A finding is any bare numeral token in prose. NOT flagged:
  - anything inside fenced code blocks or inline code spans
  - four-digit years 1900 to 2099
  - numbers inside `{{num:...}}` placeholders (they are the fix, not the disease)
  - markdown list markers (`1.`), heading numbers, and table separator rows
  - tokens exactly matching an allowlist string (the caller passes tracker-registered literature constants)
  - citation years in parentheses, e.g. `(Chung et al. 2025)`

## Frozen

- The signature and the Finding shape.
- The six not-flagged categories above. Removing one is a contract change; adding heuristics is SOFT.
- lint never mutates text and never raises on content (only on non-str input).

## Soft

- The numeral-token regex, context-window details, additional suppression heuristics.

## Placeholder pattern

- `linter.py` keeps its own copy of the placeholder pattern, `PLACEHOLDER`, since layers never import each other's code. Group 1 is the kind (`num` or `table`) and group 2 the key, `[A-Za-z0-9_.\-]+`.
- The pattern copies the grammar frozen in `ospipe/ospipe/foundation/CONTRACT.md`. A change there needs the same change here.

## Consumers

- The `review lint` command, run as `python3 -m review lint` from `verification_procedures/`.

## Fixture

- `fixture.py` — synthetic prose with: a bare percentage (must flag), a year (must not), an allowlisted constant (must not), a numeral in a fence (must not), a numeral in an inline code span (must not), a placeholder (must not), a citation year (must not), a numbered list (must not).

## Status

- realized
- Moved from `ospipe` into the verification layer on 2026-10-29.
