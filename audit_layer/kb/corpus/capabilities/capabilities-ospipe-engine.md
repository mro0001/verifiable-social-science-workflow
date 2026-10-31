---
id: capabilities-ospipe-engine
title: The ospipe engine
source: ospipe/CONTRACT.md
source_commit: sha256:02739281c7fc
updated: 2026-10-30
group: CAPABILITIES
---

# The ospipe engine

ospipe is the reproducible pipeline that turns a canonical markdown source file plus a numbers manifest into checked, numbered builds. It is invoked as python3 -m ospipe followed by a command, and its modules meet only in its composition root.

Its commands do four kinds of work.

1. The check command resolves every placeholder in the source from the numbers manifest, or fails while listing every missing key. Resolving is the hard gate, so nothing downstream sees unresolved text.
2. The build command runs the check and then writes the next numbered immutable build, a Word document, reveal.js slides, or a web page, with a copy of its resolved text and a row in the BUILDS.md ledger that records which verification streams are still unverified. It refuses to build over a corrupted archive. The rebuild command rebuilds a ledgered version from its snapshot and reports whether the checksums match.
3. The emit-manifest command fills each value in the numbers manifest from the analysis outputs. The products, add-product, and archive commands read and write the project's build file, one Makefile rule per research product, and mark older drafts as archived. The install-notes command copies the notes templates into a project.
4. The unverified and citation-evidence commands write what verification found and left open. The emit command writes a product's replication folder, which rebuilds the shipped build on its own.

The Word review tools are not part of ospipe. Extracting the author's tracked edits and margin comments from a reviewed Word document, reconciling a return against the build lineage, adding margin comments, the bare-numeral linter, and the Word compare script live in the verification layer's review package, verification_procedures/review, run as python3 -m review followed by a command.

## Consult also

- formats-numbers-manifest - for the placeholder grammar the resolver matches on.
- loop-compare-and-return - for the full compare and return procedure around build and review.
