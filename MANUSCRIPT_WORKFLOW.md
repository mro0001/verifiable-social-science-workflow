# A Reproducible, Verifiable Research Pipeline

The status tables of the proposal's technical appendix give the current state of each part, and the dated status sections below are kept as history.

Draft 0.10, 2026-10-22 (later the same day). Components and layers brought in line with the final proposal Figures 1 to 3; changelog at the end. Draft 0.9, 2026-10-22. Terminology brought in line with the proposal draft of 2026-10-22; changelog at the end. Draft 0.8, 2026-10-09, brought in line with the Organization Science Stage 1 proposal draft of 2026-10-09 and the verification procedures spec (`design/verification_procedures_design_2026-10-09.md`). Draft 0.7 (2026-08-10) fixed the store shapes and scoped verification to provenance per the rulings of 2026-08-05; changelog at the end. Evidence behind design choices is archived in working notes, and rulings live in the decision log. Neither is public.

## The law

Preserve the irreplaceable, derive everything else, and show each reader only what they came for.

1. **Three irreplaceables.** Raw data, sources, session logs. Observations that cannot be regenerated. Preserved without exception; nothing else has to be.
2. **Two regimes.** Analysis replays from raw. Writing traces its commitments.
3. **One tax.** Only the shipped build's lineage pays for reproducibility.
4. **One reader rule.** No named reader, no record. Governs generated research products, never stores.
5. **One ladder.** Record, standard, template. Knowledge climbs until it applies itself.

Everything else is a binding.

(Adopted 2026-08-04 from the recovered statement of an earlier session, amended twice: line 1 states a preservation duty rather than a cap on what may persist, and line 4 carries the scope fix from a framing review whose notes are not public, where the rule was refuted as a claim about stores and holds for generated deliverables.)

## A project's life

A project begins as an idea, not a structure. From day zero exactly one discipline is on: **capture**. Sessions are logged automatically, and anything made or fetched lands in the stores as the work happens. There is no scaffold to fill in and no filing duty; a project exists because work tagged to it starts accruing.

The middle is messy on purpose. The three streams of a project's labor — data work, literature research, prose — run interleaved and undisciplined. Workspace files are scratch: they can be moved, renamed, or deleted and nothing breaks, because the workspace was never the record. What persists is the boundary crossings: collected data, retrieved sources, scripts, notes, and drafts land in the stores with provenance stamped at write time. Dead ends cost nothing and are never cleaned up.

The turn comes when the argument firms and the question flips from *what might matter* to *what does the paper rely on*. Every empirical claim in the draft resolves to one of two things: something read, or something ran.

At ship, the **surviving file structure is emitted**: the lineage closure of the intended research product is computed by the `lineage` command, not chosen by judgment, and the stores materialize it as a plain-text repository — raw data, scripts, references, canonical manuscript, and the records binding numbers to scripts and claims to sources. The clean repository is an output of the workflow, not its precondition. Everything not selected stays in the stores: kept, findable, owing nothing.

Builds are cut throughout a project's life, so emission is not a single end event; the structure can be emitted whenever a build needs it. The working understanding, deliberately not yet a hard rule, is that the shipped emission is the one that pays the full tax.

The emitted structure then proves itself (goal 3), and the pipeline builds the research product from the structure alone. The replication package is not assembled; it *is* the surviving structure, already self-contained. Afterward the project pays forward: its sources and data remain pullable by future projects, and procedures that proved out climb the ladder.

## Custody

Authority is held by phase, not by container. Every artifact has exactly one authoritative home at every moment of its life.

