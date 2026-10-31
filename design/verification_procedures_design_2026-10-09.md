# Verification procedures: build spec

Draft 1, 2026-10-09. Builds on `verification_procedures/` (built and tested 2026-10-08). Decision sources: the decision log, entries dated 2026-10-08 (not public).

## Purpose

Verify AI work in a manuscript project without trusting a model to follow a procedure, and without the author having to ask for verification.

A procedural graph holds each verification standard as steps, conditions, and pitfalls. A program runs the graph. A model answers only fixed judgment questions inside it. Events in the AI harness start the procedures. Every result is a filled field with a record behind it, and the report is built from the fields.

## Decisions this spec rests on

The authors' rulings:

1. **Schema, fill, build.** Every procedure defines a schema, fills its fields, and builds its report from the field values, as simply as possible.
2. **Stable core, variable adapters.** The verification schema and report stay fixed across users and projects. The workflow components (Word or markdown, R or Python, Make or Quarto) vary with each user's preferences and tools.
3. **Verification follows AI contribution.** Work traceable to AI is checked. The author's own work is listed, not checked. A citation AI suggested is still checked after the author rewords or moves its sentence.
4. **Citation report shape.** This is locked as recorded in the decision log on 2026-10-08.
5. **Accepted until rejected.** The authors' working rule for this design thread. Checks never block the author's work. Problems show up as fields and in the report.

Proposed by Claude, and standing under rule 5 until rejected:

6. **The program is in charge.** A runtime walks the graph and decides each transition from field values. A model never chooses, skips, or adds steps.
7. **Events, not requests.** Procedures start from harness events (an AI edit, a turn ending, a matching request), from a build, or from a commit.
8. **Learning edits text only.** Live lessons may add or reword guidance and pitfalls on edges. Steps and edges change only by hand. This keeps the 2026-07-28 rule that automation may add nodes, not control flow.
9. **The 2026-10-08 builder conventions stand**:
   - data: one parameter accessor, with the parameter and model records written by the run
   - build: the six-part definition of a verified research product

## What exists (2026-10-08)

| Part | State |
|---|---|
| `verification_procedures/vg.py` | Runtime with `check`, `run`, `step`, `verify`, `score` and `advise`. Supports walking and branching, one ask per item, a retry followed by "not judged," `reads_optional`, step records, an append-only trail, and replay. |
| Four graphs | prose (7 steps), citations (19), data (9), build (8) |
| Fixtures and tests | A clean and a seeded fixture per stream. 38 tests. Recall 1.0 on recorded and live judgment. |
| Reports | One custom `report.py` per stream (77 to 161 lines). Only the finding shape is shared. |
| Harness hooks | SessionStart orientation, SessionEnd transcript capture, and a `py_compile` check after edits. None of them runs a procedure. |
| ospipe | `build` (numbered immutable builds plus ledger), `delta` (exit 4 on a blocking hit), `lineage`, `reconcile`, `returns` |

## What to build

### 1. Schemas

One file per stream, at `verification_procedures/schemas/<stream>.yaml`. It declares the item each row describes, each field's type and allowed values, whether the field is required, and which step fills it.

```yaml
stream: citations
version: 1
item: citation            # one row per item
fields:
  claim_sentence: {type: str, required: true, filled_by: extract_citations}
  origin:         {type: enum, values: [yours, ai_added, ai_reworded, ai_sourced_author_worded, unknown], filled_by: attribute_origin}
  exists:         {type: enum, values: [yes, no, not_checked], filled_by: check_existence}
  ...
report: citations         # names the report layout in schemas/reports/
```

Starting field sets, to be tightened while building:

