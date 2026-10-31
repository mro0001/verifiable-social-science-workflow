# The observability layer's contract

The observability layer lets the scholar watch AI work as it happens and reopen it afterwards (proposal Approach paragraphs 4 and 5, appendix A2.6 and Table A7). This file states what the layer reads, what it writes, what it promises to keep the same, and what may change. A connection from another layer to this one starts from the inputs and the trace file form named here.

## What it reads

Everything is read in place and read only, at a path named on the command line. The layer never imports another layer's code. Only files cross the layer's edge.

| Input | Named by | What is read |
|---|---|---|
| The audit home | `--audit-home DIR` | `audit.sqlite`, opened read only, with its tables `sessions`, `events`, and `transcripts`. The transcript files in the file store `files/<sha256>`, each checked against its checksum. |
| Verification runs | `--vg-runs PATH...` | A run folder of vg.py, or a folder holding run folders. From each run, `manifest.json`, `trail.jsonl`, `records/`, `prompts/`, and `responses/`. |
| Knowledge base entries | `--kb-dir DIR` | The markdown entry files in the folder and its subfolders, with their front matter. |

The audit home's `settings.yaml` is not read. Capture keeps sessions run in excluded folders out of the record, and the view shows what the record holds.

A session is read by the adapter for its harness. Claude Code sessions are read from their kept transcripts (`adapters/claude_code.py`). A session of any other harness is read from the audit events table (`adapters/events.py`), with its verbs, objects, and file roles but no results or reasoning. Runs are read by `adapters/vg_run.py`. A call to a knowledge base server named by `--kb-server NAME`, or a read of an entry file inside a `--kb-dir` folder, is marked as a retrieval. The servers are by default `workflow-kb` and `pipeline-kb`, the server's earlier name, which the default keeps so sessions from before the change still show their reads.

## What it writes

Everything goes into the view's folder, `--out DIR`, which is `~/.observability/view` unless named. A built view holds transcript text, so it stays out of project folders, commits, and replication folders.

- `<out>/traces/<trace_id>.json`, one trace file for each session or run, in OTLP JSON, OpenTelemetry's own file form. Any OpenTelemetry viewer can open it. A trace file this build did not write is removed.
- `<out>/data.js`, the tables the page reads, written whole as `window.OBS = <json>;`.
- `<out>/index.html`, `<out>/app.js`, and `<out>/style.css`, the dashboard page, copied unchanged. It opens from disk with no server and no network.

## The trace file form

