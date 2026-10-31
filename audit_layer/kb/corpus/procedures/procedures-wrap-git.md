---
id: procedures-wrap-git
title: The git wrapper, written as a procedural graph
source: verification_procedures/graphs/wrap_git.yaml
source_commit: sha256:94d922fb8076
updated: 2026-10-29
group: PROCEDURES
---

# The git wrapper, written as a procedural graph

Turn each git command the scholar ran, as the wrapper recorded it after the command returned, into one event in the audit layer's event schema, so the audit layer holds the scholar's own version control actions beside the AI's. The procedural graph system runs it with the command below, so a session finds it here and does not carry out its steps by hand.

1. Purpose. Turn each git command the scholar ran, as the wrapper recorded it after the command returned, into one event in the audit layer's event schema, so the audit layer holds the scholar's own version control actions beside the AI's. Nothing here can delay or change the command.
2. Triggers. The wrapper's call file holds calls not yet turned into events, such as before capture runs.
3. Steps. 3 steps, in the order the runtime runs them, each only when a transition into it fires.
   - `read_calls` (tool step) Read each line of the call file, keep the calls that are whole and start with git, and warn on every other line and on a repeated call id.
   - `to_events` (tool step) Turn each call into one event, with the verb and kind its git subcommand and exit code give, the command line as the object, and the session its day and folder give.
   - `report` (tool step) Count the calls and the events by verb and kind, and write a report listing every event.
4. Run command. From the `verification_procedures` folder, run `python3 vg.py run graphs/wrap_git.yaml --run runs/<new run folder> --inputs <inputs folder>`. The inputs folder holds `calls.jsonl`.
5. Version. Graph version 0.1, 3 steps and 2 transitions, checked with `python3 vg.py check graphs/wrap_git.yaml`.

## Consult also

- guidelines-authoring-procedures - to write a new procedure or revise this one.
