# Verification graphs

Procedural graphs for the four verification streams. Each graph is a verification standard written so it can run: the steps, the order, the conditions that route the work, and the pitfalls the checker meets at the step where they bite. Every run leaves step records, a trail, and a report, so the check itself can be checked.

This is the procedural-graph idea from the Methods and Theory Graph pilot (Lu et al. 2026, arXiv 2609.09153) applied to verification standards and templates, not to methods.

## Layout

| Path | What |
|---|---|
| `vg.py` | Runtime: `check`, `run`, `step`, `verify`, `score`, `advise`, `decide`, `procedures` |
| `registry.yaml` | The procedure registry, one procedure for each stream, with its graph and triggers |
| `graphs/<stream>.yaml` | The procedure: nodes, edges with condition / guidance / pitfalls |
| `schemas/<stream>.yaml` | Each stream's item fields, results fields, and report layout (see Schemas), with `schemas/versions.yaml` recording each schema's checksum at each version |
| `contracts/<stream>.yaml` | What each step reads and must produce |
| `implementations/<stream>/<node>.py` | Tool steps (deterministic Python) |
| `implementations/<stream>/<node>.prompt.md` | Judgment steps (one ask per item) |
| `implementations/_lib.py` | Shared helpers: findings, report shape, text normalization |
| `implementations/_report.py` | The one report builder, which the exit step of every stream uses |
| `fixtures/<stream>/{clean,seeded}/` | Test inputs; `seeded/truth.yaml` lists the planted faults |
| `tests/test_<stream>.py` | Clean fixture gives no blocking or warning findings; seeded fixture catches every planted fault |
| `review/` | The Word review modules `returns`, `reconcile`, `annotate`, and `lint`, and the Word compare script (see Word review) |
| `runs/` | One folder per run (gitignored) |

Besides the four streams and the self-test (`selftest`), `graphs/` holds five more procedures, each a graph the same runtime runs.

- `llm_runs` evaluates a finished run of another procedure, without rerunning it or asking a model anything.
- `mcp_kb` answers one call to one of the knowledge base server's read-only tools from the exported index.
- `ops_github` adds a project to version control on GitHub.
- `ops_hpc` connects a project to a university computing cluster.
- `wrap_git` turns the lines the git wrapper writes into events in the audit layer's event schema.

## How a run works

```
python3 vg.py run graphs/citations.yaml --run runs/X --inputs fixtures/citations/seeded \
    --judge live
python3 vg.py verify --run runs/X     # replay every tool step from its saved code
python3 vg.py score --run runs/X --truth fixtures/citations/seeded/truth.yaml
python3 vg.py decide --run runs/X --item r08 --approve --by "A. Scholar"   # or --hold
```

Three settings change how the citations stream looks up a DOI that its cache does not hold. It asks Crossref first, and DataCite, which registers arXiv and Zenodo DOIs, for a DOI Crossref has no record of.

- `VG_OFFLINE=1` counts such a DOI as not found instead of looking it up.
- `VG_CROSSREF_URL` sets the address of the Crossref lookup, `https://api.crossref.org/works/` when unset.
- `VG_DATACITE_URL` sets the address of the DataCite lookup, `https://api.datacite.org/dois/` when unset.


The scholar approves or holds each item that needs a decision with `decide`. Each decision records who made it, when, and on which run, and the latest one for an item is the one that counts. The command refuses an unknown item, an item that needs no decision, and a run with no results file.

A node runs when any incoming edge fired. An edge with a `check` (`file.json:field OP value`) fires only when the check holds; one without fires whenever its source step completes. A step that breaks its contract stops the run.

