# resolve Contract

Purpose. Substitute manifest values and table includes into canonical markdown. The hard gate that makes stale numerals impossible in builds.

## Produces

- `resolve(text: str, manifest: Mapping[str, str], tables: Mapping[str, str]) -> str`
  - Substitutes `{{table:<key>}}` FIRST (tables may themselves contain `{{num:}}` placeholders), then `{{num:<key>}}`.
  - A table substitution is surrounded by blank lines in the output (exactly one blank line before and after, collapsing any it already has).
  - Raises `MissingKeyError` listing ALL missing keys across both kinds in one exception.
  - Inside inline code or a fenced code block, as pandoc reads them, a `{{num:<key>}}` whose key the manifest holds is filled, and any other placeholder is left as written, so an example such as `{{num:key}}` stays an example. Code is never counted for missing keys and never scanned. Outside code a missing key still stops the build, with every missing key listed. Inline code is set aside only where reading its backticks line by line and up to the blank line give the same spans, outside a simple, multiline or grid table, and away from an autolink, HTML tag, link target, math or TeX command that holds a backtick. Everywhere else the placeholder is filled, the safe way to err, so one in a code span that runs across lines is filled too.
  - Known gaps. The reading is checked against pandoc 3.9, not pandoc itself. A placeholder in an indented code block is filled. A backtick inside other pandoc syntax not named above could still change how backticks pair.
  - After substitution, if `foundation.SUSPECT` matches anywhere OUTSIDE code, raises `ResolveError` naming the line number and remnant (catches typos like `{{numb:x}}` and half-deleted placeholders).
- `ResolveError(ValueError)` — carries `.line` (1-indexed) and `.remnant`.

## Frozen

- The signature, the substitution order, the all-missing-keys-in-one-failure rule, and the code rule. Inside inline code and fenced code blocks (``` or ~~~), found by pandoc's rules, only a number placeholder whose key the manifest holds is filled, and the remnant scan skips them (Track L, Step L6, and Track Q, Step Q3).
- resolve never formats values. What the manifest string says is what lands.

## Soft

- Blank-line normalization details, error message wording, internal parsing strategy.

## Consumers

- root (the check path). Later: build.

## Fixture

- `fixture.py` — reuses foundation's SAMPLE_MD and SAMPLE_TABLE, plus edge cases (placeholder at start of file, two placeholders on one line, table containing a num placeholder, remnant typo `{{numb:x}}`, fence containing `{{` that must survive untouched).

## Status

- realized
