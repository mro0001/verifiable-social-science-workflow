# Build verification

Build verification asks one question: is every deliverable a product of the build, and only of the build? It is the deliverable-side form of "results come from a process, not typed in". Five witnesses, all mechanical: the map (Makefile) names one canonical file per deliverable and nothing else claims to be it; every preference in build_prefs.yaml is carried by the map's command and shows in the build; every build on disk matches its ledger row; rebuilding from the frozen snapshot with the map's command reproduces the ledgered bytes; and results enter through {{num:key}} placeholders while the session record shows no AI write to a build. No model judges anything here.

## Summary

- Blocking: 0
- Warnings: 0
- Notes: 3

## Problems

None.

## Deliverables

| Deliverable | Canonical source | Builds | Ledger ok | Rebuild matches | Prefs integrated |
|---|---|---|---|---|---|
| paper | paper/paper.md | v001, v002 | 2/2 | 2/2 | all 6 |
| slides | slides/slides.md | v001 | 1/1 | 1/1 | all 3 |

Look-alikes: 1 found, 0 without an ARCHIVE line.

## Builds

| Build | Date | Purpose | File matches ledger | Snapshot matches ledger | Rebuild matches ledger | Snapshot re-resolved from canonical |
|---|---|---|---|---|---|---|
| builds/paper/v001.html | 2026-09-21 | first full draft | yes | yes | yes | no (canonical moved on) |
| builds/paper/v002.html | 2026-09-28 | limitations added | yes | yes | yes | yes |
| builds/slides/v001.html | 2026-09-29 | district association talk | yes | yes | yes | yes |

Rebuilt with pandoc 3.9.0.2.

## What was checked

- **read_map**: the Makefile map; one canonical per deliverable; look-alikes need an ARCHIVE line.
- **check_ledger**: every file in each builds dir against BUILDS.md (sha256 of build and snapshot).
- **check_prefs**: build_prefs.yaml against each deliverable's pandoc command, then against its latest build.
- **rebuild**: the map's command re-run on each frozen snapshot; the bytes must equal the ledger's sha256. The snapshot is re-resolved from the canonical when neither has moved on.
- **check_hardcoding**: canonical sources for bare numerals and unresolved placeholders.
- **check_ai_touch**: session_writes.jsonl for AI writes into builds dirs or ship/.

## Notes

- check_ai_touch / canonical sources: 3 AI write(s) to canonical sources; that is where AI works.
- read_map / drafts/paper_2026-09.md: Archived look-alike, correctly bannered.
- rebuild / builds/paper/v001.html: Canonical or numbers changed since this build; the rebuild starts from the frozen snapshot.