1. **Working files are scratch.** Editors, interpreters, make, and the AI harness all consume files, so the working set is files — with no custody duty attached.
2. **The stores hold the surround.** Between capture and ship the database is the authoritative store: collected data, sources, audit records (session transcripts and tool call logs), working material, and knowledge, held as cross-project stores in which project is an index dimension, not a container — a source read once serves every project that tags it. Two contracts bind every element type: the **write contract** (provenance stamped at write time: source, method, timestamp, session, reason) and the **emit contract** (a defined file serialization, so a project's slice can always be pulled as files). The trace store is append-only; corrections supersede, they never overwrite.
3. **The emitted structure is self-contained.** From emission on, the surviving structure is the authoritative home of everything in it: versioned, verifiable, and buildable with the database gone.

Two deletion tests hold the boundaries. Every store element must be emittable to files, and the emitted structure must build standalone — the pipeline never queries the database.

## The stores

Custody names five stores; this section fixes their shape. One SQLite file holds all five as table groups, with a content-addressed vault beside it. Database and vault together are the database of the custody rules: one custodial unit, two storage forms.

**The payload rule.** Structure that gets queried lives in tables. Bytes that only get retrieved live in the vault at `vault/<sha256>`, with the catalog row and the hash in the database. Content addressing does double duty as change detection, since capture re-hashes a file and an unchanged hash is a no-op.

**The spine.** The write contract is columns, not convention. Every custodial row carries `id`, `created_at`, `session_id`, `origin`, `method`, and `reason`, none of them nullable. Provenance that can be skipped is provenance that will be backfilled, and backfilled provenance is a guess.

**Data.** Collected data lands in the database as data, not as a pointer to a file. Each dataset gets its own typed table, a catalog row recording name, version, row count, checksum, and collection date, and one codebook row per variable. Tables are write-once; a correction is a new versioned table superseding the old. Non-tabular payloads — instrument output, images, raw captures — go to the vault. Emission writes a table back out as a delimited file with its codebook beside it.

**Sources.** A source record carries bibliographic metadata, an identifier block holding DOI, OpenAlex, and Semantic Scholar ids together because one identifier is rarely enough, a retrieval status, and a content fingerprint for deduplication. The retrieved original is vaulted with its retrieval method and date, because a paywalled source retrieved once may not be retrievable twice. Extracted text is held separately by kind — abstract, body, fulltext, references — with its conversion method stamped, so extraction can be re-run when tools improve. Citations are not a table here; they are links, and they carry their own evidence.

**Audit.** *(Called Trace before 0.10; this is the audit layer's store.)* Three tables. Sessions hold identity and mechanics plus a small derived layer of title, gist, summary, and keywords, stamped with the pass that produced it. Events hold the work as it happens: an ordinal, a verb, a kind (action, decision, observation, blocker), an object, and a rationale. Transcripts hold the conversation in full, vaulted. Full transcripts are custody rather than luxury, since the only permanent losses in the estate that supplied this design's evidence were transcripts from the window before automatic capture existed. Capture runs as a sweep rather than at session close, because sessions do not reliably close. The store is append-only throughout; corrections supersede.

**Working.** Notes, scripts, and drafts are captured as snapshots with their workspace-relative path preserved. The workspace itself stays scratch, exactly as custody rule 1 has it: the sweep reads the workspace and never owns it, and the preserved path is what lets a project's working files be emitted back into the folder layout they came from. The three kinds are distinguished by their exit. Notes stay records. Scripts carry a re-run duty if a number they produced ships. Drafts are the only kind whose text can itself ship, which is what makes them the kind verification watches.

**Knowledge.** Deliberately unsettled. The working sketch is an entry table (class of standard, capability, or guideline, plus title, gist, keywords, content, and a hash of the source material for staleness detection) with a history table archiving every prior version. The sketch stops there because the ladder's top rung is templates, and their growth and use will reshape this store more than any other design choice will.

**What is shared.** Four things cut across all five stores. Relations of every kind — membership, production, citation, supersession — run through a single links table, which is also where a citation's evidence lives: the quote, its location, and who settled it when. Projects are a row and a link, never a container. A field-definitions table holds each field's definition, generation rule, and null behavior as data, so the schema documents itself. An emit registry maps each element type to its serialization and path, which is what makes the emit contract checkable rather than aspirational.

*(Not written by the authors. Claude wrote this paragraph unprompted and flagged it for review; it stands until the authors rule on it.)*

**What was left out, and why.** The design was drawn against an existing working system of comparable scope (its sources are not public; 549 real conversations among 2,800 session rows, 178,000 links, 316,000 text artifacts), which supplied evidence for what to copy and what to decline. Copied: the polymorphic links table, citation evidence carried on the link, the verb-and-kind event log, the conversion-stamped text sidecar, the identifier block, history tables, and the field dictionary. Declined: a quartet of descriptive prose fields per entity, two of which restated a third while another was never once set by a human in the system's lifetime; a generic attribute table that was built and never used; embeddings stored as text in the database; and a verification-status column on every row, which stood at nine verified against 2,690 unverified and is the evidence for verification attaching to use rather than to existence.

**Extension.** How a scholar adds a table or a field for their own purposes is open. The candidate is the pattern the data store already uses, a catalog row plus a purpose-built typed table, generalized so that a project-specific table can attach to any of the five stores. Whether extension is gated, and how, is undecided.

## The problem the system answers

*(Added 0.8, from the accepted proposal.)*

AI can raise the productivity of scholars, the quality of scholarship, and the rigor of science, but it presents two challenges to rigorous science that current transparency and reproducibility practices address neither.

1. **The plausibility problem.** AI produces work that looks correct but is wrong or was produced by a process the scholar did not intend, as in hallucinated citations, misattributed claims, and analyses that reach a defensible answer while skipping the required steps.
2. **Inconsistency across runs.** Models sample their output from probabilities and GPU arithmetic varies between runs, so unlike analysis code, the same prompt can return a different answer.

The two compound. Plausibility means AI work must be checked, and inconsistency means a check on one run does not carry over to the next.

## Concepts and layers

*(Rewritten 0.9 and 0.10.)* The reproducible pipeline is the foundation. The workflow adds a verification layer, an observability layer, and an audit layer to it. Each concept is defined below; the layer is the machinery that delivers it. Figure 2 of the proposal shows the three layers.

| Layer | Concept | What the layer does | Answers |
|---|---|---|---|
| Verification layer | Verification. Provision of objective evidence that a given item fulfils specified requirements, where the item can be a process (JCGM 2012, 2.44 and Note 2) | Runs one verification procedure per stream on AI contributions before they enter the pipeline. Process verification procedures check whether the AI performed the task it was given; output verification procedures check a contribution against a known reference. Produces a verification report for the scholar | The plausibility problem |
| Observability layer | Observability. Monitoring the process behind an AI output | Gives the scholar a live view of three things: model reasoning (where the model exposes it), tool calls, and tool results. It reads the audit layer's record as it is written. Today the same data is captured after the fact; what is missing is the live reader. Events follow OpenTelemetry's conventions for AI calls, which keeps the view harness-agnostic. Less formal than verification and earlier | Inconsistency across runs |
| Audit layer | Traceability. A documented chain from each element of a research product to the inputs, sources, scripts, and sessions that produced it (adapted from JCGM 2012, 2.41) | Records, stores, and tags with metadata every AI session transcript and tool call log, so that any AI contribution can be audited. Feeds the observability layer live and the verification layer after the fact (the build integrity procedure already reads `session_writes.jsonl`, a per-write record, through `check_ai_touch.py`) | Inconsistency across runs, since the record of the run used is the only evidence of how a contribution was produced |

**Audit layer gaps.** Three requirements are not met yet. Records must be append-only (corrections supersede, never overwrite). Every record must carry origin, method, and reason (the write contract). Capture must be harness-agnostic: one event schema, with one adapter per harness; capture today reads only one harness's sessions.

The layers are not the same shape. Verification is a gate between AI work and the pipeline. Observability (during the work) and the audit layer (during and after it) run alongside everything.

**Boundary.** Passing a verification procedure establishes that a contribution meets its requirements, not that the requirements or the substantive claim are valid. That judgment stays with the scholar, supported by the knowledge base. (0.8 listed validation as a fourth property; 0.9 drops it as a property and keeps this boundary.)

## Two views of the system

*(Added 0.9, rewritten 0.10.)* The system is described in two views that answer different questions, matching the proposal's figures.

| Figure | View | What it shows |
|---|---|---|
| Figure 1 | Contrast | AI work that passes verification and the reproducible pipeline, against AI that writes straight to the research product |
| Figure 2 | Layers (flow) | How AI contributions move from the harness through the four streams, the verification layer, and the reproducible pipeline, with the observability and audit layers alongside |
| Figure 3 | Components | What software is involved, left to right: inputs (scholar, AI model, external software), the workflow (AI harness, wrappers and MCP servers, databases, reproducible pipeline, observability dashboard), and the output (research product) |

The reproducible pipeline appears in both views on purpose, as a component and as the foundation the layers sit on. Use "component" for the parts in Figure 3 and "layer" only for the three added layers. The AI harness sits inside the workflow in Figure 3 but stays swappable: any harness can fill that slot.

## Verification vocabulary

*(Added 0.9.)*

| Term | Meaning |
|---|---|
| Procedural graph | The format for writing down a procedure as steps, conditions, and pitfalls. It can hold any procedure, including methods, verification, and operational tasks |
| Procedural graph system | The procedural graph format plus the program that runs it. Three parts: the graph (steps, conditions, pitfalls; the only part learning may edit, and only its text), contracts (what each step must produce), and fixed implementations. The program is in charge: it walks the graph and decides each transition from field values, and a model answers only fixed judgment questions. Each procedure follows schema, fill, build: define a schema, fill its fields, build the report from them. Procedures start from events (an AI edit, a turn ending, a build, a commit), not requests. Rules from the verification procedures build spec (2026-10-09) and the methods graph design (2026-10-01). Verification graphs and methods graphs are the two built instances; operational-task graphs are planned |
| Verification procedure | A procedural graph that checks a contribution. Two kinds: process (did AI do the assigned task?) and output (does the contribution match its reference?) |
| Verification layer | All the verification procedures, plus the triggers that start them and the reports they produce |
| Verification report | What the scholar reviews and approves |

Retired in prose: procedural knowledge graphs, verification graphs, templates (in the verification sense), checkpoints, verification band, verification steps. "Template" keeps its meaning in the law's ladder (record, standard, template), which is a different thing. The verification code lives in `verification_procedures/` (renamed from `verification_graphs/` on 2026-10-22).

## Components

*(Added 0.8, rewritten 0.10.)* Figure 3 arranges the components left to right as input, workflow, output. All sit outside any single project, so one setup serves every project a scholar runs.

| Side | Component | What it is | Status |
|---|---|---|---|
| Input | Scholar | Directs the harness and receives the live view | n/a |
| Input | AI model | The model the harness runs. Swappable through one provider setting (base URL and model name); no codebase may hardcode a provider | Provider setting not built |
| Input | External software | The scholar's existing tools: text editor, statistical software, citation manager, version control, and build tools such as Pandoc, Make, or Quarto. Reached through the wrappers and MCP servers | Exists (scholar's tools) |
| Workflow | AI harness | The software that runs a model and connects it to tools and files. The scholar's point of contact with AI and AI's point of contact with the rest of the workflow. Any harness can fill this slot. Harness events (an AI edit, the end of a turn) start the verification procedures | External, swappable |
| Workflow | Wrappers and MCP servers | Connect the harness and the AI model to the databases and external software, and record each action for the audit layer. Wrappers are small programs that log each action; logging must never interrupt the call it wraps. MCP servers expose the databases (the knowledge base server is built and must ship in the workflow repository) | KB MCP server built; wrappers for external software not built |
| Workflow | Databases | The scholar's working knowledge base (standards and the procedural graphs that encode methods and verification procedures), the source library of citations and retrieved texts, and the session and action logs. These are the stores of Custody and The stores | Designed (The stores) |
| Workflow | Reproducible pipeline | The build engine (`ospipe`) that assembles each research product from its text, references, data, and code. Takes inputs from the harness and through the wrappers. Contains no AI. Version control supports it (history of every input and build) | Built |
| Workflow | Observability dashboard | Shows the scholar the live view: tool calls and project information. Design to be developed later | Planned |
| Output | Research product | A manuscript, website, research compendium, or presentation built by the pipeline | n/a |

## Project level and streams

*(Added 0.8.)* Within each project, scholars work messily and the workflow brings order as the work solidifies. The project organizer feature uses AI to organize files, builds, and past sessions, with every change observable and reversible. Rule: AI never deletes; it marks instead. Organizing project records comes first; physical file moves come later.

AI contributes to each project through four streams, each with its own verification procedure. Research products are not limited to manuscripts; websites, research compendia, and presentations build the same way.

| Stream | Tools | Verification procedure | What the procedure checks |
|---|---|---|---|
| Prose | Text editor, Word | Change review | Each AI revision arrives as a tracked change with its stated reason, and the author resolves it |
| References | Citation manager | Source support | The source exists and says what the research product claims it says |
| Data and analysis code | R, Python, Quarto | Code | Every reported number comes from a documented script, with its parameters and model written to a record by the run |
| Build | Pandoc, Make, Quarto | Build integrity | The research product is built only from the streams with the author's declared preferences, has no hard-coded results, matches a rebuild, and is never edited by AI |

**Open.** The authors' notes propose two levels of verification: working checks (light review, such as reading an agent's literature list before building on it) and build checks (formal checks a contribution passes before it enters the reproducible pipeline). Cut from the proposal text; not yet ruled on.

