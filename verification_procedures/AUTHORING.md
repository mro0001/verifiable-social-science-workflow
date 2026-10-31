# Writing a new procedure

This guide is for anyone adding a procedure to the procedural graph system. It covers the files a procedure needs, the rules the runtime holds them to, how to test them, and how a session finds the procedure afterward. The runtime is `vg.py` in this folder, and every command below runs from this folder unless it says otherwise. The guide's own tests (`tests/test_authoring_guide.py`) check it against `vg.py`, so every key and command named here is one the runtime accepts.

## What a procedure is

A procedure is a standard written so that it can run. Its graph names the steps, the order they run in, the conditions that route the work, and the pitfalls met at each step. Its contract says what each step reads and must produce. Each step has code (a tool step) or a prompt (a judgment step). Its test files show that it catches what it is meant to catch, and every run leaves step records, a trail, and a report, so the check itself can be checked.

A new procedure named `<name>`, with the stream key `<stream>`, adds these files.

- `graphs/<name>.yaml`, the graph.
- `contracts/<name>.yaml`, the contract.
- `implementations/<stream>/<node>.py` for each tool step, or `implementations/<stream>/<node>.prompt.md` for each judgment step.
- `fixtures/<name>/`, the test files.
- `tests/test_<name>.py`, the tests.

The runtime finds a step's code by the graph's `stream` key, so two graphs may share one code folder. The two operational procedures do this, with `stream: ops` and their code in `implementations/ops/`.

A procedure is ready when `python3 vg.py check graphs/<name>.yaml` prints OK and its tests catch every fault planted in its test files.

## The graph

A graph file holds the top-level keys `stream`, `version`, `goal`, `contracts`, `entry`, `exit`, `nodes`, and `edges`, and the runtime reads no other key. `stream` names the code folder, `version` goes up with each revision, `goal` says in plain sentences what the procedure is for, `contracts` is the contract file's path from this folder, and `entry` and `exit` name the first and the last step. Two more keys, `title` and `triggers`, are read only by the knowledge base, which writes the procedure's entry from them. `title` is a short name, and `triggers` is a list of plain sentences naming the events that start the procedure.

Each node in `nodes` is one step. A node may hold only these keys.

<!-- node keys -->
- `id`, the step's name, which is also the name of its code or prompt file.
- `kind`, either `tool` or `judgment`.
- `does`, one sentence saying what the step does.
- `invariant`, an optional sentence for readers that holds however the step runs. The runtime does not read it.
- `foreach`, for a judgment step, the file whose list items are asked about one at a time.
- `where`, for a judgment step with `foreach`, a filter of the form `field in [a, b]`.
- `role`, for a judgment step, either `judge` (the default) or `second`.
- `replay`, set to `network` for a tool step that acts outside the run.

Each edge in `edges` is a transition from one step to another. An edge may hold only these keys, and every edge needs `condition`, `guidance`, `pitfalls`, and `source`.

<!-- edge keys -->
- `from`, the step the transition leaves.
- `rel`, one of the four relations below.
- `to`, the step the transition reaches.
- `condition`, a sentence saying when the transition holds.
- `check`, an optional test the runtime reads after the `from` step finishes.
- `guidance`, what the executor of the next step should do.
- `pitfalls`, a list of the mistakes met at this point, each a sentence.
- `source`, the document section the transition comes from, or `proposed` when it is new.
- `invariant`, an optional sentence for readers.

The relations name how two steps are joined. The runtime treats all four the same way and keeps them for readers.

<!-- relations -->
- `LEADS_TO`, the next step in a line of work.
- `PROVIDES_INPUT_FOR`, a step whose output another step reads beside the main line.
- `TRIGGERS`, a step that starts another piece of work.
- `CONVERGES_TO`, a branch joining the others again, most often at the report.

A `check` has the form `<file>.json:<field> <op> <value>`, where `<op>` is one of `==`, `!=`, `>`, `>=`, `<`, and `<=`, and a field inside an object is written with dots. For example `run_index.json:is_run == true` fires only when that file's `is_run` field is true. An edge without a `check` fires whenever its `from` step finishes.

The graph must be acyclic, and every step must be reachable from `entry`. A step runs only when it is the entry or a transition into it fires, so a step that no fired transition reaches is skipped, and the trail says so. Steps run in one fixed order, which `vg.py` works out from the edges. `python3 vg.py check graphs/<name>.yaml` reports a missing key, an unknown key or relation, a cycle, a step out of reach, and a step with no contract or no code.

## The contract

The contract file has one entry per step, keyed by the step's id. Each entry may hold three keys.

- `reads`, the files the step needs. The runtime stops before the step when one is missing.
- `reads_optional`, files or wildcard patterns the step reads when they exist. A file from a branch that may be skipped goes here, and so does `findings_*.json` for a report step.
- `produces`, each file the step writes, with what the runtime checks in it.