Every run folder holds:
- `manifest.json`: graph, contract, and input hashes, plus executors
- `trail.jsonl`: an append-only event log
- `records/NN_<node>.json`: one per step, holding hashed inputs, execution, outputs, contract result, and branches fired
- `code/`: the exact code each tool step ran
- `prompts/` and `responses/`: every judgment ask and answer, one per item
- In a live run, `responses/<step>/<item>.reply.json` beside each answer, the whole reply the model service sent, byte for byte, with the model it reports, the finish reason, the token counts, and any reasoning text (`<item>.retry.reply.json` for a retry), listed with its sha256 under `replies` in the step's record and never read by `verify`
- `files/`: inputs and every produced file. Steps only add files and never overwrite.
- `files/report.md` and `files/findings.json`: the deliverable
- `results.json`, written when a run of a graph with a schema completes, outside the step files. A graph with no schema, such as the self-test graph, gets none. It holds `schema` (`verification-results`), `schema_version` 1, `stream`, `run_id` (the run folder's name), `procedure_version` (the graph's version), `inputs` (the manifest's input checksums), `items`, and `decisions`. The items are the item rows of the run's `fields.json`, in order, each holding the fields its schema's `results` list names, in that order. A field the builder marked not run is written as the empty value of its type (an empty text, list, or mapping, otherwise null), and its reason stays in `fields.json`. Each item is one row of the report, with what the report says about it and `needs_decision`. In the citations stream a citation the scholar first named in the record needs no decision. All four streams list items. The build, data, and prose streams list one row for each deliverable, manuscript number, or change in their reports, then one item for each other group of blocking or warning findings, and each item carries `kind`, `summary`, and `findings`. A change the author made needs no decision.
- `report_decided.md`, written by `decide`. It is the run's report with a count of approved, held, and undecided items and a table of each item's latest decision before its first section. `files/report.md` stays exactly as the run wrote it, so `verify` still holds.

## Conventions

Every procedure in this folder follows these conventions.

- **Tool step:** `python3 <node>.py <files_dir>`. It imports `_lib`, reads only its contract's `reads`, and writes only new files. It must be deterministic: no timestamps, no randomness, sorted output. No network, except in a node marked `replay: network`.
- **Check steps** write `findings_<node>.json` through `_lib.emit_findings(node, [...])`, even when the list is empty. A finding is `{check, severity: blocking|warning|info, item, message, evidence}`.
- **The exit node** writes `findings.json`, from `_lib.collect_findings()`, and `report.md`, from `_lib.report(...)`. The report puts the summary first and the problems first. In a graph that names a schema, the exit node fills the schema's fields from the step outputs and writes `fields.json`, `findings.json`, and `report.md` through `_report.build(fields)`, the one report builder. Before that step the runtime writes `files/steps.json`, which says which steps ran and why each skipped step did not, and copies `_report.py` and the schema, as `schema.yaml`, beside the step's code. All four streams work this way.
- **Judgment step:** `<node>.prompt.md` with `{{goal}}`, `{{pitfalls}}`, `{{item}}`, and `{{item.<field>}}`. It asks for a single JSON object. With `foreach: rows.json` (and optionally `where: "field in [a, b]"`) there is one ask per item. The runtime writes `<node>.json` as a list of answers, each carrying `item_id`, `executor`, and `prompt_sha256`. The next tool step turns answers into findings.
- **Roles:** `role: judge` (default) uses `--judge`. `role: second` uses `--second`, the independent rechecker, which must be a different model. The run refuses to start when the two are the same model (two `recorded:` executors naming the same file, or two others naming the same model).
- **Verification follows AI contribution.** Content the author owns is listed, not checked, except where a procedure's graph says otherwise. A citation AI suggested is still checked after the author rewords or moves its sentence.
- **Tests:** a clean fixture gives zero blocking or warning findings. A seeded fixture's `truth.yaml` (`faults: [{id, check, item}]`) must be fully caught. A fault is caught when any finding, of any severity, names its check and an item holding the fault's item, so a report that ranks nothing, such as the citations report, is still measured. Tests run judgment steps with `recorded:` executors, so they exercise the plumbing. Runs with a live model, scored against the same truth, test the judgment.

## Schemas

A graph may name its stream's schema with `schema: schemas/<stream>.yaml` beside `contracts:`. The path is read from this folder, and an absolute path is read as given. `vg.py check` checks the schema against the graph whenever the graph names one. A graph whose stream is `prose`, `citations`, `data`, or `build` must name its schema, and the self-test graph and any other graph may leave it out.

A schema holds these keys.
- `stream`, the graph's stream.
- `version`, a positive integer, raised by hand when a field or the layout changes. `schemas/versions.yaml` records the checksum of each schema file at each version, and `tests/test_acceptance.py` fails when a schema file changes without a new version and its line.
- `item`, a few words saying what one item is.
- `id`, the item field that names each item.
- `fields`, the item fields.
- `run`, optional, the fields with one value for the whole run.
- `tables`, optional, other row sets the report shows, each `{id, fields}`.
- `results`, optional, the item fields the results file carries.
- `report`, the layout, with `title`, `intro`, and `sections`.

Each field is `{type, values, required, filled_by, not_run_text}`. The `type` is one of `str`, `int`, `number`, `bool`, `list`, `dict`, and `enum`. Only an `enum` gives `values`, and it must give them. A field is required unless it says `required: false`. The `filled_by` list names the graph's steps that fill the field. The `not_run_text` (default `not run`) is how the report shows a field whose steps did not run.

Each section is `{heading, parts}`, and each part has a `kind` of `text`, `table`, `list`, `blocks`, or `groups`. A `text` part has a `template`. A `table` has `rows`, `columns` (each `{header, value}`), and optionally `where` and `empty`. A `list` has `rows`, `line`, and optionally `where` and `empty`. A `blocks` part has `rows`, `heading`, `lines` (each `{label, value, omit_empty}`), and optionally `where` and `empty`. A `groups` part has `rows`, `by` (an enum field of its rows), `groups` (each `{value, title}`, with the value one of that field's values), `block` (a blocks part without `rows`), and optionally `empty`. The `rows` of a part are `items` or the id of a table.

The report's title and introduction, a text part's template, a column's value, a list's line, and a block's heading and line values are templates. In a template, `{name}` is a field of the part's rows and `{run.name}` is a run field. The title, the introduction, and a text part have no rows, so they take only `{run.name}`. A template names only fields of type `str`, `int`, `number`, or `enum`. Double braces, such as `{{num:key}}`, are plain text.

The check names an unknown or missing key, an unknown type, an enum without values, a step in `filled_by` that is not in the graph, a stream that differs from the graph's, an `id` or `results` entry that is not an item field, a version that is not a positive integer, a part with an unknown kind or row set, a template field that is not a field of the part's rows or of the run, a template field of another type, and a `groups` part whose `by` is not an enum field or whose group values are not among its values.

## Registry

`registry.yaml` names one procedure for each stream of the proposal's Table 1. It holds `registry_version: 1` and `procedures`, a list of entries, each with these keys.
- `id`, the stream, which `vg.py run` takes in place of a graph path (`python3 vg.py run citations --run runs/X --inputs fixtures/citations/seeded ...`).
- `stream`, which must be the graph's stream.
- `name` and `procedure`, the stream's and the procedure's names in Table 1.
- `graph`, the graph file, read from this folder. It must pass `vg.py check` and name its schema.
- `triggers`, with `events` (any of `ai_edit`, `turn_end`, `build`, and `commit`, all four in each entry today), `phrases` (what a scholar may ask for to start the procedure), and `files` (glob patterns of the files whose change makes the stream out of date). Phrases and files are non-empty lists of text.
- `quick_steps`, the steps of the light working check, the mechanical steps cheap enough to run at the end of every turn. Each is a tool step and not the exit, they are listed in the graph's order, each one but the entry has an unconditional edge from an earlier quick step, and each one reads only procedure inputs and files an earlier quick step makes.

`python3 vg.py procedures` prints a JSON list with one object for each procedure, its registry entry plus `graph_version`, `schema`, `schema_version`, and `inputs`. The inputs are `required`, every file a step's contract reads that no step produces, apart from `steps.json`, in the order the graph first reads them, and `optional`, the `reads_optional` patterns of every step but the exit. Hooks, a request router, and adapters in another layer read this list as data. `python3 vg.py procedures --check` prints each problem with the registry, or `OK: 4 procedures`, and exits 1 on any problem. It names a repeated id, a missing or unknown key, a graph that does not exist, fails its check, or names no schema, a stream that differs from the graph's, an unknown trigger key or event, phrases or files that are not a non-empty list of text, and quick steps that are not a list of step names or break the rule above.

`python3 vg.py run <id> --quick --run X --inputs Y` is the light working check. It starts the run as usual, with `"quick": true` in the manifest, runs the quick steps in order, stops at the first contract failure, adds `run_quick_finished` to the trail, and prints `quick: <B> blocking, <W> warnings from <N> steps` from those steps' findings files. It needs no `--judge`, writes no report and no results file, and exits 1 only when a step failed. The full run, which writes the results file the build reads, is the formal check. Nothing in this layer starts a quick run on its own.

How to write a new procedure is in `AUTHORING.md`.

## Word review

The Word review modules live in `review/` and run from this folder as `python3 -m review <command>`. Each prints the lines `ospipe` printed for it. With `--json`, `returns`, `reconcile`, and `lint` print one JSON value instead, for an adapter to read as a file.

```
python3 -m review returns REVIEWED.docx [--json]
python3 -m review reconcile RETURN.docx --builds-dir DIR --of vNNN [--json]
python3 -m review annotate --docx IN --spec YAML --out OUT [--author NAME]
python3 -m review lint --manuscript FILE [--allowlist FILE] [--json]
```

- `returns` lists the tracked insertions and deletions and the margin comments in a reviewed document. A change that touches a number is marked for triage.
- `reconcile` sorts each AI change region of build `vNNN` into accepted, rejected, modified, or pending, and lists the scholar's own edits, the comments, and any region it cannot place. A missing ledger or snapshot exits 2 with `reconcile failed` and the reason.
- `annotate` attaches margin comments to a copy of a document from a YAML list of anchors and texts, and names each anchor it could not find.
- `lint` flags numbers typed into a markdown source, one line per finding, and always exits 0. It is advisory.

Word's own compare runs from a script, on macOS with Word only.

```
osascript review/word_compare.applescript ORIGINAL REVISED OUTPUT LABEL
```