Each trace file holds one resource, with `service.name` naming its source (`claude_code`, another harness's name, or `vg.py`), and one scope named `observability`. Ids come from sha256, so a rebuild gives the same ids.

| Trace | Trace id from |
|---|---|
| A Claude Code session | `claude_code:<session id>` |
| A session of another harness | `<harness>:<harness session id>` |
| A verification run | `vg:<real path of the run folder>` |

A span id comes from its trace id and a key that names the span inside the trace.

### Operations

Span names and attributes follow OpenTelemetry's conventions for AI calls, read at commit 3fe84604a581 of open-telemetry/semantic-conventions-genai, all in Development status. Every name lives in `conventions.py`, so a change is made in one place.

| Operation | Span name | Stands for |
|---|---|---|
| `invoke_agent` | `invoke_agent <agent name>` | A session, as the root of its trace, or a subagent, under the tool call that started it |
| `chat` | `chat <model>` | A model turn, or an item a live model judged in a run |
| `execute_tool` | `execute_tool <tool name>` | A tool call with its result |
| `invoke_workflow` | `invoke_workflow <stream>` | A verification run, as the root of its trace |

Inside a run, each step is a span named by its node, and an item answered from recorded answers is a span `recorded <item>` with no operation, so it is never counted as a model call. Inside a session of another harness, each event is a span `<verb> <object>`.

### Attributes from the conventions

| Key | Where |
|---|---|
| `gen_ai.operation.name` | Every span with an operation |
| `gen_ai.provider.name` | Model turns (`anthropic` for Claude Code) and live run items (the executor's prefix) |
| `gen_ai.request.model` | Model turns and live run items |
| `gen_ai.response.model` | Model turns |
| `gen_ai.response.id` | Model turns |
| `gen_ai.response.finish_reasons` | Model turns |
| `gen_ai.usage.input_tokens` | Model turns, the sum of input, cache reads, and cache writes |
| `gen_ai.usage.output_tokens` | Model turns |
| `gen_ai.usage.cache_read.input_tokens` | Model turns |
| `gen_ai.usage.cache_write.input_tokens` | Model turns |
| `gen_ai.conversation.id` | Session roots |
| `gen_ai.input.messages` | Model turns (the typed prompt that started the turn) and run items (the prompt) |
| `gen_ai.output.messages` | Model turns (text, reasoning, and tool calls) and run items (the answer, and a second answer after a retry) |
| `gen_ai.agent.id` | Subagents |
| `gen_ai.agent.name` | Session roots and subagents |
| `gen_ai.agent.description` | Subagents |
| `gen_ai.tool.name` | Tool calls |
| `gen_ai.tool.call.id` | Tool calls |
| `gen_ai.tool.type` | Tool calls, `function`, `extension` for MCP tools, or `datastore` for retrievals |
| `gen_ai.tool.call.arguments` | Tool calls |
| `gen_ai.tool.call.result` | Tool calls |
| `gen_ai.transfer.target.name` | A tool call that started a subagent of a named type |
| `gen_ai.transfer.mode` | A tool call that started a subagent, `return_to_caller` |
| `gen_ai.workflow.name` | Run roots, the stream |
| `gen_ai.data_source.id` | Retrievals, the server's name or the entry folder's name |
| `gen_ai.retrieval.documents` | Retrievals that name an entry |
| `gen_ai.retrieval.query.text` | Searches of the knowledge base |
| `error.type` | A failed tool call (`tool_error`) and a run item not judged (`not_judged`) |
| `mcp.method.name` | MCP tool calls, `tools/call` |

### Attributes from OpenTelemetry's general registry

| Key | Where |
|---|---|
| `file.path` | A tool call or event that read, edited, or produced a file |
| `service.name` | The resource of every trace file |

### The layer's own attributes

Fields the conventions do not name take the prefix `audit.` when they come from the audit record and `vg.` when they come from a run.

| Key | Where |
|---|---|
| `audit.harness` | Session roots |
| `audit.project` | Session roots, the folder the session ran in |
| `audit.role` | File roles in Table A4's words, `read`, `edited`, or `produced` |
| `audit.verb` | Events of another harness |
| `audit.kind` | Events of another harness |
| `audit.object` | Events of another harness |
| `audit.rationale` | Events of another harness |
| `audit.ordinal` | Events of another harness |
| `vg.run_id` | Run roots, the run folder's name |
| `vg.stream` | Run roots |
| `vg.graph_version` | Run roots |
| `vg.step.seq` | Run steps |
| `vg.step.kind` | Run steps |
| `vg.contract` | Run steps, `pass` or `fail` |
| `vg.executor` | Run items answered from recorded answers |

## Frozen promises

- The layer never writes into another layer's files. The audit home, run folders, and entry files are left byte for byte as they were.
- Span names and attributes are those of `conventions.py`.
- Trace ids and span ids stay the same across rebuilds, and the same record gives the same trace file bytes.
- The view adds no filter of its own. Sessions run in excluded folders stay out of the view because capture keeps them out of the record. A session the record holds is shown.

## Soft parts

These may change without notice to other layers.

- The dashboard page, its tabs, and the tables in `data.js`.
- The cut of arguments, results, messages, and reasoning at 8,000 characters, with a note of the full length, since the full text stays in the audit record.
- The interval of live mode, 5 seconds by default, and the page's reload, which follows it.

## Events from outside software

Events from outside software reach the view as sessions in the audit record. A harness, wrapper, or tool whose events form sessions there is shown by the events adapter. Runs of vg.py are read directly from their run folders.

Two connectors that bring such events are built. The wrapper (`python3 -m connections wrap`) logs each call of a program it runs, and the events tool (`python3 -m connections serve events`) lets an MCP client log an event. Capture stores their event files as sessions of the harness `wrappers`, which the view shows (`connections/README.md`).

These parts are still open.

- A harness's own OpenTelemetry export sent to the record, with the harness setting turned on one project folder at a time.
- Wrapper events shown inside a Claude Code session. They are shown as sessions of their own, since the Claude Code adapter reads transcripts.
- A ForgeCode transcript adapter. Until one is written, ForgeCode sessions appear through the events adapter.

## Commands

Run from the repository root.

`python3 -m observability build` builds the view once.

`python3 -m observability watch` builds the view with the page set to reload itself, rebuilds it at each interval when the record, a kb folder, or a run changed, and builds once more without the reload when it stops.

Both commands take these options.

| Option | Meaning |
|---|---|
| `--audit-home DIR` | The audit home holding `audit.sqlite`, read only. Required. |
| `--project DIR` | Keep only sessions in this folder or inside it. |
| `--kb-dir DIR` | A folder of knowledge base entry files, may be given again. |
| `--kb-server NAME` | A knowledge base server whose calls are retrievals, may be given again. `workflow-kb` and its earlier name `pipeline-kb` when none is given. |
| `--vg-runs PATH...` | One or more run folders of vg.py, or folders holding them, read only. |
| `--out DIR` | The folder the view goes to, `~/.observability/view` by default. |

`watch` also takes `--interval SECONDS`, the seconds between checks, 5 by default.

A missing or unreadable audit record exits 1 and names the problem.