## Design principles

*(Added 0.8.)*

| Design principle | Description |
|---|---|
| Agnostic | Works with any model, harness, software stack, and workflow, since research workflows are unique to their users (Healy 2020) |
| Scholar-first | Lets scholars start however they work and has AI organize files later, since file management is where personal information systems break down |
| Mechanical builds | Uses AI to build features and verification standards that run without AI, so the plausibility and inconsistency problems do not arise in them |
| Observable and auditable AI | Records every remaining agent and direct AI action through wrappers |

## Five goals

1. **Reproducible base.** Plain-text social science. Raw inputs preserved, transformations scripted, documents assembled, history versioned.
2. **AI integration.** AI works inside the reproducible pipeline as the labor, not alongside it as an accessory.
3. **Verification.** Logs and records of every AI-produced element, so any output is easily checked by the scholar.
4. **Cross-project knowledge base.** Standards and processes proven in one project become knowledge that AI applies to the next.
5. **Features.** External and custom skills, tools, and programs extend what the base can do.

Goal 1 is the foundation. Goals 2 and 3 are twins that only work together; integration without verification is trust, and verification without AI labor is overhead nobody would pay. Goals 4 and 5 are the compounding pair; one compounds knowledge, the other compounds capability, and each project inherits both.

## Goal 1. The reproducible base

