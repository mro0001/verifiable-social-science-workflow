# Build verification

Build verification asks one question: is every deliverable a product of the build, and only of the build? It is the deliverable-side form of "results come from a process, not typed in". Five witnesses, all mechanical: the map (Makefile) names one canonical file per deliverable and nothing else claims to be it; every preference in build_prefs.yaml is carried by the map's command and shows in the build; every build on disk matches its ledger row; rebuilding from the frozen snapshot with the map's command reproduces the ledgered bytes; and results enter through {{num:key}} placeholders while the session record shows no AI write to a build. No model judges anything here.

## Summary

- Blocking: 6
- Warnings: 1
- Notes: 5

## Problems

| Severity | Check | Item | Problem | Evidence |
|---|---|---|---|---|
| blocking | check_ai_touch | builds/slides/v001.html | AI touched the deliverable directly; only the map's build rule may write here. | session s-0104, ai via Edit |
| blocking | check_hardcoding | paper/paper.md:0.31 | Hard-coded result: equals numbers.yml key 'effect_monthly'; use {{num:effect_monthly}} so it moves with the data. | line 16: Districts that met monthly reported higher learning scores than districts that met quarterly (standardized difference 0… |
| blocking | check_hardcoding | slides/slides.md:{{num:n_teams}} | Placeholder with no value in numbers.yml; the build will refuse, by design. | n_teams |
| blocking | check_ledger | builds/paper/v001.html | Deliverable edited after build: its sha256 no longer matches the ledger. | ledger 07f6f1debcdd..., file a239813c9e1b... |
| blocking | check_prefs | slides:number_sections | Preference not integrated: the author declared it but the map's command for slides does not carry it. | number_sections: true; needs --number-sections |
| blocking | rebuild | builds/paper/v002.html | Deliverable not derived from the build: same snapshot, same command, same pandoc, different bytes (direct edit). | build has, rebuild lacks: <p>Monthly meetings clearly cause better learning.</p> |
| warning | read_map | drafts/paper_full.md | Competing canonical: this file reads as paper/paper.md (same title as the canonical) and has no ARCHIVE line. | add '> ARCHIVE <date>: superseded by paper/paper.md' after the front matter |

## Deliverables

| Deliverable | Canonical source | Builds | Ledger ok | Rebuild matches | Prefs integrated |
|---|---|---|---|---|---|
| paper | paper/paper.md | v001, v002 | **1/2** | **1/2** | all 6 |
| slides | slides/slides.md | v001 | 1/1 | 1/1 | **missing: number_sections** |

Look-alikes: 2 found, 1 without an ARCHIVE line.

## Builds

| Build | Date | Purpose | File matches ledger | Snapshot matches ledger | Rebuild matches ledger | Snapshot re-resolved from canonical |
|---|---|---|---|---|---|---|
| builds/paper/v001.html | 2026-09-21 | first full draft | **no** | yes | yes | no (canonical moved on) |
| builds/paper/v002.html | 2026-09-28 | limitations added | yes | yes | **no** | no (canonical moved on) |
| builds/slides/v001.html | 2026-09-29 | district association talk | yes | yes | yes | no (canonical moved on) |

Rebuilt with pandoc 3.9.0.2.

## What was checked

- **read_map**: the Makefile map; one canonical per deliverable; look-alikes need an ARCHIVE line.
- **check_ledger**: every file in each builds dir against BUILDS.md (sha256 of build and snapshot).
- **check_prefs**: build_prefs.yaml against each deliverable's pandoc command, then against its latest build.
- **rebuild**: the map's command re-run on each frozen snapshot; the bytes must equal the ledger's sha256. The snapshot is re-resolved from the canonical when neither has moved on.
- **check_hardcoding**: canonical sources for bare numerals and unresolved placeholders.
- **check_ai_touch**: session_writes.jsonl for AI writes into builds dirs or ship/.

## Notes

- check_ai_touch / canonical sources: 4 AI write(s) to canonical sources; that is where AI works.
- read_map / drafts/paper_2026-09.md: Archived look-alike, correctly bannered.
- rebuild / builds/paper/v001.html: Canonical or numbers changed since this build; the rebuild starts from the frozen snapshot.
- rebuild / builds/paper/v002.html: Canonical or numbers changed since this build; the rebuild starts from the frozen snapshot.
- rebuild / builds/slides/v001.html: Canonical or numbers changed since this build; the rebuild starts from the frozen snapshot.