| Stream | Item | Fields |
|---|---|---|
| Prose | change | location, kind (add, delete, move, edit), before, after, author, AI rationale, rationale honest, handoff (data, citations or none) |
| Citations | citation | claim sentence, origin, reference, exists, metadata right, passage and location, quote found, numbers found, access (full text or abstract), verdict (supports, partly, doesn't, not checked) with reason, second check, proposed fix, which copy was checked |
| Data | output (table, figure or number) | producing script, raw inputs with hashes, parameters used, model record, documentation matches code, reproduces on rerun, manuscript value matches |
| Build | research product | canonical file, sources, preferences declared, preferences present in build command, ledger row, unedited since build, rebuild matches, hard-coded results, AI writes to builds |

Every field also takes the value `not_run` with a reason. The runtime fills in `not_run` for any field whose step was skipped.

### 2. Runtime changes (`vg.py`)

- **Load and pin the schema:** the schema becomes part of the run manifest, with its hash.
- **Fields store:** add `files/fields.json`, holding rows keyed by item id. Each value carries the step that filled it and the hash of that step's record. Steps add values; a value, once filled, is never changed.
- **Contracts name fields:** contracts name the fields a step fills, as well as the files it writes. A step fails its contract if it leaves an owned field empty or fills it with a value outside the schema.
- **Judgment answers:** the schema supplies the shape of each judgment answer, and the prompt asks for exactly those fields.
- **Edge checks:** edge checks may read fields. The syntax is `field OP value`, evaluated per item. The existing `file.json:field` checks keep working.
- **Completeness:** a completeness step runs before the report. Every required field must be filled or be `not_run` with a reason.
- **Report:** one shared report builder replaces the four `report.py` files. Its sections are summary first, then problems, then one section per item group, then notes, then the trail. It reads `fields.json`, the schema's report layout, and the trail, and nothing else.

### 3. Adapters

Fill steps that read the user's files are adapters, under `implementations/<stream>/adapters/<toolset>/`. An adapter must fill the same fields as every other adapter for its stream and pass the same seeded fixture.

| Stream | Exists | To add |
|---|---|---|
| Prose | markdown versions | Word tracked changes (through ospipe `returns` and `reconcile`) |
| Citations | markdown with a YAML reference list | `.bib` from Zotero, and pandoc citekeys |
| Data | Python | R |
| Build | pandoc and Make | Quarto |

### 4. Results in the project

Each run copies its filled fields to `verification/<stream>.json` in the manuscript project. That file holds the run id, the input hashes, and the rows. It is the only link between verification and the build.

### 5. Procedure registry

There is one registry file, `verification_procedures/registry.yaml`, and adding a procedure to it makes the procedure triggerable.

```yaml
- id: citations
  graph: graphs/citations.yaml
  schema: schemas/citations.yaml
  triggers:
    phrases: [verify citations, check references, citation report]
    files: ["*.md", "references.bib", "refs.yaml"]
    builds: [manuscript]
  quick_steps: [pin_document, extract_citations, attribute_origin, match_references, check_existence]
```

`quick_steps` are the mechanical steps cheap enough to run at the end of every turn.

### 6. Triggers

All triggers are Claude Code hooks, Make targets, or git hooks, so the harness or the build tool runs them, not the model.

| Trigger | Event | Action |
|---|---|---|
| Request router | `UserPromptSubmit` | Match the prompt against the registry's `phrases`. Use keywords first, then a model fallback. On a match, add a note to the session naming the procedure and its run command. Log every match and every miss to `verification/router.jsonl`. |
| Turn check | `Stop` | Compare file hashes with the last `verification/<stream>.json`. For each stream with changed inputs, run its `quick_steps` now and queue a full run in the background. Print a one-line status. |
| Write guard | `PreToolUse` on Edit and Write | Refuse (exit 2) writes to research products and build outputs named in the build map. |
| Build | Make `verify` target, a dependency of every research product | Rerun stale streams in full. Stamp the run ids into the ospipe ledger row. Build the verification report beside the research product. Never block (decision 5); mark the research product "unverified: <stream>" when a stream is stale or has problems. |
| Commit | git `pre-commit` (optional) | Same as the turn check. Never blocks. |

### 7. Learning

A live run that produces a wrong judgment leads to a proposed pitfall or guidance edit on the edge into that step. The edit is kept only if every fixture for that stream scores no lower. Rejected edits go to `verification_procedures/rejected_edits.jsonl` so they aren't proposed again. Following decision 8, no automatic edit touches steps or edges.

### 8. Authoring guide

Add a "New procedure" section to `verification_procedures/README.md`, later promoted to a wiki entry. It gives seven steps:

1. schema
2. graph
3. adapters
4. trigger
5. register
6. test
7. learn

The worked example is an LLM evaluation run on local models, drawing on an existing LLM evaluation skill and a private wiki entry on evaluation standards.

## Acceptance

- Every existing seeded fixture still scores recall 1.0, and every clean fixture still gives 0 blocking or warning findings, with schemas and the shared report builder in place.
- Removing a step from a fixture run produces `not_run` fields and a completeness finding, not a shorter report.
- A second adapter per stream (Word, `.bib`, R, Quarto) passes the same seeded fixture as the first.
- Router: a test set of at least 20 phrasings per registered procedure, plus unrelated requests. Report the hit and miss rates, and log every miss.
- Turn check: an AI edit to a cited sentence in a scratch project triggers the citations `quick_steps` at the end of the turn, with no request.
- Write guard: an attempted Claude write to a build output is refused and logged.
- Build: a research product built after an unverified edit carries the "unverified" mark, and its ledger row names the run ids.
- Replay: every mechanical step in every run reproduces exactly.

## Build order

1. Schemas, the fields store, the completeness step, and the shared report builder. Migrate the four streams and keep the 38 tests green.
2. Results file and registry.
3. Turn check and write guard. Pilot on citations in a scratch copy of the OrgSci composite draft.
4. Make `verify` target and ledger stamping.
5. Request router.
6. Second adapters.
7. Learning loop and authoring guide, with the LLM evaluation procedure as the first new one.

## Constraints

- **Python:** 3.9 or later. No 3.10-only syntax.
- **FERPA:** hooks and the router never read, list, or send content from folders that hold student records. The router's model fallback sends only the prompt text, and skips any prompt that names one of those folders. Every subagent prompt carries this restriction.
- **Output anchoring:** all build work stays inside this workspace. Pilots run on scratch copies, never on live manuscripts.
- **Hook speed:** the turn check must finish in a few seconds. Judgment steps (the university-hosted model service) never run synchronously in a hook.
- **Coverage:** hooks only see Claude Code sessions. AI work done elsewhere is caught at build time by hash comparison.

## Open

- **Where the registry lives:** the knowledge store is deliberately left open in spec 0.7, and the registry may belong there.
- **Router model:** which model to use as the fallback, and its cost per prompt.
- **Field sets:** the starting field sets above are Claude's drafts from the existing reports and need the authors' review.
- **Real-paper test:** the first run on a real manuscript is still to come; all fixtures are synthetic.

## System fit

The system sits around the AI harness (Claude Code) rather than inside the model. It doesn't trust what the model reports. It records what happened, checks the AI's work, and links every output back to its sources.

**Verification: checks the AI's work**
- **What it does:** checks work traceable to AI before it reaches a research product. Your own work carries your warrant and is listed but not checked.
- **How:**
  - **Attribution decides what gets checked.** Word compare, a word diff between saved versions, and citation origin labels separate AI changes from yours.
  - **A procedural graph per stream runs the checks.** Code does the mechanical steps, one model answers each fixed judgment question, and a second model rechecks what gets flagged.
  - **The report is built from fields.** Findings fill the schema, and the report is generated from it.

**Observability: shows what happened**
- **What it does:** lets anyone see every step of a check and every AI session afterwards.
- **How:**
  - **Step records:** each step saves what it read, the code or prompt it used, the model's answer and what it produced.
  - **Trail:** an append-only log of every step that ran or was skipped, and why.
  - **Empty fields:** a check that didn't run shows up as a gap rather than disappearing.
  - **Sessions:** a session store saves every Claude Code transcript automatically when a session ends.

**Traceability: links outputs back to sources**
- **What it does:** follows any number, citation or research product back to where it came from.
- **How:**
  - **Hashes:** every input to every step and every build is fingerprinted, so a changed file is detected.
  - **Numbers file:** the manuscript uses placeholders like `{{num:key}}` instead of typed numbers. Each one resolves to a value and to the code that produced it.
  - **Build ledger:** one row per build, recording what went into it.
  - **`lineage` command:** one read-only command that walks any output's lineage across these records.
  - **Replay:** reruns the recorded code and must reproduce the same outputs.

**Harness connection: where it plugs into Claude Code**
- **Built:** a session-start hook gives each session its project orientation, and a session-end hook saves the transcript.
- **Designed, not built:**
  - an end-of-turn hook that runs verification on whatever changed
  - a hook that blocks AI writes to research products
  - a prompt hook that matches your request to a procedure and starts it

**In short:** the harness does the work, hooks capture it, the graphs check it, and hashes plus records let anyone follow an output back to its source. The model never vouches for itself.
