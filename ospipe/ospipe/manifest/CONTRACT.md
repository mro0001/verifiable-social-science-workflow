# manifest Contract

Purpose. The manifest emitter. Writes each value in the numbers file from the analysis outputs, so the numbers a research product cites come from the analysis and not from typing.

## Produces

- `emit_manifest(manifest_path, outputs_dir=None) -> EmitResult(changed, unchanged)`
  - The file must hold one top-level `numbers:` mapping, the data procedure's shape. Each entry is `{value, from, field, where}`.
  - For each entry the emitter reads the file `from` names under `outputs_dir`, by default the manifest's folder.
  - A `.json` file is walked along `field` split on dots, through objects by name and lists by position.
  - Any other file is read as CSV. `field` is a column of the one row whose cells equal every `where` pair, compared as text.
  - The value becomes a display string. Text is kept as it is, and a whole or decimal number goes through `str()`. True, false, null, a list, or an object is refused.
  - `changed` lists `(key, old, new)` in the file's order, with `old` as `None` for an entry that has no value yet. `unchanged` lists the other keys.
- `ManifestEmitError(ValueError)` with `.problems`, the list of every problem.
  - The problems are a file that is not the `numbers:` shape, an entry without `from` or `field`, a missing output file, a missing field or column, zero or several matching rows, and a refused value. Every one is collected and raised once, and the file is not touched.
- The rewrite. When a value changed, the file is written as its leading comment and blank lines unchanged, then `numbers:`, then one line per entry in the original order, `  <key>: {value: "...", from: "...", field: "..."}`, with `where` and any other fields after. Each value is written JSON-style in double quotes, and each key so that it loads back as the same text. When nothing changed, the file is left byte for byte.
- `python3 -m ospipe emit-manifest`, in the root contract.

## Frozen

- The fields read, `from`, `field`, and `where`, and the value written to `value`.
- The lookup rules, the ones the data procedure's numbers check uses. A dotted path through a JSON file, objects by name and lists by position. One CSV row matched on every `where` pair as text.
- The refusal lists every problem at once and leaves the file as it was.
- Values are written as strings that the build reads unchanged through `foundation.load_manifest`. The emitter formats nothing beyond `str()` of a number. Display formatting belongs in the analysis script.

## Soft

- Problem wording, the order of fields after `where`, how a field other than the four is written (JSON-style), and how a key is quoted.
- As built. A `where` that is not a mapping, and an output file that cannot be parsed, are reported as problems too. An entry whose value is already the same text, or a number whose `str()` is that text, counts as unchanged. Comments inside the `numbers:` mapping are not kept by a rewrite.

## Consumers

- root (`python3 -m ospipe emit-manifest`), called after the analysis scripts run.
- The build and the data procedure read the file it writes, the build through `foundation.load_manifest` and the data procedure through its own numbers check.

## Fixture

- `fixture.py`. Synthetic outputs (a JSON results file and a CSV table), a numbers manifest whose values match them, and a manifest holding one entry for each problem kind.
- `tests/test_manifest_emit.py` also runs the emitter on a temporary copy of `examples/sample_project/`.

## Status

- realized

## Not in this module

- The emitter does not run the analysis, does not touch the overlay, and does not compare values with a rerun. The data procedure does that.
