---
id: procedures-mcp-kb
title: The knowledge base server, written as a procedural graph
source: verification_procedures/graphs/mcp_kb.yaml
source_commit: sha256:738b177bfadd
updated: 2026-10-29
group: PROCEDURES
---

# The knowledge base server, written as a procedural graph

Answer one call to a read-only knowledge base tool from the exported index given with the call, and record which entries the answer returned. The procedural graph system runs it with the command below, so a session finds it here and does not carry out its steps by hand.

1. Purpose. Answer one call to a read-only knowledge base tool from the exported index given with the call, and record which entries the answer returned. The graph never writes to the knowledge base, and every call leaves a run folder that shows what was retrieved.
2. Triggers. A harness or model calls a knowledge base tool through an MCP server that runs this graph once per call.
3. Steps. 8 steps, in the order the runtime runs them, each only when a transition into it fires.
   - `read_request` (tool step) Read the call and the exported index, and route the call to the step that answers it, or to the refusal with the problem stated.
   - `orient_kb` (tool step) Give the knowledge base's title and description, its entry count, the count in each group, and every entry's id, title, group, and description, sorted by id.
   - `search_kb` (tool step) Score each entry for the query's words, 5 for a word in the title, 4 in the id, 2 in the point, and 1 in the body, and return the entries that score, highest first, each with a snippet of its body.
   - `list_entries` (tool step) List every entry's id, title, and group, sorted by id, only those of one group when the call names a group.
   - `get_entry` (tool step) Return one entry whole, its six frontmatter fields and its body, or say no entry has that id.
   - `lookup_provenance` (tool step) Return where one entry came from, its source, the source's checksum, and the date it was updated, or say no entry has that id.
   - `refuse` (tool step) Return the refusal's code and the problem read_request stated, and no entry.
   - `respond` (tool step) Write the response, a note naming the entries returned, and a report of the call.
4. Run command. From the `verification_procedures` folder, run `python3 vg.py run graphs/mcp_kb.yaml --run runs/<new run folder> --inputs <inputs folder>`. The inputs folder holds `kb_index.json` and `request.json`.
5. Version. Graph version 0.2, 8 steps and 12 transitions, checked with `python3 vg.py check graphs/mcp_kb.yaml`.

## Consult also

- guidelines-authoring-procedures - to write a new procedure or revise this one.
