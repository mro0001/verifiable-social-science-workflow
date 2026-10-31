# File Protocol

Draft 1.0, 2026-09-18. Shape approved by the authors on 2026-09-18 from the plain summary in chat. Companion to `MANUSCRIPT_WORKFLOW.md` draft 0.7; where the two meet, the spec's law and custody rules govern. The evidence behind the choices (six candidate designs, five judges, three refuters, one repair) is in working notes that are not public.

## The protocol in one picture

```
   MESS                    MAP                       SHIP
   any files, anywhere  →  one short file that   →  a clean folder with only
   for as long as you      says "this is the        what the paper needs;
   like                    paper, build it so"      builds on its own
```

The protocol fixes no folder name. It adds one file (the map) when you want a document and one folder (`ship/`) when you submit. Nothing is ever moved.

## 1. The mess

A project starts as a folder with a `CLAUDE.md` and, from the first note, a `notes/` folder. That is the whole scaffold.

Put anything anywhere, under any name. Never organize it. Dead ends stay where they fell. Git keeps every version. Sessions are recorded automatically.

Two rules, both about protecting what cannot be regenerated:

- Raw data and downloaded PDFs are never edited or deleted. Raw means what no script can regenerate. If a raw file must change, the old copy is set aside with a date and the path the scripts read stays current.
- Everything else may be moved, renamed, or deleted at will.

## 2. The map

The day you want to see a document, you pick which draft is the paper and add one entry to a map file at the root (a Makefile): this file is the paper; build it like this.

From then on:

- Builds are numbered and never edited. Each is a row in the ledger, `builds/BUILDS.md`. A docx sent to anyone is a build first.
- Numbers in the text pull from the numbers file (`{{num:key}}` from `numbers.yml`), citations use citekeys, exhibits come from one generated set. This can wait until you ship; drafts owe nothing.
- Any old draft that reads as the paper gets one line at the top (after any front matter): `> ARCHIVE <date>: superseded by <path>`.

The map is the only structure the protocol ever adds. For each research product it names the one canonical file, its template, and where its builds go. Nothing else is fixed; a canonical file may sit anywhere, including the root.

Want slides too? One more entry in the map and one slides file. Same numbers file, same bibliography, same exhibits; the build tool renders a different output. Retiring a research product removes its entry; its builds stay.

## 3. The ship

When you submit, the system works out what the paper actually depends on: its text, the scripts that made its numbers, the raw those scripts read, the cited references, the template. It copies exactly those into `ship/paper/`. That folder builds by itself with the workspace and the database unreachable. Its README lists what is in it, how it was built, and any AI-written claim that lacks a witness.

That folder is the replication package. It is never edited; fix the working folder and ship again. Everything not in it stays in the mess and owes nothing.

Ship as often as you like; each ship is a tag. The one that goes to the journal is the one that pays the full reproducibility tax.

## The four streams

| Stream | In the mess | In the ship |
|---|---|---|
| References | Zotero holds the citekeys. Downloaded PDFs are never edited. | The cited entries, plus the witness for each AI-cited claim (spec, Goal 3). |
| Data | Raw is never edited. Scripts and derived files live anywhere. One numbers file binds text to scripts. | Raw, the scripts that made shipped numbers, the numbers file trimmed to used keys, the exhibits. |
| Prose | Chat drafts anywhere. One canonical file per research product once you pick it. Hand edits come back as Word tracked changes on a numbered build. | The canonical file at the tag, and the builds that matter: the journal's copy, the baseline, the shipped build, the returns. |
| Structural build | The map and the build tool. | A one-entry map, the tool vendored, the template. |

## Adoption: a paper in revision today

Four moves, three today. No file moves; no folder is renamed.

1. `git init` the folder and commit everything (a `.gitignore` for secrets, environments, and Word lock files).
2. Write the map: two entries, paper and response letter. The paper entry wraps the ospipe line already in `CLAUDE.md`. The response entry names the draft the authors pick and the existing change map as its response map.
3. One ARCHIVE line at the top of the four old drafts that read as the paper (`draft_a.md`, `draft_b.md`, `draft_c.md`, the unchosen response candidate). The AI does this.
4. At resubmission, build `ship/paper/`. By hand the first time; see the engine details.

## What stays free

- Every folder name and depth. `manuscript/`, `analysis/`, `builds/` are ospipe defaults, not rules.
- Where scratch goes and what it is called. No date prefixes. Spaces allowed.
- Skill bundles (`manuscript_sessions/`, `scholar_session_*/`): the skill owns the shape.
- Code layout and language. Derived data and extractions anywhere.
- How many research products, when builds are cut, how often you ship, what is withheld at ship.
- What `notes/` contains; what `CLAUDE.md` says beyond the anchor.

## Open questions

