# ospipe Modules

One-screen manifest of the reproducible pipeline's modules. Statuses: realized = built and wired. stubbed = contract only. isolation-only = built, nothing consumes it yet.

| Module | Path | What it is | Contract | Status |
|---|---|---|---|---|
| foundation | `ospipe/foundation/` | Shared vocabulary: placeholder grammar, manifest loading, errors | `ospipe/foundation/CONTRACT.md` | realized |
| resolve | `ospipe/resolve/` | Manifest and table substitution, the hard gate | `ospipe/resolve/CONTRACT.md` | realized |
| build | `ospipe/build/` | Numbered immutable builds (docx, reveal.js slides, or a web page) plus ledger | `ospipe/build/CONTRACT.md` | realized |
| manifest | `ospipe/manifest/` | Manifest emitter, fills each value in `numbers.yml` from the analysis outputs | `ospipe/manifest/CONTRACT.md` | realized |
| layout | `ospipe/layout/` | The project's build file, one Makefile rule per research product, each naming its one source file, and archive lines for older drafts | `ospipe/layout/CONTRACT.md` | realized |
| notes_templates | `ospipe/notes_templates/` | Installs the notes templates from `templates/notes/` into a project's `notes/`, never overwriting a file | `ospipe/notes_templates/CONTRACT.md` | realized |
| evidence | `ospipe/evidence/` | The list of unverified claims and the citation evidence file, read from the project's results files and citation log by the build's own rule | `ospipe/evidence/CONTRACT.md` | realized |
| replication | `ospipe/replication/` | What a research product depends on, read from the build file, the source, and the project's analysis declarations, and the replication folder `ship/<product>/` written from it, with its own Makefile and README, which rebuilds the shipped build on its own | `ospipe/replication/CONTRACT.md` | realized |
| root | `ospipe/root/` | Composition root plus `python3 -m ospipe` CLI | `ospipe/root/CONTRACT.md` | realized |

`lint`, `annotate`, `returns`, `reconcile`, and the Word compare script moved to the verification layer's review package (`verification_procedures/review/`), and `kb` to `audit_layer/kb`.

## Laws

- Depend only toward more-frozen modules. foundation is loaded at every node.
- FROZEN promises are what consumers depend on: names, signatures, grammar, ordering rules. SOFT is everything internal.
- Real manuscript data never enters a fixture, a test, or an LLM prompt from this tree.

## Adding a module

Contract first (FROZEN/SOFT split), synthetic fixture, leaf rule (fits one focused session, no internal seam worth its own contract), three checks (leaf on fixture, real-shape per FROZEN clause, parent composition), register a row here, reconcile when done.