The plain-text social science guide (plain-text.co) supplies the model. Raw inputs stay immutable, transformations are code, documents are assembled from plain text, history lives in version control.

**Preserve.** The three irreplaceables are immutable, and each has one authoritative home at every moment — the stores during the project, the emitted structure at ship. Sessions are captured automatically by the audit layer. References and retrieved sources live in the source store [Zotero + retrieval records]. The submitted manuscript and every version exchanged with a human or a journal is frozen in the build archive.

**Transform.** Derived artifacts are made only by saved scripts. Cleaning, analysis, tables, and figures run as commented code, with a Quarto workbook re-deriving the results independently. Documents are built by pandoc from canonical markdown; paper, response letter, slides, and blog post each have one canonical markdown file and a make target that builds it, all drawing on the same numbers manifest, generated exhibits, and bibliography, so a data rerun propagates to every research product by rebuild. Human hand edits to prose happen in exactly one place, Word tracked changes, where they are visible by definition.

**Connect.** Systems join by shared identifiers. Emission copies — deliberately, and with a record; nothing else is copied.

| Identifier | Issued by | What it links |
|---|---|---|
| citekey | Zotero | prose citations to the reference library |
| source id | source retrieval | quotes and evidence records to the source text |
| session id | the audit layer | any artifact to the conversation that produced it |
| git hash | the paper's repo | any build to the exact text and scripts behind it |
| build number | build ledger | every version exchanged with a human or journal |
| task id | ClickUp | research product and revision round status |