1. Replication remote: push `ship/paper/` as a subtree of the paper's repo, or as its own repo.
2. Citations at resubmission: `refs.bib` from Zotero (citeproc regenerates References), or literal citations with the claim record as the only witness.
3. Private remote: at submission (the spec's appendix) or at the first commit, now that git holds the raw.

---

## Engine details

For the AI and the engine, not for daily use. How the protocol is realized today, and what is still owed.

**Rules, stated for the machine.**

1. One root: one folder at the workspace root, its own git repo, everything committed. `notes/` is stamped from `templates/notes/` at the first note.
2. Working files are scratch. Provenance is stamped in the stores at the crossing, never as a file in the folder. Until the Working store snapshots content, git is the binding: delete means `git rm`.
3. Raw, retrieved originals, and session logs are immutable in place. Raw = what no deterministic script regenerates (in the example paper: `data/raw/responses.jsonl`, not the CSVs that `export_data.py` writes). Session logs are the swept transcripts, never a folder file. Until the Data store binds, the folder copy of raw is custodial.
4. A research product = one canonical file + one Makefile rule + one ledger. The rule commits, then builds under `SOURCE_DATE_EPOCH` taken from the commit time, so the ledger's git hash holds the canonical and the docx hash reproduces. A look-alike (a file at the root or beside the canonical that reads as the research product) is a build or carries the ARCHIVE line, placed after any front matter.
5. Every target reads `{{num:key}}` from `numbers.yml`, citekeys from `refs.bib`, exhibits from one set. Binding is enforced at ship: `make emit` runs lint strict and refuses a bare numeral outside the allowlist. The bib is optional until it exists: `$(if $(BIB),--bib $(BIB))`.
6. `make emit D=<d>` has trace compute the closure and writes `ship/<d>/`: inputs at their working paths, ospipe vendored, a one-rule Makefile, a generated README. It refuses a closure script holding an absolute path. Gate: `make` in a fresh clone of the tag reproduces the ledger row's sha256; the rule compares digests and never cuts a build.

**Bindings today.** ospipe supplies `check`, `build`, `returns`, `delta`, `lineage`, `reconcile`, `annotate`. `--builds-dir` gives each research product its own ledger with no engine change. Word Compare is the prose witness; a return is `builds/returns/vNNN_<who>.docx`, reconciled against that build, ported one delta at a time with a port-only build after each. A directory output (a dashboard) is ledgered as a tarball's sha256.

**Owed, in order of need.**

1. `emit`: compute the closure with trace, copy, vendor, generate the README, project the Makefile. Until it lands, the first ship is by hand: key the shipped numbers, make script paths relative, copy what `trace build:vNNN` lists plus the run logs and the parser, vendor ospipe, run `make` from a fresh clone of the tag. Fix failures in the working folder, never in `ship/`. This hand run is also deletion test 2.
2. `--to revealjs` with a file column in the ledger, so slides ledger like the paper. Until then a slides rule runs `check`, then pandoc, unledgered.
3. trace reads the Makefile's variables and walks key → defining script → raw. Until then the ship README says "closure hand-chosen".
4. The citation witness file in `ship/` (quote, location, settled-by per AI-cited claim). Its shape belongs to the reference process design, deferred in the decision log on 2026-07-23. The requirement stands (spec, Goal 3); the file is not named here.

**Deltas from the spec's appendix.** "Commits by explicit path" becomes commit everything behind a `.gitignore`, because git is now the scratch binding. Private-remote timing is open question 3. The rest of the appendix stands.

**A map entry, for reference.** The paper rule wraps the existing ospipe line; the slides rule differs only in renderer, template, and builds directory.

```make
slides: slides/slides.md slides/template.html $(MANIFEST)
	git add -A && git commit -qm "build: $(PURPOSE)" || true
	SOURCE_DATE_EPOCH=$$(git log -1 --format=%ct) $(OSPIPE) build --manuscript $< --manifest $(MANIFEST) \
	  --allowlist $(ALLOW) --to revealjs --template slides/template.html --builds-dir builds/slides --purpose "$(PURPOSE)"
```

**Trees, compact.** The annotated full trees are in working notes that are not public.

The example paper after adoption. Everything already there stays put.

```
my_paper/
├── Makefile              NEW: paper, response (later: slides, emit)
├── CLAUDE.md             exists; pipeline paragraph becomes one line pointing at the map
├── manuscript/manuscript.md          canonical paper (already)
├── analysis/numbers.yml              the numbers file ({} today; keyed before the first ship)
├── builds/                           paper ledger and builds (already); builds/response/ appears at the first response build
├── data/raw/responses.jsonl          raw, never edited
├── ... forty other items ...         untouched; four drafts get an ARCHIVE line
└── ship/                             absent until resubmission
```

The paper's ship folder.

```
ship/paper/
├── README.md             generated: contents, how to build, tool versions, lineage, unverified AI claims, what is withheld
├── Makefile              one rule
├── tools/ospipe/         vendored
├── manuscript/           manuscript.md at the tag, reference.docx
├── analysis/numbers.yml  used keys only
├── data/raw/             responses.jsonl and the parser, at their working paths
├── reproducibility/      the scripts that made shipped numbers, the chosen data cache, a codebook
├── tables/               the exhibits
├── refs.bib              cited entries only (absent while citations are literal; open question 2)
└── builds/               BUILDS.md rows that ship: the journal's copy, the baseline, the shipped build, the returns
```

The slide deck's delta.

```
my_paper/
├── Makefile              +1 entry: slides
├── slides/slides.md      NEW canonical, seeded from manuscript.md; slides/template.html
├── builds/slides/        own ledger and builds
└── ship/slides/          small: the deck, its keys, its figures; README lineage points at ship/paper's tag
```
