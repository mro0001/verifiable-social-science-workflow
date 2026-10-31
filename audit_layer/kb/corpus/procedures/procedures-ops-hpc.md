---
id: procedures-ops-hpc
title: Connect a project to a university computing cluster
source: verification_procedures/graphs/ops_hpc.yaml
source_commit: sha256:9f5510c6e13f
updated: 2026-10-29
group: PROCEDURES
---

# Connect a project to a university computing cluster

Check that a project can reach the scholar's cluster over SSH with no password prompt, that its folder exists there, and that the scheduler and the modules it needs answer. The procedural graph system runs it with the command below, so a session finds it here and does not carry out its steps by hand.

1. Purpose. Check that a project can reach the scholar's cluster over SSH with no password prompt, that its folder exists there, and that the scheduler and the modules it needs answer. Run commands only when the settings file says so, and never read a key file.
2. Triggers. The scholar asks to connect a project to a computing cluster. Work is about to go to the cluster before the connection has been checked.
3. Steps. 5 steps, in the order the runtime runs them, each only when a transition into it fires.
   - `hpc_settings` (tool step) Read the settings file, fill each missing field with its default, and block on a missing or badly formed alias, host, user, identity file, or remote folder, or a scheduler this procedure does not know.
   - `hpc_ssh_entry` (tool step) Find the alias's Host entry in the copy of the ssh config, say whether its host name, user, and identity file match the settings, and write the entry to add, without opening the identity file.
   - `hpc_plan` (tool step) Plan the commands that connect with no password prompt, make the project folder on the cluster, ask the scheduler for its version, and load each module.
   - `run_commands` (tool step) Run the planned commands in order when the settings file sets apply to true, and stop at the first failure. Otherwise list them as planned.
   - `report` (tool step) Write a report with the settings, the ssh entry, and each command with its result.
4. Run command. From the `verification_procedures` folder, run `python3 vg.py run graphs/ops_hpc.yaml --run runs/<new run folder> --inputs <inputs folder>`. The inputs folder holds `hpc.yaml`, and when present `ssh_config`.
5. Version. Graph version 0.1, 5 steps and 5 transitions, checked with `python3 vg.py check graphs/ops_hpc.yaml`.

## Consult also

- guidelines-authoring-procedures - to write a new procedure or revise this one.