For a `.json` file, `produces` gives a map from field names to types, and the types are `int`, `number`, `bool`, `str`, `list`, and `dict`. A list in place of a type gives the allowed values, as in `severity: [blocking, warning, info]`. A file that holds a list of objects is written `{items: {<field>: <type>}}`, and every object in the list is checked. An empty map `{}` checks only that the file exists. For a `.md` file, `{headings: [Summary, Problems]}` names the headings the report must hold. A step that breaks its contract stops the run. `contracts/llm_runs.yaml` shows each of these forms.

The runtime copies the top-level files of the inputs folder into a run, and it skips `truth.yaml` and every name starting `recorded_`. A graph with a step that reads `"*"`, as the data procedure and the data phase reports have, also gets the inputs folder's subfolders, less hidden folders, `__pycache__`, and links, so a script at `code/s1.py` reaches the run at that path. For any other graph a folder of files goes in as one tar, as the build procedure's `project.tar` does.

## Tool steps

A tool step is a Python file run as `python3 <node>.py <files_dir>`. The runtime copies the file and `implementations/_lib.py` into a folder of their own for the run, so steps share nothing but `_lib`, and `verify` can rerun the exact code later. The conventions in `_lib.py` are frozen.

- Read only the files the contract lists, from the files folder given as the first argument, with `_lib.path`, `_lib.read_json`, `_lib.read_yaml`, or `_lib.read_text`.
- Write only new files. A step that changes a file already there fails.
- Be deterministic, with no times, no random numbers, and sorted output, so a replay gives the same bytes.
- A step that checks something writes `findings_<node>.json` through `_lib.emit_findings`, even when it finds nothing. A finding is `{check, severity, item, message, evidence}`, and its severity is `blocking`, `warning`, or `info`.

A tool step never calls the network or a model. The one exception is a step that acts outside the run, such as pushing to a server or connecting over SSH. Mark such a step `replay: network`, so `verify` compares its outputs by checksum and never reruns it, and let it act only when the scholar has said so. `implementations/ops/run_commands.py` runs its commands only when the settings file sets `apply: true`, and otherwise lists them as planned.

## Judgment steps

A judgment step is a prompt file `<node>.prompt.md`, answered by a model or by a file of recorded answers. The runtime fills these placeholders before it asks.

- `{{goal}}`, the graph's goal.
- `{{pitfalls}}`, the guidance and pitfalls of every transition into and out of the step.
- `{{item}}`, the whole item as JSON.
- `{{item.<field>}}`, one field of the item.

The prompt asks for one JSON object and nothing else. With `foreach`, the runtime asks once for each item in that file that passes `where`, and without it the runtime asks once, with the item id `all`. Small asks, one per item, keep each answer checkable. The runtime writes the answers to `<node>.json` as a list, each answer carrying `item_id`, `executor`, and `prompt_sha256`, and it saves every prompt and every response in the run folder. An item whose answer cannot be read after one retry is listed as not judged in `findings_unjudged_<node>.json`. A tool step after the judgment step turns the answers into findings.

A step with `role: judge` is answered by the `--judge` executor, and a step with `role: second` by the `--second` executor, the independent second checker, which must be a different model. An executor is `recorded:<answers file>` or a model the runtime can reach. A recorded answers file maps `<node>:<item id>` to each answer, and test files keep it under a name starting `recorded_`, so it never enters a run. See `implementations/citations/locate_passage.prompt.md` and `fixtures/citations/seeded/recorded_judge.json`.

## The report

The exit step writes the run's deliverable. It reads every `findings_*.json` through `reads_optional`, writes `findings.json` from `_lib.collect_findings()`, and writes `report.md` from `_lib.report(title, intro, findings, sections)`. The report gives the summary first and the problems first, then the sections the procedure adds, then the notes. Name the report's headings in the contract so the runtime checks them. `implementations/llm_runs/report.py` is one to copy.

## Test files

A procedure that checks something has two sets of test files. The clean set should give no blocking or warning finding. The seeded set holds planted faults and a `truth.yaml` that lists each one as `{id, check, item}`, and `python3 vg.py score --run <run> --truth fixtures/<name>/seeded/truth.yaml` reports the faults caught and missed. A graph that does a task, rather than checking one, has a test for each path through it, so every transition is seen to fire. Tests answer judgment steps from recorded answers and never call the network or a model. The tests also check that `python3 vg.py verify --run <run>` finds every tool step replays, and that the procedure's code imports nothing from another layer. See `fixtures/citations/seeded/truth.yaml`, `tests/test_citations.py`, and `tests/test_ops_github.py`.

## The knowledge base entry