## Goal 2. AI integration

Drafting, data cleaning, analysis, source retrieval, and review are performed by AI sessions using the same files, scripts, and records a human would. Because the pipeline is files, code, and records, the harness is interchangeable (Claude Code today, any equivalent tomorrow).

Chat is the drafting surface, where sections and tables are shaped before anything is committed. Word is the review surface; AI edits reach the author as native tracked changes through the compare loop, and the author's edits return as extracted deltas (mechanics in the appendix).

## Goal 3. Verification

Verification fires when AI-produced work hits the surviving path. That is the whole trigger: work that stays in the surround owes nothing, and a claim earns its witness at the point of use. The trigger is provenance, not content. An addition the author made carries the author's warrant and owes no verification, which is what makes attribution load-bearing rather than bookkeeping — the reconcile machinery in the appendix is how the system decides whose hand a change came from. Grounding a claim of one's own stays available on request; it is a service the scholar invokes, never a duty the system imposes. The obligation aligns with the four streams (see Project level and streams). What was run is checked against its execution and what was read is checked against its source. Draft 0.7 held that prose carries no check of its own because its claims decompose into the other two; 0.8 adds a prose check (change review) and a build check (build integrity), as built in `verification_procedures/`. Each check is a verification procedure, a procedural graph of steps, conditions, and pitfalls that the procedural graph system runs, with the model answering only fixed judgment questions inside it (verification procedures spec, 2026-10-09). Beyond this, the taxonomy of checks stays open (the three-check partition in an earlier framing note, not public, remains a proposal).

**Harness triggers** (lower tier). The trigger point is the harness's after-edit hook, already wired in one harness for a compile check. Every new trigger is registered and documented, so triggers do not drift from the hook configuration.

An AI's account of its own work is not evidence. The witness is. The witness depends on the claim.

| The AI claims | The witness | Where it lives |
|---|---|---|
| I cleaned data, ran the analysis, made this table | Runnable commented code. Comments tie each claimed or assumed action to the function that performs it | analysis scripts, Quarto workbook |
| I cited or summarized this source | The exact reference, the passage relied on, and a judgment of whether it was used correctly | Claim-evidence record (CER) entry with quote, location, and alignment |
| I revised the prose | Tracked changes against the prior version | Word compare documents |

A claim without a witness is unverified (the witness rule), and the pipeline can list every unverified claim on demand. The comment rule matters because narrative and code drift apart. In one paper's analysis code, a parser bug mislabeled results for weeks, because the code silently preferred one keyword over a complete answer in the same response. Nothing stated that assumption where a reader would meet it.

Verification rests on records. Each transition emits a standard one, whether the actor was AI or human. All but one of the formats already exist in the project's files; the pipeline declares them canonical rather than inventing new ones.

| Transition | Record | Exemplar |
|---|---|---|
| Data or pipeline change | Delta report. What changed, before and after, which sentences are now invalid | a delta note for a reparse or a data extension, such as `DATA_DELTA.md` |
| Source discovered, retrieved, read | Source record with retrieval status and verified quotes | source-retrieval bundle `source_records.yaml` |
| Source used in prose | CER entry | `cites` links carrying the quote and its location |
| Number taken from a source | Claim tracker row. The number needed, verbatim text, page, found or not | a claim tracker such as `claim_tracker.md` |
| Decision, open question, dispatched work | Decision log entry (LOCKED, OPEN, WIP) | a decision note such as `decision_notes.md` |
| Document exchanged | Build ledger row | `BUILDS.md` (the one new format) |

## Goal 4. The cross-project knowledge base

Standards and processes proven inside one project are registered in the knowledge store, where any future session, human or AI, reads them before inventing its own. Knowledge sits in three tiers — the project, the scholar's estate, the discipline — and only procedural knowledge is promoted outward, because only procedural knowledge is validated by execution rather than by reading. Knowledge entries obey the emit contract like every other store element.

The loop has three steps. A practice emerges inside a project; the delta report, the claim tracker, and the witness rule were all born in the diagnostic paper. When it proves out, it is written to the knowledge store as a standard, with its format and an exemplar. New projects, and the AI sessions working in them, consult the store at the start and inherit the standard instead of rediscovering it.

Two records feed this base without effort. Session capture is automatic (transcript, files touched, work log), and the decision log captures judgment deliberately. Promotion is the curatorial act; the raw material is already preserved by goal 1.

This spec is itself an instance; its formats and witness rule make that trip once adoption proves them.

## Goal 5. Features

