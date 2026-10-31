# foundation Contract

Purpose. The shared vocabulary every ospipe node imports. Placeholder grammar, manifest loading, shared errors.

## Produces

- `PLACEHOLDER` — compiled regex matching exactly `{{num:<key>}}` and `{{table:<key>}}` where `<key>` is `[A-Za-z0-9_.\-]+`. Group 1 is the kind (`num` | `table`), group 2 the key.
- `SUSPECT` — compiled regex matching `{{<word>:` — any placeholder-shaped remnant, used to catch typos after substitution.
- `load_manifest(path, overlay_path=None) -> Dict[str, str]` — loads a YAML mapping; if overlay_path exists, merges it. Overlay may only ADD keys; a key present in both raises `ManifestError`. All values are returned as strings. Either file may also take the data procedure's numbers.yml shape, a single top-level `numbers:` mapping whose entries are `{value, from, field, where}`; only each entry's `value` is read, and an entry without one raises `ManifestError` (added 2026-10-27, so one file feeds both the build and the data procedure).
- `ManifestError(ValueError)` — bad manifest shape or overlay collision.
- `MissingKeyError(KeyError)` — carries `.keys`, the sorted list of every missing key (never just the first).

## Frozen

- The two regexes, their group structure, and the key character class.
- Manifest values are display-formatted STRINGS. Consumers never format numbers. Scalars are coerced with `str()`; authors must quote values whose display differs from `str()` of the YAML scalar (`"33.50"`, `"0.050"`).
- Overlay adds, never overrides. Collision is an error, not a silent win.
- `MissingKeyError.keys` reports ALL missing keys in one failure.

## Soft

- YAML parsing details, error message wording.

## Consumers

- resolve, root, and replication (the placeholder grammar, to find a source's tables). Every node in the tree loads foundation.

## Fixture

- `fixture.py` — synthetic manifest YAML, overlay YAML, and a sample manuscript snippet (fake values, real shape: dotted keys, percent strings, code fence).

## Status

- realized