Every procedure gets one entry in the knowledge base's PROCEDURES group, so a session finds it through the knowledge base's search and runs it with the command the entry names, instead of carrying out its steps by hand. The entry gives the procedure's purpose, its triggers, its steps in the order the runtime runs them, the run command with the files the inputs folder must hold, and the graph's version. It is generated from the graph and its contract and is never edited by hand. To write it, copy `graphs/` and `contracts/`, with `registry.yaml` when there is one, to a folder, and run the command below from the repository root.

```sh
python3 -m audit_layer.kb graph-entries --procedures <copy>
```

The knowledge base lives in the audit layer, and nothing in this folder imports it, so the copy is the only thing that crosses between the two. Rerun the command whenever a graph changes. With `--check` it writes nothing and exits 1 when an entry is out of date.

## Revising a procedure

A procedure is revised when a run shows it going wrong. Change the guidance and pitfalls first, since the executor sees them at the step, and then the prompt or the code where the fault lies. Raise `version`, run the clean and seeded test files again and score them, and regenerate the knowledge base entry. The prose procedure went this way from version 0.1 to 0.2 after its first live run, when two pitfalls were added from its two errors and the same seeded test file was run again (appendix A5). Each run records the graph's version and checksum, so a run made before a revision is never taken for one made after it.

## Graphs that are not a stream

The same runtime runs procedures that do a task rather than check one. Four patterns are here to copy.

- An operational task, such as adding a project to GitHub (`graphs/ops_github.yaml`) or connecting to a university computing cluster (`graphs/ops_hpc.yaml`). Steps check the settings and the files, plan the commands, run them in a `replay: network` step only when the settings file sets `apply: true`, and report. A first run only plans, so it is harmless.
- A wrapper around outside software (`graphs/wrap_git.yaml`). It reads the call file the wrapper's own program appends to after each command returns, and turns each call into an event in the audit layer's event schema. It never delays or changes the command.
- An MCP server (`graphs/mcp_kb.yaml`). Each call to a tool is one run, with the call in `request.json` and the data it answers from beside it. The entry step routes the call to one branch per tool or to a refusal, and every branch converges on one step that writes the response, so every call leaves a run folder that shows what it returned.
- A procedure about other runs (`graphs/llm_runs.yaml`). It reads a finished run packed as `run.tar` and reruns nothing.

## The four streams only

A procedure for one of the four verification streams (prose, references, data, and build, with the stream keys `prose`, `citations`, `data`, and `build`) has three more parts, which the other graphs do not need. The first two are named here by their role, since the files that hold them are still being settled.

- A versioned schema for the items its results list.
- A row in the procedure registry, naming the procedure, its graph, and the events, phrases, and files that start it.
- The results file. When a stream's run completes, the runtime writes `results.json` in the run folder with one item for each row of the report, and the scholar approves or holds each item that needs a decision with `python3 vg.py decide --run <run> --item <id> --approve --by "<name>"`, or `--hold` in place of `--approve`.

## The worked example

This example evaluates an LLM run with the procedure `llm_runs`, on the test story's references run. First the references procedure (`citations`) runs on the story's files with recorded answers, and `verify` replays it. Then the finished run folder is packed whole as `run.tar` and handed to the evaluation, which reports which model answered each step, whether every prompt and answer was kept and matches the record, which items went unanswered, and what the replay found.

`<story inputs>` is a folder holding the story's files as its test arranges them. It holds `examples/test_story/project/manuscript.md` copied as `draft.md`, `examples/test_story/references/expected_citation_provenance.yaml` copied as `citation_provenance.yaml`, and every file of `examples/test_story/references/` whose name does not start with `expected_`. `<story run>`, `<eval inputs>`, and `<eval run>` are folders that do not exist yet. `VG_OFFLINE=1` keeps the reference lookups offline, and `COPYFILE_DISABLE=1` keeps macOS from adding its own files to the archive. Run the lines from this folder.

<!-- worked example -->
```sh
VG_OFFLINE=1 python3 vg.py run graphs/citations.yaml --run <story run> --inputs <story inputs> --judge recorded:<story inputs>/recorded_judge.json
python3 vg.py verify --run <story run>
mkdir <eval inputs>
COPYFILE_DISABLE=1 tar -cf <eval inputs>/run.tar -C <story run> .
python3 vg.py run graphs/llm_runs.yaml --run <eval run> --inputs <eval inputs>
python3 vg.py verify --run <eval run>
cat <eval run>/files/report.md
```

The report names the recorded answers files as the executors and says the run records no model version. To compare the run's answers with a reference, place a reference answer book in `<eval inputs>` as `reference.json` before the evaluation runs, such as the `answer_book.json` an earlier evaluation wrote. The evaluation's knowledge base entry, `procedures-llm-runs`, gives the same run command.