External features are adopted tools (pandoc, Quarto, Zotero and its connectors, retrieval services). Custom features are built skills and programs (the manuscript-editing and evidence-grounding skills, the source-retrieval pipeline, the build resolver that substitutes computed numbers into prose, and two planned features: **pipeline setup** (called the `/manuscript` skill before 0.9), an agentic workflow that builds a reproducible pipeline and connects it to the scholar's external software and harness, and the **project organizer**, which organizes files, builds, and past sessions with every change observable and reversible).

Two rules keep extension from becoming sprawl. A feature enters as something executable with a declared contract (what it consumes, what it produces, which records it emits); reference documents do not count. And a feature's work remains subject to goal 3; a skill that reviews a manuscript or cleans data leaves the same witnesses a raw AI session would.

Pipeline setup starts from the existing workspace-intake skill and targets the layout of the first adopted paper. Neither pipeline setup nor the project organizer appears in the proposal figures; they are features, described in the text.

The procedural graph system also lets scholars write reusable procedures for the operational tasks around research that are unique to their institution and preferences, such as connecting to a university high-performance computing cluster or adding a project to GitHub.

Goals 4 and 5 feed each other. A standard that stabilizes becomes an executable feature, and a feature's contract is written back as a standard.

## The systems

Every row is a binding; any can be swapped without redrawing the system.

| System | Role |
|---|---|
| git, GitHub | History of everything plain text. One repo per paper. A public remote at submission, when the emitted structure becomes the replication package |
| Zotero | Reference library. Exports the bib file the builds cite from |
| Store binding (to be chosen) | The stores: session capture, artifacts, CER, provenance, and the knowledge store of goal 4. Already-built implementations to pull from are listed in a file that is not public |
| Quarto | Literate analysis. The independent re-derivation of every reported number |
| Word | The human surface. Native tracked changes are the prose witness |
| ClickUp | Tasks and rounds per research product |
| Claude Code, Forgecode, any harness | The working surface. Interchangeable, because the pipeline is files, code, and records |
| Any model provider | The AI model. Interchangeable through one provider setting |

## What this kills

Failure modes observed in the diagnostic paper.

1. Nine files could claim to be the manuscript. Now one canonical file per research product; everything else is a build or a bannered archive.
2. Numbers frozen into prose rotted through two data reruns. Now prose pulls computed values from a manifest at build time, and the delta report names the sentences to re-read.
3. The most complete draft is stale on every quantity and nothing on it says so. Now staleness is marked on the artifact itself.
4. The sharpest decisions of a 19-hour session exist only in the transcript. Now decisions are logged when made.
5. AI work was accepted on its own narrative. Now the witness rule.
6. The replication package assembled by archaeology at the end. Now it is emitted; the surviving structure is the package.

## What exists (2026-10-22)

*(Added 0.8. Counts rechecked against the code on 2026-10-22.)*

**Reproducible pipeline. Built and tested.** `ospipe` has 1,951 lines across eleven modules (excluding fixtures), makes no model or network calls, and passes all 136 tests. No build proceeds while a placeholder lacks a manifest value; builds are numbered and checksummed; the engine refuses a new build if an earlier one was altered; `lineage` follows a number to its manifest entry and every sentence and table that quotes it. On one revise-and-resubmit, the analysis code regenerated all 119 outputs byte-identical from a fresh copy on the same machine.

**Verification layer. Partly built.** A runtime walks procedural graphs for all four streams; each stream has a clean and a seeded fixture, and every seeded fault is caught under recorded and live judgment across 36 tests (35 test definitions, one runs twice). Committed to the workflow repository on 2026-10-22 (branch `verification-layer`), so the research artifact includes it. The prose path (Word tracked changes, reconciled into accepted, rejected, rewritten, pending, or the author's own edit) has run end to end once, on a trial document with the author as reviewer. The knowledge base holds ten entries (`ospipe/kb/corpus`), served read-only to AI sessions in any project. Not yet built: shared schemas and reports, harness triggers, observability, adapters for R and Quarto.

## Stage 2 (January to May 2027)

*(Added 0.8, rewritten 0.10 from the proposal's Stage 2 paragraph, which is the source of truth for this list.)*

1. **Finalize the procedural graph system**, so that methods, verification procedures, and operational tasks can all be written as procedural graphs.
2. **Finish building and testing the verification layer**: a fixed schema and shared report for every verification procedure; R and Quarto adapters (the R runner ports the run-and-replay logic of the methods-graph runtime, `pg_runtime.py`); harness triggers, so that an AI edit, the end of a turn, a build, or a commit starts the relevant checks.
3. **Build the observability layer** and the associated wrappers and MCP tools required to integrate AI observability into tools outside the workflow: a live view of model reasoning, tool calls, and tool results, with the same events written to the audit layer. Capture is harness-agnostic, with one audit event schema and an adapter for each harness.
4. **Test the workflow across multiple open-source harnesses, models, external software integrations, and scenarios.**
5. **Develop an interactive web portal**, built on the toolsite catalog generator, to help scholars learn, implement, and critique the workflow.

**Later.** A seeded-fault test on a full synthetic manuscript, assembled from the per-stream seeded fixtures, reporting catch rates, misses, and scholar-minutes.

## Development and adoption

Development stays in this workspace, separate from live projects. The mechanics below are built and proven here against test materials only, a sample manuscript, a hand-rolled manifest, a scratch repo, and a copy of a real submitted docx for compare calibration. Live papers continue under their current practices and are untouched until the loop holds end to end. The engine is the `ospipe` module tree (Recursive Modules method, manifest in `ospipe/MODULES.md`), and the goal 4 standards corpus is served cross-project by the generic KB MCP under the name `workflow-kb`.

Adoption then happens paper by paper. A paper adopts with four moves: its canonical manuscript file, its manifest, its response map if it is a revise-and-resubmit, and its own repo. Because structure is emitted rather than maintained, adoption does not require a paper to start over — capture turns on, and the structure is constructed when the loop is ready to hold it. The first adoption's exit delivers goals 4 and 5; the proven formats register to the knowledge store, and the mechanics extract into the pipeline setup feature.

---

## Appendix. Mechanics (to be proven during development)

**Manifest.** Computed values appear in canonical text as `{{num:key}}`, resolved at build time from the pipeline's `numbers.yml` plus a hand-edited overlay for quick additions. The build fails on missing keys. A linter flags bare numerals (years and literature constants already in the claim tracker are allowed). After a rerun, the delta report lists changed keys; every sentence containing one is re-read before the next build, and a key crossing a decision threshold, a p-value moving across 0.05 for example, blocks the build until its sentences are re-reviewed. Manifest values are display-formatted strings; the resolver formats nothing.

**Builds.** `make docx` runs linter, resolver, then pandoc with the venue's CSL citation style, `refs.bib`, and a styled `reference.docx`. Output is `builds/vNNN.docx`, the resolved snapshot `vNNN.md`, and a ledger row (date, git hash, sha256, purpose, baseline, reviewed). Builds are never edited in place; hash checks enforce it. Builds happen when the author asks to see the document in Word, when a section is done, or when a skill needs a resolved snapshot. Chat remains the drafting surface.

**Compare and return.** Word Compare, last baseline against new build, Formatting unchecked, label set to the AI's name. The author reviews with native gestures — accept, reject, edit, comment — and saves to `returns/`. The AI extracts the gestures with `pandoc --track-changes=all --wrap=none` plus python-docx for margin comments, classifies them three-way against the ledgered baseline and revision snapshots (reconcile), and ports them into canonical markdown one delta at a time. A delta touching a number becomes a question, never an auto-revert. A delta touching a citation or the References section becomes a citekey edit; rendered citations cannot round-trip. After porting, a port-only build becomes the next compare baseline.

**Git substrate.** Each paper gets its own repo at the workspace root, commits by explicit path, private remote at submission.

**Skill interop.** The manuscript-editing and evidence-grounding skills (abt-review, preground, ground, discourse-review) never see placeholder text. They read the resolved build snapshot, and their accepted changes port back exactly like Word returns.

**R&R research product.** `v000_submitted.docx` is the journal's copy. Reviewer-facing tracked changes come from comparing v000 against the final build. Calibrate first by rebuilding the unchanged submitted text and comparing; citeproc re-renders the References section wholesale, so expect to accept-all there and note the regeneration in the response letter. One-time check that Word's remove-personal-information setting is off, or author attribution dies silently.

**Deferred until it hurts.** Pipeline emitter for the manifest (built by hand for one paper; to generalize). The unverified-claims report. Slides and blog make targets. reference.docx styling. Pipeline setup. Each is added the first time its absence costs something.

**Tools, verified on this Mac.** pandoc 3.9 (`--track-changes`, `--reference-doc`, citeproc), Word 16.111 (scriptable compare), Quarto 1.7.31, python-docx 1.2.0, PyYAML, GNU Make 3.81, git 2.50.1. Nothing needs installing.

---

## Changelog 0.9 → 0.10 (2026-10-22)

- **Brought in line with the final proposal Figures 1 to 3** and the rulings of 2026-10-22.
- **Trace layer becomes the audit layer.** Records, stores, and tags session transcripts and tool call logs; feeds observability live and verification after the fact. Gaps stated: append-only, write contract, harness-agnostic capture. The Trace store is renamed Audit.
- **Observability rewritten:** live view of model reasoning, tool calls, and tool results, read from the audit record; OpenTelemetry conventions for AI calls as the event format.
- **Components rewritten** as input, workflow, output (Figure 3): AI model added as a swappable input; wrappers and MCP servers become a component; observability dashboard added as planned; harness inside the workflow but swappable.
- **Two views rewritten** with a figure map.
- **Procedural graph system defined** from the verification procedures build spec and the methods graph design.
- **Rules added:** AI never deletes (project organizer); harness triggers registered (lower tier).
- **Stage 2 rewritten from the proposal's Stage 2 paragraph** (procedural graph system first; testing across multiple open-source harnesses, models, external software integrations, and scenarios). Knowledge base learning removed from this spec (long-term goal). Harness triggers and harness-agnostic capture placed under the proposal's items. The synthetic manuscript is under Later in both the spec and the proposal (the proposal sentence was dropped 2026-10-22).
- **Module renames in `ospipe`:** `audit` is now `delta` (delta report) and `trace` is now `lineage`, removing the clash with the audit layer and the retired trace layer.
- **Design principle** renamed "Observable and auditable AI".
- **What exists** rechecked: 136 and 36 tests pass; verification layer committed.
- **Other systems no longer named in the spec.** Their mentions made generic; already-built parts to pull from are listed in a companion file that is not public.
- **Renaming pass:** `verification_graphs/` is now `verification_procedures/`; "deliverable" replaced by "research product" in the verification procedures and file protocol design docs; the lineage closure is computed by the `lineage` command; Goal 3 says scholar, not scientist.

## Changelog 0.8 → 0.9 (2026-10-22)

- **Terminology brought in line with the proposal draft of 2026-10-22.** "Research product" replaces "deliverable" throughout, including the law's reader rule. Historical changelog entries keep their original wording.
- **Properties becomes Concepts and layers.** Verification, observability, and traceability are defined as concepts and built as the verification layer, observability layer, and trace layer. "Reproducible pipeline layer" in What exists becomes "Reproducible pipeline", since the pipeline is the foundation, not a layer.
- **Validation dropped as a property.** The boundary stays: passing a check is not validity, and that judgment stays with the scholar.
- **New sections: Two views of the system, Verification vocabulary.** Five verification terms fixed; procedural knowledge graphs, verification graphs, templates (verification sense), checkpoints, band, and verification steps retired in prose.
- **Components.** Databases entry names procedural graphs as part of the scholar's working knowledge base. External software lists build tools (Pandoc, Make, Quarto) in place of "a build script".
- **Features named.** Pipeline setup (was the `/manuscript` skill) and project organizer. The procedural graph system covers operational tasks (HPC jobs, GitHub).
- **Streams.** The data stream is "Data and analysis code" (one stream, two kinds of files).
- **Not changed, flagged.** The Stage 2 list here differs from the proposal's Stage 2 paragraph (the proposal adds the procedural graph system, wrappers and MCP tools, and a web portal; this list has knowledge base learning). Scope, not terminology, so left for the authors.

## Changelog 0.7 → 0.8 (2026-10-09)

- **Brought in line with the Organization Science Stage 1 proposal draft** of 2026-10-09 and the verification procedures spec of the same date.
- **New sections: The problem the system answers, Properties, Components, Project level and streams, Design principles, What exists, Stage 2.**
- **Four streams replace three for verification.** Build is a stream. Prose now carries a check of its own (change review), superseding the 0.7 line that prose claims decompose into the other two.
- **Observability defined** as the authors' two-part sense: real-time monitoring of the harness plus the post hoc process check that traceable logs enable.
- **"Reproducible pipeline" replaces "reproducible core"** as the name of the build engine component.
- **Two levels of verification** (working checks, build checks) recorded as open.
- **Status counts corrected against the code**: 36 verification tests, not 38.

## Changelog 0.6 → 0.7 (2026-08-10)

- **New section: The stores** — the five stores get their shapes. One database plus a content-addressed vault as a single custodial unit; the payload rule (queried structure in tables, retrieved bytes in the vault, catalog and hash always in the database); the write contract as non-nullable spine columns; per-store shapes for Data, Sources, Trace, and Working; the shared layer of links, projects, field definitions, and the emit registry.
- **Data lands as data.** Each dataset is a typed table with a catalog row and a codebook, not a database pointer to a file. The file-catalog design was rejected as a violation of the custody ruling.
- **Full session transcripts enter custody** (vaulted, swept rather than captured at close), with the derived session layer cut to four fields: title, gist, summary, keywords. The gist comes from the knowledge-base builder's entry shape.
- **Goal 3 scoped to provenance**: verification follows AI authorship, an author's own additions carry the author's warrant, and grounding is a service rather than a duty. Attribution becomes load-bearing.
- **Knowledge store and extension both left open** on the record, the first pending templates, the second pending a decision on how scholars adapt the schema.
- **Prior art declared.** The store design was drawn against an existing working system with its live data as evidence; what was copied and what was declined is stated in the section rather than left implicit.

## Changelog 0.5 → 0.6 (2026-08-04)

- **The law replaces "the system in one sentence"** (R1 adopted amended).
- **Goal 5 restored to the authors' title, Features** (reverted 2026-07-27; draft 0.5 predated the reversion and still said "Capabilities").
- **New sections: A project's life and Custody** — capture from day zero, structure emitted at ship, authority by phase, cross-project stores with write/emit contracts, the two deletion tests (the 2026-08-04 database ruling).
- **Goal 1 Preserve restated** for one-authoritative-home-per-phase; **Connect qualified** — emission copies, with a record.
- **Goal 3 generalized**: verification triggers when AI work hits the surviving path, aligned with the three streams; the taxonomy of checks deliberately left open.
- **Goal 4 gains the tier framing** (project / estate / discipline, procedural promotion only) and the emit contract.
- **Compare-and-return updated** to the reconcile mechanism (resolve-first retired 2026-07-23; 0.5 still described it); AppleScript Compare automation removed from the deferred list (built).
- **What this kills gains item 6**, the end-of-project replication archaeology.
