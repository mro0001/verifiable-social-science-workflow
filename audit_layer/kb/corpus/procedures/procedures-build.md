---
id: procedures-build
title: Build integrity
source: verification_procedures/graphs/build.yaml
source_commit: sha256:2a3a10953c75
updated: 2026-10-29
group: PROCEDURES
---

# Build integrity

Show that every deliverable is a product of the build and only of the build. The procedural graph system runs it with the command below, so a session finds it here and does not carry out its steps by hand.

1. Purpose. Show that every deliverable is a product of the build and only of the build. The author can trust a deliverable when five things hold. (1) The map (the Makefile) names exactly one canonical file per deliverable, and nothing else claims to be it. (2) Every build preference the author wrote down is carried by the map's command and shows in the built output. (3) Every build on disk is the file its ledger row recorded. (4) Rebuilding from the recorded snapshot with the map's command reproduces the ledgered file byte for byte, so no build carries text the build did not produce. (5) Results reach the deliverable through numbers.yml placeholders, not typed into prose, and the session record shows no AI write to a build except through the map's rule. This is the build-side form of "results are the output of a process, not hard-coded": the deliverable is the output of a process, not hand-made. No judgment step: each of the five is a hash, a parse, or a re-run.
2. Triggers. It starts on the harness events `ai_edit`, `turn_end`, `build`, and `commit`. It starts on a request that uses the phrase "verify the build" or "check builds".
3. Steps. 8 steps, in the order the runtime runs them, each only when a transition into it fires.
   - `read_map` (tool step) Parse the Makefile map from project.tar: each deliverable's rule, canonical source, builds dir, manifest, template, and pandoc command. Flag rules naming zero or several canonicals, canonicals that do not exist, shared builds dirs, and any other file that reads as a deliverable without an ARCHIVE line.

   - `check_ledger` (tool step) For each deliverable, compare every file in its builds dir with BUILDS.md: every build and snapshot has a row, every row's file exists, every sha256 matches.

   - `check_hardcoding` (tool step) Scan each canonical source: every {{num:key}} must resolve in the manifest; a bare numeral equal to a manifest value is a hard-coded result; any other bare numeral outside the allowlist would be refused at ship.

   - `check_ai_touch` (tool step) Read session_writes.jsonl (the session record) and flag any AI write inside a builds dir or ship/, any hand write to a build, and any build write that did not come from the deliverable's own make rule.

   - `check_prefs` (tool step) Read build_prefs.yaml (the author's preferences, in the author's words) and check each one is carried by the map's pandoc command for every deliverable it applies to, and visible in that deliverable's latest build where the output can show it.

   - `rebuild` (tool step) For each ledgered build, re-run the map's pandoc command on the frozen snapshot in a scratch copy of the project and compare with the ledger's sha256. When the canonical and numbers.yml are unchanged since the build, also re-resolve the canonical and compare with the snapshot. Writes rebuild.json.

   - `no_rebuild` (tool step) Record that the ledger is empty, so the rebuild witness was not exercised.
   - `report` (tool step) Write findings.json and report.md, with a Deliverables table.
4. Run command. From the `verification_procedures` folder, run `python3 vg.py run graphs/build.yaml --run runs/<new run folder> --inputs <inputs folder>`. The inputs folder holds `project.tar` and `session_writes.jsonl`.
5. Version. Graph version 0.1, 8 steps and 11 transitions, checked with `python3 vg.py check graphs/build.yaml`.

## Consult also

- guidelines-authoring-procedures - to write a new procedure or revise this one.
